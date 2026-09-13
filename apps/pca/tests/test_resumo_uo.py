"""Contrato de `apps/pca/resumo_uo.py`/`apps/pca/exportacao_resumo_uo.py`.
Cobre:

- `calcular_resumo_uo(qs)` — chaves (`meta`, `concluido_meta`, `no_prazo`,
  `fora_prazo` + percentuais /meta), fechamento do bloco META
  (concluido_meta + em_tramitacao + no_prazo + fora_prazo == meta, por
  construção — `Situacao` tem exatamente 4 valores), bases de percentual
  (/meta no bloco META, /ativos na análise "Total Concluído"), zero-safe
  com meta == 0, linha TOTAL, 1 única consulta agregada.
- `/resumo-uo` — 200 autenticado, redireciona login anônimo, nº de linhas,
  drill-down por célula (hrefs consolidados batendo com /tabela), cabeçalho
  em blocos (Previsto ‖ Por tipo ‖ Meta do PCA ‖ Análise) com siglas
  NC/RN/VG e "Total Concluído".
- `exportar_resumo_uo_xlsx(linhas, total)` + `/exportar/resumo-uo` — "-"
  literal para denominador zero / percentual calculável como número
  fração 0–1 com `number_format` FORMATO_PERCENTUAL, blocos espelhando a
  tela, linha de legenda das siglas, sem fórmula viva.

Verificação manual do usuário (golden numbers de produção, nunca
automatizar aqui — dependem do banco vivo): meta total = 112, concluídos
da meta = 20, a cumprir (em tramitação + no prazo + fora do prazo) = 92.
"""

import re
from decimal import Decimal
from io import BytesIO
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils.html import escape
from openpyxl import load_workbook

from apps.catalogo.models import Categoria, Exercicio, Tipo, Unidade
from apps.pca.exportacao_resumo_uo import COLUNAS as COLUNAS_XLSX
from apps.pca.exportacao_resumo_uo import (
    FORMATO_PERCENTUAL,
    exportar_resumo_uo_xlsx,
)
from apps.pca.filtros import queryset_filtrado
from apps.pca.models import Estado, Processo, Situacao
from apps.pca.resumo_uo import calcular_resumo_uo


class _BaseResumoUO(TestCase):
    """Fixture compartilhada: 2 UOs, 3 tipos (Nova Contratação/Renovação/
    Vigente) nos `nome_normalizado` que `calcular_resumo_uo` resolve, 1
    exercício (o mesmo `ano=2026` seedado pela migração de dados
    `0008_backfill_exercicio_2026`, reaproveitado por toda a suíte)."""

    @classmethod
    def setUpTestData(cls):
        cls.exercicio = Exercicio.objects.get(ano=2026)
        cls.uo_a = Unidade.objects.create(nome="GEX-ITEC")
        cls.uo_b = Unidade.objects.create(nome="GEX-LIC")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.tipo_nova = Tipo.objects.create(nome="Nova Contratação")
        cls.tipo_renovacao = Tipo.objects.create(nome="Renovação")
        cls.tipo_vigente = Tipo.objects.create(nome="Vigente")

    def _criar_processo(self, item_pca, uo, tipo, **kwargs):
        defaults = {
            "descricao_objeto": f"Objeto {item_pca}",
            "categoria": self.categoria,
            "unidade_organizacional": uo,
            "tipo": tipo,
            "estado": Estado.ATIVO,
        }
        defaults.update(kwargs)
        return Processo.objects.create(
            item_pca=item_pca, exercicio=self.exercicio, **defaults
        )


class TestCalcularResumoUO(_BaseResumoUO):
    def test_contagem_por_coluna_e_linha_total(self):
        # UO A: 2 Nova (1 concluído, 1 no prazo), 1 Renovação atrasada.
        self._criar_processo(
            1, self.uo_a, self.tipo_nova, situacao=Situacao.CONCLUIDO
        )
        self._criar_processo(
            2, self.uo_a, self.tipo_nova, situacao=Situacao.NO_PRAZO
        )
        self._criar_processo(
            3, self.uo_a, self.tipo_renovacao, situacao=Situacao.ATRASADO
        )
        # UO A também tem 1 processo CANCELADO — entra em "Total previsto"
        # (todos os processos da UO), mas fora de qualquer contagem
        # restrita a Estado.ATIVO (inclusive fora da Meta).
        self._criar_processo(
            4,
            self.uo_a,
            self.tipo_nova,
            estado=Estado.CANCELADO,
            situacao=Situacao.NO_PRAZO,
        )
        # UO B: 1 Vigente concluído, 1 Renovação em tramitação.
        self._criar_processo(
            5, self.uo_b, self.tipo_vigente, situacao=Situacao.CONCLUIDO
        )
        self._criar_processo(
            6, self.uo_b, self.tipo_renovacao, situacao=Situacao.EM_TRAMITACAO
        )

        qs = queryset_filtrado(_RequestFalso(f"exercicio={self.exercicio.ano}"))
        linhas, total = calcular_resumo_uo(qs)

        self.assertEqual(len(linhas), 2)
        uo_a = next(linha for linha in linhas if linha["uo_id"] == self.uo_a.pk)
        uo_b = next(linha for linha in linhas if linha["uo_id"] == self.uo_b.pk)

        # UO A: 4 processos previstos (3 ativos + 1 cancelado).
        self.assertEqual(uo_a["total_previsto"], 4)
        self.assertEqual(uo_a["nova"], 2)
        self.assertEqual(uo_a["renovacao"], 1)
        self.assertEqual(uo_a["vigente"], 0)
        # Quick 260901-ebb — Meta = nova + renovacao = ativos − vigentes;
        # prazos CONSOLIDADOS (NC+RN numa coluna só, por tipo de prazo).
        self.assertEqual(uo_a["meta"], 3)
        self.assertEqual(uo_a["concluido_meta"], 1)
        self.assertEqual(uo_a["em_tramitacao"], 0)
        self.assertEqual(uo_a["no_prazo"], 1)
        self.assertEqual(uo_a["fora_prazo"], 1)
        self.assertEqual(uo_a["concluido"], 1)

        # UO B: 2 processos previstos, ambos ativos. O Vigente concluído
        # entra em `concluido` (análise), mas fica FORA de `concluido_meta`.
        self.assertEqual(uo_b["total_previsto"], 2)
        self.assertEqual(uo_b["vigente"], 1)
        self.assertEqual(uo_b["renovacao"], 1)
        self.assertEqual(uo_b["meta"], 1)
        self.assertEqual(uo_b["concluido_meta"], 0)
        self.assertEqual(uo_b["concluido"], 1)
        self.assertEqual(uo_b["em_tramitacao"], 1)

        # Linha TOTAL: soma dos NÚMEROS ABSOLUTOS, nunca a média dos %.
        self.assertEqual(total["total_previsto"], 6)
        self.assertEqual(total["nova"], 2)
        self.assertEqual(total["renovacao"], 2)
        self.assertEqual(total["vigente"], 1)
        self.assertEqual(total["meta"], 4)
        self.assertEqual(total["concluido_meta"], 1)
        self.assertEqual(total["concluido"], 2)
        self.assertEqual(total["em_tramitacao"], 1)
        self.assertEqual(total["no_prazo"], 1)
        self.assertEqual(total["fora_prazo"], 1)

        # FECHAMENTO do bloco META (Quick 260901-ebb): `Situacao` tem
        # exatamente 4 valores, logo a decomposição fecha por construção —
        # em cada linha E no TOTAL.
        for linha in (uo_a, uo_b, total):
            self.assertEqual(
                linha["concluido_meta"]
                + linha["em_tramitacao"]
                + linha["no_prazo"]
                + linha["fora_prazo"],
                linha["meta"],
            )

        # Chaves antigas AUSENTES do contrato (Quick 260901-ebb): prazos
        # por tipo e a antiga base do percentual de Concluído.
        self.assertNotIn("dentro_prazo_nc", uo_a)
        self.assertNotIn("fora_prazo_renov", uo_a)
        self.assertNotIn("concluido_sem_vigente", uo_a)

        # "% no PCA" — total_previsto da UO / soma de TODAS as UOs (6).
        self.assertEqual(
            uo_a["percentual_no_pca"].quantize(Decimal("0.01")),
            (Decimal(4) / Decimal(6) * 100).quantize(Decimal("0.01")),
        )
        self.assertEqual(
            total["percentual_no_pca"].quantize(Decimal("0.01")),
            Decimal("100.00"),
        )

    def test_cancelados_ativos_e_percentuais_derivados(self):
        # Quick 260831-md1 — cancelados/ativos/percentuais derivados sobre a
        # MESMA fixture de test_contagem_por_coluna_e_linha_total: UO A tem
        # total_previsto=4 (3 ativos + 1 cancelado), UO B tem
        # total_previsto=2 (2 ativos, 0 cancelado); TOTAL soma os absolutos
        # (cancelados=1, ativos=5).
        self._criar_processo(
            1, self.uo_a, self.tipo_nova, situacao=Situacao.CONCLUIDO
        )
        self._criar_processo(
            2, self.uo_a, self.tipo_nova, situacao=Situacao.NO_PRAZO
        )
        self._criar_processo(
            3, self.uo_a, self.tipo_renovacao, situacao=Situacao.ATRASADO
        )
        self._criar_processo(
            4,
            self.uo_a,
            self.tipo_nova,
            estado=Estado.CANCELADO,
            situacao=Situacao.NO_PRAZO,
        )
        self._criar_processo(
            5, self.uo_b, self.tipo_vigente, situacao=Situacao.CONCLUIDO
        )
        self._criar_processo(
            6, self.uo_b, self.tipo_renovacao, situacao=Situacao.EM_TRAMITACAO
        )

        qs = queryset_filtrado(_RequestFalso(f"exercicio={self.exercicio.ano}"))
        linhas, total = calcular_resumo_uo(qs)

        uo_a = next(linha for linha in linhas if linha["uo_id"] == self.uo_a.pk)
        uo_b = next(linha for linha in linhas if linha["uo_id"] == self.uo_b.pk)

        self.assertEqual(uo_a["cancelados"], 1)
        self.assertEqual(uo_a["ativos"], 3)
        self.assertEqual(uo_b["cancelados"], 0)
        self.assertEqual(uo_b["ativos"], 2)
        self.assertEqual(total["cancelados"], 1)
        self.assertEqual(total["ativos"], 5)

        self.assertEqual(
            uo_a["percentual_cancelados"].quantize(Decimal("0.01")),
            (Decimal(1) / Decimal(4) * 100).quantize(Decimal("0.01")),
        )
        self.assertEqual(
            uo_a["percentual_ativos"].quantize(Decimal("0.01")),
            (Decimal(3) / Decimal(4) * 100).quantize(Decimal("0.01")),
        )
        # UO A: 2 Nova / 3 ativos, 1 Renovação / 3 ativos, 0 Vigente / 3 ativos.
        self.assertEqual(
            uo_a["percentual_nova"].quantize(Decimal("0.01")),
            (Decimal(2) / Decimal(3) * 100).quantize(Decimal("0.01")),
        )
        self.assertEqual(
            uo_a["percentual_renovacao"].quantize(Decimal("0.01")),
            (Decimal(1) / Decimal(3) * 100).quantize(Decimal("0.01")),
        )
        self.assertEqual(uo_a["percentual_vigente"], Decimal("0"))

        # UO B: 1 Vigente / 2 ativos, 1 Renovação / 2 ativos, 0 Nova.
        self.assertEqual(uo_b["percentual_vigente"], Decimal("50"))
        self.assertEqual(uo_b["percentual_renovacao"], Decimal("50"))
        self.assertEqual(uo_b["percentual_nova"], Decimal("0"))

    def test_percentuais_do_bloco_meta_somam_100_sobre_a_meta(self):
        # Quick 260901-ebb — meta=4 cobrindo os 4 destinos (1 processo em
        # cada situação) + 1 Vigente para a base de `percentual_meta`
        # (ativos=5). Os 4 percentuais do bloco META são todos /meta e a
        # soma fecha em 100%; `percentual_meta` = meta/ativos.
        self._criar_processo(
            1, self.uo_a, self.tipo_nova, situacao=Situacao.CONCLUIDO
        )
        self._criar_processo(
            2, self.uo_a, self.tipo_nova, situacao=Situacao.EM_TRAMITACAO
        )
        self._criar_processo(
            3, self.uo_a, self.tipo_nova, situacao=Situacao.NO_PRAZO
        )
        self._criar_processo(
            4, self.uo_a, self.tipo_renovacao, situacao=Situacao.ATRASADO
        )
        self._criar_processo(
            5, self.uo_a, self.tipo_vigente, situacao=Situacao.EM_TRAMITACAO
        )

        qs = queryset_filtrado(_RequestFalso(f"exercicio={self.exercicio.ano}"))
        linhas, _total = calcular_resumo_uo(qs)

        uo_a = linhas[0]
        self.assertEqual(uo_a["meta"], 4)
        self.assertEqual(uo_a["ativos"], 5)
        self.assertEqual(uo_a["percentual_concluido_meta"], Decimal("25"))
        self.assertEqual(uo_a["percentual_em_tramitacao"], Decimal("25"))
        self.assertEqual(uo_a["percentual_no_prazo"], Decimal("25"))
        self.assertEqual(uo_a["percentual_fora_prazo"], Decimal("25"))
        soma = (
            uo_a["percentual_concluido_meta"]
            + uo_a["percentual_em_tramitacao"]
            + uo_a["percentual_no_prazo"]
            + uo_a["percentual_fora_prazo"]
        )
        self.assertEqual(soma.quantize(Decimal("0.01")), Decimal("100.00"))
        self.assertEqual(
            uo_a["percentual_meta"].quantize(Decimal("0.01")),
            (Decimal(4) / Decimal(5) * 100).quantize(Decimal("0.01")),
        )

    def test_uo_so_com_cancelado_e_zero_safe_em_percentuais_de_ativos(self):
        # Quick 260831-md1 — UO só com processo CANCELADO: ativos=0 ->
        # percentual_nova/renovacao/vigente são None (zero-safe), mesmo
        # princípio de test_uo_so_com_vigente_e_zero_safe_no_bloco_meta.
        self._criar_processo(
            1, self.uo_a, self.tipo_nova, estado=Estado.CANCELADO
        )

        qs = queryset_filtrado(_RequestFalso(f"exercicio={self.exercicio.ano}"))
        linhas, _total = calcular_resumo_uo(qs)

        uo_a = linhas[0]
        self.assertEqual(uo_a["total_previsto"], 1)
        self.assertEqual(uo_a["ativos"], 0)
        self.assertIsNone(uo_a["percentual_nova"])
        self.assertIsNone(uo_a["percentual_renovacao"])
        self.assertIsNone(uo_a["percentual_vigente"])

    def test_uo_sem_processo_no_catalogo_fica_de_fora(self):
        # Unidade sem nenhum Processo no exercício — nunca aparece na
        # tabela resumo (só UOs com processo >= 1).
        Unidade.objects.create(nome="COLOG")
        self._criar_processo(1, self.uo_a, self.tipo_nova)

        qs = queryset_filtrado(_RequestFalso(f"exercicio={self.exercicio.ano}"))
        linhas, _total = calcular_resumo_uo(qs)

        self.assertEqual(len(linhas), 1)
        self.assertEqual(linhas[0]["uo_id"], self.uo_a.pk)

    def test_uo_so_com_vigente_e_zero_safe_no_bloco_meta(self):
        # Quick 260901-ebb — UO só com Vigentes (zero Nova/Renovação):
        # meta == 0 -> os 4 percentuais do bloco META são None (zero-safe),
        # nunca ZeroDivisionError. Já o "Total Concluído" (análise, base
        # /ativos) agora É calculável: 1 concluído / 1 ativo = 100%.
        self._criar_processo(
            1, self.uo_b, self.tipo_vigente, situacao=Situacao.CONCLUIDO
        )

        qs = queryset_filtrado(_RequestFalso(f"exercicio={self.exercicio.ano}"))
        linhas, _total = calcular_resumo_uo(qs)

        uo_b = linhas[0]
        self.assertEqual(uo_b["meta"], 0)
        self.assertEqual(uo_b["percentual_meta"], Decimal("0"))
        self.assertIsNone(uo_b["percentual_concluido_meta"])
        self.assertIsNone(uo_b["percentual_em_tramitacao"])
        self.assertIsNone(uo_b["percentual_no_prazo"])
        self.assertIsNone(uo_b["percentual_fora_prazo"])
        self.assertEqual(uo_b["percentual_concluido"], Decimal("100"))

    def test_calcular_resumo_uo_e_1_unica_consulta_agregada(self):
        # 1 lookup de Tipo + 1 .annotate() agregado, o mesmo orçamento
        # de calcular_blocos_kpi; nunca 1 consulta por UO. `qs` já foi
        # avaliado antes do bloco medido. O orçamento é 2 queries.
        self._criar_processo(1, self.uo_a, self.tipo_nova)
        self._criar_processo(2, self.uo_b, self.tipo_renovacao)
        qs = queryset_filtrado(_RequestFalso(f"exercicio={self.exercicio.ano}"))

        with CaptureQueriesContext(connection) as capturado:
            calcular_resumo_uo(qs)

        self.assertEqual(len(capturado.captured_queries), 2)

    def test_concluido_analise_inclui_vigentes_e_concluido_meta_nao(self):
        # Quick 260901-ebb — UO B: 1 Vigente concluído + 1 Nova concluída +
        # 1 Renovação no prazo -> ativos=3, meta=2. "Total Concluído"
        # (análise) conta os Vigentes: concluido=2, % = 2/3 dos ativos
        # (~66,67). "Concluído (meta)" NÃO: concluido_meta=1 (só a Nova),
        # % = 1/2 da meta = 50%.
        self._criar_processo(
            1, self.uo_b, self.tipo_vigente, situacao=Situacao.CONCLUIDO
        )
        self._criar_processo(
            2, self.uo_b, self.tipo_nova, situacao=Situacao.CONCLUIDO
        )
        self._criar_processo(
            3, self.uo_b, self.tipo_renovacao, situacao=Situacao.NO_PRAZO
        )

        qs = queryset_filtrado(_RequestFalso(f"exercicio={self.exercicio.ano}"))
        linhas, _total = calcular_resumo_uo(qs)

        uo_b = next(linha for linha in linhas if linha["uo_id"] == self.uo_b.pk)
        self.assertEqual(uo_b["concluido"], 2)
        self.assertEqual(
            uo_b["percentual_concluido"].quantize(Decimal("0.01")),
            (Decimal(2) / Decimal(3) * 100).quantize(Decimal("0.01")),
        )
        self.assertEqual(uo_b["concluido_meta"], 1)
        self.assertEqual(
            uo_b["percentual_concluido_meta"].quantize(Decimal("0.01")),
            Decimal("50.00"),
        )

    # --- Partição Situação dos ativos + Outros tipos, ao lado da
    # partição de meta já existente. ------------------

    def test_exemplo_obrigatorio_91_7_e_80_por_cento(self):
        # Exemplo obrigatório literal: 12 ativos (7 Vigentes + 5 NC/RN), 4
        # da meta concluídos + os 7 Vigentes concluídos -> composição dos
        # ativos Cₐ/A = 11/12 = 91,7% (nunca 220%, que seria Cₐ/M = 11/5);
        # cumprimento da meta Cₘ/M = 4/5 = 80% (nunca Cₐ/M).
        for item in range(1, 5):
            self._criar_processo(
                item, self.uo_a, self.tipo_nova, situacao=Situacao.CONCLUIDO
            )
        self._criar_processo(
            5, self.uo_a, self.tipo_renovacao, situacao=Situacao.NO_PRAZO
        )
        for item in range(6, 13):
            self._criar_processo(
                item, self.uo_a, self.tipo_vigente, situacao=Situacao.CONCLUIDO
            )

        qs = queryset_filtrado(_RequestFalso(f"exercicio={self.exercicio.ano}"))
        linhas, _total = calcular_resumo_uo(qs)

        uo_a = linhas[0]
        self.assertEqual(uo_a["ativos"], 12)
        self.assertEqual(uo_a["vigente"], 7)
        self.assertEqual(uo_a["meta"], 5)
        self.assertEqual(uo_a["concluido"], 11)
        self.assertEqual(uo_a["concluido_meta"], 4)
        self.assertEqual(uo_a["no_prazo_ativos"], 1)
        self.assertEqual(uo_a["em_tramitacao_ativos"], 0)
        self.assertEqual(uo_a["atrasado_ativos"], 0)
        self.assertEqual(
            uo_a["percentual_concluido"].quantize(Decimal("0.1")), Decimal("91.7")
        )
        self.assertEqual(
            uo_a["percentual_concluido_meta"].quantize(Decimal("0.1")),
            Decimal("80.0"),
        )
        self.assertNotEqual(uo_a["percentual_concluido_meta"], Decimal("220"))
        # MECE: concluido + em_tramitacao_ativos + no_prazo_ativos +
        # atrasado_ativos == ativos.
        self.assertEqual(
            uo_a["concluido"]
            + uo_a["em_tramitacao_ativos"]
            + uo_a["no_prazo_ativos"]
            + uo_a["atrasado_ativos"],
            uo_a["ativos"],
        )

    def test_particao_situacao_dos_ativos_fecha_mece_para_uo_e_total(self):
        # UO A: mix das 4 situações sobre tipos diferentes (irrestrito).
        self._criar_processo(
            1, self.uo_a, self.tipo_nova, situacao=Situacao.CONCLUIDO
        )
        self._criar_processo(
            2, self.uo_a, self.tipo_renovacao, situacao=Situacao.EM_TRAMITACAO
        )
        self._criar_processo(
            3, self.uo_a, self.tipo_vigente, situacao=Situacao.NO_PRAZO
        )
        self._criar_processo(
            4, self.uo_a, self.tipo_nova, situacao=Situacao.ATRASADO
        )
        # UO B: só Vigente concluído (meta == 0).
        self._criar_processo(
            5, self.uo_b, self.tipo_vigente, situacao=Situacao.CONCLUIDO
        )

        qs = queryset_filtrado(_RequestFalso(f"exercicio={self.exercicio.ano}"))
        linhas, total = calcular_resumo_uo(qs)

        for linha in linhas + [total]:
            with self.subTest(uo=linha["uo"]):
                self.assertEqual(
                    linha["concluido"]
                    + linha["em_tramitacao_ativos"]
                    + linha["no_prazo_ativos"]
                    + linha["atrasado_ativos"],
                    linha["ativos"],
                )

    def test_uo_vazia_particao_de_situacao_dos_ativos_e_zero_safe(self):
        # Recorte sem NENHUM processo: linha TOTAL com ativos == 0 -> os 4
        # percentuais da partição são None (zero-safe), nunca
        # ZeroDivisionError.
        Unidade.objects.create(nome="COLOG")

        qs = queryset_filtrado(_RequestFalso(f"exercicio={self.exercicio.ano}"))
        linhas, total = calcular_resumo_uo(qs)

        self.assertEqual(linhas, [])
        self.assertEqual(total["ativos"], 0)
        self.assertEqual(total["concluido"], 0)
        self.assertEqual(total["em_tramitacao_ativos"], 0)
        self.assertEqual(total["no_prazo_ativos"], 0)
        self.assertEqual(total["atrasado_ativos"], 0)
        self.assertIsNone(total["percentual_concluido"])
        self.assertIsNone(total["percentual_em_tramitacao_ativos"])
        self.assertIsNone(total["percentual_no_prazo_ativos"])
        self.assertIsNone(total["percentual_atrasado_ativos"])
        self.assertIsNone(total["percentual_outros_tipos"])

    def test_outros_tipos_torna_soma_por_tipo_honesta(self):
        # UO com um processo ativo de tipo fora de NC/RN/VG:
        # `outros_tipos > 0` e a soma "por tipo" volta a fechar com ativos.
        tipo_extra = Tipo.objects.create(nome="Estudo técnico preliminar")
        self._criar_processo(
            1, self.uo_a, self.tipo_nova, situacao=Situacao.CONCLUIDO
        )
        self._criar_processo(
            2, self.uo_a, self.tipo_vigente, situacao=Situacao.CONCLUIDO
        )
        self._criar_processo(3, self.uo_a, tipo_extra, situacao=Situacao.NO_PRAZO)

        qs = queryset_filtrado(_RequestFalso(f"exercicio={self.exercicio.ano}"))
        linhas, _total = calcular_resumo_uo(qs)

        uo_a = linhas[0]
        self.assertEqual(uo_a["ativos"], 3)
        self.assertEqual(uo_a["outros_tipos"], 1)
        # Sem essa coluna, nova+renovacao+vigente ficaria menor que ativos
        # silenciosamente.
        self.assertLess(
            uo_a["nova"] + uo_a["renovacao"] + uo_a["vigente"], uo_a["ativos"]
        )
        self.assertEqual(
            uo_a["nova"] + uo_a["renovacao"] + uo_a["vigente"] + uo_a["outros_tipos"],
            uo_a["ativos"],
        )
        self.assertEqual(
            uo_a["percentual_outros_tipos"].quantize(Decimal("0.01")),
            (Decimal(1) / Decimal(3) * 100).quantize(Decimal("0.01")),
        )

    def test_vigente_com_situacao_manual_nao_e_forcado_a_concluido(self):
        # Regressão-guarda: Vigente cuja `situacao_efetiva` foi gravada
        # como algo != concluído (via `pca:transicao_processo`) nunca é
        # forçado a "concluído" só por ser Vigente — entra na partição
        # irrestrita correspondente, nunca em `concluido`.
        self._criar_processo(
            1, self.uo_a, self.tipo_vigente, situacao=Situacao.ATRASADO
        )

        qs = queryset_filtrado(_RequestFalso(f"exercicio={self.exercicio.ano}"))
        linhas, _total = calcular_resumo_uo(qs)

        uo_a = linhas[0]
        self.assertEqual(uo_a["concluido"], 0)
        self.assertEqual(uo_a["atrasado_ativos"], 1)
        self.assertEqual(uo_a["em_tramitacao_ativos"], 0)
        self.assertEqual(uo_a["no_prazo_ativos"], 0)


class _RequestFalso:
    """GET mínimo — só o que `queryset_filtrado`/`filtros_ativos` leem
    (`request.GET`), sem subir todo o Django test client."""

    def __init__(self, querystring):
        from django.http import QueryDict

        self.GET = QueryDict(querystring)


class TestResumoUOView(_BaseResumoUO):
    def setUp(self):
        self.usuario = get_user_model().objects.create_user(
            email="leitor@pca.local", password="x-forte-123"
        )

    def test_get_resumo_uo_autenticado_devolve_200(self):
        self._criar_processo(1, self.uo_a, self.tipo_nova)
        self._criar_processo(2, self.uo_b, self.tipo_renovacao)
        self.client.force_login(self.usuario)

        resposta = self.client.get(reverse("pca:resumo_uo"))

        self.assertEqual(resposta.status_code, 200)

    def test_numero_de_linhas_bate_com_uos_distintas_com_processo(self):
        self._criar_processo(1, self.uo_a, self.tipo_nova)
        self._criar_processo(2, self.uo_a, self.tipo_renovacao)
        self._criar_processo(3, self.uo_b, self.tipo_vigente)
        self.client.force_login(self.usuario)

        esperado = (
            Processo.objects.filter(exercicio=self.exercicio)
            .values("unidade_organizacional_id")
            .distinct()
            .count()
        )

        resposta = self.client.get(reverse("pca:resumo_uo"))

        self.assertEqual(len(resposta.context["linhas"]), esperado)

    def test_usuario_nao_autenticado_e_redirecionado_ao_login(self):
        resposta = self.client.get(reverse("pca:resumo_uo"))

        self.assertEqual(resposta.status_code, 302)
        self.assertIn("/login/", resposta.url)

    def test_link_resumo_uo_presente_na_navegacao(self):
        self._criar_processo(1, self.uo_a, self.tipo_nova)
        self.client.force_login(self.usuario)

        resposta = self.client.get(reverse("pca:tabela"))

        self.assertContains(resposta, reverse("pca:resumo_uo"))


class TestExportarResumoUOXlsx(_BaseResumoUO):
    def setUp(self):
        self.usuario = get_user_model().objects.create_user(
            email="leitor@pca.local", password="x-forte-123"
        )

    def test_export_devolve_xlsx_valido_com_convencoes_d08(self):
        # UO só com 1 Vigente EM_TRAMITACAO -> meta == 0 -> percentuais do
        # bloco META são None -> "-" literal. A partição "Situação dos
        # ativos" é irrestrita por tipo (base ativos, não meta): mesmo
        # com meta == 0, seus percentuais são calculáveis (1 ativo > 0).
        # Percentual calculável vira número fração de Excel (0.0 aqui)
        # com `number_format` FORMATO_PERCENTUAL.
        self._criar_processo(
            1, self.uo_a, self.tipo_vigente, situacao=Situacao.EM_TRAMITACAO
        )
        qs = Processo.objects.para_listagem().filter(exercicio=self.exercicio)
        linhas, total = calcular_resumo_uo(qs)

        resposta = exportar_resumo_uo_xlsx(linhas, total)

        self.assertEqual(
            resposta["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        planilha = load_workbook(BytesIO(resposta.content))
        ws = planilha.active

        # Quick 260901-ebb — 2 linhas de cabeçalho (bloco + coluna) + 1 UO
        # + TOTAL + 1 linha de legenda das siglas (ajuste de escopo 01/09)
        # = 5.
        self.assertEqual(ws.max_row, 5)

        # Linha 1 — 4 nomes de bloco, nas posições certas: UO ocupa a
        # coluna 1 (mesclada verticalmente, não faz parte deste tuple).
        linha_1 = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
        self.assertEqual(linha_1[0], "UO")
        nomes_bloco_esperados = [
            "Previsto",
            "Por tipo",
            "Situação dos ativos",
            "Meta do PCA",
        ]
        nomes_bloco_encontrados = [
            valor for valor in linha_1[1:] if valor is not None
        ]
        self.assertEqual(nomes_bloco_encontrados, nomes_bloco_esperados)

        # Dados começam na linha 3; a ÚLTIMA linha é a legenda das siglas
        # (só a coluna 1 preenchida), então a região de dados vai até
        # max_row - 1 (a linha TOTAL).
        linha_total = ws.max_row - 1
        valores_celulas = [
            celula.value
            for linha in ws.iter_rows(min_row=3, max_row=linha_total)
            for celula in linha
        ]
        # Quick 260901-gci — nenhuma célula da região de dados fica vazia:
        # percentual calculável é float (fração), denominador zero é o
        # literal "-", e o resto é texto (UO) ou int (contagem do ORM).
        self.assertNotIn(None, valores_celulas)

        # Índices resolvidos pela CHAVE de `COLUNAS_XLSX` (não pelo
        # cabeçalho curto). meta == 0 nesta fixture: "% Concluído (meta)"
        # é "-" literal.
        chaves_colunas = [chave for chave, _, _, _ in COLUNAS_XLSX]
        indice_pct_concluido_meta = chaves_colunas.index(
            "percentual_concluido_meta"
        )
        celula_pct_concluido_meta = ws.cell(
            row=3, column=indice_pct_concluido_meta + 1
        )
        self.assertEqual(celula_pct_concluido_meta.value, "-")
        # O "-" (denominador zero) não carrega o formato de percentual:
        # prova que o number_format é condicionado a valor numérico,
        # nunca aplicado ao literal.
        self.assertNotEqual(
            celula_pct_concluido_meta.number_format, FORMATO_PERCENTUAL
        )

        # "% Em tramitação" do grupo "Situação dos ativos" é irrestrito
        # por tipo (base ativos): meta == 0 não o zera — 1 Vigente em
        # tramitação / 1 ativo = 100% -> fração 1.0 calculável, prova de
        # que a base é ativos, nunca meta.
        indice_pct_em_tramitacao_ativos = chaves_colunas.index(
            "percentual_em_tramitacao_ativos"
        )
        celula_pct_em_tramitacao_ativos = ws.cell(
            row=3, column=indice_pct_em_tramitacao_ativos + 1
        )
        self.assertAlmostEqual(celula_pct_em_tramitacao_ativos.value, 1.0)
        self.assertEqual(
            celula_pct_em_tramitacao_ativos.number_format, FORMATO_PERCENTUAL
        )

        # "% Concluídos" (situação dos ativos, /ativos): 0/1 -> fração 0.0
        # com formato de percentual (Quick 260901-gci — número, não
        # string).
        indice_pct_concluido = chaves_colunas.index("percentual_concluido")
        celula_pct_concluido = ws.cell(row=3, column=indice_pct_concluido + 1)
        self.assertEqual(celula_pct_concluido.value, 0.0)
        self.assertEqual(
            celula_pct_concluido.number_format, FORMATO_PERCENTUAL
        )

        # Quick 260901-gci — cobertura numérica NÃO-zero na linha de UO:
        # 1 Vigente / 1 ativo -> "% VG" = 100% -> fração 1.0.
        indice_pct_vigente = chaves_colunas.index("percentual_vigente")
        celula_pct_vigente = ws.cell(row=3, column=indice_pct_vigente + 1)
        self.assertAlmostEqual(celula_pct_vigente.value, 1.0)
        self.assertEqual(
            celula_pct_vigente.number_format, FORMATO_PERCENTUAL
        )

        # "Outros tipos": 0 aqui (ativos=1 é o próprio Vigente, nenhum
        # tipo fora de NC/RN/VG neste fixture) -> fração 0.0 calculável
        # (ativos != 0), não "-".
        indice_pct_outros_tipos = chaves_colunas.index("percentual_outros_tipos")
        celula_pct_outros_tipos = ws.cell(
            row=3, column=indice_pct_outros_tipos + 1
        )
        self.assertEqual(celula_pct_outros_tipos.value, 0.0)

        # Cabeçalho de bloco "Situação dos ativos" mescla as 8 colunas do
        # bloco: a primeira coluna (chave `concluido`) carrega o rótulo
        # mesclado; a seguinte fica vazia (célula mesclada).
        indice_situacao = chaves_colunas.index("concluido")
        self.assertEqual(linha_1[indice_situacao], "Situação dos ativos")
        self.assertIsNone(linha_1[indice_situacao + 1])

        # Cabeçalho de bloco "Meta do PCA" mescla as 4 colunas do bloco:
        # a primeira coluna (chave `meta`) carrega o rótulo mesclado; a
        # seguinte fica vazia (célula mesclada).
        indice_meta = chaves_colunas.index("meta")
        self.assertEqual(linha_1[indice_meta], "Meta do PCA")
        self.assertIsNone(linha_1[indice_meta + 1])

        # A decomposição detalhada da meta (em_tramitacao/no_prazo/
        # fora_prazo, restrita a NC|RN) não está no XLSX; só a versão
        # irrestrita ("Situação dos ativos") permanece exportada.
        self.assertNotIn("percentual_no_prazo", chaves_colunas)
        self.assertNotIn("percentual_fora_prazo", chaves_colunas)
        self.assertNotIn("em_tramitacao", chaves_colunas)

        # Linha TOTAL com preenchimento do bloco identificação/total.
        celula_uo_total = ws.cell(row=linha_total, column=1)
        self.assertEqual(celula_uo_total.value, "TOTAL")
        self.assertEqual(
            celula_uo_total.fill.fgColor.rgb[-6:].upper(), "14314C"
        )

        # Quick 260901-gci — a linha TOTAL é escrita por caminho de código
        # DISTINTO do append das linhas de UO; cobre o mesmo contrato
        # numérico lá: "% no PCA" do TOTAL = 100% -> fração 1.0 + formato.
        indice_pct_no_pca = chaves_colunas.index("percentual_no_pca")
        celula_pct_no_pca_total = ws.cell(
            row=linha_total, column=indice_pct_no_pca + 1
        )
        self.assertAlmostEqual(celula_pct_no_pca_total.value, 1.0)
        self.assertEqual(
            celula_pct_no_pca_total.number_format, FORMATO_PERCENTUAL
        )

        # Legenda das siglas na última linha (ajuste de escopo 01/09).
        self.assertEqual(
            ws.cell(row=ws.max_row, column=1).value,
            "NC = Nova Contratação · RN = Renovação · VG = Vigente",
        )

        # Nenhuma fórmula viva do tipo Excel (só a neutralização `'=` de
        # formula injection seria aceitável, e não há nome de UO hostil
        # neste fixture).
        for valor in valores_celulas:
            if isinstance(valor, str):
                self.assertFalse(valor.startswith("="))

    def test_get_exportar_resumo_uo_autenticado_devolve_200(self):
        self._criar_processo(1, self.uo_a, self.tipo_nova)
        self.client.force_login(self.usuario)

        resposta = self.client.get(reverse("pca:exportar_resumo_uo_xlsx"))

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(
            resposta["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


class TestDrilldownResumoUO(_BaseResumoUO):
    """Quick 260831-kfx — cada célula de `/resumo-uo` linka para `/tabela`
    com o MESMO recorte que a célula conta. Cada teste faz uma segunda
    requisição real ao href extraído do contexto de `/resumo-uo` (nunca um
    href recalculado à mão) e compara a contagem devolvida com o valor da
    célula. Quick 260901-ebb — os hrefs de prazo agora são CONSOLIDADOS
    (NC+RN juntos) e entram os hrefs `meta`/`concluido_meta`."""

    def setUp(self):
        self.usuario = get_user_model().objects.create_user(
            email="leitor-drilldown@pca.local", password="x-forte-123"
        )
        self.client.force_login(self.usuario)

    def test_href_total_previsto_de_uma_uo_bate_com_tabela(self):
        # UO A: 2 ativos (Nova) + 1 cancelado -> Total previsto = 3.
        self._criar_processo(1, self.uo_a, self.tipo_nova)
        self._criar_processo(2, self.uo_a, self.tipo_renovacao)
        self._criar_processo(
            3, self.uo_a, self.tipo_nova, estado=Estado.CANCELADO
        )
        # UO B só para não deixar a fixture trivial (>1 UO no escopo).
        self._criar_processo(4, self.uo_b, self.tipo_vigente)

        resposta_resumo = self.client.get(reverse("pca:resumo_uo"))
        linha_a = next(
            linha
            for linha in resposta_resumo.context["linhas"]
            if linha["uo_id"] == self.uo_a.pk
        )
        self.assertEqual(linha_a["total_previsto"], 3)
        href = linha_a["hrefs"]["total_previsto"]

        resposta_tabela = self.client.get(f"{reverse('pca:tabela')}?{href}")

        self.assertEqual(
            resposta_tabela.context["pagina"].paginator.count,
            linha_a["total_previsto"],
        )

    def test_href_concluido_de_uma_uo_bate_com_tabela(self):
        self._criar_processo(
            1, self.uo_a, self.tipo_nova, situacao=Situacao.CONCLUIDO
        )
        self._criar_processo(
            2, self.uo_a, self.tipo_renovacao, situacao=Situacao.CONCLUIDO
        )
        self._criar_processo(
            3, self.uo_a, self.tipo_nova, situacao=Situacao.NO_PRAZO
        )
        self._criar_processo(4, self.uo_b, self.tipo_vigente)

        resposta_resumo = self.client.get(reverse("pca:resumo_uo"))
        linha_a = next(
            linha
            for linha in resposta_resumo.context["linhas"]
            if linha["uo_id"] == self.uo_a.pk
        )
        self.assertEqual(linha_a["concluido"], 2)
        href = linha_a["hrefs"]["concluido"]

        resposta_tabela = self.client.get(f"{reverse('pca:tabela')}?{href}")

        self.assertEqual(
            resposta_tabela.context["pagina"].paginator.count,
            linha_a["concluido"],
        )

    def test_href_no_prazo_consolidado_bate_com_tabela(self):
        # Quick 260901-ebb — NO_PRAZO em NC E em RN na mesma UO: o href
        # consolidado tem que devolver a SOMA dos dois tipos (2 NC + 1 RN
        # no prazo = 3), nunca só um recorte por tipo.
        self._criar_processo(
            1, self.uo_a, self.tipo_nova, situacao=Situacao.NO_PRAZO
        )
        self._criar_processo(
            2, self.uo_a, self.tipo_nova, situacao=Situacao.NO_PRAZO
        )
        self._criar_processo(
            3, self.uo_a, self.tipo_nova, situacao=Situacao.ATRASADO
        )
        self._criar_processo(
            4, self.uo_a, self.tipo_renovacao, situacao=Situacao.NO_PRAZO
        )
        self._criar_processo(5, self.uo_b, self.tipo_vigente)

        resposta_resumo = self.client.get(reverse("pca:resumo_uo"))
        linha_a = next(
            linha
            for linha in resposta_resumo.context["linhas"]
            if linha["uo_id"] == self.uo_a.pk
        )
        self.assertEqual(linha_a["no_prazo"], 3)
        href = linha_a["hrefs"]["no_prazo"]

        resposta_tabela = self.client.get(f"{reverse('pca:tabela')}?{href}")

        self.assertEqual(
            resposta_tabela.context["pagina"].paginator.count,
            linha_a["no_prazo"],
        )

    def test_href_meta_bate_com_tabela(self):
        # Quick 260901-ebb — Meta = NC + RN ativos; o Vigente fica de fora
        # tanto da contagem quanto do recorte do href.
        self._criar_processo(1, self.uo_a, self.tipo_nova)
        self._criar_processo(2, self.uo_a, self.tipo_nova)
        self._criar_processo(3, self.uo_a, self.tipo_renovacao)
        self._criar_processo(4, self.uo_a, self.tipo_vigente)
        self._criar_processo(5, self.uo_b, self.tipo_vigente)

        resposta_resumo = self.client.get(reverse("pca:resumo_uo"))
        linha_a = next(
            linha
            for linha in resposta_resumo.context["linhas"]
            if linha["uo_id"] == self.uo_a.pk
        )
        self.assertEqual(linha_a["meta"], 3)
        href = linha_a["hrefs"]["meta"]

        resposta_tabela = self.client.get(f"{reverse('pca:tabela')}?{href}")

        self.assertEqual(
            resposta_tabela.context["pagina"].paginator.count,
            linha_a["meta"],
        )

    def test_href_concluido_meta_bate_com_tabela(self):
        # Quick 260901-ebb — CONCLUIDO em NC conta; o Vigente concluído
        # fica de fora da contagem E do recorte do href `concluido_meta`.
        self._criar_processo(
            1, self.uo_a, self.tipo_nova, situacao=Situacao.CONCLUIDO
        )
        self._criar_processo(
            2, self.uo_a, self.tipo_vigente, situacao=Situacao.CONCLUIDO
        )
        self._criar_processo(
            3, self.uo_a, self.tipo_renovacao, situacao=Situacao.NO_PRAZO
        )
        self._criar_processo(4, self.uo_b, self.tipo_vigente)

        resposta_resumo = self.client.get(reverse("pca:resumo_uo"))
        linha_a = next(
            linha
            for linha in resposta_resumo.context["linhas"]
            if linha["uo_id"] == self.uo_a.pk
        )
        self.assertEqual(linha_a["concluido_meta"], 1)
        href = linha_a["hrefs"]["concluido_meta"]

        resposta_tabela = self.client.get(f"{reverse('pca:tabela')}?{href}")

        self.assertEqual(
            resposta_tabela.context["pagina"].paginator.count,
            linha_a["concluido_meta"],
        )

    def test_href_indicador_da_linha_total_bate_com_tabela(self):
        self._criar_processo(
            1, self.uo_a, self.tipo_nova, situacao=Situacao.CONCLUIDO
        )
        self._criar_processo(
            2, self.uo_b, self.tipo_vigente, situacao=Situacao.CONCLUIDO
        )
        self._criar_processo(
            3, self.uo_b, self.tipo_renovacao, situacao=Situacao.NO_PRAZO
        )

        resposta_resumo = self.client.get(reverse("pca:resumo_uo"))
        total = resposta_resumo.context["total"]
        self.assertEqual(total["concluido"], 2)
        href = total["hrefs"]["concluido"]
        # Linha TOTAL nunca carrega `uo=` no href (regra 3 — a linha soma
        # todas as UOs, o clique não pode restringir a uma só).
        self.assertNotIn("uo=", href)

        resposta_tabela = self.client.get(f"{reverse('pca:tabela')}?{href}")

        self.assertEqual(
            resposta_tabela.context["pagina"].paginator.count,
            total["concluido"],
        )

    def test_href_cancelados_de_uma_uo_bate_com_tabela(self):
        # Quick 260831-md1 — "Cancelados" ganha drill-down próprio.
        self._criar_processo(1, self.uo_a, self.tipo_nova)
        self._criar_processo(
            2, self.uo_a, self.tipo_renovacao, estado=Estado.CANCELADO
        )
        self._criar_processo(
            3, self.uo_a, self.tipo_nova, estado=Estado.CANCELADO
        )
        self._criar_processo(4, self.uo_b, self.tipo_vigente)

        resposta_resumo = self.client.get(reverse("pca:resumo_uo"))
        linha_a = next(
            linha
            for linha in resposta_resumo.context["linhas"]
            if linha["uo_id"] == self.uo_a.pk
        )
        self.assertEqual(linha_a["cancelados"], 2)
        href = linha_a["hrefs"]["cancelados"]
        self.assertIn("estado=cancelado", href)

        resposta_tabela = self.client.get(f"{reverse('pca:tabela')}?{href}")

        self.assertEqual(
            resposta_tabela.context["pagina"].paginator.count,
            linha_a["cancelados"],
        )

    def test_href_ativos_da_linha_total_bate_com_tabela(self):
        # Quick 260831-md1 — "Ativos" da linha TOTAL nunca carrega `uo=`
        # (mesma regra já testada para `concluido` da linha TOTAL).
        self._criar_processo(1, self.uo_a, self.tipo_nova)
        self._criar_processo(
            2, self.uo_a, self.tipo_renovacao, estado=Estado.CANCELADO
        )
        self._criar_processo(3, self.uo_b, self.tipo_vigente)

        resposta_resumo = self.client.get(reverse("pca:resumo_uo"))
        total = resposta_resumo.context["total"]
        self.assertEqual(total["ativos"], 2)
        href = total["hrefs"]["ativos"]
        self.assertIn("estado=ativo", href)
        self.assertNotIn("uo=", href)

        resposta_tabela = self.client.get(f"{reverse('pca:tabela')}?{href}")

        self.assertEqual(
            resposta_tabela.context["pagina"].paginator.count,
            total["ativos"],
        )

    def test_celulas_da_tabela_resumo_uo_sao_links_para_tabela(self):
        # 3 tabelas com link por célula (painel Absolutos, painel
        # Percentuais, "Detalhar composição"), cada uma com colunas
        # diferentes (as 3 colunas irrestritas de "Situação dos ativos" e
        # "Outros tipos" não têm href), + 1 link fixo de navegação (menu
        # lateral, "Processos", contado uma vez só):
        # - painel Absolutos: por UO, 10 links (rótulo + total_previsto/
        #   cancelados/ativos + nc/rn/vg + concluídos + meta/concluído
        #   (meta)); linha TOTAL, 9 (sem rótulo).
        # - painel Percentuais: por UO, 9 links (sem rótulo de
        #   total_previsto, que não tem painel percentual); TOTAL, 8.
        # - Detalhar composição: por UO, 8 links (rótulo + participação +
        #   em_tramitacao/no_prazo/fora_prazo, cada um abs+pct); TOTAL, 7.
        self._criar_processo(1, self.uo_a, self.tipo_nova)
        self._criar_processo(2, self.uo_b, self.tipo_vigente)

        resposta = self.client.get(reverse("pca:resumo_uo"))
        n_linhas = len(resposta.context["linhas"])
        por_uo = 10 + 9 + 8
        por_total = 9 + 8 + 7
        esperado = 1 + n_linhas * por_uo + por_total

        self.assertContains(
            resposta, 'href="' + reverse("pca:tabela"), count=esperado
        )


class TestEstruturaResumoUO(_BaseResumoUO):
    """Quick 260831-md1 — cabeçalho em blocos, toggle absolutos/percentuais
    na mesma célula, filtros herdados de /tabela, subtítulo "Foto atual"
    removido, botão XLSX via OOB dedicado. Quick 260901-ebb — blocos
    reorganizados em torno da Meta (Previsto ‖ Por tipo ‖ Meta do PCA ‖
    Análise), siglas NC/RN/VG com legenda e "Total Concluído" (ajuste de
    escopo de 01/09)."""

    def setUp(self):
        self.usuario = get_user_model().objects.create_user(
            email="leitor-estrutura@pca.local", password="x-forte-123"
        )
        self.client.force_login(self.usuario)

    def test_ordem_das_colunas_no_cabecalho(self):
        # Quick 260909-rwm (`telas/matriz.md`) — não é mais um cabeçalho
        # FLAT de uma linha: virou 2 níveis (grupo + indicador,
        # `dsgov-grupo`/`th[colspan]`), dentro de `br-tab`; a asserção em si
        # só compara posições de substring por nome de coluna, então
        # continua válida sem mudança de código (o `.index()` acha a
        # PRIMEIRA ocorrência, sempre no painel Absolutos, na mesma ordem).
        # 4 grupos: Previsto ‖ Por tipo (+ Outros tipos) ‖ Situação dos
        # ativos ‖ Meta do PCA (encolhida a Meta/Concluído (meta) — a
        # decomposição detalhada mudou para "Detalhar composição", fora
        # da tabela principal).
        self._criar_processo(1, self.uo_a, self.tipo_nova)

        resposta = self.client.get(reverse("pca:resumo_uo"))
        conteudo = resposta.content.decode()
        # O bloco `dl.dsgov-detalhe` de totais (acima da tabela) repete
        # alguns rótulos ("Cancelados", "Ativos"...) — a ordem só é
        # contrato da TABELA, então a checagem começa no `<caption>` dela.
        conteudo = conteudo[conteudo.index("Resumo por unidade organizacional") :]

        nomes_coluna = [
            "Total previsto",
            "Cancelados",
            "Ativos",
            "NC",
            "RN",
            "VG",
            "Outros tipos",
            "Concluídos",
            "Em tramitação",
            "No prazo",
            "Atrasados",
            "Meta",
            "Concluído (meta)",
        ]
        posicoes_coluna = [conteudo.index(f">{nome}<") for nome in nomes_coluna]
        self.assertEqual(posicoes_coluna, sorted(posicoes_coluna))

    def test_grupo_situacao_dos_ativos_presente_e_total_concluido_nao_isolado(self):
        # "Situação dos ativos" existe como grupo; "Total Concluído"
        # (rótulo do extinto bloco Análise) não aparece mais isolado fora
        # dele — "Concluídos" é a 1ª coluna do grupo novo.
        self._criar_processo(1, self.uo_a, self.tipo_nova)

        resposta = self.client.get(reverse("pca:resumo_uo"))

        self.assertContains(resposta, "Situação dos ativos")
        self.assertNotContains(resposta, "Total Concluído")

    def test_partial_detalhar_composicao_presente(self):
        # Participação no PCA e a decomposição detalhada da meta
        # (restrita a NC|RN) vivem em "Detalhar composição", fora da
        # matriz principal.
        self._criar_processo(1, self.uo_a, self.tipo_nova)

        resposta = self.client.get(reverse("pca:resumo_uo"))

        self.assertContains(resposta, "Detalhar composição")
        self.assertContains(resposta, "Participação no PCA")

    def test_legenda_das_siglas_por_tipo_presente(self):
        # Ajuste de escopo 01/09 — as siglas NC/RN/VG do bloco "Por tipo"
        # ganham legenda discreta abaixo da tabela.
        self._criar_processo(1, self.uo_a, self.tipo_nova)

        resposta = self.client.get(reverse("pca:resumo_uo"))

        self.assertContains(
            resposta, "NC = Nova Contratação · RN = Renovação · VG = Vigente"
        )

    def test_subtitulo_foto_atual_removido(self):
        resposta = self.client.get(reverse("pca:resumo_uo"))

        self.assertNotContains(resposta, "Foto atual")

    def test_absoluto_e_percentual_vivem_na_mesma_celula(self):
        # Quick 260909-rwm (`telas/matriz.md`) — o toggle Alpine deu lugar
        # a dois painéis renderizados pelo SERVIDOR (Absolutos/
        # Percentuais): o valor absoluto e o percentual agora vivem em
        # DOIS `<a>` distintos (mesmo `href`), nunca no mesmo `<a>` — a 1ª
        # ocorrência (painel Absolutos) mostra só o número, a 2ª (painel
        # Percentuais) só o percentual.
        self._criar_processo(1, self.uo_a, self.tipo_nova)
        self._criar_processo(2, self.uo_a, self.tipo_renovacao)
        self._criar_processo(3, self.uo_a, self.tipo_vigente)

        resposta = self.client.get(reverse("pca:resumo_uo"))
        linha_a = next(
            linha
            for linha in resposta.context["linhas"]
            if linha["uo_id"] == self.uo_a.pk
        )
        self.assertEqual(linha_a["nova"], 1)
        self.assertEqual(
            linha_a["percentual_nova"].quantize(Decimal("0.1")),
            (Decimal(1) / Decimal(3) * 100).quantize(Decimal("0.1")),
        )

        conteudo = resposta.content.decode()
        href_nova = linha_a["hrefs"]["nova"]
        alvo = f'?{escape(href_nova)}'

        indice_primeiro = conteudo.index(alvo)
        inicio_1 = conteudo.rindex("<a ", 0, indice_primeiro)
        fim_1 = conteudo.index("</a>", indice_primeiro) + len("</a>")
        janela_absolutos = conteudo[inicio_1:fim_1]

        indice_segundo = conteudo.index(alvo, fim_1)
        inicio_2 = conteudo.rindex("<a ", 0, indice_segundo)
        fim_2 = conteudo.index("</a>", indice_segundo) + len("</a>")
        janela_percentuais = conteudo[inicio_2:fim_2]

        self.assertIn("1", janela_absolutos)
        self.assertNotIn("%", janela_absolutos)
        self.assertIn("33,3%", janela_percentuais)

    def test_botao_exportar_presente_no_full_page(self):
        # Sem HTMX/OOB: "Exportar XLSX" é um link secondary comum,
        # sempre com a querystring corrente (nunca congelada de uma carga
        # anterior, porque a página inteira recarrega a cada filtro).
        resposta = self.client.get(reverse("pca:resumo_uo"))

        self.assertContains(resposta, reverse("pca:exportar_resumo_uo_xlsx"))
        self.assertContains(resposta, "Exportar XLSX")
