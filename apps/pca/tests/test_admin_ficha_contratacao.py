"""Ficha da contratação no Django Admin (10/10/2026 — conferir e auditar o
que a extensão SEI Pro grava, antes de existir tela própria)."""

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.catalogo.models import Categoria, Exercicio, Tipo, Unidade
from apps.pca.models import FichaContratacao, Processo


@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False)
class FichaContratacaoAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser(email="adm@cfc.org.br", password="senha-segura")
        processo = Processo.objects.create(
            item_pca=156, descricao_objeto="Impressora multifuncional",
            tipo=Tipo.objects.create(nome="Aquisição"), categoria=Categoria.objects.create(nome="Bens"),
            unidade_organizacional=Unidade.objects.create(nome="GEX-GAFI"), exercicio=Exercicio.objects.get(ano=2026),
        )
        cls.ficha = FichaContratacao.objects.create(
            processo=processo, versao=3, dados={"objeto": {"valor": "Impressora A3", "origem": "usuario"}},
            atualizado_por=cls.admin,
        )

    def setUp(self):
        self.client = Client(HTTP_X_FORWARDED_PROTO="https")
        self.client.force_login(self.admin)

    def test_lista_e_detalhe_mostram_a_ficha(self):
        lista = self.client.get(reverse("admin:pca_fichacontratacao_changelist"))
        self.assertEqual(lista.status_code, 200)
        self.assertContains(lista, "156")
        detalhe = self.client.get(reverse("admin:pca_fichacontratacao_change", args=[self.ficha.pk]))
        self.assertEqual(detalhe.status_code, 200)
        self.assertContains(detalhe, "Impressora A3")

    def test_edicao_pelo_admin_sobe_a_versao_e_registra_o_autor(self):
        url = reverse("admin:pca_fichacontratacao_change", args=[self.ficha.pk])
        resposta = self.client.post(url, {"dados": '{"objeto": {"valor": "Impressora A4", "origem": "usuario"}}'})
        self.assertEqual(resposta.status_code, 302)
        self.ficha.refresh_from_db()
        self.assertEqual(self.ficha.versao, 4)
        self.assertEqual(self.ficha.dados["objeto"]["valor"], "Impressora A4")
        self.assertEqual(self.ficha.atualizado_por, self.admin)

    def test_nao_cria_pelo_admin(self):
        model_admin = admin.site._registry[FichaContratacao]
        request = self.client.get("/").wsgi_request
        request.user = self.admin
        self.assertFalse(model_admin.has_add_permission(request))

    def test_historico_das_versoes_registrado_no_grupo_de_auditoria(self):
        historico = admin.site._registry[FichaContratacao.history.model]
        self.assertEqual(historico.admin_grupo, "Auditoria e histórico")
