import json
import logging
from datetime import datetime, timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_not_required, permission_required
from django.contrib.auth.forms import PasswordChangeForm
from django.db import connection
from django.http import HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect, render
from django.template.response import TemplateResponse
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone
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
    """Fase 26 — página inteira na casca do padrão DSGov
    dsgov (`core/login.html`, `body.dsgov-login`), nunca mais fragmento
    HTMX: o form do padrão DSGov é um POST tradicional, sem `hx-post`.

    Nunca usa `except PermissionDenied` em torno de `authenticate()`: o
    dispatcher de nível superior do Django (`django.contrib.auth.authenticate`)
    captura o `PermissionDenied` que o `AxesBackend` levanta internamente e
    NUNCA o repassa para quem chamou — ele só devolve `None` (comportamento
    documentado tanto em `django/contrib/auth/__init__.py` quanto no próprio
    comentário de `axes/backends.py`; verificado nesta revisão do plano). A
    forma correta e suportada de distinguir "bloqueado pelo axes" de
    "credenciais erradas comuns" é o atributo `request.axes_locked_out`, que
    o `AxesBackend` seta no request antes de levantar (e que sobrevive à
    captura silenciosa do dispatcher).

    O campo do POST chama-se `username` (estrutura do padrão DSGov) — só
    o RÓTULO exibido em `core/login.html` virou "E-mail institucional"; o
    valor continua sendo o e-mail do usuário (`USERNAME_FIELD`).
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
            # mudou o destino sem `next` para
            # `/inicio`; Fase 26 unifica em `core:inicio`. `next`
            # explícito continua tendo precedência total.
            #
            # QA de segurança 30/09/2026 (achado M1): `destino.startswith("/")`
            # aceitava `//evil.example/x`/`///evil.example` — URLs relativas
            # ao protocolo que o navegador resolve para fora do site.
            # `url_has_allowed_host_and_scheme` (mesmo padrão de
            # `aparencia_view`, neste arquivo) recusa esses casos; o fallback
            # para `/inicio` continua valendo quando `destino` é vazio ou
            # reprovado pela checagem.
            from django.utils.http import url_has_allowed_host_and_scheme

            destino = request.GET.get("next") or request.POST.get("next")
            if not destino or not url_has_allowed_host_and_scheme(
                destino,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ):
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
    )  # nunca 4xx puro (Pitfall 1)


@require_POST
def logout_view(request):
    logout(request)
    return redirect("core:login")


@login_not_required
def csrf_failure_view(request, reason=""):
    """`CSRF_FAILURE_VIEW` (`config/settings/base.py`).

    Sem isto, um token velho (bfcache/"Voltar" depois de um login/logout que
    girou o token via `rotate_token()`, ou uma aba de login esquecida aberta
    por horas) cai na página crua "Verificação CSRF falhou" do Django, sem
    caminho de volta. `reason` só vai para o log (`django.security.csrf`,
    WARNING) — nunca é exposto ao usuário, e nada do corpo da requisição
    (senha) é logado.

    No login, reapresenta `core/login.html` com token/cookie novos
    (`get_token()` antes do render) e uma mensagem de expiração — o form
    preserva `usuario_digitado` e o `?next=` da URL (o template já lê
    `request.GET.next` direto, sem precisar de contexto extra). Em
    qualquer outra rota, a casca de erro do DS (`core/erro.html`); para
    requisição htmx, `HX-Redirect` para a própria página — `dsgov.js` só
    trata 403 com `HX-Login`, então a recarga inteira é o caminho seguro
    (nunca um swap parcial de um form de login dentro de um fragmento).
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
    """Fase 26 — página inteira (`core/trocar_senha.html`,
    `col-md-8`, `{{ form }}` via `DSGovFormRenderer`, `dsgov/_acoes_formulario.html`),
    nunca mais fragmento HTMX. Sem `@login_not_required`: `LoginRequiredMiddleware`
    já garante sessão válida, e é essa mesma sessão que `PasswordChangeForm`
    usa como referência da senha atual.
    """
    # `url_cancelar` (dsgov/_acoes_formulario.html) aponta para `core:inicio`:
    # quando a troca é obrigatória (`senha_temporaria=True`), o próprio
    # `TrocaSenhaObrigatoriaMiddleware` devolve o usuário para cá — "Cancelar"
    # nunca é uma saída real dessa condição, só evita um `url_cancelar` vazio;
    # "Sair" (abaixo, no template) é a saída de fato.
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
            status=200,  # nunca 4xx puro — mesmo padrão de login_view (Pitfall 1)
        )

    form.save()
    request.user.senha_temporaria = False
    request.user.save(update_fields=["senha_temporaria"])
    # Obrigatório: form.save() muda o hash da sessão e derrubaria a sessão
    # corrente sem isto.
    update_session_auth_hash(request, form.user)
    return redirect("core:inicio")


@require_POST
def aparencia_view(request):
    """Grava a aparência escolhida no painel "Personalizar aparência" (casca Tabler). Chamada em segundo
    plano a cada troca (a tela já mudou no navegador); só aceita os valores das listas do modelo."""
    from core.models import PreferenciaAparencia

    valores = PreferenciaAparencia.validar(request.POST)
    if not valores:
        return JsonResponse({"erro": "nenhum valor válido"}, status=400)
    pref, _ = PreferenciaAparencia.objects.get_or_create(usuario=request.user)
    for chave, valor in valores.items():
        setattr(pref, chave, valor)
    pref.save()
    if request.headers.get("Accept", "").startswith("application/json"):
        return JsonResponse(PreferenciaAparencia.valores_de(request.user))
    # Envio sem JS ("Salvar"): volta para a página de onde veio, se for deste site.
    from django.utils.http import url_has_allowed_host_and_scheme

    destino = request.META.get("HTTP_REFERER") or reverse("core:inicio")
    if not url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        destino = reverse("core:inicio")
    return redirect(destino)


@require_POST
def larguras_view(request):
    """Grava a largura de uma coluna ajustada numa tabela da casca Tabler. Chamada em
    segundo plano pelo pca-tabler.js ao soltar a alça; corpo JSON {"tabela", "coluna", "largura"} —
    `largura` null restaura a coluna, `coluna` null restaura a tabela inteira."""
    from core.models import PreferenciaLarguras

    try:
        dados = json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"erro": "JSON inválido"}, status=400)
    if not isinstance(dados, dict):
        return JsonResponse({"erro": "JSON inválido"}, status=400)
    tabela, coluna, largura = dados.get("tabela"), dados.get("coluna"), dados.get("largura")
    if not isinstance(tabela, str) or (coluna is not None and not isinstance(coluna, str)):
        return JsonResponse({"erro": "tabela/coluna inválidas"}, status=400)
    if not PreferenciaLarguras.gravar(request.user, tabela, coluna, largura):
        return JsonResponse({"erro": "valor recusado"}, status=400)
    return JsonResponse({"ok": True})


@require_POST
def token_gerar_view(request):
    """Fase 42 — gera (e revoga o anterior) o token pessoal de API do
    usuário logado; o valor em claro vai SÓ para a sessão (`request.session`),
    nunca para o banco — `perfil_view` o exibe UMA única vez no próximo GET e
    o remove da sessão (`pop`) assim que monta o contexto."""
    from core.models import TokenApi

    _, valor_em_claro = TokenApi.gerar(request.user)
    request.session["token_api_gerado"] = valor_em_claro
    messages.success(request, "Token de API gerado. Copie-o agora — ele não será mostrado de novo.")
    return redirect("core:perfil")


@require_POST
def token_revogar_view(request):
    """Fase 42 — revoga o token ATIVO do usuário logado, se houver."""
    from core.models import TokenApi

    atualizados = TokenApi.objects.filter(
        usuario=request.user, revogado_em__isnull=True
    ).update(revogado_em=timezone.now())
    if atualizados:
        messages.success(request, "Token de API revogado.")
    else:
        messages.info(request, "Nenhum token de API ativo para revogar.")
    return redirect("core:perfil")


def perfil_view(request):
    """Área do usuário (`core/perfil.html`): avatar-letra,
    e-mail, nome/sobrenome editáveis, atalho para `core:trocar_senha` e o
    botão Sair (POST em `core:logout`). Página inteira, POST-redirect-GET com
    `messages`, mesmo padrão de `trocar_senha_view`. `LoginRequiredMiddleware`
    garante sessão; o próprio `request.user` é a instância editada.

    Fase 42 — contexto ganha `token_ativo` (o `TokenApi` ativo do
    usuário, ou `None`) e `token_gerado` (o valor em claro poppado da
    sessão por `token_gerar_view` — sobrevive só este UM GET).
    """
    from core.models import TokenApi

    contexto = {
        "url_cancelar": reverse("core:inicio"),
        "trilha": [("Meu perfil", None)],
        "token_ativo": TokenApi.objects.filter(
            usuario=request.user, revogado_em__isnull=True
        ).first(),
        "token_gerado": request.session.pop("token_api_gerado", None),
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
    """Fase 26 — `core/erro.html` do padrão DSGov,
    texto genérico, sem stacktrace nem detalhe interno."""
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


def _dias_uteis_desde(data):
    """Dias úteis decorridos entre `data` (aware) e agora — spec §3.6 do
    robô SEI (Fase 32): o card "Sincronização com o SEI" entra em
    alerta com mais de 3 dias úteis sem execução. Loop simples somando 1
    dia por vez e pulando sábado/domingo, sem dependência nova;
    a diferença é sempre limitada pela idade real do sistema, nunca corre
    risco de laço longo.
    """
    fim = timezone.localtime().date()
    cursor = timezone.localtime(data).date()
    dias_uteis = 0
    while cursor < fim:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            dias_uteis += 1
    return dias_uteis


def _montar_sei_card(request) -> dict | None:
    """Monta o contexto do card "Sincronização com o SEI" do Início (spec §3.6) — SÓ para `pca.editar_pca`/superusuário, `None` para os
    demais (`{% if sei_card %}` no template cobre a ausência).

    Ganha um 4º estado, `em_execucao`, lido do lock
    `em_execucao` via `sei_execucoes.ler_progresso()` — só entra nesse
    ramo quando o lock já tem a chave `total` (ao menos uma linha de
    progresso emitida); sem isso (lock ausente, obsoleto, ou formato
    antigo sem `total` — ex. lock do `sei_atender` para um único pedido)
    cai no código de sempre, derivado de `sei_execucoes.ultima()`."""
    from apps.pca.sei import execucoes as sei_execucoes

    if not request.user.has_perm("pca.editar_pca"):
        return None

    progresso = sei_execucoes.ler_progresso()
    if progresso is not None and "total" in progresso:
        iniciado_em = datetime.fromisoformat(progresso["iniciado_em"])
        total = progresso["total"]
        sei_card = {
            "estado": "em_execucao",
            "carimbo": progresso["carimbo"],
            "iniciado_em": iniciado_em,
            "item": progresso["item"],
            "k": progresso["k"],
            "total": total,
            "coletados": progresso["coletados"],
            "pulados": progresso["pulados"],
            "erros": progresso["erros"],
            "ultima_linha": progresso["ultima_linha"],
            "percentual": round(progresso["k"] / total * 100) if total else 0,
            "decorrido_min": max(
                0,
                int(
                    (timezone.localtime() - timezone.localtime(iniciado_em)).total_seconds()
                    // 60
                ),
            ),
        }
    else:
        ultima_execucao = sei_execucoes.ultima()
        if ultima_execucao is None:
            sei_card = {"estado": "nunca_executado"}
        else:
            try:
                terminado_em = datetime.fromisoformat(ultima_execucao["terminado_em"])
            except (TypeError, ValueError):
                # Data corrompida/futura no JSON de execução: cai
                # no fallback seguro em vez de quebrar o Início inteiro.
                sei_card = {"estado": "nunca_executado"}
            else:
                dias_uteis = _dias_uteis_desde(terminado_em)
                alerta = ultima_execucao["status"] == "erro" or dias_uteis > 3
                sei_card = {
                    "estado": "alerta" if alerta else "ok",
                    "terminado_em": terminado_em,
                    "status": ultima_execucao["status"],
                    "mensagem": ultima_execucao.get("mensagem"),
                    "totais": ultima_execucao["totais"],
                }

    # "Último pedido pelo Admin"/"Pedidos atendidos hoje"
    # aparecem em qualquer estado (inclusive em_execucao/nunca_executado).
    ultimo_pedido = sei_execucoes.ultimo_pedido_atendido()
    sei_card["ultimo_pedido"] = ultimo_pedido
    sei_card["pedidos_atendidos_hoje"] = (
        ultimo_pedido["atendidos_hoje"] if ultimo_pedido else 0
    )

    # Itens "Sem processo SEI" (nenhum nº SEI) do exercício em
    # foco: a sincronização nunca os toca (não há de onde tirar informação);
    # o link abre a tabela já filtrada.
    from apps.pca.filtros import filtros_ativos
    from apps.pca.models import Estado, Processo

    exercicio = filtros_ativos(request.GET)["exercicio"]
    if exercicio is not None:
        sei_card["sem_processo_sei"] = {
            "total": Processo.objects.filter(
                exercicio=exercicio, estado=Estado.ATIVO, numeros_sei__isnull=True
            ).count(),
            "url": reverse("pca:tabela") + "?" + urlencode(
                {"exercicio": exercicio.ano, "estado": Estado.ATIVO.value, "sem_processo_sei": "1"}
            ),
        }
    return sei_card


@permission_required("pca.editar_pca", raise_exception=True)
def sei_card_view(request):
    """`core:sei_card` — fragmento HTMX do card "Sincronização com o SEI":
`hx-get`/`hx-trigger="every 15s"` só durante uma
    varredura em andamento (`inicio.html`, wrapper `#sei-card`). Sem
    `@login_not_required` — protegido pelo `LoginRequiredMiddleware` global
    (anônimo é redirecionado ao login antes de chegar aqui); leitor sem
    `pca.editar_pca` recebe 403 (`raise_exception=True`)."""
    return render(request, "core/_sei_card.html", {"sei_card": _montar_sei_card(request)})


def inicio(request):
    """`core:inicio` — a nova entrada única do sistema.

    Fase 26 (..17) — o CORPO desta função funde o que
    antes eram duas telas separadas (`pca:cards_inicio`/`pca:dashboard`,
    Fase 25) num único dashboard real, dentro do orçamento
    fixo de `references/telas/dashboard.md`: exatamente 4 KPIs, 4
    gráficos (rosca/barras/colunas/linha) e uma tabela de pendências.
    `apps.pca.kpis.calcular_blocos_kpi` (intocado, hash idêntico) segue
    sendo a fonte única dos 4 KPIs — nunca uma fórmula concorrente.
`apps.pca.graficos_pca` é a ponte de agregação/gráfico,
reaproveitada IDENTICAMENTE por `apps.pca.views.
    analise_view` — os números do dashboard e de Análises nunca
    divergem para o mesmo filtro (Pitfall 16).

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

    # → (Início no padrão do PNCP) →
    # (pedido da diretora, 15/10/2026): 7 KPIs, nesta ordem — Previstos =
    # Cancelados + Ativos; Ativos = Concluídos + Em tramitação + No prazo +
    # Atrasados. Os demais números de `calcular_blocos_kpi` continuam em
    # Análises. `tom` = faixa de cor no topo do cartão, a mesma cor
    # da fatia na rosca (Previstos/Ativos não têm fatia: azul de destaque).
    # `grupo` monta a grade nas duas cascas: uma linha de 7 na tela larga e,
    # abaixo disso, o universo (total + universo) em cima e a situação dos
    # ativos embaixo.
    kpis = [
        {
            "rotulo": "Previstos",
            "valor": numero(total["contagem"]),
            "apoio": f"itens no PCA {exercicio.ano}" if exercicio else "itens no PCA",
            "icone": "fas fa-clipboard-list",
            "url": url_kpi(total["href"]),
            "tom": "destaque",
            "grupo": "total",
        },
        {
            "rotulo": "Cancelados",
            "valor": numero(cancelados["contagem"]),
            "apoio": f"{percentual(cancelados['percentual'])} dos previstos",
            "icone": "fas fa-ban",
            "url": url_kpi(cancelados["href"]),
            "tom": "neutro",
            "grupo": "universo",
        },
        {
            "rotulo": "Ativos",
            "valor": numero(ativos["contagem"]),
            "apoio": f"{percentual(ativos['percentual'])} dos previstos",
            "icone": "fas fa-folder-open",
            "url": url_kpi(ativos["href"]),
            "tom": "destaque",
            "grupo": "universo",
        },
        {
            "rotulo": "Concluídos",
            "valor": numero(concluido["contagem"]),
            # Os 3 números do MESMO universo NC|RN
            # (`bloco_b["concluido"]["meta_pca"/"concluido_meta_pca"/
            # "percentual_meta_pca"]`): corrige a mistura
            # anterior de contagem-com-vigentes/percentual-sem-vigentes.
            "apoio": (
                f"Da meta: {numero(concluido['concluido_meta_pca'])} de "
                f"{numero(concluido['meta_pca'])} concluídos — "
                f"{percentual(concluido['percentual_meta_pca'])}"
            ),
            "icone": "fas fa-check-circle",
            "url": url_kpi(concluido["href"]),
            "tom": "sucesso",
            "grupo": "situacao",
        },
        {
            "rotulo": "Em tramitação",
            "valor": numero(em_tramitacao["contagem"]),
            "apoio": "entregues à Gelic, em andamento",
            "icone": "fas fa-clock",
            "url": url_kpi(em_tramitacao["href"]),
            "tom": "info",
            "grupo": "situacao",
        },
        {
            "rotulo": "No prazo",
            "valor": numero(no_prazo["contagem"]),
            "apoio": "dentro do prazo de entrega à Gelic",
            "icone": "fas fa-calendar-check",
            "url": url_kpi(no_prazo["href"]),
            "tom": "alerta",
            "grupo": "situacao",
        },
        {
            "rotulo": "Atrasados",
            "valor": numero(atrasados["contagem"]),
            "apoio": f"{numero(sobrestados['contagem'])} sobrestados",
            "icone": "fas fa-exclamation-triangle",
            "url": url_kpi(atrasados["href"]),
            "tom": "erro",
            "grupo": "situacao",
        },
    ]

    # (revisão) — Início executivo enxuto:
    # EXATAMENTE 2 gráficos (rosca de situação + barras financeiras
    # previsto×contratado), nenhum gráfico mensal. a rosca
    # volta a ter os cancelados, com o total de previstos no centro — o mesmo
    # recorte dos 7 KPIs. "Processos
    # por unidade" e "Previsto × Entregue por mês" já têm equivalente em
    # Análises (`pca:analise`); "Situação por mês previsto" perde o único
    # consumidor aqui — `calcular_situacao_por_mes`/`opcoes_situacao_por_
    # mes`/`tabela_situacao_por_mes`/`resumo_situacao_por_mes` NÃO foram
    # removidas (fora de escopo confirmar se há uso futuro; candidatas a
    # limpeza numa quick futura, ver SUMMARY do plano).
    status_distribuicao = graficos_pca.calcular_status_distribuicao(qs, get)
    # MESMO `qs` (sem filtro extra) usado pelos totais
    # financeiros de Análises (`analise_view::soma_filtrada`/
    # `soma_contratada`, `Sum` simples, inclui cancelados).
    totais_financeiros = graficos_pca.calcular_totais_financeiros(qs)
    graficos_ctx = [
        {
            "id": "grafico-situacao",
            "titulo": "Processos por situação",
            "opcoes": graficos_pca.opcoes_situacao(status_distribuicao, legenda_total="previstos"),
            "resumo": graficos_pca.resumo_situacao_previstos(status_distribuicao),
            "tabela": graficos_pca.tabela_situacao_previstos(status_distribuicao),
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

    # Pendências (até 10 linhas), "Ver todos" para a MESMA tabela
    # filtrada que a lista representa (atrasados ou, no fallback,
    # sobrestados — nunca a tabela sem recorte).
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

    # (Fase 32, spec §3.6) — card "Sincronização com o SEI", visível
    # SÓ para quem tem `pca.editar_pca` (equipe do PCA) e superusuários
    # (decisão do usuário, 18/09/2026): leitores não veem o card nem
    # qualquer alteração no Início. `_montar_sei_card` devolve `None` para
    # eles, e `{% if sei_card %}` no template cobre a ausência. Quick
    # Mesma função também serve `core:sei_card_view`.
    sei_card = _montar_sei_card(request)

    # 29/09/2026 — itens com situação manual em que as regras automáticas aplicariam outra (a trava só
    # se desmarca no Admin); só para quem edita o PCA. Uma consulta.
    manuais_divergentes = []
    if exercicio and request.user.has_perm("pca.editar_pca"):
        from apps.pca.models import Processo as _Processo

        manuais_divergentes = list(
            _Processo.objects.filter(exercicio=exercicio, situacao_manual=True)
            .exclude(situacao_regra="")
            .select_related("exercicio")
            .order_by("item_pca")
        )

    # Fase 43 — contador de partes de solicitações aguardando decisão, só para quem decide
    # em alguma alçada (equipe do PCA, diretoria, superusuário); `None` para os demais.
    from apps.solicitacoes import services as servicos_solicitacoes

    solicitacoes_a_avaliar = None
    if servicos_solicitacoes.alcadas_do_usuario(request.user):
        solicitacoes_a_avaliar = {
            "total": servicos_solicitacoes.contar_pendentes(request.user),
            "url": reverse("solicitacoes:avaliar"),
        }

    contexto = {
        # QA 30/09/2026, navegador B5 — `tabler/templates/base.html` já
        # renderiza um link fixo "Início" ANTES de iterar `trilha`;
        # `[("Início", None)]` sempre ativava o bloco e duplicava o texto.
        # Trilha vazia desliga o bloco inteiro (nas duas cascas — no
        # DSGov, `_breadcrumb.html` também usa `{% if trilha %}` para
        # TODO o bloco, então a página inicial passa a não mostrar
        # nenhuma trilha, convenção comum para a página raiz).
        "trilha": [],
        "subtitulo": f"PCA {exercicio.ano}" if exercicio else None,
        "exercicio": exercicio,
        "kpis": kpis,
        "graficos": graficos_ctx,
        "pendencias": pendencias,
        "sei_card": sei_card,
        "manuais_divergentes": manuais_divergentes,
        "solicitacoes_a_avaliar": solicitacoes_a_avaliar,
        # Faixa de abertura (busca grande) e "Acesso
        # rápido" no padrão da página inicial do PNCP; o valor total e o
        # resto dos números ficam no painel de Análises (link abaixo dos
        # gráficos).
        "analise_url": reverse("pca:analise"),
        "acesso_rapido": _acesso_rapido(request),
        # "Ver números" (`ver_numeros_url`) saiu
        # do contexto com a remoção do 4º gráfico (situação por mês); o
        # `{% if ver_numeros_url %}` de `core/templates/core/inicio.html`
        # já cobre a ausência, sem editar o template.
    }
    resposta = TemplateResponse(request, "core/inicio.html", contexto)
    # Pitfall 16 — nunca cacheável na borda; o filtro é por sessão
    # autenticada, não público.
    resposta["Cache-Control"] = "private, no-store"
    return resposta


# Cartões "Acesso rápido" do Início: os MESMOS destinos
# do menu lateral (`core.menu.itens`, que já filtra por permissão), menos a
# própria página inicial e os itens de conta/administração; "Análises" (pasta)
# aponta para o primeiro subitem que o usuário pode abrir.
_ACESSO_RAPIDO_DESCRICOES = {
    "Processos": "Todos os itens do PCA, com filtros, colunas à escolha e exportação.",
    "Calendário": "Prazos do mês e do ano, item a item.",
    "Resumo por unidade": "Planejado, contratado e situação de cada unidade.",
    "Análises": "Valores, situação, perfil do PCA e vencimentos.",
    "Relatório da reunião": "Registros da reunião e movimentação do período, em PDF ou para colar no SEI.",
    "Assistente de IA": "Perguntas sobre o PCA em linguagem natural.",
    "Reuniões": "Reuniões mensais de acompanhamento.",
    "Solicitações": "Pedidos das unidades: alterar, cancelar ou incluir itens do PCA, e acompanhar a decisão.",
}


def _acesso_rapido(request):
    from core.menu import itens

    cartoes = []
    for item in itens(request):
        descricao = _ACESSO_RAPIDO_DESCRICOES.get(item["rotulo"])
        if descricao is None:
            continue
        url = item.get("url") or (item.get("filhos") or [{}])[0].get("url")
        if url:
            cartoes.append({"rotulo": item["rotulo"], "icone": item["icone"], "url": url, "descricao": descricao})
    return cartoes


@login_not_required
def manifest_view(request):
    """`manifest.json` servido por view, não arquivo estático puro (Pitfall A).

    Em produção o `CompressedManifestStaticFilesStorage` do WhiteNoise
    hasheia o nome de cada ícone (`icon-192.abcd1234.png`); um `.json`
    estático com `"/static/img/icon-192.png"` literal 404aria depois do
    primeiro `collectstatic`. Resolvendo via `static()` aqui, o corpo do
    manifest sempre aponta para o nome real do arquivo, hasheado ou não.
    """
    dados = {
        # Sem ano, de propósito: o manifest fica em cache no dispositivo depois
        # da instalação, então um "PCA 2026" fixo aqui sobreviveria à virada de
        # exercício e passaria a mentir sobre o que o app é (Fase 5).
        "name": "PCA — Plano de Contratações Anual",
        "short_name": "PCA",
        # O PWA passa a abrir em `/inicio`
        # (nova entrada do sistema); `scope` continua "/" — o escopo do PWA
        # cobre o app inteiro, só a tela inicial pós-instalação muda.
        "start_url": "/inicio",
        "scope": "/",
        "display": "standalone",
        # Hex literal inevitável — chave de manifest PWA
        # exige valor literal, sem equivalente var(). background_color casa
        # com --cor-page (var(--gray-2), #f8f8f8) para o splash não divergir
        # do fundo real da aplicação; theme_color é o azul do govbr-ds
        # (--blue-warm-vivid-70), não mais o azul institucional do CFC (revertida).
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


# Fase 26 — precache do `install` do service worker:
# a lista fixa de CSS/JS de `base.html` (fontes primeiro, senão os
# `@font-face` de `fontes.css` apontariam para um recurso ainda não
# cacheado) + as 22 fontes woff2 (18 arquivos Rawline, 9 pesos x normal/itálico, + 4 variantes Raleway,
# `fontes.css`, todas de fato `@font-face`'d — conferido acima, nenhuma
# sobra). `echarts.min.js`/`echarts-dsgov.js` ficam FORA do precache: só
# carregam nas páginas com gráfico (`{% block scripts %}` condicional,
# `base.html`), então cacheiam em runtime na primeira visita ao dashboard/
# Análises — precachear no install penalizaria quem nunca abre essas
# páginas com download extra irrelevante.
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
    """`sw.js` hand-rolled (sem Workbox) — só cacheia `/static/`.

    Base verbatim do fetch/activate Pitfall 17, servido por
    rota de raiz (nunca `/static/sw.js` — esse é o erro nº 1 nomeado pelo
    Pitfall 17, "o PWA não instala") com `Service-Worker-Allowed: /`
    explícito. Duas extensões sobre o Pitfall 17: precache da página
    offline no `install` e fallback de navegação. HTML, fragmentos
    HTMX e JSON nunca são interceptados — só GET de mesma origem sob
    `/static/`.
    """
    offline_url = static("offline.html")
    texto = (
        "// CACHE_NAME versionado manualmente — faça bump do sufixo sempre\n"
        "// que o conjunto de estáticos cacheados mudar de formato\n"
        "//. v3: o conjunto mudou de\n"
        "// formato — os chunks p-*.entry.js do loader Stencil do govbr-ds\n"
        "// (..22-39) não existiam sob CACHE_NAME=v2.\n"
        "// v4-v7 (Fase 23..23-03): pca.css e\n"
        "// os templates da dashboard mudaram (Faixa de Volume plana, gauge\n"
        "// compacto, toolbar, hook htmx:beforeSwap em base.html).\n"
        "// v8-v9 (e 23-05): Faixa de Situação plana, top10/status\n"
        "// por container query; toolbar por query/state e Bloco 27 enxuto.\n"
        "// v10: dividers do DS nas duas faixas de KPI,\n"
        "// faixas viram .br-accordion recolhível no celular e colunas\n"
        "// proporcionais (3:2) para célula de largura uniforme — pca.css e\n"
        "// _dashboard_blocos.html mudaram.\n"
        "// v11: delimitador sutil entre KPIs vizinhos nas\n"
        "// duas faixas (pseudo-elemento + tokens de sombra) e correção do\n"
        "// .module com moldura dupla em br-card — só pca.css mudou.\n"
        "// v12 (Fase 24): zera o padding do HOST\n"
        "// (colisão [class*=col-] do bundle) + ::part(wrapper) + ::part(content)\n"
        "// dos 8 br-card.module de gráfico da dashboard abaixo de 768px, e\n"
        "// afina a borda deles para --cor-grid-tenue em qualquer largura — só\n"
        "// pca.css mudou.\n"
        "// v13 (Fase 24): Perfil do PCA\n"
        "// migrado para .pca-dashboard-faixa*/.br-accordion (5 accordions),\n"
        "// e os resumos redundantes de rodapé (\"Nos 12 meses\"/\"Concluído: R$\n"
        "// ...% do valor planejado\") saíram da dashboard — pca.css e\n"
        "// _dashboard_blocos.html mudaram.\n"
        "// v14 (Fase 24): paridade de largura útil medida\n"
        "// entre dashboard/calendário/tabela/resumo por UO — `.tabela-rodape`\n"
        "// ganha flex-wrap (elimina os 6px de overflow do documento em\n"
        "// /tabela@360, achado real: <br-pagination> forçado a caber numa só\n"
        "// linha) e `.row` da casca ganha flex:1 1 auto (achado real: sem\n"
        "// isso, /tabela perdia ~49px de largura útil a 1920px porque seu\n"
        "// conteúdo, com overflow-x:auto, contribui tamanho automático ~0\n"
        "// para o cálculo de conteúdo do ancestral) — só pca.css mudou.\n"
        "// v15 (pedido do usuário: \"borda infinita como\n"
        "// YouTube\" no smartphone): sangramento lateral (margin-inline\n"
        "// negativo, cancela o padding de .pca-shell__conteudo) + remoção da\n"
        "// moldura/raio (border/border-radius) dos br-card.module de gráfico\n"
        "// da dashboard abaixo de 768px, exceto o Perfil — só pca.css mudou.\n"
        "// v16 (Fase 24): tela \"Análise\" (gráfico\n"
        "// mensal com seletor de medida/dimensão/empilhado-agrupado) — o\n"
        "// `<div id=\"grafico-mensal\">` precisa da MESMA altura fixa que os\n"
        "// outros 4 alvos de ECharts já tinham (achado real, sem\n"
        "// altura própria o ECharts não ganha um <canvas> visível) — só\n"
        "// pca.css mudou.\n"
        "// v17 (Fase 24): tela \"Análise\" ganha\n"
        "// os dois gráficos que faltavam — \"Adiamentos por item\" (lista HTML,\n"
        "// sem ECharts) e \"Vencimento de contratos vigentes\" (barras por\n"
        "// mês); `#grafico-vencimento` precisa da MESMA altura fixa que os\n"
        "// outros alvos de ECharts (aplicada desde o início desta vez) —\n"
        "// pca.css e os templates de Análise mudaram.\n"
        "// v18: botões a ~50% em todo o app, paleta\n"
        "// categórica de 10 cores, títulos ≤2 palavras centralizados,\n"
        "// Adiamentos por item vira gráfico de barras — pca.css, templates\n"
        "// da dashboard/Análise e os scripts de gráfico mudaram.\n"
        "// v19 (Revisão 2 — checkpoint da Revisão 1\n"
        "// rejeitado): a redução de botão deixa de ser um valor calculado\n"
        "// (50%) e passa a ser a densidade \"small\" NATIVA do `<br-button>`\n"
        "// (-20% exato, --button-small) com fonte um degrau abaixo na\n"
        "// escala do design system — só pca.css mudou.\n"
        "// v22: hierarquia tipográfica do modal de\n"
        "// editar processo, densidade das linhas de campo, initial-focus-\n"
        "// selector do modal (sai do painel da aba) — só pca.css e o\n"
        "// template do modal mudaram.\n"
        "// v23: #nav-visoes sticky a partir de 992px +\n"
        "// ResizeObserver de --pca-header-altura no x-init do <br-header>\n"
        "// — pca.css e shell.html mudaram.\n"
        "// v24: hidratação dos webcomponents deixa de ser\n"
        "// checagem síncrona de tentativa única (shadowRoot num instante) e\n"
        "// passa a esperar `componentOnReady()`, com varredura inicial sobre\n"
        "// o documento inteiro (cobre o que vive fora do <main>) — só\n"
        "// base.html mudou.\n"
        "// v25 (Fase 25): manifest start_url e destino pós-login\n"
        "// sem `next` passam a ser `/inicio` (nova pagina de entrada do\n"
        "// sistema); pca.css ganha o grid de cards da Inicio (Bloco 32) —\n"
        "// core/views.py e pca.css mudaram.\n"
        "// v28 (Fase 25): bump herdado do 25-05 — pca.css\n"
        "// mudou nos commits 41f60cf/2eb3d42 sem subir o cache; corrigido\n"
        "// aqui antes de qualquer tarefa nova deste plano.\n"
        "// v31 (Fase 26): base.html/dsgov/_*.html/login/\n"
        "// trocar_senha na casca do padrão DSGov; nenhuma mudança na estratégia de\n"
        "// cache (fetch handler já cacheia /static/* em runtime, sem addAll\n"
        "// por arquivo) — core/static/dsgov/** passa a ser cacheado\n"
        "// automaticamente na primeira requisição.\n"
        "// v32 (Fase 26..17): core:inicio vira o\n"
        "// dashboard real (4 KPIs, 4 gráficos ECharts, pendências, seletor\n"
        "// de exercício) — core/templates/core/inicio.html mudou.\n"
        "// v33 (Fase 26): vendor antigo (govbr-vendor/\n"
        "// pca.css/pca-icons.js) removido; conjunto de estáticos cacheados em\n"
        "// runtime muda de formato (core/static/dsgov/** no lugar de core/\n"
        "// static/vendor/**). O `install` passa a precachear a lista fixa de\n"
        "// CSS/JS de base.html + as 22 fontes woff2 (Rawline/Raleway) — antes\n"
        "// só cacheava a página offline, deixando o primeiro carregamento\n"
        "// depender de rede mesmo com o SW já instalado.\n"
        "// v34 (Fase 27): bloco de impressão do relatório de\n"
        "// movimentação (.dsgov-relatorio) em dsgov.css.\n"
        "// v35 (Fase 28): campo de busca no header (.header-search,\n"
        "// #main-searchbox) e atalho Alt+Shift+P em dsgov.js.\n"
        "// v36 (Fase 28): alturas fixas do calendário\n"
        "// (80/128px ponteiro, 112/192px toque) e identificação de item nas\n"
        "// células (.dsgov-calendario-item/-itens) em dsgov.css.\n"
        "// v37 (Fase 28): popover próprio do calendário\n"
        "// (.br-tooltip[data-popover-calendario]) em dsgov.css/dsgov.js.\n"
        "// v38 (Fase 28): #main > .container-fluid > .row/.col\n"
        "// ganha o mesmo min-width:0 que .container-lg já tinha (achado da\n"
        "// matriz visual de fechamento — a variante fluida do container\n"
        "// (revogada) sem essa regra estourava a página\n"
        "// em telas com conteúdo largo) em dsgov.css; aria-expanded\n"
        "// do acordeão (Colunas/Mais filtros) sincronizado por JS em dsgov.js\n"
        "// (lacuna documentada em references/componentes/accordion.md).\n"
        "// v42: revogada a variante fluida do container\n"
        "// (container-lg sempre, sem variante fluida) e destravado o clique no\n"
        "// conteúdo por trás do menu lateral expandido a partir de 992px\n"
        "// (pointer-events/menu-scrim), ambos em dsgov.css/base.html.\n"
        "// v43: restauração de rolagem em <form\n"
        "// method=get> sem HTMX (Calendário/Análises/Resumo por unidade/\n"
        "// Início) — sessionStorage por pathname, guardado por referrer\n"
        "// (só restaura ao trocar filtro na mesma tela, nunca ao chegar\n"
        "// pelo menu), em dsgov.js.\n"
        "// v45: caixa de escrita do Assistente\n"
        "// presa ao rodapé como WhatsApp/Telegram no mobile e no desktop\n"
        "// (.dsgov-chat/.dsgov-chat-caixa, padrão DSGov) — dsgov.css mudou;\n"
        "// recopiado também .dsgov-grafico-extra, que já existia no padrão DSGov e\n"
        "// nunca tinha sido copiado ao repositório.\n"
        "// v46: composer do Assistente — Enter envia,\n"
        "// Alt+Enter/Shift+Enter quebram linha, textarea cresce com o texto\n"
        "// (textarea[data-composer], padrão DSGov) — dsgov.js mudou; cópia\n"
        "// também trouxe o callback de BRUpload já presente no padrão DSGov e ainda\n"
        "// não recopiado ao repositório.\n"
        "// v47: largura de coluna ajustável (arraste/\n"
        "// teclado, localStorage por navegador) em toda .br-table — dsgov.css\n"
        "// e dsgov.js mudaram (padrão DSGov); pca-tabler.css/pca-tabler.js\n"
        "// ganharam o mesmo mecanismo no vocabulário Tabler.\n"
        "// v48: ordenação por clique no\n"
        "// cabeçalho em toda tabela SEM paginação de servidor (client-side,\n"
        "// efêmera) — dsgov.css/dsgov.js (padrão DSGov) e pca-tabler.css/\n"
        "// pca-tabler.js ganharam o mesmo mecanismo nas duas cascas.\n"
        'const CACHE_NAME = "pca-static-v66";\n'
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
        "  // cai para a página offline quando a rede falha de fato —\n"
        "  // nunca serve HTML cacheado (Pitfall 17).\n"
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
    """`core:sobre` (Fase 26) — texto institucional
    herdado da Fase 25 (`apps/pca/templates/pca/inicio.html`, seções
    "Sobre o PCA CFC"/"Como usar este sistema", apagado pelo plano —
    texto resgatado do commit `4eb029df319e8382b4069af5d3af505a379e2892~1`
    antes da remoção). View trivial, sem ação — só leitura."""
    return render(
        request,
        "core/sobre.html",
        {"trilha": [("Sobre o sistema", None)]},
    )
