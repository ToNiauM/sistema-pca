# Hand-authored: mesmo padrão de
# 0020_correcao_retroativa_status_automatico.py — apps.get_model +
# models.QuerySet + snapshot manual de Historical*, nunca o manager "vivo".
#
# Correção retroativa de R3 sobre os processos hoje `vigente` cuja
# `vigencia_fim` cai dentro do ano do próprio exercício, nunca tocando
# `cancelado`, com trilha de auditoria assinada por `importador@pca.local`
# (USUARIO_PADRAO).

import hashlib

from django.db import DEFAULT_DB_ALIAS, migrations, models
from django.utils import timezone

USUARIO_PADRAO = "importador@pca.local"

# Mesmo rótulo de `apps.pca.services.MAPA_SITUACAO_POR_STATUS[Status.
# A_RENOVAR]`: ainda é um contrato vigente, só perto do fim.
SITUACAO_A_RENOVAR = "Contrato vigente"


def corrigir_a_renovar_retroativamente(apps, schema_editor):
    """Aplica R3 retroativamente sobre processos hoje `vigente` cuja
    `vigencia_fim` cai dentro do ano do próprio exercício, gravando o mesmo
    rastro de auditoria que a automação viva grava em edições novas.

    Filtro base `status="vigente"` já exclui `cancelado` por construção.
    `vigencia_fim.year == exercicio.ano` decide o alvo `a_renovar`. Depois de
    corrigido, o filtro base deixa de selecionar o processo — reaplicar a
    migração não duplica nada."""
    Processo = apps.get_model("pca", "Processo")
    HistoricalProcesso = apps.get_model("pca", "HistoricalProcesso")
    Acompanhamento = apps.get_model("pca", "Acompanhamento")
    HistoricalAcompanhamento = apps.get_model("pca", "HistoricalAcompanhamento")
    SituacaoNormalizada = apps.get_model("catalogo", "SituacaoNormalizada")
    Usuario = apps.get_model("core", "Usuario")
    db = (
        schema_editor.connection.alias
        if schema_editor is not None
        else DEFAULT_DB_ALIAS
    )

    # Busca preguiçosa: um banco sem nada a corrigir nunca toca a tabela de
    # usuários.
    _usuario_cache = []

    def _usuario_padrao():
        if not _usuario_cache:
            _usuario_cache.append(
                Usuario.objects.using(db).get(email=USUARIO_PADRAO)
            )
        return _usuario_cache[0]

    _situacao_cache = []

    def _situacao_a_renovar():
        if not _situacao_cache:
            _situacao_cache.append(
                SituacaoNormalizada.objects.using(db).get(nome=SITUACAO_A_RENOVAR)
            )
        return _situacao_cache[0]

    # Mesma técnica de 0015/0020: campos concretos lidos dinamicamente via
    # `attname`, para nunca desalinhar do modelo real.
    campos_snapshot_processo = [
        campo.attname
        for campo in Processo._meta.get_fields()
        if getattr(campo, "concrete", False) and not campo.many_to_many
    ]
    campos_snapshot_acompanhamento = [
        campo.attname
        for campo in Acompanhamento._meta.get_fields()
        if getattr(campo, "concrete", False) and not campo.many_to_many
    ]

    processos = (
        models.QuerySet(model=Processo, using=db)
        .filter(status="vigente", vigencia_fim__isnull=False)
        .select_related("exercicio")
        .order_by("pk")
    )

    for processo in processos:
        if processo.vigencia_fim.year != processo.exercicio.ano:
            continue

        agora = timezone.now()
        vigencia_fmt = processo.vigencia_fim.strftime("%d/%m/%Y")
        causa = (
            "Status atualizado automaticamente para A renovar — Vigência "
            f"encerra em {vigencia_fmt}, dentro do exercício "
            f"{processo.exercicio.ano}."
        )

        # `.filter().update()` do QuerySet base: o manager auditado da app
        # não existe no estado congelado da migração.
        models.QuerySet(model=Processo, using=db).filter(pk=processo.pk).update(
            status="a_renovar", atualizado_em=agora
        )

        snapshot_processo = {
            campo: getattr(processo, campo) for campo in campos_snapshot_processo
        }
        snapshot_processo["status"] = "a_renovar"
        snapshot_processo["atualizado_em"] = agora
        HistoricalProcesso.objects.using(db).create(
            **snapshot_processo,
            history_date=agora,
            history_type="~",
            history_change_reason="Correção retroativa 260828-01i — Q-14",
            history_user=_usuario_padrao(),
        )

        acompanhamento = Acompanhamento.objects.using(db).create(
            processo_id=processo.pk,
            referencia_data=timezone.localdate(),
            origem_hash=hashlib.sha256(
                f"retroativo-01i:{processo.pk}:a_renovar".encode()
            ).hexdigest(),
            evento="",
            tipo_evento="automatico",
            situacao_informada=causa,
            situacao_id=_situacao_a_renovar().pk,
            prazo_prometido=None,
            reuniao=None,
        )

        snapshot_acompanhamento = {
            campo: getattr(acompanhamento, campo)
            for campo in campos_snapshot_acompanhamento
        }
        HistoricalAcompanhamento.objects.using(db).create(
            **snapshot_acompanhamento,
            history_date=agora,
            history_type="+",
            history_change_reason="Correção retroativa 260828-01i — Q-14",
            history_user=_usuario_padrao(),
        )


class Migration(migrations.Migration):

    dependencies = [
        ('pca', '0021_status_a_renovar'),
        # A correção assina os snapshots com `importador@pca.local`, criado
        # por core.0003; a dependência explícita evita depender de ordem
        # alfabética entre apps.
        ('core', '0003_usuario_importacao'),
    ]

    operations = [
        # Correção de dado, não reversível de forma unívoca: não há como
        # distinguir depois um `Acompanhamento` automático real de um criado
        # por esta correção.
        migrations.RunPython(
            corrigir_a_renovar_retroativamente, migrations.RunPython.noop
        ),
    ]
