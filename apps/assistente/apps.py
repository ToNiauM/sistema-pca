from django.apps import AppConfig


class AssistenteConfig(AppConfig):
    """Fase 39 — Assistente do PCA. App autocontido, sem migração
    (todo estado próprio vive em SQLite auxiliares via `estado.py`, fora do
    banco principal)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.assistente"
    verbose_name = "Assistente do PCA"

    def ready(self):
        # Import por efeito colateral: registra o sinal de logout (apaga a
        # conversa da sessão) e os checks de configuração.
        from apps.assistente import checks  # noqa: F401
        from apps.assistente import signals  # noqa: F401
