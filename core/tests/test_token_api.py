"""Testes de `TokenApi` (Fase 42): geração/
revogação em "Meu perfil", exibição em claro UMA única vez, e
`TokenApi.autenticar` (consumido pelo plano, ainda sem view nenhuma).

Verificação por requisição real (`django.test.Client`), nunca só grep de
template (convenções do projeto, Conventions §2)."""

from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core.models import TokenApi, Usuario


@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False)
class TokenApiModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = Usuario.objects.create_user(
            email="joao.pereira@cfc.org.br",
            password="senha-segura-123",
            first_name="João",
            last_name="Pereira",
        )

    def test_gerar_devolve_valor_em_claro_e_so_o_hash_e_persistido(self):
        instancia, valor_em_claro = TokenApi.gerar(self.usuario)

        self.assertTrue(valor_em_claro)
        armazenado = TokenApi.objects.get(pk=instancia.pk)
        self.assertNotEqual(armazenado.hash, valor_em_claro)
        self.assertNotIn(valor_em_claro, list(TokenApi.objects.values_list("hash", flat=True)))

    def test_gerar_de_novo_revoga_o_anterior(self):
        TokenApi.gerar(self.usuario)
        TokenApi.gerar(self.usuario)
        TokenApi.gerar(self.usuario)

        ativos = TokenApi.objects.filter(usuario=self.usuario, revogado_em__isnull=True)
        self.assertEqual(ativos.count(), 1)
        self.assertEqual(TokenApi.objects.filter(usuario=self.usuario).count(), 3)

    def test_autenticar_com_valor_certo_devolve_usuario_e_atualiza_ultimo_uso(self):
        _, valor_em_claro = TokenApi.gerar(self.usuario)

        usuario_autenticado = TokenApi.autenticar(valor_em_claro)

        self.assertEqual(usuario_autenticado, self.usuario)
        token = TokenApi.objects.get(usuario=self.usuario, revogado_em__isnull=True)
        self.assertIsNotNone(token.ultimo_uso_em)

    def test_autenticar_com_token_revogado_devolve_none(self):
        _, primeiro_valor = TokenApi.gerar(self.usuario)
        TokenApi.gerar(self.usuario)  # revoga o primeiro

        self.assertIsNone(TokenApi.autenticar(primeiro_valor))

    def test_autenticar_com_token_inexistente_devolve_none(self):
        self.assertIsNone(TokenApi.autenticar("valor-que-nunca-existiu"))


@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False)
class TokenApiTelaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = Usuario.objects.create_user(
            email="ana.souza@cfc.org.br",
            password="senha-segura-123",
            first_name="Ana",
            last_name="Souza",
        )

    def setUp(self):
        self.client = Client(HTTP_X_FORWARDED_PROTO="https")
        self.client.force_login(self.usuario)

    def test_get_depois_de_gerar_mostra_o_valor_em_claro_uma_vez(self):
        # `fetch_redirect_response=False`: o padrão de `assertRedirects` já
        # FAZ o GET de destino (consumiria `token_api_gerado` da sessão
        # antes da asserção abaixo) — aqui o GET de verificação é explícito.
        resposta_post = self.client.post(reverse("core:token_gerar"))
        self.assertRedirects(
            resposta_post, reverse("core:perfil"), fetch_redirect_response=False
        )

        token = TokenApi.objects.get(usuario=self.usuario, revogado_em__isnull=True)
        valor_em_claro = self.client.session["token_api_gerado"]

        resposta_get = self.client.get(reverse("core:perfil"))
        self.assertIn(valor_em_claro, resposta_get.content.decode())

        resposta_segundo_get = self.client.get(reverse("core:perfil"))
        self.assertNotIn(valor_em_claro, resposta_segundo_get.content.decode())
        # o token mascarado/"ativo desde" continua informado
        self.assertIn(f"{token.criado_em:%d/%m/%Y}", resposta_segundo_get.content.decode())

    def test_post_revogar_sem_token_ativo_nao_lanca_erro(self):
        resposta = self.client.post(reverse("core:token_revogar"))

        self.assertRedirects(resposta, reverse("core:perfil"))

    def test_post_revogar_com_token_ativo_revoga(self):
        self.client.post(reverse("core:token_gerar"))
        token = TokenApi.objects.get(usuario=self.usuario, revogado_em__isnull=True)

        resposta = self.client.post(reverse("core:token_revogar"))

        self.assertRedirects(resposta, reverse("core:perfil"))
        token.refresh_from_db()
        self.assertIsNotNone(token.revogado_em)


@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False)
class TokenApiTelaTablerTests(TestCase):
    """Produção usa `PCA_DESIGN=tabler` — o cartão do token tem de existir
    também em `tabler/templates/core/perfil.html` (achado da sessão sei-pro
    em 10/10/2026: o cartão só existia na casca DSGov)."""

    @classmethod
    def setUpTestData(cls):
        cls.usuario = Usuario.objects.create_user(email="bia@cfc.org.br", password="senha-segura-123")

    def setUp(self):
        self.client = Client(HTTP_X_FORWARDED_PROTO="https")
        self.client.force_login(self.usuario)

    def test_cartao_do_token_aparece_e_gera_mostrando_uma_vez(self):
        from core.tests.test_casca_tabler import CASCA_TABLER

        with CASCA_TABLER:
            html = self.client.get(reverse("core:perfil")).content.decode()
            self.assertIn("Token de API", html)
            self.assertIn(reverse("core:token_gerar"), html)
            self.assertIn("Nenhum token ativo", html)

            self.client.post(reverse("core:token_gerar"))
            valor = self.client.session["token_api_gerado"]
            html = self.client.get(reverse("core:perfil")).content.decode()
            self.assertIn(valor, html)
            self.assertIn(reverse("core:token_revogar"), html)
            self.assertNotIn(valor, self.client.get(reverse("core:perfil")).content.decode())
