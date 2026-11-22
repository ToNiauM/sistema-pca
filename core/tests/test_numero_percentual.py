"""Filtros `numero`/`percentual` (padrão DSGov) — QA 30/09 (domínio nº5):
`formats.number_format` do Django FATIA a string decimal em vez de
arredondar (`dec_part[:decimal_pos]`), então a tela mostrava um percentual
truncado enquanto o XLSX do mesmo número (quantizado com ROUND_HALF_UP,
`core/db.py::quantizar_soma`) mostrava arredondado — ex.: card "Da meta" do
Início, 68 de 105 concluídos: tela "64,7%", XLSX "64,8%"."""

from decimal import Decimal

from django.test import SimpleTestCase

from core.templatetags.dsgov import numero, percentual


class TestFiltroNumeroArredondaAoInvesDeTruncar(SimpleTestCase):
    def test_numero_arredonda_duas_terças_partes(self):
        self.assertEqual(numero(Decimal("2") / Decimal("3") * 100, 1), "66,7")

    def test_percentual_68_de_105_bate_com_o_xlsx(self):
        # 68/105 = 0,6476190...; ×100 = 64,76190...; arredondado a 1 casa =
        # 64,8 — o par exato tela/XLSX do achado (tela truncava para
        # "64,7%").
        self.assertEqual(percentual(Decimal(68) / Decimal(105) * 100, 1), "64,8%")

    def test_numero_arredonda_para_cima_no_limite_do_milhao(self):
        self.assertEqual(numero(Decimal("999999.95")), "1.000.000")

    def test_vazio_continua_travessao(self):
        self.assertEqual(numero(None), "—")
        self.assertEqual(numero(""), "—")
