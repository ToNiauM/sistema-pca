"""Testes do módulo puro `apps.pca.projecao.virada` (Fase 38). `unittest.TestCase` simples — sem banco, sem ORM (mesmo padrão de
`test_regras_situacao.py`).

Uma asserção por linha da tabela §3 da spec + fronteiras + exercício futuro
+ renovação encadeada + `hoje` como parâmetro + `contagem`/`GRUPOS_DESTINO`.
"""

import inspect
import unittest
from collections import Counter
from datetime import date

from apps.pca.projecao import virada
from apps.pca.projecao.virada import (
    CHAVES_DESTINO,
    GRUPOS_DESTINO,
    Destino,
    contagem,
    destino,
    parametros_n1,
)


class TestTabelaDestinos(unittest.TestCase):
    """N=2026, hoje=19/09/2026 — as 7 linhas da tabela §3."""

    N = 2026
    HOJE = date(2026, 9, 19)

    def test_tabela_linha_1_vencido_independe_da_renovacao(self):
        vigencia_fim = date(2026, 9, 1)
        self.assertIs(
            destino(vigencia_fim, True, self.N, self.HOJE), Destino.VENCIDO
        )
        self.assertIs(
            destino(vigencia_fim, False, self.N, self.HOJE), Destino.VENCIDO
        )

    def test_tabela_linha_2_encerra_n(self):
        self.assertIs(
            destino(date(2026, 12, 31), False, self.N, self.HOJE),
            Destino.ENCERRA_N,
        )

    def test_tabela_linha_3_renova_n(self):
        self.assertIs(
            destino(date(2026, 12, 31), True, self.N, self.HOJE),
            Destino.RENOVA_N,
        )

    def test_tabela_linha_4_renovacao_n1(self):
        self.assertIs(
            destino(date(2027, 6, 30), True, self.N, self.HOJE),
            Destino.RENOVACAO_N1,
        )

    def test_tabela_linha_5_encerra_n1(self):
        self.assertIs(
            destino(date(2027, 6, 30), False, self.N, self.HOJE),
            Destino.ENCERRA_N1,
        )

    def test_tabela_linha_6_vigente_n1_com_renovacao_true(self):
        self.assertIs(
            destino(date(2028, 3, 15), True, self.N, self.HOJE),
            Destino.VIGENTE_N1,
        )

    def test_tabela_linha_7_vigente_n1_com_renovacao_false(self):
        self.assertIs(
            destino(date(2028, 3, 15), False, self.N, self.HOJE),
            Destino.VIGENTE_N1,
        )


class TestFronteiras(unittest.TestCase):
    N = 2026
    HOJE = date(2026, 9, 19)

    def test_fronteira_31_12_n_e_linha_n(self):
        self.assertIs(
            destino(date(2026, 12, 31), False, self.N, self.HOJE),
            Destino.ENCERRA_N,
        )
        self.assertIs(
            destino(date(2026, 12, 31), True, self.N, self.HOJE),
            Destino.RENOVA_N,
        )

    def test_fronteira_01_01_n1_e_linha_n1(self):
        self.assertIs(
            destino(date(2027, 1, 1), False, self.N, self.HOJE),
            Destino.ENCERRA_N1,
        )
        self.assertIs(
            destino(date(2027, 1, 1), True, self.N, self.HOJE),
            Destino.RENOVACAO_N1,
        )

    def test_fronteira_31_12_n1_e_linha_n1(self):
        self.assertIs(
            destino(date(2027, 12, 31), False, self.N, self.HOJE),
            Destino.ENCERRA_N1,
        )
        self.assertIs(
            destino(date(2027, 12, 31), True, self.N, self.HOJE),
            Destino.RENOVACAO_N1,
        )

    def test_fronteira_01_01_n2_e_vigente_n1(self):
        self.assertIs(
            destino(date(2028, 1, 1), False, self.N, self.HOJE),
            Destino.VIGENTE_N1,
        )
        self.assertIs(
            destino(date(2028, 1, 1), True, self.N, self.HOJE),
            Destino.VIGENTE_N1,
        )

    def test_vigencia_fim_igual_hoje_nao_e_vencido(self):
        """`vigencia_fim == hoje` (19/09/2026) NÃO é VENCIDO — cai em
        ENCERRA_N/RENOVA_N conforme RN."""
        self.assertIs(
            destino(self.HOJE, False, self.N, self.HOJE), Destino.ENCERRA_N
        )
        self.assertIs(
            destino(self.HOJE, True, self.N, self.HOJE), Destino.RENOVA_N
        )


class TestExercicioFuturo(unittest.TestCase):
    def test_exercicio_futuro_classifica_como_n(self):
        """N=2027, hoje=19/09/2026, vigencia_fim=31/12/2026 (year < N,
        >= hoje) → classifica como "== N" (última frase)."""
        hoje = date(2026, 9, 19)
        vigencia_fim = date(2026, 12, 31)
        self.assertIs(
            destino(vigencia_fim, False, 2027, hoje), Destino.ENCERRA_N
        )
        self.assertIs(
            destino(vigencia_fim, True, 2027, hoje), Destino.RENOVA_N
        )


class TestRenovacaoEncadeada(unittest.TestCase):
    def test_renovacao_encadeada_nasce_renovacao_n1_nunca_vigente(self):
        """N=2026, hoje=19/09/2026, item renovado em 2026 com nova
        vigencia_fim=30/06/2027 e RN=True → RENOVACAO_N1 (nunca
        VIGENTE_N1); o mesmo item com RN=False → ENCERRA_N1."""
        hoje = date(2026, 9, 19)
        nova_vigencia_fim = date(2027, 6, 30)
        self.assertIs(
            destino(nova_vigencia_fim, True, 2026, hoje),
            Destino.RENOVACAO_N1,
        )
        self.assertIs(
            destino(nova_vigencia_fim, False, 2026, hoje),
            Destino.ENCERRA_N1,
        )


class TestHojeEParametro(unittest.TestCase):
    def test_hoje_e_parametro(self):
        """Mesma vigencia_fim=31/12/2026, RN=True, N=2026 — com
        hoje=19/09/2026 → RENOVA_N; com hoje=05/01/2027 → VENCIDO (o
        resultado muda só porque `hoje` mudou)."""
        vigencia_fim = date(2026, 12, 31)
        self.assertIs(
            destino(vigencia_fim, True, 2026, date(2026, 9, 19)),
            Destino.RENOVA_N,
        )
        self.assertIs(
            destino(vigencia_fim, True, 2026, date(2027, 1, 5)),
            Destino.VENCIDO,
        )


class TestContagem(unittest.TestCase):
    def test_contagem_vazia_devolve_seis_chaves_em_zero(self):
        resultado = contagem([])
        self.assertEqual(len(resultado), 6)
        for d in Destino:
            self.assertEqual(resultado[d], 0)

    def test_contagem_soma_por_destino(self):
        resultado = contagem(
            [Destino.VENCIDO, Destino.VENCIDO, Destino.RENOVA_N]
        )
        self.assertEqual(resultado[Destino.VENCIDO], 2)
        self.assertEqual(resultado[Destino.RENOVA_N], 1)
        for d in Destino:
            if d not in (Destino.VENCIDO, Destino.RENOVA_N):
                self.assertEqual(resultado[d], 0)


class TestPorChaveEChavesDestino(unittest.TestCase):
    def test_por_chave_devolve_o_membro_correspondente(self):
        self.assertIs(Destino.por_chave("renovacao_n1"), Destino.RENOVACAO_N1)

    def test_por_chave_desconhecida_devolve_none(self):
        self.assertIsNone(Destino.por_chave("x"))

    def test_chaves_destino_na_ordem_canonica(self):
        self.assertEqual(
            CHAVES_DESTINO,
            (
                "vencido",
                "encerra_n",
                "renova_n",
                "renovacao_n1",
                "encerra_n1",
                "vigente_n1",
            ),
        )


class TestGruposDestino(unittest.TestCase):
    def test_grupos_destino_particionam_os_seis_destinos(self):
        """As 4 chaves exatas e a união dos 4 grupos == os 6 destinos, sem
        interseção (prova pura de C01)."""
        self.assertEqual(
            set(GRUPOS_DESTINO.keys()),
            {"encerramento_n", "renovacao_n", "renovacao_n1", "vigente_n1"},
        )
        vistos = []
        for membros in GRUPOS_DESTINO.values():
            vistos.extend(membros)
        self.assertEqual(len(vistos), len(set(vistos)), "sem interseção")
        self.assertEqual(set(vistos), set(Destino))


class TestParametrosN1(unittest.TestCase):
    """Fase 40 (spec §0) — uma asserção por linha da tabela + `VIGENTE_N1`
    sem mês na origem (`None` → 1) + os três destinos que não geram (`None`
    do parâmetro inteiro, não `(None, None, None)`)."""

    def test_renovacao_n1_no_prazo_mes_do_vencimento(self):
        self.assertEqual(
            parametros_n1(Destino.RENOVACAO_N1, date(2027, 3, 31), 9),
            ("renovacao", "no_prazo", 3),
        )

    def test_encerra_n1_concluido_mes_do_vencimento(self):
        self.assertEqual(
            parametros_n1(Destino.ENCERRA_N1, date(2027, 5, 31), 9),
            ("vigente", "concluido", 5),
        )

    def test_vigente_n1_concluido_mes_da_origem(self):
        self.assertEqual(
            parametros_n1(Destino.VIGENTE_N1, date(2028, 12, 31), 7),
            ("vigente", "concluido", 7),
        )

    def test_vigente_n1_sem_mes_da_origem_cai_em_janeiro(self):
        self.assertEqual(
            parametros_n1(Destino.VIGENTE_N1, date(2028, 12, 31), None),
            ("vigente", "concluido", 1),
        )

    def test_vencido_nao_gera(self):
        self.assertIsNone(
            parametros_n1(Destino.VENCIDO, date(2026, 9, 1), 3)
        )

    def test_encerra_n_nao_gera(self):
        self.assertIsNone(
            parametros_n1(Destino.ENCERRA_N, date(2026, 12, 31), 3)
        )

    def test_renova_n_nao_gera(self):
        self.assertIsNone(
            parametros_n1(Destino.RENOVA_N, date(2026, 12, 31), 3)
        )


class TestModuloPuro(unittest.TestCase):
    def test_modulo_nao_importa_django(self):
        fonte = inspect.getsource(virada)
        self.assertNotIn("django", fonte)

    def test_modulo_nao_usa_relogio_do_sistema(self):
        fonte = inspect.getsource(virada)
        self.assertNotIn("date.today", fonte)
        self.assertNotIn("localdate", fonte)

    def test_modulo_nao_usa_jargao_firme(self):
        fonte = inspect.getsource(virada)
        self.assertNotIn("firme", fonte)


if __name__ == "__main__":
    unittest.main()
