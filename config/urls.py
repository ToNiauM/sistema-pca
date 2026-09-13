from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from core.views import healthz


# Telas de erro na casca dsgov (`core/erro.html`), texto genérico, sem stacktrace.
handler403 = "core.views.erro_403"
handler404 = "core.views.erro_404"
handler500 = "core.views.erro_500"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", healthz, name="healthz"),
    path("", include("apps.pca.urls", namespace="pca")),
    # core.urls: namespace "core" (login/logout/casca/inicio); "/" despacha
    # de fato para core:inicio, o painel único.
    path("", include("core.urls")),
    # "raiz" só existe para reverse()/{% url 'raiz' %}; como vem depois do
    # include acima, nunca é despachada para uma requisição HTTP real.
    path("", RedirectView.as_view(pattern_name="core:inicio", permanent=True), name="raiz"),
]
