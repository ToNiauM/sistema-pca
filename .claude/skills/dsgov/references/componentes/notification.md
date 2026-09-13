# br-notification

## Quando usar / quando não usar

- **Use** para agrupar e informar o usuário sobre eventos e informações relevantes do sistema (alertas, mensagens), organizados **cronologicamente** (mais recentes no topo, "timeline infinita").
- **Use** como elemento flutuante (*dropdown*) acionado por interação do usuário, tipicamente pelo avatar/ícone de sino com *badge* no header; nunca como bloco fixo no fluxo da página.
- Em grids de 12 e 8 colunas ocupe no máximo **50% da largura** de conteúdo e nunca mais que a área visível; use rolagem interna apenas nos itens, mantendo área do usuário e tabs estáticas.
- Em grid de 4 colunas (mobile) ocupa a tela inteira; nesse caso o **botão fechar é obrigatório** e a rolagem interna deve ser evitada (use a rolagem nativa).
- **Não use** para mensagens de feedback contextual de formulário (use `br-message`) nem para uma única mensagem transitória.

## HTML canônico

Exemplo oficial (`dist/components/notification/examples.html`), com área do usuário, botão fechar e duas abas (alertas e mensagens):

```html
<div class="br-notification">
  <div class="notification-header">
    <div class="row">
      <div class="col-10">
        <span class="text-bold">Fulano da Silva</span><br/>
        <small>nome.sobrenome@dominio.gov</small>
      </div>
      <div class="col-2">
        <div class="close text-right">
          <button class="br-button circle small" type="button" aria-label="Fechar">
            <i class="fas fa-times" aria-hidden="true"></i>
          </button>
        </div>
      </div>
    </div>
  </div>
  <div class="notification-body">
    <div class="br-tab">
      <nav class="tab-nav">
        <ul>
          <li class="tab-item notification-tooltip">
            <button type="button" aria-label="Alertas" data-panel="notification-painel-alertas" data-tooltip-text="Alertas">
              <span class="name"><i class="fas fa-bell" aria-hidden="true"></i></span>
            </button>
          </li>
          <li class="tab-item notification-tooltip active">
            <button type="button" aria-label="Mensagens" data-panel="notification-painel-mensagens" data-tooltip-text="Mensagens">
              <span class="name"><i class="fas fa-envelope" aria-hidden="true"></i></span>
            </button>
          </li>
        </ul>
      </nav>
      <div class="tab-content">
        <div class="tab-panel" id="notification-painel-alertas">
          <div class="br-list">
            <button class="br-item" type="button"><i class="fas fa-heartbeat mr-2" aria-hidden="true"></i>Link de acesso</button>
            <button class="br-item" type="button"><i class="fas fa-heartbeat mr-2" aria-hidden="true"></i>Link de acesso</button>
          </div>
        </div>
        <div class="tab-panel active" id="notification-painel-mensagens">
          <div class="br-list">
            <button class="br-item" type="button" role="contentinfo" aria-label="Mensagem nova: Prazo de envio, 25 de outubro">
              <span class="br-tag status small warning"></span>
              <span class="text-bold">Prazo de envio</span>
              <span class="text-medium mb-2">25 de out</span>
              <span>O prazo para envio dos documentos termina em 3 dias.</span>
            </button>
            <button class="br-item" type="button">
              <span class="text-bold">Cadastro atualizado</span>
              <span class="text-medium mb-2">24 de out</span>
              <span>Seus dados cadastrais foram atualizados com sucesso.</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
```

## Variantes e modificadores

| Classe / atributo | Efeito | Exemplo |
| --- | --- | --- |
| `br-notification` | Container (obrigatório). Fundo `--background`, sombra `--surface-shadow-md`, `max-width: 50vw`, `max-height: calc(100vh - 86px)`, `overflow:auto`, `z-index:1`. Abaixo do breakpoint sm passa a `100vw`, `min-height` de tela, tab em densidade small e `tab-content` com rolagem. | `<div class="br-notification">` |
| `notification-header` | Área do usuário (opcional): borda inferior `1px solid var(--border-color)` e padding `--spacing-scale-2x 4x` (menor em mobile). | `<div class="notification-header">` |
| `notification-body` | Corpo que abriga o `br-tab`; zera o padding dos `tab-item`, dá `overflow-y:auto` ao `tab-content` e formata cada `br-item` (padding, `white-space:normal`, `span` em bloco, `.status` posicionado à esquerda). | `<div class="notification-body">` |
| `.close` (div dentro do header) | Wrapper do botão fechar. `div.close` fica **oculto em telas ≥ md** (`display:none`) e visível em mobile, onde é obrigatório. | `<div class="close text-right">…</div>` |
| `br-notification.close` | Estado fechado: a classe `close` **no container** aplica `display:none` em telas < md. É adicionada pelo JS ao clicar no botão fechar. | `<div class="br-notification close">` |
| `br-tab` + `tab-nav` + `tab-item` (`active`) + `data-panel` | Navegação por abas dentro do body; `data-panel` deve ter o `id` do `tab-panel` correspondente. Sempre em densidade alta (o CSS já força `--tab-size: var(--tab-small)` no mobile). | ver HTML canônico |
| `tab-item.notification-tooltip` + `data-tooltip-text` | Item de aba só com ícone: o JS cria um tooltip (placement `top`) com o texto de `data-tooltip-text`. `notification-tooltip` não tem CSS, é só gancho de JS. | `<li class="tab-item notification-tooltip"><button data-tooltip-text="Alertas">` |
| `br-list` > `br-item` | Cada notificação é um `br-item` (botão) dentro de `br-list`; conteúdo em `span`s (título `text-bold`, data `text-medium mb-2`, corpo). | ver HTML canônico |
| `br-tag status small warning` (dentro do item) | Marca de "não lido"/status; posicionado à esquerda pelo CSS (`.status { position:absolute; left: base; top: 3x }`). Outras cores: `success`, `danger`, `info`. | `<span class="br-tag status small warning"></span>` |
| `.contextual-btn` | Seletor lido pelo JS (`menuBtns`) para botões de menu contextual em itens; sem CSS próprio e sem comportamento adicional na 3.7.0. | — |

Não existem modificadores de densidade, `inverted`/`dark-mode` ou de ênfase para `br-notification` no `core.css` 3.7.0.

## Estados e acessibilidade

- **Inicialização automática**: `core-init.js` executa `new core.BRNotification('br-notification', el)` para cada `.br-notification`. Com `core.min.js` puro, instancie manualmente:
  ```javascript
  for (const el of document.querySelectorAll('.br-notification')) new core.BRNotification('br-notification', el)
  ```
- **O que o JS faz**: (1) em todo `.br-notification .close` (o `div.close`, e por bolha o botão dentro dele) adiciona `click` → `component.classList.add('close')`, escondendo o componente em telas < md; (2) para cada `.notification-tooltip` fora de `.br-header` cria um `Tooltip` com o texto de `[data-tooltip-text]` (ignora se estiver dentro de `.header-avatar`). Não há JS para reabrir: remova a classe `close` você mesmo ou controle a exibição pelo dropdown do header/avatar.
- **Tabs**: o `br-tab` interno é inicializado pelo `initInstanceTabs` (`new core.BRTab`), que troca `active` entre `tab-item`/`tab-panel` via `data-panel`.
- **ARIA**: botão fechar com `aria-label="Fechar"`; botões de aba só com ícone precisam de `aria-label`; ícones `aria-hidden="true"`. O exemplo oficial usa `role="contentinfo"` + `aria-label` nos itens com status para que o leitor de tela anuncie a notificação (o `br-tag status` vazio não é lido). Divider/List: use `br-divider` entre itens se quiser separação visual explícita.
- **Teclado**: itens são `<button class="br-item">`, portanto focáveis e acionáveis por Enter/Espaço; abas por Tab.
- **Dependências**: Button, Item, List, Tab, Tag; Font Awesome 5 (`fas fa-times`, `fas fa-bell`, `fas fa-envelope`, `fas fa-heartbeat` nos exemplos).

## Erros comuns

- Usar `<div>` ou `<a>` sem estrutura de `br-list` > `br-item`: o padding, `white-space:normal` e o `span {display:block}` só se aplicam em `.notification-body .br-tab .tab-content .br-item`.
- Esquecer o `br-tab` (ou o `tab-content`) e colocar a lista direto no `notification-body`: as regras de rolagem e espaçamento dos itens dependem dessa cadeia de seletores.
- Colocar o botão fechar fora de um `div.close`: o JS só liga o `click` em `.br-notification .close`, e a classe `close` no container é o que esconde o painel.
- Esperar o botão fechar visível no desktop: `div.close` é `display:none` em ≥ md por design (fecha-se clicando fora ou no acionador).
- Fazer o `br-notification` ocupar mais de 50% da largura ou ultrapassar a altura visível em desktop; ou usar rolagem interna em mobile.
- `data-panel` sem `id` correspondente no `tab-panel`, ou dois `tab-item`/`tab-panel` com `active`.

## Fonte

- https://www.gov.br/ds/components/notification?tab=designer
- https://www.gov.br/ds/components/notification?tab=desenvolvedor
- https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/notification/notification.md
- https://docs-ds.estaleiro.serpro.gov.br/govbr-ds-core/docs/components/notification/notification-dev.md
- Local: `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/notification/examples.html`, `dist/components/notification/notification.js`, `dist/core-init.js`, `src/components/notification/_mixins.scss`, `dist/core.css`
