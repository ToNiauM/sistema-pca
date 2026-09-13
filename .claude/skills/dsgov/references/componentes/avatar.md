# br-avatar

## Quando usar / quando não usar
- Use para representar visualmente um usuário no ambiente digital (área logada, chats, comentários, listas de contatos, cartões de perfil).
- Três tipos: **icônico** (`fas fa-user`, quando não há foto), **fotográfico** (`<img>`) e **letra** (inicial do nome).
- Densidades: alta/`small` (40px, padrão) para listas e cenários repetitivos; média/`medium` (100px) para menus personalizados; baixa/`large` (160px) para páginas de perfil.
- Pode ser acionador de dropdown (ex.: menu "Olá, Fulano" no header). Combine com `br-tooltip` para exibir o nome completo.
- Não use como ícone decorativo genérico nem como botão sem rótulo acessível.

## HTML canônico
```html
<!-- Avatar fotográfico, densidade alta (padrão) -->
<span class="br-avatar" title="Maria da Silva">
  <span class="content">
    <img src="/img/maria.jpg" alt="Foto de Maria da Silva"/>
  </span>
</span>

<!-- Avatar icônico -->
<span class="br-avatar" title="Usuário sem foto">
  <span class="content"><i class="fas fa-user" aria-hidden="true"></i></span>
</span>

<!-- Avatar letra com cor de fundo utilitária -->
<span class="br-avatar medium" title="Wagner Souza">
  <span class="content bg-violet-50 text-pure-0">W</span>
</span>
```

Avatar como acionador de dropdown (exemplo oficial, usa `br-sign-in` + `br-list`):
```html
<button class="br-sign-in" type="button" id="avatar-dropdown-trigger"
        data-toggle="dropdown" data-target="avatar-menu" aria-label="Olá, Fulano">
  <span class="br-avatar" title="Fulano da Silva">
    <span class="content bg-orange-vivid-30 text-pure-0">F</span>
  </span>
  <span class="ml-2 text-gray-80 text-weight-regular">Olá, <span class="text-weight-semi-bold">Fulano</span></span>
  <i class="fas fa-caret-down" aria-hidden="true"></i>
</button>
<div class="br-list" id="avatar-menu" hidden="hidden" role="menu" aria-labelledby="avatar-dropdown-trigger">
  <a class="br-item" href="/dados-pessoais" role="menuitem">Dados pessoais</a>
  <a class="br-item" href="/privacidade" role="menuitem">Privacidade</a>
  <a class="br-item" href="/notificacoes" role="menuitem">Notificações</a>
</div>
```

## Variantes e modificadores
| classe/atributo | efeito | exemplo |
| --- | --- | --- |
| `.br-avatar` | raiz `inline-flex`, tokens `--avatar-size/--avatar-icon-size/--avatar-text-size` (padrão = small) | `<span class="br-avatar">` |
| `.content` | círculo (`border-radius:50%`, `overflow:hidden`, fundo `--blue-10`, texto `--blue-warm-20`, `text-transform:uppercase`) | `<span class="content">` |
| `.content img` | imagem cortada no círculo, `width/height = --avatar-size` | `<img alt="…">` |
| `.content .fas` | ícone com `--icon-size = --avatar-icon-size` | `<i class="fas fa-user">` |
| `.small` / `.is-small` / `[small]` | 40px (ícone `--icon-size-2x`, texto `up-03`) — é o padrão | `<span class="br-avatar small">` |
| `.medium` / `.is-medium` / `[medium]` | 100px (ícone `5x`, texto `up-07`) | `<span class="br-avatar medium">` |
| `.large` / `.is-large` / `[large]` | 160px (ícone `8x`, texto `up-11`) | `<span class="br-avatar large">` |
| `.br-avatar-action` | botão transparente com hover/focus do DS para envolver um avatar clicável | `<button class="br-avatar-action">` |
| `.br-avatar[data-toggle="dropdown"]` | aplica estilo de foco quando o próprio avatar é acionador | — |
| `.image`, `.letter` | **depreciados** (compatibilidade 2.x; serão removidos na v4) — use `.content` | — |
| `bg-*` / `text-*` (utilitários) | cores do avatar letra (`bg-violet-50 text-pure-0`, `bg-orange-50`, `bg-green-50`…) | ver exemplo |

Não há variantes `inverted`/`dark-mode`, `block` ou `is-invalid` no SCSS do avatar.

## Estados e acessibilidade
- **Auto-init**: `core-init.js` instancia `new BRAvatar('br-avatar', el)` para cada `.br-avatar`. Manual: `new core.BRAvatar('br-avatar', el)`.
- O único comportamento JS é o dropdown: se o **elemento pai** do `.br-avatar` tiver `data-toggle="dropdown"`, o JS cria um `Dropdown` (subclasse de `Collapse`) com `iconToShow: fa-caret-down`, `iconToHide: fa-caret-up`. O pai precisa de `data-target="<id do alvo>"` (id **sem** `#`).
- O alvo (`.br-list`) começa com `hidden`; o Collapse define `aria-expanded`/`aria-controls` no acionador, `aria-hidden` no alvo, `tabindex="0"` no acionador, fecha com Esc e ao clicar fora (mousedown), e navega entre `[role="menuitem"]` com setas ↑/↓.
- Sempre informe `title` na raiz (nome do usuário) e `alt` na imagem; no ícone use `aria-hidden="true"`. Se o avatar é o único conteúdo de um botão, dê `aria-label` ao botão.
- Estados visuais: apenas hover/focus quando dentro de `.br-avatar-action` ou de acionador dropdown; não há estado desabilitado próprio.

## Erros comuns
- Colocar `<img>` direto em `.br-avatar` sem `<span class="content">`: perde o recorte circular e o dimensionamento.
- Usar `data-target="#id"` com `#`: o Collapse faz `querySelector('#' + data-target)` e falha silenciosamente.
- Colocar `data-toggle="dropdown"` no próprio `.br-avatar` esperando o JS do avatar: ele lê `parentElement.dataset.toggle`, então o atributo deve estar no **pai** (botão).
- Ícone de seta diferente de `fa-caret-down/up`: o JS só alterna essas duas classes.
- Letra em minúscula sem contar com `text-transform: uppercase` (funciona) — mas mais de 1–2 caracteres estoura o círculo.
- Fazer o avatar com `<div>` dentro de texto/linha: a raiz é `inline-flex` e `vertical-align: middle`; envolva em `<span>`.

## Fonte
- https://www.gov.br/ds/components/avatar?tab=designer (markdown bruto: https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/avatar/avatar.md)
- https://www.gov.br/ds/components/avatar?tab=desenvolvedor (SPA; markup dos exemplos locais)
- `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/avatar/examples.html`
- `/opt/web/pca/node_modules/@govbr-ds/core/src/components/avatar/_mixins.scss`
- `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/avatar/avatar.js`, `dist/partial/js/behavior/dropdown.js`, `collapse.js`
