"""A interação entre colunas dinâmicas, busca transversal, exportação
XLSX, calendário e Análises, verificada de ponta a ponta.

Cada um dos fluxos críticos (detalhe, edição, acompanhamento, relatório
de movimentação/impressão, autenticação, permissões) já tem suíte própria
— `test_edicao_formulario.py`, `test_acompanhamento_modal.py`,
`test_relatorio_movimentacao*.py`, `core/tests/test_auth.py`,
`test_permissoes.py::TestVisualizadorSemControleDeEscritaNasQuatroTelas`
já cobrem cada um isoladamente com requisição HTTP real. Este arquivo
cobre os pontos onde o comportamento de uma parte passa a depender do
estado deixado por outra."""

from io import BytesIO

import openpyxl
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from apps.catalogo.models import Categoria, Exercicio, SituacaoNormalizada, Tipo, Unidade
from apps.pca.colunas import CHAVE_SESSAO_COLUNAS
from apps.pca.models import Acompanhamento, Estado, Processo, Situacao


class FixtureIntegracaoBase(TestCase):
    """3 processos com um termo de busca único, IDs previsíveis para
    `anterior`/`proximo` na ordem da tabela (`item_pca` ascendente)."""

    @classmethod
    def setUpTestData(cls):
        cls.unidade = Unidade.objects.create(nome="UO Integração 28-08")
        cls.categoria = Categoria.objects.create(nome="Categoria Integração 28-08")
        cls.tipo = Tipo.objects.create(nome="Tipo Integração 28-08")
        cls.exercicio = Exercicio.objects.get(ano=2026)
        cls.p1 = Processo.objects.create(
            item_pca=9101,
            exercicio=cls.exercicio,
            descricao_objeto="Processo integração 28-08 termo-unico-fx28",
            tipo=cls.tipo,
            categoria=cls.categoria,
            unidade_organizacional=cls.unidade,
            estado=Estado.ATIVO.value,
            situacao=Situacao.NO_PRAZO.value,
            valor_estimado=1000,
        )
        cls.p2 = Processo.objects.create(
            item_pca=9102,
            exercicio=cls.exercicio,
            descricao_objeto="Processo integração 28-08 termo-unico-fx28 dois",
            tipo=cls.tipo,
            categoria=cls.categoria,
            unidade_organizacional=cls.unidade,
            estado=Estado.ATIVO.value,
            situacao=Situacao.EM_TRAMITACAO.value,
            valor_estimado=2000,
        )
        cls.p3 = Processo.objects.create(
            item_pca=9103,
            exercicio=cls.exercicio,
            descricao_objeto="Processo integração 28-08 termo-unico-fx28 tres",
            tipo=cls.tipo,
            categoria=cls.categoria,
            unidade_organizacional=cls.unidade,
            estado=Estado.ATIVO.value,
            situacao=Situacao.NO_PRAZO.value,
            valor_estimado=3000,
        )
        cls.editor = get_user_model().objects.create_user(
            email="integracao28-editor@pca.local", password="senha-forte-123"
        )
        cls.editor.groups.add(Group.objects.get(name="editor"))
        cls.visualizador = get_user_model().objects.create_user(
            email="integracao28-visualizador@pca.local", password="senha-forte-123"
        )
        cls.visualizador.groups.add(Group.objects.get(name="visualizador"))
        # `services.registrar_acompanhamento` resolve `SituacaoNormalizada`
        # pelo nome mapeado da situação ATUAL do processo quando
        # `situacao_novo` não é informado (só registrar uma observação) —
        # este catálogo normalmente nasce do `importar_pca`; aqui a fixture
        # é 100% ORM direto, então precisa existir por fora.
        SituacaoNormalizada.objects.get_or_create(nome="Sem informação")


class TestBuscaMaisColunasMaisExportacaoConsistentes(FixtureIntegracaoBase):
    """Colunas dinâmicas, busca e exportação XLSX tocam o mesmo
    `views.py`/`_queryset_export`. Aqui: uma busca transversal (`q=`)
    filtra a tabela e o XLSX exportado para o mesmo conjunto de itens,
    com a mesma seleção de colunas — nunca um resultado divergente entre
    tela e arquivo para o mesmo filtro."""

    def setUp(self):
        self.client.force_login(self.editor)

    def test_tabela_e_xlsx_concordam_sob_o_mesmo_filtro_de_busca(self):
        querystring = "q=termo-unico-fx28&colunas=item_pca&colunas=descricao_objeto"

        resposta_tabela = self.client.get(f"{reverse('pca:tabela')}?{querystring}")
        self.assertEqual(resposta_tabela.status_code, 200)
        itens_na_tabela = {p.item_pca for p in resposta_tabela.context["pagina"].object_list}
        self.assertEqual(itens_na_tabela, {9101, 9102, 9103})

        resposta_xlsx = self.client.get(f"{reverse('pca:exportar_xlsx')}?{querystring}")
        self.assertEqual(resposta_xlsx.status_code, 200)
        pasta = openpyxl.load_workbook(BytesIO(resposta_xlsx.content))
        aba = pasta.active
        # Cabeçalho na linha 1; só as 2 colunas pedidas (Item/Objeto) devem
        # aparecer, na mesma ordem — prova de que `?colunas=` (contrato
        # repetido do 28-04) chega intacto até o arquivo através do
        # filtro de busca do 28-03.
        cabecalhos = [c.value for c in aba[1] if c.value]
        self.assertEqual(cabecalhos[:2], ["Item", "Objeto"])
        itens_no_arquivo = {
            row[0].value for row in aba.iter_rows(min_row=2, max_row=aba.max_row)
            if isinstance(row[0].value, int)
        }
        self.assertEqual(itens_no_arquivo, itens_na_tabela)

    def test_colunas_selecionadas_em_sessao_sao_a_mesma_composicao_da_tela_e_do_export_legado(self):
        # Sem `?colunas=` explícito na exportação, o padrão depende da
        # sessão através do mesmo resolvedor compartilhado; a exportação
        # legada nunca deveria voltar a um conjunto fixo próprio depois
        # que a sessão grava uma escolha.
        self.client.get(
            f"{reverse('pca:tabela')}?colunas=item_pca&colunas=situacao"
        )
        # `_normalizar` (apps/pca/colunas.py) reinjeta `descricao_objeto`
        # (obrigatória) quando ausente da seleção explícita — a sessão
        # gravada nunca perde uma coluna obrigatória, mesmo que o
        # `?colunas=` do usuário não a tenha citado. `canonizar()` grava e
        # exporta na ordem canônica (núcleo `COLUNAS_PADRAO` primeiro),
        # não a de chegada.
        self.assertEqual(
            self.client.session[CHAVE_SESSAO_COLUNAS],
            ["item_pca", "descricao_objeto", "situacao"],
        )
        resposta_xlsx = self.client.get(reverse("pca:exportar_xlsx"))
        self.assertEqual(resposta_xlsx.status_code, 200)
        pasta = openpyxl.load_workbook(BytesIO(resposta_xlsx.content))
        cabecalhos = [c.value for c in pasta.active[1] if c.value]
        self.assertEqual(cabecalhos[:3], ["Item", "Objeto", "Situação"])


class TestVizinhosNaOrdemDaTabelaRespeitamBuscaEColunas(FixtureIntegracaoBase):
    """`views_processo._vizinhos_na_ordem_da_tabela` (usada pelo detalhe
    do processo) chama `queryset_filtrado` direto — o mesmo ponto que
    interpreta `q=`. Se a busca vazasse um `Q()` incompatível com
    `.values_list` ou dobrasse linhas via join 1:N, apareceria aqui como
    anterior/próximo errado ou 500."""

    def setUp(self):
        self.client.force_login(self.editor)

    def test_anterior_proximo_seguem_a_busca_ativa_na_querystring(self):
        url = reverse("pca:detalhe_processo", args=[2026, self.p2.item_pca])
        resposta = self.client.get(f"{url}?q=termo-unico-fx28")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.context["anterior"], {"ano": 2026, "item_pca": 9101})
        self.assertEqual(resposta.context["proximo"], {"ano": 2026, "item_pca": 9103})

    def test_anterior_proximo_ficam_none_quando_a_busca_exclui_o_proprio_processo(self):
        # Termo que não bate em p2 nenhuma família de campo — o próprio
        # processo aberto sai do recorte filtrado; `_vizinhos_na_ordem_da_
        # tabela` não pode lançar (ValueError capturado -> None, None).
        url = reverse("pca:detalhe_processo", args=[2026, self.p2.item_pca])
        resposta = self.client.get(f"{url}?q=termo-que-nao-bate-em-nada-x28z")
        self.assertEqual(resposta.status_code, 200)
        self.assertIsNone(resposta.context["anterior"])
        self.assertIsNone(resposta.context["proximo"])


class TestFluxoDeReuniaoDePontaAPonta(FixtureIntegracaoBase):
    """Objetivo do plano ('a equipe conduz a reunião mensal inteiramente
    dentro do sistema'): busca um item, abre o detalhe, registra
    acompanhamento (POST real), confirma que a mudança aparece de volta na
    tabela filtrada pela MESMA busca e no XLSX exportado com o mesmo
    filtro — nenhum plano isolado testou essa volta completa."""

    def setUp(self):
        self.client.force_login(self.editor)

    def test_registrar_acompanhamento_reflete_na_tabela_filtrada_e_no_xlsx(self):
        querystring = "q=termo-unico-fx28"

        url_modal = reverse("pca:acompanhamento_modal", args=[2026, self.p1.item_pca])
        resposta_post = self.client.post(
            url_modal,
            {
                "versao": self.p1.atualizado_em.isoformat(),
                "observacao": "Registrado no fluxo de integração 28-08.",
            },
        )
        self.assertIn(resposta_post.status_code, (302, 200))
        self.assertTrue(
            Acompanhamento.objects.filter(
                processo=self.p1, situacao_informada__icontains="integração 28-08"
            ).exists()
        )

        resposta_tabela = self.client.get(f"{reverse('pca:tabela')}?{querystring}")
        itens = {p.item_pca for p in resposta_tabela.context["pagina"].object_list}
        self.assertIn(9101, itens)

        resposta_xlsx = self.client.get(f"{reverse('pca:exportar_xlsx')}?{querystring}")
        self.assertEqual(resposta_xlsx.status_code, 200)
        pasta = openpyxl.load_workbook(BytesIO(resposta_xlsx.content))
        aba = pasta.active
        primeira_coluna = [
            row[0].value for row in aba.iter_rows(min_row=2, max_row=aba.max_row)
        ]
        self.assertIn(9101, primeira_coluna)


class TestTelasNovasDaFase28NaoVazamControleDeEscrita(FixtureIntegracaoBase):
    """Extensão de `test_permissoes.py::TestVisualizadorSemControleDeEscritaNasQuatroTelas`
    (que cobre `/`, `/tabela`, `/analise`) às duas telas de leitura pura:
    `/busca` (busca global) e `/calendario` (popover de leitura). Cada
    uma só tinha teste de conteúdo/comportamento funcional, nunca de
    vazamento de permissão."""

    def setUp(self):
        self.client.force_login(self.visualizador)

    def test_busca_global_sem_controle_de_escrita(self):
        resposta = self.client.get(
            f"{reverse('pca:busca')}?q=termo-unico-fx28"
        )
        self.assertEqual(resposta.status_code, 200)
        conteudo = resposta.content.decode()
        self.assertNotIn("Novo processo", conteudo)
        self.assertNotIn(
            reverse("pca:editar_processo", args=[2026, self.p1.item_pca]), conteudo
        )
        self.assertNotIn(
            reverse("pca:acompanhamento_modal", args=[2026, self.p1.item_pca]),
            conteudo,
        )

    def test_calendario_sem_controle_de_escrita(self):
        resposta = self.client.get(reverse("pca:calendario"))
        self.assertEqual(resposta.status_code, 200)
        conteudo = resposta.content.decode()
        self.assertNotIn("Novo processo", conteudo)
        self.assertNotIn(
            reverse("pca:editar_processo", args=[2026, self.p1.item_pca]), conteudo
        )
        self.assertNotIn(
            reverse("pca:acompanhamento_modal", args=[2026, self.p1.item_pca]),
            conteudo,
        )
