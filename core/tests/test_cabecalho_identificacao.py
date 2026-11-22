"""QA 30/09/2026, periferia #4 — usuário sem `first_name` cadastrado tem de
ver o próprio e-mail no cabeçalho, nunca a palavra "None", nas duas cascas.
`Usuario.get_username()` (herdado de `AbstractBaseUser`) devolve sempre
`getattr(self, USERNAME_FIELD)` — como `USERNAME_FIELD = "email"`, isso
nunca é `None`; `username` no model É sempre `None`, daí o bug do
`default:user.username`."""

import pathlib

from django.conf import settings
from django.test import Client, TestCase, override_settings

from core.models import Usuario
from core.tests.test_casca_tabler import CASCA_TABLER


class CabecalhoSemDefaultParaUsernameTests(TestCase):
    def test_header_dsgov_nao_cita_default_user_username(self):
        conteudo = pathlib.Path(
            settings.BASE_DIR, "core", "templates", "dsgov", "_header.html"
        ).read_text(encoding="utf-8")
        self.assertNotIn("default:user.username", conteudo)
        self.assertIn("default:user.get_username", conteudo)

    def test_base_tabler_nao_cita_default_user_username(self):
        conteudo = pathlib.Path(
            settings.BASE_DIR, "tabler", "templates", "base.html"
        ).read_text(encoding="utf-8")
        self.assertNotIn("default:user.username", conteudo)
        self.assertIn("default:user.get_username", conteudo)


@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False)
class CabecalhoSemNoneParaUsuarioSemNomeTests(TestCase):
    def setUp(self):
        self.usuario = Usuario.objects.create_user(
            email="sem-nome@pca.local", password="senha-segura-261001"
        )

    def _assert_sem_none(self, conteudo):
        self.assertNotIn(">None<", conteudo)
        self.assertNotIn("None</span>", conteudo)

    def test_dsgov_usuario_sem_nome_nunca_mostra_none(self):
        client = Client()
        client.force_login(self.usuario)
        resposta = client.get("/")
        self._assert_sem_none(resposta.content.decode("utf-8"))

    def test_tabler_usuario_sem_nome_nunca_mostra_none(self):
        with CASCA_TABLER:
            client = Client()
            client.force_login(self.usuario)
            resposta = client.get("/")
            self._assert_sem_none(resposta.content.decode("utf-8"))
