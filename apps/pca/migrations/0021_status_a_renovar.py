# Migração de catálogo: "A renovar" deixa de ser flag derivada calculada na
# leitura e passa a ser status de primeira classe, com regra automática
# própria (R3). Funil passa de 5 para 6 valores: nao_iniciado /
# em_tramitacao / concluido / cancelado / vigente / a_renovar.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pca', '0020_correcao_retroativa_status_automatico'),
    ]

    operations = [
        migrations.AlterField(
            model_name='historicalprocesso',
            name='status',
            field=models.CharField(choices=[('concluido', 'Concluído'), ('nao_iniciado', 'Não iniciado'), ('em_tramitacao', 'Em tramitação'), ('vigente', 'Vigente'), ('a_renovar', 'A renovar'), ('cancelado', 'Cancelado')], max_length=20, verbose_name='status'),
        ),
        migrations.AlterField(
            model_name='processo',
            name='status',
            field=models.CharField(choices=[('concluido', 'Concluído'), ('nao_iniciado', 'Não iniciado'), ('em_tramitacao', 'Em tramitação'), ('vigente', 'Vigente'), ('a_renovar', 'A renovar'), ('cancelado', 'Cancelado')], max_length=20, verbose_name='status'),
        ),
    ]
