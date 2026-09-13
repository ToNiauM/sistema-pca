"""Legenda paginada (legend.type="scroll") vive só no tema
`echarts-dsgov.js`, nunca em `core/graficos.py`.

O ECharts faz merge profundo entre o tema registrado e a opção de cada
gráfico. Este teste prova que o contrato Python permanece mínimo: se
`legend.type` passar a ser declarado direto em `core/graficos.py`, a
paginação do tema estaria sendo duplicada silenciosamente.
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
