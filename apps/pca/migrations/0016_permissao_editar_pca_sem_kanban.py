# Generated for Fase 14.1 — corrige o texto da permissão editar_pca.

from django.db import migrations


def corrigir_texto_permissao_editar_pca(apps, schema_editor):
    """O kanban deixou de existir como ferramenta; o rótulo já
    persistido em ``auth_permission`` precisa parar de citar "mover kanban".
    Só o campo ``name`` (rótulo de exibição) é tocado, filtrado por
    ``codename``/``content_type``; grupo, permissão e atribuições existentes
    (`Group.permissions`) sobrevivem intactos — mesma postura não destrutiva
    de `0004_grupos_editor_visualizador.py`."""
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
