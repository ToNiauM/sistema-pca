"""View da tela "Relatório de movimentação". Só wiring e apresentação —
toda a lógica de negócio já vive em apps.pca.relatorio_movimentacao,
testada isoladamente. Esta view nunca reimplementa nada disso.

Todo usuário autenticado — sem @permission_required, protegido só pelo
LoginRequiredMiddleware global."""

from django.conf import settings
from django.shortcuts import render
from django.urls import reverse

from apps.catalogo.models import Exercicio
from apps.pca.filtros import resolver_exercicio
from apps.pca.models import Reuniao
from apps.pca.relatorio_movimentacao import montar_relatorio, resolver_periodo_relatorio


def relatorio_movimentacao_view(request):
    """Filtro por exercício + reunião (intervalo automático) + datas
    livres (datas livres prevalecem)."""
    get = request.GET
    exercicio = resolver_exercicio(get)

    relatorio = None
    de = ate = None
    reunioes = Reuniao.objects.none()
    titulo_arquivo = f"{settings.DSGOV['ORGAO_SIGLA']}_movimentacao"
    trilha = [("Relatório de movimentação", None)]

    if exercicio is not None:
        de, ate = resolver_periodo_relatorio(get, exercicio)
        relatorio = montar_relatorio(
            exercicio=exercicio, de=de, ate=ate, usuario=request.user
        )
        reunioes = Reuniao.objects.filter(exercicio=exercicio).order_by("data")
        titulo_arquivo = (
            f"{settings.DSGOV['ORGAO_SIGLA']}_movimentacao_{de:%Y-%m-%d}_a_{ate:%Y-%m-%d}"
        )
        trilha = [
            (f"PCA {exercicio.ano}", f"{reverse('raiz')}?exercicio={exercicio.ano}"),
            ("Relatório de movimentação", None),
        ]

    contexto = {
        "relatorio": relatorio,
        "reunioes": reunioes,
        "exercicio": exercicio,
        "exercicios_disponiveis": Exercicio.objects.order_by("-ano"),
        "de": de,
        "ate": ate,
        "reuniao_selecionada_id": get.get("reuniao"),
        "titulo_arquivo": titulo_arquivo,
        "orgao": settings.DSGOV["ORGAO"],
        "trilha": trilha,
    }
    resposta = render(request, "pca/relatorio_movimentacao.html", contexto)
    # nunca cacheável na borda; o filtro é por sessão autenticada, não público
    resposta["Cache-Control"] = "private, no-store"
    return resposta
