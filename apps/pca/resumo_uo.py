"""Tabela resumo por UO, semântica de foto atual, calculada ao vivo do
banco: sem série mensal, sem snapshots, sem inclusões/exclusões do mês.

Módulo único de agregação: calcular_resumo_uo(qs) recebe o queryset já
filtrado, roda 1 única consulta .values().annotate() (mais 1 lookup de
Tipo) e devolve (linhas, total), nunca uma consulta por UO.

Nunca reimplementa situacao_efetiva/estado/_percentual: lê a annotation de
ProcessoQuerySet.para_listagem() e importa _percentual literalmente de
apps.pca.kpis — os números daqui nunca divergem dos de /dashboard/tabela
para o mesmo filtro.

Mapeamento fino coluna -> regra, 4 blocos além da coluna UO:

Bloco fixo (universo da UO):
- "Total previsto" = todos os processos da UO no exercício resolvido,
  Estado.ATIVO + Estado.CANCELADO; "% no PCA" = total_previsto da UO /
  soma do total_previsto de todas as UOs do escopo.
- "Cancelados" = Estado.CANCELADO no escopo, calculado em Python como
  total_previsto - ativos; % = /total_previsto da UO.
- "Ativos" = Estado.ATIVO; % = /total_previsto da UO. Coluna-síntese
  (Ativos = Meta + Vigentes), destacada na tela e no XLSX.

Bloco por tipo (decomposição dos Ativos):
- "Nova Contratação" / "Renovação" / "Vigente" = decomposição por tipo,
  restrita a Estado.ATIVO; % = /ativos da UO.

Bloco meta (o número que a equipe persegue na reunião mensal):
- "Meta" = nova + renovacao = ativos - vigentes (derivada em Python em
  _linha); % = /ativos da UO. Coluna-síntese destacada.
- As 4 colunas seguintes decompõem a Meta e fecham a conta: Situacao tem
  exatamente 4 valores, logo concluido_meta + em_tramitacao + no_prazo +
  fora_prazo == meta por construção. Percentuais todos sobre a meta da
  UO, somam 100%:
  - "Concluído (meta)" = situacao_efetiva=CONCLUIDO e Estado.ATIVO e
    tipo in (Nova, Renovação); % = /meta.
  - "Em tramitação" = situacao_efetiva=EM_TRAMITACAO, mesmo universo;
    % = /meta.
  - "No prazo" = situacao_efetiva=NO_PRAZO, mesmo universo, NC+RN
    consolidados numa coluna só; o recorte por tipo vive só no
    drill-down; % = /meta.
  - "Fora do prazo" = situacao_efetiva=ATRASADO, mesmo universo,
    consolidado; % = /meta.

Bloco análise:
- "Concluído c/ Vigentes" = situacao_efetiva=CONCLUIDO sobre Estado.ATIVO
  (Nova + Renovação + Vigente); % = /ativos da UO. Vigentes contam para
  análise, nunca para o cumprimento do PCA do exercício corrente — por
  isso ficam fora da Meta e do bloco meta inteiro.

Grupo situação dos ativos (partição irrestrita por tipo de A, ao lado da
partição restrita a NC/RN do bloco meta acima):
- "Concluídos" = concluido; "Em tramitação"/"No prazo"/"Atrasados" =
  em_tramitacao_ativos/no_prazo_ativos/atrasado_ativos, mesmo filtro de
  concluido trocando só situacao_efetiva, sem restrição de tipo. Situacao
  tem exatamente 4 valores, logo concluido + em_tramitacao_ativos +
  no_prazo_ativos + atrasado_ativos == ativos fecha por construção.
  Percentuais todos /ativos.
- "Outros tipos" = ativos - (nova + renovacao + vigente), derivado em
  Python em _linha; torna a soma "Por tipo" honesta quando existe
  processo ATIVO de um tipo além de NC/RN/VG. % = /ativos.

A linha TOTAL soma os números absolutos de todas as UOs e recalcula os
percentuais sobre esses totais, nunca a média dos percentuais de linha."""

from django.db.models import Count, Q

from apps.catalogo.models import Tipo
from apps.pca.kpis import _percentual
from apps.pca.models import Estado, Situacao

# chaves somadas em Python para montar a linha TOTAL: números absolutos
# por UO, nunca os percentuais
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
    # partição de situação dos ativos, irrestrita por tipo; estas 3 são
    # annotations do ORM, diferente de outros_tipos, que é derivada em
    # Python dentro de _linha
    "em_tramitacao_ativos",
    "no_prazo_ativos",
    "atrasado_ativos",
)


def _q_tipo(id_tipo):
    """None-safe: um id_tipo ausente do catálogo nunca vira
    Q(tipo_id=None). Devolve uma condição que nunca casa com nenhuma linha."""
    return Q(tipo_id=id_tipo) if id_tipo is not None else Q(pk__in=[])


def _linha(uo_id, uo_nome, dados, total_previsto_geral):
    """Monta uma linha (UO ou TOTAL) a partir dos números absolutos já
    agregados, calculando os percentuais zero-safe via _percentual.
    cancelados/ativos/meta são derivados em Python, zero query nova; meta
    não entra em _CHAVES_ABSOLUTAS porque a meta do TOTAL sai correta da
    soma de nova+renovacao."""
    nova = dados["nova"]
    renovacao = dados["renovacao"]
    # a Meta do PCA da UO: nova + renovacao = ativos - vigentes. As 4
    # chaves seguintes do bloco META a decompõem e fecham a conta
    meta = nova + renovacao
    cancelados = dados["total_previsto"] - dados["ativos"]
    # alguma UO pode ter processo ATIVO de um tipo além de NC/RN/VG, hoje
    # invisível na decomposição "Por tipo". Derivado em Python, zero query nova
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
        # bloco análise — contagem inclui Vigentes; % sobre ativos
        "concluido": dados["concluido"],
        "percentual_concluido": _percentual(dados["concluido"], dados["ativos"]),
        # grupo "Situação dos ativos": partição irrestrita por tipo sobre
        # A; concluido + em_tramitacao_ativos + no_prazo_ativos +
        # atrasado_ativos == ativos fecha por construção
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
    """Extraído de calcular_resumo_uo para que a view de drill-down
    reaproveite os mesmos ids de Tipo, em vez de consultar Tipo de novo ou
    hardcodar nome."""
    return dict(
        Tipo.objects.filter(
            nome_normalizado__in=("nova contratacao", "renovacao", "vigente")
        ).values_list("nome_normalizado", "id")
    )


def calcular_resumo_uo(qs):
    """Devolve (linhas, total): linhas é a lista de dicts por UO (apenas
    UOs com >= 1 processo no queryset filtrado), ordenada por nome; total
    é o mesmo formato agregando toda a qs. 1 lookup de Tipo + 1
    .annotate() combinado, nunca uma query por UO."""
    ids_tipo = ids_tipo_recorte()
    q_nova = _q_tipo(ids_tipo.get("nova contratacao"))
    q_renovacao = _q_tipo(ids_tipo.get("renovacao"))
    q_vigente = _q_tipo(ids_tipo.get("vigente"))
    q_elegivel = q_nova | q_renovacao

    agregados_uo = list(
        qs.values("unidade_organizacional_id", "unidade_organizacional__nome")
        .order_by("unidade_organizacional__nome")
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
            # "Concluído (meta)": CONCLUIDO restrito ao universo elegível
            # (Nova|Renovação), o mesmo das outras 3 colunas do bloco META
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
            # prazos consolidados (NC+RN numa annotation só); o recorte
            # por tipo vive apenas no drill-down
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
            # partição de situação dos ativos, irrestrita por tipo (mesmo
            # padrão de concluido, só trocando situacao_efetiva)
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

    # denominador de "% no PCA": soma dos totais previstos de todas as
    # UOs do escopo. Somado em Python sobre a lista já materializada
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
