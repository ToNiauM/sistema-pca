"""Testes do módulo puro `apps.pca.projecao.estatistica` (Fase 36, Plano
36-02, documento interno de desenho
§5). `unittest.TestCase` simples — sem banco, sem ORM, sem Django.
"""

import unittest
from datetime import date
from decimal import Decimal

from apps.pca.projecao.estatistica import calcular, valores, vigencia


class TestParetoOitentaPorCento(unittest.TestCase):
    def test_tres_maiores_somam_exatamente_oitenta_por_cento(self):
        # total = 1000; os 3 maiores (500+200+100=800) somam exatamente 80%
        itens = [
            {"valor_contratado": v, "uo": "UO", "valor_estimado": None, "modalidade": None, "razao_social": None}
            for v in (Decimal(x) for x in [500, 200, 100, 50, 40, 30, 30, 20, 20, 10])
        ]
        resultado = valores(itens)
        self.assertEqual(resultado["pareto_80"], 3)


class TestFaixasDeDuracao(unittest.TestCase):
    def test_duracoes_conhecidas_caem_nas_faixas_corretas(self):
        def _item(inicio, fim):
            return {
                "vigencia_inicio": inicio, "vigencia_fim": fim,
                "item_pca": 1, "valor_mensal": None,
            }

        itens = [
            _item(date(2026, 1, 1), date(2026, 3, 31)),   # 3 meses  -> 0-6
            _item(date(2026, 1, 1), date(2026, 6, 30)),   # 6 meses  -> 0-6
            _item(date(2026, 1, 1), date(2026, 7, 31)),   # 7 meses  -> 7-12
            _item(date(2026, 1, 1), date(2026, 12, 31)),  # 12 meses -> 7-12
            _item(date(2026, 1, 1), date(2027, 1, 31)),   # 13 meses -> 13-24
            _item(date(2026, 1, 1), date(2027, 12, 31)),  # 24 meses -> 13-24
            _item(date(2026, 1, 1), date(2028, 1, 31)),   # 25 meses -> 25-60
            _item(date(2026, 1, 1), date(2030, 12, 31)),  # 60 meses -> 25-60
            _item(date(2026, 1, 1), date(2031, 1, 31)),   # 61 meses -> acima_de_60
            _item(date(2026, 6, 1), date(2026, 1, 1)),    # invertida -> ignorada (nenhuma faixa)
        ]
        resultado = vigencia(itens)
        self.assertEqual(
            resultado["faixas_duracao"],
            {"0-6": 2, "7-12": 2, "13-24": 2, "25-60": 2, "acima_de_60": 1},
        )


class TestDesvioMedianoPorModalidade(unittest.TestCase):
    def test_mediana_p25_p75_n_por_modalidade_e_estrato_com_menos_de_cinco_e_sinalizado(self):
        def _item(estimado, contratado, modalidade):
            return {
                "valor_estimado": Decimal(estimado), "valor_contratado": Decimal(contratado),
                "modalidade": modalidade, "uo": "UO", "razao_social": None,
            }

        itens = [
            # Pregão: n=5 (>= limiar) -> estrato próprio
            _item(100, 110, "Pregão"),  # desvio  10 p.p.
            _item(100, 90, "Pregão"),   # desvio -10 p.p.
            _item(100, 120, "Pregão"),  # desvio  20 p.p.
            _item(100, 100, "Pregão"),  # desvio   0 p.p.
            _item(100, 105, "Pregão"),  # desvio   5 p.p.
            # Dispensa: n=2 (< limiar) -> cai no pool GERAL (7 desvios: os
            # 5 de Pregão + os 2 desta modalidade)
            _item(100, 110, "Dispensa"),  # desvio  10 p.p.
            _item(100, 90, "Dispensa"),   # desvio -10 p.p.
        ]
        resultado = valores(itens)
        desvio = resultado["desvio_por_modalidade"]

        # Pregão: estatística sobre a PRÓPRIA modalidade, em pontos
        # percentuais (M08 — nunca frações cruas).
        self.assertEqual(desvio["Pregão"]["n"], 5)
        self.assertEqual(desvio["Pregão"]["n_modalidade"], 5)
        self.assertEqual(desvio["Pregão"]["estrato"], "Pregão")
        self.assertEqual(desvio["Pregão"]["mediana"], Decimal("5.00"))
        self.assertEqual(desvio["Pregão"]["p25"], Decimal("0.00"))
        self.assertEqual(desvio["Pregão"]["p75"], Decimal("10.00"))

        # Dispensa: n=2 na própria modalidade (< limiar) -> fallback REAL
        # para o pool geral de 7 desvios (M08 — não é só o rótulo que
        # muda: a mediana/p25/p75 vêm do pool geral, não da modalidade).
        desvios_geral_esperado = sorted(
            [Decimal("10.00"), Decimal("-10.00"), Decimal("20.00"), Decimal("0.00"), Decimal("5.00"),
             Decimal("10.00"), Decimal("-10.00")]
        )
        import statistics as _statistics
        self.assertEqual(desvio["Dispensa"]["n"], 7)
        self.assertEqual(desvio["Dispensa"]["n_modalidade"], 2)
        self.assertEqual(desvio["Dispensa"]["estrato"], "geral")
        self.assertEqual(
            desvio["Dispensa"]["mediana"], _statistics.median(desvios_geral_esperado)
        )

    def test_aceite_melhorias_md_estimado_100_contratado_120_mostra_20_por_cento(self):
        # Caso de aceite de `melhorias.md` §M08: um único item (n=1, cai no
        # "geral" que com 1 item é ele mesmo) tem de mostrar 20,0% na tela,
        # nunca 0,2% (bug do desvio armazenado como fração crua).
        itens = [
            {
                "valor_estimado": Decimal("100"), "valor_contratado": Decimal("120"),
                "modalidade": "Pregão", "uo": "UO", "razao_social": None,
            },
        ]
        resultado = valores(itens)
        desvio = resultado["desvio_por_modalidade"]["Pregão"]
        self.assertEqual(desvio["mediana"], Decimal("20.00"))
        self.assertEqual(desvio["estrato"], "geral")
        self.assertEqual(desvio["n"], 1)
        self.assertEqual(desvio["n_modalidade"], 1)


class TestCalcularOrquestrador(unittest.TestCase):
    def test_combina_os_tres_blocos(self):
        itens = [
            {
                "valor_contratado": Decimal("1000"), "valor_estimado": Decimal("900"),
                "modalidade": "Pregão", "uo": "UO", "razao_social": "Fornecedor A",
                "vigencia_inicio": date(2026, 1, 1), "vigencia_fim": date(2026, 12, 31),
                "valor_mensal": Decimal("100"), "item_pca": 1,
            },
        ]
        resultado = calcular(itens)
        self.assertIn("valores", resultado)
        self.assertIn("vigencia", resultado)
        self.assertIn("perfil", resultado)


if __name__ == "__main__":
    unittest.main()
