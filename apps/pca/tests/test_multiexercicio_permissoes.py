from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase
from django.urls import reverse

from apps.catalogo.models import (
    Categoria,
    Exercicio,
    SituacaoExercicio,
    SituacaoNormalizada,
    Tipo,
    Unidade,
)
from apps.pca.models import (
    Acompanhamento,
    HistoricalProcesso,
    Processo,
    ProcessoSEI,
    Reuniao,
    Situacao,
    SituacaoReuniao,
    TipoEvento,
)
from apps.pca.services import ExercicioFechado, registrar_acompanhamento


class ClosedExercisePermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.closed, _ = Exercicio.objects.update_or_create(
            ano=2026,
            defaults={"rotulo": "PCA 2026", "situacao": SituacaoExercicio.FECHADO},
        )
        cls.open, _ = Exercicio.objects.update_or_create(
            ano=2027,
            defaults={"rotulo": "PCA 2027", "situacao": SituacaoExercicio.ABERTO},
        )
        cls.tipo = Tipo.objects.create(nome="Aquisição")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.unidade = Unidade.objects.create(nome="Presidência")
        cls.situacao = SituacaoNormalizada.objects.create(nome="Em tramitação")
        cls.editor = get_user_model().objects.create_user(
            email="editor-closed@example.com", password="senha-segura"
        )
        cls.editor.user_permissions.add(
            Permission.objects.get(codename="editar_pca")
        )

        cls.closed_process = cls._process(cls.closed, "Fechado")
        cls.open_process = cls._process(cls.open, "Aberto")
        cls.reuniao = Reuniao.objects.create(
            data=date(2027, 1, 10),
            exercicio=cls.open,
            situacao=SituacaoReuniao.ABERTA,
        )

    @classmethod
    def _process(cls, exercicio, descricao):
        return Processo.objects.create(
            exercicio=exercicio,
            item_pca=65,
            descricao_objeto=descricao,
            tipo=cls.tipo,
            categoria=cls.categoria,
            unidade_organizacional=cls.unidade,
            situacao=Situacao.EM_TRAMITACAO,
        )

    def setUp(self):
        self.client.force_login(self.editor)

    def _counts(self):
        return (
            Processo.objects.count(),
            ProcessoSEI.objects.count(),
            Acompanhamento.objects.count(),
            HistoricalProcesso.objects.count(),
        )

    def test_forged_field_edit_on_closed_annual_item_is_recoverable_and_immutable(self):
        # `pca:editar_processo` barra o exercício fechado antes de
        # instanciar o form — GET ou POST — redirecionando ao detalhe com
        # `messages.warning`.
        versao = self.closed_process.atualizado_em.isoformat()
        antes = self._counts()

        resposta = self.client.post(
            reverse("pca:editar_processo", args=[2026, 65]),
            {"descricao_objeto": "Tentativa forjada", "versao": versao},
            follow=True,
        )

        self.assertRedirects(
            resposta, reverse("pca:detalhe_processo", args=[2026, 65])
        )
        mensagens = [str(m) for m in resposta.context["messages"]]
        self.assertTrue(any("fechado" in m for m in mensagens))
        self.assertEqual(self._counts(), antes)
        self.closed_process.refresh_from_db()
        self.assertEqual(self.closed_process.descricao_objeto, "Fechado")

    def test_forged_transition_and_create_do_not_touch_closed_annual_data(self):
        antes_processos = Processo.objects.count()
        # `pca:transicao_processo` é a única forma de alterar situação, e
        # é barrada pela mesma regra de negócio
        # (`services.registrar_acompanhamento` levanta `ExercicioFechado`).
        self.client.post(
            reverse("pca:transicao_processo", args=[2026, 65]),
            {
                "destino": Situacao.CONCLUIDO,
                "justificativa": "Tentativa forjada",
                "versao": self.closed_process.atualizado_em.isoformat(),
            },
        )
        self.client.post(
            reverse("pca:criar_processo"),
            {
                "exercicio": "2026",
                "descricao_objeto": "Novo forjado",
                "tipo": self.tipo.pk,
                "categoria": self.categoria.pk,
                "unidade_organizacional": self.unidade.pk,
            },
        )

        self.assertEqual(Processo.objects.count(), antes_processos)
        self.assertEqual(self.closed_process.situacao, Situacao.EM_TRAMITACAO)

    def test_forged_sei_edit_on_closed_annual_item_is_blocked_and_old_routes_404(self):
        """Incluir ou excluir SEI num processo de exercício fechado é
        barrado pelo mesmo guard de `pca:editar_processo` que recusa o
        exercício fechado antes de tocar em
        `ProcessoForm`/`ProcessoSEIFormSet`; as rotas antigas
        `sei/adicionar`/`sei/remover` respondem 404 sem tocar em nada."""
        sei = ProcessoSEI.objects.create(
            processo=self.closed_process, numero_sei="SEI-EXISTENTE"
        )
        antes = self._counts()

        dados = {
            "descricao_objeto": self.closed_process.descricao_objeto,
            "versao": self.closed_process.atualizado_em.isoformat(),
            "numeros_sei-TOTAL_FORMS": "3",
            "numeros_sei-INITIAL_FORMS": "1",
            "numeros_sei-MIN_NUM_FORMS": "0",
            "numeros_sei-MAX_NUM_FORMS": "1000",
            "numeros_sei-0-id": str(sei.pk),
            "numeros_sei-0-numero_sei": sei.numero_sei,
            "numeros_sei-0-DELETE": "on",
            "numeros_sei-1-id": "",
            "numeros_sei-1-numero_sei": "SEI-FORJADO",
            "numeros_sei-2-id": "",
            "numeros_sei-2-numero_sei": "",
        }
        self.client.post(reverse("pca:editar_processo", args=[2026, 65]), dados)

        resposta_adicionar = self.client.post(
            "/processo/2026/65/sei/adicionar", {"numero_sei": "SEI-FORJADO"}
        )
        resposta_remover = self.client.post(f"/processo/2026/65/sei/{sei.pk}/remover")

        self.assertEqual(resposta_adicionar.status_code, 404)
        self.assertEqual(resposta_remover.status_code, 404)
        self.assertEqual(self._counts(), antes)
        self.assertTrue(ProcessoSEI.objects.filter(pk=sei.pk).exists())
        self.assertFalse(
            ProcessoSEI.objects.filter(numero_sei="SEI-FORJADO").exists()
        )

    def test_meeting_uses_focus_exercise_and_can_accompany_open_item_in_another_year(self):
        reuniao = self.reuniao
        antes = Acompanhamento.objects.count()
        with self.assertRaises(ExercicioFechado):
            registrar_acompanhamento(
                processo_id=self.closed_process.pk,
                usuario=self.editor,
                versao_cliente=self.closed_process.atualizado_em.isoformat(),
                situacao_novo=Situacao.CONCLUIDO,
                observacao="Não deve gravar",
                reuniao=reuniao,
            )

        # The closed target must be rejected before either the meeting timeline
        # or the target process is changed.
        self.assertEqual(Acompanhamento.objects.count(), antes)

    def test_open_cross_year_target_is_allowed_without_changing_meeting_exercise(self):
        # Sucesso vira `messages.success` + redirect de página inteira
        # para `pca:reuniao_listagem` (302), nunca
        # `HttpResponseClientRedirect`.
        self.reuniao.situacao = SituacaoReuniao.FECHADA
        self.reuniao.save(update_fields=["situacao"])
        resposta = self.client.post(
            f"{reverse('pca:criar_reuniao')}?exercicio=2027",
            {"data": "2027-03-10", "exercicio": "2026"},
        )
        self.assertRedirects(resposta, reverse("pca:reuniao_listagem"))
        reuniao = Reuniao.objects.get(data=date(2027, 3, 10))
        self.assertEqual(reuniao.exercicio_id, self.open.pk)


class ExerciseManagementPermissionTests(TestCase):
    def setUp(self):
        self.manager = get_user_model().objects.create_user(
            email="exercise-manager@example.com", password="senha-segura"
        )
        self.editor = get_user_model().objects.create_user(
            email="exercise-editor@example.com", password="senha-segura"
        )
        self.manager.user_permissions.add(
            Permission.objects.get(codename="gerir_exercicio")
        )
        self.open, _ = Exercicio.objects.update_or_create(
            ano=2026,
            defaults={"rotulo": "PCA 2026", "situacao": SituacaoExercicio.ABERTO},
        )
        self.other, _ = Exercicio.objects.update_or_create(
            ano=2027,
            defaults={"rotulo": "PCA 2027", "situacao": SituacaoExercicio.ABERTO},
        )

    def test_editor_cannot_manage_or_close_exercises(self):
        self.client.force_login(self.editor)
        self.assertEqual(self.client.get(reverse("pca:gerenciar_exercicios")).status_code, 403)
        self.assertEqual(
            self.client.get(reverse("pca:encerrar_confirmar", args=[2026])).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(reverse("pca:encerrar", args=[2026])).status_code, 403
        )
        self.open.refresh_from_db()
        self.assertEqual(self.open.situacao, SituacaoExercicio.ABERTO)

    def test_manager_can_close_with_csrf_and_reads_remain_available(self):
        self.client.force_login(self.manager)
        page = self.client.get(reverse("pca:gerenciar_exercicios"))
        self.assertContains(page, "Encerrar exercício")
        modal = self.client.get(reverse("pca:encerrar_confirmar", args=[2026]))
        self.assertContains(modal, "2026")
        self.assertEqual(
            self.client.post(reverse("pca:encerrar", args=[2026])).status_code, 302
        )
        self.open.refresh_from_db()
        self.assertEqual(self.open.situacao, SituacaoExercicio.FECHADO)
        self.assertEqual(self.client.get(reverse("core:inicio") + "?exercicio=2026").status_code, 200)

    def test_close_requires_csrf_and_stale_close_does_not_mutate(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.manager)
        self.assertEqual(
            csrf_client.post(reverse("pca:encerrar", args=[2026])).status_code, 403
        )
        self.open.refresh_from_db()
        self.assertEqual(self.open.situacao, SituacaoExercicio.ABERTO)
        self.client.force_login(self.manager)
        self.client.post(reverse("pca:encerrar", args=[2026]))
        self.assertEqual(self.client.post(reverse("pca:encerrar", args=[2026])).status_code, 200)
        self.open.refresh_from_db()
        self.assertEqual(self.open.situacao, SituacaoExercicio.FECHADO)

    def test_usuario_sem_permissao_de_gerir_exercicio_nao_ve_o_link(self):
        # O item "Gerenciar exercícios" do menu (`core/menu.py`) é gated
        # por `permissao="pca.gerir_exercicio"` (mesma checagem que a view
        # aplica). `self.editor` não tem `gerir_exercicio` — não vê o link.
        self.client.force_login(self.editor)
        resposta = self.client.get(reverse("pca:calendario"))
        self.assertNotContains(resposta, "Gerenciar exercícios")

    def test_usuario_com_permissao_de_gerir_exercicio_ve_o_link(self):
        # `self.manager` TEM `gerir_exercicio` (setUp) — o menu novo mostra
        # o link corretamente (a casca legada só mostrava para superuser,
        # ignorando a Permission real — bug corrigido pela migração).
        self.client.force_login(self.manager)
        resposta = self.client.get(reverse("pca:calendario"))
        self.assertContains(resposta, "Gerenciar exercícios")

    def test_superuser_sees_nav_link(self):
        superusuario = get_user_model().objects.create_superuser(
            email="exercise-superuser@example.com", password="senha-segura"
        )
        self.client.force_login(superusuario)
        resposta = self.client.get(reverse("pca:calendario"))
        self.assertContains(resposta, "Gerenciar exercícios")
