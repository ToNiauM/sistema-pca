import importlib

from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core.models import Usuario

_migracao_0004 = importlib.import_module(
    "core.migrations.0004_usuario_senha_temporaria"
)


@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False)
class ModeloSenhaTemporariaTests(TestCase):
    """Fora do Admin, `create_user`/`create_superuser` nascem com
    `senha_temporaria=False`. Os três gatilhos reais viram código
    explícito: (a) migração de dados sobre a base já existente
    (`MigracaoMarcarUsuariosExistentesTests`), (b)
    `UsuarioAdmin.save_model` na criação pelo Admin
    (`AdminCriarUsuarioTests`), (c)
    `RedefinirSenhaComTrocaObrigatoriaForm` na redefinição pelo Admin
    (`AdminRedefinirSenhaTests`)."""

    def test_create_user_nasce_com_senha_temporaria_false(self):
        usuario = Usuario.objects.create_user(
            email="novo@exemplo.gov.br", password="senha-segura-123"
        )
        self.assertFalse(usuario.senha_temporaria)

    def test_create_superuser_tambem_nasce_com_senha_temporaria_false(self):
        superusuario = Usuario.objects.create_superuser(
            email="admin-novo@exemplo.gov.br", password="senha-segura-123"
        )
        self.assertFalse(superusuario.senha_temporaria)


@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False)
class MigracaoMarcarUsuariosExistentesTests(TestCase):
    """Gatilho (a): a função `RunPython` da migração 0004 marca só as
    linhas já presentes na tabela — chamada diretamente sobre um usuário
    criado com `senha_temporaria=False`."""

    def test_run_python_marca_usuarios_existentes_para_true(self):
        usuario = Usuario.objects.create_user(
            email="ja-existente@exemplo.gov.br", password="senha-antiga-123"
        )
        self.assertFalse(usuario.senha_temporaria)

        _migracao_0004.marcar_usuarios_existentes_para_troca_de_senha(
            apps=_ApposFake(), schema_editor=None
        )

        usuario.refresh_from_db()
        self.assertTrue(usuario.senha_temporaria)


class _ApposFake:
    """Substitui `apps.get_model(...)` do `RunPython` histórico pelo
    modelo real da aplicação — a função da migração só usa esse único
    método."""

    def get_model(self, app_label, model_name):
        assert app_label == "core"
        assert model_name == "Usuario"
        return Usuario


@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False)
class AdminCriarUsuarioTests(TestCase):
    """Gatilho (b): criar um usuário pelo Admin (com senha definida) marca
    `senha_temporaria=True` via `UsuarioAdmin.save_model`."""

    def setUp(self):
        self.superusuario = Usuario.objects.create_superuser(
            email="admin@exemplo.gov.br", password="senha-do-admin-123"
        )
        self.client = Client()
        self.client.force_login(self.superusuario)

    def test_post_admin_core_usuario_add_cria_com_senha_temporaria_true(self):
        url = reverse("admin:core_usuario_add")
        response = self.client.post(
            url,
            {
                "email": "novo-pelo-admin@exemplo.gov.br",
                "password1": "senha-definida-pelo-admin-123",
                "password2": "senha-definida-pelo-admin-123",
            },
        )
        self.assertEqual(response.status_code, 302)

        criado = Usuario.objects.get(email="novo-pelo-admin@exemplo.gov.br")
        self.assertTrue(criado.senha_temporaria)


@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False)
class AdminRedefinirSenhaTests(TestCase):
    """Redefinição de senha pelo Admin remarca o usuário-alvo, inclusive
    quando ele já havia trocado antes."""

    def setUp(self):
        self.superusuario = Usuario.objects.create_superuser(
            email="admin@exemplo.gov.br", password="senha-do-admin-123"
        )
        self.alvo = Usuario.objects.create_user(
            email="alvo@exemplo.gov.br", password="senha-antiga-123"
        )

        self.client = Client()
        self.client.force_login(self.superusuario)

    def test_redefinir_senha_pelo_admin_remarca_senha_temporaria(self):
        # Nome de rota HERDADO de `UserAdmin.get_urls()` — hardcoded como
        # "auth_user_password_change" por compatibilidade histórica do
        # Django, mesmo em `UserAdmin` estendido para um modelo de usuário
        # customizado noutro app (`core`, não `auth`). Confirmado ao vivo:
        # `admin.site._registry[Usuario].get_urls()` não gera
        # "core_usuario_password_change".
        url = reverse("admin:auth_user_password_change", args=[self.alvo.pk])
        response = self.client.post(
            url,
            {"password1": "nova-senha-definida-123", "password2": "nova-senha-definida-123"},
        )
        self.assertEqual(response.status_code, 302)

        self.alvo.refresh_from_db()
        self.assertTrue(self.alvo.senha_temporaria)

        # A senha nova é efetivamente aceita no login seguinte — POST real
        # em `/login/`, não `Client.login()` (AxesBackend exige `request`
        # como argumento de `authenticate()`, que só a view fornece).
        # Campo `username`, sucesso via redirect 302 comum — o form não é htmx.
        client_alvo = Client()
        response_login = client_alvo.post(
            "/login/",
            {"username": "alvo@exemplo.gov.br", "password": "nova-senha-definida-123"},
        )
        self.assertRedirects(
            response_login, "/inicio", fetch_redirect_response=False
        )


@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False)
class TrocaSenhaObrigatoriaMiddlewareTests(TestCase):
    """O middleware intercepta qualquer navegação de usuário autenticado
    com `senha_temporaria=True`, nenhuma rota de negócio é exceção (nem a
    de um superusuário), e as rotas isentas passam.

    `create_user`/`create_superuser` nascem com `senha_temporaria=False`
    — cada teste que precisa do estado "pendente" marca a flag
    explicitamente após criar o usuário."""

    def setUp(self):
        self.usuario = Usuario.objects.create_user(
            email="pendente@exemplo.gov.br", password="senha-antiga-123"
        )
        self.usuario.senha_temporaria = True
        self.usuario.save(update_fields=["senha_temporaria"])

    def test_get_raiz_com_senha_temporaria_redireciona_para_troca(self):
        client = Client()
        client.force_login(self.usuario)
        response = client.get("/")
        self.assertRedirects(
            response, "/senha/trocar/", fetch_redirect_response=False
        )

    def test_get_raiz_htmx_com_senha_temporaria_devolve_hx_redirect(self):
        client = Client()
        client.force_login(self.usuario)
        response = client.get("/", headers={"HX-Request": "true"})
        self.assertEqual(response["HX-Redirect"], "/senha/trocar/")

    def test_superusuario_com_senha_temporaria_tambem_e_redirecionado(self):
        superusuario = Usuario.objects.create_superuser(
            email="admin-pendente@exemplo.gov.br", password="senha-antiga-123"
        )
        superusuario.senha_temporaria = True
        superusuario.save(update_fields=["senha_temporaria"])

        client = Client()
        client.force_login(superusuario)
        response = client.get("/admin/")
        self.assertRedirects(
            response, "/senha/trocar/", fetch_redirect_response=False
        )

    def test_rotas_isentas_nao_sao_interceptadas(self):
        client = Client()
        client.force_login(self.usuario)

        self.assertEqual(client.get("/senha/trocar/").status_code, 200)
        self.assertEqual(client.get("/healthz").status_code, 200)
        self.assertEqual(client.get("/manifest.json").status_code, 200)
        self.assertEqual(client.get("/sw.js").status_code, 200)

    def test_logout_funciona_mesmo_com_senha_temporaria_pendente(self):
        client = Client()
        client.force_login(self.usuario)
        response = client.post("/logout/")
        # `logout_view` é um `redirect()` comum (302); o
        # `HtmxRedirectMiddleware` só converteria para HX-Redirect com o
        # cabeçalho HX-Request, que não é o caso aqui.
        self.assertRedirects(response, "/login/", fetch_redirect_response=False)

    def test_usuario_sem_senha_temporaria_navega_normalmente(self):
        self.usuario.senha_temporaria = False
        self.usuario.save(update_fields=["senha_temporaria"])

        client = Client()
        client.force_login(self.usuario)
        response = client.get("/")
        self.assertEqual(response.status_code, 200)


@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False)
class TrocarSenhaViewTests(TestCase):
    """Troca inválida mantém a flag e mostra erro inline; troca válida
    libera a navegação normal sem derrubar a sessão."""

    def setUp(self):
        self.senha_atual = "senha-antiga-123"
        self.usuario = Usuario.objects.create_user(
            email="pendente@exemplo.gov.br", password=self.senha_atual
        )
        self.usuario.senha_temporaria = True
        self.usuario.save(update_fields=["senha_temporaria"])

        self.client = Client()
        self.client.force_login(self.usuario)

    def test_senha_atual_errada_mantem_flag_e_mostra_erro(self):
        response = self.client.post(
            "/senha/trocar/",
            {
                "old_password": "senha-errada",
                "new_password1": "nova-senha-valida-456",
                "new_password2": "nova-senha-valida-456",
            },
        )
        self.assertEqual(response.status_code, 200)

        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.senha_temporaria)

    def test_senha_nova_reprovada_pelo_validador_mantem_flag_e_mostra_erro(self):
        response = self.client.post(
            "/senha/trocar/",
            {
                "old_password": self.senha_atual,
                "new_password1": "12345678",
                "new_password2": "12345678",
            },
        )
        self.assertEqual(response.status_code, 200)

        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.senha_temporaria)

    def test_troca_valida_libera_navegacao_e_mantem_sessao(self):
        # O form não é htmx: sucesso é um `redirect("core:inicio")` comum
        # (302), nunca `HX-Redirect`.
        response = self.client.post(
            "/senha/trocar/",
            {
                "old_password": self.senha_atual,
                "new_password1": "nova-senha-valida-456",
                "new_password2": "nova-senha-valida-456",
            },
        )
        self.assertRedirects(response, "/", fetch_redirect_response=False)

        self.usuario.refresh_from_db()
        self.assertFalse(self.usuario.senha_temporaria)

        # Sessão sobrevive: GET / subsequente é 200, sem novo redirecionamento.
        response_raiz = self.client.get("/")
        self.assertEqual(response_raiz.status_code, 200)
