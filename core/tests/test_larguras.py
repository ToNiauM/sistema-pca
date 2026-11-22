"""Larguras de coluna na conta do usuário: o localStorage era por domínio, e o sistema
responde em pca.sistemascfc.org e em pca.analisedados.online — a largura ajustada tem de valer nos dois."""

import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import PreferenciaLarguras
from core.tests.test_casca_tabler import CASCA_TABLER


class LargurasTest(TestCase):
    def setUp(self):
        self.usuario = get_user_model().objects.create_user(email="largura@pca.local", password="senha-segura-123")
        self.client.force_login(self.usuario)
        self.url = reverse("core:larguras")

    def _post(self, dados):
        return self.client.post(self.url, json.dumps(dados), content_type="application/json")

    def _larguras(self):
        return PreferenciaLarguras.objects.get(usuario=self.usuario).larguras

    def test_grava_por_tabela_e_coluna(self):
        self.assertEqual(self._post({"tabela": "/tabela#0", "coluna": "descricao_objeto", "largura": 420}).status_code, 200)
        self._post({"tabela": "/tabela#0", "coluna": "valor_estimado", "largura": 150.4})
        self.assertEqual(self._larguras(), {"/tabela#0": {"descricao_objeto": 420, "valor_estimado": 150}})

    def test_largura_nula_restaura_a_coluna_e_coluna_nula_a_tabela(self):
        self._post({"tabela": "/tabela#0", "coluna": "descricao_objeto", "largura": 420})
        self._post({"tabela": "/tabela#0", "coluna": "valor_estimado", "largura": 150})
        self._post({"tabela": "/tabela#0", "coluna": "descricao_objeto", "largura": None})
        self.assertEqual(self._larguras(), {"/tabela#0": {"valor_estimado": 150}})
        self._post({"tabela": "/tabela#0", "coluna": None, "largura": None})
        self.assertEqual(self._larguras(), {})

    def test_recusa_valores_invalidos(self):
        for dados in (
            {"tabela": "/tabela#0", "coluna": "x", "largura": 5},
            {"tabela": "/tabela#0", "coluna": "x", "largura": 99999},
            {"tabela": "/tabela#0", "coluna": "x", "largura": "200"},
            {"tabela": "/tabela#0", "coluna": "x", "largura": True},
            {"tabela": "", "coluna": "x", "largura": 200},
            {"tabela": "/t#0", "coluna": "x" * 300, "largura": 200},
            {"tabela": ["/t"], "coluna": "x", "largura": 200},
            ["lista"],
        ):
            with self.subTest(dados=dados):
                self.assertEqual(self._post(dados).status_code, 400)
        resposta = self.client.post(self.url, "{nao-json", content_type="application/json")
        self.assertEqual(resposta.status_code, 400)
        self.assertFalse(PreferenciaLarguras.objects.filter(usuario=self.usuario).exclude(larguras={}).exists())

    def test_recusa_valores_nao_finitos(self):
        """QA de segurança 30/09/2026 (achado B2) — `NaN`/`Infinity`/um
        literal grande o bastante para virar `inf` em JSON puro (`1e400`)
        passam no `isinstance(largura, (int, float))`, mas derrubavam
        `int(round(largura))` com `ValueError`/`OverflowError` — a view
        deixava o 500 escapar (sem `try/except` ali). Precisa responder 400
        e não gravar nada, mesmo padrão de `test_recusa_valores_invalidos`."""
        for dados in (
            {"tabela": "/tabela#0", "coluna": "x", "largura": float("nan")},
            {"tabela": "/tabela#0", "coluna": "x", "largura": float("inf")},
            {"tabela": "/tabela#0", "coluna": "x", "largura": float("-inf")},
            {"tabela": "/tabela#0", "coluna": "x", "largura": 1e400},
        ):
            with self.subTest(dados=dados):
                self.assertEqual(self._post(dados).status_code, 400)
        self.assertFalse(
            PreferenciaLarguras.objects.filter(usuario=self.usuario)
            .exclude(larguras={})
            .exists()
        )

    def test_teto_de_tabelas_por_conta(self):
        """QA de segurança 30/09/2026 (achado B2) — 300 POSTs com chaves de
        tabela distintas inflavam o JSON da conta sem limite algum (lido a
        cada página). A 201ª tabela NOVA é recusada; apagar coluna/tabela
        (`largura`/`coluna` None) nunca é bloqueado por este teto."""
        for i in range(PreferenciaLarguras.LIMITE_TABELAS):
            self.assertTrue(
                PreferenciaLarguras.gravar(self.usuario, f"/t{i}#0", "x", 100)
            )
        self.assertEqual(
            len(PreferenciaLarguras.objects.get(usuario=self.usuario).larguras),
            PreferenciaLarguras.LIMITE_TABELAS,
        )
        self.assertFalse(
            PreferenciaLarguras.gravar(
                self.usuario, "/t-nova-201#0", "x", 100
            )
        )
        self.assertEqual(
            len(PreferenciaLarguras.objects.get(usuario=self.usuario).larguras),
            PreferenciaLarguras.LIMITE_TABELAS,
        )
        # Apagar continua liberado mesmo com o teto atingido.
        self.assertTrue(
            PreferenciaLarguras.gravar(self.usuario, "/t0#0", None, None)
        )

    def test_get_nao_permitido(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_anonimo_nao_grava(self):
        self.client.logout()
        resposta = self._post({"tabela": "/tabela#0", "coluna": "x", "largura": 200})
        self.assertNotEqual(resposta.status_code, 200)
        self.assertFalse(PreferenciaLarguras.objects.exists())

    def test_da_pagina_filtra_pelo_caminho(self):
        PreferenciaLarguras.gravar(self.usuario, "/tabela#0", "objeto", 300)
        PreferenciaLarguras.gravar(self.usuario, "/tabela-outra#0", "objeto", 500)
        self.assertEqual(PreferenciaLarguras.da_pagina(self.usuario, "/tabela"), {"/tabela#0": {"objeto": 300}})

    @CASCA_TABLER
    def test_casca_tabler_nao_publica_mais_larguras(self):
        """A grade estilo Excel saiu das duas cascas: a página não publica mais as
        larguras gravadas nem a URL de gravação (a tabela não tem mais colunas ajustáveis)."""
        caminho = reverse("core:sobre")
        PreferenciaLarguras.gravar(self.usuario, caminho + "#0", "objeto", 321)
        html = self.client.get(caminho, HTTP_X_FORWARDED_PROTO="https").content.decode()
        self.assertNotIn('id="pca-larguras"', html)
        self.assertNotIn("PCA_URL_LARGURAS", html)

    def test_casca_dsgov_nao_publica_mais_larguras(self):
        """Idem na casca gov.br: sem `dsgov_larguras_url` no contexto, o base.html
        do padrão DSGov não declara a meta nem o json_script."""
        caminho = reverse("core:sobre")
        PreferenciaLarguras.gravar(self.usuario, caminho + "#0", "objeto", 333)
        html = self.client.get(caminho, HTTP_X_FORWARDED_PROTO="https").content.decode()
        self.assertNotIn("dsgov-larguras", html)

    def test_anonimo_nao_recebe_meta_de_larguras(self):
        self.client.logout()
        html = self.client.get(reverse("core:login"), HTTP_X_FORWARDED_PROTO="https").content.decode()
        self.assertNotIn("dsgov-larguras", html)


class TestTabelaSemGradeExcel(TestCase):
    """Tabela canônica nas duas cascas: nenhuma alça de largura, nenhuma grade
    vertical; só a coluna de ações fixa à direita continua."""

    def test_js_e_css_das_duas_cascas_sem_colunas_ajustaveis(self):
        from pathlib import Path

        raiz = Path(__file__).resolve().parents[2] / "core/static"
        for nome in ("dsgov/js/dsgov.js", "dsgov/css/dsgov.css", "tabler/js/pca-tabler.js", "tabler/css/pca-tabler.css"):
            conteudo = (raiz / nome).read_text()
            with self.subTest(arquivo=nome):
                self.assertNotIn("coluna-alca", conteudo)
                self.assertNotIn("tabela-grade", conteudo)
                self.assertNotIn("col-resize", conteudo)
                self.assertIn("col-fixa", conteudo)
