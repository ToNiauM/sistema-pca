from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("catalogo", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Exercicio",
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
                ("ano", models.PositiveSmallIntegerField(unique=True, verbose_name="ano")),
                ("rotulo", models.CharField(max_length=100, verbose_name="rótulo")),
                (
                    "situacao",
                    models.CharField(
                        choices=[("aberto", "Aberto"), ("fechado", "Fechado")],
                        default="aberto",
                        max_length=10,
                        verbose_name="situação",
                    ),
                ),
            ],
            options={
                "verbose_name": "exercício",
                "verbose_name_plural": "exercícios",
                "ordering": ["-ano"],
            },
        ),
    ]
