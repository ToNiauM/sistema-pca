"""Template tags e filtros padrão da skill dsgov."""

from datetime import date, datetime
from decimal import Decimal
from urllib.parse import urlencode

from django import template
from django.utils import formats
from django.utils.safestring import mark_safe

register = template.Library()


# ---------- querystring ----------
@register.simple_tag(takes_context=True)
def url_com(context, **novos):
    """URL atual preservando a querystring e substituindo/removendo parâmetros.

    {% url_com pagina=3 %}  → mantém filtros e ordenação, troca a página.
    {% url_com ordenar="-nome" pagina=None %} → remove `pagina`.
    """
    request = context["request"]
    params = request.GET.copy()
    for chave, valor in novos.items():
        if valor is None or valor == "":
            params.pop(chave, None)
        else:
            params[chave] = valor
    codificado = params.urlencode()
    return f"{request.path}?{codificado}" if codificado else request.path


@register.simple_tag(takes_context=True)
def ordenar_por(context, campo, rotulo):
    """Cabeçalho de coluna ordenável. Ciclo: nenhum → asc → desc → nenhum, com ícone do DS."""
    request = context["request"]
    atual = request.GET.get("ordenar", "")
    if atual == campo:
        proximo, icone, aria = f"-{campo}", "fa-sort-up", "ascending"
    elif atual == f"-{campo}":
        proximo, icone, aria = "", "fa-sort-down", "descending"
    else:
        proximo, icone, aria = campo, "fa-sort", "none"
    params = request.GET.copy()
    params.pop("pagina", None)
    if proximo:
        params["ordenar"] = proximo
    else:
        params.pop("ordenar", None)
    href = f"{request.path}?{params.urlencode()}" if params else request.path
    return mark_safe(
        f'<a class="dsgov-ordenar" href="{href}" aria-sort="{aria}" hx-get="{href}" hx-target="#listagem" '
        f'hx-push-url="true">{rotulo} <i class="fas {icone}" aria-hidden="true"></i></a>'
    )


# ---------- formatação pt-BR ----------
@register.filter
def moeda(valor):
    if valor is None or valor == "":
        return "—"
    try:
        valor = Decimal(str(valor))
    except Exception:
        return valor
    inteiro, _, decimais = f"{valor:,.2f}".partition(".")
    return f"R$ {inteiro.replace(',', '.')},{decimais}"


@register.filter
def numero(valor, casas=0):
    if valor is None or valor == "":
        return "—"
    try:
        return formats.number_format(valor, decimal_pos=int(casas), use_l10n=True, force_grouping=True)
    except Exception:
        return valor


@register.filter
def percentual(valor, casas=1):
    if valor is None or valor == "":
        return "—"
    try:
        return f"{numero(valor, casas)}%"
    except Exception:
        return valor


@register.filter
def data_br(valor):
    if not valor:
        return "—"
    if isinstance(valor, datetime):
        return formats.date_format(valor, "d/m/Y H:i")
    if isinstance(valor, date):
        return formats.date_format(valor, "d/m/Y")
    return valor


@register.filter
def cpf(valor):
    d = "".join(c for c in str(valor or "") if c.isdigit())
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:11]}" if len(d) == 11 else (valor or "—")


@register.filter
def cnpj(valor):
    d = "".join(c for c in str(valor or "") if c.isdigit())
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:14]}" if len(d) == 14 else (valor or "—")


@register.filter
def ou_traco(valor):
    return valor if valor not in (None, "", []) else "—"


@register.filter
def atributo(objeto, caminho):
    """Acesso dinâmico: {{ obj|atributo:"unidade.nome" }}. Chama métodos sem argumentos."""
    atual = objeto
    for parte in str(caminho).split("."):
        if atual is None:
            return None
        atual = getattr(atual, parte, None)
        if callable(atual):
            atual = atual()
    return atual


@register.filter
def exibir(objeto, coluna):
    """Formata o valor de uma coluna de listagem conforme coluna['tipo']."""
    valor = atributo(objeto, coluna["campo"])
    tipo = coluna.get("tipo", "texto")
    if tipo == "moeda":
        return moeda(valor)
    if tipo == "data":
        return data_br(valor)
    if tipo == "numero":
        return numero(valor, coluna.get("casas", 0))
    if tipo == "percentual":
        return percentual(valor, coluna.get("casas", 1))
    if tipo == "booleano":
        return "Sim" if valor else "Não"
    return ou_traco(valor)


# ---------- suporte ao br-select ----------
@register.filter
def lista_str(valor):
    if valor is None:
        return []
    if isinstance(valor, (list, tuple)):
        return [str(v) for v in valor]
    return [str(valor)]


@register.filter
def opcoes_select(widget, valor):
    """Gera os optgroups do widget Select como o Django faz (widget.optgroups)."""
    return widget.optgroups("", valor or [])


# ---------- status ----------
@register.filter
def classe_status(chave):
    """Mapeia uma chave semântica para a classe de cor da br-tag status."""
    mapa = {
        "sucesso": "bg-success", "concluido": "bg-success", "ativo": "bg-success",
        "alerta": "bg-warning text-gray-80", "pendente": "bg-warning text-gray-80",
        "erro": "bg-danger", "atrasado": "bg-danger", "cancelado": "bg-gray-50",
        "info": "bg-info", "andamento": "bg-info", "neutro": "bg-gray-50", "inativo": "bg-gray-50",
    }
    return mapa.get(str(chave), "bg-info")


@register.inclusion_tag("dsgov/_tag_status.html")
def tag_status(rotulo, chave="info"):
    return {"rotulo": rotulo, "classe": classe_status(chave)}


# ---------- paginação ----------
@register.inclusion_tag("dsgov/_paginacao.html", takes_context=True)
def paginacao(context, pagina_obj, alvo="#listagem"):
    request = context["request"]
    paginator = pagina_obj.paginator
    numero_atual = pagina_obj.number
    inicio = (numero_atual - 1) * paginator.per_page + 1
    fim = min(numero_atual * paginator.per_page, paginator.count)
    return {
        "request": request,
        "pagina": pagina_obj,
        "inicio": inicio if paginator.count else 0,
        "fim": fim,
        "total": paginator.count,
        "por_pagina": paginator.per_page,
        "opcoes_por_pagina": context.get("opcoes_por_pagina", (10, 20, 50)),
        "alvo": alvo,
        "paginas": pagina_obj.paginator.get_elided_page_range(numero_atual, on_each_side=1, on_ends=1),
        "reticencias": paginator.ELLIPSIS,
    }
