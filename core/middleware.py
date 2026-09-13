from django.conf import settings
from django.shortcuts import redirect
from django.urls import Resolver404, resolve
from django_htmx.http import HttpResponseClientRedirect


class HtmxRedirectMiddleware:
    """Converte qualquer 301/302 numa requisição htmx em HX-Redirect.

    Sem isto, o XHR do htmx segue o redirect de forma transparente e o
    navegador troca o alvo do swap por uma página inteira — o caso letal é
    a expiração de sessão: o `<form>` de login inteiro aparece aninhado
    dentro do fragmento de uma linha da tabela. Precisa vir depois de
    `django_htmx.middleware.HtmxMiddleware`, que popula `request.htmx`.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if getattr(request, "htmx", False) and response.status_code in (301, 302):
            return HttpResponseClientRedirect(response["Location"])
        return response


class TrocaSenhaObrigatoriaMiddleware:
    """Intercepta qualquer navegação de usuário autenticado com
    `senha_temporaria=True` e redireciona para a tela de troca — nenhuma
    rota de negócio é exceção, nem a do próprio superusuário.

    Posição no final de `MIDDLEWARE`: o `redirect()` emitido aqui sobe pela
    pilha e passa por `HtmxRedirectMiddleware`, que converte o 302 em
    `HX-Redirect` quando a requisição é htmx.
    """

    NOMES_ISENTOS = {
        "core:trocar_senha",
        "core:logout",
        "core:login",
        "healthz",
        "core:manifest",
        "core:service_worker",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def _rota_isenta(self, request):
        if request.path.startswith(settings.STATIC_URL):
            return True
        try:
            match = resolve(request.path)
        except Resolver404:
            return False
        nome = (
            f"{match.namespace}:{match.url_name}"
            if match.namespace
            else match.url_name
        )
        return nome in self.NOMES_ISENTOS

    def __call__(self, request):
        usuario = getattr(request, "user", None)
        if (
            usuario is not None
            and usuario.is_authenticated
            and usuario.senha_temporaria
            and not self._rota_isenta(request)
        ):
            return redirect("core:trocar_senha")
        return self.get_response(request)
