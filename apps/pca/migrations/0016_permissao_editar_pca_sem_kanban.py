# Corrige o texto da permissão editar_pca.

from django.db import migrations


def corrigir_texto_permissao_editar_pca(apps, schema_editor):
    """Atualiza só o rótulo de exibição da permissão editar_pca; grupo,
    permissão e atribuições existentes sobrevivem intactos."""
    Permission = apps.get_model("auth", "Permission")
    Permission.objects.filter(
        codename="editar_pca", content_type__app_label="pca"
    ).update(name="Pode editar processos e registrar acompanhamento")


def reverter_texto_permissao_editar_pca(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    Permission.objects.filter(
        codename="editar_pca", content_type__app_label="pca"
    ).update(
        name="Pode editar processos, mover kanban e registrar acompanhamento"
    )


class Migration(migrations.Migration):

    dependencies = [
        ("pca", "0015_migrar_justificativa_e_remover_campos_obsoletos"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="processo",
            options={
                "ordering": ["exercicio", "item_pca"],
                "permissions": [
                    (
                        "editar_pca",
                        "Pode editar processos e registrar acompanhamento",
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
        migrations.RunPython(
            corrigir_texto_permissao_editar_pca,
            reverter_texto_permissao_editar_pca,
        ),
    ]
