"""Conexão sqlite3 compartilhada dos três auxiliares do Assistente do PCA
(`estado.sqlite3`/`conversas.sqlite3`/`indice.sqlite3`) — stdlib pura, fora
do ORM/banco principal. Mesmo padrão nos três: diretório `0700`, arquivo
criado com `0600` ANTES da conexão (nunca deixa o sqlite3 criar o arquivo
com a umask do processo), WAL, `foreign_keys=ON`, `busy_timeout`,
`synchronous=NORMAL`. Extraído de `estado.py` (Fase 39) para que
`indice.py` reaproveite o mesmo padrão sem duplicar."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path


def conectar(caminho_str: str) -> sqlite3.Connection:
    """Abre (criando se preciso) uma conexão sqlite3 em modo autocommit
    (`isolation_level=None` — toda transação multi-statement é explícita
    com `BEGIN IMMEDIATE`/`COMMIT`/`ROLLBACK`). Levanta `sqlite3.
    DatabaseError` cru quando as PRAGMAs falham (arquivo corrompido) —
    fecha a conexão antes de relançar; o chamador converte para a exceção
    operacional do seu próprio módulo (`EstadoIndisponivel`/
    `IndiceIndisponivel`), nunca deixa o erro cru escapar."""
    caminho = Path(caminho_str)
    caminho.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not caminho.exists():
        fd = os.open(str(caminho), os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
    con = sqlite3.connect(str(caminho), timeout=5, isolation_level=None)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA busy_timeout=5000")
        con.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.DatabaseError:
        con.close()
        raise
    return con
