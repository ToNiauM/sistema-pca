"""Único modal do sistema: "Registrar acompanhamento"
(`_acompanhamento_modal.html`, `br-modal` + `br-scrim-util foco`, sem
`new core.Scrim(...)` — zero JS próprio). Nunca muda `situacao`/`estado`.

`help_text` condicional de "Novo prazo" e o aviso de prazo passado pela
situação efetiva final."""

from datetime import date, timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TransactionTestCase
from django.urls import reverse

from apps.catalogo.models import SituacaoNormalizada
from apps.pca.models import Acompanhamento, Estado, Processo, Situacao, TipoEvento


class AcompanhamentoModalBase(TransactionTestCase):
    serialized_rollback = True

    def setUp(self):
        call_command(
            "importar_pca",
            "apps/pca/fixtures/modelo-controle-exemplo.xlsx",
            "--usuario=importador@pca.local",
            "--exercicio=2026",
            stdout=StringIO(),
        )
        User = get_user_model()
        self.editor = User.objects.create_user(
            email="editor-acompanhamento@pca.local", password="senha-segura"
        )
        self.editor.groups.add(Group.objects.get(name="editor"))
        self.visualizador = User.objects.create_user(
            email="visualizador-acompanhamento@pca.local", password="senha-segura"
        )
        self.processo = Processo.objects.get(item_pca=1)
        self.client.force_login(self.editor)

    @property
    def url(self):
        return reverse("pca:acompanhamento_modal", args=[2026, self.processo.item_pca])

    @property
    def url_detalhe(self):
        return reverse("pca:detalhe_processo", args=[2026, self.processo.item_pca])

    def _preparar_situacao(
        self,
        *,
        situacao,
        estado=Estado.ATIVO,
        data_assinatura_contrato=None,
        data_recebimento_gelic=None,
        manual=False,
    ):
        """Deixa `self.processo` num estado controlado para os testes de
        `help_text`/aviso: nenhum fato gravado por padrão, sem sobreposição
        manual, situação exatamente a pedida."""
        self.processo.situacao = situacao
        self.processo.estado = estado
        self.processo.data_assinatura_contrato = data_assinatura_contrato
        self.processo.data_recebimento_gelic = data_recebimento_gelic
        self.processo.save(
            update_fields=[
                "situacao",
                "estado",
                "data_assinatura_contrato",
                "data_recebimento_gelic",
                "atualizado_em",
            ]
        )
        if manual:
            Acompanhamento.objects.create(
                processo=self.processo,
                referencia_data=date.today(),
                origem_hash=f"hash-manual-teste-{self.processo.pk}",
                tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
                situacao=SituacaoNormalizada.objects.get_or_create(
                    nome="Situação manual — teste 29-02"
                )[0],
                transicao_manual=True,
            )
        self.processo.refresh_from_db()


class TestAcompanhamentoModalGet(AcompanhamentoModalBase):
    def test_get_htmx_devolve_fragmento_com_role_dialog(self):
        resposta = self.client.get(self.url, HTTP_HX_REQUEST="true")
        conteudo = resposta.content.decode()

        self.assertEqual(resposta.status_code, 200)
        self.assertIn('role="dialog"', conteudo)
        self.assertIn('aria-modal="true"', conteudo)
        self.assertIn("br-scrim-util foco active", conteudo)
        self.assertNotIn("new core.Scrim", conteudo)
        self.assertNotIn("<script", conteudo)

    def test_visualizador_recebe_403(self):
        self.client.force_login(self.visualizador)
        resposta = self.client.get(self.url, HTTP_HX_REQUEST="true")
        self.assertEqual(resposta.status_code, 403)


class TestAcompanhamentoModalPost(AcompanhamentoModalBase):
    def test_post_com_prazo_valido_cria_acompanhamento_sem_mudar_situacao(self):
        situacao_antes = self.processo.situacao
        antes = Acompanhamento.objects.filter(processo=self.processo).count()

        resposta = self.client.post(
            self.url,
            {
                "versao": self.processo.atualizado_em.isoformat(),
                "prazo_prometido": "2026-12-01",
                "justificativa": "nova promessa — teste 26-02",
            },
        )

        self.assertRedirects(resposta, self.url_detalhe)
        self.assertEqual(
            Acompanhamento.objects.filter(processo=self.processo).count(), antes + 1
        )
        self.processo.refresh_from_db()
        self.assertEqual(self.processo.situacao, situacao_antes)

    def test_post_so_com_observacao_tambem_grava_sem_mudar_situacao(self):
        situacao_antes = self.processo.situacao
        antes = Acompanhamento.objects.filter(processo=self.processo).count()

        resposta = self.client.post(
            self.url,
            {
                "versao": self.processo.atualizado_em.isoformat(),
                "observacao": "só uma observação, sem novo prazo",
            },
        )

        self.assertRedirects(resposta, self.url_detalhe)
        self.assertEqual(
            Acompanhamento.objects.filter(processo=self.processo).count(), antes + 1
        )
        self.processo.refresh_from_db()
        self.assertEqual(self.processo.situacao, situacao_antes)

    def test_post_vazio_e_recusado_sem_gravar(self):
        antes = Acompanhamento.objects.filter(processo=self.processo).count()

        resposta = self.client.post(
            self.url, {"versao": self.processo.atualizado_em.isoformat()}
        )

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(
            Acompanhamento.objects.filter(processo=self.processo).count(), antes
        )

    def test_htmx_post_valido_devolve_hx_redirect(self):
        resposta = self.client.post(
            self.url,
            {
                "versao": self.processo.atualizado_em.isoformat(),
                "observacao": "via htmx",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta["HX-Redirect"], self.url_detalhe)

    def test_visualizador_recebe_403_no_post(self):
        self.client.force_login(self.visualizador)
        resposta = self.client.post(
            self.url,
            {
                "versao": self.processo.atualizado_em.isoformat(),
                "observacao": "x",
            },
        )
        self.assertEqual(resposta.status_code, 403)

    def test_post_so_com_observacao_nunca_cria_sobreposicao_manual(self):
        """`reafirmar_situacao=True` garante que o Acompanhamento nasce
        `transicao_manual=False` quando só a observação é enviada, sem
        situação escolhida pelo usuário."""
        self.client.post(
            self.url,
            {
                "versao": self.processo.atualizado_em.isoformat(),
                "observacao": "só uma observação, sem novo prazo",
            },
        )

        acompanhamento = Acompanhamento.objects.filter(processo=self.processo).latest("id")
        self.assertFalse(acompanhamento.transicao_manual)


class TestAcompanhamentoModalAjudaCondicional(AcompanhamentoModalBase):
    """`help_text` de "Novo prazo" decidido no servidor."""

    def test_no_prazo_sem_manual_mostra_texto_de_reset(self):
        self._preparar_situacao(situacao=Situacao.NO_PRAZO)

        resposta = self.client.get(self.url, HTTP_HX_REQUEST="true")

        self.assertContains(
            resposta,
            "Passa a ser o Prazo atual. Se o processo estava Atrasado, volta a No prazo.",
        )

    def test_atrasado_sem_manual_mostra_texto_de_reset(self):
        self._preparar_situacao(
            situacao=Situacao.NO_PRAZO, data_assinatura_contrato=None,
        )
        # Força a leitura para ATRASADO via prazo vencido (situacao_efetiva).
        self.processo.prazo_entrega = date.today() - timedelta(days=5)
        self.processo.save(update_fields=["prazo_entrega"])

        resposta = self.client.get(self.url, HTTP_HX_REQUEST="true")

        self.assertContains(
            resposta,
            "Passa a ser o Prazo atual. Se o processo estava Atrasado, volta a No prazo.",
        )

    def test_em_tramitacao_mostra_texto_estavel(self):
        self._preparar_situacao(
            situacao=Situacao.EM_TRAMITACAO,
            data_recebimento_gelic=date(2026, 3, 15),
        )

        resposta = self.client.get(self.url, HTTP_HX_REQUEST="true")

        self.assertContains(
            resposta, "Passa a ser o Prazo atual; a situação não muda."
        )

    def test_concluido_mostra_texto_estavel(self):
        self._preparar_situacao(
            situacao=Situacao.CONCLUIDO,
            data_assinatura_contrato=date(2026, 3, 15),
        )

        resposta = self.client.get(self.url, HTTP_HX_REQUEST="true")

        self.assertContains(
            resposta, "Passa a ser o Prazo atual; a situação não muda."
        )

    def test_sobreposicao_manual_ativa_mostra_texto_de_prevalencia(self):
        # Mesmo em No prazo/Atrasado, uma sobreposição manual ativa usa o
        # texto de prevalência manual.
        self._preparar_situacao(situacao=Situacao.ATRASADO, manual=True)

        resposta = self.client.get(self.url, HTTP_HX_REQUEST="true")

        self.assertContains(
            resposta,
            "Passa a ser o Prazo atual; a situação definida manualmente não muda.",
        )


class TestAcompanhamentoModalAvisoPrazoPassado(AcompanhamentoModalBase):
    """Prazo passado sempre grava; o `messages.warning` reflete a
    situação efetiva final, nunca inferida só pela data digitada."""

    def _postar_prazo_passado(self):
        return self.client.post(
            self.url,
            {
                "versao": self.processo.atualizado_em.isoformat(),
                "prazo_prometido": (date.today() - timedelta(days=3)).isoformat(),
                "justificativa": "lançamento retroativo de reunião",
            },
            follow=True,
        )

    def test_sem_manual_sem_fato_avisa_atrasado(self):
        self._preparar_situacao(situacao=Situacao.NO_PRAZO)

        resposta = self._postar_prazo_passado()

        mensagens = [str(m) for m in resposta.context["messages"]]
        self.assertTrue(
            any("o item consta como Atrasado" in m for m in mensagens), mensagens
        )
        promessa = Acompanhamento.objects.filter(
            processo=self.processo, prazo_prometido__isnull=False
        ).latest("id")
        self.assertFalse(promessa.transicao_manual)

    def test_manual_no_prazo_avisa_situacao_atual_no_prazo(self):
        self._preparar_situacao(situacao=Situacao.ATRASADO, manual=True)
        # A sobreposição manual acima já gravou `Processo.situacao` — força
        # explicitamente NO_PRAZO para representar "Manual No prazo".
        self.processo.situacao = Situacao.NO_PRAZO
        self.processo.save(update_fields=["situacao", "atualizado_em"])

        resposta = self._postar_prazo_passado()

        mensagens = [str(m) for m in resposta.context["messages"]]
        self.assertTrue(
            any("Situação atual: No prazo." in m for m in mensagens), mensagens
        )
        self.processo.refresh_from_db()
        self.assertEqual(self.processo.situacao, Situacao.NO_PRAZO.value)
        promessa = Acompanhamento.objects.filter(
            processo=self.processo, prazo_prometido__isnull=False
        ).latest("id")
        self.assertFalse(promessa.transicao_manual)

    def test_em_tramitacao_nao_muda_e_avisa_situacao_atual(self):
        self._preparar_situacao(
            situacao=Situacao.EM_TRAMITACAO,
            data_recebimento_gelic=date(2026, 3, 15),
        )

        resposta = self._postar_prazo_passado()

        mensagens = [str(m) for m in resposta.context["messages"]]
        self.assertTrue(
            any("Situação atual: Em tramitação." in m for m in mensagens), mensagens
        )
        self.processo.refresh_from_db()
        self.assertEqual(self.processo.situacao, Situacao.EM_TRAMITACAO.value)
        promessa = Acompanhamento.objects.filter(
            processo=self.processo, prazo_prometido__isnull=False
        ).latest("id")
        self.assertFalse(promessa.transicao_manual)

    def test_concluido_nao_muda_e_avisa_situacao_atual(self):
        self._preparar_situacao(
            situacao=Situacao.CONCLUIDO,
            data_assinatura_contrato=date(2026, 3, 15),
        )

        resposta = self._postar_prazo_passado()

        mensagens = [str(m) for m in resposta.context["messages"]]
        self.assertTrue(
            any("Situação atual: Concluído." in m for m in mensagens), mensagens
        )
        self.processo.refresh_from_db()
        self.assertEqual(self.processo.situacao, Situacao.CONCLUIDO.value)
        promessa = Acompanhamento.objects.filter(
            processo=self.processo, prazo_prometido__isnull=False
        ).latest("id")
        self.assertFalse(promessa.transicao_manual)
