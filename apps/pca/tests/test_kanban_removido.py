from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TransactionTestCase
from django.urls import reverse

ARQUIVO_REAL = "apps/pca/fixtures/modelo-controle-exemplo.xlsx"


class _BaseComImportacao(TransactionTestCase):
    """setUp padrão replicado do arquivo apagado test_kanban_arrastar.py:
    import real via call_command, usuário `editor` no grupo `editor` e
    `visualizador` sem grupo."""

    serialized_rollback = True

    def setUp(self):
        call_command(
            "importar_pca",
            ARQUIVO_REAL,
            "--usuario=importador@pca.local",
            "--exercicio=2026",
            stdout=StringIO(),
        )
        User = get_user_model()
        self.visualizador = User.objects.create_user(
            email="visualizador-pos-kanban@pca.local", password="senha-segura"
        )
        self.editor = User.objects.create_user(
            email="editor-pos-kanban@pca.local", password="senha-segura"
        )
        self.editor.groups.add(Group.objects.get(name="editor"))


class TestRedirecionamentoKanban(_BaseComImportacao):
    """`/kanban`, com e sem querystring, devolve 301 para `/tabela` e
    nunca conteúdo HTML de quadro."""

    def test_sem_filtro(self):
        self.client.force_login(self.visualizador)
        resposta = self.client.get(reverse("pca:kanban"))
        self.assertEqual(resposta.status_code, 301)
        self.assertEqual(resposta["Location"], reverse("pca:tabela"))

    def test_com_filtro_preserva_querystring(self):
        # `redirecionar_kanban_view` só preserva filtros validados
        # (`querystring_filtros`); `situacao=` é o parâmetro real hoje.
        self.client.force_login(self.visualizador)
        resposta = self.client.get(reverse("pca:kanban"), {"situacao": "concluido"})
        self.assertEqual(resposta.status_code, 301)
        self.assertEqual(
            resposta["Location"], reverse("pca:tabela") + "?situacao=concluido"
        )


class TestNavSemKanban(_BaseComImportacao):
    """A navegação não contém o item Kanban."""

    def test_menu_nao_contem_kanban(self):
        self.client.force_login(self.visualizador)
        resposta = self.client.get(reverse("raiz"))
        conteudo = resposta.content.decode()
        self.assertNotIn('aria-label="Kanban"', conteudo)
        self.assertNotIn(">Kanban<", conteudo)


# A prova de que uma transição bem-sucedida atualiza a situação do
# processo é coberta por `test_transicao_processo.py`
# (`pca:transicao_processo`) — a única forma de alterar situação hoje é
# uma página que redireciona ao detalhe.
