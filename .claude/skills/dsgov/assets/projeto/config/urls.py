from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from core.views import healthz

urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", healthz, name="healthz"),
    path("", include("core.urls")),
    # apps de domínio (o gerador `gerar_app.py` insere aqui)
    # __URLS__
]

handler403 = "core.views.erro_403"
handler404 = "core.views.erro_404"
handler500 = "core.views.erro_500"

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
