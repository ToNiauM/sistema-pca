"""Guarda único de conformidade com o padrão dsgov: um repositório
inteiro verificado por um único script, contra um único padrão.

`ops/dsgov/verificar.py` é a cópia versionada (mesmas 10 regras, só
`CORE_CSS`/`FA_CSS`/`SKILL_CSS_DIR` reapontados para `core/static/dsgov/**`
deste repositório) — a suíte nunca depende de `~/.claude` para passar; o
segundo teste usa a skill só para auditar quando ela estiver disponível
no host, e é pulado (`skipUnless`) quando não está.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

from django.test import SimpleTestCase

RAIZ_REPO = Path(__file__).resolve().parents[3]
VERIFICADOR_PROJETO = RAIZ_REPO / "ops" / "dsgov" / "verificar.py"
VERIFICADOR_SKILL = (
    Path.home() / ".claude" / "skills" / "dsgov" / "scripts" / "verificar.py"
)


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
    """`ops/dsgov/verificar.py --avisos-como-erros` tem de devolver 0
    erros sobre o repositório inteiro, não uma amostra de telas."""

    def test_verificador_do_projeto_nao_acusa_erro(self):
        dados = _rodar(VERIFICADOR_PROJETO)
        self.assertEqual(
            dados["erros"],
            [],
            f"{len(dados['erros'])} erro(s) de conformidade DSGov — rode "
            f"`python3 {VERIFICADOR_PROJETO} {RAIZ_REPO} --avisos-como-erros` "
            "para o relatório completo.",
        )

    @unittest.skipUnless(
        VERIFICADOR_SKILL.exists(),
        "skill dsgov não instalada neste host — ops/dsgov/verificar.py "
        "continua sendo a fonte de verdade da suíte (invariante de "
        "portabilidade); este teste só AUDITA quando a skill existe.",
    )
    def test_copia_do_projeto_concorda_com_a_skill(self):
        """A cópia versionada não pode divergir silenciosamente do
        original da skill (fora dos 3 caminhos de vendor, propositalmente
        reapontados)."""
        dados_projeto = _rodar(VERIFICADOR_PROJETO)
        dados_skill = _rodar(VERIFICADOR_SKILL)
        self.assertEqual(dados_projeto, dados_skill)

    @unittest.skipUnless(
        VERIFICADOR_SKILL.exists(),
        "skill dsgov não instalada neste host — este teste só AUDITA "
        "paridade de base.html quando a skill existe (mesmo padrão de "
        "test_copia_do_projeto_concorda_com_a_skill).",
    )
    def test_base_html_concorda_com_a_skill(self):
        """`base.html` só muda na origem da skill; a cópia deste
        repositório precisa ficar byte a byte idêntica. Divergência aqui
        é sinal de edição feita no caminho errado."""
        base_projeto = (RAIZ_REPO / "core" / "templates" / "base.html").read_bytes()
        base_skill = (
            Path.home()
            / ".claude"
            / "skills"
            / "dsgov"
            / "assets"
            / "projeto"
            / "core"
            / "templates"
            / "base.html"
        ).read_bytes()
        self.assertEqual(base_projeto, base_skill)

    @unittest.skipUnless(
        VERIFICADOR_SKILL.exists(),
        "skill dsgov não instalada neste host — este teste só AUDITA "
        "paridade de _header.html quando a skill existe (mesmo padrão de "
        "test_base_html_concorda_com_a_skill).",
    )
    def test_header_html_concorda_com_a_skill(self):
        """`_header.html` (campo de busca) só muda na origem da skill; a
        cópia deste repositório precisa ficar byte a byte idêntica."""
        caminho = Path("core") / "templates" / "dsgov" / "_header.html"
        header_projeto = (RAIZ_REPO / caminho).read_bytes()
        header_skill = (
            Path.home() / ".claude" / "skills" / "dsgov" / "assets" / "projeto" / caminho
        ).read_bytes()
        self.assertEqual(header_projeto, header_skill)

    @unittest.skipUnless(
        VERIFICADOR_SKILL.exists(),
        "skill dsgov não instalada neste host — este teste só AUDITA "
        "paridade de dsgov.js quando a skill existe (mesmo padrão de "
        "test_base_html_concorda_com_a_skill).",
    )
    def test_dsgov_js_concorda_com_a_skill(self):
        """`dsgov.js` (atalho Alt+Shift+P) só muda na origem da skill; a
        cópia deste repositório precisa ficar byte a byte idêntica."""
        caminho = Path("core") / "static" / "dsgov" / "js" / "dsgov.js"
        js_projeto = (RAIZ_REPO / caminho).read_bytes()
        js_skill = (
            Path.home() / ".claude" / "skills" / "dsgov" / "assets" / "projeto" / caminho
        ).read_bytes()
        self.assertEqual(js_projeto, js_skill)
