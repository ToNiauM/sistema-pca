"""Rota `assistente:documentacao` por slug do manifesto (A12): 200 com/sem permissão, 403, 404, traversal, 1 `<h1>`, 0 `br-button
primary`."""

import re

from django.test import Client
from django.urls import reverse

from apps.assistente.tests.base import AssistenteTestBase


class TestDocumentacao(AssistenteTestBase):
    def _client_como(self, usuario):
        cliente = Client(HTTP_X_FORWARDED_PROTO="https")
        cliente.force_login(usuario)
        return cliente

    def test_sobre_o_sistema_200_sem_secao_contato(self):
        resposta = self._client_como(self.visualizador).get(
            reverse("assistente:documentacao", args=["sobre-o-sistema"])
        )
        self.assertEqual(resposta.status_code, 200)
        conteudo = resposta.content.decode("utf-8")
        self.assertIn("Quem fez", conteudo)
        self.assertNotIn("WhatsApp", conteudo)
        self.assertNotIn("@cfc.org.br", conteudo)

    def test_analises_fluxo_de_caixa_403_para_visualizador_200_para_dirigente(self):
        url = reverse("assistente:documentacao", args=["analises-fluxo-de-caixa"])
        resposta_visualizador = self._client_como(self.visualizador).get(url)
        self.assertEqual(resposta_visualizador.status_code, 403)

        resposta_dirigente = self._client_como(self.dirigente).get(url)
        self.assertEqual(resposta_dirigente.status_code, 200)

    def test_solicitacoes_200_para_qualquer_autenticado(self):
        resposta = self._client_como(self.visualizador).get(
            reverse("assistente:documentacao", args=["solicitacoes"])
        )
        self.assertEqual(resposta.status_code, 200)
        conteudo = resposta.content.decode("utf-8")
        self.assertIn("Quem decide cada pedido", conteudo)
        self.assertIn("Como avaliar", conteudo)

    def test_slug_fora_do_manifesto_404(self):
        resposta = self._client_como(self.editor).get(
            reverse("assistente:documentacao", args=["deployment"])
        )
        self.assertEqual(resposta.status_code, 404)

    def test_traversal_no_slug_404(self):
        resposta = self._client_como(self.editor).get("/assistente/docs/..%2Fdeployment")
        self.assertIn(resposta.status_code, (404, 400))

    def test_sem_chave_404(self):
        from django.test import override_settings

        with override_settings(IA_API_KEY=""):
            resposta = self._client_como(self.editor).get(
                reverse("assistente:documentacao", args=["sobre-o-sistema"])
            )
        self.assertEqual(resposta.status_code, 404)

    def test_estrutura_um_h1_zero_botao_primary(self):
        resposta = self._client_como(self.editor).get(
            reverse("assistente:documentacao", args=["assistente"])
        )
        conteudo = resposta.content.decode("utf-8")
        self.assertEqual(len(re.findall(r"<h1[ >]", conteudo)), 1)
        self.assertEqual(conteudo.count("br-button primary"), 0)
