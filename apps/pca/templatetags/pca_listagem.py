"""Filtros de apresentação exclusivos da tela Processos (Fase 26).

Não pertence a `core/templatetags/dsgov.py` (módulo fixo do padrão DSGov) —
`nome_mes`/`rotulo_situacao` são vocabulário de DOMÍNIO (mês previsto/
situação do PCA), não do padrão dsgov em si. Reaproveita as mesmas fontes de
verdade que a tela usava antes (`apps/pca/filtros.NOMES_MES`,
`apps/pca/models.Situacao`), sem duplicar o mapeamento.
"""

from django import template
from django.utils.safestring import mark_safe

from apps.pca.filtros import NOMES_MES
from apps.pca.models import Situacao

register = template.Library()


@register.filter
def nome_mes(numero):
    """Nome do mês previsto (1-12) em português. O valor armazenado
    continua inteiro (documento do projeto § Constraints — mês previsto ordena
    corretamente porque não é texto no banco); este filtro só formata a
    APRESENTAÇÃO."""
    if not numero:
        return None
    return NOMES_MES.get(int(numero))


@register.filter
def rotulo_situacao(valor):
    """Rótulo humano de um valor cru de `Situacao` (ex. "no_prazo" -> "No
    prazo") — mesma resolução de `core.templatetags.formatos.rotulo_situacao`
    (Fase 17), reaproveitada aqui para não misturar dois `{% load %}`
    concorrentes nos templates migrados ao padrão `{% load dsgov %}`."""
    return dict(Situacao.choices).get(valor, valor)


# achado de revisão nas capturas) — MAPA PROJETO-INTEIRO de `situacao_efetiva` (valor cru
# de `Situacao`, ex. "no_prazo") para a chave semântica de
# `core.templatetags.dsgov.classe_status`/`core.graficos.CORES_STATUS`.
# ÚNICA fonte de verdade, reaproveitada TANTO pelas tags `{% tag_status %}`
# (`_tabela_situacao.html`/`_calendario_grade.html`/`analise.html`, via o
# filtro abaixo) QUANTO pelos gráficos (`apps.pca.graficos_pca.
# MAPA_SITUACAO_STATUS`, chaveado pelo RÓTULO em vez do valor cru, mas com
# os MESMOS 5 destinos) — nunca dois mapeamentos divergentes para a mesma
# condição. Antes desta quick, "no_prazo" e "em_tramitacao" caíam os dois
# no fallback "bg-info" de `classe_status` (mesma cor); agora "no_prazo" ->
# "pendente" (amarelo, `bg-warning text-gray-80`) e "em_tramitacao" ->
# "andamento" (azul, `bg-info`) — nunca compartilham cor.
CLASSE_SITUACAO_EFETIVA = {
    Situacao.CONCLUIDO.value: "concluido",
    Situacao.ATRASADO.value: "atrasado",
    Situacao.EM_TRAMITACAO.value: "andamento",
    Situacao.NO_PRAZO.value: "pendente",
}


@register.filter
def classe_situacao(valor):
    """Chave semântica (destino de `{% tag_status rotulo chave %}`) para um
    valor cru de `situacao_efetiva` — ver `CLASSE_SITUACAO_EFETIVA` acima.
    Cancelado NUNCA passa por aqui (é o eixo Estado, não Situação; os
    templates continuam resolvendo "Cancelado"/"cancelado" à parte)."""
    return CLASSE_SITUACAO_EFETIVA.get(valor, "info")


@register.simple_tag(takes_context=True)
def ordenar_por_tabela(context, campo, rotulo):
    """Cabeçalho ordenável da tela Processos — mesma UI de
    `{% ordenar_por %}` do padrão DSGov (ícone + `hx-get` para `#listagem`), mas
    respeitando o contrato de DOIS parâmetros GET (`ordenar` + `dir`) de
    `apps/pca/filtros.py::ordenacao_valida`/`direcao_valida`/
    `_cabecalhos_ordenaveis` (`filtros.py` intocado nesta
    fase). A tag genérica do padrão DSGov codifica a direção num único parâmetro
    (`ordenar=-campo`) — incompatível com essa allowlist fechada sem
    editar `filtros.py`, fora do escopo. Ciclo: coluna nova
    sempre começa ascendente; coluna já ativa inverte (mesma regra de
    `apps/pca/views.py::_cabecalhos_ordenaveis`, sem "nenhum" intermediário
    — clicar de novo na coluna ativa nunca remove a ordenação, só inverte)."""
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
