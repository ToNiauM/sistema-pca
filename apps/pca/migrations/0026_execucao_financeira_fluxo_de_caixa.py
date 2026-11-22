# Gerada por `python manage.py makemigrations pca` (Django 5.2.16) e
# renomeada de `0026_historicalprocesso_regime_execucao_and_more.py` para um
# nome descritivo (Fase 36, spec §2.1/§2.2) —
# `dependencies` mantido intacto, conteúdo gerado 100% pelo Django (nunca
# escrito à mão: os campos automáticos de `simple_history.HistoricalRecords`
# mudam entre versões, ver `read_first` do plano).
import django.db.models.deletion
import simple_history.models
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pca', '0025_acompanhamento_transicao_manual'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='historicalprocesso',
            name='regime_execucao',
            field=models.CharField(blank=True, choices=[('continuado', 'Continuado'), ('unico', 'Execução única')], max_length=10, null=True, verbose_name='Regime de execução'),
        ),
        migrations.AddField(
            model_name='historicalprocesso',
            name='renovacao_prevista',
            field=models.BooleanField(default=True, verbose_name='Renovação prevista'),
        ),
        migrations.AddField(
            model_name='historicalprocesso',
            name='valor_mensal',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True, verbose_name='Valor mensal (R$)'),
        ),
        migrations.AddField(
            model_name='processo',
            name='regime_execucao',
            field=models.CharField(blank=True, choices=[('continuado', 'Continuado'), ('unico', 'Execução única')], max_length=10, null=True, verbose_name='Regime de execução'),
        ),
        migrations.AddField(
            model_name='processo',
            name='renovacao_prevista',
            field=models.BooleanField(default=True, verbose_name='Renovação prevista'),
        ),
        migrations.AddField(
            model_name='processo',
            name='valor_mensal',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True, verbose_name='Valor mensal (R$)'),
        ),
        migrations.CreateModel(
            name='HistoricalEventoFinanceiro',
            fields=[
                ('id', models.BigIntegerField(auto_created=True, blank=True, db_index=True, verbose_name='ID')),
                ('data', models.DateField(blank=True, null=True, verbose_name='data')),
                ('tipo', models.CharField(choices=[('contrato', 'Contrato'), ('aditivo', 'Aditivo'), ('apostilamento', 'Apostilamento'), ('manual', 'Manual')], max_length=15, verbose_name='tipo')),
                ('natureza', models.CharField(blank=True, choices=[('inicial', 'Inicial'), ('reajuste', 'Reajuste'), ('repactuacao', 'Repactuação'), ('acrescimo', 'Acréscimo'), ('supressao', 'Supressão'), ('prorrogacao', 'Prorrogação')], max_length=15, null=True, verbose_name='natureza')),
                ('valor', models.DecimalField(decimal_places=2, max_digits=14, verbose_name='valor (R$)')),
                ('valor_mensal', models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True, verbose_name='valor mensal (R$)')),
                ('periodicidade', models.CharField(blank=True, choices=[('mensal', 'Mensal'), ('anual', 'Anual'), ('global', 'Global')], max_length=10, null=True, verbose_name='periodicidade')),
                ('protocolo_sei', models.CharField(blank=True, max_length=20, null=True, verbose_name='protocolo SEI')),
                ('origem', models.CharField(choices=[('robo', 'Robô SEI'), ('manual', 'Manual')], max_length=10, verbose_name='origem')),
                ('observacao', models.TextField(blank=True, default='', verbose_name='observação')),
                ('history_id', models.AutoField(primary_key=True, serialize=False)),
                ('history_date', models.DateTimeField(db_index=True)),
                ('history_change_reason', models.CharField(max_length=100, null=True)),
                ('history_type', models.CharField(choices=[('+', 'Created'), ('~', 'Changed'), ('-', 'Deleted')], max_length=1)),
                ('history_user', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('processo', models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to='pca.processo')),
            ],
            options={
                'verbose_name': 'historical evento financeiro',
                'verbose_name_plural': 'historical eventos financeiros',
                'ordering': ('-history_date', '-history_id'),
                'get_latest_by': ('history_date', 'history_id'),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.CreateModel(
            name='EventoFinanceiro',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('data', models.DateField(blank=True, null=True, verbose_name='data')),
                ('tipo', models.CharField(choices=[('contrato', 'Contrato'), ('aditivo', 'Aditivo'), ('apostilamento', 'Apostilamento'), ('manual', 'Manual')], max_length=15, verbose_name='tipo')),
                ('natureza', models.CharField(blank=True, choices=[('inicial', 'Inicial'), ('reajuste', 'Reajuste'), ('repactuacao', 'Repactuação'), ('acrescimo', 'Acréscimo'), ('supressao', 'Supressão'), ('prorrogacao', 'Prorrogação')], max_length=15, null=True, verbose_name='natureza')),
                ('valor', models.DecimalField(decimal_places=2, max_digits=14, verbose_name='valor (R$)')),
                ('valor_mensal', models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True, verbose_name='valor mensal (R$)')),
                ('periodicidade', models.CharField(blank=True, choices=[('mensal', 'Mensal'), ('anual', 'Anual'), ('global', 'Global')], max_length=10, null=True, verbose_name='periodicidade')),
                ('protocolo_sei', models.CharField(blank=True, max_length=20, null=True, verbose_name='protocolo SEI')),
                ('origem', models.CharField(choices=[('robo', 'Robô SEI'), ('manual', 'Manual')], max_length=10, verbose_name='origem')),
                ('observacao', models.TextField(blank=True, default='', verbose_name='observação')),
                ('processo', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='eventos_financeiros', to='pca.processo')),
            ],
            options={
                'verbose_name': 'evento financeiro',
                'verbose_name_plural': 'eventos financeiros',
                'ordering': ['data', 'id'],
                'constraints': [models.UniqueConstraint(condition=models.Q(('protocolo_sei__isnull', False)), fields=('processo', 'protocolo_sei'), name='pca_eventofinanceiro_processo_protocolo_unico')],
            },
        ),
    ]
