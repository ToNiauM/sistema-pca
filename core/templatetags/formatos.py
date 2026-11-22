from decimal import Decimal, InvalidOperation

from django import template
from django.utils.timezone import localdate

from apps.pca.models import Situacao

register = template.Library()


@register.filter(name="moeda")
def moeda(valor):
    """Formata um Decimal/número como "1.234,56" (pt-BR, sem prefixo "R$").

    O rótulo da coluna/do card já diz que é dinheiro; o
    prefixo "R$" saiu de toda a aplicação (tabela, dashboard, kanban,
    detalhe e export XLSX).

    Convenção de fundação Armadilha 22): nunca interpolar
    `{{ valor }}` cru em tela, formulário ou export — sempre por este
    filtro, para que os três lugares nunca divirjam entre si.
    """
    if valor is None or valor == "":
        return ""

    try:
        numero = Decimal(str(valor))
    except (InvalidOperation, ValueError, TypeError):
        return ""

    negativo = numero < 0
    numero = abs(numero)

    inteiro, _, decimais = f"{numero:.2f}".partition(".")

    grupos = []
    while len(inteiro) > 3:
        grupos.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    grupos.insert(0, inteiro)
    parte_inteira = ".".join(grupos)

    sinal = "-" if negativo else ""
    return f"{sinal}{parte_inteira},{decimais}"


@register.filter(name="moeda_curta")
def moeda_curta(valor):
    """Abrevia valores monetários para cards, sem o prefixo ``R$``.

    O Dashboard exibe uma casa decimal para manter os totais legíveis em
    cartões densos: ``165,4 mi`` e ``12,4 mil``. Valores abaixo de mil ficam
    na formatação monetária integral para não perder precisão relevante.
    """
    if valor is None or valor == "":
        return ""

    try:
        numero = Decimal(str(valor))
    except (InvalidOperation, ValueError, TypeError):
        return ""

    negativo = numero < 0
    numero = abs(numero)

    if numero >= Decimal("1000000"):
        abreviado = numero / Decimal("1000000")
        sufixo = " mi"
    elif numero >= Decimal("1000"):
        abreviado = numero / Decimal("1000")
        sufixo = " mil"
    else:
        return moeda(-numero if negativo else numero)

    sinal = "-" if negativo else ""
    return f"{sinal}{abreviado:.1f}".replace(".", ",") + sufixo


@register.filter(name="badge_percentual")
def badge_percentual(valor):
    """Fase 17 — formata o `badge` dos cards de KPI:
    percentual arredondado sem casas ("13%") ou "sem base" quando o
    denominador zerou (zero-safe: `None`, nunca `0` disfarçado).

    Filtro necessário porque a cadeia `|default:""|stringformat:"s"|add:"%"`
    não distingue "denominador zero" (deveria virar "sem base") de
    "percentual genuinamente 0%" (deveria virar "0%") — `default` dispara em
    qualquer valor falsy, inclusive `Decimal("0")`.
    """
    inteiro = _inteiro(valor)
    return "sem base" if inteiro is None else f"{inteiro}%"


def _inteiro(valor):
    """Arredondamento ÚNICO dos percentuais de apresentação: `f"{Decimal:.0f}"`
    (HALF_EVEN do contexto padrão do `decimal` — 12,5 → "12", 13,5 → "14"), o
    número que os 13 KPIs exibem desde a Fase 17. `None` quando sem base
    (`None`) ou inválido. `badge_percentual` e `percentual_inteiro` derivam
    daqui, para que texto visível, `aria-valuenow`, `aria-valuetext` e a
    largura da barra nunca divirjam."""
    if valor is None:
        return None
    try:
        numero = Decimal(str(valor))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return f"{numero:.0f}"


@register.filter(name="percentual_inteiro")
def percentual_inteiro(valor):
    """Mesmo arredondamento de
    `badge_percentual` (formatação `:.0f` de `Decimal`, HALF_EVEN), sem o
    sufixo; `"0"` quando sem base ou inválido (o `aria-valuenow` e o
    `style="width: N%"` das barras da Faixa de Volume precisam de número).
    Decisão: a barra e a AT se ajustam ao texto exibido, não o contrário —
    trocar o texto para `floatformat` (HALF_UP) alteraria valores mostrados
    (em espírito)."""
    inteiro = _inteiro(valor)
    return "0" if inteiro is None else inteiro


@register.filter(name="rotulo_situacao")
def rotulo_situacao(valor):
    """Fase 17 — resolve o rótulo humano de um valor cru
    de `Situacao` (ex. "no_prazo" -> "No prazo").

    Não dá para usar `p.get_situacao_display` aqui: esse método só resolve o
    valor GRAVADO na coluna `situacao`, mas o badge unificado
    (`_status_com_prazo.html`) exibe `situacao_efetiva` — a annotation de
    `para_listagem()` que corrige a leitura quando um processo gravado
    NO_PRAZO já tem `prazo_entrega` vencido. `situacao_efetiva` não é
    um `TextChoices`, é um valor de annotation puro, então não tem
    `get_FOO_display` disponível — é preciso resolver o rótulo manualmente
    contra `Situacao.choices`.
    """
    return dict(Situacao.choices).get(valor, valor)


@register.filter(name="dias_desde")
def dias_desde(data):
    """Conta dias corridos desde uma DateField em horário local do projeto."""
    return (localdate() - data).days if data is not None else ""
