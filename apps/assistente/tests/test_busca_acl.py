"""Teste do ACL antes do top-k (`<specifics>`): índice
com trechos de `acompanhamento`/`sei`/`docs` (`ver_analises`); usuário sem
permissão NUNCA recebe trecho restrito, mesmo com `fonte=None` e escore
1,0 (vetor de consulta igual ao do trecho). A máscara de permissão é
aplicada ANTES de `argpartition` (matriz que chega já reduzida)."""

import hashlib
import tempfile
from pathlib import Path
from unittest import mock

import numpy as np
from django.test import override_settings
from django.utils import timezone

from apps.assistente import fontes as fontes_mod
from apps.assistente import indice
from apps.assistente.cliente import RespostaEmbeddings
from apps.assistente.tests.base import AssistenteTestBase

_DIM = 8


def _vetor_do_hash(texto: str, dim: int = _DIM):
    digest = hashlib.sha256(texto.encode("utf-8")).digest()
    return [((digest[i % len(digest)] / 255.0) * 2 - 1) for i in range(dim)]


class _ClienteEmbeddingsFalso:
    def __init__(self):
        self.chamadas_embeddings = 0

    def embeddings(self, textos, timeout_s):
        self.chamadas_embeddings += 1
        return RespostaEmbeddings(vetores=[_vetor_do_hash(t) for t in textos], tokens=len(textos))


def _trecho(**kwargs):
    base = dict(
        fonte="docs", ref="x", ordem=0, titulo="T", texto="texto", url=None,
        exercicio=None, item_pca=None, permissao="", atualizado_em=None,
    )
    base.update(kwargs)
    return fontes_mod.Trecho(**base)


class TestBuscaAcl(AssistenteTestBase):
    def setUp(self):
        super().setUp()
        self._tmp_indice = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp_indice.cleanup)
        self._override_indice = override_settings(
            IA_INDICE_PATH=str(Path(self._tmp_indice.name) / "indice.sqlite3"),
        )
        self._override_indice.enable()
        self.addCleanup(self._override_indice.disable)
        indice._CACHE_MATRIZ.clear()
        self.addCleanup(indice._CACHE_MATRIZ.clear)

        self.trecho_acompanhamento = _trecho(
            fonte="acompanhamento", ref="ac:1",
            texto="ficou combinado em julho sobre o item 42",
            permissao="pca.view_acompanhamento", exercicio=2026, item_pca=42,
        )
        self.trecho_sei = _trecho(
            fonte="sei", ref="sei:1", texto="corpo do contrato da Sollo",
            permissao="", exercicio=2026, item_pca=7,
        )
        self.trecho_analises = _trecho(
            fonte="docs", ref="analises-fluxo-de-caixa/0", texto="texto sobre fluxo de caixa",
            permissao="pca.ver_analises",
        )

        cliente = _ClienteEmbeddingsFalso()
        with mock.patch(
            "apps.assistente.fontes.extrair_tudo",
            return_value=[self.trecho_acompanhamento, self.trecho_sei, self.trecho_analises],
        ):
            indice.indexar(cliente, agora=timezone.now())

    @staticmethod
    def _vetor_igual_ao_trecho(trecho):
        return _vetor_do_hash(trecho.texto)

    def test_visualizador_nunca_recebe_acompanhamento_mesmo_com_escore_1_e_fonte_none(self):
        resultados = indice.buscar(
            usuario=self.visualizador,
            vetor_consulta=self._vetor_igual_ao_trecho(self.trecho_acompanhamento),
            fonte=None,
            k=6,
            limiar=0.0,
        )
        self.assertFalse(any(r.fonte == "acompanhamento" for r in resultados))

    def test_visualizador_nunca_recebe_trecho_de_ver_analises(self):
        resultados = indice.buscar(
            usuario=self.visualizador,
            vetor_consulta=self._vetor_igual_ao_trecho(self.trecho_analises),
            fonte=None,
            k=6,
            limiar=0.0,
        )
        self.assertFalse(any(r.ref == self.trecho_analises.ref for r in resultados))

    def test_editor_recebe_o_acompanhamento(self):
        resultados = indice.buscar(
            usuario=self.editor,
            vetor_consulta=self._vetor_igual_ao_trecho(self.trecho_acompanhamento),
            k=6,
            limiar=0.5,
        )
        self.assertTrue(any(r.fonte == "acompanhamento" for r in resultados))

    def test_dirigente_recebe_os_tres(self):
        for trecho in (self.trecho_acompanhamento, self.trecho_sei, self.trecho_analises):
            resultados = indice.buscar(
                usuario=self.dirigente,
                vetor_consulta=self._vetor_igual_ao_trecho(trecho),
                k=6,
                limiar=0.5,
            )
            self.assertTrue(any(r.ref == trecho.ref for r in resultados), trecho.ref)

    def test_filtro_item_pca_exclui_outros_itens(self):
        resultados = indice.buscar(
            usuario=self.dirigente,
            vetor_consulta=self._vetor_igual_ao_trecho(self.trecho_acompanhamento),
            item_pca=999,
            k=6,
            limiar=0.0,
        )
        self.assertEqual(resultados, [])

    def test_filtro_exercicio_exclui_outro_ano(self):
        resultados = indice.buscar(
            usuario=self.dirigente,
            vetor_consulta=self._vetor_igual_ao_trecho(self.trecho_acompanhamento),
            exercicio=2020,
            k=6,
            limiar=0.0,
        )
        self.assertEqual(resultados, [])

    def test_k_e_limiar_respeitados(self):
        resultados = indice.buscar(
            usuario=self.dirigente,
            vetor_consulta=self._vetor_igual_ao_trecho(self.trecho_sei),
            k=1,
            limiar=0.0,
        )
        self.assertLessEqual(len(resultados), 1)
        for resultado in resultados:
            self.assertGreaterEqual(resultado.escore, 0.0)

    def test_abstencao_com_limiar_muito_alto(self):
        vetor_ortogonal = [0.0] * _DIM
        vetor_ortogonal[0] = 1.0
        resultados = indice.buscar(
            usuario=self.dirigente,
            vetor_consulta=vetor_ortogonal,
            k=6,
            limiar=0.999,
        )
        self.assertEqual(resultados, [])

    def test_mascara_de_permissao_aplicada_antes_do_argpartition(self):
        chamadas_shape = []
        original = np.argpartition

        def _espiao(a, *args, **kwargs):
            chamadas_shape.append(a.shape[0])
            return original(a, *args, **kwargs)

        with mock.patch("numpy.argpartition", side_effect=_espiao):
            indice.buscar(
                usuario=self.visualizador,
                vetor_consulta=self._vetor_igual_ao_trecho(self.trecho_sei),
                k=6,
                limiar=0.0,
            )

        # `visualizador` só enxerga o trecho `sei` (permissao=""): a matriz
        # que chega em `argpartition` já vem com 1 linha (das 3 do índice),
        # nunca as 3 sem recorte prévio.
        self.assertEqual(chamadas_shape, [1])
