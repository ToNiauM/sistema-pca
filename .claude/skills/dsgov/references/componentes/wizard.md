# br-wizard

Assistente passo a passo (*Wizard*): painel de etapas + área de conteúdo + barra de navegação (Cancelar / Voltar / Avançar / Concluir). Versão @govbr-ds/core 3.7.0.

## Quando usar / quando não usar

- Use para entrada de informações que devem seguir uma ordem específica, em tarefas complexas divididas em subtarefas e executadas ocasionalmente.
- Use quando etapas seguintes dependem de decisões anteriores; se o usuário puder navegar livremente entre as seções, use `br-tab`.
- Mantenha conteúdo e navegação de cada etapa dentro da área visível; apresente um resumo das escolhas na etapa final antes de "Concluir".
- Botões: Cancelar sempre **terciário**, Voltar sempre **secundário** (oculto na 1.ª etapa), Avançar sempre **primário** e renomeado para **Concluir** na última etapa.
- Use linguagem simples; evite jargão técnico.

## HTML canônico

Wizard horizontal com 3 etapas, iniciando na etapa 1 (`step="1"`), recolhido no mobile (`collapsed`). Cada `wizard-progress-btn` corresponde, pela ordem, a um `wizard-panel`.

```html
<div class="br-wizard" collapsed="collapsed" step="1">
  <div class="wizard-progress" role="tablist">
    <button class="wizard-progress-btn" type="button" role="tab" aria-labelledby="info1" aria-controls="tab1" title="Dados pessoais"><span class="info" id="info1">Dados pessoais</span></button>
    <button class="wizard-progress-btn" type="button" role="tab" aria-labelledby="info2" aria-controls="tab2" title="Endereço"><span class="info" id="info2">Endereço</span></button>
    <button class="wizard-progress-btn" type="button" role="tab" aria-labelledby="info3" aria-controls="tab3" title="Confirmação" disabled="disabled"><span class="info" id="info3">Confirmação</span></button>
  </div>
  <div class="wizard-form">
    <div class="wizard-panel" active="active" role="tabpanel" id="tab1">
      <div class="wizard-panel-content" tabindex="0">
        <div class="h3">Dados pessoais</div>
        <div class="br-input">
          <label for="nome">Nome completo</label>
          <input id="nome" type="text" placeholder="Digite seu nome" />
        </div>
      </div>
      <div class="wizard-panel-btn">
        <button class="br-button wizard-btn-canc" type="button">Cancelar</button>
        <button class="br-button primary wizard-btn-next" type="button" aria-description="Passo 2 de 3 Endereço">Avançar</button>
      </div>
    </div>
    <div class="wizard-panel" role="tabpanel" id="tab2">
      <div class="wizard-panel-content" tabindex="0">
        <div class="h3">Endereço</div>
        <div class="br-input">
          <label for="cep">CEP</label>
          <input id="cep" type="text" placeholder="00000-000" />
        </div>
      </div>
      <div class="wizard-panel-btn">
        <button class="br-button wizard-btn-canc" type="button">Cancelar</button>
        <button class="br-button primary wizard-btn-next" type="button" aria-description="Passo 3 de 3 Confirmação">Avançar</button>
        <button class="br-button secondary wizard-btn-prev" type="button" aria-description="Passo 1 de 3 Dados pessoais">Voltar</button>
      </div>
    </div>
    <div class="wizard-panel" role="tabpanel" id="tab3">
      <div class="wizard-panel-content" tabindex="0">
        <div class="h3">Confirmação</div>
        <p>Revise os dados informados antes de concluir.</p>
      </div>
      <div class="wizard-panel-btn">
        <button class="br-button wizard-btn-canc" type="button">Cancelar</button>
        <button class="br-button primary wizard-btn" type="button">Concluir</button>
        <button class="br-button secondary wizard-btn-prev" type="button" aria-description="Passo 2 de 3 Endereço">Voltar</button>
      </div>
    </div>
  </div>
</div>
```

Observação: no HTML oficial os botões da barra vêm na ordem Cancelar, Avançar, Voltar; o CSS posiciona com `float` (Cancelar à esquerda; Avançar e Voltar à direita, Avançar por último). O componente ocupa `height: 100%` do pai (`min-height: 300px`, `max-height: 800px`), por isso os exemplos oficiais colocam o wizard em um container com altura definida (ex.: `height: 400px`).

## Variantes e modificadores

| Classe / atributo | Efeito | Exemplo |
| --- | --- | --- |
| `.br-wizard` | Raiz (`display:flex; flex-direction:column; height:100%`). Auto-instanciado por `core-init.js`. | `<div class="br-wizard">` |
| `vertical` (atributo na raiz) | Tipo vertical: etapas em coluna à esquerda (`max-width: 260px`), formulário à direita. É **atributo**, não classe (`.br-wizard.vertical` não existe em core.css). | `<div class="br-wizard" vertical="vertical">` |
| `step="N"` (atributo na raiz) | Etapa inicial (1-based). O JS ativa botão e painel correspondentes; sem o atributo nada é ativado além do que vier marcado no HTML. | `step="1"` |
| `collapsed` (atributo na raiz) | Em telas < sm recolhe o painel de etapas (só números, `.info` oculto). O JS alterna com swipe/touch (`collapseSteps()`/`expandSteps()`). | `collapsed="collapsed"` |
| `scroll` (atributo na raiz) | Horizontal: JS redimensiona as colunas do grid (`minmax(100px, …)`) para permitir rolagem horizontal; vertical: `.br-wizard[vertical][scroll] .wizard-progress` recebe rolagem vertical (botão `min-height:100px`). | `scroll="scroll"` |
| `.wizard-progress` | Painel de etapas (grid `auto-fit`, fundo `--background-alternative`, `min-height:164px`). Deve ter `role="tablist"`. No mobile mostra o ícone `grip-lines` (`\f7a4`) via `::after`. | `<div class="wizard-progress" role="tablist">` |
| `.wizard-progress-btn` | Cada etapa; o número vem de `::before{content: attr(step)}` (o JS grava `step`), a linha de `::after`. Use `role="tab"`, `aria-labelledby`, `aria-controls`, `title`. | `<button class="wizard-progress-btn" type="button" role="tab">` |
| `.wizard-progress-btn .info` | Rótulo da etapa; oculto quando `collapsed` em mobile. | `<span class="info" id="info1">Endereço</span>` |
| `.wizard-progress-btn[active]` | Etapa ativa/visitada (número preenchido `--active`, rótulo semi-bold). Nos exemplos oficiais as etapas já visitadas também recebem `active`. | `active="active"` |
| `.wizard-progress-btn[disabled]` | Etapa ainda não acessível. O JS remove `disabled` ao ativar a etapa. | `disabled="disabled"` |
| `.wizard-form` | Container dos painéis (`flex:1; overflow:hidden`). | `<div class="wizard-form">` |
| `.wizard-panel` / `.wizard-panel[active]` | Painel de cada etapa (`display:none`; `[active]` → `display:flex`). Use `role="tabpanel"` e `id` referenciado por `aria-controls`. | `<div class="wizard-panel" active="active" role="tabpanel" id="tab1">` |
| `.wizard-panel-content` | Área de conteúdo com rolagem interna (`overflow:auto`, `border-top`). Use `tabindex="0"`; o JS foca o primeiro elemento focável ao trocar de etapa. | `<div class="wizard-panel-content" tabindex="0">` |
| `.wizard-panel-btn` | Barra de navegação (fundo `--background-alternative`, `border-top`). | `<div class="wizard-panel-btn">` |
| `.wizard-btn-canc` | Botão Cancelar (terciário: `br-button` sem ênfase; `float:left`). Sem comportamento no JS — implemente o cancelamento. | `<button class="br-button wizard-btn-canc" type="button">Cancelar</button>` |
| `.wizard-btn-prev` | Botão Voltar (`br-button secondary`). O JS troca para o painel/etapa anterior. | `<button class="br-button secondary wizard-btn-prev" type="button">Voltar</button>` |
| `.wizard-btn-next` | Botão Avançar (`br-button primary`). O JS troca para o painel/etapa seguinte. | `<button class="br-button primary wizard-btn-next" type="button">Avançar</button>` |
| `.wizard-btn` | Botão Concluir na última etapa (`br-button primary`, mesmo posicionamento do Avançar). Sem comportamento no JS — implemente o envio. | `<button class="br-button primary wizard-btn" type="button">Concluir</button>` |
| `.inverted` / `.dark-mode` (na raiz) | Versão para fundo escuro (painel e barra transparentes, botões dark-mode). | `<div class="br-wizard dark-mode">` |
| Densidade | A diretriz de design descreve alta/média/baixa via tokens de espaçamento, mas core.css não compila classes `small`/`large` para `.br-wizard`. Aplique densidade nos `br-button` e no `br-step` internos. | `<button class="br-button primary small wizard-btn-next">` |

Ícones Font Awesome 5: o painel usa `grip-lines` (`\f7a4`, Font Awesome 5 Free) desenhado pelo CSS no mobile; a diretriz cita `grip-lines-vertical` para o tipo vertical (o CSS rotaciona o mesmo glifo). Os botões oficiais são textuais, sem ícones.

## Estados e acessibilidade

- **Instanciação**: automática via `core-init.js` (`new BRWizard('br-wizard', el)`); manual com `new core.BRWizard('br-wizard', el)`.
- **O que o JS faz**: grava `step="n"` em cada `.wizard-progress-btn`; se a raiz tiver `step`, ativa botão + painel dessa posição; clique em uma etapa (ou em seu `.info`) ativa etapa e painel; clique em `.wizard-btn-prev`/`.wizard-btn-next` move um painel para trás/frente (o painel de origem recebe `style.left` de 1%/-1% para a transição); ao ativar, define `aria-selected="true"` no botão ativo e `"false"` nos demais, remove `disabled` do ativo e foca o primeiro elemento com `tabIndex >= 0` dentro de `.wizard-panel-content`. Em touch, usa o utilitário `Swipe`: horizontal — tocar no painel de etapas expande, tocar no formulário recolhe; vertical — swipe esquerda recolhe, swipe direita expande.
- **ARIA a fornecer no HTML**: `role="tablist"` no `.wizard-progress`; `role="tab"`, `aria-labelledby="<id do .info>"`, `aria-controls="<id do painel>"` e `title` em cada botão de etapa; `role="tabpanel"` e `id` em cada `.wizard-panel`; `tabindex="0"` no `.wizard-panel-content`; `aria-description="Passo N de T <rótulo>"` nos botões Avançar/Voltar (como nos exemplos oficiais).
- **Teclado**: botões nativos — `Tab` percorre etapas habilitadas e botões da barra; `Enter`/`Espaço` aciona. Foco visível no indicador (`::before`) e `focus-soft` na área de conteúdo.
- **Sem eventos customizados**: o componente não dispara `CustomEvent`; escute `click` nos botões `.wizard-btn-next`/`.wizard-btn-prev`/`.wizard-btn`/`.wizard-btn-canc` para validação e envio.
- **Validação**: o JS avança sem validar; se precisar bloquear, intercepte o clique em `.wizard-btn-next` antes (ex.: `disabled` no botão até o formulário ser válido).

## Erros comuns

- Usar `class="vertical"`, `data-vertical`, `data-step` ou `data-collapsed`: o JS/CSS leem os **atributos** `vertical`, `step`, `collapsed`, `scroll` (sem prefixo `data-`).
- Número de `.wizard-progress-btn` diferente do número de `.wizard-panel`: a correspondência é por índice; painéis sobrando ficam inacessíveis ou o clique quebra.
- Colocar `.wizard-btn-prev`/`.wizard-btn-next` fora de um `.wizard-panel`: o JS procura o painel pai (`findParent`) e falha.
- Não dar altura ao container pai: a raiz tem `height:100%` e `min-height:300px`; sem altura definida o conteúdo pode ficar sem rolagem interna e o painel de etapas "salta".
- Escrever o número da etapa dentro do botão: o número já vem de `::before{content: attr(step)}`.
- Esquecer `type="button"`: dentro de `<form>`, Avançar/Voltar submetem o formulário.
- Usar `wizard-btn-next` na última etapa: o JS tentaria ir para um painel inexistente; use `.wizard-btn` (Concluir).

## Fonte

- https://www.gov.br/ds/components/wizard?tab=designer
- https://www.gov.br/ds/components/wizard?tab=desenvolvedor
- https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/wizard/wizard.md
- https://docs-ds.estaleiro.serpro.gov.br/govbr-ds-core/docs/components/wizard/wizard-dev.md
- Local: `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/wizard/examples/wizard-horizontal.html`, `wizard-vertical.html`, `dist/components/wizard/wizard.js`, `src/components/wizard/_mixins.scss`, `dist/core.css`.
