"""Telas das Solicitações das unidades (Fase 43).

Leitura e escrita sempre por `services.py` (que confere alçada, vínculo com a unidade e aplica o
efeito no `Processo` pelos serviços do `apps.pca`). Escrita é POST-redirect-GET com
`django.contrib.messages`; erro de negócio volta para a mesma tela, no formulário. As duas cascas
(DSGov e Tabler) usam estas mesmas views: só os templates mudam.
"""

from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Prefetch
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from apps.catalogo.models import SituacaoExercicio
from apps.pca.models import Estado, Processo

from . import apresentacao, regras, services
from .forms import AlteracaoForm, DecisaoForm, InclusaoForm, SelecionarItemForm
from .models import ParteSolicitacao, Solicitacao
from .regras import Campo, EstadoParte, EstadoSolicitacao
from .services import ErroSolicitacao, JaEncerrada, SemPermissao

# Teto de linhas das listagens "Minhas solicitações": as mais recentes; acima disso a tela avisa.
LIMITE_LISTAGEM = 200

def _pode_solicitar(usuario) -> bool:
    return usuario.has_perm(services.PERM_SOLICITAR)


def _exigir_solicitante(request):
    if not _pode_solicitar(request.user):
        raise PermissionDenied


def _resposta(request, modelo, contexto):
    resposta = render(request, modelo, contexto)
    resposta["Cache-Control"] = "private, no-store"
    return resposta


def _itens_das_unidades(unidades):
    """Itens ativos das unidades, do exercício aberto, que aceitam ao menos um pedido."""
    itens = (
        Processo.objects.para_listagem()
        .filter(
            exercicio__situacao=SituacaoExercicio.ABERTO,
            estado=Estado.ATIVO,
            unidade_organizacional__in=unidades,
        )
        .order_by("exercicio__ano", "item_pca")
    )
    return [item for item in itens if services.campos_aceitos_do_item(item)]


def _item_da_referencia(referencia, unidades_ids):
    """`?processo=<ano>/<item>` → o item (com as leituras de situação). 404 se a referência não
    existe; 403 se o item não é de uma unidade do usuário."""
    try:
        ano, numero = (int(parte) for parte in referencia.split("/"))
    except ValueError:
        raise Http404 from None
    item = get_object_or_404(Processo.objects.para_listagem(), exercicio__ano=ano, item_pca=numero)
    if item.unidade_organizacional_id not in unidades_ids:
        raise PermissionDenied
    return item


# --- Nova solicitação ----------------------------------------------------------------------


@require_http_methods(["GET", "HEAD", "POST"])
def nova_view(request):
    _exigir_solicitante(request)
    unidades = list(services.unidades_do_usuario(request.user))
    contexto = {
        "trilha": [("Solicitações", reverse("solicitacoes:minhas")), ("Nova solicitação", None)],
        "sem_unidade": not unidades,
        "url_nova": reverse("solicitacoes:nova"),
        "url_inclusao": f"{reverse('solicitacoes:nova')}?tipo=inclusao",
    }
    if request.GET.get("tipo") == "inclusao":
        return _nova_inclusao(request, unidades, contexto)
    return _nova_alteracao(request, unidades, contexto)


def _nova_alteracao(request, unidades, contexto):
    contexto["modo"] = "alteracao"
    if not unidades:
        return _resposta(request, "solicitacoes/nova.html", contexto)

    referencia = request.GET.get("processo", "").strip()
    if not referencia:
        contexto["form_item"] = SelecionarItemForm(itens=_itens_das_unidades(unidades))
        return _resposta(request, "solicitacoes/nova.html", contexto)

    item = _item_da_referencia(referencia, {unidade.pk for unidade in unidades})
    campos = services.campos_aceitos_do_item(item)
    pendentes = set(
        ParteSolicitacao.objects.filter(processo=item, estado=EstadoParte.PENDENTE).values_list(
            "campo", flat=True
        )
    )
    if Campo.CANCELAMENTO in pendentes:
        livres = ()
    else:
        livres = tuple(campo for campo in campos if campo.value not in pendentes)
    contexto.update(
        {
            "item": apresentacao.resumo_do_item(item),
            "form_item": SelecionarItemForm(
                itens=_itens_das_unidades(unidades), initial={"processo": referencia}
            ),
            "em_analise": [Campo(campo).label for campo in sorted(pendentes)],
            "cancelamento_em_analise": Campo.CANCELAMENTO in pendentes,
            "item_fechado": (
                "" if campos else regras.motivo_do_item_fechado(
                    estado=item.estado,
                    situacao_efetiva=item.situacao_efetiva,
                    exercicio_aberto=item.exercicio.situacao == SituacaoExercicio.ABERTO,
                )
            ),
        }
    )
    if not livres:
        return _resposta(request, "solicitacoes/nova.html", contexto)

    if request.method == "POST":
        form = AlteracaoForm(request.POST, campos_aceitos=livres)
        if form.is_valid():
            try:
                solicitacao = services.criar_solicitacao(
                    usuario=request.user,
                    processo_id=item.pk,
                    justificativa=form.cleaned_data["justificativa"],
                    pedidos=form.pedidos,
                    numero_sei=form.cleaned_data["numero_sei"],
                )
            except SemPermissao:
                raise PermissionDenied from None
            except ErroSolicitacao as erro:
                form.add_error(None, str(erro))
            else:
                messages.success(
                    request,
                    f"Solicitação {solicitacao.codigo} enviada. Você acompanha a decisão em "
                    "Minhas solicitações.",
                )
                return redirect(apresentacao.url_da_solicitacao(solicitacao))
    else:
        form = AlteracaoForm(campos_aceitos=livres)
    contexto.update(
        {
            "form": form,
            "linhas": apresentacao.linhas_do_pedido(item, livres, form),
            "pode_cancelar": Campo.CANCELAMENTO in livres,
            "avisos": apresentacao.avisos_de_alcada(livres),
            "url_cancelar": reverse("pca:detalhe_processo", args=[item.exercicio.ano, item.item_pca]),
        }
    )
    return _resposta(request, "solicitacoes/nova.html", contexto)


def _nova_inclusao(request, unidades, contexto):
    contexto["modo"] = "inclusao"
    if not unidades:
        return _resposta(request, "solicitacoes/nova.html", contexto)
    if request.method == "POST":
        form = InclusaoForm(request.POST, unidades=unidades)
        if form.is_valid():
            dados = form.cleaned_data
            try:
                solicitacao = services.criar_inclusao(
                    usuario=request.user,
                    unidade_id=int(dados["unidade"]),
                    descricao_objeto=dados["descricao_objeto"],
                    tipo_id=int(dados["tipo"]),
                    categoria_id=int(dados["categoria"]),
                    valor_estimado=dados["valor_estimado"],
                    mes_previsto=dados["mes_previsto"],
                    prazo_entrega=dados["prazo_entrega"],
                    justificativa=dados["justificativa"],
                    numero_sei=dados["numero_sei"],
                )
            except SemPermissao:
                raise PermissionDenied from None
            except ErroSolicitacao as erro:
                form.add_error(None, str(erro))
            else:
                messages.success(
                    request,
                    f"Solicitação {solicitacao.codigo} enviada. O item só recebe número no PCA "
                    "quando a diretoria aprovar a inclusão.",
                )
                return redirect(apresentacao.url_da_solicitacao(solicitacao))
    else:
        form = InclusaoForm(unidades=unidades)
    contexto.update(
        {
            "form": form,
            "avisos": apresentacao.avisos_de_alcada([Campo.INCLUSAO]),
            "url_cancelar": reverse("solicitacoes:minhas"),
        }
    )
    return _resposta(request, "solicitacoes/nova.html", contexto)


# --- Listagens -----------------------------------------------------------------------------


def _solicitacoes_com_partes(queryset):
    return queryset.select_related("unidade", "solicitante", "exercicio", "processo").prefetch_related(
        Prefetch(
            "partes",
            queryset=ParteSolicitacao.objects.select_related("decidido_por").order_by("id"),
        )
    )


@require_http_methods(["GET", "HEAD"])
def minhas_view(request):
    """Solicitações das unidades do usuário; equipe e diretoria veem as de todas as unidades."""
    alcadas = services.alcadas_do_usuario(request.user)
    if not _pode_solicitar(request.user) and not alcadas:
        raise PermissionDenied
    todas_as_unidades = bool(alcadas)
    consulta = _solicitacoes_com_partes(services.solicitacoes_visiveis(request.user))
    lidas = list(consulta[: LIMITE_LISTAGEM + 1])
    truncada = len(lidas) > LIMITE_LISTAGEM
    solicitacoes = [apresentacao.solicitacao_para_tela(s, alcadas) for s in lidas[:LIMITE_LISTAGEM]]

    # Desistir: só quem pede e é da unidade (a regra final é de `services.desistir`).
    ids_das_unidades = set(services.unidades_do_usuario(request.user).values_list("pk", flat=True))
    pode_pedir = _pode_solicitar(request.user)
    for s in solicitacoes:
        s["pode_desistir"] = (
            s["pendente"] and pode_pedir
            and (s["obj"].unidade_id in ids_das_unidades or request.user.is_superuser)
        )
        s["url_desistir"] = reverse("solicitacoes:desistir", args=[s["obj"].ano, s["obj"].numero])
    contexto = {
        "trilha": [("Solicitações", None)],
        "titulo": "Todas as solicitações" if todas_as_unidades else "Minhas solicitações",
        "todas_as_unidades": todas_as_unidades,
        "pode_pedir": pode_pedir,
        "abas": [
            ("todas", "Todas", solicitacoes),
            ("analise", "Em análise", [s for s in solicitacoes if s["pendente"]]),
            ("decididas", "Decididas", [s for s in solicitacoes if not s["pendente"]]),
        ],
        "truncada": truncada,
        "limite": LIMITE_LISTAGEM,
        "url_nova": reverse("solicitacoes:nova"),
    }
    return _resposta(request, "solicitacoes/minhas.html", contexto)


@require_http_methods(["GET", "HEAD"])
def avaliar_view(request):
    """Fila "Para avaliar": só as partes da alçada de quem está logado."""
    alcadas = services.alcadas_do_usuario(request.user)
    if not alcadas:
        raise PermissionDenied
    fila = apresentacao.linhas_da_fila(services.partes_para_avaliar(request.user))
    contexto = {
        "trilha": [("Solicitações", reverse("solicitacoes:minhas")), ("Para avaliar", None)],
        "alcadas": " e ".join(
            regras.Alcada(a).label for a in (regras.Alcada.EQUIPE, regras.Alcada.DIRETORIA) if a in alcadas
        ),
        "limite_parada": regras.LIMITE_PARADA_DIAS_UTEIS,
        "kpis": [
            {
                "rotulo": "Em análise", "valor": fila["pendentes"], "icone": "fas fa-inbox", "tom": "alerta",
                "apoio": "partes da sua alçada aguardando decisão",
            },
            {
                "rotulo": "Paradas", "valor": fila["paradas"], "icone": "fas fa-hourglass-half",
                "tom": "erro" if fila["paradas"] else "neutro",
                "apoio": f"há mais de {regras.LIMITE_PARADA_DIAS_UTEIS} dias úteis",
            },
            {
                "rotulo": "Fora do exercício", "valor": fila["fora_do_exercicio"], "icone": "fas fa-calendar-alt",
                "tom": "info", "apoio": "prazo pedido depois de 31/12",
            },
        ],
        **fila,
    }
    return _resposta(request, "solicitacoes/avaliar.html", contexto)


# --- Detalhe e decisão ---------------------------------------------------------------------


def _solicitacao_visivel(request, ano, numero):
    consulta = _solicitacoes_com_partes(services.solicitacoes_visiveis(request.user))
    return get_object_or_404(consulta, ano=ano, numero=numero)


def _renderizar_detalhe(request, solicitacao, formularios=None):
    formularios = formularios or {}
    alcadas = services.alcadas_do_usuario(request.user)
    partes = []
    for parte in solicitacao.partes.all():
        tela = apresentacao.parte_para_tela(parte, alcadas)
        if tela["pode_decidir"]:
            tela["form"] = formularios.get(parte.pk) or DecisaoForm(
                campo=parte.campo, prefix=f"parte{parte.pk}"
            )
            tela["url_decidir"] = reverse(
                "solicitacoes:decidir", args=[solicitacao.ano, solicitacao.numero, parte.pk]
            )
        partes.append(tela)
    resumo = apresentacao.solicitacao_para_tela(solicitacao, alcadas)
    pode_desistir = (
        solicitacao.estado == EstadoSolicitacao.PENDENTE
        and _pode_solicitar(request.user)
        and (
            request.user.is_superuser
            or services.unidades_do_usuario(request.user).filter(pk=solicitacao.unidade_id).exists()
        )
    )
    contexto = {
        "trilha": [
            ("Solicitações", reverse("solicitacoes:minhas")),
            (f"Solicitação {solicitacao.codigo}", None),
        ],
        "s": resumo,
        "partes": partes,
        "justificativa": solicitacao.justificativa,
        "numero_sei": solicitacao.numero_sei,
        "inclusao": (
            apresentacao.linhas_da_inclusao(solicitacao) if solicitacao.tipo == "inclusao" else []
        ),
        "eventos": apresentacao.trilha_da_solicitacao(solicitacao, solicitacao.partes.all()),
        "pode_desistir": pode_desistir,
        "url_desistir": reverse("solicitacoes:desistir", args=[solicitacao.ano, solicitacao.numero]),
        "url_minhas": reverse("solicitacoes:minhas"),
    }
    return _resposta(request, "solicitacoes/detalhe.html", contexto)


@require_http_methods(["GET", "HEAD"])
def detalhe_view(request, ano, numero):
    return _renderizar_detalhe(request, _solicitacao_visivel(request, ano, numero))


@require_POST
def decidir_view(request, ano, numero, parte_id):
    solicitacao = _solicitacao_visivel(request, ano, numero)
    parte = next((p for p in solicitacao.partes.all() if p.pk == parte_id), None)
    if parte is None:
        raise Http404
    url = apresentacao.url_da_solicitacao(solicitacao)
    form = DecisaoForm(request.POST, campo=parte.campo, prefix=f"parte{parte.pk}")
    if form.is_valid():
        dados = form.cleaned_data
        try:
            services.decidir_parte(
                parte_id=parte.pk,
                usuario=request.user,
                decisao=dados["decisao"],
                valor_ajuste=dados.get("valor_ajuste"),
                motivo=dados.get("motivo", ""),
            )
        except SemPermissao:
            raise PermissionDenied from None
        except JaEncerrada as erro:
            messages.error(request, str(erro))
            return redirect(url)
        except ErroSolicitacao as erro:
            form.add_error(None, str(erro))
        else:
            messages.success(
                request, f"{Campo(parte.campo).label}: decisão registrada na solicitação {solicitacao.codigo}."
            )
            return redirect(url)
    return _renderizar_detalhe(request, solicitacao, {parte.pk: form})


@require_POST
def desistir_view(request, ano, numero):
    solicitacao = _solicitacao_visivel(request, ano, numero)
    try:
        services.desistir(solicitacao_id=solicitacao.pk, usuario=request.user)
    except SemPermissao:
        raise PermissionDenied from None
    except ErroSolicitacao as erro:
        messages.error(request, str(erro))
    else:
        messages.success(
            request,
            f"Você desistiu da solicitação {solicitacao.codigo}. Se ainda precisar, faça um novo pedido.",
        )
    return redirect(apresentacao.url_da_solicitacao(solicitacao))
