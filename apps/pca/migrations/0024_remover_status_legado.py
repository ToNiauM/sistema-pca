# Hand-authored (Fase 17) — remoção final do enum `Status`/
# campo `Processo.status` ("qualquer outra coisa não existirá mais"),
# preservando `HistoricalProcesso.status` fisicamente no banco.
#
# (1) `RemoveField(processo, status)` — state E database: dropa de verdade a
# coluna crua de `processo`. Seguro porque a auditoria confirmou zero código vivo lendo/escrevendo `Processo.status`
# desde o plano (o campo só sobrevivia no schema, nunca decidindo nada
# em código novo desta fase).
#
# (2) `SeparateDatabaseAndState` em `historicalprocesso.status` — o Django
# "esquece" o campo no grafo de migrações e no model Python
# `HistoricalProcesso` (que já não o declara, porque `HistoricalRecords()`
# espelha `Processo`, sem `status`). A coluna `status` permanece fisicamente
# lá, com os 154+ valores históricos reais intactos — NENHUM `DROP COLUMN`/
# `UPDATE` roda sobre linha nenhuma, `database_operations` só relaxa a
# constraint NOT NULL (ver bug abaixo).
#
# Deviation (bug bloqueante, encontrado na verificação desta
# própria task): `database_operations=[]` puro (a intenção original) quebra
# TODA gravação futura de `Processo` — `HistoricalRecords()` cria uma linha
# de `historicalprocesso` a cada `save()`, e sem o campo `status` no model
# Python, o INSERT gerado pelo ORM simplesmente omite essa coluna. A coluna
# é NOT NULL sem `DEFAULT` a nível de banco (o CharField original nunca
# declarou `default=` nem `db_default=`), então o INSERT falha com
# `NotNullViolation` — confirmado por `setUpTestData` de
# `test_acoes_tabela.py` na primeira rodada de verificação. `RunSQL(ALTER
# TABLE ... ALTER COLUMN status DROP NOT NULL)` resolve: só afrouxa a
# constraint (nenhum valor existente muda, nenhuma linha é tocada), futuras
# linhas de `historicalprocesso` nascem com `status=NULL` — inacessível pelo
# ORM de qualquer forma, já que o campo nem existe mais no model Python.
#
# Precedente EXATO (para a técnica de divergência state/DB, não para a
# direção nullable→NOT NULL): STATE.md, decisão "Phase 05-01" —
# "HistoricalProcesso mantém estado de modelo nullable do simple-history,
# mas sua coluna é NOT NULL no banco via SeparateDatabaseAndState." Lá o
# Python SEMPRE fornece um valor (então a coluna física pode ficar NOT
# NULL); aqui o Python NUNCA mais fornece valor para `status` — por isso a
# direção é a oposta (DB precisa aceitar NULL), mesma técnica de
# `SeparateDatabaseAndState`.
#
# Contraste com 0019 (`RemoveField` simples de `data_recebimento_processo`):
# aquele campo tinha ZERO preenchimentos reais — RemoveField normal em AMBOS
# os modelos não descartava nenhum dado. `status` tem 154+ valores
# históricos reais; por isso `historicalprocesso.status` NÃO segue o mesmo
# padrão simples.

from django.db import migrations

# RunPython vendor-condicional: em SQLite o banco nasce do zero (sem dado
# histórico a preservar), então a coluna é removida de verdade. Em
# PostgreSQL preserva-se o SQL original — só afrouxa a constraint NOT NULL,
# nenhuma linha existente é tocada.


def _remover_not_null_status(apps, schema_editor):
    HistoricalProcesso = apps.get_model("pca", "historicalprocesso")
    campo = HistoricalProcesso._meta.get_field("status")
    if schema_editor.connection.vendor == "sqlite":
        schema_editor.remove_field(HistoricalProcesso, campo)
    else:
        schema_editor.execute(
            "ALTER TABLE pca_historicalprocesso "
            "ALTER COLUMN status DROP NOT NULL;"
        )


def _restaurar_not_null_status(apps, schema_editor):
    HistoricalProcesso = apps.get_model("pca", "historicalprocesso")
    campo = HistoricalProcesso._meta.get_field("status")
    if schema_editor.connection.vendor == "sqlite":
        schema_editor.add_field(HistoricalProcesso, campo)
    else:
        schema_editor.execute(
            "UPDATE pca_historicalprocesso SET status = '' "
            "WHERE status IS NULL;"
        )
        schema_editor.execute(
            "ALTER TABLE pca_historicalprocesso "
            "ALTER COLUMN status SET NOT NULL;"
        )


class Migration(migrations.Migration):

    dependencies = [
        ('pca', '0023_estado_situacao_tres_eixos'),
    ]

    operations = [
        # (1) processo.status — remoção real, state + database.
        migrations.RemoveField(
            model_name='processo',
            name='status',
        ),
        # (2) historicalprocesso.status — remoção só de STATE; a coluna
        # física permanece em PostgreSQL, com a constraint NOT NULL
        # relaxada (acima) para não quebrar o INSERT
        # automático do simple-history em toda gravação futura de
        # Processo. Em SQLite, banco novo, a coluna é removida de verdade.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name='historicalprocesso',
                    name='status',
                ),
            ],
            database_operations=[
                migrations.RunPython(
                    _remover_not_null_status,
                    _restaurar_not_null_status,
                ),
            ],
        ),
    ]
