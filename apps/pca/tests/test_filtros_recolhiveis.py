"""Tela Processos: o painel de filtros recolhe e reabre
("Ocultar filtros"/"Mostrar filtros", escolha lembrada no navegador) e todas
as caixas de filtro têm a mesma largura — antes, as de "Mais filtros" ficavam
recuadas e estreitas pelo padding do `br-accordion .content` do core
(~160px contra ~304px das principais). O comportamento visual (larguras,
recolher/expandir) é medido no navegador; aqui fica o contrato do HTML, do
CSS e do JS que o sustentam, nas duas cascas."""

import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.catalogo.models import Categoria, Modalidade, Tipo, Unidade

HTTPS = {"HTTP_X_FORWARDED_PROTO": "https"}
ESTATICOS = Path(settings.BASE_DIR) / "core" / "static"


class FiltrosRecolhiveisBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_superuser(
            email="filtros-f7r@example.com", password="senha-segura"
        )
        Unidade.objects.create(nome="GEX-F7R")
        Categoria.objects.create(nome="Serviços F7R")
        Tipo.objects.create(nome="Aquisição F7R")
        Modalidade.objects.create(nome="Pregão eletrônico F7R")

    def _pagina(self):
        self.client.force_login(self.usuario)
        return self.client.get(reverse("pca:tabela"), **HTTPS).content.decode()


class TestFiltrosRecolhiveisDsgov(FiltrosRecolhiveisBase):
    def test_botao_alterna_o_painel_de_filtros(self):
        conteudo = self._pagina()
        botao = re.search(r"<button[^>]*data-alternar-painel[^>]*>.*?</button>", conteudo, re.S).group(0)
        self.assertIn('aria-controls="painel-filtros"', botao)
        self.assertIn('aria-expanded="true"', botao)
        self.assertIn('data-rotulo-fechado="Mostrar filtros"', botao)
        self.assertIn("Ocultar filtros", botao)
        self.assertIn("br-button secondary", botao)
        self.assertEqual(conteudo.count("br-button primary"), 1)

    def test_painel_envolve_o_form_e_fica_fora_da_listagem(self):
        conteudo = self._pagina()
        painel = conteudo.index('id="painel-filtros"')
        form = conteudo.index('id="filtros-processos"')
        fim_painel = conteudo.index("</aside>", form)
        listagem = conteudo.index('id="listagem"')
        self.assertLess(painel, form)
        self.assertLess(fim_painel, listagem)
        self.assertIn('hx-include="#form-colunas, #estado-vista"', conteudo)

    def test_todos_os_campos_usam_a_mesma_coluna(self):
        conteudo = self._pagina()
        inicio = conteudo.index('id="filtros-processos"')
        form = conteudo[inicio: conteudo.index("</form>", inicio)]
        colunas = re.findall(r'<div class="(col-[^"]*) mb-3">', form)
        self.assertGreaterEqual(len(colunas), 10)
        self.assertEqual(set(colunas), {"col-12 col-md-6 col-lg-12"})

    def test_css_tira_o_recuo_do_mais_filtros_e_alarga_a_lista(self):
        css = (ESTATICOS / "dsgov" / "css" / "dsgov.css").read_text()
        self.assertIn(
            ".dsgov-filtros-lateral .br-accordion .content { margin: 0; padding: var(--spacing-scale-base) 0",
            css,
        )
        self.assertIn(
            '@media (min-width: 1280px) { .row.dsgov-painel-recolhido > [class*="col-lg-"] '
            "{ flex-basis: 100%; max-width: 100%; } }",
            css,
        )

    def test_js_lembra_a_escolha_sem_quebrar_sem_localstorage(self):
        js = (ESTATICOS / "dsgov" / "js" / "dsgov.js").read_text()
        self.assertIn('ev.target.closest("[data-alternar-painel]")', js)
        self.assertIn('try { return window.localStorage.getItem(CHAVE_PAINEL + id); } catch (e) { return null; }', js)
        self.assertIn('window.matchMedia("(min-width: 1280px)")', js)
        self.assertIn('classList.toggle("dsgov-painel-recolhido", !aberto)', js)


class TestFiltrosRecolhiveisTabler(FiltrosRecolhiveisBase):
    def _pagina_tabler(self):
        from core.tests.test_casca_tabler import CASCA_TABLER

        with CASCA_TABLER:
            return self._pagina()

    def test_cartao_de_filtros_recolhe_pelo_collapse(self):
        conteudo = self._pagina_tabler()
        self.assertIn('<div class="collapse show d-print-none" id="painel-filtros">', conteudo)
        botao = re.search(r"<button[^>]*data-alternar-filtros[^>]*>.*?</button>", conteudo, re.S).group(0)
        self.assertIn('data-bs-target="#painel-filtros"', botao)
        self.assertIn("Ocultar filtros", botao)
        painel = conteudo.index('id="painel-filtros"')
        self.assertLess(painel, conteudo.index('id="filtros-processos"'))
        self.assertLess(conteudo.index("</form>", painel), conteudo.index('id="listagem"'))

    def test_todos_os_campos_usam_a_mesma_coluna(self):
        conteudo = self._pagina_tabler()
        inicio = conteudo.index('id="filtros-processos"')
        form = conteudo[inicio: conteudo.index("</form>", inicio)]
        colunas = re.findall(r'<div class="(col-[^"]*?)(?: pb-2)?"(?: data-mais-filtro| id="acordeao-mais-filtros")?>', form)
        self.assertGreaterEqual(len(colunas), 10)
        self.assertEqual(set(colunas), {"col-12 col-sm-6 col-lg-3"})

    def test_js_lembra_a_escolha(self):
        js = (ESTATICOS / "tabler" / "js" / "pca-tabler.js").read_text()
        self.assertIn('var CHAVE_FILTROS = "pca:painel:painel-filtros";', js)
        self.assertIn("if (ev.target !== painel) return;", js)
