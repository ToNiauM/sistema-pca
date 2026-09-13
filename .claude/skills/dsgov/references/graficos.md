# Gráficos e dashboard

O DSGov não tem componente de gráfico, só um padrão de design ("Padrões > Gráfico"). A skill fixa
**ECharts 5.5.0** com o tema `dsgov` (`core/static/dsgov/js/echarts-dsgov.js`). O modelo nunca escolhe
cor, fonte ou estilo de gráfico: escolhe apenas o **tipo** e os **dados**.

## Regras fixas

1. Todo gráfico vive dentro de um `br-card` com `card-header` (título e, se preciso, subtítulo em
   `text-down-01 text-gray-70`) e `card-content` com o `<div data-grafico>` de altura fixa. O título fica
   no HTML, nunca dentro do canvas (`title.show=false` no tema).
2. Opções vêm do Django via `{{ opcoes|json_script:"grafico-x" }}` e `data-grafico="grafico-x"`. Nada de
   montar objetos de opções à mão em `<script>` dentro do template.
3. Cores: só as do tema. Uma série → azul da marca. Várias categorias → paleta categórica na ordem.
   Escala de intensidade → `dsgov.graficos.sequencial`, obtida em Python com `barras_horizontais(..., escala=True)`
   (mais escuro = maior; é o desenho certo para ranking por unidade/órgão). Status → `dsgov.graficos.status` (mesmas cores
   das `br-tag status`). Passar `color` em série é desvio; o verificador aponta hex em templates.
4. Tipos permitidos e quando usar:
   - **Barras horizontais**: ranking por categoria com rótulos longos (unidades, órgãos, fornecedores).
   - **Colunas**: comparação entre poucos períodos ou categorias curtas (meses, trimestres).
   - **Linha**: evolução no tempo (até 4 séries).
   - **Rosca** (`pie` com `radius: ['55%','80%']`): composição de um todo com até 6 fatias, com total
     no centro (`rosca(..., total=(133, "ativos"), rotulos=True)` escreve "rótulo: valor (pct%)" nas
     fatias). Nunca pizza cheia, nunca 3D.
   - **Colunas empilhadas**: composição ao longo do tempo.
   Não use radar, funil, gauge, treemap ou mapas sem pedido explícito do usuário.
5. Rótulos diretos quando cabem (`label: {show: true, position: 'right'}` em barras); legenda embaixo.
6. Formatação pt-BR nos eixos e tooltips: `dsgov.graficos.inteiro`, `.moeda`, `.percentual` (o ECharts
   aceita `formatter` como função só no JS; no JSON, use `axisLabel.formatter: '{value}'` e formate os
   valores já no servidor quando forem moeda).
7. Acessibilidade: o `<div data-grafico>` leva `role="img"` e `aria-label` com uma frase resumindo o
   dado ("Processos por situação: 12 concluídos, 5 em andamento, 2 atrasados"). Abaixo do gráfico, ou
   num `br-table` na mesma página, os mesmos números aparecem em texto. Cor nunca é a única pista.
   O jeito canônico é `"tabela": graficos.tabela_dados(colunas, linhas)` no dict do card: o
   `_grafico_card.html` renderiza um acordeão "Ver dados" recolhido com a `br-table` (células com `url`
   viram links). Controles do gráfico (medida, ordem) entram como `"acoes"`: um `<form method="get">`
   com `br-select` e botão terciário, renderizado pela view, à direita do título; a troca recarrega a
   página — nunca alternância em JS.
8. Altura: `style` inline é proibido; use as classes `dsgov-grafico` (280px) ou `dsgov-grafico-alto`
   (400px) definidas em `dsgov.css`.
9. Drill-down (filtrar clicando no recorte): um item de dado pode trazer `url` — em rosca
   `{"name": "Atrasado", "value": 12, "url": "/processos?situacao=atrasado"}`, em barras/colunas
   `{"value": 12, "url": "..."}` no lugar do número. O `echarts-dsgov.js` navega ao clique; é a única
   forma de clique permitida (nenhum handler em template, nenhum JS do projeto). A mesma navegação
   tem de existir em texto (tabela companheira ou links), porque clique em canvas não é acessível.
10. Legenda com muitos itens: o tema `dsgov` (`legend: {..., type: "scroll", ...}`) já pagina a
    legenda em UMA única linha com setas de navegação sempre que uma série/categoria tem mais itens
    do que cabem na largura do card — nunca quebra em várias linhas, o que empurraria/sobreporia o
    eixo X e as barras (achado real: card "UO por mês" com 14+ séries, `grid.bottom` fixo do tema
    não crescia para acomodar a legenda de várias linhas). O Python (`colunas()`/`linha()`/
    `rosca()`) nunca declara `legend.type` — o merge profundo tema+opção do próprio ECharts injeta a
    paginação em toda legenda visível (o mesmo mecanismo que já hoje aplica `icon: "roundRect"`/
    `itemWidth: 12` sem o Python declarar nada disso); gráficos com poucas séries continuam com a
    legenda em uma linha só, sem paginação visível (o ECharts só pagina quando não cabe).
11. `montar()` (`echarts-dsgov.js`) chama `inst.setOption(opcoes)` e, IMEDIATAMENTE depois — mesma
    tarefa síncrona, sem `setTimeout`/`requestAnimationFrame` — `inst.setOption(inst.getOption())`.
    Achado real (mesma investigação da regra 10): `type: "scroll"` sozinho não bastava — a PRIMEIRA
    `setOption()` de uma instância nova DESENHA a legenda paginada errada quando há muitos itens
    (ex.: "UO por mês", 14 séries): cada item na posição de OUTRO item, texto sobreposto sobre o
    eixo X e as barras — mesmo a opção já estando correta desde o início (`getOption()` já mostrava
    `type: "scroll"`; só o DESENHO da primeira passada saía errado). A causa NÃO é tempo decorrido
    nem fonte: chamar `setOption(opcoes)` de novo — o MESMO objeto raso que veio do `json_script`,
    sem os campos que o tema resolveu — não corrige em NENHUM atraso testado (nem 0ms nem vários
    segundos depois): o ECharts trata como "nada mudou" e pula o relayout da legenda. Só
    `setOption(inst.getOption())` corrige — o objeto é visivelmente diferente (traz todos os campos
    já resolvidos pelo tema), então o ECharts força o relayout completo; funciona de imediato, na
    MESMA tarefa, sem qualquer atraso (medido empiricamente: `document.fonts.ready` já resolvia bem
    antes do primeiro desenho, e `inst.resize()` sozinho nunca corrigia). Qualquer gráfico novo
    herda a correção automaticamente — nenhum template nem `core/graficos.py` precisa saber disso.

## Exemplo canônico (template)

```django
<div class="col-sm-12 col-md-6 mb-3">
  <div class="br-card h-100">
    <div class="card-header">
      <div class="text-weight-semi-bold text-up-01">Processos por situação</div>
      <div class="text-down-01 text-gray-70">Exercício {{ exercicio }}</div>
    </div>
    <div class="card-content">
      {{ grafico_situacao|json_script:"grafico-situacao" }}
      <div class="dsgov-grafico" data-grafico="grafico-situacao" role="img"
           aria-label="{{ grafico_situacao_resumo }}"></div>
    </div>
  </div>
</div>
```

## Exemplo canônico (view)

```python
def opcoes_rosca(rotulos_valores: list[tuple[str, int]]) -> dict:
    return {
        "tooltip": {"trigger": "item"},
        "legend": {"bottom": 0},
        "series": [{
            "type": "pie", "radius": ["55%", "80%"], "avoidLabelOverlap": True,
            "label": {"show": False}, "emphasis": {"label": {"show": True, "fontWeight": "bold"}},
            "data": [{"name": r, "value": v} for r, v in rotulos_valores],
        }],
    }

def opcoes_barras_horizontais(rotulos: list[str], valores: list[int], nome: str) -> dict:
    return {
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "xAxis": {"type": "value"},
        "yAxis": {"type": "category", "data": rotulos, "inverse": True},
        "series": [{"type": "bar", "name": nome, "data": valores, "label": {"show": True, "position": "right"}}],
    }

def opcoes_linha(categorias: list[str], series: dict[str, list]) -> dict:
    return {
        "tooltip": {"trigger": "axis"},
        "legend": {"bottom": 0},
        "xAxis": {"type": "category", "data": categorias, "boundaryGap": False},
        "yAxis": {"type": "value"},
        "series": [{"type": "line", "name": n, "data": d} for n, d in series.items()],
    }
```

Para colorir por status (rosca de situações), a view passa os nomes e o JS do tema não sabe qual fatia é
qual. Nesse caso, e só nesse, a view inclui `"itemStyle": {"color": COR_STATUS[chave]}` usando o dict
`CORES_STATUS` de `core/graficos.py`, que espelha `dsgov.graficos.status`. É a única exceção.

## Layout fixo do dashboard

Ordem imutável, de cima para baixo:

1. `h1` com o nome do painel e, opcional, um `p` de contexto (período, filtro ativo).
2. **Linha de KPIs**: 4 cards (`col-sm-6 col-md-3`), cada um com `_kpi_card.html`: rótulo em
   `text-down-01 text-gray-70 text-uppercase`, valor em `text-up-04 text-weight-semi-bold`, e uma linha de
   apoio (variação, meta, ícone). Em tablet ficam 2 por linha, em celular 1.
3. **Grade de gráficos**: 2 colunas (`col-md-6`), 2 a 4 cards. Cada card = 1 gráfico.
4. **Pendências / últimos registros**: um `br-table` curto (até 10 linhas, sem paginação, sem busca) com
   link "Ver todos" para a listagem completa, dentro de um card ou direto na página.

O modelo decide o que entra em cada bloco; nunca a ordem, o número de colunas ou o estilo.
