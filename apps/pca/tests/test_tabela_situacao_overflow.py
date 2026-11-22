"""QA 30/09/2026, navegador B2 — a tabela de Processos (Tabler) gerava
rolagem horizontal ao alargar a coluna de situação: o `visually-hidden`
interno do selo se ancorava num ancestral não posicionado distante.
`position-relative` no wrapper imediato (`d-inline-flex`) corrige, sem CSS
próprio novo (utilitário Bootstrap já vendorizado)."""

import pathlib

from django.conf import settings
from django.test import SimpleTestCase


class TabelaSituacaoOverflowTests(SimpleTestCase):
    def test_wrapper_tem_position_relative(self):
        conteudo = pathlib.Path(
            settings.BASE_DIR, "tabler", "templates", "pca", "_tabela_situacao.html"
        ).read_text(encoding="utf-8")
        self.assertIn("position-relative", conteudo)
