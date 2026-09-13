# br-tab

Abas de navegação interna da página (Design System gov.br, @govbr-ds/core 3.7.0). Comportamento em `dist/components/tab/tab.js` (classe `BRTab`), instanciado automaticamente por `core-init.js` para todo `.br-tab`.

## Quando usar / quando não usar

- Use quando houver informação em excesso na página e for preciso organizá-la em categorias ou seções menores, melhorando a usabilidade.
- Rótulo curto e direto: de uma a três palavras. Itens ficam alinhados à esquerda; a superfície (linha divisória) se estende até a borda direita da tela.
- Não coloque `br-tab` dentro de outro `br-tab`; para subdivisões use `br-list`.
- Abas somente com ícone precisam de tooltip (`data-tooltip-text`) e `aria-label` no botão para expor o nome.
- Quando as abas excedem a largura, a navegação rola horizontalmente (swipe); use densidade `small` em espaços restritos e `large` para dar destaque.

## HTML canônico

```html
<div class="br-tab">
  <nav class="tab-nav" aria-label="Seções do serviço">
    <ul role="tablist">
      <li class="tab-item active" title="Sobre" role="presentation">
        <button type="button" role="tab" id="tab-sobre" data-panel="painel-sobre" aria-controls="painel-sobre" aria-selected="true"><span class="name">Sobre</span></button>
      </li>
      <li class="tab-item" title="Documentos" role="presentation">
        <button type="button" role="tab" id="tab-documentos" data-panel="painel-documentos" aria-controls="painel-documentos" aria-selected="false"><span class="name">Documentos</span></button>
      </li>
      <li class="tab-item" title="Contato" role="presentation">
        <button type="button" role="tab" id="tab-contato" data-panel="painel-contato" aria-controls="painel-contato" aria-selected="false"><span class="name">Contato</span></button>
      </li>
    </ul>
  </nav>
  <div class="tab-content">
    <div class="tab-panel active" id="painel-sobre" role="tabpanel" aria-labelledby="tab-sobre">
      <p>Conteúdo da aba Sobre.</p>
    </div>
    <div class="tab-panel" id="painel-documentos" role="tabpanel" aria-labelledby="tab-documentos">
      <p>Conteúdo da aba Documentos.</p>
    </div>
    <div class="tab-panel" id="painel-contato" role="tabpanel" aria-labelledby="tab-contato">
      <p>Conteúdo da aba Contato.</p>
    </div>
  </div>
</div>
```

Estrutura mínima dos exemplos oficiais: `.br-tab > nav.tab-nav > ul > li.tab-item > button[data-panel] > span.name` e `.br-tab > .tab-content > .tab-panel[id]`. Os atributos `role`/`aria-*` acima não constam dos exemplos oficiais (que trazem só `title` no `li`); o JS gerencia apenas `aria-selected`.

## Variantes e modificadores

| Classe/atributo | Efeito | Exemplo |
| --- | --- | --- |
| `br-tab` | Container; define tokens `--tab-padding: var(--spacing-scale-3x)` e `--tab-size` (padding vertical) | `<div class="br-tab">` |
| `tab-nav` | Barra rolável (`overflow-x: auto`, scrollbar customizada); o `ul` interno tem `border-bottom: 1px solid var(--border-color)` e `display: flex` | `<nav class="tab-nav"><ul>…</ul></nav>` |
| `tab-item` | `li` flex centralizado, `white-space: nowrap`; `button`/`a` interno com `font-size: var(--font-size-scale-up-02)`, peso medium, borda inferior de 4px transparente, foco (`focus`) e hover por cor | `<li class="tab-item">` |
| `tab-item.active` ou `tab-item.is-active` | Aba ativa: borda inferior 4px `var(--active)` e texto `var(--active)`; `.results` em semi-bold | `<li class="tab-item active">` |
| `button[data-panel="ID"]` (ou `data-target="ID"`) | Liga o botão ao `.tab-panel#ID`; o JS aceita qualquer dos dois atributos | `<button type="button" data-panel="painel-1">` |
| `span.name` | Rótulo do botão; com ícone use `<span class="name"><span class="d-flex flex-column flex-sm-row"><span class="icon mb-1 mb-sm-0 mr-sm-1"><i class="fas fa-image" aria-hidden="true"></i></span><span class="name">Rótulo</span></span></span>` (ícone acima do texto em telas `xs`, ao lado a partir de `sm`) | ver exemplo `tab-default.html` |
| `data-counter="true"` (no `.br-tab`) + `span.results` | Versão com contadores: `ul` ganha `margin-bottom` extra e cada `.results` (irmão do botão, fora dele) é posicionado abaixo do item em `position: absolute; top: 100%` | `<div class="br-tab" data-counter="true">… <button …><span class="name">Todos</span></button><span class="results">(124)</span>` |
| `tab-content` / `tab-panel` | Painéis `display: none`; `.tab-panel.active` ou `.is-active` fica `display: block` | `<div class="tab-content"><div class="tab-panel active" id="painel-1">` |
| `small` / `[small]` / `is-small` | Densidade alta: padding vertical `--spacing-scale-base` | `<div class="br-tab small">` |
| `medium` / `[medium]` / `is-medium` | Densidade padrão: `--spacing-scale-2x` (igual a omitir) | `<div class="br-tab medium">` |
| `large` / `[large]` / `is-large` | Densidade baixa: `--spacing-scale-3x` | `<div class="br-tab large">` |
| `dark-mode` ou `inverted` | Mixin `dark-mode`; aba ativa com borda `--background-light` e texto `--color` (claro). Use sobre fundo escuro, ex. `bg-gray-60` | `<div class="bg-gray-60 p-3"><div class="br-tab dark-mode">…` |
| Aba só com ícone | `<button type="button" aria-label="Sobre" data-panel="…" data-tooltip-text="Sobre"><span class="name"><i class="fas fa-image" aria-hidden="true"></i></span></button>`; `data-tooltip-text` gera tooltip via utilitário Tooltip do `core-init.js` | ver `tab-icons.html` |
| `not-tab="true"` (no `li.tab-item`) | O JS ignora o item na troca de abas (não recebe listener nem `active`) | `<li class="tab-item" not-tab="true">` |

Ícones Font Awesome 5 usados nos exemplos: `fas fa-image` (com `fa-1x` opcional).

Observação: o SCSS possui um mixin `tab-nav-gradiente` (`.tab-nav-right`/`.tab-nav-left`, sombras laterais) que **não** é incluído em `tab-configs`; o JS adiciona essas classes, mas não há regra correspondente em `core.css` 3.7.0.

## Estados e acessibilidade

- Inicialização automática: `core-init.js` executa `new BRTab('br-tab', el)` para cada `.br-tab`. Com `core.min.js` puro, instancie manualmente: `new core.BRTab('br-tab', document.querySelector('.br-tab'))`.
- O que o JS faz: no `click` de `.tab-nav .tab-item:not([not-tab="true"]) button` marca o `li` como `active` (remove `active`/`is-active` dos demais), define `aria-selected="true"/"false"` em cada botão e mostra o `.tab-panel` cujo `id` casa com `data-panel` (ou `data-target`) do botão. Também mede o `.tab-nav` e grava `--height-nav` e `--right-gradient-nav` como estilos inline.
- Teclado (handler `keyup` no botão): `←`/`→` movem o foco para o botão anterior/seguinte; `Home`/`End` ativam a primeira/última aba; `Espaço` aciona o clique; `Tab` mantém o foco no item atual. `Enter` usa o clique nativo do botão. Ao perder foco (`blur`) o JS esconde todos os `.br-tooltip` da página.
- ARIA recomendada (padrão WAI-ARIA Tabs): `role="tablist"` no `ul`, `role="tab"` + `aria-controls` + `aria-selected` nos botões, `role="tabpanel"` + `aria-labelledby` nos painéis. O JS só mantém `aria-selected`; os demais devem vir no HTML.
- Estado inicial: coloque `active` no `li.tab-item` **e** no `.tab-panel` correspondente; sem isso nenhum painel aparece até o primeiro clique.
- Não há evento customizado disparado pelo `BRTab`; observe o `click` dos botões se precisar reagir.

## Erros comuns

- `id` do painel diferente do `data-panel` do botão: o clique marca a aba mas nenhum conteúdo aparece.
- Esquecer o `ul` dentro de `nav.tab-nav` ou usar `div` no lugar de `li.tab-item`: a borda inferior e o alinhamento flex se perdem.
- Colocar o texto solto dentro do `button` sem `span.name`, ou colocar `span.results` **dentro** do botão (deve ser irmão do botão, dentro do `li`).
- Usar `data-counter` sem o valor `"true"`: a regra CSS é `[data-counter=true]` e o espaço para os contadores não é reservado.
- Aplicar `small`/`large` no `tab-nav` ou nos itens em vez do container `.br-tab`.
- Abas somente com ícone sem `aria-label`/`data-tooltip-text`: o nome da aba fica inacessível.
- Aninhar `br-tab` dentro de `br-tab` (contra a diretriz e confunde o `querySelectorAll` interno de painéis).

## Fonte

- https://www.gov.br/ds/components/tab?tab=designer
- https://www.gov.br/ds/components/tab?tab=desenvolvedor
- https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/tab/tab.md
- https://docs-ds.estaleiro.serpro.gov.br/govbr-ds-core/docs/components/tab/tab-dev.md
- Local: `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/tab/examples.html`, `dist/components/tab/examples/*.html`, `dist/components/tab/tab.js`, `src/components/tab/_mixins.scss`, `dist/core-init.js`, `dist/core.css`
