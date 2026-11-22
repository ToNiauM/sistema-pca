"""Legenda paginada (legend.type="scroll") vive só no tema
`echarts-dsgov.js`, nunca em `core/graficos.py`.

O ECharts faz merge PROFUNDO entre o tema registrado (`echarts.registerTheme("dsgov", tema)`) e a
opção de cada gráfico — é o MESMO mecanismo que já hoje aplica `icon: "roundRect"`/`itemWidth: 12`
a toda legenda sem que `colunas()`/`linha()`/`rosca()` declarem nada disso (eles só passam
`{"bottom": 0}` ou `{"show": False}`). Este teste prova que o contrato Python permanece mínimo:
se algum dia `legend.type` passar a ser declarado direto em `core/graficos.py`, é sinal de que a
paginação do tema está sendo blindada/duplicada silenciosamente — o fix da legenda sobreposta
(card "UO por mês", 14+ séries) deve continuar vivendo inteiramente no tema compartilhado.
"""

from django.test import SimpleTestCase

from core.graficos import colunas, linha, rosca


class TestLegendaMultiSerieNaoBlindaOTema(SimpleTestCase):
    def test_colunas_multi_serie_nao_declara_type_de_legenda(self):
        opcoes = colunas(["Jan", "Fev"], {"A": [1, 2], "B": [3, 4]})
        self.assertNotIn("type", opcoes["legend"])

    def test_linha_multi_serie_nao_declara_type_de_legenda(self):
        opcoes = linha(["Jan", "Fev"], {"A": [1, 2], "B": [3, 4]})
        self.assertNotIn("type", opcoes["legend"])

    def test_rosca_nao_declara_type_de_legenda(self):
        opcoes = rosca([("A", 1), ("B", 2)])
        self.assertNotIn("type", opcoes["legend"])

    def test_colunas_uma_serie_so_continua_com_legenda_oculta(self):
        self.assertEqual(colunas(["Jan"], {"A": [1]})["legend"], {"show": False})


class TestColunasComLinhaSobreposta(SimpleTestCase):
    """Fase 37 (spec §3.4) — `linha=` acrescenta série(s) `line`
    sobrepostas às barras empilhadas, sem quebrar nenhuma chamada
    pré-existente (parâmetro opcional, default `None`)."""

    def test_linha_none_preserva_comportamento_atual(self):
        opcoes = colunas(["Jan"], {"A": [1]}, empilhado=True)
        self.assertEqual(len(opcoes["series"]), 1)
        self.assertEqual(opcoes["series"][0]["type"], "bar")

    def test_linha_acrescenta_serie_line_sem_stack_nem_label(self):
        opcoes = colunas(
            ["Jan", "Fev"],
            {"A": [1, 2]},
            empilhado=True,
            linha={"Oficial": [3, 4]},
        )
        series_line = [s for s in opcoes["series"] if s["type"] == "line"]
        self.assertEqual(len(series_line), 1)
        self.assertEqual(series_line[0]["name"], "Oficial")
        self.assertEqual(series_line[0]["data"], [3, 4])
        self.assertNotIn("stack", series_line[0])
        self.assertNotIn("label", series_line[0])
        # a série de barras original continua intacta
        series_bar = [s for s in opcoes["series"] if s["type"] == "bar"]
        self.assertEqual(len(series_bar), 1)
        self.assertEqual(series_bar[0]["stack"], "total")


class RoscaRotuloExternoTest(SimpleTestCase):
    """Valor e percentual fora do anel, com linha-guia, em todas as fatias."""

    def test_rotulo_externo_com_linha_guia_em_todas_as_fatias(self):
        serie = rosca([("A", 1), ("B", 99)], rotulo_externo=True)["series"][0]
        self.assertEqual(serie["label"]["position"], "outside")
        self.assertEqual(serie["label"]["formatter"], "{c} ({d}%)")
        self.assertTrue(serie["labelLine"]["show"])
        self.assertEqual(serie["minShowLabelAngle"], 0)
        self.assertEqual(serie["percentPrecision"], 0)

    def test_formato_valor_vai_pronto_em_cada_fatia(self):
        dados = rosca([("A", 1500.5)], rotulo_externo=True, formato_valor=lambda v: f"R$ {v:.0f}")["series"][0]["data"]
        self.assertEqual(dados[0]["label"]["formatter"], "R$ 1500 ({d}%)")
