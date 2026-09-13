from django.db import models


class QuerySetAuditado(models.QuerySet):
    """Bloqueia .update() em modelos versionados: um UPDATE SQL direto não
    passa por save(), furando a trilha de auditoria. A correção em massa
    correta é percorrer as instâncias e chamar save() uma a uma. O bloqueio
    fica no QuerySet (não só no Manager) para cobrir também
    Modelo.objects.filter(...).update(...)."""

    def update(self, *args, **kwargs):
        raise NotImplementedError(
            "bulk_update_with_history também aciona este bloqueio (chama "
            "bulk_update() -> queryset.update() por baixo) — corrija "
            "instância por instância com save(), setando "
            "_history_user/_change_reason (PITFALLS.md #5)"
        )


class ManagerAuditado(models.Manager.from_queryset(QuerySetAuditado)):
    pass
