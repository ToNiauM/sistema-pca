from datetime import timedelta

from django.db.models import (
    BooleanField,
    Case,
    CharField,
    Count,
    DateField,
    DurationField,
    ExpressionWrapper,
    Exists,
    F,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    Value,
    When,
)
from django.db.models.functions import Coalesce, Extract, Greatest
from django.utils.timezone import localdate

from .managers import QuerySetAuditado


class ProcessoQuerySet(QuerySetAuditado):
    """Queryset base com as propriedades derivadas do histórico (nº de
    reuniões, nº de compromissos assumidos, prazo prometido vigente,
    situação na última reunião) mais a anotação de atraso. Consumido por
    tabela, kanban, dashboard e export sempre via .para_listagem(), nunca
    annotate() repetido numa view."""

    def para_listagem(self):
        # import local: evita import circular entre models.py e querysets.py
        from apps.pca.models import Acompanhamento, Estado, Situacao

        ultimo = Acompanhamento.objects.filter(
            processo=OuterRef("pk")
        ).order_by("-referencia_data", "-id")  # desempate determinístico

        # "Prazo inicial": ordenação ascendente por (referencia_data, id),
        # a primeira promessa já registrada, espelho do desempate
        # descendente de ultimo acima
        primeira_promessa = Acompanhamento.objects.filter(
            processo=OuterRef("pk"), prazo_prometido__isnull=False
        ).order_by("referencia_data", "id")

        # .order_by() vazio antes de .values().annotate(): limpa o
        # Meta.ordering herdado, que senão entra no GROUP BY e quebra a contagem
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
        # "compromissos reprometidos" conta processos que assumiram datas
        # de entrega diferentes ao longo do histórico, não só "mais de um
        # compromisso". Count(..., distinct=True) sobre uma Subquery
        # correlacionada, nunca um Count() somado a outro no mesmo annotate()
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
            # COALESCE(prazo_entrega, primeira promessa): o prazo original
            # do PCA manda quando existe; sem ele, a primeira promessa do
            # histórico é o "Prazo inicial"
            prazo_inicial=Coalesce(
                F("prazo_entrega"),
                Subquery(primeira_promessa.values("prazo_prometido")[:1]),
                output_field=DateField(),
            ),
            # existe sobreposição manual ativa quando qualquer
            # Acompanhamento do processo tem transicao_manual=True
            sobreposicao_manual_ativa=Exists(
                Acompanhamento.objects.filter(
                    processo=OuterRef("pk"), transicao_manual=True
                )
            ),
        )
        qs = qs.annotate(
            reprometido=Case(
                When(n_prazos_distintos__gt=1, then=Value(True)),
                default=Value(False),
                output_field=BooleanField(),
            )
        )

        # prazo_efetivo é a identidade única de avaliação de prazo
        # (COALESCE(prazo_vigente, prazo_entrega)): a promessa vigente da
        # UO manda; sem promessa registrada, cai no prazo de Planejamento.
        # Estágio separado de annotate(), depois que prazo_vigente já foi
        # anotado acima
        qs = qs.annotate(
            prazo_efetivo=Coalesce(
                F("prazo_vigente"), F("prazo_entrega"), output_field=DateField()
            ),
        )
        # número de prorrogações é a contagem de datas distintas menos uma,
        # nunca negativo. reprometido permanece só como alias booleano
        # compatível com o querystring legado ?reprometidos=1
        qs = qs.annotate(
            n_prorrogacoes=Greatest(F("n_prazos_distintos") - Value(1), Value(0)),
        )

        # "hoje" resolvido em Python via localdate(), nunca
        # timezone.now().date() nem date.today(); constante da chamada,
        # não uma expressão SQL de NOW(), para o teste com freezegun
        # controlar o valor
        hoje = localdate()

        # atrasado mede contra prazo_efetivo, nunca data_prevista_conclusao.
        # Rede dupla que fecha o atraso: entrega ao Delic preenchida ou
        # status terminal (Concluído/Cancelado), o que vier primeiro
        qs = qs.annotate(
            atrasado=Case(
                When(
                    Q(prazo_efetivo__lt=hoje)
                    & Q(data_recebimento_gelic__isnull=True)
                    & ~Q(situacao=Situacao.CONCLUIDO)
                    & ~Q(estado=Estado.CANCELADO),
                    then=Value(True),
                ),
                default=Value(False),
                output_field=BooleanField(),
            )
        )

        # dias em atraso: diferença inteira e não negativa entre hoje e
        # prazo_efetivo, só quando atrasado=True; zero nos demais estados.
        # EXTRACT(DAY FROM ...) lê esse número direto no banco
        diferenca_em_dias = ExpressionWrapper(
            Value(hoje, output_field=DateField()) - F("prazo_efetivo"),
            output_field=DurationField(),
        )
        qs = qs.annotate(
            dias_atraso=Case(
                When(atrasado=True, then=Extract(diferenca_em_dias, "day")),
                default=Value(0),
                output_field=IntegerField(),
            )
        )

        # qualificador textual da situação: "fora do prazo" quando
        # atrasado; "dentro do prazo" quando há prazo ativo ainda não
        # vencido; string vazia sem prazo algum ou já encerrado
        encerrado = (
            Q(data_recebimento_gelic__isnull=False)
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
        # correção-na-leitura do eixo Situação: um processo gravado
        # NO_PRAZO cuja promessa vigente (prazo_efetivo) já venceu é
        # exibido/contado como ATRASADO em toda tela que usa
        # para_listagem(), sem job noturno nem escrita no banco. A correção
        # só anda no sentido NO_PRAZO->ATRASADO: qualquer outro valor
        # gravado passa direto pelo default=F("situacao"), nunca é
        # revertido pela leitura.
        # a correção-na-leitura só se aplica sem sobreposição manual ativa:
        # uma alteração manual explícita prevalece sobre a leitura factual
        # do prazo. atrasado/dias_atraso continuam medindo o prazo factual
        # sem exceção — só a situação exibida respeita a sobreposição manual
        qs = qs.annotate(
            situacao_efetiva=Case(
                When(
                    Q(situacao=Situacao.NO_PRAZO)
                    & Q(prazo_efetivo__isnull=False)
                    & Q(prazo_efetivo__lt=hoje)
                    & Q(sobreposicao_manual_ativa=False),
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
        """"Críticos": apenas processos cujo grau de prioridade resolve
        para "Alta", excluindo concluídos e cancelados. Resolve pela chave
        natural grau_prioridade__nome_normalizado="alta", tolerante a
        renomeação/acentos do rótulo. Não depende de para_listagem()."""
        from apps.pca.models import Estado, Situacao

        return (
            self.filter(grau_prioridade__nome_normalizado="alta")
            .exclude(situacao=Situacao.CONCLUIDO)
            .exclude(estado=Estado.CANCELADO)
        )

    def proximos_do_prazo(self):
        """"Próximos do prazo": prazo_efetivo estritamente maior que hoje
        e menor ou igual a hoje+30 dias. Hoje fica fora; dia 30 fica
        dentro. Exclui concluídos e cancelados. Pressupõe as anotações de
        para_listagem() (prazo_efetivo)."""
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
        """"Próximos do vencimento" (Bloco B): subconjunto de NO PRAZO
        (coluna crua situacao, não situacao_efetiva) a dias corridos ou
        menos do prazo_entrega, hoje incluso. Nunca inclui itens já
        ATRASADOS. Exclui CANCELADO."""
        from apps.pca.models import Estado, Situacao

        hoje = localdate()
        return self.exclude(estado=Estado.CANCELADO).filter(
            situacao=Situacao.NO_PRAZO,
            prazo_entrega__isnull=False,
            prazo_entrega__gte=hoje,
            prazo_entrega__lte=hoje + timedelta(days=dias),
        )

    def sobrestados(self):
        """"Processos sobrestados": ATIVOS cuja entrega foi adiada mais de
        uma vez (n_prorrogacoes > 1). Pode intersectar com ATRASADOS."""
        from apps.pca.models import Estado

        return self.exclude(estado=Estado.CANCELADO).filter(n_prorrogacoes__gt=1)

    def sem_atualizacao_recente(self):
        """"Sem atualização recente": processos sem nenhum acompanhamento
        ou cujo último acompanhamento é anterior a hoje-30 dias. Exclui
        concluídos e cancelados. A derivação de "último acompanhamento" é
        condicional, anotada aqui e não em para_listagem(), para não pesar
        em todos os consumidores."""
        from apps.pca.models import Acompanhamento, Estado, Situacao

        hoje = localdate()
        ultimo = Acompanhamento.objects.filter(
            processo=OuterRef("pk")
        ).order_by("-referencia_data", "-id")  # desempate determinístico
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
