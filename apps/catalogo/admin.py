from django.contrib import admin, messages
from django.db.models import Count
from django.http import HttpResponseRedirect
from django.urls import reverse

from .models import (
    Categoria,
    Classificacao,
    GrauPrioridade,
    InstrumentoContratual,
    Modalidade,
    SituacaoNormalizada,
    Tipo,
    Unidade,
    Exercicio,
)


class ContagemDeUsoAdminMixin:
    """Protege catálogos referenciados e exibe seu uso sem consultas por linha."""

    campo_relacionado = "processos"

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _uso=Count(self.campo_relacionado, distinct=True)
        )

    @admin.display(description="uso", ordering="_uso")
    def uso(self, obj):
        return obj._uso

    def _contagem_uso(self, obj):
        return getattr(obj, self.campo_relacionado).count()

    def _descricao_uso(self):
        if self.campo_relacionado == "acompanhamentos":
            return "acompanhamento(s)"
        return "processo(s)"

    def _mensagem_exclusao_bloqueada(self, request, obj, contagem):
        self.message_user(
            request,
            (
                f"Não é possível excluir '{obj}': {contagem} "
                f"{self._descricao_uso()} ainda o referenciam."
            ),
            level=messages.ERROR,
        )

    def delete_view(self, request, object_id, extra_context=None):
        """Evita que o Collector do Django esconda a mensagem de erro."""
        obj = self.get_object(request, object_id)
        if obj is not None:
            contagem = self._contagem_uso(obj)
            if contagem:
                self._mensagem_exclusao_bloqueada(request, obj, contagem)
                return HttpResponseRedirect(
                    reverse(
                        f"admin:{self.opts.app_label}_{self.opts.model_name}_changelist"
                    )
                )
        return super().delete_view(request, object_id, extra_context)

    def delete_model(self, request, obj):
        contagem = self._contagem_uso(obj)
        if contagem:
            self._mensagem_exclusao_bloqueada(request, obj, contagem)
            return
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        bloqueados = []
        for obj in queryset:
            contagem = self._contagem_uso(obj)
            if contagem:
                bloqueados.append(
                    f"'{obj}' ({contagem} {self._descricao_uso()})"
                )
                continue
            super().delete_model(request, obj)

        if bloqueados:
            self.message_user(
                request,
                "Não é possível excluir: " + ", ".join(bloqueados) + ".",
                level=messages.ERROR,
            )


class DominioAdmin(ContagemDeUsoAdminMixin, admin.ModelAdmin):
    """Vocabulário editável livremente no Admin, sem auditoria própria."""

    admin_grupo = "Catálogos do PCA"
    list_display = ("nome", "uso")
    search_fields = ("nome",)
    ordering = ("nome",)


@admin.register(Exercicio)
class ExercicioAdmin(ContagemDeUsoAdminMixin, admin.ModelAdmin):
    admin_grupo = "Catálogos do PCA"
    list_display = ("ano", "rotulo", "situacao", "uso")
    list_filter = ("situacao",)
    search_fields = ("rotulo", "ano")
    ordering = ("-ano",)


for _modelo in (
    Unidade,
    Categoria,
    Tipo,
    GrauPrioridade,
    Classificacao,
    Modalidade,
    InstrumentoContratual,
):
    admin.site.register(_modelo, DominioAdmin)


@admin.register(SituacaoNormalizada)
class SituacaoNormalizadaAdmin(DominioAdmin):
    campo_relacionado = "acompanhamentos"
