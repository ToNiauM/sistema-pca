"""Gancho único da "prejudicada".

Quando um item é cancelado ou concluído — pela equipe (modal de transição), pelo Admin
(`alterar_estado`/edição) ou pelo robô SEI (`aplicar_regras_automaticas`/
`registrar_acompanhamento`) —, todos esses caminhos terminam num `Processo.save()`. Este
receptor de `post_save` é o ÚNICO ponto que liga o fato à solicitação: as partes pendentes do
item encerram como "prejudicada" (`services.prejudicar_pendentes_do_processo`). Grava só
quando o item está encerrado e o `save()` pode ter mexido em `estado`/`situacao` (um
`save(update_fields=[...])` sem esses campos não consulta nada).
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.pca.models import Estado, Processo, Situacao

_CAMPOS_QUE_ENCERRAM = {"estado", "situacao"}


@receiver(post_save, sender=Processo, dispatch_uid="solicitacoes_item_encerrado")
def item_encerrado(sender, instance, created, update_fields, **kwargs):
    if created:
        return
    if update_fields is not None and not _CAMPOS_QUE_ENCERRAM & set(update_fields):
        return
    if instance.estado == Estado.CANCELADO:
        motivo = "Item cancelado."
    elif instance.situacao == Situacao.CONCLUIDO:
        motivo = "Item concluído."
    else:
        return
    from apps.solicitacoes import services

    services.prejudicar_pendentes_do_processo(
        instance.pk, usuario=getattr(instance, "_history_user", None), motivo=motivo
    )
