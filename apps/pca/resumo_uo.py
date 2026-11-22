"""Fase 17.1 — tabela resumo por UO, semântica de
FOTO ATUAL, calculada ao vivo do banco. Reproduz, no que a foto atual
permite, a planilha `Percentual_execucao_UO_27_07_26_.xlsx` que a equipe já
usa na reunião mensal (aba `27_07_26`, 21 colunas A:U) — sem série Mensal,
sem snapshots, sem Inclusões/Exclusões do mês, sem base recalculada I
(dependem de fotografia periódica que o sistema ainda não
materializa).

Módulo único de agregação: `calcular_resumo_uo(qs)` recebe o queryset JÁ
filtrado (saída de `apps.pca.filtros.queryset_filtrado`), roda 1 única
consulta `.values().annotate()` (mais 1 lookup de `Tipo`, mesmo orçamento de
`apps.pca.kpis.calcular_blocos_kpi`: "1 lookup de Tipo + 1 aggregate, nunca
mais que 2 queries no total") e devolve `(linhas, total)` — nunca uma
consulta por UO (T-172-03).

NUNCA reimplementa `situacao_efetiva`/`estado`/`_percentual`: lê a annotation
de `ProcessoQuerySet.para_listagem()` e importa `_percentual` literalmente
de `apps.pca.kpis` (T-172-04) — os números daqui nunca divergem dos de
`/dashboard`/`/tabela` para o mesmo filtro.

Mapeamento fino coluna -> regra (documentação canônica;
reorganiza a tabela em torno da META do PCA), 4 blocos além da coluna UO:

Bloco FIXO (universo da UO):
- "Total previsto" = TODOS os processos da UO no exercício resolvido,
  `Estado.ATIVO` + `Estado.CANCELADO` (mesmo universo do card "TOTAL
  PREVISTO" de `calcular_blocos_kpi`); "% no PCA" = total_previsto da UO /
  soma do total_previsto de TODAS as UOs do escopo (nunca denominador fixo).
- "Cancelados" = `Estado.CANCELADO` no escopo, calculado
  em Python como `total_previsto - ativos` (zero query nova, os dois
  operandos já vêm agregados); % = /total_previsto da UO.
- "Ativos" = `Estado.ATIVO`; % = /total_previsto da UO. Coluna-SÍNTESE
  (Ativos = Meta + Vigentes), destacada na tela e no XLSX.

Bloco POR TIPO (decomposição dos Ativos):
- "Nova Contratação" / "Renovação" / "Vigente" = decomposição por `tipo`,
  restrita a `Estado.ATIVO`; % = /ativos da UO.

Bloco META (o número que a equipe persegue na reunião
mensal: "dos N da meta, onde estão?"):
- "Meta" = nova + renovacao = ativos − vigentes (derivada em Python em
  `_linha`, zero query nova); % = /ativos da UO. Coluna-SÍNTESE destacada.
- As 4 colunas seguintes DECOMPÕEM a Meta e FECHAM a conta: `Situacao` tem
  exatamente 4 valores (NO_PRAZO, ATRASADO, EM_TRAMITACAO, CONCLUIDO),
  logo, para o universo ATIVO & (Nova|Renovação),
  concluido_meta + em_tramitacao + no_prazo + fora_prazo == meta POR
  CONSTRUÇÃO. Percentuais TODOS sobre a meta da UO — somam 100%:
  - "Concluído (meta)" = `situacao_efetiva=CONCLUIDO` E `Estado.ATIVO` E
    `tipo in (Nova, Renovação)`; % = /meta.
  - "Em tramitação" = `situacao_efetiva=EM_TRAMITACAO`, mesmo universo;
    % = /meta (a base "elegível" de antes JÁ era a meta — só mudou o nome).
  - "No prazo" = `situacao_efetiva=NO_PRAZO`, mesmo universo — NC+RN
    CONSOLIDADOS numa coluna só; o recorte por tipo saiu da tabela e vive
    apenas no drill-down (filtros de /tabela); % = /meta.
  - "Fora do prazo" = `situacao_efetiva=ATRASADO`, mesmo universo,
    consolidado; % = /meta.

Bloco ANÁLISE:
- "Concluído c/ Vigentes" = `situacao_efetiva=CONCLUIDO` sobre
  `Estado.ATIVO` (Nova + Renovação + Vigente); % = /ativos da UO. Regra de
  negócio (reafirmada): Vigentes contam
  para ANÁLISE, nunca para o cumprimento do PCA do exercício corrente —
  por isso ficam fora da Meta e do bloco META inteiro.

Grupo SITUAÇÃO DOS ATIVOS (partição irrestrita
por tipo de A, ao lado da partição restrita a NC/RN do bloco META acima):
- "Concluídos" = `concluido` (já existente, Cₐ); "Em tramitação"/"No
  prazo"/"Atrasados" = `em_tramitacao_ativos`/`no_prazo_ativos`/
  `atrasado_ativos`, MESMO filtro de `concluido` trocando só
  `situacao_efetiva`, SEM restrição de tipo. `Situacao` tem exatamente 4
  valores, logo `concluido + em_tramitacao_ativos + no_prazo_ativos +
  atrasado_ativos == ativos` fecha por construção (mesma garantia MECE da
  partição da meta). Percentuais TODOS /ativos.
- "Outros tipos" ("A não é assumido como M+V") = `ativos - (nova +
  renovacao + vigente)`, derivado em Python em `_linha` (zero query nova,
  mesmo padrão de `cancelados`/`meta`); torna a soma "Por tipo" honesta
  quando existe processo ATIVO de um tipo além de NC/RN/VG. % = /ativos.

A linha TOTAL soma os NÚMEROS ABSOLUTOS de todas as UOs e recalcula os
percentuais sobre esses totais — nunca a média dos percentuais de linha
(um erro clássico de planilha que este módulo evita por construção).

Os defeitos conhecidos da planilha original (K11 hardcoded, SUMs
truncados em E19/F19, fórmulas não uniformes em I) não têm onde acontecer
aqui: tudo é somado pelo ORM/Python, nunca uma fórmula replicada."""

from django.db.models import Count, F, Q
from django.db.models.functions import Collate

from apps.catalogo.models import Tipo
from apps.pca.kpis import _percentual
from apps.pca.models import Estado, Situacao

# Chaves somadas em Python para montar a linha TOTAL — os números
# ABSOLUTOS por UO, nunca os percentuais (que são recalculados sobre a soma).
_CHAVES_ABSOLUTAS = (
    "total_previsto",
    "ativos",
    "nova",
    "renovacao",
    "vigente",
    "concluido",
    "concluido_meta",
    "em_tramitacao",
    "no_prazo",
    "fora_prazo",
    # Partição de SITUAÇÃO DOS ATIVOS, irrestrita por
    # tipo (Cₐ já era `concluido`, acima); estas 3 SÃO annotations do ORM
    # (existem como chave em `agregados_uo`), diferente de `outros_tipos`,
    #que — como `meta`/`cancelados` — é derivada em Python
    # dentro de `_linha` a partir de `ativos`/`nova`/`renovacao`/`vigente`
    # (todos já lineares em `_CHAVES_ABSOLUTAS`); por isso `outros_tipos`
    # NÃO entra aqui (entraria em KeyError contra o dict bruto do ORM) — a
    # soma bate por construção porque os 4 operandos batem.
    "em_tramitacao_ativos",
    "no_prazo_ativos",
    "atrasado_ativos",
)


def _q_tipo(id_tipo):
    """None-safe: um `id_tipo` ausente do catálogo (Tipo "nova
    contratacao"/"renovacao"/"vigente" não cadastrado) nunca vira
    `Q(tipo_id=None)` — que o ORM traduziria para `tipo_id IS NULL` e
    contaria processos sem tipo algum. Devolve uma condição que nunca
    casa com nenhuma linha."""
    return Q(tipo_id=id_tipo) if id_tipo is not None else Q(pk__in=[])


def _linha(uo_id, uo_nome, dados, total_previsto_geral):
    """Monta uma linha (UO ou TOTAL) a partir dos números absolutos já
    agregados, calculando os percentuais zero-safe via `_percentual`
    (de `apps.pca.kpis`, nunca reimplementada). acrescenta
    `cancelados`/`ativos` (derivados em Python, zero query nova — os dois
    operandos já vêm agregados); deriva `meta` do mesmo
    jeito (nova + renovacao, como `cancelados` — por isso `meta` NÃO entra
    em `_CHAVES_ABSOLUTAS`: a meta do TOTAL sai correta da soma de
    nova+renovacao) e ancora os percentuais do bloco META todos em /meta."""
    nova = dados["nova"]
    renovacao = dados["renovacao"]
    # A Meta do PCA da UO: nova + renovacao = ativos −
    # vigentes. As 4 chaves seguintes do bloco META a decompõem e fecham a
    # conta (Situacao tem exatamente 4 valores): concluido_meta +
    # em_tramitacao + no_prazo + fora_prazo == meta, por construção.
    meta = nova + renovacao
    cancelados = dados["total_previsto"] - dados["ativos"]
    # "A não é assumido como M+V": alguma UO pode ter
    # processo ATIVO de um tipo além de NC/RN/VG, hoje invisível na
    # decomposição "Por tipo". Derivado em Python, zero query nova (mesmo
    # padrão de `cancelados`/`meta` acima).
    outros_tipos = dados["ativos"] - (nova + renovacao + dados["vigente"])
    return {
        "uo_id": uo_id,
        "uo": uo_nome,
        "total_previsto": dados["total_previsto"],
        "percentual_no_pca": _percentual(dados["total_previsto"], total_previsto_geral),
        "cancelados": cancelados,
        "percentual_cancelados": _percentual(cancelados, dados["total_previsto"]),
        "ativos": dados["ativos"],
        "percentual_ativos": _percentual(dados["ativos"], dados["total_previsto"]),
        "nova": nova,
        "percentual_nova": _percentual(nova, dados["ativos"]),
        "renovacao": renovacao,
        "percentual_renovacao": _percentual(renovacao, dados["ativos"]),
        "vigente": dados["vigente"],
        "percentual_vigente": _percentual(dados["vigente"], dados["ativos"]),
        "outros_tipos": outros_tipos,
        "percentual_outros_tipos": _percentual(outros_tipos, dados["ativos"]),
        "meta": meta,
        "percentual_meta": _percentual(meta, dados["ativos"]),
        "concluido_meta": dados["concluido_meta"],
        "percentual_concluido_meta": _percentual(dados["concluido_meta"], meta),
        "em_tramitacao": dados["em_tramitacao"],
        "percentual_em_tramitacao": _percentual(dados["em_tramitacao"], meta),
        "no_prazo": dados["no_prazo"],
        "percentual_no_prazo": _percentual(dados["no_prazo"], meta),
        "fora_prazo": dados["fora_prazo"],
        "percentual_fora_prazo": _percentual(dados["fora_prazo"], meta),
        # Bloco ANÁLISE — contagem inclui Vigentes; % sobre ativos.
        "concluido": dados["concluido"],
        "percentual_concluido": _percentual(dados["concluido"], dados["ativos"]),
        # GRUPO NOVO "Situação dos ativos":
        # partição IRRESTRITA por tipo sobre A (`concluido`, acima, é o
        # 1º membro — Cₐ). `concluido + em_tramitacao_ativos +
        # no_prazo_ativos + atrasado_ativos == ativos` fecha por construção
        # (mesma garantia MECE do bloco META: `Situacao` tem exatamente 4
        # valores). Percentuais todos /ativos.
        "em_tramitacao_ativos": dados["em_tramitacao_ativos"],
        "percentual_em_tramitacao_ativos": _percentual(
            dados["em_tramitacao_ativos"], dados["ativos"]
        ),
        "no_prazo_ativos": dados["no_prazo_ativos"],
        "percentual_no_prazo_ativos": _percentual(
            dados["no_prazo_ativos"], dados["ativos"]
        ),
        "atrasado_ativos": dados["atrasado_ativos"],
        "percentual_atrasado_ativos": _percentual(
            dados["atrasado_ativos"], dados["ativos"]
        ),
    }


def ids_tipo_recorte():
    """(rule 7) — extraído de `calcular_resumo_uo` para que
    a view de drill-down (`apps.pca.views._hrefs_resumo_uo`) reaproveite os
    MESMOS ids de Tipo que a agregação já resolvia internamente, em vez de
    consultar `Tipo` de novo ou hardcodar nome. Nenhuma regra de negócio
    nova: só expõe uma chave de recorte que já existia, escondida."""
    return dict(
        Tipo.objects.filter(
            nome_normalizado__in=("nova contratacao", "renovacao", "vigente")
        ).values_list("nome_normalizado", "id")
    )


def calcular_resumo_uo(qs):
    """Devolve `(linhas, total)` — `linhas` é a lista de dicts por UO
    (apenas UOs com >= 1 processo no queryset filtrado, nunca as UOs do
    catálogo sem processo), ordenada por nome; `total` é o mesmo formato de
    dict agregando toda a `qs`. 1 lookup de `Tipo` + 1 `.annotate()`
    combinado — nunca uma query por UO (T-172-03)."""
    ids_tipo = ids_tipo_recorte()
    q_nova = _q_tipo(ids_tipo.get("nova contratacao"))
    q_renovacao = _q_tipo(ids_tipo.get("renovacao"))
    q_vigente = _q_tipo(ids_tipo.get("vigente"))
    q_elegivel = q_nova | q_renovacao

    agregados_uo = list(
        qs.values("unidade_organizacional_id", "unidade_organizacional__nome")
        .order_by(Collate(F("unidade_organizacional__nome"), "ptbr"))
        .annotate(
            total_previsto=Count("id"),
            ativos=Count("id", filter=Q(estado=Estado.ATIVO)),
            nova=Count("id", filter=Q(estado=Estado.ATIVO) & q_nova),
            renovacao=Count("id", filter=Q(estado=Estado.ATIVO) & q_renovacao),
            vigente=Count("id", filter=Q(estado=Estado.ATIVO) & q_vigente),
            concluido=Count(
                "id",
                filter=Q(estado=Estado.ATIVO, situacao_efetiva=Situacao.CONCLUIDO),
            ),
            # "Concluído (meta)": CONCLUIDO restrito ao
            # universo elegível (Nova|Renovação), o mesmo das outras 3
            # colunas do bloco META — assim a conta fecha por construção
            # (`& q_elegivel` é mais estrito que o antigo `& ~q_vigente`,
            # que deixaria entrar processo sem tipo). Mesma consulta
            # agregada única (T-172-03 preservado).
            concluido_meta=Count(
                "id",
                filter=(
                    Q(estado=Estado.ATIVO, situacao_efetiva=Situacao.CONCLUIDO)
                    & q_elegivel
                ),
            ),
            em_tramitacao=Count(
                "id",
                filter=(
                    Q(estado=Estado.ATIVO, situacao_efetiva=Situacao.EM_TRAMITACAO)
                    & q_elegivel
                ),
            ),
            # Prazos CONSOLIDADOS (NC+RN numa annotation
            # só, por tipo de prazo); o recorte por tipo saiu da tabela e
            # vive apenas no drill-down (filtros de /tabela).
            no_prazo=Count(
                "id",
                filter=(
                    Q(estado=Estado.ATIVO, situacao_efetiva=Situacao.NO_PRAZO)
                    & q_elegivel
                ),
            ),
            fora_prazo=Count(
                "id",
                filter=(
                    Q(estado=Estado.ATIVO, situacao_efetiva=Situacao.ATRASADO)
                    & q_elegivel
                ),
            ),
            # Partição de SITUAÇÃO DOS ATIVOS,
            # IRRESTRITA por tipo (mesmo padrão de `concluido`, acima, só
            # trocando `situacao_efetiva`). Ao lado de `concluido`,
            # particiona A por construção (Situacao tem exatamente 4
            # valores): concluido + em_tramitacao_ativos + no_prazo_ativos +
            # atrasado_ativos == ativos. MESMA consulta agregada única
            # (T-172-03 preservado, nenhuma query nova).
            em_tramitacao_ativos=Count(
                "id",
                filter=Q(
                    estado=Estado.ATIVO, situacao_efetiva=Situacao.EM_TRAMITACAO
                ),
            ),
            no_prazo_ativos=Count(
                "id",
                filter=Q(estado=Estado.ATIVO, situacao_efetiva=Situacao.NO_PRAZO),
            ),
            atrasado_ativos=Count(
                "id",
                filter=Q(estado=Estado.ATIVO, situacao_efetiva=Situacao.ATRASADO),
            ),
        )
    )

    # Denominador de "% no PCA": soma dos totais previstos de TODAS
    # as UOs do escopo — nunca um número fixo. Somado em Python sobre a
    # lista já materializada (zero query nova).
    total_previsto_geral = sum(linha["total_previsto"] for linha in agregados_uo)

    linhas = [
        _linha(
            linha["unidade_organizacional_id"],
            linha["unidade_organizacional__nome"],
            linha,
            total_previsto_geral,
        )
        for linha in agregados_uo
    ]

    totais_absolutos = {
        chave: sum(linha[chave] for linha in agregados_uo)
        for chave in _CHAVES_ABSOLUTAS
    }
    total = _linha(None, "TOTAL", totais_absolutos, total_previsto_geral)

    return linhas, total
