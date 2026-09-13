from django.urls import path

from core import views

app_name = "core"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("manifest.json", views.manifest_view, name="manifest"),
    path("sw.js", views.service_worker_view, name="service_worker"),
    path("senha/trocar/", views.trocar_senha_view, name="trocar_senha"),
    path("perfil/", views.perfil_view, name="perfil"),
    path("sobre/", views.sobre_view, name="sobre"),
    path("", views.inicio, name="inicio"),
]
