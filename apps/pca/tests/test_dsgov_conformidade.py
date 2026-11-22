"""Guarda único da fase de conformidade estrita (Fase 26). Substitui os 6 guardas de reskin específicos da era webcomponents
(`test_reskin_institucional`, `test_pca_css_tokens`, `test_icones_govbr`,
`test_paleta_contraste`, `test_mobile_responsivo`, `test_hidratacao_casca`) —
nenhum deles fazia sentido depois que o repositório inteiro passou a ser
verificado por um único script, contra um único padrão.

`ops/dsgov/verificar.py` é a cópia versionada (mesmas 10 regras, só
`CORE_CSS`/`FA_CSS`/`SKILL_CSS_DIR` reapontados para `core/static/dsgov/**`
deste repositório) — a suíte NUNCA depende de a instalação de referência do DSGov para passar
(invariante de portabilidade, documento do projeto § Constraints`); o segundo teste
usa o padrão DSGov só para AUDITAR quando ela estiver disponível no host, e é
pulado (`skipUnless`) quando não está.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

from django.test import SimpleTestCase

RAIZ_REPO = Path(__file__).resolve().parents[3]
VERIFICADOR_PROJETO = RAIZ_REPO / "ops" / "dsgov" / "verificar.py"


def _rodar(caminho_script):
    resultado = subprocess.run(
        [
            sys.executable,
            str(caminho_script),
            str(RAIZ_REPO),
            "--avisos-como-erros",
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return json.loads(resultado.stdout)


class TestConformidadeDSGov(SimpleTestCase):
    """`ops/dsgov/verificar.py --avisos-como-erros` tem de devolver 0 erros
    sobre o repositório INTEIRO — o critério de pronto da Fase 26 inteira
    ("o padrão DSGov é fonte da verdade"), não uma amostra de
    telas."""

    def test_verificador_do_projeto_nao_acusa_erro(self):
        dados = _rodar(VERIFICADOR_PROJETO)
        self.assertEqual(
            dados["erros"],
            [],
            f"{len(dados['erros'])} erro(s) de conformidade DSGov — rode "
            f"`python3 {VERIFICADOR_PROJETO} {RAIZ_REPO} --avisos-como-erros` "
            "para o relatório completo.",
        )
