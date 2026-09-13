"""Testes de UX dos controles globais da casca: exportação como download
real, painel de filtros sob demanda em qualquer largura.

`pca:tabela` usa a casca da skill dsgov: filtros ficam sempre visíveis
(sem painel/botão "Filtros (N)"), export é página própria (`pca:exportar`,
um `<a>`/`<form>` normal, sem `hx-boost`). `core:inicio` funde
Início/Dashboard; `pca:analise` é relatório puro, sem painel de filtros.
`pca:calendario`/`pca:resumo_uo` continuam na casca legada e mantêm os
contratos originais.

`TransactionTestCase`/`serialized_rollback=True`: mesmo padrão do resto da
suíte (import real de planilha em `setUp()`, preserva o usuário de serviço
criado pela migração de dados)."""

from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TransactionTestCase
from django.urls import reverse


ARQUIVO_REAL = "apps/pca/fixtures/modelo-controle-exemplo.xlsx"


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

    # --- Exportação como download real (UX25-05) --------------------------

    def test_calendario_e_resumo_uo_exportam_sem_hx_boost(self):
        # `base.html` nunca usa `hx-boost` em `<main>`; os links de
        # exportação são `<a>` comuns, sem atributo especial.
        corpo = self.client.get(reverse("pca:calendario")).content.decode()
        self.assertNotIn('hx-boost="false"', corpo)

        corpo_resumo = self.client.get(reverse("pca:resumo_uo")).content.decode()
        self.assertIn(reverse("pca:exportar_resumo_uo_xlsx"), corpo_resumo)
        self.assertNotIn('hx-boost="false"', corpo_resumo)

    def test_tabela_exporta_via_pagina_propria_sem_hx_boost(self):
        """`pca:tabela`: um único `br-button secondary` aponta para
        `pca:exportar`, página própria com formato/colunas escolhíveis."""
        corpo = self.client.get(reverse("pca:tabela")).content.decode()
        self.assertNotIn('hx-boost="false"', corpo)
        self.assertIn(reverse("pca:exportar"), corpo)

    # --- Botão único "Filtros (N)" nas visões ainda não migradas -----------

    # `pca:calendario`/`pca:resumo_uo` não têm painel de filtros (nem
    # botão "Filtros (N)" nem `filtrosAbertos`): a página inteira recarrega
    # a cada mudança. Ver `test_filtros_tabela.py::
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
