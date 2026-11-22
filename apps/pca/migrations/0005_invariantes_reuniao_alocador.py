from django.db import migrations, models
from django.db.models import Q


def semear_alocador(apps, schema_editor):
    ProcessoAlocador = apps.get_model("pca", "ProcessoAlocador")
    ProcessoAlocador.objects.get_or_create(chave=1)


class Migration(migrations.Migration):
    dependencies = [
        ("pca", "0004_grupos_editor_visualizador"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="reuniao",
            constraint=models.UniqueConstraint(
                fields=("data",),
                name="pca_reuniao_data_unica",
            ),
        ),
        migrations.AddConstraint(
            model_name="reuniao",
            constraint=models.UniqueConstraint(
                condition=Q(situacao="aberta"),
                fields=("situacao",),
                name="pca_reuniao_aberta_unica",
            ),
        ),
        migrations.CreateModel(
            name="ProcessoAlocador",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "chave",
                    models.PositiveSmallIntegerField(
                        default=1,
                        editable=False,
                        unique=True,
                        verbose_name="chave do alocador",
                    ),
                ),
            ],
            options={
                "verbose_name": "alocador de processo",
                "verbose_name_plural": "alocadores de processo",
            },
        ),
        migrations.RunPython(semear_alocador, migrations.RunPython.noop),
    ]
