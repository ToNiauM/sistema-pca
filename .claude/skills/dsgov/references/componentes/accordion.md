# br-accordion

> Verificado no @govbr-ds/core **3.7.0**: o accordion continua sendo um componente próprio (`.br-accordion`, classe JS `BRAccordion`, arquivo `dist/components/accordion/`). O padrão alternativo "lista expansível" (`.br-list` + `.br-item[data-toggle="collapse"]`) existe em paralelo e está documentado em `list.md`; não substitui o `br-accordion`.

## Quando usar / quando não usar
- Use em conteúdos extensos, especialmente em dispositivos móveis, para diminuir a densidade de informação exibida de uma vez.
- Cada seção tem cabeçalho clicável (toda a área do cabeçalho é acionável) e conteúdo que expande/recolhe; por padrão várias seções podem ficar abertas ao mesmo tempo.
- Use o atributo `single` quando a regra de negócio exigir apenas uma seção aberta por vez.
- Evite accordion dentro de accordion (má prática de UX segundo a documentação oficial).
- Não use para navegação principal (use `br-menu`) nem para agrupar campos de formulário obrigatórios que o usuário precisa ver sempre.

## HTML canônico
```html
<div class="br-accordion" id="accordion-servicos">
  <div class="item">
    <button class="header" type="button" aria-controls="acc-conteudo-1" aria-expanded="false">
      <span class="icon"><i class="fas fa-angle-down" aria-hidden="true"></i></span>
      <span class="title">Assuntos</span>
    </button>
  </div>
  <div class="content" id="acc-conteudo-1">
    Texto do primeiro painel. Pode conter parágrafos, listas e links.
  </div>
  <div class="item">
    <button class="header" type="button" aria-controls="acc-conteudo-2" aria-expanded="false">
      <span class="icon"><i class="fas fa-angle-down" aria-hidden="true"></i></span>
      <span class="title">Serviços</span>
    </button>
  </div>
  <div class="content" id="acc-conteudo-2">
    Texto do segundo painel.
  </div>
  <div class="item">
    <button class="header" type="button" aria-controls="acc-conteudo-3" aria-expanded="false">
      <span class="icon"><i class="fas fa-angle-down" aria-hidden="true"></i></span>
      <span class="title">Canais de atendimento</span>
    </button>
  </div>
  <div class="content" id="acc-conteudo-3">
    Texto do terceiro painel.
  </div>
</div>
```

## Variantes e modificadores
| classe/atributo | efeito | exemplo |
| --- | --- | --- |
| `.br-accordion` | raiz; fundo `--bg-color`, borda superior 1px e borda inferior por item | `<div class="br-accordion">` |
| `.item` | container do cabeçalho de uma seção (`display:flex; flex-direction:column`) | `<div class="item">` |
| `.item[active]` | seção aberta: título em semi-bold, remove borda inferior e exibe o `.content` **irmão seguinte** (`.item[active] + .content { display:block }`) | `<div class="item" active>` |
| `button.header` | acionador; ocupa 100% da largura, cor `--interactive`, hover/focus do DS | `<button class="header" type="button">` |
| `.header .icon` | wrapper do ícone Font Awesome (margem direita 2x) | `<span class="icon"><i class="fas fa-angle-down"></i></span>` |
| `.header .title` | texto do cabeçalho (`flex:1; margin:0`) | `<span class="title">…</span>` |
| `.content` | painel; `display:none` por padrão, padding `base 8x 2x` | `<div class="content" id="…">` |
| `[single]` (na raiz) | comportamento exclusivo: abrir um item fecha os demais | `<div class="br-accordion" single="single">` |
| `[negative]` (na raiz) | tema escuro (mixin `dark-mode`, `--bg-color: var(--background-dark)`) | `<div class="br-accordion" negative="negative">` |
| `fas fa-angle-down` / `fas fa-angle-up` | ícones fechado/aberto; o JS troca a classe do **primeiro filho** de `.icon` | ver HTML canônico |

Não existem variantes de densidade (`small/large`), `block`, `circle` ou `is-invalid` para este componente no SCSS 3.7.0.

## Estados e acessibilidade
- **Auto-init**: `core-init.js` executa `new BRAccordion('br-accordion', el)` para cada `.br-accordion`. Se você carrega apenas `core.js`, instancie manualmente: `new core.BRAccordion('br-accordion', document.querySelector('.br-accordion'))`.
- O JS escuta `click` em todo `button.header` dentro da raiz, alterna o atributo `active` no `.item` pai do botão (`event.currentTarget.parentNode`) e troca `fa-angle-down` ⇄ `fa-angle-up` em `.icon > :first-child`.
- Com `single` na raiz, ao abrir um item o JS remove `active` dos demais `.item`.
- Estado inicial aberto: coloque `active` no `.item` (o JS respeita e alterna a partir dele). O `.content` não usa `hidden`; a visibilidade é 100% CSS via o seletor irmão.
- **ARIA**: os exemplos oficiais trazem `aria-controls="<id do .content>"` no botão. O JS **não** gerencia `aria-expanded`; adicione `aria-expanded="false"` e atualize por conta própria (ou aceite a lacuna). Marque o `<i>` com `aria-hidden="true"`. Fase 28/Plano 28-08 (pca-cfc) — `dsgov.js` cobre a lacuna com um listener em `document` (bubbling, roda depois do clique já ter alternado `active`) que sincroniza `aria-expanded` de todo `button.header` do MESMO `.br-accordion` a cada clique, inclusive no modo `single`.
- **Teclado**: por ser `<button type="button">`, Enter/Espaço acionam nativamente; Tab percorre os cabeçalhos. Foco visível vem do mixin `focus` do DS (`outline`), não remova.
- Estados visuais: padrão, hover (fundo azul translúcido no cabeçalho), ativo (semi-bold + `angle-up`), foco.

## Erros comuns
- Colocar o `.content` **dentro** do `.item`: o CSS depende do seletor `.item[active] + .content`; o painel precisa ser irmão imediato do `.item`.
- Usar `<div class="header">` em vez de `<button class="header" type="button">`: o JS só faz `querySelectorAll('button.header')`; divs não recebem o clique nem são focáveis.
- Esquecer `type="button"` dentro de um `<form>`: o clique submete o formulário.
- Trocar o ícone por outro par (`fa-chevron-*`, `fa-plus/minus`): o JS remove/adiciona apenas `fa-angle-down`/`fa-angle-up`; use exatamente esses.
- Colocar o `<i>` diretamente em `.header` sem o `<span class="icon">`: o JS acessa `.icon` → `children[0]`; sem o wrapper lança erro e o accordion inteiro para de funcionar.
- Esperar animação/transição: em 3.7.0 é `display:none/block` sem transição.

## Fonte
- https://www.gov.br/ds/components/accordion?tab=designer (SPA; conteúdo lido no markdown bruto https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/accordion/accordion.md)
- https://www.gov.br/ds/components/accordion?tab=desenvolvedor (SPA sem conteúdo estático; markup obtido dos exemplos locais)
- `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/accordion/examples.html`
- `/opt/web/pca/node_modules/@govbr-ds/core/src/components/accordion/_accordion.scss`
- `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/accordion/accordion.js`, `dist/core-init.js`
