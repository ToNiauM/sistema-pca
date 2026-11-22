"""Checkout do banco no corte — "como o sistema estava naquele dia".

`copia_no_corte(corte)` entrega uma cópia descartável do banco (SQLite) reconstruída do histórico do
`simple_history` no instante do corte; `apurar_no_corte(...)` roda `relatorio_checkout` num subprocesso
apontado para essa cópia e devolve os FATOS do relatório (`apurar_relatorio`, JSON puro) — quem renderiza é
a tela, com o código atual. O banco principal nunca é tocado nem a conexão do worker trocada (decisão).

O que volta no tempo: os modelos com `HistoricalRecords` (menos o Usuário). Ficam como estão hoje as tabelas
sem histórico (catálogo, ProcessoSEI, Usuário...) e as relações M2M.
"""

import contextlib
import json
import logging
import os
import sqlite3
import subprocess
import sys
import tempfile

from django.apps import apps as django_apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.db.models import Min
from django.utils import timezone

logger = logging.getLogger(__name__)

# Abaixo dos 60 s do gunicorn: a tela responde com erro em vez de o worker ser morto.
TIMEOUT_SUBPROCESSO = 45


class CheckoutErro(Exception):
    """O checkout não conseguiu produzir os fatos (cópia, subprocesso, timeout)."""


def modelos_com_historico():
    """Pares `(modelo, modelo_historico)` de todo modelo com `HistoricalRecords`, menos o Usuário.

    Mesmo padrão de `apps/assistente/esquema.py`: os próprios `Historical*` também são modelos do app
    (têm `instance_type`) e ficam de fora; `core.Usuario` é registrado no histórico mas não é reconstruído
    (a senha/sessão do usuário não voltam no tempo)."""
    usuario = get_user_model()
    pares = []
    for modelo in django_apps.get_models():
        if hasattr(modelo, "instance_type") or modelo is usuario:
            continue
        historico = getattr(modelo, "history", None)
        if historico is None:
            continue
        pares.append((modelo, historico.model))
    return pares


def primeiro_registro_historico():
    """Menor `history_date` entre os históricos rastreados (aware), ou None se não há nenhum registro."""
    menor = None
    for _modelo, historico in modelos_com_historico():
        data = historico.objects.aggregate(m=Min("history_date"))["m"]
        if data is not None and (menor is None or data < menor):
            menor = data
    return menor


# ---------------------------------------------------------------------------
# Cópia reconstruída
# ---------------------------------------------------------------------------


def _q(nome):
    return '"' + nome.replace('"', '""') + '"'


def _colunas(con, tabela):
    return [(linha[1], linha[3], linha[4], linha[5]) for linha in con.execute(f"PRAGMA table_info({_q(tabela)})")]


def _reconstruir_modelo(con, modelo, historico, corte_txt, avisos):
    tabela = modelo._meta.db_table
    tab_hist = historico._meta.db_table
    pk = modelo._meta.pk.column
    colunas_principal = _colunas(con, tabela)
    colunas_hist = {c[0] for c in _colunas(con, tab_hist)}
    comuns = [c[0] for c in colunas_principal if c[0] in colunas_hist]
    so_principal = [c for c in colunas_principal if c[0] not in colunas_hist]
    if pk not in colunas_hist:
        raise CheckoutErro(f"O histórico de {modelo.__name__} não tem a coluna {pk}.")

    # Objetos que nunca tiveram nenhum registro de histórico (criados por SQL cru/antes do histórico).
    avisos["sem_historico"] += con.execute(
        f"SELECT COUNT(*) FROM {_q(tabela)} WHERE {_q(pk)} NOT IN (SELECT {_q(pk)} FROM {_q(tab_hist)})"
    ).fetchone()[0]

    con.execute(f"DELETE FROM {_q(tab_hist)} WHERE history_date > ?", [corte_txt])

    lista_h = ", ".join(f"h.{_q(c)}" for c in comuns)
    con.execute("DROP TABLE IF EXISTS temp._ultimo")
    con.execute(
        f"CREATE TEMP TABLE _ultimo AS SELECT * FROM (SELECT {lista_h}, h.history_type AS _tipo, "
        f"ROW_NUMBER() OVER (PARTITION BY h.{_q(pk)} ORDER BY h.history_date DESC, h.history_id DESC) AS _rn "
        f"FROM {_q(tab_hist)} h) WHERE _rn = 1"
    )
    obrigatorias = [c[0] for c in so_principal if c[1] and c[2] is None and not c[3]]
    con.execute("DROP TABLE IF EXISTS temp._atual")
    if so_principal:
        lista_so = ", ".join(_q(c[0]) for c in so_principal)
        con.execute(f"CREATE TEMP TABLE _atual AS SELECT {_q(pk)} AS _pk, {lista_so} FROM {_q(tabela)}")
    con.execute(f"DELETE FROM {_q(tabela)}")

    destino = ", ".join(_q(c) for c in comuns + [c[0] for c in so_principal])
    origem = ", ".join([f"u.{_q(c)}" for c in comuns] + [f"a.{_q(c[0])}" for c in so_principal])
    juncao = f" LEFT JOIN _atual a ON a._pk = u.{_q(pk)}" if so_principal else ""
    onde = "u._tipo != '-'"
    if obrigatorias:
        # Sem a linha atual não há de onde tirar a coluna obrigatória que o histórico não tem: pula e avisa.
        avisos["puladas"] += con.execute(
            f"SELECT COUNT(*) FROM _ultimo u{juncao} WHERE {onde} AND a._pk IS NULL"
        ).fetchone()[0]
        onde += " AND a._pk IS NOT NULL"
    consulta = f"SELECT {origem} FROM _ultimo u{juncao} WHERE {onde}"
    insercao = f"INSERT INTO {_q(tabela)} ({destino}) {consulta}"
    try:
        con.execute("SAVEPOINT lote")
        con.execute(insercao)
        con.execute("RELEASE lote")
    except sqlite3.IntegrityError:
        con.execute("ROLLBACK TO lote")
        con.execute("RELEASE lote")
        marcas = ", ".join("?" for _ in comuns + so_principal)
        for linha in con.execute(consulta).fetchall():
            try:
                con.execute("SAVEPOINT linha")
                con.execute(f"INSERT INTO {_q(tabela)} ({destino}) VALUES ({marcas})", linha)
                con.execute("RELEASE linha")
            except sqlite3.IntegrityError:
                con.execute("ROLLBACK TO linha")
                con.execute("RELEASE linha")
                avisos["puladas"] += 1
    con.execute("DROP TABLE IF EXISTS temp._ultimo")
    con.execute("DROP TABLE IF EXISTS temp._atual")


def _reconstruir(con, corte, avisos):
    con.execute("PRAGMA foreign_keys=OFF")
    corte_txt = connection.ops.adapt_datetimefield_value(corte)
    con.isolation_level = None  # transação e savepoints sob nosso controle
    con.execute("BEGIN")
    for modelo, historico in modelos_com_historico():
        _reconstruir_modelo(con, modelo, historico, corte_txt, avisos)
    reuniao = django_apps.get_model("pca", "Reuniao")
    con.execute(
        f"DELETE FROM {_q(reuniao._meta.db_table)} WHERE data > ?", [timezone.localtime(corte).date().isoformat()]
    )
    con.execute("COMMIT")


@contextlib.contextmanager
def copia_no_corte(corte):
    """Context manager que entrega `(caminho, avisos)`: um arquivo SQLite temporário (0600) com o banco como
    estava em `corte` (datetime aware). `avisos` = contagens do que não pôde ser reconstruído. O arquivo (e
    `-wal`/`-shm`) some ao sair do contexto, com ou sem erro."""
    descritor, caminho = tempfile.mkstemp(suffix=".sqlite3", dir=tempfile.gettempdir())
    os.close(descritor)
    avisos = {"sem_historico": 0, "puladas": 0}
    try:
        origem = sqlite3.connect(connection.settings_dict["NAME"], timeout=30)
        try:
            destino = sqlite3.connect(caminho, timeout=30)
            try:
                origem.backup(destino)
                destino.execute("PRAGMA journal_mode=DELETE")
                _reconstruir(destino, corte, avisos)
            finally:
                destino.close()
        finally:
            origem.close()
        yield caminho, avisos
    finally:
        for sufixo in ("", "-wal", "-shm", "-journal"):
            with contextlib.suppress(FileNotFoundError):
                os.unlink(caminho + sufixo)


# ---------------------------------------------------------------------------
# Fatos no corte (subprocesso)
# ---------------------------------------------------------------------------


def apurar_no_corte(*, corte, exercicio, reuniao, de, ate, usuario):
    """Contrato: os FATOS do relatório (dict JSON, o mesmo de `apurar_relatorio`) como o banco estava
    em `corte` (datetime aware). Quem renderiza é a tela, com o código atual. A apuração roda num subprocesso
    (`relatorio_checkout`) contra uma cópia reconstruída do histórico; o banco principal nunca é tocado nem a
    conexão do worker trocada. `reuniao` e `usuario` podem ser None. Levanta `CheckoutErro` em qualquer falha."""
    try:
        with copia_no_corte(corte) as (caminho, avisos):
            if avisos["sem_historico"] or avisos["puladas"]:
                logger.warning("Checkout em %s: %s", corte.isoformat(), avisos)
            comando = [
                sys.executable, str(settings.BASE_DIR / "manage.py"), "relatorio_checkout",
                "--banco", caminho,
                "--corte", corte.isoformat(),
                "--exercicio", str(exercicio.pk),
                "--reuniao", str(reuniao.pk) if reuniao is not None else "",
                "--de", de.isoformat(),
                "--ate", ate.isoformat(),
                "--usuario", str(usuario.pk) if usuario is not None else "",
            ]
            ambiente = dict(os.environ)
            ambiente["DATABASE_URL"] = f"sqlite:///{os.path.abspath(caminho)}"
            # `settings.SETTINGS_MODULE` vem None dentro de um `override_settings`; o ambiente é a fonte.
            modulo = os.environ.get("DJANGO_SETTINGS_MODULE") or settings.SETTINGS_MODULE
            if modulo:
                ambiente["DJANGO_SETTINGS_MODULE"] = modulo
            ambiente["PYTHONIOENCODING"] = "utf-8"
            try:
                resultado = subprocess.run(
                    comando, cwd=str(settings.BASE_DIR), capture_output=True, timeout=TIMEOUT_SUBPROCESSO,
                    env=ambiente,
                )
            except subprocess.TimeoutExpired as exc:
                raise CheckoutErro(f"A reconstituição passou de {TIMEOUT_SUBPROCESSO} segundos.") from exc
    except (sqlite3.Error, OSError) as exc:
        raise CheckoutErro(f"Falha ao copiar o banco: {exc}") from exc
    if resultado.returncode != 0:
        fim = resultado.stderr.decode("utf-8", "replace").strip()[-600:]
        raise CheckoutErro(f"O subprocesso terminou com erro {resultado.returncode}: {fim}")
    try:
        return json.loads(resultado.stdout.decode("utf-8"))
    except ValueError as exc:
        raise CheckoutErro("O subprocesso não devolveu os fatos em JSON.") from exc
