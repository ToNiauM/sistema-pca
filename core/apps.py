import django.contrib.admin.apps as _django_admin_apps
from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"


class PcaAdminConfig(_django_admin_apps.AdminConfig):
    """Troca o `AdminSite` padrão do Django pelo `PcaAdminSite`.

    Não redeclara `name` — herda `"django.contrib.admin"` de `AdminConfig`.
    `import ... as _django_admin_apps` evita que `AdminConfig` apareça como
    atributo do módulo, e `default = False` tira `PcaAdminConfig` da lista
    de candidatos automáticos de `"core"` — sem os dois o Django não
    consegue decidir o AppConfig default desse app.
    """

    # "core.admin_site" (não "core.admin"): admin.py registra UsuarioAdmin;
    # se PcaAdminSite morasse lá, o próprio import reentraria em admin.site
    # antes dele terminar de se configurar.
    default_site = "core.admin_site.PcaAdminSite"
    default = False
