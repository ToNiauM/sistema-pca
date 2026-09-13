# br-step

Indicador de etapas e progresso (*Steps*) para fluxos passo a passo. Versão @govbr-ds/core 3.7.0.

## Quando usar / quando não usar

- Use quando houver etapas sequenciais em um fluxo e for preciso mostrar ao usuário o progresso (etapas concluídas, em andamento, pendentes) e o tamanho da jornada.
- Use o **Step Complexo** (padrão, com rótulos) em *wizards*; o **Step Simples** (`data-type="simple"`, bolinhas) dentro de carrosséis, cards e modais, com 4 a 5 etapas no máximo; o **Step Textual** (`data-type="text"`, "3/5") quando o número de etapas for grande.
- Na grid de 12 colunas use horizontal ou vertical; nas grids de 8 e 4 colunas prefira a orientação **vertical** ou, se horizontal, no máximo 4 etapas visíveis com `data-scroll`.
- Progressão linear: mantenha as etapas não visitadas com `disabled`; não linear: todas interativas.
- Não use quando não houver sequência de progressão (use Menu ou Tab) nem quando as etapas não tiverem relação entre si.

## HTML canônico

Step horizontal com rótulo acima do indicador (`data-label="top"`), quatro etapas, iniciando na etapa 2, com estados de alerta:

```html
<nav class="br-step" data-initial="2" data-label="top" data-scroll="data-scroll" role="none">
  <div class="step-progress" role="listbox" aria-orientation="horizontal" aria-label="Lista de Opções">
    <button class="step-progress-btn" role="option" aria-posinset="1" aria-setsize="4" type="button" data-alert="success">
      <span class="step-info">Acesse sua conta</span><span class="step-alert"></span>
    </button>
    <button class="step-progress-btn" role="option" aria-posinset="2" aria-setsize="4" type="button" data-alert="info">
      <span class="step-info">Dados da entrega</span><span class="step-alert"></span>
    </button>
    <button class="step-progress-btn" role="option" aria-posinset="3" aria-setsize="4" type="button" data-alert="danger">
      <span class="step-info">Dados de pagamento</span><span class="step-alert"></span>
    </button>
    <button class="step-progress-btn" role="option" aria-posinset="4" aria-setsize="4" type="button" disabled="disabled" data-alert="warning">
      <span class="step-info">Finalizar</span><i class="step-icon fas fa-check" aria-hidden="true"></i><span class="step-alert"></span>
    </button>
  </div>
</nav>
```

Forma mínima (sem alertas, rótulo abaixo):

```html
<nav class="br-step" data-initial="1" data-label="bottom" role="none">
  <div class="step-progress" role="listbox" aria-orientation="horizontal" aria-label="Lista de Opções">
    <button class="step-progress-btn" role="option" aria-posinset="1" aria-setsize="3" type="button"><span class="step-info">Dados pessoais</span></button>
    <button class="step-progress-btn" role="option" aria-posinset="2" aria-setsize="3" type="button"><span class="step-info">Endereço</span></button>
    <button class="step-progress-btn" role="option" aria-posinset="3" aria-setsize="3" type="button"><span class="step-info">Confirmação</span></button>
  </div>
</nav>
```

## Variantes e modificadores

| Classe / atributo | Efeito | Exemplo |
| --- | --- | --- |
| `.br-step` | Raiz (`display:flex; padding: var(--spacing-scale-base)`). Auto-instanciado por `core-init.js`. Use `<nav role="none">`. | `<nav class="br-step" role="none">` |
| `.step-progress` | Container das etapas (`display:flex; flex-grow:1`). Deve ter `role="listbox"`, `aria-orientation`, `aria-label`. | `<div class="step-progress" role="listbox" aria-orientation="horizontal">` |
| `.step-progress-btn` | Cada etapa (`<button type="button">`). O número do indicador é desenhado por `::before { content: attr(step-num) }`; o JS grava `step-num`. Linha do tempo pelo `::after`. | `<button class="step-progress-btn" role="option" aria-posinset="1" aria-setsize="3" type="button">` |
| `.step-info` | Rótulo textual da etapa (`--font-size-scale-up-01`, `--font-weight-medium`). Oculto em `data-type="void|simple|text"` e em telas < sm quando `data-label="left|right"`. | `<span class="step-info">Endereço</span>` |
| `.step-icon` + `fas fa-*` | Indicador icônico em vez de número. Quando existe, o JS grava `step-num=""`. Exemplos oficiais: `fas fa-lock`, `fas fa-truck`, `far fa-credit-card`, `fas fa-check`. | `<i class="step-icon fas fa-check" aria-hidden="true"></i>` |
| `.step-alert` | Badge circular de estado no canto do indicador; o ícone vem do CSS (`::after` com Font Awesome: check, exclamation-triangle, info, times). Exige `data-alert` no botão. | `<span class="step-alert"></span>` |
| `data-alert="success|info|warning|danger"` (no botão) | Colore rótulo/indicador e o `.step-alert` com a cor do estado. `warning` usa texto escuro. | `data-alert="danger"` |
| `.vertical` (na raiz) | Orientação vertical (`flex-direction: column`); combine com `aria-orientation="vertical"` e `data-label="left|right"`. | `<nav class="br-step vertical" data-label="right">` |
| `data-label="top|bottom|left|right"` | Posição do rótulo em relação ao indicador. `top` = rótulo acima, linha abaixo; `bottom` = rótulo abaixo; `left|right` = rótulo lateral (escondido abaixo de sm no horizontal). | `data-label="bottom"` |
| `data-type="void"` | Indicador vazio (bolinha 16 px, sem número); rótulo oculto. Use `data-tooltip-text` para expor o rótulo. | `<nav class="br-step" data-type="void">` |
| `data-type="simple"` | Step simples: bolinhas cinzas de 8 px, sem linha, centralizado (`--step-simple-size`). | `data-type="simple"` |
| `data-type="text"` | Step textual: só a etapa ativa aparece como "n/total" (o JS grava `step-num="3/5"`). Cursor default. | `data-type="text"` |
| `data-initial="N"` | Etapa ativa inicial (1-based). Sem o atributo, o JS ativa a etapa 1. | `data-initial="2"` |
| `data-scroll` (ou `scroll`) | Rolagem horizontal (`overflow-x:auto`, botão `min-width:200px`); no `.vertical`, rolagem vertical (`min-height:100px`). Use quando a largura/altura for fixa. | `data-scroll="data-scroll"` |
| `data-tooltip-text="…"` (no botão) | Texto de tooltip para tipos sem rótulo visível (usado nos exemplos oficiais de `void`, `simple`, `text`). | `data-tooltip-text="Endereço"` |
| `.active` / `[active]` (no botão) | Etapa ativa (indicador preenchido com `--active`). O JS gerencia via atributo `active`. | `<button class="step-progress-btn" active>` |
| `disabled` (no botão) | Etapa desabilitada (borda e ícone com opacidade `--disabled`). | `disabled="disabled"` |
| `.inverted` / `.dark-mode` (na raiz) | Versão para fundo escuro (cores `*-alternative`, indicador ativo claro). | `<nav class="br-step dark-mode">` |
| Densidade | Tokens `--step-small: 32px`, `--step-medium: 40px` (padrão), `--step-large: 48px` definidos em `--step-size`; não há classe `small`/`large` compilada para `.br-step` em core.css — ajuste sobrescrevendo `--step-size`. | `style="--step-size: var(--step-small)"` |

## Estados e acessibilidade

- **Instanciação**: automática via `core-init.js` (`new BRStep('br-step', el)`); manual com `new core.BRStep('br-step', el)`.
- **O que o JS faz**: grava `step-num` em cada botão (número, "" se houver `.step-icon`, ou "n/total" em `data-type="text"`); ativa a etapa de `data-initial` (ou 1) com `active=""` e `aria-current="step"`, removendo `disabled` dela; ao clicar em uma etapa (ou em um filho dela) troca `active`/`aria-current`. Não emite eventos customizados nem gerencia painéis de conteúdo (isso é papel do `br-wizard`).
- **ARIA a fornecer no HTML**: `role="none"` no `<nav>`, `role="listbox"` + `aria-orientation="horizontal|vertical"` + `aria-label` no `.step-progress`, `role="option"` + `aria-posinset` + `aria-setsize` em cada botão, `aria-hidden="true"` nos ícones. O JS acrescenta `aria-current="step"` no ativo.
- **Teclado**: os botões são `<button>` nativos — `Tab` percorre as etapas habilitadas, `Enter`/`Espaço` ativa. Foco visível pelo `::before` (`--focus`). Etapas `disabled` ficam fora da tabulação.
- **Estados visuais**: interativo, hover (`--hover` sobre o indicador), foco, ativo (`--active`), desabilitado, e os alertas `success|info|warning|danger` (com `.step-alert`). Quando a etapa com alerta é a ativa em `data-type="void"`, o badge recebe borda na cor ativa.

## Erros comuns

- Escrever o número dentro do botão: o número vem de `::before{content: attr(step-num)}`; texto manual duplica o indicador.
- Usar `.step-alert` sem `data-alert` no botão (ou vice-versa): o badge fica sem cor/ícone, ou o estado fica sem badge.
- Usar `data-vertical` ou `vertical` como atributo: a orientação vertical é a **classe** `vertical` na raiz.
- Usar `data-label="left|right"` em horizontal sem prever que o rótulo desaparece abaixo de 576 px.
- Esquecer `data-scroll` ao fixar a largura com muitas etapas: os botões encolhem e os rótulos se sobrepõem.
- Omitir `type="button"` nos botões dentro de `<form>`: submete o formulário ao trocar de etapa.

## Fonte

- https://www.gov.br/ds/components/step?tab=designer
- https://www.gov.br/ds/components/step?tab=desenvolvedor
- https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/step/step.md
- https://docs-ds.estaleiro.serpro.gov.br/govbr-ds-core/docs/components/step/step-dev.md
- Local: `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/step/examples/*.html` (step-horizontal, step-vertical, step-alert, step-icon, step-simple, step-text, step-void), `dist/components/step/step.js`, `src/components/step/_mixins.scss`, `dist/core.css`.
