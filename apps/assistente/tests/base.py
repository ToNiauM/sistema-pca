"""Base comum da suíte do assistente (Fase 39). Mesmo padrão de
`apps.pca.tests.test_analise_telas`/`test_sei_comandos`: import real da
planilha + `configurar_grupos`, `tempfile.TemporaryDirectory()` +
`override_settings` para os 3 SQLite auxiliares (nunca `BASE_DIR/data`
real) e um `ClienteFalso` que os testes de agente/tela substituem via
`patch_cliente`."""

import hashlib
import json
import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import Client, TransactionTestCase, override_settings

from apps.assistente.cliente import ChamadaFerramenta, RespostaChat, RespostaEmbeddings

ARQUIVO_REAL = "Modelo_de_Controle_.xlsx"

_DIM_EMBEDDING_FALSO = 8


def vetor_do_hash(texto: str, dim: int = _DIM_EMBEDDING_FALSO) -> list[float]:
    """Vetor determinístico derivado do SHA-256 do texto — mesmo padrão
    usado por `apps.assistente.tests.test_indice`/`test_busca_acl` (Fase
    39), exposto aqui para que `ClienteFalso.embeddings`
    e testes de ponta a ponta via `agente.responder` usem o MESMO vetor
    para o mesmo texto, sem chamada real ao provedor."""
    digest = hashlib.sha256(texto.encode("utf-8")).digest()
    return [((digest[i % len(digest)] / 255.0) * 2 - 1) for i in range(dim)]


class ClienteFalso:
    """Substitui `ClienteOpenAI`: devolve `RespostaChat`s scriptadas em
    ordem, registra cada payload enviado (`mensagens`/`ferramentas`/
    `tool_choice`) em `self.chamadas`, e chama `ao_chamar()` (gancho da
    corrida de logout/revogação) antes de responder. `embeddings`
    (39-02) devolve um vetor determinístico por texto — nunca
    chamada real ao provedor; cada lote pedido fica em
    `self.chamadas_embeddings` (lista de listas de texto)."""

    def __init__(self, respostas=None, ao_chamar=None):
        self.respostas = list(respostas or [])
        self.ao_chamar = ao_chamar
        self.chamadas = []
        self.chamadas_embeddings = []
        self.modelo_chat = "gpt-4o-fake"
        self.modelo_embed = "text-embedding-3-small-fake"

    def chat(self, mensagens, ferramentas, tool_choice, max_tokens, timeout_s, ao_receber_texto=None):
        self.chamadas.append(
            {
                "mensagens": mensagens,
                "ferramentas": ferramentas,
                "tool_choice": tool_choice,
                "max_tokens": max_tokens,
                "timeout_s": timeout_s,
                "stream": ao_receber_texto is not None,
            }
        )
        if self.ao_chamar:
            self.ao_chamar()
        if not self.respostas:
            resposta = RespostaChat(conteudo="")
        else:
            resposta = self.respostas.pop(0)
        if ao_receber_texto is not None and resposta.conteudo:
            texto = resposta.conteudo
            tamanho = max(1, len(texto) // 3)
            blocos = [texto[i : i + tamanho] for i in range(0, len(texto), tamanho)] or [texto]
            for bloco in blocos:
                ao_receber_texto(bloco)
        return resposta

    def embeddings(self, textos, timeout_s):
        self.chamadas_embeddings.append(list(textos))
        vetores = [vetor_do_hash(texto) for texto in textos]
        return RespostaEmbeddings(vetores=vetores, tokens=len(textos) * 3)


def resposta_texto(texto):
    return RespostaChat(conteudo=texto)


def resposta_ferramenta(nome, argumentos_dict, id="call_1"):
    return RespostaChat(
        conteudo=None,
        chamadas=[
            ChamadaFerramenta(id=id, nome=nome, argumentos_json=json.dumps(argumentos_dict))
        ],
    )


def patch_cliente(fake):
    return mock.patch("apps.assistente.cliente.criar_cliente", return_value=fake)


class AssistenteTestBase(TransactionTestCase):
    serialized_rollback = True

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self._override = override_settings(
            IA_API_KEY="chave-de-teste",
            IA_INDICE_PATH=str(base / "indice.sqlite3"),
            IA_ESTADO_PATH=str(base / "estado.sqlite3"),
            IA_CONVERSAS_PATH=str(base / "conversas.sqlite3"),
            SEI_DATA_DIR=str(base / "sei"),
        )
        self._override.enable()
        self.addCleanup(self._override.disable)

        call_command(
            "importar_pca",
            ARQUIVO_REAL,
            "--usuario=importador@pca.local",
            "--exercicio=2026",
            stdout=StringIO(),
        )
        call_command("configurar_grupos", stdout=StringIO())
        User = get_user_model()
        self.editor = User.objects.create_user(
            email="editor-assistente@pca.local", password="senha-segura"
        )
        self.editor.groups.add(Group.objects.get(name="editor"))
        self.visualizador = User.objects.create_user(
            email="visualizador-assistente@pca.local", password="senha-segura"
        )
        self.visualizador.groups.add(Group.objects.get(name="visualizador"))
        self.dirigente = User.objects.create_user(
            email="dirigente-assistente@pca.local", password="senha-segura"
        )
        self.dirigente.groups.add(Group.objects.get(name="editor"))
        self.dirigente.groups.add(Group.objects.get(name="dirigentes"))
        self.client = Client(HTTP_X_FORWARDED_PROTO="https")

        # `_iniciar_thread` roda de forma
        # SÍNCRONA por padrão em toda a suíte (o mesmo padrão de
        # `apps.pca.sei.execucoes`/testes do robô): o POST só devolve a
        # resposta depois que o "processamento em segundo plano" já
        # terminou, preservando o comportamento das trocas gravadas que a
        # suíte anterior a esta quick já esperava. Testes que precisam da
        # THREAD DE VERDADE (ex.: `test_streaming.TestThreadReal`) desligam
        # este patch explicitamente com `self._patch_thread_sincrona.stop()`.
        self._patch_thread_sincrona = mock.patch(
            "apps.assistente.views._iniciar_thread",
            side_effect=lambda alvo, *args, **kwargs: alvo(*args, **kwargs),
        )
        self._patch_thread_sincrona.start()
        self.addCleanup(self._patch_thread_sincrona.stop)
