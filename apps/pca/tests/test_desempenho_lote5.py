"""QA 30/09/2026 (periferia nº2/nº10, dados B6) — 3 achados de desempenho do
Lote 5: `/admin/pca/processo/` e `/admin/pca/historicaleventofinanceiro/`
N+1 (cobertos aqui e em `test_admin_auditoria.py::TestAdminProcessoSemNMais1`),
`POST /exportar` com orçamento de consultas diferente do `GET /exportar/xlsx`
equivalente, e o XLSX de Análises › Fluxo de caixa quadrático (`ws.max_row`
lido dentro de laço proporcional a N). Fixture de catálogo/processos
reaproveitada de `apps.pca.tests.test_desempenho_fase28` (NÃO duplicada)."""

import types
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from openpyxl.worksheet.worksheet import Worksheet

from apps.pca.exportacao_fluxo import exportar_fluxo_xlsx
from apps.pca.models import Processo
from apps.pca.projecao import CAMADAS, LinhaMemoria, Memoria, Parcela, Projecao
from apps.pca.tests.test_desempenho_fase28 import _criar_processos, _popular_catalogo


class TestExportarPostMesmoOrcamentoDeConsultasDoGet(TestCase):
    """Dados B6 — `POST /exportar` (página com formulário de colunas) fazia
    194 consultas contra 8 do `GET /exportar/xlsx` equivalente:
    `exportar_view` chamava `_queryset_export(request)` SEM o 2º argumento,
    então `select_related("modalidade"/"instrumento_contratual")` nunca
    ativava mesmo com essas colunas selecionadas — 1 consulta extra de
    `catalogo_modalidade` por processo com modalidade preenchida."""

    @classmethod
    def setUpTestData(cls):
        (
            cls.unidades,
            cls.tipos,
            cls.categoria,
            cls.prioridade,
            cls.classificacao,
            cls.modalidade,
            cls.exercicio,
        ) = _popular_catalogo()
        cls.usuario = get_user_model().objects.create_user(
            email="desempenho-lote5@pca.local", password="senha-forte-123"
        )

    def setUp(self):
        self.client.force_login(self.usuario)

    def _consultas_post(self, quantidade):
        Processo.objects.all().delete()
        _criar_processos(
            quantidade, self.unidades, self.tipos, self.categoria, self.prioridade,
            self.classificacao, self.modalidade, self.exercicio,
        )
        with CaptureQueriesContext(connection) as captura:
            resposta = self.client.post(
                reverse("pca:exportar"), {"formato": "xlsx", "colunas": ["modalidade"]}
            )
        self.assertEqual(resposta.status_code, 200)
        return len(captura.captured_queries)

    def test_post_exportar_nao_cresce_de_8_para_60_processos(self):
        pequeno = self._consultas_post(8)
        grande = self._consultas_post(60)
        self.assertEqual(pequeno, grande)


class TestExportarFluxoXlsxSemWsMaxRowNoLaco(SimpleTestCase):
    """Periferia nº2 — as 5 abas do XLSX de Análises › Fluxo de caixa liam
    `ws.max_row` (openpyxl faz `max()` sobre todas as células já escritas)
    dentro de laços proporcionais a N (parcelas/contratações/memória) —
    custo QUADRÁTICO. `SimpleTestCase` (sem banco): `exportar_fluxo_xlsx` é
    puro, só recebe argumentos já calculados."""

    def test_max_row_nunca_e_lido_dentro_do_laco(self):
        projecao = Projecao(
            parcelas=[
                Parcela(
                    item_pca=i,
                    instrumento="principal",
                    competencia=f"2026-{(i % 12) + 1:02d}",
                    valor=Decimal("100.00"),
                    camada="contratado",
                    origem="motor",
                )
                for i in range(200)
            ],
            por_ano={2026: {c: Decimal("0") for c in CAMADAS}},
            totais={
                "ate_fim_exercicio": Decimal("0"),
                "proximo_ano": Decimal("0"),
                "cinco_anos": Decimal("0"),
                "percentual_contratado": Decimal("0"),
            },
            memorias={
                i: Memoria(
                    item_pca=i,
                    linhas=[
                        LinhaMemoria(
                            competencia="2026-01",
                            camada="contratado",
                            valor=Decimal("10.00"),
                            formula="x",
                        )
                    ],
                )
                for i in range(200)
            },
        )
        lista_recorte = [
            {
                "item_pca": i,
                "objeto": f"Objeto {i}",
                "uo": "Unidade",
                "instrumentos": "Principal",
                "valores_por_camada": {c: Decimal("0") for c in CAMADAS},
                "total": Decimal("0"),
            }
            for i in range(200)
        ]
        exercicio = types.SimpleNamespace(ano=2026)

        contador = {"n": 0}
        max_row_original = Worksheet.max_row

        def _contado(self):
            contador["n"] += 1
            return max_row_original.fget(self)

        with mock.patch.object(Worksheet, "max_row", property(_contado)):
            resposta = exportar_fluxo_xlsx(
                exercicio=exercicio,
                cenario_nome="base",
                cenario_rotulo="Base",
                autor="qa",
                filtros_ativos_texto="",
                variaveis_simuladas=[],
                projecao_oficial=projecao,
                projecao_simulada=None,
                lista_recorte=lista_recorte,
                anos_horizonte=[2026],
            )

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(contador["n"], 0)
