# br-message

## Quando usar / quando não usar
- Use para transmitir informação ao usuário decorrente de interações ou eventos do sistema, em quatro estados: **informativo** (`info`), **sucesso** (`success`), **alerta** (`warning`) e **erro** (`danger`).
- **Tipo padrão** (`.br-message`): feedback de contexto global (tela/seção), com ícone, título opcional, mensagem e botão fechar opcional.
- **Tipo contextual** (`.feedback`): feedback ligado a um componente específico (ex.: validação de campo), uma linha, itálico, logo abaixo do elemento.
- Evite textos longos com muitas quebras; evite múltiplas mensagens padrão empilhadas — para vários elementos use mensagens contextuais.
- Não use para conteúdo estático/decorativo nem como substituto de `br-modal` para confirmações.

## HTML canônico
```html
<div class="br-message danger">
  <div class="icon"><i class="fas fa-times-circle fa-lg" aria-hidden="true"></i></div>
  <div class="content" role="alert">
    <span class="message-title">Data de início inválida.</span>
    <span class="message-body"> A data não pode ser superior à data atual.</span>
  </div>
  <div class="close">
    <button class="br-button circle small" type="button" aria-label="Fechar a mensagem de erro">
      <i class="fas fa-times" aria-hidden="true"></i>
    </button>
  </div>
</div>

<!-- Contextual -->
<span class="feedback success" role="alert"><i class="fas fa-check-circle" aria-hidden="true"></i>Campo preenchido corretamente.</span>
```

## Variantes e modificadores
| classe/atributo | efeito | exemplo |
| --- | --- | --- |
| `.br-message` | flex, fundo `--message-background`, `margin-bottom: 2x` | raiz do tipo padrão |
| `.icon > i.fas.fa-lg` | ícone centralizado (cor `--message-color-icon`) | — |
| `.content` | `flex:1`, fonte `up-01`, padding `3x base 3x 2x` | — |
| `.message-title` / `.message-body` | título semi-bold / corpo regular (no mesmo `.content`) | — |
| `.close > button.br-button.circle.small` | botão fechar (margens `base`); cor herda `--message-color-icon` | opcional |
| `.success` / `.is-success` / `[success]` | fundo `--success-alternative`, ícone `--success`; ícone `fas fa-check-circle` | `class="br-message success"` |
| `.danger` / `.is-danger` / `[danger]` | fundo `--danger-alternative`; ícone `fas fa-times-circle` | `class="br-message danger"` |
| `.info` / `.is-info` / `[info]` | fundo `--info-alternative`; ícone `fas fa-info-circle` | `class="br-message info"` |
| `.warning` / `.is-warning` / `[warning]` | fundo `--warning-alternative`; ícone `fas fa-exclamation-triangle`; botão fechar em `--color` | `class="br-message warning"` |
| `.feedback` | tipo contextual: `inline-flex`, itálico, medium, padding `half`, fundo `--feedback-background` (cor sólida do estado), texto branco (exceto `warning`, texto escuro) | `<span class="feedback danger" role="alert">` |
| `.feedback.{success|danger|info|warning}` | cores do estado (mesmos ícones acima, sem `fa-lg`) | — |
| `.feedback` dentro de `.br-input` | `margin-bottom: half` (integração com input) | ver `input.md` |

Não há densidades, `inverted/dark-mode` nem `block/circle` para o message.

## Estados e acessibilidade
- **Auto-init**: `core-init.js` executa `new BRMessage('br-message', el)` (classe interna `BRAlert`) para cada `.br-message`. Manual: `new core.BRMessage('br-message', el)`.
- Comportamento: clique em `.close` (qualquer elemento com essa classe dentro de `.br-message`) **remove o componente do DOM** (`parentNode.removeChild`). Mensagens criadas dinamicamente após o init precisam de nova instância (ou listener próprio, como no exemplo oficial).
- `role="alert"` no `.content` (padrão) ou no `span.feedback` (contextual) para anunciar imediatamente; os exemplos também repetem o texto em `aria-label` no `.content` (opcional/redundante).
- Botão fechar: `aria-label` descritivo obrigatório; ícone `aria-hidden="true"`.
- Para mensagens de validação, ligue o campo com `aria-describedby` ao `id` do `.feedback`.
- Sem estados hover/focus próprios além do botão fechar.

## Erros comuns
- Usar `.alert`, `.error` ou `.br-alert`: as classes são `br-message` + `danger|success|info|warning` (e `feedback` para o contextual).
- Colocar o ícone diretamente em `.br-message` sem `<div class="icon">`: perde centralização e cor.
- Esquecer `fa-lg` no ícone do tipo padrão: ícone fica pequeno demais em relação ao texto.
- Botão fechar fora de `<div class="close">`: o JS busca `.br-message .close`; a margem e a cor também dependem do wrapper.
- Recriar a mensagem via JS e esperar que o fechar funcione sem reinstanciar `BRMessage`.
- Usar `.feedback` para mensagens longas ou globais: é `inline-flex`, feito para uma linha junto ao componente.

## Fonte
- https://www.gov.br/ds/components/message?tab=designer (markdown bruto: https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/message/message.md)
- https://www.gov.br/ds/components/message?tab=desenvolvedor (SPA; markup dos exemplos locais)
- `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/message/examples.html`
- `/opt/web/pca/node_modules/@govbr-ds/core/src/components/message/_mixins.scss`, `_message.scss`
- `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/message/message.js`, `dist/core-init.js`
