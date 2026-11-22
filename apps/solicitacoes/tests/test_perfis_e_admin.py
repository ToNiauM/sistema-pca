"""Grupos/permissões da migração de dados, restrição de unicidade no banco
e Admin do vínculo usuário↔unidade."""

from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction
from django.urls import reverse

from apps.solicitacoes.models import ParteSolicitacao, VinculoUnidade
from apps.solicitacoes.regras import Campo

from .base import CenarioBase


def _codenames(grupo):
    return set(
        Group.objects.get(name=grupo)
        .permissions.filter(content_type__app_label="solicitacoes")
        .values_list("codename", flat=True)
    )


class TestGruposEPermissoes(CenarioBase):
    def test_d43_02_grupos_e_permissoes_criados_pela_migracao(self):
        self.assertEqual(_codenames("solicitante"), {"solicitar"})
        self.assertEqual(_codenames("diretoria"), {"decidir_diretoria"})
        self.assertEqual(_codenames("editor"), {"decidir_equipe"})

    def test_d43_02_delegacao_e_por_grupo_so_quem_o_admin_poe_decide(self):
        grupo = Group.objects.get(name="diretoria")  # a migração o cria vazio
        self.assertEqual(
            set(grupo.user_set.values_list("email", flat=True)),
            {self.diretoria.email, self.ambos.email},  # os que o cenário pôs
        )
        self.assertTrue(self.diretoria.has_perm("solicitacoes.decidir_diretoria"))
        self.assertFalse(self.equipe.has_perm("solicitacoes.decidir_diretoria"))
        self.assertFalse(self.diretoria.has_perm("solicitacoes.decidir_equipe"))

    def test_d43_10_solicitante_nao_ganha_permissao_de_editar_o_pca(self):
        self.assertFalse(self.solicitante.has_perm("pca.editar_pca"))
        self.assertFalse(self.solicitante.has_perm("solicitacoes.decidir_equipe"))
        self.assertTrue(self.solicitante.has_perm("solicitacoes.solicitar"))


class TestRestricoesDoBanco(CenarioBase):
    def test_d43_05_o_banco_barra_duas_partes_pendentes_do_mesmo_campo_no_mesmo_item(self):
        from apps.solicitacoes import services

        services.criar_solicitacao(
            usuario=self.solicitante, processo_id=self.item.pk, justificativa="x",
            pedidos={Campo.MES_PREVISTO: 9},
        )
        outra = services.criar_solicitacao(
            usuario=self.solicitante, processo_id=self.item.pk, justificativa="y",
            pedidos={Campo.VALOR_ESTIMADO: "50"},
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            ParteSolicitacao.objects.create(
                solicitacao=outra, processo=self.item, campo=Campo.MES_PREVISTO, alcada="equipe",
                valor_pedido="10",
            )

    def test_vinculo_usuario_unidade_e_unico(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            VinculoUnidade.objects.create(usuario=self.solicitante, unidade=self.unidade)


class TestAdmin(CenarioBase):
    def setUp(self):
        self.client.force_login(self.admin)

    def test_vinculo_aparece_e_se_edita_na_tela_do_usuario(self):
        url = reverse("admin:core_usuario_change", args=[self.sem_vinculo.pk])
        resposta = self.client.get(url)
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "vinculos_unidade-TOTAL_FORMS")

        dados = {
            "email": self.sem_vinculo.email, "first_name": "", "last_name": "", "is_active": "on",
            "groups": [Group.objects.get(name="solicitante").pk],
            "date_joined_0": "2026-01-01", "date_joined_1": "00:00:00",
            "vinculos_unidade-TOTAL_FORMS": "1", "vinculos_unidade-INITIAL_FORMS": "0",
            "vinculos_unidade-MIN_NUM_FORMS": "0", "vinculos_unidade-MAX_NUM_FORMS": "1000",
            "vinculos_unidade-0-unidade": self.outra_unidade.pk,
            "vinculos_unidade-0-usuario": self.sem_vinculo.pk,
        }
        resposta = self.client.post(url, dados)
        self.assertEqual(resposta.status_code, 302, getattr(resposta, "context", None) and resposta.context["errors"])
        self.assertTrue(
            VinculoUnidade.objects.filter(usuario=self.sem_vinculo, unidade=self.outra_unidade).exists()
        )
        self.assertTrue(
            VinculoUnidade.history.filter(usuario=self.sem_vinculo, history_user=self.admin).exists()
        )

    def test_consulta_de_solicitacoes_e_historicos(self):
        from apps.solicitacoes import services

        solicitacao = services.criar_solicitacao(
            usuario=self.solicitante, processo_id=self.item.pk, justificativa="x",
            pedidos={Campo.MES_PREVISTO: 9},
        )
        for nome in (
            "solicitacoes_solicitacao_changelist",
            "solicitacoes_vinculounidade_changelist",
            "solicitacoes_historicalsolicitacao_changelist",
            "solicitacoes_historicalpartesolicitacao_changelist",
            "solicitacoes_historicalvinculounidade_changelist",
        ):
            with self.subTest(nome=nome):
                self.assertEqual(self.client.get(reverse(f"admin:{nome}")).status_code, 200)
        resposta = self.client.get(reverse("admin:solicitacoes_solicitacao_change", args=[solicitacao.pk]))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Mês previsto")

    def test_solicitacao_nao_se_cria_pelo_admin(self):
        self.assertEqual(self.client.get(reverse("admin:solicitacoes_solicitacao_add")).status_code, 403)
