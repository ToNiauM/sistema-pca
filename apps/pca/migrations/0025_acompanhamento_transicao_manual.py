# AddField simples e totalmente reversível, sem RunPython — o próprio
# default=False estático é o backfill correto: nenhum Acompanhamento
# gravado até hoje é uma "transição manual de situação" por definição; o
# campo só nasce True a partir desta migração, quando
# registrar_acompanhamento recebe situacao_novo explícito por uma via
# não-automática.
#
# Ressalva aceita: sobreposição manual histórica registrada antes desta
# migração perde a proteção retroativa da guarda de
# aplicar_regras_automaticas (o campo nasce False, indistinguível de um
# fato reafirmado); não é perda de dado, é limitação de alcance temporal,
# auditável comparando referencia_data/tipo_evento de cada Acompanhamento
# antigo.
#
# O campo espelhado em historicalacompanhamento nasce automaticamente
# porque HistoricalRecords() reflete o model Acompanhamento.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pca', '0024_remover_status_legado'),
    ]

    operations = [
        migrations.AddField(
            model_name='acompanhamento',
            name='transicao_manual',
            field=models.BooleanField(
                default=False, verbose_name='transição manual de situação'
            ),
        ),
        migrations.AddField(
            model_name='historicalacompanhamento',
            name='transicao_manual',
            field=models.BooleanField(
                default=False, verbose_name='transição manual de situação'
            ),
        ),
    ]
