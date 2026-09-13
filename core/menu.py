"""Menu lateral do sistema.

Cada item: {"rotulo", "icone" (classe Font Awesome 5, ex. "fas fa-home"), "url" (caminho já resolvido),
"filhos" (lista de itens, opcional), "permissao" (codename opcional, ex. "diarias.view_diaria")}.
Um item com filhos vira um menu-folder; sem filhos, um menu-item direto.

Fonte dos itens: `apps.pca.navegacao` (import LOCAL, dentro de `itens()`, para não criar dependência
circular de import em nível de módulo entre `core` e `apps.pca`).
"""

from django.urls import reverse


_ICONES_DESTINOS_OPERACIONAIS = {
    "processos": "fas fa-list",
    "calendario": "fas fa-calendar-alt",
    "resumo_uo": "fas fa-building",
    "analise": "fas fa-chart-bar",
    # Última entrada: ordem do dict determina a ordem no menu (itens() itera .items()).
    "relatorio_movimentacao": "fas fa-file-alt",
}


def itens(request):
    usuario = request.user
    # Import local — evita ciclo de import em nível de módulo entre core e apps.pca.
    from apps.pca import navegacao

    mapa_destinos = {d["chave"]: d for d in navegacao.DESTINOS_OPERACIONAIS}

    todos = [{"rotulo": "Início", "icone": "fas fa-home", "url": reverse("core:inicio")}]
    for chave, icone in _ICONES_DESTINOS_OPERACIONAIS.items():
        destino = mapa_destinos[chave]
        todos.append({"rotulo": destino["rotulo"], "icone": icone, "url": reverse(destino["url_name"])})
    todos.append({"rotulo": "Reuniões", "icone": "fas fa-users", "url": reverse("pca:reuniao_listagem")})
    todos.append({
        "rotulo": "Gerenciar exercícios",
        "icone": "fas fa-calendar-check",
        "url": reverse("pca:gerenciar_exercicios"),
        "permissao": "pca.gerir_exercicio",
        "divisor": True,
    })
    # Mesma área alcançável pelo dropdown do avatar; no menu lateral fica
    # ao alcance do polegar no celular.
    todos.append({"rotulo": "Meu perfil", "icone": "fas fa-user", "url": reverse("core:perfil")})
    todos.append({"rotulo": "Sobre o sistema", "icone": "fas fa-info-circle", "url": reverse("core:sobre")})
    if usuario.is_staff:
        todos.append({"rotulo": "Administração", "icone": "fas fa-cog", "url": "/admin/", "divisor": True})
    return [i for i in todos if _permitido(usuario, i)]


def _permitido(usuario, item):
    perm = item.get("permissao")
    if perm and not usuario.has_perm(perm):
        return False
    if item.get("filhos"):
        item["filhos"] = [f for f in item["filhos"] if _permitido(usuario, f)]
        return bool(item["filhos"])
    return True
