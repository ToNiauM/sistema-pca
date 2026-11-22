"""Pseudo-streaming: `Cliente.chat` com `stream=True` +
`agente.responder` com callback de progresso. Sem chamada real ao provedor
(SDK sempre falso/mockado nesta suíte)."""

import threading
import time
from unittest import mock

from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from apps.assistente import agente
from apps.assistente.cliente import ClienteOpenAI
from apps.assistente.tests.base import (
    AssistenteTestBase,
    ClienteFalso,
    resposta_ferramenta,
    resposta_texto,
)
from apps.assistente.tests.test_tela import _extrair_requisicao_id


class _FunctionDelta:
    def __init__(self, name=None, arguments=None):
        self.name = name
        self.arguments = arguments


class _ToolCallDelta:
    def __init__(self, index, id=None, name=None, arguments=None):
        self.index = index
        self.id = id
        self.function = _FunctionDelta(name=name, arguments=arguments) if (name or arguments) else None


class _Delta:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _Choice:
    def __init__(self, delta=None, finish_reason=None):
        self.delta = delta
        self.finish_reason = finish_reason


class _Usage:
    def __init__(self, prompt_tokens=0, completion_tokens=0):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _Chunk:
    def __init__(self, choices=None, usage=None):
        self.choices = choices or []
        self.usage = usage


def _construir_cliente_com_sdk_falso():
    """`ClienteOpenAI` real, mas com `_cliente`/`_openai` substituídos por
    dublês — não abre conexão nenhuma, só exercita `_chat_com_stream`."""
    cliente = ClienteOpenAI.__new__(ClienteOpenAI)
    cliente.modelo_chat = "gpt-4o-fake"
    cliente.modelo_embed = "text-embedding-3-small-fake"
    cliente.timeout_padrao_s = 30.0
    cliente.esforco_raciocinio = ""
    import openai

    cliente._openai = openai
    cliente._cliente = mock.MagicMock()
    return cliente


class TestClienteChatComStream(SimpleTestCase):
    def test_content_em_blocos_chama_callback_e_concatena(self):
        cliente = _construir_cliente_com_sdk_falso()
        chunks = [
            _Chunk(choices=[_Choice(delta=_Delta(content="Olá"))]),
            _Chunk(choices=[_Choice(delta=_Delta(content=", tudo"))]),
            _Chunk(
                choices=[_Choice(delta=_Delta(content=" bem?"), finish_reason="stop")],
                usage=_Usage(prompt_tokens=10, completion_tokens=3),
            ),
        ]
        cliente._cliente.chat.completions.create.return_value = iter(chunks)
        blocos_recebidos = []
        resposta = cliente.chat(
            [{"role": "user", "content": "oi"}],
            [],
            "none",
            100,
            10.0,
            ao_receber_texto=blocos_recebidos.append,
        )
        self.assertEqual(blocos_recebidos, ["Olá", ", tudo", " bem?"])
        self.assertEqual(resposta.conteudo, "Olá, tudo bem?")
        self.assertEqual(resposta.tokens_entrada, 10)
        self.assertEqual(resposta.tokens_saida, 3)
        self.assertEqual(resposta.motivo_parada, "stop")
        kwargs = cliente._cliente.chat.completions.create.call_args.kwargs
        self.assertTrue(kwargs["stream"])
        self.assertEqual(kwargs["stream_options"], {"include_usage": True})

    def test_tool_calls_fragmentados_remontam_argumentos(self):
        cliente = _construir_cliente_com_sdk_falso()
        chunks = [
            _Chunk(
                choices=[
                    _Choice(
                        delta=_Delta(
                            tool_calls=[
                                _ToolCallDelta(0, id="call_1", name="ficha", arguments='{"item"')
                            ]
                        )
                    )
                ]
            ),
            _Chunk(
                choices=[
                    _Choice(
                        delta=_Delta(tool_calls=[_ToolCallDelta(0, arguments=": 4}")]),
                        finish_reason="tool_calls",
                    )
                ],
                usage=_Usage(prompt_tokens=5, completion_tokens=1),
            ),
        ]
        cliente._cliente.chat.completions.create.return_value = iter(chunks)
        resposta = cliente.chat(
            [{"role": "user", "content": "oi"}], [], "auto", 100, 10.0, ao_receber_texto=lambda _: None
        )
        self.assertEqual(len(resposta.chamadas), 1)
        chamada = resposta.chamadas[0]
        self.assertEqual(chamada.id, "call_1")
        self.assertEqual(chamada.nome, "ficha")
        self.assertEqual(chamada.argumentos_json, '{"item": 4}')
        import json

        self.assertEqual(json.loads(chamada.argumentos_json), {"item": 4})

    def test_sem_callback_caminho_atual_intacto(self):
        """Sem `ao_receber_texto`, `chat` não entra no caminho de stream."""
        cliente = _construir_cliente_com_sdk_falso()
        resposta_falsa = mock.MagicMock()
        resposta_falsa.choices = [mock.MagicMock(finish_reason="stop")]
        resposta_falsa.choices[0].message.content = "olá"
        resposta_falsa.choices[0].message.tool_calls = None
        resposta_falsa.usage.prompt_tokens = 1
        resposta_falsa.usage.completion_tokens = 1
        cliente._cliente.chat.completions.create.return_value = resposta_falsa
        resposta = cliente.chat([{"role": "user", "content": "oi"}], [], "none", 100, 10.0)
        self.assertEqual(resposta.conteudo, "olá")
        kwargs = cliente._cliente.chat.completions.create.call_args.kwargs
        self.assertNotIn("stream", kwargs)


class TestAgenteComProgresso(AssistenteTestBase):
    def test_etapas_na_ordem_e_texto_parcial_cresce(self):
        fake = ClienteFalso(
            [
                resposta_ferramenta("consultar_processos", {"exercicio": 2026, "limite": 20}),
                resposta_texto("Há 3 itens atrasados."),
            ]
        )
        exercicio = self._exercicio_2026()
        eventos = []
        resposta = agente.responder(
            usuario=self.editor,
            exercicio=exercicio,
            pergunta="quantos itens estão atrasados?",
            trocas=[],
            cliente=fake,
            agora=timezone.now(),
            progresso=lambda etapa, parcial: eventos.append((etapa, parcial)),
        )
        etapas = [e for e, _ in eventos]
        self.assertEqual(etapas[0], "Consultando processos…")
        self.assertTrue(all(e == "Redigindo…" for e in etapas[1:]))
        parciais = [p for e, p in eventos if e == "Redigindo…"]
        self.assertTrue(parciais)
        for anterior, atual in zip(parciais, parciais[1:]):
            self.assertTrue(atual.startswith(anterior))
        self.assertEqual(parciais[-1], resposta.texto_md)

    def test_sem_progresso_cliente_falso_nao_recebe_callback(self):
        fake = ClienteFalso([resposta_texto("Há 3 itens atrasados.")])
        exercicio = self._exercicio_2026()
        agente.responder(
            usuario=self.editor,
            exercicio=exercicio,
            pergunta="quantos itens estão atrasados?",
            trocas=[],
            cliente=fake,
            agora=timezone.now(),
        )
        self.assertFalse(fake.chamadas[-1]["stream"])

    def _exercicio_2026(self):
        from apps.catalogo.models import Exercicio

        return Exercicio.objects.get(ano=2026)


class _ClienteLento(ClienteFalso):
    """Mesmo `ClienteFalso`, mas com um `sleep` antes de responder — usado
    só para o teste de thread DE VERDADE (`TestThreadReal`), nunca chama o
    provedor real."""

    def chat(self, *args, **kwargs):
        time.sleep(0.3)
        return super().chat(*args, **kwargs)


class TestThreadReal(AssistenteTestBase):
    """`_iniciar_thread` verdadeiro (não o patch síncrono da base) — prova
    que a bolha fica `em_andamento` enquanto a thread ainda roda e conclui
    (`HX-Location`) depois que a thread termina."""

    def test_thread_de_verdade_fica_em_andamento_e_depois_conclui(self):
        self._patch_thread_sincrona.stop()
        threads_criadas = []

        def _iniciar_com_captura(alvo, *args, **kwargs):
            fio = threading.Thread(target=alvo, args=args, kwargs=kwargs, daemon=True)
            threads_criadas.append(fio)
            fio.start()

        try:
            self.client.force_login(self.editor)
            get1 = self.client.get(reverse("assistente:pagina") + "?exercicio=2026")
            rid = _extrair_requisicao_id(get1.content.decode())
            fake = _ClienteLento([resposta_texto("pronto de verdade")])
            # O `mock.patch` de `criar_cliente` precisa continuar ativo até
            # a thread de verdade terminar — ela chama `criar_cliente()`
            # dentro do próprio corpo, bem depois do POST já ter devolvido
            # a resposta; sair do `with` antes do `join` deixaria a thread
            # construir um `ClienteOpenAI` REAL com a chave falsa de teste.
            with (
                mock.patch("apps.assistente.cliente.criar_cliente", return_value=fake),
                mock.patch(
                    "apps.assistente.views._iniciar_thread", side_effect=_iniciar_com_captura
                ),
            ):
                resposta = self.client.post(
                    reverse("assistente:perguntar"),
                    {"pergunta": "oi", "requisicao_id": rid, "exercicio": 2026},
                )
                self.assertEqual(resposta.status_code, 302)
                self.assertEqual(len(threads_criadas), 1)

                # A thread ainda está no `time.sleep(0.3)` — a bolha continua
                # em andamento.
                em_andamento = self.client.get(reverse("assistente:andamento", args=[rid]))
                self.assertEqual(em_andamento.status_code, 200)
                self.assertIn('id="bolha-andamento"', em_andamento.content.decode())

                threads_criadas[0].join(timeout=5)
                self.assertFalse(threads_criadas[0].is_alive())

            concluido = self.client.get(
                reverse("assistente:andamento", args=[rid]), HTTP_HX_REQUEST="true"
            )
            self.assertIn("HX-Location", concluido)
            pagina = self.client.get(reverse("assistente:pagina") + "?exercicio=2026")
            self.assertIn("pronto de verdade", pagina.content.decode())
        finally:
            self._patch_thread_sincrona.start()


class TestParametrosDoModelo(SimpleTestCase):
    """Modelos gpt-6 recusam `max_tokens` e só aceitam ferramentas na API de chat com raciocínio "none";
    o gpt-4.1 recusa `reasoning_effort`. O cliente manda `max_completion_tokens` sempre e o esforço só
    quando configurado."""

    def test_sem_esforco_configurado_nao_manda_reasoning_effort(self):
        cliente = _construir_cliente_com_sdk_falso()
        self.assertEqual(cliente._limites(1500), {"max_completion_tokens": 1500})

    def test_com_esforco_none_manda_reasoning_effort(self):
        cliente = _construir_cliente_com_sdk_falso()
        cliente.esforco_raciocinio = "none"
        self.assertEqual(cliente._limites(1500), {"max_completion_tokens": 1500, "reasoning_effort": "none"})

    def test_chamada_ao_sdk_nunca_usa_max_tokens(self):
        cliente = _construir_cliente_com_sdk_falso()
        cliente.esforco_raciocinio = "none"
        try:
            cliente.chat([{"role": "user", "content": "oi"}], [], "auto", 100, 5)
        except Exception:  # noqa: BLE001 — o dublê não devolve resposta válida; só importam os argumentos
            pass
        kwargs = cliente._cliente.chat.completions.create.call_args.kwargs
        self.assertNotIn("max_tokens", kwargs)
        self.assertEqual(kwargs["max_completion_tokens"], 100)
        self.assertEqual(kwargs["reasoning_effort"], "none")
