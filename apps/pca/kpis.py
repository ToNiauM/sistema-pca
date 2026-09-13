"""Módulo único de definições e cálculo dos 12 KPIs do header analítico
(Bloco A — Volume, Bloco B — Situação) mais o gauge do Bloco C; a UI só
itera sobre os dicts, nenhuma lógica de negócio no template.

Ícones (slugs, lista fechada, na ordem dos 12 cards):
    total, cancelados, ativos, nova, renovacao, vigentes, meta_exercicio,
    no_prazo, tramitacao, concluido, atrasados,
    proximo_vencimento, sobrestado

Bloco B lê sempre situacao_efetiva (annotation corrigida-na-leitura) para
NO PRAZO/ATRASADOS/EM TRAMITAÇÃO/CONCLUÍDO/PRÓXIMOS DO VENCIMENTO, nunca a
coluna crua situacao.

PRÓXIMOS DO VENCIMENTO usa condicao_proximo_do_prazo (base
situacao_efetiva/prazo_efetivo), a mesma leitura de proximidade que
calcular_proximos_vencimentos usa para a tabela "Próximos vencimentos" de
Análises — os dois nunca são apresentados como equivalentes ao KPI de
vigência contratual (vigencia_fim), que permanece um dado à parte.

O card ATRASADOS é a fonte única de "atraso" no dashboard: mede o universo
restrito (Nova Contratação + Renovação ativos).

sinal usa o vocabulário real de data-sinal que _kpi_card.html/input.css
resolvem (neutro|info|ok|ok-cheio|atencao|erro|vigente|marca|seq-600|
seq-450|sobrestado). ok-cheio é a variante terminal de ok — mesma borda,
mais preenchimento; usada só por CONCLUÍDO, para diferenciar do card NO
PRAZO (situação em curso, só borda)."""

from datetime import timedelta
from decimal import Decimal

from django.db.models import Case, Count, Q, When
from django.utils.timezone import localdate

from apps.catalogo.models import Tipo
from apps.pca.filtros import CHAVES_MULTIVALOR, filtros_ativos, querystring_filtros
from apps.pca.models import Estado, Situacao

TITULO_TOTAL = "Total de processos do PCA (CANCELADOS + ATIVOS)."
TITULO_CANCELADOS = "Contratações excluídas do PCA."
TITULO_ATIVOS = "TOTAL PREVISTO subtraído dos CANCELADOS."
TITULO_NOVA = (
    "Processo ATIVO de contratação que será contratada no exercício do PCA."
)
TITULO_RENOVACAO = (
    "Processo ATIVO de contratação que precisa ser renovada no ano corrente "
    "do PCA e que veio de outro exercício."
)
TITULO_VIGENTES = (
    "Processo ATIVO cujo contrato está vigente e extrapola o exercício "
    "(ex.: contrato de 5 anos firmado em 2024 permanece vigente no PCA)."
)
TITULO_META_EXERCICIO = (
    "ATIVOS que ainda precisam ser contratados neste exercício do PCA "
    "(ATIVOS menos VIGENTES)."
)
TITULO_NO_PRAZO = (
    "Processos ATIVOS (Nova Contratação ou Renovação) dentro do prazo de "
    "entrega no Gelic."
)
TITULO_ATRASADOS = (
    "Processos ATIVOS (Nova Contratação ou Renovação) FORA do prazo de "
    "entrega no Gelic."
)
TITULO_EM_TRAMITACAO = (
    "Processos ATIVOS (Nova Contratação ou Renovação) que JÁ FORAM entregues "
    "no prazo no Gelic e seguem em andamento."
)
TITULO_CONCLUIDO = (
    "Todos os processos ATIVOS concluídos — aqui entram Nova Contratação, "
    "Renovação e Vigentes."
    " O percentual exclui Vigentes — eles contam para análise, não para o "
    "cumprimento do PCA do exercício."
)
TITULO_SOBRESTADOS = (
    "Processos ATIVOS que tiveram a entrega no Gelic adiada mais de uma vez."
)


def _titulo_proximos_vencimento(dias):
    return (
        f"Processos ATIVOS (Nova Contratação ou Renovação) a {dias} dias ou "
        "menos do prazo atual."
    )


def condicao_proximo_do_prazo(hoje, ids_elegiveis, *, dias=None, exigir_no_prazo=True):
    """Condição pura de proximidade de prazo (só monta um Q(), nenhuma
    consulta disparada aqui), compartilhada pelo KPI "PRÓXIMOS DO
    VENCIMENTO" e por calcular_proximos_vencimentos. Base prazo_efetivo,
    nunca prazo_entrega."""
    condicao = (
        Q(estado=Estado.ATIVO)
        & Q(tipo_id__in=ids_elegiveis)
        & Q(prazo_efetivo__isnull=False)
        & Q(prazo_efetivo__gte=hoje)
    )
    if exigir_no_prazo:
        condicao &= Q(situacao_efetiva=Situacao.NO_PRAZO)
    if dias is not None:
        condicao &= Q(prazo_efetivo__lte=hoje + timedelta(days=dias))
    return condicao


def _percentual(numerador, denominador):
    """Zero-safe: None (nunca 0 nem ZeroDivisionError) quando o
    denominador é zero; a UI trata None como "valor indisponível"."""
    if not denominador:
        return None
    return Decimal(numerador) / Decimal(denominador) * Decimal("100")


def _esta_selecionado(filtros_atuais, overrides):
    """Compara, para cada chave de overrides, se o filtro atual da
    requisição já bate com o card. Decide se o clique deve limpar o
    filtro (segundo clique) em vez de aplicá-lo."""
    for chave, valor in overrides.items():
        if chave in CHAVES_MULTIVALOR:
            esperado = {
                str(v) for v in (valor if isinstance(valor, (list, tuple)) else [valor])
            }
            atual = {str(v) for v in (filtros_atuais.get(chave) or [])}
            if esperado != atual:
                return False
        else:
            if not filtros_atuais.get(chave):
                return False
    return True


def calcular_blocos_kpi(qs, get, *, dias_proximo_vencimento):
    """Recebe o qs já filtrado e os dias de PRÓXIMOS DO VENCIMENTO. Devolve
    (bloco_a, bloco_b, gauge_conclusao) — dicts prontos para o template
    iterar, sem nenhuma consulta por KPI: 1 lookup de Tipo + 1
    .aggregate() combinado, nunca mais que 2 queries no total."""
    hoje = localdate()

    ids_tipo = dict(
        Tipo.objects.filter(
            nome_normalizado__in=("nova contratacao", "renovacao", "vigente")
        ).values_list("nome_normalizado", "id")
    )
    id_nova = ids_tipo.get("nova contratacao")
    id_renovacao = ids_tipo.get("renovacao")
    id_vigente = ids_tipo.get("vigente")
    ids_elegiveis = [i for i in (id_nova, id_renovacao) if i is not None]
    # Vigentes contam para análise, nunca para o cumprimento do PCA do
    # exercício corrente: o percentual do card CONCLUÍDO e o gauge
    # excluem Vigentes do numerador e do denominador
    q_nao_vigente = ~Q(tipo_id=id_vigente) if id_vigente is not None else Q()

    agregados = qs.aggregate(
        total=Count("id"),
        cancelados=Count(Case(When(estado=Estado.CANCELADO, then=1))),
        nova=Count(Case(When(Q(estado=Estado.ATIVO) & Q(tipo_id=id_nova), then=1))),
        renovacao=Count(
            Case(When(Q(estado=Estado.ATIVO) & Q(tipo_id=id_renovacao), then=1))
        ),
        vigentes_natureza=Count(
            Case(When(Q(estado=Estado.ATIVO) & Q(tipo_id=id_vigente), then=1))
        ),
        no_prazo=Count(
            Case(
                When(
                    Q(estado=Estado.ATIVO)
                    & Q(tipo_id__in=ids_elegiveis)
                    & Q(situacao_efetiva=Situacao.NO_PRAZO),
                    then=1,
                )
            )
        ),
        atrasados=Count(
            Case(
                When(
                    Q(estado=Estado.ATIVO)
                    & Q(tipo_id__in=ids_elegiveis)
                    & Q(situacao_efetiva=Situacao.ATRASADO),
                    then=1,
                )
            )
        ),
        em_tramitacao=Count(
            Case(
                When(
                    Q(estado=Estado.ATIVO)
                    & Q(tipo_id__in=ids_elegiveis)
                    & Q(situacao_efetiva=Situacao.EM_TRAMITACAO),
                    then=1,
                )
            )
        ),
        concluido=Count(
            Case(
                When(
                    Q(estado=Estado.ATIVO) & Q(situacao_efetiva=Situacao.CONCLUIDO),
                    then=1,
                )
            )
        ),
        # mesmo .aggregate() combinado: base do percentual do card CONCLUÍDO/gauge
        concluido_sem_vigente=Count(
            Case(
                When(
                    Q(estado=Estado.ATIVO)
                    & Q(situacao_efetiva=Situacao.CONCLUIDO)
                    & q_nao_vigente,
                    then=1,
                )
            )
        ),
        # Meta/Concluído da meta exatos (mesmo universo NC|RN), para o
        # apoio do KPI Concluídos não superestimar a meta quando existem
        # "outros tipos"
        concluido_meta=Count(
            Case(
                When(
                    Q(estado=Estado.ATIVO)
                    & Q(tipo_id__in=ids_elegiveis)
                    & Q(situacao_efetiva=Situacao.CONCLUIDO),
                    then=1,
                )
            )
        ),
        # condicao_proximo_do_prazo substitui o Q() cru de prazo_entrega/situacao
        proximos_vencimento=Count(
            Case(
                When(
                    condicao_proximo_do_prazo(
                        hoje, ids_elegiveis, dias=dias_proximo_vencimento
                    ),
                    then=1,
                )
            )
        ),
        sobrestados=Count(
            Case(When(Q(estado=Estado.ATIVO) & Q(n_prorrogacoes__gt=1), then=1))
        ),
    )

    total = agregados["total"] or 0
    cancelados = agregados["cancelados"] or 0
    ativos = total - cancelados
    nova = agregados["nova"] or 0
    renovacao = agregados["renovacao"] or 0
    vigentes_natureza = agregados["vigentes_natureza"] or 0
    elegivel = nova + renovacao
    no_prazo = agregados["no_prazo"] or 0
    atrasados = agregados["atrasados"] or 0
    em_tramitacao = agregados["em_tramitacao"] or 0
    concluido = agregados["concluido"] or 0
    concluido_sem_vigente = agregados["concluido_sem_vigente"] or 0
    ativos_sem_vigente = ativos - vigentes_natureza
    proximos_vencimento = agregados["proximos_vencimento"] or 0
    sobrestados = agregados["sobrestados"] or 0

    # invariante nova + renovacao + vigentes == ativos; divergência vira
    # selo de inconsistência no card ATIVOS
    soma_natureza = nova + renovacao + vigentes_natureza
    inconsistente_ativos = soma_natureza != ativos
    diferenca_ativos = abs(ativos - soma_natureza)

    titulo_ativos = TITULO_ATIVOS
    selo_inconsistencia_ativos = ""
    if inconsistente_ativos:
        texto_divergencia = (
            f"Atenção: a soma por natureza diverge em {diferenca_ativos} "
            f"processo(s)."
        )
        titulo_ativos = TITULO_ATIVOS + " " + texto_divergencia
        # o mesmo texto do title do card precisa virar selo visível, não só tooltip
        selo_inconsistencia_ativos = texto_divergencia

    filtros_atuais = filtros_ativos(get)

    def card(rotulo, contagem, percentual, sinal, titulo, icone, overrides):
        if not overrides:
            return {
                "rotulo": rotulo,
                "contagem": contagem,
                "percentual": percentual,
                "sinal": sinal,
                "titulo": titulo,
                "icone": icone,
                "href": querystring_filtros(get),
                "selecionado": False,
            }
        selecionado = _esta_selecionado(filtros_atuais, overrides)
        href = (
            querystring_filtros(get, excluir=list(overrides.keys()))
            if selecionado
            else querystring_filtros(get, **overrides)
        )
        return {
            "rotulo": rotulo,
            "contagem": contagem,
            "percentual": percentual,
            "sinal": sinal,
            "titulo": titulo,
            "icone": icone,
            "href": href,
            "selecionado": selecionado,
        }

    bloco_a = {
        "total": card(
            "TOTAL PREVISTO", total, None, "neutro", TITULO_TOTAL, "total", {}
        ),
        "cancelados": card(
            "CANCELADOS",
            cancelados,
            _percentual(cancelados, total),
            "neutro",
            TITULO_CANCELADOS,
            "cancelados",
            {"estado": [Estado.CANCELADO.value]},
        ),
        "ativos": {
            **card(
                "ATIVOS",
                ativos,
                _percentual(ativos, total),
                "marca",
                titulo_ativos,
                "ativos",
                {"estado": [Estado.ATIVO.value]},
            ),
            "inconsistente": inconsistente_ativos,
            "selo_inconsistencia": selo_inconsistencia_ativos,
        },
        "nova": card(
            "NOVA CONTRATAÇÃO",
            nova,
            _percentual(nova, ativos),
            "seq-600",
            TITULO_NOVA,
            "nova",
            (
                {"estado": [Estado.ATIVO.value], "tipo": [id_nova]}
                if id_nova is not None
                else {}
            ),
        ),
        "renovacao": card(
            "RENOVAÇÃO",
            renovacao,
            _percentual(renovacao, ativos),
            "seq-450",
            TITULO_RENOVACAO,
            "renovacao",
            (
                {"estado": [Estado.ATIVO.value], "tipo": [id_renovacao]}
                if id_renovacao is not None
                else {}
            ),
        ),
        "vigentes": card(
            "VIGENTES",
            vigentes_natureza,
            _percentual(vigentes_natureza, ativos),
            "vigente",
            TITULO_VIGENTES,
            "vigentes",
            (
                {"estado": [Estado.ATIVO.value], "tipo": [id_vigente]}
                if id_vigente is not None
                else {}
            ),
        ),
        "meta_exercicio": card(
            "META EXERCÍCIO",
            ativos_sem_vigente,
            _percentual(ativos_sem_vigente, ativos),
            "marca",
            TITULO_META_EXERCICIO,
            "meta_exercicio",
            (
                {"estado": [Estado.ATIVO.value], "tipo": ids_elegiveis}
                if ids_elegiveis
                else {}
            ),
        ),
    }

    # ordem de leitura do funil; concluido usa ok-cheio (terminal),
    # distinto de no_prazo (ok, em curso)
    bloco_b = {
        "no_prazo": card(
            "NO PRAZO",
            no_prazo,
            _percentual(no_prazo, elegivel),
            "ok",
            TITULO_NO_PRAZO,
            "no_prazo",
            {
                "estado": [Estado.ATIVO.value],
                "tipo": ids_elegiveis,
                "situacao": [Situacao.NO_PRAZO.value],
            },
        ),
        "em_tramitacao": card(
            "EM TRAMITAÇÃO",
            em_tramitacao,
            _percentual(em_tramitacao, elegivel),
            "info",
            TITULO_EM_TRAMITACAO,
            "tramitacao",
            {
                "estado": [Estado.ATIVO.value],
                "tipo": ids_elegiveis,
                "situacao": [Situacao.EM_TRAMITACAO.value],
            },
        ),
        "concluido": {
            **card(
                "CONCLUÍDO",
                concluido,
                _percentual(concluido_sem_vigente, ativos_sem_vigente),
                "ok-cheio",
                TITULO_CONCLUIDO,
                "concluido",
                {
                    "estado": [Estado.ATIVO.value],
                    "situacao": [Situacao.CONCLUIDO.value],
                },
            ),
            # apoio do KPI Concluídos: meta/concluído da meta exatos
            # (universo NC|RN), ao lado das chaves já existentes
            "meta_pca": elegivel,
            "concluido_meta_pca": agregados["concluido_meta"] or 0,
            "percentual_meta_pca": _percentual(
                agregados["concluido_meta"], elegivel
            ),
        },
        "atrasados": card(
            "ATRASADOS",
            atrasados,
            _percentual(atrasados, elegivel),
            "erro",
            TITULO_ATRASADOS,
            "atrasados",
            {
                "estado": [Estado.ATIVO.value],
                "tipo": ids_elegiveis,
                "situacao": [Situacao.ATRASADO.value],
            },
        ),
        # limitação conhecida: o href de drill-down ainda usa
        # vencimento_proximo=1 (base prazo_entrega/situacao crua), enquanto
        # a contagem acima já usa condicao_proximo_do_prazo — os dois podem
        # divergir num recorte com promessas vigentes distintas
        "proximos_vencimento": card(
            "PRÓXIMOS DO VENCIMENTO",
            proximos_vencimento,
            _percentual(proximos_vencimento, ativos),
            "atencao",
            _titulo_proximos_vencimento(dias_proximo_vencimento),
            "proximo_vencimento",
            {
                "estado": [Estado.ATIVO.value],
                "situacao": [Situacao.NO_PRAZO.value],
                "vencimento_proximo": "1",
            },
        ),
        "sobrestados": card(
            "PROCESSOS SOBRESTADOS",
            sobrestados,
            _percentual(sobrestados, ativos),
            "sobrestado",
            TITULO_SOBRESTADOS,
            "sobrestado",
            {"estado": [Estado.ATIVO.value], "sobrestado": "1"},
        ),
    }

    # cada faixa da meia-lua carrega seu próprio querystring, os dois
    # excluindo Vigentes
    tipo_overrides = {"tipo": ids_elegiveis} if ids_elegiveis else {}
    gauge_conclusao = {
        # o gauge é uma visualização de percentual de cumprimento: os dois
        # números que o compõem excluem Vigentes
        "concluidos": concluido_sem_vigente,
        "ativos": ativos_sem_vigente,
        # subtração Python pura sobre valores já calculados, sem query nova
        "restantes": max(ativos_sem_vigente - concluido_sem_vigente, 0),
        "href_concluidos": querystring_filtros(
            get,
            estado=[Estado.ATIVO.value],
            situacao=[Situacao.CONCLUIDO.value],
            **tipo_overrides,
        ),
        "href_restantes": querystring_filtros(
            get,
            estado=[Estado.ATIVO.value],
            situacao=[
                Situacao.NO_PRAZO.value,
                Situacao.ATRASADO.value,
                Situacao.EM_TRAMITACAO.value,
            ],
            **tipo_overrides,
        ),
    }

    return bloco_a, bloco_b, gauge_conclusao
