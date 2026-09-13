from django.contrib.auth.hashers import make_password
from django.db import migrations

EMAIL_SERVICO = "importador@pca.local"


def criar_usuario_servico(apps, schema_editor):
    """Cria o usuário de serviço do import: dono das linhas de histórico
    da linha de base, sem login possível. Idempotente; grava senha
    inutilizável direto no campo porque o modelo histórico não expõe
    set_unusable_password()."""

    Usuario = apps.get_model("core", "Usuario")
    Usuario.objects.get_or_create(
        email=EMAIL_SERVICO,
        defaults={
            "is_active": False,
            "is_staff": False,
            "is_superuser": False,
            "password": make_password(None),
        },
    )


def remover_usuario_servico(apps, schema_editor):
    Usuario = apps.get_model("core", "Usuario")
    Usuario.objects.filter(email=EMAIL_SERVICO).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_alter_usuario_managers"),
    ]

    operations = [
        migrations.RunPython(criar_usuario_servico, remover_usuario_servico),
    ]
