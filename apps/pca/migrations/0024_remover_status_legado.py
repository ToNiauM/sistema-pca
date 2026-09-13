# Remoção final do campo `Processo.status`, preservando
# `HistoricalProcesso.status` fisicamente no banco.
#
# (1) RemoveField(processo, status) — state e database: dropa de verdade a
# coluna de `processo`; confirmado que nenhum código vivo lê/escreve
# `Processo.status`.
#
# (2) SeparateDatabaseAndState em `historicalprocesso.status` — o Django
# esquece o campo no grafo de migrações e no model Python (HistoricalRecords
# espelha Processo, sem status); a coluna permanece fisicamente com os
# valores históricos intactos, e `database_operations` só relaxa a
# constraint NOT NULL.
#
# Correção de bug: `database_operations=[]` puro quebraria toda gravação
# futura de Processo — HistoricalRecords insere uma linha de
# historicalprocesso a cada save(), e sem o campo `status` no model Python o
# INSERT omite essa coluna; como ela é NOT NULL sem DEFAULT no banco, o
# INSERT falharia com NotNullViolation. `RunSQL(ALTER TABLE ... ALTER COLUMN
# status DROP NOT NULL)` resolve sem tocar nenhum valor existente; futuras
# linhas nascem com status=NULL, inacessível pelo ORM de qualquer forma.
#
# Contraste com 0019 (RemoveField simples): aquele campo tinha zero
# preenchimentos reais; `status` tem 154+ valores históricos reais, por isso
# não segue o mesmo padrão simples.

from django.db import migrations


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
        # física permanece, com a constraint NOT NULL relaxada para não
        # quebrar o INSERT automático do simple-history.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name='historicalprocesso',
                    name='status',
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        'ALTER TABLE pca_historicalprocesso '
                        'ALTER COLUMN status DROP NOT NULL;'
                    ),
                    reverse_sql=(
                        "UPDATE pca_historicalprocesso SET status = '' "
                        'WHERE status IS NULL;\n'
                        'ALTER TABLE pca_historicalprocesso '
                        'ALTER COLUMN status SET NOT NULL;'
                    ),
                ),
            ],
        ),
    ]
