import django.contrib.admin.apps as _django_admin_apps
from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        # Import por efeito colateral: registra `Unaccent` em
        # CharField/TextField (core.db, nível de módulo) e disponibiliza o
        # receiver que arma unaccent/collation em cada conexão SQLite nova.
        from django.db.backends.signals import connection_created

        from core import db as _core_db

        connection_created.connect(_core_db.configurar_conexao_sqlite)


class PcaAdminConfig(_django_admin_apps.AdminConfig):
    """Troca o `AdminSite` padrão do Django pelo `PcaAdminSite`.

    Não redeclara `name` — herda `"django.contrib.admin"` de `AdminConfig`,
    o que é obrigatório para o Django reconhecer esta subclasse como a
    configuração do app `django.contrib.admin` (interface).
    `config/urls.py` não muda: `admin.site` é um `LazyObject` que lê
    `apps.get_app_config("admin").default_site` na primeira chamada.

    Duas armadilhas de autodiscovery encontradas na execução, ambas
    sobre a entrada plain `"core"` de `INSTALLED_APPS`: o Django enumera
    TODAS as classes acessíveis como atributo do módulo `core.apps` para
    decidir o `AppConfig` default desse app.
    - `import django.contrib.admin.apps as _django_admin_apps` (em vez de
      `from ... import AdminConfig`) evita que a própria `AdminConfig`
      apareça como atributo do módulo — só `PcaAdminConfig` (que a
      subclassifica) fica visível.
    - `default = False` remove `PcaAdminConfig` da lista de candidatos
      automáticos da entrada `"core"`; ela já é referenciada de forma
      explícita em `INSTALLED_APPS` (`"core.apps.PcaAdminConfig"`), então
      não depende de autodiscovery para ser usada como config do app
      `django.contrib.admin`.
    Sem as duas, o Django ora levanta `RuntimeError: 'core.apps' declares
    more than one default AppConfig` (só a segunda aplicada), ora
    `ImproperlyConfigured: Application labels aren't unique, duplicates:
    admin` (a entrada `"core"` resolvendo por engano para `AdminConfig`).
    """

    # "core.admin_site" (não "core.admin"): PcaAdminSite vive num módulo sem
    # nenhum admin.site.register() próprio (ver docstring de
    # core/admin_site.py), bug de reentrância descoberto na
    # execução. `core/admin.py` registra UsuarioAdmin; se PcaAdminSite
    # morasse lá, o próprio import do módulo (disparado de dentro da
    # resolução preguiçosa de `admin.site`) reacessaria `admin.site` antes
    # dela terminar de se configurar, e a instância mais externa a terminar
    # sobrescreveria `_wrapped` com um registro vazio, apagando os registros
    # feitos pela instância descartada no meio do caminho.
    default_site = "core.admin_site.PcaAdminSite"
    default = False
