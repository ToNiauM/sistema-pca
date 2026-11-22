"""Serviço "Contratos a vencer" (Fase 38, spec §2/§4/§8).

Pacote `apps/pca/servicos/` (distinto de `apps/pca/services.py`, mesmo
padrão de `apps/pca/servicos/eventos_financeiros.py`): este módulo não
recebe o objeto da requisição HTTP nem importa view alguma — exercício e
UOs chegam já validados por `apps.pca.filtros.filtros_ativos`, e a
construção do queryset filtrado consolidado daquele mesmo módulo (usado
pela tabela de Processos) fica de fora por decisão (C05): os filtros
legados de situação/estado/tipo de lá contradizem o universo desta seção
(item `concluido` — contratação assinada — é exatamente o contrato vigente
que M07 fazia sumir).

Granularidade (C11): uma linha por item do PCA — a vigência é do
`Processo`, não do instrumento; contagens não representam contratos
distintos dentro de um mesmo item.

`contratos_a_vencer()` é o ponto de entrada público, reutilizável pela
Fase 39 (assistente) sem importar view nem recalcular destino num terceiro
lugar — o único `Case/When` de destino vive em `anotar_destino`, e o único
`aggregate` de KPIs vive em `kpis` (uma consulta de página + um
count de paginação + um aggregate; medido/fixado por
`test_servicos_contratos.py::TestOrcamentoConsultasConstante`)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Sequence

from django.db.models import CharField, Case, Count, QuerySet, Q, Sum, Value, When
from django.utils.timezone import localdate

from apps.pca.models import Estado, Processo, RegimeExecucao
from apps.pca.projecao.virada import CHAVES_DESTINO, GRUPOS_DESTINO, Destino

VENCE_OPCOES = ("todos", "vencidos", "90", "180", "365", "N", "N+1")
RENOVACAO_OPCOES = ("todas", "sim", "nao")


def populacao(exercicio, uos: Sequence[int] = ()) -> QuerySet:
    """"Itens com contrato" do exercício (spec §2): `estado=ativo
    ∧ vigencia_fim IS NOT NULL ∧ regime_execucao != "unico"` (NULL entra —
    `.exclude()` nunca elimina NULL). NÃO filtra por `situacao`, `tipo` nem
    `renovacao_prevista` — a população não decide destino, só existência.
    `exercicio is None` → `Processo.objects.none()` (estado vazio seguro).

    Ordenação: `vigencia_fim` ascendente já coloca os vencidos
    (as datas mais antigas) primeiro, mais antigo primeiro, seguido dos
    ainda vigentes em ordem crescente — um único `order_by` cobre as duas
    regras; desempate por `item_pca`, depois `pk`."""

    if exercicio is None:
        return Processo.objects.none()

    qs = (
        Processo.objects.para_listagem()
        .filter(
            exercicio=exercicio,
            estado=Estado.ATIVO,
            vigencia_fim__isnull=False,
        )
        .exclude(regime_execucao=RegimeExecucao.UNICO)
    )
    if uos:
        qs = qs.filter(unidade_organizacional_id__in=uos)

    return qs.select_related(
        "exercicio", "unidade_organizacional", "tipo"
    ).order_by("vigencia_fim", "item_pca", "pk")


def anotar_destino(qs: QuerySet, exercicio_ano: int, hoje: date) -> QuerySet:
    """Anota `destino` (a chave de `Destino`) por `Case/When` — o ÚNICO
    `Case/When` de destino do sistema. Precedência EXATA de
    `apps/pca/projecao/virada.py::destino`, `When` a `When` — o teste de
    paridade (`TestParidadeCaseWhenVsRegraPura`) é a prova de que os dois
    lugares concordam."""

    return qs.annotate(
        destino=Case(
            When(vigencia_fim__lt=hoje, then=Value(Destino.VENCIDO.chave)),
            When(
                vigencia_fim__year__lte=exercicio_ano,
                renovacao_prevista=False,
                then=Value(Destino.ENCERRA_N.chave),
            ),
            When(
                vigencia_fim__year__lte=exercicio_ano,
                renovacao_prevista=True,
                then=Value(Destino.RENOVA_N.chave),
            ),
            When(
                vigencia_fim__year=exercicio_ano + 1,
                renovacao_prevista=True,
                then=Value(Destino.RENOVACAO_N1.chave),
            ),
            When(
                vigencia_fim__year=exercicio_ano + 1,
                renovacao_prevista=False,
                then=Value(Destino.ENCERRA_N1.chave),
            ),
            default=Value(Destino.VIGENTE_N1.chave),
            output_field=CharField(),
        )
    )


def aplicar_vence(
    qs: QuerySet, vence: str, exercicio_ano: int, hoje: date
) -> QuerySet:
    """Filtro `vence` (§4): horizontes `90`/`180`/`365` são
    inclusivos nas duas pontas (`vigencia_fim == hoje` entra, `hoje + dias`
    entra); `N`/`N+1` são limites superiores inclusivos em 31/12, SEM
    limite inferior (vencidos entram); `vencidos` é `< hoje`;
    `todos`/qualquer valor fora da allowlist não filtra."""

    if vence == "vencidos":
        return qs.filter(vigencia_fim__lt=hoje)
    if vence in ("90", "180", "365"):
        dias = int(vence)
        return qs.filter(
            vigencia_fim__gte=hoje, vigencia_fim__lte=hoje + timedelta(days=dias)
        )
    if vence == "N":
        return qs.filter(vigencia_fim__lte=date(exercicio_ano, 12, 31))
    if vence == "N+1":
        return qs.filter(vigencia_fim__lte=date(exercicio_ano + 1, 12, 31))
    return qs


def aplicar_renovacao(qs: QuerySet, renovacao: str) -> QuerySet:
    """`sim` → `renovacao_prevista=True`; `nao` → `False`; `todas`/valor
    fora da allowlist não filtra."""

    if renovacao == "sim":
        return qs.filter(renovacao_prevista=True)
    if renovacao == "nao":
        return qs.filter(renovacao_prevista=False)
    return qs


def aplicar_destino(
    qs: QuerySet, destino: str | None, grupo_destino: str | None
) -> QuerySet:
    """`destino` (uma chave de `Destino`) prevalece sobre `grupo_destino`
    quando ambos são informados; chave/grupo fora da allowlist não filtra
    (o serviço nunca levanta — quem avisa o usuário é a view)."""

    if destino in CHAVES_DESTINO:
        return qs.filter(destino=destino)
    if grupo_destino in GRUPOS_DESTINO:
        chaves = [d.chave for d in GRUPOS_DESTINO[grupo_destino]]
        return qs.filter(destino__in=chaves)
    return qs


def _kpis_vazio() -> dict:
    vazio = {
        "total": 0,
        "soma_valor_mensal": None,
        "sem_valor_mensal": 0,
        "por_destino": {chave: 0 for chave in CHAVES_DESTINO},
    }
    for grupo in GRUPOS_DESTINO:
        vazio[grupo] = 0
    return vazio


def kpis(recorte_base: QuerySet) -> dict:
    """UM `aggregate` só: `total`, `soma_valor_mensal`, `sem_valor_mensal`,
    os 4 grupos de KPI (`encerramento_n`/`renovacao_n`/
    `renovacao_n1`/`vigente_n1` — os nomes que a tela usa nos cards) e,
    à parte em `por_destino`, as 6 contagens individuais por chave de
    `Destino` (C07 — só para o teste de paridade e para um futuro
    detalhamento; NUNCA no mesmo nível dos 4 grupos: duas chaves de grupo
    — `renovacao_n1`/`vigente_n1` — são literalmente iguais a uma chave de
    destino, então misturar os dois níveis sobrescreveria a contagem
    individual pela soma do grupo). Soma dos grupos em Python é soma de 6
    inteiros já agregados, não iteração de processos (C08/C01).
    `recorte_base` já deve estar anotado com `destino` (`anotar_destino`)."""

    contagens_por_chave = {
        chave: Count("pk", filter=Q(destino=chave)) for chave in CHAVES_DESTINO
    }
    agregados = recorte_base.aggregate(
        total=Count("pk"),
        soma_valor_mensal=Sum("valor_mensal"),
        sem_valor_mensal=Count("pk", filter=Q(valor_mensal__isnull=True)),
        **contagens_por_chave,
    )

    por_destino = {chave: agregados[chave] for chave in CHAVES_DESTINO}
    resultado = {
        "total": agregados["total"],
        "soma_valor_mensal": agregados["soma_valor_mensal"],
        "sem_valor_mensal": agregados["sem_valor_mensal"],
        "por_destino": por_destino,
    }
    for grupo, membros in GRUPOS_DESTINO.items():
        resultado[grupo] = sum(por_destino[membro.chave] for membro in membros)
    return resultado


@dataclass(frozen=True)
class Resultado:
    """Saída de `contratos_a_vencer` — `queryset` já anotado/filtrado/
    ordenado, `kpis` sobre o recorte-base (ANTES de `destino`/
    `grupo_destino`, C08), e os valores efetivamente aplicados (já
    normalizados pelas allowlists)."""

    queryset: QuerySet
    kpis: dict
    exercicio_ano: int | None
    hoje: date
    vence: str
    renovacao: str
    destino: str | None
    grupo_destino: str | None


def contratos_a_vencer(
    exercicio,
    horizonte: str = "todos",
    *,
    uos: Sequence[int] = (),
    renovacao: str = "todas",
    destino: str | None = None,
    grupo_destino: str | None = None,
    hoje: date | None = None,
) -> Resultado:
    """Ponto de entrada público (contrato citado para a
    Fase 39). `horizonte` é o valor de `vence`. Valores fora das allowlists
    (`VENCE_OPCOES`/`RENOVACAO_OPCOES`/`CHAVES_DESTINO`/`GRUPOS_DESTINO`)
    viram o padrão SEM levantar — quem avisa o usuário é a view
    (`messages.warning`), nunca este serviço. `hoje=None` → `localdate()`
    aqui (o módulo puro `projecao.virada` NUNCA tem esse default)."""

    hoje = hoje or localdate()

    vence = horizonte if horizonte in VENCE_OPCOES else "todos"
    renovacao_normalizada = renovacao if renovacao in RENOVACAO_OPCOES else "todas"

    destino_normalizado = destino if destino in CHAVES_DESTINO else None
    grupo_normalizado = None
    if destino_normalizado is None and grupo_destino in GRUPOS_DESTINO:
        grupo_normalizado = grupo_destino

    if exercicio is None:
        return Resultado(
            queryset=Processo.objects.none(),
            kpis=_kpis_vazio(),
            exercicio_ano=None,
            hoje=hoje,
            vence=vence,
            renovacao=renovacao_normalizada,
            destino=destino_normalizado,
            grupo_destino=grupo_normalizado,
        )

    exercicio_ano = exercicio.ano

    base = populacao(exercicio, uos)
    base = aplicar_vence(base, vence, exercicio_ano, hoje)
    base = aplicar_renovacao(base, renovacao_normalizada)
    base = anotar_destino(base, exercicio_ano, hoje)

    kpis_calculados = kpis(base)

    queryset = aplicar_destino(base, destino_normalizado, grupo_normalizado)

    return Resultado(
        queryset=queryset,
        kpis=kpis_calculados,
        exercicio_ano=exercicio_ano,
        hoje=hoje,
        vence=vence,
        renovacao=renovacao_normalizada,
        destino=destino_normalizado,
        grupo_destino=grupo_normalizado,
    )
