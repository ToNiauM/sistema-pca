from django.apps import AppConfig


class PcaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.pca"
    verbose_name = "PCA — processos e acompanhamentos"

    def ready(self):
        # Import por efeito colateral: liga o gancho de fechamento da reunião.
        from apps.pca import signals  # noqa: F401
