"""Estatísticas descritivas — `apps/pca/projecao/estatistica.py` (Fase
36/, spec §5). Módulo PURO: nenhum import de `django`/`from
django`; `itens: list[dict]`, mesmo contrato de `fluxo.py` (a view do Plano
36-03 monta a lista uma única vez e passa para os três módulos)."""

import statistics
from decimal import ROUND_HALF_UP, Decimal

LIMIAR_N_MODALIDADE = 5

# (M08) — convenção do projeto (`fluxo.py::_agregar`,
# `percentual_contratado`): percentuais são pontos percentuais NA ORIGEM,
# nunca frações cruas — `core/templatetags/dsgov.py::percentual` só formata
# e concatena "%", não multiplica por 100.
DUAS_CASAS = Decimal("0.01")


def _quantizar(valor):
    return valor.quantize(DUAS_CASAS, rounding=ROUND_HALF_UP)

FAIXAS_VALOR = (
    (Decimal("10000"), "ate_10_mil"),
    (Decimal("100000"), "10_mil_a_100_mil"),
    (Decimal("1000000"), "100_mil_a_1_mi"),
    (Decimal("10000000"), "1_mi_a_10_mi"),
)


def _percentil(ordenado, fracao):
    """Interpolação linear sobre lista ordenada, em `Decimal` — mesma
    técnica de `apps/pca/projecao/prazos.py::_percentil` (copiada, não
    importada, para manter cada módulo puro isolado dos demais)."""

    n = len(ordenado)
    if n == 1:
        return Decimal(ordenado[0])
    posicao = fracao * Decimal(n - 1)
    indice_inferior = int(posicao)
    resto = posicao - indice_inferior
    if indice_inferior + 1 >= n:
        return Decimal(ordenado[-1])
    inferior = Decimal(ordenado[indice_inferior])
    superior = Decimal(ordenado[indice_inferior + 1])
    return inferior + (superior - inferior) * resto


def _pareto_80(valores_itens):
    """Quantos itens (do maior para o menor valor) somam >= 80% do total."""

    ordenado = sorted(valores_itens, reverse=True)
    total = sum(ordenado, Decimal("0"))
    if total == 0:
        return 0
    limite = total * Decimal("0.8")
    acumulado = Decimal("0")
    for i, valor in enumerate(ordenado, start=1):
        acumulado += valor
        if acumulado >= limite:
            return i
    return len(ordenado)


def _meses_calendario(inicio, fim):
    return max((fim.year - inicio.year) * 12 + (fim.month - inicio.month) + 1, 1)


def _faixa_duracao_meses(meses):
    if meses <= 6:
        return "0-6"
    if meses <= 12:
        return "7-12"
    if meses <= 24:
        return "13-24"
    if meses <= 60:
        return "25-60"
    return "acima_de_60"


def _faixa_valor(valor):
    for limite, nome in FAIXAS_VALOR:
        if valor < limite:
            return nome
    return "acima_de_10_mi"


def _estatisticas_desvio(desvios):
    """`mediana`/`p25`/`p75`/`n` sobre uma lista de desvios já em pontos
    percentuais (ver `_quantizar` acima) — `n` é o tamanho da base
    EFETIVAMENTE usada aqui (própria modalidade ou pool geral, decidido por
    quem chama)."""
    ordenado = sorted(desvios)
    return {
        "mediana": statistics.median(ordenado),
        "p25": _percentil(ordenado, Decimal("0.25")),
        "p75": _percentil(ordenado, Decimal("0.75")),
        "n": len(ordenado),
    }


def valores(itens):
    """Execução financeira (Σcontratado/Σestimado) por UO; desvio estimado x
    contratado — mediana/P25-P75/n por modalidade (fallback para o pool
    GERAL de desvios, mesmo padrão de
    `prazos.py::lead_time_estratificado`, quando n < 5 na própria
    modalidade); concentração (Pareto 80 %); top 10 fornecedores por valor.

    `mediana`/`p25`/`p75` de `desvio_por_modalidade` são PONTOS PERCENTUAIS
    ((contratado-estimado)/estimado × 100, quantizados a 2 casas) — nunca
    frações cruas; `core/templatetags/dsgov.py::percentual` só formata e
    concatena "%", não multiplica (M08)."""

    execucao_por_uo = {}
    for item in itens:
        uo = item.get("uo")
        execucao_por_uo.setdefault(uo, {"contratado": Decimal("0"), "estimado": Decimal("0")})
        execucao_por_uo[uo]["contratado"] += item.get("valor_contratado") or Decimal("0")
        execucao_por_uo[uo]["estimado"] += item.get("valor_estimado") or Decimal("0")

    desvios_por_modalidade = {}
    for item in itens:
        estimado = item.get("valor_estimado")
        contratado = item.get("valor_contratado")
        modalidade = item.get("modalidade")
        if not estimado or contratado is None or modalidade is None:
            continue
        desvios_por_modalidade.setdefault(modalidade, []).append(
            _quantizar((contratado - estimado) / estimado * 100)
        )

    # Pool GERAL — todos os desvios, de todas as modalidades. Fallback real
    # (não só de rótulo) para modalidade com poucos casos.
    desvios_geral = [
        desvio for lista in desvios_por_modalidade.values() for desvio in lista
    ]

    desvio_por_modalidade = {}
    for modalidade, desvios in desvios_por_modalidade.items():
        n_modalidade = len(desvios)
        if n_modalidade >= LIMIAR_N_MODALIDADE:
            estatisticas = _estatisticas_desvio(desvios)
            estatisticas["estrato"] = modalidade
        else:
            estatisticas = _estatisticas_desvio(desvios_geral)
            estatisticas["estrato"] = "geral"
        estatisticas["n_modalidade"] = n_modalidade
        desvio_por_modalidade[modalidade] = estatisticas

    valores_contratados = [
        item["valor_contratado"] for item in itens if item.get("valor_contratado")
    ]
    pareto_80 = _pareto_80(valores_contratados)

    fornecedores = {}
    for item in itens:
        fornecedor = item.get("razao_social")
        valor = item.get("valor_contratado")
        if fornecedor is None or valor is None:
            continue
        fornecedores[fornecedor] = fornecedores.get(fornecedor, Decimal("0")) + valor
    top_fornecedores = [
        {"razao_social": nome, "valor": total}
        for nome, total in sorted(fornecedores.items(), key=lambda kv: kv[1], reverse=True)[:10]
    ]

    return {
        "execucao_por_uo": execucao_por_uo,
        "desvio_por_modalidade": desvio_por_modalidade,
        "pareto_80": pareto_80,
        "top_fornecedores": top_fornecedores,
    }


def vigencia(itens):
    """Duração contratada em faixas (0-6/7-12/13-24/25-60 meses);
    vencimentos por trimestre (quantidade e valor mensal); alerta de
    vigência acumulada >= 48 meses (art. 107 da Lei 14.133/2021)."""

    faixas_duracao = {"0-6": 0, "7-12": 0, "13-24": 0, "25-60": 0, "acima_de_60": 0}
    vencimentos_por_trimestre = {}
    alertas_48_meses = []

    for item in itens:
        inicio = item.get("vigencia_inicio")
        fim = item.get("vigencia_fim")
        # QA 30/09 (domínio nº12) — vigência INVERTIDA (fim antes do início)
        # caía em "0-6" por acidente; some de TODAS as saídas desta função
        # (faixas/trimestre/alerta de 48 meses), nunca só da faixa — os três
        # ficariam igualmente sem sentido para uma vigência invertida.
        if inicio is None or fim is None or fim < inicio:
            continue

        meses = _meses_calendario(inicio, fim)
        faixas_duracao[_faixa_duracao_meses(meses)] += 1
        if meses >= 48:
            alertas_48_meses.append(item.get("item_pca"))

        trimestre = f"{fim.year:04d}-T{(fim.month - 1) // 3 + 1}"
        vencimentos_por_trimestre.setdefault(
            trimestre, {"quantidade": 0, "valor_mensal": Decimal("0")}
        )
        vencimentos_por_trimestre[trimestre]["quantidade"] += 1
        vencimentos_por_trimestre[trimestre]["valor_mensal"] += item.get("valor_mensal") or Decimal("0")

    return {
        "faixas_duracao": faixas_duracao,
        "vencimentos_por_trimestre": vencimentos_por_trimestre,
        "alertas_vigencia_acumulada_48_meses": alertas_48_meses,
    }


def perfil(itens):
    """Distribuição por faixa de valor em escala log (10 mil/100 mil/1
    mi/10 mi), cruzada por modalidade."""

    distribuicao = {}
    for item in itens:
        valor = item.get("valor_contratado")
        if valor is None:
            valor = item.get("valor_estimado")
        if valor is None:
            continue
        modalidade = item.get("modalidade") or "sem_modalidade"
        faixa = _faixa_valor(valor)
        distribuicao.setdefault(faixa, {})
        distribuicao[faixa][modalidade] = distribuicao[faixa].get(modalidade, 0) + 1

    return {"distribuicao_por_faixa_e_modalidade": distribuicao}


def calcular(itens):
    """Orquestrador — combina os três blocos sobre a MESMA lista de itens
    (a view monta `itens` uma única vez)."""

    return {
        "valores": valores(itens),
        "vigencia": vigencia(itens),
        "perfil": perfil(itens),
    }
