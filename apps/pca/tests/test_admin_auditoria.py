from datetime import date

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse

from apps.catalogo.models import Categoria, Exercicio, SituacaoNormalizada, Tipo, Unidade
from apps.pca.importacao.models import EventoImportacao
from apps.pca.models import (
    Acompanhamento,
    Estado,
    Processo,
    ProcessoSEI,
    Reuniao,
    Situacao,
    TipoEvento,
)


class HistoricosAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_superuser(
            email="auditoria@example.com", password="senha-segura"
        )
        cls.unidade = Unidade.objects.create(nome="Presidência")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.tipo = Tipo.objects.create(nome="Aquisição")
        cls.exercicio = Exercicio.objects.get(ano=2026)

    def setUp(self):
        self.request = RequestFactory().get("/admin/")
        self.request.user = self.usuario

    def _processo(self):
        return Processo.objects.create(
            item_pca=1,
            descricao_objeto="Objeto auditável",
            tipo=self.tipo,
            categoria=self.categoria,
            unidade_organizacional=self.unidade,
            exercicio=self.exercicio,
        )

    def test_historicos_bloqueiam_add_mas_delegam_change_e_delete_a_permissao_nativa(self):
        for model in (Processo.history.model, Acompanhamento.history.model):
            with self.subTest(model=model.__name__):
                model_admin = admin.site._registry[model]
                self.assertFalse(model_admin.has_add_permission(self.request))
                self.assertTrue(model_admin.has_change_permission(self.request))
                self.assertTrue(model_admin.has_delete_permission(self.request))
                self.assertIn(
                    "delete_selected", model_admin.get_actions(self.request)
                )

    def test_edicao_de_processo_grava_diff(self):
        processo = self._processo()
        historico_anterior = processo.history.latest()
        total_antes = Processo.history.model.objects.filter(id=processo.pk).count()

        processo.situacao = Situacao.EM_TRAMITACAO.value
        processo._history_user = self.usuario
        processo.save()

        historico_novo = processo.history.latest()
        self.assertEqual(
            Processo.history.model.objects.filter(id=processo.pk).count(),
            total_antes + 1,
        )
        self.assertEqual(historico_novo.history_user, self.usuario)
        self.assertIsNotNone(historico_novo.history_date)
        self.assertIn(
            "situacao", historico_novo.diff_against(historico_anterior).changed_fields
        )


class TestAcompanhamentoAdminCorrecao(TestCase):
    """A única via de correção de `prazo_prometido` e `evento` é o
    Django Admin; a promessa web nunca ganha caminho de edição/exclusão.
    A exclusão individual e em massa (`delete_selected`) pelo Admin são
    permitidas para quem tem `pca.delete_acompanhamento` (superuser por
    padrão), preservando o histórico via `simple_history`."""

    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_superuser(
            email="admin-acomp@example.com", password="senha-segura"
        )
        cls.unidade = Unidade.objects.create(nome="Presidência")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.tipo = Tipo.objects.create(nome="Aquisição")
        cls.exercicio = Exercicio.objects.get(ano=2026)
        cls.situacao = SituacaoNormalizada.objects.create(nome="Em tramitação")
        cls.processo = Processo.objects.create(
            item_pca=1,
            descricao_objeto="Objeto auditável",
            tipo=cls.tipo,
            categoria=cls.categoria,
            unidade_organizacional=cls.unidade,
            exercicio=cls.exercicio,
        )
        cls.acompanhamento = Acompanhamento.objects.create(
            processo=cls.processo,
            referencia_data=date(2026, 5, 15),
            origem_hash="hash-admin-correcao-1",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
            situacao=cls.situacao,
            prazo_prometido=date(2026, 5, 15),
            evento="justificativa original",
        )

    def setUp(self):
        self.client.force_login(self.usuario)

    def test_change_form_expoe_prazo_e_evento_editaveis(self):
        url = reverse(
            "admin:pca_acompanhamento_change", args=[self.acompanhamento.pk]
        )

        resposta = self.client.get(url)

        self.assertContains(resposta, 'name="prazo_prometido"')
        self.assertContains(resposta, 'name="evento"')

    def test_post_administrativo_corrige_prazo_e_evento_com_historico(self):
        url = reverse(
            "admin:pca_acompanhamento_change", args=[self.acompanhamento.pk]
        )
        dados = {
            "processo": self.processo.pk,
            "referencia_data": "2026-05-20",
            "origem_hash": "hash-admin-correcao-1",
            "evento": "corrigido pelo admin",
            "tipo_evento": TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
            "situacao_informada": "",
            "situacao": self.situacao.pk,
            "prazo_prometido": "2026-05-21",
            "data_evento_informada": "",
            "area_informada": "",
            "_continue": "Salvar e continuar editando",
        }

        resposta = self.client.post(url, dados)

        self.assertEqual(resposta.status_code, 302)
        self.acompanhamento.refresh_from_db()
        self.assertEqual(self.acompanhamento.evento, "corrigido pelo admin")
        self.assertEqual(self.acompanhamento.prazo_prometido, date(2026, 5, 21))
        historico = (
            self.acompanhamento.history.filter(history_user=self.usuario)
            .order_by("-history_date")
            .first()
        )
        self.assertIsNotNone(historico)
        self.assertEqual(historico.evento, "corrigido pelo admin")

    def test_exclusao_individual_por_superuser_remove_registro_e_preserva_historico(self):
        model_admin = admin.site._registry[Acompanhamento]
        request = RequestFactory().get("/admin/")
        request.user = self.usuario

        self.assertTrue(
            model_admin.has_delete_permission(request, self.acompanhamento)
        )

        pk = self.acompanhamento.pk
        url_apagar = reverse("admin:pca_acompanhamento_delete", args=[pk])
        resposta = self.client.post(url_apagar, {"post": "yes"})

        self.assertEqual(resposta.status_code, 302)
        self.assertFalse(Acompanhamento.objects.filter(pk=pk).exists())

        historico_delete = Acompanhamento.history.model.objects.filter(
            id=pk, history_type="-"
        ).first()
        self.assertIsNotNone(historico_delete)
        self.assertEqual(historico_delete.history_user, self.usuario)

    def test_exclusao_individual_sem_permissao_e_recusada(self):
        usuario_sem_permissao = get_user_model().objects.create_user(
            email="staff-sem-permissao@example.com",
            password="senha-segura",
            is_staff=True,
        )
        model_admin = admin.site._registry[Acompanhamento]
        request = RequestFactory().get("/admin/")
        request.user = usuario_sem_permissao

        # Prova de nível de model: sem pca.delete_acompanhamento, o
        # ModelAdmin recusa a exclusão mesmo se algo já tivesse passado pelo
        # gate do site.
        self.assertFalse(
            model_admin.has_delete_permission(request, self.acompanhamento)
        )

        # PcaAdminSite.has_permission exige is_superuser para qualquer
        # acesso ao Admin — mais restritivo que o is_staff padrão. Um
        # staff sem is_superuser é barrado no gate do site e redirecionado
        # ao login (302), não 403.
        self.client.logout()
        self.client.force_login(usuario_sem_permissao)
        url_apagar = reverse(
            "admin:pca_acompanhamento_delete", args=[self.acompanhamento.pk]
        )
        resposta = self.client.post(url_apagar, {"post": "yes"})

        self.assertEqual(resposta.status_code, 302)
        self.assertIn(reverse("admin:login"), resposta.url)
        self.assertTrue(
            Acompanhamento.objects.filter(pk=self.acompanhamento.pk).exists()
        )

    def test_exclusao_em_massa_permitida_para_superuser(self):
        model_admin = admin.site._registry[Acompanhamento]
        request = RequestFactory().get("/admin/")
        request.user = self.usuario

        self.assertIn(
            "delete_selected", model_admin.get_actions(request)
        )


class TestProcessoAdminTresEixos(TestCase):
    """`ProcessoAdmin` opera sobre estado/tipo/situacao, e a mudança de
    Estado pelo admin precisa auditar essa mudança via
    `services.alterar_estado`, gerando um `Acompanhamento` automático — o
    `ModelForm` padrão sozinho só faria um `UPDATE` silencioso na
    coluna."""

    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_superuser(
            email="admin-3eixos@example.com", password="senha-segura"
        )
        cls.unidade = Unidade.objects.create(nome="Presidência")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.tipo = Tipo.objects.create(nome="Aquisição")
        cls.exercicio = Exercicio.objects.get(ano=2026)
        # `services.alterar_estado` grava um `Acompanhamento` com
        # `SituacaoNormalizada` "Cancelado"/"Sem informação" — mesmas 4
        # entradas fixturadas em `TestAlterarEstadoECriacao`
        # (test_servico_status.py), não seedadas por migração.
        for nome in ("Concluído", "Sem informação", "Em tramitação", "Cancelado"):
            SituacaoNormalizada.objects.get_or_create(nome=nome)

    def setUp(self):
        self.client.force_login(self.usuario)

    def _processo(self, **extra):
        valores = dict(
            item_pca=1,
            descricao_objeto="Objeto três eixos",
            tipo=self.tipo,
            categoria=self.categoria,
            unidade_organizacional=self.unidade,
            estado=Estado.ATIVO.value,
            situacao=Situacao.NO_PRAZO.value,
            exercicio=self.exercicio,
        )
        valores.update(extra)
        return Processo.objects.create(**valores)

    def _payload(self, processo, **overrides):
        """Payload completo do `ModelForm` padrão do admin (sem
        `fieldsets`/`exclude`, todo campo concreto é exposto) a partir do
        estado atual de `processo`, só com os campos que a submissão
        efetivamente muda em `overrides`."""
        dados = {
            "item_pca": processo.item_pca,
            "exercicio": processo.exercicio_id,
            "origem": "",
            "descricao_objeto": processo.descricao_objeto,
            "justificativa": processo.justificativa,
            "tipo": processo.tipo_id,
            "categoria": processo.categoria_id,
            "unidade_organizacional": processo.unidade_organizacional_id,
            "valor_estimado": "",
            "mes_previsto": "",
            "data_inclusao_pca": "",
            "grau_prioridade": "",
            "classificacao": "",
            "data_envio_gelic": "",
            "prazo_entrega": "",
            "data_recebimento_gelic": "",
            "data_prevista_conclusao": "",
            "estado": processo.estado,
            "situacao": processo.situacao,
            "modalidade": "",
            "vigencia_inicio": "",
            "vigencia_fim": "",
            "numero_contratacao": "",
            "numero_arp": "",
            "instrumento_contratual": "",
            "numero_instrumento_contratual": "",
            "valor_contratado": "",
            "fornecedor_cnpj": "",
            "fornecedor_razao_social": "",
            "data_assinatura_contrato": "",
            "data_lancamento_spw": "",
            "data_lancamento_wordpress": "",
            "data_lancamento_dados_abertos": "",
            "situacao_sei": "",
        }
        dados.update(overrides)
        return dados

    def test_list_display_e_list_filter_expoem_estado_tipo_situacao(self):
        processo_ativo = self._processo(item_pca=1)
        processo_cancelado = self._processo(
            item_pca=2, estado=Estado.CANCELADO.value
        )

        url = reverse("admin:pca_processo_changelist")
        resposta = self.client.get(url)

        self.assertEqual(resposta.status_code, 200)
        list_display = resposta.context["cl"].list_display
        self.assertIn("estado", list_display)
        self.assertIn("tipo", list_display)
        self.assertIn("situacao", list_display)
        list_filter = [
            spec[0] if isinstance(spec, (list, tuple)) else spec
            for spec in resposta.context["cl"].list_filter
        ]
        self.assertIn("estado", list_filter)
        self.assertIn("situacao", list_filter)

        resposta_filtrada = self.client.get(url, {"estado__exact": "cancelado"})

        self.assertEqual(resposta_filtrada.status_code, 200)
        pks_filtrados = {
            obj.pk for obj in resposta_filtrada.context["cl"].result_list
        }
        self.assertEqual(pks_filtrados, {processo_cancelado.pk})
        self.assertNotIn(processo_ativo.pk, pks_filtrados)

    def test_mudanca_de_estado_pelo_admin_gera_acompanhamento_automatico_auditado(
        self,
    ):
        processo = self._processo()
        total_acompanhamentos_antes = Acompanhamento.objects.filter(
            processo=processo
        ).count()
        url = reverse("admin:pca_processo_change", args=[processo.pk])
        dados = self._payload(processo, estado=Estado.CANCELADO.value)

        resposta = self.client.post(url, dados)

        self.assertEqual(resposta.status_code, 302)
        processo.refresh_from_db()
        self.assertEqual(processo.estado, Estado.CANCELADO.value)

        acompanhamentos = Acompanhamento.objects.filter(processo=processo)
        self.assertEqual(
            acompanhamentos.count(), total_acompanhamentos_antes + 1
        )
        automatico = acompanhamentos.latest("id")
        self.assertEqual(automatico.tipo_evento, TipoEvento.AUTOMATICO.value)
        self.assertNotEqual(automatico.situacao_informada, "")

        historico_mais_recente = processo.history.latest()
        self.assertEqual(historico_mais_recente.history_user, self.usuario)

    def test_salvar_sem_mudar_estado_apos_cancelar_nao_duplica_acompanhamento(self):
        processo = self._processo(estado=Estado.CANCELADO.value)
        url = reverse("admin:pca_processo_change", args=[processo.pk])
        total_acompanhamentos_antes = Acompanhamento.objects.filter(
            processo=processo
        ).count()
        dados = self._payload(
            processo,
            estado=Estado.CANCELADO.value,
            descricao_objeto="Objeto três eixos — revisado",
        )

        resposta = self.client.post(url, dados)

        self.assertEqual(resposta.status_code, 302)
        processo.refresh_from_db()
        self.assertEqual(processo.descricao_objeto, "Objeto três eixos — revisado")
        self.assertEqual(
            Acompanhamento.objects.filter(processo=processo).count(),
            total_acompanhamentos_antes,
        )

    def test_mudar_outro_campo_persiste_normalmente_sem_tocar_acompanhamento(self):
        processo = self._processo()
        url = reverse("admin:pca_processo_change", args=[processo.pk])
        total_acompanhamentos_antes = Acompanhamento.objects.filter(
            processo=processo
        ).count()
        dados = self._payload(
            processo, descricao_objeto="Objeto três eixos — só descrição"
        )

        resposta = self.client.post(url, dados)

        self.assertEqual(resposta.status_code, 302)
        processo.refresh_from_db()
        self.assertEqual(
            processo.descricao_objeto, "Objeto três eixos — só descrição"
        )
        self.assertEqual(processo.estado, Estado.ATIVO.value)
        self.assertEqual(
            Acompanhamento.objects.filter(processo=processo).count(),
            total_acompanhamentos_antes,
        )


class TestTodoModelAdminPermiteEdicaoEExclusaoParaSuperuser(TestCase):
    """Todo `ModelAdmin` registrado permite change/delete e expõe
    `delete_selected` para um superuser, exceto os três
    `Historical*`/`EventoImportacao` que continuam sem
    `has_add_permission`."""

    @classmethod
    def setUpTestData(cls):
        cls.superuser = get_user_model().objects.create_superuser(
            email="registry-completo@example.com", password="senha-segura"
        )

    def test_todo_model_admin_permite_change_delete_e_delete_selected(self):
        request = RequestFactory().get("/admin/")
        request.user = self.superuser

        for model, model_admin in admin.site._registry.items():
            with self.subTest(model=model.__name__):
                self.assertTrue(model_admin.has_change_permission(request))
                self.assertTrue(model_admin.has_delete_permission(request))
                self.assertIn(
                    "delete_selected", model_admin.get_actions(request)
                )


class TestExclusaoRealViaAdminHTTP(TestCase):
    """Verificação HTTP real (não só `has_*_permission` em nível de
    model) de que change/delete funcionam de fato pelo Admin."""

    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_superuser(
            email="http-real@example.com", password="senha-segura"
        )
        cls.unidade = Unidade.objects.create(nome="Presidência")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.tipo = Tipo.objects.create(nome="Aquisição")
        cls.exercicio = Exercicio.objects.get(ano=2026)
        cls.situacao = SituacaoNormalizada.objects.create(nome="Em tramitação")

    def setUp(self):
        self.client.force_login(self.usuario)

    def _processo(self, **extra):
        valores = dict(
            item_pca=1,
            descricao_objeto="Objeto HTTP real",
            tipo=self.tipo,
            categoria=self.categoria,
            unidade_organizacional=self.unidade,
            exercicio=self.exercicio,
        )
        valores.update(extra)
        return Processo.objects.create(**valores)

    def test_change_de_historico_de_acompanhamento_via_admin_altera_evento(self):
        processo = self._processo()
        acompanhamento = Acompanhamento.objects.create(
            processo=processo,
            referencia_data=date(2026, 5, 15),
            origem_hash="hash-historico-http-1",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
            situacao=self.situacao,
        )
        historico = Acompanhamento.history.filter(id=acompanhamento.pk).latest(
            "history_date"
        )
        url = reverse(
            "admin:pca_historicalacompanhamento_change", args=[historico.pk]
        )

        resposta_get = self.client.get(url)

        self.assertEqual(resposta_get.status_code, 200)

        dados = {
            "id": historico.id,
            "referencia_data": historico.referencia_data.isoformat(),
            "origem_hash": historico.origem_hash,
            "evento": "corrigido via histórico pelo admin",
            "tipo_evento": historico.tipo_evento,
            "situacao_informada": historico.situacao_informada or "",
            "prazo_prometido": (
                historico.prazo_prometido.isoformat()
                if historico.prazo_prometido
                else ""
            ),
            "data_evento_informada": (
                historico.data_evento_informada.isoformat()
                if historico.data_evento_informada
                else ""
            ),
            "area_informada": historico.area_informada or "",
            "processo": historico.processo_id,
            "situacao": historico.situacao_id,
            "reuniao": historico.reuniao_id or "",
            "history_date_0": historico.history_date.date().isoformat(),
            "history_date_1": historico.history_date.time().isoformat(),
            "history_change_reason": "correção manual",
            "history_type": historico.history_type,
            "history_user": self.usuario.pk,
        }

        resposta = self.client.post(url, dados)

        self.assertEqual(resposta.status_code, 302)
        historico.refresh_from_db()
        self.assertEqual(historico.evento, "corrigido via histórico pelo admin")

    def test_delete_de_reuniao_sem_acompanhamento_funciona_via_admin(self):
        reuniao = Reuniao.objects.create(data=date(2026, 1, 10), exercicio=self.exercicio)
        url = reverse("admin:pca_reuniao_delete", args=[reuniao.pk])

        resposta = self.client.post(url, {"post": "yes"})

        self.assertRedirects(resposta, reverse("admin:pca_reuniao_changelist"))
        self.assertFalse(Reuniao.objects.filter(pk=reuniao.pk).exists())

    def test_delete_de_processo_sei_funciona_via_admin(self):
        processo = self._processo()
        processo_sei = ProcessoSEI.objects.create(
            processo=processo, numero_sei="00000.000099/2026-01"
        )
        url = reverse("admin:pca_processosei_delete", args=[processo_sei.pk])

        resposta = self.client.post(url, {"post": "yes"})

        self.assertRedirects(resposta, reverse("admin:pca_processosei_changelist"))
        self.assertFalse(ProcessoSEI.objects.filter(pk=processo_sei.pk).exists())

    def test_delete_de_evento_importacao_funciona_via_admin(self):
        evento = EventoImportacao.objects.create(
            disparado_por=self.usuario,
            arquivo_nome="planilha.xlsx",
            exercicio=self.exercicio,
        )
        url = reverse("admin:pca_eventoimportacao_delete", args=[evento.pk])

        resposta = self.client.post(url, {"post": "yes"})

        self.assertRedirects(
            resposta, reverse("admin:pca_eventoimportacao_changelist")
        )
        self.assertFalse(EventoImportacao.objects.filter(pk=evento.pk).exists())
