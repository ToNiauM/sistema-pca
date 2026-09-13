"""Testes do módulo puro `apps.pca.regras_situacao`. `unittest.TestCase`
simples — o módulo é puro, sem banco, sem ORM.
"""

import unittest
from datetime import date

from apps.pca.regras_situacao import situacao_inicial, situacao_por_eventos


class TestSituacaoPorEventos(unittest.TestCase):
    def test_tipo_vigente_e_sempre_concluido_independente_de_qualquer_data(self):
        """Vigente é concluído por natureza."""
        self.assertEqual(
            situacao_por_eventos(
                tipo_nome_normalizado="vigente",
                data_assinatura_contrato=None,
                data_recebimento_gelic=None,
            ),
            "concluido",
        )

    def test_assinatura_conclui_nova_contratacao_e_renovacao(self):
        """Assinatura conclui tanto Nova Contratação quanto Renovação."""
        for tipo in ("nova contratacao", "renovacao"):
            with self.subTest(tipo=tipo):
                self.assertEqual(
                    situacao_por_eventos(
                        tipo_nome_normalizado=tipo,
                        data_assinatura_contrato=date(2026, 6, 1),
                        data_recebimento_gelic=None,
                    ),
                    "concluido",
                )

    def test_recebimento_gelic_e_em_tramitacao_mesmo_fora_do_prazo(self):
        """A função nem recebe prazo; prova por assinatura que a regra
        nunca olha timing, inclusive quando o recebimento é posterior a um
        prazo hipotético."""
        self.assertEqual(
            situacao_por_eventos(
                tipo_nome_normalizado="nova contratacao",
                data_assinatura_contrato=None,
                data_recebimento_gelic=date(2030, 1, 1),
            ),
            "em_tramitacao",
        )

    def test_sem_nenhum_fato_gravado_nao_ha_alvo_automatico(self):
        """Sem fatos, retorna None; nunca ATRASADO sob nenhuma combinação
        de argumentos."""
        self.assertIsNone(
            situacao_por_eventos(
                tipo_nome_normalizado="nova contratacao",
                data_assinatura_contrato=None,
                data_recebimento_gelic=None,
            )
        )

    def test_nunca_retorna_atrasado_em_nenhuma_combinacao_booleana(self):
        """Varredura das 4 combinações booleanas de assinatura/
        recebimento; a função nunca devolve 'atrasado'."""
        assinatura_opcoes = (None, date(2026, 1, 1))
        recebimento_opcoes = (None, date(2026, 1, 1))
        for assinatura in assinatura_opcoes:
            for recebimento in recebimento_opcoes:
                with self.subTest(assinatura=assinatura, recebimento=recebimento):
                    resultado = situacao_por_eventos(
                        tipo_nome_normalizado="nova contratacao",
                        data_assinatura_contrato=assinatura,
                        data_recebimento_gelic=recebimento,
                    )
                    self.assertNotEqual(resultado, "atrasado")


class TestSituacaoInicial(unittest.TestCase):
    def test_prazo_vencido_sem_evento_e_atrasado(self):
        """prazo_entrega anterior a hoje, sem evento gravado."""
        hoje = date(2026, 8, 28)
        self.assertEqual(
            situacao_inicial(
                tipo_nome_normalizado="nova contratacao",
                data_assinatura_contrato=None,
                data_recebimento_gelic=None,
                prazo_entrega=date(2026, 8, 27),
                hoje=hoje,
            ),
            "atrasado",
        )

    def test_prazo_futuro_sem_evento_e_no_prazo(self):
        hoje = date(2026, 8, 28)
        self.assertEqual(
            situacao_inicial(
                tipo_nome_normalizado="nova contratacao",
                data_assinatura_contrato=None,
                data_recebimento_gelic=None,
                prazo_entrega=date(2026, 8, 29),
                hoje=hoje,
            ),
            "no_prazo",
        )

    def test_sem_prazo_entrega_e_no_prazo_por_padrao(self):
        """'sem prazo_entrega ⇒ NO PRAZO por padrão'."""
        hoje = date(2026, 8, 28)
        self.assertEqual(
            situacao_inicial(
                tipo_nome_normalizado="nova contratacao",
                data_assinatura_contrato=None,
                data_recebimento_gelic=None,
                prazo_entrega=None,
                hoje=hoje,
            ),
            "no_prazo",
        )

    def test_prazo_vigente_tem_prioridade_sobre_prazo_entrega_no_fallback(self):
        """`prazo_efetivo = COALESCE(prazo_vigente, prazo_entrega)`: a
        promessa vigente (mais recente) vence sobre `prazo_entrega`, mesmo
        quando `prazo_entrega` está no futuro ou ausente."""
        hoje = date(2026, 8, 28)
        self.assertEqual(
            situacao_inicial(
                tipo_nome_normalizado="nova contratacao",
                data_assinatura_contrato=None,
                data_recebimento_gelic=None,
                prazo_entrega=date(2026, 12, 1),  # futuro
                prazo_vigente=date(2026, 8, 27),  # vencido
                hoje=hoje,
            ),
            "atrasado",
        )
        self.assertEqual(
            situacao_inicial(
                tipo_nome_normalizado="nova contratacao",
                data_assinatura_contrato=None,
                data_recebimento_gelic=None,
                prazo_entrega=None,
                prazo_vigente=date(2026, 8, 27),  # vencido
                hoje=hoje,
            ),
            "atrasado",
        )

    def test_evento_gravado_tem_precedencia_sobre_prazo_vencido(self):
        """Assinatura preenchida retorna CONCLUIDO mesmo com
        prazo_entrega vencido; situacao_inicial primeiro tenta
        situacao_por_eventos, só cai no fallback de prazo se este devolver
        None."""
        hoje = date(2026, 8, 28)
        self.assertEqual(
            situacao_inicial(
                tipo_nome_normalizado="nova contratacao",
                data_assinatura_contrato=date(2026, 6, 1),
                data_recebimento_gelic=None,
                prazo_entrega=date(2026, 8, 27),
                hoje=hoje,
            ),
            "concluido",
        )


if __name__ == "__main__":
    unittest.main()
