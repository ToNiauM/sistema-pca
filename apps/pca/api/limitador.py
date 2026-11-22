"""Limite de requisições por token (Fase 42): 60
requisições/minuto por token, contador em `django.core.cache.cache` (janela
fixa de 1 minuto, chave composta por `token_hash` + o minuto corrente).

O contador é por processo/worker (cache em memória local, sem Redis) —
suficiente como teto de abuso contra um token comprometido, não como
garantia distribuída exata entre múltiplos workers/processos gunicorn."""

from __future__ import annotations

import time

from django.core.cache import cache

LIMITE_POR_MINUTO = 60


def permitido(token_hash: str) -> bool:
    """`False` quando a chamada que acabou de incrementar o contador já
    ultrapassa o limite (a própria chamada que estoura já conta — por isso
    a checagem é "maior que 60", não "maior ou igual")."""
    minuto = int(time.time()) // 60
    chave = f"api_limitador:{token_hash}:{minuto}"
    cache.add(chave, 0, timeout=70)
    valor = cache.incr(chave)
    return valor <= LIMITE_POR_MINUTO
