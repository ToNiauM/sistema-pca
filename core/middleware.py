import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.conf import settings
from django.contrib import messages
from django.db import OperationalError
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import Resolver404, resolve
from django.utils.http import url_has_allowed_host_and_scheme
from django_htmx.http import HttpResponseClientRedirect


_RE_EXTENSAO_CHROME = re.compile(r"^chrome-extension://[a-p]{32}$")


class CorsExtensaoMiddleware:
    """CORS restrito a `/api/` para as extensões SEI Pro (Fase 42, Plano
    42-03): nenhuma outra rota do sistema ganha cabeçalho CORS
    algum. CORS nunca autentica sozinho — só decide quem recebe o cabeçalho
    de resposta; a autenticação real é sempre o token Bearer
    (`apps/pca/api/autenticacao.py`), verificada independente da origem.

    Origem permitida: bate EXATAMENTE com algum item de
    `settings.API_ORIGENS_EXTENSAO` OU casa com
    `^chrome-extension://[a-p]{32}$` (ID de extensão Chrome não empacotada —
    muda por máquina/instalação; quem protege o acesso é o token, não a
    origem). `OPTIONS` com origem permitida responde 200 vazio direto
    daqui (preflight), sem chegar na view. Origem ausente ou não permitida:
    a resposta segue normal, sem nenhum cabeçalho CORS — o browser da
    extensão bloqueia sozinho.

    Posição em `MIDDLEWARE` (config/settings/base.py): logo após
    `CommonMiddleware`, antes de `CsrfViewMiddleware` — as views da API são
    `csrf_exempt`, então a ordem exata em relação ao CSRF não importa, mas
    precisa vir antes de `LoginRequiredMiddleware` (a do plano
    isenta as views da API via `login_not_required`).

    `PUT` entrou na v1.1 (`PUT /api/sei/ficha`) — a lógica
    de origem permitida é independente do método."""

    METODOS_PERMITIDOS = "GET, POST, PUT, OPTIONS"
    CABECALHOS_PERMITIDOS = "Authorization, Content-Type"

    def __init__(self, get_response):
        self.get_response = get_response

    def _origem_permitida(self, origem):
        if not origem:
            return False
        if origem in settings.API_ORIGENS_EXTENSAO:
            return True
        return bool(_RE_EXTENSAO_CHROME.match(origem))

    def __call__(self, request):
        if not request.path.startswith("/api/"):
            return self.get_response(request)

        origem = request.headers.get("Origin")
        if not self._origem_permitida(origem):
            return self.get_response(request)

        if request.method == "OPTIONS":
            resposta = HttpResponse(status=200)
        else:
            resposta = self.get_response(request)

        resposta["Access-Control-Allow-Origin"] = origem
        resposta["Access-Control-Allow-Methods"] = self.METODOS_PERMITIDOS
        resposta["Access-Control-Allow-Headers"] = self.CABECALHOS_PERMITIDOS
        return resposta


class HtmxRedirectMiddleware:
    """Converte qualquer 301/302 numa requisição htmx em HX-Redirect.

    Sem isto, o XHR do htmx segue o redirect de forma transparente e o
    navegador troca o alvo do swap por uma página inteira — o caso letal é
    a expiração de sessão: o `<form>` de login inteiro aparece aninhado
    dentro do fragmento de uma linha da tabela (Pitfall 2). Precisa vir
    DEPOIS de `django_htmx.middleware.HtmxMiddleware`, que é quem popula
    `request.htmx`.

    QA de segurança 30/09/2026 (fluxos #9) — quando o redirect é para
    `settings.LOGIN_URL` com `next=`, esse `next` hoje é o path do
    FRAGMENTO que a requisição htmx buscava (ex.: `/processo/2026/15/
    acompanhamento`), não a página real que o navegador mostra. Depois do
    login, o usuário cai num fragmento cru, sem casca/menu. A correção
    reescreve `next` a partir de `HX-Current-URL` (a página de origem),
    com a mesma validação `url_has_allowed_host_and_scheme` de
    `core/views.py::login_view` (M1) — sem o header, ou com um valor
    reprovado na validação, o `Location` original não é tocado.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if getattr(request, "htmx", False) and response.status_code in (301, 302):
            return HttpResponseClientRedirect(
                self._reescrever_next_do_login(request, response["Location"])
            )
        return response

    def _reescrever_next_do_login(self, request, location):
        partes_location = urlsplit(location)
        if partes_location.path != settings.LOGIN_URL:
            return location

        hx_current_url = request.headers.get("HX-Current-URL")
        if not hx_current_url:
            return location

        partes_origem = urlsplit(hx_current_url)
        destino = partes_origem.path + (
            f"?{partes_origem.query}" if partes_origem.query else ""
        )
        if not url_has_allowed_host_and_scheme(
            destino,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return location

        query_location = dict(parse_qsl(partes_location.query, keep_blank_values=True))
        query_location["next"] = destino
        return urlunsplit(
            (
                partes_location.scheme,
                partes_location.netloc,
                partes_location.path,
                urlencode(query_location),
                partes_location.fragment,
            )
        )


class TrocaSenhaObrigatoriaMiddleware:
    """Intercepta qualquer navegação de usuário autenticado com
    `senha_temporaria=True` e redireciona para a tela de troca — nenhuma
    rota de negócio é exceção, nem a do próprio superusuário (plano).

    Posição no FINAL de `MIDDLEWARE` (depois de `LoginRequiredMiddleware`,
    config/settings/base.py): o `redirect()` comum emitido aqui sobe pela
    pilha e passa por `HtmxRedirectMiddleware`, que está mais cedo na lista
    e por isso envolve esta por fora na volta — é ele quem converte o
    302 em `HX-Redirect` quando a requisição é htmx, sem duplicar essa
    lógica aqui.
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


class BancoOcupadoMiddleware:
    """Traduz `OperationalError("database is locked")` numa mensagem amigável
    em vez da página de erro 500 padrão do Django (revisão da Fase 31).

    Com SQLite + `transaction_mode="IMMEDIATE"`, toda escrita
    adquire o lock do banco INTEIRO pela duração da transação — diferente do
    lock por linha do PostgreSQL. `select_for_update()` (usado em
    `apps/pca/services.py`) é NO-OP no backend sqlite3 do Django (MD-02): a
    exclusão mútua real vem inteiramente desse lock de banco inteiro, e uma
    segunda escrita concorrente pode estourar em `OperationalError` depois de
    `busy_timeout` (20s) — cenário real durante a reunião mensal, quando
    várias pessoas editam ao mesmo tempo (Core Value da Fase 31).

    Só trata POST (o caminho de escrita): a resposta é um redirect comum
    (PRG) para a própria página de origem, com uma mensagem de
    `django.contrib.messages` pedindo nova tentativa — o mesmo `redirect()`
    sobe pela pilha e é convertido em `HX-Redirect` por
    `HtmxRedirectMiddleware` (mais cedo em `MIDDLEWARE`, config/settings/
    base.py) quando a requisição é htmx. Precisa vir DEPOIS de
    `MessageMiddleware`/`SessionMiddleware` (para que `request._messages` já
    exista) — por isso está por último em `MIDDLEWARE`, mais perto da view,
    o que também dá a ela a primeira chance de tratar a exceção
    (`process_exception` é chamado de baixo para cima). GET nunca escreve;
    a exceção simplesmente propaga (Django devolve o 500 padrão), sem
    mensagem de retry que não faria sentido numa leitura.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if not isinstance(exception, OperationalError):
            return None
        if "locked" not in str(exception).lower():
            return None
        if request.method != "POST":
            return None
        messages.error(
            request,
            "O sistema está gravando outra alteração neste momento. "
            "Aguarde alguns segundos e tente novamente.",
        )
        destino = request.META.get("HTTP_REFERER") or request.get_full_path()
        return redirect(destino)


class CacheControlAutenticadoMiddleware:
    """QA de segurança 30/09/2026 (fluxos #13) — qualquer resposta de
    usuário autenticado sem `Cache-Control` próprio permitia que o HTML
    sensível ficasse reaproveitável pelo cache do navegador/disco num
    computador compartilhado, depois do logout. Cerca de 16 views já
    setam `resposta["Cache-Control"] = "private, no-store"` manualmente
    (ex.: `apps/pca/views.py::tabela_view`) — esta middleware NUNCA
    sobrescreve esse valor (`not response.has_header(...)`), só cobre as
    rotas que ainda não decidiram nada.

    Por último em `MIDDLEWARE` (depois de `BancoOcupadoMiddleware`,
    config/settings/base.py): mais perto da view, vê a resposta final de
    qualquer rota.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        usuario = getattr(request, "user", None)
        if (
            usuario is not None
            and usuario.is_authenticated
            and not response.has_header("Cache-Control")
        ):
            response["Cache-Control"] = "private, no-store"
        return response
