"""View genérica de listagem no padrão da skill dsgov: busca, filtros, ordenação e paginação
server-side, com resposta parcial para HTMX. As subclasses só declaram atributos.
"""

from django.conf import settings
from django.db.models import Q
from django.views.generic import ListView


class ListagemView(ListView):
    """Uso:

    class ListarDiarias(ListagemView):
        model = Diaria
        template_name = "diarias/listar.html"
        template_parcial = "diarias/_tabela.html"
        titulo = "Diárias"
        busca_campos = ["servidor__nome", "destino"]             # icontains, parâmetro ?q=
        ordenacoes = {"servidor": "servidor__nome", "data": "data_ida", "valor": "valor_total"}
        ordenacao_padrao = "-data_ida"
        filtros = {"situacao": "situacao", "unidade": "servidor__unidade_id"}   # ?situacao=...
        colunas = [ {"campo": "servidor.nome", "rotulo": "Servidor", "ordenar": "servidor"},
                    {"campo": "data_ida", "rotulo": "Ida", "tipo": "data", "ordenar": "data"},
                    {"campo": "valor_total", "rotulo": "Valor", "tipo": "moeda", "ordenar": "valor"} ]
    """

    template_parcial = None
    titulo = ""
    busca_campos: list[str] = []
    ordenacoes: dict[str, str] = {}
    ordenacao_padrao = "-pk"
    filtros: dict[str, str] = {}
    colunas: list[dict] = []
    context_object_name = "objetos"

    def get_paginate_by(self, queryset):
        opcoes = settings.DSGOV.get("OPCOES_POR_PAGINA", (10, 20, 50))
        try:
            pedido = int(self.request.GET.get("por_pagina", ""))
        except ValueError:
            pedido = 0
        return pedido if pedido in opcoes else settings.DSGOV.get("ITENS_POR_PAGINA", 20)

    def get_page_kwarg_value(self):
        return self.request.GET.get("pagina") or 1

    def paginate_queryset(self, queryset, page_size):
        self.kwargs[self.page_kwarg] = self.get_page_kwarg_value()
        return super().paginate_queryset(queryset, page_size)

    def get_queryset(self):
        qs = super().get_queryset()
        q = self.request.GET.get("q", "").strip()
        if q and self.busca_campos:
            cond = Q()
            for campo in self.busca_campos:
                cond |= Q(**{f"{campo}__icontains": q})
            qs = qs.filter(cond)
        for param, lookup in self.filtros.items():
            valores = [v for v in self.request.GET.getlist(param) if v != ""]
            if len(valores) == 1:
                qs = qs.filter(**{lookup: valores[0]})
            elif valores:
                qs = qs.filter(**{f"{lookup}__in": valores})
        return qs.order_by(self._ordenacao())

    def _ordenacao(self):
        pedido = self.request.GET.get("ordenar", "")
        chave = pedido.lstrip("-")
        if chave in self.ordenacoes:
            campo = self.ordenacoes[chave]
            return f"-{campo}" if pedido.startswith("-") else campo
        return self.ordenacao_padrao

    def filtros_ativos(self):
        """[(param, valor, rótulo)] para os chips de filtros ativos."""
        ativos = []
        q = self.request.GET.get("q", "").strip()
        if q:
            ativos.append(("q", q, f"Busca: {q}"))
        for param in self.filtros:
            for valor in self.request.GET.getlist(param):
                if valor:
                    ativos.append((param, valor, f"{param.replace('_', ' ').capitalize()}: {self.rotulo_filtro(param, valor)}"))
        return ativos

    def opcoes_filtros(self) -> dict[str, list[tuple]]:
        """{param: [(valor, rótulo)]} para os br-select de filtro. Sobrescreva na subclasse."""
        return {}

    def _opcoes_filtros_cache(self):
        if not hasattr(self, "_opcoes"):
            self._opcoes = self.opcoes_filtros()
        return self._opcoes

    def rotulo_filtro(self, param, valor):
        """Traduz o valor do filtro (id ou chave) para o rótulo exibido no chip."""
        for v, r in self._opcoes_filtros_cache().get(param, []):
            if str(v) == str(valor):
                return r
        return valor

    def get_template_names(self):
        if getattr(self.request, "htmx", False) and self.template_parcial:
            return [self.template_parcial]
        return super().get_template_names()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update({
            "titulo": self.titulo,
            "colunas": self.colunas,
            "busca": self.request.GET.get("q", ""),
            "filtros_ativos": self.filtros_ativos(),
            "opcoes_por_pagina": settings.DSGOV.get("OPCOES_POR_PAGINA", (10, 20, 50)),
            "por_pagina": self.get_paginate_by(None),
            "ordenacao_atual": self.request.GET.get("ordenar", ""),
            "opcoes_filtros": self._opcoes_filtros_cache(),
        })
        return ctx
