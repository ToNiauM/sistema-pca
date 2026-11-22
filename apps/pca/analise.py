"""Fase 24 — tela "Análise": agregações para os
gráficos que vivem fora da dashboard, porque a dashboard já está no limite
de densidade. `calcular_grafico_mensal` (deste
plano) é o primeiro: distribuição mensal por dimensão categórica, com
seletor de medida (quantidade/valor previsto/valor contratado), seletor de
dimensão (todos os eixos que o painel de filtros já conhece) e alternância
empilhado/agrupado.

Mesmo contrato dos outros módulos de agregação do app (`apps.pca.kpis`,
`apps.pca.resumo_uo`): consome o queryset JÁ filtrado (saída de
`apps.pca.filtros.queryset_filtrado`), nunca reimplementa
`situacao_efetiva` (lê a annotation de `ProcessoQuerySet.para_listagem()`),
e devolve dados prontos para o template servir via `json_script` — nenhuma
regra de negócio no template.
"""

from calendar import monthrange
from datetime import date
from decimal import Decimal

from django.db.models import Count, Sum
from django.db.models.functions import ExtractMonth, ExtractYear
from django.urls import reverse
from django.utils.timezone import localdate

from apps.catalogo.models import Tipo
from apps.pca.filtros import (
    MESES,
    NOMES_MES,
    SENTINEL_NAO_CLASSIFICADO,
    querystring_filtros,
)
from apps.pca.kpis import condicao_proximo_do_prazo
from apps.pca.models import Estado, Situacao
from core.db import quantizar_soma

# Rótulo humano de cada uma das 7 dimensões — a MESMA lista que o painel de
# filtros conhece (`apps.pca.filtros.opcoes_filtros`/`_filtros.html`).
ROTULOS_DIMENSAO = {
    "uo": "UO",
    "modalidade": "Modalidade",
    "categoria": "Categoria",
    "prioridade": "Prioridade",
    "tipo": "Tipo",
    "estado": "Estado",
    "situacao": "Situação",
}

# Para cada dimensão: (campo de nome para o GROUP BY, campo de id
# companheiro — None quando a dimensão não é uma FK, chave de
# `querystring_filtros`, se a chave é multivalor — `CHAVES_MULTIVALOR` de
# filtros.py). `uo`/`categoria`/`tipo` são FKs obrigatórias (nunca nulas);
# `modalidade`/`prioridade` (grau_prioridade) são FKs opcionais;
# `estado`/`situacao` são campos de choices diretos, sem id próprio.
_CONFIG_DIMENSAO = {
    "uo": ("unidade_organizacional__nome", "unidade_organizacional_id", "uo", True),
    "modalidade": ("modalidade__nome", "modalidade_id", "modalidade", False),
    "categoria": ("categoria__nome", "categoria_id", "categoria", True),
    "prioridade": ("grau_prioridade__nome", "grau_prioridade_id", "prioridade", True),
    "tipo": ("tipo__nome", "tipo_id", "tipo", True),
    "estado": ("estado", None, "estado", True),
    "situacao": ("situacao_efetiva", None, "situacao", True),
}

_ROTULO_ESTADO = dict(Estado.choices)
_ROTULO_SITUACAO = dict(Situacao.choices)


def _rotulo_do_grupo(dimensao, nome_bruto, valor_bruto):
    """Rótulo humano de UM grupo (uma série) dentro de uma dimensão.
    `estado`/`situacao` traduzem o valor cru pelo mapa de `choices`
    (`nome_bruto` já É o valor cru para essas duas, sem JOIN de nome);
    as demais leem o `nome` da FK, com "Não informado" para o grupo nulo
    (só `modalidade`/`prioridade` podem ser nulas — `uo`/`categoria`/`tipo`
    são FKs obrigatórias no model)."""
    if dimensao == "estado":
        return _ROTULO_ESTADO.get(valor_bruto, str(valor_bruto))
    if dimensao == "situacao":
        return _ROTULO_SITUACAO.get(valor_bruto, str(valor_bruto))
    if nome_bruto is None:
        # Prioridade tem sentinela própria no filtro ("não classificado");
        # o rótulo aqui segue o MESMO texto que `tags_ativas` já usa para
        # ela, para não introduzir um segundo nome para o mesmo conceito.
        return "Não classificado" if dimensao == "prioridade" else "Não informado"
    return nome_bruto


def _querystring_do_ponto(get, chave_filtro, multivalor, valor_bruto, numero_mes):
    """Querystring de UM ponto (mês × grupo): sempre carrega `mes=`; a
    chave da própria dimensão só entra quando o filtro sabe isolar aquele
    valor — `prioridade` tem sentinela para o grupo nulo
    (`SENTINEL_NAO_CLASSIFICADO`), mas `categoria`/`tipo`/`modalidade`
    nulos não têm equivalente em `apps.pca.filtros` (o filtro genuinamente
    não sabe isolar "categoria vazia"): nesses casos o ponto existe com
    rótulo "Não informado", mas a querystring carrega só o mês."""
    overrides = {"mes": numero_mes}
    if valor_bruto is None:
        if chave_filtro == "prioridade":
            overrides["prioridade"] = [SENTINEL_NAO_CLASSIFICADO]
        # demais dimensões nulas: sem chave própria, só `mes=` — limitação
        # documentada acima.
    elif multivalor:
        overrides[chave_filtro] = [valor_bruto]
    else:
        overrides[chave_filtro] = valor_bruto
    return querystring_filtros(get, **overrides)


def calcular_grafico_mensal(qs, get):
    """Devolve um dict com EXATAMENTE as 7 chaves de dimensão (`uo`,
    `modalidade`, `categoria`, `prioridade`, `tipo`, `estado`, `situacao`).
    Cada valor é uma lista de séries (uma por valor distinto da dimensão,
    ordenada por nome); cada série tem `"nome"` e `"pontos"` com 12 entradas
    (mês 1 a 12, zero quando o grupo não tem processo naquele mês).

    1 única consulta `.values().annotate()` por dimensão — 7 dimensões, 7
    queries fixas, nunca uma consulta por processo/mês/grupo (mesmo
    orçamento de `apps.pca.resumo_uo.calcular_resumo_uo`/
    `apps.pca.kpis.calcular_blocos_kpi`). Processos sem `mes_previsto`
    ficam FORA do gráfico (mesma regra de `mes_confronto`/
    `processos_sem_mes` em `dashboard_view`) — nunca perdidos nem
    duplicados: a soma de `quantidade` de todos os pontos de todas as
    séries de UMA dimensão, mais os processos sem mês, bate com
    `qs.count()`."""
    qs_com_mes = qs.exclude(mes_previsto__isnull=True)
    resultado = {}
    for dimensao, (campo_nome, campo_id, chave_filtro, multivalor) in _CONFIG_DIMENSAO.items():
        campos_values = ["mes_previsto", campo_nome]
        if campo_id:
            campos_values.append(campo_id)
        linhas = (
            qs_com_mes.values(*campos_values)
            .order_by()
            .annotate(
                quantidade=Count("id"),
                valor_previsto=Sum("valor_estimado"),
                valor_contratado=Sum("valor_contratado"),
            )
        )

        # Agrupa as linhas (mês × grupo) por grupo — chave_grupo é o id da
        # FK quando existe (nunca o nome, que poderia colidir entre
        # catálogos distintos) ou o próprio valor cru para estado/situacao.
        grupos = {}
        for linha in linhas:
            valor_bruto = linha[campo_id] if campo_id else linha[campo_nome]
            chave_grupo = valor_bruto
            grupo = grupos.setdefault(
                chave_grupo,
                {
                    "nome": _rotulo_do_grupo(dimensao, linha[campo_nome], valor_bruto),
                    "valor_bruto": valor_bruto,
                    "por_mes": {},
                },
            )
            grupo["por_mes"][linha["mes_previsto"]] = linha

        series = []
        for grupo in grupos.values():
            pontos = []
            for numero_mes in MESES:
                linha = grupo["por_mes"].get(numero_mes)
                pontos.append(
                    {
                        "mes": numero_mes,
                        "quantidade": linha["quantidade"] if linha else 0,
                        "valor_previsto": str(
                            quantizar_soma(linha["valor_previsto"] if linha else None)
                            or Decimal("0")
                        ),
                        "valor_contratado": str(
                            quantizar_soma(linha["valor_contratado"] if linha else None)
                            or Decimal("0")
                        ),
                        "querystring": _querystring_do_ponto(
                            get, chave_filtro, multivalor, grupo["valor_bruto"], numero_mes
                        ),
                    }
                )
            series.append({"nome": grupo["nome"], "pontos": pontos})
        series.sort(key=lambda serie: serie["nome"])
        resultado[dimensao] = series

    return resultado


# Rótulo curto (3 letras, minúsculo) de cada mês — MESMO texto de
# `NOMES_MES`, só truncado; as 12 iniciais em português são distintas entre
# si (Jan/Fev/Mar/Abr/Mai/Jun/Jul/Ago/Set/Out/Nov/Dez), sem colisão.
_NOMES_MES_ABREV = {mes: nome[:3].lower() for mes, nome in NOMES_MES.items()}


def calcular_grafico_vencimento_contratos(qs, get):
    """Fase 24 — contagem de contratos vigentes por mês
    de `vigencia_fim`, 12 meses a partir do mês corrente (âncora
    `localdate()`, NUNCA `now()`/`today()` — Pitfall 11). Só conta
    `Estado.ATIVO` com `tipo` "vigente" (mesma resolução por
    `nome_normalizado` já usada em `dashboard_view` para `id_tipo_vigente`
    — nunca `tipo__nome_normalizado=` dentro de `.filter()`).

    Devolve `{"pontos": [...], "sem_vigencia_fim": N}` — 12 dicts
    (`rotulo`, `ano`, `mes`, `quantidade`, `querystring`) e a contagem de
    vigentes sem `vigencia_fim` (ressalva no template, só quando > 0).
    Uma única consulta agregada (`.values("ano", "mes").annotate(Count)`),
    nunca uma consulta por mês/ponto.

    A `querystring` de cada ponto carrega `tipo=<id vigente>` e
    `estado=ativo` além do intervalo de `vigencia_fim` — sem essas duas
    chaves, `/tabela` mostraria QUALQUER processo com vencimento naquele
    mês (cancelados, outros tipos), divergindo da contagem do ponto (que
    só conta vigentes ativos). Achado real (ver SUMMARY): a base
    real já tem vigentes ativos com `vigencia_fim` cadastrado — sem o
    escopo por tipo/estado no link, a coerência exigida pelo `<behavior>`
    do plano quebraria com dados reais, não só numa fixture adversarial."""
    id_tipo_vigente = (
        Tipo.objects.filter(nome_normalizado="vigente")
        .values_list("id", flat=True)
        .first()
    )
    qs_vigentes = qs.filter(estado=Estado.ATIVO, tipo_id=id_tipo_vigente)

    contagens = {
        (linha["ano"], linha["mes"]): linha["quantidade"]
        for linha in qs_vigentes.exclude(vigencia_fim__isnull=True)
        .annotate(
            ano=ExtractYear("vigencia_fim"), mes=ExtractMonth("vigencia_fim")
        )
        .values("ano", "mes")
        .order_by()
        .annotate(quantidade=Count("id"))
    }
    sem_vigencia_fim = qs_vigentes.filter(vigencia_fim__isnull=True).count()

    overrides_escopo = {"estado": [Estado.ATIVO]}
    if id_tipo_vigente is not None:
        overrides_escopo["tipo"] = [id_tipo_vigente]

    hoje = localdate()
    ano, mes = hoje.year, hoje.month
    pontos = []
    for _ in range(12):
        primeiro_dia = date(ano, mes, 1)
        ultimo_dia = date(ano, mes, monthrange(ano, mes)[1])
        pontos.append(
            {
                "rotulo": f"{_NOMES_MES_ABREV[mes]}/{ano}",
                "ano": ano,
                "mes": mes,
                "quantidade": contagens.get((ano, mes), 0),
                "querystring": querystring_filtros(
                    get,
                    vigencia_fim_de=primeiro_dia.isoformat(),
                    vigencia_fim_ate=ultimo_dia.isoformat(),
                    **overrides_escopo,
                ),
            }
        )
        mes += 1
        if mes > 12:
            mes = 1
            ano += 1

    return {"pontos": pontos, "sem_vigencia_fim": sem_vigencia_fim}


def _ids_elegiveis_nc_rn():
    """Fase 28 — os ids de Nova Contratação/Renovação, mesma
    resolução por `nome_normalizado` que `apps.pca.kpis.
    calcular_blocos_kpi` já faz (nunca `tipo__nome_normalizado=` dentro de
    `.filter()`): 1 lookup, reaproveitado pelas duas condições desta
    função (elegíveis e vencidos)."""
    return list(
        Tipo.objects.filter(
            nome_normalizado__in=("nova contratacao", "renovacao")
        ).values_list("id", flat=True)
    )


def calcular_proximos_vencimentos(qs, get, *, limite=10):
    """Fase 28 — "Próximos vencimentos — prazos
    dos processos": MESMA condição de proximidade do KPI
    (`apps.pca.kpis.condicao_proximo_do_prazo`), SEM janela de dias (lista
    ordenada por prazo, não contagem de um horizonte fixo) — mais os dois
    filtros próprios da tabela operacional: não recebido no Gelic e não
    concluído (a função NUNCA reescreve `situacao_efetiva`, só lê — uma
    situação manual "Atrasado" com `prazo_efetivo` futuro continua
    aparecendo com essa situação exibida).

    Devolve `(processos_pagina, total_no_recorte, total_vencidos,
    url_vencidos)`: `processos_pagina` já limitado/ordenado por
    `prazo_efetivo`/`item_pca`/`id`; `total_no_recorte` é a contagem cheia
    (para o "10/20" saber se há mais do que a página mostra);
    `total_vencidos`/`url_vencidos` usam a MESMA elegibilidade (ativos
    NC|RN, não recebidos, não concluídos) mas com `prazo_efetivo` no
    PASSADO — a mesma condição que a annotation `atrasado` de
    `ProcessoQuerySet.para_listagem()` já expressa,
    então o filtro real de `/tabela` é só `atrasado=1` + `estado`/`tipo`
    ("vencidos: contagem + acesso ao recorte, fora das 10/20
    primeiras"). Nenhuma consulta por linha: `qs` já vem anotado por
    `para_listagem()` (2 `.count()` + 1 `list()` fatiado, orçamento fixo
    independente de `limite`)."""
    hoje = localdate()
    ids_elegiveis = _ids_elegiveis_nc_rn()

    # `exigir_no_prazo=False` — não usa `situacao_efetiva` como
    # critério de entrada (só exclui CONCLUIDO, abaixo): um processo com
    # situação manual "Atrasado" e `prazo_efetivo` futuro continua
    # aparecendo, com essa situação exibida.
    base = (
        qs.filter(
            condicao_proximo_do_prazo(
                hoje, ids_elegiveis, dias=None, exigir_no_prazo=False
            )
        )
        .filter(data_recebimento_gelic__isnull=True)
        .exclude(situacao_efetiva=Situacao.CONCLUIDO)
    )
    total_no_recorte = base.count()
    processos_pagina = list(
        base.order_by("prazo_efetivo", "item_pca", "id")[:limite]
    )

    vencidos = qs.filter(
        estado=Estado.ATIVO,
        tipo_id__in=ids_elegiveis,
        atrasado=True,
    )
    total_vencidos = vencidos.count()
    url_vencidos = (
        f"{reverse('pca:tabela')}?"
        f"{querystring_filtros(get, estado=[Estado.ATIVO.value], tipo=ids_elegiveis, atrasado='1')}"
    )

    return processos_pagina, total_no_recorte, total_vencidos, url_vencidos
