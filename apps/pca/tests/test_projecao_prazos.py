"""Testes do módulo puro `apps.pca.projecao.prazos` (Fase 36,
documento interno de desenho
§4). `unittest.TestCase` simples — sem banco, sem ORM, sem Django.
"""

import unittest
from datetime import date
from decimal import Decimal

from apps.pca.projecao.prazos import (
    calcular,
    data_provavel,
    lead_time_estratificado,
    lead_time_por_etapa,
    score_risco,
    sobrevivencia_km,
)


class TestLeadTimePorEtapa(unittest.TestCase):
    def test_mediana_p25_p75_p90_de_lista_conhecida(self):
        duracoes = [10, 12, 15, 20, 22, 25, 30]
        resultado = lead_time_por_etapa(duracoes)
        self.assertEqual(resultado["n"], 7)
        self.assertEqual(resultado["mediana"], Decimal(20))
        # interpolação linear (índice fracionário fracao*(n-1)):
        # p25 -> posição 1,5 -> 12 + (15-12)*0,5 = 13,5
        self.assertEqual(resultado["p25"], Decimal("13.5"))
        # p75 -> posição 4,5 -> 22 + (25-22)*0,5 = 23,5
        self.assertEqual(resultado["p75"], Decimal("23.5"))
        # p90 -> posição 5,4 -> 25 + (30-25)*0,4 = 27,0
        self.assertEqual(resultado["p90"], Decimal("27.0"))


class TestLeadTimeEstratificado(unittest.TestCase):
    def test_estrato_com_menos_de_cinco_casos_cai_para_o_geral_com_aviso(self):
        duracoes_geral = [10, 12, 15, 20, 22, 25, 30]
        duracoes_estrato = [10, 20]  # n=2, abaixo do limiar
        resultado = lead_time_estratificado(duracoes_estrato, duracoes_geral, "Unidade X")
        self.assertEqual(resultado["estrato"], "geral")
        self.assertIsNotNone(resultado["aviso"])
        self.assertEqual(resultado["mediana"], Decimal(20))  # veio do geral, não do estrato

    def test_estrato_com_cinco_ou_mais_casos_usa_o_proprio_estrato(self):
        duracoes_geral = [10, 12, 15, 20, 22, 25, 30]
        duracoes_estrato = [1, 2, 3, 4, 5]  # n=5, no limiar
        resultado = lead_time_estratificado(duracoes_estrato, duracoes_geral, "Unidade X")
        self.assertEqual(resultado["estrato"], "Unidade X")
        self.assertIsNone(resultado["aviso"])
        self.assertEqual(resultado["mediana"], Decimal(3))


class TestKaplanMeierDezPontos(unittest.TestCase):
    def test_sobrevivencia_de_dez_pontos_bate_com_o_produto_calculado_a_mao(self):
        # 5 concluídos (evento) em 5, 8, 8, 12, 20 dias; 5 abertos
        # (censurados) em 3, 6, 10, 15, 25 dias — "hoje" = 25 (maior valor
        # observado). Conta manual, mesma técnica do produto de
        # Kaplan-Meier (∏ 1 − d_i/n_i), processando os tempos em ordem:
        #
        # t=3  (censura) -> sai do risco, n 10->9, S inalterado
        # t=5  (evento, d=1, n=9)  -> S = 1 * (9-1)/9        = 8/9
        # t=6  (censura) -> n 8->7 (7 seguem em risco)
        # t=8  (evento, d=2, n=7)  -> S = 8/9 * (7-2)/7       = 8/9 * 5/7
        # t=10 (censura) -> n 5->4
        # t=12 (evento, d=1, n=4)  -> S = anterior * (4-1)/4  = anterior * 3/4
        # t=15 (censura) -> n 3->2
        # t=20 (evento, d=1, n=2)  -> S = anterior * (2-1)/2  = anterior * 1/2
        # t=25 (censura) -> n 1->0
        pontos = [
            (5, False), (8, False), (8, False), (12, False), (20, False),
            (3, True), (6, True), (10, True), (15, True), (25, True),
        ]
        curva = sobrevivencia_km(pontos)
        por_tempo = {p["t"]: p["s"] for p in curva}

        s_5 = Decimal(9 - 1) / Decimal(9)
        s_8 = s_5 * (Decimal(7 - 2) / Decimal(7))
        s_12 = s_8 * (Decimal(4 - 1) / Decimal(4))
        s_20 = s_12 * (Decimal(2 - 1) / Decimal(2))

        self.assertEqual(por_tempo[5], s_5)
        self.assertEqual(por_tempo[8], s_8)
        self.assertEqual(por_tempo[12], s_12)
        self.assertEqual(por_tempo[20], s_20)
        # só os 4 tempos de EVENTO entram na curva — censuras não geram ponto
        self.assertEqual(sorted(por_tempo), [5, 8, 12, 20])
        # n_risco/eventos batem com a conta manual acima
        self.assertEqual(curva[0]["n_risco"], 9)
        self.assertEqual(curva[1]["n_risco"], 7)
        self.assertEqual(curva[1]["eventos"], 2)


class TestScoreDeRisco(unittest.TestCase):
    _CURVA = sobrevivencia_km(
        [
            (5, False), (8, False), (8, False), (12, False), (20, False),
            (3, True), (6, True), (10, True), (15, True), (25, True),
        ]
    )

    def test_score_dentro_de_zero_e_um_quando_a_formula_e_positiva(self):
        # S(20) < S(5) nesta curva (sobrevivência decrescente) — a fórmula
        # da spec §4.2 (score = 1 − S(t_prazo)/S(t_hoje)) só produz um valor
        # positivo informativo quando S(t_prazo) < S(t_hoje); aqui
        # t_prazo=20, t_hoje=5.
        resultado = score_risco(t_prazo=20, t_hoje=5, curva=self._CURVA)
        self.assertGreaterEqual(resultado["score"], Decimal("0"))
        self.assertLessEqual(resultado["score"], Decimal("1"))
        self.assertGreater(resultado["score"], Decimal("0"))
        self.assertIn(resultado["faixa"], ("baixo", "medio", "alto"))
        self.assertIn("n", resultado)
        self.assertIn("estrato", resultado)
        self.assertIn("metodo", resultado)

    def test_score_nunca_fica_negativo_quando_a_formula_crua_seria_negativa(self):
        # t_prazo=5, t_hoje=20 -> S(t_prazo) > S(t_hoje) -> razão > 1 ->
        # 1 - razão < 0 antes do clamp; o resultado tem de ficar em 0.
        resultado = score_risco(t_prazo=5, t_hoje=20, curva=self._CURVA)
        self.assertEqual(resultado["score"], Decimal("0"))

    def test_multiplicador_com_historico_suficiente_e_aplicado(self):
        com_historico = score_risco(
            t_prazo=20, t_hoje=5, curva=self._CURVA,
            multiplicadores=[{"valor": Decimal("1.2"), "n": 8}],
        )
        sem_multiplicador = score_risco(t_prazo=20, t_hoje=5, curva=self._CURVA)
        self.assertGreater(com_historico["score"], sem_multiplicador["score"])
        self.assertEqual(com_historico["n"], 8)

    def test_multiplicador_sem_historico_suficiente_e_ignorado(self):
        com_pouco_historico = score_risco(
            t_prazo=20, t_hoje=5, curva=self._CURVA,
            multiplicadores=[{"valor": Decimal("1.2"), "n": 3}],  # n < 5
        )
        sem_multiplicador = score_risco(t_prazo=20, t_hoje=5, curva=self._CURVA)
        self.assertEqual(com_pouco_historico["score"], sem_multiplicador["score"])
        self.assertEqual(com_pouco_historico["n"], 0)


class TestDataProvavel(unittest.TestCase):
    def test_devolve_intervalo_nunca_data_unica(self):
        resultado = data_provavel(date(2026, 9, 19), dias_p25=10, dias_p75=30, n=8, estrato="geral")
        self.assertIsInstance(resultado["p25"], date)
        self.assertIsInstance(resultado["p75"], date)
        self.assertLessEqual(resultado["p25"], resultado["p75"])
        self.assertIn("n", resultado)
        self.assertIn("estrato", resultado)
        self.assertIn("metodo", resultado)


class TestContratoNEstratoMetodo(unittest.TestCase):
    def test_todo_bloco_de_calcular_carrega_n_estrato_e_metodo(self):
        itens_concluidos = [
            {"duracao_gelic_assinatura": d, "dias_ate_assinatura": d, "modalidade": "Pregão"}
            for d in [10, 12, 15, 20, 22, 25, 30]
        ]
        itens_abertos = [
            {
                "item_pca": 1,
                "dias_em_aberto": 5,
                "t_prazo": 20,
                "tempo_restante_p25": 5,
                "tempo_restante_p75": 15,
                "regime_execucao": "continuado",
                "renovacao_prevista": True,
                "vigencia_fim": date(2026, 12, 1),
            },
        ]
        resultado = calcular(itens_concluidos, itens_abertos, hoje=date(2026, 9, 19))

        self.assertIn("n", resultado["lead_time"]["geral"])
        self.assertIn("estrato", resultado["lead_time"]["geral"])
        self.assertIn("metodo", resultado["lead_time"]["geral"])

        for bloco in resultado["lead_time"]["por_modalidade"].values():
            self.assertIn("n", bloco)
            self.assertIn("estrato", bloco)
            self.assertIn("metodo", bloco)

        self.assertIn("n", resultado["sobrevivencia"]["geral"])
        self.assertIn("estrato", resultado["sobrevivencia"]["geral"])
        self.assertIn("metodo", resultado["sobrevivencia"]["geral"])

        self.assertTrue(resultado["risco"])
        for item_risco in resultado["risco"]:
            self.assertIn("n", item_risco)
            self.assertIn("estrato", item_risco)
            self.assertIn("metodo", item_risco)
            self.assertIn("n", item_risco["data_provavel"])
            self.assertIn("estrato", item_risco["data_provavel"])
            self.assertIn("metodo", item_risco["data_provavel"])

    def test_vincendos_lista_item_continuado_com_renovacao_prevista_no_horizonte(self):
        itens_abertos = [
            {
                "item_pca": 2,
                "regime_execucao": "continuado",
                "renovacao_prevista": True,
                "vigencia_fim": date(2026, 11, 1),  # ~43 dias de 19/09
            },
            {
                "item_pca": 3,
                "regime_execucao": "unico",  # não entra — não é continuado
                "renovacao_prevista": True,
                "vigencia_fim": date(2026, 11, 1),
            },
        ]
        resultado = calcular([], itens_abertos, hoje=date(2026, 9, 19))
        item_pcas_90 = [v["item_pca"] for v in resultado["vincendos"]["90"]]
        self.assertIn(2, item_pcas_90)
        self.assertNotIn(3, item_pcas_90)


if __name__ == "__main__":
    unittest.main()
