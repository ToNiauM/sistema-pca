"""Preditivos de prazo — `apps/pca/projecao/prazos.py` (Fase 36,
spec §4). Módulo PURO: nenhum import de `django`/`from django`. Estatística
descritiva com `statistics` + `Decimal`. Regra para *n* pequeno:
estimativa por estrato (UO, modalidade) só com n >= 5 concluídos; abaixo,
cai para o estrato geral e sinaliza isso no retorno. Todo número preditivo
carrega `n`, `estrato` e `metodo` — nada é salvo, tudo é recalculado por
requisição.
"""

import statistics
from datetime import timedelta
from decimal import Decimal

DUAS_CASAS = Decimal("0.01")
LIMIAR_N_ESTRATO = 5


# --------------------------------------------------------------------------
# 4.1 — Lead time por etapa


def lead_time_por_etapa(duracoes):
    """`duracoes`: list[int] (dias). Devolve mediana/p25/p75/p90/n via
    `statistics.median` + interpolação linear própria para os quartis."""

    n = len(duracoes)
    if n == 0:
        return {"mediana": None, "p25": None, "p75": None, "p90": None, "n": 0}

    ordenado = sorted(duracoes)
    return {
        "mediana": Decimal(statistics.median(ordenado)),
        "p25": _percentil(ordenado, Decimal("0.25")),
        "p75": _percentil(ordenado, Decimal("0.75")),
        "p90": _percentil(ordenado, Decimal("0.90")),
        "n": n,
    }


def _percentil(ordenado, fracao):
    """Interpolação linear (método comum de percentil) sobre uma lista já
    ordenada, em `Decimal`."""

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


def lead_time_estratificado(duracoes_estrato, duracoes_geral, nome_estrato):
    """Envelope de `lead_time_por_etapa` com a regra de n pequeno:
    n >= 5 no estrato usa o próprio estrato; abaixo, cai para `duracoes_geral`
    com `estrato="geral"` + aviso."""

    if len(duracoes_estrato) >= LIMIAR_N_ESTRATO:
        resultado = lead_time_por_etapa(duracoes_estrato)
        resultado["estrato"] = nome_estrato
        resultado["metodo"] = "mediana_p25_p75_p90"
        resultado["aviso"] = None
        return resultado

    resultado = lead_time_por_etapa(duracoes_geral)
    resultado["estrato"] = "geral"
    resultado["metodo"] = "mediana_p25_p75_p90"
    resultado["aviso"] = (
        f"estimativa geral (poucos casos em {nome_estrato}: "
        f"n={len(duracoes_estrato)})"
    )
    return resultado


# --------------------------------------------------------------------------
# 4.2 — Kaplan-Meier, score de risco, data provável


def sobrevivencia_km(pontos):
    """`pontos`: list[(dias: int, censurado: bool)]. Implementação própria
    do produto de Kaplan-Meier (spec §4.2, sem biblioteca externa):
    `S(t) = S(t-) * (1 - d_t/n_t)` a cada tempo de EVENTO (não-censurado);
    censuras só reduzem o `n_risco` disponível para o próximo tempo.
    Devolve uma lista ordenada por tempo, só com os tempos de evento:
    `[{"t": int, "s": Decimal, "n_risco": int, "eventos": int}]`."""

    if not pontos:
        return []

    tempos_unicos = sorted({t for t, _ in pontos})
    total = len(pontos)
    processados = 0
    sobrevivencia = Decimal("1")
    curva = []

    for t in tempos_unicos:
        censuras_no_tempo = [c for (d, c) in pontos if d == t]
        eventos = sum(1 for c in censuras_no_tempo if not c)
        n_risco = total - processados
        if eventos > 0:
            sobrevivencia = sobrevivencia * (
                Decimal(n_risco - eventos) / Decimal(n_risco)
            )
            curva.append(
                {"t": t, "s": sobrevivencia, "n_risco": n_risco, "eventos": eventos}
            )
        processados += len(censuras_no_tempo)

    return curva


def _sobrevivencia_em(curva, t):
    """Avalia a curva (função escada) em `t`: 1,0 antes do 1º evento, senão
    o `s` do último evento com tempo <= t."""

    s = Decimal("1")
    for ponto in curva:
        if ponto["t"] <= t:
            s = ponto["s"]
        else:
            break
    return s


def score_risco(t_prazo, t_hoje, curva, multiplicadores=None, estrato="geral"):
    """`score = 1 − S(t_prazo)/S(t_hoje)` (spec §4.2), ajustado pelos
    multiplicadores empíricos cujo próprio `n` sustenta o uso (n >= 5);
    sem histórico suficiente, o multiplicador fica 1,0. Resultado
    SEMPRE dentro de `[0, 1]` (clamp explícito)."""

    s_prazo = _sobrevivencia_em(curva, t_prazo)
    s_hoje = _sobrevivencia_em(curva, t_hoje)

    if s_hoje == 0:
        base = Decimal("1")
    else:
        base = Decimal("1") - (s_prazo / s_hoje)

    fator_total = Decimal("1")
    n_usado = 0
    for multiplicador in multiplicadores or []:
        n_m = multiplicador.get("n", 0)
        if n_m is not None and n_m >= LIMIAR_N_ESTRATO:
            fator_total *= multiplicador["valor"]
            n_usado = max(n_usado, n_m)
        # n < 5: multiplicador ignorado, permanece 1,0

    score = base * fator_total
    score = max(Decimal("0"), min(Decimal("1"), score))

    percentual = score * 100
    if percentual < 30:
        faixa = "baixo"
    elif percentual <= 60:
        faixa = "medio"
    else:
        faixa = "alto"

    return {
        "score": score,
        "faixa": faixa,
        "n": n_usado,
        "estrato": estrato,
        "metodo": "kaplan_meier_multiplicadores",
    }


def data_provavel(hoje, dias_p25, dias_p75, n, estrato, metodo="tempo_restante_condicional"):
    """Intervalo `(p25, p75)` de datas — NUNCA uma data única."""

    return {
        "p25": hoje + timedelta(days=int(dias_p25)),
        "p75": hoje + timedelta(days=int(dias_p75)),
        "n": n,
        "estrato": estrato,
        "metodo": metodo,
    }


# --------------------------------------------------------------------------
# 4.3 — Orquestrador


def calcular(itens_concluidos, itens_abertos, hoje):
    """Monta lead time geral/por modalidade, a curva KM geral, a lista de
    risco por item aberto (score + faixa + data provável) e os vincendos em
    90/180/365 dias (spec §4.3, regra "continuado ∧ renovacao_prevista ∧
    vigencia_fim no horizonte" — mesma regra de `renovacao` do `fluxo.py`,
    aqui só para LISTAR, não para projetar valor)."""

    duracoes_geral = [
        i["duracao_gelic_assinatura"]
        for i in itens_concluidos
        if i.get("duracao_gelic_assinatura") is not None
    ]
    lead_time_geral = lead_time_estratificado(duracoes_geral, duracoes_geral, "geral")

    modalidades = {i.get("modalidade") for i in itens_concluidos if i.get("modalidade")}
    lead_time_por_modalidade = {}
    for modalidade in modalidades:
        duracoes_mod = [
            i["duracao_gelic_assinatura"]
            for i in itens_concluidos
            if i.get("modalidade") == modalidade
            and i.get("duracao_gelic_assinatura") is not None
        ]
        lead_time_por_modalidade[modalidade] = lead_time_estratificado(
            duracoes_mod, duracoes_geral, modalidade
        )

    pontos_geral = [
        (i["dias_ate_assinatura"], False)
        for i in itens_concluidos
        if i.get("dias_ate_assinatura") is not None
    ] + [
        (i["dias_em_aberto"], True)
        for i in itens_abertos
        if i.get("dias_em_aberto") is not None
    ]
    curva_geral = sobrevivencia_km(pontos_geral)
    km_geral = {
        "curva": curva_geral,
        "n": len(pontos_geral),
        "estrato": "geral",
        "metodo": "kaplan_meier",
    }

    riscos = []
    for item in itens_abertos:
        t_prazo = item.get("t_prazo")
        t_hoje = item.get("dias_em_aberto")
        if t_prazo is None or t_hoje is None:
            continue
        resultado_score = score_risco(
            t_prazo, t_hoje, curva_geral, item.get("multiplicadores"), estrato="geral"
        )
        resultado_data = data_provavel(
            hoje,
            item.get("tempo_restante_p25", 0),
            item.get("tempo_restante_p75", 0),
            km_geral["n"],
            "geral",
        )
        riscos.append(
            {
                "item_pca": item["item_pca"],
                **resultado_score,
                "data_provavel": resultado_data,
            }
        )

    vincendos = {"90": [], "180": [], "365": []}
    for item in itens_abertos:
        if not (item.get("regime_execucao") == "continuado" and item.get("renovacao_prevista")):
            continue
        vigencia_fim = item.get("vigencia_fim")
        if vigencia_fim is None:
            continue
        dias_para_vencer = (vigencia_fim - hoje).days
        for limite in (90, 180, 365):
            if 0 <= dias_para_vencer <= limite:
                vincendos[str(limite)].append(
                    {"item_pca": item["item_pca"], "vigencia_fim": vigencia_fim}
                )
                break

    return {
        "lead_time": {"geral": lead_time_geral, "por_modalidade": lead_time_por_modalidade},
        "sobrevivencia": {"geral": km_geral},
        "risco": riscos,
        "vincendos": vincendos,
    }
