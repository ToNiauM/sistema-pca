# (documento interno de desenho, V-1/V-5) — escrita à mão porque o `compose.
# override.yml` de dev monta a árvore em `/app` SOMENTE-LEITURA
# (`makemigrations` roda numa cópia temporária dentro do container; este
# arquivo é o conteúdo gerado lá, copiado byte a byte, com o `RunPython`
# acrescentado à mão no MESMO molde de `0004_grupos_editor_visualizador.py`/
# `0016_permissao_editar_pca_sem_kanban.py`/`0028_fluxo_caixa_simulacao.py`.
#
# Tudo aditivo: `AlterModelOptions` só acrescenta a 4ª permissão,
# `CreateModel`/`CreateModel` (histórico) sem nenhum `DeleteModel`/
# `RemoveField` destrutivo; reverso é NOOP (grupo/permissão nunca são
# apagados no rollback, mesma postura de `0004`/`0016`/`0028`). NUNCA
# aplicada ao banco real por esta quick — só a suíte de teste (banco
# efêmero em `tempfile`) a aplica.
import django.db.models.deletion
import simple_history.models
from django.apps import apps as django_apps
from django.conf import settings
from django.contrib.auth.management import create_permissions
from django.db import migrations, models


def criar_permissao_e_grupo_demandante(apps, schema_editor):
    """`instruir_contratacao` (Meta.permissions de `Processo`) + grupo
    `demandante`, criado VAZIO (mesma postura do grupo
    `dirigentes`): nenhuma associação automática de usuário — só o
    superusuário atribui usuários/grupos pelo Admin."""
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    # Mesmo motivo de `0004`/`0016`/`0028`: o `Apps` histórico da migration
    # não tem `models_module`; o helper do Django precisa do AppConfig real.
    create_permissions(django_apps.get_app_config("pca"), verbosity=0)
    grupo_demandante, _ = Group.objects.get_or_create(name="demandante")
    permissao = Permission.objects.get(
        codename="instruir_contratacao", content_type__app_label="pca"
    )
    grupo_demandante.permissions.add(permissao)


def preservar_permissao_e_grupo(apps, schema_editor):
    # Apagar grupo/permissão no rollback poderia destruir atribuições reais
    # de usuários (mesma postura de `0004`/`0016`/`0028`) — NOOP deliberado.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("pca", "0033_situacao_manual"),
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
                    (
                        "instruir_contratacao",
                        "Pode vincular nº SEI e editar a ficha da "
                        "contratação (grupo demandante)",
                    ),
                ],
                "verbose_name": "processo",
                "verbose_name_plural": "processos",
            },
        ),
        migrations.CreateModel(
            name="FichaContratacao",
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
                    "versao",
                    models.PositiveIntegerField(default=1, verbose_name="versão"),
                ),
                ("dados", models.JSONField(default=dict, verbose_name="dados")),
                (
                    "atualizado_em",
                    models.DateTimeField(auto_now=True, verbose_name="atualizado em"),
                ),
                (
                    "atualizado_por",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="fichas_contratacao_atualizadas",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="atualizado por",
                    ),
                ),
                (
                    "processo",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ficha_contratacao",
                        to="pca.processo",
                        verbose_name="processo",
                    ),
                ),
            ],
            options={
                "verbose_name": "ficha da contratação",
                "verbose_name_plural": "fichas da contratação",
            },
        ),
        migrations.CreateModel(
            name="HistoricalFichaContratacao",
            fields=[
                (
                    "id",
                    models.BigIntegerField(
                        auto_created=True, blank=True, db_index=True, verbose_name="ID"
                    ),
                ),
                (
                    "versao",
                    models.PositiveIntegerField(default=1, verbose_name="versão"),
                ),
                ("dados", models.JSONField(default=dict, verbose_name="dados")),
                (
                    "atualizado_em",
                    models.DateTimeField(
                        blank=True, editable=False, verbose_name="atualizado em"
                    ),
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
                    "atualizado_por",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="atualizado por",
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
                (
                    "processo",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="pca.processo",
                        verbose_name="processo",
                    ),
                ),
            ],
            options={
                "verbose_name": "historical ficha da contratação",
                "verbose_name_plural": "historical fichas da contratação",
                "ordering": ("-history_date", "-history_id"),
                "get_latest_by": ("history_date", "history_id"),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.RunPython(
            criar_permissao_e_grupo_demandante,
            preservar_permissao_e_grupo,
        ),
    ]
