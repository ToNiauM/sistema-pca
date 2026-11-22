from django.db import migrations


class Migration(migrations.Migration):
    """Em PostgreSQL a extensão `unaccent` já está aplicada no banco
    existente (esta migração já rodou lá antes da troca de backend). Em
    SQLite não existe extensão equivalente — a busca sem acento vem de
    `core.db.Unaccent`, uma UDF Python registrada em toda conexão nova
    (`core/apps.py`). Migração vazia, mantida só pela dependência de
    histórico de outras migrações."""

    dependencies = [
        ("pca", "0001_initial"),
    ]

    operations = []
