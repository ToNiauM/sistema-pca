# Hand-authored (Fase 17) — gap-closure do GAP 1 (BLOCKER) do
# `AddField` simples e totalmente reversível, sem
# `RunPython` — o próprio `default=False` estático É o backfill correto.
#
# Por que nenhum `RunPython` é necessário: nenhum `Acompanhamento` gravado
# até hoje — nem os 381 registros importados de `Modelo_de_Controle_.xlsx`
# (`importacao/executor.py` instancia `Acompanhamento` direto, fora de
# `registrar_acompanhamento`), nem os automáticos de `aplicar_regras_
# automaticas`/`alterar_estado` — é uma "transição manual de situação" por
# definição: o campo só nasce `True` a partir desta migração em diante,
# quando `registrar_acompanhamento` é chamado com `situacao_novo` explícito
# por uma via NÃO-automática (o caso real de `confirmar_transicao_view`).
#
# Ressalva documentada (aceita, ver objective -02
# do threat_model): qualquer sobreposição manual histórica registrada ANTES
# desta migração perde a proteção retroativa da guarda de `aplicar_regras_
# automaticas` (o campo novo nasce `False` para ela, indistinguível de um
# fato reafirmado). Não é uma perda de dado — `HistoricalRecords` preserva
# tudo — é uma limitação de alcance temporal da correção, auditável
# comparando `referencia_data`/`tipo_evento` de cada `Acompanhamento` antigo.
#
# O campo espelhado em `historicalacompanhamento` nasce automaticamente
# porque `HistoricalRecords()` reflete o model `Acompanhamento` — dois
# `AddField` abaixo, nenhuma outra alteração (mesmo padrão de 0019 acima).

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
