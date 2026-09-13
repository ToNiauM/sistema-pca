# Tela: Dashboard (página inicial)

Layout fixo (ordem imutável): título → linha de 4 KPIs → grade de gráficos em 2 colunas → tabela curta de
pendências. O modelo escolhe os dados; não a forma. Template: `core/templates/core/inicio.html` (já pronto).
A view `core/views.py::inicio` só preenche o contexto:

```python
from django.db.models import Count, Sum
from django.urls import reverse
from core import graficos
from core.templatetags.dsgov import moeda
from apps.diarias.models import Diaria

def inicio(request):
    qs = Diaria.objects.all()
    por_situacao = list(qs.values("situacao").annotate(n=Count("id")).order_by("situacao"))
    rotulos = dict(Diaria._meta.get_field("situacao").choices)
    kpis = [
        {"rotulo": "Diárias no ano", "valor": qs.count(), "icone": "fas fa-plane", "url": reverse("diarias:diaria_listar")},
        {"rotulo": "Valor total", "valor": moeda(qs.aggregate(t=Sum("valor"))["t"] or 0), "icone": "fas fa-coins"},
        {"rotulo": "Aguardando aprovação", "valor": qs.filter(situacao="solicitada").count(), "icone": "fas fa-clock",
         "apoio": "Pendentes de análise", "url": reverse("diarias:diaria_listar") + "?situacao=solicitada"},
        {"rotulo": "Pagas", "valor": qs.filter(situacao="paga").count(), "icone": "fas fa-check-circle"},
    ]
    fatias = [(rotulos[r["situacao"]], r["n"]) for r in por_situacao]
    graficos_ctx = [
        {"id": "g-situacao", "titulo": "Diárias por situação",
         "opcoes": graficos.rosca(fatias, status={rotulos[k]: v for k, v in Diaria.STATUS_SITUACAO.items()}),
         "resumo": "Diárias por situação: " + ", ".join(f"{n} {r.lower()}" for r, n in fatias)},
        {"id": "g-unidade", "titulo": "Valor por unidade", "subtitulo": "Em reais",
         "opcoes": graficos.barras_horizontais(unidades, valores, "Valor"), "resumo": "..."},
    ]
    pendencias = {
        "titulo": "Últimas solicitações",
        "url": reverse("diarias:diaria_listar") + "?situacao=solicitada",
        "colunas": [{"campo": "servidor", "rotulo": "Servidor", "url": "get_absolute_url"},
                    {"campo": "destino", "rotulo": "Destino"},
                    {"campo": "data_ida", "rotulo": "Ida", "tipo": "data"},
                    {"campo": "valor", "rotulo": "Valor", "tipo": "moeda"},
                    {"campo": "get_situacao_display", "rotulo": "Situação", "tipo": "status", "chave": "situacao_chave"}],
        "objetos": qs.filter(situacao="solicitada").select_related("servidor").order_by("-criado_em")[:10],
    }
    return render(request, "core/inicio.html", {"trilha": [("Início", None)], "kpis": kpis, "graficos": graficos_ctx, "pendencias": pendencias})
```

Regras:
- Exatamente 4 KPIs (se o domínio só tem 3 métricas relevantes, o quarto é um total ou uma contagem
  do período). KPI é número + rótulo curto + apoio opcional. Nunca gráfico dentro de KPI.
- 2 a 4 gráficos, tipos em `graficos.md`. Cada gráfico tem `resumo` textual (acessibilidade).
- Pendências: no máximo 10 linhas, com "Ver todos" para a listagem filtrada.
- Todo número já formatado no servidor (moeda, milhar). Filtros de período, quando existirem, ficam
  num `br-select` no topo, à direita do título, e recarregam a página inteira (sem HTMX aqui).
