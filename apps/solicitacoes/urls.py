from django.urls import path

from . import views

app_name = "solicitacoes"

# Sem barra final, como as demais rotas do sistema. Inclusão em `config/urls.py` (sem prefixo):
# o prefixo "solicitacoes/" mora aqui.
urlpatterns = [
    path("solicitacoes/nova", views.nova_view, name="nova"),
    path("solicitacoes/minhas", views.minhas_view, name="minhas"),
    path("solicitacoes/avaliar", views.avaliar_view, name="avaliar"),
    path("solicitacoes/<int:ano>/<int:numero>", views.detalhe_view, name="detalhe"),
    path(
        "solicitacoes/<int:ano>/<int:numero>/partes/<int:parte_id>/decidir",
        views.decidir_view,
        name="decidir",
    ),
    path("solicitacoes/<int:ano>/<int:numero>/desistir", views.desistir_view, name="desistir"),
]
