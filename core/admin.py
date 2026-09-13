import axes.utils
import simple_history
import simple_history.utils
from axes.admin import AccessAttemptAdmin, AccessFailureLogAdmin, AccessLogAdmin
from axes.conf import settings as axes_settings
from axes.models import AccessAttempt, AccessFailureLog, AccessLog
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import AdminPasswordChangeForm

from core.models import Usuario

# Histórico ligado via simple_history.register() em vez de
# HistoricalRecords() direto no modelo — exigência do django-simple-history
# para User customizado.
simple_history.register(Usuario)


class RedefinirSenhaComTrocaObrigatoriaForm(AdminPasswordChangeForm):
    """Toda redefinição de senha pelo Admin remarca o usuário-alvo para
    trocar a senha no próximo acesso."""

    def save(self, commit=True):
        self.user.senha_temporaria = True
        return super().save(commit=commit)


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    """UserAdmin padrão do Django adaptado para e-mail no lugar de username."""

    admin_grupo = "Usuários e bloqueios de login"
    ordering = ("email",)
    change_password_form = RedefinirSenhaComTrocaObrigatoriaForm
    list_display = (
        "email",
        "first_name",
        "last_name",
        "is_staff",
        "is_active",
        "senha_temporaria",
        "grupos_do_usuario",
        "last_login",
    )
    # list_filter não é redeclarado: o padrão herdado de UserAdmin já cobre
    # "is_staff", "is_superuser", "is_active" e "groups".
    search_fields = ("email", "first_name", "last_name")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Informações pessoais", {"fields": ("first_name", "last_name")}),
        (
            "Permissões",
            {
                "fields": (
                    "is_active",
                    "senha_temporaria",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Datas importantes", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "password1", "password2"),
            },
        ),
    )
    actions = ["ativar_usuarios", "desativar_usuarios"]

    def save_model(self, request, obj, form, change):
        # Só a CRIAÇÃO pelo Admin marca a flag; create_user()/
        # create_superuser() fora do Admin nascem com senha_temporaria=False
        # (default do campo). `not change` distingue "add" de "change".
        if not change:
            obj.senha_temporaria = True
        super().save_model(request, obj, form, change)

    @admin.display(description="grupos")
    def grupos_do_usuario(self, obj):
        return ", ".join(grupo.name for grupo in obj.groups.all())

    def _definir_is_active_com_historico(self, request, queryset, valor, motivo):
        # queryset.update() não gera HistoricalUsuario; por isso o valor é
        # setado em memória e persistido via bulk_update_with_history, que
        # grava uma linha de histórico por objeto.
        objetos = list(queryset)
        for objeto in objetos:
            objeto.is_active = valor
        simple_history.utils.bulk_update_with_history(
            objetos,
            Usuario,
            ["is_active"],
            default_user=request.user,
            default_change_reason=motivo,
        )

    @admin.action(description="Ativar usuários selecionados")
    def ativar_usuarios(self, request, queryset):
        self._definir_is_active_com_historico(
            request, queryset, True, "Ativado em massa pelo admin"
        )

    @admin.action(description="Desativar usuários selecionados")
    def desativar_usuarios(self, request, queryset):
        self._definir_is_active_com_historico(
            request, queryset, False, "Desativado em massa pelo admin"
        )


class HistoricalUsuarioAdmin(admin.ModelAdmin):
    """Consulta do histórico de usuários: sem adicionar linha histórica pelo
    Admin; editar e apagar seguem a permissão nativa do model."""

    admin_grupo = "Auditoria e histórico"
    list_display = ("history_date", "history_type", "history_user", "email")
    list_filter = ("history_date", "history_type", "history_user")
    search_fields = ("email",)
    list_select_related = ("history_user",)
    ordering = ("-history_date",)

    def has_add_permission(self, request):
        return False


admin.site.register(Usuario.history.model, HistoricalUsuarioAdmin)


# Complemento do admin que o django-axes já registra — nunca re-registro
# às cegas. "axes" precede "core" em INSTALLED_APPS, então o autodiscovery
# já importou axes/admin.py e registrou os models; unregister() antes de
# re-registrar evita AlreadyRegistered.
if axes_settings.AXES_ENABLE_ADMIN:
    admin.site.unregister(AccessAttempt)
    admin.site.unregister(AccessLog)
    admin.site.unregister(AccessFailureLog)

    @admin.register(AccessAttempt)
    class PcaAccessAttemptAdmin(AccessAttemptAdmin):
        """Estende o admin do axes só com agrupamento e desbloqueio.

        list_display/search_fields/fieldsets vêm de AccessAttemptAdmin.
        """

        admin_grupo = "Usuários e bloqueios de login"
        actions = [*AccessAttemptAdmin.actions, "desbloquear_selecionados"]

        @admin.action(description="Desbloquear tentativas selecionadas")
        def desbloquear_selecionados(self, request, queryset):
            # O IP aqui exibido depende de AXES_IPWARE_PROXY_COUNT/
            # AXES_IPWARE_META_PRECEDENCE_ORDER (config/settings/prod.py).
            total_removido = 0
            for tentativa in queryset:
                total_removido += axes.utils.reset(
                    ip=tentativa.ip_address, username=tentativa.username
                )
            self.message_user(
                request,
                f"{total_removido} registro(s) de bloqueio removido(s).",
            )

    @admin.register(AccessLog)
    class PcaAccessLogAdmin(AccessLogAdmin):
        admin_grupo = "Usuários e bloqueios de login"

    @admin.register(AccessFailureLog)
    class PcaAccessFailureLogAdmin(AccessFailureLogAdmin):
        admin_grupo = "Usuários e bloqueios de login"
