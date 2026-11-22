# Hand-authored (Fase 17) — padrão "nullable → backfill →
# finalização" já usado na Fase 5 e em 0007..0009. Duas colunas novas
# (`estado`/`situacao`) nascem nullable com AddField, o RunPython
# `preencher_estado_situacao` calcula o valor exato de cada um dos 154
# processos reais via `apps.pca.regras_situacao.situacao_inicial` (módulo
# puro, sem `django.db.models`, seguro para importar de dentro de uma
# migração congelada — mesmo motivo de `apps/pca/importacao/parsers.py`) e
# grava com `.update()` do QuerySet BASE (nunca o manager `ManagerAuditado`,
# que bloqueia `.update()` — Pitfall 5), e o AlterField final fecha para
# NOT NULL.
#
# Mapeamento do backfill —
#   status="cancelado"                    -> estado="cancelado" (situação
#                                              recalculada pelos dados, mesma
#                                              fórmula que os demais);
#   status in ("concluido", "vigente")    -> estado="ativo", situacao=
#                                              "concluido" (via
#                                              situacao_por_eventos: tipo
#                                              vigente OU assinatura
#                                              preenchida cobrem os 2 casos
#                                              reais medidos em 28/08/2026);
#   status="em_tramitacao"                -> estado="ativo",
#                                              situacao="em_tramitacao";
#   status="nao_iniciado"                 -> estado="ativo", situacao=
#                                              "atrasado"/"no_prazo" conforme
#                                              prazo_entrega vs. hoje ("no_
#                                              prazo" por padrão quando não
#                                              há prazo_entrega).
#
# Este backfill é dado inicial, não uma mudança auditável de negócio —
# ao contrário de 0020/0022, NÃO grava `HistoricalProcesso` nem
# `Acompanhamento` novo: é a fotografia do estado real de cada processo no
# momento em que o novo schema nasce, não uma transição "acontecendo agora".
# A trilha `HistoricalProcesso` de cada processo permanece intacta.

from django.db import DEFAULT_DB_ALIAS, migrations, models
from django.utils import timezone

from apps.pca.regras_situacao import situacao_inicial


def preencher_estado_situacao(apps, schema_editor):
    Processo = apps.get_model("pca", "Processo")
    db = (
        schema_editor.connection.alias
        if schema_editor is not None
        else DEFAULT_DB_ALIAS
    )
    hoje = timezone.localdate()

    processos = (
        models.QuerySet(model=Processo, using=db)
        .select_related("tipo")
        .order_by("pk")
    )

    for processo in processos:
        estado = "cancelado" if processo.status == "cancelado" else "ativo"
        situacao = situacao_inicial(
            tipo_nome_normalizado=processo.tipo.nome_normalizado,
            data_assinatura_contrato=processo.data_assinatura_contrato,
            data_recebimento_gelic=processo.data_recebimento_gelic,
            prazo_entrega=processo.prazo_entrega,
            hoje=hoje,
        )
        models.QuerySet(model=Processo, using=db).filter(pk=processo.pk).update(
            estado=estado, situacao=situacao,
        )


ESTADO_CHOICES = [("ativo", "Ativo"), ("cancelado", "Cancelado")]
SITUACAO_CHOICES = [
    ("no_prazo", "No prazo"),
    ("atrasado", "Atrasado"),
    ("em_tramitacao", "Em tramitação"),
    ("concluido", "Concluído"),
]


class Migration(migrations.Migration):

    dependencies = [
        ('pca', '0022_correcao_retroativa_a_renovar'),
    ]

    operations = [
        # (1) AddField nullable — 4 operações (processo + historicalprocesso).
        migrations.AddField(
            model_name='processo',
            name='estado',
            field=models.CharField(
                choices=ESTADO_CHOICES, default='ativo', max_length=15,
                null=True, blank=True, verbose_name='estado',
            ),
        ),
        migrations.AddField(
            model_name='processo',
            name='situacao',
            field=models.CharField(
                choices=SITUACAO_CHOICES, default='no_prazo', max_length=20,
                null=True, blank=True, verbose_name='situação',
            ),
        ),
        migrations.AddField(
            model_name='historicalprocesso',
            name='estado',
            field=models.CharField(
                choices=ESTADO_CHOICES, default='ativo', max_length=15,
                null=True, blank=True, verbose_name='estado',
            ),
        ),
        migrations.AddField(
            model_name='historicalprocesso',
            name='situacao',
            field=models.CharField(
                choices=SITUACAO_CHOICES, default='no_prazo', max_length=20,
                null=True, blank=True, verbose_name='situação',
            ),
        ),

        # (2) Backfill dos 154 processos reais — não reversível de
        # forma unívoca (mesma decisão de 0015/0020/0022): reverse é noop, o
        # AddField reverso já apaga as colunas.
        migrations.RunPython(
            preencher_estado_situacao, migrations.RunPython.noop
        ),

        # (3) Finalização NOT NULL — 4 AlterField, mesmo default.
        migrations.AlterField(
            model_name='processo',
            name='estado',
            field=models.CharField(
                choices=ESTADO_CHOICES, default='ativo', max_length=15,
                verbose_name='estado',
            ),
        ),
        migrations.AlterField(
            model_name='processo',
            name='situacao',
            field=models.CharField(
                choices=SITUACAO_CHOICES, default='no_prazo', max_length=20,
                verbose_name='situação',
            ),
        ),
        migrations.AlterField(
            model_name='historicalprocesso',
            name='estado',
            field=models.CharField(
                choices=ESTADO_CHOICES, default='ativo', max_length=15,
                verbose_name='estado',
            ),
        ),
        migrations.AlterField(
            model_name='historicalprocesso',
            name='situacao',
            field=models.CharField(
                choices=SITUACAO_CHOICES, default='no_prazo', max_length=20,
                verbose_name='situação',
            ),
        ),
    ]
