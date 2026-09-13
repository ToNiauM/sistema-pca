# br-list

## Quando usar / quando não usar
- Use para listar itens (`br-item`) de forma ordenada: alfabética, cronológica ou por qualquer critério lógico. **Vertical** é o padrão; **horizontal** (`horizontal`) distribui os itens em linha.
- Header opcional (`.header > .title`) seguido de `br-divider`; agrupe itens por **rótulo** (item-título), por **separador** (`br-divider`) ou por **expansão** (`data-toggle="collapse"`).
- Densidades alta (padrão), média (`py-3`) e baixa (`py-4`) definidas pelo padding dos itens; evite densidade alta em telas de 4 colunas.
- Evite mais de um sub-nível de agrupamento; mantenha altura e recursos consistentes entre os itens.
- Não use para navegação principal (use `br-menu`) nem para dados tabulares (use `br-table`).

## HTML canônico
```html
<div class="br-list" role="list">
  <div class="header">
    <div class="title">Documentos</div>
  </div>
  <span class="br-divider"></span>
  <div class="br-item" role="listitem">
    <div class="row align-items-center">
      <div class="col-auto"><i class="fas fa-file-pdf" aria-hidden="true"></i></div>
      <div class="col">Certidão negativa</div>
      <div class="col-auto">PDF</div>
    </div>
  </div>
  <span class="br-divider"></span>
  <div class="br-item" role="listitem">
    <div class="row align-items-center">
      <div class="col-auto"><i class="fas fa-file-pdf" aria-hidden="true"></i></div>
      <div class="col">Comprovante de residência</div>
      <div class="col-auto">PDF</div>
    </div>
  </div>
</div>
```

Agrupamento por expansão (exemplo oficial):
```html
<div class="br-list" role="list">
  <div class="header"><div class="title">Por expansão</div></div>
  <span class="br-divider"></span>
  <div class="br-item" role="listitem" data-toggle="collapse" data-target="grupo-1">
    <div class="content">
      <div class="flex-fill">RÓTULO 01</div><i class="fas fa-chevron-down" aria-hidden="true"></i>
    </div>
  </div>
  <div class="br-list" id="grupo-1" role="list" hidden="hidden">
    <div class="br-item" role="listitem">
      <div class="row align-items-center">
        <div class="col-auto"><i class="fas fa-heartbeat" aria-hidden="true"></i></div>
        <div class="col">Sub-item</div>
      </div>
    </div>
    <span class="br-divider"></span>
  </div>
</div>
```

## Variantes e modificadores
| classe/atributo | efeito | exemplo |
| --- | --- | --- |
| `.br-list` | container com fundo `--background`; `.br-item` internos `width:100%`, `> .content` flex | `<div class="br-list" role="list">` |
| `.header > .title` | cabeçalho (bold, padding `base 2x`, `space-between`) | ver canônico |
| `span.br-divider` | separador entre header/itens/grupos | — |
| `.horizontal` | `display:flex; flex-wrap:wrap`; header ocupa 100%; itens/grupos com `flex:1; min-height:56px`; dividers viram verticais (1px) | `<div class="br-list horizontal">` |
| `.group` (dentro de `.horizontal`) | agrupa item-rótulo + sub-lista em uma "coluna" | `<div class="group">…</div>` |
| `.one-line` / `.two-lines` / `.three-lines` (em item/grupo horizontal) | altura fixa do `.content` 56px / 72px / 6em | `class="br-item one-line"` |
| `[data-one-line]` / `[data-two-lines]` / `[data-three-lines]` (na lista) | altura fixa dos itens 2em / 4em / 6em com conteúdo cortado | `<div class="br-list" data-two-lines>` |
| `.br-item[data-toggle="collapse"][data-target="id"]` | item expansível (cursor pointer; sub-lista `~ .br-list .br-item` com padding `base 3x`) | ver exemplo |
| `.br-list#id[hidden]` (irmã seguinte) | sub-lista alvo, começa oculta | ver exemplo |
| `[data-sub]` (na lista) | **impede** o auto-init do `BRList` (usado pelo footer e por componentes que controlam a lista) | `<div class="br-list" data-sub>` |
| `.br-list .br-list` | lista aninhada: `overflow:hidden; transition: all 400ms` | — |
| `.br-item.py-3` / `.py-4` | densidade média / baixa (utilitários) | — |
| `.br-checkbox.hidden-label` em `.col-auto` | lista com itens selecionáveis (exemplo oficial) | — |
| `.toggle` / `[data-toggle]` em `.horizontal` | itens em `display:block` | — |

Não há `inverted/dark-mode` próprio da lista (aplique nos itens ou no container).

## Estados e acessibilidade
- **Auto-init**: `core-init.js` executa `new BRList('br-list', el)` para cada `.br-list:not([data-sub])`. Manual: `new core.BRList('br-list', el)`.
- Comportamento: para cada `[data-toggle="collapse"]` dentro da lista o JS cria um `Collapse` com `iconToShow: fa-chevron-down`, `iconToHide: fa-chevron-up`, alvo `#<data-target>`. O Collapse define `aria-controls`, `aria-expanded`, `data-visible` no trigger, `aria-hidden` no alvo, `tabindex="0"` no trigger, aceita Enter/Espaço, fecha com Esc e devolve o foco.
- **Ícone**: o JS alterna as classes `fa-chevron-down/up` no `i.fas` do trigger. O exemplo oficial usa `fa-angle-down`; nesse caso o `<i>` acumula `fa-angle-down fa-chevron-up` ao abrir (o CSS do Font Awesome resolve pelo último definido). Para consistência use `fa-chevron-down` no HTML.
- Semântica: `role="list"` na raiz e `role="listitem"` nos itens (divs não são listas nativas). Sub-lista também com `role="list"`.
- Estados: hover em itens interativos; `.selected`/`.active` vêm do `br-item`.

## Erros comuns
- Usar `<ul>/<li>` com `br-list/br-item` sem resetar: marcadores e paddings do navegador aparecem.
- `data-target` com `#` ou sub-lista sem `hidden` inicial: o Collapse não encontra o alvo / inicia invertido.
- Colocar a sub-lista **dentro** do item trigger: deve ser irmã seguinte (`~ .br-list`) para o CSS de padding e para não propagar o clique.
- Esquecer `data-sub` em listas controladas por outro componente (footer, select): duplo `Collapse` e ícones alternando duas vezes.
- Horizontal sem `.group` ao usar expansão: o trigger e a sub-lista viram colunas separadas.
- Divider dentro de `.horizontal` sem ser filho direto de `.br-item`/`.group` irmão: o CSS `+ .br-divider` não aplica a borda vertical.

## Fonte
- https://www.gov.br/ds/components/list?tab=designer (markdown bruto: https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/list/list.md)
- https://www.gov.br/ds/components/list?tab=desenvolvedor (SPA; markup dos exemplos locais)
- `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/list/examples.html`
- `/opt/web/pca/node_modules/@govbr-ds/core/src/components/list/_mixins.scss`
- `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/list/list.js`, `dist/partial/js/behavior/collapse.js`, `dist/core-init.js`
