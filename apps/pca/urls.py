from django.urls import path
from django.views.generic import RedirectView

from apps.pca import views
from apps.pca import views_analise
from apps.pca import views_busca
from apps.pca import views_processo
from apps.pca import views_relatorio_movimentacao
from apps.pca import views_tabela

app_name = "pca"

urlpatterns = [
    # Fase 26 — `/inicio` (a "Início" de cards da
    # Fase 25) redireciona 301 para `core:inicio`, a nova entrada única do
    # sistema. Fase 26 — `core:inicio` agora É o
    # dashboard real (funde Início + Dashboard); `pca:cards_inicio`/
    # `pca:dashboard` (realocações temporárias do 26-01 que preservavam
    # `inicio_view`/`dashboard_view` até esta frente fundir o conteúdo)
    # saem — `inicio_view`/`dashboard_view` apagadas de `views.py`, os 6
    # templates que só elas usavam apagados junto (ver).
    path("inicio", RedirectView.as_view(pattern_name="core:inicio", permanent=True), name="inicio"),
    # Sem barra final: a rota física é "/tabela", igual à URL
    # colável na reunião que o UI-SPEC (§Screen Contracts 3) descreve.
    path("tabela", views.tabela_view, name="tabela"),
    # Fase 28 — busca global, alvo do campo de
    # busca do header (`config.settings.base.DSGOV["BUSCA_URL_NAME"]`) e do
    # skiplink (`#main-searchbox`). Mesma convenção sem barra final.
    path("busca", views_busca.busca_view, name="busca"),
    path("calendario", views.calendario_view, name="calendario"),
    # Fase 17.1 — tela + export do resumo por UO,
    # mesma convenção sem barra final das demais visões.
    path("resumo-uo", views.resumo_uo_view, name="resumo_uo"),
    # Fase 24 — tela "Análise": gráficos que não cabem
    # na dashboard, mesma convenção sem barra final das demais visões.
    path("analise", views.analise_view, name="analise"),
    # Fase 36 — as 3 telas novas de Análises
    # (Fluxo de caixa/Estatísticas/Prazos), mesmo módulo `views_analise.py`
    # (`views.py` já tinha 3536+ linhas antes desta fase).
    path("analise/fluxo", views_analise.analise_fluxo_view, name="analise_fluxo"),
    path("analise/fluxo/csv", views_analise.analise_fluxo_csv_view, name="analise_fluxo_csv"),
    # Fase 37 (spec §5) — memória de cálculo por item: "de onde
    # veio este número?" sem Admin/JSON.
    path(
        "analise/fluxo/memoria/<int:item_pca>",
        views_analise.analise_fluxo_memoria_view,
        name="analise_fluxo_memoria",
    ),
    # Fase 37 (spec §3.2/§3.3) — rascunho de simulação na
    # sessão: painel "Simular" (índices/lead time) e ações por item
    # (excluir/incluir/renovação/valor/início), todas POST, mesmo padrão
    # PRG de `pca:analise_prazos_renovar` acima.
    path("analise/fluxo/simular", views_analise.analise_fluxo_simular_view, name="analise_fluxo_simular"),
    path(
        "analise/fluxo/item/<int:item_pca>/excluir",
        views_analise.analise_fluxo_item_excluir_view,
        name="analise_fluxo_item_excluir",
    ),
    path(
        "analise/fluxo/item/<int:item_pca>/incluir",
        views_analise.analise_fluxo_item_incluir_view,
        name="analise_fluxo_item_incluir",
    ),
    path(
        "analise/fluxo/item/<int:item_pca>/renovacao",
        views_analise.analise_fluxo_item_renovacao_view,
        name="analise_fluxo_item_renovacao",
    ),
    path(
        "analise/fluxo/item/<int:item_pca>/valor",
        views_analise.analise_fluxo_item_valor_view,
        name="analise_fluxo_item_valor",
    ),
    path(
        "analise/fluxo/item/<int:item_pca>/inicio",
        views_analise.analise_fluxo_item_inicio_view,
        name="analise_fluxo_item_inicio",
    ),
    path(
        "analise/fluxo/voltar-oficial",
        views_analise.analise_fluxo_voltar_oficial_view,
        name="analise_fluxo_voltar_oficial",
    ),
    # Fase 37 (spec §3.2, §0 decisão 5) — CRUD de `CenarioFluxo`:
    # salvar como novo, sobrescrever, carregar no rascunho, excluir (com
    # página de confirmação própria, nunca modal) — mesmo padrão PRG das
    # ações de simulação acima. XLSX de 5 abas do cenário projetado
    # (spec §0 decisão 6, §6).
    path(
        "analise/fluxo/cenario/salvar",
        views_analise.cenario_fluxo_salvar_como_view,
        name="analise_fluxo_cenario_salvar_como",
    ),
    path(
        "analise/fluxo/cenario/<int:cenario_id>/salvar",
        views_analise.cenario_fluxo_salvar_view,
        name="analise_fluxo_cenario_salvar",
    ),
    path(
        "analise/fluxo/cenario/<int:cenario_id>/carregar",
        views_analise.cenario_fluxo_carregar_view,
        name="analise_fluxo_cenario_carregar",
    ),
    path(
        "analise/fluxo/cenario/<int:cenario_id>/excluir/confirmar",
        views_analise.cenario_fluxo_excluir_confirmar_view,
        name="analise_fluxo_cenario_excluir_confirmar",
    ),
    path(
        "analise/fluxo/cenario/<int:cenario_id>/excluir",
        views_analise.cenario_fluxo_excluir_view,
        name="analise_fluxo_cenario_excluir",
    ),
    path("analise/fluxo/xlsx", views_analise.analise_fluxo_xlsx_view, name="analise_fluxo_xlsx"),
    path(
        "analise/estatisticas",
        views_analise.analise_estatisticas_view,
        name="analise_estatisticas",
    ),
    path("analise/prazos", views_analise.analise_prazos_view, name="analise_prazos"),
    path(
        "processo/<int:ano>/<int:item_pca>/renovacao",
        views_analise.alternar_renovacao_view,
        name="analise_prazos_renovar",
    ),
    # Fase 27 — "Relatório de movimentação"; desde a,
    # "Relatório da reunião" (mesma URL; exige
    # pca.view_acompanhamento; sem HTMX, filtros por GET, recarga inteira).
    path(
        "relatorio-movimentacao",
        views_relatorio_movimentacao.relatorio_movimentacao_view,
        name="relatorio_movimentacao",
    ),
    # Fase 14.1 — o kanban deixou de existir; alias histórico agora
    # redireciona 301 para /tabela, preservando os filtros validados.
    path("kanban", views.redirecionar_kanban_view, name="kanban"),
    # Fase 26 — criar/editar como página, mesmo
    # template `processo_formulario.html` (`telas/formulario.md`).
    path("processo/novo", views_processo.criar_processo_view, name="criar_processo"),
    # Fase 26 — detalhe do processo como página
    # própria (`telas/detalhe.md`), sem abas. Renasce depois de ter morrido
    # na Fase 14 — desta vez sem convivência com um modal: é a única
    # superfície de LEITURA do processo.
    path("processo/<int:ano>/<int:item_pca>", views_processo.detalhe_processo_view, name="detalhe_processo"),
    path("processo/<int:ano>/<int:item_pca>/editar", views_processo.editar_processo_view, name="editar_processo"),
    # Fase 26 — alterar situação como página,
    # com aviso explícito da consequência, nunca mais um modal de
    # confirmação. Fase 26 — o modal universal de transição
    # (`transicao/preparar`/`transicao/confirmar`, Fase 17) saiu junto
    # com `editar_campo_view`/`_tabela_linha_legado.html`: esta é a ÚNICA
    # forma de alterar situação a partir de agora.
    path("processo/<int:ano>/<int:item_pca>/situacao", views_processo.transicao_processo_view, name="transicao_processo"),
    # Fase 26 — único modal do sistema:
    # "Registrar acompanhamento". Substitui `pca:registrar_promessa`
    # (apagada — nada mais a referenciava depois que `_form_editar_processo.
    # html` saiu, confirmado por grep).
    path("processo/<int:ano>/<int:item_pca>/acompanhamento", views_processo.acompanhamento_modal_view, name="acompanhamento_modal"),
    # Excluir acompanhamento pela ficha (superusuário +
    # pca.gerir_exercicio), mesmo padrão de nomes já usado pelo par
    # cenario_fluxo_excluir/cenario_fluxo_excluir_confirmar
    # (views_analise.py): a URL mais longa ("/excluir/confirmar") é o GET
    # da página de confirmação; a URL curta ("/excluir") é o POST real.
    path(
        "processo/<int:ano>/<int:item_pca>/acompanhamento/<int:pk>/excluir/confirmar",
        views_processo.acompanhamento_excluir_confirmar_view,
        name="acompanhamento_excluir_confirmar",
    ),
    path(
        "processo/<int:ano>/<int:item_pca>/acompanhamento/<int:pk>/excluir",
        views_processo.acompanhamento_excluir_view,
        name="acompanhamento_excluir",
    ),
    # Fase 29 — `pca:adicionar_sei`/
    # `pca:remover_sei` saíram: números SEI só mudam pelo formset inline do
    # fieldset Processo de `pca:editar_processo` (`ProcessoSEIFormSet`),
    # nunca mais por rota avulsa a partir do detalhe.
    path("reunioes", views.reuniao_listagem_view, name="reuniao_listagem"),
    path("reuniao/novo", views.criar_reuniao_view, name="criar_reuniao"),
    # (02-04) — downloads síncronos do conjunto filtrado; mesma
    # convenção sem barra final de "tabela"/"kanban".
    # Fase 26 — página própria de exportação (formato +
    # colunas escolhíveis); os dois downloads diretos abaixo continuam
    # respondendo por GET, URLs históricas preservadas.
    path("exportar", views_tabela.exportar_view, name="exportar"),
    path("exportar/csv", views.exportar_csv_view, name="exportar_csv"),
    path("exportar/xlsx", views.exportar_xlsx_view, name="exportar_xlsx"),
    # Fase 17.1 — export síncrono do resumo por UO.
    path("exportar/resumo-uo", views.exportar_resumo_uo_xlsx_view, name="exportar_resumo_uo_xlsx"),
    # Fase 26 — wizard de 3 etapas: virada (etapa 1,
    # Selecionar) / virada_ajustar (etapa 2) / virada_revisar (etapa 3).
    # virada_linha/virada_selecionar_pagina/virada_campo/virada_salvar
    # (edição inline por linha/campo, HTMX) foram apagadas — substituídas
    # pelo POST único de página inteira de `virada_view` e pelo
    # ViradaItemForm de `virada_item_editar_view`.
    path("exercicio/<int:ano_destino>/virada", views.virada_view, name="virada"),
    path("exercicio/<int:ano_destino>/virada/ajustar", views.virada_ajustar_view, name="virada_ajustar"),
    path("exercicio/<int:ano_destino>/virada/ajustar/item/<int:item_pca>", views.virada_item_editar_view, name="virada_item_editar"),
    path("exercicio/<int:ano_destino>/virada/revisar", views.virada_revisar_view, name="virada_revisar"),
    path("exercicio/<int:ano_destino>/virada/descarte", views.virada_confirmar_descarte_view, name="virada_confirmar_descarte"),
    path("exercicio/<int:ano_destino>/virada/descartar", views.virada_descartar_view, name="virada_descartar"),
    path("exercicio/<int:ano_destino>/virada/confirmacao", views.virada_confirmacao_view, name="virada_confirmacao"),
    path("exercicio/<int:ano_destino>/virada/confirmar", views.virada_confirmar_view, name="virada_confirmar"),
    path("exercicios/gerir", views.gerenciar_exercicios_view, name="gerenciar_exercicios"),
    # Fase 40 (spec §1) — prévia (GET) + confirmação (POST) da
    # ação "Gerar itens de N+1" a partir dos contratos vigentes de N.
    path("exercicio/<int:ano>/gerar-n1", views.gerar_n1_previa_view, name="gerar_n1"),
    path("exercicio/<int:ano>/gerar-n1/confirmar", views.gerar_n1_confirmar_view, name="gerar_n1_confirmar"),
    path("exercicio/<int:ano>/encerrar/confirmar", views.encerrar_confirmar_view, name="encerrar_confirmar"),
    path("exercicio/<int:ano>/encerrar", views.encerrar_view, name="encerrar"),
]
