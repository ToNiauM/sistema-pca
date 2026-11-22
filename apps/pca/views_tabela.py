"""Views próprias da tela Processos que este plano ACRESCENTA (Fase 26/Plano
26-03, coordenação de arquivo compartilhado). `tabela_view`
(pré-existente) continua em `apps/pca/views.py`, reescrita in-place; só a
view NOVA (`exportar_view`) mora aqui, para reduzir o diff em `urls.py` a
uma linha e não competir com 26-02/26-04/26-05 no mesmo módulo grande.
"""

from django.shortcuts import render
from django.urls import reverse

from apps.pca.colunas import COLUNAS, _filtrar_restritas
from apps.pca.filtros import PARAMETROS_FILTRO, filtros_ativos, querystring_filtros
from apps.pca.forms_listagem import ExportarForm
from apps.pca.views import _queryset_export

from apps.pca.exportacao import exportar_csv, exportar_xlsx


def exportar_view(request):
    """Página própria de exportação (`telas/formulario.md`):
    formato (CSV/XLSX) e colunas escolhíveis, filtros atuais preservados.

    O form NUNCA decide o recorte de dados, só formato/colunas;
    `_queryset_export`/`queryset_filtrado` (intocados) continuam sendo a
    ÚNICA leitura validada do filtro. O `<form method="post">` desta página
    aponta `action` para a MESMA URL com a querystring de filtros atual
    embutida (`?{{ querystring_filtros }}`) — `request.GET` é resolvido a
    partir da querystring da URL em QUALQUER método HTTP (Django), então
    `_queryset_export(request)` enxerga o recorte certo mesmo dentro de um
    POST. Os campos `hidden` no template espelham os mesmos filtros só para
    transparência visual; a filtragem real nunca depende deles (evita o bug
    de campos `hidden` num `<form method="post">` caírem em `request.POST`,
    invisível para `queryset_filtrado`, que só lê `request.GET`).

    `pca:exportar_csv`/`pca:exportar_xlsx` continuam respondendo por GET
    direto — URLs históricas preservadas.

    Fase 28 — `exercicio` é resolvido ANTES do
    ramo POST (precisa alimentar `exportar_xlsx`/`exportar_csv` com o
    nome/aba dinâmicos pelo exercício efetivo); `ExportarForm.formato`
    está travado em `"xlsx"` (interface de Processos oferece só XLSX), mas o ramo `else` (CSV) é preservado por se tratar de um
    valor de formulário — nunca alcançável pela UI, só por um POST manual
    fora dela."""
    exercicio = filtros_ativos(request.GET)["exercicio"]
    if request.method == "POST":
        form = ExportarForm(request.POST, request=request)
        if form.is_valid():
            # QA de segurança 30/09/2026 (achado M2) — a ausência de seleção
            # explícita continua exportando "tudo", mas só o que ESTE
            # usuário pode ver: `_filtrar_restritas` roda sempre, mesmo no
            # caso `colunas=None` (nenhum checkbox marcado no POST).
            colunas = form.cleaned_data["colunas"] or [c.chave for c in COLUNAS]
            colunas = _filtrar_restritas(colunas, request)
            queryset = _queryset_export(request, colunas)
            if form.cleaned_data["formato"] == "xlsx":
                resposta = exportar_xlsx(queryset, colunas, exercicio=exercicio)
            else:
                resposta = exportar_csv(queryset, colunas, exercicio=exercicio)
            # Download nunca cacheável na borda (mesma disciplina
            # de exportar_csv_view/exportar_xlsx_view).
            resposta["Cache-Control"] = "private, no-store"
            return resposta
    else:
        form = ExportarForm(request=request)

    filtros_hidden = [
        (chave, valor)
        for chave in PARAMETROS_FILTRO
        for valor in request.GET.getlist(chave)
        if valor
    ]
    querystring_atual = querystring_filtros(request.GET)

    contexto = {
        "form": form,
        "filtros_hidden": filtros_hidden,
        "querystring_filtros": querystring_atual,
        "url_cancelar": (
            f"{reverse('pca:tabela')}?{querystring_atual}"
            if querystring_atual
            else reverse("pca:tabela")
        ),
        "rotulo_salvar": "Exportar",
        "trilha": [("Processos", reverse("pca:tabela")), ("Exportar", None)],
        "exercicio": exercicio,
        "nome_tela": "Exportar processos",
    }
    return render(request, "pca/exportar.html", contexto)
