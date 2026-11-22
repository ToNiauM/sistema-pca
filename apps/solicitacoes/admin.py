"""Admin das Solicitações (Fase 43).

O vínculo usuário↔unidade é editado na própria tela do usuário (inline acrescentado a
`UsuarioAdmin` aqui, para `core/` seguir sem importar nada de `apps/`). As solicitações
nascem pelos serviços (pedido com regras e alçadas), nunca pelo Admin — sem "adicionar";
o superusuário corrige e apaga como em qualquer registro (regra de 11/09/2026).
"""

from django.contrib import admin

from apps.pca.admin import HistoricoSomenteLeituraAdmin
from core.admin import UsuarioAdmin

from .models import ParteSolicitacao, Solicitacao, VinculoUnidade


class VinculoUnidadeInline(admin.TabularInline):
    model = VinculoUnidade
    extra = 1
    verbose_name = "unidade do usuário"
    verbose_name_plural = "unidades do usuário (para quem faz solicitações)"


# `inlines` é lido a cada requisição: acrescentar aqui vale para o `UsuarioAdmin` já registrado.
UsuarioAdmin.inlines = (*UsuarioAdmin.inlines, VinculoUnidadeInline)


@admin.register(VinculoUnidade)
class VinculoUnidadeAdmin(admin.ModelAdmin):
    list_display = ("usuario", "unidade")
    list_select_related = ("usuario", "unidade")
    list_filter = ("unidade",)
    search_fields = ("usuario__email", "usuario__first_name", "usuario__last_name")


class ParteSolicitacaoInline(admin.TabularInline):
    model = ParteSolicitacao
    extra = 0
    can_delete = False
    fields = (
        "campo", "alcada", "valor_atual", "valor_pedido", "estado", "valor_concedido",
        "motivo", "decidido_por", "decidido_em", "fora_do_exercicio",
    )
    readonly_fields = ("campo", "alcada", "valor_atual", "valor_pedido", "decidido_por", "decidido_em")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Solicitacao)
class SolicitacaoAdmin(admin.ModelAdmin):
    list_display = ("codigo", "unidade", "tipo", "estado", "processo", "solicitante", "criada_em")
    list_select_related = ("unidade", "solicitante", "processo")
    list_filter = ("estado", "tipo", "unidade", "exercicio")
    search_fields = (
        "justificativa", "numero_sei", "solicitante__email", "=processo__item_pca",
    )
    ordering = ("-criada_em", "-id")
    readonly_fields = ("numero", "ano", "exercicio", "processo", "unidade", "solicitante", "tipo", "criada_em")
    inlines = [ParteSolicitacaoInline]

    @admin.display(description="solicitação", ordering="numero")
    def codigo(self, obj):
        return obj.codigo

    def has_add_permission(self, request):
        return False  # nasce pelos serviços, que aplicam regras e alçadas


class HistoricalSolicitacaoAdmin(HistoricoSomenteLeituraAdmin):
    admin_grupo = "Auditoria e histórico"
    list_display = ("numero", "ano", "history_date", "history_type", "history_user", "estado")
    list_filter = ("history_date", "history_type", "history_user")
    search_fields = ("=numero",)


class HistoricalParteSolicitacaoAdmin(HistoricoSomenteLeituraAdmin):
    admin_grupo = "Auditoria e histórico"
    list_display = ("history_date", "history_type", "history_user", "campo", "estado")
    list_filter = ("history_date", "history_type", "history_user", "campo")


class HistoricalVinculoUnidadeAdmin(HistoricoSomenteLeituraAdmin):
    admin_grupo = "Auditoria e histórico"
    list_display = ("history_date", "history_type", "history_user", "usuario", "unidade")
    list_filter = ("history_date", "history_type", "history_user")
    list_select_related = ("history_user", "usuario", "unidade")


admin.site.register(Solicitacao.history.model, HistoricalSolicitacaoAdmin)
admin.site.register(ParteSolicitacao.history.model, HistoricalParteSolicitacaoAdmin)
admin.site.register(VinculoUnidade.history.model, HistoricalVinculoUnidadeAdmin)
