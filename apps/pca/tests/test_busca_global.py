"""Busca global (header/skiplink/atalho) cobrindo todos os exercícios;
`/tabela` continua restrita ao seu exercício. Fixtures reais via ORM
direto (`django.test.TestCase`)."""

import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.catalogo.models import Categoria, Exercicio, Tipo, Unidade
from apps.pca.models import Processo

RAIZ_REPO = Path(__file__).resolve().parents[3]


class TestBuscaGlobalCobreTodosOsExercicios(TestCase):
    """A busca global encontra um processo de qualquer exercício, mesmo
    que o exercício atual (mais recentemente aberto) seja outro;
    `/tabela` (sem `exercicio=` explícito) continua restrita ao seu
    próprio recorte."""

    TERMO_UNICO = "TermoUnicoBusca28x9k"

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.usuario = User.objects.create_user(
            email="busca@example.com", password="senha-segura"
        )
        cls.tipo = Tipo.objects.create(nome="Aquisição")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.unidade = Unidade.objects.create(nome="Presidência")

        # Exercício ATUAL (o mais recente aberto) — nenhum processo com o
        # termo aqui, para que a busca por /tabela (que resolve este
        # exercício por padrão) não encontre o processo do exercício
        # anterior por acaso.
        cls.exercicio_atual = Exercicio.objects.get(ano=2026)
        # Exercício ANTERIOR — onde o processo-alvo mora.
        cls.exercicio_anterior = Exercicio.objects.create(
            ano=2025, rotulo="PCA 2025", situacao="fechado"
        )
        cls.processo_alvo = Processo.objects.create(
            item_pca=1,
            descricao_objeto=cls.TERMO_UNICO,
            tipo=cls.tipo,
            categoria=cls.categoria,
            unidade_organizacional=cls.unidade,
            exercicio=cls.exercicio_anterior,
        )

    def test_busca_global_encontra_processo_de_exercicio_anterior(self):
        client = Client()
        client.force_login(self.usuario)
        resposta = client.get(reverse("pca:busca"), {"q": self.TERMO_UNICO})
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, str(self.processo_alvo.item_pca))
        self.assertContains(resposta, self.TERMO_UNICO)

    def test_tabela_sem_exercicio_explicito_nao_encontra_processo_de_outro_exercicio(
        self,
    ):
        client = Client()
        client.force_login(self.usuario)
        resposta = client.get(reverse("pca:tabela"), {"q": self.TERMO_UNICO})
        self.assertEqual(resposta.status_code, 200)
        # O termo digitado é ecoado de volta no próprio campo de filtro
        # (`value="{{ filtros.q }}"`); o que precisa estar AUSENTE é a
        # linha do processo (de outro exercício) no resultado.
        self.assertContains(resposta, "Nenhum processo com esses filtros")
        url_detalhe = reverse(
            "pca:detalhe_processo",
            args=[self.exercicio_anterior.ano, self.processo_alvo.item_pca],
        )
        self.assertNotContains(resposta, url_detalhe)

    def test_busca_global_restringe_a_um_exercicio_quando_informado(self):
        client = Client()
        client.force_login(self.usuario)
        resposta = client.get(
            reverse("pca:busca"),
            {"q": self.TERMO_UNICO, "exercicio": self.exercicio_atual.ano},
        )
        self.assertEqual(resposta.status_code, 200)
        # O termo em si é ecoado de volta (título da página, campo de busca
        # do header e o próprio formulário desta tela) mesmo sem resultado —
        # o que precisa estar AUSENTE é a linha do processo encontrado.
        self.assertContains(resposta, "Nenhum processo encontrado")
        url_detalhe = reverse(
            "pca:detalhe_processo",
            args=[self.exercicio_anterior.ano, self.processo_alvo.item_pca],
        )
        self.assertNotContains(resposta, url_detalhe)

    def test_busca_global_sem_termo_mostra_estado_aguardar_pesquisa(self):
        client = Client()
        client.force_login(self.usuario)
        resposta = client.get(reverse("pca:busca"))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Digite um termo para pesquisar")

    def test_busca_global_devolve_aviso_de_data_invalida(self):
        client = Client()
        client.force_login(self.usuario)
        resposta = client.get(reverse("pca:busca"), {"q": "31/02/2026"})
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Data inválida")


class TestHeaderSkiplinkEAtalho(TestCase):
    """O header expõe o campo de busca que o skiplink já esperava; o
    atalho Alt+Shift+P está em `dsgov.js`."""

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.usuario = User.objects.create_user(
            email="header@example.com", password="senha-segura"
        )

    def test_header_tem_main_searchbox_e_data_toggle_search(self):
        client = Client()
        client.force_login(self.usuario)
        resposta = client.get(reverse("pca:tabela"))
        conteudo = resposta.content.decode()
        self.assertIn("main-searchbox", conteudo)
        self.assertIn('data-toggle="search"', conteudo)

    def test_skiplink_aponta_para_main_searchbox(self):
        client = Client()
        client.force_login(self.usuario)
        resposta = client.get(reverse("pca:tabela"))
        self.assertContains(resposta, 'href="#main-searchbox"')

    def test_dsgov_js_tem_atalho_alt_shift_p(self):
        conteudo = (
            RAIZ_REPO / "core" / "static" / "dsgov" / "js" / "dsgov.js"
        ).read_text(encoding="utf-8")
        self.assertIn("KeyP", conteudo)
        self.assertIn("isComposing", conteudo)

    def test_cache_worker_avancou_desde_o_plano_28_03(self):
        # O número só precisa ser maior que 35, nunca igual ou menor —
        # provando que toda mudança em estático desde então cumpriu a
        # convenção "pca-static-vN sobe a cada mudança".
        conteudo = (RAIZ_REPO / "core" / "views.py").read_text(encoding="utf-8")
        match = re.search(r'pca-static-v(\d+)', conteudo)
        self.assertIsNotNone(match, "CACHE_NAME pca-static-vN não encontrado em core/views.py")
        self.assertGreater(int(match.group(1)), 35)
        self.assertNotIn("pca-static-v34", conteudo)
