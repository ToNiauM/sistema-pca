"""Tags e filtros da casca Tabler (PCA_DESIGN=tabler).

Os templates de tabler/templates/ carregam só esta biblioteca (`{% load ui %}`): ela reaproveita a formatação
pt-BR e os utilitários de listagem já existentes e troca apenas o que gera HTML — cabeçalho ordenável, selo de
situação e paginação — pelo markup do Tabler. Não muda nenhuma regra de negócio.
"""

from django import template
from django.utils.safestring import mark_safe

from core.templatetags import dsgov as _base
from core.templatetags import formatos as _formatos

register = template.Library()

# Formatação e utilitários sem HTML: os mesmos de sempre.
for _nome in ("url_com",):
    register.simple_tag(takes_context=True)(getattr(_base, _nome))
for _nome in ("numero", "percentual", "data_br", "cpf", "cnpj", "ou_traco", "atributo", "exibir", "lista_str", "opcoes_select"):
    register.filter(_nome, getattr(_base, _nome))
register.filter("moeda", _formatos.moeda)
for _nome in ("moeda_curta", "badge_percentual", "percentual_inteiro", "dias_desde"):
    register.filter(_nome, getattr(_formatos, _nome))
register.filter("rotulo_situacao_padrao", _formatos.rotulo_situacao)

# Chave semântica de situação → cor do Tabler (selo "-lt" e cor sólida para pontos de status).
CORES = {
    "sucesso": "green", "concluido": "green", "ativo": "green",
    "alerta": "yellow", "pendente": "yellow",
    "erro": "red", "atrasado": "red",
    "cancelado": "secondary", "neutro": "secondary", "inativo": "secondary",
    "info": "blue", "andamento": "blue",
    # valores crus de situacao_efetiva (colunas da tabela e pendências passam o campo direto)
    "em_tramitacao": "blue", "no_prazo": "yellow",
}


@register.filter
def cor_status(chave):
    """Cor do Tabler (green, yellow, red, blue, secondary) para uma chave semântica de situação."""
    return CORES.get(str(chave), "blue")


@register.inclusion_tag("ui/_status.html")
def tag_status(rotulo, chave="info"):
    """Selo de situação: ponto colorido + rótulo, no padrão .status do Tabler."""
    return {"rotulo": rotulo, "cor": cor_status(chave)}


@register.inclusion_tag("ui/_paginacao.html", takes_context=True)
def paginacao(context, pagina_obj, alvo="#listagem"):
    """Paginação (mesmos dados de sempre; só o HTML muda)."""
    return _base.paginacao(context, pagina_obj, alvo)


def _cabecalho(href, rotulo, aria, alvo="#listagem"):
    icone = {"ascending": "ti-sort-ascending", "descending": "ti-sort-descending"}.get(aria, "ti-arrows-sort")
    ativo = " text-body fw-bold" if aria != "none" else ""
    return mark_safe(
        f'<a class="table-sort-link text-reset text-decoration-none{ativo}" href="{href}" aria-sort="{aria}" '
        f'hx-get="{href}" hx-target="{alvo}" hx-push-url="true">{rotulo} '
        f'<i class="ti {icone} ms-1{"" if ativo else " opacity-50"}" aria-hidden="true"></i></a>'
    )


@register.simple_tag(takes_context=True)
def ordenar_por(context, campo, rotulo):
    """Cabeçalho ordenável (parâmetro único `ordenar=[-]campo`), ciclo nenhum → asc → desc → nenhum."""
    request = context["request"]
    atual = request.GET.get("ordenar", "")
    if atual == campo:
        proximo, aria = f"-{campo}", "ascending"
    elif atual == f"-{campo}":
        proximo, aria = "", "descending"
    else:
        proximo, aria = campo, "none"
    params = request.GET.copy()
    params.pop("pagina", None)
    if proximo:
        params["ordenar"] = proximo
    else:
        params.pop("ordenar", None)
    href = f"{request.path}?{params.urlencode()}" if params else request.path
    return _cabecalho(href, rotulo, aria)


# Ícones do menu (definidos em Font Awesome no core/menu.py) → Tabler Icons.
ICONES = {
    "fa-home": "ti-home", "fa-list": "ti-list-details", "fa-calendar-alt": "ti-calendar-event",
    "fa-calendar-check": "ti-calendar-check", "fa-calendar-day": "ti-calendar-due", "fa-building": "ti-building",
    "fa-chart-bar": "ti-chart-bar", "fa-file-alt": "ti-file-text", "fa-file-excel": "ti-file-spreadsheet",
    "fa-file-contract": "ti-file-certificate", "fa-comments": "ti-message-chatbot", "fa-robot": "ti-sparkles", "fa-users": "ti-users-group",
    "fa-user": "ti-user", "fa-user-cog": "ti-user-cog", "fa-cog": "ti-settings", "fa-cogs": "ti-settings-2",
    "fa-download": "ti-download", "fa-upload": "ti-upload", "fa-search": "ti-search", "fa-info-circle": "ti-info-circle",
    "fa-question-circle": "ti-help-circle", "fa-exchange-alt": "ti-arrows-exchange", "fa-sync": "ti-refresh",
    "fa-sync-alt": "ti-refresh", "fa-redo": "ti-rotate-clockwise", "fa-database": "ti-database", "fa-table": "ti-table",
    "fa-clipboard-list": "ti-clipboard-list", "fa-folder-open": "ti-folder-open", "fa-book": "ti-book",
    "fa-history": "ti-history", "fa-tasks": "ti-list-check", "fa-stream": "ti-timeline", "fa-check-circle": "ti-circle-check",
    "fa-clock": "ti-clock", "fa-hourglass-half": "ti-hourglass-high", "fa-exclamation-triangle": "ti-alert-triangle",
    "fa-eye": "ti-eye", "fa-plus": "ti-plus", "fa-pen": "ti-pencil", "fa-flag-checkered": "ti-flag-check",
    "fa-crosshairs": "ti-target", "fa-sort": "ti-arrows-sort", "fa-sort-up": "ti-sort-ascending",
    "fa-sort-down": "ti-sort-descending", "fa-ban": "ti-ban", "fa-inbox": "ti-inbox",
}

# `kpi.tom` (o mesmo do DSGov: faixa de cor do cartão = cor da fatia na rosca) → cor
# do Tabler para o avatar do ícone do KPI.
CORES_TOM = {
    "destaque": "primary", "sucesso": "green", "info": "azure", "alerta": "yellow", "erro": "red",
    "neutro": "secondary",
}


@register.filter
def ti(classe_fa):
    """Converte 'fas fa-home' (ou 'fa-home') no ícone equivalente do Tabler ('ti ti-home')."""
    for parte in str(classe_fa or "").split():
        if parte.startswith("fa-") and parte in ICONES:
            return f"ti {ICONES[parte]}"
    return "ti ti-point"


@register.filter
def cor_tom(tom):
    """Converte o tom do KPI ('sucesso', 'erro'...) na cor do Tabler ('green', 'red'...); sem tom, 'primary'."""
    return CORES_TOM.get(tom, "primary")


@register.filter
def widget_classe(campo, classes):
    """Renderiza o widget de um campo de formulário com as classes do Tabler (somadas às que o widget já tenha),
    marcando aria-invalid e ligando aria-describedby à ajuda e ao erro."""
    attrs = dict(campo.field.widget.attrs)
    attrs.pop("col", None)
    atuais = attrs.get("class", "")
    extra = " is-invalid" if campo.errors else ""
    attrs["class"] = f"{atuais} {classes}{extra}".strip()
    descritores = []
    if campo.help_text:
        descritores.append(f"{campo.auto_id}_ajuda")
    if campo.errors:
        descritores.append(f"{campo.auto_id}_erro")
        attrs["aria-invalid"] = "true"
    if descritores:
        attrs["aria-describedby"] = " ".join(descritores)
    return campo.as_widget(attrs=attrs)


# ---------- Painel "Personalizar aparência" ----------
NOMES_COR = {
    "blue": "Azul", "azure": "Azul-céu", "indigo": "Índigo", "purple": "Roxo", "pink": "Rosa", "red": "Vermelho",
    "orange": "Laranja", "yellow": "Amarelo", "lime": "Lima", "green": "Verde", "teal": "Verde-azulado", "cyan": "Ciano",
}
NOMES_BASE = {"slate": "Ardósia", "gray": "Cinza", "zinc": "Zinco", "neutral": "Neutro", "stone": "Pedra"}
NOMES_CANTOS = {"0": "Retos", "0.5": "Suaves", "1": "Padrão", "1.5": "Arredondados", "2": "Bem arredondados"}


@register.filter
def ui_nome_cor(valor):
    return NOMES_COR.get(valor, valor)


@register.filter
def ui_nome_base(valor):
    return NOMES_BASE.get(valor, valor)


@register.filter
def ui_nome_cantos(valor):
    return NOMES_CANTOS.get(valor, valor)


@register.filter
def ui_opcoes(texto):
    """"a:A:x,b:B:y" → [("a", "A", "x"), ("b", "B", "y")] — listas curtas de opções escritas no template."""
    return [tuple(parte.split(":")) for parte in str(texto).split(",") if parte]
