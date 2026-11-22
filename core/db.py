"""Peças portáveis que substituem recursos exclusivos do PostgreSQL:
extensão `unaccent`, `Extract(DurationField)` para diferença de
datas e a collation ICU de `initdb` para ordenação de texto em pt-BR.

Registradas na conexão em `connection_created` (ver `core.apps.CoreConfig.
ready`), só quando `connection.vendor == "sqlite"` — em PostgreSQL, as
mesmas peças continuam funcionando pelos caminhos nativos já existentes
(`django.contrib.postgres.lookups.Unaccent`/subtração nativa de datas/ICU),
sem precisar desta função de setup.
"""

import unicodedata
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import CharField, Func, IntegerField, TextField, Transform


def _unaccent(texto):
    """Remove diacríticos via NFKD e aplica casefold. `texto` pode ser
    `None` — a UDF do SQLite é chamada com `None` para colunas nulas."""
    if texto is None:
        return None
    forma_decomposta = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(
        caractere
        for caractere in forma_decomposta
        if not unicodedata.combining(caractere)
    )
    return sem_acento.casefold()


class Unaccent(Transform):
    """Mesmos três atributos de `django.contrib.postgres.lookups.Unaccent`
    — `bilateral = True` aplica a transformação nos dois lados da
    comparação (coluna E termo buscado), condição necessária para um termo
    acentuado encontrar conteúdo sem acento e vice-versa."""

    bilateral = True
    lookup_name = "unaccent"
    function = "UNACCENT"


CharField.register_lookup(Unaccent)
TextField.register_lookup(Unaccent)


class DiasEntre(Func):
    """Diferença inteira de dias entre duas datas (`arg1 - arg2`). A forma
    final é uma subtração de duas expressões compiladas separadamente, não
    uma função de dois argumentos separados por vírgula — por isso não usa
    o template padrão de `Func`."""

    arity = 2
    output_field = IntegerField()

    def as_sqlite(self, compiler, connection, **extra_context):
        lhs, rhs = self.get_source_expressions()
        lhs_sql, lhs_params = compiler.compile(lhs)
        rhs_sql, rhs_params = compiler.compile(rhs)
        sql = f"CAST(julianday({lhs_sql}) - julianday({rhs_sql}) AS INTEGER)"
        return sql, (*lhs_params, *rhs_params)

    def as_postgresql(self, compiler, connection, **extra_context):
        lhs, rhs = self.get_source_expressions()
        lhs_sql, lhs_params = compiler.compile(lhs)
        rhs_sql, rhs_params = compiler.compile(rhs)
        sql = f"({lhs_sql} - {rhs_sql})"
        return sql, (*lhs_params, *rhs_params)


def _collation_ptbr(a, b):
    """Compara pelo texto sem acento/caixa primeiro; o texto original
    original entra como desempate estável. `a`/`b` nunca são `None` — o
    SQLite ordena valores nulos sem chamar a collation."""
    chave_a = (_unaccent(a), a)
    chave_b = (_unaccent(b), b)
    if chave_a < chave_b:
        return -1
    if chave_a > chave_b:
        return 1
    return 0


def configurar_conexao_sqlite(sender, connection, **kwargs):
    """Receiver de `connection_created` — registra a função `unaccent` e a
    collation `ptbr` na conexão bruta do SQLite. No-op em qualquer outro
    vendor."""
    if connection.vendor != "sqlite":
        return
    conexao_bruta = connection.connection
    conexao_bruta.create_function("unaccent", 1, _unaccent, deterministic=True)
    conexao_bruta.create_collation("ptbr", _collation_ptbr)


def quantizar_soma(valor, casas=2):
    """O `SUM()` nativo do SQLite acumula em ponto flutuante binário mesmo
    para colunas `DecimalField` (o PostgreSQL soma como `NUMERIC` exato) —
    149 parcelas de centavos exatos podem voltar como
    `Decimal("162642475.662000")` em vez de `Decimal("162642475.66")`.
    Quantiza o resultado de um `.aggregate(Sum(...))` de volta às casas
    decimais do campo; `None` passa direto (queryset vazio)."""
    if valor is None:
        return None
    return valor.quantize(Decimal("1").scaleb(-casas), rounding=ROUND_HALF_UP)
