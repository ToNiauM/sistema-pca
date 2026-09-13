"""`core:inicio` — dashboard real: 4 KPIs, 2 gráficos executivos (rosca
de situação só-ativos + barras "Valor previsto x valor contratado") e uma
tabela de pendências. Import real do `.xlsx`, `TransactionTestCase` +
`serialized_rollback=True` — os números aqui nunca divergem dos de
`apps.pca.kpis.calcular_blocos_kpi`, a prova de que a apresentação mudou
sem tocar a regra de negócio. O apoio do KPI Concluídos é "Da meta: X de
Y concluídos — Z%"."""

import time
from decimal import Decimal
from io import StringIO

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TransactionTestCase
from django.urls import reverse

from apps.catalogo.models import Categoria, Exercicio, Tipo, Unidade
from apps.pca.filtros import filtros_ativos, queryset_filtrado
from apps.pca.kpis import calcular_blocos_kpi
from apps.pca.models import Estado, Processo

ARQUIVO_REAL = "apps/pca/fixtures/modelo-controle-exemplo.xlsx"


class TestInicioComExercicioReal(TransactionTestCase):
    """`core:inicio` sobre o exercício 2026 importado de verdade."""

    serialized_rollback = True

    def setUp(self):
        call_command(
            "importar_pca",
            ARQUIVO_REAL,
            "--usuario=importador@pca.local",
            "--exercicio=2026",
            stdout=StringIO(),
        )
        self.exercicio = Exercicio.objects.get(ano=2026)
        self.usuario = get_user_model().objects.create_user(
            email="leitor-core-inicio@pca.local", password="x-forte-123"
        )
        self.client.force_login(self.usuario)

    def _blocos(self):
        from django.test import RequestFactory

        request = RequestFactory().get(
            "/", {"exercicio": self.exercicio.ano}
        )
        qs = queryset_filtrado(request)
        return calcular_blocos_kpi(
            qs,
            request.GET,
            dias_proximo_vencimento=settings.PCA_DIAS_PROXIMOS_VENCIMENTO,
        )

    def test_reverse_core_inicio_e_a_raiz(self):
        self.assertEqual(reverse("core:inicio"), "/")

    def test_autenticado_recebe_200_com_o_template_certo(self):
        resposta = self.client.get("/", {"exercicio": self.exercicio.ano})
        self.assertEqual(resposta.status_code, 200)
        self.assertTemplateUsed(resposta, "core/inicio.html")

    def test_anonimo_e_redirecionado_para_login(self):
        self.client.logout()
        resposta = self.client.get("/")
        self.assertEqual(resposta.status_code, 302)
        self.assertIn("/login", resposta.url)

    def test_exatamente_quatro_kpis_na_ordem_do_prompt(self):
        resposta = self.client.get("/", {"exercicio": self.exercicio.ano})
        kpis = resposta.context["kpis"]
        self.assertEqual(len(kpis), 4)
        self.assertEqual(
            [kpi["rotulo"] for kpi in kpis],
            ["Ativos", "Concluídos", "Em tramitação", "Atrasados"],
        )

    def test_kpis_batem_com_calcular_blocos_kpi_sem_formula_concorrente(self):
        bloco_a, bloco_b, _gauge = self._blocos()
        resposta = self.client.get("/", {"exercicio": self.exercicio.ano})
        kpis = {kpi["rotulo"]: kpi for kpi in resposta.context["kpis"]}

        self.assertIn(str(bloco_a["ativos"]["contagem"]), kpis["Ativos"]["valor"])
        self.assertIn(
            str(bloco_b["concluido"]["contagem"]), kpis["Concluídos"]["valor"]
        )
        self.assertIn(
            str(bloco_b["em_tramitacao"]["contagem"]),
            kpis["Em tramitação"]["valor"],
        )
        self.assertIn(
            str(bloco_b["atrasados"]["contagem"]), kpis["Atrasados"]["valor"]
        )

    def test_apoio_de_cada_kpi_segue_o_texto_do_prompt(self):
        bloco_a, bloco_b, _gauge = self._blocos()
        resposta = self.client.get("/", {"exercicio": self.exercicio.ano})
        kpis = {kpi["rotulo"]: kpi for kpi in resposta.context["kpis"]}

        self.assertIn("previstos", kpis["Ativos"]["apoio"])
        self.assertIn("cancelados", kpis["Ativos"]["apoio"])
        # "Da meta: X de Y concluídos — Z%", os 3 números do mesmo universo NC|RN.
        self.assertIn("Da meta:", kpis["Concluídos"]["apoio"])
        self.assertIn("concluídos", kpis["Concluídos"]["apoio"])
        self.assertIn("no prazo", kpis["Em tramitação"]["apoio"])
        self.assertIn("sobrestados", kpis["Atrasados"]["apoio"])

    def test_apoio_concluidos_bate_com_meta_pca_do_mesmo_universo(self):
        """Os 3 números do texto vêm de
        `bloco_b['concluido']['meta_pca'/'concluido_meta_pca'/
        'percentual_meta_pca']`, nunca uma fórmula concorrente."""
        _bloco_a, bloco_b, _gauge = self._blocos()
        concluido = bloco_b["concluido"]
        resposta = self.client.get("/", {"exercicio": self.exercicio.ano})
        kpis = {kpi["rotulo"]: kpi for kpi in resposta.context["kpis"]}
        apoio = kpis["Concluídos"]["apoio"]
        self.assertIn(str(concluido["concluido_meta_pca"]), apoio)
        self.assertIn(str(concluido["meta_pca"]), apoio)

    def test_clique_no_kpi_ativos_leva_ao_mesmo_recorte_da_tabela(self):
        bloco_a, _bloco_b, _gauge = self._blocos()
        resposta = self.client.get("/", {"exercicio": self.exercicio.ano})
        kpis = {kpi["rotulo"]: kpi for kpi in resposta.context["kpis"]}
        url_ativos = kpis["Ativos"]["url"]

        resposta_tabela = self.client.get(url_ativos)
        self.assertEqual(resposta_tabela.status_code, 200)
        # A mesma contagem do KPI aparece no rodapé de paginação da tabela.
        self.assertContains(
            resposta_tabela, str(bloco_a["ativos"]["contagem"])
        )

    def test_exatamente_dois_graficos_permitidos_com_role_e_aria_label(self):
        """Exatamente dois gráficos; duas barras financeiras; nenhum
        gráfico mensal no Início."""
        resposta = self.client.get("/", {"exercicio": self.exercicio.ano})
        graficos = resposta.context["graficos"]
        self.assertEqual(len(graficos), 2)
        conteudo = resposta.content.decode("utf-8")
        self.assertEqual(conteudo.count("data-grafico="), 2)
        self.assertEqual(conteudo.count('role="img"'), 2)
        for grafico in graficos:
            self.assertTrue(grafico["resumo"])
            self.assertIn(f'data-grafico="{grafico["id"]}"', conteudo)

    def test_nenhum_tipo_de_grafico_fora_da_lista_permitida(self):
        resposta = self.client.get("/", {"exercicio": self.exercicio.ano})
        for grafico in resposta.context["graficos"]:
            tipos = {serie["type"] for serie in grafico["opcoes"]["series"]}
            self.assertTrue(tipos.issubset({"pie", "bar", "line"}))

    def test_pendencias_tem_ver_todos_e_no_maximo_dez_linhas(self):
        resposta = self.client.get("/", {"exercicio": self.exercicio.ano})
        pendencias = resposta.context["pendencias"]
        self.assertLessEqual(len(pendencias["objetos"]), 10)
        conteudo = resposta.content.decode("utf-8")
        self.assertIn("Ver todos", conteudo)

    def test_seletor_de_exercicio_e_form_get_sem_htmx(self):
        resposta = self.client.get("/", {"exercicio": self.exercicio.ano})
        conteudo = resposta.content.decode("utf-8")
        self.assertIn('<form method="get"', conteudo)
        self.assertNotIn("hx-get", conteudo.split('<form method="get"')[1][:600])

    def test_troca_de_exercicio_recalcula_kpis(self):
        outro = Exercicio.objects.create(
            ano=2027, rotulo="PCA 2027", situacao="aberto"
        )
        resposta = self.client.get("/", {"exercicio": outro.ano})
        self.assertEqual(resposta.status_code, 200)
        kpis = {kpi["rotulo"]: kpi for kpi in resposta.context["kpis"]}
        self.assertEqual(kpis["Ativos"]["valor"], "0")

    def test_rosca_situacao_e_so_ativos_com_total_no_centro(self):
        resposta = self.client.get("/", {"exercicio": self.exercicio.ano})
        opcoes = resposta.context["graficos"][0]["opcoes"]
        nomes = {item["name"] for item in opcoes["series"][0]["data"]}
        self.assertNotIn("Cancelado", nomes)
        self.assertIn("graphic", opcoes)

    def test_segundo_grafico_e_barras_financeiras_com_duas_medidas(self):
        """2ª entrada de `graficos`: barras "Valor previsto x valor
        contratado", exatamente 2 categorias/1 série."""
        resposta = self.client.get("/", {"exercicio": self.exercicio.ano})
        grafico = resposta.context["graficos"][1]
        self.assertEqual(grafico["id"], "grafico-financeiro")
        opcoes = grafico["opcoes"]
        self.assertEqual(opcoes["xAxis"]["data"], ["Valor previsto", "Valor contratado"])
        self.assertEqual(len(opcoes["series"]), 1)
        self.assertEqual(len(opcoes["series"][0]["data"]), 2)

    def test_ver_dados_rosca_situacao_quatro_colunas_mais_total(self):
        """Situação/Quantidade/Percentual dos ativos/Valor estimado +
        linha "Total"."""
        resposta = self.client.get("/", {"exercicio": self.exercicio.ano})
        tabela = resposta.context["graficos"][0]["tabela"]
        self.assertEqual(
            tabela["colunas"],
            ["Situação", "Quantidade", "Percentual dos ativos", "Valor estimado"],
        )
        self.assertEqual(tabela["linhas"][-1][0]["valor"], "Total")

    def test_ver_dados_barras_financeiras_duas_medidas_batem_com_analise(self):
        """Mesmos números de `analise_view`'s `soma_filtrada`/
        `soma_contratada` para o mesmo filtro."""
        from core.templatetags.dsgov import moeda

        resposta_inicio = self.client.get("/", {"exercicio": self.exercicio.ano})
        resposta_analise = self.client.get(
            reverse("pca:analise"), {"exercicio": self.exercicio.ano}
        )
        tabela = resposta_inicio.context["graficos"][1]["tabela"]
        self.assertEqual(tabela["colunas"], ["Medida", "Valor"])
        valores = {linha[0]["valor"]: linha[1]["valor"] for linha in tabela["linhas"]}
        self.assertEqual(
            valores["Valor previsto"], moeda(resposta_analise.context["soma_filtrada"])
        )
        self.assertEqual(
            valores["Valor contratado"],
            moeda(resposta_analise.context["soma_contratada"]),
        )

    def test_subtitulo_processos_sem_valor_contratado_quando_houver(self):
        """Nulos não viram zero; o apoio textual informa a quantidade
        sem preenchimento."""
        processo_sem_contratado = (
            Processo.objects.filter(
                exercicio=self.exercicio, valor_contratado__isnull=True
            )
            .exclude(estado=Estado.CANCELADO)
            .first()
        )
        self.assertIsNotNone(
            processo_sem_contratado,
            "fixture precisa de ao menos 1 processo com valor_contratado nulo",
        )
        resposta = self.client.get("/", {"exercicio": self.exercicio.ano})
        grafico = resposta.context["graficos"][1]
        self.assertIsNotNone(grafico["subtitulo"])
        self.assertIn("sem valor contratado preenchido", grafico["subtitulo"])

    def test_ver_numeros_url_nao_existe_mais_no_contexto(self):
        """O link "Ver números" não existe mais no contexto do Início."""
        resposta = self.client.get("/", {"exercicio": self.exercicio.ano})
        self.assertNotIn("ver_numeros_url", resposta.context)
        conteudo = resposta.content.decode("utf-8")
        self.assertNotIn("Ver números", conteudo)

    def test_universo_ativo_vazio_nao_lanca_excecao_e_mostra_traco(self):
        """Exercício sem nenhum processo ativo: percentuais viram "—",
        nunca "0%"/erro."""
        exercicio_vazio = Exercicio.objects.create(
            ano=2099, rotulo="PCA 2099", situacao="aberto"
        )
        resposta = self.client.get("/", {"exercicio": exercicio_vazio.ano})
        self.assertEqual(resposta.status_code, 200)
        tabela = resposta.context["graficos"][0]["tabela"]
        for linha in tabela["linhas"]:
            self.assertEqual(linha[2]["valor"], "—")

    def test_drilldown_bate_com_a_tabela_em_todos_os_pontos_de_todos_os_graficos(
        self,
    ):
        """A contagem da tabela filtrada (`pagina.paginator.count`) bate
        exatamente com o valor de cada ponto/fatia/barra/segmento com
        `url`, nos 2 gráficos do dashboard."""
        resposta = self.client.get("/", {"exercicio": self.exercicio.ano})
        graficos = resposta.context["graficos"]
        verificados = 0
        for grafico in graficos:
            for serie in grafico["opcoes"]["series"]:
                for item in serie["data"]:
                    if not isinstance(item, dict):
                        continue
                    url = item.get("url")
                    valor = item.get("value")
                    if not url:
                        continue
                    resposta_tabela = self.client.get(url)
                    self.assertEqual(
                        resposta_tabela.status_code, 200, msg=url
                    )
                    contagem = resposta_tabela.context["pagina"].paginator.count
                    self.assertEqual(
                        contagem,
                        valor,
                        msg=f"{grafico['titulo']} — {url}: esperado {valor}, tabela devolveu {contagem}",
                    )
                    verificados += 1
        self.assertGreater(verificados, 0)


class TestInicioPerformance(TransactionTestCase):
    """Dashboard abaixo de 2 s com até 500 processos. Mesma expansão
    determinística a 500 processos."""

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
            email="leitor-perf-core-inicio@pca.local", password="x-forte-123"
        )
        self.client.force_login(self.usuario)

        unidades = list(Unidade.objects.all())
        categorias = list(Categoria.objects.all())
        tipos = list(Tipo.objects.all())
        maior_item = Processo.objects.order_by("-item_pca").first().item_pca
        exercicio = Exercicio.objects.get(ano=2026)

        sinteticos = []
        for indice in range(500 - Processo.objects.count()):
            item = maior_item + 1 + indice
            sinteticos.append(
                Processo(
                    item_pca=item,
                    exercicio=exercicio,
                    descricao_objeto=f"Processo sintético de desempenho {item}",
                    tipo=tipos[indice % len(tipos)],
                    categoria=categorias[indice % len(categorias)],
                    unidade_organizacional=unidades[indice % len(unidades)],
                    valor_estimado=Decimal("1000.00") * (indice + 1),
                    mes_previsto=(indice % 12) + 1,
                )
            )
        Processo.objects.bulk_create(sinteticos)
        self.assertEqual(Processo.objects.count(), 500)

    def test_core_inicio_responde_abaixo_de_dois_segundos_com_500_processos(self):
        inicio = time.monotonic()
        resposta = self.client.get("/")
        decorrido = time.monotonic() - inicio
        self.assertEqual(resposta.status_code, 200)
        self.assertLess(decorrido, 2)
