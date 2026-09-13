from django_htmx.http import HttpResponseClientRedirect


class HtmxRedirectMiddleware:
    """Converte 301/302 numa requisição HTMX em HX-Redirect.

    Sem isto, o XHR segue o redirect e o navegador troca um fragmento (uma linha de tabela) pela
    página de login inteira. Precisa vir DEPOIS de django_htmx.middleware.HtmxMiddleware.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if getattr(request, "htmx", False) and response.status_code in (301, 302):
            return HttpResponseClientRedirect(response["Location"])
        return response
