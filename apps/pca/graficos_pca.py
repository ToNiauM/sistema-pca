"""Ponte entre apps.pca (dados) e core.graficos (opções ECharts prontas,
tema dsgov). Cada função aqui só agrega com o ORM e chama a função
correspondente de core.graficos, nunca reimplementa cor/estilo.

As funções de cálculo são compartilhadas entre o dashboard e a tela
Análises: cada um consome os mesmos números, nunca uma segunda query
concorrente para o mesmo dado."""

from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.urls import reverse

from apps.catalogo.models import Tipo
from apps.pca.analise import calcular_grafico_vencimento_contratos
from apps.pca.filtros import MESES, NOMES_MES, querystring_filtros
from apps.pca.kpis import _percentual
from apps.pca.models import Estado, Situacao
from core import graficos
from core.templatetags.dsgov import moeda, numero, percentual

# mesma ordem/rótulos de apps/pca/views.py::ORDEM_ROSCA
ORDEM_STATUS = (
    ("estado", Estado.CANCELADO, "Cancelado"),
    ("situacao", Situacao.CONCLUIDO, "Concluído"),
    ("situacao", Situacao.NO_PRAZO, "No prazo"),
    ("situacao", Situacao.EM_TRAMITACAO, "Em tramitação"),
    ("situacao", Situacao.ATRASADO, "Atrasado"),
)

# única exceção de cor: colorir por status via CORES_STATUS. Chaves = rotulo
# de ORDEM_STATUS; valores = chaves de core.graficos.CORES_STATUS
MAPA_SITUACAO_STATUS = {
    "Concluído": "concluido",
    "Atrasado": "atrasado",
    "Em tramitação": "andamento",
    "No prazo": "pendente",
    "Cancelado": "cancelado",
}


def _ids_elegiveis():
    """Ids de Nova Contratação + Renovação, resolvidos de novo aqui
    porque kpis.py não os expõe."""
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
    de ativos) — total/soma/querystring por fatia, 1 única consulta."""
    por_estado_situacao = {
        (linha["estado"], linha["situacao_efetiva"]): linha
        for linha in qs.values("estado", "situacao_efetiva")
        .order_by()
        .annotate(total=Count("id"), soma=Sum("valor_estimado"))
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


def opcoes_situacao(status_distribuicao):
    """Versão completa (5 linhas, incl. Cancelado), reusada por Análises;
    fatias com valor+%, total geral no centro do anel."""
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
        rotulos=True,
        total=(numero(total_geral), "processos"),
    )


def resumo_situacao(status_distribuicao):
    partes = ", ".join(
        f"{linha['total']} {linha['rotulo'].lower()}" for linha in status_distribuicao
    )
    return f"Processos por situação: {partes}."


def opcoes_situacao_ativos(status_distribuicao):
    """Rosca do dashboard só com os ativos — Cancelado sai (já contado no
    apoio do KPI Ativos); total de ativos no centro do anel."""
    ativas = [linha for linha in status_distribuicao if linha["rotulo"] != "Cancelado"]
    fatias = [(linha["rotulo"], linha["total"]) for linha in ativas]
    status_map = {
        linha["rotulo"]: MAPA_SITUACAO_STATUS[linha["rotulo"]]
        for linha in ativas
        if linha["rotulo"] in MAPA_SITUACAO_STATUS
    }
    total_ativos = sum(linha["total"] for linha in ativas)
    return graficos.rosca(
        fatias,
        status=status_map,
        urls=_urls_por_rotulo(ativas),
        rotulos=True,
        total=(numero(total_ativos), "ativos"),
    )


def resumo_situacao_ativos(status_distribuicao):
    ativas = [linha for linha in status_distribuicao if linha["rotulo"] != "Cancelado"]
    total_ativos = sum(linha["total"] for linha in ativas)
    partes = ", ".join(f"{linha['total']} {linha['rotulo'].lower()}" for linha in ativas)
    return f"Processos ativos por situação: {total_ativos} no total — {partes}."


def tabela_situacao_ativos(status_distribuicao):
    """Tabela companheira ("Ver dados") da rosca "Processos por situação"
    do dashboard, mesmo recorte só-ativos. 4 colunas (Situação/Quantidade/
    Percentual dos ativos/Valor estimado) + linha Total."""
    ativas = [linha for linha in status_distribuicao if linha["rotulo"] != "Cancelado"]
    urls = _urls_por_rotulo(ativas)
    total_ativos = sum(linha["total"] for linha in ativas)
    soma_ativos = sum(linha["soma"] for linha in ativas)
    linhas = [
        [
            {"valor": linha["rotulo"], "url": urls.get(linha["rotulo"])},
            numero(linha["total"]),
            percentual(_percentual(linha["total"], total_ativos)),
            moeda(linha["soma"]),
        ]
        for linha in ativas
    ]
    linhas.append(
        [
            "Total",
            numero(total_ativos),
            percentual(_percentual(total_ativos, total_ativos)),
            moeda(soma_ativos),
        ]
    )
    return graficos.tabela_dados(
        ["Situação", "Quantidade", "Percentual dos ativos", "Valor estimado"], linhas
    )


def calcular_totais_financeiros(qs):
    """2 barras do Início: soma de valor_estimado e valor_contratado sobre
    o mesmo qs do exercício. Um .aggregate() só; sem_contratado conta
    processos com valor_contratado nulo."""
    return qs.aggregate(
        estimado=Sum("valor_estimado"),
        contratado=Sum("valor_contratado"),
        sem_contratado=Count("id", filter=Q(valor_contratado__isnull=True)),
    )


def opcoes_totais_financeiros(dados):
    """2 categorias, 1 série, sem legenda redundante para 2 barras."""
    return graficos.colunas(
        ["Valor previsto", "Valor contratado"],
        {"R$": [float(dados["estimado"] or 0), float(dados["contratado"] or 0)]},
        rotulos=True,
    )


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
    """Ranking de unidades por volume, rótulos longos (barras horizontais)."""
    return list(
        qs.values("unidade_organizacional_id", "unidade_organizacional__nome")
        .order_by()
        .annotate(total=Count("id"), soma=Sum("valor_estimado"))
        .order_by("-total")
    )


def tabela_por_unidade(qs, get):
    """calcular_por_unidade no contrato genérico rotulo/total/soma/querystring."""
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
    """Recebe a lista já computada por tabela_por_unidade; nunca chama
    calcular_por_unidade de novo, uma query só reusada por dashboard e
    Análises."""
    rotulos = [linha["rotulo"] for linha in tabela_unidade]
    valores = [linha["total"] for linha in tabela_unidade]
    urls = [
        f"{reverse('pca:tabela')}?{linha['querystring']}" for linha in tabela_unidade
    ]
    # escala=True ativa o visualMap/CORES_SEQUENCIAL (mais escuro = mais
    # processos): intensidade por valor usa rampa monocromática
    return graficos.barras_horizontais(
        rotulos, valores, "Processos", escala=True, urls=urls
    )


def tabela_unidade_dados(tabela_unidade):
    """Tabela companheira ("Ver dados") do gráfico "Processos por unidade",
    a partir do mesmo tabela_unidade já computado."""
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
    """12 pontos (mês previsto 1-12): quantidade prevista (todo processo
    com aquele mês) x entregue (ativo e já concluído)."""
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
                # "entregue" é ativo + concluído dentro do mês previsto,
                # nunca recebido_de/ate (mês de recebimento no Gelic)
                "querystring_previsto": querystring_previsto,
                "querystring_entregue": querystring_filtros(
                    get,
                    mes=numero_mes,
                    estado=[Estado.ATIVO.value],
                    situacao=[Situacao.CONCLUIDO.value],
                ),
                # alias de querystring_previsto, mantido para não quebrar o template
                "querystring": querystring_previsto,
            }
        )
    return pontos


def opcoes_previsto_entregue(pontos):
    """12 meses abreviados, rótulo de valor no topo das colunas, url de
    drill-down por série. Recebe pontos já computado por
    calcular_previsto_entregue, chamado uma única vez pela view."""
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
    """Tabela companheira ("Ver dados") do card "Previsto x Entregue por
    mês", a partir do mesmo pontos já computado."""
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
    """Recebe o dict já computado por
    calcular_grafico_vencimento_contratos; Análises reusa o mesmo dict
    para a tabela e o gráfico, nunca uma 2ª consulta."""
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
    """"Ver dados" do par "Vencimentos de contratos vigentes"; mesmo dados
    já computado, nenhuma query nova."""
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
    """4º gráfico do dashboard: colunas empilhadas de situação x mês
    previsto, 1 única consulta. sobrestados_por_mes/total_sobrestados são
    só números de apoio, nunca um 6º segmento da pilha — sobrestado não é
    mutuamente exclusivo com as 5 combinações MECE."""
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
    # única exceção de cor: colorir por status, porque a série é um status
    for serie_opcoes in opcoes["series"]:
        chave_status = MAPA_SITUACAO_STATUS.get(serie_opcoes["name"], "cancelado")
        serie_opcoes["itemStyle"] = {"color": graficos.CORES_STATUS[chave_status]}
    return opcoes


def tabela_situacao_por_mes(dados):
    """Tabela companheira ("Ver dados") do 4º gráfico do dashboard, a
    partir do mesmo dados já computado."""
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
    """Até 10 "Processos atrasados" (maior atraso primeiro, mesmo filtro
    do KPI Atrasados); vazio cai para "Processos sobrestados"; vazio de
    novo devolve lista vazia."""
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


# dict por chave — calcular_perfil_grupo busca uma entrada, nunca as 5
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
    """Roda a query de uma única dimensão, buscada em _CONFIG_PERFIL por
    chave — 1 consulta por troca de perfil_dimensao, nunca 5."""
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
                "soma": linha["soma"] or 0,
                "querystring": querystring,
            }
        )
    return {"chave": dimensao, "titulo": titulo, "linhas": linhas}


def opcoes_perfil_grupo(grupo, medida="total"):
    """Rosca de até 6 fatias por grupo de Perfil; linhas > 6 agrupam o
    resto em "Outros", sem drill-down. medida escolhe a fatia: "total"
    (contagem) ou "soma" (valor estimado); valores monetários viram float
    antes de entrar no ECharts."""
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
        rotulos=True,
        total=(formatar_total(total_geral), grupo["titulo"].lower()),
    )


def tabela_perfil_grupo(grupo):
    """"Ver dados" do par de Perfil: Quantidade + Valor estimado por
    linha, mesmo recorte > 6 -> 5 + "Outros" do gráfico companheiro."""
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
    """Formata calcular_grafico_mensal(qs, get)[dimensao] para a tabela
    "mês x dimensão": cada ponto ganha rotulo_mes e valor_exibido já
    formatado pt-BR."""
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
    """Gráfico companheiro da tabela "mês x dimensão": series_dimensao é o
    valor bruto de calcular_grafico_mensal, não a versão formatada."""
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
    """Tabela-resumo compacta do par "Distribuição mensal por dimensão":
    uma linha por série com o total anual somado dos 12 pontos."""
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
    """Colunas de pendências (Item, Objeto, Unidade, Prazo atual,
    Situação); campo/chave/url apontam para os atributos reais/computados
    de Processo."""
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
