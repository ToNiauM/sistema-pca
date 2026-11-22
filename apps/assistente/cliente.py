"""Adaptadores de provedor de IA do Assistente do PCA (A18, A21;
`ClienteAnthropic` e a escolha por `IA_PROVEDOR` são).

`ClienteOpenAI` (chat + embeddings) e `ClienteAnthropic` (só chat —
embeddings continuam exclusivos da OpenAI, delegados a um `ClienteOpenAI`
injetado) expõem a MESMA interface pública (`chat`/`embeddings`, mesmos
tipos de retorno) — `agente.py`/`ferramentas.py`/`indice.py`/`views.py`
não sabem qual provedor está por trás. Import dos SDKs (`openai`/
`anthropic`) é preguiçoso (dentro de cada `__init__`), para que
`manage.py check`, a suíte e o robô sem `IA_API_KEY` nunca dependam deles
em import de módulo. `criar_cliente()` é o ÚNICO ponto que os testes
substituem (`unittest.mock.patch("apps.assistente.cliente.criar_cliente")`).

Erros do SDK NUNCA são expostos crus: `ErroCliente.mensagem_curta` é um
texto fixo por `codigo`, nunca `str(exc)` nem payload da requisição — a
mensagem/log não pode carregar a chave nem o corpo da conversa (A18)."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from django.conf import settings

logger = logging.getLogger("apps.assistente")

# Mensagens fixas por código; nunca o texto da exceção do SDK.
_MENSAGENS_ERRO = {
    "timeout": "O provedor de IA não respondeu a tempo.",
    "limite_taxa": "O provedor de IA está temporariamente sobrecarregado.",
    "autenticacao": "Falha de autenticação com o provedor de IA.",
    "conexao": "Não foi possível conectar ao provedor de IA.",
    "provedor": "O provedor de IA devolveu um erro inesperado.",
    "resposta_invalida": "O provedor de IA devolveu uma resposta inválida.",
}


class ErroCliente(Exception):
    """`codigo` é um dos definidos em `_MENSAGENS_ERRO`. `mensagem_curta` é
    sempre um texto fixo — nunca `str(exc)` do SDK."""

    def __init__(self, codigo: str):
        self.codigo = codigo
        self.mensagem_curta = _MENSAGENS_ERRO.get(codigo, _MENSAGENS_ERRO["provedor"])
        super().__init__(self.mensagem_curta)


@dataclass
class ChamadaFerramenta:
    id: str
    nome: str
    argumentos_json: str


@dataclass
class RespostaChat:
    conteudo: str | None
    chamadas: list[ChamadaFerramenta] = field(default_factory=list)
    tokens_entrada: int = 0
    tokens_saida: int = 0
    motivo_parada: str | None = None


@dataclass
class RespostaEmbeddings:
    vetores: list[list[float]]
    tokens: int = 0


def esquema_estrito(nome: str, descricao: str, propriedades: dict, obrigatorios: list[str]) -> dict:
    """Devolve o dict de ferramenta (`{"type": "function", "function": {...}}`)
    com `strict=True`, `additionalProperties=False` e `required` = TODAS as
    propriedades declaradas — campos opcionais aceitam tipo
    `["tipo", "null"]` já no dict de `propriedades` recebido."""
    return {
        "type": "function",
        "function": {
            "name": nome,
            "description": descricao,
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": propriedades,
                "required": list(propriedades.keys()),
                "additionalProperties": False,
            },
        },
    }


def _mensagens_para_anthropic(
    mensagens: list[dict], blocos_originais: dict[str, list[dict]] | None = None
) -> tuple[str, list[dict]]:
    """Converte o histórico no formato OpenAI que `agente.py` já monta para
    o formato Anthropic (`ClienteAnthropic.chat`):
    mensagens `role="system"` viram o parâmetro top-level `system`
    (concatenadas com uma linha em branco entre si, nunca aparecem na
    lista devolvida); `tool_calls` de um assistant viram blocos
    `tool_use`; mensagens `role="tool"` consecutivas viram UMA mensagem
    `user` com um bloco `tool_result` por chamada, na mesma ordem (a API
    Anthropic exige os resultados de uma rodada numa única mensagem
    user). `json.loads` de `arguments` corrompido vira
    `ErroCliente("resposta_invalida")` em vez de estourar (T-qxs-02) —
    histórico é gerado pelo próprio sistema, mas nunca deve quebrar o
    adaptador."""
    partes_sistema: list[str] = []
    saida: list[dict] = []
    pendentes_tool_result: list[dict] = []

    def _fechar_pendentes():
        nonlocal pendentes_tool_result
        if pendentes_tool_result:
            saida.append({"role": "user", "content": pendentes_tool_result})
            pendentes_tool_result = []

    for mensagem in mensagens:
        papel = mensagem["role"]
        if papel == "system":
            if mensagem.get("content"):
                partes_sistema.append(mensagem["content"])
            continue
        if papel == "tool":
            pendentes_tool_result.append(
                {
                    "type": "tool_result",
                    "tool_use_id": mensagem["tool_call_id"],
                    "content": mensagem["content"],
                }
            )
            continue
        _fechar_pendentes()
        if papel == "assistant" and mensagem.get("tool_calls"):
            # Blocos devolvidos pela API nesta mesma pergunta (com os de
            # `thinking` assinados) voltam INTACTOS — Opus 5.5/Sonnet 5
            # descartam ou recusam raciocínio de histórico reescrito.
            originais = (blocos_originais or {}).get(mensagem["tool_calls"][0]["id"])
            if originais is not None:
                saida.append({"role": "assistant", "content": originais})
                continue
            blocos = []
            if mensagem.get("content"):
                blocos.append({"type": "text", "text": mensagem["content"]})
            for chamada in mensagem["tool_calls"]:
                try:
                    argumentos = json.loads(chamada["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    raise ErroCliente("resposta_invalida") from None
                blocos.append(
                    {
                        "type": "tool_use",
                        "id": chamada["id"],
                        "name": chamada["function"]["name"],
                        "input": argumentos,
                    }
                )
            saida.append({"role": "assistant", "content": blocos})
        else:
            saida.append({"role": papel, "content": mensagem.get("content")})

    _fechar_pendentes()
    return "\n\n".join(partes_sistema), saida


def _ferramentas_para_anthropic(ferramentas: list[dict]) -> list[dict]:
    """Converte o formato de ferramenta OpenAI (`esquema_estrito`, `{"type":
    "function", "function": {...}}`) para o formato `tools` do SDK
    Anthropic. SEM `strict`: o modo estrito da Anthropic
    recusa `enum` junto de tipo em lista (`["string", "null"]`) e limita a
    16 os parâmetros com união de tipos — as ferramentas do Assistente têm
    22 (400 medido em 08/10/2026). Quem barra argumento fora do esquema
    continua sendo `ferramentas.executar` (allowlist de chaves + JSON
    inválido + exceção viram envelope de erro, nunca consulta)."""
    saida = []
    for item in ferramentas:
        funcao = item["function"]
        saida.append(
            {
                "name": funcao["name"],
                "description": funcao["description"],
                "input_schema": funcao["parameters"],
            }
        )
    return saida


def _tool_choice_para_anthropic(tool_choice: str) -> dict:
    """`"none"` -> `{"type": "none"}`; qualquer outro valor (sempre
    `"auto"` na prática, conforme `agente.py`) -> `{"type": "auto",
    "disable_parallel_tool_use": True}`."""
    if tool_choice == "none":
        return {"type": "none"}
    return {"type": "auto", "disable_parallel_tool_use": True}


class ClienteOpenAI:
    """Único adaptador do SDK `openai`. `max_retries=0` na construção
nenhum retry automático escondido consumindo o orçamento de
    tempo do agente."""

    def __init__(
        self, api_key: str, modelo_chat: str, modelo_embed: str, timeout_padrao_s: float,
        esforco_raciocinio: str = "",
    ):
        self.modelo_chat = modelo_chat
        self.esforco_raciocinio = esforco_raciocinio
        self.modelo_embed = modelo_embed
        self.timeout_padrao_s = timeout_padrao_s
        import openai  # noqa: PLC0415 — import preguiçoso (ver docstring do módulo)

        self._openai = openai
        self._cliente = openai.OpenAI(api_key=api_key, max_retries=0)

    def _limites(self, max_tokens: int) -> dict:
        """Parâmetros de tamanho/raciocínio aceitos pelos modelos atuais. `max_completion_tokens` (os
        modelos gpt-6 recusam o antigo `max_tokens`; o gpt-4.1 aceita os dois). `reasoning_effort` só vai
        quando configurado: o gpt-6-luna só aceita ferramentas nesta API com o raciocínio em "none", e
        os modelos sem raciocínio (gpt-4.1) recusam o parâmetro."""
        parametros = {"max_completion_tokens": max_tokens}
        if self.esforco_raciocinio:
            parametros["reasoning_effort"] = self.esforco_raciocinio
        return parametros

    def _tratar_erro(self, exc: Exception) -> ErroCliente:
        openai = self._openai
        if isinstance(exc, openai.APITimeoutError):
            codigo = "timeout"
        elif isinstance(exc, openai.RateLimitError):
            codigo = "limite_taxa"
        elif isinstance(exc, openai.AuthenticationError):
            codigo = "autenticacao"
        elif isinstance(exc, openai.APIConnectionError):
            codigo = "conexao"
        elif isinstance(exc, openai.APIError):
            codigo = "provedor"
        else:
            codigo = "resposta_invalida"
        logger.warning("cliente erro=%s modelo=%s", codigo, self.modelo_chat)
        return ErroCliente(codigo)

    def chat(
        self,
        mensagens: list[dict],
        ferramentas: list[dict],
        tool_choice: str,
        max_tokens: int,
        timeout_s: float,
        ao_receber_texto: Callable[[str], None] | None = None,
    ) -> RespostaChat:
        if ao_receber_texto is not None:
            return self._chat_com_stream(
                mensagens, ferramentas, tool_choice, max_tokens, timeout_s, ao_receber_texto
            )
        try:
            resposta = self._cliente.chat.completions.create(
                model=self.modelo_chat,
                messages=mensagens,
                tools=ferramentas,
                tool_choice=tool_choice,
                parallel_tool_calls=False,
                store=False,
                **self._limites(max_tokens),
                timeout=timeout_s,
            )
        except Exception as exc:  # noqa: BLE001 — convertido para ErroCliente abaixo
            raise self._tratar_erro(exc) from None

        try:
            escolha = resposta.choices[0]
            mensagem = escolha.message
            chamadas = [
                ChamadaFerramenta(
                    id=chamada.id,
                    nome=chamada.function.name,
                    argumentos_json=chamada.function.arguments,
                )
                for chamada in (mensagem.tool_calls or [])
            ]
            uso = resposta.usage
            return RespostaChat(
                conteudo=mensagem.content,
                chamadas=chamadas,
                tokens_entrada=getattr(uso, "prompt_tokens", 0) or 0,
                tokens_saida=getattr(uso, "completion_tokens", 0) or 0,
                motivo_parada=escolha.finish_reason,
            )
        except (AttributeError, IndexError, KeyError):
            logger.warning("cliente erro=%s modelo=%s", "resposta_invalida", self.modelo_chat)
            raise ErroCliente("resposta_invalida") from None

    def _chat_com_stream(
        self,
        mensagens: list[dict],
        ferramentas: list[dict],
        tool_choice: str,
        max_tokens: int,
        timeout_s: float,
        ao_receber_texto: Callable[[str], None],
    ) -> RespostaChat:
        """Mesmo contrato de `chat`, via `stream=True` — acumula
        `delta.content` (chamando `ao_receber_texto` a cada bloco) e
        `delta.tool_calls` (por índice, concatenando `arguments`), e
        devolve o MESMO `RespostaChat` de sempre. Erros do SDK, inclusive no
        meio do stream, viram `ErroCliente` como no caminho sem stream."""
        conteudo_acumulado = ""
        chamadas_por_indice: dict[int, dict] = {}
        motivo_parada = None
        tokens_entrada = 0
        tokens_saida = 0
        try:
            fluxo = self._cliente.chat.completions.create(
                model=self.modelo_chat,
                messages=mensagens,
                tools=ferramentas,
                tool_choice=tool_choice,
                parallel_tool_calls=False,
                store=False,
                **self._limites(max_tokens),
                timeout=timeout_s,
                stream=True,
                stream_options={"include_usage": True},
            )
            for pedaco in fluxo:
                if pedaco.usage is not None:
                    tokens_entrada = getattr(pedaco.usage, "prompt_tokens", 0) or 0
                    tokens_saida = getattr(pedaco.usage, "completion_tokens", 0) or 0
                if not pedaco.choices:
                    continue
                escolha = pedaco.choices[0]
                delta = escolha.delta
                if escolha.finish_reason:
                    motivo_parada = escolha.finish_reason
                if delta is None:
                    continue
                if delta.content:
                    conteudo_acumulado += delta.content
                    ao_receber_texto(delta.content)
                for chamada_delta in delta.tool_calls or []:
                    indice = chamada_delta.index
                    acumulada = chamadas_por_indice.setdefault(
                        indice, {"id": None, "nome": None, "argumentos": ""}
                    )
                    if chamada_delta.id:
                        acumulada["id"] = chamada_delta.id
                    if chamada_delta.function is not None:
                        if chamada_delta.function.name:
                            acumulada["nome"] = chamada_delta.function.name
                        if chamada_delta.function.arguments:
                            acumulada["argumentos"] += chamada_delta.function.arguments
        except Exception as exc:  # noqa: BLE001 — convertido para ErroCliente abaixo
            raise self._tratar_erro(exc) from None

        chamadas = [
            ChamadaFerramenta(
                id=dados["id"],
                nome=dados["nome"],
                argumentos_json=dados["argumentos"],
            )
            for _, dados in sorted(chamadas_por_indice.items())
        ]
        return RespostaChat(
            conteudo=conteudo_acumulado or None,
            chamadas=chamadas,
            tokens_entrada=tokens_entrada,
            tokens_saida=tokens_saida,
            motivo_parada=motivo_parada,
        )

    def embeddings(self, textos: list[str], timeout_s: float) -> RespostaEmbeddings:
        try:
            resposta = self._cliente.embeddings.create(
                model=self.modelo_embed,
                input=textos,
                timeout=timeout_s,
            )
        except Exception as exc:  # noqa: BLE001
            raise self._tratar_erro(exc) from None

        try:
            vetores = [item.embedding for item in resposta.data]
            tokens = getattr(resposta.usage, "prompt_tokens", 0) or 0
            return RespostaEmbeddings(vetores=vetores, tokens=tokens)
        except (AttributeError, KeyError):
            logger.warning("cliente erro=%s modelo=%s", "resposta_invalida", self.modelo_embed)
            raise ErroCliente("resposta_invalida") from None


def _resposta_de_mensagem_anthropic(mensagem) -> RespostaChat:
    """Monta `RespostaChat` a partir de uma mensagem final do SDK Anthropic
    (`client.messages.create`/`fluxo.get_final_message()`, quick) — mesma forma usada pelo caminho com e sem stream."""
    conteudo: str | None = None
    chamadas: list[ChamadaFerramenta] = []
    for bloco in mensagem.content:
        if bloco.type == "text":
            conteudo = (conteudo or "") + bloco.text
        elif bloco.type == "tool_use":
            chamadas.append(
                ChamadaFerramenta(
                    id=bloco.id,
                    nome=bloco.name,
                    argumentos_json=json.dumps(bloco.input, ensure_ascii=False),
                )
            )
    return RespostaChat(
        conteudo=conteudo,
        chamadas=chamadas,
        tokens_entrada=getattr(mensagem.usage, "input_tokens", 0) or 0,
        tokens_saida=getattr(mensagem.usage, "output_tokens", 0) or 0,
        motivo_parada=mensagem.stop_reason,
    )


class ClienteAnthropic:
    """Segundo adaptador do Assistente do PCA — mesma
    interface pública de `ClienteOpenAI` (`chat`/`embeddings`, mesmos tipos
    de retorno), sobre o SDK oficial `anthropic`. `cliente_embed` é sempre
    um `ClienteOpenAI` injetado pelo construtor (a Anthropic não tem API de
    embeddings). `esforco_raciocinio` (`IA_ESFORCO_RACIOCINIO`) vazio ou
    "none" desliga o raciocínio (`thinking: disabled`) — com ele ligado, o
    Sonnet 5 gasta o `IA_MAX_TOKENS_RESPOSTA` inteiro pensando e devolve
    resposta vazia (medido em 08/10/2026); qualquer outro valor vira
    `output_config.effort` (low..max, raciocínio adaptativo). Import do SDK é
    preguiçoso (dentro de `__init__`), mesmo padrão de `ClienteOpenAI`."""

    def __init__(
        self, api_key: str, modelo_chat: str, timeout_padrao_s: float, cliente_embed,
        esforco_raciocinio: str = "",
    ):
        self.modelo_chat = modelo_chat
        self.esforco_raciocinio = esforco_raciocinio
        self.timeout_padrao_s = timeout_padrao_s
        self._cliente_embed = cliente_embed
        # id do 1º tool_use -> blocos crus da resposta (inclui `thinking`),
        # reaproveitados por `_mensagens_para_anthropic` na rodada seguinte.
        # O cliente vive uma pergunta só (`criar_cliente()` por pedido).
        self._blocos_originais: dict[str, list[dict]] = {}
        import anthropic  # noqa: PLC0415 — import preguiçoso (ver docstring da classe)

        self._anthropic = anthropic
        self._cliente = anthropic.Anthropic(api_key=api_key, max_retries=0)

    def _raciocinio(self) -> dict:
        if self.esforco_raciocinio in ("", "none"):
            return {"thinking": {"type": "disabled"}}
        return {"output_config": {"effort": self.esforco_raciocinio}}

    def _tratar_erro(self, exc: Exception) -> ErroCliente:
        anthropic = self._anthropic
        if isinstance(exc, anthropic.APITimeoutError):
            codigo = "timeout"
        elif isinstance(exc, anthropic.RateLimitError):
            codigo = "limite_taxa"
        elif isinstance(exc, anthropic.AuthenticationError):
            codigo = "autenticacao"
        elif isinstance(exc, anthropic.APIConnectionError):
            codigo = "conexao"
        elif isinstance(exc, anthropic.APIError):
            codigo = "provedor"
        else:
            codigo = "resposta_invalida"
        logger.warning("cliente erro=%s modelo=%s", codigo, self.modelo_chat)
        return ErroCliente(codigo)

    def chat(
        self,
        mensagens: list[dict],
        ferramentas: list[dict],
        tool_choice: str,
        max_tokens: int,
        timeout_s: float,
        ao_receber_texto: Callable[[str], None] | None = None,
    ) -> RespostaChat:
        sistema, mensagens_conv = _mensagens_para_anthropic(mensagens, self._blocos_originais)
        ferramentas_conv = _ferramentas_para_anthropic(ferramentas)
        tool_choice_conv = _tool_choice_para_anthropic(tool_choice)
        if ao_receber_texto is not None:
            return self._chat_com_stream(
                sistema, mensagens_conv, ferramentas_conv, tool_choice_conv,
                max_tokens, timeout_s, ao_receber_texto,
            )
        try:
            resposta = self._cliente.messages.create(
                model=self.modelo_chat,
                max_tokens=max_tokens,
                system=sistema,
                messages=mensagens_conv,
                tools=ferramentas_conv,
                tool_choice=tool_choice_conv,
                **self._raciocinio(),
                timeout=timeout_s,
            )
        except Exception as exc:  # noqa: BLE001 — convertido para ErroCliente abaixo
            raise self._tratar_erro(exc) from None
        return self._registrar(resposta)

    def _chat_com_stream(
        self,
        sistema: str,
        mensagens_conv: list[dict],
        ferramentas_conv: list[dict],
        tool_choice_conv: dict,
        max_tokens: int,
        timeout_s: float,
        ao_receber_texto: Callable[[str], None],
    ) -> RespostaChat:
        """Mesmo contrato de `chat`, via `client.messages.stream` (quick) — entrega `fluxo.text_stream` incrementalmente a
        `ao_receber_texto` e devolve o `RespostaChat` final a partir de
        `fluxo.get_final_message()` (os blocos `tool_use` já vêm
        completos)."""
        try:
            with self._cliente.messages.stream(
                model=self.modelo_chat,
                max_tokens=max_tokens,
                system=sistema,
                messages=mensagens_conv,
                tools=ferramentas_conv,
                tool_choice=tool_choice_conv,
                **self._raciocinio(),
                timeout=timeout_s,
            ) as fluxo:
                for texto in fluxo.text_stream:
                    ao_receber_texto(texto)
                mensagem = fluxo.get_final_message()
        except Exception as exc:  # noqa: BLE001 — convertido para ErroCliente abaixo
            raise self._tratar_erro(exc) from None
        return self._registrar(mensagem)

    def _registrar(self, mensagem) -> RespostaChat:
        resposta = _resposta_de_mensagem_anthropic(mensagem)
        if resposta.chamadas and all(hasattr(b, "model_dump") for b in mensagem.content):
            self._blocos_originais[resposta.chamadas[0].id] = [
                bloco.model_dump(mode="json", exclude_none=True) for bloco in mensagem.content
            ]
        return resposta

    def embeddings(self, textos: list[str], timeout_s: float) -> RespostaEmbeddings:
        return self._cliente_embed.embeddings(textos, timeout_s)


def criar_cliente() -> ClienteOpenAI | ClienteAnthropic | None:
    """Lê `settings.IA_*` e devolve `ClienteOpenAI`/`ClienteAnthropic`
    conforme `IA_PROVEDOR`, ou `None` quando `IA_API_KEY` está vazia.
    ÚNICO ponto substituído pelos testes. com
    `IA_PROVEDOR == "anthropic"`, embeddings continuam delegados a um
    `ClienteOpenAI` interno (`IA_API_KEY_EMBED` ou, vazio, reaproveita
    `IA_API_KEY`) — a Anthropic não tem API de embeddings."""
    if not settings.IA_API_KEY:
        return None
    if settings.IA_PROVEDOR == "anthropic":
        chave_embed = settings.IA_API_KEY_EMBED or settings.IA_API_KEY
        cliente_embed = ClienteOpenAI(
            api_key=chave_embed,
            modelo_chat=settings.IA_MODELO_ASSISTENTE,
            modelo_embed=settings.IA_MODELO_EMBED,
            timeout_padrao_s=settings.IA_TIMEOUT_S,
        )
        return ClienteAnthropic(
            api_key=settings.IA_API_KEY,
            modelo_chat=settings.IA_MODELO_ASSISTENTE,
            timeout_padrao_s=settings.IA_TIMEOUT_S,
            cliente_embed=cliente_embed,
            esforco_raciocinio=settings.IA_ESFORCO_RACIOCINIO,
        )
    return ClienteOpenAI(
        api_key=settings.IA_API_KEY,
        modelo_chat=settings.IA_MODELO_ASSISTENTE,
        modelo_embed=settings.IA_MODELO_EMBED,
        timeout_padrao_s=settings.IA_TIMEOUT_S,
        esforco_raciocinio=settings.IA_ESFORCO_RACIOCINIO,
    )
