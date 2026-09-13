import logging

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_not_required
from django.db import connection
from django.http import HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

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
            destino = request.GET.get("next") or request.POST.get("next") or "/"
            return redirect(destino if destino.startswith("/") else "/")
        contexto["bloqueado"] = bool(getattr(request, "axes_locked_out", False))
        contexto["erro"] = (
            "Muitas tentativas. Aguarde alguns minutos e tente novamente."
            if contexto["bloqueado"]
            else "Usuário ou senha inválidos."
        )
    return render(request, "core/login.html", contexto, status=200)


@require_POST
def logout_view(request):
    logout(request)
    return redirect("core:login")


@login_not_required
def csrf_failure_view(request, reason=""):
    """`CSRF_FAILURE_VIEW` — token velho (bfcache/"Voltar" após
    rotate_token() no login/logout, ou aba de login esquecida aberta) nunca
    cai na página crua "Verificação CSRF falhou" do Django. `reason` só vai
    para o log (django.security.csrf, WARNING) — nunca ao usuário."""
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
        resposta = render(request, "core/login.html", contexto, status=403)
        resposta["Cache-Control"] = "private, no-store"
        return resposta

    if getattr(request, "htmx", False):
        resposta = HttpResponse(status=403)
        resposta["HX-Redirect"] = request.headers.get("HX-Current-URL") or request.path
        return resposta

    return render(
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


def resposta_bloqueio(request, credentials, *args, **kwargs):
    """django-axes chama isto quando o usuário+IP está bloqueado. Reaproveita a tela de login."""
    return render(
        request,
        "core/login.html",
        {"erro": "Muitas tentativas. Aguarde alguns minutos e tente novamente.", "bloqueado": True,
         "usuario_digitado": credentials.get("username", "")},
        status=200,
    )


def inicio(request):
    """Dashboard inicial. A skill dsgov gera o esqueleto; o projeto preenche KPIs e gráficos aqui."""
    contexto = {
        "trilha": [("Início", None)],
        "kpis": [],       # ver core/templates/dsgov/_kpi_card.html
        "graficos": [],   # [{"id", "titulo", "subtitulo", "opcoes", "resumo"}]
        "pendencias": None,
    }
    return render(request, "core/inicio.html", contexto)


@login_not_required
def erro_403(request, exception=None):
    return render(request, "core/erro.html", {"codigo": 403, "titulo": "Acesso negado",
                  "texto": "Você não tem permissão para acessar esta página."}, status=403)


@login_not_required
def erro_404(request, exception=None):
    return render(request, "core/erro.html", {"codigo": 404, "titulo": "Página não encontrada",
                  "texto": "O endereço digitado não existe ou foi movido."}, status=404)


@login_not_required
def erro_500(request):
    return render(request, "core/erro.html", {"codigo": 500, "titulo": "Erro interno",
                  "texto": "Ocorreu um erro inesperado. Tente novamente em instantes."}, status=500)
