from django.urls import path
from django.views.generic import RedirectView

from apps.pca import views
from apps.pca import views_busca
from apps.pca import views_processo
from apps.pca import views_relatorio_movimentacao
from apps.pca import views_tabela

app_name = "pca"

urlpatterns = [
    # /inicio redireciona 301 para core:inicio, a entrada única do sistema
    path("inicio", RedirectView.as_view(pattern_name="core:inicio", permanent=True), name="inicio"),
    # sem barra final: a rota física é "/tabela"
    path("tabela", views.tabela_view, name="tabela"),
    # busca global, alvo do campo de busca do header e do skiplink
    path("busca", views_busca.busca_view, name="busca"),
    path("calendario", views.calendario_view, name="calendario"),
    # tela + export do resumo por UO
    path("resumo-uo", views.resumo_uo_view, name="resumo_uo"),
    # tela "Análise": gráficos que não cabem na dashboard
    path("analise", views.analise_view, name="analise"),
    # "Relatório de movimentação", o "git log" do PCA entre duas datas
    path(
        "relatorio-movimentacao",
        views_relatorio_movimentacao.relatorio_movimentacao_view,
        name="relatorio_movimentacao",
    ),
    # alias histórico redireciona 301 para /tabela, preservando os filtros
    path("kanban", views.redirecionar_kanban_view, name="kanban"),
    # criar/editar como página, mesmo template processo_formulario.html
    path("processo/novo", views_processo.criar_processo_view, name="criar_processo"),
    # detalhe do processo como página própria, sem abas: única superfície de leitura
    path("processo/<int:ano>/<int:item_pca>", views_processo.detalhe_processo_view, name="detalhe_processo"),
    path("processo/<int:ano>/<int:item_pca>/editar", views_processo.editar_processo_view, name="editar_processo"),
    # alterar situação como página, com aviso explícito da consequência
    path("processo/<int:ano>/<int:item_pca>/situacao", views_processo.transicao_processo_view, name="transicao_processo"),
    # único modal do sistema: "Registrar acompanhamento"
    path("processo/<int:ano>/<int:item_pca>/acompanhamento", views_processo.acompanhamento_modal_view, name="acompanhamento_modal"),
    # números SEI só mudam pelo formset inline do fieldset Processo
    path("reunioes", views.reuniao_listagem_view, name="reuniao_listagem"),
    path("reuniao/novo", views.criar_reuniao_view, name="criar_reuniao"),
    # downloads síncronos do conjunto filtrado; página própria de
    # exportação (formato + colunas escolhíveis); os dois downloads
    # diretos abaixo continuam respondendo por GET, URLs históricas preservadas
    path("exportar", views_tabela.exportar_view, name="exportar"),
    path("exportar/csv", views.exportar_csv_view, name="exportar_csv"),
    path("exportar/xlsx", views.exportar_xlsx_view, name="exportar_xlsx"),
    # export síncrono do resumo por UO
    path("exportar/resumo-uo", views.exportar_resumo_uo_xlsx_view, name="exportar_resumo_uo_xlsx"),
    # wizard de 3 etapas: virada (Selecionar) / virada_ajustar / virada_revisar
    path("exercicio/<int:ano_destino>/virada", views.virada_view, name="virada"),
    path("exercicio/<int:ano_destino>/virada/ajustar", views.virada_ajustar_view, name="virada_ajustar"),
    path("exercicio/<int:ano_destino>/virada/ajustar/item/<int:item_pca>", views.virada_item_editar_view, name="virada_item_editar"),
    path("exercicio/<int:ano_destino>/virada/revisar", views.virada_revisar_view, name="virada_revisar"),
    path("exercicio/<int:ano_destino>/virada/descarte", views.virada_confirmar_descarte_view, name="virada_confirmar_descarte"),
    path("exercicio/<int:ano_destino>/virada/descartar", views.virada_descartar_view, name="virada_descartar"),
    path("exercicio/<int:ano_destino>/virada/confirmacao", views.virada_confirmacao_view, name="virada_confirmacao"),
    path("exercicio/<int:ano_destino>/virada/confirmar", views.virada_confirmar_view, name="virada_confirmar"),
    path("exercicios/gerir", views.gerenciar_exercicios_view, name="gerenciar_exercicios"),
    path("exercicio/<int:ano>/encerrar/confirmar", views.encerrar_confirmar_view, name="encerrar_confirmar"),
    path("exercicio/<int:ano>/encerrar", views.encerrar_view, name="encerrar"),
]
