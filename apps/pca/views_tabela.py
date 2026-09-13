"""Views próprias da tela Processos que este módulo acrescenta.
tabela_view continua em apps/pca/views.py; só exportar_view mora aqui."""

from django.shortcuts import render
from django.urls import reverse

from apps.pca.filtros import PARAMETROS_FILTRO, filtros_ativos, querystring_filtros
from apps.pca.forms_listagem import ExportarForm
from apps.pca.views import _queryset_export

from apps.pca.exportacao import exportar_csv, exportar_xlsx


def exportar_view(request):
    """Página própria de exportação: formato (CSV/XLSX) e colunas
    escolhíveis, filtros atuais preservados.

    O form nunca decide o recorte de dados, só formato/colunas;
    _queryset_export/queryset_filtrado continuam sendo a única leitura
    validada do filtro. O form aponta action para a mesma URL com a
    querystring de filtros atual embutida, então _queryset_export enxerga
    o recorte certo mesmo dentro de um POST. Os campos hidden no template
    espelham os mesmos filtros só para transparência visual; a filtragem
    real nunca depende deles.

    pca:exportar_csv/pca:exportar_xlsx continuam respondendo por GET
    direto. exercicio é resolvido antes do ramo POST; ExportarForm.formato
    está travado em "xlsx" (a interface oferece só XLSX), mas o ramo else
    (CSV) é preservado por não ser alcançável pela UI, só por um POST
    manual fora dela."""
    exercicio = filtros_ativos(request.GET)["exercicio"]
    if request.method == "POST":
        form = ExportarForm(request.POST)
        if form.is_valid():
            colunas = form.cleaned_data["colunas"] or None
            queryset = _queryset_export(request)
            if form.cleaned_data["formato"] == "xlsx":
                resposta = exportar_xlsx(queryset, colunas, exercicio=exercicio)
            else:
                resposta = exportar_csv(queryset, colunas, exercicio=exercicio)
            # download nunca cacheável na borda
            resposta["Cache-Control"] = "private, no-store"
            return resposta
    else:
        form = ExportarForm()

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
