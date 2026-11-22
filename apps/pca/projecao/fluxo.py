"""Cálculo do fluxo de caixa projetado — `projetar(itens, parametros) ->
Projecao` (Fase 36, spec §3; Fase 37, motor
corrigido — spec `2026-09-19-fluxo-de-caixa-simulacao-design.md` §2).
Módulo PURO: nenhum import de `django`/`from django`; saída = dataclasses de
`apps.pca.projecao`. `Decimal` do começo ao fim; arredondamento a 2 casas só
na ÚLTIMA parcela de cada segmento contínuo de geração — `sum(parcelas) ==
valor usado` sempre (M01).

Dois formatos de entrada convivem neste módulo (Fase 37 —
compatibilidade retroativa OBRIGATÓRIA pelo plano: "todos os testes
pré-existentes do arquivo passam"):

- **Formato NOVO** (`item["contratos"]` não vazio, spec §2.1): 0..n contratos
  independentes, cada um com periodicidade EXPLÍCITA (`mensal`/`anual`/
  `global`) e eventos próprios — motor corrigido (M01/M02/M03/M05/M10),
  funções `_contrato_*`/`_gerar_*`/`_segmentos_contrato` abaixo.
- **Formato ANTIGO** (campos soltos no item — `valor_contratado`,
  `vigencia_inicio`, `eventos`— sem `contratos[]`): motor da Fase 36, INTOCADO — inclusive a aritmética de rateio "meses de
  calendário ÷ proporcionalidade diária" que o M01 corrige só para o
  contrato NOVO (`_camada_contratado_*`/`_distribuir_mensal`/
  `_mensal_base_em` abaixo). Preservar essa aritmética aqui é deliberado:
  sem ela, os 21 testes pré-existentes de `test_projecao_fluxo.py`
  (calibrados nesses números exatos) quebrariam. `grep meses_calendario`
  encontra ocorrências SÓ nestas funções do formato antigo — nunca no
  cálculo de `"global"` do formato novo (`_peso_dias_periodo`).

As quatro camadas (`contratado`/`renovacao`/`reajuste`/`planejado`) e os
quatro cenários (`base`/`contratado`/`sem_reajuste`/`sem_renovacao`) usam o
vocabulário da Lei 14.133/2021 — o jargão de mercado descartado
pelo usuário (ver) não aparece em nenhum identificador
nem string deste módulo (teste-guarda: `grep -ic` do termo descartado = 0).
"""

from calendar import monthrange
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from apps.pca.regras_situacao import regime_presumido_projecao

from . import LinhaMemoria, Memoria, Parcela, Projecao, ROTULOS_CAMADA

DUAS_CASAS = Decimal("0.01")
INSTRUMENTO_PRINCIPAL = "principal"

# Quais camadas cada cenário inclui (spec §3.3). `contratado` (só a
# camada 1) NÃO inclui `planejado` — só o que já tem valor contratado.
CAMADAS_POR_CENARIO = {
    "base": ("contratado", "renovacao", "reajuste", "planejado"),
    "contratado": ("contratado",),
    "sem_reajuste": ("contratado", "renovacao", "planejado"),
    "sem_renovacao": ("contratado", "reajuste", "planejado"),
}


def projetar(itens, parametros):
    """Entrada: `itens` (spec §2.1) + `Parametros`. Saída: `Projecao` com
    `parcelas` já filtradas ao horizonte, mais os agregados prontos e
    `memorias` (Fase 37, um `Memoria` por item que gerou ao menos uma
    parcela ou tem contratos declarados).

    `sinais_premissas` (Fase 36, fix de apresentação — deviation) acumula os fatos brutos por ITEM (nunca por parcela/mês) durante
    o loop abaixo; `_consolidar_premissas` no fim transforma isso em NO
    MÁXIMO uma linha por (tipo de premissa) ou por (índice, ano), com a
    contagem de itens afetados — nunca uma linha repetida por competência.
    Só a apresentação muda; a regra de fallback do índice (último ano
    conhecido) continua em `_multiplicador_reajuste`, intocada."""

    camadas_permitidas = CAMADAS_POR_CENARIO[parametros.cenario]
    parcelas = []
    sem_dado = []
    memorias = {}
    sinais_premissas = {"vigencia_sem_fim": set(), "indices_ausentes": {}}

    for item in itens:
        if item.get("estado") == "cancelado":
            # QA (spec §3.4/bordas): cancelado é situação já tratada,
            # não é lacuna de dado — fora de toda camada, fora de sem_dado.
            continue
        parcelas_item, memoria, motivo = _projetar_item(
            item, parametros, camadas_permitidas, sinais_premissas
        )
        parcelas.extend(parcelas_item)
        if memoria is not None:
            memorias[item["item_pca"]] = memoria
        if motivo is not None:
            sem_dado.append({"item_pca": item["item_pca"], "motivo": motivo})

    premissas = _consolidar_premissas(sinais_premissas, parametros)

    # `_projetar_item` já filtra ao horizonte por item (acima) — sem
    # filtro global duplicado aqui (Fase 37, otimização de desempenho).
    por_mes, por_ano, por_uo_ano, totais = _agregar(parcelas, itens, parametros)

    return Projecao(
        parcelas=parcelas,
        por_mes=por_mes,
        por_ano=por_ano,
        por_uo_ano=por_uo_ano,
        totais=totais,
        sem_dado=sem_dado,
        premissas=premissas,
        memorias=memorias,
    )


# --------------------------------------------------------------------------
# Roteamento por item — formato NOVO (`contratos[]`) tem precedência; sem
# `contratos[]`, cai no motor antigo (formato soltos no item, intocado).


def _projetar_item(item, parametros, camadas_permitidas, sinais_premissas):
    # Fase 37 — `_itens_para_projecao`
    # sempre acrescenta um contrato "principal" a partir dos campos soltos
    # do `Processo`, MESMO quando o item é puramente planejado (sem
    # vigência nem valor contratado nenhum, `views_analise.py::
    # _itens_para_projecao`, grupo "principal" incondicional). Um `[{...
    # tudo None}]` é tecnicamente uma lista não vazia — sem este filtro,
    # `if contratos:` roteava TODO item (inclusive planejado puro) para o
    # motor novo, que descarta o contrato vazio e nunca chega a olhar
    # `valor_estimado`: a camada "planejado" inteira desapareceria.
    contratos = [c for c in (item.get("contratos") or []) if _contrato_tem_dado(c)]

    if contratos:
        parcelas, motivo = _projetar_item_contratos(
            item, contratos, parametros, camadas_permitidas, sinais_premissas
        )
        # Filtra ao horizonte AQUI (uma vez, por item) — `projetar()` não
        # filtra de novo globalmente (Fase 37, otimização de desempenho:
        # evita comparar a competência de cada parcela duas vezes) — e a
        # memória, construída a partir do MESMO `parcelas` já filtrado,
        # concilia por construção com o que `Projecao.parcelas` mostra.
        parcelas = _filtrar_horizonte(parcelas, parametros)
        memoria = _construir_memoria(item, contratos, parcelas)
        return parcelas, memoria, motivo

    if item.get("valor_contratado") is not None:
        parcelas, motivo = _camada_contratado_e_derivadas(
            item, parametros, camadas_permitidas, sinais_premissas
        )
        parcelas = _filtrar_horizonte(parcelas, parametros)
        memoria = _construir_memoria_legado(item, parcelas)
        return parcelas, memoria, motivo

    if item.get("valor_estimado") is None:
        return [], None, "sem_valor"

    if "planejado" not in camadas_permitidas:
        return [], None, None

    parcelas, motivo = _camada_planejado(item, parametros)
    parcelas = _filtrar_horizonte(parcelas, parametros)
    memoria = _construir_memoria_legado(item, parcelas)
    return parcelas, memoria, motivo


def _filtrar_horizonte(parcelas, parametros):
    competencia_inicio = _competencia(parametros.horizonte_inicio)
    competencia_fim = _competencia(parametros.horizonte_fim)
    return [p for p in parcelas if competencia_inicio <= p.competencia <= competencia_fim]


# ==========================================================================
# MOTOR NOVO — item["contratos"] (Fase 37, spec §2)


def _contrato_tem_dado(contrato):
    return (
        contrato.get("vigencia_inicio") is not None
        or contrato.get("vigencia_fim") is not None
        or contrato.get("data_assinatura") is not None
        or contrato.get("valor") is not None
    )


def _projetar_item_contratos(item, contratos, parametros, camadas_permitidas, sinais_premissas):
    parcelas = []
    algum_valido = False
    algum_sem_valor = False
    for contrato in contratos:
        vigencia_inicio = contrato.get("vigencia_inicio")
        vigencia_fim = contrato.get("vigencia_fim")
        data_assinatura = contrato.get("data_assinatura")
        valor = contrato.get("valor")

        if vigencia_inicio is None and vigencia_fim is None and data_assinatura is None:
            continue
        if valor is None:
            algum_sem_valor = True
            continue
        algum_valido = True

        # Fase 37: o formato NOVO não reaproveita
        # `regime_presumido_projecao` para decidir "único vs. continuado" —
        # o limiar de 12 meses (`_meses_entre`) daquela função foi
        # calibrado para o formato ANTIGO (sem `periodicidade`), e classifica
        # um contrato de 01/01 a 31/12 do MESMO ano como "único" (11,97
        # meses, um dia de fração abaixo do limiar) — contradizendo os
        # casos de aceite do plano (contrato mensal/global de um ano
        # inteiro, sem `regime_execucao` explícito, esperando `continuado`).
        # No contrato novo, `periodicidade` (mensal/anual/global) já É o
        # sinal de obrigação contínua — "único" fica reservado a
        # `regime_execucao` explícito ou à ausência de `vigencia_inicio`
        # (pagamento único histórico sem data de início registrada).
        regime = item.get("regime_execucao")
        if regime is None:
            regime = "unico" if vigencia_inicio is None else "continuado"

        if regime == "unico":
            parcelas.extend(_contrato_unico(item, contrato, camadas_permitidas))
        else:
            parcelas.extend(
                _contrato_continuado(
                    item, contrato, parametros, camadas_permitidas, sinais_premissas
                )
            )

    if algum_valido:
        motivo = None
    elif algum_sem_valor:
        motivo = "sem_valor"
    else:
        motivo = "sem_vigencia"
    return parcelas, motivo


def _contrato_unico(item, contrato, camadas_permitidas):
    """Pagamento único — mesma regra do motor antigo
    (`_camada_contratado_unico`): lança 100% no fim da vigência, ou 30 dias
    após a assinatura quando não há `vigencia_fim`."""

    vigencia_fim = contrato.get("vigencia_fim")
    data_assinatura = contrato.get("data_assinatura")

    if vigencia_fim is not None:
        competencia_data = vigencia_fim
    elif data_assinatura is not None:
        competencia_data = data_assinatura + timedelta(days=30)
    else:
        return []

    valor = contrato.get("valor")
    if valor is None:
        return []

    if "contratado" not in camadas_permitidas:
        return []

    instrumento = contrato.get("instrumento") or INSTRUMENTO_PRINCIPAL
    parcela = Parcela(
        item_pca=item["item_pca"],
        instrumento=instrumento,
        competencia=_competencia(competencia_data),
        valor=_quantizar(valor),
        camada="contratado",
        origem="calculo",
    )
    return [parcela]


def _contrato_continuado(item, contrato, parametros, camadas_permitidas, sinais_premissas):
    vigencia_inicio = contrato.get("vigencia_inicio")
    vigencia_fim = contrato.get("vigencia_fim")
    if vigencia_inicio is None:
        return []

    if vigencia_fim is None:
        vigencia_fim = _somar_meses(vigencia_inicio, 12) - timedelta(days=1)
        sinais_premissas["vigencia_sem_fim"].add(item["item_pca"])

    instrumento = contrato.get("instrumento") or INSTRUMENTO_PRINCIPAL
    segmentos = _segmentos_contrato(contrato, vigencia_inicio, vigencia_fim)

    parcelas = []
    if vigencia_fim >= parametros.horizonte_inicio:
        for segmento in segmentos:
            inicio_geracao = max(segmento["inicio"], parametros.horizonte_inicio)
            fim_geracao = min(segmento["fim"], parametros.horizonte_fim)
            if inicio_geracao > fim_geracao:
                continue
            meses = list(_iterar_meses(inicio_geracao, fim_geracao))
            eventos_no_segmento = _eventos_no_periodo(
                contrato, segmento["inicio"], segmento["fim"]
            )
            incluir_contratado = "contratado" in camadas_permitidas
            incluir_reajuste = "reajuste" in camadas_permitidas
            if segmento["periodicidade"] == "mensal":
                if incluir_contratado or incluir_reajuste:
                    parcelas.extend(
                        _gerar_contratado_reajuste_mensal(
                            item, instrumento, segmento, eventos_no_segmento, meses,
                            parametros, sinais_premissas, incluir_contratado, incluir_reajuste,
                        )
                    )
            else:
                if incluir_contratado:
                    parcelas.extend(
                        _gerar_camada_contratado(
                            item["item_pca"], instrumento, segmento, eventos_no_segmento, meses
                        )
                    )
                if incluir_reajuste:
                    parcelas.extend(
                        _gerar_camada_reajuste(
                            item, instrumento, segmento, eventos_no_segmento, meses,
                            parametros, sinais_premissas,
                        )
                    )

    ultimo_segmento = segmentos[-1] if segmentos else None
    if (
        item.get("renovacao_prevista")
        and vigencia_fim <= parametros.horizonte_fim
        and ultimo_segmento is not None
    ):
        eventos_ultimo = _eventos_no_periodo(
            contrato, ultimo_segmento["inicio"], ultimo_segmento["fim"]
        )
        valor_renovacao = _valor_base_mes(ultimo_segmento, eventos_ultimo, vigencia_fim)
        incluir_renovacao = "renovacao" in camadas_permitidas
        incluir_reajuste = "reajuste" in camadas_permitidas
        if incluir_renovacao or incluir_reajuste:
            parcelas.extend(
                _gerar_renovacao_e_reajuste(
                    item, instrumento, parametros, vigencia_fim, valor_renovacao,
                    ultimo_segmento["ancora"], sinais_premissas,
                    incluir_renovacao, incluir_reajuste,
                )
            )

    return parcelas


# --------------------------------------------------------------------------
# Segmentos de data-base (M02, spec §2.2) — cada contrato é dividido em
# segmentos `[inicio, fim]`; a âncora inicial é `data_base` do contrato (ou
# `vigencia_inicio`); todo evento de `reajuste`/`repactuacao` elegível (com
# `data` não nula) redefine a âncora E o valor-base a partir da sua própria
# data — os aniversários seguintes contam a partir da NOVA âncora, nunca da
# original. A fronteira do segmento é o primeiro dia do MÊS do evento (não o
# dia exato) — o mês do evento já usa o valor/âncora novos por inteiro, o
# que evita reajuste projetado duplicado no mesmo mês/ano de um evento real
# (a competência do evento cai inteira no segmento novo, cujo primeiro
# aniversário só chega um ano depois — nunca no próprio mês de entrada).


def _segmentos_contrato(contrato, vigencia_inicio, vigencia_fim):
    ancora_inicial = contrato.get("data_base") or vigencia_inicio
    valor_inicial = contrato.get("valor")
    periodicidade_inicial = contrato.get("periodicidade") or "global"

    eventos_reajuste = sorted(
        (
            e for e in (contrato.get("eventos") or [])
            if e.get("natureza") in ("reajuste", "repactuacao") and e.get("data") is not None
        ),
        key=lambda e: (e["data"], e["id"]),
    )

    pontos = []
    inicio_atual = vigencia_inicio
    ancora_atual = ancora_inicial
    valor_atual = valor_inicial
    periodicidade_atual = periodicidade_inicial

    for evento in eventos_reajuste:
        boundary = _primeiro_dia_mes(evento["data"])
        if boundary > inicio_atual:
            pontos.append((inicio_atual, ancora_atual, valor_atual, periodicidade_atual))
            inicio_atual = boundary
        ancora_atual = evento["data"]
        novo_valor = evento.get("valor_mensal")
        if novo_valor is None:
            novo_valor = evento.get("valor")
        if novo_valor is not None:
            valor_atual = novo_valor
        if evento.get("periodicidade"):
            periodicidade_atual = evento["periodicidade"]

    pontos.append((inicio_atual, ancora_atual, valor_atual, periodicidade_atual))

    segmentos = []
    for i, (inicio, ancora, valor_base, periodicidade) in enumerate(pontos):
        if i + 1 < len(pontos):
            fim = pontos[i + 1][0] - timedelta(days=1)
        else:
            fim = vigencia_fim
        segmentos.append(
            {
                "inicio": inicio,
                "fim": fim,
                "ancora": ancora,
                "valor_base": valor_base,
                "periodicidade": periodicidade or "global",
            }
        )
    return segmentos


def _eventos_no_periodo(contrato, inicio, fim):
    eventos = []
    for e in contrato.get("eventos") or []:
        d = e.get("data")
        if d is None or d < inicio or d > fim:
            continue
        eventos.append(e)
    return eventos


def _valor_base_mes(segmento, eventos_no_segmento, competencia_date):
    """Valor-base de UM mês, dado o segmento (âncora/valor/periodicidade
    fixos no segmento) e os eventos que caem dentro dele. Só `"mensal"`
    resolve substituição de valor por evento dentro do próprio segmento
    (ex. supressão/aditivo sem redefinir âncora, M05) — `"anual"`/`"global"`
    usam sempre o valor-base do segmento (o rateio é do segmento inteiro,
    não tem "mês vigente" isolado)."""

    periodicidade = segmento["periodicidade"]
    if periodicidade == "mensal":
        vigentes = [
            e for e in eventos_no_segmento
            if e.get("data") is not None and e["data"] <= competencia_date
        ]
        if vigentes:
            evento = max(vigentes, key=lambda e: (e["data"], e["id"]))
            valor = evento.get("valor_mensal")
            if valor is None:
                valor = evento.get("valor")
            if valor is not None:
                return valor
        return segmento["valor_base"]

    if periodicidade == "anual":
        mensal_base = segmento["valor_base"] / Decimal(12)
        fracao = _fracao_do_mes(competencia_date, segmento["inicio"], segmento["fim"])
        return mensal_base * fracao

    # "global" — rateio por peso temporal (M01): dias da competência dentro
    # do segmento ÷ dias TOTAIS do segmento (nunca meses de calendário).
    peso = _peso_dias_periodo(competencia_date, segmento["inicio"], segmento["fim"])
    return segmento["valor_base"] * peso


def _gerar_camada_contratado(item_pca, instrumento, segmento, eventos_no_segmento, meses):
    periodicidade = segmento["periodicidade"]
    if periodicidade == "mensal":
        # M03 — mensal usa o valor como está, SEM rateio nem proração de
        # ponta, mesmo em meses parciais do início/fim da vigência.
        parcelas = []
        for m in meses:
            valor = _valor_base_mes(segmento, eventos_no_segmento, m)
            parcelas.append(
                Parcela(
                    item_pca=item_pca,
                    instrumento=instrumento,
                    competencia=_competencia(m),
                    valor=_quantizar(valor),
                    camada="contratado",
                    origem="calculo",
                )
            )
        return parcelas

    pares = [(m, _valor_base_mes(segmento, eventos_no_segmento, m)) for m in meses]
    return _fechar_parcelas(item_pca, instrumento, "contratado", pares)


def _gerar_camada_reajuste(item, instrumento, segmento, eventos_no_segmento, meses, parametros, sinais_premissas):
    """Camada 3 — só a DIFERENÇA entre o valor com reajuste composto (a cada
    aniversário da âncora EFETIVA do segmento) e o valor-base do segmento
    naquele mês (camada 1, nunca ajustada)."""

    ancora = segmento["ancora"]
    cache_multiplicador = {}
    parcelas = []
    for m in meses:
        multiplicador = _multiplicador_reajuste_cache(
            cache_multiplicador, item, parametros, ancora, m, sinais_premissas
        )
        if multiplicador == Decimal("1"):
            continue
        valor_base = _valor_base_mes(segmento, eventos_no_segmento, m)
        valor_efetivo = valor_base * multiplicador
        diferenca = _quantizar(valor_efetivo - valor_base)
        if diferenca == 0:
            continue
        parcelas.append(
            Parcela(
                item_pca=item["item_pca"],
                instrumento=instrumento,
                competencia=_competencia(m),
                valor=diferenca,
                camada="reajuste",
                origem="calculo",
            )
        )
    return parcelas


def _gerar_contratado_reajuste_mensal(
    item, instrumento, segmento, eventos_no_segmento, meses, parametros, sinais_premissas,
    incluir_contratado, incluir_reajuste,
):
    """Mesma saída de `_gerar_camada_contratado`+`_gerar_camada_reajuste`
    combinados, só para `periodicidade == "mensal"` (o caso mais comum) —
    UM laço mensal em vez de dois, reaproveitando `_valor_base_mes`/
    `_competencia` já calculados para `"contratado"` também no cálculo do
    `"reajuste"` do mesmo mês (Fase 37, otimização de desempenho, spec §9).
    `"anual"`/`"global"` continuam pelas duas funções separadas — o rateio
    por lote (`_fechar_parcelas`) não tem o mesmo "valor do mês" avulso para
    reaproveitar."""

    ancora = segmento["ancora"]
    cache_multiplicador = {}
    parcelas = []
    for m in meses:
        competencia = _competencia(m)
        valor_base = _valor_base_mes(segmento, eventos_no_segmento, m)
        if incluir_contratado:
            parcelas.append(
                Parcela(
                    item_pca=item["item_pca"],
                    instrumento=instrumento,
                    competencia=competencia,
                    valor=_quantizar(valor_base),
                    camada="contratado",
                    origem="calculo",
                )
            )
        if incluir_reajuste:
            multiplicador = _multiplicador_reajuste_cache(
                cache_multiplicador, item, parametros, ancora, m, sinais_premissas
            )
            if multiplicador == Decimal("1"):
                continue
            diferenca = _quantizar(valor_base * multiplicador - valor_base)
            if diferenca == 0:
                continue
            parcelas.append(
                Parcela(
                    item_pca=item["item_pca"],
                    instrumento=instrumento,
                    competencia=competencia,
                    valor=diferenca,
                    camada="reajuste",
                    origem="calculo",
                )
            )
    return parcelas


def _gerar_renovacao_e_reajuste(
    item, instrumento, parametros, vigencia_fim, valor_base, ancora, sinais_premissas,
    incluir_renovacao, incluir_reajuste,
):
    """Camadas 2 e 3 durante a renovação, num ÚNICO laço mensal (Fase 37,
    otimização de desempenho — spec §9: motor ×2 por requisição dentro do
    orçamento; duas funções separadas percorrendo os MESMOS meses dobrava o
    custo de `_iterar_meses`/`_competencia` sem necessidade).

    Camada 2 (renovação) — continuidade presumida após `vigencia_fim`,
    valor igual à última mensalidade vigente ANTES de reajuste (camada
    SEPARADA de `contratado`). Camada 3 (M02, o bug central) — o reajuste
    CONTINUA gerando parcelas durante a renovação, com a MESMA âncora
    efetiva e o MESMO valor-base fixo da renovação (não mais a fração da
    vigência original, que não se aplica fora dela)."""

    inicio_renovacao = _proximo_mes(vigencia_fim)
    inicio_geracao = max(inicio_renovacao, parametros.horizonte_inicio)
    fim_geracao = parametros.horizonte_fim
    if inicio_geracao > fim_geracao:
        return []

    parcelas = []
    valor_quantizado = _quantizar(valor_base) if incluir_renovacao else None
    cache_multiplicador = {}
    for m in _iterar_meses(inicio_geracao, fim_geracao):
        competencia = _competencia(m)
        if incluir_renovacao:
            parcelas.append(
                Parcela(
                    item_pca=item["item_pca"],
                    instrumento=instrumento,
                    competencia=competencia,
                    valor=valor_quantizado,
                    camada="renovacao",
                    origem="calculo",
                )
            )
        if incluir_reajuste:
            multiplicador = _multiplicador_reajuste_cache(
                cache_multiplicador, item, parametros, ancora, m, sinais_premissas
            )
            if multiplicador == Decimal("1"):
                continue
            diferenca = _quantizar(valor_base * multiplicador - valor_base)
            if diferenca == 0:
                continue
            parcelas.append(
                Parcela(
                    item_pca=item["item_pca"],
                    instrumento=instrumento,
                    competencia=competencia,
                    valor=diferenca,
                    camada="reajuste",
                    origem="calculo",
                )
            )
    return parcelas


def _fechar_parcelas(item_pca, instrumento, camada, pares):
    """Quantização SÓ ao final do segmento contínuo de geração (M01) — o
    resíduo do arredondamento é somado à ÚLTIMA parcela emitida, para que
    `sum(parcelas) == quantizar(soma bruta)` sempre (nunca "meses de
    calendário e depois proporcionalidade diária", o defeito original)."""

    if not pares:
        return []

    soma_bruta = sum((v for _, v in pares), Decimal("0"))
    total_quantizado = _quantizar(soma_bruta)

    parcelas = []
    acumulado = Decimal("0")
    ultimo_indice = len(pares) - 1
    for i, (competencia_date, valor_bruto) in enumerate(pares):
        if i == ultimo_indice:
            valor = total_quantizado - acumulado
        else:
            valor = _quantizar(valor_bruto)
            acumulado += valor
        parcelas.append(
            Parcela(
                item_pca=item_pca,
                instrumento=instrumento,
                competencia=_competencia(competencia_date),
                valor=valor,
                camada=camada,
                origem="calculo",
            )
        )
    return parcelas


def _peso_dias_periodo(competencia_date, periodo_inicio, periodo_fim):
    """M01 — peso temporal que preserva o valor `"global"` na vigência
    completa: dias da competência dentro do período ÷ dias TOTAIS do
    período (`periodo_fim - periodo_inicio`, nunca meses de calendário)."""

    dias_no_mes = _dias_no_mes(competencia_date)
    dia_inicio = 1
    dia_fim = dias_no_mes
    if (competencia_date.year, competencia_date.month) == (
        periodo_inicio.year, periodo_inicio.month,
    ):
        dia_inicio = periodo_inicio.day
    if (competencia_date.year, competencia_date.month) == (
        periodo_fim.year, periodo_fim.month,
    ):
        dia_fim = periodo_fim.day
    dias_cobertos = dia_fim - dia_inicio + 1
    dias_totais = (periodo_fim - periodo_inicio).days + 1
    return Decimal(dias_cobertos) / Decimal(dias_totais)


def _primeiro_dia_mes(d):
    return date(d.year, d.month, 1)


# --------------------------------------------------------------------------
# Memória de cálculo (spec §2.3) — construída a partir das MESMAS parcelas
# já filtradas ao horizonte (1:1 Parcela -> LinhaMemoria), garantindo por
# construção que `sum(linhas por camada) == sum(parcelas por camada)`.


def _construir_memoria(item, contratos, parcelas):
    fontes = []
    descartados = []
    for contrato in contratos:
        instrumento = contrato.get("instrumento") or INSTRUMENTO_PRINCIPAL
        periodicidade = contrato.get("periodicidade") or "global"
        fontes.append(
            f"Contrato {instrumento}: vigência {_fmt_data(contrato.get('vigencia_inicio'))} "
            f"a {_fmt_data(contrato.get('vigencia_fim'))}, valor "
            f"{_fmt_moeda(contrato.get('valor'))} ({periodicidade})."
        )
        for evento in contrato.get("eventos") or []:
            if evento.get("data") is None:
                descartados.append(
                    f"descartado: evento sem data no contrato {instrumento}"
                )
                continue
            valor_evento = evento.get("valor_mensal")
            if valor_evento is None:
                valor_evento = evento.get("valor")
            fontes.append(
                f"Evento considerado: {evento.get('tipo') or evento.get('natureza') or 'evento'} "
                f"em {_fmt_data(evento['data'])}, valor {_fmt_moeda(valor_evento)} "
                f"({evento.get('periodicidade') or periodicidade})."
            )

    # `f"R$ {p.valor}"` em vez de `_fmt_moeda` (Fase 37, otimização de
    # desempenho): esta lista tem uma entrada por PARCELA (até dezenas de
    # milhares em cargas grandes), não por contrato/evento — a formatação
    # completa pt-BR (milhar com ponto) fica para a tela/XLSX do Plano
    # 37-04, que lê poucas linhas de cada vez (o item aberto na tela), não
    # o volume agregado de `projetar()` inteiro.
    linhas = [
        LinhaMemoria(
            competencia=p.competencia,
            camada=p.camada,
            valor=p.valor,
            formula=f"{ROTULOS_CAMADA.get(p.camada, p.camada)} ({p.instrumento}): R$ {p.valor}",
        )
        for p in parcelas
    ]

    return Memoria(
        item_pca=item["item_pca"], fontes=fontes, descartados=descartados, linhas=linhas
    )


def _construir_memoria_legado(item, parcelas):
    """Itens no formato ANTIGO (sem `contratos[]`) — memória mínima, só com
    as linhas (a fonte detalhada por instrumento não existe nesse formato,
    "limitação conhecida" — a origem completa só existe para itens
    já migrados ao `contratos[]` pela fronteira, `views_analise.py`)."""

    if not parcelas:
        return None
    linhas = [
        LinhaMemoria(
            competencia=p.competencia,
            camada=p.camada,
            valor=p.valor,
            formula=f"{ROTULOS_CAMADA.get(p.camada, p.camada)}: R$ {p.valor}",
        )
        for p in parcelas
    ]
    fontes = [
        "Registro no formato anterior ao contrato de entrada padronizado "
        "(Fase 37) — sem detalhamento por instrumento."
    ]
    return Memoria(item_pca=item["item_pca"], fontes=fontes, linhas=linhas)


def _fmt_data(d):
    return d.strftime("%d/%m/%Y") if d else "data não informada"


def _fmt_moeda(v):
    if v is None:
        return "valor não informado"
    inteiro, _, centavos = f"{v:,.2f}".partition(".")
    return f"R$ {inteiro.replace(',', '.')},{centavos}"


# ==========================================================================
# MOTOR ANTIGO — formato de item soltos (`valor_contratado`/`vigencia_*`/
# `eventos` no nível do item), Fase 36, INTOCADO por
# compatibilidade retroativa (ver docstring do módulo).


# --------------------------------------------------------------------------
# Camada 1 — Contratado (+ derivadas 2/3: renovação/reajuste)


def _camada_contratado_e_derivadas(item, parametros, camadas_permitidas, sinais_premissas):
    vigencia_inicio = item.get("vigencia_inicio")
    vigencia_fim = item.get("vigencia_fim")
    data_assinatura = item.get("data_assinatura_contrato")

    if vigencia_inicio is None and vigencia_fim is None and data_assinatura is None:
        return [], "sem_vigencia"

    regime = item.get("regime_execucao") or regime_presumido_projecao(
        vigencia_inicio, vigencia_fim
    )

    if regime == "unico":
        return _camada_contratado_unico(item, parametros, camadas_permitidas)

    return _camada_contratado_continuado(
        item, parametros, camadas_permitidas, sinais_premissas
    )


def _camada_contratado_unico(item, parametros, camadas_permitidas):
    vigencia_fim = item.get("vigencia_fim")
    data_assinatura = item.get("data_assinatura_contrato")

    if vigencia_fim is not None:
        competencia_data = vigencia_fim
    elif data_assinatura is not None:
        competencia_data = data_assinatura + timedelta(days=30)
    else:
        return [], "sem_vigencia"

    global_vigente, mensal_vigente = _resolver_global(item, competencia_data)
    valor = global_vigente if global_vigente is not None else mensal_vigente
    if valor is None:
        return [], "sem_valor"

    if "contratado" not in camadas_permitidas:
        return [], None

    parcela = Parcela(
        item_pca=item["item_pca"],
        instrumento=INSTRUMENTO_PRINCIPAL,
        competencia=_competencia(competencia_data),
        valor=_quantizar(valor),
        camada="contratado",
        origem="calculo",
    )
    return [parcela], None


def _camada_contratado_continuado(item, parametros, camadas_permitidas, sinais_premissas):
    item_pca = item["item_pca"]
    vigencia_inicio = item.get("vigencia_inicio")
    vigencia_fim = item.get("vigencia_fim")

    if vigencia_inicio is None:
        return [], "sem_vigencia"

    if vigencia_fim is None:
        vigencia_fim = _somar_meses(vigencia_inicio, 12) - timedelta(days=1)
        # Fase 36 (fix de apresentação): registra o ITEM no
        # sinal consolidado, nunca mais um append por linha — a mensagem
        # final ("N itens") é composta uma vez só em `_consolidar_premissas`.
        sinais_premissas["vigencia_sem_fim"].add(item_pca)

    global_inicial, mensal_inicial = _resolver_global(item, vigencia_inicio)
    if global_inicial is None and mensal_inicial is None:
        return [], "sem_valor"

    meses_vigencia = _meses_calendario(vigencia_inicio, vigencia_fim)

    parcelas = []
    if vigencia_fim >= parametros.horizonte_inicio:
        if "contratado" in camadas_permitidas:
            parcelas.extend(
                _distribuir_mensal(
                    item, parametros, vigencia_inicio, vigencia_fim,
                    meses_vigencia, "contratado",
                )
            )
        if "reajuste" in camadas_permitidas:
            parcelas.extend(
                _camada_reajuste(
                    item, parametros, vigencia_inicio, vigencia_fim,
                    meses_vigencia, sinais_premissas,
                )
            )

    if (
        item.get("renovacao_prevista")
        and vigencia_fim <= parametros.horizonte_fim
        and "renovacao" in camadas_permitidas
    ):
        valor_renovacao = _mensal_base_em(item, meses_vigencia, vigencia_fim)
        parcelas.extend(_camada_renovacao(item, parametros, vigencia_fim, valor_renovacao))

    return parcelas, None


def _camada_renovacao(item, parametros, vigencia_fim, valor_mensal):
    """Camada 2 (spec §3.2-2): continuidade presumida após `vigencia_fim`,
    valor igual à última parcela mensal ANTES de reajuste — camada SEPARADA
    de `contratado` (a diferença de reajuste, se houver, é sempre camada 3)."""

    inicio_renovacao = _proximo_mes(vigencia_fim)
    inicio_geracao = max(inicio_renovacao, parametros.horizonte_inicio)
    fim_geracao = parametros.horizonte_fim
    if inicio_geracao > fim_geracao:
        return []
    return [
        Parcela(
            item_pca=item["item_pca"],
            instrumento=INSTRUMENTO_PRINCIPAL,
            competencia=_competencia(c),
            valor=_quantizar(valor_mensal),
            camada="renovacao",
            origem="calculo",
        )
        for c in _iterar_meses(inicio_geracao, fim_geracao)
    ]


def _camada_reajuste(item, parametros, vigencia_inicio, vigencia_fim, meses_vigencia, sinais_premissas):
    """Camada 3 (spec §3.2-3): só a DIFERENÇA entre o valor com reajuste
    composto (a cada aniversário de `vigencia_inicio`) e o valor base
    (camada 1/2, nunca ajustado)."""

    inicio_geracao = max(vigencia_inicio, parametros.horizonte_inicio)
    fim_geracao = min(vigencia_fim, parametros.horizonte_fim)
    if inicio_geracao > fim_geracao:
        return []

    parcelas = []
    cache_multiplicador = {}
    for competencia_date in _iterar_meses(inicio_geracao, fim_geracao):
        multiplicador = _multiplicador_reajuste_cache(
            cache_multiplicador, item, parametros, vigencia_inicio, competencia_date,
            sinais_premissas,
        )
        if multiplicador == Decimal("1"):
            continue
        fracao = _fracao_do_mes(competencia_date, vigencia_inicio, vigencia_fim)
        mensal_base = _mensal_base_em(item, meses_vigencia, competencia_date)
        valor_base = mensal_base * fracao
        valor_efetivo = valor_base * multiplicador
        diferenca = _quantizar(valor_efetivo - valor_base)
        if diferenca == 0:
            continue
        parcelas.append(
            Parcela(
                item_pca=item["item_pca"],
                instrumento=INSTRUMENTO_PRINCIPAL,
                competencia=_competencia(competencia_date),
                valor=diferenca,
                camada="reajuste",
                origem="calculo",
            )
        )
    return parcelas


def _bucket_aniversario(ancora, competencia_date):
    """Mesmo cálculo de `_aniversarios_ate` (nº de anos completos desde a
    âncora), só que devolvendo UM inteiro em vez da lista — dois meses com o
    mesmo `_bucket_aniversario` produzem exatamente o mesmo multiplicador
    (Fase 37, otimização de desempenho: `_multiplicador_reajuste` refaz o
    produto acumulado do zero a cada chamada; sem cache, um contrato de 72
    meses recalcula o MESMO resultado até 72 vezes — orçamento de 500 itens
    × 72 meses × 2 chamadas, spec §2.4/§9)."""

    anos_completos = competencia_date.year - ancora.year
    if competencia_date.month < ancora.month:
        anos_completos -= 1
    return max(anos_completos, 0)


def _multiplicador_reajuste_cache(cache, item, parametros, ancora, competencia_date, sinais_premissas):
    """Memoiza `_multiplicador_reajuste` por `_bucket_aniversario` dentro de
    UMA chamada de `_gerar_camada_reajuste`/`_gerar_renovacao_e_reajuste`/
    `_camada_reajuste` (o `cache` é local ao loop do chamador, nunca global
    — cada contrato/segmento tem sua própria âncora, então reaproveitar
    entre segmentos diferentes seria incorreto). Sinais de premissa
    (`sinais_premissas`) continuam registrados normalmente na primeira vez
    que o bucket é calculado — o registro é por `(ano_aniversario, item)`
    num `set`, então recomputar o mesmo bucket de novo seria inofensivo,
    mas o cache evita até isso."""

    bucket = _bucket_aniversario(ancora, competencia_date)
    multiplicador = cache.get(bucket)
    if multiplicador is None:
        multiplicador = _multiplicador_reajuste(
            item, parametros, ancora, competencia_date, sinais_premissas
        )
        cache[bucket] = multiplicador
    return multiplicador


def _multiplicador_reajuste(item, parametros, vigencia_inicio, competencia_date, sinais_premissas):
    """Compartilhado pelos dois motores (a "âncora" pode ser
    `vigencia_inicio` do formato antigo ou a âncora efetiva de um segmento
    do formato novo — a função só precisa de uma data de referência para
    contar aniversários, nunca do resto do contrato)."""

    multiplicador = Decimal("1")
    for ano_aniversario in _aniversarios_ate(vigencia_inicio, competencia_date):
        percentual = parametros.indices.get(ano_aniversario)
        if percentual is None:
            anos_conhecidos = [a for a in parametros.indices if a <= ano_aniversario]
            if anos_conhecidos:
                ultimo_ano = max(anos_conhecidos)
                percentual = parametros.indices[ultimo_ano]
            else:
                # M10 (Fase 37) — sem NENHUM ano conhecido (`indices={}`),
                # o multiplicador continua 1,0 (nunca reajuste negativo
                # inventado), mas a premissa é registrada do mesmo jeito:
                # "índice sem valor" nunca pode ficar silencioso só porque
                # não há absolutamente nenhum ano de referência.
                ultimo_ano = None
                percentual = Decimal("0")
            # Fase 36 (fix de apresentação):
            # este bloco roda uma vez por MÊS da vigência (o loop de
            # `_camada_reajuste`/`_gerar_camada_reajuste`), então o mesmo
            # (ano, item) seria registrado dezenas de vezes sem o `set()`
            # abaixo — era exatamente o defeito reportado (1250 linhas/106
            # distintas). Só o fato bruto é guardado aqui; o texto final
            # ("N itens") é composto uma vez em `_consolidar_premissas`. A
            # REGRA de fallback (último ano conhecido) é a mesma de sempre.
            sinal = sinais_premissas["indices_ausentes"].setdefault(
                ano_aniversario,
                {"ultimo_ano": ultimo_ano, "percentual": percentual, "itens": set()},
            )
            sinal["itens"].add(item["item_pca"])
        multiplicador *= Decimal("1") + percentual / Decimal("100")
    return multiplicador


def _aniversarios_ate(vigencia_inicio, competencia_date):
    """Anos em que já ocorreu um aniversário de `vigencia_inicio` até
    `competencia_date` (inclusive) — o 1º aniversário é `vigencia_inicio.year
    + 1`, nunca o próprio ano de início."""

    anos_completos = competencia_date.year - vigencia_inicio.year
    if competencia_date.month < vigencia_inicio.month:
        anos_completos -= 1
    anos_completos = max(anos_completos, 0)
    return [vigencia_inicio.year + n for n in range(1, anos_completos + 1)]


# --------------------------------------------------------------------------
# Premissas — consolidação por tipo/ano (Fase 36, fix de
# apresentação). Entrada: `sinais_premissas` acumulado
# item a item durante o loop de `projetar()` (nunca por parcela/mês). Saída:
# NO MÁXIMO uma linha por tipo de premissa — "vigência sem fim" vira 1 linha
# com a contagem/lista de itens; "índice ausente" vira 1 linha por
# (ano-alvo, ano usado no fallback), também com a contagem de itens — nunca
# mais uma linha por item × mês. A regra de fallback do índice em si (último
# ano conhecido) não muda, só como ela é relatada.


def _consolidar_premissas(sinais_premissas, parametros):
    premissas = []

    itens_vigencia_sem_fim = sorted(sinais_premissas["vigencia_sem_fim"])
    if itens_vigencia_sem_fim:
        premissas.append(_premissa_vigencia_sem_fim(itens_vigencia_sem_fim))

    for ano_aniversario in sorted(sinais_premissas["indices_ausentes"]):
        dados = sinais_premissas["indices_ausentes"][ano_aniversario]
        premissas.append(_premissa_indice_ausente(ano_aniversario, dados, parametros))

    return premissas


def _premissa_vigencia_sem_fim(itens):
    plural = "item" if len(itens) == 1 else "itens"
    lista = ", ".join(str(item_pca) for item_pca in itens)
    return (
        f"Vigência final ausente, presumidos 12 meses a partir do início da "
        f"vigência: {len(itens)} {plural} ({lista})."
    )


def _premissa_indice_ausente(ano_aniversario, dados, parametros):
    itens = sorted(dados["itens"])
    plural = "item" if len(itens) == 1 else "itens"
    nome_indice = parametros.indice_nome or "reajuste"
    if dados["ultimo_ano"] is None:
        # M10 — nenhum ano cadastrado para o índice escolhido: nunca "zero
        # silencioso", a premissa diz explicitamente que não há base.
        return (
            f"Índice {nome_indice} sem valor cadastrado para {ano_aniversario}: "
            f"reajuste não projetado em {len(itens)} {plural}."
        )
    percentual_fmt = _formatar_percentual(dados["percentual"])
    return (
        f"Índice {nome_indice} sem valor para {ano_aniversario}: usado o de "
        f"{dados['ultimo_ano']} ({percentual_fmt}) em {len(itens)} {plural}."
    )


def _formatar_percentual(valor):
    return f"{valor:.2f}".replace(".", ",") + " %"


# --------------------------------------------------------------------------
# Camada 4 — Planejado (formato do item, comum aos dois motores — spec
# §2.1: "planejado não tem contratos, continua usando valor_estimado/
# mes_previsto/prazo_efetivo no nível do item").


def _camada_planejado(item, parametros):
    item_pca = item["item_pca"]
    mes_previsto = item.get("mes_previsto")
    prazo_efetivo = item.get("prazo_efetivo")

    data_mes_previsto = date(parametros.exercicio, mes_previsto, 1) if mes_previsto else None
    candidatos = [d for d in (data_mes_previsto, prazo_efetivo) if d is not None]
    if not candidatos:
        return [], "sem_mes_previsto"

    referencia = max(candidatos)
    inicio = referencia + timedelta(days=parametros.lead_time_mediano_dias)

    valor_estimado = item.get("valor_estimado")
    # M01 (Fase 37) — "valor estimado inteiro" significa valor INTEGRAL, sem
    # deságio, não "sem centavos": o truncamento para inteiro que existia
    # aqui removia os centavos de execução única (R$ 1.000,49 virava
    # R$ 1.000,00) — os centavos são preservados como estão, sem conversão.
    valor_estimado_integral = valor_estimado

    regime = item.get("regime_execucao") or "continuado"

    if regime == "unico":
        parcela = Parcela(
            item_pca=item_pca,
            instrumento=INSTRUMENTO_PRINCIPAL,
            competencia=_competencia(inicio),
            valor=valor_estimado_integral,
            camada="planejado",
            origem="calculo",
        )
        return [parcela], None

    fim = _somar_meses(inicio, 12) - timedelta(days=1)
    meses_vigencia = _meses_calendario(inicio, fim)
    mensal_fixo = _quantizar(valor_estimado_integral / meses_vigencia)

    item_para_distribuicao = dict(item)
    item_para_distribuicao["valor_mensal"] = mensal_fixo
    item_para_distribuicao["eventos"] = []

    parcelas = _distribuir_mensal(
        item_para_distribuicao, parametros, inicio, fim, meses_vigencia, "planejado"
    )
    return parcelas, None


# --------------------------------------------------------------------------
# Distribuição mensal genérica (contratado e planejado, formato ANTIGO)


def _distribuir_mensal(item, parametros, vigencia_inicio, vigencia_fim, meses_vigencia, camada):
    inicio_geracao = max(vigencia_inicio, parametros.horizonte_inicio)
    fim_geracao = min(vigencia_fim, parametros.horizonte_fim)
    if inicio_geracao > fim_geracao:
        return []

    meses = list(_iterar_meses(inicio_geracao, fim_geracao))
    valores_brutos = []
    soma_bruta = Decimal("0")
    for competencia_date in meses:
        fracao = _fracao_do_mes(competencia_date, vigencia_inicio, vigencia_fim)
        mensal_base = _mensal_base_em(item, meses_vigencia, competencia_date)
        valor_bruto = mensal_base * fracao
        valores_brutos.append((competencia_date, valor_bruto))
        soma_bruta += valor_bruto

    total_quantizado = _quantizar(soma_bruta)

    parcelas = []
    acumulado = Decimal("0")
    ultimo_indice = len(valores_brutos) - 1
    for i, (competencia_date, valor_bruto) in enumerate(valores_brutos):
        if i == ultimo_indice:
            valor = total_quantizado - acumulado
        else:
            valor = _quantizar(valor_bruto)
            acumulado += valor
        parcelas.append(
            Parcela(
                item_pca=item["item_pca"],
                instrumento=INSTRUMENTO_PRINCIPAL,
                competencia=_competencia(competencia_date),
                valor=valor,
                camada=camada,
                origem="calculo",
            )
        )
    return parcelas


def _mensal_base_em(item, meses_vigencia, referencia):
    global_vigente, mensal_vigente = _resolver_global(item, referencia)
    if mensal_vigente is not None:
        return mensal_vigente
    if global_vigente is None:
        return Decimal("0")
    return _quantizar(global_vigente / meses_vigencia)


def _resolver_global(item, referencia):
    """O global e o mensal vigentes em `referencia` vêm do último evento com
    `data <= referencia` (spec §3.2-1); sem série, cai para
    `valor_contratado`/`valor_mensal` do item."""

    eventos = [
        e for e in (item.get("eventos") or [])
        if e.get("data") is not None and e["data"] <= referencia
    ]
    if eventos:
        evento = max(eventos, key=lambda e: (e["data"], e.get("id", 0)))
        global_vigente = evento.get("valor")
        mensal_vigente = evento.get("valor_mensal")
        if global_vigente is None:
            global_vigente = item.get("valor_contratado")
        if mensal_vigente is None:
            mensal_vigente = item.get("valor_mensal")
        return global_vigente, mensal_vigente
    return item.get("valor_contratado"), item.get("valor_mensal")


# --------------------------------------------------------------------------
# Agregação (por_mes/por_ano/por_uo_ano/totais)


def _agregar(parcelas, itens, parametros):
    # `defaultdict` (Fase 37, otimização de desempenho — spec §9: motor ×2
    # por requisição dentro do orçamento) evita o padrão antigo
    # `setdefault(...)` + `.get(..., 0)` + atribuição — 3 buscas no dict por
    # parcela viram 1.
    uo_por_item = {item["item_pca"]: item.get("uo") for item in itens}

    por_mes = defaultdict(lambda: defaultdict(Decimal))
    por_ano = defaultdict(lambda: defaultdict(Decimal))
    por_uo_ano = defaultdict(lambda: defaultdict(Decimal))

    for p in parcelas:
        ano = int(p.competencia[:4])
        por_mes[p.competencia][p.camada] += p.valor
        por_ano[ano][p.camada] += p.valor
        por_uo_ano[uo_por_item.get(p.item_pca)][ano] += p.valor

    por_mes = {k: dict(v) for k, v in por_mes.items()}
    por_ano = {k: dict(v) for k, v in por_ano.items()}
    por_uo_ano = {k: dict(v) for k, v in por_uo_ano.items()}

    fim_exercicio_str = f"{parametros.exercicio:04d}-12"
    total_ate_fim_exercicio = sum(
        (
            valor
            for competencia, camadas in por_mes.items()
            if competencia <= fim_exercicio_str
            for valor in camadas.values()
        ),
        Decimal("0"),
    )
    total_proximo_ano = sum(
        por_ano.get(parametros.exercicio + 1, {}).values(), Decimal("0")
    )
    # M11 — os 5 EXERCÍCIOS SEGUINTES ao
    # corrente (exercicio+1..exercicio+5), sem misturar o restante do
    # exercício corrente (que já é o KPI "ate_fim_exercicio" acima). Chave
    # do dict mantida "cinco_anos" para não tocar mais arquivos.
    total_cinco_anos = sum(
        (
            valor
            for ano, camadas in por_ano.items()
            if parametros.exercicio + 1 <= ano <= parametros.exercicio + 5
            for valor in camadas.values()
        ),
        Decimal("0"),
    )
    total_geral = sum((p.valor for p in parcelas), Decimal("0"))
    total_contratado = sum(
        (p.valor for p in parcelas if p.camada == "contratado"), Decimal("0")
    )
    percentual_contratado = (
        _quantizar(total_contratado / total_geral * 100) if total_geral else Decimal("0")
    )

    totais = {
        "ate_fim_exercicio": total_ate_fim_exercicio,
        "proximo_ano": total_proximo_ano,
        # M11 — 5 exercícios SEGUINTES ao corrente (exercicio+1..+5), nunca
        # o exercício corrente (esse é "ate_fim_exercicio").
        "cinco_anos": total_cinco_anos,
        "percentual_contratado": percentual_contratado,
    }
    return por_mes, por_ano, por_uo_ano, totais


# --------------------------------------------------------------------------
# Utilitários de data/mês/arredondamento (compartilhados pelos dois motores)


def _quantizar(valor):
    return valor.quantize(DUAS_CASAS, rounding=ROUND_HALF_UP)


def _competencia(d):
    return f"{d.year:04d}-{d.month:02d}"


def _dias_no_mes(d):
    return monthrange(d.year, d.month)[1]


def _proximo_mes(d):
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def _iterar_meses(inicio, fim):
    atual = date(inicio.year, inicio.month, 1)
    limite = date(fim.year, fim.month, 1)
    while atual <= limite:
        yield atual
        atual = _proximo_mes(atual)


def _fracao_do_mes(competencia_date, vigencia_inicio, vigencia_fim):
    dias_no_mes = _dias_no_mes(competencia_date)
    dia_inicio = 1
    dia_fim = dias_no_mes
    if (competencia_date.year, competencia_date.month) == (
        vigencia_inicio.year, vigencia_inicio.month,
    ):
        dia_inicio = vigencia_inicio.day
    if (competencia_date.year, competencia_date.month) == (
        vigencia_fim.year, vigencia_fim.month,
    ):
        dia_fim = vigencia_fim.day
    dias_cobertos = dia_fim - dia_inicio + 1
    return Decimal(dias_cobertos) / Decimal(dias_no_mes)


def _meses_calendario(inicio, fim):
    return max((fim.year - inicio.year) * 12 + (fim.month - inicio.month) + 1, 1)


def _somar_meses(data_base, n):
    """Mesma técnica de `apps/pca/regras_situacao.py::_somar_meses`/
    `apps/pca/sei/extracao.py::_somar_meses` — copiada (não importada) para
    manter este módulo sem NENHUM import de fora da biblioteca padrão além
    de `regime_presumido_projecao` (a única dependência intra-projeto
    admitida, spec/interfaces do plano)."""

    mes_total = data_base.month - 1 + n
    ano = data_base.year + mes_total // 12
    mes = mes_total % 12 + 1
    proximo_mes = date(ano + 1, 1, 1) if mes == 12 else date(ano, mes + 1, 1)
    ultimo_dia_do_mes = (proximo_mes - timedelta(days=1)).day
    dia = min(data_base.day, ultimo_dia_do_mes)
    return date(ano, mes, dia)
