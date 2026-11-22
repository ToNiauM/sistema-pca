from copy import copy

from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin.views.main import IncorrectLookupParameters
from django.core.exceptions import PermissionDenied
from django.http import QueryDict
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

from apps.pca import services
from apps.pca.importacao import views
from apps.pca.importacao.models import EventoImportacao
from apps.pca.sei import execucoes
from .models import (
    Acompanhamento,
    CenarioFluxo,
    Estado,
    EventoFinanceiro,
    FichaContratacao,
    Processo,
    ProcessoSEI,
    RascunhoItemVirada,
    RascunhoVirada,
    RelatorioCongelado,
    Reuniao,
)


class EventoFinanceiroInline(admin.TabularInline):
    """Fase 36 (spec §6.6) — a série de valores do
    processo, direto na tela do Processo no Admin (mesmo padrão de
    `RascunhoItemViradaInline` abaixo). `instrumento` (Fase 37,
    spec §2.1/§8) acrescentado ao fim, mesma edição manual pelo Admin dos
    demais campos do inline."""

    model = EventoFinanceiro
    extra = 0
    fields = (
        "data", "tipo", "natureza", "valor", "valor_mensal",
        "periodicidade", "protocolo_sei", "origem", "instrumento",
    )


@admin.register(Processo)
class ProcessoAdmin(admin.ModelAdmin):
    change_form_template = "admin/pca/processo/change_form.html"
    list_display = (
        "item_pca", "descricao_objeto", "estado", "tipo", "situacao", "situacao_manual",
        "unidade_organizacional", "exercicio", "valor_estimado",
        "sei_ultima_consulta",
    )
    list_filter = (
        "exercicio", "estado", "situacao", "situacao_manual", "unidade_organizacional",
        "categoria", "tipo",
    )
    search_fields = ("item_pca", "descricao_objeto")
    ordering = ("-exercicio__ano", "item_pca")
    list_select_related = ("unidade_organizacional", "exercicio", "tipo")
    inlines = [EventoFinanceiroInline]
    # Gravados só pelo robô SEI; aparecem como texto no
    # change form, nunca como `<input>`.
    readonly_fields = ("unidade_sei_atual", "unidade_sei_atual_desde", "situacao_regra")
    # (Fase 32) — único disparo sob demanda do
    # robô SEI: nenhum botão nas telas do sistema, só esta ação, só
    # superusuário ("senão queima meu server", decisão do usuário). A ação
    # só GRAVA um pedido em data/sei/pedidos/ — nunca consulta o SEI, nunca
    # grava Processo/Acompanhamento; quem consulta e aplica é sei_atender
    # (serviço robo permanente), spec §3.7.
    actions = ["atualizar_com_o_sei", "reindexar_assistente"]

    def get_queryset(self, request):
        """QA 30/09 (periferia nº10) — `sei_ultima_consulta` relia
        `ultima_consulta.json` do disco a cada LINHA do changelist (1
        chamada a `execucoes.carregar_ultima_consulta()` por objeto).
        Cacheia UMA vez por request, no início, antes de qualquer linha ser
        renderizada."""
        self._cache_sei_ultima_consulta = execucoes.carregar_ultima_consulta()
        return super().get_queryset(request)

    def save_model(self, request, obj, form, change):
        """Fase 17 Estado é alterável SOMENTE pelo
        Django Admin. O `ModelForm` padrão, sozinho, faria só um `UPDATE`
        silencioso na coluna `estado` — sem gerar o `Acompanhamento`
        automático que a Fase 3 promete para toda mudança de situação de um
        processo. Quando o form indica que `estado` mudou (`changed_data`,
        populado pelo próprio Django a partir do valor inicial do form vs. o
        POST), rotear por `services.alterar_estado` ANTES do save padrão:
        essa chamada já persiste `estado`/`atualizado_em` e grava o
        `Acompanhamento` auditável. Depois, `refresh_from_db(fields=
        ["atualizado_em"])` traz só esse campo (excluído do `ModelForm`
        porque `auto_now=True` o torna `editable=False` — o form nunca o
        carrega) para `obj`, evitando que o `super().save_model()` seguinte
        grave um valor desatualizado; e então o save padrão grava os DEMAIS
        campos que o form também tenha mudado na mesma submissão. Refresh
        deliberadamente restrito a `atualizado_em` (não a linha inteira):
        um `refresh_from_db()` sem `fields=` sobrescreveria em memória
        qualquer OUTRO campo que o form tenha alterado na mesma submissão
        (ainda não persistido nesse ponto), descartando silenciosamente a
        edição simultânea do usuário, bug de perda de dado que a
        redação literal do `<action>` do plano introduziria.
        Criação nova (`change=False`) ou edição sem mexer em `estado` seguem
        o caminho padrão, sem chamar `alterar_estado`.
        """
        if change and "estado" in form.changed_data:
            services.alterar_estado(
                processo_id=obj.pk,
                usuario=request.user,
                estado_novo=obj.estado,
            )
            obj.refresh_from_db(fields=["atualizado_em"])
        super().save_model(request, obj, form, change)
        # 29/09/2026 — desmarcar "situação manual" devolve o item às regras automáticas: registra no
        # histórico quem liberou e recalcula a situação na hora.
        if change and "situacao_manual" in form.changed_data and not obj.situacao_manual:
            services.liberar_situacao_automatica(
                processo_id=obj.pk, usuario=request.user, ignorar_exercicio_fechado=True
            )
            obj.refresh_from_db()
        elif change and "situacao_manual" in form.changed_data and obj.situacao_manual:
            services.atualizar_situacao_regra(
                type(obj).objects.select_related("tipo", "exercicio").get(pk=obj.pk), request.user
            )
            obj.refresh_from_db()

    def get_actions(self, request):
        """"Atualizar com o SEI" some da lista de ações em
        massa para qualquer staff não-superusuário. `PcaAdminSite.
        has_permission` (core/admin_site.py) já restringe o Admin
        INTEIRO a superusuário, então nenhum staff comum chega até aqui de
        verdade — esta checagem é defesa em profundidade (spec §3.7/§9), não
        a única barreira, documentada para o próximo leitor não achar
        redundância sem explicação."""
        acoes = super().get_actions(request)
        if not request.user.is_superuser:
            acoes.pop("atualizar_com_o_sei", None)
            acoes.pop("reindexar_assistente", None)
        return acoes

    @admin.action(description="Atualizar com o SEI")
    def atualizar_com_o_sei(self, request, queryset):
        """spec §3.7 — único disparo sob demanda do robô
        SEI. Só GRAVA um pedido por item em `data/sei/pedidos/`; nunca
        consulta o SEI, nunca grava `Processo`/`Acompanhamento` — quem
        consulta e aplica é `sei_atender` (serviço `robo` permanente)."""
        if not request.user.is_superuser:
            # Defesa em profundidade (spec §3.7/§9): 403 mesmo que o Admin
            # inteiro já seja só-superusuário — a view da própria
            # ação recusa também, independente do gate de site.
            raise PermissionDenied

        from apps.pca.sei import execucoes  # import local — hábito de todo código que toca apps.pca.sei.*

        registrados = 0
        ignorados = 0
        for processo in queryset:
            if processo.estado == Estado.CANCELADO or not processo.numeros_sei.exists():
                ignorados += 1
                continue
            execucoes.gravar_pedido(
                item_pca=processo.item_pca,
                exercicio=processo.exercicio.ano,
                solicitado_por=request.user.pk,
            )
            registrados += 1

        mensagem = (
            f"{registrados} pedido(s) registrado(s). O robô atende um por vez; "
            "o resultado aparece na linha do tempo do item e em Sincronização "
            "com o SEI, no Início."
        )
        if ignorados:
            mensagem += f" {ignorados} item(ns) ignorado(s) (cancelado ou sem nº SEI)."
        self.message_user(request, mensagem)

    @admin.action(description="Reindexar assistente")
    def reindexar_assistente(self, request, queryset):
        """Fase 39 — mesmo padrão de "Atualizar com o SEI": só
        GRAVA um pedido em `data/ia/pedidos/`; nunca indexa dentro do
        request. A ação é GLOBAL (independe do `queryset` selecionado —
        Django Admin exige ao menos uma linha marcada para habilitar a
        barra de ações em massa, mas reindexar o assistente não tem
        relação nenhuma com processos específicos)."""
        if not request.user.is_superuser:
            raise PermissionDenied

        if not settings.IA_API_KEY:
            self.message_user(
                request,
                "Assistente não configurado (IA_API_KEY ausente) — nada foi agendado.",
                level=messages.WARNING,
            )
            return

        from apps.assistente import fila  # import local — hábito de todo código que toca apps.assistente.*

        fila.gravar_pedido_reindexacao(
            solicitado_por=request.user.pk, completo=False, agora=timezone.now()
        )
        self.message_user(
            request,
            "Reindexação do assistente agendada. O robô executa quando não houver "
            "pedido SEI pendente; acompanhe em data/ia/pedidos/.",
        )

    def sei_ultima_consulta(self, obj):
        """Coluna somente-leitura (spec §3.7) — lida de `data/sei/
        ultima_consulta.json` via `execucoes.carregar_ultima_consulta()`,
        nunca de query por linha (não vem do banco, sem `admin_order_field`
        nem `list_editable`). QA 30/09 (periferia nº10) — lê do cache
        gravado por `get_queryset` (1x por request), não do disco por
        linha."""
        cache = getattr(self, "_cache_sei_ultima_consulta", None)
        if cache is None:
            cache = execucoes.carregar_ultima_consulta()
        dados = cache.get(execucoes.chave_item(obj.item_pca, obj.exercicio.ano))
        if not dados:
            return "—"
        return f"{dados['data_hora']} ({dados['resultado']})"

    sei_ultima_consulta.short_description = "SEI: última consulta"

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
            pks = list(changelist.queryset.values_list("pk", flat=True))
        except (IncorrectLookupParameters, OverflowError):
            # QA 30/09/2026 (achado INFO I1) — um `item_pca__in=` com ID de
            # 20+ dígitos levantava `OverflowError` na AVALIAÇÃO do
            # queryset, que antes ficava fora deste `try`.
            return navegacao
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

    # Admin passou a ser edição/exclusão nativa em tudo, por
    # pedido do usuário. `get_actions`/`get_deleted_objects` (que removiam
    # `delete_selected` e descartavam `perms_needed`) saíram — o collector
    # nativo do Django volta a computar a cascata de verdade.


@admin.register(Acompanhamento)
class AcompanhamentoAdmin(admin.ModelAdmin):
    # (Fase 11) — a promessa é imutável na web; correção de
    # `prazo_prometido`/`evento` é EXCLUSIVA daqui. Nenhum dos dois entra em
    # `readonly_fields`/`exclude`: o ModelForm padrão já os grava.
    list_display = (
        "processo", "referencia_data", "tipo_evento", "situacao",
        "prazo_prometido", "evento",
    )
    list_filter = ("tipo_evento", "situacao")
    search_fields = ("processo__item_pca", "situacao_informada", "evento")
    ordering = ("processo", "-referencia_data")
    list_select_related = ("processo", "situacao")

    # (Fase 11) já previa "correção ou remoção somente
    # pelo Django Admin, nunca pela interface" — o plano que implementou shippou mais restritivo do que a decisão pedia,
    # fixando `has_delete_permission` em `False` também para o Admin. Este
    # método NÃO é sobrescrito de propósito: cai no comportamento padrão do
    # `ModelAdmin` (`request.user.has_perm("pca.delete_acompanhamento")`),
    # espelhando `ProcessoAdmin`. A trilha de auditoria (LGPD) não fica mais
    # fraca — `HistoricalRecords()` com `HistoryRequestMiddleware` ativo grava
    # automaticamente `history_type="-"` com o `history_user` no delete; só a
    # linha viva (que alimenta `n_reunioes`/timeline) deixa de existir.
    # Reversão rastreada; get_actions residual (ainda
    # tirava delete_selected) removido.


@admin.register(Reuniao)
class ReuniaoAdmin(admin.ModelAdmin):
    """Superfície mínima de gestão da reunião no MVP: abrir/fechar é alterar `situacao`. Tela própria de condução da
    reunião, se necessária, vem depois — a entidade nasce com o mínimo.

    Exclusão (individual ou em massa) é governada por `pca.delete_reuniao`
    (superuser por padrão) — não há mais `has_delete_permission`
    hardcoded. Apagar uma Reuniao com Acompanhamento vinculado continua
    recusado, mas pela tela nativa de objetos protegidos do Django
    (`on_delete=PROTECT` em `Acompanhamento.reuniao`), não por permissão.
    """

    list_display = ("data", "exercicio", "condutor", "situacao")
    list_filter = ("exercicio", "situacao")
    ordering = ("-data",)
    list_select_related = ("condutor", "exercicio")


@admin.register(RelatorioCongelado)
class RelatorioCongeladoAdmin(admin.ModelAdmin):
    """Só leitura, até para superusuário: a versão congelada do relatório da
    reunião é imutável. Sem add/change/delete (o que também remove a ação "excluir selecionados"); os fatos
    (JSON enorme) ficam fora do formulário."""

    list_display = ("reuniao", "versao", "origem", "hash_curto", "corte", "criado_em", "criado_por")
    list_filter = ("origem",)
    exclude = ("dados",)
    list_select_related = ("reuniao", "criado_por")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ProcessoSEI)
class ProcessoSEIAdmin(admin.ModelAdmin):
    list_display = ("processo", "numero_sei", "link_sei")
    search_fields = ("processo__item_pca", "numero_sei")
    list_select_related = ("processo",)

    @admin.display(description="Link SEI")
    def link_sei(self, obj):
        """Mesmo mapa de `execucoes.ler_links()` da
        tabela/ficha. Admin não passa pelo verificador dsgov (UI própria do
        Django), sem risco de quebrar guardas."""
        entrada = execucoes.ler_links().get("processos", {}).get(obj.numero_sei)
        id_procedimento = entrada.get("id_procedimento") if entrada else None
        if not id_procedimento:
            return "—"
        url = (
            "https://sei.cfc.org.br/sei/controlador.php?"
            f"acao=procedimento_trabalhar&id_procedimento={id_procedimento}"
        )
        return format_html('<a href="{}" target="_blank" rel="noopener">abrir</a>', url)


class HistoricoSomenteLeituraAdmin(admin.ModelAdmin):
    """Trilha de auditoria: sem adicionar linha histórica pelo Admin
    (não faz sentido criar histórico à mão); editar e apagar passam a ser
    governados pela permissão nativa do model, por pedido do usuário
criar uma linha de histórico continua sem sentido,
    corrigir ou remover uma não. `list_select_related` evita 1 SELECT de
    usuário por linha."""

    list_display = ("id", "history_date", "history_type", "history_user")
    list_select_related = ("history_user",)
    ordering = ("-history_date",)

    def has_add_permission(self, request):
        return False


class HistoricalProcessoAdmin(HistoricoSomenteLeituraAdmin):
    """Consulta do histórico imutável de processos."""

    admin_grupo = "Auditoria e histórico"
    list_display = ("history_date", "history_type", "history_user", "item_pca")
    list_filter = ("history_date", "history_type", "history_user")
    search_fields = ("=item_pca",)


class HistoricalAcompanhamentoAdmin(HistoricoSomenteLeituraAdmin):
    """Consulta do histórico imutável de acompanhamentos."""

    admin_grupo = "Auditoria e histórico"
    list_display = ("history_date", "history_type", "history_user", "processo")
    list_filter = ("history_date", "history_type", "history_user")
    search_fields = ("=processo__item_pca", "situacao_informada")
    list_select_related = ("history_user", "processo")


class HistoricalEventoFinanceiroAdmin(HistoricoSomenteLeituraAdmin):
    """Consulta do histórico imutável de eventos financeiros (Fase
    36/, mesmo molde de `HistoricalProcessoAdmin`/
    `HistoricalAcompanhamentoAdmin` acima)."""

    admin_grupo = "Auditoria e histórico"
    list_display = ("processo", "history_date", "history_type", "history_user")
    list_filter = ("history_date", "history_type", "history_user")
    list_select_related = ("history_user", "processo")


admin.site.register(Processo.history.model, HistoricalProcessoAdmin)
admin.site.register(Acompanhamento.history.model, HistoricalAcompanhamentoAdmin)
admin.site.register(EventoFinanceiro.history.model, HistoricalEventoFinanceiroAdmin)


@admin.register(FichaContratacao)
class FichaContratacaoAdmin(admin.ModelAdmin):
    """Ficha da contratação gravada pela extensão SEI Pro (`PUT
    /api/sei/ficha`) — para conferir e auditar o que a extensão grava
    enquanto não há tela própria (10/10/2026). O conteúdo é da extensão.
    Superusuário edita/apaga como qualquer registro (regra de 11/09/2026); toda edição pelo Admin SOBE a versão e registra o
    autor, para a extensão receber 409 em vez de sobrescrever."""

    list_display = ("processo", "versao", "atualizado_por", "atualizado_em")
    list_select_related = ("processo__exercicio", "atualizado_por")
    list_filter = ("processo__exercicio",)
    search_fields = ("=processo__item_pca", "processo__descricao_objeto")
    ordering = ("-atualizado_em",)
    fields = ("processo", "versao", "atualizado_por", "atualizado_em", "dados")
    readonly_fields = ("processo", "versao", "atualizado_por", "atualizado_em")

    def has_add_permission(self, request):
        return False  # a ficha nasce pela extensão (PUT com versao 0)

    def save_model(self, request, obj, form, change):
        if change and "dados" in form.changed_data:
            obj.versao += 1
            obj.atualizado_por = request.user
        super().save_model(request, obj, form, change)


class HistoricalFichaContratacaoAdmin(HistoricoSomenteLeituraAdmin):
    """Versões anteriores da ficha da contratação (mesmo molde dos demais
    históricos)."""

    admin_grupo = "Auditoria e histórico"
    list_display = ("history_date", "history_type", "history_user", "processo", "versao")
    list_filter = ("history_date", "history_type")
    search_fields = ("=processo__item_pca",)
    list_select_related = ("history_user", "processo")


admin.site.register(FichaContratacao.history.model, HistoricalFichaContratacaoAdmin)


@admin.register(EventoFinanceiro)
class EventoFinanceiroAdmin(admin.ModelAdmin):
    """Fase 36 — lista própria além do inline em
    `ProcessoAdmin`, espelhando `RascunhoItemVirada` (registrado tanto
    como inline quanto como model próprio logo abaixo)."""

    list_display = ("processo", "data", "tipo", "natureza", "valor", "origem")
    list_filter = ("tipo", "natureza", "origem")
    search_fields = ("=processo__item_pca", "protocolo_sei")
    list_select_related = ("processo",)


@admin.register(CenarioFluxo)
class CenarioFluxoAdmin(admin.ModelAdmin):
    """Fase 37 (spec §3.2/§8) — leitura/edição manual pelo
    Admin; a tela própria de cenários salvos vem no plano.
    `simple_history` já cobre a trilha, sem inline de histórico próprio
    (mesmo padrão de `EventoFinanceiro`)."""

    list_display = ("nome", "exercicio", "autor", "atualizado_em")
    list_filter = ("exercicio",)
    list_select_related = ("exercicio", "autor")
    readonly_fields = ("criado_em", "atualizado_em")


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
        "valor_estimado_editado", "mes_previsto_editado_nome",
    )
    list_select_related = ("rascunho", "processo_origem")
    search_fields = ("processo_origem__item_pca",)
    ordering = ("rascunho", "ordem")

    @admin.display(description="Mês previsto")
    def mes_previsto_editado_nome(self, obj):
        from apps.pca.filtros import NOMES_MES

        return NOMES_MES.get(obj.mes_previsto_editado, "—")


@admin.register(EventoImportacao)
class EventoImportacaoAdmin(admin.ModelAdmin):
    """Rastro imutável de quem confirmou uma importação pela tela."""

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
