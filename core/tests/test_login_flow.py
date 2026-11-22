from urllib.parse import parse_qs, urlsplit

from django.test import Client, TestCase, override_settings

from core.models import Usuario


@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False)
class LoginFlowTests(TestCase):
    """Fase 26 — `core/login.html` do padrão DSGov:
    página inteira (nunca fragmento HTMX), campo `username` (estrutura da
    padrão DSGov; só o rótulo virou "E-mail institucional"), sucesso via
    `redirect()` comum (nunca `HttpResponseClientRedirect`/`HX-Redirect`,
    que só fazia sentido com o form antigo em `hx-post`)."""

    def setUp(self):
        self.email = "pres@cfc.org.br"
        self.password = "correta"
        self.user = Usuario.objects.create_user(
            email=self.email, password=self.password
        )

    def test_get_login_renderiza_pagina_inteira_na_casca_do_padrao(self):
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

    def test_next_protocol_relative_url_nao_vaza_para_fora_do_site(self):
        """M1 — `//evil.example/x` e `///evil.example` são URLs relativas ao
        protocolo: `destino.startswith("/")` aceita as duas, mas o navegador
        as resolve para `http(s)://evil.example/...`. Precisa cair em
        `/inicio`, nunca sair do site."""
        for destino in ("//evil.example/x", "///evil.example"):
            with self.subTest(destino=destino):
                client = Client()
                response = client.post(
                    f"/login/?next={destino}",
                    {"username": self.email, "password": self.password},
                )
                self.assertRedirects(
                    response, "/inicio", fetch_redirect_response=False
                )

    def test_login_logout_login_csrf_round_trip(self):
        """Prova viva do fluxo CSRF completo (Pitfall 3): rotate_token() roda
        no login e no logout; o token tem que ser lido do cookie a cada
        request, nunca congelado num hx-headers estático."""
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

    # Fase 26 — `test_shell_has_accessible_hamburger_
    # markup`/`test_shell_tem_roteador_brnavigate_e_main_boostado` removidos:
    # os dois usavam `/calendario` como o ÚLTIMO exemplar sobrevivente da
    # casca `shell.html` (webcomponents/HTMX-router/`brMenuToggle`) — esta
    # mesma fase migra `/calendario` para `base.html`,
    # e nenhuma outra tela do sistema usa mais essa casca. `shell.html`
    # continua existindo em disco (remoção física é do plano), mas
    # sem nenhum consumidor vivo para provar o contrato contra uma
    # requisição real — os dois testes ficariam testando um arquivo morto,
    # não comportamento observável.

    def test_sessao_expirada_em_fragmento_htmx_leva_a_pagina_real_de_origem(self):
        """QA 30/09/2026, fluxos #9 — o `next=` do redirect de login numa
        requisição HTMX anônima tem de apontar para a PÁGINA real que o
        navegador mostra (`HX-Current-URL`), nunca para o path do
        fragmento que a requisição buscava (`acompanhamento`, que não tem
        casca/menu nenhum fora do swap)."""
        client = Client()
        response = client.get(
            "/processo/2026/15/acompanhamento",
            HTTP_HX_REQUEST="true",
            HTTP_HX_CURRENT_URL="http://testserver/tabela?situacao=atrasado",
        )
        self.assertIn("HX-Redirect", response)
        partes = urlsplit(response["HX-Redirect"])
        self.assertEqual(partes.path, "/login/")
        next_valor = parse_qs(partes.query)["next"][0]
        self.assertEqual(next_valor, "/tabela?situacao=atrasado")

    def test_five_wrong_attempts_render_lockout_copy_on_the_sixth(self):
        """Fecha o laço entre a prova de backend
        (AxesBackend levanta PermissionDenied na 6ª) e a experiência real
        do usuário na tela de login: a 6ª tentativa via HTTP renderiza a
        cópia de bloqueio, com status 200 (nunca 4xx) e o botão desabilitado."""
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
    """Reprodução do bug real (screenshot 12/09/2026
    09:49 -03): um token CSRF velho (bfcache/"Voltar" depois de um
    login/logout que girou o token via `rotate_token()`, ou uma aba de
    login esquecida aberta por horas) não pode mais cair na página crua
    "Verificação CSRF falhou" do Django — nem no login, nem em outra rota."""

    def setUp(self):
        self.email = "pres@cfc.org.br"
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
