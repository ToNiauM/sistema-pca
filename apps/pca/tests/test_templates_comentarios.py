"""Regressão do vazamento de comentário de template.

A sintaxe `{# ... #}` do Django Template Language é reconhecida pelo lexer
apenas dentro de UMA linha: o padrão é `\\{%.*?%\\}|\\{\\{.*?\\}\\}|\\{#.*?#\\}`
sem `re.DOTALL`. Um `{#` que abre numa linha e fecha noutra não é comentário
— é texto literal, e sai renderizado na página para o usuário.

A correção é trocar todos por `{% comment %}...{% endcomment %}`, que é
multi-linha por construção. Estes testes impedem a volta por dois
caminhos independentes:

1. `test_nenhum_comentario_multilinha_nos_templates` — varredura estática dos
   arquivos, cobre inclusive template que nenhuma rota exercita hoje.
2. `test_nenhuma_rota_vaza_comentario` — prova pelo HTML de resposta real.
"""

import re
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

ARQUIVO_REAL = "apps/pca/fixtures/modelo-controle-exemplo.xlsx"

# Diretórios de template do PROJETO. Deliberadamente não usa
# get_app_template_dirs(): ele traria os templates do django.contrib.admin
# em site-packages, que não são nossos para consertar.
RAIZES_TEMPLATES = ("apps", "core")

ABERTURA_COMENTARIO = re.compile(r"\{#")
COMENTARIO_DE_UMA_LINHA = re.compile(r"\{#.*?#\}")

# <style> e <script> viajam no HTML mas o usuário nunca os lê. Comentário de
# CSS (/* UI-SPEC ... */) e de JS (// UI-SPEC ...) dentro deles é legítimo e
# não é o defeito investigado — o defeito é texto de comentário aparecendo
# como conteúdo da página. Por isso a checagem de "UI-SPEC" roda sobre o
# corpo COM esses blocos removidos.
BLOCOS_NAO_VISIVEIS = re.compile(
    r"<(style|script)\b[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE
)


def _texto_visivel(corpo_html):
    return BLOCOS_NAO_VISIVEIS.sub("", corpo_html)


def _templates_do_projeto():
    base = Path(settings.BASE_DIR)
    for raiz in RAIZES_TEMPLATES:
        yield from sorted((base / raiz).rglob("templates/**/*.html"))


class TestComentariosDeTemplate(TestCase):
    """Varredura estática — não precisa de banco nem de dados importados."""

    def test_existem_templates_para_varrer(self):
        """Guarda contra o teste passar por não ter achado arquivo nenhum."""
        self.assertGreater(
            len(list(_templates_do_projeto())),
            5,
            "A varredura não encontrou templates — o glob de RAIZES_TEMPLATES "
            "quebrou e os outros testes deste módulo estariam passando vazios.",
        )

    def test_nenhum_comentario_multilinha_nos_templates(self):
        infratores = []
        for caminho in _templates_do_projeto():
            texto = caminho.read_text(encoding="utf-8")
            # Remove os comentários bem formados (abrem e fecham na mesma
            # linha); qualquer `{#` restante abre um bloco que o lexer não
            # fecha, e portanto vaza como texto.
            restante = COMENTARIO_DE_UMA_LINHA.sub("", texto)
            for numero, linha in enumerate(restante.splitlines(), start=1):
                if ABERTURA_COMENTARIO.search(linha):
                    relativo = caminho.relative_to(Path(settings.BASE_DIR))
                    infratores.append(f"{relativo.as_posix()}:{numero}")

        self.assertEqual(
            infratores,
            [],
            "Comentário `{# ... #}` quebrando linha — o Django só reconhece "
            "essa sintaxe dentro de uma linha, então o bloco sai renderizado "
            "na tela. Use {% comment %}...{% endcomment %}. Ocorrências: "
            + ", ".join(infratores),
        )


class TestRotasNaoVazamComentario(TransactionTestCase):
    """Prova pelo HTML servido. Mesmo padrão de setUp das demais suítes da
    fase: import real por teste (TransactionTestCase dá flush e nunca chama
    setUpTestData) e serialized_rollback para preservar o usuário de serviço
    criado por migração de dados."""

    serialized_rollback = True

    def setUp(self):
        call_command(
            "importar_pca",
            ARQUIVO_REAL,
            "--usuario=importador@pca.local",
            "--exercicio=2026",
            stdout=StringIO(),
        )
        self.usuario = get_user_model().objects.create_user(
            email="leitor@pca.local", password="x-forte-123"
        )
        self.client.force_login(self.usuario)

    def test_nenhuma_rota_vaza_comentario(self):
        rotas = [
            reverse("raiz"),
            reverse("pca:tabela"),
            # /processo/99999 não resolve rota alguma — 404 de roteamento
            # puro, não o template processo_nao_encontrado.html.
            reverse("pca:editar_processo", args=[2026, 1]) + "?modo=ver",
            "/processo/99999",
        ]
        for rota in rotas:
            with self.subTest(rota=rota):
                corpo = self.client.get(rota).content.decode("utf-8")
                self.assertNotIn(
                    "{#",
                    corpo,
                    f"{rota} devolveu abertura de comentário de template no HTML.",
                )
                self.assertNotIn(
                    "UI-SPEC",
                    _texto_visivel(corpo),
                    f"{rota} vazou texto de comentário de código para o usuário.",
                )

    def test_fragmento_htmx_de_filtro_nao_vaza_comentario(self):
        """A troca de filtro devolve _tabela_resultado.html + o OOB de
        _tags_filtros.html/_acoes_export.html — caminho distinto da página
        completa, e três dos dezesseis blocos vazados viviam nele."""
        for rota in (reverse("pca:tabela"), reverse("raiz")):
            with self.subTest(rota=rota):
                corpo = self.client.get(
                    rota,
                    {"status": "concluido"},
                    headers={"hx-request": "true"},
                ).content.decode("utf-8")
                self.assertNotIn("{#", corpo)
                self.assertNotIn("UI-SPEC", _texto_visivel(corpo))
