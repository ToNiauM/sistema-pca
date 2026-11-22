from apps.catalogo.models import Exercicio


def exercicios_disponiveis(request):
    """Fonte do seletor de exercício de cada tela (`core/templates/core/inicio.html`
    e demais telas que montam seu próprio `<form method="get">` de exercício). Roda em TODA página renderizada pelo engine, inclusive
    login/admin/healthz, que não têm `Exercicio` no seu domínio; o
    `try/except` devolve lista vazia fora do domínio do PCA, mesmo padrão
    defensivo de `core.context_processors.usuario_atual`/`dsgov`."""
    try:
        return {"exercicios_disponiveis": Exercicio.objects.order_by("-ano")}
    except Exception:
        return {"exercicios_disponiveis": []}
