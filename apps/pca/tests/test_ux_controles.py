"""(A06, final) — testes de UX dos controles
globais da casca: exportação como download real (`hx-boost="false"`),
botão único "Filtros (N)" nas visões ainda não migradas, painel de filtros
sob demanda em qualquer largura, e F5 devolvido ao navegador.

Fase 26 — `pca:tabela` migrou para a
casca do padrão DSGov: filtros ficam sempre visíveis (sem painel/botão
"Filtros (N)"), export virou página própria (`pca:exportar`, sem
`hx-boost` — é um `<a>`/`<form>` normal para uma página, não um download
direto com boost desligado), e a casca nova não tem o handler F5 legado.

Fase 26 — `pca:dashboard` foi apagada
(`core:inicio` funde Início/Dashboard) e `pca:analise` também migrou
(relatório puro, sem painel de filtros nem `_acoes_export.html`). Só
`pca:calendario`/`pca:resumo_uo` (frente 5) continuam na casca legada e
mantêm os contratos originais.

`TransactionTestCase`/`serialized_rollback=True`: mesmo padrão do resto da
suíte (import real de planilha em `setUp()`, preserva o usuário de serviço
criado pela migração de dados)."""

from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TransactionTestCase
from django.urls import reverse


ARQUIVO_REAL = "Modelo_de_Controle_.xlsx"


class TestUxControlesGlobais(TransactionTestCase):
    serialized_rollback = True

    def setUp(self):
        call_command(
            "importar_pca",
            ARQUIVO_REAL,
            "--usuario=importador@pca.local",
            "--exercicio=2026",
            stdout=StringIO(),
        )
        self.usuario = get_user_model().objects.create_user(
            email="ux-controles@pca.local", password="x-forte-123"
        )
        self.client.force_login(self.usuario)

    # --- Exportação como download real --------------------------

    def test_calendario_e_resumo_uo_exportam_sem_hx_boost(self):
        # Fase 26 — `base.html` (padrão DSGov)
        # nunca usa `hx-boost` em `<main>` (não existe roteador de troca
        # de painel); os links de exportação são `<a>` comuns, sem
        # nenhum atributo especial necessário para abrir o download real.
        corpo = self.client.get(reverse("pca:calendario")).content.decode()
        self.assertNotIn('hx-boost="false"', corpo)

        corpo_resumo = self.client.get(reverse("pca:resumo_uo")).content.decode()
        self.assertIn(reverse("pca:exportar_resumo_uo_xlsx"), corpo_resumo)
        self.assertNotIn('hx-boost="false"', corpo_resumo)

    def test_tabela_exporta_via_pagina_propria_sem_hx_boost(self):
        """`pca:tabela` não tem mais `_acoes_export.html`
        (CSV/XLSX diretos): um único `br-button secondary` aponta para
        `pca:exportar`, página própria com formato/colunas escolhíveis."""
        corpo = self.client.get(reverse("pca:tabela")).content.decode()
        self.assertNotIn('hx-boost="false"', corpo)
        self.assertIn(reverse("pca:exportar"), corpo)

    # --- Botão único "Filtros (N)" nas visões ainda não migradas -----------

    # `test_filtros_n_aparece_nas_2_visoes_legadas_com_contagem_correta`/
    # `test_painel_de_filtros_comeca_fechado_nas_2_visoes_legadas` removidos
    # pelo plano — `pca:calendario`/`pca:resumo_uo` não
    # têm mais painel de filtros nenhum (nem botão "Filtros (N)" nem
    # `filtrosAbertos`/Alpine): a página inteira recarrega a cada mudança,
    # sem painel para abrir/fechar. Mesmo raciocínio de
    # `test_tabela_nao_tem_mais_painel_de_filtros_sob_demanda` abaixo,
    # generalizado — ver `test_filtros_tabela.py::
    # test_calendario_e_resumo_uo_tambem_nao_tem_mais_painel_sob_demanda`.

    def test_tabela_nao_tem_mais_painel_de_filtros_sob_demanda(self):
        corpo = self.client.get(reverse("pca:tabela")).content.decode()
        self.assertNotIn("filtrosAbertos", corpo)

    # --- F5 devolvido ao navegador (A06) ----------------------------------

    def test_f5_nao_intercepta_em_nenhuma_tela_renderizada(self):
        for rota in (
            reverse("core:inicio"),
            reverse("pca:tabela"),
            reverse("pca:calendario"),
            reverse("pca:resumo_uo"),
            reverse("pca:analise"),
        ):
            with self.subTest(rota=rota):
                corpo = self.client.get(rota).content.decode()
                self.assertNotIn("@keydown.window.f5", corpo, rota)
