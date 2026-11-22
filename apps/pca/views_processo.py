"""Views de tela própria do processo — Fase 26.

Substitui os 3 modais de webcomponents (`processo_modal.html`,
`processo_modal_criar.html`, `_modal_transicao.html`) e a edição multi-campo em
modal (`_form_editar_processo.html`) por páginas no padrão
`telas/detalhe.md`/`telas/formulario.md` do padrão DSGov, mantendo como único
modal do sistema o `br-modal` tipo Entrada de "Registrar acompanhamento".


Módulo novo (extração de `views.py` em
módulos por tela): `views.py` já tinha 3536 linhas antes deste plano;
`editar_campo_view`/`tabela_view`/`dashboard_view`/etc. continuam lá
intocadas. `urls.py` importa os dois módulos.
"""

from django.contrib.auth.decorators import permission_required
from decimal import Decimal
import json
from urllib.parse import urlparse

from django.contrib import messages
from django.db import transaction
from django.http import Http404, HttpResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.timezone import localdate, localtime
from django.views.decorators.http import require_POST

from apps.catalogo.models import Exercicio, SituacaoExercicio
from apps.pca.filtros import NOMES_MES, querystring_filtros, querystring_tabela, queryset_filtrado
from apps.pca import mudancas
from apps.pca.forms import (
    AcompanhamentoForm,
    ProcessoForm,
    ProcessoSEIFormSet,
    TransicaoForm,
    ajuda_novo_prazo,
)
from apps.pca.models import Acompanhamento, Estado, Processo, Situacao
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
    contexto_timeline,
)

def _com_querystring(url, querystring):
    """Devolve `url?querystring` se `querystring` for
    truthy, senão `url` sem alteração (mesmo padrão de composição de todos
    os links/redirects opcionais desta quick)."""
    return f"{url}?{querystring}" if querystring else url


def _querystring_retorno(request):
    """ÚNICO ponto que decide "qual querystring esta
    view deve preservar": GET lê da URL (o link que trouxe o usuário até
    aqui); POST lê do campo oculto `querystring_retorno` do formulário, que
    sobrevive mesmo quando o `<form>` tem `action=`/`hx-post` explícito e
    por isso NÃO herda a querystring da barra de endereço na submissão
    (caso de `_acompanhamento_modal.html`)."""
    if request.method == "POST":
        return request.POST.get("querystring_retorno", "")
    return querystring_tabela(request.GET)


def _origem_e_querystring(request):
    """ÚNICO ponto de `acompanhamento_modal_view` que
    decide `(origem, querystring)`: de onde o modal foi aberto e quais
    filtros da tabela preservar, para escolher entre fechar por
    `HX-Location` (troca só `#listagem`, sem recarga) ou pelo PRG da quick
    pw7 (redirect/`HX-Redirect` de página inteira).

    GET: se a requisição é htmx e `HX-Current-URL` aponta para o MESMO path
    de `pca:tabela` (nunca refletido cru — só o path é comparado, a
    querystring desse header é revalidada por `querystring_tabela`, que só
    reconstrói filtros já validados), origem = "tabela". Qualquer outro
    caso (detalhe, sem htmx, header ausente/de outra origem) é
    origem = "detalhe" com a querystring atual de `request.GET`
    (comportamento anterior).

    POST: origem vem do campo oculto `origem` do formulário — só
    "tabela"/"detalhe" são aceitos, qualquer outro valor (ausente,
    adulterado) cai em "detalhe"; a querystring vem revalidada por
    `querystring_tabela` a partir do campo oculto `querystring_retorno`,
    nunca refletida crua.
    """
    if request.method == "POST":
        origem = request.POST.get("origem")
        if origem not in ("tabela", "detalhe"):
            origem = "detalhe"
        querystring = querystring_tabela(
            QueryDict(request.POST.get("querystring_retorno", ""))
        )
        return origem, querystring

    hx_current_url = request.headers.get("HX-Current-URL", "")
    if getattr(request, "htmx", False) and hx_current_url:
        partes = urlparse(hx_current_url)
        if partes.path == reverse("pca:tabela"):
            return "tabela", querystring_tabela(QueryDict(partes.query))
    return "detalhe", querystring_tabela(request.GET)


# Fase 17 (paleta) — mapa (eixo, valor) → chave semântica de
# `core.templatetags.dsgov.classe_status`. Cancelado (eixo Estado) tem
# prioridade sobre qualquer Situação gravada — um processo cancelado nunca
# exibe "No prazo"/"Atrasado" residual.
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
    """Falta a permissão de escrita? (herdado de `views.py`)."""
    return not request.user.has_perm("pca.editar_pca")


def _vizinhos_na_ordem_da_tabela(request, processo):
    """(anterior, proximo) do processo na ordem que a tabela está exibindo —
    mesmo corpo de `views._vizinhos_na_ordem_da_tabela` (Fase 11), agora
    consumido só por `views_processo.py`."""
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
    processo (pares da ficha dizem "Não informado", nunca "—";
    tabelas continuam com traço via `core.templatetags.dsgov.ou_traco`).

    Reaproveita `_tipo_widget` (dispatch por tipo de campo Django, `views.py`)
    em vez de reinventar um segundo entendimento de como cada campo aparece.
    """
    valor = getattr(processo, campo)
    if valor in (None, ""):
        return "Não informado"
    widget = _tipo_widget(campo)
    if widget == "boolean":
        return "Sim" if valor else "Não"
    if widget == "select_choice":
        return getattr(processo, f"get_{campo}_display")()
    if widget == "select_mes":
        return NOMES_MES.get(valor, str(valor))
    if widget == "money":
        from core.templatetags.dsgov import moeda

        return moeda(valor)
    if widget == "date":
        from core.templatetags.dsgov import data_br

        return data_br(valor)
    return str(valor)


# /03 (herdado de `_badge_pendencia.html`, apagado com o modal) — os
# 3 canais de publicação ganham um selo "pendente há N dias" quando
# `publicacao_pendente` (annotation de `.para_listagem()`) está ligada E o
# canal específico ainda não foi lançado. `publicacao_pendente` já é uma
# annotation do ORM (sem consulta por linha, /convenções do projeto); a contagem de
# dias é aritmética em memória sobre um campo já carregado.
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


# VALOR PREVISTO/VALOR CONTRATADO viram quadros de
# destaque da ficha (`_valor_quadro_monetario`), não pares repetidos dentro
# de "Planejamento"/"Execução contratual".
_CAMPOS_QUADRO_FICHA = {"valor_estimado", "valor_contratado"}

_LIMITE_COERENCIA_VALOR_MENSAL = Decimal("0.05")


def _aviso_coerencia_valor_mensal(processo):
    """Fase 36 — coerência SINALIZADA, nunca imposta
    (o `save()` sempre grava, mesmo divergente): "se valor_mensal × meses
    diverge de valor_contratado em mais de 5%, a tela avisa". Sem dado
    suficiente (falta qualquer um dos 4 campos, ou vigência invertida/zero),
    devolve `""` — sem aviso. `meses` é a duração inteira da vigência em
    dias ÷ 30,44 (média do ano civil), arredondada, mínimo 1 — a mesma
    aproximação de "quantos meses cabem numa vigência" usada só para este
    alerta de UI, distinta da heurística exata de `regras_situacao.
    regime_presumido_*` (que decide `continuado`/`unico`, não multiplica
    valores)."""
    if not (
        processo.valor_mensal
        and processo.valor_contratado
        and processo.vigencia_inicio
        and processo.vigencia_fim
    ):
        return ""
    dias = (processo.vigencia_fim - processo.vigencia_inicio).days
    if dias <= 0:
        return ""
    meses = max(1, round(dias / 30.44))
    calculado = processo.valor_mensal * meses
    limite = processo.valor_contratado * _LIMITE_COERENCIA_VALOR_MENSAL
    if abs(calculado - processo.valor_contratado) <= limite:
        return ""

    from core.templatetags.dsgov import moeda

    return (
        f"Valor mensal × {meses} mês(es) de vigência ({moeda(calculado)}) "
        f"diverge do valor contratado ({moeda(processo.valor_contratado)}) "
        "em mais de 5%."
    )


def _rotulo_campo(campo):
    """Rótulo de TELA com fallback ao
    `verbose_name` do model — `ROTULOS` nunca é consumido sozinho."""
    return ROTULOS.get(campo, Processo._meta.get_field(campo).verbose_name)


def _valor_quadro_monetario(valor):
    """Quadros financeiros da ficha: só `None` vira "Não
    informado"; zero é `R$ 0,00` (nulo e zero nunca se confundem, princípio
    da Fase 28)."""
    if valor is None:
        return "Não informado"
    from core.templatetags.dsgov import moeda

    return moeda(valor)


def _linha_prazo_inicial(processo):
    """O par "Prazo inicial:" da ficha usa a MESMA
    anotação COALESCE de `ProcessoQuerySet.para_listagem()::prazo_inicial`
e indica a procedência quando a data veio do histórico
    (`prazo_entrega` vazio, primeira promessa preenchida): "(primeiro prazo
    registrado)" em texto secundário. Só na ficha — tabela e XLSX mostram a
    data pura (célula de data, nunca texto)."""
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


def _valor_unidade_sei_atual(processo):
    """Somente leitura, gravado só pelo robô SEI. `""`
    devolve "—" (não "Não informado", não se aplica aqui, decisão
    explícita desta quick — mesmo padrão do resto da coluna/ficha de
    `unidade_sei_atual`, campo tipo "texto" que já cai em `ou_traco`)."""
    if not processo.unidade_sei_atual:
        return "—"
    if not processo.unidade_sei_atual_desde:
        return processo.unidade_sei_atual
    desde = localtime(processo.unidade_sei_atual_desde).strftime("%d/%m/%Y %H:%M")
    return f"{processo.unidade_sei_atual} · desde {desde}"


def _secoes_detalhe(processo, pode_ver_acompanhamento=True):
    """Campos agrupados por `SECOES_FORMULARIO_PROCESSO`, resolvidos como
    pares "Rótulo: valor" da ficha PNCP — o mesmo agrupamento
    do formulário (do plano), em modo leitura.

    O detalhe é estritamente de
    leitura para números SEI: a linha "Números SEI" entra na seção
    "Processo" (mesmo card de Situação SEI/Recebimento no Gelic) sem
    formulário nem controle de remoção; incluir/excluir só acontece no
    fieldset Processo de `processo_formulario.html` (`ProcessoSEIFormSet`).
    Valor ausente aqui é sempre "Não informado", nunca "—".

    `pode_ver_acompanhamento` (default `True` preserva o
    comportamento anterior): sem a permissão, a linha "Prazo inicial" (é
    acompanhamento/prazo) some da ficha — só `continue`, nenhum `.append`."""
    secoes = []
    for titulo, campos in SECOES_FORMULARIO_PROCESSO:
        linhas = []
        for campo in campos:
            if campo not in CAMPOS_EDITAVEIS_PROCESSO:
                continue
            if campo in _CAMPOS_QUADRO_FICHA:
                continue
            if campo == "prazo_entrega":
                if pode_ver_acompanhamento:
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
            linhas.append(
                {
                    "pendencia": None,
                    "rotulo": "Unidade atual (SEI)",
                    "valor": _valor_unidade_sei_atual(processo),
                    "complemento": "",
                    "largo": False,
                }
            )
        if linhas:
            secoes.append({"titulo": titulo, "linhas": linhas})
    return secoes


def _secoes_form(form):
    """Campos do `ProcessoForm` agrupados por `SECOES_FORMULARIO_PROCESSO`,
    para o template renderizar `<fieldset>` por seção — só os campos
    que o form realmente expõe (na criação, nenhuma seção sobrevive)."""
    secoes = []
    for titulo, campos in SECOES_FORMULARIO_PROCESSO:
        bound_fields = [form[campo] for campo in campos if campo in form.fields]
        if bound_fields:
            secoes.append({"titulo": titulo, "campos": bound_fields})
    return secoes


def _pode_excluir_acompanhamento(user) -> bool:
    """Guarda MAIS ESTRITA que `pode_editar`: só
    superusuário COM `pca.gerir_exercicio` vê a coluna Ações/link
    "Excluir" e pode acionar as duas rotas novas. Helper próprio (mesmo
    padrão de `views_analise.py::_pode_gerar_n1`) para poder divergir de
    lá no futuro, mesmo com a MESMA regra hoje."""
    return bool(user.is_superuser and user.has_perm("pca.gerir_exercicio"))


def detalhe_processo_view(request, ano, item_pca):
    """Página de detalhe do processo — `telas/detalhe.md`, sem abas.

    Aberta a qualquer usuário autenticado (`LoginRequiredMiddleware` global);
    os botões de ação (Editar/Alterar situação/Registrar acompanhamento) só
    aparecem para quem tem `pca.editar_pca` E o exercício está aberto — mesmo
    par de condições que `editar_processo_view` usa para decidir se grava.
    """
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
    pode_ver_acompanhamento = request.user.has_perm("pca.view_acompanhamento")
    # Fase 37 (spec §5 item 6) — link "Memória de
    # cálculo" na seção "Execução contratual" só para quem tem
    # `pca.ver_analises`; a ficha em si continua aberta a todo
    # autenticado, sem regressão (mesmo padrão de `pode_ver_acompanhamento`
    # acima).
    pode_ver_analises = request.user.has_perm("pca.ver_analises")
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
        "secoes": _secoes_detalhe(processo, pode_ver_acompanhamento),
        "rotulo_status": rotulo_status,
        "chave_status": chave_status,
        "pode_editar": pode_editar,
        "anterior": anterior,
        "proximo": proximo,
        "querystring_tabela": querystring_tabela_atual,
        # Os três quadros de destaque da ficha PNCP (Plano
        # 29-04): VALOR PREVISTO/VALOR CONTRATADO ("Não
        # informado" só quando `None`) e PRAZO ATUAL (SEMPRE presente, reaproveita `compromisso_vigente` por dentro) —
        # PRAZO ATUAL é acompanhamento, `None` sem a
        # permissão (o template só mostra o quadro `{% if
        # prazo_atual_ficha %}`).
        "valor_previsto_ficha": _valor_quadro_monetario(processo.valor_estimado),
        "valor_contratado_ficha": _valor_quadro_monetario(processo.valor_contratado),
        "prazo_atual_ficha": prazo_atual_ficha(processo) if pode_ver_acompanhamento else None,
        # A ficha DSGov junta prazo inicial e prazo atual
        # numa linha só ("Compromisso vigente"), no lugar do quadro PRAZO
        # ATUAL; `secoes` não muda (a ficha Tabler continua usando o par).
        "linha_prazo_inicial": _linha_prazo_inicial(processo) if pode_ver_acompanhamento else None,
        "pode_ver_acompanhamento": pode_ver_acompanhamento,
        "pode_ver_analises": pode_ver_analises,
        # Coluna Ações/link "Excluir" na tabela de
        # acompanhamentos, guarda mais estrita que `pode_editar`.
        "pode_excluir_acompanhamento": _pode_excluir_acompanhamento(request.user),
        # Fase 36 — "" quando não há dado suficiente
        # (o template só mostra o `br-message warning` quando truthy).
        "aviso_valor_mensal": _aviso_coerencia_valor_mensal(processo),
    }
    # 5 acompanhamentos mais recentes por padrão, com
    # alternância "Ver mais"/"Ver menos" (ver `contexto_timeline`).
    #
    # A timeline inteira (Acompanhamentos e prazos) é
    # gated por `pca.view_acompanhamento`: sem a permissão, nenhuma das
    # chaves `timeline_exibida`/`timeline_total`/`timeline_ocultos`/
    # `url_ver_mais`/`url_ver_menos` entra no contexto.
    if pode_ver_acompanhamento:
        contexto.update(contexto_timeline(request, processo, querystring_tabela_atual))
    # Fase 43 — botão "Solicitar alteração" (só para a unidade do item) e aba "Solicitações" (unidade
    # do item, equipe do PCA e diretoria). Import local: as Solicitações dependem de apps.pca.
    from apps.solicitacoes.ficha import contexto_da_ficha

    contexto.update(contexto_da_ficha(request.user, processo))
    resposta = render(request, "pca/processo_detalhe.html", contexto)
    resposta["Cache-Control"] = "private, no-store"
    return resposta


def editar_processo_view(request, ano, item_pca):
    """Criar/editar como página — `telas/formulario.md`, `processo_formulario.html`.

    GET com `?modo=ver`: redireciona ao detalhe (a leitura pura mudou de
    superfície — o modal em `?modo=ver` da Fase 14 não existe mais;
    quem só quer ver abre `pca:detalhe_processo`). Registrado como desvio de
    em `26-deferred-items.md`.
    """
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
        # Exercício fechado nunca abre a tela de edição; a
        # leitura continua disponível em `pca:detalhe_processo`.
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
    # Os dois têm de ser válidos ANTES de qualquer escrita; `and`
    # encadeado deixaria de chamar `formset.is_valid()` se o form já tivesse
    # falhado, escondendo erros do formset na resposta.
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
            # Mesma transação e o mesmo token otimista do ProcessoForm
            #o formset já validado é reapontado para a
            # instância travada antes de salvar; erro em qualquer parte
            # reverte pai e filhos juntos.
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
    """Criar como página — mesmo template do editar, só 4 campos (`criando=True`)."""
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
    """Alterar situação como página — `processo_transicao.html`.

    Fase 26 — `pca:preparar_transicao`/`pca:confirmar_transicao`
    (Fase 17, o modal universal de webcomponents) saíram por completo:
    `pca:transicao_processo` é hoje a ÚNICA forma de alterar situação.
    """
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
    except services.SituacaoImpostaPelaVigencia as imposta:
        form.add_error("destino", imposta.motivo)
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
    """Único modal do sistema — `_acompanhamento_modal.html`.

    GET (sempre chamado via `hx-get` de dentro de `processo_detalhe.html`)
    devolve o fragmento `br-scrim-util foco active` já ativo — o clique que
    disparou o `hx-get` É a ação do usuário que abre a modal (`scrim.md`:
    "não abra em eventos do sistema"; aqui não há evento de sistema algum, a
    modal só existe porque o usuário clicou). Sem `new core.Scrim(...)`
    algum: "Cancelar" é um link real de volta ao detalhe (zero JS próprio).

    POST bem-sucedido de origem **tabela** (htmx) responde 200 com
    `HX-Location` para `#listagem` — nenhuma recarga, scroll preservado.
De qualquer outra origem (detalhe, ou sem htmx),
    volta para a PRÓPRIA FICHA do item (`#acompanhamentos`), com filtros
    preservados — nunca mais para a tabela (`HX-Redirect`
    quando é htmx, redirect comum caso contrário, via
    `HtmxRedirectMiddleware`). Nunca muda `situacao`/`estado`.
    """
    # Busca já anotada (`para_listagem()`) para
    # decidir o `help_text` condicional de "Novo prazo" (situação
    # efetiva/sobreposição manual ativa) sem um segundo `annotate()`
    # separado (Pitfall 8/9/10).
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
    origem, querystring_retorno = _origem_e_querystring(request)

    if request.method == "GET":
        # Só o GET pré-preenche: no POST o form
        # é sempre ligado a `request.POST`, o que o usuário digitou manda
        # sempre, a proposta nunca sobrepõe (nem em POST inválido).
        form = AcompanhamentoForm(
            ajuda_prazo=ajuda_prazo,
            initial={"observacao": mudancas.propor_texto(processo)},
        )
        return render(
            request,
            "pca/_acompanhamento_modal.html",
            {
                "form": form,
                "processo": processo,
                "versao": processo.atualizado_em.isoformat(),
                # Aviso de leitura do compromisso
                # vigente, sem novo campo no formulário.
                "compromisso_vigente": compromisso_vigente(processo),
                "querystring_retorno": querystring_retorno,
                "origem": origem,
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
                "origem": origem,
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
            # Sem prazo novo, esta submissão só tem
            # observação/justificativa (`AcompanhamentoForm.clean()` aceita
            # "só observação"): reafirma a situação já gravada, sem mudar o
            # valor final, e SEM contar como transição manual — o modal
            # nunca altera situação/estado por conta própria, então esta
            # reafirmação interna não pode virar uma sobreposição manual
            # ativa que trava para sempre.
            reafirmar_situacao=not prazo_prometido,
            # A ORIGEM diz o sentido do
            # registro, não um campo novo na tela: aberto pela TABELA é
            # reunião item a item, então continua colando na reunião
            # ABERTA (comportamento de sempre); aberto pela FICHA é o
            # editor do PCA corrigindo/registrando fora de reunião — nunca
            # amarra a um compromisso que ninguém assumiu numa reunião.
            usar_reuniao_corrente=(origem == "tabela"),
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
                "origem": origem,
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
                "origem": origem,
            },
        )

    if prazo_prometido is not None and prazo_prometido < localdate():
        # Prazo passado sempre grava (lançamento
        # retroativo de reunião); o aviso descreve a SITUAÇÃO EFETIVA FINAL
        # depois da gravação, buscada de novo por `para_listagem()` — nunca
        # inferida só pela data digitada, para respeitar sobreposição
        # manual, fatos gravados e a ordem cronológica dos compromissos.
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

    messages.success(
        request, f"Acompanhamento do item {processo.item_pca} registrado."
    )
    if getattr(request, "htmx", False) and origem == "tabela":
        # Da tabela, fecha SEM recarregar a página: 200 +
        # `HX-Location` faz o htmx buscar `/tabela?<qs>` (que já devolve
        # `_listagem.html` para `HX-Request`) e trocar só `#listagem` —
        # scroll preservado, `messages.success` acima é mostrado por
        # `_listagem.html` no ramo `request.htmx` desse GET seguinte.
        return HttpResponse(
            status=200,
            headers={
                "HX-Location": json.dumps(
                    {
                        "path": _com_querystring(
                            reverse("pca:tabela"), querystring_retorno
                        ),
                        "target": "#listagem",
                        "swap": "innerHTML",
                    }
                )
            },
        )
    # `core.middleware.HtmxRedirectMiddleware` (global, intocado) já converte
    # este redirect em `HX-Redirect` quando a requisição é htmx — nenhuma
    # ramificação própria necessária aqui. volta para a
    # PRÓPRIA FICHA do item (`#acompanhamentos`), nunca mais para a tabela
    # (revoga para este caminho; o caminho tabela+htmx
    # acima, continua intocado). por
    # htmx (o modal de verdade) volta SEM a âncora: `dsgov.js`/`pca-tabler.js`
    # devolvem a tela ao mesmo ponto em que o modal foi aberto; a âncora
    # `#acompanhamentos` fazia a página pular. Sem htmx, a âncora continua.
    return redirect(
        _com_querystring(
            reverse("pca:detalhe_processo", args=[ano, item_pca]), querystring_retorno
        )
        + ("" if getattr(request, "htmx", False) else "#acompanhamentos")
    )


# `adicionar_sei_view`/
# `remover_sei_view` (rotas `pca:adicionar_sei`/`pca:remover_sei`) saíram:
# incluir/excluir número SEI só acontece pelo `ProcessoSEIFormSet` dentro
# do fieldset Processo de `editar_processo_view`, na mesma transação e no
# mesmo token otimista do `ProcessoForm` — nenhuma escrita avulsa a partir
# do detalhe sobrevive (as URLs antigas respondem 404).


# Excluir acompanhamento pela ficha: link "Excluir" por
# linha (só superusuário + `pca.gerir_exercicio`), página de confirmação
# própria (nunca modal, mesmo padrão de `cenario_fluxo_confirmar_excluir.
# html`/`views_analise.py::cenario_fluxo_excluir_confirmar_view`) que
# anuncia o efeito real no estado derivado, calculado por
# `services.efeito_da_exclusao` (transação+rollback). POST real preserva a
# trilha `simple_history` (autor gravado por `services.
# excluir_acompanhamento`).


def acompanhamento_excluir_confirmar_view(request, ano, item_pca, pk):
    """GET — página de confirmação. `get_object_or_404` já amarra o
    acompanhamento ao item (ano/item_pca/pk): pk de outro processo devolve
    404 antes mesmo da checagem de permissão, nunca apaga nada."""
    if not _pode_excluir_acompanhamento(request.user):
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied

    acompanhamento = get_object_or_404(
        Acompanhamento.objects.select_related(
            "processo", "processo__exercicio", "reuniao"
        ),
        pk=pk,
        processo__exercicio__ano=ano,
        processo__item_pca=item_pca,
    )
    querystring_retorno = _querystring_retorno(request)
    url_ficha = (
        _com_querystring(
            reverse("pca:detalhe_processo", args=[ano, item_pca]),
            querystring_retorno,
        )
        + "#acompanhamentos"
    )
    contexto = {
        "acompanhamento": acompanhamento,
        "p": acompanhamento.processo,
        "efeito": services.efeito_da_exclusao(acompanhamento),
        "querystring_retorno": querystring_retorno,
        "url_cancelar": url_ficha,
        "trilha": [
            (
                "Processos",
                _com_querystring(reverse("pca:tabela"), querystring_tabela(request.GET)),
            ),
            (f"Item {item_pca}", reverse("pca:detalhe_processo", args=[ano, item_pca])),
            ("Excluir acompanhamento", None),
        ],
    }
    return render(request, "pca/acompanhamento_confirmar_excluir.html", contexto)


@require_POST
def acompanhamento_excluir_view(request, ano, item_pca, pk):
    """POST real — uma linha por chamada, nunca lote. `get_object_or_404`
    amarra o acompanhamento ao item (mesmo par ano/item_pca do GET): pk de
    outro processo devolve 404 sem apagar nada."""
    if not _pode_excluir_acompanhamento(request.user):
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied

    acompanhamento = get_object_or_404(
        Acompanhamento, pk=pk, processo__exercicio__ano=ano, processo__item_pca=item_pca
    )
    try:
        resultado = services.excluir_acompanhamento(
            acompanhamento_id=acompanhamento.pk, usuario=request.user
        )
    except services.ExercicioFechado as fechado:
        messages.error(request, str(fechado))
        querystring_retorno = _querystring_retorno(request)
        return redirect(
            _com_querystring(
                reverse("pca:detalhe_processo", args=[ano, item_pca]),
                querystring_retorno,
            )
            + "#acompanhamentos"
        )
    messages.success(request, f"Acompanhamento de {resultado['resumo']} excluído.")

    querystring_retorno = _querystring_retorno(request)
    return redirect(
        _com_querystring(
            reverse("pca:detalhe_processo", args=[ano, item_pca]),
            querystring_retorno,
        )
        + "#acompanhamentos"
    )
