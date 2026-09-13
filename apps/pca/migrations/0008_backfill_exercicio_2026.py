from django.db import DEFAULT_DB_ALIAS, migrations, models


def backfill_exercicio_2026(apps, schema_editor):
    Exercicio = apps.get_model("catalogo", "Exercicio")
    Processo = apps.get_model("pca", "Processo")
    HistoricalProcesso = apps.get_model("pca", "HistoricalProcesso")
    Reuniao = apps.get_model("pca", "Reuniao")
    db = schema_editor.connection.alias if schema_editor is not None else DEFAULT_DB_ALIAS

    exercicio, _ = Exercicio.objects.using(db).get_or_create(
        ano=2026,
        defaults={"rotulo": "PCA 2026", "situacao": "aberto"},
    )
    for model in (Processo, HistoricalProcesso, Reuniao):
        models.QuerySet(model=model, using=db).filter(
            exercicio__isnull=True
        ).update(exercicio_id=exercicio.pk)


class Migration(migrations.Migration):
    dependencies = [
        ("pca", "0007_exercicio_estrutura"),
    ]

    operations = [
        migrations.RunPython(backfill_exercicio_2026, migrations.RunPython.noop),
    ]
