"""Simulação de variáveis do fluxo de caixa projetado (Fase 37,
documento interno de desenho
§0 decisão 4, §3.1). Módulo PURO — mesmo padrão de `apps/pca/projecao/
fluxo.py`: nenhum `import django`/`from django`, nenhum ORM, nenhum request.

Decisão A do §0 ("ajustes como transformação da entrada"): `aplicar()`
transforma `itens`/`parametros` — o formato de entrada que `fluxo.projetar`
já consome — em cópias ajustadas, e devolve as duas; o motor
em si (`fluxo.py`) continua sem saber que simulação existe, chamado 2x pela
view (oficial + simulado, spec §3.4).

`Ajustes` é `frozen` (nunca mutado depois de criado) e sempre percorrido por
CÓPIA em `aplicar()` — a garantia central do módulo (spec §10):
`aplicar(itens, parametros, ajustes)` NUNCA muta `itens`/`parametros` de
entrada, e `de_json(para_json(a)) == a` para qualquer `Ajustes`.

`de_json` é a fronteira de um valor vindo da SESSÃO do usuário (mitigado pela VIEW antes de gravar em `request.session`) — mesmo assim,
`de_json` nunca lança em entrada malformada: cada campo cai no seu default
(dict/set vazio, `lead_time_dias=None`) quando o valor bruto não corresponde
ao formato esperado, em vez de derrubar a página."""

from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class Ajustes:
    """As 6 variáveis editáveis pela simulação (spec §0 decisão 4/§3.1)."""

    indices_por_ano: dict = field(default_factory=dict)  # {int ano: Decimal percentual}
    itens_excluidos: set = field(default_factory=set)  # {int item_pca}
    renovacao_por_item: dict = field(default_factory=dict)  # {int item_pca: bool}
    valor_por_item: dict = field(default_factory=dict)  # {int item_pca: Decimal}
    inicio_por_item: dict = field(default_factory=dict)  # {int item_pca: date}
    lead_time_dias: int = None


def vazio():
    """`Ajustes` sem nenhuma variável alterada — o rascunho "limpo" (mesmo
    estado de "voltar ao oficial", spec §3.2)."""
    return Ajustes()


def aplicar(itens, parametros, ajustes):
    """Transforma `itens`/`parametros` conforme `ajustes` (spec §3.1) — só
    reescreve chaves que `fluxo.py` já entende (`contratos`/`valor_estimado`/
    `mes_previsto`/`prazo_efetivo`/`renovacao_prevista`, mais
    `Parametros.indices`/`lead_time_mediano_dias`), nunca introduz chave
    nova. Sempre trabalha sobre CÓPIAS — nenhum dict/objeto de entrada é
    mutado (spec §10).

    Ordem (spec/ `parametros2` primeiro, para `inicio_por_item`
    usar o `lead_time_mediano_dias` JÁ ajustado): índices/lead time em
    `parametros2` → por item, `renovacao_por_item` → `valor_por_item` →
    `inicio_por_item` (só quando o item não tem `contratos`, isto é,
    planejado)."""
    parametros2 = replace(
        parametros,
        indices={**parametros.indices, **ajustes.indices_por_ano},
        lead_time_mediano_dias=(
            ajustes.lead_time_dias
            if ajustes.lead_time_dias is not None
            else parametros.lead_time_mediano_dias
        ),
    )

    itens2 = []
    for item in itens:
        item_pca = item["item_pca"]
        if item_pca in ajustes.itens_excluidos:
            continue

        item2 = dict(item)
        item2["contratos"] = [dict(c) for c in (item.get("contratos") or [])]

        if item_pca in ajustes.renovacao_por_item:
            item2["renovacao_prevista"] = ajustes.renovacao_por_item[item_pca]

        if item_pca in ajustes.valor_por_item:
            novo_valor = ajustes.valor_por_item[item_pca]
            if item2["contratos"]:
                item2["contratos"][0]["valor"] = novo_valor
            else:
                item2["valor_estimado"] = novo_valor

        if item_pca in ajustes.inicio_por_item and not item2["contratos"]:
            inicio_desejado = ajustes.inicio_por_item[item_pca]
            item2["prazo_efetivo"] = inicio_desejado - timedelta(
                days=parametros2.lead_time_mediano_dias
            )
            item2["mes_previsto"] = None

        itens2.append(item2)

    return itens2, parametros2


# --------------------------------------------------------------------------
# Serialização (spec §3.2 — o rascunho vive em `request.session["fluxo_
# ajustes"]`, um JSON puro; chaves de dict JSON são sempre string, por isso
# `int` vira `str` na ida e volta em `para_json`/`de_json`).


def para_json(a):
    """`Ajustes` → dict serializável por `json.dumps` (Decimal/date/set
    viram str/isoformat/list)."""
    return {
        "indices_por_ano": {
            str(ano): str(percentual) for ano, percentual in a.indices_por_ano.items()
        },
        "itens_excluidos": sorted(a.itens_excluidos),
        "renovacao_por_item": {
            str(item_pca): bool(valor) for item_pca, valor in a.renovacao_por_item.items()
        },
        "valor_por_item": {
            str(item_pca): str(valor) for item_pca, valor in a.valor_por_item.items()
        },
        "inicio_por_item": {
            str(item_pca): data.isoformat() for item_pca, data in a.inicio_por_item.items()
        },
        "lead_time_dias": a.lead_time_dias,
    }


def de_json(d):
    """dict (vindo de `request.session`/JSON) → `Ajustes` — NUNCA lança:
    entrada que não é um dict, ou um campo em formato inesperado, cai no
    default daquele campo."""
    if not isinstance(d, dict):
        return vazio()

    return Ajustes(
        indices_por_ano=_dict_ano_decimal(d.get("indices_por_ano")),
        itens_excluidos=_set_int(d.get("itens_excluidos")),
        renovacao_por_item=_dict_int_bool(d.get("renovacao_por_item")),
        valor_por_item=_dict_int_decimal(d.get("valor_por_item")),
        inicio_por_item=_dict_int_date(d.get("inicio_por_item")),
        lead_time_dias=_int_ou_none(d.get("lead_time_dias")),
    )


def _dict_ano_decimal(bruto):
    resultado = {}
    if not isinstance(bruto, dict):
        return resultado
    for chave, valor in bruto.items():
        try:
            ano = int(chave)
            percentual = Decimal(str(valor))
        except (TypeError, ValueError, InvalidOperation):
            continue
        # QA 30/09/2026 (achado INFO I2) — `Decimal("NaN")`/`Decimal(
        # "Infinity")` são construções VÁLIDAS (não levantam
        # `InvalidOperation`); um `CenarioFluxo` editado manualmente pelo
        # Admin (LGPD) pode carregar um dos dois — descartado aqui, nunca
        # propagado para `aplicar()`/`_comparacao`.
        if not percentual.is_finite():
            continue
        resultado[ano] = percentual
    return resultado


def _set_int(bruto):
    resultado = set()
    if not isinstance(bruto, (list, tuple, set)):
        return resultado
    for valor in bruto:
        try:
            resultado.add(int(valor))
        except (TypeError, ValueError):
            continue
    return resultado


def _dict_int_bool(bruto):
    resultado = {}
    if not isinstance(bruto, dict):
        return resultado
    for chave, valor in bruto.items():
        try:
            item_pca = int(chave)
        except (TypeError, ValueError):
            continue
        resultado[item_pca] = bool(valor)
    return resultado


def _dict_int_decimal(bruto):
    resultado = {}
    if not isinstance(bruto, dict):
        return resultado
    for chave, valor in bruto.items():
        try:
            item_pca = int(chave)
            valor_decimal = Decimal(str(valor))
        except (TypeError, ValueError, InvalidOperation):
            continue
        # QA 30/09/2026 (achado INFO I2) — mesmo descarte de não finitos
        # de `_dict_ano_decimal` acima.
        if not valor_decimal.is_finite():
            continue
        resultado[item_pca] = valor_decimal
    return resultado


def _dict_int_date(bruto):
    resultado = {}
    if not isinstance(bruto, dict):
        return resultado
    for chave, valor in bruto.items():
        try:
            item_pca = int(chave)
            data = date.fromisoformat(str(valor))
        except (TypeError, ValueError):
            continue
        resultado[item_pca] = data
    return resultado


def _int_ou_none(bruto):
    if bruto is None:
        return None
    try:
        return int(bruto)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# Descrição legível (spec §3.3/§3.4 — faixa "Simulação ativa" no topo da
# tela; painel "Simular"/lista de contratações não recalculam nada aqui, só
# leem `Ajustes` já resolvido).


def descrever(a, rotulos=None):
    """Uma string por variável alterada, em português, citando o rótulo do
    item quando disponível (`rotulos.get(item_pca, f"Item {item_pca}")`)."""
    rotulos = rotulos or {}
    linhas = []

    for ano in sorted(a.indices_por_ano):
        linhas.append(
            f"Índice de {ano} alterado para {_formatar_percentual(a.indices_por_ano[ano])}"
        )

    for item_pca in sorted(a.itens_excluidos):
        linhas.append(f"{_rotulo_item(item_pca, rotulos)} excluído da simulação")

    for item_pca in sorted(a.renovacao_por_item):
        acao = "marcada" if a.renovacao_por_item[item_pca] else "desmarcada"
        linhas.append(f"{_rotulo_item(item_pca, rotulos)}: renovação {acao}")

    for item_pca in sorted(a.valor_por_item):
        valor_fmt = _formatar_moeda(a.valor_por_item[item_pca])
        linhas.append(f"{_rotulo_item(item_pca, rotulos)}: valor alterado para {valor_fmt}")

    for item_pca in sorted(a.inicio_por_item):
        data_fmt = a.inicio_por_item[item_pca].strftime("%d/%m/%Y")
        linhas.append(f"{_rotulo_item(item_pca, rotulos)}: início deslocado para {data_fmt}")

    if a.lead_time_dias is not None:
        linhas.append(f"Lead time alterado para {a.lead_time_dias} dias")

    return linhas


def _rotulo_item(item_pca, rotulos):
    return rotulos.get(item_pca, f"Item {item_pca}")


def _formatar_percentual(valor):
    return f"{valor:.2f}".replace(".", ",") + "%"


def _formatar_moeda(valor):
    inteiro, _, centavos = f"{valor:,.2f}".partition(".")
    return f"R$ {inteiro.replace(',', '.')},{centavos}"
