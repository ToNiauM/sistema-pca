"""Testes do módulo puro `apps.pca.sei.extenso` (Fase 32). `unittest.TestCase` simples, sem banco, sem Django — o
módulo é importável só com stdlib.
"""

import unittest
from decimal import Decimal

from apps.pca.sei.extenso import (
    cifra_para_decimal,
    inteiro_por_extenso,
    valor_por_extenso_para_decimal,
    valores_conferem,
)


class TestCifraParaDecimal(unittest.TestCase):
    def test_cifra_com_prefixo_rs(self):
        self.assertEqual(cifra_para_decimal("R$ 18.001,20"), Decimal("18001.20"))

    def test_cifra_tolera_espaco_variavel_apos_rs(self):
        self.assertEqual(cifra_para_decimal("R$  18.001,20"), Decimal("18001.20"))
        self.assertEqual(cifra_para_decimal("R$18.001,20"), Decimal("18001.20"))

    def test_cifra_sem_prefixo_tambem_funciona(self):
        self.assertEqual(cifra_para_decimal("18.001,20"), Decimal("18001.20"))

    def test_cifra_ilegivel_devolve_none_sem_lancar_excecao(self):
        self.assertIsNone(cifra_para_decimal("valor a combinar"))
        self.assertIsNone(cifra_para_decimal(""))
        self.assertIsNone(cifra_para_decimal(None))


class TestValorPorExtensoParaDecimal(unittest.TestCase):
    def test_dezoito_mil_e_um_reais_e_vinte_centavos(self):
        self.assertEqual(
            valor_por_extenso_para_decimal("dezoito mil e um reais e vinte centavos"),
            Decimal("18001.20"),
        )

    def test_trinta_e_sete_mil_reais_sem_centavos_vira_ponto_zero_zero(self):
        self.assertEqual(
            valor_por_extenso_para_decimal("trinta e sete mil reais"),
            Decimal("37000.00"),
        )

    def test_trinta_e_oito_mil_setecentos_e_trinta_e_um_reais_e_noventa_centavos(self):
        self.assertEqual(
            valor_por_extenso_para_decimal(
                "trinta e oito mil setecentos e trinta e um reais e noventa centavos"
            ),
            Decimal("38731.90"),
        )

    def test_cinquenta_e_quatro_mil_cento_e_cinquenta_e_seis_reais(self):
        self.assertEqual(
            valor_por_extenso_para_decimal(
                "cinquenta e quatro mil cento e cinquenta e seis reais"
            ),
            Decimal("54156.00"),
        )

    def test_tolera_espaco_interno_espurio_dentro_de_uma_palavra(self):
        """Defeito real de extração de HTML: "c inquenta" em vez de
        "cinquenta". Mesmo resultado do caso sem o defeito."""
        self.assertEqual(
            valor_por_extenso_para_decimal(
                "c inquenta e quatro mil cento e cinquenta e seis reais"
            ),
            Decimal("54156.00"),
        )

    def test_extenso_ilegivel_devolve_none_sem_lancar_excecao(self):
        self.assertIsNone(valor_por_extenso_para_decimal("texto qualquer sem valor"))
        self.assertIsNone(valor_por_extenso_para_decimal(""))
        self.assertIsNone(valor_por_extenso_para_decimal(None))

    def test_tolera_virgulas_entre_grupos_item_105(self):
        """Defeito real do UAT 18/09/2026 (item 105): o SEI escreve o
        extenso com vírgula entre cada grupo de milhar/milhão."""
        self.assertEqual(
            valor_por_extenso_para_decimal(
                "três milhões, oitocentos e trinta e dois mil, "
                "setecentos e quarenta reais"
            ),
            Decimal("3832740.00"),
        )

    def test_tolera_mil_e_setecentos(self):
        self.assertEqual(
            valor_por_extenso_para_decimal("dois mil e setecentos e quarenta reais"),
            Decimal("2740.00"),
        )

    def test_tolera_virgula_antes_de_reais(self):
        self.assertEqual(
            valor_por_extenso_para_decimal("dois mil e setecentos e quarenta, reais"),
            Decimal("2740.00"),
        )

    def test_um_milhao_de_reais(self):
        # Achado dados B1 (QA 30/09/2026) — "de" como conectivo entre
        # escala e "reais", sem casa decimal.
        self.assertEqual(
            valor_por_extenso_para_decimal("um milhão de reais"),
            Decimal("1000000.00"),
        )

    def test_dois_milhoes_de_reais_e_cinquenta_centavos(self):
        self.assertEqual(
            valor_por_extenso_para_decimal("dois milhões de reais e cinquenta centavos"),
            Decimal("2000000.50"),
        )


class TestValoresConferem(unittest.TestCase):
    def test_cifra_e_extenso_batendo_devolve_true(self):
        self.assertTrue(
            valores_conferem("R$ 18.001,20", "dezoito mil e um reais e vinte centavos")
        )

    def test_cifra_e_extenso_divergentes_devolve_false(self):
        self.assertFalse(valores_conferem("R$ 100,00", "noventa reais"))

    def test_um_dos_dois_ilegivel_devolve_false_sem_lancar_excecao(self):
        self.assertFalse(valores_conferem("texto qualquer", "dezoito mil reais"))
        self.assertFalse(valores_conferem("R$ 100,00", "texto qualquer"))

    def test_item_105_com_virgulas_entre_grupos_confere_com_a_cifra(self):
        self.assertTrue(
            valores_conferem(
                "R$ 3.832.740,00",
                "três milhões, oitocentos e trinta e dois mil, "
                "setecentos e quarenta reais",
            )
        )


class TestInteiroPorExtenso(unittest.TestCase):
    def test_doze(self):
        self.assertEqual(inteiro_por_extenso("doze"), 12)

    def test_vinte_e_quatro(self):
        self.assertEqual(inteiro_por_extenso("vinte e quatro"), 24)

    def test_sessenta(self):
        self.assertEqual(inteiro_por_extenso("sessenta"), 60)

    def test_texto_nao_numerico_devolve_none(self):
        self.assertIsNone(inteiro_por_extenso("texto qualquer sem número"))

    def test_texto_vazio_devolve_none(self):
        self.assertIsNone(inteiro_por_extenso(""))
        self.assertIsNone(inteiro_por_extenso(None))


if __name__ == "__main__":
    unittest.main()
