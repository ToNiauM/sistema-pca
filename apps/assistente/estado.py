"""Conversa temporária e quota atômica do Assistente do PCA (A01, A02, A20) — dois arquivos SQLite auxiliares via
`sqlite3` da stdlib, TOTALMENTE fora do ORM/banco principal.

`estado.sqlite3`: `quota`/`requisicao` (idempotência, lease, contagem
diária). `conversas.sqlite3`: `conversa`/`troca` (texto da conversa, até 10
pares, apagados no logout/"Nova conversa"/expiração). NENHUM prompt de
sistema, payload de ferramenta, token de autenticação ou e-mail é gravado
em nenhum dos dois. `isolation_level=None` (autocommit) — toda transação
multi-statement é explícita com `BEGIN IMMEDIATE`/`COMMIT`/`ROLLBACK`, para
que a chamada de rede aconteça SEMPRE entre transações, nunca dentro de
uma."""

from __future__ import annotations

import json
import logging
import secrets
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from datetime import time as _hora_min
from pathlib import Path

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger("apps.assistente")

CHAVE_SESSAO_CONVERSA = "assistente_conversa_id"

SCHEMA_VERSAO = 2
_LEASE_S = 120
_MAX_TROCAS = 10
_ANDAMENTO_ORFAO_HORAS = 1


class EstadoIndisponivel(Exception):
    """Arquivo auxiliar inacessível/corrompido — erro operacional seguro.
    NUNCA leva a reset silencioso de quota nem recriação do arquivo (A20)."""


# --- Conexão e schema -------------------------------------------------

_SCHEMA_ESTADO = """
CREATE TABLE IF NOT EXISTS meta (chave TEXT PRIMARY KEY, valor TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS quota (
    usuario_id INTEGER NOT NULL,
    dia TEXT NOT NULL,
    perguntas INTEGER NOT NULL DEFAULT 0,
    tokens_entrada INTEGER NOT NULL DEFAULT 0,
    tokens_saida INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(usuario_id, dia)
);
CREATE TABLE IF NOT EXISTS requisicao (
    id TEXT PRIMARY KEY,
    usuario_id INTEGER NOT NULL,
    dia TEXT NOT NULL,
    estado TEXT NOT NULL CHECK(estado IN ('emitida','em_andamento','concluida','falha')),
    sessao_hash TEXT NOT NULL,
    conversa_id TEXT NOT NULL,
    exercicio INTEGER NOT NULL,
    emitida_em TEXT NOT NULL,
    iniciada_em TEXT,
    concluida_em TEXT,
    lease_ate TEXT,
    erro_codigo TEXT
);
CREATE INDEX IF NOT EXISTS idx_requisicao_usuario_estado ON requisicao(usuario_id, estado);
CREATE TABLE IF NOT EXISTS andamento (
    requisicao_id TEXT PRIMARY KEY REFERENCES requisicao(id) ON DELETE CASCADE,
    pergunta TEXT NOT NULL DEFAULT '',
    etapa TEXT NOT NULL DEFAULT '',
    texto_parcial TEXT NOT NULL DEFAULT '',
    atualizado_em TEXT NOT NULL
);
"""

_SCHEMA_CONVERSAS = """
CREATE TABLE IF NOT EXISTS meta (chave TEXT PRIMARY KEY, valor TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS conversa (
    id TEXT PRIMARY KEY,
    usuario_id INTEGER NOT NULL,
    sessao_hash TEXT NOT NULL,
    permissoes_hash TEXT NOT NULL,
    exercicio INTEGER NOT NULL,
    criada_em TEXT NOT NULL,
    expira_em TEXT NOT NULL,
    apagada INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS troca (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversa_id TEXT NOT NULL REFERENCES conversa(id) ON DELETE CASCADE,
    ordem INTEGER NOT NULL,
    pergunta TEXT NOT NULL,
    resposta_md TEXT NOT NULL,
    referencias_json TEXT NOT NULL,
    proveniencia_json TEXT NOT NULL,
    rodape TEXT NOT NULL,
    criada_em TEXT NOT NULL,
    UNIQUE(conversa_id, ordem)
);
"""


def _conectar(caminho_str: str) -> sqlite3.Connection:
    # Fase 39 — padrão de conexão extraído para `apps.assistente.
    # _sqlite.conectar`, compartilhado com `indice.py`; comportamento
    # idêntico ao de antes (regressão zero).
    from apps.assistente import _sqlite

    try:
        return _sqlite.conectar(caminho_str)
    except sqlite3.DatabaseError:
        raise EstadoIndisponivel("arquivo auxiliar corrompido") from None


def _garantir_schema(con: sqlite3.Connection, schema_sql: str) -> None:
    try:
        con.executescript(schema_sql)
        linha = con.execute(
            "SELECT valor FROM meta WHERE chave='schema_versao'"
        ).fetchone()
        if linha is None:
            con.execute(
                "INSERT INTO meta(chave, valor) VALUES ('schema_versao', ?)",
                (str(SCHEMA_VERSAO),),
            )
        elif int(linha[0]) > SCHEMA_VERSAO:
            raise EstadoIndisponivel("schema mais novo que o suportado por esta versão")
    except sqlite3.DatabaseError:
        raise EstadoIndisponivel("arquivo auxiliar corrompido") from None


def _conectar_estado() -> sqlite3.Connection:
    con = _conectar(settings.IA_ESTADO_PATH)
    _garantir_schema(con, _SCHEMA_ESTADO)
    return con


def _conectar_conversas() -> sqlite3.Connection:
    con = _conectar(settings.IA_CONVERSAS_PATH)
    _garantir_schema(con, _SCHEMA_CONVERSAS)
    return con


# --- Identidade ---------------------------------------------------------

def hash_sessao(session_key: str) -> str:
    import hashlib

    return hashlib.sha256((session_key or "").encode("utf-8")).hexdigest()


def hash_permissoes(usuario) -> str:
    import hashlib

    permissoes = "|".join(sorted(usuario.get_all_permissions()))
    texto = f"{permissoes}|super={usuario.is_superuser}|ativo={usuario.is_active}"
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def dia_civil(agora) -> str:
    """Dia civil em `TIME_ZONE` (América/São Paulo) para o instante `agora`
    — nunca `date.today()`/`datetime.now()` cru (mesma disciplina de
    `apps.pca.querysets`)."""
    return timezone.localdate(agora).isoformat()


def segundos_ate_meia_noite(agora) -> int:
    hoje_local = timezone.localdate(agora)
    amanha_local = hoje_local + timedelta(days=1)
    meia_noite = timezone.make_aware(
        datetime.combine(amanha_local, _hora_min.min),
        timezone.get_current_timezone(),
    )
    delta = meia_noite - agora
    return max(1, int(delta.total_seconds()))


# --- Dataclasses ----------------------------------------------------------

@dataclass
class Troca:
    ordem: int
    pergunta: str
    resposta_md: str
    referencias: list
    proveniencia: dict
    rodape: str
    criada_em: str


@dataclass
class Conversa:
    id: str
    exercicio: int
    expira_em: str
    trocas: list = field(default_factory=list)


@dataclass
class Reserva:
    requisicao_id: str
    perguntas_hoje: int


@dataclass
class Recusa:
    motivo: str


@dataclass
class Consumo:
    perguntas: int
    tokens_entrada: int
    tokens_saida: int


@dataclass
class Andamento:
    """Progresso de uma requisição em curso — nunca grava
    prompt de sistema nem payload de ferramenta, só o rótulo da etapa e o
    texto parcial já produzido pelo modelo."""

    pergunta: str
    etapa: str
    texto_parcial: str
    atualizado_em: str


@dataclass
class Requisicao:
    """Leitura de `requisicao` com verificação de dono — usada
    pela rota de polling, que nunca expõe uma requisição de outro usuário
    ou de outra sessão."""

    id: str
    estado: str
    lease_ate: str | None
    erro_codigo: str | None
    conversa_id: str
    exercicio: int
    dia: str


# --- Conversas --------------------------------------------------------

def criar_conversa(usuario_id, sessao_hash, permissoes_hash, exercicio, agora) -> str:
    conversa_id = secrets.token_urlsafe(24)
    expira_em = agora + timedelta(seconds=settings.IA_CONVERSA_TTL_S)
    con = _conectar_conversas()
    try:
        con.execute(
            "INSERT INTO conversa"
            "(id, usuario_id, sessao_hash, permissoes_hash, exercicio, criada_em, expira_em, apagada)"
            " VALUES (?,?,?,?,?,?,?,0)",
            (
                conversa_id,
                usuario_id,
                sessao_hash,
                permissoes_hash,
                exercicio,
                agora.isoformat(),
                expira_em.isoformat(),
            ),
        )
    except sqlite3.DatabaseError:
        raise EstadoIndisponivel("não foi possível criar a conversa") from None
    finally:
        con.close()
    return conversa_id


def carregar_conversa(conversa_id, *, usuario_id, sessao_hash, permissoes_hash, agora) -> Conversa | None:
    if not conversa_id:
        return None
    con = _conectar_conversas()
    try:
        linha = con.execute(
            "SELECT usuario_id, sessao_hash, permissoes_hash, exercicio, expira_em, apagada "
            "FROM conversa WHERE id=?",
            (conversa_id,),
        ).fetchone()
        if linha is None:
            return None
        db_usuario_id, db_sessao_hash, db_permissoes_hash, exercicio, expira_em, apagada = linha
        agora_iso = agora.isoformat()
        if apagada or expira_em <= agora_iso:
            return None
        if db_usuario_id != usuario_id or db_sessao_hash != sessao_hash:
            return None
        if db_permissoes_hash != permissoes_hash:
            # Revogação/mudança de permissões invalida a conversa inteira
            # ANTES de exibir/reenviar histórico.
            con.execute("UPDATE conversa SET apagada=1 WHERE id=?", (conversa_id,))
            con.execute("DELETE FROM troca WHERE conversa_id=?", (conversa_id,))
            return None
        linhas_troca = con.execute(
            "SELECT ordem, pergunta, resposta_md, referencias_json, proveniencia_json, rodape, criada_em "
            "FROM troca WHERE conversa_id=? ORDER BY ordem",
            (conversa_id,),
        ).fetchall()
        trocas = [
            Troca(
                ordem=ordem,
                pergunta=pergunta,
                resposta_md=resposta_md,
                referencias=json.loads(referencias_json),
                proveniencia=json.loads(proveniencia_json),
                rodape=rodape,
                criada_em=criada_em,
            )
            for (ordem, pergunta, resposta_md, referencias_json, proveniencia_json, rodape, criada_em)
            in linhas_troca
        ]
        return Conversa(id=conversa_id, exercicio=exercicio, expira_em=expira_em, trocas=trocas)
    except sqlite3.DatabaseError:
        raise EstadoIndisponivel("arquivo de conversas corrompido") from None
    finally:
        con.close()


def acrescentar_troca(
    conversa_id,
    *,
    usuario_id,
    sessao_hash,
    permissoes_hash,
    agora,
    pergunta,
    resposta_md,
    referencias,
    proveniencia,
    rodape,
) -> bool:
    """Revalida (dentro de UMA transação `BEGIN IMMEDIATE`) as mesmas
    condições de `carregar_conversa` antes de gravar — a revalidação
    pós-rede que impede uma resposta tardia (após logout/revogação) de
    recriar conteúdo apagado."""
    con = _conectar_conversas()
    try:
        con.execute("BEGIN IMMEDIATE")
        linha = con.execute(
            "SELECT usuario_id, sessao_hash, permissoes_hash, expira_em, apagada "
            "FROM conversa WHERE id=?",
            (conversa_id,),
        ).fetchone()
        agora_iso = agora.isoformat()
        valido = (
            linha is not None
            and not linha[4]
            and linha[3] > agora_iso
            and linha[0] == usuario_id
            and linha[1] == sessao_hash
            and linha[2] == permissoes_hash
        )
        if not valido:
            con.execute("ROLLBACK")
            return False
        maior = con.execute(
            "SELECT COALESCE(MAX(ordem), 0) FROM troca WHERE conversa_id=?", (conversa_id,)
        ).fetchone()[0]
        nova_ordem = maior + 1
        con.execute(
            "INSERT INTO troca"
            "(conversa_id, ordem, pergunta, resposta_md, referencias_json, proveniencia_json, rodape, criada_em)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (
                conversa_id,
                nova_ordem,
                pergunta,
                resposta_md,
                json.dumps(referencias, ensure_ascii=False),
                json.dumps(proveniencia, ensure_ascii=False),
                rodape,
                agora_iso,
            ),
        )
        con.execute(
            "DELETE FROM troca WHERE conversa_id=? AND ordem <= "
            "(SELECT MAX(ordem) FROM troca WHERE conversa_id=?) - ?",
            (conversa_id, conversa_id, _MAX_TROCAS),
        )
        con.execute("COMMIT")
        return True
    except sqlite3.DatabaseError:
        con.execute("ROLLBACK")
        raise EstadoIndisponivel("não foi possível gravar a troca") from None
    finally:
        con.close()


def apagar_conversa(conversa_id) -> None:
    con = _conectar_conversas()
    try:
        con.execute("UPDATE conversa SET apagada=1 WHERE id=?", (conversa_id,))
        con.execute("DELETE FROM troca WHERE conversa_id=?", (conversa_id,))
    except sqlite3.DatabaseError:
        raise EstadoIndisponivel("não foi possível apagar a conversa") from None
    finally:
        con.close()


def apagar_conversas_da_sessao(usuario_id, sessao_hash) -> None:
    con = _conectar_conversas()
    try:
        ids = [
            linha[0]
            for linha in con.execute(
                "SELECT id FROM conversa WHERE usuario_id=? AND sessao_hash=? AND apagada=0",
                (usuario_id, sessao_hash),
            ).fetchall()
        ]
        con.execute(
            "UPDATE conversa SET apagada=1 WHERE usuario_id=? AND sessao_hash=?",
            (usuario_id, sessao_hash),
        )
        for conversa_id in ids:
            con.execute("DELETE FROM troca WHERE conversa_id=?", (conversa_id,))
    except sqlite3.DatabaseError:
        raise EstadoIndisponivel("não foi possível apagar as conversas da sessão") from None
    finally:
        con.close()


def limpar_expiradas(agora) -> int:
    con = _conectar_conversas()
    try:
        cursor = con.execute(
            "DELETE FROM conversa WHERE apagada=1 OR expira_em <= ?", (agora.isoformat(),)
        )
        return cursor.rowcount
    except sqlite3.DatabaseError:
        raise EstadoIndisponivel("não foi possível limpar conversas expiradas") from None
    finally:
        con.close()


# --- Quota e requisição (A02) --------------------------------

def emitir_requisicao(*, usuario_id, sessao_hash, conversa_id, exercicio, agora) -> str:
    requisicao_id = secrets.token_urlsafe(32)
    dia = dia_civil(agora)
    con = _conectar_estado()
    try:
        con.execute(
            "INSERT INTO requisicao"
            "(id, usuario_id, dia, estado, sessao_hash, conversa_id, exercicio, emitida_em)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (requisicao_id, usuario_id, dia, "emitida", sessao_hash, conversa_id, exercicio, agora.isoformat()),
        )
    except sqlite3.DatabaseError:
        raise EstadoIndisponivel("não foi possível emitir a requisição") from None
    finally:
        con.close()
    return requisicao_id


def reservar(*, requisicao_id, usuario_id, sessao_hash, conversa_id, exercicio, agora, limite):
    dia = dia_civil(agora)
    agora_iso = agora.isoformat()
    con = _conectar_estado()
    try:
        con.execute("BEGIN IMMEDIATE")
        linha = con.execute(
            "SELECT usuario_id, sessao_hash, conversa_id, exercicio, estado, lease_ate "
            "FROM requisicao WHERE id=?",
            (requisicao_id,),
        ).fetchone()
        if linha is None:
            con.execute("ROLLBACK")
            return Recusa("invalida")
        db_usuario_id, db_sessao_hash, db_conversa_id, db_exercicio, estado_atual, lease_ate = linha
        if (
            db_usuario_id != usuario_id
            or db_sessao_hash != sessao_hash
            or db_conversa_id != conversa_id
            or db_exercicio != exercicio
        ):
            con.execute("ROLLBACK")
            return Recusa("invalida")

        if estado_atual == "concluida":
            con.execute("ROLLBACK")
            return Recusa("concluida")
        if estado_atual == "falha":
            con.execute("ROLLBACK")
            return Recusa("falha")
        if estado_atual == "em_andamento":
            if lease_ate and lease_ate > agora_iso:
                con.execute("ROLLBACK")
                return Recusa("em_andamento")
            # Lease vencido sem conclusão: trata como falha — nova
            # tentativa exige um novo ID.
            con.execute(
                "UPDATE requisicao SET estado='falha', erro_codigo='lease_expirado' WHERE id=?",
                (requisicao_id,),
            )
            con.execute("COMMIT")
            return Recusa("falha")

        # estado_atual == "emitida" a partir daqui.
        outra_em_andamento = con.execute(
            "SELECT id FROM requisicao WHERE usuario_id=? AND estado='em_andamento' "
            "AND lease_ate > ? AND id != ?",
            (usuario_id, agora_iso, requisicao_id),
        ).fetchone()
        if outra_em_andamento is not None:
            con.execute("ROLLBACK")
            return Recusa("concorrencia")

        linha_quota = con.execute(
            "SELECT perguntas FROM quota WHERE usuario_id=? AND dia=?", (usuario_id, dia)
        ).fetchone()
        perguntas_atuais = linha_quota[0] if linha_quota else 0
        if perguntas_atuais >= limite:
            con.execute("ROLLBACK")
            return Recusa("quota")

        lease_ate_novo = (agora + timedelta(seconds=_LEASE_S)).isoformat()
        con.execute(
            "INSERT INTO quota(usuario_id, dia, perguntas) VALUES (?,?,1) "
            "ON CONFLICT(usuario_id, dia) DO UPDATE SET perguntas = perguntas + 1",
            (usuario_id, dia),
        )
        con.execute(
            "UPDATE requisicao SET estado='em_andamento', iniciada_em=?, lease_ate=? WHERE id=?",
            (agora_iso, lease_ate_novo, requisicao_id),
        )
        con.execute("COMMIT")
        return Reserva(requisicao_id=requisicao_id, perguntas_hoje=perguntas_atuais + 1)
    except sqlite3.DatabaseError:
        con.execute("ROLLBACK")
        raise EstadoIndisponivel("não foi possível reservar a pergunta") from None
    finally:
        con.close()


def concluir(*, requisicao_id, agora, tokens_entrada=0, tokens_saida=0, erro_codigo=None) -> None:
    con = _conectar_estado()
    try:
        con.execute("BEGIN IMMEDIATE")
        linha = con.execute(
            "SELECT usuario_id, dia FROM requisicao WHERE id=?", (requisicao_id,)
        ).fetchone()
        if linha is None:
            con.execute("ROLLBACK")
            return
        usuario_id, dia = linha
        novo_estado = "falha" if erro_codigo else "concluida"
        con.execute(
            "UPDATE requisicao SET estado=?, concluida_em=?, erro_codigo=? WHERE id=?",
            (novo_estado, agora.isoformat(), erro_codigo, requisicao_id),
        )
        con.execute(
            "UPDATE quota SET tokens_entrada = tokens_entrada + ?, tokens_saida = tokens_saida + ? "
            "WHERE usuario_id=? AND dia=?",
            (tokens_entrada, tokens_saida, usuario_id, dia),
        )
        # A bolha de andamento deixa de existir assim que a troca
        # final (ou o erro) está gravada; a rota de polling passa a ler a
        # requisição concluída, não mais o `andamento`.
        con.execute("DELETE FROM andamento WHERE requisicao_id=?", (requisicao_id,))
        con.execute("COMMIT")
    except sqlite3.DatabaseError:
        con.execute("ROLLBACK")
        raise EstadoIndisponivel("não foi possível concluir a requisição") from None
    finally:
        con.close()


def requisicao_ler(requisicao_id, *, usuario_id, sessao_hash) -> Requisicao | None:
    """Leitura de `requisicao` com verificação de dono — devolve
    `None` quando o id não existe OU pertence a outro usuário/sessão (a
    view converte em 404, nunca vaza a existência do id)."""
    con = _conectar_estado()
    try:
        linha = con.execute(
            "SELECT usuario_id, sessao_hash, estado, lease_ate, erro_codigo, conversa_id, exercicio, dia "
            "FROM requisicao WHERE id=?",
            (requisicao_id,),
        ).fetchone()
        if linha is None:
            return None
        db_usuario_id, db_sessao_hash, estado_atual, lease_ate, erro_codigo, conversa_id, exercicio, dia = linha
        if db_usuario_id != usuario_id or db_sessao_hash != sessao_hash:
            return None
        return Requisicao(
            id=requisicao_id,
            estado=estado_atual,
            lease_ate=lease_ate,
            erro_codigo=erro_codigo,
            conversa_id=conversa_id,
            exercicio=exercicio,
            dia=dia,
        )
    except sqlite3.DatabaseError:
        raise EstadoIndisponivel("não foi possível ler a requisição") from None
    finally:
        con.close()


def requisicao_em_andamento(usuario_id, sessao_hash, conversa_id) -> str | None:
    """Id da requisição `em_andamento` mais recente do usuário nesta
    conversa/sessão — usada por `_contexto_pagina` para mostrar
    a bolha de progresso desde o primeiro GET, mesmo se a página foi
    recarregada enquanto a thread ainda respondia."""
    con = _conectar_estado()
    try:
        linha = con.execute(
            "SELECT id FROM requisicao WHERE usuario_id=? AND sessao_hash=? AND conversa_id=? "
            "AND estado='em_andamento' ORDER BY iniciada_em DESC LIMIT 1",
            (usuario_id, sessao_hash, conversa_id),
        ).fetchone()
        return linha[0] if linha else None
    except sqlite3.DatabaseError:
        raise EstadoIndisponivel("não foi possível consultar requisições em andamento") from None
    finally:
        con.close()


def andamento_gravar(requisicao_id, *, agora, etapa=None, texto_parcial=None, pergunta=None) -> None:
    """UPSERT do progresso de UMA requisição — transação curta (só a
    gravação), nunca segura durante a chamada de rede. Campos
    não informados preservam o valor já gravado; a primeira chamada de
    cada requisição normalmente informa `pergunta` (a view) e as
    seguintes só `etapa`/`texto_parcial` (a thread)."""
    con = _conectar_estado()
    try:
        con.execute("BEGIN IMMEDIATE")
        linha = con.execute(
            "SELECT pergunta, etapa, texto_parcial FROM andamento WHERE requisicao_id=?",
            (requisicao_id,),
        ).fetchone()
        agora_iso = agora.isoformat()
        if linha is None:
            con.execute(
                "INSERT INTO andamento(requisicao_id, pergunta, etapa, texto_parcial, atualizado_em) "
                "VALUES (?,?,?,?,?)",
                (requisicao_id, pergunta or "", etapa or "", texto_parcial or "", agora_iso),
            )
        else:
            pergunta_atual, etapa_atual, texto_atual = linha
            con.execute(
                "UPDATE andamento SET pergunta=?, etapa=?, texto_parcial=?, atualizado_em=? "
                "WHERE requisicao_id=?",
                (
                    pergunta if pergunta is not None else pergunta_atual,
                    etapa if etapa is not None else etapa_atual,
                    texto_parcial if texto_parcial is not None else texto_atual,
                    agora_iso,
                    requisicao_id,
                ),
            )
        con.execute("COMMIT")
    except sqlite3.DatabaseError:
        con.execute("ROLLBACK")
        raise EstadoIndisponivel("não foi possível gravar o andamento") from None
    finally:
        con.close()


def andamento_ler(requisicao_id) -> Andamento | None:
    con = _conectar_estado()
    try:
        linha = con.execute(
            "SELECT pergunta, etapa, texto_parcial, atualizado_em FROM andamento WHERE requisicao_id=?",
            (requisicao_id,),
        ).fetchone()
        if linha is None:
            return None
        pergunta, etapa, texto_parcial, atualizado_em = linha
        return Andamento(
            pergunta=pergunta, etapa=etapa, texto_parcial=texto_parcial, atualizado_em=atualizado_em
        )
    except sqlite3.DatabaseError:
        raise EstadoIndisponivel("não foi possível ler o andamento") from None
    finally:
        con.close()


def andamento_apagar(requisicao_id) -> None:
    con = _conectar_estado()
    try:
        con.execute("DELETE FROM andamento WHERE requisicao_id=?", (requisicao_id,))
    except sqlite3.DatabaseError:
        raise EstadoIndisponivel("não foi possível apagar o andamento") from None
    finally:
        con.close()


def limpar_andamento_orfao(agora, horas: int = _ANDAMENTO_ORFAO_HORAS) -> int:
    """Apaga `andamento` que sobrou de uma thread morta (reciclagem do
    worker, crash) — nunca tocado por `concluir` porque a thread nunca
    chegou lá. Preserva qualquer registro atualizado dentro da última
    hora; `ia_limpar` chama esta função sob demanda."""
    limite = (agora - timedelta(hours=horas)).isoformat()
    con = _conectar_estado()
    try:
        cursor = con.execute("DELETE FROM andamento WHERE atualizado_em < ?", (limite,))
        return cursor.rowcount
    except sqlite3.DatabaseError:
        raise EstadoIndisponivel("não foi possível limpar o andamento órfão") from None
    finally:
        con.close()


def consumo(usuario_id, dia) -> Consumo:
    con = _conectar_estado()
    try:
        linha = con.execute(
            "SELECT perguntas, tokens_entrada, tokens_saida FROM quota WHERE usuario_id=? AND dia=?",
            (usuario_id, dia),
        ).fetchone()
        if linha is None:
            return Consumo(0, 0, 0)
        return Consumo(*linha)
    except sqlite3.DatabaseError:
        raise EstadoIndisponivel("não foi possível ler o consumo") from None
    finally:
        con.close()


def limpar_metadados(hoje: date, dias: int = 7) -> int:
    """Apaga `quota`/`requisicao` de dias anteriores a `hoje - dias` e
    requisições `emitida` (nunca reservadas) anteriores ao dia atual. O dia
    atual nunca é apagado."""
    limite = (hoje - timedelta(days=dias)).isoformat()
    hoje_iso = hoje.isoformat()
    con = _conectar_estado()
    try:
        con.execute("BEGIN IMMEDIATE")
        apagados = 0
        apagados += con.execute("DELETE FROM quota WHERE dia < ?", (limite,)).rowcount
        apagados += con.execute("DELETE FROM requisicao WHERE dia < ?", (limite,)).rowcount
        apagados += con.execute(
            "DELETE FROM requisicao WHERE estado='emitida' AND dia < ?", (hoje_iso,)
        ).rowcount
        con.execute("COMMIT")
        return apagados
    except sqlite3.DatabaseError:
        con.execute("ROLLBACK")
        raise EstadoIndisponivel("não foi possível limpar metadados") from None
    finally:
        con.close()


def limpar_se_necessario(agora, *, intervalo_s: int = 60, marcador: Path | None = None) -> dict | None:
    """Verificação a cada passagem do laço do robô —
    roda `limpar_expiradas`/`limpar_metadados` só quando o marcador não
    existe ou registra um instante mais velho que `intervalo_s`, e toca o
    marcador em seguida. O marcador grava o instante de `agora` como TEXTO
    (ISO) em vez de depender do `mtime` do arquivo — o `mtime` é o relógio
    real do sistema operacional, que `freezegun` não substitui, e os
    testes desta verificação precisam de um relógio falso controlável
    ((6)) para provar "duas passagens dentro de 60s não limpam
    duas vezes". Funciona SEM `IA_API_KEY` (não depende de rede/cliente).
    `EstadoIndisponivel` vira `logger.warning` e `None` — a verificação de
    limpeza nunca derruba o laço do robô."""
    caminho_marcador = marcador or (Path(settings.IA_ESTADO_PATH).parent / "ultima_limpeza")
    try:
        if caminho_marcador.exists():
            try:
                ultima_limpeza = datetime.fromisoformat(
                    caminho_marcador.read_text(encoding="utf-8").strip()
                )
            except ValueError:
                ultima_limpeza = None
            if ultima_limpeza is not None and (agora - ultima_limpeza).total_seconds() < intervalo_s:
                return None
        expiradas = limpar_expiradas(agora)
        metadados = limpar_metadados(timezone.localdate(agora))
        caminho_marcador.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        caminho_marcador.write_text(agora.isoformat(), encoding="utf-8")
        return {"conversas_expiradas": expiradas, "metadados_apagados": metadados}
    except EstadoIndisponivel:
        logger.warning("limpeza periódica do assistente indisponível")
        return None
