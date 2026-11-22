"""Testes do documento comum `pca/_relatorio_reuniao_documento.html`, renderizado
direto, sem a página: substitui os testes do antigo fragmento copiável do Relatório de movimentação
(`_relatorio_movimentacao_corpo.html`, que deixou de existir — o "Copiar relatório" agora copia o próprio
documento, com os estilos calculados)."""

from datetime import date
from html.parser import HTMLParser

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import TestCase

from apps.pca.relatorio_reuniao import montar_relatorio_reuniao
from apps.pca.tests.test_relatorio_reuniao import HOJE, cenario_reuniao


class _Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class DocumentoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        c = cenario_reuniao()
        usuario = get_user_model().objects.create_user(email="doc-r9m@pca.local", password="senha-forte-123")
        cls.relatorio = montar_relatorio_reuniao(
            exercicio=c["exercicio"], reuniao=c["aberta"], de=date(2026, 9, 2), ate=HOJE, usuario=usuario, hoje=HOJE
        )

    def _render(self, **extra):
        html = render_to_string("pca/_relatorio_reuniao_documento.html", {"relatorio": self.relatorio, **extra})
        coletor = _Tags()
        coletor.feed(html)
        return html, coletor.tags

    def test_um_h1_sem_style_e_classes_neutras(self):
        for extra in ({}, {"casca_tabler": True}):
            with self.subTest(**extra):
                html, tags = self._render(**extra)
                self.assertEqual(sum(1 for t, _ in tags if t == "h1"), 1)
                self.assertFalse([t for t, a in tags if "style" in a])
                self.assertEqual(tags[0], ("article", {"class": "abnt-doc", "id": "relatorio-documento",
                                                       "aria-labelledby": "relatorio-titulo"}))

    def test_envoltorio_br_table_so_no_dsgov(self):
        html, _ = self._render()
        self.assertEqual(html.count('class="br-table abnt-tabela"'), html.count("<table"))
        html, tags = self._render(casca_tabler=True)
        self.assertNotIn("br-", html)
        self.assertNotIn("table-header", html)
        self.assertEqual(sum(1 for t, a in tags if t == "div" and a.get("class") == "abnt-tabela"), html.count("<table"))

    def test_conteudo_essencial(self):
        html, tags = self._render()
        for trecho in ("Relatório de acompanhamento", "1 Introdução", "2 Síntese da reunião", "Quadro 1",
                       "Quadro 2", "Itens ativos por situação", "3 Situação do PCA", "4 Registros da reunião", "5 Movimentação do período",
                       "Fonte: Sistema PCA CFC (15 out. 2026).", "Sinais convencionais: – zero; .. não se aplica.",
                       "20/09/2026 → 30/10/2026 (repactuado)", "GEX-A", "Cancelado"):
            self.assertIn(trecho, html)
        self.assertTrue(any(t == "section" and a.get("class") == "abnt-anexo-paisagem" for t, a in tags))
        self.assertTrue(any(t == "img" and a.get("alt") == "Conselho Federal de Contabilidade" for t, a in tags))

    def test_dois_graficos_e_quatro_cartoes(self):
        for extra in ({}, {"casca_tabler": True}):
            with self.subTest(**extra):
                html, tags = self._render(**extra)
                svgs = [a for t, a in tags if t == "svg"]
                self.assertEqual(len(svgs), 2, "só os dois gráficos de colunas; sem minibarras nem gráficos em barras")
                for a in svgs:
                    self.assertEqual(a.get("class"), "abnt-svg")
                    self.assertEqual(a.get("role"), "img")
                    self.assertTrue(a.get("aria-label"))
                cartoes = [a["class"].split() for t, a in tags if t == "div" and "abnt-cartao" in a.get("class", "").split()]
                self.assertEqual(len(cartoes), 4)
                self.assertEqual(sum(1 for c in cartoes if "abnt-cartao-alerta" in c), 1)
                self.assertEqual(html.count('class="abnt-cartao-numero"'), 4)
                self.assertEqual(html.count('class="abnt-cartao-rotulo"'), 4)
                self.assertIn("Gráfico 1</b> – Valor previsto e contratado", html)
                self.assertIn("Gráfico 2</b> – Itens ativos por unidade", html)
                self.assertNotIn("Gráfico 3", html)
