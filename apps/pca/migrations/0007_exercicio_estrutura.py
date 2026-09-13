import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("catalogo", "0002_exercicio"),
        ("pca", "0006_fornecedor_cnpj_validators"),
    ]

    operations = [
        migrations.AddField(
            model_name="processo",
            name="exercicio",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="processos",
                to="catalogo.exercicio",
                verbose_name="exercício",
            ),
        ),
        migrations.AddField(
            model_name="processo",
            name="origem",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="derivados",
                to="pca.processo",
                verbose_name="processo de origem",
            ),
        ),
        migrations.AddField(
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
        migrations.AddField(
            model_name="historicalprocesso",
            name="origem",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="pca.processo",
                verbose_name="processo de origem",
            ),
        ),
        migrations.AddField(
            model_name="reuniao",
            name="exercicio",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="reunioes",
                to="catalogo.exercicio",
                verbose_name="exercício",
            ),
        ),
    ]
