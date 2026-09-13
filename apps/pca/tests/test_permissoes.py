from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib import admin
from django.test import RequestFactory, TestCase
from django.urls import reverse

from apps.catalogo.models import Categoria, Exercicio, SituacaoNormalizada, Tipo, Unidade
from apps.pca.models import (
    Acompanhamento,
    Processo,
    ProcessoSEI,
    RascunhoItemVirada,
    RascunhoVirada,
    Reuniao,
    TipoEvento,
)


class TestGruposEPermissao(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.editor = User.objects.create_user(
            email="editor@example.com", password="senha-segura"
        )
        cls.visualizador = User.objects.create_user(
            email="visualizador@example.com", password="senha-segura"
        )
        cls.sem_grupo = User.objects.create_user(
            email="sem-grupo@example.com", password="senha-segura"
        )
        cls.superuser = User.objects.create_superuser(
            email="admin@example.com", password="senha-segura"
        )

        cls.editor.groups.add(Group.objects.get(name="editor"))
        cls.visualizador.groups.add(Group.objects.get(name="visualizador"))

    def test_grupos_e_permissao_sao_criados(self):
        self.assertEqual(
            Group.objects.filter(name__in=("editor", "visualizador")).count(), 2
        )
        self.assertTrue(
            Permission.objects.filter(
                codename="editar_pca", content_type__app_label="pca"
            ).exists()
        )

    def test_editor_tem_permissao(self):
        self.assertTrue(self.editor.has_perm("pca.editar_pca"))

    def test_visualizador_nao_tem_permissao(self):
        self.assertFalse(self.visualizador.has_perm("pca.editar_pca"))

    def test_usuario_sem_grupo_falha_fechado(self):
        self.assertFalse(self.sem_grupo.has_perm("pca.editar_pca"))

    def test_superuser_tem_permissao_sem_grupo(self):
        self.assertFalse(self.superuser.groups.exists())
        self.assertTrue(self.superuser.has_perm("pca.editar_pca"))

    def test_grupos_e_permissao_sao_idempotentes(self):
        self.assertEqual(
            Group.objects.filter(name__in=("editor", "visualizador")).count(), 2
        )
        self.assertEqual(
            Permission.objects.filter(
                codename="editar_pca", content_type__app_label="pca"
            ).count(),
            1,
        )


class TestBloqueioExclusaoAdmin(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_superuser(
            email="admin-admin@example.com", password="senha-segura"
        )
        cls.usuario_sem_permissao = get_user_model().objects.create_user(
            email="sem-exclusao@example.com", password="senha-segura"
        )
        cls.unidade = Unidade.objects.create(nome="Presidência")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.tipo = Tipo.objects.create(nome="Aquisição")
        cls.exercicio = Exercicio.objects.get(ano=2026)

    def setUp(self):
        self.request = RequestFactory().get("/admin/")
        self.request.user = self.usuario

    def _processo_elegivel(self):
        return Processo.objects.create(
            item_pca=1,
            descricao_objeto="Processo elegível para exclusão",
            tipo=self.tipo,
            categoria=self.categoria,
            unidade_organizacional=self.unidade,
            exercicio=self.exercicio,
        )

    def test_processo_delega_exclusao_a_permissao_nativa(self):
        processo_admin = admin.site._registry[Processo]
        request = RequestFactory().get("/admin/")
        request.user = self.usuario_sem_permissao

        self.assertFalse(processo_admin.has_delete_permission(request))

        permissao = Permission.objects.get(
            content_type__app_label="pca", codename="delete_processo"
        )
        self.usuario_sem_permissao.user_permissions.add(permissao)
        request.user = get_user_model().objects.get(pk=self.usuario_sem_permissao.pk)

        self.assertTrue(processo_admin.has_delete_permission(request))

    def test_change_form_e_confirmacao_excluem_processo_elegivel(self):
        processo = self._processo_elegivel()
        self.client.force_login(self.usuario)
        change_url = reverse("admin:pca_processo_change", args=[processo.pk])
        delete_url = reverse("admin:pca_processo_delete", args=[processo.pk])

        response = self.client.get(change_url)

        self.assertContains(response, delete_url)

        response = self.client.post(delete_url, {"post": "yes"})

        self.assertRedirects(response, reverse("admin:pca_processo_changelist"))
        self.assertFalse(Processo.objects.filter(pk=processo.pk).exists())

    def test_processo_sei_delega_exclusao_a_permissao_nativa(self):
        model_admin = admin.site._registry[ProcessoSEI]
        request = RequestFactory().get("/admin/")
        request.user = self.usuario_sem_permissao

        self.assertFalse(model_admin.has_delete_permission(request))

        permissao = Permission.objects.get(
            content_type__app_label="pca", codename="delete_processosei"
        )
        self.usuario_sem_permissao.user_permissions.add(permissao)
        request.user = get_user_model().objects.get(pk=self.usuario_sem_permissao.pk)

        self.assertTrue(model_admin.has_delete_permission(request))

    def test_acompanhamento_delega_exclusao_a_permissao_nativa(self):
        # `AcompanhamentoAdmin` não sobrescreve `has_delete_permission`:
        # a exclusão individual é governada por
        # `pca.delete_acompanhamento`, espelhando `ProcessoAdmin`; só a
        # ação em massa (`delete_selected`) segue desligada.
        model_admin = admin.site._registry[Acompanhamento]

        self.assertTrue(model_admin.has_delete_permission(self.request))
        self.assertTrue(model_admin.has_delete_permission(self.request, object()))

        sem_permissao = RequestFactory().get("/admin/")
        sem_permissao.user = self.usuario_sem_permissao
        self.assertFalse(model_admin.has_delete_permission(sem_permissao))

    def test_exclusao_em_massa_aparece_no_admin_para_superuser(self):
        for model in (Processo, Acompanhamento, ProcessoSEI, Reuniao):
            with self.subTest(model=model.__name__):
                model_admin = admin.site._registry[model]
                self.assertIn("delete_selected", model_admin.get_actions(self.request))

    def test_reuniao_delega_exclusao_a_permissao_nativa(self):
        model_admin = admin.site._registry[Reuniao]
        request = RequestFactory().get("/admin/")
        request.user = self.usuario_sem_permissao

        self.assertFalse(model_admin.has_delete_permission(request))

        permissao = Permission.objects.get(
            content_type__app_label="pca", codename="delete_reuniao"
        )
        self.usuario_sem_permissao.user_permissions.add(permissao)
        request.user = get_user_model().objects.get(pk=self.usuario_sem_permissao.pk)

        self.assertTrue(model_admin.has_delete_permission(request))

    def test_exclusao_de_reuniao_com_acompanhamento_e_recusada_por_protect(self):
        reuniao = Reuniao.objects.create(data=date(2026, 1, 10), exercicio=self.exercicio)
        situacao = SituacaoNormalizada.objects.create(nome="Em tramitação")
        processo = self._processo_elegivel()
        Acompanhamento.objects.create(
            processo=processo,
            referencia_data=date(2026, 1, 10),
            origem_hash="hash-reuniao-protect-1",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
            situacao=situacao,
            reuniao=reuniao,
        )

        self.client.force_login(self.usuario)
        delete_url = reverse("admin:pca_reuniao_delete", args=[reuniao.pk])

        response = self.client.post(delete_url, {"post": "yes"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Reuniao.objects.filter(pk=reuniao.pk).exists())

    def test_exclusao_de_processo_cascateia_e_filhos_isolados_continuam_protegidos(self):
        processo = self._processo_elegivel()
        situacao = SituacaoNormalizada.objects.create(nome="Em tramitação")
        acompanhamento = Acompanhamento.objects.create(
            processo=processo,
            referencia_data=date(2026, 1, 10),
            origem_hash="hash-cascata-lp0-1",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
            situacao=situacao,
        )
        processo_sei = ProcessoSEI.objects.create(
            processo=processo, numero_sei="00000.000001/2026-01"
        )
        rascunho = RascunhoVirada.objects.create(
            exercicio_origem=self.exercicio,
            ano_destino=2027,
            criado_por=self.usuario,
        )
        item_rascunho = RascunhoItemVirada.objects.create(
            rascunho=rascunho, processo_origem=processo, ordem=1,
        )

        self.client.force_login(self.usuario)
        delete_url = reverse("admin:pca_processo_delete", args=[processo.pk])

        response = self.client.get(delete_url)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "não tem a permissão para remoção")
        self.assertFalse(response.context["perms_lacking"])

        response = self.client.post(delete_url, {"post": "yes"})

        self.assertRedirects(response, reverse("admin:pca_processo_changelist"))
        self.assertFalse(Processo.objects.filter(pk=processo.pk).exists())
        self.assertFalse(Acompanhamento.objects.filter(pk=acompanhamento.pk).exists())
        self.assertFalse(ProcessoSEI.objects.filter(pk=processo_sei.pk).exists())
        self.assertFalse(
            RascunhoItemVirada.objects.filter(pk=item_rascunho.pk).exists()
        )

        # Um nº SEI isolado (fora de uma cascata a partir de um Processo
        # apagado) também é excluível para quem tem
        # `pca.delete_processosei` (superuser por padrão): não há bloqueio
        # hardcoded. O Acompanhamento isolado é excluível pela permissão
        # nativa `pca.delete_acompanhamento`.
        outro_processo = Processo.objects.create(
            item_pca=2,
            descricao_objeto="Outro processo elegível",
            tipo=self.tipo,
            categoria=self.categoria,
            unidade_organizacional=self.unidade,
            exercicio=self.exercicio,
        )
        outro_acompanhamento = Acompanhamento.objects.create(
            processo=outro_processo,
            referencia_data=date(2026, 1, 11),
            origem_hash="hash-cascata-lp0-2",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
            situacao=situacao,
        )
        outro_processo_sei = ProcessoSEI.objects.create(
            processo=outro_processo, numero_sei="00000.000002/2026-01"
        )

        response = self.client.get(
            reverse("admin:pca_acompanhamento_delete", args=[outro_acompanhamento.pk])
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.get(
            reverse("admin:pca_processosei_delete", args=[outro_processo_sei.pk])
        )
        self.assertEqual(response.status_code, 200)

    def test_processo_derivado_sobrevive_a_exclusao_da_origem(self):
        processo_origem = self._processo_elegivel()
        processo_derivado = Processo.objects.create(
            item_pca=2,
            descricao_objeto="Processo derivado da virada",
            tipo=self.tipo,
            categoria=self.categoria,
            unidade_organizacional=self.unidade,
            exercicio=self.exercicio,
            origem=processo_origem,
        )

        self.client.force_login(self.usuario)
        delete_url = reverse("admin:pca_processo_delete", args=[processo_origem.pk])

        response = self.client.post(delete_url, {"post": "yes"})

        self.assertRedirects(response, reverse("admin:pca_processo_changelist"))
        self.assertFalse(Processo.objects.filter(pk=processo_origem.pk).exists())
        processo_derivado.refresh_from_db()
        self.assertIsNone(processo_derivado.origem_id)


class TestVisualizadorSemControleDeEscritaNasQuatroTelas(TestCase):
    """Varredura única confirmando que o grupo `visualizador` não vê
    nenhum controle de escrita em `/` (`core:inicio`), `/tabela` e
    `/analise`, simultaneamente: botão "Novo processo" (gated por
    `perms.pca.editar_pca`), link para editar o processo
    (`pca:editar_processo`) e link para registrar acompanhamento
    (`pca:acompanhamento_modal`) — as duas superfícies de escrita da
    linha da tabela. Não duplica os testes já existentes por tela (cada
    um cobre um controle isoladamente); esta classe cobre as telas de uma
    vez, com o mesmo usuário e o mesmo processo, provando que a ausência
    é simultânea, não uma coincidência de fixture.

    Os marcadores são os links reais que a linha da tabela emite só para
    quem tem `pca.editar_pca`."""

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.visualizador = User.objects.create_user(
            email="visualizador-4telas@example.com", password="senha-segura"
        )
        cls.visualizador.groups.add(Group.objects.get(name="visualizador"))

        cls.unidade = Unidade.objects.create(nome="Presidência")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.tipo = Tipo.objects.create(nome="Aquisição")
        cls.exercicio = Exercicio.objects.get(ano=2026)
        cls.processo = Processo.objects.create(
            item_pca=1,
            descricao_objeto="Processo visível ao visualizador",
            tipo=cls.tipo,
            categoria=cls.categoria,
            unidade_organizacional=cls.unidade,
            exercicio=cls.exercicio,
        )

    def setUp(self):
        self.client.force_login(self.visualizador)

    def test_visualizador_nao_ve_controle_de_escrita_em_nenhuma_das_4_telas(self):
        urls = {
            "inicio": reverse("core:inicio"),
            "tabela": reverse("pca:tabela"),
            "analise": reverse("pca:analise"),
        }
        marcador_editar = reverse(
            "pca:editar_processo", args=[self.exercicio.ano, self.processo.item_pca]
        )
        marcador_acompanhamento = reverse(
            "pca:acompanhamento_modal",
            args=[self.exercicio.ano, self.processo.item_pca],
        )

        for nome_tela, url in urls.items():
            with self.subTest(tela=nome_tela):
                resposta = self.client.get(url)
                conteudo = resposta.content.decode()

                self.assertEqual(resposta.status_code, 200)
                self.assertNotIn(
                    "Novo processo",
                    conteudo,
                    f"{nome_tela}: botão de escrita 'Novo processo' vazou "
                    "para o visualizador",
                )
                self.assertNotIn(
                    marcador_editar,
                    conteudo,
                    f"{nome_tela}: link de editar o processo "
                    "(pca:editar_processo) vazou para o visualizador",
                )
                self.assertNotIn(
                    marcador_acompanhamento,
                    conteudo,
                    f"{nome_tela}: link de registrar acompanhamento "
                    "(pca:acompanhamento_modal) vazou para o visualizador",
                )
