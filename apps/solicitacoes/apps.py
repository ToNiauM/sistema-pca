from django.apps import AppConfig


class SolicitacoesConfig(AppConfig):
    """Fase 43 — Solicitações das unidades: pedidos de alteração, cancelamento e
    inclusão de itens do PCA, decididos pela equipe do PCA ou pela diretoria."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.solicitacoes"
    verbose_name = "Solicitações das unidades"

    def ready(self):
        # Import por efeito colateral: liga o gancho único de "prejudicada".
        from apps.solicitacoes import signals  # noqa: F401
