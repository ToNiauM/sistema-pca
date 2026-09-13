from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from apps.catalogo.models import Categoria, Exercicio, Tipo, Unidade
from apps.pca.models import Processo


class TestColunaAcoesTabela(TestCase):
    """A coluna Ações da tela Processos tem exatamente 3 `br-button circle
    small`: Ver (sempre), Editar e Registrar acompanhamento (só com
    `pca.editar_pca`)."""

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.editor = User.objects.create_user(
            email="editor-acoes@example.com", password="senha-segura"
        )
        cls.editor.groups.add(Group.objects.get(name="editor"))

        cls.visualizador = User.objects.create_user(
            email="visualizador-acoes@example.com", password="senha-segura"
        )
        cls.visualizador.groups.add(Group.objects.get(name="visualizador"))

        cls.unidade = Unidade.objects.create(nome="Presidência")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.tipo = Tipo.objects.create(nome="Aquisição")
        cls.exercicio = Exercicio.objects.get(ano=2026)

        cls.processo1 = Processo.objects.create(
            item_pca=1,
            descricao_objeto="Processo 1 para teste de acoes",
            tipo=cls.tipo,
            categoria=cls.categoria,
            unidade_organizacional=cls.unidade,
            exercicio=cls.exercicio,
        )
        cls.processo2 = Processo.objects.create(
            item_pca=2,
            descricao_objeto="Processo 2 para teste de acoes",
            tipo=cls.tipo,
            categoria=cls.categoria,
            unidade_organizacional=cls.unidade,
            exercicio=cls.exercicio,
        )

    def test_editor_ve_ver_editar_e_registrar_acompanhamento(self):
        self.client.force_login(self.editor)
        conteudo = self.client.get(reverse("pca:tabela")).content.decode()
        url_editar = reverse(
            "pca:editar_processo", args=[self.exercicio.ano, self.processo1.item_pca]
        )
        url_acompanhamento = reverse(
            "pca:acompanhamento_modal",
            args=[self.exercicio.ano, self.processo1.item_pca],
        )
        self.assertIn(url_editar, conteudo)
        self.assertIn(url_acompanhamento, conteudo)
        self.assertIn("fa-eye", conteudo)
        self.assertIn("fa-pen", conteudo)
        self.assertIn("fa-plus", conteudo)

    def test_visualizador_ve_so_ver_sem_editar_nem_registrar(self):
        self.client.force_login(self.visualizador)
        conteudo = self.client.get(reverse("pca:tabela")).content.decode()
        url_editar = reverse(
            "pca:editar_processo", args=[self.exercicio.ano, self.processo1.item_pca]
        )
        url_acompanhamento = reverse(
            "pca:acompanhamento_modal",
            args=[self.exercicio.ano, self.processo1.item_pca],
        )
        self.assertIn("fa-eye", conteudo)
        self.assertNotIn(url_editar, conteudo)
        self.assertNotIn(url_acompanhamento, conteudo)

    def test_novo_processo_so_no_cabecalho_e_so_para_editor(self):
        self.client.force_login(self.editor)
        conteudo = self.client.get(reverse("pca:tabela")).content.decode()
        self.assertEqual(conteudo.count(reverse("pca:criar_processo")), 1)

        self.client.force_login(self.visualizador)
        conteudo = self.client.get(reverse("pca:tabela")).content.decode()
        self.assertNotIn(reverse("pca:criar_processo"), conteudo)

    def test_nenhuma_celula_e_editavel_na_linha(self):
        """Zero edição inline: nenhum `hx-post` para `pca:editar_campo`
        nem `<input>`/`<select>` de edição por célula na linha da tabela."""
        self.client.force_login(self.editor)
        conteudo = self.client.get(reverse("pca:tabela")).content.decode()
        self.assertNotIn("editar_campo", conteudo)
        self.assertNotIn('hx-target="#modal"', conteudo)
        self.assertNotIn("modo=ver", conteudo)


