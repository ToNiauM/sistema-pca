"""Tags do domínio PCA para a casca Tabler (PCA_DESIGN=tabler): as mesmas de pca_listagem/sei_links,
com o HTML trocado pelo do Tabler onde elas geram markup."""

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

from apps.pca.templatetags import pca_listagem as _listagem
from apps.pca.templatetags import sei_links as _sei
from core.templatetags.ui import _cabecalho

register = template.Library()

for _nome in ("nome_mes", "rotulo_situacao", "classe_situacao"):
    register.filter(_nome, getattr(_listagem, _nome))
register.filter("linkar_sei", _sei.linkar_sei)
for _nome, _f in _listagem.register.filters.items():
    register.filters.setdefault(_nome, _f)
for _nome, _f in _sei.register.filters.items():
    if _nome != "link_sei":
        register.filters.setdefault(_nome, _f)


@register.simple_tag(takes_context=True)
def ordenar_por_tabela(context, campo, rotulo):
    """Cabeçalho ordenável da tela Processos (dois parâmetros: `ordenar` + `dir`); coluna nova começa ascendente,
    coluna ativa inverte."""
    request = context["request"]
    ativa = request.GET.get("ordenar", "") == campo
    dir_atual = request.GET.get("dir", "asc")
    proxima = "desc" if (ativa and dir_atual == "asc") else "asc"
    aria = "none" if not ativa else ("ascending" if dir_atual == "asc" else "descending")
    params = request.GET.copy()
    params.pop("pagina", None)
    params["ordenar"] = campo
    params["dir"] = proxima
    return _cabecalho(f"{request.path}?{params.urlencode()}", rotulo, aria)


@register.filter
def link_sei(numero_sei):
    """Número de processo SEI como link; selo de aviso quando a resolução não achou o processo."""
    resultado = _sei.link_sei(numero_sei)
    if isinstance(resultado, str) and "não encontrado no SEI" in resultado and "<span" in resultado:
        return mark_safe(f'{escape(numero_sei)} <span class="badge bg-orange-lt">não encontrado no SEI</span>')
    return resultado
