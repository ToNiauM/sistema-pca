"""Área "Meu perfil" e menu do avatar (Sair).

Verificação por requisição real (`django.test.Client`), nunca só grep de
template."""

import re
from pathlib import Path
import unittest

from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core import menu
from core.models import Usuario

SKILL_PROJETO = Path.home() / ".claude" / "skills" / "dsgov" / "assets" / "projeto"
RAIZ = Path(__file__).resolve().parents[2]


@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False)
class PerfilViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = Usuario.objects.create_user(
            email="maria.silva@exemplo.gov.br",
            password="senha-segura-123",
            first_name="Maria",
            last_name="Silva",
        )

    def setUp(self):
        self.client = Client(HTTP_X_FORWARDED_PROTO="https")
        self.client.force_login(self.usuario)

    def test_get_mostra_identidade_e_acoes(self):
        resposta = self.client.get(reverse("core:perfil"))
        self.assertEqual(resposta.status_code, 200)
        html = resposta.content.decode()
        self.assertIn("maria.silva@exemplo.gov.br", html)
        self.assertIn(">MS<", html)  # avatar-letra
        self.assertIn(reverse("core:trocar_senha"), html)
        self.assertIn(f'action="{reverse("core:logout")}"', html)
        self.assertEqual(html.count("<h1"), 1)
        self.assertEqual(html.count("br-button primary"), 1)

    def test_post_atualiza_nome_com_prg_e_mensagem(self):
        resposta = self.client.post(
            reverse("core:perfil"), {"first_name": "Ana", "last_name": "Souza"}
        )
        self.assertRedirects(resposta, reverse("core:perfil"), fetch_redirect_response=False)
        self.usuario.refresh_from_db()
        self.assertEqual((self.usuario.first_name, self.usuario.last_name), ("Ana", "Souza"))
        seguinte = self.client.get(reverse("core:perfil"))
        self.assertContains(seguinte, "Perfil atualizado.")
        self.assertContains(seguinte, ">AS<")

    def test_post_nao_altera_email_nem_senha(self):
        self.client.post(
            reverse("core:perfil"),
            {"first_name": "Ana", "last_name": "Souza", "email": "outro@x.com", "password": "nova"},
        )
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.email, "maria.silva@exemplo.gov.br")
        self.assertTrue(self.usuario.check_password("senha-segura-123"))

    def test_anonimo_vai_para_login(self):
        resposta = Client(HTTP_X_FORWARDED_PROTO="https").get(reverse("core:perfil"))
        self.assertEqual(resposta.status_code, 302)
        self.assertIn(reverse("core:login"), resposta.url)

    def test_header_e_menu_lateral_levam_ao_perfil(self):
        html = self.client.get(reverse("core:inicio")).content.decode()
        bloco = re.search(r'id="avatar-menu".*?<form method="post"', html, re.S).group(0)
        self.assertIn(f'href="{reverse("core:perfil")}"', bloco)
        self.assertIn("Meu perfil", bloco)
        rotulos = [i["rotulo"] for i in menu.itens(self._request())]
        self.assertIn("Meu perfil", rotulos)

    def _request(self):
        from django.test import RequestFactory

        request = RequestFactory().get("/")
        request.user = self.usuario
        return request


class IniciaisTests(TestCase):
    def test_duas_iniciais_do_nome(self):
        u = Usuario(email="x@y.z", first_name="José", last_name="da Costa")
        self.assertEqual(u.iniciais, "JD")

    def test_sem_nome_usa_email(self):
        self.assertEqual(Usuario(email="paulo@exemplo.gov.br").iniciais, "P")


class AvatarDropdownJsTests(TestCase):
    """O CSS do core esconde `.header-actions .dropdown:not(.show) .br-list`
    abaixo de 1280px; `dsgov.js` precisa espelhar `hidden` em `.show`."""

    def test_dsgov_js_sincroniza_show_do_wrapper(self):
        js = (RAIZ / "core/static/dsgov/js/dsgov.js").read_text(encoding="utf-8")
        self.assertIn("function sincronizarDropdown(btn)", js)
        self.assertIn('pai.classList.toggle("show", aberto)', js)
        self.assertIn("sincronizarDropdown(btn);", js)

    @unittest.skipUnless(SKILL_PROJETO.exists(), "skill dsgov não instalada neste host")
    def test_copias_do_projeto_identicas_a_skill(self):
        for rel in ("core/static/dsgov/js/dsgov.js", "core/templates/dsgov/_header.html"):
            with self.subTest(arquivo=rel):
                self.assertEqual(
                    (RAIZ / rel).read_bytes(), (SKILL_PROJETO / rel).read_bytes(),
                    f"{rel} divergiu da fonte da skill",
                )
