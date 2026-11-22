"""Testes do módulo puro `apps.pca.projecao.simulacao` (Fase 37, Plano
37-05, documento interno de desenho §3.1/§10). `unittest.TestCase` simples — mesmo padrão de
`test_projecao_fluxo.py`: o módulo é puro, sem banco, sem ORM, sem Django.
Fixtures (`_item`/`_contrato`/`_parametros`) reaproveitadas de
`test_projecao_fluxo.py` (mesmo padrão de dado que `simulacao.aplicar`
consome, já calibrado ao contrato de `fluxo.py`)."""

import copy
import json
import unittest
from datetime import date
from decimal import Decimal

from apps.pca.projecao import simulacao
from apps.pca.tests.test_projecao_fluxo import _contrato, _item, _parametros


class TestAplicarNaoMutaEntrada(unittest.TestCase):
    def test_aplicar_nunca_muta_entrada(self):
        item = _item(
            item_pca=7,
            renovacao_prevista=False,
            contratos=[_contrato(instrumento="principal", valor=Decimal("1000.00"))],
        )
        itens = [item]
        parametros = _parametros(indices={2027: Decimal("10")}, lead_time_mediano_dias=90)

        itens_esperado = copy.deepcopy(itens)
        indices_esperado = dict(parametros.indices)

        ajustes = simulacao.Ajustes(
            indices_por_ano={2028: Decimal("15")},
            itens_excluidos=set(),
            renovacao_por_item={7: True},
            valor_por_item={7: Decimal("2000.00")},
            inicio_por_item={},
            lead_time_dias=45,
        )

        simulacao.aplicar(itens, parametros, ajustes)

        self.assertEqual(itens, itens_esperado)
        self.assertEqual(parametros.indices, indices_esperado)
        self.assertEqual(parametros.lead_time_mediano_dias, 90)


class TestItemExcluido(unittest.TestCase):
    def test_item_excluido_nao_aparece_na_saida(self):
        itens = [_item(item_pca=7), _item(item_pca=8)]
        parametros = _parametros()
        ajustes = simulacao.Ajustes(itens_excluidos={7})

        itens2, _ = simulacao.aplicar(itens, parametros, ajustes)

        self.assertEqual([i["item_pca"] for i in itens2], [8])


class TestRenovacaoForcada(unittest.TestCase):
    def test_renovacao_forcada_sobrescreve_o_valor_oficial(self):
        itens = [
            _item(
                item_pca=7,
                renovacao_prevista=False,
                contratos=[_contrato(vigencia_inicio=date(2026, 1, 1))],
            )
        ]
        parametros = _parametros()
        ajustes = simulacao.Ajustes(renovacao_por_item={7: True})

        itens2, _ = simulacao.aplicar(itens, parametros, ajustes)

        self.assertIs(itens2[0]["renovacao_prevista"], True)


class TestIndicePorAno(unittest.TestCase):
    def test_indice_por_ano_sobrescreve_so_o_ano_editado(self):
        itens = [_item(item_pca=7)]
        parametros = _parametros(indices={2027: Decimal("10")})
        ajustes = simulacao.Ajustes(indices_por_ano={2028: Decimal("15")})

        _, parametros2 = simulacao.aplicar(itens, parametros, ajustes)

        self.assertEqual(
            parametros2.indices, {2027: Decimal("10"), 2028: Decimal("15")}
        )


class TestLeadTimeDias(unittest.TestCase):
    def test_lead_time_dias_sobrescreve_o_padrao(self):
        itens = [_item(item_pca=7)]
        parametros = _parametros(lead_time_mediano_dias=90)
        ajustes = simulacao.Ajustes(lead_time_dias=45)

        _, parametros2 = simulacao.aplicar(itens, parametros, ajustes)

        self.assertEqual(parametros2.lead_time_mediano_dias, 45)


class TestValorPorItemContratado(unittest.TestCase):
    def test_valor_por_item_contratado_sobrescreve_o_contrato_principal(self):
        itens = [
            _item(
                item_pca=7,
                contratos=[
                    _contrato(
                        instrumento="principal",
                        valor=Decimal("1000.00"),
                        periodicidade="mensal",
                    )
                ],
            )
        ]
        parametros = _parametros()
        ajustes = simulacao.Ajustes(valor_por_item={7: Decimal("2000.00")})

        itens2, _ = simulacao.aplicar(itens, parametros, ajustes)

        self.assertEqual(itens2[0]["contratos"][0]["valor"], Decimal("2000.00"))
        self.assertEqual(itens2[0]["contratos"][0]["periodicidade"], "mensal")


class TestValorPorItemPlanejado(unittest.TestCase):
    def test_valor_por_item_planejado_sobrescreve_valor_estimado(self):
        itens = [_item(item_pca=7, valor_estimado=Decimal("1000.00"), contratos=[])]
        parametros = _parametros()
        ajustes = simulacao.Ajustes(valor_por_item={7: Decimal("3000.00")})

        itens2, _ = simulacao.aplicar(itens, parametros, ajustes)

        self.assertEqual(itens2[0]["valor_estimado"], Decimal("3000.00"))


class TestInicioPorItemPlanejado(unittest.TestCase):
    def test_inicio_por_item_planejado_desloca_a_referencia(self):
        itens = [_item(item_pca=7, mes_previsto=6, contratos=[])]
        parametros = _parametros()
        ajustes = simulacao.Ajustes(
            inicio_por_item={7: date(2027, 1, 1)}, lead_time_dias=30
        )

        itens2, parametros2 = simulacao.aplicar(itens, parametros, ajustes)

        self.assertEqual(parametros2.lead_time_mediano_dias, 30)
        self.assertIsNone(itens2[0]["mes_previsto"])
        self.assertEqual(itens2[0]["prazo_efetivo"], date(2026, 12, 2))


class TestSerializacao(unittest.TestCase):
    def _ajustes_completo(self):
        return simulacao.Ajustes(
            indices_por_ano={2027: Decimal("10"), 2028: Decimal("15.5")},
            itens_excluidos={7, 12},
            renovacao_por_item={7: True, 8: False},
            valor_por_item={7: Decimal("2000.00")},
            inicio_por_item={7: date(2027, 1, 1)},
            lead_time_dias=45,
        )

    def test_de_json_para_json_roundtrip(self):
        a = self._ajustes_completo()

        self.assertEqual(simulacao.de_json(simulacao.para_json(a)), a)

    def test_para_json_e_serializavel_por_json_dumps(self):
        a = self._ajustes_completo()

        json.dumps(simulacao.para_json(a))  # não deve lançar

    def test_de_json_nunca_lanca_com_entrada_malformada(self):
        malformado = {
            "indices_por_ano": "não é um dict",
            "itens_excluidos": {"não": "é lista"},
            "renovacao_por_item": ["não", "é", "dict"],
            "valor_por_item": {"abc": "não é decimal"},
            "inicio_por_item": {"7": "não é data"},
            "lead_time_dias": "quarenta e cinco",
        }

        self.assertEqual(simulacao.de_json(malformado), simulacao.vazio())
        self.assertEqual(simulacao.de_json(None), simulacao.vazio())
        self.assertEqual(simulacao.de_json("string qualquer"), simulacao.vazio())

    def test_de_json_descarta_percentual_e_valor_nao_finitos(self):
        # QA 30/09/2026 (achado INFO I2) — `Decimal("NaN")`/`Decimal(
        # "Infinity")` são construções VÁLIDAS (não levantam
        # `InvalidOperation`), então sobreviviam a `_dict_ano_decimal`/
        # `_dict_int_decimal` e só explodiam depois, numa comparação.
        resultado = simulacao.de_json(
            {
                "indices_por_ano": {"2027": "NaN"},
                "valor_por_item": {"1": "Infinity"},
            }
        )

        self.assertEqual(resultado, simulacao.vazio())


class TestDescrever(unittest.TestCase):
    def test_descrever_lista_cada_variavel_alterada(self):
        a = simulacao.Ajustes(
            indices_por_ano={2028: Decimal("15")},
            itens_excluidos={7},
        )

        linhas = simulacao.descrever(a, {7: "Serviço de limpeza"})

        self.assertGreaterEqual(len(linhas), 2)
        self.assertTrue(any("2028" in l and "15" in l for l in linhas))
        self.assertTrue(any("Serviço de limpeza" in l or "Item 7" in l for l in linhas))


if __name__ == "__main__":
    unittest.main()
