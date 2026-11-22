"""Índice semântico do Assistente do PCA (A05..A08) —
SQLite próprio (`indice.sqlite3`), schema versionado, publicado por geração
ATÔMICA (estágio separado, promoção em transação curta, falha preserva a
geração anterior inteira). Escritor único (`fcntl.flock` exclusivo não
bloqueante) — cron/Admin nunca indexam ao mesmo tempo.

`buscar()` calcula as fontes autorizadas do usuário (`fontes.
permissoes_autorizadas`) ANTES de carregar qualquer candidato — a máscara
de permissão/metadados é aplicada antes do cosseno/top-k, nunca depois.
Nenhum resultado fica em cache por usuário — só a matriz de
vetores (por `geracao`, sem identidade nenhuma) é reaproveitada entre
chamadas."""

from __future__ import annotations

import fcntl
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from django.conf import settings

from apps.assistente import _sqlite, fontes

SCHEMA_VERSAO = 1

_TAMANHO_LOTE_EMBEDDINGS = 64
_TETO_BYTES_LOTE_EMBEDDINGS = 200 * 1024

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (chave TEXT PRIMARY KEY, valor TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS trecho (
    id INTEGER PRIMARY KEY,
    fonte TEXT NOT NULL,
    ref TEXT NOT NULL,
    ordem INTEGER NOT NULL,
    titulo TEXT NOT NULL,
    texto TEXT NOT NULL,
    url TEXT,
    exercicio INTEGER,
    item_pca INTEGER,
    permissao TEXT NOT NULL,
    hash_texto TEXT NOT NULL,
    atualizado_em TEXT,
    UNIQUE(fonte, ref, ordem)
);
CREATE INDEX IF NOT EXISTS idx_trecho_permissao ON trecho(permissao);
CREATE INDEX IF NOT EXISTS idx_trecho_exercicio_item ON trecho(exercicio, item_pca);

CREATE TABLE IF NOT EXISTS vetor (
    trecho_id INTEGER PRIMARY KEY REFERENCES trecho(id) ON DELETE CASCADE,
    dim INTEGER NOT NULL,
    blob BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS estagio_trecho (
    id INTEGER PRIMARY KEY,
    fonte TEXT NOT NULL,
    ref TEXT NOT NULL,
    ordem INTEGER NOT NULL,
    titulo TEXT NOT NULL,
    texto TEXT NOT NULL,
    url TEXT,
    exercicio INTEGER,
    item_pca INTEGER,
    permissao TEXT NOT NULL,
    hash_texto TEXT NOT NULL,
    atualizado_em TEXT
);
CREATE TABLE IF NOT EXISTS estagio_vetor (
    trecho_id INTEGER,
    dim INTEGER NOT NULL,
    blob BLOB NOT NULL
);
"""


class IndiceIndisponivel(Exception):
    """Índice ausente/corrompido — a ferramenta devolve erro amigável,
    nunca 500."""


class IndiceOcupado(Exception):
    """Já existe uma indexação em andamento — escritor único."""


@dataclass
class ResumoIndexacao:
    geracao: int
    novos: int
    reaproveitados: int
    removidos: int
    tokens: int
    duracao_s: float


@dataclass
class Resultado:
    trecho_id: int
    escore: float
    fonte: str
    ref: str
    titulo: str
    texto: str
    url: str | None
    exercicio: int | None
    item_pca: int | None
    atualizado_em: str | None


def assinatura_compatibilidade(modelo: str, dimensao: int) -> str:
    return f"{modelo}|{dimensao}|{fontes.FRAGMENTADOR_VERSAO}"


def _lock_path() -> Path:
    return Path(f"{settings.IA_INDICE_PATH}.lock")


def _conectar() -> sqlite3.Connection:
    try:
        con = _sqlite.conectar(settings.IA_INDICE_PATH)
    except sqlite3.DatabaseError:
        raise IndiceIndisponivel("índice corrompido") from None
    try:
        con.executescript(_SCHEMA)
        linha = con.execute("SELECT valor FROM meta WHERE chave='schema_versao'").fetchone()
        if linha is None:
            con.execute(
                "INSERT INTO meta(chave, valor) VALUES ('schema_versao', ?)", (str(SCHEMA_VERSAO),)
            )
        elif int(linha[0]) > SCHEMA_VERSAO:
            raise IndiceIndisponivel("schema mais novo que o suportado por esta versão")
    except sqlite3.DatabaseError:
        con.close()
        raise IndiceIndisponivel("índice corrompido") from None
    except IndiceIndisponivel:
        con.close()
        raise
    return con


def _ler_meta(con: sqlite3.Connection) -> dict:
    linhas = con.execute("SELECT chave, valor FROM meta").fetchall()
    return dict(linhas)


def _upsert_meta(con: sqlite3.Connection, chave: str, valor: str) -> None:
    con.execute(
        "INSERT INTO meta(chave, valor) VALUES (?, ?) "
        "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor",
        (chave, valor),
    )


def publicado_em() -> str | None:
    """Leitura barata de `meta.publicado_em` — `None` sem arquivo/índice
    corrompido (usado na faixa de contexto da tela e no rodapé; NUNCA
    lança para essas duas chamadas)."""
    if not Path(settings.IA_INDICE_PATH).exists():
        return None
    try:
        con = _conectar()
    except IndiceIndisponivel:
        return None
    try:
        return _ler_meta(con).get("publicado_em") or None
    finally:
        con.close()


def _serializar_vetor(vetor) -> bytes:
    """float32 little-endian normalizado L2 — vetor de norma zero é
    armazenado zerado (nunca divide por zero)."""
    arr = np.asarray(vetor, dtype=np.float64)
    norma = float(np.linalg.norm(arr))
    if norma > 0:
        arr = arr / norma
    return arr.astype("<f4").tobytes()


def indexar(cliente, *, completo: bool = False, agora, stdout=None) -> ResumoIndexacao:
    """Publica uma nova geração do índice — ver docstring do módulo para o
    contrato completo. `cliente` é o `ClienteOpenAI` (ou falso,
    em teste) — `cliente is None` (IA_API_KEY vazia) levanta
    `IndiceIndisponivel` antes de tocar em qualquer coisa."""
    if cliente is None:
        raise IndiceIndisponivel("cliente de IA indisponível")

    inicio = time.monotonic()
    caminho_lock = _lock_path()
    caminho_lock.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    arquivo_lock = open(caminho_lock, "a+")
    try:
        try:
            fcntl.flock(arquivo_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise IndiceOcupado("indexação já em andamento") from None

        # (2) extração ANTES de tocar o índice — falha aborta sem publicar
        # nada e sem sequer abrir a conexão de escrita.
        trechos = fontes.extrair_tudo()

        con = _conectar()
        try:
            meta_atual = _ler_meta(con)
            chaves_antigas = set(
                con.execute("SELECT fonte, ref, ordem FROM trecho").fetchall()
            )

            modelo_publicado = meta_atual.get("modelo_embed")
            fragmentador_publicado = meta_atual.get("fragmentador_versao")
            reconstruir = (
                completo
                or not modelo_publicado
                or modelo_publicado != settings.IA_MODELO_EMBED
                or str(fragmentador_publicado) != str(fontes.FRAGMENTADOR_VERSAO)
            )

            reaproveitaveis: dict = {}
            if not reconstruir:
                linhas = con.execute(
                    "SELECT t.fonte, t.ref, t.ordem, t.hash_texto, v.dim, v.blob "
                    "FROM trecho t JOIN vetor v ON v.trecho_id = t.id"
                ).fetchall()
                for linha_fonte, ref, ordem, hash_anterior, dim, blob in linhas:
                    reaproveitaveis[(linha_fonte, ref, ordem)] = (hash_anterior, dim, blob)

            # plano[i] = [trecho, hash_atual, dim|None, blob|None] — dim/blob
            # preenchidos aqui quando reaproveitado, ou depois do lote de
            # embeddings quando novo/mudou.
            plano: list[list] = []
            fila_embeddings: list[int] = []
            for trecho in trechos:
                chave = (trecho.fonte, trecho.ref, trecho.ordem)
                hash_atual = fontes.hash_texto_normalizado(trecho.texto)
                anterior = reaproveitaveis.get(chave)
                if anterior is not None and anterior[0] == hash_atual:
                    plano.append([trecho, hash_atual, anterior[1], anterior[2]])
                else:
                    plano.append([trecho, hash_atual, None, None])
                    fila_embeddings.append(len(plano) - 1)

            # (5) embeddings em lotes, FORA de qualquer transação — ErroCliente
            # no meio propaga (o `finally` solta o lock; nada foi gravado).
            tokens_novos = 0
            i = 0
            while i < len(fila_embeddings):
                indices_lote: list[int] = []
                bytes_lote = 0
                while i < len(fila_embeddings) and len(indices_lote) < _TAMANHO_LOTE_EMBEDDINGS:
                    idx = fila_embeddings[i]
                    tamanho = len(plano[idx][0].texto.encode("utf-8"))
                    if indices_lote and bytes_lote + tamanho > _TETO_BYTES_LOTE_EMBEDDINGS:
                        break
                    indices_lote.append(idx)
                    bytes_lote += tamanho
                    i += 1
                textos_lote = [plano[idx][0].texto for idx in indices_lote]
                resposta = cliente.embeddings(textos_lote, settings.IA_TIMEOUT_S)
                tokens_novos += resposta.tokens
                for idx, vetor in zip(indices_lote, resposta.vetores):
                    plano[idx][2] = len(vetor)
                    plano[idx][3] = _serializar_vetor(vetor)

            contagens: dict = {}
            linhas_trecho = []
            linhas_vetor = []
            dimensao_final = int(meta_atual.get("dimensao") or 0)
            for trecho, hash_atual, dim, blob in plano:
                linhas_trecho.append((
                    trecho.fonte, trecho.ref, trecho.ordem, trecho.titulo, trecho.texto,
                    trecho.url, trecho.exercicio, trecho.item_pca, trecho.permissao,
                    hash_atual, trecho.atualizado_em,
                ))
                linhas_vetor.append((dim or 0, blob or b""))
                contagens[trecho.fonte] = contagens.get(trecho.fonte, 0) + 1
                if dim:
                    dimensao_final = dim

            chaves_novas = {(t.fonte, t.ref, t.ordem) for t in trechos}
            removidos = len(chaves_antigas - chaves_novas)
            geracao_nova = int(meta_atual.get("geracao") or 0) + 1
            tokens_acumulados = int(meta_atual.get("tokens_indexacao") or 0) + tokens_novos

            # (6) promoção — estágio recriado, trecho+vetor+meta em UMA
            # transação curta; JOIN pela chave natural (fonte, ref, ordem),
            # nunca por suposição de ordem de rowid entre as duas tabelas.
            con.execute("BEGIN IMMEDIATE")
            try:
                con.execute("DELETE FROM estagio_vetor")
                con.execute("DELETE FROM estagio_trecho")
                for linha_trecho, (dim, blob) in zip(linhas_trecho, linhas_vetor):
                    cursor = con.execute(
                        "INSERT INTO estagio_trecho"
                        "(fonte, ref, ordem, titulo, texto, url, exercicio, item_pca, "
                        "permissao, hash_texto, atualizado_em) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        linha_trecho,
                    )
                    con.execute(
                        "INSERT INTO estagio_vetor(trecho_id, dim, blob) VALUES (?,?,?)",
                        (cursor.lastrowid, dim, blob),
                    )

                con.execute("DELETE FROM vetor")
                con.execute("DELETE FROM trecho")
                con.execute(
                    "INSERT INTO trecho"
                    "(fonte, ref, ordem, titulo, texto, url, exercicio, item_pca, permissao, "
                    "hash_texto, atualizado_em) "
                    "SELECT fonte, ref, ordem, titulo, texto, url, exercicio, item_pca, "
                    "permissao, hash_texto, atualizado_em FROM estagio_trecho"
                )
                con.execute(
                    "INSERT INTO vetor(trecho_id, dim, blob) "
                    "SELECT t.id, sv.dim, sv.blob "
                    "FROM trecho t "
                    "JOIN estagio_trecho st "
                    "  ON st.fonte = t.fonte AND st.ref = t.ref AND st.ordem = t.ordem "
                    "JOIN estagio_vetor sv ON sv.trecho_id = st.id"
                )

                _upsert_meta(con, "geracao", str(geracao_nova))
                _upsert_meta(con, "modelo_embed", settings.IA_MODELO_EMBED)
                _upsert_meta(con, "dimensao", str(dimensao_final))
                _upsert_meta(con, "fragmentador_versao", str(fontes.FRAGMENTADOR_VERSAO))
                _upsert_meta(con, "publicado_em", agora.isoformat())
                _upsert_meta(con, "contagens_json", json.dumps(contagens, ensure_ascii=False))
                _upsert_meta(con, "tokens_indexacao", str(tokens_acumulados))
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        finally:
            con.close()
    finally:
        try:
            fcntl.flock(arquivo_lock, fcntl.LOCK_UN)
        except OSError:
            pass
        arquivo_lock.close()

    _CACHE_MATRIZ.clear()
    duracao_s = round(time.monotonic() - inicio, 3)
    resumo = ResumoIndexacao(
        geracao=geracao_nova,
        novos=len(fila_embeddings),
        reaproveitados=len(plano) - len(fila_embeddings),
        removidos=removidos,
        tokens=tokens_novos,
        duracao_s=duracao_s,
    )
    if stdout is not None:
        stdout.write(
            f"geração {resumo.geracao} publicada: novos={resumo.novos} "
            f"reaproveitados={resumo.reaproveitados} removidos={resumo.removidos} "
            f"tokens={resumo.tokens} em {resumo.duracao_s} s"
        )
    return resumo


# --- Busca ---------------------------------------------------------------

# Cache de módulo da matriz de vetores por `geracao` — NUNCA por usuário/
# permissão (ACL é sempre recalculada por chamada, nunca cacheada).
# Guarda só a última geração vista; invalidada quando `meta.geracao` muda.
_CACHE_MATRIZ: dict[int, tuple] = {}


_SEM_EXERCICIO = -1
_SEM_ITEM = -1


def _carregar_matriz(con: sqlite3.Connection):
    """Carrega a matriz de vetores + metadados VETORIZADOS (arrays numpy,
    não uma lista de tuplas percorrida em Python) — a máscara de ACL em
    `buscar()` compara arrays inteiros, não faz um laço Python por trecho
    (o laço por linha custava a maior parte do tempo na medição de 50 mil
    trechos, muito mais que o cosseno em si, que já é BLAS)."""
    linhas = con.execute(
        "SELECT t.id, t.fonte, t.exercicio, t.item_pca, t.permissao, v.dim, v.blob "
        "FROM trecho t JOIN vetor v ON v.trecho_id = t.id ORDER BY t.id"
    ).fetchall()
    if not linhas:
        vazio_meta = {
            "fontes": np.array([], dtype=object),
            "exercicios": np.array([], dtype=np.int64),
            "itens": np.array([], dtype=np.int64),
            "permissoes": np.array([], dtype=object),
        }
        return np.array([], dtype=np.int64), np.zeros((0, 0), dtype="<f4"), vazio_meta

    dim = max((linha[5] for linha in linhas), default=0) or 1
    n = len(linhas)
    ids = np.empty(n, dtype=np.int64)
    matriz = np.zeros((n, dim), dtype="<f4")
    fontes_arr = np.empty(n, dtype=object)
    exercicios_arr = np.empty(n, dtype=np.int64)
    itens_arr = np.empty(n, dtype=np.int64)
    permissoes_arr = np.empty(n, dtype=object)

    for posicao, (id_, fonte, exercicio, item_pca, permissao, dim_linha, blob) in enumerate(linhas):
        ids[posicao] = id_
        fontes_arr[posicao] = fonte
        exercicios_arr[posicao] = exercicio if exercicio is not None else _SEM_EXERCICIO
        itens_arr[posicao] = item_pca if item_pca is not None else _SEM_ITEM
        permissoes_arr[posicao] = permissao
        vetor = np.frombuffer(blob, dtype="<f4")
        if dim_linha and len(vetor) == dim_linha:
            matriz[posicao, : len(vetor)] = vetor

    meta = {
        "fontes": fontes_arr,
        "exercicios": exercicios_arr,
        "itens": itens_arr,
        "permissoes": permissoes_arr,
    }
    return ids, matriz, meta


def _matriz(geracao: int):
    if geracao in _CACHE_MATRIZ:
        return _CACHE_MATRIZ[geracao]
    con = _conectar()
    try:
        resultado = _carregar_matriz(con)
    finally:
        con.close()
    _CACHE_MATRIZ.clear()
    _CACHE_MATRIZ[geracao] = resultado
    return resultado


def buscar(
    *,
    usuario,
    vetor_consulta,
    exercicio: int | None = None,
    item_pca: int | None = None,
    fonte: str | None = None,
    k: int = 6,
    limiar: float = 0.25,
) -> list[Resultado]:
    """Busca autorizada: `permissoes_autorizadas(usuario)`
    calculado ANTES de qualquer candidato; máscara de metadados (permissão
    + filtros) aplicada antes do cosseno/top-k — `fonte=None` NÃO relaxa a
    máscara de permissão. Lista vazia = abstenção. `IndiceIndisponivel`
    quando o índice nunca foi gerado ou está corrompido."""
    permitidas = fontes.permissoes_autorizadas(usuario)

    if not Path(settings.IA_INDICE_PATH).exists():
        raise IndiceIndisponivel("índice ainda não gerado")

    con = _conectar()
    try:
        geracao = int(_ler_meta(con).get("geracao") or 0)
    finally:
        con.close()

    if geracao == 0 or not permitidas:
        return []

    ids, matriz, meta = _matriz(geracao)
    if len(ids) == 0:
        return []

    # Máscara de ACL/filtros — vetorizada (numpy), nunca um laço Python por
    # trecho: comparações array-a-array, aplicadas ANTES do cosseno/top-k.
    #`fonte=None` não relaxa a máscara de permissão.
    mascara = np.isin(meta["permissoes"], np.array(list(permitidas), dtype=object))
    if fonte is not None:
        mascara &= meta["fontes"] == fonte
    if exercicio is not None:
        mascara &= meta["exercicios"] == exercicio
    if item_pca is not None:
        mascara &= meta["itens"] == item_pca

    indices_permitidos = np.nonzero(mascara)[0]
    if indices_permitidos.size == 0:
        return []

    vetor = np.asarray(vetor_consulta, dtype=np.float64)
    norma = float(np.linalg.norm(vetor))
    if norma > 0:
        vetor = vetor / norma
    vetor_f4 = vetor.astype("<f4")

    submatriz = matriz[indices_permitidos]
    if submatriz.shape[1] != vetor_f4.shape[0]:
        return []
    escores = submatriz @ vetor_f4

    k_efetivo = min(k, escores.shape[0])
    if k_efetivo <= 0:
        return []
    topo_local = np.argpartition(-escores, k_efetivo - 1)[:k_efetivo]
    topo_local = topo_local[np.argsort(-escores[topo_local])]

    resultados: list[Resultado] = []
    con = _conectar()
    try:
        for posicao_local in topo_local:
            escore = float(escores[posicao_local])
            if escore < limiar:
                continue
            trecho_id = int(ids[indices_permitidos[posicao_local]])
            linha = con.execute(
                "SELECT fonte, ref, titulo, texto, url, exercicio, item_pca, atualizado_em "
                "FROM trecho WHERE id = ?",
                (trecho_id,),
            ).fetchone()
            if linha is None:
                continue
            resultados.append(
                Resultado(
                    trecho_id=trecho_id,
                    escore=round(escore, 3),
                    fonte=linha[0],
                    ref=linha[1],
                    titulo=linha[2],
                    texto=linha[3],
                    url=linha[4],
                    exercicio=linha[5],
                    item_pca=linha[6],
                    atualizado_em=linha[7],
                )
            )
    finally:
        con.close()
    return resultados
