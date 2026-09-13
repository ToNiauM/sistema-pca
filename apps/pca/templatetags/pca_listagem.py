"""Filtros de apresentação exclusivos da tela Processos. Não pertence a
core/templatetags/dsgov.py: nome_mes/rotulo_situacao são vocabulário de
domínio, reaproveitando as mesmas fontes de verdade da tela."""

from django import template
from django.utils.safestring import mark_safe

from apps.pca.filtros import NOMES_MES
from apps.pca.models import Situacao

register = template.Library()


@register.filter
def nome_mes(numero):
    """Nome do mês previsto (1-12) em português; este filtro só formata a
    apresentação, o valor armazenado continua inteiro."""
    if not numero:
        return None
    return NOMES_MES.get(int(numero))


@register.filter
def rotulo_situacao(valor):
    """Rótulo humano de um valor cru de Situacao (ex. "no_prazo" -> "No
    prazo")."""
    return dict(Situacao.choices).get(valor, valor)


# mapa projeto-inteiro de situacao_efetiva (valor cru) para a chave
# semântica de core.templatetags.dsgov.classe_status/CORES_STATUS. Única
# fonte de verdade, reaproveitada pelas tags {% tag_status %} e pelos
# gráficos — nunca dois mapeamentos divergentes para a mesma condição.
CLASSE_SITUACAO_EFETIVA = {
    Situacao.CONCLUIDO.value: "concluido",
    Situacao.ATRASADO.value: "atrasado",
    Situacao.EM_TRAMITACAO.value: "andamento",
    Situacao.NO_PRAZO.value: "pendente",
}


@register.filter
def classe_situacao(valor):
    """Chave semântica para um valor cru de situacao_efetiva. Cancelado
    nunca passa por aqui: os templates resolvem "Cancelado" à parte."""
    return CLASSE_SITUACAO_EFETIVA.get(valor, "info")


@register.simple_tag(takes_context=True)
def ordenar_por_tabela(context, campo, rotulo):
    """Cabeçalho ordenável da tela Processos: ícone + hx-get para
    #listagem, respeitando o contrato de dois parâmetros GET (ordenar +
    dir). Ciclo: coluna nova sempre começa ascendente; coluna já ativa
    inverte, sem "nenhum" intermediário."""
    request = context["request"]
    ordenar_atual = request.GET.get("ordenar", "")
    dir_atual = request.GET.get("dir", "asc")
    ativa = ordenar_atual == campo
    proxima_direcao = "desc" if (ativa and dir_atual == "asc") else "asc"
    if not ativa:
        icone, aria = "fa-sort", "none"
    elif dir_atual == "asc":
        icone, aria = "fa-sort-up", "ascending"
    else:
        icone, aria = "fa-sort-down", "descending"
    params = request.GET.copy()
    params.pop("pagina", None)
    params["ordenar"] = campo
    params["dir"] = proxima_direcao
    href = f"{request.path}?{params.urlencode()}"
    return mark_safe(
        f'<a class="dsgov-ordenar" href="{href}" aria-sort="{aria}" hx-get="{href}" '
        f'hx-target="#listagem" hx-push-url="true">{rotulo} '
        f'<i class="fas {icone}" aria-hidden="true"></i></a>'
    )
