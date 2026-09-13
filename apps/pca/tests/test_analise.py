"""Tela "Análise": rota/view/template, agregação mensal por dimensão e
os três seletores + clique. Mesmo padrão de setUp de
`TestNavegacaoPreservaFiltro`/`TestDashboardGoldenNumbers`: import real em
`setUp()` (TransactionTestCase nunca chama `setUpTestData()`, e faz
`flush()` a cada teste), `serialized_rollback=True` para preservar o
usuário de serviço da migração de dados.
"""

import json
import re
from calendar import monthrange
from datetime import date
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, TransactionTestCase
from django.urls import reverse
from freezegun import freeze_time

from apps.catalogo.models import (
    Categoria,
    Exercicio,
    Tipo,
    Unidade,
)
from apps.pca.analise import (
    calcular_grafico_mensal,
    calcular_grafico_vencimento_contratos,
    calcular_proximos_vencimentos,
)
from apps.pca.graficos_pca import calcular_perfil_grupo, opcoes_perfil_grupo
from apps.pca.filtros import queryset_filtrado
from apps.pca.models import Acompanhamento, Estado, Processo, Situacao, TipoEvento

ARQUIVO_REAL = "apps/pca/fixtures/modelo-controle-exemplo.xlsx"


class AnaliseBase(TransactionTestCase):
    serialized_rollback = True

    def setUp(self):
        call_command(
            "importar_pca",
            ARQUIVO_REAL,
            "--usuario=importador@pca.local",
            "--exercicio=2026",
            stdout=StringIO(),
        )
        self.usuario = get_user_model().objects.create_user(
            email="analise@pca.local", password="x-forte-123"
        )
        self.client.force_login(self.usuario)


class TestRotaEAutenticacao(AnaliseBase):
    """Task 1 — contrato de rota/view: `reverse` resolve sem barra final,
    autenticado recebe 200 com o template certo, anônimo é redirecionado
    para o login (a nova view herda o `LoginRequiredMiddleware` global,
    AUTH-05, sem `@permission_required`/`@login_not_required` próprios)."""

    def test_reverse_resolve_para_analise_sem_barra_final(self):
        self.assertEqual(reverse("pca:analise"), "/analise")

    def test_autenticado_acessa_analise(self):
        resposta = self.client.get(reverse("pca:analise"))
        self.assertEqual(resposta.status_code, 200)
        self.assertTemplateUsed(resposta, "pca/analise.html")

    def test_anonimo_e_redirecionado_para_login(self):
        self.client.logout()
        resposta = self.client.get(reverse("pca:analise"))
        self.assertEqual(resposta.status_code, 302)
        self.assertIn("/login", resposta.url)

    def test_trilha_tem_pca_ano_e_analise(self):
        # `pca:analise` usa a casca da skill dsgov (`base.html`); `trilha`
        # é lista de tuplas `(rotulo, url)` (contrato de
        # `dsgov/_breadcrumb.html`).
        resposta = self.client.get(reverse("pca:analise"))
        trilha = resposta.context["trilha"]
        self.assertEqual(trilha[-1][0], "Análises")
        self.assertIsNone(trilha[-1][1])


class TestItemDeMenu(AnaliseBase):
    """O item "Análises" existe no menu lateral (`dsgov/_menu.html`,
    fonte `core/menu.py::itens()`, `reverse("pca:analise")`). A marcação
    de item ativo por rota corrente não existe no menu da skill —
    `dsgov/_menu.html` nunca compara `request.path`."""

    def test_item_analise_aparece_no_menu(self):
        resposta = self.client.get(reverse("pca:analise"))
        conteudo = resposta.content.decode("utf-8")
        self.assertIn('href="/analise"', conteudo)
        self.assertIn(">Análises<", conteudo)


class TestAnaliseRelatorio(AnaliseBase):
    """Análises é relatório puro: sem gráfico com seletor em JS, bloco
    de totais em `dl.dsgov-detalhe`, `br-table`s sem busca/paginação,
    rodapé "Gerado em"."""

    def test_pagina_tem_seis_graficos_com_role_e_aria_label(self):
        """Estado da página: situação, unidade, perfil (1), previsto×
        entregue, distribuição mensal, vencimento = 6 no total; Adiamentos
        não existe.

        Todos os pares seguem o mesmo contrato do partial canônico
        (`{"titulo", "grafico": {id/opcoes/resumo}, "tabela"}`)."""
        resposta = self.client.get(reverse("pca:analise"))
        conteudo = resposta.content.decode("utf-8")
        self.assertEqual(conteudo.count('role="img"'), 6)
        graficos = [
            resposta.context["grafico_situacao"]["grafico"],
            resposta.context["unidade_par"]["grafico"],
            resposta.context["perfil_par"]["grafico"],
            resposta.context["previsto_entregue_par"]["grafico"],
            resposta.context["mesdim_par"]["grafico"],
            resposta.context["vencimento_par"]["grafico"],
        ]
        self.assertEqual(len(graficos), 6)
        for grafico in graficos:
            self.assertTrue(grafico["resumo"])
            self.assertIn(f'data-grafico="{grafico["id"]}"', conteudo)

    def test_cada_grafico_tem_a_tabela_companheira_logo_abaixo_no_html(self):
        resposta = self.client.get(reverse("pca:analise"))
        conteudo = resposta.content.decode("utf-8")

        # Todos os pares usam o partial canônico
        # (`dsgov/_par_analitico.html`, caption com sr-only, gráfico e
        # tabela no mesmo br-card); ver
        # `test_par_analitico_situacao_grafico_e_tabela_no_mesmo_card`
        # para a prova completa do par de Situação.
        posicao_grafico_situacao = conteudo.index(
            'data-grafico="analise-grafico-situacao"'
        )
        posicao_tabela_situacao = conteudo.index(
            "Processos por situação — dados"
        )
        self.assertGreater(posicao_tabela_situacao, posicao_grafico_situacao)

        posicao_grafico_unidade = conteudo.index(
            'data-grafico="analise-grafico-unidade"'
        )
        posicao_tabela_unidade = conteudo.index("Processos por unidade — dados")
        self.assertGreater(posicao_tabela_unidade, posicao_grafico_unidade)

    def test_par_analitico_situacao_grafico_e_tabela_no_mesmo_card(self):
        """Critério literal 28-01.2: lado a lado em 992px (grid do
        partial); empilhado em 991px (mesmo grid, CSS — não testável por
        `django.test.Client`); tabela e gráfico com quantidades idênticas.
        Prova aqui: gráfico e tabela do par de Situação vivem dentro do
        MESMO `br-card` (uma única ocorrência de `br-card` até o próximo
        `data-grafico`, não duas `.row` separadas), e a soma dos valores
        do `json_script` do gráfico bate com `total_filtrado`."""
        resposta = self.client.get(reverse("pca:analise"))
        conteudo = resposta.content.decode("utf-8")

        # Só 1 <div class="br-card" antes do data-grafico de Situação, e
        # nenhum outro data-grafico entre ele e o fechamento da tabela —
        # prova de que gráfico+tabela estão no mesmo card, não em duas
        # `.row` distintas.
        posicao_card = conteudo.rindex(
            '<div class="br-card mb-4">',
            0,
            conteudo.index('data-grafico="analise-grafico-situacao"'),
        )
        posicao_tabela_situacao = conteudo.index(
            "Processos por situação — dados"
        )
        trecho = conteudo[posicao_card:posicao_tabela_situacao]
        self.assertNotIn("br-accordion", trecho, "tabela nunca recolhida")
        self.assertNotIn(
            'data-grafico="analise-grafico-unidade"',
            trecho,
            "gráfico de Unidade não deveria estar dentro do card de Situação",
        )

        opcoes_json = conteudo.split(
            'id="analise-grafico-situacao" type="application/json">'
        )[1].split("</script>")[0]
        opcoes = json.loads(opcoes_json)
        soma_grafico = sum(item["value"] for item in opcoes["series"][0]["data"])
        self.assertEqual(soma_grafico, resposta.context["total_filtrado"])

        tabela = resposta.context["grafico_situacao"]["tabela"]
        self.assertEqual(tabela["colunas"], ["Situação", "Quantidade", "Valor estimado", "%"])
        self.assertEqual(len(tabela["linhas"]), len(opcoes["series"][0]["data"]))

    def test_drilldown_dos_graficos_de_analise_bate_com_a_tabela(self):
        """Mesmo contrato do dashboard (`core.tests.
        test_inicio_dashboard`): a contagem da tabela filtrada bate com o
        valor de cada ponto com `url`."""
        resposta = self.client.get(reverse("pca:analise"))
        verificados = 0
        for chave in (
            "unidade_par",
            "mesdim_par",
            "vencimento_par",
            "previsto_entregue_par",
        ):
            grafico = resposta.context[chave]["grafico"]
            for serie in grafico["opcoes"]["series"]:
                for item in serie["data"]:
                    if not isinstance(item, dict):
                        continue
                    url = item.get("url")
                    valor = item.get("value")
                    if not url:
                        continue
                    resposta_tabela = self.client.get(url)
                    self.assertEqual(resposta_tabela.status_code, 200, msg=url)
                    contagem = resposta_tabela.context["pagina"].paginator.count
                    self.assertEqual(
                        contagem, valor, msg=f"{chave} — {url}"
                    )
                    verificados += 1

        # `grafico_situacao` é o "par" do partial canônico; o gráfico
        # propriamente dito mora em `grafico_situacao["grafico"]`, mesmo
        # contrato opcoes/id/resumo.
        grafico_situacao = resposta.context["grafico_situacao"]["grafico"]
        for serie in grafico_situacao["opcoes"]["series"]:
            for item in serie["data"]:
                if not isinstance(item, dict):
                    continue
                url = item.get("url")
                valor = item.get("value")
                if not url:
                    continue
                resposta_tabela = self.client.get(url)
                self.assertEqual(resposta_tabela.status_code, 200, msg=url)
                contagem = resposta_tabela.context["pagina"].paginator.count
                self.assertEqual(
                    contagem, valor, msg=f"grafico_situacao — {url}"
                )
                verificados += 1

        self.assertGreater(verificados, 0)

    def test_totais_do_bloco_de_analise_sao_links(self):
        resposta = self.client.get(reverse("pca:analise"))
        conteudo = resposta.content.decode("utf-8")
        bloco = conteudo.split('<dl class="dsgov-detalhe')[1].split("</dl>")[0]
        self.assertGreater(bloco.count("<dt>"), 0)
        self.assertEqual(bloco.count("<dt>"), bloco.count("<a href="))

    def test_bloco_de_totais_em_dl_dsgov_detalhe(self):
        resposta = self.client.get(reverse("pca:analise"))
        conteudo = resposta.content.decode("utf-8")
        self.assertIn('dl class="dsgov-detalhe', conteudo)

    def test_rodape_tem_gerado_em_imprimir_e_voltar(self):
        resposta = self.client.get(reverse("pca:analise"))
        conteudo = resposta.content.decode("utf-8")
        self.assertIn("Gerado em", conteudo)
        self.assertIn("window.print()", conteudo)
        self.assertIn(">Voltar<", conteudo)

    def test_form_get_de_dimensao_medida_preserva_exercicio(self):
        resposta = self.client.get(reverse("pca:analise"), {"exercicio": 2026})
        conteudo = resposta.content.decode("utf-8")
        self.assertIn('<form method="get"', conteudo)
        self.assertIn('name="exercicio" value="2026"', conteudo)

    def test_tabela_situacao_soma_bate_com_total_filtrado(self):
        """`grafico_situacao["tabela"]` (contrato `tabela_dados`,
        células já formatadas por `numero()`); soma da coluna Quantidade
        bate com `total_filtrado` (mesmo recorte MECE)."""
        resposta = self.client.get(reverse("pca:analise"))
        tabela = resposta.context["grafico_situacao"]["tabela"]
        total_tabela = sum(
            int(linha[1]["valor"].replace(".", "")) for linha in tabela["linhas"]
        )
        self.assertEqual(total_tabela, resposta.context["total_filtrado"])

    def test_cada_linha_da_tabela_situacao_linka_para_a_tabela_filtrada(self):
        from django.utils.html import escape

        resposta = self.client.get(reverse("pca:analise"))
        conteudo = resposta.content.decode("utf-8")
        for linha in resposta.context["grafico_situacao"]["tabela"]["linhas"]:
            url = linha[0]["url"]
            if not url:
                continue
            # `&` vira `&amp;` no HTML servido (autoescape do Django) — o
            # próprio navegador resolve de volta, mesmo padrão de qualquer
            # outro `href` com querystring composta neste projeto.
            esperado = escape(url)
            self.assertIn(esperado, conteudo)


class TestReordenacaoAnalisesERemocaoDeAdiamentos(AnaliseBase):
    """Nenhuma tabela companheira desnecessariamente distante; consulta
    de adiamentos não executa."""

    def test_ordem_das_secoes_segue_d_28_48(self):
        resposta = self.client.get(reverse("pca:analise"))
        conteudo = resposta.content.decode("utf-8")
        posicao_unidade = conteudo.index(">Processos por unidade<")
        posicao_perfil = conteudo.index(">Perfil do PCA<")
        posicao_vencimentos_proc = conteudo.index(
            ">Próximos vencimentos — prazos dos processos<"
        )
        posicao_previsto_entregue = conteudo.index(">Previsto × Entregue por mês<")
        posicao_distribuicao = conteudo.index(">Distribuição mensal por dimensão<")
        posicao_vencimento = conteudo.index(">Vencimentos por mês<")
        self.assertLess(posicao_unidade, posicao_perfil)
        self.assertLess(posicao_perfil, posicao_vencimentos_proc)
        self.assertLess(posicao_vencimentos_proc, posicao_previsto_entregue)
        self.assertLess(posicao_previsto_entregue, posicao_distribuicao)
        self.assertLess(posicao_distribuicao, posicao_vencimento)

    def test_adiamentos_nao_existe_mais_no_html(self):
        resposta = self.client.get(reverse("pca:analise"))
        conteudo = resposta.content.decode("utf-8")
        self.assertNotIn("Adiamentos", conteudo)

    def test_adiamentos_nao_existe_mais_no_contexto(self):
        resposta = self.client.get(reverse("pca:analise"))
        self.assertNotIn("grafico_adiamentos", resposta.context)
        self.assertNotIn("grafico_adiamentos_card", resposta.context)

    def test_consulta_de_adiamentos_nao_executa(self):
        """Nenhuma consulta de `/analise` traz a marca exclusiva de
        `calcular_grafico_adiamentos` (agora removida): `vezes_sobrestado`
        (subquery de `Acompanhamento` sobre "sobrestado") e
        `total_adiamentos` (`n_prorrogacoes + vezes_sobrestado`, filtro
        `__gt=0`). `n_prorrogacoes` sozinho NÃO é a marca — é annotation
        de base de `ProcessoQuerySet.para_listagem()`, presente em toda
        consulta desta página (usada pelo KPI "Processos sobrestados")."""
        from django.db import connection, reset_queries
        from django.test import override_settings

        with override_settings(DEBUG=True):
            reset_queries()
            self.client.get(reverse("pca:analise"))
            queries_sql = [q["sql"] for q in connection.queries]

        for sql in queries_sql:
            self.assertNotIn("vezes_sobrestado", sql)
            self.assertNotIn("total_adiamentos", sql)

    def test_calcular_grafico_adiamentos_nao_existe_mais(self):
        import apps.pca.analise as modulo_analise

        self.assertFalse(hasattr(modulo_analise, "calcular_grafico_adiamentos"))

    def test_opcoes_e_resumo_adiamentos_nao_existem_mais(self):
        import apps.pca.graficos_pca as modulo_graficos

        self.assertFalse(hasattr(modulo_graficos, "opcoes_adiamentos"))
        self.assertFalse(hasattr(modulo_graficos, "resumo_adiamentos"))

    def test_unidade_e_previsto_entregue_e_vencimento_usam_par_analitico(self):
        """Todos os pares de Análises usam o partial canônico (mesmo
        contrato titulo/grafico/tabela) — nenhuma tabela companheira
        desnecessariamente distante do gráfico."""
        resposta = self.client.get(reverse("pca:analise"))
        for chave in ("unidade_par", "previsto_entregue_par", "mesdim_par", "vencimento_par"):
            par = resposta.context[chave]
            self.assertIn("titulo", par)
            self.assertIn("grafico", par)
            self.assertIn("tabela", par)
            self.assertIn("colunas", par["tabela"])
            self.assertIn("linhas", par["tabela"])


class TestPerfilDimensaoSelecionavel(AnaliseBase):
    """Perfil do PCA é 1 único componente com `?perfil_dimensao=`,
    separado de `?dimensao=` (distribuição mensal): uma instância de
    gráfico de perfil; mudança atualiza tabela e gráfico juntos; 'Outros'
    fecha a soma."""

    def test_sem_perfil_dimensao_mostra_categoria_por_padrao(self):
        resposta = self.client.get(reverse("pca:analise"))
        self.assertEqual(resposta.context["perfil_dimensao_selecionada"], "categoria")
        self.assertEqual(resposta.context["perfil_par"]["chave"], "categoria")
        self.assertEqual(resposta.context["perfil_par"]["titulo"], "Categoria")

    def test_perfil_dimensao_invalida_cai_no_padrao_categoria_sem_erro_500(self):
        resposta = self.client.get(reverse("pca:analise"), {"perfil_dimensao": "lixo"})
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.context["perfil_dimensao_selecionada"], "categoria")

    def test_trocar_perfil_dimensao_nao_aumenta_o_numero_de_consultas_da_pagina(self):
        """Orçamento de consultas — trocar `perfil_dimensao` não soma a
        query de uma 2ª dimensão: o total de consultas da página com
        `perfil_dimensao=categoria` é igual ao total com
        `perfil_dimensao=tipo` (mesma forma, dimensão diferente)."""
        from django.db import connection, reset_queries
        from django.test import override_settings

        with override_settings(DEBUG=True):
            reset_queries()
            self.client.get(reverse("pca:analise"), {"perfil_dimensao": "categoria"})
            total_categoria = len(connection.queries)

            reset_queries()
            self.client.get(reverse("pca:analise"), {"perfil_dimensao": "tipo"})
            total_tipo = len(connection.queries)

        self.assertEqual(total_categoria, total_tipo)

    def test_perfil_dimensao_tipo_usa_valor_estimado_como_medida(self):
        """"Orçamento por tipo": medida = Valor estimado (soma), não
        contagem; o total central do anel (`graphic`) usa `moeda()`
        (formato "R$")."""
        resposta = self.client.get(reverse("pca:analise"), {"perfil_dimensao": "tipo"})
        self.assertEqual(resposta.context["perfil_par"]["titulo"], "Orçamento por tipo")
        opcoes = resposta.context["perfil_par"]["grafico"]["opcoes"]
        texto_central = opcoes["graphic"][0]["style"]["text"]
        self.assertIn("R$", texto_central)

        linhas = resposta.context["perfil_par"]["linhas"]
        soma_valor_estimado = sum(linha["soma"] for linha in linhas)
        soma_fatias = sum(item["value"] for item in opcoes["series"][0]["data"])
        self.assertAlmostEqual(soma_fatias, float(soma_valor_estimado), places=2)

    def test_mais_de_seis_categorias_vira_cinco_mais_outros_e_tabela_bate(self):
        """> 6 categorias vira 5 + "Outros"; a tabela representa
        exatamente essas mesmas fatias (soma das 6 linhas bate com o
        total geral). Testa a primeira das 5 dimensões do Perfil que, no
        recorte real, tiver mais de 6 valores distintos — não depende de
        qual dimensão específica é (a regra é a mesma nas 5)."""
        qs, get = self._qs_e_get()
        dimensao_com_mais_de_seis = None
        for chave in ("categoria", "prioridade", "classificacao", "modalidade", "tipo"):
            grupo_bruto = calcular_perfil_grupo(qs, get, chave)
            if len(grupo_bruto["linhas"]) > 6:
                dimensao_com_mais_de_seis = chave
                break
        if dimensao_com_mais_de_seis is None:
            self.skipTest(
                "fixture real não tem nenhuma dimensão do Perfil com mais "
                "de 6 valores distintos no recorte"
            )
        resposta = self.client.get(
            reverse("pca:analise"), {"perfil_dimensao": dimensao_com_mais_de_seis}
        )
        opcoes = resposta.context["perfil_par"]["grafico"]["opcoes"]
        fatias = opcoes["series"][0]["data"]
        self.assertEqual(len(fatias), 6)
        self.assertEqual(fatias[-1]["name"], "Outros")

        tabela = resposta.context["perfil_par"]["tabela"]
        self.assertEqual(len(tabela["linhas"]), 6)
        self.assertEqual(tabela["linhas"][-1][0]["valor"], "Outros")
        total_geral = sum(linha["total"] for linha in grupo_bruto["linhas"])
        soma_fatias = sum(item["value"] for item in fatias)
        self.assertEqual(soma_fatias, total_geral)

    def _qs_e_get(self, **params):
        request = RequestFactory().get("/analise", params)
        request.user = self.usuario
        qs = queryset_filtrado(request)
        return qs, request.GET

    def test_form_perfil_dimensao_no_html_com_exercicio_hidden(self):
        resposta = self.client.get(reverse("pca:analise"), {"exercicio": 2026})
        conteudo = resposta.content.decode("utf-8")
        self.assertIn("perfil_dimensao", conteudo)
        self.assertIn('name="exercicio" value="2026"', conteudo)


class TestCalcularGraficoMensal(AnaliseBase):
    """`apps.pca.analise.calcular_grafico_mensal`: agregação ORM por
    mês × dimensão × medida, para as 7 dimensões conhecidas pelo painel
    de filtros."""

    def _qs_e_get(self, **params):
        request = RequestFactory().get("/analise", params)
        request.user = self.usuario
        qs = queryset_filtrado(request)
        return qs, request.GET

    def test_devolve_exatamente_as_sete_chaves_de_dimensao(self):
        qs, get = self._qs_e_get()
        resultado = calcular_grafico_mensal(qs, get)
        self.assertEqual(
            set(resultado.keys()),
            {
                "uo",
                "modalidade",
                "categoria",
                "prioridade",
                "tipo",
                "estado",
                "situacao",
            },
        )

    def test_serie_de_uo_tem_doze_pontos_com_os_campos_esperados(self):
        qs, get = self._qs_e_get()
        resultado = calcular_grafico_mensal(qs, get)
        self.assertGreater(len(resultado["uo"]), 0)
        for serie in resultado["uo"]:
            self.assertIn("nome", serie)
            self.assertEqual(len(serie["pontos"]), 12)
            meses = [ponto["mes"] for ponto in serie["pontos"]]
            self.assertEqual(meses, list(range(1, 13)))
            for ponto in serie["pontos"]:
                self.assertIsInstance(ponto["quantidade"], int)
                # Nunca float: string decimal, mesmo contrato de
                # `calcular_resumo_uo`/exportação.
                self.assertIsInstance(ponto["valor_previsto"], str)
                self.assertIsInstance(ponto["valor_contratado"], str)
                self.assertIn("mes=", ponto["querystring"])
                self.assertIn("uo=", ponto["querystring"])

    def test_soma_de_quantidade_mais_sem_mes_bate_com_o_total_do_queryset(self):
        qs, get = self._qs_e_get()
        resultado = calcular_grafico_mensal(qs, get)
        total_qs = qs.count()
        processos_sem_mes = qs.filter(mes_previsto__isnull=True).count()
        for dimensao, series in resultado.items():
            with self.subTest(dimensao=dimensao):
                soma = sum(
                    ponto["quantidade"]
                    for serie in series
                    for ponto in serie["pontos"]
                )
                self.assertEqual(soma + processos_sem_mes, total_qs)

    def test_querystring_de_um_ponto_da_dimensao_uo_bate_com_a_tabela(self):
        qs, get = self._qs_e_get()
        resultado = calcular_grafico_mensal(qs, get)
        candidato = None
        for serie in resultado["uo"]:
            for ponto in serie["pontos"]:
                if ponto["quantidade"] > 0:
                    candidato = ponto
                    break
            if candidato:
                break
        self.assertIsNotNone(candidato, "esperado ao menos 1 ponto não-zero")
        resposta = self.client.get(
            f"{reverse('pca:tabela')}?{candidato['querystring']}"
        )
        pagina = resposta.context["pagina"]
        self.assertEqual(pagina.paginator.count, candidato["quantidade"])

    def test_querystring_de_um_ponto_da_dimensao_estado_bate_com_a_tabela(self):
        qs, get = self._qs_e_get()
        resultado = calcular_grafico_mensal(qs, get)
        candidato = None
        for serie in resultado["estado"]:
            for ponto in serie["pontos"]:
                if ponto["quantidade"] > 0:
                    candidato = ponto
                    break
            if candidato:
                break
        self.assertIsNotNone(candidato, "esperado ao menos 1 ponto não-zero")
        resposta = self.client.get(
            f"{reverse('pca:tabela')}?{candidato['querystring']}"
        )
        pagina = resposta.context["pagina"]
        self.assertEqual(pagina.paginator.count, candidato["quantidade"])

    def test_numero_de_queries_e_fixo_por_dimensao(self):
        qs, get = self._qs_e_get()
        # 1 `.values().annotate()` por dimensão — 7 dimensões, 7 queries
        # fixas, nunca escalando com o total de processos (mesmo
        # orçamento de `calcular_resumo_uo`/`calcular_blocos_kpi`).
        with self.assertNumQueries(7):
            calcular_grafico_mensal(qs, get)

    def test_soma_dos_querystrings_do_grafico_mensal_bate_com_total_filtrado_da_tabela(
        self,
    ):
        # A soma das contagens obtidas seguindo a querystring de cada
        # ponto não-zero da dimensão "estado" (via /tabela, o mesmo
        # destino que o clique no gráfico usa) mais os processos sem mês
        # bate exatamente com `total_filtrado` da tela — nenhuma
        # tolerância. `pca:analise` não expõe o dict das 7 dimensões
        # inteiro no contexto (só a dimensão selecionada, já serializada
        # para a tabela); `calcular_grafico_mensal` continua testável
        # direto (`self._qs_e_get()`).
        resposta = self.client.get(reverse("pca:analise"))
        total_filtrado = resposta.context["total_filtrado"]
        qs, get = self._qs_e_get()
        grafico_mensal = calcular_grafico_mensal(qs, get)
        processos_sem_mes = qs.filter(mes_previsto__isnull=True).count()

        soma_via_drilldown = 0
        for serie in grafico_mensal["estado"]:
            for ponto in serie["pontos"]:
                if ponto["quantidade"] == 0:
                    continue
                resposta_tabela = self.client.get(
                    f"{reverse('pca:tabela')}?{ponto['querystring']}"
                )
                soma_via_drilldown += resposta_tabela.context[
                    "pagina"
                ].paginator.count

        self.assertEqual(soma_via_drilldown + processos_sem_mes, total_filtrado)


class AnaliseFixtureBase(AnaliseBase):
    """Base comum de fixture controlada — números conhecidos, não a
    planilha real. `ARQUIVO_REAL` (importado pelo `setUp` de
    `AnaliseBase`) só entra para confirmar que a base real não tem
    `SituacaoNormalizada` "sobrestado"; os processos/acompanhamentos de
    cada teste são fabricados direto via ORM, sobre o mesmo exercício
    2026 da planilha real."""

    def setUp(self):
        super().setUp()
        self.exercicio = Exercicio.objects.get(ano=2026)
        self.tipo = Tipo.objects.first()
        self.categoria = Categoria.objects.first()
        self.unidade = Unidade.objects.first()

    def _qs_e_get(self, **params):
        request = RequestFactory().get("/analise", params)
        request.user = self.usuario
        qs = queryset_filtrado(request)
        return qs, request.GET

    def _processo(self, item_pca, **kwargs):
        defaults = {
            "descricao_objeto": f"Fixture 24-06 {item_pca}",
            "tipo": self.tipo,
            "categoria": self.categoria,
            "unidade_organizacional": self.unidade,
        }
        defaults.update(kwargs)
        return Processo.objects.create(
            item_pca=item_pca, exercicio=self.exercicio, **defaults
        )

    def _acompanhamento(self, processo, situacao, **kwargs):
        defaults = {
            "referencia_data": date(2026, 1, 1),
            "tipo_evento": TipoEvento.REUNIAO_ACOMPANHAMENTO,
            "origem_hash": f"hash-24-06-{Acompanhamento.objects.count()}",
        }
        defaults.update(kwargs)
        return Acompanhamento.objects.create(
            processo=processo, situacao=situacao, **defaults
        )


class TestPerfilGrupoMaisDeSeisValoresFixture(AnaliseFixtureBase):
    """Fixture determinística (8 categorias sintéticas, 1 processo
    cada) para o cenário "> 6 categorias": a planilha real (ver
    `TestPerfilDimensaoSelecionavel.test_mais_de_seis_categorias_...`) não
    garante essa composição em nenhuma das 5 dimensões, então este teste
    não depende dela."""

    def test_mais_de_seis_valores_vira_cinco_mais_outros_com_soma_intacta(self):
        for indice in range(8):
            categoria = Categoria.objects.create(
                nome=f"Categoria sintética 28-06-{indice}"
            )
            self._processo(900 + indice, categoria=categoria)
        qs, get = self._qs_e_get()
        qs = qs.filter(item_pca__in=range(900, 908))
        grupo = calcular_perfil_grupo(qs, get, "categoria")
        self.assertEqual(len(grupo["linhas"]), 8)

        opcoes = opcoes_perfil_grupo(grupo)
        fatias = opcoes["series"][0]["data"]
        self.assertEqual(len(fatias), 6)
        self.assertEqual(fatias[-1]["name"], "Outros")
        total_geral = sum(linha["total"] for linha in grupo["linhas"])
        soma_fatias = sum(item["value"] for item in fatias)
        self.assertEqual(soma_fatias, total_geral)

        from apps.pca.graficos_pca import tabela_perfil_grupo

        tabela = tabela_perfil_grupo(grupo)
        self.assertEqual(len(tabela["linhas"]), 6)
        self.assertEqual(tabela["linhas"][-1][0]["valor"], "Outros")


class TestCalcularGraficoVencimentoContratos(AnaliseFixtureBase):
    """`calcular_grafico_vencimento_contratos`: 12 meses a partir do mês
    corrente (âncora `localdate()`, congelada via `freeze_time` para o
    teste ser determinístico), só `Estado.ATIVO` com `tipo` "vigente". A
    base real (`ARQUIVO_REAL`) já tem vigentes ativos com `vigencia_fim`
    real espalhados pelos próximos anos — os testes comparam a contagem
    antes/depois de cada fixture (delta), nunca um número absoluto."""

    def _tipo_vigente(self):
        return Tipo.objects.get(nome_normalizado="vigente")

    def _pontos_por_mes(self, resultado):
        return {(p["ano"], p["mes"]): p["quantidade"] for p in resultado["pontos"]}

    @freeze_time("2026-09-15")
    def test_doze_pontos_a_partir_do_mes_corrente_e_contagem_por_delta(self):
        tipo_vigente = self._tipo_vigente()
        qs, get = self._qs_e_get()
        antes = calcular_grafico_vencimento_contratos(qs, get)
        pontos_antes = self._pontos_por_mes(antes)

        self.assertEqual(len(antes["pontos"]), 12)
        self.assertEqual(antes["pontos"][0]["ano"], 2026)
        self.assertEqual(antes["pontos"][0]["mes"], 9)
        self.assertEqual(antes["pontos"][-1]["ano"], 2027)
        self.assertEqual(antes["pontos"][-1]["mes"], 8)

        # dentro da janela (set/2026 é o mês corrente)
        self._processo(
            977, tipo=tipo_vigente, estado=Estado.ATIVO,
            vigencia_fim=date(2026, 9, 30),
        )
        # 3 meses à frente (dez/2026), ainda dentro da janela de 12 meses
        self._processo(
            978, tipo=tipo_vigente, estado=Estado.ATIVO,
            vigencia_fim=date(2026, 12, 1),
        )
        # fora da janela (13 meses à frente)
        self._processo(
            979, tipo=tipo_vigente, estado=Estado.ATIVO,
            vigencia_fim=date(2027, 10, 1),
        )
        # não conta: não é "vigente" (tipo diferente)
        self._processo(980, estado=Estado.ATIVO, vigencia_fim=date(2026, 9, 30))
        # não conta: vigente mas CANCELADO
        self._processo(
            981, tipo=tipo_vigente, estado=Estado.CANCELADO,
            vigencia_fim=date(2026, 9, 30),
        )

        qs, get = self._qs_e_get()
        depois = calcular_grafico_vencimento_contratos(qs, get)
        pontos_depois = self._pontos_por_mes(depois)

        self.assertEqual(pontos_depois[(2026, 9)] - pontos_antes[(2026, 9)], 1)
        self.assertEqual(pontos_depois[(2026, 12)] - pontos_antes[(2026, 12)], 1)

        total_antes = sum(pontos_antes.values())
        total_depois = sum(pontos_depois.values())
        # só 977 e 978 entram na janela — 979 (fora), 980 (tipo errado) e
        # 981 (cancelado) nunca contam.
        self.assertEqual(total_depois - total_antes, 2)

    @freeze_time("2026-09-15")
    def test_sem_vigencia_fim_conta_a_parte_e_nunca_num_ponto(self):
        tipo_vigente = self._tipo_vigente()
        qs, get = self._qs_e_get()
        antes = calcular_grafico_vencimento_contratos(qs, get)

        self._processo(
            982, tipo=tipo_vigente, estado=Estado.ATIVO, vigencia_fim=None
        )

        qs, get = self._qs_e_get()
        depois = calcular_grafico_vencimento_contratos(qs, get)
        self.assertEqual(depois["sem_vigencia_fim"] - antes["sem_vigencia_fim"], 1)
        total_antes = sum(p["quantidade"] for p in antes["pontos"])
        total_depois = sum(p["quantidade"] for p in depois["pontos"])
        self.assertEqual(total_depois, total_antes)

    @freeze_time("2026-09-15")
    def test_querystring_do_ponto_bate_com_a_contagem_de_tabela(self):
        """Prova de coerência: o clique num ponto do gráfico leva a
        `/tabela` com a mesma contagem — a querystring do ponto precisa
        escopar por tipo/estado (não só por `vigencia_fim`), senão a
        planilha real (que já tem vigentes ativos com vencimento
        cadastrado) faria o número da tabela divergir do ponto.

        `force_login` em `setUp()` roda em tempo real, então a sessão
        expira em `SESSION_COOKIE_AGE` (8h) a partir de hoje — sob
        `@freeze_time("2026-09-15")`, "agora" pula 10 dias
        para a frente e a sessão já nasce expirada, fazendo `/tabela`
        devolver 302 (login) em vez de 200. Re-logar AQUI, já dentro do
        tempo congelado, corrige sem mudar `SESSION_COOKIE_AGE`."""
        self.client.force_login(self.usuario)
        tipo_vigente = self._tipo_vigente()
        self._processo(
            983, tipo=tipo_vigente, estado=Estado.ATIVO,
            vigencia_fim=date(2026, 9, 20),
        )
        qs, get = self._qs_e_get()
        resultado = calcular_grafico_vencimento_contratos(qs, get)
        ponto = resultado["pontos"][0]
        resposta = self.client.get(
            f"{reverse('pca:tabela')}?{ponto['querystring']}"
        )
        pagina = resposta.context["pagina"]
        self.assertEqual(pagina.paginator.count, ponto["quantidade"])

    @freeze_time("2026-09-15")
    def test_soma_dos_pontos_via_drilldown_bate_com_total_independente_do_periodo(
        self,
    ):
        # Os 12 meses são mutuamente exclusivos (cada ponto filtra por
        # `vigencia_fim_de`/`vigencia_fim_ate` do próprio mês), então a
        # soma das contagens obtidas seguindo a querystring de cada ponto
        # (via /tabela, o mesmo destino que o clique na barra usa)
        # precisa bater exatamente com uma contagem independente (ORM
        # direto, sem passar por `calcular_grafico_vencimento_contratos`)
        # do mesmo universo (tipo vigente, estado ativo, vigência fim
        # dentro da janela inteira de 12 meses) — nenhuma tolerância.
        self.client.force_login(self.usuario)
        tipo_vigente = self._tipo_vigente()
        self._processo(
            984, tipo=tipo_vigente, estado=Estado.ATIVO,
            vigencia_fim=date(2026, 10, 5),
        )
        self._processo(
            985, tipo=tipo_vigente, estado=Estado.ATIVO,
            vigencia_fim=date(2027, 2, 12),
        )
        qs, get = self._qs_e_get()
        resultado = calcular_grafico_vencimento_contratos(qs, get)

        soma_via_drilldown = 0
        for ponto in resultado["pontos"]:
            if ponto["quantidade"] == 0:
                continue
            resposta = self.client.get(
                f"{reverse('pca:tabela')}?{ponto['querystring']}"
            )
            soma_via_drilldown += resposta.context["pagina"].paginator.count

        primeiro, ultimo = resultado["pontos"][0], resultado["pontos"][-1]
        inicio = date(primeiro["ano"], primeiro["mes"], 1)
        fim = date(
            ultimo["ano"], ultimo["mes"], monthrange(ultimo["ano"], ultimo["mes"])[1]
        )
        total_independente = Processo.objects.filter(
            estado=Estado.ATIVO,
            tipo=tipo_vigente,
            vigencia_fim__gte=inicio,
            vigencia_fim__lte=fim,
        ).count()

        self.assertEqual(
            soma_via_drilldown, sum(p["quantidade"] for p in resultado["pontos"])
        )
        self.assertEqual(soma_via_drilldown, total_independente)


@freeze_time("2026-09-15")
class TestProximosVencimentos(AnaliseFixtureBase):
    """`calcular_proximos_vencimentos` mede a mesma condição de
    proximidade do KPI (`apps.pca.kpis.condicao_proximo_do_prazo`), sem
    janela de dias. `freeze_time` fixa "hoje" em 2026-09-15 —
    determinístico independente da data real de execução da suíte."""

    def setUp(self):
        super().setUp()
        self.tipo = Tipo.objects.get(nome_normalizado="nova contratacao")
        self.tipo_vigente = Tipo.objects.get(nome_normalizado="vigente")

    def test_vence_hoje_e_em_n_dias(self):
        hoje = self._processo(970, estado=Estado.ATIVO, situacao=Situacao.NO_PRAZO, prazo_entrega=date(2026, 9, 15))
        daqui_a_cinco = self._processo(971, estado=Estado.ATIVO, situacao=Situacao.NO_PRAZO, prazo_entrega=date(2026, 9, 20))
        qs, get = self._qs_e_get()
        processos, _total, _vencidos, _url = calcular_proximos_vencimentos(qs, get)
        rotulos = {p.item_pca: p for p in processos}
        self.assertIn(hoje.item_pca, rotulos)
        self.assertIn(daqui_a_cinco.item_pca, rotulos)
        dias_hoje = (rotulos[hoje.item_pca].prazo_efetivo - date(2026, 9, 15)).days
        dias_cinco = (rotulos[daqui_a_cinco.item_pca].prazo_efetivo - date(2026, 9, 15)).days
        self.assertEqual(dias_hoje, 0)
        self.assertEqual(dias_cinco, 5)

    def test_vencido_fica_fora_das_10_primeiras_mas_conta_no_total_vencidos(self):
        vencido = self._processo(
            972, estado=Estado.ATIVO, situacao=Situacao.NO_PRAZO,
            prazo_entrega=date(2026, 9, 1),
        )
        # Neutraliza a promessa vigente do item 65 (base real) para não
        # interferir na contagem: usa só as fixtures deste teste.
        futuro = self._processo(
            973, estado=Estado.ATIVO, situacao=Situacao.NO_PRAZO,
            prazo_entrega=date(2026, 10, 1),
        )
        qs, get = self._qs_e_get()
        processos, _total, total_vencidos, url_vencidos = calcular_proximos_vencimentos(
            qs, get
        )
        itens_visiveis = {p.item_pca for p in processos}
        self.assertNotIn(vencido.item_pca, itens_visiveis)
        self.assertIn(futuro.item_pca, itens_visiveis)
        self.assertGreaterEqual(total_vencidos, 1)
        # `item_pca` alto (fixture sintética) cai fora da 1ª página (20 por
        # padrão) — pagina até encontrar, não confunde "ausente" com "está
        # na página seguinte".
        itens_vencidos = set()
        pagina = 1
        separador = "&" if "?" in url_vencidos else "?"
        while True:
            resposta = self.client.get(f"{url_vencidos}{separador}pagina={pagina}")
            objetos = resposta.context["pagina"].object_list
            if not objetos:
                break
            itens_vencidos.update(p.item_pca for p in objetos)
            if not resposta.context["pagina"].has_next():
                break
            pagina += 1
        self.assertIn(vencido.item_pca, itens_vencidos)

    def test_concluido_ou_recebido_no_gelic_nunca_aparece(self):
        concluido = self._processo(
            974, estado=Estado.ATIVO, situacao=Situacao.CONCLUIDO,
            prazo_entrega=date(2026, 9, 20),
        )
        recebido = self._processo(
            975, estado=Estado.ATIVO, situacao=Situacao.NO_PRAZO,
            prazo_entrega=date(2026, 9, 20),
            data_recebimento_gelic=date(2026, 9, 10),
        )
        qs, get = self._qs_e_get()
        processos, _total, _vencidos, _url = calcular_proximos_vencimentos(qs, get)
        itens = {p.item_pca for p in processos}
        self.assertNotIn(concluido.item_pca, itens)
        self.assertNotIn(recebido.item_pca, itens)

    def test_situacao_manual_atrasado_com_prazo_futuro_continua_aparecendo(self):
        # A função nunca reescreve `situacao_efetiva`, só lê: uma
        # situação manual "Atrasado" com `prazo_efetivo` futuro continua
        # aparecendo na lista, com essa mesma situação exibida (não é
        # reclassificada como "No prazo" para caber na condição).
        atrasado_manual = self._processo(
            976, estado=Estado.ATIVO, situacao=Situacao.ATRASADO,
            prazo_entrega=date(2026, 10, 1),
        )
        qs, get = self._qs_e_get()
        processos, _total, _vencidos, _url = calcular_proximos_vencimentos(qs, get)
        encontrado = next(
            (p for p in processos if p.item_pca == atrasado_manual.item_pca), None
        )
        self.assertIsNotNone(encontrado)
        self.assertEqual(encontrado.situacao_efetiva, Situacao.ATRASADO.value)

    def test_vencimentos_20_mostra_ate_20_e_valor_fora_da_allowlist_cai_em_10(self):
        for indice in range(15):
            self._processo(
                980 + indice, estado=Estado.ATIVO, situacao=Situacao.NO_PRAZO,
                prazo_entrega=date(2026, 9, 16 + indice),
            )
        resposta_10 = self.client.get(reverse("pca:analise"))
        self.assertEqual(resposta_10.context["proximos_vencimentos"]["limite"], 10)
        self.assertLessEqual(len(resposta_10.context["proximos_vencimentos"]["linhas"]), 10)

        resposta_20 = self.client.get(reverse("pca:analise"), {"vencimentos": "20"})
        self.assertEqual(resposta_20.context["proximos_vencimentos"]["limite"], 20)
        self.assertLessEqual(len(resposta_20.context["proximos_vencimentos"]["linhas"]), 20)
        self.assertGreater(
            len(resposta_20.context["proximos_vencimentos"]["linhas"]),
            len(resposta_10.context["proximos_vencimentos"]["linhas"]),
        )

        resposta_invalida = self.client.get(
            reverse("pca:analise"), {"vencimentos": "999"}
        )
        self.assertEqual(
            resposta_invalida.context["proximos_vencimentos"]["limite"], 10
        )

    def test_kpi_proximos_do_vencimento_muda_de_base_sem_mudar_orcamento_de_consultas(self):
        from django.conf import settings
        from apps.pca.kpis import calcular_blocos_kpi

        self._processo(
            977, estado=Estado.ATIVO, situacao=Situacao.NO_PRAZO,
            prazo_entrega=date(2026, 9, 20),
        )
        qs, get = self._qs_e_get()
        with self.assertNumQueries(2):
            _bloco_a, bloco_b, _gauge = calcular_blocos_kpi(
                qs, get, dias_proximo_vencimento=settings.PCA_DIAS_PROXIMOS_VENCIMENTO
            )
        self.assertGreaterEqual(bloco_b["proximos_vencimento"]["contagem"], 1)

    def test_titulo_analise_html_contem_proximos_vencimentos(self):
        resposta = self.client.get(reverse("pca:analise"))
        conteudo = resposta.content.decode("utf-8")
        self.assertIn("Próximos vencimentos", conteudo)

    def test_vocabulario_prazo_atual_fechado_preserva_vigencia_contratual(self):
        # A tabela Próximos vencimentos usa "Prazo atual" (como no
        # resto da UI); vigência contratual (`vigencia_fim`, par
        # "Vencimentos por mês") não é afetada.
        self._processo(
            978, estado=Estado.ATIVO, situacao=Situacao.NO_PRAZO,
            prazo_entrega=date(2026, 9, 20),
        )
        resposta = self.client.get(reverse("pca:analise"))
        conteudo = resposta.content.decode("utf-8")
        self.assertIn(">Prazo atual<", conteudo)
        self.assertNotIn("Prazo vigente", conteudo)
        self.assertIn("Vencimentos por mês", conteudo)


class TestParAnaliticoDataThCasaComAColuna(SimpleTestCase):
    """28-REVIEW (CR-02) — reprodução isolada (`render_to_string`, sem
    banco) do off-by-one de `data-th` nos partials congelados
    `dsgov/_par_analitico.html` e `dsgov/_grafico_card.html`
    (`colunas|slice:forloop.counter0|last` produzia o rótulo da coluna
    ANTERIOR em toda célula, com a primeira sempre vazia — corrigido para
    `forloop.counter`, 1-based, que `colunas[:N][-1] == colunas[N-1]`
    resolve corretamente). Assunto de `SimpleTestCase` (nenhum banco
    necessário) para a prova ficar restrita ao TEMPLATE, não à view."""

    COLUNAS = ["C1", "C2", "C3", "C4"]

    def _data_th_por_celula(self, html):
        """Extrai, na ordem em que aparecem, todos os valores de
        `data-th="..."` do HTML renderizado — uma célula por entrada."""
        return re.findall(r'data-th="([^"]*)"', html)

    def test_par_analitico_data_th_na_ordem_correta_das_colunas(self):
        linha = [{"valor": "v1"}, {"valor": "v2"}, {"valor": "v3"}, {"valor": "v4"}]
        html = render_to_string(
            "dsgov/_par_analitico.html",
            {
                "par": {
                    "titulo": "Teste",
                    "grafico": {"id": "g-teste", "opcoes": {}, "resumo": "resumo"},
                    "tabela": {"colunas": self.COLUNAS, "linhas": [linha]},
                }
            },
        )
        self.assertEqual(self._data_th_por_celula(html), self.COLUNAS)

    def test_grafico_card_data_th_na_ordem_correta_das_colunas(self):
        linha = [{"valor": "v1"}, {"valor": "v2"}, {"valor": "v3"}, {"valor": "v4"}]
        html = render_to_string(
            "dsgov/_grafico_card.html",
            {
                "grafico": {
                    "id": "g-teste",
                    "titulo": "Teste",
                    "opcoes": {},
                    "resumo": "resumo",
                    "tabela": {"colunas": self.COLUNAS, "linhas": [linha]},
                }
            },
        )
        self.assertEqual(self._data_th_por_celula(html), self.COLUNAS)
