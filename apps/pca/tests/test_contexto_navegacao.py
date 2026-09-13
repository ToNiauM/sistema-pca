from io import StringIO

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TransactionTestCase
from django.urls import reverse

from apps.catalogo.models import Exercicio

ARQUIVO_REAL = "apps/pca/fixtures/modelo-controle-exemplo.xlsx"


class TestContextoNavegacao(TransactionTestCase):
    """Cobertura de regressão da identidade anual, rótulos únicos de
    menu/rodapé e foco pós-navegação.

    Mesmo padrão de `setUp()` de `TestNavegacaoPreservaFiltro`
    (`test_navegacao_filtro.py`): import real a cada teste
    (`TransactionTestCase` não chama `setUpTestData()` e faz `flush()`
    entre testes) e `serialized_rollback` para preservar o usuário de
    serviço da migração. Um segundo exercício (2027, sem processo — só a
    identidade) é criado à mão para exercitar o item ancestral da trilha
    com um exercício diferente do que o import real usa (2026)."""

    serialized_rollback = True

    def setUp(self):
        call_command(
            "importar_pca",
            ARQUIVO_REAL,
            "--usuario=importador@pca.local",
            "--exercicio=2026",
            stdout=StringIO(),
        )
        Exercicio.objects.get_or_create(ano=2027, defaults={"rotulo": "PCA 2027"})
        self.usuario = get_user_model().objects.create_user(
            email="leitor@pca.local", password="x-forte-123"
        )
        self.client.force_login(self.usuario)

    # `pca:calendario`/`pca:resumo_uo` usam `base.html` (skill dsgov).
    # Nenhuma tela do sistema usa a casca legada.
    #
    # Testes removidos (sem exemplar vivo para provar contra uma
    # requisição real; features do contrato legado, não reimplementadas
    # pela skill):
    # - `test_ancestral_da_trilha_preserva_exercicio_da_pagina`:
    #   `dsgov/_breadcrumb.html` (fixo, intocável) sempre linka o ícone de
    #   casa para `core:inicio` puro, sem propagar `exercicio` — a skill
    #   não reproduz esse comportamento, e o partial não pode ser editado.
    # - `test_rodape_tem_os_5_destinos_e_carrega_o_filtro_ativo`:
    #   `dsgov/_footer.html` (fixo) é só logo + texto institucional, sem
    #   nenhum link de navegação — a lista de "5 destinos" simplesmente
    #   não existe no rodapé da skill.
    # - `test_navegacao_sequencial_nao_duplica_conteudo_principal`: o
    #   roteador `brNavigate`/`#conteudo-principal` (troca só do `<main>`
    #   via HTMX) não existe em nenhuma tela — toda navegação é página
    #   inteira.
    # - `test_x_init_do_shell_nao_vaza_javascript_como_texto`: guarda de
    #   `div.pca-shell`/`x-init` (Alpine), inexistente em `base.html`.
    #
    # Testes reescritos contra o contrato NOVO abaixo.

    def test_titulo_da_pagina_usa_o_rotulo_correto_de_cada_tela(self):
        # Contrato de `base.html`: `<title>{{ bloco titulo }} — {{
        # DSGOV.SISTEMA }}</title>`, sempre com o sufixo `DSGOV.SISTEMA`.
        # Cada tela escolhe seu próprio separador `·`/`—` antes do ano —
        # não normalizado.
        sistema = settings.DSGOV["SISTEMA"]
        casos = (
            ("pca:calendario", f"<title>Calendário · PCA 2026 — {sistema}</title>"),
            (
                "pca:resumo_uo",
                f"<title>Resumo por unidade — PCA 2026 — {sistema}</title>",
            ),
        )
        for nome_rota, titulo_esperado in casos:
            with self.subTest(rota=nome_rota):
                resposta = self.client.get(reverse(nome_rota), {"exercicio": "2026"})
                conteudo = resposta.content.decode("utf-8")
                self.assertIn(titulo_esperado, conteudo)

    def test_paginas_migradas_tem_h1_unico_sem_roteador_legado(self):
        # Exatamente 1 `<h1>`, nunca a classe `pca-titulo-pagina`
        # (roteador/foco legado, que não existe em nenhuma tela).
        for nome_rota in ("pca:tabela", "pca:calendario", "pca:resumo_uo"):
            with self.subTest(rota=nome_rota):
                resposta = self.client.get(reverse(nome_rota))
                conteudo = resposta.content.decode("utf-8")
                self.assertEqual(conteudo.count("<h1"), 1)
                self.assertNotIn("pca-titulo-pagina", conteudo)
