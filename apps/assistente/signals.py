"""Sinal de logout do Assistente do PCA — apaga a conversa da
sessão ANTES dela ser descartada (`django.contrib.auth.logout()` dispara
`user_logged_out` antes de `request.session.flush()`, `core/views.py::
logout_view`). Nunca lança: um `EstadoIndisponivel` aqui não pode impedir
o logout de completar."""

import logging

from django.contrib.auth.signals import user_logged_out
from django.dispatch import receiver

from apps.assistente import estado

logger = logging.getLogger("apps.assistente")


@receiver(user_logged_out)
def apagar_conversa_no_logout(sender, request, user, **kwargs):
    if user is None or not getattr(request, "session", None):
        return
    session_key = request.session.session_key
    if not session_key:
        return
    try:
        estado.apagar_conversas_da_sessao(user.pk, estado.hash_sessao(session_key))
    except estado.EstadoIndisponivel:
        logger.warning("logout falha_limpeza_conversa")
    request.session.pop(estado.CHAVE_SESSAO_CONVERSA, None)
