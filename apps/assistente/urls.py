from django.urls import path

from apps.assistente import views

app_name = "assistente"

urlpatterns = [
    path("", views.pagina_view, name="pagina"),
    path("perguntar", views.perguntar_view, name="perguntar"),
    path("andamento/<str:requisicao_id>", views.andamento_view, name="andamento"),
    path("nova-conversa", views.nova_conversa_view, name="nova_conversa"),
    # /A12 — conversor `<slug:slug>` já rejeita "/" e "." (traversal).
    path("docs/<slug:slug>", views.documentacao_view, name="documentacao"),
]
