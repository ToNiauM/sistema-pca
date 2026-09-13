from django.conf import settings
from django.urls import NoReverseMatch

from core import menu


def usuario_atual(request):
    """Expõe o usuário autenticado ao template — usado no rodapé da sidebar
    (iniciais, e-mail) sem cada view precisar passá-lo explicitamente."""
    return {"usuario_atual": getattr(request, "user", None)}


def dsgov(request):
    """Identidade visual e menu da casca dsgov — toda página recebe isto
    sem a view fazer nada.

    `menu.itens()` resolve nomes de rota via `reverse()`, que pressupõe o
    urlconf real do projeto; um teste que troca `ROOT_URLCONF` por um
    urlconf mínimo pode fazer `reverse()` levantar `NoReverseMatch`/
    `KeyError`. Um context processor nunca pode quebrar o render por uma
    falha de menu — cai para `[]`, mesmo padrão defensivo de
    `usuario_atual` acima."""
    cfg = settings.DSGOV
    usuario = getattr(request, "user", None)
    dsgov_menu = []
    if usuario and usuario.is_authenticated:
        try:
            dsgov_menu = menu.itens(request)
        except (NoReverseMatch, KeyError):
            dsgov_menu = []
    return {"DSGOV": cfg, "dsgov_menu": dsgov_menu}
