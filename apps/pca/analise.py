"""Agregações para os gráficos da tela Análise: consome o queryset já
filtrado e devolve dados prontos para o template renderizar via json_script.
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

# rótulo humano de cada uma das 7 dimensões do painel de filtros
ROTULOS_DIMENSAO = {
    "uo": "UO",
    "modalidade": "Modalidade",
    "categoria": "Categoria",
    "prioridade": "Prioridade",
    "tipo": "Tipo",
    "estado": "Estado",
    "situacao": "Situação",
}

# para cada dimensão: (campo de nome para GROUP BY, campo de id companheiro
# ou None, chave de querystring_filtros, se a chave é multivalor)
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
    """Rótulo humano de um grupo (série) dentro de uma dimensão."""
    if dimensao == "estado":
        return _ROTULO_ESTADO.get(valor_bruto, str(valor_bruto))
    if dimensao == "situacao":
        return _ROTULO_SITUACAO.get(valor_bruto, str(valor_bruto))
    if nome_bruto is None:
        return "Não classificado" if dimensao == "prioridade" else "Não informado"
    return nome_bruto


def _querystring_do_ponto(get, chave_filtro, multivalor, valor_bruto, numero_mes):
    """Querystring de um ponto (mês x grupo) do gráfico."""
    overrides = {"mes": numero_mes}
    if valor_bruto is None:
        if chave_filtro == "prioridade":
            overrides["prioridade"] = [SENTINEL_NAO_CLASSIFICADO]
        # demais dimensões nulas: sem chave própria, só mes=
    elif multivalor:
        overrides[chave_filtro] = [valor_bruto]
    else:
        overrides[chave_filtro] = valor_bruto
    return querystring_filtros(get, **overrides)


def calcular_grafico_mensal(qs, get):
    """Dict com uma lista de séries mensais por dimensão (uo, modalidade,
    categoria, prioridade, tipo, estado, situacao); 7 queries fixas, uma
    por dimensão. Processos sem mes_previsto ficam fora do gráfico."""
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

        # agrupa as linhas (mês x grupo) por grupo
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
                            (linha["valor_previsto"] if linha else None) or Decimal("0")
                        ),
                        "valor_contratado": str(
                            (linha["valor_contratado"] if linha else None) or Decimal("0")
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


# rótulo curto (3 letras, minúsculo) de cada mês
_NOMES_MES_ABREV = {mes: nome[:3].lower() for mes, nome in NOMES_MES.items()}


def calcular_grafico_vencimento_contratos(qs, get):
    """Contagem de contratos vigentes por mês de vigencia_fim, 12 meses a
    partir do mês corrente. Devolve {"pontos": [...], "sem_vigencia_fim": N};
    uma única consulta agregada por (ano, mes)."""
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
    """Ids de Nova Contratação/Renovação, por nome_normalizado."""
    return list(
        Tipo.objects.filter(
            nome_normalizado__in=("nova contratacao", "renovacao")
        ).values_list("id", flat=True)
    )


def calcular_proximos_vencimentos(qs, get, *, limite=10):
    """Lista de próximos vencimentos ordenada por prazo, mais contagem de
    vencidos. Devolve (processos_pagina, total_no_recorte, total_vencidos,
    url_vencidos)."""
    hoje = localdate()
    ids_elegiveis = _ids_elegiveis_nc_rn()

    # exigir_no_prazo=False: só exclui CONCLUIDO, abaixo
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
