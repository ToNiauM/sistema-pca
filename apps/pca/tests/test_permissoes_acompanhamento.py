"""Gate `pca.view_acompanhamento`: acompanhamentos e
prazos (timeline da ficha, quadro "PRAZO ATUAL", colunas de prazo/
reuniões da tabela, calendário, reuniões, relatório de movimentação, itens
de menu) passam a ser visíveis só para o grupo `editor`. Mesmo padrão de
fixture de `test_permissoes.py` (editor/visualizador/superuser via
`Group.objects.get(name=...)`, já existentes pela migration 0004) mais
`call_command("configurar_grupos")` no `setUpTestData` para garantir
`view_acompanhamento` no editor ANTES dos testes — o comando não roda em
produção automaticamente."""

from datetime import date
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.catalogo.models import Categoria, Exercicio, SituacaoNormalizada, Tipo, Unidade
from apps.pca.models import Acompanhamento, Processo, Situacao, TipoEvento
from core.menu import itens as itens_menu


class PermissoesAcompanhamentoBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("configurar_grupos", stdout=StringIO())

        User = get_user_model()
        cls.editor = User.objects.create_user(
            email="editor-acompanhamento@example.com", password="senha-segura"
        )
        cls.editor.groups.add(Group.objects.get(name="editor"))
        cls.visualizador = User.objects.create_user(
            email="visualizador-acompanhamento@example.com", password="senha-segura"
        )
        cls.visualizador.groups.add(Group.objects.get(name="visualizador"))

        cls.unidade = Unidade.objects.create(nome="Presidência x9bf0")
        cls.categoria = Categoria.objects.create(nome="Serviços x9bf0")
        cls.tipo = Tipo.objects.create(nome="Aquisição x9bf0")
        cls.exercicio = Exercicio.objects.get(ano=2026)
        cls.situacao_normalizada = SituacaoNormalizada.objects.create(
            nome="Em tramitação x9bf0"
        )
        cls.processo = Processo.objects.create(
            item_pca=1,
            exercicio=cls.exercicio,
            descricao_objeto="Processo de teste do gate de acompanhamento",
            tipo=cls.tipo,
            categoria=cls.categoria,
            unidade_organizacional=cls.unidade,
            situacao=Situacao.EM_TRAMITACAO,
        )
        cls.acompanhamento = Acompanhamento.objects.create(
            processo=cls.processo,
            referencia_data=date(2026, 3, 1),
            origem_hash="hash-x9bf0-1",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO,
            situacao=cls.situacao_normalizada,
            prazo_prometido=date(2026, 6, 1),
            evento="Compromisso de teste x9bf0",
        )


class TestFichaProcessoGateAcompanhamento(PermissoesAcompanhamentoBase):
    def _url_detalhe(self):
        return reverse(
            "pca:detalhe_processo", args=[self.exercicio.ano, self.processo.item_pca]
        )

    def test_visualizador_nao_ve_timeline_nem_prazo_atual(self):
        self.client.force_login(self.visualizador)
        resposta = self.client.get(self._url_detalhe())
        self.assertEqual(resposta.status_code, 200)
        self.assertNotIn("timeline_exibida", resposta.context)
        self.assertNotIn("timeline_total", resposta.context)
        self.assertIsNone(resposta.context["prazo_atual_ficha"])
        self.assertFalse(resposta.context["pode_ver_acompanhamento"])
        conteudo = resposta.content.decode()
        self.assertNotIn("Prazo inicial", conteudo)
        self.assertNotIn("Compromisso vigente", conteudo)
        self.assertNotIn("Acompanhamentos e prazos", conteudo)
        self.assertNotIn(self.acompanhamento.evento, conteudo)

    def test_editor_ve_timeline_e_prazo_atual(self):
        self.client.force_login(self.editor)
        resposta = self.client.get(self._url_detalhe())
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("timeline_exibida", resposta.context)
        self.assertIn("timeline_total", resposta.context)
        self.assertIsNotNone(resposta.context["prazo_atual_ficha"])
        self.assertTrue(resposta.context["pode_ver_acompanhamento"])
        conteudo = resposta.content.decode()
        self.assertIn("Prazo atual", conteudo)  # Linha "Compromisso vigente"
        self.assertIn("Acompanhamentos e prazos", conteudo)


class TestTabelaGateAcompanhamento(PermissoesAcompanhamentoBase):
    def test_visualizador_nunca_ve_colunas_restritas_mesmo_pedindo_explicitamente(self):
        self.client.force_login(self.visualizador)
        resposta = self.client.get(reverse("pca:tabela"), {"colunas": "n_reunioes"})
        self.assertEqual(resposta.status_code, 200)
        chaves = [c["chave"] for c in resposta.context["cabecalhos_dinamicos"]]
        self.assertNotIn("n_reunioes", chaves)
        for _secao, colunas in resposta.context["colunas_por_secao"]:
            for coluna in colunas:
                self.assertNotIn(
                    coluna.chave,
                    (
                        "prazo_inicial",
                        "prazo_efetivo",
                        "n_reunioes",
                        "n_compromissos",
                        "dias_atraso",
                        "n_prorrogacoes",
                        "situacao_atual",
                    ),
                )

    def test_editor_ve_coluna_restrita_quando_selecionada(self):
        self.client.force_login(self.editor)
        resposta = self.client.get(reverse("pca:tabela"), {"colunas": "n_reunioes"})
        self.assertEqual(resposta.status_code, 200)
        chaves = [c["chave"] for c in resposta.context["cabecalhos_dinamicos"]]
        self.assertIn("n_reunioes", chaves)


class TestRotasGateAcompanhamento(PermissoesAcompanhamentoBase):
    def test_calendario_visualizador_403_editor_200(self):
        self.client.force_login(self.visualizador)
        self.assertEqual(self.client.get(reverse("pca:calendario")).status_code, 403)
        self.client.force_login(self.editor)
        self.assertEqual(self.client.get(reverse("pca:calendario")).status_code, 200)

    def test_reunioes_visualizador_403_editor_200(self):
        self.client.force_login(self.visualizador)
        self.assertEqual(
            self.client.get(reverse("pca:reuniao_listagem")).status_code, 403
        )
        self.client.force_login(self.editor)
        self.assertEqual(
            self.client.get(reverse("pca:reuniao_listagem")).status_code, 200
        )

    def test_relatorio_movimentacao_visualizador_403_editor_200(self):
        self.client.force_login(self.visualizador)
        self.assertEqual(
            self.client.get(reverse("pca:relatorio_movimentacao")).status_code, 403
        )
        self.client.force_login(self.editor)
        self.assertEqual(
            self.client.get(reverse("pca:relatorio_movimentacao")).status_code, 200
        )


class TestMenuLateralGateAcompanhamento(PermissoesAcompanhamentoBase):
    def _rotulos_do_menu(self, usuario):
        from django.test import RequestFactory

        request = RequestFactory().get("/")
        request.user = usuario
        return [item["rotulo"] for item in itens_menu(request)]

    def test_visualizador_sem_os_tres_itens(self):
        rotulos = self._rotulos_do_menu(self.visualizador)
        self.assertNotIn("Calendário", rotulos)
        self.assertNotIn("Reuniões", rotulos)
        self.assertNotIn("Relatório da reunião", rotulos)

    def test_editor_com_os_tres_itens(self):
        rotulos = self._rotulos_do_menu(self.editor)
        self.assertIn("Calendário", rotulos)
        self.assertIn("Reuniões", rotulos)
        self.assertIn("Relatório da reunião", rotulos)
