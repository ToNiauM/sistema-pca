# br-select

Componente de seleção de itens em lista (*select* simples ou *multiselect*). Compõe `br-input` + `br-button` (gatilho) + `br-list` de `br-item` com `br-radio` (simples) ou `br-checkbox` (múltiplo). Versão @govbr-ds/core 3.7.0.

## Quando usar / quando não usar

- Use para coletar uma escolha do usuário em uma lista de opções; use o tipo **multiselect** quando ele puder escolher mais de um item.
- Ordene os itens de forma lógica (alfabética, cronológica etc.) e, se possível, deixe como padrão a opção mais escolhida.
- Prefira textos curtos e objetivos nos itens; evite quebra de linha dentro do item.
- Respeite as dimensões: largura mínima recomendada de 64 px (CSS impõe `min-width: 100px` e `max-width: 400px`), altura de 40 px no input e 56 px por item; a lista mostra até ~10 itens (`max-height: 404px`) e depois rola.
- O ícone de busca (`fa-search`) é inserido automaticamente pelo JS; em espaços muito reduzidos a diretriz permite retirá-lo.
- Não use para listas muito curtas (2-3 opções) em que `br-radio` ou `br-checkbox` visíveis seriam mais diretos.

## HTML canônico

Select simples (uma escolha). O JS envolve o `<input>` em `div.input-group > div.input-icon > i.fas.fa-search` automaticamente; não escreva isso à mão.

```html
<div class="br-select">
  <div class="br-input">
    <label for="select-uf">Unidade da Federação</label>
    <input id="select-uf" type="text" placeholder="Selecione o item" />
    <button class="br-button" type="button" aria-label="Exibir lista" tabindex="-1" data-trigger="data-trigger">
      <i class="fas fa-angle-down" aria-hidden="true"></i>
    </button>
  </div>
  <div class="br-list" tabindex="0">
    <div class="br-item" tabindex="-1">
      <div class="br-radio">
        <input id="uf-ac" type="radio" name="uf" value="AC" />
        <label for="uf-ac">Acre</label>
      </div>
    </div>
    <div class="br-item" tabindex="-1">
      <div class="br-radio">
        <input id="uf-al" type="radio" name="uf" value="AL" />
        <label for="uf-al">Alagoas</label>
      </div>
    </div>
    <div class="br-item" tabindex="-1">
      <div class="br-radio">
        <input id="uf-df" type="radio" name="uf" value="DF" />
        <label for="uf-df">Distrito Federal</label>
      </div>
    </div>
  </div>
</div>
<span class="feedback warning" role="alert"><i class="fas fa-exclamation-triangle" aria-hidden="true"></i>Texto auxiliar para prevenir erros.</span>
```

Select múltiplo (multiselect): acrescente o atributo `multiple` na raiz, troque `br-radio` por `br-checkbox` e inclua como primeiro item o "Selecionar todos" com `data-all` e classe `highlighted`:

```html
<div class="br-select" multiple="multiple">
  <div class="br-input">
    <label for="select-ufs">Unidades da Federação</label>
    <input id="select-ufs" type="text" placeholder="Selecione os itens" />
    <button class="br-button" type="button" aria-label="Exibir lista" tabindex="-1" data-trigger="data-trigger">
      <i class="fas fa-angle-down" aria-hidden="true"></i>
    </button>
  </div>
  <div class="br-list" tabindex="0">
    <div class="br-item highlighted" data-all="data-all" tabindex="-1">
      <div class="br-checkbox">
        <input id="ufs-todos" name="ufs-todos" type="checkbox" />
        <label for="ufs-todos">Selecionar todos</label>
      </div>
    </div>
    <div class="br-item" tabindex="-1">
      <div class="br-checkbox">
        <input id="ufs-ac" name="ufs-ac" type="checkbox" value="AC" />
        <label for="ufs-ac">Acre</label>
      </div>
    </div>
    <div class="br-item" tabindex="-1">
      <div class="br-checkbox">
        <input id="ufs-al" name="ufs-al" type="checkbox" value="AL" />
        <label for="ufs-al">Alagoas</label>
      </div>
    </div>
  </div>
</div>
```

## Variantes e modificadores

| Classe / atributo | Efeito | Exemplo |
| --- | --- | --- |
| `.br-select` | Raiz. `position: relative; min-width: 100px; max-width: 400px`. Auto-instanciado por `core-init.js`. | `<div class="br-select">` |
| `multiple` (atributo na raiz) | Modo multiselect: JS lê `component.hasAttribute('multiple')`; itens usam `br-checkbox`; input mostra "Item + (N)"; `aria-multiselectable="true"` é adicionado. Não existe `data-multiple`. | `<div class="br-select" multiple="multiple">` |
| `.br-input` | Container do campo. Aceita densidades do Input: `.br-input.small` (alta), `.br-input.large` (baixa); padrão = média. | `<div class="br-input small">` |
| `.br-input.danger` / `.br-input.success` + `span.feedback.danger|success|warning|info` | Estados de validação (herdados do Input). Feedback com `role="alert"` logo após o `.br-select`. | `<span class="feedback danger" role="alert"><i class="fas fa-times-circle" aria-hidden="true"></i>Campo obrigatório</span>` |
| `button.br-button[data-trigger]` | Botão terciário que abre/fecha a lista. JS alterna o ícone `fa-angle-down` ↔ `fa-angle-up` e `aria-label` "Exibir lista"/"Ocultar lista". `tabindex="-1"` para não duplicar foco. | `<button class="br-button" data-trigger="data-trigger" tabindex="-1">` |
| `.br-list` | Lista flutuante (`display:none`, sombra `--surface-shadow-md`, `max-height: 404px`, `z-index:1`). Precisa de `tabindex="0"` para navegação por teclado. | `<div class="br-list" tabindex="0">` |
| `.br-list[expanded]` | Estado aberto (`display:block`). Controlado pelo JS; pode ser pré-definido no HTML. | `<div class="br-list" expanded>` |
| `.br-item` | Cada opção, com `tabindex="-1"`; divisor `--select-divider` entre itens. | `<div class="br-item" tabindex="-1">` |
| `.br-item.selected` / `.br-item[selected]` | Item selecionado (fundo escuro). JS adiciona/remove; usar no HTML para carregar pré-selecionado. | `<div class="br-item selected">` |
| `input[checked]` | Alternativa para carregar pré-selecionado (radio ou checkbox). | `<input type="radio" checked>` |
| `.br-item.highlighted` / `[highlighted]` | Item destacado (fundo `--gray-2`, rótulo semi-bold). Usado no "Selecionar todos". | `<div class="br-item highlighted" data-all="data-all">` |
| `data-all` (no `.br-item`) | Marca o item que seleciona/deseleciona todos; JS alterna rótulo "Selecionar todos"/"Deselecionar todos". Só no multiselect. | `data-all="data-all"` |
| `.br-item.disabled` | Item desabilitado (CSS: mais padding, sem hover/focus). | `<div class="br-item disabled">` |
| `.br-item.not-found` | Item de "Ops! Não encontramos..." injetado pelo JS quando o filtro não acha nada (o HTML é o 3.º parâmetro opcional do construtor). Sem CSS próprio em core.css. | `new core.BRSelect('br-select', el, '<div class="br-item not-found">…</div>')` |
| `.br-select.inverted` / `.br-select.dark-mode` | Versão para fundo escuro (`label` claro, input dark-mode). | `<div class="br-select dark-mode">` |
| `.input-group` / `.input-icon` + `i.fas.fa-search` | Gerados pelo JS (`_setSearchIcon`) dentro de `.br-input`; ícone de busca à esquerda do input. | (automático) |
| Filtro/busca | Sempre ativo: digitar no input filtra os itens (`_filter`). Não existe atributo `data-search`; a busca é intrínseca ao componente. | (automático) |
| `name` / `value` nos inputs | Obrigatórios nos `radio`/`checkbox`; `value` alimenta a propriedade `selectedValue`. | `<input type="radio" name="uf" value="AC">` |

Ícones Font Awesome 5 usados oficialmente: `fas fa-angle-down` / `fas fa-angle-up` (gatilho), `fas fa-search` (busca, gerado pelo JS), `fas fa-exclamation-triangle` (feedback warning). O documento de design cita `fa-caret-down`/`fa-caret-up`, mas o HTML oficial usa `fa-angle-*`.

## Estados e acessibilidade

- **Instanciação**: `core-init.js` executa `new BRSelect('br-select', el)` para cada `.br-select`. Se usar só `core.min.js`, instancie manualmente: `new core.BRSelect('br-select', el, notFoundHtml?)`.
- **ARIA gerado pelo JS**: `.br-input` recebe `role="combobox"`, `aria-expanded`, `aria-controls="<id da lista>"`, `aria-autocomplete="list"`; `.br-list` recebe `role="listbox"`, `aria-label="Lista de Opções"` e um `id` aleatório se não tiver; cada `.br-item` recebe `role="option"` e `aria-selected="true"` quando selecionado; botão gatilho recebe `aria-controls`, `aria-expanded` e `aria-label` "Exibir lista"/"Ocultar lista". No multiselect, `aria-multiselectable="true"`.
- **No HTML, você deve fornecer**: `label[for]` ligado ao `input`, `aria-label="Exibir lista"` no botão, `tabindex="0"` na `.br-list` e `tabindex="-1"` nos `.br-item`, `name`/`value` nos inputs.
- **Teclado** (input): `ArrowDown`/`ArrowUp` abre a lista e move o foco; `Enter` abre/fecha; `Escape` fecha; `Tab` fecha e segue. (lista): `ArrowUp/ArrowDown` navegam; `Enter` ou `Espaço` selecionam; `Escape` volta o foco ao input e fecha; `Tab` fecha. Clique fora do componente fecha a lista.
- **Evento**: a raiz dispara `CustomEvent('onChange')` a cada seleção; `event.detail` contém o elemento raiz. Ex.: `el.addEventListener('onChange', e => …)`.
- **API**: propriedades `selected` (rótulos) e `selectedValue` (values) — string/`undefined` no simples, array no múltiplo; método `resetOptionsList()` após alterar os itens em tempo de execução.
- **Estados visuais**: foco no input (`--focus`), hover no item, `selected`, `highlighted`, `disabled`, validação via `.br-input.danger|success` + `.feedback`.

## Erros comuns

- Usar `data-multiple` ou `class="multiple"`: o JS só reconhece o atributo `multiple` na raiz `.br-select`.
- Esquecer `data-trigger` no botão: a seta não abre a lista e o ícone não alterna.
- Escrever `div.input-group`/`div.input-icon` manualmente: o JS envolve o input de novo, duplicando o ícone de busca.
- Omitir `tabindex="0"` na `.br-list` ou `tabindex="-1"` nos `.br-item`: quebra a navegação por teclado.
- Usar `br-checkbox` no select simples (ou `br-radio` no múltiplo): a lógica de seleção espera `radio` para simples e `checkbox` para `multiple`.
- Colocar o item "Selecionar todos" sem `data-all` ou fora da primeira posição, ou usar `data-all` no select simples.
- Aninhar o `.br-select` em um container com `overflow: hidden` baixo: a lista é `position:absolute` e será cortada.

## Fonte

- https://www.gov.br/ds/components/select?tab=designer
- https://www.gov.br/ds/components/select?tab=desenvolvedor
- https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/select/select.md
- https://docs-ds.estaleiro.serpro.gov.br/govbr-ds-core/docs/components/select/select-dev.md
- Local: `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/select/examples/select-simples.html`, `select-multiplo.html`, `dist/components/select/select.js`, `src/components/select/_mixins.scss`, `dist/core.css` (verificação das classes).
