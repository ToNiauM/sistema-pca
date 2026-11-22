"""Fase 26 — único modal do sistema:
"Registrar acompanhamento" (`_acompanhamento_modal.html`, `br-modal` +
`br-scrim-util foco`, sem `new core.Scrim(...)` — zero JS próprio). Nunca
muda `situacao`/`estado`.

Fase 29 — `help_text` condicional de "Novo prazo"
e o aviso de prazo passado pela situação efetiva final.


Proposta automática de texto
(`apps.pca.mudancas.propor_texto`) pré-preenchendo Observação no GET, e
`help_text` fixo de padrão de escrita em Observação/Justificativa."""

import json
from datetime import date, timedelta
from decimal import Decimal
from io import StringIO

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TransactionTestCase
from django.urls import reverse

from apps.catalogo.models import SituacaoNormalizada
from apps.pca.models import (
    Acompanhamento,
    Estado,
    Processo,
    Reuniao,
    Situacao,
    SituacaoReuniao,
    TipoEvento,
)


class AcompanhamentoModalBase(TransactionTestCase):
    serialized_rollback = True

    def setUp(self):
        call_command(
            "importar_pca",
            "Modelo_de_Controle_.xlsx",
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

    @property
    def url_tabela_retorno(self):
        """Destino do redirect ao fechar o modal
        (salvar ou cancelar): a tabela de Processos, com âncora na linha."""
        return reverse("pca:tabela") + f"#item-{self.processo.pk}"

    @property
    def url_detalhe_ancora(self):
        """Origem "detalhe": o sucesso do POST volta
        para a PRÓPRIA FICHA (`#acompanhamentos`), nunca para a tabela —
        só a origem "tabela" continua indo para
        `#listagem`."""
        return self.url_detalhe + "#acompanhamentos"

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
            self.processo.situacao_manual = True  # 29/09/2026 — a trava é o campo explícito
            self.processo.save(update_fields=["situacao_manual"])
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
        # QA 30/09/2026, navegador M4 — mudança DELIBERADA de contrato: o
        # modal acessível exige foco ao abrir + Tab-trap + Esc, que só é
        # possível com um <script> inline nesta mesma resposta (o script
        # antigo não existia; este fragmento HTMX é o único lugar onde o
        # JS do modal pode viver).
        self.assertIn("<script", conteudo)
        self.assertIn("data-cancelar-modal", conteudo)
        self.assertIn('addEventListener("keydown"', conteudo)
        self.assertIn('"Tab"', conteudo)

    def test_visualizador_recebe_403(self):
        self.client.force_login(self.visualizador)
        resposta = self.client.get(self.url, HTTP_HX_REQUEST="true")
        self.assertEqual(resposta.status_code, 403)

    def test_cancelar_aponta_para_a_tabela(self):
        """O link "Cancelar" volta à tabela, não à
        ficha do item."""
        resposta = self.client.get(self.url, HTTP_HX_REQUEST="true")
        conteudo = resposta.content.decode()
        self.assertIn(f'href="{self.url_tabela_retorno}"', conteudo)
        self.assertNotIn("pca:detalhe_processo", conteudo)


class TestBotoesDeEscritaNaSecaoAcompanhamentos(AcompanhamentoModalBase):
    """Concentra a escrita da timeline num lugar só:
    "Alterar situação" e "Registrar acompanhamento" saem do topo da ficha
    e migram para a linha de título da seção "Acompanhamentos e prazos"
    (mesma rota/`hx-get`/querystring de antes, só o lugar muda); o topo
    fica só com "Editar". Guardas preservadas: os dois exigem
    `pode_editar` (`pca.editar_pca` + exercício aberto), independente de
    `pca.view_acompanhamento` (que só gate a seção/tabela em si); o teste
    de ordem usa um editor com AMBAS as permissões, para poder comparar a
    posição dos botões contra `id="acompanhamentos"`. Visualizador não vê
    nenhum dos dois."""

    def setUp(self):
        super().setUp()
        from django.contrib.auth.models import Permission

        self.editor.user_permissions.add(
            Permission.objects.get(codename="view_acompanhamento")
        )

    def test_editor_ve_os_dois_botoes_no_topo_junto_de_editar(self):
        """(ficha no padrão do PNCP, aprovada em
        14/10/2026) — as três ações do item voltam ao topo, lado a lado
        (Alterar situação, Registrar acompanhamento, Editar), antes das
        abas; mesmas guardas e mesma rota/`hx-get`."""
        resposta = self.client.get(self.url_detalhe)
        conteudo = resposta.content.decode()

        indice_secao = conteudo.index('id="acompanhamentos"')
        indice_transicao = conteudo.index("Alterar situação")
        indice_acompanhamento = conteudo.index("Registrar acompanhamento")
        indice_editar = conteudo.index("</i>Editar")

        self.assertLess(indice_transicao, indice_secao)
        self.assertLess(indice_acompanhamento, indice_secao)
        self.assertLess(indice_transicao, indice_editar)

    def test_visualizador_nao_ve_nenhum_dos_dois_botoes(self):
        self.client.force_login(self.visualizador)
        resposta = self.client.get(self.url_detalhe)
        conteudo = resposta.content.decode()

        self.assertNotIn("Alterar situação", conteudo)
        self.assertNotIn("Registrar acompanhamento", conteudo)


class TestAcompanhamentoModalOrigemTabela(AcompanhamentoModalBase):
    """Origem/querystring derivadas de `HX-Current-URL`
    no GET, e o fechamento por `HX-Location` (em vez de `HX-Redirect`)
    quando a origem é a tabela."""

    def test_get_da_tabela_deriva_filtros_e_origem_do_hx_current_url(self):
        uo_id = self.processo.unidade_organizacional_id
        resposta = self.client.get(
            self.url,
            HTTP_HX_REQUEST="true",
            HTTP_HX_CURRENT_URL=f"https://testserver/tabela?uo={uo_id}&pagina=2",
        )
        conteudo = resposta.content.decode()

        self.assertIn('name="origem" value="tabela"', conteudo)
        self.assertIn(f"uo={uo_id}", conteudo)
        self.assertIn("pagina=2", conteudo)

    def test_get_com_hx_current_url_invalida_cai_no_padrao(self):
        resposta = self.client.get(
            self.url,
            HTTP_HX_REQUEST="true",
            HTTP_HX_CURRENT_URL="https://evil/x?uo=<script>",
        )
        conteudo = resposta.content.decode()

        self.assertIn('name="origem" value="detalhe"', conteudo)
        self.assertIn('name="querystring_retorno" value=""', conteudo)

    def test_post_htmx_da_tabela_devolve_hx_location_sem_recarregar(self):
        uo_id = self.processo.unidade_organizacional_id
        antes = Acompanhamento.objects.filter(processo=self.processo).count()

        resposta = self.client.post(
            self.url,
            {
                "versao": self.processo.atualizado_em.isoformat(),
                "observacao": "da tabela, via HX-Location",
                "origem": "tabela",
                "querystring_retorno": f"uo={uo_id}",
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(resposta.status_code, 200)
        self.assertNotIn("HX-Redirect", resposta)
        self.assertEqual(
            json.loads(resposta["HX-Location"]),
            {"path": f"/tabela?uo={uo_id}", "target": "#listagem", "swap": "innerHTML"},
        )
        self.assertEqual(
            Acompanhamento.objects.filter(processo=self.processo).count(), antes + 1
        )

        resposta_listagem = self.client.get(
            reverse("pca:tabela"), {"uo": uo_id}, HTTP_HX_REQUEST="true"
        )
        conteudo = resposta_listagem.content.decode()
        self.assertIn(
            f"Acompanhamento do item {self.processo.item_pca} registrado.", conteudo
        )
        self.assertIn('id="modal-acompanhamento"', conteudo)

    def test_post_htmx_do_detalhe_volta_para_a_propria_ficha(self):
        """Origem "detalhe" volta para a FICHA
        (`#acompanhamentos`), não mais para a tabela; só a origem "tabela"
        continua indo para `#listagem` (inalterada)."""
        resposta = self.client.post(
            self.url,
            {
                "versao": self.processo.atualizado_em.isoformat(),
                "observacao": "do detalhe, volta pra ficha",
                "origem": "detalhe",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta["HX-Redirect"], self.url_detalhe)  # Sem âncora por htmx

    def test_post_com_origem_invalida_trata_como_detalhe(self):
        resposta = self.client.post(
            self.url,
            {
                "versao": self.processo.atualizado_em.isoformat(),
                "observacao": "origem adulterada",
                "origem": "xyz",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta["HX-Redirect"], self.url_detalhe)  # Sem âncora por htmx


class TestAcompanhamentoModalPost(AcompanhamentoModalBase):
    def test_post_com_prazo_valido_cria_acompanhamento_sem_mudar_situacao(self):
        # 29/09/2026 — "em tramitação" só vale com recebimento no Gelic no ano do PCA; o item da
        # planilha de teste tem recebimento de ano anterior, então o fixture ganha um de 2026.
        self.processo.data_recebimento_gelic = date(2026, 3, 2)
        self.processo._history_user = self.processo.history.first().history_user
        self.processo.save()
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

        self.assertRedirects(
            resposta, self.url_detalhe_ancora, fetch_redirect_response=False
        )
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

        self.assertRedirects(
            resposta, self.url_detalhe_ancora, fetch_redirect_response=False
        )
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
        self.assertEqual(resposta["HX-Redirect"], self.url_detalhe)  # Sem âncora por htmx

    def test_post_preserva_querystring_da_tabela_no_redirect(self):
        """`querystring_retorno` do
        formulário (filtros da tabela que trouxeram o usuário até o modal)
        sobrevive no redirect final, antes da âncora — agora para a ficha,
        origem "detalhe"."""
        resposta = self.client.post(
            self.url,
            {
                "versao": self.processo.atualizado_em.isoformat(),
                "observacao": "preserva filtros",
                "querystring_retorno": "uo=3&situacao=atrasado",
            },
        )
        self.assertRedirects(
            resposta,
            self.url_detalhe + "?uo=3&situacao=atrasado#acompanhamentos",
            fetch_redirect_response=False,
        )

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

    def test_mensagem_de_sucesso_identifica_o_item(self):
        """O usuário cai na tabela, então a mensagem
        precisa dizer de qual item o acompanhamento foi registrado."""
        resposta = self.client.post(
            self.url,
            {
                "versao": self.processo.atualizado_em.isoformat(),
                "observacao": "mensagem com item",
            },
            follow=True,
        )
        mensagens = [str(m) for m in resposta.context["messages"]]
        self.assertIn(
            f"Acompanhamento do item {self.processo.item_pca} registrado.",
            mensagens,
        )

    def test_post_so_com_observacao_nunca_cria_sobreposicao_manual(self):
        """Antes desta correção, `situacao_novo=processo.situacao`
        era reenviado só para satisfazer a pré-condição do serviço, e
        `registrar_acompanhamento` gravava `transicao_manual=True` mesmo
        sem o usuário ter escolhido situação nenhuma — travando
        para sempre no primeiro "só observação". `reafirmar_situacao=True`
        fecha esse caminho: o Acompanhamento nasce `transicao_manual=False`."""
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
        # prevalece sobre mesmo em No prazo/Atrasado, uma
        # sobreposição manual ativa usa o texto de prevalência manual.
        self._preparar_situacao(situacao=Situacao.ATRASADO, manual=True)

        resposta = self.client.get(self.url, HTTP_HX_REQUEST="true")

        self.assertContains(
            resposta,
            "Passa a ser o Prazo atual; a situação definida manualmente não muda.",
        )


class TestAcompanhamentoModalAvisoPrazoPassado(AcompanhamentoModalBase):
    """Prazo passado sempre grava; o `messages.warning`
    reflete a situação efetiva FINAL, nunca inferida só pela data digitada."""

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


class TestAcompanhamentoModalAjudaDeEscrita(AcompanhamentoModalBase):
    """`help_text` fixo do padrão de escrita
    em Observação/Justificativa (independe de proposta de texto)."""

    def test_observacao_e_justificativa_mostram_o_padrao_de_escrita(self):
        resposta = self.client.get(self.url, HTTP_HX_REQUEST="true")

        self.assertContains(resposta, "Um fato por frase, com a fonte")
        self.assertContains(resposta, "Não repita a situação do item")
        self.assertContains(resposta, "Só o porquê do prazo, em minúscula")
        self.assertContains(resposta, "aguardando manifestação da Projur")


class TestAcompanhamentoModalPropostaDeTexto(AcompanhamentoModalBase):
    """`apps.pca.mudancas.propor_texto` pré-
    preenche Observação no GET, nunca sobrepõe o POST do usuário e some
    depois que o acompanhamento é registrado (corte ponta a ponta)."""

    FRASE_SUGESTAO = "Texto sugerido a partir das suas últimas edições neste item"

    def test_get_traz_observacao_pre_preenchida_com_a_proposta(self):
        # Valores distintos do exemplo estático do help_text (R$ 120.000,00
        # -> R$ 148.500,00), para não colidir com ele nas asserções abaixo.
        self.processo.valor_estimado = Decimal("999999.00")
        self.processo.mes_previsto = 11
        self.processo._history_user = self.editor
        self.processo.save(
            update_fields=["valor_estimado", "mes_previsto", "atualizado_em"]
        )

        resposta = self.client.get(self.url, HTTP_HX_REQUEST="true")

        self.assertContains(resposta, "para R$ 999.999,00")
        self.assertContains(resposta, "Mês previsto alterado de")
        self.assertContains(resposta, "para novembro.")
        self.assertContains(resposta, self.FRASE_SUGESTAO)

    def test_proposta_some_depois_de_registrar(self):
        """Corte pelo último Acompanhamento funciona de ponta a ponta: a
        mesma edição que apareceu na proposta some depois de registrada."""
        self.processo.valor_estimado = Decimal("999999.00")
        self.processo._history_user = self.editor
        self.processo.save(update_fields=["valor_estimado", "atualizado_em"])

        resposta_antes = self.client.get(self.url, HTTP_HX_REQUEST="true")
        self.assertContains(resposta_antes, "para R$ 999.999,00")

        self.client.post(
            self.url,
            {
                "versao": self.processo.atualizado_em.isoformat(),
                "observacao": "registrado agora",
            },
        )

        resposta_depois = self.client.get(self.url, HTTP_HX_REQUEST="true")
        self.assertNotContains(resposta_depois, "para R$ 999.999,00")
        self.assertNotContains(resposta_depois, self.FRASE_SUGESTAO)

    def test_edicao_do_usuario_tecnico_nao_gera_proposta(self):
        User = get_user_model()
        email_robo = (
            getattr(settings, "SEI_USUARIO_TECNICO_EMAIL", None) or "robo-sei@pca.local"
        )
        robo, _ = User.objects.get_or_create(
            email=email_robo, defaults={"is_active": False}
        )
        self.processo.valor_estimado = Decimal("777777.00")
        self.processo._history_user = robo
        self.processo.save(update_fields=["valor_estimado", "atualizado_em"])

        resposta = self.client.get(self.url, HTTP_HX_REQUEST="true")

        self.assertNotContains(resposta, "para R$ 777.777,00")
        self.assertNotContains(resposta, self.FRASE_SUGESTAO)

    def test_post_invalido_preserva_o_que_o_usuario_digitou_sem_a_proposta_por_cima(self):
        self.processo.valor_estimado = Decimal("555555.00")
        self.processo._history_user = self.editor
        self.processo.save(update_fields=["valor_estimado", "atualizado_em"])

        resposta = self.client.post(
            self.url,
            {
                "versao": self.processo.atualizado_em.isoformat(),
                "prazo_prometido": "",
                "observacao": "",
            },
        )

        self.assertEqual(resposta.status_code, 200)
        self.assertNotContains(resposta, "para R$ 555.555,00")

    def test_sem_proposta_nao_mostra_a_linha_de_sugestao(self):
        resposta = self.client.get(self.url, HTTP_HX_REQUEST="true")
        self.assertNotContains(resposta, self.FRASE_SUGESTAO)


class TestAcompanhamentoModalOrigemDaReuniao(AcompanhamentoModalBase):
    """A origem do modal decide
    `usar_reuniao_corrente`: aberta pela FICHA (origem "detalhe") nunca
    amarra a linha à reunião ABERTA; aberta pela TABELA (origem "tabela")
    continua amarrando, como sempre."""

    def _abrir_reuniao(self):
        return Reuniao.objects.create(
            data=date.today(),
            exercicio=self.processo.exercicio,
            situacao=SituacaoReuniao.ABERTA,
        )

    def test_origem_detalhe_com_reuniao_aberta_nao_amarra(self):
        self._abrir_reuniao()

        self.client.post(
            self.url,
            {
                "versao": self.processo.atualizado_em.isoformat(),
                "prazo_prometido": "2026-12-01",
                "justificativa": "prazo pela ficha",
                "origem": "detalhe",
            },
        )

        acompanhamento = Acompanhamento.objects.filter(
            processo=self.processo
        ).latest("id")
        self.assertIsNone(acompanhamento.reuniao_id)
        self.assertEqual(acompanhamento.referencia_data, date.today())

    def test_origem_tabela_com_reuniao_aberta_amarra(self):
        reuniao = self._abrir_reuniao()
        uo_id = self.processo.unidade_organizacional_id

        self.client.post(
            self.url,
            {
                "versao": self.processo.atualizado_em.isoformat(),
                "prazo_prometido": "2026-12-01",
                "justificativa": "prazo pela tabela",
                "origem": "tabela",
                "querystring_retorno": f"uo={uo_id}",
            },
            HTTP_HX_REQUEST="true",
        )

        acompanhamento = Acompanhamento.objects.filter(
            processo=self.processo
        ).latest("id")
        self.assertEqual(acompanhamento.reuniao_id, reuniao.pk)
        self.assertEqual(acompanhamento.referencia_data, reuniao.data)

    def test_sem_reuniao_aberta_origem_detalhe_continua_como_hoje(self):
        self.client.post(
            self.url,
            {
                "versao": self.processo.atualizado_em.isoformat(),
                "observacao": "sem reunião aberta, origem detalhe",
                "origem": "detalhe",
            },
        )

        acompanhamento = Acompanhamento.objects.filter(
            processo=self.processo
        ).latest("id")
        self.assertIsNone(acompanhamento.reuniao_id)

    def test_sem_reuniao_aberta_origem_tabela_continua_como_hoje(self):
        uo_id = self.processo.unidade_organizacional_id

        self.client.post(
            self.url,
            {
                "versao": self.processo.atualizado_em.isoformat(),
                "observacao": "sem reunião aberta, origem tabela",
                "origem": "tabela",
                "querystring_retorno": f"uo={uo_id}",
            },
            HTTP_HX_REQUEST="true",
        )

        acompanhamento = Acompanhamento.objects.filter(
            processo=self.processo
        ).latest("id")
        self.assertIsNone(acompanhamento.reuniao_id)


class TestModalVoltaAoMesmoPonto(AcompanhamentoModalBase):
    """Ao salvar, o modal fecha e a tela volta ao MESMO
    ponto, nas duas cascas (DSGov e Tabler): o retorno à ficha por htmx vem
    sem âncora e os dois JS carregam o mesmo bloco de restauração."""

    def test_post_htmx_da_ficha_volta_sem_ancora(self):
        resposta = self.client.post(
            self.url,
            {
                "versao": self.processo.atualizado_em.isoformat(),
                "observacao": "mesmo ponto",
                "origem": "detalhe",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(resposta["HX-Redirect"], self.url_detalhe)
        self.assertNotIn("#", resposta["HX-Redirect"])

    def test_post_sem_htmx_mantem_ancora(self):
        resposta = self.client.post(
            self.url,
            {"versao": self.processo.atualizado_em.isoformat(), "observacao": "sem js"},
        )
        self.assertRedirects(
            resposta, self.url_detalhe_ancora, fetch_redirect_response=False
        )

    def test_js_das_duas_cascas_restaura_a_rolagem(self):
        from pathlib import Path

        raiz = Path(__file__).resolve().parents[3] / "core/static"
        for nome in ("dsgov/js/dsgov.js", "tabler/js/pca-tabler.js"):
            conteudo = (raiz / nome).read_text()
            with self.subTest(js=nome):
                self.assertIn('"pca-rolagem-modal"', conteudo)
                self.assertIn("form-acompanhamento", conteudo)
                self.assertIn('alvo.id === "listagem"', conteudo)
                self.assertIn("restaurarRolagemModal", conteudo)


class TestModalRetangular(AcompanhamentoModalBase):
    """O modal é mais largo que alto nas duas cascas: DSGov com
    `br-modal dsgov-modal-largo`, Tabler com `modal-xl`, e Observação/Justificativa
    lado a lado (`col-md-4`, três colunas)."""

    def test_dsgov_modal_largo_com_campos_lado_a_lado(self):
        html = self.client.get(self.url, HTTP_HX_REQUEST="true").content.decode()
        self.assertIn('class="br-modal dsgov-modal-largo"', html)
        self.assertEqual(html.count('class="col-md-4 mb-3"'), 3)

    def test_tabler_modal_xl(self):
        from pathlib import Path

        caminho = Path(__file__).resolve().parents[3] / "tabler/templates/pca/_acompanhamento_modal.html"
        conteudo = caminho.read_text()
        self.assertIn("modal-dialog modal-xl", conteudo)
        self.assertNotIn("modal-lg", conteudo)
