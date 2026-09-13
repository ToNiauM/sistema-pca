"""Filtro `moeda()` sem o prefixo "R$".

Testes diretos do filtro, sem passar por request/template: `moeda()` é
consumido por vários templates e pelo pré-preenchimento dos campos
monetários editáveis — testá-lo isoladamente cobre todos os call sites.
"""

from decimal import Decimal

from django.test import SimpleTestCase

from core.templatetags.formatos import badge_percentual, moeda, moeda_curta, percentual_inteiro


class TestFiltroMoeda(SimpleTestCase):
    def test_none_vira_string_vazia(self):
        self.assertEqual(moeda(None), "")

    def test_string_vazia_vira_string_vazia(self):
        self.assertEqual(moeda(""), "")

    def test_valor_grande_formata_com_milhar_e_sem_prefixo(self):
        self.assertEqual(moeda(Decimal("162642475.66")), "162.642.475,66")

    def test_valor_redondo_formata_com_duas_casas(self):
        self.assertEqual(moeda(Decimal("10000")), "10.000,00")

    def test_negativo_mantem_o_sinal_antes_do_numero(self):
        self.assertEqual(moeda(Decimal("-1234.56")), "-1.234,56")

    def test_entrada_invalida_vira_string_vazia(self):
        self.assertEqual(moeda("não é número"), "")


class TestFiltroMoedaCurta(SimpleTestCase):
    def test_milhoes_usam_uma_casa_e_sufixo_mi(self):
        self.assertEqual(moeda_curta(Decimal("165400000")), "165,4 mi")

    def test_milhares_usam_uma_casa_e_sufixo_mil(self):
        self.assertEqual(moeda_curta(Decimal("12400")), "12,4 mil")

    def test_valor_abaixo_de_mil_mantem_precisao_monetaria(self):
        self.assertEqual(moeda_curta(Decimal("999.5")), "999,50")

    def test_valor_negativo_mantem_sinal(self):
        self.assertEqual(moeda_curta(Decimal("-1200000")), "-1,2 mi")

    def test_entrada_invalida_vira_string_vazia(self):
        self.assertEqual(moeda_curta("não é número"), "")


class TestFiltroPercentualInteiro(SimpleTestCase):
    """`percentual_inteiro` é o mesmo arredondamento de `badge_percentual`
    (`f"{Decimal:.0f}"`, HALF_EVEN), sem o sufixo; `"0"` quando sem base
    ou inválido. Provado por igualdade: `badge == inteiro + "%"`."""

    CASOS = (
        (Decimal("12.5"), "12"),
        (Decimal("13.5"), "14"),
        (Decimal("86.4"), "86"),
        (Decimal("0"), "0"),
    )

    def test_arredonda_como_badge_percentual_sem_sufixo(self):
        for valor, esperado in self.CASOS:
            with self.subTest(valor=str(valor)):
                self.assertEqual(percentual_inteiro(valor), esperado)

    def test_sem_base_ou_invalido_vira_zero(self):
        self.assertEqual(percentual_inteiro(None), "0")
        self.assertEqual(percentual_inteiro("x"), "0")

    def test_identidade_com_badge_percentual(self):
        for valor, _ in self.CASOS:
            with self.subTest(valor=str(valor)):
                self.assertEqual(badge_percentual(valor), percentual_inteiro(valor) + "%")
