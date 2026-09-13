# Tela: Par analítico (gráfico + tabela)

Padrão para qualquer bloco de Análises/relatório onde um gráfico e sua tabela companheira
representam o MESMO dataset com um título comum — "Processos por situação", "Processos por
unidade", cada grupo de Perfil. Fase 28/Plano 28-01 (D-28-13): primeira fatia completa entregue no
par "Processos por situação" de `apps/pca/templates/pca/analise.html`; os demais pares do mesmo
arquivo migram no Plano 28-06.

## Por que um partial novo (e não `_grafico_card.html`)

`dsgov/_grafico_card.html` (card de gráfico com "Ver dados" opcional, tabela RECOLHIDA num
`br-accordion`) continua correto para os usos em que a tabela é um detalhe secundário — o
dashboard, por exemplo. O par analítico é diferente por contrato (D-28-13/D-28-14):

- Título comum ao gráfico E à tabela — um único `card-header`, não dois blocos com título
  duplicado.
- Gráfico e tabela **lado a lado** a partir de 992px, não um em cima do outro em telas largas.
- A tabela é **sempre visível**, nunca dentro de `br-accordion` — no mobile ela aparece empilhada
  logo abaixo do gráfico, nunca recolhida (D-28-14: recolhimento só em "Ver dados" do Início e em
  detalhamentos secundários, nunca aqui).
- Nunca aninhar um `_grafico_card.html` de meia largura dentro de outra meia largura — o
  antipadrão que motivou este partial (gráfico `col-md-6` sozinho numa `.row`, tabela full-width
  numa segunda `.row` abaixo, distantes verticalmente em desktop sem necessidade).

## Anatomia

Um único `br-card` com `card-header` (título + subtítulo opcional) e `card-content` com uma
`.row` de duas colunas:

1. Gráfico ECharts (`json_script` + `div[data-grafico]` com `role="img"`/`aria-label`, mesmo
   contrato de `_grafico_card.html`).
2. `br-table small` sempre visível, iterando `par.tabela.colunas`/`par.tabela.linhas` (mesmo
   formato `core.graficos.tabela_dados()` que `_grafico_card.html` usa dentro do acordeão) — aqui
   sem acordeão nenhum.

Contrato do contexto (`par`):

```python
par = {
    "titulo": "Processos por situação",        # card-header — também vira <caption class="sr-only">
    "subtitulo": None,                          # opcional
    "grafico": {
        "id": "analise-grafico-situacao",       # data-grafico e id do json_script
        "opcoes": {...},                        # dict ECharts pronto (core.graficos)
        "resumo": "Processos por situação: ...",# aria-label
        "alto": False,                          # opcional — dsgov-grafico-alto em vez de dsgov-grafico
        # SEM "tabela" nem "acoes" — este dict não é o de _grafico_card.html
    },
    "tabela": core.graficos.tabela_dados(colunas, linhas),  # {"colunas": [...], "linhas": [[...]]}
}
```

```django
{% include "dsgov/_par_analitico.html" with par=meu_par %}
```

## Proporção do grid (D-28-13)

Padrão 6/6 (`col_grafico`/`col_tabela` omitidos, default `col-md-6` nos dois — empilha < 992px,
lado a lado >= 992px, breakpoints de `references/layout.md`). Ranking por unidade — onde a tabela
tem uma linha por UO e precisa de mais largura que o gráfico de barras — usa 5/7 a partir de
1280px:

```django
{% include "dsgov/_par_analitico.html" with par=par_unidade col_grafico="col-lg-5" col_tabela="col-lg-7" %}
```

`col_grafico`/`col_tabela` sempre entram já com `col-12` (mobile) somado pelo próprio partial —
quem inclui só passa a classe do breakpoint maior (`col-md-6`, `col-lg-5`, `col-lg-7`...).

## Reaproveitamento

Toda tabela do par usa exatamente a mesma agregação já computada para o gráfico (D-29 — nenhuma
consulta nova por par). `core.graficos.tabela_dados(colunas, linhas)` aceita células já formatadas
(`numero()`/`moeda()`/`percentual()`, aplicados pela VIEW antes de montar `linhas` — o partial
nunca formata número) ou `{"valor": ..., "url": ...}` quando a célula é um link de drill-down para
`/tabela?<querystring>` (mesmo padrão de `_grafico_card.html`).
