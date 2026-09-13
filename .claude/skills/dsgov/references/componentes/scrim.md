# br-scrim

## Quando usar / quando não usar

- **Use** para tornar uma superfície temporariamente menos proeminente e redirecionar a atenção do usuário. Três tipos: **Foco** (overlay preto 40% em tela cheia, destaca um elemento novo como a modal), **Legibilidade** (overlay preto 64% atrás de um texto sobre imagem/superfície sem contraste suficiente) e **Inibição** (overlay com a cor de fundo predominante, 64%, simulando área desativada).
- Podem coexistir vários scrims de tipos diferentes na mesma tela; pode ser aplicado a um elemento inteiro, parcialmente ou à tela toda (inclusive "scrim vazado" com fresta de destaque).
- **Não use** inibição em áreas pequenas ou componentes isolados: prefira o estado `disabled` real, pois os elementos sob o scrim não ficam realmente desativados.
- **Cuidado**: não bloqueie com scrim a busca nem a área de acessibilidade sem justificativa forte.

## HTML canônico

Scrim de **foco** envolvendo uma modal, usando o utilitário JS `Scrim` (exemplo oficial `dist/util/scrim/examples/scrim-behavior.html`, simplificado para as classes que existem no CSS):

```html
<div class="br-scrim-util foco" id="scrim-confirmacao" data-scrim="true">
  <div class="br-modal medium" aria-labelledby="titulo-scrim-confirmacao">
    <div class="br-modal-header">
      <div class="modal-title" id="titulo-scrim-confirmacao">Confirmar envio</div>
    </div>
    <div class="br-modal-body">
      <p>Deseja enviar a solicitação para análise?</p>
    </div>
    <div class="br-modal-footer justify-content-center">
      <button class="br-button secondary" type="button" data-dismiss="true">Cancelar</button>
      <button class="br-button primary mt-3 mt-sm-0 ml-sm-3" type="button">Enviar</button>
    </div>
  </div>
</div>
<button class="br-button primary" type="button" id="abrir-scrim-confirmacao">Enviar solicitação</button>

<script src="node_modules/@govbr-ds/core/dist/core.min.js"></script>
<script>
  const scrim = new core.Scrim({
    trigger: document.querySelector('#scrim-confirmacao'),
    escEnable: true,      // Esc fecha
    limitTabKey: true,    // Tab preso dentro do scrim
  })
  document.querySelector('#abrir-scrim-confirmacao').addEventListener('click', () => scrim.showScrim())
</script>
```

Legibilidade (sem JS):

```html
<div class="br-scrim legibilidade">
  <img src="foto.jpg" alt="Fachada do prédio"/>
  <div class="scrim-text">Legenda sobre a imagem</div>
</div>
```

Inibição (sem JS):

```html
<div class="br-scrim inibicao">
  <!-- conteúdo visualmente inibido -->
</div>
```

## Variantes e modificadores

| Classe / atributo | Efeito | Exemplo |
| --- | --- | --- |
| `br-scrim` | Container do componente. Sozinho não tem estilo: **deve** vir com um tipo (`foco`, `legibilidade` ou `inibicao`). | `<div class="br-scrim foco">` |
| `br-scrim-util` | Mesmas regras CSS de `br-scrim` (mixin idêntico). É a classe usada nos exemplos do **utilitário JS** `Scrim`, evitando que o `core-init.js` instancie também a classe `BRScrim` sobre o mesmo elemento. | `<div class="br-scrim-util foco" data-scrim="true">` |
| `foco` | Overlay fixo em tela cheia (`position:fixed; inset:0; background: var(--surface-overlay-scrim); z-index:999`), `display:none` até receber `active`. Centraliza um `.br-modal` filho (`position:absolute; top/left:50%; translate(-50%,-50%); max-height:90%; overflow:auto; z-index:1000`). | `<div class="br-scrim foco active">` |
| `active` (com `foco`) | Torna o scrim visível (`display:block`). Adicionado/removido pelo JS (`showScrim`/`hideScrim`). | — |
| `legibilidade` | `position:relative` no container; o filho `.scrim-text` fica absoluto no rodapé (`bottom:0; left:0; width:100%`), fundo `var(--surface-overlay-text)`, padding `3x baseh`. | `<div class="br-scrim legibilidade"><img…/><div class="scrim-text">…</div></div>` |
| `scrim-text` | Bloco de texto do tipo legibilidade (obrigatório para posicionar o texto). | ver acima |
| `inibicao` | `position:relative` e pseudo-elemento `::before` cobrindo 100% com `var(--surface-overlay-scrim)`, simulando área desativada. | `<div class="br-scrim inibicao">…</div>` |
| `data-scrim="true"` | **Obrigatório para o utilitário `Scrim`**: marca o elemento de fundo; clique em um alvo com `data-scrim` chama `hideScrim()`. | `<div class="br-scrim-util foco" data-scrim="true">` |
| `data-dismiss="true"` | Elemento interno que fecha o scrim ao ser clicado (utilitário `Scrim`). | `<button data-dismiss="true">Cancelar</button>` |
| `data-dismiss="<id do scrim>"` | Fecha o scrim quando se usa a classe de componente `BRScrim` (`new core.BRScrim('br-scrim', el)`), que também fecha ao clicar no fundo. | `<div class="br-scrim foco" id="ex1">… <button data-dismiss="ex1">` |
| `data-visible="true|false"` | Gerado automaticamente pelo utilitário `Scrim` (visibilidade); não precisa ser escrito à mão. | — |
| `aria-modal="true"` + `role="dialog"` | Inseridos automaticamente pelo utilitário `Scrim` no primeiro filho do scrim ao abrir; documente-os também no HTML quando não usar o utilitário. | — |
| `data-trigger="scrim"` | Aparece nos exemplos oficiais de `br-scrim foco`, mas **nenhum JS do core lê esse atributo** na 3.7.0. Inócuo. | — |

Não há variantes `inverted`/`dark-mode`, densidade ou ênfase para scrim. `.br-modal-dialog`/`.br-modal-content` dos exemplos antigos não têm CSS.

## Estados e acessibilidade

- **Duas implementações JS**, ambas exportadas em `core.min.js`:
  1. **Utilitário `core.Scrim({ trigger, closeElement, escEnable, limitTabKey })`** (`dist/partial/js/behavior/scrim.js`) — recomendado para modais. `showScrim()` adiciona `active`, define `aria-modal="true"`, `role="dialog"` e `data-visible="true"` no primeiro filho, e foca o primeiro elemento com `tabIndex >= 0`; `hideScrim()` remove `active` e grava `data-visible="false"`. Fecha por clique em `[data-dismiss=true]`, no seletor `closeElement`, no fundo (`[data-scrim]`) e com **Esc** se `escEnable: true`. `limitTabKey: true` redireciona qualquer `focusin` externo de volta ao primeiro focável interno (foco preso). **Não é auto-instanciado** pelo `core-init.js` (só no exemplo `#buttonactivatemodal`).
  2. **Componente `core.BRScrim('br-scrim', el)`** (`dist/components/scrim/scrim.js`) — auto-instanciado pelo `core-init.js` para cada `.br-scrim`. Reconhece o tipo pela classe (`foco|legibilidade|inibicao`); só o tipo `foco` tem comportamento: clique no próprio fundo (`event.target` com classe `br-scrim`) ou em `[data-dismiss=<id>]` remove `active`; `showScrim()` adiciona `active`. Não trata Esc, foco nem Tab.
- **Sem JS**: basta alternar a classe `active` no `.br-scrim.foco` (documentação oficial mostra `scrim.classList.add('active')` / `remove('active')`).
- **Teclado/foco**: com o utilitário, Esc fecha e o Tab fica contido; ao fechar, o foco **não** retorna sozinho ao acionador — faça `botao.focus()` no seu código. Sem o utilitário nada disso existe.
- **ARIA** no conteúdo destacado: `role="dialog"`, `aria-modal="true"` e `aria-labelledby`/`aria-label` (ver `modal.md`).
- **Dependências**: nenhuma (o conteúdo interno costuma ser `br-modal`).

## Erros comuns

- `br-scrim` sem o tipo (`foco`, `legibilidade`, `inibicao`): não há estilo algum.
- Esquecer `data-scrim="true"` ao usar `core.Scrim`: o clique no fundo deixa de fechar. Ou usar `data-dismiss="true"` com `BRScrim` (que espera `data-dismiss="<id>"`) e vice-versa.
- Usar `br-scrim` (em vez de `br-scrim-util`) junto com `core.Scrim` numa página com `core-init.js`: o elemento recebe também um `BRScrim` automático; normalmente funciona, mas os dois handlers de clique no fundo coexistem. Os exemplos oficiais usam `br-scrim-util` justamente para isso.
- Achar que o scrim abre sozinho: nada no core chama `showScrim()` por você; ligue o acionador manualmente ou adicione `active`.
- Tipo legibilidade sem `scrim-text` (texto não posiciona) ou container sem conteúdo dimensionado (o `position:relative` precisa de um filho com tamanho, ex.: `<img>`).
- Colocar `.active` fixo no HTML: a modal aparece aberta no carregamento (contra a diretriz de só abrir por ação do usuário).

## Fonte

- https://www.gov.br/ds/components/scrim?tab=designer
- https://www.gov.br/ds/components/scrim?tab=desenvolvedor
- https://www.gov.br/ds/utilitarios/js/scrim (utilitário JS)
- https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/scrim/scrim.md
- https://docs-ds.estaleiro.serpro.gov.br/govbr-ds-core/docs/components/scrim/scrim-dev.md
- https://docs-ds.estaleiro.serpro.gov.br/govbr-ds-core/docs/utilitarios/js/scrim/scrim-dev.md
- Local: `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/scrim/examples.html`, `dist/components/scrim/examples/*.html`, `dist/util/scrim/examples.html`, `dist/components/scrim/scrim.js`, `dist/partial/js/behavior/scrim.js`, `dist/core-init.js`, `src/components/scrim/_mixins.scss`, `dist/core.css`
