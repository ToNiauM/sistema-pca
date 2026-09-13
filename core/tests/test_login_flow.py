from django.test import Client, TestCase, override_settings

from core.models import Usuario


@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False)
class LoginFlowTests(TestCase):
    """`core/login.html` da skill dsgov: página inteira (nunca fragmento
    HTMX), campo `username` (só o rótulo virou "E-mail institucional"),
    sucesso via `redirect()` comum."""

    def setUp(self):
        self.email = "pres@exemplo.gov.br"
        self.password = "correta"
        self.user = Usuario.objects.create_user(
            email=self.email, password=self.password
        )

    def test_get_login_renderiza_pagina_inteira_na_casca_da_skill(self):
        client = Client()
        response = client.get("/login/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn('body class="dsgov-login"', content)
        self.assertIn('name="username"', content)
        self.assertIn('type="email"', content)
        self.assertIn("E-mail institucional", content)

    def test_visiting_root_without_session_redirects_to_login(self):
        client = Client()
        response = client.get("/")
        self.assertRedirects(
            response, "/login/?next=/", fetch_redirect_response=False
        )

    def test_invalid_credentials_return_200_with_inline_error_and_preserva_email(self):
        client = Client()
        response = client.post(
            "/login/", {"username": "errado@x.com", "password": "errado"}
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("E-mail ou senha incorretos.", content)
        self.assertIn('value="errado@x.com"', content)

    def test_valid_credentials_sem_next_redireciona_302_para_inicio(self):
        client = Client()
        response = client.post(
            "/login/", {"username": self.email, "password": self.password}
        )
        self.assertRedirects(response, "/inicio", fetch_redirect_response=False)

    def test_valid_credentials_com_next_respeita_o_destino(self):
        client = Client()
        response = client.post(
            "/login/?next=/tabela", {"username": self.email, "password": self.password}
        )
        self.assertRedirects(response, "/tabela", fetch_redirect_response=False)

    def test_login_logout_login_csrf_round_trip(self):
        """Fluxo CSRF completo: rotate_token() roda no login e no logout; o
        token tem que ser lido do cookie a cada request, nunca congelado
        num hx-headers estático."""
        client = Client(enforce_csrf_checks=True)

        client.get("/login/")
        csrf_token = client.cookies["csrftoken"].value
        response = client.post(
            "/login/",
            {
                "username": self.email,
                "password": self.password,
                "csrfmiddlewaretoken": csrf_token,
            },
        )
        self.assertRedirects(response, "/inicio", fetch_redirect_response=False)

        csrf_token = client.cookies["csrftoken"].value
        response_logout = client.post(
            "/logout/", {"csrfmiddlewaretoken": csrf_token}
        )
        self.assertRedirects(response_logout, "/login/", fetch_redirect_response=False)

        csrf_token = client.cookies["csrftoken"].value
        response2 = client.post(
            "/login/",
            {
                "username": self.email,
                "password": self.password,
                "csrfmiddlewaretoken": csrf_token,
            },
        )
        self.assertRedirects(response2, "/inicio", fetch_redirect_response=False)

    def test_shell_requires_login(self):
        client = Client()
        response = client.get("/")
        self.assertEqual(response.status_code, 302)

    def test_five_wrong_attempts_render_lockout_copy_on_the_sixth(self):
        """A 6ª tentativa via HTTP renderiza a cópia de bloqueio, com
        status 200 (nunca 4xx) e o botão desabilitado."""
        client = Client()
        for _ in range(5):
            client.post("/login/", {"username": self.email, "password": "errada"})

        response = client.post(
            "/login/", {"username": self.email, "password": "errada"}
        )

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Muitas tentativas.", content)
        self.assertIn("disabled", content)


@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False)
class TokenCsrfExpiradoTests(TestCase):
    """Um token CSRF velho (bfcache/"Voltar" depois de um login/logout que
    girou o token, ou uma aba de login esquecida aberta) não pode cair na
    página crua "Verificação CSRF falhou" do Django — nem no login, nem
    em outra rota."""

    def setUp(self):
        self.email = "pres@exemplo.gov.br"
        self.password = "correta"
        self.user = Usuario.objects.create_user(
            email=self.email, password=self.password
        )

    def test_get_login_nunca_cacheavel(self):
        response = self.client.get(
            "/login/", HTTP_X_FORWARDED_PROTO="https", HTTP_HOST="testserver"
        )
        self.assertIn("no-store", response.get("Cache-Control", ""))

    def test_token_invalido_reapresenta_login_com_mensagem_e_token_novo(self):
        client = Client(enforce_csrf_checks=True, HTTP_X_FORWARDED_PROTO="https")
        client.get("/login/", HTTP_HOST="testserver")

        with self.assertLogs("django.security.csrf", level="WARNING"):
            response = client.post(
                "/login/",
                {
                    "username": "errado@x.com",
                    "password": "y",
                    "csrfmiddlewaretoken": "invalido",
                },
                HTTP_HOST="testserver",
            )

        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, "core/login.html")
        content = response.content.decode("utf-8")
        self.assertIn("expirou", content.lower())
        self.assertNotIn("Proibido (403)", content)
        self.assertNotIn("Verificação CSRF falhou", content)
        self.assertIn('value="errado@x.com"', content)
        self.assertIn("csrftoken", response.cookies)

    def test_fluxo_real_token_velho_depois_logout_falha_amigavel_token_novo_funciona(
        self,
    ):
        client = Client(enforce_csrf_checks=True, HTTP_X_FORWARDED_PROTO="https")

        client.get("/login/", HTTP_HOST="testserver")
        token_velho = client.cookies["csrftoken"].value

        response = client.post(
            "/login/",
            {
                "username": self.email,
                "password": self.password,
                "csrfmiddlewaretoken": token_velho,
            },
            HTTP_HOST="testserver",
        )
        self.assertRedirects(response, "/inicio", fetch_redirect_response=False)

        token_pos_login = client.cookies["csrftoken"].value
        response_logout = client.post(
            "/logout/",
            {"csrfmiddlewaretoken": token_pos_login},
            HTTP_HOST="testserver",
        )
        self.assertRedirects(
            response_logout, "/login/", fetch_redirect_response=False
        )

        # Aba antiga: o token capturado ANTES do login (que já girou uma vez
        # em rotate_token()) é o único que o navegador tem em cache.
        response_velho = client.post(
            "/login/",
            {
                "username": self.email,
                "password": self.password,
                "csrfmiddlewaretoken": token_velho,
            },
            HTTP_HOST="testserver",
        )
        self.assertEqual(response_velho.status_code, 403)
        self.assertTemplateUsed(response_velho, "core/login.html")
        self.assertIn("expirou", response_velho.content.decode("utf-8").lower())

        # Novo GET+POST com o token que a re-renderização acabou de emitir: funciona.
        client.get("/login/", HTTP_HOST="testserver")
        token_novo = client.cookies["csrftoken"].value
        response_ok = client.post(
            "/login/",
            {
                "username": self.email,
                "password": self.password,
                "csrfmiddlewaretoken": token_novo,
            },
            HTTP_HOST="testserver",
        )
        self.assertRedirects(response_ok, "/inicio", fetch_redirect_response=False)

    def test_csrf_falho_em_outra_rota_autenticada_mostra_casca_de_erro(self):
        client = Client(enforce_csrf_checks=True, HTTP_X_FORWARDED_PROTO="https")
        client.force_login(self.user)
        response = client.post("/tabela", {}, HTTP_HOST="testserver")
        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, "core/erro.html")
        self.assertNotIn(
            "Verificação CSRF falhou", response.content.decode("utf-8")
        )

    def test_csrf_falho_htmx_devolve_hx_redirect(self):
        client = Client(enforce_csrf_checks=True, HTTP_X_FORWARDED_PROTO="https")
        client.force_login(self.user)
        response = client.post(
            "/tabela", {}, HTTP_HOST="testserver", HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("HX-Redirect", response)
