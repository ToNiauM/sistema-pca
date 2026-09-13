def resposta_bloqueio(request, original_response, credentials=None):
    """Configurado em `AXES_LOCKOUT_CALLABLE`.

    Sem isto, `axes.middleware.AxesMiddleware` substitui a resposta de
    qualquer view por uma página HTML genérica própria sempre que
    `request.axes_locked_out` for `True` — mesmo quando a view já detectou
    o bloqueio e devolveu o fragmento correto em HTTP 200.
    """
    return original_response
