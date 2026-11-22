from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from apps.catalogo.models import Categoria, Exercicio, Tipo, Unidade
from apps.pca.models import Estado, Processo, Reuniao, Situacao, SituacaoReuniao


class ReuniaoConstraintTests(TestCase):
    def test_data_da_reuniao_e_unica(self):
        exercicio = Exercicio.objects.get(ano=2026)
        Reuniao.objects.create(
            data="2026-06-30", situacao=SituacaoReuniao.FECHADA, exercicio=exercicio
        )
        with self.assertRaises(IntegrityError):
            Reuniao.objects.create(
                data="2026-06-30", situacao=SituacaoReuniao.FECHADA, exercicio=exercicio
            )

    def test_no_maximo_uma_reuniao_aberta_e_varias_fechadas(self):
        exercicio = Exercicio.objects.get(ano=2026)
        Reuniao.objects.create(
            data="2026-05-31", situacao=SituacaoReuniao.FECHADA, exercicio=exercicio
        )
        Reuniao.objects.create(
            data="2026-06-30", situacao=SituacaoReuniao.FECHADA, exercicio=exercicio
        )
        Reuniao.objects.create(
            data="2026-07-31", situacao=SituacaoReuniao.ABERTA, exercicio=exercicio
        )
        with self.assertRaises(IntegrityError):
            Reuniao.objects.create(
                data="2026-08-31", situacao=SituacaoReuniao.ABERTA, exercicio=exercicio
            )


class AuditoriaProcessoTests(TestCase):
    """/02: editar um Processo pelo Admin grava linha em
    HistoricalProcesso com history_user preenchido."""

    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            email="admin@pca.local", password="x-forte-123"
        )
        self.client.force_login(self.admin)
        self.unidade = Unidade.objects.create(nome="Presidência")
        self.categoria = Categoria.objects.create(nome="Serviços")
        self.tipo = Tipo.objects.create(nome="Aquisição")

    def test_criar_processo_via_admin_gera_historico_com_usuario(self):
        resp = self.client.post(
            reverse("admin:pca_processo_add"),
            {
                "item_pca": 42,
                "descricao_objeto": "Objeto de teste",
                "tipo": self.tipo.pk,
                "categoria": self.categoria.pk,
                "unidade_organizacional": self.unidade.pk,
                # Fase 17 (regressão direta): `estado`/
                # `situacao` deixaram de ser `readonly_fields` (deviation
                # provisória do plano) para virarem editáveis no admin
                #o `ModelForm` padrão agora os exige em toda
                # criação, `blank=False`. Sem eles, este POST falhava a
                # validação em silêncio (form redisplay 200, nenhum
                # `Processo` criado).
                "estado": Estado.ATIVO.value,
                "situacao": Situacao.NO_PRAZO.value,
                "exercicio": Exercicio.objects.get(ano=2026).pk,
                # ProcessoSEI continua em admin separado, mas a Fase 36 acrescentou `EventoFinanceiroInline`
                # a `ProcessoAdmin` — o management form do formset precisa
                # estar presente mesmo sem nenhuma linha, senão o Django
                # rejeita a submissão inteira (200, formulário redesenhado).
                "eventos_financeiros-TOTAL_FORMS": "0",
                "eventos_financeiros-INITIAL_FORMS": "0",
                "eventos_financeiros-MIN_NUM_FORMS": "0",
                "eventos_financeiros-MAX_NUM_FORMS": "1000",
            },
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        proc = Processo.objects.get(item_pca=42)
        self.assertEqual(proc.history.count(), 1)
        self.assertEqual(proc.history.first().history_user, self.admin)


class ManagerAuditadoTests(TestCase):
    def test_update_em_massa_e_bloqueado(self):
        with self.assertRaises(NotImplementedError):
            Processo.objects.update(situacao=Situacao.CONCLUIDO.value)

    def test_filter_update_tambem_e_bloqueado(self):
        with self.assertRaises(NotImplementedError):
            Processo.objects.filter(item_pca=1).update(situacao=Situacao.CONCLUIDO.value)


class UsuarioServicoTests(TestCase):
    """Importador@pca.local existe após o migrate, sem login possível."""

    def test_usuario_servico_existe_e_e_inutilizavel(self):
        u = get_user_model().objects.get(email="importador@pca.local")
        self.assertFalse(u.is_active)
        self.assertFalse(u.is_staff)
        self.assertFalse(u.has_usable_password())
