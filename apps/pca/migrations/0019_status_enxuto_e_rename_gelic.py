# Hand-authored: RenameField + AlterField explícitos, sem depender do
# prompt interativo de `makemigrations`. Catálogo de status enxuto; funde
# `data_entrega_delic` com o extinto `data_recebimento_processo` em
# `data_recebimento_gelic`; renomeia `data_envio_delic` para
# `data_envio_gelic`; adiciona `TipoEvento.AUTOMATICO`.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pca', '0018_alter_historicalprocesso_status_and_more'),
    ]

    operations = [
        # (1) Status enxuto (5 valores) em processo e historicalprocesso.
        migrations.AlterField(
            model_name='historicalprocesso',
            name='status',
            field=models.CharField(choices=[('concluido', 'Concluído'), ('nao_iniciado', 'Não iniciado'), ('em_tramitacao', 'Em tramitação'), ('vigente', 'Vigente'), ('cancelado', 'Cancelado')], max_length=20, verbose_name='status'),
        ),
        migrations.AlterField(
            model_name='processo',
            name='status',
            field=models.CharField(choices=[('concluido', 'Concluído'), ('nao_iniciado', 'Não iniciado'), ('em_tramitacao', 'Em tramitação'), ('vigente', 'Vigente'), ('cancelado', 'Cancelado')], max_length=20, verbose_name='status'),
        ),

        # (2)+(3) Rename + verbose_name de data_envio_delic -> data_envio_gelic.
        migrations.RenameField(
            model_name='historicalprocesso',
            old_name='data_envio_delic',
            new_name='data_envio_gelic',
        ),
        migrations.RenameField(
            model_name='processo',
            old_name='data_envio_delic',
            new_name='data_envio_gelic',
        ),
        migrations.AlterField(
            model_name='historicalprocesso',
            name='data_envio_gelic',
            field=models.DateField(blank=True, null=True, verbose_name='Data envio ao Gelic'),
        ),
        migrations.AlterField(
            model_name='processo',
            name='data_envio_gelic',
            field=models.DateField(blank=True, null=True, verbose_name='Data envio ao Gelic'),
        ),

        # (4)+(5) Rename + verbose_name de data_entrega_delic ->
        # data_recebimento_gelic, dados preservados.
        migrations.RenameField(
            model_name='historicalprocesso',
            old_name='data_entrega_delic',
            new_name='data_recebimento_gelic',
        ),
        migrations.RenameField(
            model_name='processo',
            old_name='data_entrega_delic',
            new_name='data_recebimento_gelic',
        ),
        migrations.AlterField(
            model_name='historicalprocesso',
            name='data_recebimento_gelic',
            field=models.DateField(blank=True, null=True, verbose_name='Data de Recebimento do Processo no Gelic'),
        ),
        migrations.AlterField(
            model_name='processo',
            name='data_recebimento_gelic',
            field=models.DateField(blank=True, null=True, verbose_name='Data de Recebimento do Processo no Gelic'),
        ),

        # (6) data_recebimento_processo sai do schema — zero preenchimentos
        # medidos, sem conflito a resolver.
        migrations.RemoveField(
            model_name='historicalprocesso',
            name='data_recebimento_processo',
        ),
        migrations.RemoveField(
            model_name='processo',
            name='data_recebimento_processo',
        ),

        # (7) TipoEvento.AUTOMATICO em acompanhamento e historicalacompanhamento.
        migrations.AlterField(
            model_name='historicalacompanhamento',
            name='tipo_evento',
            field=models.CharField(choices=[('reuniao_acompanhamento', 'Reunião de acompanhamento'), ('gestao_riscos', 'Gestão de Riscos'), ('automatico', 'Automático')], max_length=30, verbose_name='tipo de evento'),
        ),
        migrations.AlterField(
            model_name='acompanhamento',
            name='tipo_evento',
            field=models.CharField(choices=[('reuniao_acompanhamento', 'Reunião de acompanhamento'), ('gestao_riscos', 'Gestão de Riscos'), ('automatico', 'Automático')], max_length=30, verbose_name='tipo de evento'),
        ),
    ]
