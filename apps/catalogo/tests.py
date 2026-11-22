from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from apps.pca.models import Acompanhamento, Processo

from .models import (
    Categoria,
    Exercicio,
    IndiceReajuste,
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

        # Golden number: 8 (linha de base, pré-Fase-25) → 9 no fechamento da
        # Fase 25 (`apps.pca.context_processors.
        # destinos_navegacao`, /A02-A03, rodava em TODA página do
        # engine "inclusive login/admin/healthz", somando 1 query mesmo em
        # páginas do Django Admin que nunca liam esse contexto) → de volta a
        # 8 na Fase 26: `destinos_navegacao` saiu por
        # completo (só existia para `_nav_visoes.html`/`_rodape_visoes.html`,
        # a casca legada removida nesta fase) — a query extra desapareceu
        # junto, não é regressão, é a correção que a própria Fase 25 já
        # apontava como efeito colateral indesejado. 8 → 9 na Fase 43: a casca
        # do Admin também desenha o menu lateral, que agora traz o contador "Para avaliar" das
        # Solicitações (1 COUNT constante, só para quem decide; não cresce com as linhas).
        with self.assertNumQueries(9):
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


class TestSeedIndiceReajuste(TestCase):
    """Fase 36 (spec §2.3) — o seed roda pela migração
    de dados `0004_indice_reajuste`, já aplicada pelo runner de teste
    padrão do Django (o banco de teste é criado do zero rodando todas as
    migrações) — nenhum `setUp` monta dado aqui, só confirma o que já está
    no banco."""

    def test_ipca_inpc_2024_e_2025_existem(self):
        for indice in ("IPCA", "INPC"):
            for ano in (2024, 2025):
                self.assertTrue(
                    IndiceReajuste.objects.filter(indice=indice, ano=ano).exists(),
                    f"{indice} {ano} ausente do seed",
                )

    def test_meta_bc_2026_a_2031_existe(self):
        for ano in range(2026, 2032):
            self.assertTrue(
                IndiceReajuste.objects.filter(indice="META_BC", ano=ano).exists(),
                f"META_BC {ano} ausente do seed",
            )

    def test_unique_constraint_indice_ano_rejeita_duplicata(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                IndiceReajuste.objects.create(
                    indice="IPCA", ano=2024, percentual=Decimal("9.99"),
                )
