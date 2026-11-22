from django.urls import path

from apps.pca.api import views

app_name = "api_sei"

urlpatterns = [
    path("saude", views.saude_view, name="saude"),
    path("processo", views.processo_view, name="processo"),
    path("coleta", views.coleta_view, name="coleta"),
    path("vinculo", views.vinculo_view, name="vinculo"),
    path("ficha", views.ficha_view, name="ficha"),
]
