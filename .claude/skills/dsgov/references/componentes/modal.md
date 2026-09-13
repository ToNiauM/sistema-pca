# br-modal

## Quando usar / quando não usar

- **Use** quando for necessário obter a atenção imediata do usuário com uma interrupção proposital do fluxo: erros que impedem o fluxo normal, informações críticas que exigem decisão ou reconhecimento, ou entrada de dados sem perder o contexto da tela.
- **Use** os três tipos previstos: **Alerta** (título opcional, 1 ou 2 botões), **Opção** (lista ou seleção; título altamente recomendado) e **Entrada** (formulário; botão de confirmação desativado até preencher os obrigatórios).
- **Não use** para diálogos longos, pesquisas complexas ou conteúdo que exija consultar outras fontes: prefira *popover* ou *tooltip*. Nunca empilhe duas modais ao mesmo tempo.
- **Não abra** a modal em eventos do sistema (ex.: no carregamento da página); mostre apenas em resposta a uma ação do usuário.
- Máximo de **dois botões**: um de confirmação (primário) e um de negação (secundário). Se houver só um, ele é de conhecimento (primário) ou negação. Evite um terceiro botão "Saiba mais". Evite títulos alarmistas como "Você tem certeza?"; combine título e rótulo do botão ("Excluir foto" / "Excluir").
- Jamais use rolagem horizontal; quando houver rolagem vertical, o título fica fixo no topo e os botões no rodapé.

## HTML canônico

Modal de alerta (variante mais comum), na largura `medium` (500px), com botão terciário de fechar no canto superior direito:

```html
<div class="br-modal medium" role="dialog" aria-modal="true" aria-labelledby="titulo-modal-exclusao">
  <div class="br-modal-header">
    <div class="modal-title" id="titulo-modal-exclusao">Excluir documento</div>
    <button class="br-button close circle" type="button" data-dismiss="br-modal" aria-label="Fechar">
      <i class="fas fa-times" aria-hidden="true"></i>
    </button>
  </div>
  <div class="br-modal-body">
    <p>O documento será removido permanentemente e não poderá ser recuperado.</p>
  </div>
  <div class="br-modal-footer justify-content-end">
    <button class="br-button secondary" type="button">Cancelar</button>
    <button class="br-button primary ml-2" type="button">Excluir</button>
  </div>
</div>
```

Para exibi-la sobre a página com *overlay*, envolva-a no utilitário Scrim (veja `scrim.md`). Exemplo oficial (`dist/components/modal/examples/scrim-behavior.html`):

```html
<div class="br-scrim-util foco" id="scrim-modal-exclusao" data-scrim="true">
  <div class="br-modal medium" aria-labelledby="titulo-modal-exclusao">
    <div class="br-modal-header" id="titulo-modal-exclusao">Excluir documento</div>
    <div class="br-modal-body">
      <p>O documento será removido permanentemente.</p>
    </div>
    <div class="br-modal-footer justify-content-center">
      <button class="br-button secondary" type="button" data-dismiss="true">Cancelar</button>
      <button class="br-button primary mt-3 mt-sm-0 ml-sm-3" type="button">Excluir</button>
    </div>
  </div>
</div>
<button class="br-button primary" type="button" id="abrir-modal-exclusao">Excluir documento</button>

<script src="node_modules/@govbr-ds/core/dist/core.min.js"></script>
<script>
  const scrim = new core.Scrim({
    trigger: document.querySelector('#scrim-modal-exclusao'),
    escEnable: true,
    limitTabKey: true,
  })
  document.querySelector('#abrir-modal-exclusao').addEventListener('click', () => scrim.showScrim())
</script>
```

## Variantes e modificadores

| Classe / atributo | Efeito | Exemplo |
| --- | --- | --- |
| `br-modal` | Container (obrigatório). `display:flex; flex-direction:column; max-width: var(--modal-size)`; fundo `--background`, sombra `--surface-shadow-sm`, `z-index: var(--z-index-layer-4)`. Sem modificador de largura usa `medium`. | `<div class="br-modal">` |
| `br-modal-header` | Cabeçalho; fonte `--font-size-scale-up-01` bold, padding `2x 2x 0`, `position:relative` para posicionar `.close`. Pode carregar o `id` referenciado por `aria-labelledby`. | `<div class="br-modal-header" id="t1">Título</div>` |
| `modal-title` (dentro do header) | Título limitado a ~3 linhas (`max-height: calc(font-size-up-01 * 3)`, `overflow:hidden; text-overflow:ellipsis`) e `margin-right:40px` para não sobrepor o botão fechar. | `<div class="modal-title" id="t1">Título</div>` |
| `br-modal-header .close` | Botão fechar absoluto no canto superior direito (`right/top: --spacing-scale-base`). Use `br-button close circle` + `fas fa-times` + `aria-label="Fechar"`. Em telas < sm o `top` passa a 0. | `<button class="br-button close circle" data-dismiss="br-modal" aria-label="Fechar">` |
| `br-modal-body` | Corpo (obrigatório). `flex:1; overflow:auto; margin: 3x 0 2x; padding: 0 2x`, barra de rolagem estilizada. O scroll aparece automaticamente quando a modal recebe uma altura/`max-height`. | `<div class="br-modal-body">…</div>` |
| `br-modal-body.loading.medium` | Corpo com indicador de carregamento (dependência: componente Loading); `min-height` compatível com o loading indeterminado médio. Variante "Modal com temporizador". | `<div class="br-modal-body loading medium"></div>` |
| `br-modal-footer` | Rodapé `display:flex; flex-wrap:wrap; padding: 2x`. Alinhe os botões com utilitários flex: `justify-content-end` (padrão de design), `justify-content-center` (ação única), `justify-content-around`. | `<div class="br-modal-footer justify-content-end">` |
| `xsmall` / `is-xsmall` | `--modal-size: 220px` | `<div class="br-modal xsmall">` |
| `small` / `is-small` | `--modal-size: 300px` | `<div class="br-modal small">` |
| `medium` / `is-medium` | `--modal-size: 500px` (padrão) | `<div class="br-modal medium">` |
| `large` / `is-large` | `--modal-size: 640px` | `<div class="br-modal large">` |
| `auto` / `is-auto` | `--modal-size: auto` (largura pelo conteúdo) | `<div class="br-modal auto">` |
| `.terms` (dentro da modal) | **Depreciado**. Área de termos com altura fixa 216px, sombra interna e rolagem própria. Mantido no CSS apenas por compatibilidade; o exemplo oficial "termo de aceite" atual usa apenas `br-modal-body` com `max-height` na modal. | — |
| `.br-scrim.foco .br-modal` / `.br-scrim-util.foco .br-modal` | Quando dentro de um scrim de foco, a modal fica `position:absolute; top/left:50%; transform:translate(-50%,-50%); max-height:90%; overflow:auto; z-index:1000`. | ver HTML canônico |
| `role="dialog"` + `aria-modal="true"` | Semântica de diálogo modal. Obrigatórios. Quando aberta via utilitário Scrim eles são inseridos automaticamente no primeiro filho do scrim. | — |
| `aria-labelledby="id"` / `aria-label` | Aponta para o título (`modal-title` ou o próprio `br-modal-header`). Modal sem título usa `aria-label` e opcionalmente `aria-describedby` apontando para o `br-modal-body`. | `<div class="br-modal" aria-label="Carregando conteúdo">` |
| `data-dismiss="br-modal"` | Atributo usado nos exemplos oficiais no botão fechar. **Não há JS no core que trate esse valor**: é apenas um gancho para o seu código. O fechamento automático só acontece com `data-dismiss="true"` (utilitário Scrim) ou `data-dismiss="<id-do-scrim>"` (classe BRScrim). | — |

Não existem modificadores `inverted`/`dark-mode`, `primary`/`secondary` ou de densidade para `br-modal` no `core.css` 3.7.0. As classes `br-modal-dialog` e `br-modal-content`, que aparecem em alguns exemplos antigos de Scrim, **não têm regra alguma no CSS** e podem ser omitidas.

## Estados e acessibilidade

- **Semântica**: `role="dialog"` e `aria-modal="true"` no `br-modal`; `aria-labelledby` para o título ou `aria-label` quando não há título; `aria-describedby` opcional para o corpo. Botão fechar com `aria-label="Fechar"` e ícone `aria-hidden="true"`.
- **JS do componente**: `dist/components/modal/modal.js` (`BRModal`) apenas instancia `BRScrim` para todos os `.br-scrim` e liga o botão irmão `.br-scrim + button` a `showScrim()`. O `core-init.js` **não** instancia `BRModal` para `.br-modal` (o `initInstanceModal` só trata o exemplo `#buttonactivatemodal`). Ou seja: **a modal em si é CSS puro; abrir/fechar é responsabilidade do utilitário Scrim**.
- **Abrir/fechar com o utilitário Scrim (recomendado)**: envolva a modal em `<div class="br-scrim-util foco" id="…" data-scrim="true">` e crie `new core.Scrim({ trigger, closeElement?, escEnable: true, limitTabKey: true })`. `showScrim()` adiciona `.active` ao scrim, coloca `aria-modal="true"`, `role="dialog"` e `data-visible="true"` no primeiro filho e move o foco para o primeiro elemento focável; `hideScrim()` remove `.active` e grava `data-visible="false"`. Fecha ao clicar em elementos com `data-dismiss="true"`, no seletor `closeElement`, com **Esc** (`escEnable`) ou clicando no fundo (elemento com `data-scrim`). `limitTabKey: true` prende a navegação por **Tab** dentro da modal.
- **Alternativa com `core.BRScrim('br-scrim', el)`**: exige `<div class="br-scrim foco" id="X">`; fecha ao clicar no fundo (`event.target` com classe `br-scrim`) ou em elementos com `data-dismiss="X"`. Não trata Esc nem prende o Tab. É essa a classe que o `core-init.js` instancia automaticamente para cada `.br-scrim` — mas ninguém chama `showScrim()` por você: você precisa chamar `instancia.showScrim()` ou adicionar `.active`.
- **Teclado**: Tab/Shift+Tab entre botões e campos; Esc fecha quando `escEnable`. Sem o Scrim, garanta você mesmo o retorno de foco ao acionador ao fechar.
- **Estado do botão de confirmação**: em modal de entrada, mantenha `disabled` até os campos obrigatórios serem preenchidos (exemplo oficial: `<button class="br-button primary ml-2" disabled>Finalizar</button>`).
- **Dependências**: `br-button` (rodapé e fechar), Loading (`.loading`), Font Awesome 5 (`fas fa-times`).

## Erros comuns

- Esquecer a classe de largura e esperar outro tamanho: sem `xsmall|small|medium|large|auto` a modal usa `medium` (500px); larguras são `max-width`, então em telas estreitas ela encolhe.
- Colocar o botão `.close` fora de `br-modal-header`: o posicionamento absoluto depende do `position:relative` do header. Também não esquecer `modal-title` quando há botão fechar, pois é ele que reserva `margin-right:40px`.
- Usar `br-modal` sem scrim e esperar que ela "flutue" centralizada: a centralização (`position:absolute; translate(-50%,-50%)`) só existe dentro de `.br-scrim.foco`/`.br-scrim-util.foco`. Fora disso ela é um bloco normal no fluxo.
- Achar que `data-dismiss="br-modal"` fecha algo: o JS só reage a `data-dismiss="true"` (utilitário `Scrim`) ou `data-dismiss="<id do scrim>"` (`BRScrim`).
- Colocar `id` do título em um elemento e `aria-labelledby` apontando para outro; ou omitir `role="dialog"`/`aria-modal` quando não usa o utilitário Scrim (que os insere automaticamente).
- Alinhar botões com CSS próprio em vez das utilidades `justify-content-end|center|around` no `br-modal-footer`, ou colocar mais de dois botões.

## Fonte

- https://www.gov.br/ds/components/modal?tab=designer
- https://www.gov.br/ds/components/modal?tab=desenvolvedor
- https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/modal/modal.md (designer)
- https://docs-ds.estaleiro.serpro.gov.br/govbr-ds-core/docs/components/modal/modal-dev.md (desenvolvedor)
- https://docs-ds.estaleiro.serpro.gov.br/govbr-ds-core/docs/utilitarios/js/scrim/scrim-dev.md (utilitário Scrim)
- Local: `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/modal/examples.html`, `dist/components/modal/examples/*.html`, `dist/components/modal/modal.js`, `dist/partial/js/behavior/scrim.js`, `dist/core-init.js`, `src/components/modal/_mixins.scss`, `dist/core.css`
