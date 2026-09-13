"""View da busca global: único ponto de entrada que pesquisa em todos os
exercícios acessíveis de uma vez, diferente de /tabela, que continua
restrita ao exercício resolvido. As duas telas consomem o mesmo serviço
de interpretação de termo (apps.pca.busca.aplicar_busca) — só o recorte
de exercício muda entre elas.

Sem @permission_required, protegida só pelo LoginRequiredMiddleware
global."""

from django.conf import settings
from django.core.paginator import Paginator
from django.shortcuts import render

from apps.catalogo.models import Exercicio
from apps.pca.busca import LIMITE_TERMO, aplicar_busca
from apps.pca.models import Processo


def busca_view(request):
    """Termo vazio não roda aplicar_busca: mostra o estado "aguardar
    pesquisa", nunca "zero resultados"."""
    get = request.GET
    termo = get.get("q", "").strip()[:LIMITE_TERMO]

    # ausente/vazio = "Todos os exercícios"; só restringe quando o valor
    # casa um exercício existente, sem fallback para o exercício aberto
    exercicio_selecionado = None
    valor_exercicio = get.get("exercicio")
    if valor_exercicio:
        try:
            ano = int(valor_exercicio)
        except (TypeError, ValueError):
            ano = None
        if ano is not None:
            exercicio_selecionado = Exercicio.objects.filter(ano=ano).first()

    avisos = []
    pagina = None
    total_encontrado = 0
    if termo:
        # este sistema não tem recorte de exercícios por permissão de
        # usuário; "todos os exercícios acessíveis" é lido como "todos os
        # exercícios cadastrados"
        qs = Processo.objects.para_listagem().select_related(
            "exercicio", "unidade_organizacional"
        )
        if exercicio_selecionado is not None:
            qs = qs.filter(exercicio=exercicio_selecionado)
        qs, avisos = aplicar_busca(qs, termo)
        qs = qs.order_by("-exercicio__ano", "item_pca")

        opcoes_por_pagina = settings.DSGOV.get("OPCOES_POR_PAGINA", (10, 20, 50))
        try:
            por_pagina = int(get.get("por_pagina", settings.DSGOV["ITENS_POR_PAGINA"]))
        except (TypeError, ValueError):
            por_pagina = settings.DSGOV["ITENS_POR_PAGINA"]
        if por_pagina not in opcoes_por_pagina:
            por_pagina = settings.DSGOV["ITENS_POR_PAGINA"]

        paginador = Paginator(qs, por_pagina)
        pagina = paginador.get_page(get.get("pagina"))
        total_encontrado = paginador.count

    contexto = {
        "termo": termo,
        "exercicio_selecionado": exercicio_selecionado,
        "exercicios_disponiveis": Exercicio.objects.order_by("-ano"),
        "avisos": avisos,
        "pagina": pagina,
        "total_encontrado": total_encontrado,
        "trilha": [("Busca", None)],
        "nome_tela": "Busca",
    }
    resposta = render(request, "pca/busca.html", contexto)
    # nunca cacheável na borda; leitura autenticada por sessão
    resposta["Cache-Control"] = "private, no-store"
    return resposta
