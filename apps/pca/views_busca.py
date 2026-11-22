"""View da busca global (Fase 28).

Único ponto de entrada do sistema que pesquisa em TODOS os exercícios
acessíveis ao usuário autenticado de uma vez — diferente de `/tabela`
(`apps.pca.views.tabela_view`), que continua restrita ao exercício
resolvido e aos filtros da listagem. As duas telas consomem o MESMO
serviço de interpretação de termo (`apps.pca.busca.aplicar_busca`) — só o RECORTE de exercício muda entre elas.

Sem `@permission_required` — mesmo padrão de leitura de
`resumo_uo_view`/`analise_view`/`relatorio_movimentacao_view`, protegida
só pelo `LoginRequiredMiddleware` global. A busca sempre usou
a largura padrão (`container-lg`) de `base.html` — desde `[quick]`, sem exceção nenhuma: nenhuma página do sistema usa mais
`container-fluid`.
"""

from django.conf import settings
from django.core.paginator import Paginator
from django.shortcuts import render

from apps.catalogo.models import Exercicio
from apps.pca.busca import LIMITE_TERMO, aplicar_busca
from apps.pca.models import Processo


def busca_view(request):
    """(segunda metade) — termo vazio não roda `aplicar_busca`:
    mostra o estado "aguardar pesquisa", nunca "zero resultados" (os dois
    são mensagens diferentes para o usuário)."""
    get = request.GET
    termo = get.get("q", "").strip()[:LIMITE_TERMO]

    # Ausente/vazio = "Todos os exercícios"; só restringe quando o
    # valor casa um exercício EXISTENTE (mesmo cuidado de `resolver_exercicio`
    # em filtros.py, mas sem o fallback para o exercício aberto: aqui
    # "nenhum valor" tem um significado PRÓPRIO, não é "resolva um padrão").
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
        # Premissa registrada no SUMMARY: este sistema não tem
        # hoje um recorte de exercícios por permissão de usuário; "todos os
        # exercícios acessíveis" é lido, por ora, como "todos os exercícios
        # cadastrados" (mesma leitura de `exercicios_disponiveis`, o
        # context processor global já usado por `relatorio_movimentacao_view`).
        qs = Processo.objects.para_listagem().select_related(
            "exercicio", "unidade_organizacional"
        )
        if exercicio_selecionado is not None:
            qs = qs.filter(exercicio=exercicio_selecionado)
        qs, avisos = aplicar_busca(qs, termo, request=request)
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
    # Pitfall 16 — nunca cacheável na borda; leitura autenticada por sessão.
    resposta["Cache-Control"] = "private, no-store"
    return resposta
