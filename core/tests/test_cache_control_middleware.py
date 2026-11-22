"""QA 30/09/2026, fluxos #13 — toda resposta de usuário autenticado precisa
carregar `Cache-Control: private, no-store`, mesmo nas rotas que hoje não
setam o header manualmente. `/analise/fluxo`, `/reunioes` e `/perfil/` são
três exemplos reais sem esse header antes da correção (achado do QA)."""

from django.test import Client, TestCase, override_settings

from core.models import Usuario


@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False)
class CacheControlAutenticadoTests(TestCase):
    def setUp(self):
        self.usuario = Usuario.objects.create_user(
            email="leitor-cache-control@pca.local", password="senha-segura-261001"
        )
        self.client = Client()
        self.client.force_login(self.usuario)

    def test_rotas_sem_cache_control_proprio_ganham_private_no_store(self):
        for rota in ("/analise/fluxo", "/reunioes", "/perfil/"):
            with self.subTest(rota=rota):
                resposta = self.client.get(rota)
                self.assertEqual(
                    resposta["Cache-Control"], "private, no-store"
                )
