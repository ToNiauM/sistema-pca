"""Fase 26 (..17) — ponte entre `apps.pca` (dados) e
`core.graficos` (opções ECharts prontas, tema dsgov). Cada função aqui só
agrega com o ORM e chama a função correspondente de `core.graficos` — nunca
reimplementa cor/estilo/tipo de gráfico (`graficos.md`, regra 2). `kpis.py`/
`regras_situacao.py`/`querysets.py` continuam intocados (hash idêntico);
este módulo só CONSOME o que eles já expõem.

`calcular_status_distribuicao`/`calcular_por_unidade`/
`calcular_previsto_entregue`/`calcular_pendencias` são compartilhados entre
`core/views.py::inicio` (dashboard) e `apps/pca/views.py::
analise_view` (relatório) — cada um consome os MESMOS números,
nunca uma segunda query concorrente para o mesmo dado (Pitfall 16).
"""

from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.urls import reverse

from apps.catalogo.models import Tipo
from apps.pca.analise import calcular_grafico_vencimento_contratos
from apps.pca.filtros import MESES, NOMES_MES, querystring_filtros
from apps.pca.kpis import _percentual
from apps.pca.models import Estado, Situacao
from core import graficos
from core.db import quantizar_soma
from core.templatetags.dsgov import moeda, numero, percentual
from core.templatetags.formatos import moeda_curta

# Mesma ordem/rótulos de `apps/pca/views.py::ORDEM_ROSCA` (Fase 17) —
# reproduzida aqui porque este módulo sobrevive depois que `dashboard_view`
# (dono original da constante) sai deste plano.
# Mesma ordem dos KPIs do Início (Cancelados, Concluídos,
# Em tramitação, No prazo, Atrasados), pedida pela diretora em 15/10/2026.
ORDEM_STATUS = (
    ("estado", Estado.CANCELADO, "Cancelado"),
    ("situacao", Situacao.CONCLUIDO, "Concluído"),
    ("situacao", Situacao.EM_TRAMITACAO, "Em tramitação"),
    ("situacao", Situacao.NO_PRAZO, "No prazo"),
    ("situacao", Situacao.ATRASADO, "Atrasado"),
)

# graficos.md — "só nesse caso a view inclui itemStyle via CORES_STATUS de
# core/graficos.py; é a única exceção de cor". Chaves = rotulo de
# ORDEM_STATUS; valores = chaves de `core.graficos.CORES_STATUS`.
# achado de revisão) — "No prazo" e
# "Em tramitação" caíam os dois em "info" (MESMA cor); agora usam as
# chaves DEDICADAS de `CORES_STATUS` ("pendente" amarelo, "andamento"
# azul — nunca compartilham cor). MESMO destino semântico de
# `apps.pca.templatetags.pca_listagem.CLASSE_SITUACAO_EFETIVA` (a outra
# metade do mapa projeto-inteiro, chaveada pelo valor cru de
# `situacao_efetiva` em vez do rótulo — usada pelas tags `{% tag_status %}`
# em vez dos gráficos).
MAPA_SITUACAO_STATUS = {
    "Concluído": "concluido",
    "Atrasado": "atrasado",
    "Em tramitação": "andamento",
    "No prazo": "pendente",
    "Cancelado": "cancelado",
}


def _ids_elegiveis():
    """Mesmo universo restrito de `apps.pca.kpis.calcular_blocos_kpi`
    (Nova Contratação + Renovação) — resolvido de novo aqui porque
    `kpis.py` não expõe os ids (nunca duplicar a REGRA, só a
    resolução do catálogo, idêntica à já usada em `dashboard_view`/
    `resumo_uo.py` para `id_tipo_vigente`)."""
    ids_tipo = dict(
        Tipo.objects.filter(
            nome_normalizado__in=("nova contratacao", "renovacao")
        ).values_list("nome_normalizado", "id")
    )
    return [
        i
        for i in (ids_tipo.get("nova contratacao"), ids_tipo.get("renovacao"))
        if i is not None
    ]


def calcular_status_distribuicao(qs, get):
    """5 combinações MECE de estado/situação (Cancelado + as 4 situações
    de ATIVOS) — total/soma/querystring por fatia. 1 única consulta
    agrupando por `estado`/`situacao_efetiva` (nunca uma consulta por
    fatia)."""
    linhas_agregadas = list(
        qs.values("estado", "situacao_efetiva")
        .order_by()
        .annotate(total=Count("id"), soma=Sum("valor_estimado"))
    )
    for linha_agregada in linhas_agregadas:
        # quantizar_soma corrige o ruido de ponto flutuante do SUM() do SQLite.
        linha_agregada["soma"] = quantizar_soma(linha_agregada["soma"])
    por_estado_situacao = {
        (linha["estado"], linha["situacao_efetiva"]): linha
        for linha in linhas_agregadas
    }
    resultado = []
    for eixo, valor, rotulo in ORDEM_STATUS:
        if eixo == "estado":
            linhas = [
                linha
                for (estado_linha, _situacao_linha), linha in por_estado_situacao.items()
                if estado_linha == valor
            ]
            querystring = querystring_filtros(get, estado=[valor.value])
        else:
            linhas = [
                linha
                for (estado_linha, situacao_linha), linha in por_estado_situacao.items()
                if estado_linha == Estado.ATIVO and situacao_linha == valor
            ]
            querystring = querystring_filtros(
                get, estado=[Estado.ATIVO.value], situacao=[valor.value]
            )
        total = sum(linha["total"] for linha in linhas)
        soma = sum((linha["soma"] or 0) for linha in linhas)
        resultado.append(
            {
                "rotulo": rotulo,
                "total": total,
                "soma": soma,
                "querystring": querystring,
            }
        )
    return resultado


def _urls_por_rotulo(linhas):
    return {
        linha["rotulo"]: f"{reverse('pca:tabela')}?{linha['querystring']}"
        for linha in linhas
        if linha.get("querystring")
    }


def opcoes_situacao(status_distribuicao, legenda_total="processos"):
    """Versão COMPLETA (5 linhas, incl. Cancelado) — Análises (`pca:analise`)
    e, desde, também o Início (`legenda_total="previstos"`).
    Fatias com valor+% (`rotulos=True`) e total geral no
    centro do anel (`urls`/`total` — regra 4/9 de `graficos.md`)."""
    fatias = [(linha["rotulo"], linha["total"]) for linha in status_distribuicao]
    status_map = {
        linha["rotulo"]: MAPA_SITUACAO_STATUS[linha["rotulo"]]
        for linha in status_distribuicao
        if linha["rotulo"] in MAPA_SITUACAO_STATUS
    }
    total_geral = sum(linha["total"] for linha in status_distribuicao)
    return graficos.rosca(
        fatias,
        status=status_map,
        urls=_urls_por_rotulo(status_distribuicao),
        rotulo_externo=True,
        total=(numero(total_geral), legenda_total),
    )


def resumo_situacao(status_distribuicao):
    partes = ", ".join(
        f"{linha['total']} {linha['rotulo'].lower()}" for linha in status_distribuicao
    )
    return f"Processos por situação: {partes}."


# Plural de cada fatia no texto alternativo da rosca do Início.
_PLURAL_STATUS = {
    "Cancelado": "cancelados",
    "Concluído": "concluídos",
    "Em tramitação": "em tramitação",
    "No prazo": "no prazo",
    "Atrasado": "atrasados",
}


def resumo_situacao_previstos(status_distribuicao):
    """Texto alternativo da rosca do Início, no mesmo recorte
    dos 7 KPIs: previstos = cancelados + ativos; ativos = as 4 situações."""
    ativas = [linha for linha in status_distribuicao if linha["rotulo"] != "Cancelado"]
    cancelados = sum(linha["total"] for linha in status_distribuicao if linha["rotulo"] == "Cancelado")
    total_ativos = sum(linha["total"] for linha in ativas)
    partes = ", ".join(f"{linha['total']} {_PLURAL_STATUS[linha['rotulo']]}" for linha in ativas)
    return (
        f"Processos previstos por situação: {total_ativos + cancelados} no total — "
        f"{cancelados} cancelados e {total_ativos} ativos ({partes})."
    )


def tabela_situacao_previstos(status_distribuicao):
    """(antes `tabela_situacao_ativos`) — "Ver dados"
    da rosca do Início, agora com TODOS os previstos: as 4 situações dos ativos,
    o subtotal dos ativos, os cancelados e o total. `percentual` é zero-safe
    (`_percentual` devolve `None` com universo vazio e o filtro traduz para "—")."""
    urls = _urls_por_rotulo(status_distribuicao)
    total_previstos = sum(linha["total"] for linha in status_distribuicao)
    soma_previstos = sum(linha["soma"] for linha in status_distribuicao)
    ativas = [linha for linha in status_distribuicao if linha["rotulo"] != "Cancelado"]
    canceladas = [linha for linha in status_distribuicao if linha["rotulo"] == "Cancelado"]

    def linha_tabela(rotulo, total, soma, url=None):
        return [
            {"valor": rotulo, "url": url} if url else rotulo,
            numero(total),
            percentual(_percentual(total, total_previstos)),
            moeda(soma),
        ]

    linhas = [linha_tabela(l["rotulo"], l["total"], l["soma"], urls.get(l["rotulo"])) for l in ativas]
    linhas.append(
        linha_tabela(
            "Ativos (subtotal)",
            sum(l["total"] for l in ativas),
            sum(l["soma"] for l in ativas),
        )
    )
    linhas += [linha_tabela(l["rotulo"], l["total"], l["soma"], urls.get(l["rotulo"])) for l in canceladas]
    linhas.append(linha_tabela("Total", total_previstos, soma_previstos))
    return graficos.tabela_dados(
        ["Situação", "Quantidade", "Percentual dos previstos", "Valor estimado"], linhas
    )


def calcular_totais_financeiros(qs):
    """Fase 28 — 2 barras do Início: Σ
    `valor_estimado` e Σ `valor_contratado` sobre o MESMO `qs` do
    exercício (sem filtro extra, inclui cancelados — mesma base que
    `analise_view` já soma para "Valor planejado"/"Valor contratado").
    UM `.aggregate()` só; `sem_contratado` conta processos com
    `valor_contratado` nulo — nunca tratado como zero na soma."""
    dados = qs.aggregate(
        estimado=Sum("valor_estimado"),
        contratado=Sum("valor_contratado"),
        sem_contratado=Count("id", filter=Q(valor_contratado__isnull=True)),
    )
    # quantizar_soma corrige o ruido de ponto flutuante do SUM() do SQLite.
    dados["estimado"] = quantizar_soma(dados["estimado"])
    dados["contratado"] = quantizar_soma(dados["contratado"])
    return dados


def opcoes_totais_financeiros(dados):
    """2 categorias, 1 série (`rotulos=True`, sem legenda
    redundante para 2 barras).

    Cada coluna na cor do cartão de valor da ficha
    (`graficos.CORES_VALOR`, padrão PNCP) e o rótulo abreviado pronto
    ("R$ 216,3 mi"), sem o eixo de valores: o número no topo já diz tudo."""
    opcoes = graficos.colunas(
        ["Valor previsto", "Valor contratado"],
        {"R$": [float(dados["estimado"] or 0), float(dados["contratado"] or 0)]},
        rotulos=True,
    )
    serie = opcoes["series"][0]
    serie["barMaxWidth"] = 96
    serie["data"] = [
        {
            "value": valor,
            "itemStyle": {"color": graficos.CORES_VALOR[chave]},
            "label": {"formatter": f"R$ {moeda_curta(dados[chave] or 0)}", "fontWeight": "bold"},
        }
        for chave, valor in zip(("estimado", "contratado"), serie["data"])
    ]
    opcoes["yAxis"] = {"type": "value", "show": False}
    return opcoes


def resumo_totais_financeiros(dados):
    return (
        f"Valor previsto x valor contratado: {moeda(dados['estimado'])} previstos, "
        f"{moeda(dados['contratado'])} contratados."
    )


def tabela_totais_financeiros(dados):
    """"Ver dados" das barras financeiras — mesmas 2 medidas do gráfico."""
    return graficos.tabela_dados(
        ["Medida", "Valor"],
        [
            ["Valor previsto", moeda(dados["estimado"])],
            ["Valor contratado", moeda(dados["contratado"])],
        ],
    )


def calcular_por_unidade(qs):
    """Ranking de unidades por volume — 18 UOs, rótulos longos (barras
    horizontais, `graficos.md` regra 4)."""
    linhas = list(
        qs.values("unidade_organizacional_id", "unidade_organizacional__nome")
        .order_by()
        .annotate(total=Count("id"), soma=Sum("valor_estimado"))
        .order_by("-total")
    )
    for linha in linhas:
        # quantizar_soma corrige o ruido de ponto flutuante do SUM() do SQLite.
        linha["soma"] = quantizar_soma(linha["soma"])
    return linhas


def tabela_por_unidade(qs, get):
    """`calcular_por_unidade` no contrato genérico
    `{"rotulo","total","soma","querystring"}` de `_analise_tabela_totais.html`
mesma agregação do gráfico 2, sem consulta extra."""
    return [
        {
            "rotulo": linha["unidade_organizacional__nome"],
            "total": linha["total"],
            "soma": linha["soma"] or 0,
            "querystring": querystring_filtros(
                get, uo=linha["unidade_organizacional_id"]
            ),
        }
        for linha in calcular_por_unidade(qs)
    ]


def opcoes_por_unidade_de(tabela_unidade):
    """Recebe a lista JÁ COMPUTADA por
    `tabela_por_unidade(qs, get)`; NUNCA chama `calcular_por_unidade` de
    novo (uma query só, reusada por dashboard e Análises).
    `Unidade.nome` já É a sigla da UO (Objective item 3 do plano) — o
    mesmo rótulo aparece no gráfico, no tooltip e na tabela companheira.
    `core.graficos.barras_horizontais` já mostra os 18 rótulos por
    completo (`yAxis.axisLabel.interval=0` incondicional)."""
    rotulos = [linha["rotulo"] for linha in tabela_unidade]
    valores = [linha["total"] for linha in tabela_unidade]
    urls = [
        f"{reverse('pca:tabela')}?{linha['querystring']}" for linha in tabela_unidade
    ]
    # achado de revisão) — `escala=True`
    # ativa o `visualMap`/`CORES_SEQUENCIAL` (mais escuro = mais processos),
    # regra 3/7 de `graficos.md`: barras cujo significado é intensidade por
    # VALOR (não status) usam a rampa monocromática, nunca uma cor fixa.
    return graficos.barras_horizontais(
        rotulos, valores, "Processos", escala=True, urls=urls
    )


def tabela_unidade_dados(tabela_unidade):
    """Tabela companheira ("Ver dados") do
    gráfico "Processos por unidade", a partir do MESMO `tabela_unidade` já
    computado por `tabela_por_unidade(qs, get)`."""
    url_tabela = reverse("pca:tabela")
    linhas = [
        [
            linha["rotulo"],
            {
                "valor": numero(linha["total"]),
                "url": f"{url_tabela}?{linha['querystring']}",
            },
        ]
        for linha in tabela_unidade
    ]
    return graficos.tabela_dados(["Unidade", "Processos"], linhas)


def resumo_por_unidade_de(tabela_unidade):
    if not tabela_unidade:
        return "Processos por unidade: nenhum processo no recorte atual."
    maior = tabela_unidade[0]
    return (
        f"Processos por unidade: {len(tabela_unidade)} unidades; "
        f"{maior['rotulo']} tem o maior volume, com {maior['total']} processos."
    )


def calcular_previsto_entregue(qs, get):
    """12 pontos (mês previsto 1-12): quantidade PREVISTA (todo processo
    com aquele mês) × ENTREGUE (ATIVO e já concluído, mesma definição de
    `situacao_efetiva` que `dashboard_view::mes_confronto` usava antes
    desta fase)."""
    brutos = {
        linha["mes_previsto"]: linha
        for linha in qs.exclude(mes_previsto__isnull=True)
        .values("mes_previsto")
        .order_by()
        .annotate(
            previsto=Count("id"),
            entregue=Count(
                "id",
                filter=Q(estado=Estado.ATIVO, situacao_efetiva=Situacao.CONCLUIDO),
            ),
        )
    }
    pontos = []
    for numero_mes in MESES:
        linha = brutos.get(numero_mes, {"previsto": 0, "entregue": 0})
        querystring_previsto = querystring_filtros(get, mes=numero_mes)
        pontos.append(
            {
                "mes": numero_mes,
                "rotulo": NOMES_MES[numero_mes],
                "previsto": linha["previsto"],
                "entregue": linha["entregue"],
                # Objective item 2 — "entregue" é ATIVO +
                # CONCLUÍDO dentro do mês PREVISTO (a MESMA definição do
                # `annotate` acima), nunca `recebido_de/ate` (mês de
                # recebimento no Gelic): usar essa segunda data produziria
                # uma contagem que não bate com o valor do ponto.
                "querystring_previsto": querystring_previsto,
                "querystring_entregue": querystring_filtros(
                    get,
                    mes=numero_mes,
                    estado=[Estado.ATIVO.value],
                    situacao=[Situacao.CONCLUIDO.value],
                ),
                # `apps/pca/templates/pca/analise.html` já linka a célula
                # "Mês" por `ponto.querystring` — alias de
                # `querystring_previsto`, mantido para não quebrar o
                # template existente.
                "querystring": querystring_previsto,
            }
        )
    return pontos


def opcoes_previsto_entregue(pontos):
    """12 meses abreviados (`_NOMES_MES_CURTOS`), rótulo
    de valor no topo das colunas, `url` de drill-down por série (Previsto
    usa o mês; Entregue usa a MESMA definição do ponto). recebe `pontos` JÁ COMPUTADO por
    `calcular_previsto_entregue(qs, get)`, chamado uma única vez pela view
antes desta quick, `opcoes_previsto_entregue`/
    `resumo_previsto_entregue` chamavam a função de agregação cada um por
    conta própria (2 consultas idênticas); agora, com a tabela companheira
    somando um 3º consumidor do mesmo dado, as três funções compartilham UM
    cálculo só."""
    categorias = [_NOMES_MES_CURTOS[ponto["mes"]] for ponto in pontos]
    url_tabela = reverse("pca:tabela")
    return graficos.colunas(
        categorias,
        {
            "Previsto": [ponto["previsto"] for ponto in pontos],
            "Entregue": [ponto["entregue"] for ponto in pontos],
        },
        urls={
            "Previsto": [
                f"{url_tabela}?{ponto['querystring_previsto']}" for ponto in pontos
            ],
            "Entregue": [
                f"{url_tabela}?{ponto['querystring_entregue']}" for ponto in pontos
            ],
        },
        rotulos=True,
    )


def resumo_previsto_entregue(pontos):
    total_previsto = sum(ponto["previsto"] for ponto in pontos)
    total_entregue = sum(ponto["entregue"] for ponto in pontos)
    return (
        f"Previsto × Entregue por mês: {total_previsto} processos previstos, "
        f"{total_entregue} entregues no exercício."
    )


def tabela_previsto_entregue(pontos):
    """Tabela companheira ("Ver dados")
    do card "Previsto × Entregue por mês", a partir do MESMO `pontos` já
    computado."""
    url_tabela = reverse("pca:tabela")
    linhas = [
        [
            ponto["rotulo"],
            {
                "valor": numero(ponto["previsto"]),
                "url": f"{url_tabela}?{ponto['querystring_previsto']}",
            },
            {
                "valor": numero(ponto["entregue"]),
                "url": f"{url_tabela}?{ponto['querystring_entregue']}",
            },
        ]
        for ponto in pontos
    ]
    return graficos.tabela_dados(["Mês", "Previsto", "Entregue"], linhas)


def opcoes_vencimento(dados):
    """Recebe o dict JÁ COMPUTADO por
    `apps.pca.analise.calcular_grafico_vencimento_contratos(qs, get)`
    (Análises reusa o mesmo dict para a tabela e o gráfico, nunca uma 2ª
    consulta). BRIEF item 2 — colunas, não linha, para este gráfico
    (ele sai do dashboard e migra inteiro para Análises nesta quick)."""
    pontos = dados["pontos"]
    url_tabela = reverse("pca:tabela")
    return graficos.colunas(
        [ponto["rotulo"] for ponto in pontos],
        {"Contratos a vencer": [ponto["quantidade"] for ponto in pontos]},
        urls={
            "Contratos a vencer": [
                f"{url_tabela}?{ponto['querystring']}" for ponto in pontos
            ]
        },
        rotulos=True,
    )


def resumo_vencimento(dados):
    total = sum(ponto["quantidade"] for ponto in dados["pontos"])
    return (
        f"Contratos a vencer nos próximos 12 meses: {total} contratos vigentes."
    )


def tabela_vencimento(dados):
    """Fase 28 — "Ver dados" do par "Vencimentos de
    contratos vigentes"; MESMO `dados` já computado por
    `apps.pca.analise.calcular_grafico_vencimento_contratos(qs, get)`
    (nenhuma query nova)."""
    url_tabela = reverse("pca:tabela")
    linhas = [
        [
            ponto["rotulo"],
            {
                "valor": numero(ponto["quantidade"]),
                "url": f"{url_tabela}?{ponto['querystring']}",
            },
        ]
        for ponto in dados["pontos"]
    ]
    return graficos.tabela_dados(["Mês", "Quantidade"], linhas)


def calcular_situacao_por_mes(qs, get):
    """NOVO — 4º gráfico do dashboard: colunas empilhadas
    de situação × mês previsto, substituindo "Contratos a vencer" (que
    migra para Análises). 1 única consulta agrupando por
    `mes_previsto`×`estado`×`situacao_efetiva` — mesma leitura MECE de
    `ORDEM_STATUS`/`calcular_status_distribuicao` (Cancelado + as 4
    situações de ativos). `sobrestados_por_mes`/`total_sobrestados` (Objective
    item 1) são só números de apoio — NUNCA um 6º segmento da pilha:
    `sobrestado` (`n_prorrogacoes > 1`) não é mutuamente exclusivo com as 5
    combinações MECE (um item pode estar atrasado E sobrestado ao mesmo
    tempo), então somá-lo à pilha quebraria a soma MECE."""
    brutos = {}
    for linha in (
        qs.exclude(mes_previsto__isnull=True)
        .values("mes_previsto", "estado", "situacao_efetiva")
        .order_by()
        .annotate(total=Count("id"))
    ):
        brutos[(linha["mes_previsto"], linha["estado"], linha["situacao_efetiva"])] = linha["total"]

    series = []
    for eixo, valor, rotulo in ORDEM_STATUS:
        valores = []
        querystrings = []
        for numero_mes in MESES:
            if eixo == "estado":
                total_mes = sum(
                    total
                    for (mes, estado, _situacao), total in brutos.items()
                    if mes == numero_mes and estado == valor
                )
                querystring = querystring_filtros(
                    get, estado=[valor.value], mes=numero_mes
                )
            else:
                total_mes = sum(
                    total
                    for (mes, estado, situacao), total in brutos.items()
                    if mes == numero_mes
                    and estado == Estado.ATIVO
                    and situacao == valor
                )
                querystring = querystring_filtros(
                    get,
                    estado=[Estado.ATIVO.value],
                    situacao=[valor.value],
                    mes=numero_mes,
                )
            valores.append(total_mes)
            querystrings.append(querystring)
        series.append({"rotulo": rotulo, "valores": valores, "querystrings": querystrings})

    sobrestados_brutos = {
        linha["mes_previsto"]: linha["total"]
        for linha in qs.sobrestados()
        .exclude(mes_previsto__isnull=True)
        .values("mes_previsto")
        .order_by()
        .annotate(total=Count("id"))
    }
    sobrestados_por_mes = [sobrestados_brutos.get(numero_mes, 0) for numero_mes in MESES]

    return {
        "series": series,
        "sobrestados_por_mes": sobrestados_por_mes,
        "total_sobrestados": sum(sobrestados_por_mes),
    }


def opcoes_situacao_por_mes(dados):
    categorias = [_NOMES_MES_CURTOS[numero_mes] for numero_mes in MESES]
    series = {serie["rotulo"]: serie["valores"] for serie in dados["series"]}
    url_tabela = reverse("pca:tabela")
    urls = {
        serie["rotulo"]: [f"{url_tabela}?{qs}" for qs in serie["querystrings"]]
        for serie in dados["series"]
    }
    opcoes = graficos.colunas(categorias, series, empilhado=True, urls=urls)
    # graficos.md — única exceção de cor: colorir por status (`CORES_STATUS`
    # via `MAPA_SITUACAO_STATUS`), porque a série É um status.
    for serie_opcoes in opcoes["series"]:
        chave_status = MAPA_SITUACAO_STATUS.get(serie_opcoes["name"], "cancelado")
        serie_opcoes["itemStyle"] = {"color": graficos.CORES_STATUS[chave_status]}
    return opcoes


def tabela_situacao_por_mes(dados):
    """Tabela companheira ("Ver dados") do
    4º gráfico do dashboard (colunas empilhadas), a partir do MESMO `dados`
    já computado por `calcular_situacao_por_mes(qs, get)`."""
    url_tabela = reverse("pca:tabela")
    colunas_tabela = ["Mês"] + [serie["rotulo"] for serie in dados["series"]]
    linhas = []
    for indice, numero_mes in enumerate(MESES):
        linha = [NOMES_MES[numero_mes]]
        for serie in dados["series"]:
            linha.append(
                {
                    "valor": numero(serie["valores"][indice]),
                    "url": f"{url_tabela}?{serie['querystrings'][indice]}",
                }
            )
        linhas.append(linha)
    return graficos.tabela_dados(colunas_tabela, linhas)


def resumo_situacao_por_mes(dados):
    partes = ", ".join(
        f"{sum(serie['valores'])} {serie['rotulo'].lower()}" for serie in dados["series"]
    )
    texto = f"Situação por mês previsto: {partes}."
    if dados["total_sobrestados"] > 0:
        texto += (
            f" {dados['total_sobrestados']} sobrestados no período "
            "(contagem cruzada, não somada às colunas)."
        )
    return texto


def calcular_pendencias(qs):
    """Até 10 "Processos atrasados" (maior atraso primeiro,
    MESMO filtro do KPI Atrasados: ATIVO, Nova Contratação/Renovação,
    `situacao_efetiva=ATRASADO`); vazio cai para "Processos sobrestados"
    (`ProcessoQuerySet.sobrestados()`); vazio de novo devolve lista vazia
    (o template mostra "Nenhuma pendência.")."""
    ids_elegiveis = _ids_elegiveis()
    processos = list(
        qs.filter(
            estado=Estado.ATIVO,
            tipo_id__in=ids_elegiveis,
            situacao_efetiva=Situacao.ATRASADO,
        )
        .select_related("exercicio", "unidade_organizacional")
        .order_by("-dias_atraso", "item_pca")[:10]
    )
    titulo = "Processos atrasados"
    if not processos:
        titulo = "Processos sobrestados"
        processos = list(
            qs.sobrestados()
            .select_related("exercicio", "unidade_organizacional")
            .order_by("-n_prorrogacoes", "item_pca")[:10]
        )

    rotulos_situacao = dict(Situacao.choices)
    for processo in processos:
        processo.url_detalhe = reverse(
            "pca:detalhe_processo", args=[processo.exercicio.ano, processo.item_pca]
        )
        processo.situacao_rotulo = rotulos_situacao.get(
            processo.situacao_efetiva, processo.situacao_efetiva
        )
    return titulo, processos


# Fase 28 — dict por CHAVE (não mais tupla iterada
# das 5 de uma vez): `calcular_perfil_grupo` busca UMA entrada, nunca as
# 5. Rótulo "Orçamento por tipo" (sem parênteses) é o literal.
_CONFIG_PERFIL = {
    "categoria": ("Categoria", "categoria__nome", "categoria_id", "categoria", False),
    "prioridade": (
        "Prioridade",
        "grau_prioridade__nome",
        "grau_prioridade_id",
        "prioridade",
        True,
    ),
    "classificacao": (
        "Estratégica",
        "classificacao__nome",
        "classificacao_id",
        "classificacao",
        True,
    ),
    "modalidade": (
        "Modalidade",
        "modalidade__nome",
        "modalidade_id",
        "modalidade",
        True,
    ),
    "tipo": ("Orçamento por tipo", "tipo__nome", "tipo_id", "tipo", False),
}


def calcular_perfil_grupo(qs, get, dimensao):
    """Fase 28 — substitui `calcular_perfil`
    (que sempre calculava as 5 dimensões): roda a query de UMA ÚNICA
    dimensão, buscada em `_CONFIG_PERFIL` por chave. Mesmo corpo de
    agregação da versão anterior, só que para 1 grupo em vez
    de 5 — 1 consulta por troca de `perfil_dimensao`, nunca 5."""
    titulo, campo_nome, campo_id, chave_filtro, aceita_nao_informado = _CONFIG_PERFIL[
        dimensao
    ]
    linhas_brutas = (
        qs.values(campo_id, campo_nome)
        .order_by()
        .annotate(total=Count("id"), soma=Sum("valor_estimado"))
    )
    linhas = []
    for linha in sorted(linhas_brutas, key=lambda linha: -linha["total"]):
        identificador = linha[campo_id]
        if identificador is None:
            rotulo = "Não classificado" if dimensao == "prioridade" else "Não informado"
            querystring = None
        else:
            rotulo = linha[campo_nome]
            querystring = querystring_filtros(get, **{chave_filtro: identificador})
        if identificador is None and not aceita_nao_informado:
            continue
        linhas.append(
            {
                "rotulo": rotulo,
                "total": linha["total"],
                # quantizar_soma corrige o ruido de ponto flutuante do SUM() do SQLite.
                "soma": quantizar_soma(linha["soma"]) or 0,
                "querystring": querystring,
            }
        )
    return {"chave": dimensao, "titulo": titulo, "linhas": linhas}


def opcoes_perfil_grupo(grupo, medida="total"):
    """(Análises, Escopo 2) — rosca de até 6 fatias por
    grupo de Perfil; linhas > 6 agrupam o resto em "Outros" (sem
    drill-down, `querystring=None`, graficos.md regra 4 — máximo 6
    fatias). Consome o grupo JÁ COMPUTADO por `calcular_perfil_grupo(qs,
    get, dimensao)` (nenhuma query nova).

    Fase 28 — `medida` escolhe a fatia: "total"
    (contagem, `numero()`, padrão) ou "soma" (valor estimado, `moeda()`)
    — só "Orçamento por tipo" usa `medida="soma"`; as outras 4 dimensões
    continuam com a contagem. Valores monetários viram `float` antes de
    entrar no ECharts (mesmo padrão de `opcoes_mes_dimensao` — o
    `DjangoJSONEncoder` serializaria `Decimal` como string, quebrando o
    cálculo de percentual da fatia no cliente)."""
    linhas = grupo["linhas"]

    def _valor(linha):
        bruto = linha[medida]
        return float(bruto) if medida == "soma" else bruto

    total_geral = sum(_valor(linha) for linha in linhas)
    if len(linhas) > 6:
        principais = linhas[:5]
        resto = linhas[5:]
        linhas_grafico = principais + [
            {
                "rotulo": "Outros",
                "total": sum(linha["total"] for linha in resto),
                "soma": sum(linha["soma"] for linha in resto),
                "querystring": None,
            }
        ]
    else:
        linhas_grafico = linhas
    fatias = [(linha["rotulo"], _valor(linha)) for linha in linhas_grafico]
    formatar_total = moeda if medida == "soma" else numero
    return graficos.rosca(
        fatias,
        urls=_urls_por_rotulo(linhas_grafico),
        rotulo_externo=True,
        formato_valor=moeda_curta if medida == "soma" else None,
        total=(formatar_total(total_geral), grupo["titulo"].lower()),
    )


def tabela_perfil_grupo(grupo):
    """Fase 28 — "Ver dados" do par de Perfil:
    Quantidade + Valor estimado por linha, MESMO recorte > 6 -> 5 +
    "Outros" do gráfico companheiro (`opcoes_perfil_grupo`) — a tabela
    principal representa exatamente as mesmas fatias."""
    linhas = grupo["linhas"]
    if len(linhas) > 6:
        principais = linhas[:5]
        resto = linhas[5:]
        linhas_tabela = principais + [
            {
                "rotulo": "Outros",
                "total": sum(linha["total"] for linha in resto),
                "soma": sum(linha["soma"] for linha in resto),
                "querystring": None,
            }
        ]
    else:
        linhas_tabela = linhas
    urls = _urls_por_rotulo(linhas_tabela)
    tabela_linhas = [
        [
            {"valor": linha["rotulo"], "url": urls.get(linha["rotulo"])},
            numero(linha["total"]),
            moeda(linha["soma"]),
        ]
        for linha in linhas_tabela
    ]
    return graficos.tabela_dados([grupo["titulo"], "Quantidade", "Valor estimado"], tabela_linhas)


_NOMES_MES_CURTOS = {mes: nome[:3] for mes, nome in NOMES_MES.items()}


def serializar_series_mensais(series, medida):
    """Formata `apps.pca.analise.calcular_grafico_mensal(qs, get)[dimensao]`
    para a tabela "mês × dimensão" de Análises: cada ponto ganha
    `rotulo_mes` (3 letras) e `valor_exibido` (já formatado pt-BR — moeda ou
    número, nunca `{{ valor }}` cru no template). `medida` é uma das 3
    chaves de `calcular_grafico_mensal`: quantidade/valor_previsto/
    valor_contratado."""
    from core.templatetags.dsgov import moeda, numero

    formatar = numero if medida == "quantidade" else moeda
    resultado = []
    for serie in series:
        pontos = []
        for ponto in serie["pontos"]:
            pontos.append(
                {
                    "rotulo_mes": _NOMES_MES_CURTOS[ponto["mes"]],
                    "valor_exibido": formatar(ponto[medida]),
                    "querystring": ponto["querystring"],
                }
            )
        resultado.append({"nome": serie["nome"], "pontos": pontos})
    return resultado


def opcoes_mes_dimensao(series_dimensao, medida):
    """(Análises, Escopo 2) — gráfico companheiro da
    tabela "mês × dimensão": `series_dimensao` é o valor BRUTO de
    `apps.pca.analise.calcular_grafico_mensal(qs, get)[dimensao]` (NÃO a
    versão formatada de `serializar_series_mensais` — o ECharts precisa de
    número, não string pt-BR)."""
    categorias = [_NOMES_MES_CURTOS[numero_mes] for numero_mes in MESES]
    url_tabela = reverse("pca:tabela")
    series = {}
    urls = {}
    for serie in series_dimensao:
        valores = []
        pontos_urls = []
        for ponto in serie["pontos"]:
            valor = (
                ponto["quantidade"]
                if medida == "quantidade"
                else float(ponto[medida])
            )
            valores.append(valor)
            pontos_urls.append(f"{url_tabela}?{ponto['querystring']}")
        series[serie["nome"]] = valores
        urls[serie["nome"]] = pontos_urls
    return graficos.colunas(categorias, series, empilhado=True, urls=urls)


def resumo_mes_dimensao(series_dimensao, dimensao_rotulo, medida_rotulo):
    return f"{dimensao_rotulo} por mês ({medida_rotulo}): {len(series_dimensao)} série(s)."


def tabela_resumo_mes_dimensao(series_dimensao, medida, dimensao_rotulo):
    """Fase 28 — tabela-resumo COMPACTA do par
    "Distribuição mensal por dimensão": uma linha por série com o TOTAL
    ANUAL somado dos 12 pontos (não os 12 meses — isso é o "detalhamento"
    full-width que continua abaixo, `series_mensais`). Recebe o valor
    BRUTO de `apps.pca.analise.calcular_grafico_mensal(qs, get)[dimensao]`
    (mesmo padrão de `opcoes_mes_dimensao`, nenhuma query nova)."""
    linhas = []
    for serie in series_dimensao:
        if medida == "quantidade":
            total_anual = sum(ponto["quantidade"] for ponto in serie["pontos"])
            valor_exibido = numero(total_anual)
        else:
            total_anual = sum(
                Decimal(ponto[medida]) for ponto in serie["pontos"]
            )
            valor_exibido = moeda(total_anual)
        linhas.append([serie["nome"], valor_exibido])
    return graficos.tabela_dados([dimensao_rotulo, "Total anual"], linhas)


def colunas_pendencias():
    """Colunas de `dashboard.md::pendencias` (Item, Objeto, Unidade, Prazo
    atual, Situação) — `campo`/`chave`/`url` apontam para os atributos
    reais/computados de `Processo` (`_kpi_card.html`/`core/inicio.html` da
    padrão DSGov leem via `{% filter atributo %}`/`{% filter exibir %}`)."""
    return [
        {"campo": "item_pca", "rotulo": "Item", "url": "url_detalhe"},
        {"campo": "descricao_objeto", "rotulo": "Objeto"},
        {"campo": "unidade_organizacional.nome", "rotulo": "Unidade"},
        {"campo": "prazo_efetivo", "rotulo": "Prazo atual", "tipo": "data"},
        {
            "campo": "situacao_rotulo",
            "rotulo": "Situação",
            "tipo": "status",
            "chave": "situacao_efetiva",
        },
    ]


def graficos_resumo_uo(total):
    """Resumo por unidade (29/09/2026, pedido do usuário) — as três roscas do topo, no mesmo padrão do
    dashboard (`core.graficos.rosca`, total no centro): Previstos (ativos × cancelados), Ativos por tipo
    (NC, RN, VG) e Meta PCA (NC + RN) por situação. Cada fatia abre a /tabela com os filtros do Resumo
    (`total["hrefs"]`, os mesmos links da linha TOTAL da matriz). Três cards estreitos lado a lado: sem
    rótulos em volta do anel (seriam cortados), o número vai na legenda ("Ativos (129)"), legenda que
    quebra linha em vez de paginar e anel um pouco menor — os três cards ficam com a mesma altura."""
    base = reverse("pca:tabela") + "?"
    hrefs = total["hrefs"]

    def rosca(fatias, centro):
        """fatias = [(rótulo, valor, chave do href, status ou None)]."""
        nomes = [(f"{rotulo} ({numero(valor)})", valor, chave, status) for rotulo, valor, chave, status in fatias]
        opcoes = graficos.rosca(
            [(nome, valor) for nome, valor, _, _ in nomes],
            status={nome: status for nome, _, _, status in nomes if status} or None,
            urls={nome: base + hrefs[chave] for nome, _, chave, _ in nomes},
            total=centro,
            rotulo_externo=True,
        )
        opcoes["legend"] = {"bottom": 0, "type": "plain"}
        opcoes["series"][0]["radius"] = ["45%", "68%"]
        return opcoes

    previstos = [
        ("Ativos", total["ativos"], "ativos", "concluido"),
        ("Cancelados", total["cancelados"], "cancelados", "cancelado"),
    ]
    tipos = [
        ("NC", total["nova"], "nova", None),
        ("RN", total["renovacao"], "renovacao", None),
        ("VG", total["vigente"], "vigente", None),
    ]
    meta = [
        ("Concluído", total["concluido_meta"], "concluido_meta", "concluido"),
        ("Em tramitação", total["em_tramitacao"], "em_tramitacao", "andamento"),
        ("No prazo", total["no_prazo"], "no_prazo", "pendente"),
        ("Atrasado", total["fora_prazo"], "fora_prazo", "atrasado"),
    ]
    return [
        {
            "id": "grafico-resumo-previstos",
            "titulo": "Previstos no PCA",
            "subtitulo": f"{percentual(total['percentual_ativos'])} seguem ativos",
            "opcoes": rosca(previstos, (numero(total["total_previsto"]), "previstos")),
            "resumo": f"Previstos no PCA: {total['total_previsto']} — {total['ativos']} ativos e {total['cancelados']} cancelados.",
            "col": "col-sm-12 col-lg-4",
        },
        {
            "id": "grafico-resumo-tipos",
            "titulo": "Ativos por tipo",
            "subtitulo": "Nova contratação, renovação e vigente",
            "opcoes": rosca(tipos, (numero(total["ativos"]), "ativos")),
            "resumo": f"Ativos por tipo: {total['nova']} NC, {total['renovacao']} RN e {total['vigente']} VG.",
            "col": "col-sm-12 col-lg-4",
        },
        {
            "id": "grafico-resumo-meta",
            "titulo": "Meta PCA (NC + RN)",
            "subtitulo": f"{percentual(total['percentual_concluido_meta'])} concluído",
            "opcoes": rosca(meta, (numero(total["meta"]), "na meta")),
            "resumo": (
                f"Meta PCA: {total['meta']} — {total['concluido_meta']} concluídos, {total['em_tramitacao']} em "
                f"tramitação, {total['no_prazo']} no prazo e {total['fora_prazo']} atrasados."
            ),
            "col": "col-sm-12 col-lg-4",
        },
    ]
