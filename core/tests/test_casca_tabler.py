"""Casca Tabler (PCA_DESIGN=tabler, branch tabler).

Três garantias:
1. Os templates de tabler/templates/ não citam o design antigo em nada (nem classe, nem parcial, nem static,
   nem comentário) — a casca nova é independente.
2. Com a casca ligada, cada tela principal abre (200), sai com o CSS do Tabler, sem nenhum vestígio do design
   antigo no HTML renderizado, com exatamente um <h1> e no máximo uma ação primária, e gráficos acessíveis.
3. Sem a casca (padrão), nada muda: as mesmas telas continuam no design de sempre.
"""

import re
from html.parser import HTMLParser
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.urls import reverse

RAIZ = Path(settings.BASE_DIR) / "tabler" / "templates"
PROIBIDO = re.compile(r"dsgov|\bbr-[a-z]|\bfas? fa-|\bfa-[a-z]|text-(up|down)-0|text-gray-\d|text-weight-", re.I)


def _templates_tabler():
    motor = dict(settings.TEMPLATES[0])
    motor["DIRS"] = [RAIZ] + [d for d in motor["DIRS"] if Path(d) != RAIZ]
    opcoes = dict(motor["OPTIONS"])
    processadores = list(opcoes["context_processors"])
    if "core.context_processors.ui" not in processadores:
        processadores.append("core.context_processors.ui")
    opcoes["context_processors"] = processadores
    motor["OPTIONS"] = opcoes
    return [motor]


CASCA_TABLER = override_settings(TEMPLATES=_templates_tabler(), FORM_RENDERER="core.forms.renderer.TablerFormRenderer")


class TemplatesTablerIndependentesTest(SimpleTestCase):
    def test_nenhum_template_da_casca_cita_o_design_antigo(self):
        achados = []
        for arquivo in sorted(RAIZ.rglob("*.html")):
            for n, linha in enumerate(arquivo.read_text(encoding="utf-8").splitlines(), 1):
                if PROIBIDO.search(linha):
                    achados.append(f"{arquivo.relative_to(RAIZ)}:{n}: {linha.strip()[:120]}")
        self.assertEqual(achados, [], "\n".join(achados))

    def test_estaticos_da_casca_existem(self):
        estaticos = Path(settings.BASE_DIR) / "core" / "static" / "tabler"
        for relativo in ("vendor/tabler.min.css", "vendor/tabler.min.js", "vendor/tabler-icons/tabler-icons.min.css",
                         "vendor/echarts/echarts.min.js", "vendor/htmx/htmx.min.js", "js/pca-tabler.js",
                         "js/echarts-pca.js", "css/pca-tabler.css"):
            self.assertTrue((estaticos / relativo).is_file(), relativo)


class _Coletor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.h1 = 0
        self.primarios = 0
        self.graficos = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        if tag == "h1":
            self.h1 += 1
        if tag in ("a", "button") and "btn-primary" in classes:
            self.primarios += 1
        if "data-grafico" in a:
            self.graficos.append(a)


class TelasNaCascaTablerTest(TransactionTestCase):
    serialized_rollback = True

    def setUp(self):
        call_command("importar_pca", "Modelo_de_Controle_.xlsx", "--usuario=importador@pca.local",
                     "--exercicio=2026", stdout=StringIO())
        self.admin = get_user_model().objects.create_superuser(email="admin-tabler@pca.local", password="senha-segura")
        self.item_pca = 65

    def _urls(self):
        p = [2026, self.item_pca]
        return {
            "inicio": reverse("core:inicio"), "sobre": reverse("core:sobre"), "trocar_senha": reverse("core:trocar_senha"),
            "perfil": reverse("core:perfil"), "tabela": reverse("pca:tabela"), "busca": reverse("pca:busca") + "?q=contrata",
            "analise": reverse("pca:analise"), "analise_fluxo": reverse("pca:analise_fluxo"),
            "analise_estatisticas": reverse("pca:analise_estatisticas"), "analise_prazos": reverse("pca:analise_prazos"),
            "relatorio_movimentacao": reverse("pca:relatorio_movimentacao"), "calendario": reverse("pca:calendario"),
            "resumo_uo": reverse("pca:resumo_uo"), "gerenciar_exercicios": reverse("pca:gerenciar_exercicios"),
            "reuniao_listagem": reverse("pca:reuniao_listagem"), "reuniao_formulario": reverse("pca:criar_reuniao"),
            "exportar": reverse("pca:exportar"), "detalhe_processo": reverse("pca:detalhe_processo", args=p),
            "editar_processo": reverse("pca:editar_processo", args=p), "criar_processo": reverse("pca:criar_processo"),
            "transicao_processo": reverse("pca:transicao_processo", args=p),
            "encerrar_confirmar": reverse("pca:encerrar_confirmar", args=[2026]),
            "virada_selecionar": reverse("pca:virada", args=[2027]),
            # Fase 43 — Solicitações das unidades (o fluxo completo está em apps.solicitacoes.tests.test_telas).
            "solicitacoes_nova": reverse("solicitacoes:nova"), "solicitacoes_inclusao": reverse("solicitacoes:nova") + "?tipo=inclusao",
            "solicitacoes_minhas": reverse("solicitacoes:minhas"), "solicitacoes_avaliar": reverse("solicitacoes:avaliar"),
        }

    @CASCA_TABLER
    def test_login_na_casca_tabler(self):
        html = self.client.get(reverse("core:login")).content.decode()
        self.assertIn("tabler/vendor/tabler.min.css", html)
        self.assertNotIn("dsgov", html.lower())
        self.assertIn('name="username"', html)
        self.assertIn('name="password"', html)

    @CASCA_TABLER
    def test_telas_principais_na_casca_tabler(self):
        self.client.force_login(self.admin)
        for nome, url in self._urls().items():
            with self.subTest(tela=nome):
                resposta = self.client.get(url)
                self.assertEqual(resposta.status_code, 200, nome)
                html = resposta.content.decode()
                self.assertIn("tabler/vendor/tabler.min.css", html, nome)
                self.assertNotIn("dsgov", html.lower(), nome)
                self.assertNotRegex(html, r'class="[^"]*\bbr-[a-z]', nome)
                coletor = _Coletor()
                coletor.feed(html)
                self.assertEqual(coletor.h1, 1, f"{nome}: <h1>")
                self.assertLessEqual(coletor.primarios, 1, f"{nome}: ações primárias")
                for g in coletor.graficos:
                    self.assertEqual(g.get("role"), "img", nome)
                    self.assertTrue(g.get("aria-label"), nome)

    def test_sem_a_casca_nada_muda(self):
        if settings.PCA_DESIGN == "tabler":
            self.skipTest("suíte rodando com a casca Tabler ligada")
        self.client.force_login(self.admin)
        html = self.client.get(reverse("core:inicio")).content.decode()
        self.assertNotIn("tabler/vendor/tabler.min.css", html)
        self.assertIn("dsgov", html.lower())
