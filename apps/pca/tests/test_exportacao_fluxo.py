"""Testes do relatório XLSX do fluxo de caixa (Fase 37, spec
documento interno de desenho
§0 decisão 6/§6). Reaproveita `AnaliseTelasBase` (mesma fixture real
`Modelo_de_Controle_.xlsx`, exercício 2026, persona `editor` com
`pca.ver_analises`) — nenhum teste toca `apps.pca.sei.coletor`."""

from decimal import Decimal
from io import BytesIO

from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory
from django.urls import reverse

from openpyxl import load_workbook

from apps.catalogo.models import Exercicio
from apps.pca.models import CenarioFluxo
from apps.pca.tests.test_analise_telas import AnaliseTelasBase
from apps.pca.views_analise import _contexto_fluxo

ABAS_ESPERADAS = ["Resumo", "Anual", "Contratações", "Parcelas", "Memória"]


def _ctx_fluxo(usuario, params):
    """Monta o mesmo `_contexto_fluxo` que a view usa, via `RequestFactory`
    (sem HTTP real) — usado só para conferir os números do XLSX contra a
    MESMA `Projecao` que a tela leria para os mesmos parâmetros, sem
    duplicar o motor no teste."""
    factory = RequestFactory()
    request = factory.get(reverse("pca:analise_fluxo"), params)
    request.user = usuario
    SessionMiddleware(lambda r: None).process_request(request)
    request.session.save()
    return _contexto_fluxo(request)


class TestXlsxCincoAbas(AnaliseTelasBase):
    def _xlsx(self, params=None):
        self.client.force_login(self.editor)
        resposta = self.client.get(
            reverse("pca:analise_fluxo_xlsx"),
            params or {"exercicio": "2026"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(
            resposta["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        planilha = load_workbook(BytesIO(resposta.content))
        return resposta, planilha

    def test_xlsx_tem_exatamente_as_5_abas_na_ordem(self):
        _, planilha = self._xlsx()
        self.assertEqual(planilha.sheetnames, ABAS_ESPERADAS)

    def test_visualizador_sem_ver_analises_recebe_403(self):
        self.client.force_login(self.visualizador)
        resposta = self.client.get(
            reverse("pca:analise_fluxo_xlsx"), {"exercicio": "2026"}, HTTP_HOST="testserver"
        )
        self.assertEqual(resposta.status_code, 403)

    def test_content_disposition_tem_nome_de_arquivo_com_exercicio(self):
        resposta, _ = self._xlsx()
        self.assertIn("pca-fluxo-de-caixa-2026-oficial.xlsx", resposta["Content-Disposition"])

    def test_resumo_lista_indicadores_oficial_simulado_delta(self):
        _, planilha = self._xlsx()
        ws = planilha["Resumo"]
        textos = [str(c.value) for linha in ws.iter_rows() for c in linha if c.value is not None]
        self.assertTrue(any("Indicador" in t for t in textos))
        self.assertTrue(any("A pagar até 31/12" in t for t in textos))
        self.assertTrue(any("% contratado" in t for t in textos))

    def test_aba_anual_tem_uma_linha_por_ano_e_camada(self):
        _, planilha = self._xlsx()
        ws = planilha["Anual"]
        cabecalho = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
        self.assertEqual(cabecalho, ["Ano", "Camada", "Oficial (R$)", "Simulado (R$)", "Δ (R$)"])
        # 6 anos (exercício..exercício+5) × 4 camadas = 24 linhas de dado.
        self.assertEqual(ws.max_row - 1, 24)

    def test_totais_aba_anual_batem_com_projecao_por_ano_da_tela(self):
        _, planilha = self._xlsx()
        ws = planilha["Anual"]
        somas_xlsx = {}
        for linha in ws.iter_rows(min_row=2, values_only=True):
            ano, _camada, oficial, _simulado, _delta = linha
            somas_xlsx[ano] = somas_xlsx.get(ano, Decimal("0")) + Decimal(str(oficial))

        ctx = _ctx_fluxo(self.editor, {"exercicio": "2026"})
        projecao = ctx["projecao"]
        for ano in range(ctx["exercicio"].ano, ctx["exercicio"].ano + 6):
            total_projecao = sum(projecao.por_ano.get(ano, {}).values(), Decimal("0"))
            self.assertEqual(
                somas_xlsx[ano].quantize(Decimal("0.01")),
                total_projecao.quantize(Decimal("0.01")),
                f"ano {ano}: XLSX {somas_xlsx[ano]} != projecao {total_projecao}",
            )

    def test_sem_recorte_ativo_aba_contratacoes_e_memoria_tem_so_aviso(self):
        _, planilha = self._xlsx({"exercicio": "2026"})
        ws_contratacoes = planilha["Contratações"]
        self.assertEqual(ws_contratacoes.max_row, 2)  # cabeçalho + aviso
        self.assertIn("Nenhum recorte selecionado", str(ws_contratacoes.cell(2, 1).value))
        ws_memoria = planilha["Memória"]
        self.assertEqual(ws_memoria.max_row, 2)
        self.assertIn("Nenhum recorte selecionado", str(ws_memoria.cell(2, 1).value))

    def test_com_recorte_ativo_aba_contratacoes_lista_o_item(self):
        _, planilha = self._xlsx({"exercicio": "2026", "ano": "2026"})
        ws = planilha["Contratações"]
        self.assertGreater(ws.max_row, 1)
        itens_coluna = [ws.cell(r, 1).value for r in range(2, ws.max_row + 1)]
        self.assertTrue(all(isinstance(v, int) for v in itens_coluna))

    def test_com_recorte_ativo_aba_memoria_tem_linhas_do_item(self):
        _, planilha = self._xlsx({"exercicio": "2026", "ano": "2026"})
        ws = planilha["Memória"]
        self.assertGreater(ws.max_row, 1)
        cabecalho = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
        self.assertEqual(cabecalho, ["Item", "Competência", "Camada", "Valor (R$)", "Fórmula"])

    def test_aba_parcelas_sem_simulacao_nao_tem_coluna_valor_simulado(self):
        _, planilha = self._xlsx({"exercicio": "2026"})
        ws = planilha["Parcelas"]
        cabecalho = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
        self.assertEqual(
            cabecalho,
            ["Item", "Instrumento", "Competência", "Camada", "Valor Oficial (R$)", "Origem"],
        )

    def test_aba_parcelas_com_simulacao_ganha_coluna_valor_simulado_e_item_excluido_fica_vazio(self):
        self.client.force_login(self.editor)
        # Escolhe um item que de fato tem parcela oficial (o primeiro da
        # aba "Parcelas" sem simulação) — não hardcoda `item_pca=1`, que
        # pode não ter camada gerada dependendo da fixture do exercício.
        _, planilha_sem_sim = self._xlsx({"exercicio": "2026"})
        ws_sem_sim = planilha_sem_sim["Parcelas"]
        item_alvo = next(ws_sem_sim.iter_rows(min_row=2, max_row=2, values_only=True))[0]

        self.client.post(
            reverse("pca:analise_fluxo_item_excluir", args=[item_alvo]),
            {"exercicio": "2026"},
            HTTP_HOST="testserver",
        )
        resposta = self.client.get(
            reverse("pca:analise_fluxo_xlsx"),
            {"exercicio": "2026", "sim": "rascunho"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 200)
        planilha = load_workbook(BytesIO(resposta.content))
        ws = planilha["Parcelas"]
        cabecalho = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
        self.assertEqual(cabecalho[-1], "Valor Simulado (R$)")
        linhas_item_alvo = [
            linha for linha in ws.iter_rows(min_row=2, values_only=True) if linha[0] == item_alvo
        ]
        self.assertTrue(linhas_item_alvo, f"item {item_alvo} sem nenhuma parcela oficial no XLSX")
        for linha in linhas_item_alvo:
            self.assertIsNone(linha[-1], "item excluído da simulação deveria ficar vazio, não 0")


class TestXlsxNeutralizaInjecaoDeFormula(AnaliseTelasBase):
    def test_nome_de_cenario_iniciado_por_igual_nunca_vira_formula(self):
        exercicio = Exercicio.objects.get(ano=2026)
        cenario = CenarioFluxo.objects.create(
            exercicio=exercicio,
            nome="=SOMA(A1:A10)",
            autor=self.editor,
            ajustes={},
        )
        self.client.force_login(self.editor)
        resposta = self.client.get(
            reverse("pca:analise_fluxo_xlsx"),
            {"exercicio": "2026", "sim": str(cenario.pk)},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 200)
        planilha = load_workbook(BytesIO(resposta.content))
        ws = planilha["Resumo"]
        celula_cenario = None
        for linha in ws.iter_rows():
            for c in linha:
                if isinstance(c.value, str) and c.value.startswith("Cenário:"):
                    celula_cenario = c.value
                    break
        self.assertIsNotNone(celula_cenario, "linha 'Cenário:' não encontrada na aba Resumo")
        self.assertIn("'=SOMA(A1:A10)", celula_cenario)
