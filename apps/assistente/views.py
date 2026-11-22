"""Views da tela "Assistente" — PRG canônico.
Escrita sempre POST-redirect-GET; GET nunca cobra. o form de pergunta ganhou HTMX: sucesso vira 200 + `HX-Location`
para `#area-chat` em vez de recarregar a página inteira; sem HTMX, o PRG
comum (redirect) continua idêntico."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.assistente import agente
from apps.assistente import cliente as cliente_mod
from apps.assistente import estado, fontes, indice, renderizacao
from apps.assistente.forms import PerguntaForm
from apps.catalogo.models import Exercicio
from apps.pca import navegacao
from apps.pca.filtros import resolver_exercicio

logger = logging.getLogger("apps.assistente")

_RODAPE_ERRO_POR_CODIGO = {
    "timeout": "o provedor de IA não respondeu a tempo",
    "limite_taxa": "o provedor de IA está temporariamente sobrecarregado",
    "autenticacao": "falha de autenticação com o provedor de IA",
    "conexao": "não foi possível conectar ao provedor de IA",
    "provedor": "o provedor de IA devolveu um erro inesperado",
    "resposta_invalida": "o provedor de IA devolveu uma resposta inválida",
    "prazo": "o tempo disponível para responder se esgotou",
    "interno": "ocorreu um erro interno inesperado",
}


@dataclass
class PedidoEmAndamento:
    """Tudo que `_processar_em_segundo_plano` precisa, capturado ANTES de
    disparar a thread — nunca o objeto `request` (não é seguro
    entre threads) nem o `usuario`/`Exercicio` do ORM da request atual
    (refeitos dentro da thread com uma conexão própria)."""

    requisicao_id: str
    usuario_id: int
    session_key: str | None
    sessao_hash: str
    permissoes_hash: str
    exercicio_ano: int
    conversa_id: str
    trocas: list
    pergunta: str
    agora: object


def _iniciar_thread(alvo, *args, **kwargs) -> None:
    """Extraído para que os testes substituam por execução síncrona
    (`mock.patch("apps.assistente.views._iniciar_thread", ...)`) — em
    produção sempre uma thread `daemon=True` de verdade."""
    threading.Thread(target=alvo, args=args, kwargs=kwargs, daemon=True).start()


def _processar_em_segundo_plano(dados: PedidoEmAndamento) -> None:
    """Roda em thread separada: a chamada de rede acontece
    inteiramente aqui, longe do request/Gunicorn slot. Nenhuma transação
    SQLite fica aberta durante a rede — cada gravação de
    `andamento`/`concluir` é uma transação curta própria dentro de
    `estado.py`. `connection.close()` no `finally` — a conexão Django
    (ORM do PCA) aberta por esta thread nunca fica pendurada."""

    def progresso(etapa: str, texto_parcial: str) -> None:
        try:
            estado.andamento_gravar(
                dados.requisicao_id, agora=timezone.now(), etapa=etapa, texto_parcial=texto_parcial
            )
        except estado.EstadoIndisponivel:
            logger.warning("andamento indisponível requisicao=%s", dados.requisicao_id)

    try:
        Usuario = get_user_model()
        usuario = Usuario.objects.filter(pk=dados.usuario_id).first()
        exercicio_obj = Exercicio.objects.filter(ano=dados.exercicio_ano).first()
        if usuario is None or exercicio_obj is None:
            estado.concluir(
                requisicao_id=dados.requisicao_id, agora=timezone.now(), erro_codigo="revalidacao"
            )
            return

        cliente_atual = cliente_mod.criar_cliente()
        resposta = agente.responder(
            usuario=usuario,
            exercicio=exercicio_obj,
            pergunta=dados.pergunta,
            trocas=dados.trocas,
            cliente=cliente_atual,
            agora=dados.agora,
            progresso=progresso,
        )

        # Revalidação pós-rede — idêntica à de antes desta quick:
        # logout/nova conversa/revogação durante a chamada descartam a
        # resposta. Sem `request`: a sessão é conferida pelo `session_key`
        # capturado, não por `request.session`.
        usuario_atual = Usuario.objects.filter(pk=dados.usuario_id, is_active=True).first()
        sessao_ainda_existe = bool(dados.session_key) and SessionStore(
            session_key=dados.session_key
        ).exists(dados.session_key)
        permissoes_hash_atual = estado.hash_permissoes(usuario_atual) if usuario_atual else None

        if usuario_atual is None or not sessao_ainda_existe or permissoes_hash_atual != dados.permissoes_hash:
            estado.concluir(
                requisicao_id=dados.requisicao_id,
                agora=timezone.now(),
                tokens_entrada=resposta.tokens_entrada,
                tokens_saida=resposta.tokens_saida,
                erro_codigo="revalidacao",
            )
            logger.info("resposta descartada motivo=revalidacao usuario=%s", dados.usuario_id)
            return

        if resposta.erro_codigo:
            estado.concluir(
                requisicao_id=dados.requisicao_id,
                agora=timezone.now(),
                tokens_entrada=resposta.tokens_entrada,
                tokens_saida=resposta.tokens_saida,
                erro_codigo=resposta.erro_codigo,
            )
            return

        gravou = estado.acrescentar_troca(
            dados.conversa_id,
            usuario_id=dados.usuario_id,
            sessao_hash=dados.sessao_hash,
            permissoes_hash=permissoes_hash_atual,
            agora=timezone.now(),
            pergunta=dados.pergunta,
            resposta_md=resposta.texto_md,
            referencias=resposta.referencias,
            proveniencia=resposta.proveniencia,
            rodape=resposta.rodape,
        )
        estado.concluir(
            requisicao_id=dados.requisicao_id,
            agora=timezone.now(),
            tokens_entrada=resposta.tokens_entrada,
            tokens_saida=resposta.tokens_saida,
            erro_codigo=None if gravou else "revalidacao",
        )
    except estado.EstadoIndisponivel:
        logger.warning("estado indisponível ao processar requisicao=%s", dados.requisicao_id)
    except Exception:  # noqa: BLE001 — a thread nunca morre sem registrar/concluir
        logger.exception("erro inesperado ao processar requisicao=%s", dados.requisicao_id)
        try:
            estado.concluir(requisicao_id=dados.requisicao_id, agora=timezone.now(), erro_codigo="interno")
        except estado.EstadoIndisponivel:
            pass
    finally:
        connection.close()


def _nao_configurado(request):
    return TemplateResponse(
        request,
        "core/erro.html",
        {
            "codigo": 404,
            "titulo": "Assistente não configurado",
            "texto": "O assistente do PCA não está habilitado neste ambiente.",
        },
        status=404,
    )


def _indisponivel(request):
    """/A20 — arquivo auxiliar corrompido/inacessível é um erro
    operacional seguro: 503 curto, NUNCA 500 cru, NUNCA recria o arquivo
    nem zera a quota (a recriação/reset é decisão de operação, não de
    request). Mesmo template de `_nao_configurado`, código e mensagem
    diferentes."""
    return TemplateResponse(
        request,
        "core/erro.html",
        {
            "codigo": 503,
            "titulo": "Assistente temporariamente indisponível",
            "texto": (
                "Um arquivo auxiliar do assistente está indisponível no momento. "
                "Tente novamente em instantes."
            ),
        },
        status=503,
    )


def _ir_para(request, destino):
    """Sucesso de `_perguntar`/`nova_conversa_view`: sem HTMX é o
    PRG comum (redirect); com HTMX vira 200 + `HX-Location` (path/target/
    select/swap) para o htmx buscar `destino` e trocar só `#area-chat`,
    sem recarregar a página. Redirects para `core:login` (sessão expirada)
    NUNCA passam por aqui — continuam `redirect()` puro, convertido em
    `HX-Redirect` pelo `HtmxRedirectMiddleware` global (a página inteira
    muda, não só `#area-chat`)."""
    if getattr(request, "htmx", False):
        return HttpResponse(
            status=200,
            headers={
                "HX-Location": json.dumps(
                    {
                        "path": destino,
                        "target": "#area-chat",
                        "select": "#area-chat",
                        "swap": "outerHTML show:#pergunta:bottom",
                    }
                )
            },
        )
    return redirect(destino)


def _contexto_identidade(request):
    if not request.session.session_key:
        request.session.save()
    sessao_hash = estado.hash_sessao(request.session.session_key)
    permissoes_hash = estado.hash_permissoes(request.user)
    return request.user.pk, sessao_hash, permissoes_hash


def _conversa_atual(request, exercicio, agora):
    usuario_id, sessao_hash, permissoes_hash = _contexto_identidade(request)
    conversa_id = request.session.get(estado.CHAVE_SESSAO_CONVERSA)
    conversa = None
    if conversa_id:
        conversa = estado.carregar_conversa(
            conversa_id,
            usuario_id=usuario_id,
            sessao_hash=sessao_hash,
            permissoes_hash=permissoes_hash,
            agora=agora,
        )
    if conversa is None or conversa.exercicio != exercicio.ano:
        novo_id = estado.criar_conversa(usuario_id, sessao_hash, permissoes_hash, exercicio.ano, agora)
        request.session[estado.CHAVE_SESSAO_CONVERSA] = novo_id
        conversa = estado.carregar_conversa(
            novo_id,
            usuario_id=usuario_id,
            sessao_hash=sessao_hash,
            permissoes_hash=permissoes_hash,
            agora=agora,
        )
    return conversa


def _contexto_pagina(request, exercicio, conversa, form, *, status=200, retry_after=None, sugestao=None):
    usuario_id, sessao_hash, permissoes_hash = _contexto_identidade(request)
    agora = timezone.now()
    dia = estado.dia_civil(agora)
    consumo = estado.consumo(usuario_id, dia)
    limite = settings.IA_MAX_PERGUNTAS_DIA
    quota_esgotada = consumo.perguntas >= limite

    trocas = []
    for troca in (conversa.trocas if conversa else []):
        trocas.append(
            {
                "pergunta": troca.pergunta,
                "resposta_html": renderizacao.renderizar_resposta(troca.resposta_md),
                "referencias_html": renderizacao.renderizar_referencias(troca.referencias),
                "rodape": troca.rodape,
            }
        )

    requisicao_id = None
    if conversa is not None and not quota_esgotada:
        requisicao_id = estado.emitir_requisicao(
            usuario_id=usuario_id,
            sessao_hash=sessao_hash,
            conversa_id=conversa.id,
            exercicio=exercicio.ano,
            agora=agora,
        )

    # Se já existe uma pergunta em processamento nesta conversa
    # (a página foi recarregada/reaberta enquanto a thread ainda respondia),
    # mostra a bolha de progresso desde o primeiro GET, não só após o POST.
    andamento_contexto = None
    if conversa is not None:
        rid_em_andamento = estado.requisicao_em_andamento(usuario_id, sessao_hash, conversa.id)
        if rid_em_andamento:
            info_andamento = estado.andamento_ler(rid_em_andamento)
            if info_andamento is not None:
                andamento_contexto = {
                    "requisicao_id": rid_em_andamento,
                    "pergunta": info_andamento.pergunta,
                    "etapa": info_andamento.etapa or "Pensando…",
                    "texto_parcial_html": (
                        renderizacao.renderizar_resposta(info_andamento.texto_parcial)
                        if info_andamento.texto_parcial
                        else ""
                    ),
                    "destino_pagina": f"{reverse('assistente:pagina')}?exercicio={exercicio.ano}#pergunta",
                }

    indice_publicado_em = indice.publicado_em()
    contexto = {
        "trilha": navegacao.trilha_padrao(exercicio, "Assistente de IA"),
        "exercicio": exercicio,
        "exercicios": Exercicio.objects.order_by("-ano"),
        "consumo": consumo,
        "limite": limite,
        "quota_esgotada": quota_esgotada,
        "trocas": trocas,
        "form": form,
        "requisicao_id": requisicao_id,
        "andamento": andamento_contexto,
        "sugestao": sugestao or "",
        # (Fase 39) — "Textos indexados em" na faixa de contexto.
        "indice_publicado_em": (
            timezone.localtime(datetime.fromisoformat(indice_publicado_em)).strftime(
                "%d/%m/%Y %H:%M"
            )
            if indice_publicado_em
            else "não disponível"
        ),
    }
    # Para requisição htmx, 400/409/429 respondem 200 com a área
    # re-renderizada (a mensagem/erro já está no contexto: `messages` ou
    # `form.pergunta.errors`); sem htmx, o código original é preservado.
    status_resposta = 200 if getattr(request, "htmx", False) else status
    resposta = render(request, "assistente/pagina.html", contexto, status=status_resposta)
    if retry_after:
        resposta["Retry-After"] = str(retry_after)
    return resposta


def pagina_view(request):
    if not settings.IA_API_KEY:
        return _nao_configurado(request)

    exercicio = resolver_exercicio(request.GET)
    if exercicio is None:
        return render(
            request,
            "assistente/pagina.html",
            {
                "trilha": navegacao.trilha_padrao(None, "Assistente de IA"),
                "exercicio": None,
                "exercicios": Exercicio.objects.none(),
                "trocas": [],
                "form": None,
                "requisicao_id": None,
                "sugestao": "",
                "sem_exercicio": True,
            },
        )

    agora = timezone.now()
    try:
        conversa = _conversa_atual(request, exercicio, agora)
        sugestao = (request.GET.get("sugestao") or "")[:1000]
        form = PerguntaForm(initial={"pergunta": sugestao, "exercicio": exercicio.ano})
        return _contexto_pagina(request, exercicio, conversa, form, sugestao=sugestao)
    except estado.EstadoIndisponivel:
        return _indisponivel(request)


@require_POST
def perguntar_view(request):
    if not settings.IA_API_KEY:
        return _nao_configurado(request)
    try:
        return _perguntar(request)
    except estado.EstadoIndisponivel:
        return _indisponivel(request)


def _perguntar(request):
    exercicio_pagina = resolver_exercicio(request.GET) or resolver_exercicio(request.POST)
    form = PerguntaForm(request.POST)
    if not form.is_valid():
        conversa = _conversa_atual(request, exercicio_pagina, timezone.now()) if exercicio_pagina else None
        return _contexto_pagina(request, exercicio_pagina, conversa, form, status=400)

    exercicio_obj = Exercicio.objects.filter(ano=form.cleaned_data["exercicio"]).first()
    if exercicio_obj is None:
        conversa = _conversa_atual(request, exercicio_pagina, timezone.now()) if exercicio_pagina else None
        return _contexto_pagina(request, exercicio_pagina, conversa, form, status=400)

    agora = timezone.now()
    usuario_id, sessao_hash, permissoes_hash = _contexto_identidade(request)
    conversa = _conversa_atual(request, exercicio_obj, agora)

    resultado = estado.reservar(
        requisicao_id=form.cleaned_data["requisicao_id"],
        usuario_id=usuario_id,
        sessao_hash=sessao_hash,
        conversa_id=conversa.id,
        exercicio=exercicio_obj.ano,
        agora=agora,
        limite=settings.IA_MAX_PERGUNTAS_DIA,
    )

    destino_pagina = f"{reverse('assistente:pagina')}?exercicio={exercicio_obj.ano}#pergunta"

    if isinstance(resultado, estado.Recusa):
        if resultado.motivo == "invalida":
            return _contexto_pagina(request, exercicio_obj, conversa, form, status=400)
        if resultado.motivo == "concluida":
            messages.info(request, "Essa pergunta já foi respondida.")
            return _ir_para(request, destino_pagina)
        if resultado.motivo == "falha":
            messages.warning(
                request,
                "A tentativa anterior falhou; nenhuma pergunta nova foi cobrada. "
                "Envie de novo se quiser tentar outra vez.",
            )
            return _ir_para(request, destino_pagina)
        if resultado.motivo in ("em_andamento", "concorrencia"):
            messages.warning(
                request,
                "Já existe uma pergunta sua em andamento. Aguarde a resposta antes de enviar outra.",
            )
            return _contexto_pagina(request, exercicio_obj, conversa, form, status=409)
        # resultado.motivo == "quota"
        retry_after = estado.segundos_ate_meia_noite(agora)
        messages.warning(
            request,
            f"Você atingiu o limite de {settings.IA_MAX_PERGUNTAS_DIA} perguntas por dia. "
            "O limite renova à meia-noite.",
        )
        return _contexto_pagina(
            request, exercicio_obj, conversa, form, status=429, retry_after=retry_after
        )

    # resultado é Reserva — a pergunta e a chamada de rede saem do request:
    #a thread processa em segundo plano, gravando o progresso
    # em `andamento`; o POST devolve na hora, sem segurar o slot do Gunicorn.
    pergunta_texto = form.cleaned_data["pergunta"]
    estado.andamento_gravar(
        resultado.requisicao_id, agora=agora, etapa="Pensando…", texto_parcial="", pergunta=pergunta_texto
    )
    dados = PedidoEmAndamento(
        requisicao_id=resultado.requisicao_id,
        usuario_id=usuario_id,
        session_key=request.session.session_key,
        sessao_hash=sessao_hash,
        permissoes_hash=permissoes_hash,
        exercicio_ano=exercicio_obj.ano,
        conversa_id=conversa.id,
        trocas=conversa.trocas,
        pergunta=pergunta_texto,
        agora=agora,
    )
    _iniciar_thread(_processar_em_segundo_plano, dados)

    # Rede de segurança (também cobre a suíte, que substitui `_iniciar_thread`
    # por execução síncrona): se a sessão ATUAL já não existe mais no
    # instante em que a thread termina, `request.session.flush()` evita que
    # o SessionMiddleware tente salvar uma sessão apagada no fim da request
    # (senão: SessionInterrupted -> 400, mascarando o redirect).
    session_key = request.session.session_key
    if session_key and not SessionStore(session_key=session_key).exists(session_key):
        request.session.flush()
        return redirect("core:login")

    return _ir_para(request, destino_pagina)


def andamento_view(request, requisicao_id):
    """GET de polling — `hx-trigger="load delay:400ms, every
    700ms"` na bolha de progresso. `em_andamento` devolve o fragmento
    atualizado; `concluida`/`falha`/lease vencido devolvem `HX-Location`
    (o polling cessa porque a bolha é substituída pela área inteira)."""
    if not settings.IA_API_KEY:
        return _nao_configurado(request)
    try:
        usuario_id, sessao_hash, _permissoes_hash = _contexto_identidade(request)
        requisicao = estado.requisicao_ler(requisicao_id, usuario_id=usuario_id, sessao_hash=sessao_hash)
        if requisicao is None:
            raise Http404("requisição não encontrada")

        destino_pagina = f"{reverse('assistente:pagina')}?exercicio={requisicao.exercicio}#pergunta"
        agora = timezone.now()

        if requisicao.estado == "em_andamento":
            if requisicao.lease_ate and requisicao.lease_ate < agora.isoformat():
                # Thread morta (reciclagem do worker, crash) — libera nova
                # pergunta sem deixar o usuário travado esperando para sempre.
                estado.concluir(requisicao_id=requisicao_id, agora=agora, erro_codigo="interrompida")
                messages.error(request, "A resposta foi interrompida. Tente perguntar de novo.")
                return _ir_para(request, destino_pagina)

            info = estado.andamento_ler(requisicao_id)
            contexto = {
                "requisicao_id": requisicao_id,
                "etapa": (info.etapa if info else "") or "Pensando…",
                "texto_parcial_html": (
                    renderizacao.renderizar_resposta(info.texto_parcial)
                    if info and info.texto_parcial
                    else ""
                ),
                "destino_pagina": destino_pagina,
            }
            return render(request, "assistente/_bolha_andamento.html", contexto)

        if requisicao.estado == "falha" and requisicao.erro_codigo != "revalidacao":
            rotulo_erro = _RODAPE_ERRO_POR_CODIGO.get(requisicao.erro_codigo, "erro desconhecido")
            messages.error(
                request,
                f"O assistente não conseguiu responder agora (motivo: {rotulo_erro}). "
                "A pergunta contou no seu limite diário.",
            )

        # "concluida", "falha" com revalidação silenciosa (mesmo padrão de
        # antes desta quick — nenhuma mensagem, a troca simplesmente não
        # existe) — a área inteira é re-renderizada; o polling cessa.
        return _ir_para(request, destino_pagina)
    except estado.EstadoIndisponivel:
        return _indisponivel(request)


@require_POST
def nova_conversa_view(request):
    if not settings.IA_API_KEY:
        return _nao_configurado(request)

    exercicio = resolver_exercicio(request.POST) or resolver_exercicio(request.GET)
    conversa_id = request.session.get(estado.CHAVE_SESSAO_CONVERSA)
    try:
        if conversa_id:
            estado.apagar_conversa(conversa_id)
    except estado.EstadoIndisponivel:
        return _indisponivel(request)
    request.session.pop(estado.CHAVE_SESSAO_CONVERSA, None)

    destino = reverse("assistente:pagina")
    if exercicio is not None:
        destino += f"?exercicio={exercicio.ano}"
    return _ir_para(request, destino)


def documentacao_view(request, slug):
    """Documentação autenticada por slug do manifesto (A12) — slug
    fora do manifesto ou com traversal (`<slug:>` já rejeita `/`/`.`) vira
    404; permissão do documento (quando declarada) vira 403 da casca."""
    if not settings.IA_API_KEY:
        return _nao_configurado(request)

    doc = fontes.documento_do_manifesto(slug)
    if doc is None:
        raise Http404("documento não encontrado")
    if doc["permissao"] and not request.user.has_perm(doc["permissao"]):
        raise PermissionDenied

    caminho = Path(settings.BASE_DIR) / doc["arquivo"]
    try:
        texto = caminho.read_text(encoding="utf-8")
    except OSError:
        raise Http404("documento indisponível") from None

    secoes = fontes.secoes_markdown(texto, excluir=doc["secoes_excluidas"])
    contexto = {
        "trilha": [("Assistente de IA", reverse("assistente:pagina")), (doc["titulo"], None)],
        "titulo_documento": doc["titulo"],
        "secoes": [
            {"titulo": titulo_secao, "corpo_html": renderizacao.renderizar_documento(corpo)}
            for titulo_secao, corpo in secoes
        ],
    }
    return render(request, "assistente/documentacao.html", contexto)
