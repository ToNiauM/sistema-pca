# br-pagination

Componente de paginação do Design System gov.br (@govbr-ds/core 3.7.0). Existem dois tipos: **Padrão** (`<nav class="br-pagination">` com `<ul>` de identificadores de página `.page`, setas e botão de reticências) e **Contextual** (setas de navegação + módulos opcionais de exibição por página, informação "X–Y de Z itens" e atalho para página, usado dentro de tabelas e cards).

## Quando usar / quando não usar

- **Use** quando o volume de dados carregados for extenso e precisar ser dividido em páginas sequenciais menores, melhorando a usabilidade de listas.
- **Use o tipo Padrão** ao final do conteúdo da tela, sempre centralizado; os identificadores de página ficam visíveis e são acessados diretamente.
- **Use o tipo Contextual** integrado a outros componentes (tabela, cards) para controlar a sequência daquele componente; nele só as setas de navegação são obrigatórias, os módulos de exibição, informação e atalho são opcionais e podem ser alinhados à esquerda ou à direita com utilitários.
- **Use o botão de reticências** para compactar quando houver muitas páginas (no início, no final ou em ambos); com reticências, limite a no mínimo quatro identificadores visíveis. A lista do dropdown deve ter rolagem acima de 4 itens (o CSS limita a 220px).
- **Prefira densidade baixa (`large`)** na grid de 4 colunas (mobile) para aumentar a área de toque.
- **Não use** paginação para navegação vertical contínua; nesse caso o guia recomenda um botão de ênfase secundária "carregar mais" com `br-loading`, ou rolagem automática.
- Identificadores de página aceitam apenas caracteres numéricos; com 3 ou mais dígitos assumem formato de pílula (crescem na horizontal).

## HTML canônico

Tipo Padrão com reticências (variante mais comum em listagens):

```html
<nav class="br-pagination" aria-label="paginação" data-total="10" data-current="1">
  <ul>
    <li>
      <button class="br-button circle" type="button" data-previous-page="data-previous-page" aria-label="Voltar página"><i class="fas fa-angle-left" aria-hidden="true"></i>
      </button>
    </li>
    <li><a class="page active" href="javascript:void(0)" aria-label="Página 1">1</a></li>
    <li class="pagination-ellipsis">
      <button class="br-button circle" type="button" data-toggle="dropdown" aria-label="Abrir ou fechar a lista de paginação"><i class="fas fa-ellipsis-h" aria-hidden="true"></i>
      </button>
      <div class="br-list" role="menu">
        <a class="br-item" href="javascript:void(0)" aria-label="Página 2" role="menuitem">2</a>
        <a class="br-item" href="javascript:void(0)" aria-label="Página 3" role="menuitem">3</a>
        <a class="br-item" href="javascript:void(0)" aria-label="Página 4" role="menuitem">4</a>
        <a class="br-item" href="javascript:void(0)" aria-label="Página 5" role="menuitem">5</a>
        <a class="br-item" href="javascript:void(0)" aria-label="Página 6" role="menuitem">6</a>
        <a class="br-item" href="javascript:void(0)" aria-label="Página 7" role="menuitem">7</a>
      </div>
    </li>
    <li><a class="page" href="javascript:void(0)" aria-label="Página 8">8</a></li>
    <li><a class="page" href="javascript:void(0)" aria-label="Página 9">9</a></li>
    <li><a class="page" href="javascript:void(0)" aria-label="Página 10">10</a></li>
    <li>
      <button class="br-button circle" type="button" data-next-page="data-next-page" aria-label="Página seguinte"><i class="fas fa-angle-right" aria-hidden="true"></i>
      </button>
    </li>
  </ul>
</nav>
```

Tipo Padrão simples (sem reticências, `pagination-default.html`):

```html
<nav class="br-pagination" aria-label="paginação" data-total="4" data-current="1">
  <ul>
    <li>
      <button class="br-button circle" type="button" data-previous-page="data-previous-page" aria-label="Voltar página"><i class="fas fa-angle-left" aria-hidden="true"></i></button>
    </li>
    <li><a class="page active" aria-label="Página 1" href="javascript:void(0)">1</a></li>
    <li><a class="page" aria-label="Página 2" href="javascript:void(0)">2</a></li>
    <li><a class="page" aria-label="Página 3" href="javascript:void(0)">3</a></li>
    <li><a class="page" aria-label="Página 4" href="javascript:void(0)">4</a></li>
    <li>
      <button class="br-button circle" type="button" data-next-page="data-next-page" aria-label="Página seguinte"><i class="fas fa-angle-right" aria-hidden="true"></i></button>
    </li>
  </ul>
</nav>
```

Tipo Contextual completo (módulo de exibição + informação + atalho + setas; é o usado em `.table-footer` do `br-table`). A ordem dos módulos e o alinhamento são livres — use `ml-auto`, `d-none d-sm-flex`, `mx-3` e `br-divider` para organizar:

```html
<nav class="br-pagination" aria-label="paginação" data-total="50" data-current="1" data-per-page="20">
  <div class="pagination-per-page">
    <div class="br-select">
      <div class="br-input">
        <label for="per-page-selection-random-72658">Exibir</label>
        <input id="per-page-selection-random-72658" type="text" placeholder=" "/>
        <button class="br-button" type="button" aria-label="Exibir lista" tabindex="-1" data-trigger="data-trigger"><i class="fas fa-angle-down" aria-hidden="true"></i>
        </button>
      </div>
      <div class="br-list" tabindex="0">
        <div class="br-item" tabindex="-1">
          <div class="br-radio">
            <input id="per-page-10-random-72658" type="radio" name="per-page-random-72658" value="per-page-10-random-72658" checked="checked"/>
            <label for="per-page-10-random-72658">10</label>
          </div>
        </div>
        <div class="br-item" tabindex="-1">
          <div class="br-radio">
            <input id="per-page-20-random-72658" type="radio" name="per-page-random-72658" value="per-page-20-random-72658"/>
            <label for="per-page-20-random-72658">20</label>
          </div>
        </div>
        <div class="br-item" tabindex="-1">
          <div class="br-radio">
            <input id="per-page-30-random-72658" type="radio" name="per-page-random-72658" value="per-page-30-random-72658"/>
            <label for="per-page-30-random-72658">30</label>
          </div>
        </div>
      </div>
    </div>
  </div><span class="br-divider d-none d-sm-block mx-3"></span>
  <div class="pagination-information d-none d-sm-flex"><span class="current">1</span>&ndash;<span class="per-page">20</span>&nbsp;de&nbsp;<span class="total">50</span>&nbsp;itens</div>
  <div class="pagination-go-to-page d-none d-sm-flex ml-auto">
    <div class="br-select">
      <div class="br-input">
        <label for="go-to-selection-random-83721">Página</label>
        <input id="go-to-selection-random-83721" type="text" placeholder=" "/>
        <button class="br-button" type="button" aria-label="Exibir lista" tabindex="-1" data-trigger="data-trigger"><i class="fas fa-angle-down" aria-hidden="true"></i>
        </button>
      </div>
      <div class="br-list" tabindex="0">
        <div class="br-item" tabindex="-1">
          <div class="br-radio">
            <input id="go-to-1-random-83721" type="radio" name="go-to-random-83721" value="go-to-1-random-83721" checked="checked"/>
            <label for="go-to-1-random-83721">1</label>
          </div>
        </div>
        <div class="br-item" tabindex="-1">
          <div class="br-radio">
            <input id="go-to-2-random-83721" type="radio" name="go-to-random-83721" value="go-to-2-random-83721"/>
            <label for="go-to-2-random-83721">2</label>
          </div>
        </div>
        <div class="br-item" tabindex="-1">
          <div class="br-radio">
            <input id="go-to-3-random-83721" type="radio" name="go-to-random-83721" value="go-to-3-random-83721"/>
            <label for="go-to-3-random-83721">3</label>
          </div>
        </div>
      </div>
    </div>
  </div><span class="br-divider d-none d-sm-block mx-3"></span>
  <div class="pagination-arrows ml-auto ml-sm-0">
    <button class="br-button circle" type="button" aria-label="Voltar página"><i class="fas fa-angle-left" aria-hidden="true"></i>
    </button>
    <button class="br-button circle" type="button" aria-label="Página seguinte"><i class="fas fa-angle-right" aria-hidden="true"></i>
    </button>
  </div>
</nav>
```

Tipo Contextual compacto (só setas): `<nav class="br-pagination" aria-label="paginação" data-total="50" data-current="1" data-per-page="10"><div class="pagination-arrows">…dois br-button circle…</div></nav>`. Qualquer combinação de módulos é válida (o exemplo oficial `pagination-contextual.html` traz três arranjos: exibição→informação→atalho→setas; setas→atalho→exibição→informação; exibição→informação→atalho→setas com `ml-auto`).

## Variantes e modificadores

| Classe / atributo | Efeito | Exemplo |
| --- | --- | --- |
| `.br-pagination` | Container obrigatório (`display: flex; flex-wrap: wrap; justify-content: center`). Define `--pagination-size: var(--pagination-medium)` (32px), `--pagination-margin: var(--spacing-scale-base)`, `--pagination-select-width: 88px`. | `<nav class="br-pagination" aria-label="paginação">` |
| `data-total="N"` | Total de páginas (documentado como obrigatório). Informativo: o JS 3.7.0 não o lê, conta os `.page` presentes. | `data-total="10"` |
| `data-current="N"` | Página ativa (documentado como obrigatório). Informativo: o JS usa a classe `.active`. | `data-current="1"` |
| `data-per-page="N"` | Itens por página, usado só na variante contextual (informativo). | `data-per-page="20"` |
| `ul > li > a.page` | Identificador de página (tipo Padrão). Círculo de `--pagination-size`, cor `--interactive`, hover com `@include hover`; pílula quando o texto é largo (`padding: 0 var(--spacing-scale-base)`). | `<li><a class="page" href="javascript:void(0)" aria-label="Página 2">2</a></li>` |
| `a.page.active` | Página atual: fundo `--active`, texto `--color-dark`, `--font-weight-semi-bold`. O JS move esta classe ao clicar e seta `aria-current="page"`. | `<a class="page active" aria-current="page" …>1</a>` |
| `[data-previous-page]` / `[data-next-page]` | Botões de seta (`br-button circle`, ícones `fas fa-angle-left` / `fas fa-angle-right`). Obrigatórios no tipo Padrão; o JS os desabilita (`disabled`) na primeira/última página após uma seleção e usa-os como limite da navegação por teclado. | `<button class="br-button circle" type="button" data-previous-page="data-previous-page" aria-label="Voltar página">` |
| `li.pagination-ellipsis` | Item de reticências: `br-button circle` com `data-toggle="dropdown"` (ícone `fas fa-ellipsis-h`) seguido de `.br-list[role=menu]` com `a.br-item[role=menuitem]`. A lista tem `max-height: 220px`, `overflow-y: auto`, `min-width: 4em`, `z-index: var(--z-index-layer-1)`. O JS adiciona `.dropdown` ao `li`, `aria-haspopup="true"`/`aria-expanded` ao botão e `hidden` à lista quando fechada. | ver HTML canônico |
| `[data-previous-interval]` / `[data-next-interval]` (gerados) | `li` de reticências estáticas (`<a><i class="fas fa-ellipsis-h"></i></a>`) inseridos automaticamente pelo JS quando há mais de 9 `.page` e o usuário troca de página (`_setLayout`); páginas excedentes recebem `.d-none`. | gerado pelo JS |
| `.small` | Densidade alta: `--pagination-size: var(--pagination-small)` = 24px. | `<nav class="br-pagination small">` |
| `.medium` | Densidade média (padrão explícito): 32px. | `<nav class="br-pagination medium">` |
| `.large` | Densidade baixa: 40px (recomendada em mobile / touch). | `<nav class="br-pagination large">` |
| `.dark-mode` / `.inverted` | Fundo escuro: aplica `dark-mode` e `select-dark-mode`; `.page` fica `--color-dark`, labels dos `br-item` também; `.page.active` ganha `background-color: var(--background-light)` e `color: var(--active)`. A documentação dev cita apenas `dark-mode`; `inverted` também existe no CSS. Use dentro de um fundo escuro (ex.: `bg-gray-60 p-3`). | `<div class="bg-gray-60 p-3"><nav class="br-pagination dark-mode">…</nav></div>` |
| `.pagination-per-page` | Módulo de exibição (itens por página): `br-select` com label "Exibir" ao lado do input (label `--font-weight-regular`, `margin-right: base`), input com `--input-size: var(--pagination-medium)`, largura 88px, texto alinhado à direita e borda transparente quando sem foco. Lista `min-width: 5em; right: 0`. | ver HTML contextual |
| `.pagination-go-to-page` | Módulo de atalho (ir para página): mesma estrutura de `br-select` com label "Página". | ver HTML contextual |
| `.pagination-information` | Módulo de informação: `display: flex; align-items: center`. Conteúdo textual `<span class="current">1</span>&ndash;<span class="per-page">20</span>&nbsp;de&nbsp;<span class="total">50</span>&nbsp;itens`. As classes `current`, `per-page`, `total` não têm CSS próprio; são ganchos para a aplicação atualizar os números. | ver HTML contextual |
| `.pagination-arrows` | Módulo de setas do tipo Contextual: dois `br-button circle` (`fas fa-angle-left`, `fas fa-angle-right`) com `aria-label="Voltar página"` / `"Página seguinte"`. Aqui não se usa `data-previous-page`/`data-next-page` (o exemplo oficial não os usa). | ver HTML contextual |
| `span.br-divider` | Separador vertical entre módulos (`border-right-width: var(--divider-size); border-top: 0` dentro do `.br-pagination`). Nos exemplos: `class="br-divider d-none d-sm-block mx-3"`. | `<span class="br-divider d-none d-sm-block mx-3"></span>` |
| Utilitários de layout | `d-none d-sm-flex` (oculta módulo no mobile), `d-none d-sm-block` (divider), `ml-auto` (empurra módulo para a direita), `ml-sm-0`, `mx-3`. Todos existem em `core.css`. | `<div class="pagination-go-to-page d-none d-sm-flex ml-auto">` |
| `data-trigger` no botão do `br-select` | Exigido pelo `BRSelect` para abrir a lista; botão com `tabindex="-1"` e `aria-label="Exibir lista"`, ícone `fas fa-angle-down`. Dentro de `.br-pagination .br-select .br-input .br-button` o botão fica `position: absolute; right: var(--spacing-scale-half)`. | `<button class="br-button" type="button" aria-label="Exibir lista" tabindex="-1" data-trigger="data-trigger">` |
| `disabled` (atributo) nos botões de seta | Estado desabilitado do `br-button`; o JS o aplica em `[data-previous-page]` quando a página ativa é 1 e em `[data-next-page]` quando é a última. | `<button class="br-button circle" disabled …>` |

## Estados e acessibilidade

- **Inicialização**: `core-init.js` instancia automaticamente cada `.br-pagination` (`new BRPagination('br-pagination', el)`). Com apenas `core.min.js`:

```javascript
const paginationList = []
for (const brPagination of window.document.querySelectorAll('.br-pagination')) {
  paginationList.push(new core.BRPagination('br-pagination', brPagination))
}
```

- **Dependências**: Button, Divider, Input, Item, List, Radio, Select. Os `br-select` do tipo Contextual precisam também do `BRSelect` (auto-inicializado por `core-init.js` em todo `.br-select`).
- **O que o JS faz**: (1) teclado — em `li > *:first-child`, `ArrowLeft`/`ArrowRight` movem o foco para o item anterior/seguinte (parando nos botões `data-previous-page`/`data-next-page`), `ArrowDown` sobre o botão de reticências foca o primeiro item da `.br-list`; dentro de `.pagination-per-page .br-list`, `Esc` devolve o foco ao pai; (2) `_setActive` — adiciona `aria-current="page"` ao `.page` cujo texto é igual à página atual (inicialmente 1) e registra clique em `.page` e em `.pagination-ellipsis .br-item`; (3) `_selectPage` — remove `.active`/`aria-current` de todos, aplica ao clicado e chama `_setLayout` (desabilita setas nas extremidades e, com mais de 9 páginas, oculta páginas com `.d-none` inserindo `li[data-previous-interval]`/`li[data-next-interval]`); (4) dropdown das reticências — `aria-haspopup="true"`, `aria-expanded` alternado, `hidden` na lista, `role="menu"`, fecha ao clicar fora, `Esc` fecha e devolve o foco ao botão, `Tab` no último item fecha, `ArrowUp`/`ArrowDown` circulam entre `.br-item`; (5) no `load`, marca `.pagination-per-page .br-select .br-list` com `role="menu"` e seus `.br-item` com `role="menuitem"`.
- **O JS não** carrega dados nem altera `data-current`, `.pagination-information` ou `data-per-page`; a aplicação deve escutar cliques em `.page`/`.br-item`/setas e atualizar os números e o conteúdo.
- **ARIA obrigatório**: `<nav aria-label="paginação">` (landmark); cada `a.page` e `a.br-item` com `aria-label="Página N"` (texto visível é só o número); setas com `aria-label="Voltar página"` / `"Página seguinte"`; botão de reticências com `aria-label="Abrir ou fechar a lista de paginação"`; ícones `<i class="fas …" aria-hidden="true">`; lista com `role="menu"` e itens `role="menuitem"`. Página atual com `aria-current="page"` (o JS aplica, mas coloque no HTML inicial também).
- **Estados visuais** (guia de design): interativo (padrão), hover (`.page:not(:disabled):hover` e hover do `br-button`), ativo (`.page.active`), pressionado (herdado do `br-button`), desabilitado (`disabled` nas setas). Cores: setas e páginas `--blue-warm-vivid-70` (`--interactive`); em fundo escuro `--blue-warm-20`; página ativa fundo `--active` com texto branco (em dark-mode inverte: fundo claro, texto `--active`).
- **Ícones Font Awesome 5**: `fas fa-angle-left`, `fas fa-angle-right` (setas), `fas fa-ellipsis-h` (reticências), `fas fa-angle-down` (botão dos `br-select` contextuais).

## Erros comuns

- **Misturar os dois tipos**: colocar `.page` soltos fora de `<ul><li>` ou usar `<ul>` dentro do tipo Contextual. O tipo Padrão exige `nav.br-pagination > ul > li > (a.page | button[data-previous-page] | button[data-next-page] | li.pagination-ellipsis)`; o Contextual usa apenas `div.pagination-*` diretos no `nav`.
- **Esquecer `.active` na página inicial** ou colocar `.active` em mais de um `.page`: o JS deriva `currentPage` de `.active` e desabilita as setas com base nele.
- **Reticências sem `.br-list` imediatamente após o botão**: o JS usa `element.nextElementSibling` como alvo do dropdown; um wrapper intermediário quebra abrir/fechar e o `Esc`.
- **Usar `<button>` em vez de `<a class="page">`** para os números: o CSS (`border-radius: 100em`, `min-width/min-height: var(--pagination-size)`) e o `aria-current` foram desenhados para o `a.page`; botões herdam estilos de `br-button` se receberem essa classe, mas não são o padrão oficial.
- **Omitir `data-trigger` no botão do `br-select`** do tipo Contextual ou trocar `type="text"` do input: o `BRSelect` só abre a lista pelo `.br-button[data-trigger]` e só escreve em `input[type="text"]`.
- **Aplicar `small|large|dark-mode` nos `<li>` ou nos botões** em vez do `nav.br-pagination`: as variáveis `--pagination-size` e as cores são definidas no container.
- **Ocultar módulos sem `d-none d-sm-flex`** no mobile: o guia recomenda esconder módulos menos relevantes na grid de 4 colunas; sem isso o componente quebra em várias linhas (`flex-wrap: wrap`).

## Fonte

- https://www.gov.br/ds/components/pagination?tab=designer
- https://www.gov.br/ds/components/pagination?tab=desenvolvedor
- Markdown bruto (designer): https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/pagination/pagination.md
- Markdown bruto (desenvolvedor): https://docs-ds.estaleiro.serpro.gov.br/govbr-ds-core/docs/components/pagination/pagination-dev.md
- Exemplos oficiais locais: `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/pagination/examples.html` e `dist/components/pagination/examples/pagination-default.html`, `pagination-ellipsis.html`, `pagination-contextual.html`, `pagination-sizes.html`, `pagination-dark.html`
- JS: `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/pagination/pagination.js`, `dist/core-init.js`
- SCSS: `/opt/web/pca/node_modules/@govbr-ds/core/src/components/pagination/_pagination.scss`, `_mixins.scss`
- CSS compilado verificado: `/opt/web/pca/node_modules/@govbr-ds/core/dist/core.css`
