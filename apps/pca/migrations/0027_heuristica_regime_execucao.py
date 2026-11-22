# Fase 36 (spec §2.1) — migração de dados
# vazia + `RunPython` (mesmo precedente de `0023_estado_situacao_tres_eixos.
# py`: `situacao_inicial` importada de `regras_situacao.py`, módulo puro,
# seguro para dentro de uma migração congelada). Preenche `regime_execucao`
# só quando ainda está `null` — nunca sobrescreve um valor já gravado à mão
# ou pelo robô; itens sem vigência (`regime_presumido_migracao` devolve
# `None`) permanecem `null`, para a tela mostrar "regime presumido" via a
# heurística de runtime (`regime_presumido_projecao`, limiar 12, Plano
# 36-02 — NUNCA esta aqui, limiar 11). `reverse_code = noop` (nunca
# migração reversa que apaga dado).
from django.db import DEFAULT_DB_ALIAS, migrations, models

from apps.pca.regras_situacao import regime_presumido_migracao


def preencher_regime_execucao(apps, schema_editor):
    Processo = apps.get_model("pca", "Processo")
    db = (
        schema_editor.connection.alias
        if schema_editor is not None
        else DEFAULT_DB_ALIAS
    )

    processos = (
        models.QuerySet(model=Processo, using=db)
        .filter(regime_execucao__isnull=True)
        .only("id", "vigencia_inicio", "vigencia_fim")
        .order_by("pk")
    )

    for processo in processos:
        regime = regime_presumido_migracao(
            processo.vigencia_inicio, processo.vigencia_fim
        )
        if regime is not None:
            models.QuerySet(model=Processo, using=db).filter(pk=processo.pk).update(
                regime_execucao=regime,
            )


class Migration(migrations.Migration):

    dependencies = [
        ('pca', '0026_execucao_financeira_fluxo_de_caixa'),
    ]

    operations = [
        migrations.RunPython(
            preencher_regime_execucao, reverse_code=migrations.RunPython.noop,
        ),
    ]
