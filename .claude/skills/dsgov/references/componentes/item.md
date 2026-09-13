# br-item

## Quando usar / quando não usar
- Componente de apoio: é a unidade de `br-list`, menus, dropdowns, select, footer, breadcrumb. Use quando precisar apresentar conteúdos repetidos e ordenados.
- Áreas sugeridas: suporte visual (ícone/avatar/imagem) à esquerda, área principal (texto) e suporte complementar (metadados, botões) à direita — implementadas com a grid interna `.row > .col-auto/.col`.
- Um item pode ser: estático (`div`), interativo inteiro (`a.br-item`, `button.br-item`), com elemento interativo interno (botão dentro), selecionável (`data-toggle="selection"` + checkbox/radio) ou expansível (`data-toggle="collapse"`, ver `list.md`).
- Mantenha a mesma altura e o mesmo padrão de recursos entre itens de uma mesma lista.
- Não use fora de um contexto de lista/menu como "caixa" genérica.

## HTML canônico
```html
<div class="br-list" role="list">
  <div class="br-item" role="listitem">
    <div class="row align-items-center">
      <div class="col-auto"><i class="fas fa-file-alt" aria-hidden="true"></i></div>
      <div class="col">Comprovante de inscrição</div>
      <div class="col-auto">
        <button class="br-button circle" type="button" aria-label="Baixar comprovante">
          <i class="fas fa-download" aria-hidden="true"></i>
        </button>
      </div>
    </div>
  </div>
  <span class="br-divider"></span>
  <a class="br-item" href="/detalhes" role="listitem">Item que é um link</a>
  <span class="br-divider"></span>
  <button class="br-item" type="button" role="listitem">Item que é um botão</button>
</div>
```

Item selecionável (exemplo oficial):
```html
<div class="br-item" data-toggle="selection">
  <div class="br-checkbox">
    <input id="opcao-01" name="opcoes" type="checkbox"/>
    <label for="opcao-01">Rótulo da opção 01</label>
  </div>
</div>
<div class="br-item" data-toggle="selection">
  <div class="br-radio">
    <input id="radio-01" type="radio" name="grupo" value="1"/>
    <label for="radio-01">Rótulo do rádio 01</label>
  </div>
</div>
```

## Variantes e modificadores
| classe/atributo | efeito | exemplo |
| --- | --- | --- |
| `.br-item` | `display:block; width:100%`, padding `base 2x` (`--item-padding`), fundo `--background`, texto à esquerda | `<div class="br-item">` |
| `a.br-item` | cor `--interactive`, hover/active do DS | `<a class="br-item" href>` |
| `button.br-item` | fundo transparente, cor `--color`, focus/hover/active | `<button class="br-item" type="button">` |
| `.row > .col-auto / .col` (interna) | grid com gutters reduzidos (`base`) para suporte visual / conteúdo / meta | ver canônico |
| `.content` | quando em `br-list`: `display:flex; align-items:center` (usado com `data-toggle`), ícones `[class*="fa-"]` 14×16px | `<div class="content">…</div>` |
| `.toogle-icon-interactive` | ícone azul de seta em item `data-toggle` (grafia oficial com "toogle") | — |
| `[data-toggle]` (qualquer valor) | `cursor:pointer` + hover | `data-toggle="collapse"` |
| `[data-toggle="selection"]` + `> .br-checkbox` / `> .br-radio` | item selecionável: checkbox/radio ocupam todo o item (margens negativas), JS adiciona `.selected` | ver exemplo |
| `.selected` | fundo `--selected` (mixin dark-mode) — aplicado pelo JS | — |
| `.active` | fundo `--active`, texto `--color` | `class="br-item active"` |
| `.inverted` / `.dark-mode` | tema escuro; `.active` fica com fundo claro e texto `--active` | `class="br-item dark-mode"` |
| `[disabled]` | exemplo oficial usa `disabled="disabled"` no `div` (estilo do utilitário global `[disabled]`) | `<div class="br-item" disabled="disabled">` |
| `.{cor}` (chaves do mapa `$br-colors`) | colorização via mixin `colorize` (ex.: `.primary`, cores da paleta) | evite; use utilitários `bg-*` |
| `.br-checkbox.hidden-label` interno | checkbox sem texto à direita (lista selecionável) | ver `list.md` |
| utilitários `py-3` / `py-4` | densidades média/baixa (exemplos oficiais de `br-list`) | `class="br-item py-3"` |

## Estados e acessibilidade
- **Auto-init**: `core-init.js` instancia `new BRItem('br-item', el)` para **cada** `.br-item` da página. Manual: `new core.BRItem('br-item', el)`.
- Comportamento JS: para `.br-checkbox input[type="checkbox"]` interno, adiciona/remove `.selected` no item conforme `checked` (inclusive no carregamento). Para `.br-radio input[type="radio"]`, ao clicar marca este item como `.selected` e remove dos irmãos (`parentElement.querySelectorAll('.br-item')`), sincronizando o atributo `checked`.
- Em listas, use `role="listitem"` nos itens e `role="list"` na `br-list` (os exemplos oficiais fazem isso porque `div` não tem semântica de lista).
- Item interativo inteiro: prefira `a`/`button` reais; `div[data-toggle]` só ganha cursor, não foco — adicione `tabindex="0"` e tratamento de teclado se for `div`.
- Botões internos circulares precisam de `aria-label`; ícones `aria-hidden="true"`.
- Estados visuais: hover (itens interativos), selecionado, ativo, desabilitado, foco.

## Erros comuns
- Colocar checkbox/radio em `.br-item` sem `data-toggle="selection"`: funciona, mas sem `cursor:pointer`/hover; e o CSS de margens negativas só vale para filho **direto** (`> .br-checkbox`).
- Usar `li.br-item` dentro de `ul` sem resetar estilos: o DS espera `div/a/button`; o `ul` traz marcadores/padding.
- Esquecer `align-items-center` na `.row`: ícone e texto desalinham verticalmente.
- Aninhar `.br-item` dentro de `.br-item`: padding duplicado e seletores de lista (`.br-list .br-item`) aplicados duas vezes.
- Radios de itens diferentes com `name` distintos: o JS sincroniza `.selected` entre irmãos, mas a exclusividade nativa depende do mesmo `name`.
- Escrever `.toggle-icon-interactive` (grafia correta em inglês): a classe no SCSS é `toogle-icon-interactive`.

## Fonte
- https://www.gov.br/ds/components/item?tab=designer (markdown bruto: https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/item/item.md)
- https://www.gov.br/ds/components/item?tab=desenvolvedor (SPA; markup dos exemplos locais)
- `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/item/examples.html`
- `/opt/web/pca/node_modules/@govbr-ds/core/src/components/item/_mixins.scss`, `_item.scss`
- `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/item/item.js`, `dist/core-init.js`
