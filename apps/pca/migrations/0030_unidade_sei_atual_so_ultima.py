# Escrita à mão porque o `compose.override.yml` de dev
# monta a árvore em `/app` SOMENTE-LEITURA (mesmo motivo documentado em
# `0029_unidade_sei_atual.py`/`0028_fluxo_caixa_simulacao.py`).
#
# Correção de dado: `unidade_sei_atual` deixou de guardar a lista de
# unidades "abertas" juntas por `" / "` (regra antiga de
# `apps.pca.sei.regras.unidade_atual`, revogada por esta quick) e passou a
# guardar só a unidade do recebimento mais recente. Nos valores já
# gravados no formato antigo "A / B / C", o primeiro segmento é o de
# recebimento mais recente (a regra antiga ordenava mais recente primeiro
# — `abertas.sort(..., reverse=True)`), então basta manter o primeiro
# segmento. A próxima `sei_sincronizar` recalcula tudo pela regra nova de
# qualquer forma; esta migração só evita exibir "A / B" para quem não
# rodar o robô antes de olhar a tabela. Não toca `HistoricalProcesso` — a
# trilha de auditoria já registrada com o valor antigo permanece como
# estava (correção estrutural de exibição, não fato de negócio a
# re-narrar).
from django.db import migrations, models


def reduzir_ao_primeiro_segmento(apps, schema_editor):
    Processo = apps.get_model("pca", "Processo")
    db = schema_editor.connection.alias

    processos = models.QuerySet(model=Processo, using=db).filter(
        unidade_sei_atual__contains=" / "
    )
    for processo in processos:
        primeiro = processo.unidade_sei_atual.split(" / ")[0].strip()
        models.QuerySet(model=Processo, using=db).filter(pk=processo.pk).update(
            unidade_sei_atual=primeiro
        )


class Migration(migrations.Migration):

    dependencies = [
        ("pca", "0029_unidade_sei_atual"),
    ]

    operations = [
        migrations.RunPython(reduzir_ao_primeiro_segmento, migrations.RunPython.noop),
    ]
