from django.contrib.postgres.operations import UnaccentExtension
from django.db import migrations


class Migration(migrations.Migration):
    """Habilita a extensão `unaccent` do PostgreSQL, usada pelo lookup
    `__unaccent` (busca sem acento); requer superuser no banco."""

    dependencies = [
        ("pca", "0001_initial"),
    ]

    operations = [
        UnaccentExtension(),
    ]
