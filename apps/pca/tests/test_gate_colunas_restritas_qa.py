"""QA de segurança 30/09/2026 — regressão dos achados M2 (export entrega ao
visualizador as colunas restritas a `pca.view_acompanhamento`) e B1
(busca/ordenação/filtros alcançam os mesmos dados restritos por um caminho
lateral). Reaproveita a fixture de `test_permissoes_acompanhamento.py`
(`PermissoesAcompanhamentoBase`: grupo `editor` com `view_acompanhamento`,
grupo `visualizador` sem ela) — nunca redeclara usuários/grupos."""

import csv
from datetime import date
from io import BytesIO, StringIO

from django.urls import reverse
from openpyxl import load_workbook

from apps.pca.colunas import CHAVES_RESTRITAS_ACOMPANHAMENTO
from apps.pca.exportacao import COLUNAS_POR_CHAVE as _COLUNAS_EXPORT_POR_CHAVE
from apps.pca.models import Processo, Reuniao, SituacaoReuniao, TipoEvento
from apps.pca.tests.test_permissoes_acompanhamento import PermissoesAcompanhamentoBase

_ROTULOS_RESTRITOS = {
    _COLUNAS_EXPORT_POR_CHAVE[chave][1] for chave in CHAVES_RESTRITAS_ACOMPANHAMENTO
}


class TestExportColunasRestritasQA(PermissoesAcompanhamentoBase):
    """M2 — `?colunas=` explícito (CSV/XLSX) e `POST /exportar` sem
    `colunas` nenhuma (todas) nunca entregam ao visualizador os 7 campos de
    `CHAVES_RESTRITAS_ACOMPANHAMENTO`."""

    def _csv_linhas(self, resposta):
        return list(
            csv.reader(
                StringIO(resposta.content.decode("utf-8-sig")), delimiter=";"
            )
        )

    def test_visualizador_csv_nao_traz_colunas_restritas(self):
        self.client.force_login(self.visualizador)
        resposta = self.client.get(
            reverse("pca:exportar_csv"),
            {"colunas": ["item_pca", "n_reunioes", "situacao_atual"]},
        )
        self.assertEqual(resposta.status_code, 200)
        cabecalho = self._csv_linhas(resposta)[0]
        self.assertNotIn(
            _COLUNAS_EXPORT_POR_CHAVE["n_reunioes"][1], cabecalho
        )
        self.assertNotIn(
            _COLUNAS_EXPORT_POR_CHAVE["situacao_atual"][1], cabecalho
        )

    def test_visualizador_xlsx_nao_traz_colunas_restritas(self):
        self.client.force_login(self.visualizador)
        resposta = self.client.get(
            reverse("pca:exportar_xlsx"),
            {"colunas": ["item_pca", "n_reunioes", "situacao_atual"]},
        )
        self.assertEqual(resposta.status_code, 200)
        planilha = load_workbook(BytesIO(resposta.content)).active
        cabecalho = [celula.value for celula in planilha[1]]
        self.assertNotIn(_COLUNAS_EXPORT_POR_CHAVE["n_reunioes"][1], cabecalho)
        self.assertNotIn(
            _COLUNAS_EXPORT_POR_CHAVE["situacao_atual"][1], cabecalho
        )

    def test_visualizador_post_exportar_sem_colunas_nao_traz_restritas(self):
        """Reproduz o caso `colunas=None` do achado: nenhum `colunas` no
        corpo, o que antes exportava TODAS as colunas (inclusive as
        restritas)."""
        self.client.force_login(self.visualizador)
        resposta = self.client.post(
            reverse("pca:exportar"), {"formato": "xlsx"}
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(
            resposta.get("Content-Type"),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        planilha = load_workbook(BytesIO(resposta.content)).active
        cabecalho = [celula.value for celula in planilha[1]]
        for rotulo in _ROTULOS_RESTRITOS:
            self.assertNotIn(rotulo, cabecalho)

    def test_editor_continua_vendo_colunas_restritas_csv(self):
        """Controle: o grupo `editor` (com `view_acompanhamento`) continua
        recebendo os rótulos restritos normalmente — a correção não
        restringe quem TEM a permissão."""
        self.client.force_login(self.editor)
        resposta = self.client.get(
            reverse("pca:exportar_csv"),
            {"colunas": ["item_pca", "n_reunioes", "situacao_atual"]},
        )
        self.assertEqual(resposta.status_code, 200)
        cabecalho = self._csv_linhas(resposta)[0]
        self.assertIn(_COLUNAS_EXPORT_POR_CHAVE["n_reunioes"][1], cabecalho)
        self.assertIn(
            _COLUNAS_EXPORT_POR_CHAVE["situacao_atual"][1], cabecalho
        )


class TestBuscaOrdenacaoFiltrosRestritosQA(PermissoesAcompanhamentoBase):
    """B1 — busca textual, ordenação e os filtros `reprometidos`/
    `proximo_prazo`/`sem_atualizacao` não podem servir de caminho lateral
    para os mesmos dados restritos que a tela já esconde do visualizador."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # Segundo processo com DOIS prazos prometidos DIFERENTES (anota
        # `reprometido=True`). `n_reunioes` do item 1 (cls.processo) é
        # deliberadamente MAIOR que o do item 2 — o OPOSTO da ordem de
        # `item_pca` — para que uma ordenação real por `n_reunioes`
        # descendente ([1, 2]) nunca possa ser confundida com o fallback de
        # `item_pca` descendente que o gate produz ([2, 1]): as duas ordens
        # só divergem de verdade quando os dados não estão alinhados.
        #
        # `situacao=FECHADA` em todas: só uma reunião ABERTA é permitida por
        # vez (`pca_reuniao_aberta_unica`), e esta fixture não precisa de
        # reunião corrente — só de `reuniao_id` preenchido para `n_reunioes`
        # contar.
        reuniao1 = Reuniao.objects.create(
            data=date(2026, 3, 1),
            exercicio=cls.exercicio,
            situacao=SituacaoReuniao.FECHADA,
        )
        reuniao2 = Reuniao.objects.create(
            data=date(2026, 4, 1),
            exercicio=cls.exercicio,
            situacao=SituacaoReuniao.FECHADA,
        )
        reuniao3 = Reuniao.objects.create(
            data=date(2026, 5, 1),
            exercicio=cls.exercicio,
            situacao=SituacaoReuniao.FECHADA,
        )
        # Item 1 (cls.processo) ganha 2 reuniões — mais que o item 2.
        cls.processo.acompanhamentos.create(
            referencia_data=date(2026, 3, 1),
            origem_hash="hash-qa-b1-item1-reuniao1",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO,
            situacao=cls.situacao_normalizada,
            reuniao=reuniao1,
            evento="Primeira reunião do item 1",
        )
        cls.processo.acompanhamentos.create(
            referencia_data=date(2026, 4, 1),
            origem_hash="hash-qa-b1-item1-reuniao2",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO,
            situacao=cls.situacao_normalizada,
            reuniao=reuniao2,
            evento="Segunda reunião do item 1",
        )

        cls.processo2 = Processo.objects.create(
            item_pca=2,
            exercicio=cls.exercicio,
            descricao_objeto="Segundo processo do gate B1",
            tipo=cls.tipo,
            categoria=cls.categoria,
            unidade_organizacional=cls.unidade,
        )
        # Item 2 ganha só 1 reunião (menos que o item 1) e dois prazos
        # prometidos DIFERENTES (anota `reprometido=True`).
        cls.processo2.acompanhamentos.create(
            referencia_data=date(2026, 3, 1),
            origem_hash="hash-qa-b1-item2-1",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO,
            situacao=cls.situacao_normalizada,
            prazo_prometido=date(2026, 6, 1),
            reuniao=reuniao3,
            evento="Primeira reunião do processo 2",
        )
        cls.processo2.acompanhamentos.create(
            referencia_data=date(2026, 4, 1),
            origem_hash="hash-qa-b1-item2-2",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO,
            situacao=cls.situacao_normalizada,
            prazo_prometido=date(2026, 7, 1),
            evento="Segunda reunião do processo 2 (prazo remarcado)",
        )

    def test_visualizador_busca_nao_encontra_pelo_campo_restrito(self):
        self.client.force_login(self.visualizador)
        resposta = self.client.get(
            reverse("pca:tabela"),
            {"q": self.situacao_normalizada.nome, "exercicio": self.exercicio.ano},
        )
        self.assertEqual(resposta.status_code, 200)
        itens = [p.item_pca for p in resposta.context["pagina"].object_list]
        self.assertEqual(itens, [])

    def test_editor_busca_encontra_pelo_campo_restrito(self):
        self.client.force_login(self.editor)
        resposta = self.client.get(
            reverse("pca:tabela"),
            {"q": self.situacao_normalizada.nome, "exercicio": self.exercicio.ano},
        )
        self.assertEqual(resposta.status_code, 200)
        itens = {p.item_pca for p in resposta.context["pagina"].object_list}
        self.assertEqual(itens, {1, 2})

    def test_visualizador_ordenar_n_reunioes_cai_no_padrao(self):
        """O item 1 tem MAIS reuniões que o item 2 (setUpTestData) —
        propositalmente o OPOSTO da ordem de `item_pca` — para que a ordem
        REAL por `n_reunioes` descendente ([1, 2]) nunca possa ser
        confundida com o fallback (`item_pca` descendente, por causa de
        `dir=desc`, mesmo contrato de qualquer `?ordenar=` fora da
        allowlist — `test_ordenacao_ignora_parametro_fora_da_allowlist`)
        que o gate produz para quem não tem `pca.view_acompanhamento`."""
        self.client.force_login(self.visualizador)
        resposta = self.client.get(
            reverse("pca:tabela"),
            {
                "ordenar": "n_reunioes",
                "dir": "desc",
                "exercicio": self.exercicio.ano,
            },
        )
        self.assertEqual(resposta.status_code, 200)
        itens = [p.item_pca for p in resposta.context["pagina"].object_list]
        # Fallback (item_pca, mesma allowlist de qualquer coluna inválida),
        # NUNCA a ordem real por n_reunioes (que seria [1, 2] — item 1 tem
        # mais reuniões).
        self.assertEqual(itens, [2, 1])

    def test_editor_ordenar_n_reunioes_reordena_de_verdade(self):
        self.client.force_login(self.editor)
        resposta = self.client.get(
            reverse("pca:tabela"),
            {
                "ordenar": "n_reunioes",
                "dir": "desc",
                "exercicio": self.exercicio.ano,
            },
        )
        self.assertEqual(resposta.status_code, 200)
        itens = [p.item_pca for p in resposta.context["pagina"].object_list]
        self.assertEqual(itens, [1, 2])  # item 1 tem mais reuniões

    def test_visualizador_filtro_reprometidos_e_ignorado(self):
        self.client.force_login(self.visualizador)
        resposta_sem_filtro = self.client.get(
            reverse("pca:tabela"), {"exercicio": self.exercicio.ano}
        )
        resposta_com_filtro = self.client.get(
            reverse("pca:tabela"),
            {"reprometidos": "1", "exercicio": self.exercicio.ano},
        )
        self.assertEqual(resposta_sem_filtro.status_code, 200)
        self.assertEqual(resposta_com_filtro.status_code, 200)
        self.assertEqual(
            resposta_sem_filtro.context["pagina"].paginator.count,
            resposta_com_filtro.context["pagina"].paginator.count,
        )

    def test_editor_filtro_reprometidos_filtra_de_verdade(self):
        self.client.force_login(self.editor)
        resposta_sem_filtro = self.client.get(
            reverse("pca:tabela"), {"exercicio": self.exercicio.ano}
        )
        resposta_com_filtro = self.client.get(
            reverse("pca:tabela"),
            {"reprometidos": "1", "exercicio": self.exercicio.ano},
        )
        self.assertEqual(resposta_sem_filtro.status_code, 200)
        self.assertEqual(resposta_com_filtro.status_code, 200)
        self.assertLess(
            resposta_com_filtro.context["pagina"].paginator.count,
            resposta_sem_filtro.context["pagina"].paginator.count,
        )
