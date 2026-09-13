from copy import copy

from django.contrib import admin
from django.contrib.admin.views.main import IncorrectLookupParameters
from django.http import QueryDict
from django.shortcuts import redirect
from django.urls import path, reverse

from apps.pca import services
from apps.pca.importacao import views
from apps.pca.importacao.models import EventoImportacao
from .models import (
    Acompanhamento,
    Processo,
    ProcessoSEI,
    RascunhoItemVirada,
    RascunhoVirada,
    Reuniao,
)


@admin.register(Processo)
class ProcessoAdmin(admin.ModelAdmin):
    change_form_template = "admin/pca/processo/change_form.html"
    list_display = (
        "item_pca", "descricao_objeto", "estado", "tipo", "situacao",
        "unidade_organizacional", "exercicio", "valor_estimado",
    )
    list_filter = (
        "exercicio", "estado", "situacao", "unidade_organizacional",
        "categoria", "tipo",
    )
    search_fields = ("item_pca", "descricao_objeto")
    ordering = ("-exercicio__ano", "item_pca")
    list_select_related = ("unidade_organizacional", "exercicio")

    def save_model(self, request, obj, form, change):
        """Quando `estado` muda pelo Admin, roteia por `services.alterar_estado`
        para gerar o `Acompanhamento` automático antes do save padrão."""
        if change and "estado" in form.changed_data:
            services.alterar_estado(
                processo_id=obj.pk,
                usuario=request.user,
                estado_novo=obj.estado,
            )
            obj.refresh_from_db(fields=["atualizado_em"])
        super().save_model(request, obj, form, change)

    def _url_do_changelist(self):
        return reverse(f"{self.admin_site.name}:pca_processo_changelist")

    def _url_de_change(self, pk, filtros):
        url = reverse(f"{self.admin_site.name}:pca_processo_change", args=[pk])
        if not filtros:
            return url

        parametros = QueryDict(mutable=True)
        parametros["_changelist_filters"] = filtros.urlencode()
        return f"{url}?{parametros.urlencode()}"

    def _contexto_navegacao(self, request, obj):
        """Preserva a sequência efetiva do ChangeList sem alterar a request real."""
        filtros = QueryDict(request.GET.get("_changelist_filters", ""))
        url_changelist = self._url_do_changelist()
        if filtros:
            url_changelist = f"{url_changelist}?{filtros.urlencode()}"

        navegacao = {
            "voltar_url": url_changelist,
            "anterior_url": None,
            "proximo_url": None,
        }
        request_changelist = copy(request)
        request_changelist.GET = filtros

        try:
            changelist = self.get_changelist_instance(request_changelist)
        except IncorrectLookupParameters:
            return navegacao

        pks = list(changelist.queryset.values_list("pk", flat=True))
        try:
            posicao_atual = pks.index(obj.pk)
        except ValueError:
            return navegacao

        if posicao_atual:
            navegacao["anterior_url"] = self._url_de_change(
                pks[posicao_atual - 1], filtros
            )
        if posicao_atual < len(pks) - 1:
            navegacao["proximo_url"] = self._url_de_change(
                pks[posicao_atual + 1], filtros
            )
        return navegacao

    def render_change_form(
        self, request, context, add=False, change=False, form_url="", obj=None
    ):
        if change and obj is not None:
            context["processo_navegacao"] = self._contexto_navegacao(request, obj)
        return super().render_change_form(request, context, add, change, form_url, obj)


@admin.register(Acompanhamento)
class AcompanhamentoAdmin(admin.ModelAdmin):
    # correção de prazo_prometido/evento é exclusiva do Admin
    list_display = (
        "processo", "referencia_data", "tipo_evento", "situacao",
        "prazo_prometido", "evento",
    )
    list_filter = ("tipo_evento", "situacao")
    search_fields = ("processo__item_pca", "situacao_informada", "evento")
    ordering = ("processo", "-referencia_data")
    list_select_related = ("processo", "situacao")

    # exclusão segue a permissão padrão do ModelAdmin; histórico continua auditado


@admin.register(Reuniao)
class ReuniaoAdmin(admin.ModelAdmin):
    """Gestão mínima da reunião: abrir/fechar é alterar `situacao`."""

    list_display = ("data", "exercicio", "condutor", "situacao")
    list_filter = ("exercicio", "situacao")
    ordering = ("-data",)
    list_select_related = ("condutor", "exercicio")


@admin.register(ProcessoSEI)
class ProcessoSEIAdmin(admin.ModelAdmin):
    list_display = ("processo", "numero_sei")
    search_fields = ("processo__item_pca", "numero_sei")
    list_select_related = ("processo",)


class HistoricoSomenteLeituraAdmin(admin.ModelAdmin):
    """Base de admin de histórico somente leitura: nunca permite adicionar linha."""

    list_display = ("id", "history_date", "history_type", "history_user")
    list_select_related = ("history_user",)
    ordering = ("-history_date",)

    def has_add_permission(self, request):
        return False


class HistoricalProcessoAdmin(HistoricoSomenteLeituraAdmin):
    """Consulta do histórico de processos."""

    admin_grupo = "Auditoria e histórico"
    list_display = ("history_date", "history_type", "history_user", "item_pca")
    list_filter = ("history_date", "history_type", "history_user")
    search_fields = ("=item_pca",)


class HistoricalAcompanhamentoAdmin(HistoricoSomenteLeituraAdmin):
    """Consulta do histórico de acompanhamentos."""

    admin_grupo = "Auditoria e histórico"
    list_display = ("history_date", "history_type", "history_user", "processo")
    list_filter = ("history_date", "history_type", "history_user")
    search_fields = ("=processo__item_pca", "situacao_informada")
    list_select_related = ("history_user", "processo")


admin.site.register(Processo.history.model, HistoricalProcessoAdmin)
admin.site.register(Acompanhamento.history.model, HistoricalAcompanhamentoAdmin)


class RascunhoItemViradaInline(admin.TabularInline):
    model = RascunhoItemVirada
    extra = 0
    fields = (
        "processo_origem", "ordem", "selecionado",
        "valor_estimado_editado", "mes_previsto_editado",
    )


@admin.register(RascunhoVirada)
class RascunhoViradaAdmin(admin.ModelAdmin):
    list_display = (
        "exercicio_origem", "ano_destino", "criado_por", "criado_em",
        "confirmado_em", "confirmado_por",
    )
    list_filter = ("exercicio_origem",)
    list_select_related = ("exercicio_origem", "criado_por", "confirmado_por")
    ordering = ("-criado_em",)
    inlines = [RascunhoItemViradaInline]


@admin.register(RascunhoItemVirada)
class RascunhoItemViradaAdmin(admin.ModelAdmin):
    list_display = (
        "rascunho", "processo_origem", "ordem", "selecionado",
        "valor_estimado_editado", "mes_previsto_editado",
    )
    list_select_related = ("rascunho", "processo_origem")
    search_fields = ("processo_origem__item_pca",)
    ordering = ("rascunho", "ordem")


@admin.register(EventoImportacao)
class EventoImportacaoAdmin(admin.ModelAdmin):
    """Rastro de quem confirmou uma importação pela tela."""

    admin_grupo = "Importação da planilha"
    list_display = (
        "arquivo_nome",
        "exercicio",
        "disparado_por",
        "criado_em",
        "processos_criados",
        "acompanhamentos_criados",
    )
    list_select_related = ("exercicio", "disparado_por")
    ordering = ("-criado_em",)

    def add_view(self, request, form_url="", extra_context=None):
        """O botão padrão abre o primeiro passo, em vez de um ModelForm."""
        return redirect("admin:pca_eventoimportacao_importar")

    def get_urls(self):
        urls = super().get_urls()
        urls_importacao = [
            path(
                "importar/modelo/",
                self.admin_site.admin_view(views.baixar_modelo_view),
                name="pca_eventoimportacao_modelo",
            ),
            path(
                "importar/",
                self.admin_site.admin_view(views.importar_view),
                name="pca_eventoimportacao_importar",
            ),
            path(
                "importar/confirmar/",
                self.admin_site.admin_view(views.confirmar_view),
                name="pca_eventoimportacao_confirmar",
            ),
        ]
        return urls_importacao + urls
