"""Testes da ação "Atualizar com o SEI" em `ProcessoAdmin` (Fase 32, Plano
32-04). Verificação sempre por requisição real
(`django.test.Client`, `force_login`, `HTTP_X_FORWARDED_PROTO="https"`),
nunca só grep de template (convenções do projeto, Conventions §2). Todo teste roda
contra um diretório temporário (`tempfile.TemporaryDirectory()` +
`@override_settings(SEI_DATA_DIR=...)`) — nunca `data/sei` de verdade."""

import json
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.catalogo.models import Categoria, Exercicio, SituacaoExercicio, Tipo, Unidade
from apps.pca.models import Estado, Processo, ProcessoSEI
from apps.pca.sei import execucoes


@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False)
class AcaoAtualizarComOSeiBase(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._override = override_settings(SEI_DATA_DIR=self._tmp.name)
        self._override.enable()
        self.addCleanup(self._override.disable)
        self.base = Path(self._tmp.name)

        # Fase 39 — a nova ação "Reindexar assistente"
        # grava em `data/ia/pedidos/`; isolar aqui evita que os testes
        # desta classe toquem o `data/ia/` REAL do container de dev.
        self._override_ia = override_settings(
            IA_ESTADO_PATH=str(self.base / "ia" / "estado.sqlite3"),
        )
        self._override_ia.enable()
        self.addCleanup(self._override_ia.disable)

        self.exercicio, _ = Exercicio.objects.get_or_create(
            ano=2026, defaults={"rotulo": "PCA 2026", "situacao": SituacaoExercicio.ABERTO}
        )
        self.tipo = Tipo.objects.create(nome="Serviço")
        self.categoria = Categoria.objects.create(nome="Serviços")
        self.unidade = Unidade.objects.create(nome="Presidência")

        self.superusuario = get_user_model().objects.create_superuser(
            email="admin-sei@example.com", password="senha-segura-123"
        )
        self.staff_comum = get_user_model().objects.create_user(
            email="staff-sei@example.com", password="senha-segura-123",
            is_staff=True, is_superuser=False,
        )

        self.client_super = Client(HTTP_X_FORWARDED_PROTO="https")
        self.client_super.force_login(self.superusuario)
        self.client_staff = Client(HTTP_X_FORWARDED_PROTO="https")
        self.client_staff.force_login(self.staff_comum)

        self.changelist_url = reverse("admin:pca_processo_changelist")

    def processo(self, item, **overrides):
        valores = dict(
            item_pca=item,
            exercicio=self.exercicio,
            descricao_objeto="Objeto de teste",
            justificativa="Justificativa",
            tipo=self.tipo,
            categoria=self.categoria,
            unidade_organizacional=self.unidade,
            estado=Estado.ATIVO,
        )
        valores.update(overrides)
        return Processo.objects.create(**valores)

    def _post_acao(self, client, pks):
        return client.post(
            self.changelist_url,
            {
                "action": "atualizar_com_o_sei",
                "_selected_action": [str(pk) for pk in pks],
                "index": "0",
            },
            HTTP_HOST="testserver",
        )


class TestSuperusuarioVeEExecuta(AcaoAtualizarComOSeiBase):
    def test_get_changelist_mostra_a_acao(self):
        self.processo(1)  # o Django Admin só renderiza a barra de ações com ao menos 1 linha
        resposta = self.client_super.get(self.changelist_url, HTTP_HOST="testserver")
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Atualizar com o SEI")

    def test_post_grava_pedido_com_solicitado_por_correto(self):
        processo = self.processo(3)
        ProcessoSEI.objects.create(processo=processo, numero_sei="90796110000007.000036/2025-81")

        resposta = self._post_acao(self.client_super, [processo.pk])

        self.assertIn(resposta.status_code, (200, 302))
        caminho = self.base / "pedidos" / f"{self.exercicio.ano}-{processo.item_pca}.json"
        self.assertTrue(caminho.exists())
        pedido = json.loads(caminho.read_text(encoding="utf-8"))
        self.assertEqual(pedido["item_pca"], 3)
        self.assertEqual(pedido["exercicio"], self.exercicio.ano)
        self.assertEqual(pedido["solicitado_por"], self.superusuario.pk)


class TestStaffComumNaoVeNemExecuta(AcaoAtualizarComOSeiBase):
    def test_get_changelist_nao_mostra_a_acao(self):
        resposta = self.client_staff.get("/admin/", HTTP_HOST="testserver")
        # `PcaAdminSite.has_permission` já barra staff não-superusuário
        # do Admin inteiro — a checagem chega antes de qualquer changelist.
        self.assertNotEqual(resposta.status_code, 200)

    def test_post_forcado_pelo_caminho_http_nunca_grava_pedido(self):
        """Ponta a ponta (`django.test.Client`, POST real): o gate de site
        `PcaAdminSite.has_permission` já barra o Admin INTEIRO a
        staff não-superusuário — medido empiricamente, o POST forçado volta
        302 (redirect para o login), nunca 200; em nenhum caso um pedido é
        gravado."""
        processo = self.processo(3)
        ProcessoSEI.objects.create(processo=processo, numero_sei="111")

        resposta = self._post_acao(self.client_staff, [processo.pk])

        self.assertEqual(resposta.status_code, 302)
        self.assertIn("/admin/login/", resposta.url)
        self.assertFalse((self.base / "pedidos").exists())

    def test_acao_recusa_com_permission_denied_para_staff_nao_superusuario(self):
        """Defesa em profundidade exigida pela spec (§3.7/§9): a view da
        própria ação também recusa com `PermissionDenied` quando
        `request.user.is_superuser` é `False` — testada chamando o método da
        ação DIRETO (`RequestFactory`, sem passar pelo roteamento HTTP), já
        que o gate de site impede qualquer staff comum de alcançar
        essa view pelo caminho HTTP normal (teste anterior). Django converte
        `PermissionDenied` em HTTP 403 automaticamente para qualquer view que
        a levante — é essa conversão que a ação depende, caso o gate de site
        mude no futuro."""
        from django.contrib.admin.sites import site as django_site
        from django.core.exceptions import PermissionDenied
        from django.test import RequestFactory

        from apps.pca.admin import ProcessoAdmin
        from apps.pca.models import Processo as ProcessoModel

        processo = self.processo(3)
        ProcessoSEI.objects.create(processo=processo, numero_sei="111")

        request = RequestFactory().post(
            self.changelist_url,
            {"action": "atualizar_com_o_sei", "_selected_action": [str(processo.pk)]},
        )
        request.user = self.staff_comum
        model_admin = ProcessoAdmin(ProcessoModel, django_site)

        with self.assertRaises(PermissionDenied):
            model_admin.atualizar_com_o_sei(
                request, ProcessoModel.objects.filter(pk=processo.pk)
            )

        self.assertFalse((self.base / "pedidos").exists())


class TestCanceladoOuSemNumeroSeiIgnorado(AcaoAtualizarComOSeiBase):
    def test_ignorados_com_aviso_sem_arquivo_de_pedido(self):
        cancelado = self.processo(1, estado=Estado.CANCELADO)
        ProcessoSEI.objects.create(processo=cancelado, numero_sei="111")
        sem_numero = self.processo(2)  # ativo, sem nenhum ProcessoSEI

        resposta = self._post_acao(self.client_super, [cancelado.pk, sem_numero.pk])

        pasta_pedidos = self.base / "pedidos"
        arquivos = list(pasta_pedidos.glob("*.json")) if pasta_pedidos.exists() else []
        self.assertEqual(arquivos, [])

        if resposta.status_code == 302:
            resposta_seguinte = self.client_super.get(resposta.url, HTTP_HOST="testserver")
            self.assertContains(resposta_seguinte, "ignorado")
        else:
            self.assertContains(resposta, "ignorado")


class TestSegundoPedidoSobrescreve(AcaoAtualizarComOSeiBase):
    def test_executar_duas_vezes_mantem_um_unico_arquivo(self):
        processo = self.processo(3)
        ProcessoSEI.objects.create(processo=processo, numero_sei="111")

        self._post_acao(self.client_super, [processo.pk])
        primeiro = execucoes.listar_pedidos()
        self.assertEqual(len(primeiro), 1)
        primeiro_solicitado_em = primeiro[0]["solicitado_em"]

        self._post_acao(self.client_super, [processo.pk])
        segundo = execucoes.listar_pedidos()

        self.assertEqual(len(segundo), 1)
        self.assertGreaterEqual(segundo[0]["solicitado_em"], primeiro_solicitado_em)
        arquivos = list((self.base / "pedidos").glob("*.json"))
        self.assertEqual(len(arquivos), 1)


class AcaoReindexarAssistenteBase(AcaoAtualizarComOSeiBase):
    def _post_reindexar(self, client, pks):
        return client.post(
            self.changelist_url,
            {
                "action": "reindexar_assistente",
                "_selected_action": [str(pk) for pk in pks],
                "index": "0",
            },
            HTTP_HOST="testserver",
        )


@override_settings(IA_API_KEY="chave-de-teste")
class TestSuperusuarioReindexaAssistente(AcaoReindexarAssistenteBase):
    def test_get_changelist_mostra_a_acao(self):
        self.processo(1)
        resposta = self.client_super.get(self.changelist_url, HTTP_HOST="testserver")
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Reindexar assistente")

    def test_post_grava_um_pedido_pendente(self):
        processo = self.processo(1)

        resposta = self._post_reindexar(self.client_super, [processo.pk])

        self.assertIn(resposta.status_code, (200, 302))
        pasta_pedidos = self.base / "ia" / "pedidos"
        arquivos = list(pasta_pedidos.glob("*.json"))
        self.assertEqual(len(arquivos), 1)
        pedido = json.loads(arquivos[0].read_text(encoding="utf-8"))
        self.assertEqual(pedido["estado"], "pendente")
        self.assertEqual(pedido["solicitado_por"], self.superusuario.pk)
        self.assertNotIn("email", pedido)


class TestSemChaveNaoAgendaReindexacao(AcaoReindexarAssistenteBase):
    @override_settings(IA_API_KEY="")
    def test_post_sem_chave_avisa_e_nao_grava_pedido(self):
        processo = self.processo(1)

        resposta = self._post_reindexar(self.client_super, [processo.pk])

        pasta_pedidos = self.base / "ia" / "pedidos"
        arquivos = list(pasta_pedidos.glob("*.json")) if pasta_pedidos.exists() else []
        self.assertEqual(arquivos, [])

        if resposta.status_code == 302:
            resposta_seguinte = self.client_super.get(resposta.url, HTTP_HOST="testserver")
            self.assertContains(resposta_seguinte, "IA_API_KEY ausente")
        else:
            self.assertContains(resposta, "IA_API_KEY ausente")


@override_settings(IA_API_KEY="chave-de-teste")
class TestStaffComumNaoReindexaAssistente(AcaoReindexarAssistenteBase):
    def test_post_forcado_pelo_caminho_http_nunca_grava_pedido(self):
        processo = self.processo(1)

        resposta = self._post_reindexar(self.client_staff, [processo.pk])

        self.assertEqual(resposta.status_code, 302)
        self.assertIn("/admin/login/", resposta.url)
        self.assertFalse((self.base / "ia" / "pedidos").exists())

    def test_acao_recusa_com_permission_denied_para_staff_nao_superusuario(self):
        from django.contrib.admin.sites import site as django_site
        from django.core.exceptions import PermissionDenied
        from django.test import RequestFactory

        from apps.pca.admin import ProcessoAdmin
        from apps.pca.models import Processo as ProcessoModel

        processo = self.processo(1)

        request = RequestFactory().post(
            self.changelist_url,
            {"action": "reindexar_assistente", "_selected_action": [str(processo.pk)]},
        )
        request.user = self.staff_comum
        model_admin = ProcessoAdmin(ProcessoModel, django_site)

        with self.assertRaises(PermissionDenied):
            model_admin.reindexar_assistente(
                request, ProcessoModel.objects.filter(pk=processo.pk)
            )

        self.assertFalse((self.base / "ia" / "pedidos").exists())
