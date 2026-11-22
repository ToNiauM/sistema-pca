"""Revisão da Fase 31 — `core.middleware.BancoOcupadoMiddleware`
traduz `OperationalError("database is locked")` numa mensagem amigável em
vez da página de erro 500 padrão do Django, só no caminho de escrita
(POST); GET simplesmente propaga."""

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.db import OperationalError
from django.http import HttpResponse
from django.test import Client, TestCase, override_settings
from django.urls import path


def _view_banco_ocupado(request):
    raise OperationalError("database is locked")


def _view_ok(request):
    return HttpResponse("ok")


urlpatterns = [
    path("banco-ocupado-teste/", _view_banco_ocupado, name="banco-ocupado-teste"),
    path("banco-ocupado-teste/ok/", _view_ok, name="banco-ocupado-teste-ok"),
]


@override_settings(ROOT_URLCONF="core.tests.test_middleware_banco_ocupado")
class TestBancoOcupadoMiddleware(TestCase):
    def setUp(self):
        self.usuario = get_user_model().objects.create_user(
            email="editor-banco-ocupado@pca.local", password="senha-segura"
        )
        self.client = Client()
        self.client.force_login(self.usuario)

    def test_post_com_banco_ocupado_redireciona_e_mostra_mensagem(self):
        resposta = self.client.post(
            "/banco-ocupado-teste/",
            HTTP_REFERER="/banco-ocupado-teste/ok/",
        )

        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(resposta.url, "/banco-ocupado-teste/ok/")

        resposta_destino = self.client.get(resposta.url)
        mensagens = [str(m) for m in get_messages(resposta_destino.wsgi_request)]
        self.assertIn(
            "O sistema está gravando outra alteração neste momento. "
            "Aguarde alguns segundos e tente novamente.",
            mensagens,
        )

    def test_post_sem_referer_redireciona_para_a_propria_url(self):
        resposta = self.client.post("/banco-ocupado-teste/")

        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(resposta.url, "/banco-ocupado-teste/")

    def test_get_com_banco_ocupado_propaga_o_erro(self):
        cliente_sem_conversao = Client(raise_request_exception=False)
        cliente_sem_conversao.force_login(self.usuario)

        resposta = cliente_sem_conversao.get("/banco-ocupado-teste/")

        self.assertEqual(resposta.status_code, 500)
