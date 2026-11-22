from datetime import timedelta

from django.db.models import (
    BooleanField,
    Case,
    CharField,
    Count,
    DateField,
    Exists,
    F,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    Value,
    When,
)
from django.db.models.functions import Coalesce, Greatest
from django.utils.timezone import localdate

from core.db import DiasEntre

from .managers import QuerySetAuditado


class ProcessoQuerySet(QuerySetAuditado):
    """O queryset base com as 4 propriedades derivadas do histórico
    (nº de reuniões, nº de compromissos assumidos, prazo prometido vigente,
    situação na última reunião) mais a anotação de atraso. Consumido por
    tabela (01-05), kanban, dashboard e export (fases seguintes) sem
    reescrita — sempre via `.para_listagem()`, nunca `annotate()` repetido
    numa view /#9/#10)."""

    def para_listagem(self):
        # Import local: evita import circular entre models.py (que atribui
        # este queryset ao Manager de Processo) e querysets.py, que precisa
        # de Acompanhamento para montar as subqueries correlacionadas.
        from apps.pca.models import Acompanhamento, Estado, Situacao

        ultimo = Acompanhamento.objects.filter(
            processo=OuterRef("pk")
        ).order_by("-referencia_data", "-id")  # desempate determinístico — Pitfall 10

        # "Prazo inicial": a mesma origem alimenta a
        # coluna/XLSX/ficha e a frase institucional de
        # `relatorio_movimentacao.py::frase_compromisso`. Ordenação
        # ASCENDENTE por `(referencia_data, id)` — a PRIMEIRA promessa já
        # registrada, espelho exato do desempate descendente de `ultimo`
        # acima (EDGE ordering).
        primeira_promessa = Acompanhamento.objects.filter(
            processo=OuterRef("pk"), prazo_prometido__isnull=False
        ).order_by("referencia_data", "id")

        # .order_by() vazio ANTES de .values().annotate(): limpa o
        # Meta.ordering herdado de Acompanhamento, que senão entra no
        # GROUP BY e quebra a contagem (Pitfall 9).
        contagem_reunioes = (
            Acompanhamento.objects.filter(
                processo=OuterRef("pk"), reuniao__isnull=False
            )
            .order_by()
            .values("processo")
            .annotate(c=Count("reuniao", distinct=True))
            .values("c")
        )
        contagem_compromissos = (
            Acompanhamento.objects.filter(
                processo=OuterRef("pk"), prazo_prometido__isnull=False
            )
            .order_by()
            .values("processo")
            .annotate(c=Count("*"))
            .values("c")
        )
        # (02-02) — "compromissos reprometidos" conta processos que
        # assumiram DATAS DE ENTREGA DIFERENTES ao longo do histórico, não
        # só "mais de um compromisso" (contagem_compromissos acima conta
        # toda reunião com prazo, mesmo repetindo a mesma data — ver o caso
        # nomeado do processo 65, 15/05 → 21/08 → 21/08 tem 3
        # compromissos mas só 2 datas distintas). `Count(..., distinct=True)`
        # sobre uma Subquery correlacionada por processo, nunca um `Count()`
        # somado a outro no mesmo `annotate()` (Pitfall 9).
        contagem_prazos_distintos = (
            Acompanhamento.objects.filter(
                processo=OuterRef("pk"), prazo_prometido__isnull=False
            )
            .order_by()
            .values("processo")
            .annotate(c=Count("prazo_prometido", distinct=True))
            .values("c")
        )

        qs = self.select_related(
            "exercicio",
            "unidade_organizacional",
            "categoria",
            "grau_prioridade",
            "classificacao",
        ).annotate(
            situacao_atual=Subquery(ultimo.values("situacao__nome")[:1]),
            prazo_vigente=Subquery(
                ultimo.filter(prazo_prometido__isnull=False).values(
                    "prazo_prometido"
                )[:1]
            ),
            n_reunioes=Coalesce(Subquery(contagem_reunioes), 0),
            n_compromissos=Coalesce(Subquery(contagem_compromissos), 0),
            n_prazos_distintos=Coalesce(Subquery(contagem_prazos_distintos), 0),
            # COALESCE(prazo_entrega, primeira promessa): o prazo
            # original do PCA manda quando existe; sem ele, a PRIMEIRA
            # promessa do histórico é o "Prazo inicial" (EDGE
            # empty: nulo quando nenhuma das duas fontes existe).
            prazo_inicial=Coalesce(
                F("prazo_entrega"),
                Subquery(primeira_promessa.values("prazo_prometido")[:1]),
                output_field=DateField(),
            ),
            # Existe sobreposição manual ativa quando QUALQUER
            # Acompanhamento do processo tem `transicao_manual=True`: não há
            # sinal autorizado de reset, então a existência isolada já
            # basta (mesmo critério de `services.aplicar_regras_
            # automaticas`/`registrar_acompanhamento`).
            # 29/09/2026 — a trava agora é o campo explícito `situacao_manual` (liga na escolha
            # manual, desmarca no Admin), não mais a existência de transição manual no histórico.
            sobreposicao_manual_ativa=F("situacao_manual"),
        )
        qs = qs.annotate(
            reprometido=Case(
                When(n_prazos_distintos__gt=1, then=Value(True)),
                default=Value(False),
                output_field=BooleanField(),
            )
        )

        # Fase 11 — assumption delta: `prazo_efetivo` é a identidade
        # única de avaliação de prazo (COALESCE(prazo_vigente, prazo_entrega)):
        # a promessa vigente da UO manda; sem promessa registrada, cai no
        # prazo de Planejamento. Estágio separado de annotate(), depois que
        # `prazo_vigente` já foi anotado acima — nunca dois Subquery/Count
        # somados no mesmo annotate() (Pitfall 9).
        qs = qs.annotate(
            prazo_efetivo=Coalesce(
                F("prazo_vigente"), F("prazo_entrega"), output_field=DateField()
            ),
        )
        # Número de prorrogações é a contagem de datas distintas
        # menos uma, nunca negativo (piso zero). `reprometido` (acima)
        # permanece só como alias booleano compatível com o querystring
        # legado `?reprometidos=1` (filtros.py).
        qs = qs.annotate(
            n_prorrogacoes=Greatest(F("n_prazos_distintos") - Value(1), Value(0)),
        )

        # "Hoje" resolvido em Python via localdate() — NUNCA
        # timezone.now().date() nem date.today() (Pitfall 11). É uma
        # constante da chamada, não uma expressão SQL de NOW(), para que o
        # teste com freezegun controle o valor de forma determinística.
        hoje = localdate()

        # QA 30/09 (domínio nº2) — commit 93d9a6b (regras_situacao.
        # situacao_por_eventos) só "blinda" o atraso quando o recebimento no
        # Gelic é do ANO DO EXERCÍCIO do próprio processo; essa regra
        # precisa chegar às anotações de LEITURA (atrasado/dias_atraso/
        # qualificador_prazo), que até aqui só checavam
        # `data_recebimento_gelic__isnull`, ignorando o ano. Comparação de
        # ANO com `F("exercicio__ano")` é NULL-safe: sem
        # `data_recebimento_gelic`, a comparação nunca casa (equivalente a
        # `isnull=True` para fins de `~recebido_gelic_no_ano`).
        recebido_gelic_no_ano = Q(data_recebimento_gelic__year__gte=F("exercicio__ano"))

        # Atrasado agora mede contra `prazo_efetivo`,
        # nunca mais `data_prevista_conclusao` (que passa a só descrever a
        # previsão de conclusão da contratação, sem reger nenhuma flag). Rede dupla que fecha o atraso: entrega ao Delic preenchida
        # OU status terminal (Concluído/Cancelado) — o que vier primeiro.
        qs = qs.annotate(
            atrasado=Case(
                When(
                    Q(prazo_efetivo__lt=hoje)
                    & ~recebido_gelic_no_ano
                    & ~Q(situacao=Situacao.CONCLUIDO)
                    & ~Q(estado=Estado.CANCELADO),
                    then=Value(True),
                ),
                default=Value(False),
                output_field=BooleanField(),
            )
        )

        # Dias em atraso: diferença inteira e não negativa entre hoje
        # e `prazo_efetivo`, só quando `atrasado=True`; zero nos demais
        # estados. `DiasEntre` (core.db) calcula a diferença direto no
        # banco, sem consulta por linha nem cálculo Python — portável entre
        # SQLite (julianday) e PostgreSQL (subtração nativa de datas).
        qs = qs.annotate(
            dias_atraso=Case(
                When(
                    atrasado=True,
                    then=DiasEntre(
                        Value(hoje, output_field=DateField()), F("prazo_efetivo")
                    ),
                ),
                default=Value(0),
                output_field=IntegerField(),
            )
        )

        # Qualificador textual da situação: "fora do prazo" quando
        # atrasado; "dentro do prazo" quando há prazo ativo (nem entregue ao
        # Delic, nem em status terminal) ainda não vencido; string vazia sem
        # prazo algum ou já encerrado (o colapsou esse sufixo no
        # import porque o sistema não sabia calcular atraso; agora sabe).
        encerrado = (
            recebido_gelic_no_ano
            | Q(situacao=Situacao.CONCLUIDO)
            | Q(estado=Estado.CANCELADO)
        )
        qs = qs.annotate(
            qualificador_prazo=Case(
                When(atrasado=True, then=Value("fora do prazo")),
                When(
                    Q(prazo_efetivo__isnull=False) & ~encerrado,
                    then=Value("dentro do prazo"),
                ),
                default=Value(""),
                output_field=CharField(),
            )
        )
        # Fase 17 (emendada em 29/08/2026, gap 1) —
        # correção-na-leitura do eixo Situação: um processo gravado NO_PRAZO
        # cuja PROMESSA VIGENTE (`prazo_efetivo = COALESCE(prazo_vigente,
        # prazo_entrega)`, a mesma identidade que `atrasado`/`dias_atraso`
        # usam desde a Fase 11) já venceu é exibido/contado como ATRASADO em
        # toda tela que usa `para_listagem()`, sem job noturno nem escrita no
        # banco. a correção só anda no sentido NO_PRAZO→ATRASADO:
        # qualquer outro valor gravado (inclusive ATRASADO manual/sobreposto)
        # passa direto pelo `default=F("situacao")`, nunca é revertido pela
        # leitura.
        # A correção-na-leitura NO_PRAZO→ATRASADO só se aplica sem
        # sobreposição manual ativa: uma alteração manual explícita (mesmo
        # que tenha sido NO_PRAZO, para um prazo depois vencido) prevalece
        # sobre a leitura factual do prazo. `atrasado`/`dias_atraso` (acima)
        # continuam medindo o prazo factual sem exceção — só a situação
        # exibida respeita a sobreposição manual.
        # Renovação no ano ainda sem contrato/termo aditivo
        # do ano (a regra de escrita a deixa em NO_PRAZO) com a vigência OU
        # o prazo já vencidos: lida como ATRASADO mesmo com sobreposição
        # manual antiga — a regra de renovação × vigência vence o manual.
        qs = qs.annotate(
            situacao_efetiva=Case(
                When(
                    Q(situacao=Situacao.NO_PRAZO)
                    & Q(prazo_efetivo__isnull=False)
                    & Q(prazo_efetivo__lt=hoje)
                    & Q(sobreposicao_manual_ativa=False)
                    & ~Q(estado=Estado.CANCELADO),
                    then=Value(Situacao.ATRASADO),
                ),
                When(
                    Q(situacao=Situacao.NO_PRAZO)
                    & Q(situacao_manual=False)
                    & Q(renovacao_prevista=True)
                    & (
                        Q(vigencia_fim__year=F("exercicio__ano"))
                        | Q(vigencia_fim__isnull=True, tipo__nome_normalizado="renovacao")
                    )
                    & (Q(vigencia_fim__lt=hoje) | Q(prazo_efetivo__lt=hoje))
                    & ~Q(estado=Estado.CANCELADO),
                    then=Value(Situacao.ATRASADO),
                ),
                default=F("situacao"),
                output_field=CharField(),
            )
        )

        qs = qs.annotate(
            publicacao_pendente=Case(
                When(
                    Q(data_assinatura_contrato__lt=hoje)
                    & (
                        Q(data_lancamento_spw__isnull=True)
                        | Q(data_lancamento_wordpress__isnull=True)
                        | Q(data_lancamento_dados_abertos__isnull=True)
                    ),
                    then=Value(True),
                ),
                default=Value(False),
                output_field=BooleanField(),
            )
        )

        return qs

    def criticos(self):
        """(06-01) — "Críticos": apenas processos cujo grau de
        prioridade resolve para "Alta", excluindo concluídos e cancelados.

        Resolve pela chave natural `grau_prioridade__nome_normalizado="alta"`
        (derivada por DominioBase.save()) — sem query de lookup, e tolerante
        a renomeação/acentos do rótulo. Se o grau "Alta" não existir no
        domínio, o filtro retorna vazio (contador zero, link visível).
        Não depende de anotação de `para_listagem()`."""
        from apps.pca.models import Estado, Situacao

        return (
            self.filter(grau_prioridade__nome_normalizado="alta")
            .exclude(situacao=Situacao.CONCLUIDO)
            .exclude(estado=Estado.CANCELADO)
        )

    def proximos_do_prazo(self):
        """(06-01)/Fase 11 — "Próximos do prazo": `prazo_efetivo`
        (anotado por `para_listagem()`, promessa vigente com fallback para o
        prazo de Planejamento) estritamente maior que hoje e menor ou igual
        a hoje+30 dias. Hoje fica fora; dia 30 fica dentro. Exclui
        concluídos e cancelados.

        '"Hoje"' resolvido em Python via localdate() — NUNCA NOW() no SQL
        (Pitfall 11), para freezegun controlar o valor. Pressupõe as
        anotações de `para_listagem()` (prazo_efetivo), como o filtro
        `atrasado` já o faz."""
        from apps.pca.models import Estado, Situacao

        hoje = localdate()
        return (
            self.filter(
                prazo_efetivo__gt=hoje,
                prazo_efetivo__lte=hoje + timedelta(days=30),
            )
            .exclude(situacao=Situacao.CONCLUIDO)
            .exclude(estado=Estado.CANCELADO)
        )

    def proximo_vencimento_gelic(self, dias):
        """Fase 17 — "Próximos do vencimento" (Bloco B): subconjunto de
        NO PRAZO (coluna crua `situacao`, NÃO `situacao_efetiva` — esta é
        annotation exclusiva de `para_listagem()` e pode não estar disponível
        se este método for chamado antes dela) a `dias` corridos ou menos do
        `prazo_entrega`, hoje incluso. Nunca inclui itens já ATRASADOS.
        Exclui CANCELADO (recorte transversal sobre ATIVOS)."""
        from apps.pca.models import Estado, Situacao

        hoje = localdate()
        return self.exclude(estado=Estado.CANCELADO).filter(
            situacao=Situacao.NO_PRAZO,
            prazo_entrega__isnull=False,
            prazo_entrega__gte=hoje,
            prazo_entrega__lte=hoje + timedelta(days=dias),
        )

    def sobrestados(self):
        """Fase 17 — "Processos sobrestados": ATIVOS cuja entrega foi
        adiada mais de uma vez (`n_prorrogacoes > 1`, anotação já existente
        de `para_listagem()` — pressuposta aqui, mesma pressuposição que
        `proximos_do_prazo()`/`criticos()` já fazem para `atrasado`). Pode
        intersectar com ATRASADOS (recorte transversal, não etapa de funil)."""
        from apps.pca.models import Estado

        return self.exclude(estado=Estado.CANCELADO).filter(n_prorrogacoes__gt=1)

    def sem_atualizacao_recente(self):
        """(06-01) — "Sem atualização recente": processos sem nenhum
        acompanhamento OU cujo último acompanhamento (referencia_data mais
        recente) é anterior a hoje-30 dias. Exatamente 30 dias fica fora;
        31 dias fica dentro. Exclui concluídos e cancelados.

        A derivação de "último acompanhamento" é CONDICIONAL — anotada aqui,
        e não em `para_listagem()`, para não pesar em todos os consumidores
        (§Invariants). '"Hoje"' via localdate() em Python
        (Pitfall 11)."""
        from apps.pca.models import Acompanhamento, Estado, Situacao

        hoje = localdate()
        ultimo = Acompanhamento.objects.filter(
            processo=OuterRef("pk")
        ).order_by("-referencia_data", "-id")  # desempate — Pitfall 10
        qs = self.annotate(
            ultimo_acompanhamento_em=Subquery(ultimo.values("referencia_data")[:1])
        )
        return (
            qs.filter(
                Q(ultimo_acompanhamento_em__isnull=True)
                | Q(ultimo_acompanhamento_em__lt=hoje - timedelta(days=30))
            )
            .exclude(situacao=Situacao.CONCLUIDO)
            .exclude(estado=Estado.CANCELADO)
        )
