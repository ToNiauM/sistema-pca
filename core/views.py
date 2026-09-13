import json
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.forms import PasswordChangeForm
from django.db import connection
from django.http import HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect, render
from django.template.response import TemplateResponse
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from django_htmx.http import HttpResponseClientRedirect

from core.forms.perfil import PerfilForm
from core.templatetags.dsgov import numero, percentual

logger_csrf = logging.getLogger("django.security.csrf")


@login_not_required
def healthz(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return JsonResponse({"status": "error"}, status=503)
    return JsonResponse({"status": "ok"})


@login_not_required
@never_cache
def login_view(request):
    """Página inteira na casca da skill dsgov (`core/login.html`,
    `body.dsgov-login`), nunca fragmento HTMX: o form é um POST
    tradicional, sem `hx-post`.

    Nunca usa `except PermissionDenied` em torno de `authenticate()`: o
    dispatcher do Django captura o `PermissionDenied` que o `AxesBackend`
    levanta internamente e nunca o repassa para quem chamou — só devolve
    `None`. A forma correta de distinguir "bloqueado pelo axes" de
    "credenciais erradas comuns" é o atributo `request.axes_locked_out`.

    O campo do POST chama-se `username` — só o rótulo exibido em
    `core/login.html` virou "E-mail institucional"; o valor continua
    sendo o e-mail do usuário (`USERNAME_FIELD`).
    """
    if request.user.is_authenticated:
        return redirect("core:inicio")

    contexto = {"erro": None, "bloqueado": False, "usuario_digitado": ""}
    if request.method == "POST":
        usuario_digitado = request.POST.get("username", "").strip()
        senha = request.POST.get("password", "")
        contexto["usuario_digitado"] = usuario_digitado

        user = authenticate(request, username=usuario_digitado, password=senha)
        if user is not None:
            login(request, user)
            # Destino sem `next` explícito é `/inicio`; `next` continua
            # tendo precedência total.
            destino = request.GET.get("next") or request.POST.get("next")
            if not destino or not destino.startswith("/"):
                destino = "/inicio"
            return redirect(destino)  # nunca HttpResponseClientRedirect — página inteira

        contexto["bloqueado"] = bool(getattr(request, "axes_locked_out", False))
        contexto["erro"] = (
            "Muitas tentativas. Aguarde alguns minutos e tente novamente."
            if contexto["bloqueado"]
            else "E-mail ou senha incorretos."
        )

    return TemplateResponse(
        request, "core/login.html", contexto, status=200
    )  # nunca 4xx puro


@require_POST
def logout_view(request):
    logout(request)
    return redirect("core:login")


@login_not_required
def csrf_failure_view(request, reason=""):
    """`CSRF_FAILURE_VIEW` (`config/settings/base.py`).

    Sem isto, um token velho (bfcache/"Voltar" depois de um login/logout
    que girou o token, ou uma aba de login esquecida aberta) cai na página
    crua "Verificação CSRF falhou" do Django, sem caminho de volta.
    `reason` só vai para o log — nunca é exposto ao usuário.

    No login, reapresenta `core/login.html` com token/cookie novos e uma
    mensagem de expiração. Em qualquer outra rota, a casca de erro do DS;
    para requisição htmx, `HX-Redirect` para a própria página — a recarga
    inteira é o caminho seguro.
    """
    logger_csrf.warning("Falha de CSRF em %s: %s", request.path, reason)

    if request.path == reverse("core:login"):
        get_token(request)
        contexto = {
            "erro": (
                "Sua página de login estava aberta há muito tempo e "
                "expirou. Confira os dados e tente novamente."
            ),
            "bloqueado": False,
            "usuario_digitado": request.POST.get("username", "").strip(),
        }
        resposta = TemplateResponse(request, "core/login.html", contexto, status=403)
        resposta["Cache-Control"] = "private, no-store"
        return resposta

    if getattr(request, "htmx", False):
        resposta = HttpResponse(status=403)
        resposta["HX-Redirect"] = request.headers.get("HX-Current-URL") or request.path
        return resposta

    return TemplateResponse(
        request,
        "core/erro.html",
        {
            "codigo": 403,
            "titulo": "Sessão expirada",
            "texto": (
                "Sua sessão expirou ou a página estava aberta há muito "
                "tempo. Recarregue a página e tente de novo."
            ),
        },
        status=403,
    )


def trocar_senha_view(request):
    """Página inteira (`core/trocar_senha.html`, `{{ form }}` via
    `DSGovFormRenderer`), nunca fragmento HTMX. Sem `@login_not_required`:
    `LoginRequiredMiddleware` já garante sessão válida, e é essa mesma
    sessão que `PasswordChangeForm` usa como referência da senha atual.
    """
    # Quando a troca é obrigatória, `TrocaSenhaObrigatoriaMiddleware`
    # devolve o usuário para cá; "Cancelar" só evita `url_cancelar` vazio.
    contexto = {"url_cancelar": reverse("core:inicio")}
    if request.method != "POST":
        contexto["form"] = PasswordChangeForm(request.user)
        return TemplateResponse(request, "core/trocar_senha.html", contexto)

    form = PasswordChangeForm(request.user, request.POST)
    if not form.is_valid():
        contexto["form"] = form
        return TemplateResponse(
            request,
            "core/trocar_senha.html",
            contexto,
            status=200,  # nunca 4xx puro — mesmo padrão de login_view
        )

    form.save()
    request.user.senha_temporaria = False
    request.user.save(update_fields=["senha_temporaria"])
    # form.save() muda o hash da sessão; sem isto a sessão corrente cai.
    update_session_auth_hash(request, form.user)
    return redirect("core:inicio")


def perfil_view(request):
    """Área do usuário (`core/perfil.html`): avatar-letra, e-mail,
    nome/sobrenome editáveis, atalho para `core:trocar_senha` e o botão
    Sair. Página inteira, POST-redirect-GET com `messages`.
    `LoginRequiredMiddleware` garante sessão; `request.user` é a instância
    editada.
    """
    contexto = {
        "url_cancelar": reverse("core:inicio"),
        "trilha": [("Meu perfil", None)],
    }
    if request.method != "POST":
        contexto["form"] = PerfilForm(instance=request.user)
        return TemplateResponse(request, "core/perfil.html", contexto)

    form = PerfilForm(request.POST, instance=request.user)
    if not form.is_valid():
        contexto["form"] = form
        return TemplateResponse(request, "core/perfil.html", contexto, status=200)

    form.save()
    messages.success(request, "Perfil atualizado.")
    return redirect("core:perfil")


@login_not_required
def erro_403(request, exception=None):
    """`core/erro.html` da skill, texto genérico, sem stacktrace nem
    detalhe interno."""
    return TemplateResponse(
        request,
        "core/erro.html",
        {
            "codigo": 403,
            "titulo": "Acesso negado",
            "texto": "Você não tem permissão para acessar esta página.",
        },
        status=403,
    )


@login_not_required
def erro_404(request, exception=None):
    return TemplateResponse(
        request,
        "core/erro.html",
        {
            "codigo": 404,
            "titulo": "Página não encontrada",
            "texto": "O endereço digitado não existe ou foi movido.",
        },
        status=404,
    )


@login_not_required
def erro_500(request):
    return TemplateResponse(
        request,
        "core/erro.html",
        {
            "codigo": 500,
            "titulo": "Erro interno",
            "texto": "Ocorreu um erro inesperado. Tente novamente em instantes.",
        },
        status=500,
    )


def inicio(request):
    """`core:inicio` — a entrada única do sistema: dashboard com
    exatamente 4 KPIs, 2 gráficos e uma tabela de pendências.
    `apps.pca.kpis.calcular_blocos_kpi` é a fonte única dos 4 KPIs — nunca
    uma fórmula concorrente. `apps.pca.graficos_pca` é a ponte de
    agregação/gráfico, reaproveitada identicamente por
    `apps.pca.views.analise_view` — os números do dashboard e de Análises
    nunca divergem para o mesmo filtro.

    Sem `@login_not_required`: mesmo padrão de leitura das demais views,
    protegido só pelo `LoginRequiredMiddleware` global.
    """
    # Imports locais (apps.pca) — mesmo padrão de `core/menu.py::itens()`:
    # evita dependência circular de import em nível de módulo entre `core`
    # e `apps.pca` na ordem de carregamento dos apps Django.
    from apps.pca import graficos_pca
    from apps.pca.filtros import filtros_ativos, querystring_filtros, queryset_filtrado
    from apps.pca.kpis import calcular_blocos_kpi
    from apps.pca.models import Estado, Situacao

    get = request.GET
    qs = queryset_filtrado(request)
    exercicio = filtros_ativos(get)["exercicio"]

    bloco_a, bloco_b, _gauge_nao_usado = calcular_blocos_kpi(
        qs, get, dias_proximo_vencimento=settings.PCA_DIAS_PROXIMOS_VENCIMENTO
    )

    url_tabela = reverse("pca:tabela")

    def url_kpi(href):
        return f"{url_tabela}?{href}" if href else url_tabela

    ativos = bloco_a["ativos"]
    total = bloco_a["total"]
    cancelados = bloco_a["cancelados"]
    concluido = bloco_b["concluido"]
    em_tramitacao = bloco_b["em_tramitacao"]
    no_prazo = bloco_b["no_prazo"]
    atrasados = bloco_b["atrasados"]
    sobrestados = bloco_b["sobrestados"]

    # Exatamente 4 KPIs, nesta ordem; os demais números de
    # `calcular_blocos_kpi` ficam disponíveis em Análises.
    kpis = [
        {
            "rotulo": "Ativos",
            "valor": numero(ativos["contagem"]),
            "apoio": (
                f"de {numero(total['contagem'])} previstos · "
                f"{numero(cancelados['contagem'])} cancelados"
            ),
            "icone": "fas fa-folder-open",
            "url": url_kpi(ativos["href"]),
        },
        {
            "rotulo": "Concluídos",
            "valor": numero(concluido["contagem"]),
            # Os 3 números vêm do mesmo universo NC|RN
            # (bloco_b["concluido"]["meta_pca"/"concluido_meta_pca"/
            # "percentual_meta_pca"]).
            "apoio": (
                f"Da meta: {numero(concluido['concluido_meta_pca'])} de "
                f"{numero(concluido['meta_pca'])} concluídos — "
                f"{percentual(concluido['percentual_meta_pca'])}"
            ),
            "icone": "fas fa-check-circle",
            "url": url_kpi(concluido["href"]),
        },
        {
            "rotulo": "Em tramitação",
            "valor": numero(em_tramitacao["contagem"]),
            "apoio": f"{numero(no_prazo['contagem'])} no prazo",
            "icone": "fas fa-clock",
            "url": url_kpi(em_tramitacao["href"]),
        },
        {
            "rotulo": "Atrasados",
            "valor": numero(atrasados["contagem"]),
            "apoio": f"{numero(sobrestados['contagem'])} sobrestados",
            "icone": "fas fa-exclamation-triangle",
            "url": url_kpi(atrasados["href"]),
        },
    ]

    # Início executivo enxuto: exatamente 2 gráficos (rosca de situação
    # só-ativos + barras financeiras previsto×contratado), nenhum gráfico
    # mensal. "Processos por unidade" e "Previsto × Entregue por mês" já
    # têm equivalente em Análises (`pca:analise`).
    status_distribuicao = graficos_pca.calcular_status_distribuicao(qs, get)
    # Mesmo `qs` (sem filtro extra) usado pelos totais financeiros de
    # Análises (`analise_view::soma_filtrada`/`soma_contratada`).
    totais_financeiros = graficos_pca.calcular_totais_financeiros(qs)
    graficos_ctx = [
        {
            "id": "grafico-situacao",
            "titulo": "Processos por situação",
            "opcoes": graficos_pca.opcoes_situacao_ativos(status_distribuicao),
            "resumo": graficos_pca.resumo_situacao_ativos(status_distribuicao),
            "tabela": graficos_pca.tabela_situacao_ativos(status_distribuicao),
        },
        {
            "id": "grafico-financeiro",
            "titulo": "Valor previsto x valor contratado",
            "opcoes": graficos_pca.opcoes_totais_financeiros(totais_financeiros),
            "resumo": graficos_pca.resumo_totais_financeiros(totais_financeiros),
            "tabela": graficos_pca.tabela_totais_financeiros(totais_financeiros),
            "subtitulo": (
                f"{numero(totais_financeiros['sem_contratado'])} processo(s) sem "
                "valor contratado preenchido"
                if totais_financeiros["sem_contratado"]
                else None
            ),
        },
    ]

    # Pendências (até 10 linhas): "Ver todos" leva à mesma tabela filtrada
    # que a lista representa (atrasados ou, no fallback, sobrestados).
    titulo_pendencias, processos_pendencias = graficos_pca.calcular_pendencias(qs)
    if titulo_pendencias == "Processos atrasados":
        href_pendencias = querystring_filtros(
            get, estado=[Estado.ATIVO.value], situacao=[Situacao.ATRASADO.value]
        )
    else:
        href_pendencias = querystring_filtros(
            get, estado=[Estado.ATIVO.value], sobrestado="1"
        )
    pendencias = {
        "titulo": titulo_pendencias,
        "url": url_kpi(href_pendencias),
        "colunas": graficos_pca.colunas_pendencias(),
        "objetos": processos_pendencias,
    }

    contexto = {
        "trilha": [("Início", None)],
        "subtitulo": f"PCA {exercicio.ano}" if exercicio else None,
        "exercicio": exercicio,
        "kpis": kpis,
        "graficos": graficos_ctx,
        "pendencias": pendencias,
    }
    resposta = TemplateResponse(request, "core/inicio.html", contexto)
    # Nunca cacheável na borda; o filtro é por sessão autenticada, não pública.
    resposta["Cache-Control"] = "private, no-store"
    return resposta


@login_not_required
def manifest_view(request):
    """`manifest.json` servido por view, não arquivo estático puro.

    Em produção o `CompressedManifestStaticFilesStorage` do WhiteNoise
    hasheia o nome de cada ícone; um `.json` estático com um caminho
    literal 404aria depois do `collectstatic`. Resolvendo via `static()`
    aqui, o manifest sempre aponta para o nome real do arquivo.
    """
    dados = {
        # Sem ano, de propósito: o manifest fica em cache no dispositivo
        # depois da instalação, e um ano fixo sobreviveria à virada de
        # exercício, mentindo sobre o que o app é.
        "name": "PCA — Plano de Contratações Anual",
        "short_name": "PCA",
        # O PWA abre em `/inicio`; `scope` continua "/" — cobre o app
        # inteiro, só a tela inicial pós-instalação muda.
        "start_url": "/inicio",
        "scope": "/",
        "display": "standalone",
        # Hex literal inevitável — chave de manifest PWA exige valor
        # literal, sem equivalente var(). background_color casa com
        # --cor-page (#f8f8f8) para o splash não divergir do fundo real da
        # aplicação; theme_color é o azul do govbr-ds.
        "background_color": "#f8f8f8",
        "theme_color": "#1351b4",
        "icons": [
            {
                "src": static("img/icon-192.png"),
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any",
            },
            {
                "src": static("img/icon-512.png"),
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any",
            },
            {
                "src": static("img/icon-512-maskable.png"),
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "maskable",
            },
        ],
    }
    return JsonResponse(dados, content_type="application/manifest+json")


# Precache do `install` do service worker: a lista fixa de CSS/JS de
# `base.html` (fontes primeiro, senão os `@font-face` de `fontes.css`
# apontariam para um recurso ainda não cacheado) + as fontes woff2 do
# Rawline/Raleway. `echarts.min.js`/`echarts-dsgov.js` ficam fora do
# precache: só carregam nas páginas com gráfico e cacheiam em runtime na
# primeira visita.
_PRECACHE_ESTATICOS = tuple(
    static(caminho)
    for caminho in (
        "dsgov/css/fontes.css",
        "dsgov/vendor/govbr-ds/core.min.css",
        "dsgov/vendor/fontawesome/css/all.min.css",
        "dsgov/css/dsgov.css",
        "dsgov/vendor/govbr-ds/core.min.js",
        "dsgov/vendor/htmx/htmx.min.js",
        "dsgov/js/dsgov.js",
        "dsgov/vendor/fonts/rawline/rawline-100.woff2",
        "dsgov/vendor/fonts/rawline/rawline-100i.woff2",
        "dsgov/vendor/fonts/rawline/rawline-200.woff2",
        "dsgov/vendor/fonts/rawline/rawline-200i.woff2",
        "dsgov/vendor/fonts/rawline/rawline-300.woff2",
        "dsgov/vendor/fonts/rawline/rawline-300i.woff2",
        "dsgov/vendor/fonts/rawline/rawline-400.woff2",
        "dsgov/vendor/fonts/rawline/rawline-400i.woff2",
        "dsgov/vendor/fonts/rawline/rawline-500.woff2",
        "dsgov/vendor/fonts/rawline/rawline-500i.woff2",
        "dsgov/vendor/fonts/rawline/rawline-600.woff2",
        "dsgov/vendor/fonts/rawline/rawline-600i.woff2",
        "dsgov/vendor/fonts/rawline/rawline-700.woff2",
        "dsgov/vendor/fonts/rawline/rawline-700i.woff2",
        "dsgov/vendor/fonts/rawline/rawline-800.woff2",
        "dsgov/vendor/fonts/rawline/rawline-800i.woff2",
        "dsgov/vendor/fonts/rawline/rawline-900.woff2",
        "dsgov/vendor/fonts/rawline/rawline-900i.woff2",
        "dsgov/vendor/fonts/raleway/raleway-latin.woff2",
        "dsgov/vendor/fonts/raleway/raleway-latin-ext.woff2",
        "dsgov/vendor/fonts/raleway/raleway-latin-italic.woff2",
        "dsgov/vendor/fonts/raleway/raleway-latin-ext-italic.woff2",
    )
)


@login_not_required
def service_worker_view(request):
    """`sw.js` hand-rolled, sem Workbox — só cacheia `/static/`.

    Servido por rota de raiz (nunca `/static/sw.js`) com
    `Service-Worker-Allowed: /` explícito. Precache da página offline no
    `install` e fallback de navegação. HTML, fragmentos HTMX e JSON nunca
    são interceptados — só GET de mesma origem sob `/static/`.
    """
    offline_url = static("offline.html")
    texto = (
        "// CACHE_NAME versionado manualmente — faça bump do sufixo sempre\n"
        "// que o conjunto de estáticos cacheados mudar de formato.\n"
        "// O cache guarda a lista fixa de CSS/JS de base.html, as fontes\n"
        "// woff2 (Rawline/Raleway) e a página offline; o fetch handler\n"
        "// cacheia o restante de /static/* em runtime.\n"
        'const CACHE_NAME = "pca-static-v44";\n'
        f'const OFFLINE_URL = "{offline_url}";\n'
        f'const PRECACHE = {json.dumps(list(_PRECACHE_ESTATICOS) + [offline_url])};\n'
        "\n"
        'self.addEventListener("install", (event) => {\n'
        "  self.skipWaiting();\n"
        "  event.waitUntil(\n"
        "    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE))\n"
        "  );\n"
        "});\n"
        "\n"
        'self.addEventListener("fetch", (event) => {\n'
        "  const url = new URL(event.request.url);\n"
        "\n"
        "  // Navegação (troca de página): sempre tenta a rede primeiro; só\n"
        "  // cai para a página offline quando a rede falha de fato — nunca\n"
        "  // serve HTML cacheado.\n"
        '  if (event.request.mode === "navigate") {\n'
        "    event.respondWith(\n"
        "      fetch(event.request).catch(() => caches.match(OFFLINE_URL))\n"
        "    );\n"
        "    return;\n"
        "  }\n"
        "\n"
        "  // 1) só GET, 2) só mesma origem, 3) SÓ /static/. Todo o resto\n"
        "  // passa direto (sem respondWith nenhum) — HTML/HTMX/JSON nunca\n"
        "  // entram no Cache Storage.\n"
        '  if (event.request.method !== "GET") return;\n'
        "  if (url.origin !== location.origin) return;\n"
        '  if (!url.pathname.startsWith("/static/")) return;\n'
        "  event.respondWith(\n"
        "    caches.match(event.request).then((r) => r || fetch(event.request).then((resp) => {\n"
        '      if (resp.ok && resp.type === "basic") {\n'
        "        const c = resp.clone();\n"
        "        caches.open(CACHE_NAME).then((k) => k.put(event.request, c));\n"
        "      }\n"
        "      return resp;\n"
        "    }))\n"
        "  );\n"
        "});\n"
        "\n"
        'self.addEventListener("activate", (event) => event.waitUntil(\n'
        "  caches.keys().then((ks) => Promise.all(\n"
        "    ks.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))\n"
        "  )).then(() => self.clients.claim())\n"
        "));\n"
    )
    resposta = HttpResponse(texto, content_type="application/javascript")
    resposta["Service-Worker-Allowed"] = "/"
    return resposta


def sobre_view(request):
    """`core:sobre` — texto institucional sobre o sistema. View trivial,
    sem ação — só leitura."""
    return render(
        request,
        "core/sobre.html",
        {"trilha": [("Sobre o sistema", None)]},
    )
