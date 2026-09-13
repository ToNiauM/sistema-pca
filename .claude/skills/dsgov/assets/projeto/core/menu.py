"""Menu lateral do sistema.

Cada item: {"rotulo", "icone" (classe Font Awesome 5, ex. "fas fa-home"), "url" (caminho já resolvido),
"filhos" (lista de itens, opcional), "permissao" (codename opcional, ex. "diarias.view_diaria")}.
Um item com filhos vira um menu-folder; sem filhos, um menu-item direto.
A skill dsgov gera este arquivo; o gerador `gerar_app.py` acrescenta um item por app.
"""

from django.urls import reverse


def itens(request):
    usuario = request.user
    todos = [
        {"rotulo": "Início", "icone": "fas fa-home", "url": reverse("core:inicio")},
        # __MENU__
    ]
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
