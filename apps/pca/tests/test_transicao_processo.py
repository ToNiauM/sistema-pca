"""Alterar situação como página própria (`processo_transicao.html`), com
`br-message warning` explicando a consequência, nunca um modal de
confirmação. `pca:transicao_processo` é a única forma de alterar
situação."""

from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TransactionTestCase
from django.urls import reverse

from apps.pca.models import Processo, Situacao


class TransicaoProcessoBase(TransactionTestCase):
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
            email="editor-transicao@pca.local", password="senha-segura"
        )
        self.editor.groups.add(Group.objects.get(name="editor"))
        self.visualizador = User.objects.create_user(
            email="visualizador-transicao@pca.local", password="senha-segura"
        )
        self.processo = Processo.objects.get(item_pca=1)
        self.client.force_login(self.editor)

    @property
    def url(self):
        return reverse("pca:transicao_processo", args=[2026, self.processo.item_pca])

    @property
    def url_detalhe(self):
        return reverse("pca:detalhe_processo", args=[2026, self.processo.item_pca])


class TestTransicaoProcessoPermissao(TransicaoProcessoBase):
    def test_visualizador_recebe_403(self):
        self.client.force_login(self.visualizador)
        resposta = self.client.get(self.url)
        self.assertEqual(resposta.status_code, 403)

    def test_editor_ve_pagina_com_select_preselecionado_e_aviso(self):
        resposta = self.client.get(self.url)
        conteudo = resposta.content.decode()

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(conteudo.count("<h1"), 1)
        self.assertIn("br-message warning", conteudo)
        self.assertNotIn("<br-modal", conteudo)
        # `br-select` do renderer marca a opção corrente com `checked`
        # (radios em `br-list`, `dsgov/forms/select.html`).
        self.assertIn(f'value="{self.processo.situacao}" checked', conteudo)


class TestTransicaoProcessoEscrita(TransicaoProcessoBase):
    def test_post_valido_muda_situacao_e_redireciona_ao_detalhe(self):
        resposta = self.client.post(
            self.url,
            {
                "versao": self.processo.atualizado_em.isoformat(),
                "destino": Situacao.CONCLUIDO,
                "justificativa": "Contrato encerrado — teste 26-02",
            },
        )
        self.assertRedirects(resposta, self.url_detalhe)
        self.processo.refresh_from_db()
        self.assertEqual(self.processo.situacao, Situacao.CONCLUIDO.value)

    def test_post_destino_invalido_devolve_200_com_erro_nunca_500(self):
        resposta = self.client.post(
            self.url,
            {
                "versao": self.processo.atualizado_em.isoformat(),
                "destino": "valor_invalido",
                "justificativa": "x",
            },
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("Faça uma escolha válida", resposta.content.decode())

    def test_post_sem_justificativa_e_recusado(self):
        situacao_antes = self.processo.situacao
        resposta = self.client.post(
            self.url,
            {
                "versao": self.processo.atualizado_em.isoformat(),
                "destino": Situacao.CONCLUIDO,
                "justificativa": "",
            },
        )
        self.assertEqual(resposta.status_code, 200)
        self.processo.refresh_from_db()
        self.assertEqual(self.processo.situacao, situacao_antes)

    def test_conflito_de_versao_reabre_a_pagina_com_aviso(self):
        resposta = self.client.post(
            self.url,
            {
                "versao": "2000-01-01T00:00:00+00:00",
                "destino": Situacao.CONCLUIDO,
                "justificativa": "não deveria gravar",
            },
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("mudou enquanto você editava", resposta.content.decode())

    def test_visualizador_recebe_403_no_post(self):
        self.client.force_login(self.visualizador)
        resposta = self.client.post(
            self.url,
            {
                "versao": self.processo.atualizado_em.isoformat(),
                "destino": Situacao.CONCLUIDO,
                "justificativa": "x",
            },
        )
        self.assertEqual(resposta.status_code, 403)
