from django.contrib import admin
from django.contrib.auth.models import Group
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse

from axes.models import AccessAttempt

from core.models import Usuario

Usuario_history = Usuario.history.model


@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False)
class PcaAdminSiteGateTests(TestCase):
    """O gate exige is_active and is_superuser, mais restritivo que o
    is_staff padrão do AdminSite."""

    def setUp(self):
        self.staff_nao_superuser = Usuario.objects.create_user(
            email="staff@example.com", password="senha-segura", is_staff=True
        )
        self.superuser = Usuario.objects.create_superuser(
            email="admin@example.com", password="senha-segura"
        )

    def test_gate_exige_superuser(self):
        client = Client()
        client.force_login(self.staff_nao_superuser)

        response = client.get("/admin/")

        self.assertEqual(response.status_code, 302)

    def test_gate_permite_superuser_ativo(self):
        client = Client()
        client.force_login(self.superuser)

        response = client.get("/admin/")

        self.assertEqual(response.status_code, 200)


@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False)
class PcaAdminSiteIndiceTests(TestCase):
    """Prova que nenhum modelo desaparece do índice ao trocar o AdminSite
    e que o agrupamento pt-BR funciona."""

    @classmethod
    def setUpTestData(cls):
        cls.superuser = Usuario.objects.create_superuser(
            email="admin@example.com", password="senha-segura"
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.superuser)

    def test_indice_agrupa_usuarios_e_bloqueios(self):
        response = self.client.get("/admin/")

        grupo = next(
            (
                app
                for app in response.context["app_list"]
                if app["name"] == "Usuários e bloqueios de login"
            ),
            None,
        )
        self.assertIsNotNone(grupo)

        nomes_modelos = {modelo["object_name"] for modelo in grupo["models"]}
        self.assertEqual(
            nomes_modelos,
            {"Usuario", "AccessAttempt", "AccessLog", "AccessFailureLog"},
        )

    def test_indice_agrupa_historico_de_usuarios(self):
        response = self.client.get("/admin/")

        grupo = next(
            (
                app
                for app in response.context["app_list"]
                if app["name"] == "Auditoria e histórico"
            ),
            None,
        )
        self.assertIsNotNone(grupo)
        self.assertIn(
            Usuario_history,
            {modelo["model"] for modelo in grupo["models"]},
        )

    def test_nenhum_modelo_desaparece_do_indice(self):
        response = self.client.get("/admin/")

        total_no_indice = sum(
            len(app["models"]) for app in response.context["app_list"]
        )

        self.assertEqual(total_no_indice, len(admin.site._registry))


class HistoricalUsuarioAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.superuser = Usuario.objects.create_superuser(
            email="admin@example.com", password="senha-segura"
        )

    def setUp(self):
        self.request = RequestFactory().get("/admin/")
        self.request.user = self.superuser

    def test_historico_de_usuario_bloqueia_add_mas_delega_change_e_delete(self):
        model_admin = admin.site._registry[Usuario_history]

        self.assertFalse(model_admin.has_add_permission(self.request))
        self.assertTrue(model_admin.has_change_permission(self.request))
        self.assertTrue(model_admin.has_delete_permission(self.request))
        self.assertIn("delete_selected", model_admin.get_actions(self.request))


@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False)
class UsuarioAdminAcoesTests(TestCase):
    """Ação em massa de ativar/desativar usuário, com histórico via
    bulk_update_with_history, não queryset.update()."""

    @classmethod
    def setUpTestData(cls):
        cls.superuser = Usuario.objects.create_superuser(
            email="admin@example.com", password="senha-segura"
        )
        cls.alvo = Usuario.objects.create_user(
            email="alvo@example.com", password="senha-segura", is_active=True
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.superuser)

    def test_ativar_desativar_usuarios_gera_historico(self):
        response = self.client.post(
            reverse("admin:core_usuario_changelist"),
            {"action": "desativar_usuarios", "_selected_action": [self.alvo.pk]},
        )

        self.assertEqual(response.status_code, 302)
        self.alvo.refresh_from_db()
        self.assertFalse(self.alvo.is_active)
        self.assertTrue(
            Usuario_history.objects.filter(
                id=self.alvo.pk, history_type="~"
            ).exists()
        )


@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False)
class AxesAdminDesbloqueioTests(TestCase):
    """Ação explícita de desbloqueio, sem AlreadyRegistered na carga."""

    @classmethod
    def setUpTestData(cls):
        cls.superuser = Usuario.objects.create_superuser(
            email="admin@example.com", password="senha-segura"
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.superuser)

    def test_desbloqueio_remove_tentativas(self):
        tentativa = AccessAttempt.objects.create(
            username="bloqueado@example.com",
            ip_address="203.0.113.5",
            failures_since_start=5,
        )

        response = self.client.post(
            reverse("admin:axes_accessattempt_changelist"),
            {
                "action": "desbloquear_selecionados",
                "_selected_action": [tentativa.pk],
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            AccessAttempt.objects.filter(pk=tentativa.pk).exists()
        )


@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False)
class GrupoNaoCriadoTests(TestCase):
    """Nenhum grupo 'administrador' é criado automaticamente."""

    def test_grupo_administrador_nao_existe(self):
        self.assertFalse(Group.objects.filter(name="administrador").exists())
