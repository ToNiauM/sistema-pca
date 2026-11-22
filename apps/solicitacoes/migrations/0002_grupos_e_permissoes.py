# Fase 43 — grupos `solicitante` e `diretoria` e as três permissões do
# app. Mesmo molde de `apps/pca/migrations/0004_grupos_editor_visualizador.py` e
# `0034_instruir_contratacao_ficha_contratacao.py`: `create_permissions` explícito (o
# `post_migrate` ainda não rodou), `get_or_create` nos grupos, reverso NOOP (apagar grupo
# no rollback destruiria atribuições reais de usuários).
#
#   solicitante -> solicitacoes.solicitar          (a unidade pede nos seus itens)
#   editor      -> solicitacoes.decidir_equipe     (equipe do PCA: prazo e mês)
#   diretoria   -> solicitacoes.decidir_diretoria  (inclusão, cancelamento, valor, objeto)
#
# O grupo `diretoria` nasce VAZIO: a delegação é o administrador pondo a pessoa no grupo.
from django.apps import apps as django_apps
from django.contrib.auth.management import create_permissions
from django.db import migrations


def criar_grupos_e_permissoes(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    create_permissions(django_apps.get_app_config("solicitacoes"), verbosity=0)

    def permissao(codename):
        return Permission.objects.get(codename=codename, content_type__app_label="solicitacoes")

    solicitante, _ = Group.objects.get_or_create(name="solicitante")
    solicitante.permissions.add(permissao("solicitar"))
    diretoria, _ = Group.objects.get_or_create(name="diretoria")
    diretoria.permissions.add(permissao("decidir_diretoria"))
    editor, _ = Group.objects.get_or_create(name="editor")
    editor.permissions.add(permissao("decidir_equipe"))


def preservar_grupos_e_permissoes(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("solicitacoes", "0001_modelos_iniciais"),
    ]

    operations = [
        migrations.RunPython(criar_grupos_e_permissoes, preservar_grupos_e_permissoes),
    ]
