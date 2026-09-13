from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.pca.models import Acompanhamento, Processo

from .models import (
    Categoria,
    Exercicio,
    SituacaoNormalizada,
    Tipo,
    Unidade,
    normalizar_nome,
)


class NormalizacaoTests(TestCase):
    def test_normaliza_acento_e_caixa(self):
        self.assertEqual(normalizar_nome("Água"), "agua")
        self.assertEqual(normalizar_nome("Ação"), "acao")
        self.assertEqual(normalizar_nome("  Contratação  "), "contratacao")

    def test_save_deriva_nome_normalizado(self):
        u = Unidade.objects.create(nome="Água")
        self.assertEqual(u.nome_normalizado, "agua")
        self.assertEqual(Unidade.objects.create(nome="Ação").nome_normalizado, "acao")


class AdminCatalogoTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            email="admin@pca.local", password="x-forte-123"
        )
        self.client.force_login(self.admin)
        self.exercicio, _ = Exercicio.objects.get_or_create(
            ano=2026, defaults={"rotulo": "PCA 2026"}
        )

    def _criar_processo(self, unidade, item_pca):
        tipo = Tipo.objects.create(nome=f"Tipo {item_pca}")
        categoria = Categoria.objects.create(nome=f"Categoria {item_pca}")
        return Processo.objects.create(
            exercicio=self.exercicio,
            item_pca=item_pca,
            descricao_objeto=f"Objeto {item_pca}",
            tipo=tipo,
            categoria=categoria,
            unidade_organizacional=unidade,
        )

    def test_changelist_das_8_tabelas_responde_200(self):
        for modelo in (
            "unidade", "categoria", "tipo", "grauprioridade",
            "classificacao", "modalidade", "instrumentocontratual",
            "situacaonormalizada",
        ):
            url = reverse(f"admin:catalogo_{modelo}_changelist")
            self.assertEqual(self.client.get(url).status_code, 200, modelo)

    def test_uso_conta_via_annotate_sem_query_por_linha(self):
        unidade = Unidade.objects.create(nome="Unidade com processos")
        self._criar_processo(unidade, 1)
        self._criar_processo(unidade, 2)
        Unidade.objects.create(nome="Unidade sem processos")

        # 8 queries: annotate evita N+1 por linha
        with self.assertNumQueries(8):
            response = self.client.get(
                reverse("admin:catalogo_unidade_changelist")
            )

        self.assertContains(response, 'class="field-uso">2</td>', html=False)

    def test_exclusao_bloqueada_quando_em_uso(self):
        unidade = Unidade.objects.create(nome="Unidade protegida")
        self._criar_processo(unidade, 1)

        response = self.client.post(
            reverse("admin:catalogo_unidade_delete", args=[unidade.pk]),
            {"post": "yes"},
            follow=True,
        )

        self.assertTrue(Unidade.objects.filter(pk=unidade.pk).exists())
        self.assertContains(response, "Não é possível excluir")
        self.assertContains(response, "Unidade protegida")
        self.assertContains(response, "1 processo(s) ainda o referenciam.")

    def test_exclusao_permitida_quando_sem_uso(self):
        unidade = Unidade.objects.create(nome="Unidade livre")

        response = self.client.post(
            reverse("admin:catalogo_unidade_delete", args=[unidade.pk]),
            {"post": "yes"},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Unidade.objects.filter(pk=unidade.pk).exists())

    def test_situacao_normalizada_conta_acompanhamentos(self):
        unidade = Unidade.objects.create(nome="Unidade acompanhada")
        processo = self._criar_processo(unidade, 1)
        situacao = SituacaoNormalizada.objects.create(nome="Em acompanhamento")
        Acompanhamento.objects.create(
            processo=processo,
            referencia_data=date(2026, 1, 1),
            origem_hash="situacao-normalizada-admin",
            tipo_evento="atualizacao",
            situacao=situacao,
        )

        response = self.client.get(
            reverse("admin:catalogo_situacaonormalizada_changelist")
        )

        self.assertContains(response, 'class="field-uso">1</td>', html=False)
