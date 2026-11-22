"""Gancho de fechamento da reunião.

Fechar uma reunião que estava ABERTA — pelo Admin, por um serviço ou pelo shell, qualquer caminho que
termine num `Reuniao.save()` — grava uma versão congelada do relatório. Criar uma reunião já FECHADA (o
importador) não congela nada: a tela reconstrói depois, sob demanda. `queryset.update()` não dispara
signal; quem fechar assim também cai na reconstrução preguiçosa da tela. O render roda depois do commit
(`on_commit` robusto) e uma falha nunca desfaz nem quebra o fechamento (ver `congelamento`).
"""

import functools

from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from simple_history.models import HistoricalRecords

from apps.pca import congelamento
from apps.pca.models import Reuniao, SituacaoReuniao


@receiver(pre_save, sender=Reuniao, dispatch_uid="pca_reuniao_situacao_anterior")
def guardar_situacao_anterior(sender, instance, raw=False, **kwargs):
    instance._situacao_anterior = None
    if raw or instance.pk is None or instance._state.adding:
        return
    instance._situacao_anterior = (
        Reuniao.objects.filter(pk=instance.pk).values_list("situacao", flat=True).first()
    )


def _usuario_do_fechamento(instance):
    usuario = getattr(instance, "_history_user", None)
    if usuario is not None:
        return usuario
    pedido = getattr(HistoricalRecords.context, "request", None)
    candidato = getattr(pedido, "user", None)
    if candidato is not None and getattr(candidato, "is_authenticated", False):
        return candidato
    return None


@receiver(post_save, sender=Reuniao, dispatch_uid="pca_reuniao_congelar_no_fechamento")
def congelar_ao_fechar(sender, instance, created=False, raw=False, update_fields=None, **kwargs):
    if created or raw:
        return
    if update_fields is not None and "situacao" not in update_fields:
        return
    if (
        getattr(instance, "_situacao_anterior", None) != SituacaoReuniao.ABERTA
        or instance.situacao != SituacaoReuniao.FECHADA
    ):
        return
    usuario = _usuario_do_fechamento(instance)
    transaction.on_commit(
        functools.partial(
            congelamento.congelar_no_fechamento, instance.pk, usuario.pk if usuario else None
        ),
        robust=True,
    )
