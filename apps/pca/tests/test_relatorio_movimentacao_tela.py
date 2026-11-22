"""Testes da tela "Relatório da reunião" (antes "Relatório de movimentação", Fase 27).

A view e a renderização HTML real nas DUAS cascas, via `django.test.Client` (convenções do projeto § 2): status,
cabeçalhos, estrutura (um <h1>, no máximo uma ação primária), o documento comum, a regra de cada casca
(DSGov: toda tabela num br-table; Tabler: nada de "dsgov" nem de classe br-*), filtros e permissão. A lógica
do documento está em `test_relatorio_reuniao.py`.
"""

import re
from html.parser import HTMLParser
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.catalogo.models import Exercicio
from apps.pca.models import Acompanhamento, Processo, Reuniao
from apps.pca.relatorio_reuniao import apurar_relatorio
from apps.pca.tests.test_relatorio_reuniao import cenario_reuniao
from core.tests.test_casca_tabler import CASCA_TABLER


class _Coletor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.h1 = 0
        self.primarios = 0
        self.svgs = []
        self.estilos = 0
        self.dentro_doc = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        if tag == "h1":
            self.h1 += 1
        if tag in ("a", "button") and (("br-button" in classes and "primary" in classes) or "btn-primary" in classes):
            self.primarios += 1
        if tag == "svg" and "abnt-svg" in classes:
            self.svgs.append(a)
        if a.get("id") == "relatorio-documento":
            self.dentro_doc = 1
        if self.dentro_doc and "style" in a:
            self.estilos += 1

    def handle_endtag(self, tag):
        if tag == "article":
            self.dentro_doc = 0


def _checkout_no_processo(*, corte, exercicio, reuniao, de, ate, usuario):
    """Substitui o subprocesso do checkout: apura no próprio processo, com `hoje` = dia do corte."""
    return apurar_relatorio(
        exercicio=exercicio, reuniao=reuniao, de=de, ate=ate, usuario=usuario,
        hoje=timezone.localtime(corte).date(),
    )


class RelatorioReuniaoTelaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.c = cenario_reuniao()
        cls.usuario = get_user_model().objects.create_user(email="relatorio-tela@pca.local", password="senha-forte-123")
        cls.usuario.user_permissions.add(
            Permission.objects.get(codename="view_acompanhamento", content_type__app_label="pca")
        )
        cls.url = reverse("pca:relatorio_movimentacao")

    def setUp(self):
        self.client.force_login(self.usuario)

    def _get(self, tabler=False, **params):
        if tabler:
            with CASCA_TABLER:
                return self.client.get(self.url, params)
        return self.client.get(self.url, params)

    def test_tela_nas_duas_cascas(self):
        for tabler in (False, True):
            with self.subTest(casca="tabler" if tabler else "dsgov"):
                resposta = self._get(tabler)
                self.assertEqual(resposta.status_code, 200)
                self.assertEqual(resposta["Cache-Control"], "private, no-store")
                html = resposta.content.decode()
                coletor = _Coletor()
                coletor.feed(html)
                self.assertEqual(coletor.h1, 1)
                self.assertLessEqual(coletor.primarios, 1)
                self.assertIn('id="relatorio-documento"', html)
                self.assertIn("2ª reunião de acompanhamento do PCA 2026", html)
                self.assertIn("Anexo I – Resumo por unidade organizacional", html)
                self.assertIn("Anexo II – Processos do PCA 2026, em ordem de item", html)
                self.assertIn('data-relatorio-acao="copiar"', html)
                self.assertIn('data-relatorio-acao="baixar-html"', html)
                self.assertIn("window.print()", html)
                self.assertIn("<title>Relatorio-reuniao-PCA-2026-10-01", html)
                self.assertEqual(coletor.estilos, 0, "documento sem style inline")
                self.assertEqual(len(coletor.svgs), 2)
                for svg in coletor.svgs:
                    self.assertEqual(svg.get("role"), "img")
                    self.assertTrue(svg.get("aria-label"))

    def test_dsgov_toda_tabela_dentro_de_br_table(self):
        html = self._get().content.decode()
        tabelas = html.count("<table")
        self.assertGreater(tabelas, 5)
        self.assertEqual(html.count('<div class="br-table abnt-tabela"><div class="table-header"></div><table'), tabelas)
        self.assertIn("dsgov-nao-imprimir", html)

    def test_tabler_sem_dsgov_nem_classe_br(self):
        html = self._get(tabler=True).content.decode()
        self.assertIn("tabler/vendor/tabler.min.css", html)
        self.assertNotIn("dsgov", html.lower())
        self.assertNotRegex(html, r'class="[^"]*\bbr-[a-z]')
        self.assertIn("d-print-none", html)
        self.assertIn('<div class="abnt-tabela"><table', html)

    def test_reuniao_aberta_vem_marcada_e_outra_pode_ser_escolhida(self):
        html = self._get().content.decode()
        marcada = re.search(r'id="reuniao_relatorio_(\d+)"[^>]*checked', html)
        self.assertEqual(int(marcada.group(1)), self.c["aberta"].pk)
        self.assertIn("2ª reunião – 01/10/2026 (em andamento)", html)
        with mock.patch("apps.pca.checkout.apurar_no_corte", side_effect=_checkout_no_processo):
            html = self._get(reuniao=self.c["anterior"].pk).content.decode()
        self.assertIn("1ª reunião de acompanhamento do PCA 2026", html)
        self.assertIn("<title>Relatorio-reuniao-PCA-2026-09-01", html)

    def test_campos_de_ate_vazios_no_primeiro_get_nas_duas_cascas(self):
        for tabler, padrao in ((False, r'<input id="de"[^>]*value="([^"]*)"'),
                               (True, r'<input class="form-control" id="de"[^>]*value="([^"]*)"')):
            with self.subTest(tabler=tabler):
                html = self._get(tabler).content.decode()
                self.assertEqual(re.search(padrao, html).group(1), "")
                self.assertEqual(re.search(padrao.replace('"de"', '"ate"'), html).group(1), "")

    def test_datas_livres_e_periodo_invalido(self):
        with mock.patch("apps.pca.checkout.apurar_no_corte", side_effect=_checkout_no_processo):
            html = self._get(de="2026-03-01", ate="2026-03-31").content.decode()
        self.assertIn("1 a 31/03/2026", html)
        html = self._get(de="2026-12-31", ate="2026-01-01").content.decode()
        self.assertIn("período padrão aplicado", html)

    def test_sem_exercicio_cadastrado(self):
        Acompanhamento.objects.all().delete()
        Reuniao.objects.all().delete()
        Processo.objects.all().delete()
        Exercicio.objects.all().delete()
        for tabler in (False, True):
            with self.subTest(tabler=tabler):
                resposta = self._get(tabler)
                self.assertEqual(resposta.status_code, 200)
                html = resposta.content.decode()
                self.assertIn("Nenhum exercício cadastrado.", html)
                coletor = _Coletor()
                coletor.feed(html)
                self.assertEqual(coletor.h1, 1)
                self.assertNotIn('id="relatorio-documento"', html)

    def test_permissao(self):
        sem_permissao = get_user_model().objects.create_user(email="sem-acompanhamento@pca.local", password="x-senha-123")
        self.client.force_login(sem_permissao)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_rotulo_do_menu(self):
        html = self._get().content.decode()
        self.assertIn("Relatório da reunião", html)
        self.assertNotIn("Relatório de movimentação", html)
