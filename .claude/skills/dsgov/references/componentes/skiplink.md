# br-skiplink

## Quando usar / quando não usar

- **Use em todas as páginas**, como **primeiro elemento após o `<body>`**, para que usuários de teclado/leitores de tela pulem direto para blocos importantes (conteúdo, menu, busca, rodapé).
- Dois tipos: **Simples** (um item visível por vez, ao tabular; indique a posição no rótulo: "(1/4)") e **Composto** (`full`: todos os itens ao mesmo tempo, **no máximo quatro**).
- Rótulos curtos e diretos ("Ir para o conteúdo"). Opcionalmente uma `br-tag` com o número da tecla de atalho (`accesskey`).
- **Nunca** use o estado desabilitado; o componente fica oculto até receber foco por Tab e volta a se ocultar ao perder o foco.
- **Não use** como menu de navegação visível permanente.

## HTML canônico

Tipo simples (exemplo oficial `dist/components/skiplink/examples/skiplink-simple.html`):

```html
<nav class="br-skiplink" role="menubar">
  <a class="br-item" href="#main-content" role="menuitem" accesskey="1">Ir para o conteúdo <span aria-hidden="true">(1/4)</span> <span aria-hidden="true" class="br-tag text ml-1">1</span></a>
  <a class="br-item" href="#header-navigation" role="menuitem" accesskey="2">Ir para o menu <span aria-hidden="true">(2/4)</span> <span aria-hidden="true" class="br-tag text ml-1">2</span></a>
  <a class="br-item" href="#main-searchbox" role="menuitem" accesskey="3">Ir para a busca <span aria-hidden="true">(3/4)</span> <span aria-hidden="true" class="br-tag text ml-1">3</span></a>
  <a class="br-item" href="#footer" role="menuitem" accesskey="4">Ir para o rodapé <span aria-hidden="true">(4/4)</span> <span aria-hidden="true" class="br-tag text ml-1">4</span></a>
</nav>
```

Os alvos precisam existir na página: `<main id="main-content">`, `<nav id="header-navigation">`, `<div id="main-searchbox">`, `<footer id="footer">` (ids usados pelo template base e pelo `br-header`).

## Variantes e modificadores

| Classe / atributo | Efeito | Exemplo |
| --- | --- | --- |
| `br-skiplink` | Container (obrigatório): `position:fixed; top:0; left: --spacing-scale-2x; display:inline-flex; flex-direction:column; z-index: var(--z-index-layer-4)`. | `<nav class="br-skiplink">` |
| `br-skiplink a` (tipo simples) | Cada link é `position:absolute; top:-100vh` (oculto), `min-width:300px`, fundo `--background`, sombra `--surface-shadow-lg`, `white-space:nowrap`; ao receber `:focus`/`:focus-visible` desliza para `top:0` (transição 150ms ease-out). Só o link focado aparece, sempre na mesma posição. | `<a class="br-item" href="#main-content">` |
| `br-item` (nos links) | Estilo de item (padding, hover, cor de link) herdado do componente Item. Usado em todos os exemplos oficiais. | — |
| `full` | Tipo **composto**: o container inteiro fica oculto (`top:-100vh`) e aparece com `:focus-within`; itens em linha (`flex-direction:row`), `position:relative`, sem sombra individual (`min-width:0`), sombra no container. | `<nav class="br-skiplink full">` |
| `br-skiplink .br-tag` | Tag dentro do item recebe `background: var(--interactive)`. | `<span class="br-tag text ml-1">1</span>` |
| `text` (na tag) | Aparece nos exemplos oficiais, mas **não há regra `.br-tag.text` no `core.css` 3.7.0** (a tag padrão já é o tipo texto). Inócua; pode manter para fidelidade ao exemplo. | — |
| `ml-1` | Espaço entre rótulo e tag (utilitário). | — |
| `href="#id"` | Alvo do atalho (obrigatório). | `href="#main-content"` |
| `accesskey="n"` | Tecla de atalho (obrigatório na doc): número do item. A combinação varia por navegador (Alt+n, Alt+Shift+n, Ctrl+Alt+n). | `accesskey="1"` |
| `role="menubar"` / `role="menuitem"` | Papéis usados no exemplo oficial. | — |
| `<span aria-hidden="true">(1/4)</span>` | Indicador de posição no tipo simples, oculto do leitor de tela. | — |

Não existem variantes de densidade, `inverted`/`dark-mode`, ênfase ou estado `disabled` para skiplink no `core.css` 3.7.0 (e o estado desabilitado é proibido pela diretriz).

## Estados e acessibilidade

- **CSS puro**: não há `dist/components/skiplink/skiplink.js`, nem classe `BRSkiplink`; o `core-init.js` não faz nada com `.br-skiplink`. Nenhum `data-*`.
- **Estados**: oculto (padrão), **foco** (`a:focus`/`a:focus-visible` no simples; `.full:focus-within` no composto), hover (herdado de `br-item`). Jamais desabilitado.
- **Teclado**: Tab revela o primeiro item; Tab/Shift+Tab percorrem os itens (o exemplo cita Ctrl+Tab para sentido oposto na diretriz); Enter ativa o link e move o foco para o alvo; `accesskey` dá o atalho direto. O componente volta a se ocultar quando o foco sai dele.
- **ARIA**: `role="menubar"` no container e `role="menuitem"` em cada link (exemplo oficial); `aria-hidden="true"` nos indicadores "(1/4)" e na tag numérica para o leitor de tela ler apenas o rótulo. Alternativa mais neutra e igualmente válida: `<nav aria-label="Atalhos de acessibilidade">` com links simples.
- **Alvos focáveis**: para o foco realmente pousar no destino, o elemento alvo deve ser focável (`<main id="main-content" tabindex="-1">` quando não for nativamente focável).
- **Dependências**: Tag (`br-tag`), Item (`br-item`).

## Erros comuns

- Colocar o skiplink no meio da página ou depois do header: deve ser o **primeiro** elemento focável após `<body>`, senão o usuário tabula por todo o header antes de vê-lo.
- `href` apontando para `id` inexistente (o link não leva a nada) ou alvo não focável (o foco fica onde estava).
- Esquecer `br-item` nos links: perdem padding, cor e hover do Item.
- Mais de quatro itens no tipo `full`, ou tipo simples sem a indicação "(n/total)" no rótulo.
- Tentar mostrar o componente permanentemente com CSS próprio (`top:0`): ele foi desenhado para aparecer só sob foco.
- Aplicar `disabled`/`aria-disabled`: proibido pela diretriz e sem estilo no CSS.

## Fonte

- https://www.gov.br/ds/components/skiplink?tab=designer
- https://www.gov.br/ds/components/skiplink?tab=desenvolvedor
- https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/skiplink/skiplink.md
- https://docs-ds.estaleiro.serpro.gov.br/govbr-ds-core/docs/components/skiplink/skiplink-dev.md
- https://developer.mozilla.org/pt-BR/docs/Web/HTML/Global_attributes/accesskey (citado pela doc)
- Local: `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/skiplink/examples.html`, `dist/components/skiplink/examples/*.html`, `src/components/skiplink/_mixins.scss`, `dist/core.css`
