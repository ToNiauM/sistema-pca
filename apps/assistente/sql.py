"""(documento interno de desenho) — execução SQL somente leitura sobre o banco inteiro,
exceto senha e sessão. Módulo PURO: nenhum import de Django/`apps.*`/ORM —
`caminho_db` chega já resolvido pelo chamador (`apps/assistente/ferramentas.
py`) a partir de `settings.DATABASES["default"]["NAME"]`, para que
este módulo continue testável isoladamente com um arquivo temporário
(`apps/assistente/tests/test_sql.py`).

Defesa em profundidade (T-xaq-01/02/04): conexão própria aberta em
`mode=ro` (SQLite recusa qualquer escrita no nível do arquivo,
independente do authorizer) + `set_authorizer` com allowlist (nega
INSERT/UPDATE/DELETE/CREATE/DROP/ALTER/ATTACH/DETACH/TRANSACTION/PRAGMA/
`load_extension`, e nega leitura de tabela/coluna bloqueada) +
`set_progress_handler` com relógio monotônico (aborta após `timeout_s`).
`TABELAS_BLOQUEADAS`/`PREFIXOS_TABELAS_BLOQUEADAS`/`COLUNAS_BLOQUEADAS` são
a fonte ÚNICA da allowlist — `apps/assistente/esquema.py` as reimporta,
nunca duplica."""

from __future__ import annotations

import decimal
import json
import sqlite3
import time

# Nº de instruções da VM do SQLite entre duas chamadas ao progress handler
# (quanto menor, mais granular a checagem de tempo — e um pouco mais lento).
_PASSO_PROGRESSO = 1000


class ErroSQL(Exception):
    """`mensagem` é sempre um texto legível em português — nunca a
    exceção crua do SQLite sem contexto, mas sempre incluindo `str(exc)`
    original para o modelo poder corrigir a consulta."""

    def __init__(self, mensagem: str):
        self.mensagem = mensagem
        super().__init__(mensagem)


# Fonte única da allowlist de tabelas/colunas (reimportada por
# `apps.assistente.esquema` — nunca duplicar esta lista em outro arquivo).
TABELAS_BLOQUEADAS = frozenset({"django_session"})
PREFIXOS_TABELAS_BLOQUEADAS = ("axes_",)
COLUNAS_BLOQUEADAS = {
    "core_usuario": frozenset({"password"}),
    "core_historicalusuario": frozenset({"password"}),
}

_ACOES_PERMITIDAS = frozenset(
    {
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_FUNCTION,
        sqlite3.SQLITE_RECURSIVE,
    }
)


def _tabela_bloqueada(tabela: str | None) -> bool:
    if not tabela:
        return False
    if tabela in TABELAS_BLOQUEADAS:
        return True
    return any(tabela.startswith(prefixo) for prefixo in PREFIXOS_TABELAS_BLOQUEADAS)


def _autorizador(acao, arg1, arg2, nome_bd, contexto_disparador):
    if acao not in _ACOES_PERMITIDAS:
        return sqlite3.SQLITE_DENY
    if acao == sqlite3.SQLITE_FUNCTION:
        # A posição do nome da função varia por binding/versão — empiricamente
        # (ciclo RED→GREEN desta task) o SQLite entrega `arg2` (NULL em arg1).
        nome_funcao = (arg2 or arg1 or "").lower()
        if nome_funcao == "load_extension":
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    if acao == sqlite3.SQLITE_READ:
        tabela = arg1
        coluna = arg2
        if _tabela_bloqueada(tabela):
            return sqlite3.SQLITE_DENY
        if coluna and coluna in COLUNAS_BLOQUEADAS.get(tabela or "", frozenset()):
            return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def _serializar_valor(valor):
    if isinstance(valor, (decimal.Decimal, bytes)):
        return str(valor)
    return valor


def _tamanho_json(colunas: list[str], linhas: list[list]) -> int:
    return len(
        json.dumps({"colunas": colunas, "linhas": linhas}, ensure_ascii=False, default=str).encode(
            "utf-8"
        )
    )


def _erro_de_excecao(exc: Exception) -> ErroSQL:
    texto = str(exc)
    if texto == "interrupted":
        return ErroSQL("consulta excedeu o tempo limite")
    return ErroSQL(f"erro ao executar a consulta: {texto}")


def executar_select(
    sql: str,
    *,
    caminho_db,
    timeout_s: float = 3.0,
    max_linhas: int = 200,
    teto_bytes: int = 32 * 1024,
) -> dict:
    """Executa UM `SELECT` (ou CTE) somente leitura e devolve
    `{"colunas", "linhas", "total_linhas", "truncado"}`. Levanta `ErroSQL`
    (nunca a exceção crua do SQLite) para qualquer escrita, estrutura,
    tabela/coluna bloqueada, múltiplas instruções, tempo esgotado ou erro
    de sintaxe — sempre com mensagem legível em português."""
    if not sql or not sql.strip():
        raise ErroSQL("consulta vazia")

    conexao = sqlite3.connect(f"file:{caminho_db}?mode=ro", uri=True)
    try:
        conexao.set_authorizer(_autorizador)
        inicio = time.monotonic()

        def _verificar_prazo() -> int:
            return 1 if (time.monotonic() - inicio) > timeout_s else 0

        conexao.set_progress_handler(_verificar_prazo, _PASSO_PROGRESSO)

        try:
            cursor = conexao.execute(sql)
            colunas = [descricao[0] for descricao in (cursor.description or [])]
            brutas = cursor.fetchmany(max_linhas + 1)
        except (sqlite3.Warning, sqlite3.DatabaseError) as exc:
            raise _erro_de_excecao(exc) from None

        truncado = len(brutas) > max_linhas
        linhas = [
            [_serializar_valor(valor) for valor in linha] for linha in brutas[:max_linhas]
        ]

        while linhas and _tamanho_json(colunas, linhas) > teto_bytes:
            linhas.pop()
            truncado = True

        return {
            "colunas": colunas,
            "linhas": linhas,
            "total_linhas": len(linhas),
            "truncado": truncado,
        }
    finally:
        conexao.close()
