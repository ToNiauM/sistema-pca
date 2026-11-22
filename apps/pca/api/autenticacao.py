"""Autenticação Bearer + guarda de tamanho de corpo da API (Fase 42, Plano
42-03). `requer_token()` resolve o cabeçalho `Authorization` para o usuário
dono do token (`core.models.TokenApi.autenticar`) — nunca sessão de
navegador; checagem manual (não `@login_required`/`@permission_required` do
Django), porque 401/403/429 precisam de corpo JSON distinto, não da página
de login padrão."""

from __future__ import annotations

import functools

from django.conf import settings
from django.http import JsonResponse

from apps.pca.api import limitador
from core.models import TokenApi

PREFIXO_BEARER = "Bearer "


def _erro(status: int, codigo: str) -> JsonResponse:
    return JsonResponse({"erro": codigo}, status=status)


def pode_instruir(usuario) -> bool:
    """(V-1 do documento interno de desenho): OR semântico — o grupo novo
    `demandante` (`pca.instruir_contratacao`) grava `POST /vinculo`/
    `PUT /ficha` SEM precisar de `pca.editar_pca`; quem já tem
    `pca.editar_pca` (grupo `editor`) também grava, sem precisar entrar no
    grupo `demandante`."""
    return usuario.has_perm("pca.instruir_contratacao") or usuario.has_perm(
        "pca.editar_pca"
    )


def requer_token(permissao=None):
    """Decorator de view: sem `Authorization`, sem o prefixo `Bearer `, ou
    com token inválido/revogado -> 401 `{"erro": "nao_autenticado"}`, sem
    chamar a view. Com token válido, conta a chamada contra o limite de 60/
    min ANTES de checar `permissao` (uma 61ª chamada com token e permissão
    corretos ainda devolve 429, nunca chega na view) — `limitador.permitido`
    só é chamado quando o token foi encontrado (tentativas com token
    inválido nunca contam contra o limite de ninguém). `permissao` aceita
    uma STRING (codename `"app.codename"`, checada via `usuario.has_perm`)
    OU um CALLABLE de um argumento (`permissao(usuario) -> bool`, quick
    Usado por `pode_instruir` acima, OR de duas permissões);
    falso em qualquer um dos dois casos -> 403 `{"erro": "sem_permissao"}`.
    Caso contrário, define `request.user` como o usuário do token (para que
    `HistoryRequestMiddleware`/trilha de histórico vejam o usuário certo) e
    chama a view."""

    def decorador(view):
        @functools.wraps(view)
        def view_decorada(request, *args, **kwargs):
            cabecalho = request.META.get("HTTP_AUTHORIZATION", "")
            if not cabecalho.startswith(PREFIXO_BEARER):
                return _erro(401, "nao_autenticado")

            valor_em_claro = cabecalho[len(PREFIXO_BEARER):]
            usuario = TokenApi.autenticar(valor_em_claro)
            if usuario is None:
                return _erro(401, "nao_autenticado")

            token_hash = TokenApi._hash_de(valor_em_claro)
            if not limitador.permitido(token_hash):
                return _erro(429, "limite_requisicoes")

            if permissao is not None:
                ok = (
                    permissao(usuario)
                    if callable(permissao)
                    else usuario.has_perm(permissao)
                )
                if not ok:
                    return _erro(403, "sem_permissao")

            request.user = usuario
            return view(request, *args, **kwargs)

        return view_decorada

    return decorador


def corpo_dentro_do_limite(request) -> bool:
    """`False` quando `CONTENT_LENGTH` ultrapassa `settings.API_MAX_CORPO_MB`
    (usada pelo POST do plano antes de qualquer parsing do corpo —
    413 sem gastar CPU com JSON grande demais). Sem `CONTENT_LENGTH`
    (GET, ou corpo vazio), devolve `True` — não há corpo a medir aqui."""
    content_length = request.META.get("CONTENT_LENGTH")
    if not content_length:
        return True
    try:
        tamanho = int(content_length)
    except (TypeError, ValueError):
        return True
    limite = settings.API_MAX_CORPO_MB * 1024 * 1024
    return tamanho <= limite
