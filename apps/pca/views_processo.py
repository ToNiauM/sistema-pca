"""Views de tela própria do processo: páginas de detalhe/formulário/
transição, mantendo como único modal do sistema o "Registrar
acompanhamento".

Módulo separado de views.py, que já era grande demais; urls.py importa os
dois módulos."""

from django.contrib.auth.decorators import permission_required
from django.contrib import messages
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.timezone import localdate

from apps.catalogo.models import Exercicio, SituacaoExercicio
from apps.pca.filtros import querystring_filtros, querystring_tabela, queryset_filtrado
from apps.pca.forms import (
    AcompanhamentoForm,
    ProcessoForm,
    ProcessoSEIFormSet,
    TransicaoForm,
    ajuda_novo_prazo,
)
from apps.pca.models import Estado, Processo, Situacao
from apps.pca.relatorio_movimentacao import compromisso_vigente, prazo_atual_ficha
from apps.pca.rotulos import ROTULOS
from apps.pca import services
from apps.pca.views import (
    CAMPOS_EDITAVEIS_PROCESSO,
    SECOES_FORMULARIO_PROCESSO,
    _carregar_processo_modal,
    _ordenar_para_tabela,
    _processo_nao_encontrado,
    _tipo_widget,
)

def _com_querystring(url, querystring):
    """Devolve url?querystring se querystring for truthy, senão url sem
    alteração."""
    return f"{url}?{querystring}" if querystring else url


def _querystring_retorno(request):
    """Único ponto que decide "qual querystring esta view deve preservar":
    GET lê da URL; POST lê do campo oculto querystring_retorno do
    formulário, que sobrevive quando o form tem action/hx-post explícito."""
    if request.method == "POST":
        return request.POST.get("querystring_retorno", "")
    return querystring_tabela(request.GET)


# mapa (eixo, valor) -> chave semântica de classe_status. Cancelado tem
# prioridade sobre qualquer Situação gravada
_CHAVE_STATUS_SITUACAO = {
    Situacao.NO_PRAZO: "alerta",
    Situacao.ATRASADO: "erro",
    Situacao.EM_TRAMITACAO: "info",
    Situacao.CONCLUIDO: "sucesso",
}


def _status_processo(processo):
    if processo.estado == Estado.CANCELADO:
        return "Cancelado", "cancelado"
    rotulo = Situacao(processo.situacao_efetiva).label
    chave = _CHAVE_STATUS_SITUACAO.get(processo.situacao_efetiva, "info")
    return rotulo, chave


def _sem_permissao_de_edicao(request):
    """Falta a permissão de escrita?"""
    return not request.user.has_perm("pca.editar_pca")


def _vizinhos_na_ordem_da_tabela(request, processo):
    """(anterior, proximo) do processo na ordem que a tabela está exibindo."""
    qs = _ordenar_para_tabela(request, queryset_filtrado(request))
    linhas = list(qs.values_list("pk", "exercicio__ano", "item_pca"))
    try:
        indice = [linha[0] for linha in linhas].index(processo.pk)
    except ValueError:
        return None, None
    anterior = linhas[indice - 1] if indice > 0 else None
    proximo = linhas[indice + 1] if indice + 1 < len(linhas) else None
    para_dict = lambda linha: (
        {"ano": linha[1], "item_pca": linha[2]} if linha else None
    )
    return para_dict(anterior), para_dict(proximo)


def _valor_exibicao_campo(processo, campo):
    """Rótulo humano do valor de um campo do model, para a ficha do
    processo (pares dizem "Não informado", nunca "-"; tabelas continuam
    com traço). Reaproveita _tipo_widget em vez de reinventar um segundo
    entendimento de como cada campo aparece."""
    valor = getattr(processo, campo)
    if valor in (None, ""):
        return "Não informado"
    widget = _tipo_widget(campo)
    if widget == "boolean":
        return "Sim" if valor else "Não"
    if widget == "select_choice":
        return getattr(processo, f"get_{campo}_display")()
    if widget == "money":
        from core.templatetags.dsgov import moeda

        return moeda(valor)
    if widget == "date":
        from core.templatetags.dsgov import data_br

        return data_br(valor)
    return str(valor)


# os 3 canais de publicação ganham um selo "pendente há N dias" quando
# publicacao_pendente está ligada e o canal específico ainda não foi
# lançado; a contagem de dias é aritmética em memória
_ROTULO_PENDENCIA_PUBLICACAO = {
    "data_lancamento_spw": "SPW",
    "data_lancamento_wordpress": "WordPress",
    "data_lancamento_dados_abertos": "Dados Abertos",
}


def _pendencia_publicacao(processo, campo):
    rotulo = _ROTULO_PENDENCIA_PUBLICACAO.get(campo)
    if rotulo is None or not processo.publicacao_pendente or getattr(processo, campo):
        return None
    from django.utils.timezone import localdate

    dias = (localdate() - processo.data_assinatura_contrato).days
    return f"{rotulo} pendente há {dias} dia{'s' if dias != 1 else ''}"


# VALOR PREVISTO/VALOR CONTRATADO viram quadros de destaque da ficha, não
# pares repetidos dentro de "Planejamento"/"Execução contratual"
_CAMPOS_QUADRO_FICHA = {"valor_estimado", "valor_contratado"}


def _rotulo_campo(campo):
    """Rótulo de tela com fallback ao verbose_name do model."""
    return ROTULOS.get(campo, Processo._meta.get_field(campo).verbose_name)


def _valor_quadro_monetario(valor):
    """Quadros financeiros da ficha: só None vira "Não informado"; zero é
    R$ 0,00 — nulo e zero nunca se confundem."""
    if valor is None:
        return "Não informado"
    from core.templatetags.dsgov import moeda

    return moeda(valor)


def _linha_prazo_inicial(processo):
    """O par "Prazo inicial:" da ficha usa a mesma anotação COALESCE de
    prazo_inicial e indica a procedência quando a data veio do histórico:
    "(primeiro prazo registrado)" em texto secundário. Só na ficha — tabela
    e XLSX mostram a data pura."""
    valor_data = processo.prazo_inicial
    if valor_data is None:
        valor, complemento = "Não informado", ""
    else:
        from core.templatetags.dsgov import data_br

        valor = data_br(valor_data)
        complemento = (
            "(primeiro prazo registrado)" if processo.prazo_entrega is None else ""
        )
    return {
        "pendencia": None,
        "rotulo": _rotulo_campo("prazo_entrega"),
        "valor": valor,
        "complemento": complemento,
        "largo": False,
    }


def _secoes_detalhe(processo):
    """Campos agrupados por SECOES_FORMULARIO_PROCESSO, resolvidos como
    pares "Rótulo: valor" da ficha, o mesmo agrupamento do formulário em
    modo leitura.

    O detalhe é estritamente de leitura para números SEI: a linha "Números
    SEI" entra na seção "Processo" sem formulário nem controle de remoção;
    incluir/excluir só acontece no fieldset Processo do formulário. Valor
    ausente aqui é sempre "Não informado", nunca "-"."""
    secoes = []
    for titulo, campos in SECOES_FORMULARIO_PROCESSO:
        linhas = []
        for campo in campos:
            if campo not in CAMPOS_EDITAVEIS_PROCESSO:
                continue
            if campo in _CAMPOS_QUADRO_FICHA:
                continue
            if campo == "prazo_entrega":
                linhas.append(_linha_prazo_inicial(processo))
                continue
            linhas.append(
                {
                    "pendencia": _pendencia_publicacao(processo, campo),
                    "rotulo": _rotulo_campo(campo),
                    "valor": _valor_exibicao_campo(processo, campo),
                    "complemento": "",
                    "largo": _tipo_widget(campo) == "textarea",
                }
            )
        if titulo == "Processo":
            numeros = [sei.numero_sei for sei in sorted(
                processo.numeros_sei.all(), key=lambda sei: sei.id
            )]
            linhas.append(
                {
                    "pendencia": None,
                    "rotulo": "Números SEI",
                    "valor": ", ".join(numeros) if numeros else "Não informado",
                    "complemento": "",
                    "largo": True,
                }
            )
        if linhas:
            secoes.append({"titulo": titulo, "linhas": linhas})
    return secoes


def _secoes_form(form):
    """Campos do ProcessoForm agrupados por SECOES_FORMULARIO_PROCESSO,
    para o template renderizar <fieldset> por seção — só os campos que o
    form realmente expõe."""
    secoes = []
    for titulo, campos in SECOES_FORMULARIO_PROCESSO:
        bound_fields = [form[campo] for campo in campos if campo in form.fields]
        if bound_fields:
            secoes.append({"titulo": titulo, "campos": bound_fields})
    return secoes


def detalhe_processo_view(request, ano, item_pca):
    """Página de detalhe do processo, sem abas. Aberta a qualquer usuário
    autenticado; os botões de ação só aparecem para quem tem
    pca.editar_pca e o exercício está aberto."""
    try:
        processo = _carregar_processo_modal(ano, item_pca)
    except Http404:
        return _processo_nao_encontrado(request, ano, item_pca)

    anterior, proximo = _vizinhos_na_ordem_da_tabela(request, processo)
    rotulo_status, chave_status = _status_processo(processo)
    pode_editar = (
        not _sem_permissao_de_edicao(request)
        and processo.exercicio.situacao == SituacaoExercicio.ABERTO
    )
    querystring_tabela_atual = querystring_tabela(request.GET)
    contexto = {
        "p": processo,
        "trilha": [
            (
                "Processos",
                _com_querystring(reverse("pca:tabela"), querystring_tabela_atual),
            ),
            (f"Item {item_pca}", None),
        ],
        "secoes": _secoes_detalhe(processo),
        "rotulo_status": rotulo_status,
        "chave_status": chave_status,
        "pode_editar": pode_editar,
        "anterior": anterior,
        "proximo": proximo,
        "querystring_tabela": querystring_tabela_atual,
        # os três quadros de destaque da ficha: VALOR PREVISTO/VALOR
        # CONTRATADO ("Não informado" só quando None) e PRAZO ATUAL,
        # sempre presente, reaproveita compromisso_vigente por dentro
        "valor_previsto_ficha": _valor_quadro_monetario(processo.valor_estimado),
        "valor_contratado_ficha": _valor_quadro_monetario(processo.valor_contratado),
        "prazo_atual_ficha": prazo_atual_ficha(processo),
    }
    resposta = render(request, "pca/processo_detalhe.html", contexto)
    resposta["Cache-Control"] = "private, no-store"
    return resposta


def editar_processo_view(request, ano, item_pca):
    """Criar/editar como página. GET com ?modo=ver: redireciona ao
    detalhe — a leitura pura mudou de superfície, quem só quer ver abre
    pca:detalhe_processo."""
    try:
        processo = _carregar_processo_modal(ano, item_pca)
    except Http404:
        return _processo_nao_encontrado(request, ano, item_pca)

    querystring_retorno = _querystring_retorno(request)

    if request.GET.get("modo") == "ver":
        destino = reverse("pca:detalhe_processo", args=[ano, item_pca])
        return redirect(_com_querystring(destino, querystring_retorno))

    if _sem_permissao_de_edicao(request):
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied

    if processo.exercicio.situacao != SituacaoExercicio.ABERTO:
        # exercício fechado nunca abre a tela de edição; a leitura
        # continua disponível em pca:detalhe_processo
        messages.warning(
            request,
            f"O exercício {processo.exercicio.ano} está fechado. Não é "
            "possível editar itens de um exercício encerrado.",
        )
        return redirect(
            _com_querystring(
                reverse("pca:detalhe_processo", args=[ano, item_pca]), querystring_retorno
            )
        )

    if request.method == "GET":
        form = ProcessoForm(instance=processo)
        formset = ProcessoSEIFormSet(
            instance=processo, queryset=processo.numeros_sei.order_by("id")
        )
        return render(
            request,
            "pca/processo_formulario.html",
            {
                "form": form,
                "formset": formset,
                "processo": processo,
                "titulo": f"Editar item {item_pca}",
                "secoes_form": _secoes_form(form),
                "versao": processo.atualizado_em.isoformat(),
                "querystring_retorno": querystring_retorno,
                "trilha": [
                    (
                        "Processos",
                        _com_querystring(reverse("pca:tabela"), querystring_retorno),
                    ),
                    (f"Item {item_pca}", reverse("pca:detalhe_processo", args=[ano, item_pca])),
                    ("Editar", None),
                ],
                "url_cancelar": _com_querystring(
                    reverse("pca:detalhe_processo", args=[ano, item_pca]), querystring_retorno
                ),
            },
        )

    versao = request.POST.get("versao", "")
    form = ProcessoForm(request.POST, instance=processo)
    formset = ProcessoSEIFormSet(
        request.POST, instance=processo, queryset=processo.numeros_sei.order_by("id")
    )
    # os dois têm de ser válidos antes de qualquer escrita; and encadeado
    # deixaria de chamar formset.is_valid() se o form já tivesse falhado
    form_valido = form.is_valid()
    formset_valido = formset.is_valid()
    if not (form_valido and formset_valido):
        return render(
            request,
            "pca/processo_formulario.html",
            {
                "form": form,
                "formset": formset,
                "processo": processo,
                "titulo": f"Editar item {item_pca}",
                "secoes_form": _secoes_form(form),
                "versao": versao,
                "querystring_retorno": querystring_retorno,
                "trilha": [
                    (
                        "Processos",
                        _com_querystring(reverse("pca:tabela"), querystring_retorno),
                    ),
                    (f"Item {item_pca}", reverse("pca:detalhe_processo", args=[ano, item_pca])),
                    ("Editar", None),
                ],
                "url_cancelar": _com_querystring(
                    reverse("pca:detalhe_processo", args=[ano, item_pca]), querystring_retorno
                ),
            },
        )

    try:
        with transaction.atomic():
            travado = services.bloquear_para_edicao(processo.pk, versao)
            for campo, valor in form.cleaned_data.items():
                setattr(travado, campo, valor)
            travado._history_user = request.user
            travado.save()
            # mesma transação e o mesmo token otimista do ProcessoForm; o
            # formset já validado é reapontado para a instância travada
            formset.instance = travado
            formset.save()
            services.aplicar_regras_automaticas(processo=travado, usuario=request.user)
    except (services.ConflitoDeEdicao, services.ExercicioFechado) as erro:
        processo = _carregar_processo_modal(ano, item_pca)
        aviso = (
            "Este item mudou enquanto você editava. Os valores exibidos são os "
            "seus; confira e salve de novo para aplicá-los."
            if isinstance(erro, services.ConflitoDeEdicao)
            else str(erro)
        )
        form.add_error(None, aviso)
        return render(
            request,
            "pca/processo_formulario.html",
            {
                "form": form,
                "formset": formset,
                "processo": processo,
                "titulo": f"Editar item {item_pca}",
                "secoes_form": _secoes_form(form),
                "versao": processo.atualizado_em.isoformat(),
                "querystring_retorno": querystring_retorno,
                "trilha": [
                    (
                        "Processos",
                        _com_querystring(reverse("pca:tabela"), querystring_retorno),
                    ),
                    (f"Item {item_pca}", reverse("pca:detalhe_processo", args=[ano, item_pca])),
                    ("Editar", None),
                ],
                "url_cancelar": _com_querystring(
                    reverse("pca:detalhe_processo", args=[ano, item_pca]), querystring_retorno
                ),
            },
        )

    messages.success(request, "Processo atualizado.")
    return redirect(
        _com_querystring(
            reverse("pca:detalhe_processo", args=[ano, item_pca]), querystring_retorno
        )
    )


@permission_required("pca.editar_pca", raise_exception=True)
def criar_processo_view(request):
    """Criar como página, mesmo template do editar, só 4 campos."""
    exercicio_ano = request.GET.get("exercicio") or request.POST.get("exercicio")
    try:
        exercicio = (
            Exercicio.objects.get(ano=int(exercicio_ano))
            if exercicio_ano
            else Exercicio.objects.filter(situacao=SituacaoExercicio.ABERTO)
            .order_by("-ano")
            .first()
        )
    except (TypeError, ValueError, Exercicio.DoesNotExist):
        exercicio = None

    if request.method == "GET":
        form = ProcessoForm(criando=True)
        return render(
            request,
            "pca/processo_formulario.html",
            {
                "form": form,
                "processo": None,
                "titulo": "Novo processo",
                "trilha": [("Processos", reverse("pca:tabela")), ("Novo processo", None)],
                "url_cancelar": reverse("pca:tabela"),
            },
        )

    form = ProcessoForm(request.POST, criando=True)
    if not form.is_valid():
        return render(
            request,
            "pca/processo_formulario.html",
            {
                "form": form,
                "processo": None,
                "titulo": "Novo processo",
                "trilha": [("Processos", reverse("pca:tabela")), ("Novo processo", None)],
                "url_cancelar": reverse("pca:tabela"),
            },
        )

    try:
        processo = services.criar_processo(
            usuario=request.user,
            descricao_objeto=form.cleaned_data["descricao_objeto"],
            tipo_id=form.cleaned_data["tipo"].pk,
            categoria_id=form.cleaned_data["categoria"].pk,
            unidade_organizacional_id=form.cleaned_data["unidade_organizacional"].pk,
            exercicio=exercicio,
        )
    except services.ExercicioFechado as fechado:
        form.add_error(None, str(fechado))
        return render(
            request,
            "pca/processo_formulario.html",
            {
                "form": form,
                "processo": None,
                "titulo": "Novo processo",
                "trilha": [("Processos", reverse("pca:tabela")), ("Novo processo", None)],
                "url_cancelar": reverse("pca:tabela"),
            },
        )

    messages.success(request, "Processo criado com sucesso.")
    return redirect(
        reverse("pca:detalhe_processo", args=[processo.exercicio.ano, processo.item_pca])
    )


def transicao_processo_view(request, ano, item_pca):
    """Alterar situação como página própria; é hoje a única forma de
    alterar situação."""
    processo = get_object_or_404(Processo, exercicio__ano=ano, item_pca=item_pca)
    if _sem_permissao_de_edicao(request):
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied

    querystring_retorno = _querystring_retorno(request)
    trilha = [
        ("Processos", _com_querystring(reverse("pca:tabela"), querystring_retorno)),
        (f"Item {item_pca}", reverse("pca:detalhe_processo", args=[ano, item_pca])),
        ("Alterar situação", None),
    ]

    if request.method == "GET":
        form = TransicaoForm(initial={"destino": processo.situacao})
        return render(
            request,
            "pca/processo_transicao.html",
            {
                "form": form,
                "processo": processo,
                "trilha": trilha,
                "versao": processo.atualizado_em.isoformat(),
                "querystring_retorno": querystring_retorno,
            },
        )

    form = TransicaoForm(request.POST)
    versao = request.POST.get("versao", "")
    if not form.is_valid():
        return render(
            request,
            "pca/processo_transicao.html",
            {
                "form": form,
                "processo": processo,
                "trilha": trilha,
                "versao": versao,
                "querystring_retorno": querystring_retorno,
            },
        )

    try:
        services.registrar_acompanhamento(
            processo_id=processo.pk,
            usuario=request.user,
            versao_cliente=versao,
            situacao_novo=form.cleaned_data["destino"],
            justificativa=form.cleaned_data["justificativa"],
        )
    except services.ConflitoDeEdicao:
        processo.refresh_from_db()
        form.add_error(
            None,
            "Este item mudou enquanto você editava. Confira e confirme de novo.",
        )
        return render(
            request,
            "pca/processo_transicao.html",
            {
                "form": form,
                "processo": processo,
                "trilha": trilha,
                "versao": processo.atualizado_em.isoformat(),
                "querystring_retorno": querystring_retorno,
            },
        )
    except services.ExercicioFechado as fechado:
        form.add_error(None, str(fechado))
        return render(
            request,
            "pca/processo_transicao.html",
            {
                "form": form,
                "processo": processo,
                "trilha": trilha,
                "versao": versao,
                "querystring_retorno": querystring_retorno,
            },
        )
    except services.ObservacaoObrigatoria:
        form.add_error(
            "justificativa", "Observação obrigatória para cancelar o processo."
        )
        return render(
            request,
            "pca/processo_transicao.html",
            {
                "form": form,
                "processo": processo,
                "trilha": trilha,
                "versao": versao,
                "querystring_retorno": querystring_retorno,
            },
        )

    messages.success(request, "Situação alterada.")
    return redirect(
        _com_querystring(
            reverse("pca:detalhe_processo", args=[ano, item_pca]), querystring_retorno
        )
    )


def acompanhamento_modal_view(request, ano, item_pca):
    """Único modal do sistema. GET devolve o fragmento já ativo — o clique
    que disparou o hx-get é a ação do usuário que abre a modal. Sem JS
    próprio: "Cancelar" é um link real de volta ao detalhe.

    POST sempre redireciona ao detalhe em caso de sucesso, convertido em
    HX-Redirect quando a requisição é htmx. Nunca muda situacao/estado."""
    # busca já anotada (para_listagem()) para decidir o help_text
    # condicional de "Novo prazo" sem um segundo annotate() separado
    processo = get_object_or_404(
        Processo.objects.para_listagem(), exercicio__ano=ano, item_pca=item_pca
    )
    if _sem_permissao_de_edicao(request):
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied

    ajuda_prazo = ajuda_novo_prazo(
        sobreposicao_manual_ativa=processo.sobreposicao_manual_ativa,
        situacao_efetiva=processo.situacao_efetiva,
    )
    querystring_retorno = _querystring_retorno(request)

    if request.method == "GET":
        form = AcompanhamentoForm(ajuda_prazo=ajuda_prazo)
        return render(
            request,
            "pca/_acompanhamento_modal.html",
            {
                "form": form,
                "processo": processo,
                "versao": processo.atualizado_em.isoformat(),
                # aviso de leitura do compromisso vigente, sem novo campo no formulário
                "compromisso_vigente": compromisso_vigente(processo),
                "querystring_retorno": querystring_retorno,
            },
        )

    form = AcompanhamentoForm(request.POST, ajuda_prazo=ajuda_prazo)
    versao = request.POST.get("versao", "")
    if not form.is_valid():
        return render(
            request,
            "pca/_acompanhamento_modal.html",
            {
                "form": form,
                "processo": processo,
                "versao": versao,
                "compromisso_vigente": compromisso_vigente(processo),
                "querystring_retorno": querystring_retorno,
            },
        )

    prazo_prometido = form.cleaned_data.get("prazo_prometido")
    try:
        services.registrar_acompanhamento(
            processo_id=processo.pk,
            usuario=request.user,
            versao_cliente=versao,
            prazo_prometido=prazo_prometido,
            observacao=form.cleaned_data.get("observacao", ""),
            justificativa=form.cleaned_data.get("justificativa", ""),
            # sem prazo novo, esta submissão só tem observação/justificativa:
            # reafirma a situação já gravada, sem mudar o valor final, e sem
            # contar como transição manual
            reafirmar_situacao=not prazo_prometido,
        )
    except services.ConflitoDeEdicao:
        processo.refresh_from_db()
        form.add_error(
            None,
            "Este item mudou enquanto você registrava. Confira e registre de novo.",
        )
        return render(
            request,
            "pca/_acompanhamento_modal.html",
            {
                "form": form,
                "processo": processo,
                "versao": processo.atualizado_em.isoformat(),
                "compromisso_vigente": compromisso_vigente(processo),
                "querystring_retorno": querystring_retorno,
            },
        )
    except services.ExercicioFechado as fechado:
        form.add_error(None, str(fechado))
        return render(
            request,
            "pca/_acompanhamento_modal.html",
            {
                "form": form,
                "processo": processo,
                "versao": versao,
                "compromisso_vigente": compromisso_vigente(processo),
                "querystring_retorno": querystring_retorno,
            },
        )

    if prazo_prometido is not None and prazo_prometido < localdate():
        # prazo passado sempre grava (lançamento retroativo de reunião); o
        # aviso descreve a situação efetiva final depois da gravação,
        # buscada de novo, nunca inferida só pela data digitada
        situacao_final = (
            Processo.objects.para_listagem()
            .values_list("situacao_efetiva", flat=True)
            .get(pk=processo.pk)
        )
        if situacao_final == Situacao.ATRASADO:
            messages.warning(
                request,
                "Prazo registrado com data já passada: o item consta como Atrasado.",
            )
        else:
            messages.warning(
                request,
                "Prazo registrado com data já passada. Situação atual: "
                f"{Situacao(situacao_final).label}.",
            )

    messages.success(request, "Acompanhamento registrado.")
    # HtmxRedirectMiddleware já converte este redirect em HX-Redirect
    # quando a requisição é htmx — nenhuma ramificação própria necessária
    return redirect(
        _com_querystring(
            reverse("pca:detalhe_processo", args=[ano, item_pca]), querystring_retorno
        )
    )


# incluir/excluir número SEI só acontece pelo ProcessoSEIFormSet dentro
# do fieldset Processo de editar_processo_view, na mesma transação e no
# mesmo token otimista do ProcessoForm
