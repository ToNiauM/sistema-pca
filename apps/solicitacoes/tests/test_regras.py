"""Regras puras das Solicitações (..07) — sem banco."""

from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from apps.pca.models import Estado, Situacao
from apps.solicitacoes import regras
from apps.solicitacoes.regras import Alcada, Campo, Decisao, EstadoParte, EstadoSolicitacao


class TestLiteraisEspelhados(SimpleTestCase):
    def test_literais_batem_com_os_enums_do_pca(self):
        self.assertEqual(regras.ESTADO_ATIVO, Estado.ATIVO)
        self.assertEqual(regras.SITUACAO_NO_PRAZO, Situacao.NO_PRAZO)
        self.assertEqual(regras.SITUACAO_ATRASADO, Situacao.ATRASADO)
        self.assertEqual(regras.SITUACAO_EM_TRAMITACAO, Situacao.EM_TRAMITACAO)
        self.assertEqual(regras.SITUACAO_CONCLUIDO, Situacao.CONCLUIDO)


class TestAlcadas(SimpleTestCase):
    def test_d43_02_prazo_e_mes_sao_da_equipe_o_resto_da_diretoria(self):
        self.assertEqual(regras.alcada_do_campo(Campo.PRAZO_ENTREGA), Alcada.EQUIPE)
        self.assertEqual(regras.alcada_do_campo(Campo.MES_PREVISTO), Alcada.EQUIPE)
        for campo in (Campo.VALOR_ESTIMADO, Campo.DESCRICAO_OBJETO, Campo.CANCELAMENTO, Campo.INCLUSAO):
            self.assertEqual(regras.alcada_do_campo(campo), Alcada.DIRETORIA)

    def test_cada_um_so_a_sua_alcada_e_quem_esta_nos_dois_decide_tudo(self):
        self.assertTrue(regras.pode_decidir(Alcada.EQUIPE, equipe=True, diretoria=False))
        self.assertFalse(regras.pode_decidir(Alcada.DIRETORIA, equipe=True, diretoria=False))
        self.assertTrue(regras.pode_decidir(Alcada.DIRETORIA, equipe=False, diretoria=True))
        self.assertFalse(regras.pode_decidir(Alcada.EQUIPE, equipe=False, diretoria=True))
        self.assertTrue(regras.pode_decidir(Alcada.EQUIPE, equipe=True, diretoria=True))
        self.assertTrue(regras.pode_decidir(Alcada.DIRETORIA, equipe=True, diretoria=True))
        self.assertFalse(regras.pode_decidir(Alcada.EQUIPE, equipe=False, diretoria=False))


class TestCamposAceitos(SimpleTestCase):
    def _aceitos(self, situacao, estado="ativo", aberto=True):
        return set(regras.campos_aceitos(estado=estado, situacao_efetiva=situacao, exercicio_aberto=aberto))

    def test_d43_06_a_entregar_aceita_tudo(self):
        esperado = {
            Campo.PRAZO_ENTREGA, Campo.MES_PREVISTO, Campo.VALOR_ESTIMADO,
            Campo.DESCRICAO_OBJETO, Campo.CANCELAMENTO,
        }
        self.assertEqual(self._aceitos("no_prazo"), esperado)
        self.assertEqual(self._aceitos("atrasado"), esperado)

    def test_d43_06_em_tramitacao_nao_aceita_prazo_nem_mes(self):
        self.assertEqual(
            self._aceitos("em_tramitacao"),
            {Campo.VALOR_ESTIMADO, Campo.DESCRICAO_OBJETO, Campo.CANCELAMENTO},
        )

    def test_d43_06_concluido_cancelado_e_exercicio_fechado_nao_aceitam_nada(self):
        self.assertEqual(self._aceitos("concluido"), set())
        self.assertEqual(self._aceitos("no_prazo", estado="cancelado"), set())
        self.assertEqual(self._aceitos("no_prazo", aberto=False), set())

    def test_motivo_do_item_fechado(self):
        self.assertIn("fechado", regras.motivo_do_item_fechado(
            estado="ativo", situacao_efetiva="no_prazo", exercicio_aberto=False))
        self.assertIn("cancelado", regras.motivo_do_item_fechado(
            estado="cancelado", situacao_efetiva="no_prazo", exercicio_aberto=True))
        self.assertIn("concluído", regras.motivo_do_item_fechado(
            estado="ativo", situacao_efetiva="concluido", exercicio_aberto=True))

    def test_d43_06_fora_do_exercicio(self):
        self.assertFalse(regras.fora_do_exercicio(date(2026, 12, 31), 2026))
        self.assertTrue(regras.fora_do_exercicio(date(2027, 1, 1), 2026))


class TestPedido(SimpleTestCase):
    def test_d43_03_varios_campos_de_alteracao_combinam(self):
        regras.validar_pedido([Campo.PRAZO_ENTREGA, Campo.VALOR_ESTIMADO])
        self.assertEqual(
            regras.tipo_do_pedido([Campo.PRAZO_ENTREGA, Campo.VALOR_ESTIMADO]), "alteracao"
        )

    def test_d43_03_cancelamento_e_exclusivo(self):
        regras.validar_pedido([Campo.CANCELAMENTO])
        self.assertEqual(regras.tipo_do_pedido([Campo.CANCELAMENTO]), "cancelamento")
        with self.assertRaisesMessage(ValueError, "sozinho"):
            regras.validar_pedido([Campo.CANCELAMENTO, Campo.PRAZO_ENTREGA])

    def test_pedido_vazio_ou_com_inclusao_e_invalido(self):
        with self.assertRaises(ValueError):
            regras.validar_pedido([])
        with self.assertRaises(ValueError):
            regras.validar_pedido([Campo.INCLUSAO])

    def test_campo_desconhecido_levanta(self):
        with self.assertRaises(ValueError):
            regras.validar_pedido(["cor_do_item"])


class TestValores(SimpleTestCase):
    def test_normaliza_cada_campo(self):
        self.assertEqual(regras.normalizar_valor(Campo.PRAZO_ENTREGA, "2026-11-30"), date(2026, 11, 30))
        self.assertEqual(regras.normalizar_valor(Campo.PRAZO_ENTREGA, date(2026, 11, 30)), date(2026, 11, 30))
        self.assertEqual(regras.normalizar_valor(Campo.MES_PREVISTO, "7"), 7)
        self.assertEqual(regras.normalizar_valor(Campo.VALOR_ESTIMADO, "1500.5"), Decimal("1500.50"))
        self.assertEqual(regras.normalizar_valor(Campo.DESCRICAO_OBJETO, "  Serviço   de TI "), "Serviço de TI")

    def test_recusa_valores_ruins(self):
        for campo, bruto in (
            (Campo.PRAZO_ENTREGA, "31/11/2026"),
            (Campo.MES_PREVISTO, "13"),
            (Campo.MES_PREVISTO, "abc"),
            (Campo.VALOR_ESTIMADO, "0"),
            (Campo.VALOR_ESTIMADO, "-3"),
            (Campo.VALOR_ESTIMADO, "NaN"),
            (Campo.VALOR_ESTIMADO, "x"),
            (Campo.DESCRICAO_OBJETO, "   "),
            (Campo.CANCELAMENTO, "qualquer"),
        ):
            with self.subTest(campo=campo, bruto=bruto), self.assertRaises(ValueError):
                regras.normalizar_valor(campo, bruto)

    def test_texto_estavel_ida_e_volta(self):
        casos = (
            (Campo.PRAZO_ENTREGA, date(2026, 3, 9), "2026-03-09"),
            (Campo.MES_PREVISTO, 4, "4"),
            (Campo.VALOR_ESTIMADO, Decimal("1234.5"), "1234.50"),
            (Campo.DESCRICAO_OBJETO, "Objeto", "Objeto"),
        )
        for campo, valor, texto in casos:
            with self.subTest(campo=campo):
                self.assertEqual(regras.para_texto(campo, valor), texto)
                self.assertEqual(regras.de_texto(campo, texto), valor)
        self.assertEqual(regras.para_texto(Campo.PRAZO_ENTREGA, None), "")
        self.assertIsNone(regras.de_texto(Campo.PRAZO_ENTREGA, ""))


class TestDecisao(SimpleTestCase):
    def test_d43_04_aprovar_nao_exige_motivo(self):
        estado, concedido, motivo = regras.validar_decisao(
            Campo.MES_PREVISTO, Decisao.APROVAR, valor_pedido=8
        )
        self.assertEqual((estado, concedido, motivo), (EstadoParte.APROVADA, 8, ""))

    def test_d43_04_ajuste_exige_motivo_e_valor_diferente_do_pedido(self):
        with self.assertRaisesMessage(ValueError, "motivo"):
            regras.validar_decisao(Campo.MES_PREVISTO, Decisao.AJUSTE, valor_ajuste=9, valor_pedido=8)
        with self.assertRaisesMessage(ValueError, "igual ao pedido"):
            regras.validar_decisao(
                Campo.MES_PREVISTO, Decisao.AJUSTE, motivo="x", valor_ajuste=8, valor_pedido=8
            )
        estado, concedido, motivo = regras.validar_decisao(
            Campo.MES_PREVISTO, Decisao.AJUSTE, motivo=" mês 9 cabe ", valor_ajuste="9", valor_pedido=8
        )
        self.assertEqual((estado, concedido, motivo), (EstadoParte.APROVADA_AJUSTE, 9, "mês 9 cabe"))

    def test_d43_04_recusa_exige_motivo(self):
        with self.assertRaisesMessage(ValueError, "motivo"):
            regras.validar_decisao(Campo.VALOR_ESTIMADO, Decisao.RECUSAR)
        estado, concedido, _ = regras.validar_decisao(
            Campo.VALOR_ESTIMADO, Decisao.RECUSAR, motivo="sem verba"
        )
        self.assertEqual((estado, concedido), (EstadoParte.RECUSADA, None))

    def test_cancelamento_e_inclusao_so_aprovam_ou_recusam(self):
        for campo in (Campo.CANCELAMENTO, Campo.INCLUSAO):
            self.assertEqual(regras.decisoes_admitidas(campo), (Decisao.APROVAR, Decisao.RECUSAR))
            with self.assertRaises(ValueError):
                regras.validar_decisao(campo, Decisao.AJUSTE, motivo="x", valor_ajuste="y")

    def test_decisao_desconhecida(self):
        with self.assertRaises(ValueError):
            regras.validar_decisao(Campo.MES_PREVISTO, "devolver")


class TestFechamentoEFila(SimpleTestCase):
    def test_d43_03_fecha_quando_nenhuma_parte_esta_pendente(self):
        self.assertEqual(
            regras.estado_da_solicitacao(["aprovada", "pendente"]), EstadoSolicitacao.PENDENTE
        )
        self.assertEqual(
            regras.estado_da_solicitacao(["aprovada", "recusada"]), EstadoSolicitacao.CONCLUIDA
        )
        self.assertEqual(
            regras.estado_da_solicitacao(["prejudicada", "prejudicada"]), EstadoSolicitacao.CONCLUIDA
        )
        self.assertEqual(
            regras.estado_da_solicitacao(["desistida", "desistida"]), EstadoSolicitacao.DESISTIDA
        )
        self.assertEqual(
            regras.estado_da_solicitacao(["aprovada", "desistida"]), EstadoSolicitacao.CONCLUIDA
        )

    def test_dias_uteis_pulam_fim_de_semana(self):
        sexta, segunda = date(2026, 10, 9), date(2026, 10, 12)
        self.assertEqual(regras.dias_uteis_entre(sexta, segunda), 1)
        self.assertEqual(regras.dias_uteis_entre(date(2026, 10, 5), date(2026, 10, 12)), 5)
        self.assertEqual(regras.dias_uteis_entre(segunda, segunda), 0)

    def test_d43_11_parada_e_mais_de_10_dias_uteis(self):
        inicio = date(2026, 10, 5)  # segunda
        self.assertFalse(regras.esta_parada(inicio, date(2026, 10, 19)))  # 10 dias úteis
        self.assertTrue(regras.esta_parada(inicio, date(2026, 10, 20)))  # 11
