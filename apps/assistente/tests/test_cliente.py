"""`ClienteOpenAI` com SDK falso (`mock.patch.dict(sys.modules,
{"openai": ...})`, já que o import do SDK é preguiçoso dentro de
`__init__`): prova `store=False`/`parallel_tool_calls=False`/
`max_retries=0`, conversão de `tool_calls`, mapeamento de exceções para
`ErroCliente` sem vazar texto/chave, e `esquema_estrito`."""

import sys
import types
from unittest import mock

from django.test import SimpleTestCase

from apps.assistente import cliente as cliente_mod


def _montar_modulo_fake(chat_create=None, embed_create=None, init_kwargs=None):
    modulo = types.ModuleType("openai")
    modulo.APITimeoutError = type("APITimeoutError", (Exception,), {})
    modulo.RateLimitError = type("RateLimitError", (Exception,), {})
    modulo.AuthenticationError = type("AuthenticationError", (Exception,), {})
    modulo.APIConnectionError = type("APIConnectionError", (Exception,), {})
    modulo.APIError = type("APIError", (Exception,), {})

    class _Completions:
        def create(self, **kwargs):
            return chat_create(**kwargs)

    class _Embeddings:
        def create(self, **kwargs):
            return embed_create(**kwargs)

    class _Chat:
        completions = _Completions()

    class _OpenAI:
        def __init__(self, **kwargs):
            if init_kwargs is not None:
                init_kwargs.update(kwargs)
            self.chat = _Chat()
            self.embeddings = _Embeddings()

    modulo.OpenAI = _OpenAI
    return modulo


def _resposta_chat(conteudo=None, tool_calls=None, motivo="stop", entrada=10, saida=5):
    return types.SimpleNamespace(
        choices=[
            types.SimpleNamespace(
                message=types.SimpleNamespace(content=conteudo, tool_calls=tool_calls),
                finish_reason=motivo,
            )
        ],
        usage=types.SimpleNamespace(prompt_tokens=entrada, completion_tokens=saida),
    )


class TestClienteOpenAI(SimpleTestCase):
    def _cliente(self, **kwargs):
        modulo = _montar_modulo_fake(**kwargs)
        with mock.patch.dict(sys.modules, {"openai": modulo}):
            return cliente_mod.ClienteOpenAI(
                api_key="sk-teste-nunca-logado",
                modelo_chat="gpt-4o",
                modelo_embed="text-embedding-3-small",
                timeout_padrao_s=30,
            ), modulo

    def test_chat_envia_flags_obrigatorias(self):
        capturado = {}
        init_kwargs = {}

        def chat_create(**kwargs):
            capturado.update(kwargs)
            return _resposta_chat(conteudo="olá")

        cliente, _ = self._cliente(chat_create=chat_create, init_kwargs=init_kwargs)
        resposta = cliente.chat([{"role": "user", "content": "oi"}], [], "auto", 100, 12)

        self.assertEqual(capturado["store"], False)
        self.assertEqual(capturado["parallel_tool_calls"], False)
        self.assertEqual(capturado["timeout"], 12)
        self.assertEqual(init_kwargs["max_retries"], 0)
        self.assertEqual(resposta.conteudo, "olá")
        self.assertEqual(resposta.tokens_entrada, 10)
        self.assertEqual(resposta.tokens_saida, 5)

    def test_tool_calls_viram_chamadaferramenta_preservando_id(self):
        tool_calls = [
            types.SimpleNamespace(
                id="call_abc",
                function=types.SimpleNamespace(
                    name="consultar_processos", arguments='{"exercicio": 2026}'
                ),
            )
        ]

        def chat_create(**kwargs):
            return _resposta_chat(conteudo=None, tool_calls=tool_calls)

        cliente, _ = self._cliente(chat_create=chat_create)
        resposta = cliente.chat([], [], "auto", 100, 10)

        self.assertEqual(len(resposta.chamadas), 1)
        self.assertEqual(resposta.chamadas[0].id, "call_abc")
        self.assertEqual(resposta.chamadas[0].nome, "consultar_processos")
        self.assertEqual(resposta.chamadas[0].argumentos_json, '{"exercicio": 2026}')

    def test_erros_do_sdk_viram_errocliente_sem_vazar_texto(self):
        casos = [
            ("RateLimitError", "limite_taxa"),
            ("APITimeoutError", "timeout"),
            ("AuthenticationError", "autenticacao"),
            ("APIConnectionError", "conexao"),
        ]
        for nome_excecao, codigo_esperado in casos:
            with self.subTest(nome_excecao):
                segredo = "sk-chave-secreta-nunca-deve-aparecer"
                caixa = {}

                def chat_create(**kwargs):
                    excecao_cls = getattr(caixa["modulo"], nome_excecao)
                    raise excecao_cls(f"payload sigiloso {segredo}")

                cliente, modulo = self._cliente(chat_create=chat_create)
                caixa["modulo"] = modulo
                with self.assertRaises(cliente_mod.ErroCliente) as ctx:
                    cliente.chat([], [], "auto", 100, 10)
                self.assertEqual(ctx.exception.codigo, codigo_esperado)
                self.assertNotIn(segredo, str(ctx.exception))
                self.assertNotIn(segredo, ctx.exception.mensagem_curta)

    def test_embeddings(self):
        def embed_create(**kwargs):
            return types.SimpleNamespace(
                data=[types.SimpleNamespace(embedding=[0.1, 0.2])],
                usage=types.SimpleNamespace(prompt_tokens=3),
            )

        cliente, _ = self._cliente(embed_create=embed_create)
        resposta = cliente.embeddings(["texto"], 10)
        self.assertEqual(resposta.vetores, [[0.1, 0.2]])
        self.assertEqual(resposta.tokens, 3)


def _montar_modulo_anthropic_fake(chat_create=None, chat_stream=None, init_kwargs=None):
    modulo = types.ModuleType("anthropic")
    modulo.APITimeoutError = type("APITimeoutError", (Exception,), {})
    modulo.RateLimitError = type("RateLimitError", (Exception,), {})
    modulo.AuthenticationError = type("AuthenticationError", (Exception,), {})
    modulo.APIConnectionError = type("APIConnectionError", (Exception,), {})
    modulo.APIError = type("APIError", (Exception,), {})

    class _FluxoFake:
        def __init__(self, textos, mensagem_final):
            self._textos = textos
            self._mensagem_final = mensagem_final

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        @property
        def text_stream(self):
            return iter(self._textos)

        def get_final_message(self):
            return self._mensagem_final

    class _Messages:
        def create(self, **kwargs):
            return chat_create(**kwargs)

        def stream(self, **kwargs):
            textos, mensagem_final = chat_stream(**kwargs)
            return _FluxoFake(textos, mensagem_final)

    class _Anthropic:
        def __init__(self, **kwargs):
            if init_kwargs is not None:
                init_kwargs.update(kwargs)
            self.messages = _Messages()

    modulo.Anthropic = _Anthropic
    return modulo


def _resposta_anthropic(blocos, motivo="end_turn", entrada=10, saida=5):
    return types.SimpleNamespace(
        content=blocos,
        stop_reason=motivo,
        usage=types.SimpleNamespace(input_tokens=entrada, output_tokens=saida),
    )


class TestClienteAnthropic(SimpleTestCase):
    def _cliente(self, cliente_embed=None, **kwargs):
        modulo = _montar_modulo_anthropic_fake(**kwargs)
        with mock.patch.dict(sys.modules, {"anthropic": modulo}):
            return (
                cliente_mod.ClienteAnthropic(
                    api_key="sk-ant-teste-nunca-logado",
                    modelo_chat="claude-haiku-4-5",
                    timeout_padrao_s=30,
                    cliente_embed=cliente_embed,
                ),
                modulo,
            )

    def test_chat_sem_stream_devolve_texto(self):
        capturado = {}

        def chat_create(**kwargs):
            capturado.update(kwargs)
            return _resposta_anthropic([types.SimpleNamespace(type="text", text="olá")])

        cliente, _ = self._cliente(chat_create=chat_create)
        resposta = cliente.chat([{"role": "user", "content": "oi"}], [], "auto", 100, 12)

        self.assertEqual(capturado["model"], "claude-haiku-4-5")
        self.assertEqual(capturado["max_tokens"], 100)
        self.assertEqual(capturado["system"], "")
        self.assertEqual(capturado["timeout"], 12)
        self.assertNotIn("store", capturado)
        self.assertNotIn("parallel_tool_calls", capturado)
        self.assertEqual(capturado["thinking"], {"type": "disabled"})
        self.assertNotIn("output_config", capturado)
        self.assertEqual(
            resposta,
            cliente_mod.RespostaChat(
                conteudo="olá", chamadas=[], tokens_entrada=10, tokens_saida=5,
                motivo_parada="end_turn",
            ),
        )

    def test_esforco_vira_output_config_sem_desligar_raciocinio(self):
        capturado = {}

        def chat_create(**kwargs):
            capturado.update(kwargs)
            return _resposta_anthropic([types.SimpleNamespace(type="text", text="olá")])

        cliente, _ = self._cliente(chat_create=chat_create)
        cliente.esforco_raciocinio = "low"
        cliente.chat([{"role": "user", "content": "oi"}], [], "auto", 100, 12)

        self.assertEqual(capturado["output_config"], {"effort": "low"})
        self.assertNotIn("thinking", capturado)

    def test_chat_com_tool_use(self):
        def chat_create(**kwargs):
            return _resposta_anthropic(
                [
                    types.SimpleNamespace(
                        type="tool_use",
                        id="toolu_1",
                        name="consultar_processos",
                        input={"exercicio": 2026},
                    )
                ]
            )

        cliente, _ = self._cliente(chat_create=chat_create)
        resposta = cliente.chat([], [], "auto", 100, 10)

        self.assertEqual(
            resposta.chamadas,
            [
                cliente_mod.ChamadaFerramenta(
                    id="toolu_1", nome="consultar_processos",
                    argumentos_json='{"exercicio": 2026}',
                )
            ],
        )

    def test_chat_com_stream_entrega_texto_incremental(self):
        recebidos = []
        mensagem_final = _resposta_anthropic([types.SimpleNamespace(type="text", text="olá")])

        def chat_stream(**kwargs):
            return ["ol", "á"], mensagem_final

        cliente, _ = self._cliente(chat_stream=chat_stream)
        resposta = cliente.chat(
            [{"role": "user", "content": "oi"}], [], "auto", 100, 12,
            ao_receber_texto=recebidos.append,
        )

        self.assertEqual(recebidos, ["ol", "á"])
        self.assertEqual(resposta.conteudo, "olá")

    def test_erros_do_sdk_viram_errocliente_sem_vazar_texto(self):
        casos = [
            ("RateLimitError", "limite_taxa"),
            ("APITimeoutError", "timeout"),
            ("AuthenticationError", "autenticacao"),
            ("APIConnectionError", "conexao"),
            ("APIError", "provedor"),
        ]
        for nome_excecao, codigo_esperado in casos:
            with self.subTest(nome_excecao):
                segredo = "sk-ant-chave-secreta-nunca-deve-aparecer"
                caixa = {}

                def chat_create(**kwargs):
                    excecao_cls = getattr(caixa["modulo"], nome_excecao)
                    raise excecao_cls(f"payload sigiloso {segredo}")

                cliente, modulo = self._cliente(chat_create=chat_create)
                caixa["modulo"] = modulo
                with self.assertRaises(cliente_mod.ErroCliente) as ctx:
                    cliente.chat([], [], "auto", 100, 10)
                self.assertEqual(ctx.exception.codigo, codigo_esperado)
                self.assertNotIn(segredo, str(ctx.exception))
                self.assertNotIn(segredo, ctx.exception.mensagem_curta)

    def test_embeddings_delega_para_cliente_embed(self):
        cliente_embed_fake = mock.Mock()
        cliente_embed_fake.embeddings.return_value = cliente_mod.RespostaEmbeddings(
            vetores=[[0.1]], tokens=3
        )
        cliente, _ = self._cliente(cliente_embed=cliente_embed_fake)
        resposta = cliente.embeddings(["texto"], 10)

        cliente_embed_fake.embeddings.assert_called_once_with(["texto"], 10)
        self.assertEqual(resposta, cliente_mod.RespostaEmbeddings(vetores=[[0.1]], tokens=3))


class TestConversaoParaAnthropic(SimpleTestCase):
    """Funções puras de módulo, sem SDK/rede."""

    def test_system_vira_parametro_top_level(self):
        sistema, mensagens = cliente_mod._mensagens_para_anthropic(
            [
                {"role": "system", "content": "texto A"},
                {"role": "user", "content": "oi"},
            ]
        )
        self.assertEqual(sistema, "texto A")
        self.assertEqual(mensagens, [{"role": "user", "content": "oi"}])

    def test_duas_mensagens_system_sao_concatenadas(self):
        sistema, _ = cliente_mod._mensagens_para_anthropic(
            [
                {"role": "system", "content": "texto A"},
                {"role": "system", "content": "texto B"},
            ]
        )
        self.assertEqual(sistema, "texto A\n\ntexto B")

    def test_tool_calls_do_assistant_e_tool_result_do_tool(self):
        _, mensagens = cliente_mod._mensagens_para_anthropic(
            [
                {
                    "role": "assistant",
                    "content": "deixa eu checar",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "consultar_processos",
                                "arguments": '{"exercicio": 2026}',
                            },
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call_1", "content": '{"total": 3}'},
            ]
        )
        self.assertEqual(
            mensagens[0],
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "deixa eu checar"},
                    {
                        "type": "tool_use",
                        "id": "call_1",
                        "name": "consultar_processos",
                        "input": {"exercicio": 2026},
                    },
                ],
            },
        )
        self.assertEqual(
            mensagens[1],
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "call_1", "content": '{"total": 3}'}
                ],
            },
        )

    def test_tool_calls_com_content_none_nao_gera_bloco_text(self):
        _, mensagens = cliente_mod._mensagens_para_anthropic(
            [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "f", "arguments": "{}"},
                        }
                    ],
                },
            ]
        )
        self.assertEqual(len(mensagens[0]["content"]), 1)
        self.assertEqual(mensagens[0]["content"][0]["type"], "tool_use")

    def test_duas_mensagens_tool_consecutivas_viram_uma_mensagem_user(self):
        _, mensagens = cliente_mod._mensagens_para_anthropic(
            [
                {"role": "tool", "tool_call_id": "call_1", "content": "a"},
                {"role": "tool", "tool_call_id": "call_2", "content": "b"},
            ]
        )
        self.assertEqual(len(mensagens), 1)
        self.assertEqual(
            mensagens[0]["content"],
            [
                {"type": "tool_result", "tool_use_id": "call_1", "content": "a"},
                {"type": "tool_result", "tool_use_id": "call_2", "content": "b"},
            ],
        )

    def test_mensagem_user_simples_passa_sem_empacotar(self):
        _, mensagens = cliente_mod._mensagens_para_anthropic(
            [{"role": "user", "content": "oi"}]
        )
        self.assertEqual(mensagens, [{"role": "user", "content": "oi"}])

    def test_ferramentas_para_anthropic(self):
        esquema = cliente_mod.esquema_estrito("f", "desc", {"x": {"type": "integer"}}, ["x"])
        convertido = cliente_mod._ferramentas_para_anthropic([esquema])
        self.assertEqual(
            convertido,
            [
                {
                    "name": "f",
                    "description": "desc",
                    "input_schema": {
                        "type": "object",
                        "properties": {"x": {"type": "integer"}},
                        "required": ["x"],
                        "additionalProperties": False,
                    },
                }
            ],
        )

    def test_assistant_com_tool_calls_reusa_blocos_originais(self):
        originais = [
            {"type": "thinking", "thinking": "", "signature": "assinatura"},
            {"type": "tool_use", "id": "t1", "name": "f", "input": {"x": 1}},
        ]
        _, convertidas = cliente_mod._mensagens_para_anthropic(
            [
                {"role": "user", "content": "oi"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {"id": "t1", "type": "function", "function": {"name": "f", "arguments": "{}"}}
                    ],
                },
                {"role": "tool", "tool_call_id": "t1", "content": "{}"},
            ],
            {"t1": originais},
        )
        self.assertEqual(convertidas[1], {"role": "assistant", "content": originais})
        self.assertEqual(convertidas[2]["content"][0]["tool_use_id"], "t1")

    def test_tool_choice_para_anthropic(self):
        self.assertEqual(
            cliente_mod._tool_choice_para_anthropic("auto"),
            {"type": "auto", "disable_parallel_tool_use": True},
        )
        self.assertEqual(cliente_mod._tool_choice_para_anthropic("none"), {"type": "none"})


class TestEsquemaEstrito(SimpleTestCase):
    def test_produz_additionalproperties_false_strict_e_required_completo(self):
        esquema = cliente_mod.esquema_estrito(
            "consultar_processos",
            "Consulta processos do PCA.",
            {
                "exercicio": {"type": ["integer", "null"]},
                "unidade": {"type": ["string", "null"]},
            },
            [],
        )
        funcao = esquema["function"]
        self.assertTrue(funcao["strict"])
        self.assertFalse(funcao["parameters"]["additionalProperties"])
        self.assertEqual(
            set(funcao["parameters"]["required"]), {"exercicio", "unidade"}
        )
