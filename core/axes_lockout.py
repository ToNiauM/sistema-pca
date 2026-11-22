def resposta_bloqueio(request, original_response, credentials=None):
    """Configurado em `AXES_LOCKOUT_CALLABLE`.

    Sem isto, `axes.middleware.AxesMiddleware` substitui a resposta de
    QUALQUER view por uma página HTML genérica própria (status
    `AXES_HTTP_RESPONSE_CODE`, default 429) sempre que
    `request.axes_locked_out` for `True` — mesmo quando a view (aqui,
    `core.views.login_view`) já detectou o bloqueio e devolveu o fragmento
    correto em HTTP 200. Sem este callable, a página genérica do axes
    sobrescreveria silenciosamente o fragmento inline e quebraria a mesma
    convenção htmx que a Armadilha 1 exige (4xx/qualquer
    coisa fora de 200 não faz swap por padrão) — descoberto nesta revisão
    ao testar a 6ª tentativa via HTTP, não apenas via `AxesBackend` direto.
    """
    return original_response
