# br-breadcrumb

## Quando usar / quando não usar
- Use para mostrar onde o usuário está na hierarquia de navegação e melhorar o SEO; posicione logo abaixo do header, de forma consistente em todas as telas.
- É navegação **secundária**: não substitui o menu principal.
- Não use em sites/sistemas sem agrupamento ou hierarquia lógica de páginas.
- O botão Home (terciário, circular) é obrigatório no tipo padrão e aponta para a tela inicial; o último item é a página atual (não é link, fica em destaque).
- Em grid de 4 colunas (mobile) use o tipo **especial** (todos os links vão para o menu dropdown, exceto a página atual) — o JS faz isso automaticamente abaixo de 575px.
- Truncamento automático quando há mais de 5 itens ou falta espaço: os intermediários vão para uma `list dropdown`. Nunca truncar Home, última ancestral e página atual.

## HTML canônico
```html
<nav class="br-breadcrumb" aria-label="Breadcrumbs">
  <ol class="crumb-list" role="list">
    <li class="crumb home">
      <a class="br-button circle" href="/">
        <span class="sr-only">Página inicial</span><i class="fas fa-home"></i>
      </a>
    </li>
    <li class="crumb"><i class="icon fas fa-chevron-right"></i><a href="/servicos">Serviços</a></li>
    <li class="crumb"><i class="icon fas fa-chevron-right"></i><a href="/servicos/documentos">Documentos</a></li>
    <li class="crumb" data-active="active">
      <i class="icon fas fa-chevron-right"></i><span tabindex="0" aria-current="page">Segunda via de CPF</span>
    </li>
  </ol>
</nav>
```

Item com nome longo + tooltip (exemplo oficial "com truncamento"):
```html
<li class="crumb">
  <i class="icon fas fa-chevron-right"></i><a href="/pagina">Página Ancestral Com Título Grande</a>
  <div class="br-tooltip" role="tooltip" info="info" place="top">
    <span class="text" role="tooltip">Página Ancestral Com Título Grande</span>
  </div>
</li>
```

## Variantes e modificadores
| classe/atributo | efeito | exemplo |
| --- | --- | --- |
| `nav.br-breadcrumb` | raiz `inline-grid`, fonte `down-01` medium, `min-height: 7x`, `position:relative` (âncora do dropdown) | `<nav class="br-breadcrumb" aria-label="Breadcrumbs">` |
| `ol.crumb-list` | lista flex sem marcadores, `overflow-x:auto`, padding esquerdo base | `<ol class="crumb-list" role="list">` |
| `li.crumb` | item flex, altura 5x; `a` com `max-width:180px` + `text-overflow:ellipsis` | `<li class="crumb">` |
| `li.crumb.home` | primeiro item; contém `a.br-button.circle` com `fa-home`; margem direita base | ver canônico |
| `.crumb .icon` | separador (`fas fa-chevron-right`), cor `--border-color`, tamanho `sm`, `margin-right:-6px` | `<i class="icon fas fa-chevron-right"></i>` |
| `li.crumb[data-active="active"]` | página atual; o `span` interno recebe estilo de foco; ignorado pelo truncamento (`.crumb:not([data-active])`) | `<li class="crumb" data-active="active">` |
| `span[aria-current="page"][tabindex="0"]` | título da página atual (não é link), `font-weight: medium`, `white-space:nowrap` | ver canônico |
| `li.crumb.menu-mobil[data-toggle="dropdown"]` | **gerado pelo JS**: botão de truncamento (`button.br-button.circle` + `fas fa-folder-plus` / `fa-folder-minus`, ícone `fa-chevron-right`) | não escreva manualmente |
| `nav.br-card > .br-item > a` | **gerado pelo JS**: lista dropdown dos itens ocultos (`position:absolute; left: 9x; top: 7x`) | não escreva manualmente |
| `.d-none` | utilitário que o JS aplica aos crumbs truncados | — |
| `.br-tooltip[info][place="top"]` | tooltip opcional para nomes truncados | ver exemplo |

Não há variantes de cor, densidade ou `inverted` no SCSS do breadcrumb.

## Estados e acessibilidade
- **Auto-init**: `core-init.js` executa `new BRBreadcrumb('br-breadcrumb', el)`. Manual: `new core.BRBreadcrumb('br-breadcrumb', el)`. Método público `resetBreadcrumbs()` refaz o cálculo (útil após alterar a lista via JS).
- Truncamento (`_setView`, reexecutado em `resize`): 
  - `window.innerWidth < 575` → esconde **todos** os crumbs não ativos (se houver mais de um) e insere o botão `menu-mobil` (tipo especial);
  - caso contrário, se `crumbList.scrollWidth > offsetWidth` **ou** mais de 5 crumbs não ativos → esconde os intermediários (mantém o primeiro após Home e o último ancestral) e insere o botão.
- Ao abrir o dropdown o JS cria `nav.br-card` com clones dos `<a>` ocultos (o Home nunca entra), alterna `fa-folder-plus`/`fa-folder-minus`, atualiza `aria-label` do botão ("Breadcrumb menu aberto/fechado") e coloca `tabindex="-1"` no `[aria-current="page"]` enquanto truncado. Clique fora da raiz remove o card.
- **ARIA obrigatória**: `aria-label="Breadcrumbs"` no `nav`, `role="list"` no `ol` (o CSS remove os marcadores), `aria-current="page"` no item atual, `span.sr-only` com texto no botão Home (ícone sem texto).
- Teclado: links e botão Home são focáveis nativamente; o título atual recebe `tabindex="0"` para ser lido em sequência.

## Erros comuns
- Usar `<ul>`/`<div>` em vez de `ol.crumb-list`: o JS busca `.crumb-list` e `.crumb`; o CSS de lista some.
- Esquecer `data-active="active"` no último item: o JS o trata como truncável e pode escondê-lo no mobile.
- Colocar o separador `fa-chevron-right` **depois** do link ou fora do `li`: a ordem canônica é ícone → link dentro do mesmo `li.crumb` (o Home não tem separador).
- Fazer o Home como `<a href>` simples: perde o formato de botão terciário circular (`a.br-button.circle`) exigido pela documentação.
- Escrever manualmente o `li.menu-mobil`/`nav.br-card`: o `_reset()` remove qualquer `.menu-mobil` e recria; duplica ou quebra.
- Colocar o `br-breadcrumb` em container com `overflow:hidden` estreito: o `.br-card` (absoluto) fica cortado.

## Fonte
- https://www.gov.br/ds/components/breadcrumb?tab=designer (markdown bruto: https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/breadcrumb/breadcrumb.md)
- https://www.gov.br/ds/components/breadcrumb?tab=desenvolvedor (SPA; markup dos exemplos locais)
- `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/breadcrumb/examples.html`
- `/opt/web/pca/node_modules/@govbr-ds/core/src/components/breadcrumb/_mixins.scss`
- `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/breadcrumb/breadcrumb.js`
