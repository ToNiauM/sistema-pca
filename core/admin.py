import axes.utils
import simple_history
import simple_history.utils
from axes.admin import AccessAttemptAdmin, AccessFailureLogAdmin, AccessLogAdmin
from axes.conf import settings as axes_settings
from axes.models import AccessAttempt, AccessFailureLog, AccessLog
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import AdminPasswordChangeForm

from core.models import Usuario

# Modelo de usuário customizado: o histórico é ligado via simple_history.register()
# em vez de HistoricalRecords() direto no modelo Armadilha 7 §4 —
# exigência documentada do django-simple-history para User customizado).
simple_history.register(Usuario)


class RedefinirSenhaComTrocaObrigatoriaForm(AdminPasswordChangeForm):
    """Toda redefinição de senha feita pelo Admin remarca o usuário-alvo para
    trocar a senha no próximo acesso — quem viu a senha em texto claro no
    formulário foi o administrador, não a pessoa dona da conta (D do plano,
    gatilho c)."""

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
    # "is_staff", "is_superuser", "is_active" e "groups" ("filtro por
    # grupo e por is_active" já satisfeito sem código novo).
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
        # Gatilho (b) -gdi (Opção B do checkpoint): só a
        # CRIAÇÃO pelo Admin marca a flag — `create_user()`/`create_superuser()`
        # fora do Admin (scripts, `createsuperuser`, fixtures de teste)
        # nascem com `senha_temporaria=False` (default do campo). `not
        # change` é o mesmo sinal que `ModelAdmin.save_model` documenta para
        # distinguir "add" de "change"; `add_fieldsets` sempre inclui
        # `password1`/`password2`, então toda criação aqui já vem com senha
        # definida pelo administrador.
        if not change:
            obj.senha_temporaria = True
        super().save_model(request, obj, form, change)

    @admin.display(description="grupos")
    def grupos_do_usuario(self, obj):
        return ", ".join(grupo.name for grupo in obj.groups.all())

    def _definir_is_active_com_historico(self, request, queryset, valor, motivo):
        # Usuario tem histórico via simple_history.register(Usuario) (topo
        # deste arquivo); queryset.update() não gera HistoricalUsuario (mesma
        # armadilha do Pitfall 5 do por isso o valor é setado
        # em memória em cada objeto e persistido via bulk_update_with_history,
        # que grava uma linha de histórico por objeto com o usuário e o
        # motivo da ação.
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
        # QA de segurança 30/09/2026 (periferia #11, T-41o-03) — o próprio
        # `request.user` nunca é desativado por esta ação, mesmo quando
        # está dentro do lote selecionado junto com outros alvos.
        if queryset.filter(pk=request.user.pk).exists():
            messages.warning(
                request, "Sua própria conta não foi desativada por esta ação."
            )
        queryset = queryset.exclude(pk=request.user.pk)
        self._definir_is_active_com_historico(
            request, queryset, False, "Desativado em massa pelo admin"
        )


class HistoricalUsuarioAdmin(admin.ModelAdmin):
    """Consulta do histórico de usuários: sem adicionar
    linha histórica pelo Admin (não faz sentido criar histórico à mão);
    editar e apagar passam a ser governados pela permissão nativa do model,
    por pedido do usuário — criar uma linha de histórico
    continua sem sentido, corrigir ou remover uma não."""

    admin_grupo = "Auditoria e histórico"
    list_display = ("history_date", "history_type", "history_user", "email")
    list_filter = ("history_date", "history_type", "history_user")
    search_fields = ("email",)
    list_select_related = ("history_user",)
    ordering = ("-history_date",)

    def has_add_permission(self, request):
        return False


admin.site.register(Usuario.history.model, HistoricalUsuarioAdmin)


# Complemento do admin que o django-axes já registra — nunca
# re-registro às cegas. "axes" precede "core" em INSTALLED_APPS
# (config/settings/base.py), então o autodiscovery do Django já importou
# axes/admin.py e registrou AccessAttempt/AccessLog/AccessFailureLog em
# admin.site quando este módulo é importado; unregister() antes de
# re-registrar evita AlreadyRegistered. AXES_ENABLE_ADMIN é True por padrão
# neste projeto (nenhum override em config/settings/) — o guard replica a
# mesma condição que axes/admin.py usa para decidir se registra.
if axes_settings.AXES_ENABLE_ADMIN:
    admin.site.unregister(AccessAttempt)
    admin.site.unregister(AccessLog)
    admin.site.unregister(AccessFailureLog)

    @admin.register(AccessAttempt)
    class PcaAccessAttemptAdmin(AccessAttemptAdmin):
        """Estende o admin do axes só com agrupamento e desbloqueio.

        list_display/search_fields/fieldsets não são redeclarados — já vêm
        de AccessAttemptAdmin com e-mail tentado (`username`), IP
        (`ip_address`), falhas (`failures_since_start`) e data
        (`attempt_time`).
        """

        admin_grupo = "Usuários e bloqueios de login"
        actions = [*AccessAttemptAdmin.actions, "desbloquear_selecionados"]

        @admin.action(description="Desbloquear tentativas selecionadas")
        def desbloquear_selecionados(self, request, queryset):
            # O IP aqui exibido depende de AXES_IPWARE_PROXY_COUNT e
            # AXES_IPWARE_META_PRECEDENCE_ORDER (já configurados em
            # config/settings/prod.py), mas isso nunca foi verificado ao vivo
            # sob a topologia real Cloudflare/Docker (Phase 999.1). Esta
            # tela não deve ser lida como IP confiável sem essa verificação.
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
