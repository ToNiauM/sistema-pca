# Escrita à mão porque o `compose.override.yml` de dev
# monta a árvore em `/app` SOMENTE-LEITURA (`makemigrations` roda no
# container, mas não consegue gravar o arquivo; conteúdo conferido contra
# `manage.py makemigrations pca --check --dry-run` dentro do container),
# mesmo motivo documentado em `0028_fluxo_caixa_simulacao.py`. Conteúdo
# estrutural gerado a partir do estado real de `apps/pca/models.py` (mesma
# forma que o Django produziria).
#
# Aditivo: dois `AddField` com `blank=True`/`default=""` (CharField) e
# `blank=True, null=True` (DateTimeField) em `historicalprocesso` e
# `processo` — sem `RunPython`, sem `SeparateDatabaseAndState`.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pca", "0028_fluxo_caixa_simulacao"),
    ]

    operations = [
        migrations.AddField(
            model_name="historicalprocesso",
            name="unidade_sei_atual",
            field=models.CharField(blank=True, default="", max_length=80, verbose_name="Unidade atual (SEI)"),
        ),
        migrations.AddField(
            model_name="historicalprocesso",
            name="unidade_sei_atual_desde",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Na unidade desde"),
        ),
        migrations.AddField(
            model_name="processo",
            name="unidade_sei_atual",
            field=models.CharField(blank=True, default="", max_length=80, verbose_name="Unidade atual (SEI)"),
        ),
        migrations.AddField(
            model_name="processo",
            name="unidade_sei_atual_desde",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Na unidade desde"),
        ),
    ]
