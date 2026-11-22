import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("pca", "0009_exercicio_obrigatorio"),
        ("catalogo", "0002_exercicio"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="RascunhoVirada",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ano_destino", models.PositiveSmallIntegerField(verbose_name="ano de destino")),
                ("criado_em", models.DateTimeField(auto_now_add=True, verbose_name="criado em")),
                ("atualizado_em", models.DateTimeField(auto_now=True, verbose_name="atualizado em")),
                ("confirmado_em", models.DateTimeField(blank=True, null=True, verbose_name="confirmado em")),
                ("confirmado_por", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="rascunhos_virada_confirmados", to=settings.AUTH_USER_MODEL, verbose_name="confirmado por")),
                ("criado_por", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="rascunhos_virada_criados", to=settings.AUTH_USER_MODEL, verbose_name="criado por")),
                ("exercicio_origem", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="rascunhos_virada_origem", to="catalogo.exercicio", verbose_name="exercício de origem")),
            ],
            options={"verbose_name": "rascunho de virada", "verbose_name_plural": "rascunhos de virada"},
        ),
        migrations.CreateModel(
            name="RascunhoItemVirada",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ordem", models.PositiveIntegerField(verbose_name="ordem")),
                ("selecionado", models.BooleanField(default=False, verbose_name="selecionado")),
                ("valor_estimado_editado", models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True, verbose_name="valor estimado revisado")),
                ("mes_previsto_editado", models.PositiveSmallIntegerField(blank=True, null=True, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(12)], verbose_name="mês previsto revisado")),
                ("processo_origem", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="itens_rascunho_virada", to="pca.processo", verbose_name="processo de origem")),
                ("rascunho", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="itens", to="pca.rascunhovirada", verbose_name="rascunho")),
            ],
            options={"ordering": ["ordem", "processo_origem_id"], "verbose_name": "item do rascunho de virada", "verbose_name_plural": "itens do rascunho de virada"},
        ),
        migrations.AddConstraint(
            model_name="rascunhovirada",
            constraint=models.UniqueConstraint(condition=models.Q(("confirmado_em__isnull", True)), fields=("exercicio_origem", "ano_destino"), name="pca_virada_pendente_origem_destino_unica"),
        ),
        migrations.AddConstraint(
            model_name="rascunhoitemvirada",
            constraint=models.UniqueConstraint(fields=("rascunho", "processo_origem"), name="pca_virada_item_origem_unico"),
        ),
        migrations.AddConstraint(
            model_name="rascunhoitemvirada",
            constraint=models.UniqueConstraint(fields=("rascunho", "ordem"), name="pca_virada_item_ordem_unica"),
        ),
    ]
