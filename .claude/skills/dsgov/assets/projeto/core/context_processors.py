from django.conf import settings

from core import menu


def dsgov(request):
    """Identidade visual e menu para o layout base. Toda página recebe isto sem a view fazer nada."""
    cfg = settings.DSGOV
    usuario = getattr(request, "user", None)
    return {
        "DSGOV": cfg,
        "dsgov_menu": menu.itens(request) if usuario and usuario.is_authenticated else [],
    }
