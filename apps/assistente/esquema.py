"""Catálogo do esquema do banco embutido na
descrição da ferramenta `consultar_sql` (`apps/assistente/ferramentas.py`),
para o modelo conhecer tabelas/colunas sem gastar uma chamada extra.
Cobre `apps.pca` + `apps.catalogo` + `core.Usuario` (+ os `Historical*` de
cada um, via `modelo.history.model` — simple_history), omitindo toda
tabela/coluna bloqueada em `apps.assistente.sql` (fonte ÚNICA da
allowlist, nunca duplicada aqui: bloquear uma tabela/coluna nova em
`sql.py` automaticamente a tira do catálogo também)."""

from __future__ import annotations

import functools

from apps.assistente import sql

_CABECALHO = (
    "Convenções do domínio (banco inteiro do PCA, SQLite):\n"
    "- Mês previsto (`mes_previsto`) é um inteiro 1–12, nunca o texto "
    "'jan'..'dez'.\n"
    "- Valores monetários são reais em colunas DECIMAL/afinidade NUMERIC — "
    "SUM/AVG funcionam direto, sem conversão.\n"
    "- O exercício (ano do PCA) vive em `catalogo_exercicio.ano`; "
    "`pca_processo.exercicio_id` referencia essa tabela.\n"
    "- Tabelas `*_historical*` têm `history_date` (quando), `history_type` "
    "(`+`=criado, `~`=alterado, `-`=excluído) e `history_user_id` (quem)."
)


def _tabela_omitida(db_table: str) -> bool:
    if db_table in sql.TABELAS_BLOQUEADAS:
        return True
    return any(db_table.startswith(prefixo) for prefixo in sql.PREFIXOS_TABELAS_BLOQUEADAS)


def _linha_campo(campo, db_table: str) -> str | None:
    coluna = campo.column
    if coluna in sql.COLUNAS_BLOQUEADAS.get(db_table, frozenset()):
        return None
    linha = f"{coluna} ({campo.get_internal_type()}) — {campo.verbose_name}"
    if campo.choices:
        pares = "; ".join(f"{valor}={rotulo}" for valor, rotulo in campo.choices)
        linha += f" [{pares}]"
    if campo.is_relation and campo.many_to_one:
        linha += f"\nFK: {coluna} → {campo.related_model._meta.db_table}.id"
    return linha


def _bloco_modelo(modelo) -> str | None:
    db_table = modelo._meta.db_table
    if _tabela_omitida(db_table):
        return None
    linhas = [
        linha
        for campo in modelo._meta.concrete_fields
        if (linha := _linha_campo(campo, db_table)) is not None
    ]
    return f"## {db_table}\n" + "\n".join(linhas)


@functools.cache
def catalogo() -> str:
    """Catálogo de tabelas/colunas/FKs/choices, em texto, cacheado por
    processo (sem rede/DB a cada chamada — recarregar o worker é o único
    jeito de atualizar, igual a qualquer outro catálogo estático do
    sistema)."""
    from django.apps import apps as django_apps

    from core.models import Usuario

    modelos_correntes = [
        *django_apps.get_app_config("pca").get_models(),
        *django_apps.get_app_config("catalogo").get_models(),
        Usuario,
    ]
    # `get_models()` já inclui os modelos `Historical*` do simple_history
    # como registros próprios (uma tabela de verdade) — removê-los da
    # lista "corrente" aqui para não duplicar o bloco quando eles entrarem
    # de novo abaixo, via `modelo.history.model`, na ordem pedida pela
    # spec (tabela corrente primeiro, Historical* depois).
    modelos_correntes = [
        modelo for modelo in modelos_correntes if not hasattr(modelo, "instance_type")
    ]

    modelos_historicos = []
    for modelo in modelos_correntes:
        historico = getattr(modelo, "history", None)
        if historico is not None:
            modelos_historicos.append(historico.model)

    blocos = [_CABECALHO]
    for modelo in [*modelos_correntes, *modelos_historicos]:
        bloco = _bloco_modelo(modelo)
        if bloco is not None:
            blocos.append(bloco)
    return "\n\n".join(blocos)
