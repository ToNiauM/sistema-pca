"""Filtro `data_br` (padrão DSGov) converte datetime ciente para o fuso da
aplicação antes de formatar — bug de 19/09/2026: "Última atualização" nas telas
aparecia 3 h à frente (UTC do banco formatado sem `timezone.localtime`)."""

from datetime import date, datetime, timezone as dt_timezone

from django.test import SimpleTestCase, override_settings

from core.templatetags.dsgov import data_br


@override_settings(TIME_ZONE="America/Sao_Paulo", USE_TZ=True)
class TestFiltroDataBr(SimpleTestCase):
    def test_datetime_utc_e_convertido_para_o_fuso_da_aplicacao(self):
        # 04:47 UTC == 01:47 em Brasília (-03:00).
        valor = datetime(2026, 9, 19, 4, 47, tzinfo=dt_timezone.utc)
        self.assertEqual(data_br(valor), "19/09/2026 01:47")

    def test_datetime_que_vira_o_dia_ao_converter(self):
        # 01:30 UTC do dia 20 == 22:30 do dia 19 em Brasília.
        valor = datetime(2026, 9, 20, 1, 30, tzinfo=dt_timezone.utc)
        self.assertEqual(data_br(valor), "19/09/2026 22:30")

    def test_datetime_ingenuo_e_formatado_como_esta(self):
        self.assertEqual(data_br(datetime(2026, 9, 19, 1, 47)), "19/09/2026 01:47")

    def test_date_nao_ganha_hora(self):
        self.assertEqual(data_br(date(2026, 9, 19)), "19/09/2026")

    def test_vazio_vira_travessao(self):
        self.assertEqual(data_br(None), "—")
        self.assertEqual(data_br(""), "—")
