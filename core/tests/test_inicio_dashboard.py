"""Fase 26 (..17) — `core:inicio` vira o dashboard real:
4 KPIs, 4 gráficos permitidos, uma tabela de pendências. Mesmo padrão de
`apps/pca/tests/test_dashboard.py` (import real do `.xlsx`,
`TransactionTestCase` + `serialized_rollback=True`) — os números aqui
nunca divergem dos de `apps.pca.kpis.calcular_blocos_kpi` (intocado), a
prova de que a apresentação mudou sem tocar a regra de negócio.

Fase 28 (..20) — Início reduz de 4 para EXATAMENTE 2
gráficos executivos (rosca de situação só-ativos + barras "Valor previsto
x valor contratado"); "Processos por unidade"/"Previsto x Entregue por
mês"/"Situação por mês previsto" saem (equivalente em Análises, exceto o
último, que fica sem consumidor mas não é removido — ver `core/views.py`).
`ver_numeros_url` sai do contexto junto com o 4º gráfico. O apoio do KPI
Concluídos passa a "Da meta: X de Y concluídos — Z%". Os testes
abaixo que mediam os gráficos 2/3/4 antigos (unidade/mês/situação-por-mês)
e o link "Ver números" foram substituídos pelos equivalentes do novo
contrato — divergência do plano (que listava só `apps/pca/tests/
test_analise.py`) registrada como desvio no SUMMARY: este arquivo testa
`core:inicio` diretamente, não `pca:analise`, e quebraria sem o ajuste."""

import time
from decimal import Decimal
from io import StringIO

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from apps.catalogo.models import Categoria, Exercicio, Tipo, Unidade
from apps.pca.filtros import filtros_ativos, queryset_filtrado
from apps.pca.kpis import calcular_blocos_kpi
from apps.pca.models import Estado, Processo

ARQUIVO_REAL = "Modelo_de_Controle_.xlsx"


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

    def test_trilha_do_inicio_nao_duplica_no_tabler(self):
        """QA 30/09/2026, navegador B5 — `trilha=[("Início", None)]`
        sempre ativava o bloco `{% if trilha %}` de `tabler/templates/
        base.html`, que já tem um link fixo "Início" ANTES de iterar
        `trilha` — duplicando o texto. Trilha vazia desliga o bloco
        inteiro."""
        from core.tests.test_casca_tabler import CASCA_TABLER

        with CASCA_TABLER:
            resposta = self.client.get("/", {"exercicio": self.exercicio.ano})
            html = resposta.content.decode("utf-8")
            self.assertNotIn('aria-label="Trilha de navegação"', html)

    def test_exatamente_sete_kpis_na_ordem_aprovada(self):
        """(pedido da diretora, 15/10/2026) — Previstos |
        Cancelados | Ativos | Concluídos | Em tramitação | No prazo |
        Atrasados; cada cartão tem o tom da cor da fatia na rosca e o grupo
        que monta a grade (universo em cima, situação dos ativos embaixo)."""
        resposta = self.client.get("/", {"exercicio": self.exercicio.ano})
        kpis = resposta.context["kpis"]
        self.assertEqual(len(kpis), 7)
        self.assertEqual(
            [kpi["rotulo"] for kpi in kpis],
            ["Previstos", "Cancelados", "Ativos", "Concluídos", "Em tramitação", "No prazo", "Atrasados"],
        )
        self.assertEqual(
            [kpi["tom"] for kpi in kpis],
            ["destaque", "neutro", "destaque", "sucesso", "info", "alerta", "erro"],
        )
        self.assertEqual(
            [kpi["grupo"] for kpi in kpis],
            ["total", "universo", "universo", "situacao", "situacao", "situacao", "situacao"],
        )
        conteudo = resposta.content.decode("utf-8")
        self.assertEqual(conteudo.count("dsgov-kpi h-100"), 7)
        self.assertEqual(conteudo.count("dsgov-kpi-neutro"), 1)
        self.assertEqual(conteudo.count('class="col-6 col-md-3 col-lg mb-3"'), 4)

    def test_previstos_somam_cancelados_e_ativos_e_ativos_somam_as_situacoes(self):
        """O recorte que a diretora pediu fecha: previstos =
        cancelados + ativos; ativos = concluídos + em tramitação + no prazo +
        atrasados."""
        resposta = self.client.get("/", {"exercicio": self.exercicio.ano})
        valores = {kpi["rotulo"]: int(kpi["valor"].replace(".", "")) for kpi in resposta.context["kpis"]}
        self.assertEqual(valores["Previstos"], valores["Cancelados"] + valores["Ativos"])
        self.assertEqual(
            valores["Ativos"],
            valores["Concluídos"] + valores["Em tramitação"] + valores["No prazo"] + valores["Atrasados"],
        )

    def test_kpis_batem_com_calcular_blocos_kpi_sem_formula_concorrente(self):
        bloco_a, bloco_b, _gauge = self._blocos()
        resposta = self.client.get("/", {"exercicio": self.exercicio.ano})
        kpis = {kpi["rotulo"]: kpi for kpi in resposta.context["kpis"]}

        self.assertIn(str(bloco_a["total"]["contagem"]), kpis["Previstos"]["valor"])
        self.assertIn(str(bloco_a["cancelados"]["contagem"]), kpis["Cancelados"]["valor"])
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
        self.assertIn(str(bloco_b["no_prazo"]["contagem"]), kpis["No prazo"]["valor"])

    def test_apoio_de_cada_kpi_segue_o_texto_do_prompt(self):
        bloco_a, bloco_b, _gauge = self._blocos()
        resposta = self.client.get("/", {"exercicio": self.exercicio.ano})
        kpis = {kpi["rotulo"]: kpi for kpi in resposta.context["kpis"]}

        self.assertIn(f"PCA {self.exercicio.ano}", kpis["Previstos"]["apoio"])
        self.assertIn("dos previstos", kpis["Cancelados"]["apoio"])
        self.assertIn("dos previstos", kpis["Ativos"]["apoio"])
        # "Da meta: X de Y concluídos — Z%", os 3
        # números do MESMO universo NC|RN.
        self.assertIn("Da meta:", kpis["Concluídos"]["apoio"])
        self.assertIn("concluídos", kpis["Concluídos"]["apoio"])
        self.assertIn("Gelic", kpis["Em tramitação"]["apoio"])
        self.assertIn("prazo", kpis["No prazo"]["apoio"])
        self.assertIn("sobrestados", kpis["Atrasados"]["apoio"])

    def test_apoio_concluidos_bate_com_meta_pca_do_mesmo_universo(self):
        """Os 3 números do texto vêm de `bloco_b['concluido']
        ['meta_pca'/'concluido_meta_pca'/'percentual_meta_pca']` (Plano
        28-05), nunca uma fórmula concorrente."""
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
        """Critério literal 28-06.1: "Exatamente
        dois gráficos; duas barras financeiras; nenhum gráfico mensal no
        Início"."""
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

    # (revisão, decisão do usuário
    # 09/09/2026) — os 2 gráficos do dashboard mudam de forma, mas
    # continuam sendo exatamente 2 (teste acima), com drill-down por
    # clique em TODO ponto (regra 9 de graficos.md).

    def test_rosca_situacao_tem_todos_os_previstos_com_total_no_centro(self):
        """A rosca contempla o mesmo recorte dos 7 KPIs:
        Cancelado + as 4 situações dos ativos, na ordem dos cartões, e o
        total de previstos no centro."""
        bloco_a, _bloco_b, _gauge = self._blocos()
        resposta = self.client.get("/", {"exercicio": self.exercicio.ano})
        opcoes = resposta.context["graficos"][0]["opcoes"]
        self.assertEqual(
            [item["name"] for item in opcoes["series"][0]["data"]],
            ["Cancelado", "Concluído", "Em tramitação", "No prazo", "Atrasado"],
        )
        self.assertEqual(
            sum(item["value"] for item in opcoes["series"][0]["data"]),
            bloco_a["total"]["contagem"],
        )
        self.assertTrue(opcoes["graphic"][0]["style"]["text"].endswith("previstos"))
        self.assertIn("cancelados", resposta.context["graficos"][0]["resumo"])

    def test_rosca_situacao_mostra_valor_e_percentual_com_linha_guia(self):
        """Valor e percentual de TODAS as fatias aparecem sem passar o mouse,
        fora do anel e ligados à fatia por uma linha-guia."""
        resposta = self.client.get("/", {"exercicio": self.exercicio.ano})
        serie = resposta.context["graficos"][0]["opcoes"]["series"][0]
        self.assertTrue(serie["label"]["show"])
        self.assertEqual(serie["label"]["position"], "outside")
        self.assertEqual(serie["label"]["formatter"], "{c} ({d}%)")
        self.assertTrue(serie["labelLine"]["show"])
        self.assertEqual(serie["minShowLabelAngle"], 0)

    def test_segundo_grafico_e_barras_financeiras_com_duas_medidas(self):
        """2ª entrada de `graficos`: barras "Valor previsto x
        valor contratado", exatamente 2 categorias/1 série (`rotulos=True`,
        sem legenda redundante para 2 barras)."""
        resposta = self.client.get("/", {"exercicio": self.exercicio.ano})
        grafico = resposta.context["graficos"][1]
        self.assertEqual(grafico["id"], "grafico-financeiro")
        opcoes = grafico["opcoes"]
        self.assertEqual(opcoes["xAxis"]["data"], ["Valor previsto", "Valor contratado"])
        self.assertEqual(len(opcoes["series"]), 1)
        self.assertEqual(len(opcoes["series"][0]["data"]), 2)

    def test_ver_dados_rosca_situacao_quatro_colunas_subtotal_e_total(self):
        """→ Situação/Quantidade/Percentual dos
        previstos/Valor estimado: as 4 situações, o subtotal dos ativos, os
        cancelados e a linha "Total"."""
        resposta = self.client.get("/", {"exercicio": self.exercicio.ano})
        tabela = resposta.context["graficos"][0]["tabela"]
        self.assertEqual(
            tabela["colunas"],
            ["Situação", "Quantidade", "Percentual dos previstos", "Valor estimado"],
        )
        self.assertEqual(
            [linha[0]["valor"] for linha in tabela["linhas"]],
            ["Concluído", "Em tramitação", "No prazo", "Atrasado", "Ativos (subtotal)", "Cancelado", "Total"],
        )

    def test_ver_dados_barras_financeiras_duas_medidas_batem_com_analise(self):
        """Mesmos números de `analise_view`'s `soma_filtrada`/
        `soma_contratada` para o mesmo filtro (Pitfall 16)."""
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
        """Nulos não viram zero; o apoio textual informa a
        quantidade sem preenchimento."""
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
        """O 4º gráfico (situação por mês) saiu do Início; o link
        "Ver números" que apontava para ele sai junto."""
        resposta = self.client.get("/", {"exercicio": self.exercicio.ano})
        self.assertNotIn("ver_numeros_url", resposta.context)
        conteudo = resposta.content.decode("utf-8")
        self.assertNotIn("Ver números", conteudo)

    def test_universo_ativo_vazio_nao_lanca_excecao_e_mostra_traco(self):
        """Exercício sem nenhum processo ativo: percentuais viram
        "—", nunca "0%"/erro."""
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
        """Mesmo contrato do 24/ a contagem da tabela filtrada
        (`pagina.paginator.count`) bate EXATAMENTE com o valor de cada
        ponto/fatia/barra/segmento com `url`, nos 2 gráficos do
        dashboard."""
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
    """Fase 26 — RNF /Critério de Sucesso 1 (documento do projeto
    §Constraints, "dashboard abaixo de 2 s com até 500 processos") migra
    junto com o dashboard real para `core:inicio`; `TestDashboardPerformance`
    (`apps/pca/tests/test_dashboard.py`, `pca:dashboard`) sai
    deste plano. Mesma expansão determinística a 500 processos."""

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


class InicioPadraoPncpTests(TestCase):
    """Faixa de abertura com busca, link para Análises,
    "Acesso rápido" com os destinos do menu (respeitando permissão) e as
    colunas financeiras nas cores dos cartões de valor."""

    def setUp(self):
        from apps.pca.models import Exercicio

        self.exercicio, _ = Exercicio.objects.get_or_create(ano=2026)
        usuario = get_user_model()
        self.leitor = usuario.objects.create_user(email="leitor-p5n@pca.local", password="senha-segura-261014")
        self.editor = usuario.objects.create_user(email="editor-p5n@pca.local", password="senha-segura-261014")
        from django.contrib.auth.models import Permission

        self.editor.user_permissions.add(
            Permission.objects.get(codename="editar_pca"),
            Permission.objects.get(codename="view_acompanhamento"),
        )

    def _get(self, usuario):
        self.client.force_login(usuario)
        return self.client.get("/", {"exercicio": 2026}, HTTP_X_FORWARDED_PROTO="https")

    def test_faixa_tem_busca_para_a_busca_global_e_link_para_analises(self):
        conteudo = self._get(self.leitor).content.decode("utf-8")
        self.assertIn('class="dsgov-faixa"', conteudo)
        self.assertIn(f'action="{reverse("pca:busca")}"', conteudo)
        self.assertIn('id="busca-inicio"', conteudo)
        self.assertIn(f'href="{reverse("pca:analise")}?exercicio=2026"', conteudo)
        self.assertIn("Mais informações no painel de Análises", conteudo)

    def test_acesso_rapido_respeita_as_permissoes_do_menu(self):
        rotulos_leitor = [c["rotulo"] for c in self._get(self.leitor).context["acesso_rapido"]]
        self.assertIn("Processos", rotulos_leitor)
        self.assertIn("Análises", rotulos_leitor)
        self.assertNotIn("Calendário", rotulos_leitor)
        self.assertNotIn("Reuniões", rotulos_leitor)
        self.assertNotIn("Início", rotulos_leitor)
        rotulos_editor = [c["rotulo"] for c in self._get(self.editor).context["acesso_rapido"]]
        self.assertIn("Calendário", rotulos_editor)
        self.assertIn("Reuniões", rotulos_editor)

    def test_colunas_financeiras_nas_cores_dos_cartoes_de_valor(self):
        from core.graficos import CORES_VALOR

        opcoes = self._get(self.leitor).context["graficos"][1]["opcoes"]
        dados = opcoes["series"][0]["data"]
        self.assertEqual(
            [d["itemStyle"]["color"] for d in dados],
            [CORES_VALOR["estimado"], CORES_VALOR["contratado"]],
        )
        self.assertTrue(all(d["label"]["formatter"].startswith("R$ ") for d in dados))
        self.assertFalse(opcoes["yAxis"]["show"])
