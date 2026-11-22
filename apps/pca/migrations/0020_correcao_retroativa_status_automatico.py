# Hand-authored (Fase 15) — mesmo padrão de
# 0015_migrar_justificativa_e_remover_campos_obsoletos.py: `apps.get_model` +
# `models.QuerySet` + snapshot manual de `Historical*`. Não chama
# `apps.pca.services.aplicar_regras_automaticas` (usa `Processo.objects`, o
# manager "vivo" que bloqueia `.update()` — Pitfall 5 — e models importados
# de `apps.pca.models`, incompatíveis com o estado congelado da migração).
#
# Correção retroativa de R1/R2 sobre
# os processos hoje inconsistentes, nunca tocando `cancelado`, com
# trilha de auditoria completa assinada por `importador@pca.local`
# (USUARIO_PADRAO, do import).

import hashlib

from django.db import DEFAULT_DB_ALIAS, migrations, models
from django.utils import timezone

USUARIO_PADRAO = "importador@pca.local"

# Rótulo de Status — mesmo texto de `Status.label`, usado no texto de
# causa gravado em `situacao_informada`.
STATUS_LABEL = {
    "em_tramitacao": "Em tramitação",
    "vigente": "Vigente",
    "concluido": "Concluído",
}

# Mesmos rótulos de `apps.pca.services.MAPA_SITUACAO_POR_STATUS`,
# usados para resolver a `SituacaoNormalizada` do novo `Acompanhamento`.
SITUACAO_POR_STATUS = {
    "em_tramitacao": "Em tramitação",
    "vigente": "Contrato vigente",
    "concluido": "Concluído",
}


def corrigir_status_retroativamente(apps, schema_editor):
    """Aplica R1/R2 retroativamente sobre processos hoje
    inconsistentes, gravando o mesmo rastro de auditoria que a automação viva
    (`aplicar_regras_automaticas`) grava em edições novas.

    Predicado (replicado com literais, nunca com o enum `Status`/`TipoEvento`
    — mesmo motivo que `importacao/parsers.py::STATUS_POR_ROTULO` já duplica
    os tokens manualmente):
    - Pula processo `cancelado` — automação nunca ressuscita cancelado.
    - R2 (prioridade): `data_assinatura_contrato` preenchida decide o alvo
      por `tipo.nome_normalizado` (`renovacao`/`vigente` -> `vigente`, senão
      `concluido`).
    - R1 (só se R2 não se aplicou): `status == nao_iniciado` e
      `data_recebimento_gelic` preenchida -> `em_tramitacao`.
    - Se o alvo calculado for igual ao status atual (ou nenhuma regra bateu),
      não faz nada — é o que garante a idempotência: rodar a migração de novo
      sobre um banco já corrigido não duplica `Acompanhamento` nem
      `HistoricalProcesso`.
    """
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

    # (revisão Fase 15) — busca preguiçosa: um banco sem nada a
    # corrigir nunca toca a tabela de usuários. Quando há correção a gravar,
    # a dependência explícita de `core.0003_usuario_importacao` (abaixo)
    # garante que `importador@pca.local` já existe.
    _usuario_cache = []

    def _usuario_padrao():
        if not _usuario_cache:
            _usuario_cache.append(
                Usuario.objects.using(db).get(email=USUARIO_PADRAO)
            )
        return _usuario_cache[0]

    # Mesma técnica de `campos_snapshot` de 0015: campos concretos lidos
    # dinamicamente (via `attname`, correto tanto para campo simples quanto
    # FK) para nunca desalinhar do modelo real.
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

    situacoes_cache = {}

    def _situacao(nome):
        if nome not in situacoes_cache:
            situacoes_cache[nome] = SituacaoNormalizada.objects.using(db).get(
                nome=nome
            )
        return situacoes_cache[nome]

    processos = (
        models.QuerySet(model=Processo, using=db)
        .exclude(status="cancelado")
        .select_related("tipo", "exercicio")
        .order_by("pk")
    )

    for processo in processos:
        alvo = None
        causa = None

        if processo.data_assinatura_contrato is not None:
            if processo.tipo.nome_normalizado in {"renovacao", "vigente"}:
                alvo = "vigente"
            else:
                alvo = "concluido"
            data_fmt = processo.data_assinatura_contrato.strftime("%d/%m/%Y")
            causa = (
                f"Status atualizado automaticamente para {STATUS_LABEL[alvo]} "
                f"— Data de assinatura do contrato preenchida ({data_fmt})."
            )
        elif (
            processo.status == "nao_iniciado"
            and processo.data_recebimento_gelic is not None
        ):
            alvo = "em_tramitacao"
            data_fmt = processo.data_recebimento_gelic.strftime("%d/%m/%Y")
            causa = (
                "Status atualizado automaticamente para Em tramitação — "
                f"Data de Recebimento no Gelic preenchida ({data_fmt})."
            )

        if alvo is None or alvo == processo.status:
            continue

        agora = timezone.now()

        # `.filter().update()` do `models.QuerySet` BASE (não o manager
        # `ManagerAuditado` da app, que não existe no estado congelado da
        # migração e bloquearia `.update()` por design — Pitfall 5).
        models.QuerySet(model=Processo, using=db).filter(pk=processo.pk).update(
            status=alvo, atualizado_em=agora
        )

        snapshot_processo = {
            campo: getattr(processo, campo) for campo in campos_snapshot_processo
        }
        snapshot_processo["status"] = alvo
        snapshot_processo["atualizado_em"] = agora
        HistoricalProcesso.objects.using(db).create(
            **snapshot_processo,
            history_date=agora,
            history_type="~",
            history_change_reason="Correção retroativa Fase 15 — ",
            history_user=_usuario_padrao(),
        )

        acompanhamento = Acompanhamento.objects.using(db).create(
            processo_id=processo.pk,
            referencia_data=timezone.localdate(),
            origem_hash=hashlib.sha256(
                f"retroativo-fase15:{processo.pk}:{alvo}".encode()
            ).hexdigest(),
            evento="",
            tipo_evento="automatico",
            situacao_informada=causa,
            situacao_id=_situacao(SITUACAO_POR_STATUS[alvo]).pk,
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
            history_change_reason="Correção retroativa Fase 15 — ",
            history_user=_usuario_padrao(),
        )


class Migration(migrations.Migration):

    dependencies = [
        ('pca', '0019_status_enxuto_e_rename_gelic'),
        # (revisão Fase 15) — a correção assina os snapshots com
        # `importador@pca.local`, criado por core.0003. Sem a dependência
        # explícita, a ordem "core antes de pca" num `migrate` de banco
        # zerado é acidente alfabético ("core" < "pca"), não contrato — a
        # dependência swappable-user de pca resolve só para core.0001.
        ('core', '0003_usuario_importacao'),
    ]

    operations = [
        # Correção de dado, não reversível de forma unívoca (não há como
        # distinguir depois um `Acompanhamento` automático "de verdade" de um
        # criado pela correção retroativa sem apagar histórico real) — mesma
        # decisão de `0015`.
        migrations.RunPython(
            corrigir_status_retroativamente, migrations.RunPython.noop
        ),
    ]
