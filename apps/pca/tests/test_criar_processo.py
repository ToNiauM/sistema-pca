from datetime import date
from concurrent.futures import ThreadPoolExecutor
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.db import close_old_connections
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils.timezone import localdate

from apps.pca.models import Acompanhamento, Estado, Processo, Situacao
from apps.pca.services import criar_processo


ARQUIVO_REAL = "apps/pca/fixtures/modelo-controle-exemplo.xlsx"


class CriacaoProcessoBase(TransactionTestCase):
    serialized_rollback = True

    def setUp(self):
        call_command(
            "importar_pca",
            ARQUIVO_REAL,
            "--usuario=importador@pca.local",
            exercicio=2026,
            stdout=StringIO(),
        )
        self.editor = get_user_model().objects.create_user(
            email="editor-criacao@pca.local", password="senha-segura"
        )
        self.editor.groups.add(Group.objects.get(name="editor"))
        self.visualizador = get_user_model().objects.create_user(
            email="visualizador-criacao@pca.local", password="senha-segura"
        )
        self.tipo = Processo.objects.get(item_pca=1).tipo
        self.categoria = Processo.objects.get(item_pca=1).categoria
        self.unidade = Processo.objects.get(item_pca=1).unidade_organizacional


class TestCriarProcessoServico(CriacaoProcessoBase):
    def _criar(self, usuario=None, descricao="Novo processo na reunião"):
        return criar_processo(
            usuario=usuario or self.editor,
            descricao_objeto=descricao,
            tipo_id=self.tipo.pk,
            categoria_id=self.categoria.pk,
            unidade_organizacional_id=self.unidade.pk,
        )

    def test_proximo_item_data_inclusao_e_autoria(self):
        processo = self._criar()

        self.assertEqual(processo.item_pca, 31)
        self.assertEqual(processo.data_inclusao_pca, localdate())
        self.assertTrue(
            processo.history.filter(history_user=self.editor).exists()
        )
        self.assertIsNone(processo.valor_estimado)
        self.assertIsNone(processo.grau_prioridade_id)
        self.assertIsNone(processo.classificacao_id)
        # `criar_processo_view` não pede status ao usuário: todo processo
        # novo nasce Estado=Ativo/Situação=No prazo, mesmo par literal de
        # `services.criar_processo`.
        self.assertEqual(processo.estado, Estado.ATIVO.value)
        self.assertEqual(processo.situacao, Situacao.NO_PRAZO.value)

    def test_chamadas_sequenciais_recebem_numeros_distintos(self):
        primeiro = self._criar(descricao="Primeiro processo")
        segundo = self._criar(descricao="Segundo processo")

        self.assertEqual((primeiro.item_pca, segundo.item_pca), (31, 32))
        self.assertEqual(Processo.objects.filter(item_pca__gte=31).count(), 2)

    def test_banco_vazio_comeca_em_um_e_continua_em_dois(self):
        Acompanhamento.objects.all().delete()
        Processo.objects.all().delete()

        primeiro = self._criar(descricao="Primeiro processo da base vazia")
        segundo = self._criar(descricao="Segundo processo da base vazia")

        self.assertEqual((primeiro.item_pca, segundo.item_pca), (1, 2))

    def test_criacoes_concorrentes_na_base_vazia_sao_sequenciais(self):
        Acompanhamento.objects.all().delete()
        Processo.objects.all().delete()

        def criar_em_outra_conexao(numero):
            close_old_connections()
            try:
                return self._criar(descricao=f"Concorrente {numero}").item_pca
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            itens = sorted(executor.map(criar_em_outra_conexao, (1, 2)))

        self.assertEqual(itens, [1, 2])


class TestCriarProcessoView(CriacaoProcessoBase):
    """`pca:criar_processo` é página própria (`processo_formulario.html`).
    Sucesso redireciona ao detalhe, nunca fica na tela."""

    def _dados(self, descricao="Processo criado pela tela"):
        return {
            "descricao_objeto": descricao,
            "tipo": str(self.tipo.pk),
            "categoria": str(self.categoria.pk),
            "unidade_organizacional": str(self.unidade.pk),
        }

    def test_post_valido_redireciona_ao_detalhe_do_item_novo(self):
        self.client.force_login(self.editor)

        resposta = self.client.post(reverse("pca:criar_processo"), self._dados())

        self.assertEqual(resposta.status_code, 302)
        self.assertRegex(resposta.url, r"/processo/\d+/31$")
        # Sem seletor de status no form: o item nasce
        # Estado=Ativo/Situação=No prazo sem input do usuário.
        processo = Processo.objects.get(item_pca=31)
        self.assertEqual(processo.estado, Estado.ATIVO.value)
        self.assertEqual(processo.situacao, Situacao.NO_PRAZO.value)

        resposta_detalhe = self.client.get(resposta.url)
        mensagens = [str(m) for m in resposta_detalhe.context["messages"]]
        self.assertIn("Processo criado com sucesso.", mensagens)

    def test_post_invalido_preserva_selecoes_e_exibe_erro(self):
        self.client.force_login(self.editor)
        dados = self._dados(descricao="")

        resposta = self.client.post(reverse("pca:criar_processo"), dados)
        conteudo = resposta.content.decode()

        self.assertEqual(resposta.status_code, 200)
        self.assertIn("Este campo é obrigatório", conteudo)
        # br-select do renderer marca a opção selecionada com `checked`, não
        # `selected` (contrato do `br-select` — radios dentro de `br-list`,
        # `dsgov/forms/select.html`), diferente do `<select>` nativo que o
        # modal antigo usava.
        self.assertIn(f'value="{self.tipo.pk}" checked', conteudo)
        self.assertIn(f'value="{self.categoria.pk}" checked', conteudo)
        self.assertIn(f'value="{self.unidade.pk}" checked', conteudo)
        self.assertEqual(Processo.objects.count(), 30)

    def test_visualizador_recebe_403(self):
        self.client.force_login(self.visualizador)

        resposta = self.client.post(
            reverse("pca:criar_processo"), self._dados()
        )

        self.assertEqual(resposta.status_code, 403)

    def test_get_devolve_pagina_completa_com_um_h1_e_4_campos(self):
        self.client.force_login(self.editor)

        resposta = self.client.get(reverse("pca:criar_processo"))
        conteudo = resposta.content.decode()

        self.assertEqual(resposta.status_code, 200)
        self.assertIn("<html", conteudo)
        self.assertEqual(conteudo.count("<h1"), 1)
        self.assertIn("Novo processo", conteudo)
        self.assertNotIn("<br-modal", conteudo)
        self.assertNotIn("x-data", conteudo)


class TestSeloInclusao(CriacaoProcessoBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.editor)

    def test_base_real_tem_data_apenas_nos_itens_incluidos(self):
        incluidos = set(
            Processo.objects.exclude(data_inclusao_pca__isnull=True).values_list(
                "item_pca", flat=True
            )
        )
        self.assertEqual(incluidos, set(range(25, 31)))

    def test_selo_data_inclusao_aparece_no_detalhe_do_processo(self):
        # `data_inclusao_pca` não é coluna visível da tabela; a
        # superfície viva que carrega essa informação é o detalhe do
        # processo (`pca:detalhe_processo`), que lista todo
        # `SECOES_FORMULARIO_PROCESSO` em modo leitura.
        processo_selo = Processo.objects.get(item_pca=25)
        resposta = self.client.get(
            reverse(
                "pca:detalhe_processo", args=[processo_selo.exercicio.ano, 25]
            )
        )
        conteudo = resposta.content.decode()
        self.assertIn("Data de inclusão no PCA", conteudo)
        self.assertIn("09/03/2026", conteudo)

    def test_item_sem_data_mostra_ausencia_explicita_no_detalhe(self):
        # Ausência nunca é célula em branco, provado contra o detalhe do
        # processo.
        processo_1 = Processo.objects.get(item_pca=1)
        resposta = self.client.get(
            reverse(
                "pca:detalhe_processo", args=[processo_1.exercicio.ano, 1]
            )
        )
        conteudo = resposta.content.decode()
        inicio = conteudo.index("Data de inclusão no PCA")
        trecho = conteudo[inicio : inicio + 300]
        self.assertNotIn("09/03/2026", trecho)

    def test_botao_novo_processo_so_aparece_para_editor(self):
        editor_html = self.client.get(reverse("pca:tabela")).content.decode()
        self.assertIn("Novo processo", editor_html)
        self.assertIn('href="/processo/novo"', editor_html)

        self.client.force_login(self.visualizador)
        visualizador_html = self.client.get(reverse("pca:tabela")).content.decode()
        self.assertNotIn("Novo processo", visualizador_html)
        self.assertNotIn('href="/processo/novo"', visualizador_html)
