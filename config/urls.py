from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from core.views import healthz


# Fase 26 — telas de erro na casca do padrão DSGov
# dsgov (`core/erro.html`), texto genérico, sem stacktrace nem detalhe
# interno.
handler403 = "core.views.erro_403"
handler404 = "core.views.erro_404"
handler500 = "core.views.erro_500"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", healthz, name="healthz"),
    # Fase 42 — API JSON para as extensões SEI Pro: prefixo
    # próprio, sem colisão com nenhuma rota de apps.pca.urls (mesmo motivo
    # de organização do include do assistente, logo abaixo).
    path("api/sei/", include("apps.pca.api.urls", namespace="api_sei")),
    path("", include("apps.pca.urls", namespace="pca")),
    # Fase 39 — Assistente do PCA. Entra ANTES do include de core.urls
    # (mesmo motivo do include de apps.pca.urls acima): namespace próprio,
    # 404 "Assistente não configurado" quando IA_API_KEY está vazio
    # (apps/assistente/views.py).
    path("assistente/", include("apps.assistente.urls", namespace="assistente")),
    # Fase 43 — Solicitações das unidades (pedidos de alteração, cancelamento e inclusão de itens).
    path("", include("apps.solicitacoes.urls", namespace="solicitacoes")),
    # core.urls carrega o namespace "core" (login/logout/casca/inicio) —
    # necessário para {% url 'core:login' %}/{% url 'core:inicio' %}
    # resolverem como os templates do padrão DSGov esperam. A partir daqui
    # (Fase 26), é ESTE include — não mais um
    # `path("", dashboard_view, name="raiz")` antes dele — quem de fato
    # despacha requisições reais para "/": `core:inicio` (`core/urls.py`,
    # `path("", views.inicio, name="inicio")`) é o novo painel único.
    path("", include("core.urls")),
    # "raiz" permanece resolvível SÓ para `reverse()`: dezenas de
    # chamadas existentes (`apps.pca.navegacao.trilha_padrao`/
    # `destinos_com_href`, testes, templates ainda não migrados) fazem
    # `reverse("raiz")`/`{% url 'raiz' %}` esperando a URL de entrada do
    # sistema. Como esse padrão vem DEPOIS do include acima, ele nunca é de
    # fato despachado para uma requisição HTTP real (mesmo precedente do
    # antigo `core:shell`, que também ficava "morto" por ordem de
    # `urlpatterns` — ver git blame). Não é um redirect(): um redirect
    # aqui apontando para `core:inicio` apontaria para a MESMA URL ("/"),
    # o que criaria um loop infinito — a rota acima já resolve "/"
    # diretamente, então este padrão só existe pelo nome.
    path("", RedirectView.as_view(pattern_name="core:inicio", permanent=True), name="raiz"),
]
