from apps.catalogo.models import Exercicio


def exercicios_disponiveis(request):
    """Lista de exercícios para o seletor; lista vazia se o app não estiver disponível."""
    try:
        return {"exercicios_disponiveis": Exercicio.objects.order_by("-ano")}
    except Exception:
        return {"exercicios_disponiveis": []}
