import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("pca", "0008_backfill_exercicio_2026"),
    ]

    operations = [
        migrations.AlterField(
            model_name="processo",
            name="item_pca",
            field=models.PositiveIntegerField(db_index=True, verbose_name="item PCA"),
        ),
        migrations.AlterField(
            model_name="processo",
            name="exercicio",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="processos",
                to="catalogo.exercicio",
                verbose_name="exercício",
            ),
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.AlterField(
                    model_name="historicalprocesso",
                    name="exercicio",
                    field=models.ForeignKey(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="catalogo.exercicio",
                        verbose_name="exercício",
                    ),
                ),
            ],
            state_operations=[
                migrations.AlterField(
                    model_name="historicalprocesso",
                    name="exercicio",
                    field=models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="catalogo.exercicio",
                        verbose_name="exercício",
                    ),
                ),
            ],
        ),
        migrations.AlterField(
            model_name="reuniao",
            name="exercicio",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="reunioes",
                to="catalogo.exercicio",
                verbose_name="exercício",
            ),
        ),
        migrations.AddConstraint(
            model_name="processo",
            constraint=models.UniqueConstraint(
                fields=("exercicio", "item_pca"),
                name="pca_processo_exercicio_item_unico",
            ),
        ),
        migrations.AlterModelOptions(
            name="processo",
            options={
                "ordering": ["exercicio", "item_pca"],
                "permissions": [
                    (
                        "editar_pca",
                        "Pode editar processos, mover kanban e registrar acompanhamento",
                    ),
                    (
                        "gerir_exercicio",
                        "Pode criar, abrir e fechar exercícios do PCA",
                    ),
                ],
                "verbose_name": "processo",
                "verbose_name_plural": "processos",
            },
        ),
    ]
