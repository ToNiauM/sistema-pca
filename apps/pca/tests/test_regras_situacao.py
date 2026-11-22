"""Testes do módulo puro `apps.pca.regras_situacao` (Fase 17). `unittest.TestCase` simples — o módulo é puro, sem banco, sem ORM.
"""

import unittest
from datetime import date

from apps.pca.regras_situacao import (
    regime_presumido_migracao,
    regime_presumido_projecao,
    situacao_inicial,
    situacao_por_eventos,
)


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
        """Sem fatos, retorna None; nunca ATRASADO sob nenhuma
        combinação de argumentos."""
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
        """Prazo_entrega anterior a hoje, sem evento gravado."""
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
        """emendada (29/08/2026) — `prazo_efetivo = COALESCE(prazo_vigente,
        prazo_entrega)`: a promessa vigente (mais recente) vence sobre
        `prazo_entrega`, mesmo quando `prazo_entrega` está no futuro ou
        ausente."""
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


class TestRegimePresumido(unittest.TestCase):
    """Fase 36 (spec §2.1) — as DUAS funções
    puras que presumem `regime_execucao`, com limiares deliberadamente
    diferentes: 11 meses para `regime_presumido_migracao` (só a migração
    0027), 12 meses para `regime_presumido_projecao` (só `apps.pca.
    projecao.fluxo`). Mesmo conjunto de vigências nos dois
    limiares prova que eles realmente divergem entre 11 e 12 meses."""

    def test_migracao_onze_meses_exatos_e_continuado(self):
        self.assertEqual(
            regime_presumido_migracao(date(2025, 1, 1), date(2025, 12, 1)),
            "continuado",
        )

    def test_migracao_dez_meses_e_vinte_nove_dias_e_unico(self):
        self.assertEqual(
            regime_presumido_migracao(date(2025, 1, 1), date(2025, 11, 30)),
            "unico",
        )

    def test_migracao_sem_vigencia_fim_e_none(self):
        self.assertIsNone(regime_presumido_migracao(date(2025, 1, 1), None))

    def test_migracao_sem_vigencia_inicio_e_none(self):
        self.assertIsNone(regime_presumido_migracao(None, date(2025, 12, 1)))

    def test_projecao_onze_meses_e_unico_limiar_diferente_da_migracao(self):
        """Limiar 12 (projeção): os mesmos 11 meses que `_migracao` classifica
        como `continuado` aqui são `unico` — prova a divergência 11 vs. 12."""
        self.assertEqual(
            regime_presumido_projecao(date(2025, 1, 1), date(2025, 12, 1)),
            "unico",
        )

    def test_projecao_doze_meses_exatos_e_continuado(self):
        self.assertEqual(
            regime_presumido_projecao(date(2025, 1, 1), date(2026, 1, 1)),
            "continuado",
        )

    def test_projecao_sem_vigencia_e_none(self):
        self.assertIsNone(regime_presumido_projecao(date(2025, 1, 1), None))
        self.assertIsNone(regime_presumido_projecao(None, None))


if __name__ == "__main__":
    unittest.main()


class TestRecebimentoGelicSoContaNoAnoDoPCA(unittest.TestCase):
    """29/09/2026 (decisão do usuário) — NC/RN só está em tramitação se o recebimento no Gelic é do
    ano do PCA; recebimento de ano anterior (processo SEI reaproveitado) não conta."""

    def _situacao(self, recebimento, **extra):
        return situacao_por_eventos(
            tipo_nome_normalizado="renovacao",
            data_assinatura_contrato=None,
            data_recebimento_gelic=recebimento,
            ano_exercicio=2026,
            **extra,
        )

    def test_recebimento_no_ano_poe_em_tramitacao(self):
        self.assertEqual(self._situacao(date(2026, 9, 17)), "em_tramitacao")

    def test_recebimento_de_ano_anterior_nao_conta(self):
        self.assertIsNone(self._situacao(date(2022, 9, 2)))
        self.assertIsNone(self._situacao(date(2025, 12, 17)))

    def test_sem_ano_exercicio_mantem_o_comportamento_antigo(self):
        self.assertEqual(
            situacao_por_eventos(
                tipo_nome_normalizado="renovacao",
                data_assinatura_contrato=None,
                data_recebimento_gelic=date(2022, 9, 2),
            ),
            "em_tramitacao",
        )
