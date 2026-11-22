"""Testes do módulo `apps.pca.relatorio_reuniao` — o Relatório da reunião.

Cobre a resolução de reunião e período (a reunião aberta vai até hoje), os registros da reunião agrupados
por unidade com os indicadores cumprido/repactuado/vencido, a numeração dinâmica de tabelas e gráficos, o
Anexo II em ordem de item (com "Cancelado"), a geometria dos gráficos de colunas em SVG, os cartões de situação e os casos vazios (exercício
sem reunião; reunião sem registros). `cenario_reuniao()` é reaproveitado pelos testes de tela.
"""

from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.http import QueryDict
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.catalogo.models import Categoria, Exercicio, SituacaoNormalizada, Tipo, Unidade
from apps.pca.models import (
    Acompanhamento, Estado, Processo, Reuniao, Situacao, SituacaoReuniao, TipoEvento,
)
from apps.pca.relatorio_reuniao import (
    ALTURA_MINIMA,
    ALTURA_TEXTO,
    LARGURA_CARACTERE,
    MARGEM,
    TOPO,
    ZONA_LEGENDA,
    ZONA_ROTULO,
    _grafico_colunas,
    _colunas_por_unidade,
    _referencias,
    _resumo_de_fatos,
    apresentar_relatorio,
    apurar_relatorio,
    montar_relatorio_reuniao,
    periodo_curto,
    periodo_por_extenso,
    resolver_periodo,
    resolver_reuniao,
)

HOJE = date(2026, 10, 15)


def _antedatar_historico(processo, dia):
    """O history nasce com a data de agora; os compromissos são apurados contra datas passadas."""
    momento = timezone.make_aware(datetime(dia.year, dia.month, dia.day, 10, 0))
    Processo.history.filter(id=processo.pk).update(history_date=momento)


def cenario_reuniao():
    """Exercício 2026 com uma reunião fechada (01/09) e a aberta (01/10). Na aberta foram tratados 3 itens de
    2 unidades: item 1 (GEX-B) repactuou o prazo, item 2 (GEX-A) cumpriu o da reunião anterior (concluiu
    antes do prazo) e item 3 (GEX-A) deixou vencer. O item 4 está cancelado e nunca foi tratado."""
    exercicio = Exercicio.objects.get(ano=2026)
    tipo = Tipo.objects.create(nome="Aquisição")
    categoria = Categoria.objects.create(nome="Serviços")
    situacao_norm = SituacaoNormalizada.objects.create(nome="Em andamento (teste)")
    uo_a = Unidade.objects.create(nome="GEX-A")
    uo_b = Unidade.objects.create(nome="GEX-B")
    anterior = Reuniao.objects.create(data=date(2026, 9, 1), situacao=SituacaoReuniao.FECHADA, exercicio=exercicio)
    aberta = Reuniao.objects.create(data=date(2026, 10, 1), situacao=SituacaoReuniao.ABERTA, exercicio=exercicio)

    def processo(item, uo, descricao, **extra):
        return Processo.objects.create(
            item_pca=item, exercicio=exercicio, descricao_objeto=descricao, tipo=tipo, categoria=categoria,
            unidade_organizacional=uo, valor_estimado=Decimal("1000.00") * item, mes_previsto=11, **extra,
        )

    repactua = processo(1, uo_b, "aquisição de cadeiras")
    cumpre = processo(2, uo_a, "manutenção predial", situacao=Situacao.CONCLUIDO)
    vence = processo(3, uo_a, "serviço de limpeza", prazo_entrega=date(2026, 9, 15))
    cancelado = processo(4, uo_a, "curso cancelado", estado=Estado.CANCELADO)
    for p in (repactua, cumpre, vence, cancelado):
        _antedatar_historico(p, date(2026, 8, 1))

    def registro(p, reuniao, chave, prazo=None, evento=""):
        Acompanhamento.objects.create(
            processo=p, referencia_data=reuniao.data, origem_hash=f"teste-r9m-{chave}",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO, situacao=situacao_norm, prazo_prometido=prazo,
            reuniao=reuniao, evento=evento,
        )

    registro(repactua, anterior, "1a", date(2026, 9, 20), "Prazo assumido.")
    registro(cumpre, anterior, "2a", date(2026, 9, 10), "Prazo assumido.")
    registro(vence, anterior, "3a", date(2026, 9, 15), "Prazo assumido.")
    registro(repactua, aberta, "1b", date(2026, 10, 30), "Aguardando a pesquisa de preços.")
    registro(cumpre, aberta, "2b", None, "Contrato assinado.")
    registro(vence, aberta, "3b", None, "Sem novidade.")
    return {"exercicio": exercicio, "anterior": anterior, "aberta": aberta, "uo_a": uo_a, "uo_b": uo_b}


class PeriodoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.c = cenario_reuniao()

    def test_reuniao_aberta_e_a_padrao_e_o_periodo_vai_ate_hoje(self):
        reuniao = resolver_reuniao(QueryDict(""), self.c["exercicio"], hoje=HOJE)
        self.assertEqual(reuniao, self.c["aberta"])
        self.assertEqual(
            resolver_periodo(QueryDict(""), self.c["exercicio"], reuniao, hoje=HOJE),
            (date(2026, 9, 2), HOJE, None),
        )

    def test_reuniao_fechada_vai_do_inicio_do_exercicio_ate_a_data_dela(self):
        get = QueryDict(f"reuniao={self.c['anterior'].pk}")
        reuniao = resolver_reuniao(get, self.c["exercicio"], hoje=HOJE)
        self.assertEqual(reuniao, self.c["anterior"])
        self.assertEqual(resolver_periodo(get, self.c["exercicio"], reuniao, hoje=HOJE)[:2],
                         (date(2026, 1, 1), date(2026, 9, 1)))

    def test_datas_livres_prevalecem_sobre_a_reuniao(self):
        get = QueryDict("de=2026-03-01&ate=2026-03-31")
        de, ate, _ = resolver_periodo(get, self.c["exercicio"], self.c["aberta"], hoje=HOJE)
        self.assertEqual((de, ate), (date(2026, 3, 1), date(2026, 3, 31)))

    def test_reuniao_de_outro_exercicio_ou_invalida_cai_na_aberta(self):
        for valor in ("999999", "abc", ""):
            with self.subTest(valor=valor):
                reuniao = resolver_reuniao(QueryDict(f"reuniao={valor}"), self.c["exercicio"], hoje=HOJE)
                self.assertEqual(reuniao, self.c["aberta"])

    def test_textos_de_periodo(self):
        self.assertEqual(periodo_por_extenso(date(2026, 10, 6), date(2026, 10, 15)), "de 6 a 15 de outubro de 2026")
        self.assertEqual(periodo_por_extenso(date(2026, 9, 6), date(2026, 10, 15)),
                         "de 6 de setembro a 15 de outubro de 2026")
        self.assertEqual(periodo_por_extenso(date(2026, 10, 15), date(2026, 10, 15)), "em 15 de outubro de 2026")
        self.assertEqual(periodo_curto(date(2026, 10, 6), date(2026, 10, 15)), "6 a 15/10/2026")
        self.assertEqual(periodo_curto(date(2026, 9, 6), date(2026, 10, 15)), "6/9 a 15/10/2026")
        self.assertEqual(periodo_curto(date(2025, 12, 6), date(2026, 1, 15)), "06/12/2025 a 15/01/2026")


class MontagemTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.c = cenario_reuniao()
        cls.usuario = get_user_model().objects.create_user(email="r9m@pca.local", password="senha-forte-123")

    def _montar(self, reuniao=None, de=date(2026, 9, 2), ate=HOJE):
        return montar_relatorio_reuniao(
            exercicio=self.c["exercicio"], reuniao=self.c["aberta"] if reuniao is None else reuniao,
            de=de, ate=ate, usuario=self.usuario, hoje=HOJE,
        )

    def test_cabecalho_da_reuniao_aberta(self):
        r = self._montar()
        self.assertEqual(r["titulo"], "2ª reunião de acompanhamento do PCA 2026")
        self.assertTrue(r["em_andamento"])
        self.assertEqual(r["periodo_curto"], "2/9 a 15/10/2026")
        self.assertEqual(r["fonte"], "Fonte: Sistema PCA CFC (15 out. 2026).")
        self.assertIn("desde a reunião anterior, de 1 de setembro", r["introducao"])

    def test_registros_agrupados_por_unidade_com_indicadores(self):
        registros = self._montar()["registros"]
        self.assertEqual([g["uo"] for g in registros["grupos"]], ["GEX-A", "GEX-B"])
        self.assertEqual([l["item"] for l in registros["grupos"][0]["linhas"]], [2, 3])
        self.assertEqual((registros["itens"], registros["unidades"]), (3, 2))
        self.assertEqual(
            (registros["cumpridos"], registros["repactuados"], registros["vencidos"]), (1, 1, 1)
        )
        por_item = {l["item"]: l for g in registros["grupos"] for l in g["linhas"]}
        self.assertEqual(por_item[1]["prazo"], "20/09/2026 → 30/10/2026")
        self.assertEqual(por_item[1]["status"], "repactuado")
        self.assertEqual(por_item[2]["status"], "cumprido")
        self.assertEqual(por_item[3]["status"], "vencido")
        self.assertEqual(por_item[1]["registro"], "Aguardando a pesquisa de preços.")
        self.assertEqual(por_item[1]["objeto"], "Aquisição de cadeiras")
        self.assertEqual(registros["lideres"], ["GEX-A"])

    def test_textos_citam_os_numeros_que_existem(self):
        r = self._montar()
        self.assertEqual(r["tabelas"]["registros"], 2)
        self.assertEqual(r["graficos"], {"valores": 1, "unidades": 2})
        self.assertNotIn("Gráfico", r["registros_texto"])
        self.assertIn("A Tabela 2 traz os registros", r["registros_texto"])
        self.assertIn("GEX-A teve 2 itens", r["registros_texto"])
        self.assertIn("Foram tratados 3 itens de 2 unidades", r["sintese"])
        self.assertIn("1 compromisso de prazo cumprido, 1 prazo repactuado e 1 compromisso vencido", r["sintese"])
        self.assertEqual(r["tabelas"]["anexo_processos"], r["tabelas"]["anexo_resumo"] + 1)

    def test_valores_em_duas_colunas(self):
        c = self.c
        fatos = apurar_relatorio(
            exercicio=c["exercicio"], reuniao=c["aberta"], de=date(2026, 9, 2), ate=HOJE, usuario=self.usuario,
            hoje=HOJE,
        )
        # Só a apresentação lê os fatos: valores sintéticos para as duas colunas terem altura.
        fatos["financeiro"] = {"estimado": "12500000.00", "contratado": "3200000.00"}
        g = apresentar_relatorio(fatos)["grafico_valores"]
        self.assertEqual([col["rotulo"] for col in g["colunas"]], ["Previsto", "Contratado"])
        self.assertEqual([col["valor"] for col in g["colunas"]], ["R$ 12,5 milhões", "R$ 3,2 milhões"])
        self.assertEqual([col["segmentos"][0]["classe"] for col in g["colunas"]], ["abnt-cor-3", "abnt-cor-1"])
        self.assertFalse(g["inclinado"])
        self.assertEqual(g["colunas"][0]["segmentos"][0]["y"], f"{TOPO:.2f}")

    def test_anexo_ii_em_ordem_de_item_com_cancelado(self):
        processos = self._montar()["anexo_processos"]
        self.assertEqual([p["item"] for p in processos], [1, 2, 3, 4])
        self.assertEqual(processos[3]["situacao"], "Cancelado")
        self.assertEqual(processos[1]["situacao"], "Concluído")
        self.assertEqual(processos[0]["objeto"], "Aquisição de cadeiras")

    def test_anexo_i_tem_as_colunas_do_resumo_por_unidade_e_o_total(self):
        anexo = self._montar()["anexo_resumo"]
        self.assertEqual(anexo["total"]["uo"], "TOTAL")
        self.assertEqual(len(anexo["total"]["celulas"]), 11)
        self.assertEqual(anexo["total"]["celulas"][0]["n"], 4)
        self.assertEqual(anexo["total"]["celulas"][0]["pct"], "100,0%")
        self.assertEqual(anexo["total"]["celulas"][1]["n"], 1)
        self.assertEqual([c["sep"] for c in anexo["total"]["celulas"]].count(True), 4)

    def test_situacao_do_pca_bate_com_o_resumo_por_unidade(self):
        r = self._montar()
        self.assertIn("o PCA 2026 tinha 4 itens previstos: 1 cancelados e 3 ativos", r["situacao_texto"])
        cartoes = r["cartoes_situacao"]
        self.assertEqual([c["rotulo"] for c in cartoes], ["Concluído", "Em tramitação", "No prazo", "Atrasado"])
        self.assertEqual([c["classe"] for c in cartoes],
                         ["abnt-cartao-1", "abnt-cartao-2", "abnt-cartao-3", "abnt-cartao-alerta"])
        total = _resumo_de_fatos(self._fatos()["resumo_uo"]["total"])
        self.assertEqual([c["n"] for c in cartoes], [
            total["concluido"], total["em_tramitacao_ativos"], total["no_prazo_ativos"], total["atrasado_ativos"],
        ])
        self.assertEqual(cartoes[0]["n"], 1)  # o item 2 está concluído
        # colunas de unidade: GEX-A (2 ativos) antes de GEX-B (1); a legenda tem as 3 séries
        unidades = r["grafico_unidades"]
        self.assertEqual([c["rotulo"] for c in unidades["colunas"]], ["GEX-A", "GEX-B"])
        self.assertEqual([c["valor"] for c in unidades["colunas"]], ["2", "1"])
        self.assertEqual([i["classe"] for i in unidades["legenda"]], ["abnt-cor-1", "abnt-cor-2", "abnt-cor-3"])
        self.assertEqual([i["texto"] for i in unidades["legenda"]], ["Concluído", "Em tramitação", "A entregar à Gelic"])
        self.assertFalse(r["unidades_agrupadas"])

    def _fatos(self):
        c = self.c
        return apurar_relatorio(
            exercicio=c["exercicio"], reuniao=c["aberta"], de=date(2026, 9, 2), ate=HOJE, usuario=self.usuario,
            hoje=HOJE,
        )

    def test_quadros_graficos_e_citacoes_com_reuniao(self):
        r = self._montar()
        self.assertEqual(r["quadros"], {"indicadores": 1, "situacao": 2})
        self.assertEqual(r["graficos"], {"valores": 1, "unidades": 2})
        self.assertIn("(Quadro 2)", r["situacao_texto"])
        self.assertIn("(Gráfico 1)", r["situacao_texto"])
        self.assertIn("(Gráfico 2)", r["situacao_texto"])
        self.assertNotIn("Gráfico 3", r["situacao_texto"])
        self.assertIn("(Quadro 1)", r["sintese"])

    def test_chaves_do_desenho_antigo_sumiram(self):
        r = self._montar()
        for chave in ("grafico_situacao", "grafico_incluidos", "incluidos_alem_do_grafico"):
            self.assertNotIn(chave, r)
        self.assertNotIn("grafico", r["registros"])
        self.assertTrue(r["tabela1"])
        self.assertFalse([l for l in r["tabela1"] if "barra" in l])

    def test_incluidos_texto_cita_so_a_tabela(self):
        fatos = self._fatos()
        fatos["inclusoes"] = {
            "contagem": 1, "soma_valor": "5000.00",
            "linhas": [{"item": 9, "uo": "GEX-A", "objeto": "Item novo", "valor": "5000.00", "mes": 11, "extras": []}],
        }
        r = apresentar_relatorio(fatos)
        self.assertNotIn("Gráfico", r["incluidos_texto"])
        self.assertTrue(r["incluidos_texto"].endswith(f"(Tabela {r['tabelas']['incluidos']})."))

    def test_r_cifrao_nunca_se_separa_do_numero(self):
        r = self._montar()
        self.assertNotIn("R$ ", r["situacao_texto"])
        self.assertIn("R$ ", r["situacao_texto"])

    def test_reuniao_sem_registros(self):
        r = self._montar(reuniao=self.c["anterior"], de=date(2026, 1, 1), ate=date(2026, 9, 1))
        # A reunião de 01/09 tem registros (os compromissos); a aberta, sem eles, é o caso vazio:
        Acompanhamento.objects.filter(reuniao=self.c["aberta"]).delete()
        vazio = self._montar()
        self.assertTrue(r["registros"]["grupos"])
        self.assertEqual(vazio["registros"]["grupos"], [])
        self.assertNotIn("grafico", vazio["registros"])
        self.assertNotIn("registros", vazio["tabelas"])
        self.assertEqual(vazio["registros_texto"], "Nenhum item teve registro nesta reunião.")
        self.assertTrue(vazio["sintese"].startswith("Nenhum item tem registro nesta reunião (Quadro 1)."))

    def test_exercicio_sem_reuniao(self):
        Acompanhamento.objects.all().delete()
        Reuniao.objects.all().delete()
        exercicio = self.c["exercicio"]
        reuniao = resolver_reuniao(QueryDict(""), exercicio, hoje=HOJE)
        self.assertIsNone(reuniao)
        de, ate, _ = resolver_periodo(QueryDict(""), exercicio, None, hoje=HOJE)
        r = montar_relatorio_reuniao(exercicio=exercicio, reuniao=None, de=de, ate=ate, usuario=self.usuario, hoje=HOJE)
        self.assertEqual(r["titulo"], "Relatório de acompanhamento do PCA 2026")
        self.assertEqual(r["registros"]["itens"], 0)
        # Relatório de período (sem reunião): nada de "reunião cadastrada" nem de registros da reunião.
        self.assertNotIn("Não há reunião cadastrada", r["sintese"])
        self.assertNotIn("Quadro 1", r["sintese"])
        self.assertTrue(r["sintese"].startswith("No período,"))
        self.assertEqual(r["registros_texto"], "")
        self.assertEqual(r["secoes"], {"movimentacao": 4, "solicitacoes": 5})
        self.assertEqual(r["quadros"], {"situacao": 1})
        self.assertIn("(Quadro 1)", r["situacao_texto"])
        self.assertNotIn("Quadro 2", r["situacao_texto"])
        self.assertEqual(len(r["anexo_processos"]), 4)


def _col(rotulo, *segmentos, valor=None):
    total = sum(v for v, _ in segmentos)
    return {"rotulo": rotulo, "segmentos": list(segmentos), "valor": str(total) if valor is None else valor}


class GeometriaColunasTests(SimpleTestCase):
    def test_colunas_mais_altas_tocam_o_topo_e_ocupam_a_altura_da_area(self):
        g = _grafico_colunas([_col("A", (10, "abnt-cor-1")), _col("B", (10, "abnt-cor-2"))],
                             largura=300, altura_area=100, fracao=0.5)
        self.assertEqual(g["base_y"], "120.00")
        for coluna in g["colunas"]:
            self.assertEqual(coluna["segmentos"][0]["y"], "20.00")
            self.assertAlmostEqual(sum(float(s["h"]) for s in coluna["segmentos"]), 100.0)

    def test_segmentos_empilhados_na_ordem_e_zero_omitido(self):
        g = _grafico_colunas([_col("A", (5, "abnt-cor-1"), (0, "abnt-cor-2"), (5, "abnt-cor-3")), _col("B", (10, "abnt-cor-1"))],
                             largura=300, altura_area=100, fracao=0.5)
        primeiro, segundo = g["colunas"][0]["segmentos"]
        self.assertEqual((primeiro["classe"], segundo["classe"]), ("abnt-cor-1", "abnt-cor-3"))
        self.assertAlmostEqual(float(primeiro["y"]) + float(primeiro["h"]), float(g["base_y"]))
        self.assertAlmostEqual(float(segundo["y"]) + float(segundo["h"]), float(primeiro["y"]))

    def test_valor_minusculo_ganha_altura_minima_visivel(self):
        g = _grafico_colunas([_col("A", (1000, "abnt-cor-1")), _col("B", (1, "abnt-cor-1"))],
                             largura=300, altura_area=100, fracao=0.5)
        self.assertEqual(float(g["colunas"][1]["segmentos"][0]["h"]), ALTURA_MINIMA)
        self.assertEqual(ALTURA_MINIMA, 1.5)

    def test_colunas_em_fatias_iguais(self):
        g = _grafico_colunas([_col(r, (v, "abnt-cor-1")) for r, v in (("A", 4), ("B", 2), ("C", 3))],
                             largura=300, altura_area=100, fracao=0.4)
        centros = [float(c["x"]) for c in g["colunas"]]
        fatia = centros[1] - centros[0]
        self.assertAlmostEqual(centros[2] - centros[1], fatia, places=1)
        for coluna in g["colunas"]:
            self.assertAlmostEqual(float(coluna["segmentos"][0]["w"]), fatia * 0.4, places=1)
        ultima = g["colunas"][-1]["segmentos"][0]
        self.assertLess(float(ultima["x"]) + float(ultima["w"]), 300 - MARGEM)

    def test_rotulos_curtos_ficam_retos(self):
        g = _grafico_colunas([_col("Previsto", (10, "abnt-cor-3")), _col("Contratado", (4, "abnt-cor-1"))],
                             largura=604, altura_area=150, fracao=0.4)
        self.assertFalse(g["inclinado"])
        for coluna in g["colunas"]:
            self.assertEqual(coluna["transform"], "")
            self.assertEqual(float(coluna["rotulo_y"]), float(g["base_y"]) + 14)
        self.assertEqual(float(g["altura"]), TOPO + 150 + ZONA_ROTULO + 6)

    def test_rotulos_longos_inclinam_o_grafico_todo_sem_cruzar_a_borda(self):
        colunas = [_col(f"Unidade{i:02d}", (14 - i, "abnt-cor-1")) for i in range(14)]
        g = _grafico_colunas(colunas, largura=604, altura_area=180, fracao=0.6)
        self.assertTrue(g["inclinado"])
        for coluna in g["colunas"]:
            self.assertEqual(coluna["transform"], f"rotate(-45.00 {coluna['rotulo_x']} {coluna['rotulo_y']})")
        extensao = (9 * LARGURA_CARACTERE + ALTURA_TEXTO) * 0.71
        self.assertGreaterEqual(float(g["colunas"][0]["x"]) - extensao, 0)
        fatia = float(g["colunas"][1]["x"]) - float(g["colunas"][0]["x"])
        self.assertGreaterEqual(fatia * 0.71, 12)
        self.assertGreaterEqual(float(g["altura"]), TOPO + 180 + extensao)

    def test_um_rotulo_comprido_na_primeira_coluna_alarga_a_margem(self):
        colunas = [_col("Secretaria Executiva", (9, "abnt-cor-1"))] + [_col(f"U{i}", (3, "abnt-cor-1")) for i in range(14)]
        g = _grafico_colunas(colunas, largura=604, altura_area=100, fracao=0.6)
        self.assertTrue(g["inclinado"])
        self.assertGreaterEqual(float(g["colunas"][0]["x"]) - (20 * LARGURA_CARACTERE + ALTURA_TEXTO) * 0.71, 0)
        self.assertGreater(float(g["eixo_x1"]), MARGEM)

    def test_legenda_abaixo_dos_rotulos_e_centrada_na_area_das_colunas(self):
        colunas = [_col("A", (10, "abnt-cor-1")), _col("B", (5, "abnt-cor-2"))]
        sem = _grafico_colunas(colunas, largura=300, altura_area=100, fracao=0.5)
        legenda = [{"classe": "abnt-cor-1", "texto": "Concluído"}, {"classe": "abnt-cor-2", "texto": "Em tramitação"}]
        com = _grafico_colunas(colunas, largura=300, altura_area=100, fracao=0.5, legenda=legenda)
        self.assertEqual(float(com["altura"]) - float(sem["altura"]), ZONA_LEGENDA - 6)
        self.assertEqual(com["legenda"], legenda)
        self.assertEqual(float(com["legenda_y"]), float(com["base_y"]) + ZONA_ROTULO + 14)
        self.assertAlmostEqual(float(com["legenda_x"]), (float(com["eixo_x1"]) + float(com["eixo_x2"])) / 2, places=1)
        self.assertEqual(sem["legenda"], [])

    def test_lista_vazia_e_colunas_zeradas_nao_quebram(self):
        vazio = _grafico_colunas([], largura=604, altura_area=100, fracao=0.5)
        self.assertEqual(vazio["colunas"], [])
        zerado = _grafico_colunas([_col("A", (0, "abnt-cor-1")), _col("B")], largura=604, altura_area=100, fracao=0.5)
        self.assertEqual([c["segmentos"] for c in zerado["colunas"]], [[], []])


class TextosTests(SimpleTestCase):
    def test_referencias_no_texto(self):
        self.assertEqual(_referencias("Tabela", [3]), "Tabela 3")
        self.assertEqual(_referencias("Tabela", [3, 4]), "Tabelas 3 e 4")
        self.assertEqual(_referencias("Tabela", [3, 4, 5]), "Tabelas 3 a 5")
        self.assertEqual(_referencias("Tabela", [3, 5, 6]), "Tabelas 3, 5 e 6")


def _linha_uo(uo, ativos, concluido=0, tramitacao=0, prazo=0, atrasado=0):
    return {"uo": uo, "ativos": ativos, "concluido": concluido, "em_tramitacao_ativos": tramitacao,
            "no_prazo_ativos": prazo, "atrasado_ativos": atrasado}


class ColunasPorUnidadeTests(SimpleTestCase):
    def test_todas_as_unidades_com_ativos_ate_o_limite(self):
        linhas = [_linha_uo(f"U{i:02d}", 3 + (i % 4), concluido=1, tramitacao=1, prazo=1) for i in range(14)]
        linhas.append(_linha_uo("ZERO", 0))
        colunas, demais = _colunas_por_unidade(linhas)
        self.assertEqual(len(colunas), 14)
        self.assertEqual(demais, [])
        self.assertNotIn("ZERO", [c["rotulo"] for c in colunas])
        # ordem: ativos decrescente e, no empate, pelo nome
        esperada = [l["uo"] for l in sorted(linhas[:14], key=lambda l: (-l["ativos"], l["uo"]))]
        self.assertEqual([c["rotulo"] for c in colunas], esperada)

    def test_segmentos_e_total_de_cada_coluna(self):
        colunas, _ = _colunas_por_unidade([_linha_uo("GEX-A", 9, concluido=2, tramitacao=3, prazo=3, atrasado=1)])
        self.assertEqual(colunas[0]["segmentos"], [(2, "abnt-cor-1"), (3, "abnt-cor-2"), (4, "abnt-cor-3")])
        self.assertEqual(colunas[0]["valor"], "9")

    def test_acima_de_20_as_menores_viram_outras(self):
        linhas = [_linha_uo(f"U{i:02d}", 30 - i, concluido=1, tramitacao=2, prazo=3, atrasado=1) for i in range(25)]
        colunas, demais = _colunas_por_unidade(linhas)
        self.assertEqual(len(colunas), 20)
        self.assertEqual(len(demais), 6)
        self.assertEqual([c["rotulo"] for c in colunas[:19]], [f"U{i:02d}" for i in range(19)])
        ultima = colunas[-1]
        self.assertEqual(ultima["rotulo"], "Outras 6 unidades")
        self.assertEqual(ultima["segmentos"], [(6, "abnt-cor-1"), (12, "abnt-cor-2"), (24, "abnt-cor-3")])
        self.assertEqual(ultima["valor"], str(sum(30 - i for i in range(19, 25))))
        self.assertEqual([l["uo"] for l in demais], [f"U{i:02d}" for i in range(19, 25)])

    def test_exatamente_20_unidades_nao_agrupa(self):
        colunas, demais = _colunas_por_unidade([_linha_uo(f"U{i:02d}", 5) for i in range(20)])
        self.assertEqual((len(colunas), demais), (20, []))
