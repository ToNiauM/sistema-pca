"""do plano ((2)/(3)) — matriz de
perfis nas seis ferramentas (`consultar_processos`, `ficha`,
`fluxo_de_caixa`, `contratos_a_vencer`, `memoria_de_calculo`,
`buscar_texto`), busca global, histórico após revogação e referências
resolvíveis por perfil. Fonte não autorizada ausente também do payload
enviado à API (A05)."""

import hashlib
import json
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.assistente import fontes as fontes_mod
from apps.assistente import ferramentas, indice
from apps.assistente.cliente import RespostaEmbeddings
from apps.assistente.tests.base import (
    AssistenteTestBase,
    ClienteFalso,
    patch_cliente,
    resposta_ferramenta,
    resposta_texto,
)
from apps.catalogo.models import Exercicio
from apps.pca.models import Acompanhamento, Processo, SituacaoNormalizada
from apps.pca.sei import execucoes
from apps.pca.tests.test_estrutura_paginas import _coletar

_DIM = 8


def _vetor_do_hash(texto: str, dim: int = _DIM):
    digest = hashlib.sha256(texto.encode("utf-8")).digest()
    return [((digest[i % len(digest)] / 255.0) * 2 - 1) for i in range(dim)]


class _ClienteEmbeddingsFalso:
    def embeddings(self, textos, timeout_s):
        return RespostaEmbeddings(vetores=[_vetor_do_hash(t) for t in textos], tokens=len(textos))


# Argumentos mínimos válidos por ferramenta — `executar()` só exige que as
# chaves presentes estejam no esquema (`set(argumentos) <= propriedades`);
# chaves ausentes usam os defaults da própria função.
ARGUMENTOS = {
    "consultar_processos": {},
    "ficha": {"item": 1},
    "fluxo_de_caixa": {},
    "memoria_de_calculo": {"item": 1},
    "contratos_a_vencer": {},
    "buscar_texto": {"pergunta": "o que ficou combinado sobre o item 1?"},
}

# MATRIZ declarativa: ferramenta -> perfil -> "ok" | "recusa" | "parcial".
MATRIZ = {
    "consultar_processos": {
        "visualizador": "ok", "editor": "ok", "dirigente_sem_acomp": "ok",
        "dirigente": "ok", "superusuario": "ok",
    },
    "ficha": {
        "visualizador": "parcial", "editor": "ok", "dirigente_sem_acomp": "parcial",
        "dirigente": "ok", "superusuario": "ok",
    },
    "fluxo_de_caixa": {
        "visualizador": "recusa", "editor": "recusa", "dirigente_sem_acomp": "ok",
        "dirigente": "ok", "superusuario": "ok",
    },
    "memoria_de_calculo": {
        "visualizador": "recusa", "editor": "recusa", "dirigente_sem_acomp": "ok",
        "dirigente": "ok", "superusuario": "ok",
    },
    "contratos_a_vencer": {
        "visualizador": "recusa", "editor": "recusa", "dirigente_sem_acomp": "recusa",
        "dirigente": "ok", "superusuario": "ok",
    },
    "buscar_texto": {
        "visualizador": "ok", "editor": "ok", "dirigente_sem_acomp": "ok",
        "dirigente": "ok", "superusuario": "ok",
    },
}


class MatrizPerfisBase(AssistenteTestBase):
    def setUp(self):
        super().setUp()
        User = get_user_model()
        self.dirigente_sem_acomp = User.objects.create_user(
            email="dirigente-sem-acomp-matriz@pca.local", password="senha-segura"
        )
        self.dirigente_sem_acomp.groups.add(Group.objects.get(name="dirigentes"))
        self.superusuario = User.objects.create_superuser(
            email="super-matriz@pca.local", password="senha-segura"
        )
        self.exercicio = Exercicio.objects.get(ano=2026)
        self.perfis = {
            "visualizador": self.visualizador,
            "editor": self.editor,
            "dirigente_sem_acomp": self.dirigente_sem_acomp,
            "dirigente": self.dirigente,
            "superusuario": self.superusuario,
        }


class TestMatrizExecutarDireto(MatrizPerfisBase):
    """Primeiro teste: a matriz percorrida diretamente por
    `ferramentas.executar` — recusa nunca consulta nada além da própria
    permissão, `ok`/`parcial` nunca recusam por completo."""

    def test_matriz_completa(self):
        for nome, por_perfil in MATRIZ.items():
            for perfil_nome, esperado in por_perfil.items():
                usuario = self.perfis[perfil_nome]
                with self.subTest(ferramenta=nome, perfil=perfil_nome):
                    # Aquece o cache de permissões — não é o que a
                    # assertNumQueries de "recusa" abaixo está medindo.
                    usuario.has_perm("pca.ver_analises")
                    usuario.has_perm("pca.view_acompanhamento")
                    with CaptureQueriesContext(connection) as capturado:
                        envelope = ferramentas.executar(
                            nome,
                            json.dumps(ARGUMENTOS[nome]),
                            usuario=usuario,
                            exercicio_padrao=self.exercicio,
                        )
                    if esperado == "recusa":
                        self.assertTrue(envelope.sem_permissao, (nome, perfil_nome))
                        self.assertNotIn("por_ano", envelope.dados)
                        self.assertNotIn("kpis", envelope.dados)
                        self.assertNotIn("linhas", envelope.dados)
                        self.assertLessEqual(
                            len(capturado.captured_queries), 1, capturado.captured_queries
                        )
                    elif esperado == "ok":
                        self.assertFalse(envelope.sem_permissao, (nome, perfil_nome, envelope.dados))
                    elif esperado == "parcial":
                        self.assertTrue(envelope.sem_permissao, (nome, perfil_nome))
                        self.assertIn("item_pca", envelope.dados)
                        self.assertIsNone(envelope.dados.get("acompanhamentos"))


class TestTrilhaCompletaPorPerfil(MatrizPerfisBase):
    """Segundo teste: trilha real via POST, uma pergunta por
    ferramenta (6 perguntas por perfil) — a recusa aparece na resposta
    RENDERIZADA mesmo com o modelo devolvendo texto vazio (A04), e o
    payload de `ClienteFalso.chamadas` nunca carrega conteúdo restrito."""

    def _perguntar(self, client, tool_name, args):
        fake = ClienteFalso([resposta_ferramenta(tool_name, args), resposta_texto("")])
        with patch_cliente(fake):
            get1 = client.get(reverse("assistente:pagina") + "?exercicio=2026")
            html = get1.content.decode()
            import re

            m = re.search(r'name="requisicao_id" value="([^"]*)"', html)
            requisicao_id = m.group(1)
            post = client.post(
                reverse("assistente:perguntar"),
                {
                    "pergunta": f"pergunta sobre {tool_name}",
                    "requisicao_id": requisicao_id,
                    "exercicio": 2026,
                },
            )
            self.assertIn(post.status_code, (302, 400))
            get2 = client.get(reverse("assistente:pagina") + "?exercicio=2026")
        return get2.content.decode(), fake.chamadas

    def test_trilha_por_perfil(self):
        # Item com acompanhamento restrito, para provar que o payload
        # enviado ao provedor nunca carrega o texto do evento quando o
        # perfil não tem `view_acompanhamento`.
        processo = Processo.objects.filter(exercicio__ano=2026).first()
        situacao, _ = SituacaoNormalizada.objects.get_or_create(nome="Em tramitação")
        Acompanhamento.objects.create(
            processo=processo,
            referencia_data=timezone.localdate(),
            origem_hash="hash-matriz-perfis-1",
            evento="TEXTO-SECRETO-DE-ACOMPANHAMENTO",
            tipo_evento="reuniao_acompanhamento",
            situacao_informada="Em andamento",
            situacao=situacao,
        )

        for perfil_nome, usuario in self.perfis.items():
            client = Client(HTTP_X_FORWARDED_PROTO="https")
            client.force_login(usuario)
            for nome, args in ARGUMENTOS.items():
                esperado = MATRIZ[nome][perfil_nome]
                html, chamadas = self._perguntar(client, nome, args)
                with self.subTest(perfil=perfil_nome, ferramenta=nome):
                    if esperado == "recusa":
                        self.assertIn("Sem permissão para consultar", html)
                    payload_texto = json.dumps(chamadas)
                    if not usuario.has_perm("pca.view_acompanhamento"):
                        self.assertNotIn("TEXTO-SECRETO-DE-ACOMPANHAMENTO", payload_texto)
                    if not usuario.has_perm("pca.ver_analises"):
                        self.assertNotIn("por_ano", payload_texto)


class TestHistoricoAposRevogacao(MatrizPerfisBase):
    """Terceiro teste — revogar `dirigentes` invalida a conversa
    inteira; a próxima pergunta não reenvia o histórico anterior."""

    def test_revogacao_invalida_conversa(self):
        client = Client(HTTP_X_FORWARDED_PROTO="https")
        client.force_login(self.dirigente)

        fake1 = ClienteFalso([resposta_ferramenta("fluxo_de_caixa", {}), resposta_texto("ok fluxo")])
        with patch_cliente(fake1):
            get1 = client.get(reverse("assistente:pagina") + "?exercicio=2026")
            import re

            requisicao_id = re.search(
                r'name="requisicao_id" value="([^"]*)"', get1.content.decode()
            ).group(1)
            client.post(
                reverse("assistente:perguntar"),
                {"pergunta": "como está o fluxo?", "requisicao_id": requisicao_id, "exercicio": 2026},
            )
            get2 = client.get(reverse("assistente:pagina") + "?exercicio=2026")
        self.assertIn("ok fluxo", get2.content.decode())

        # Revoga o grupo que concede `ver_analises` — a próxima requisição
        # carrega um `request.user` NOVO a partir da sessão (nunca o
        # objeto Python `self.dirigente` em cache), então a permissão
        # revogada já vale na view seguinte.
        self.dirigente.groups.remove(Group.objects.get(name="dirigentes"))

        get3 = client.get(reverse("assistente:pagina") + "?exercicio=2026")
        self.assertNotIn("ok fluxo", get3.content.decode())
        self.assertNotIn("como está o fluxo?", get3.content.decode())

        fake2 = ClienteFalso([resposta_texto("nova resposta")])
        with patch_cliente(fake2):
            requisicao_id2 = re.search(
                r'name="requisicao_id" value="([^"]*)"', get3.content.decode()
            ).group(1)
            client.post(
                reverse("assistente:perguntar"),
                {"pergunta": "nova pergunta", "requisicao_id": requisicao_id2, "exercicio": 2026},
            )
        payload_enviado = json.dumps(fake2.chamadas)
        self.assertNotIn("como está o fluxo?", payload_enviado)
        self.assertNotIn("ok fluxo", payload_enviado)


class TestBuscaGlobal(MatrizPerfisBase):
    """Quarto teste — `buscar_texto(fonte=None)` como
    visualizador devolve só fontes autenticadas, mesmo com trechos
    restritos de escore máximo."""

    def setUp(self):
        super().setUp()
        self._tmp_indice = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp_indice.cleanup)
        from django.test import override_settings

        self._override_indice = override_settings(
            IA_INDICE_PATH=str(Path(self._tmp_indice.name) / "indice.sqlite3"),
        )
        self._override_indice.enable()
        self.addCleanup(self._override_indice.disable)
        indice._CACHE_MATRIZ.clear()
        self.addCleanup(indice._CACHE_MATRIZ.clear)

        self.trecho_acompanhamento = fontes_mod.Trecho(
            fonte="acompanhamento", ref="ac:1", ordem=0, titulo="Acompanhamento",
            texto="ficou combinado em julho sobre o item 42",
            url=None, exercicio=2026, item_pca=42,
            permissao="pca.view_acompanhamento", atualizado_em=None,
        )
        self.trecho_analises = fontes_mod.Trecho(
            fonte="docs", ref="analises-fluxo-de-caixa/0", ordem=0, titulo="Análises",
            texto="texto restrito sobre fluxo de caixa",
            url=None, exercicio=None, item_pca=None,
            permissao="pca.ver_analises", atualizado_em=None,
        )
        with mock.patch(
            "apps.assistente.fontes.extrair_tudo",
            return_value=[self.trecho_acompanhamento, self.trecho_analises],
        ):
            indice.indexar(_ClienteEmbeddingsFalso(), agora=timezone.now())

    def test_visualizador_fonte_none_nao_recebe_trechos_restritos(self):
        contexto = ferramentas.ContextoExecucao(
            usuario=self.visualizador,
            exercicio_padrao=self.exercicio,
            cliente=_ClienteEmbeddingsFalso(),
            embeddings_restantes=4,
        )
        envelope = ferramentas.buscar_texto(
            self.visualizador,
            pergunta="ficou combinado em julho sobre o item 42",
            fonte=None,
            contexto=contexto,
        )
        fontes_recebidas = {t["fonte"] for t in envelope.dados["trechos"]}
        self.assertNotIn("acompanhamento", fontes_recebidas)
        for referencia in envelope.referencias:
            self.assertNotEqual(referencia["url"], self.trecho_analises.url)


class TestReferenciasResolveis(MatrizPerfisBase):
    """Quinto teste (A17) — para cada perfil `ok`, toda URL
    interna de `referencias` resolve 200; URLs externas (SEI) nunca são
    requisitadas, só conferidas pelo prefixo."""

    def test_referencias_internas_resolvem_200(self):
        for nome, por_perfil in MATRIZ.items():
            if nome == "buscar_texto":
                continue  # sem referências garantidas sem índice publicado
            for perfil_nome, esperado in por_perfil.items():
                if esperado != "ok":
                    continue
                usuario = self.perfis[perfil_nome]
                envelope = ferramentas.executar(
                    nome,
                    json.dumps(ARGUMENTOS[nome]),
                    usuario=usuario,
                    exercicio_padrao=self.exercicio,
                )
                client = Client(HTTP_X_FORWARDED_PROTO="https")
                client.force_login(usuario)
                for referencia in envelope.referencias:
                    url = referencia["url"]
                    with self.subTest(ferramenta=nome, perfil=perfil_nome, url=url):
                        if url.startswith("https://sei.cfc.org.br/"):
                            continue
                        resposta = client.get(url, HTTP_HOST="testserver")
                        self.assertEqual(resposta.status_code, 200)
