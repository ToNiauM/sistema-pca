from django.conf import settings
from django.urls import NoReverseMatch

from core import menu


def usuario_atual(request):
    """Expõe o usuário autenticado ao template — usado no rodapé da sidebar
    (iniciais, e-mail) sem cada view precisar passá-lo explicitamente."""
    return {"usuario_atual": getattr(request, "user", None)}


def dsgov(request):
    """Identidade visual e menu da casca dsgov (Fase 26) — toda
    página recebe isto sem a view fazer nada, mesmo padrão do
    assets/projeto/core/context_processors.py do padrão DSGov.

    Bug] `menu.itens()` resolve nomes de rota (`core:inicio`,
    `pca:tabela`...) via `reverse()`, o que pressupõe o urlconf real do
    projeto. Como este é um context processor GLOBAL (roda em toda
    página, inclusive as do Django Admin), qualquer teste que troque
    `ROOT_URLCONF` por um urlconf mínimo isolado (padrão comum para testar
    uma view sem depender do projeto inteiro — ex.:
    apps.pca.tests.test_import_admin) faz `reverse()` levantar
    `NoReverseMatch`/`KeyError` para nomes que esse urlconf não registra,
    derrubando a página inteira por causa de um menu que ela nem usa. Um
    context processor nunca pode quebrar o render por uma falha de menu —
    cai para `[]`, mesmo padrão defensivo de `usuario_atual` acima
    (nunca lança)."""
    cfg = settings.DSGOV
    usuario = getattr(request, "user", None)
    dsgov_menu = []
    if usuario and usuario.is_authenticated:
        try:
            dsgov_menu = menu.itens(request)
        except (NoReverseMatch, KeyError):
            dsgov_menu = []
    contexto = {"DSGOV": cfg, "dsgov_menu": dsgov_menu}
    return contexto


def ui(request):
    """Casca Tabler (PCA_DESIGN=tabler): identidade do sistema como APP e o menu lateral como MENU —
    os mesmos dados do contexto de sempre, com nomes neutros para os templates de tabler/templates/."""
    from core.models import PreferenciaAparencia

    contexto = dsgov(request)
    return {
        "APP": contexto["DSGOV"],
        "MENU": contexto["dsgov_menu"],
        # Aparência do usuário (claro/escuro, cor, base, cantos) e as opções do painel "Personalizar".
        "APARENCIA": PreferenciaAparencia.valores_de(getattr(request, "user", None)),
        "APARENCIA_OPCOES": {
            "cores": PreferenciaAparencia.CORES, "bases": PreferenciaAparencia.BASES,
            "cantos": PreferenciaAparencia.CANTOS,
        },
    }
