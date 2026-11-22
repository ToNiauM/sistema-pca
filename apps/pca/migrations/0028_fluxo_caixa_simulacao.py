# Fase 37 (documento interno de desenho §8) — escrita à mão porque o `compose.override.
# yml` de dev monta a árvore em `/app` SOMENTE-LEITURA (`makemigrations`
# roda no container, mas não consegue gravar o arquivo; conteúdo conferido
# contra `manage.py makemigrations pca --check` dentro do container, mesmo
# padrão descrito em convenções do projeto). Conteúdo estrutural (`AddField`/
# `CreateModel`) gerado a partir do estado real de `apps/pca/models.py`
# (mesma forma que o Django produziria); só o `RunPython` é lógica nova,
# no molde EXATO de `0004_grupos_editor_visualizador.py`/
# `0016_permissao_editar_pca_sem_kanban.py`.
#
# Tudo aditivo (do registro de ameaças do plano): `AddField`
# com `default=""`, `CreateModel`, e um `RunPython` que só usa
# `get_or_create`/`.add()` — nenhum `DeleteModel`/`RemoveField`/`update()`
# destrutivo; reverso é NOOP (grupo/permissão nunca são apagados no
# rollback, mesma postura de `0004`/`0016`).
import django.db.models.deletion
import simple_history.models
from django.conf import settings
from django.contrib.auth.management import create_permissions
from django.apps import apps as django_apps
from django.db import migrations, models


def criar_permissao_e_grupo_dirigentes(apps, schema_editor):
    """`ver_analises` (Meta.permissions de `Processo`) + grupo `dirigentes`,
    criado VAZIO: nenhuma associação automática de usuário — só o
    superusuário atribui usuários/grupos pelo Admin."""
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    # Mesmo motivo de `0004`/`0016`: o `Apps` histórico da migration não tem
    # `models_module`; o helper do Django precisa do AppConfig real.
    create_permissions(django_apps.get_app_config("pca"), verbosity=0)
    grupo_dirigentes, _ = Group.objects.get_or_create(name="dirigentes")
    permissao = Permission.objects.get(
        codename="ver_analises", content_type__app_label="pca"
    )
    grupo_dirigentes.permissions.add(permissao)


def preservar_permissao_e_grupo(apps, schema_editor):
    # Apagar grupo/permissão no rollback poderia destruir atribuições reais
    # de usuários (mesma postura de `0004`/`0016`) — NOOP deliberado.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("pca", "0027_heuristica_regime_execucao"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
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
                    (
                        "ver_analises",
                        "Pode ver as análises estratégicas (fluxo de "
                        "caixa, estatísticas e prazos)",
                    ),
                ],
                "verbose_name": "processo",
                "verbose_name_plural": "processos",
            },
        ),
        migrations.AddField(
            model_name="eventofinanceiro",
            name="instrumento",
            field=models.CharField(
                blank=True, default="", max_length=60, verbose_name="instrumento"
            ),
        ),
        migrations.AddField(
            model_name="historicaleventofinanceiro",
            name="instrumento",
            field=models.CharField(
                blank=True, default="", max_length=60, verbose_name="instrumento"
            ),
        ),
        migrations.CreateModel(
            name="HistoricalCenarioFluxo",
            fields=[
                (
                    "id",
                    models.BigIntegerField(
                        auto_created=True, blank=True, db_index=True, verbose_name="ID"
                    ),
                ),
                ("nome", models.CharField(max_length=100, verbose_name="nome")),
                (
                    "criado_em",
                    models.DateTimeField(
                        blank=True, editable=False, verbose_name="criado em"
                    ),
                ),
                (
                    "atualizado_em",
                    models.DateTimeField(
                        blank=True, editable=False, verbose_name="atualizado em"
                    ),
                ),
                ("ajustes", models.JSONField(default=dict, verbose_name="ajustes")),
                (
                    "descricao",
                    models.TextField(blank=True, default="", verbose_name="descrição"),
                ),
                ("history_id", models.AutoField(primary_key=True, serialize=False)),
                ("history_date", models.DateTimeField(db_index=True)),
                (
                    "history_change_reason",
                    models.CharField(max_length=100, null=True),
                ),
                (
                    "history_type",
                    models.CharField(
                        choices=[
                            ("+", "Created"),
                            ("~", "Changed"),
                            ("-", "Deleted"),
                        ],
                        max_length=1,
                    ),
                ),
                (
                    "autor",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="autor",
                    ),
                ),
                (
                    "exercicio",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="catalogo.exercicio",
                        verbose_name="exercício",
                    ),
                ),
                (
                    "history_user",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "historical cenário de fluxo de caixa",
                "verbose_name_plural": "historical cenários de fluxo de caixa",
                "ordering": ("-history_date", "-history_id"),
                "get_latest_by": ("history_date", "history_id"),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.CreateModel(
            name="CenarioFluxo",
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
                ("nome", models.CharField(max_length=100, verbose_name="nome")),
                (
                    "criado_em",
                    models.DateTimeField(auto_now_add=True, verbose_name="criado em"),
                ),
                (
                    "atualizado_em",
                    models.DateTimeField(auto_now=True, verbose_name="atualizado em"),
                ),
                ("ajustes", models.JSONField(default=dict, verbose_name="ajustes")),
                (
                    "descricao",
                    models.TextField(blank=True, default="", verbose_name="descrição"),
                ),
                (
                    "autor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="cenarios_fluxo",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="autor",
                    ),
                ),
                (
                    "exercicio",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="cenarios_fluxo",
                        to="catalogo.exercicio",
                        verbose_name="exercício",
                    ),
                ),
            ],
            options={
                "verbose_name": "cenário de fluxo de caixa",
                "verbose_name_plural": "cenários de fluxo de caixa",
                "ordering": ["-atualizado_em"],
            },
        ),
        migrations.AddConstraint(
            model_name="cenariofluxo",
            constraint=models.UniqueConstraint(
                fields=("exercicio", "nome"),
                name="pca_cenariofluxo_exercicio_nome_unico",
            ),
        ),
        migrations.RunPython(
            criar_permissao_e_grupo_dirigentes,
            preservar_permissao_e_grupo,
        ),
    ]
