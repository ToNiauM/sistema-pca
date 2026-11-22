"""Renderizador Markdown fechado (A04): HTML/links/
imagens do modelo nunca viram elemento ativo."""

from django.test import SimpleTestCase, override_settings

from apps.assistente.renderizacao import renderizar_referencias, renderizar_resposta


class TestRenderizarResposta(SimpleTestCase):
    def test_imagem_com_onerror_nao_vira_elemento_ativo(self):
        saida = renderizar_resposta("<img src=x onerror=alert(1)>")
        self.assertNotIn("<img", saida)
        self.assertIn("&lt;img", saida)

    def test_link_javascript_nao_vira_ancora(self):
        saida = renderizar_resposta("[x](javascript:alert(1))")
        self.assertNotIn("<a", saida)

    def test_script_e_escapado(self):
        saida = renderizar_resposta("<script>alert(1)</script>")
        self.assertNotIn("<script", saida)

    def test_negrito_italico_lista_codigo(self):
        saida = renderizar_resposta("**negrito** *itálico*\n\n- item um\n\n`codigo`")
        self.assertIn("<strong>negrito</strong>", saida)
        self.assertIn("<em>itálico</em>", saida)
        self.assertIn("<li>item um</li>", saida)
        self.assertIn("<code>codigo</code>", saida)

    def test_autolink_vira_texto(self):
        saida = renderizar_resposta("<https://exemplo.com>")
        self.assertNotIn("<a", saida)

    def test_tabela_markdown_vira_tabela_com_celula_escapada(self):
        saida = renderizar_resposta("| Item | Situação |\n|---|---|\n| 7 | <b>x</b> [a](javascript:1) |\n")
        self.assertIn("<table>", saida)
        self.assertIn("<th>Situação</th>", saida)
        self.assertIn('<div class="br-table small my-2"><div class="responsive"><table>', saida)
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", saida)
        self.assertNotIn("<a ", saida)

    @override_settings(PCA_DESIGN="tabler")
    def test_tabela_na_casca_tabler(self):
        saida = renderizar_resposta("| A | B |\n|---|---|\n| 1 | 2 |\n")
        self.assertIn('<table class="table table-sm table-bordered">', saida)

    def test_texto_vazio(self):
        self.assertEqual(renderizar_resposta(""), "")


class TestRenderizarReferencias(SimpleTestCase):
    def test_url_externa_nao_confiavel_vira_texto(self):
        saida = renderizar_referencias([{"rotulo": "Link", "url": "https://mal.example/"}])
        self.assertNotIn("<a", saida)
        self.assertIn("Link", saida)

    def test_url_relativa_vira_link(self):
        saida = renderizar_referencias([{"rotulo": "Processos", "url": "/tabela?uo=3"}])
        self.assertIn('<a href="/tabela?uo=3">Processos</a>', saida)

    def test_sem_referencias(self):
        self.assertEqual(renderizar_referencias([]), "")

    def test_rotulo_e_escapado(self):
        saida = renderizar_referencias([{"rotulo": "<script>x</script>", "url": "/tabela"}])
        self.assertNotIn("<script>x</script>", saida)
