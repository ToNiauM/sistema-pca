from django.db import models


class QuerySetAuditado(models.QuerySet):
    """Bloqueia `.update()` em modelos versionados.

    `.update()` roda um UPDATE SQL direto, sem passar por `save()` — não gera
    linha em `Historical*`, furando a trilha de auditoria exigida pela Lei
    14.133/2021. `bulk_update_with_history` NÃO é alternativa válida para
    correção em massa: por baixo ele chama `Model.objects.bulk_update()`, que
    por sua vez chama `queryset.update()` — o mesmo bloqueio deste Manager
    (verificado em produção; incidente reunião id=8, 2026-09-01). A correção
    em massa correta é percorrer as instâncias e chamar `save()` uma a uma,
    com `_history_user`/`_change_reason` setados (ou
    `simple_history.utils.update_change_reason`).
    O bloqueio fica no QuerySet (não só no Manager) para cobrir também
    `Modelo.objects.filter(...).update(...)`.
    """

    def update(self, *args, **kwargs):
        raise NotImplementedError(
            "bulk_update_with_history também aciona este bloqueio (chama "
            "bulk_update() -> queryset.update() por baixo) — corrija "
            "instância por instância com save(), setando "
            "_history_user/_change_reason "
        )


class ManagerAuditado(models.Manager.from_queryset(QuerySetAuditado)):
    pass
