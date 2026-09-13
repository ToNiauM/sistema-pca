# br-header

## Quando usar / quando não usar
- Use para identificar o site/sistema (logo, assinatura, título, subtítulo) e agrupar navegação (botão menu), links de acesso rápido, funcionalidades, busca e autenticação (Entrar / avatar).
- Dois tipos recomendados: **Padrão** (mais informação, ênfase na marca; portais) e **Compacto** (`compact`; sistemas, mais espaço ao conteúdo). Densidades `small`/`large` ajustam o padding.
- `data-sticky` fixa o header no topo e o compacta ao rolar.
- Título é o único item obrigatório; todo o resto é opcional (use os atributos `data-no-*` ou simplesmente omita os blocos).
- Não use header para conteúdo de página nem múltiplos headers por página.

## HTML canônico
```html
<header class="br-header">
  <div class="container-lg">
    <div class="header-top">
      <div class="header-logo">
        <img src="/img/logo.png" alt="Logo do órgão"/>
        <span class="br-divider vertical"></span>
        <div class="header-sign">Ministério Exemplo</div>
      </div>
      <div class="header-actions">
        <div class="header-links dropdown">
          <button class="br-button circle small" type="button" data-toggle="dropdown" aria-label="Abrir Acesso Rápido">
            <i class="fas fa-ellipsis-v" aria-hidden="true"></i>
          </button>
          <div class="br-list">
            <div class="header"><div class="title">Acesso Rápido</div></div>
            <a class="br-item" href="/orgaos">Órgãos do Governo</a>
            <a class="br-item" href="/acesso-informacao">Acesso à Informação</a>
            <a class="br-item" href="/legislacao">Legislação</a>
            <a class="br-item" href="/acessibilidade">Acessibilidade</a>
          </div>
        </div>
        <span class="br-divider vertical mx-half mx-sm-1"></span>
        <div class="header-functions dropdown">
          <button class="br-button circle small" type="button" data-toggle="dropdown" aria-label="Abrir Funcionalidades do Sistema">
            <i class="fas fa-th" aria-hidden="true"></i>
          </button>
          <div class="br-list">
            <div class="header"><div class="title">Funcionalidades do Sistema</div></div>
            <div class="br-item">
              <button class="br-button circle small" type="button" aria-label="Relatórios">
                <i class="fas fa-chart-bar" aria-hidden="true"></i><span class="text">Relatórios</span>
              </button>
            </div>
            <div class="br-item">
              <button class="br-button circle small" type="button" aria-label="Suporte">
                <i class="fas fa-headset" aria-hidden="true"></i><span class="text">Suporte</span>
              </button>
            </div>
          </div>
        </div>
        <div class="header-search-trigger">
          <button class="br-button circle" type="button" aria-label="Abrir Busca" data-toggle="search" data-target=".header-search">
            <i class="fas fa-search" aria-hidden="true"></i>
          </button>
        </div>
        <div class="header-login">
          <div class="header-sign-in">
            <button class="br-sign-in small" type="button" data-trigger="login">
              <i class="fas fa-user" aria-hidden="true"></i><span class="d-sm-inline">Entrar</span>
            </button>
          </div>
          <div class="header-avatar"></div>
        </div>
      </div>
    </div>
    <div class="header-bottom">
      <div class="header-menu">
        <div class="header-menu-trigger">
          <button class="br-button small circle" type="button" aria-label="Menu" data-toggle="menu" data-target="#main-navigation" id="navigation">
            <i class="fas fa-bars" aria-hidden="true"></i>
          </button>
        </div>
        <div class="header-info">
          <div class="header-title">Nome do Sistema</div>
          <div class="header-subtitle">Subtítulo ou descrição curta</div>
        </div>
      </div>
      <div class="header-search">
        <div class="br-input has-icon">
          <label for="busca-header">Texto da pesquisa</label>
          <input id="busca-header" type="text" placeholder="O que você procura?"/>
          <button class="br-button circle small" type="button" aria-label="Pesquisar">
            <i class="fas fa-search" aria-hidden="true"></i>
          </button>
        </div>
        <button class="br-button circle search-close ml-1" type="button" aria-label="Fechar Busca" data-dismiss="search">
          <i class="fas fa-times" aria-hidden="true"></i>
        </button>
      </div>
    </div>
  </div>
</header>
<!-- O menu alvo (id="main-navigation") é um br-menu; ver menu.md -->
```

## Variantes e modificadores
| classe/atributo | efeito | exemplo |
| --- | --- | --- |
| `header.br-header` | fundo `--background`, sombra `sm`, `display:flex`, padding `--header-padding` (2x) | raiz |
| `.compact` | logo 16px, padding `small`, exibe `.header-search-trigger`, assinatura oculta, layout em float (tablet+) | `class="br-header compact"` |
| `.small` / `.medium` / `.large` | padding `base` / `2x` / `3x` (densidades alta/padrão/baixa) | `class="br-header small"` |
| `[data-sticky]` | `position:sticky; top:0; z-index: layer-2`; o JS adiciona `.sticky.compact` quando `pageYOffset > offsetHeight` | `<header class="br-header" data-sticky="data-sticky">` |
| `.container-lg` | limita a largura interna | obrigatório |
| `.header-top` / `.header-bottom` | linhas superior (logo + ações) e inferior (menu/título + busca) | — |
| `.header-logo` > `img` + `.br-divider.vertical` + `.header-sign` | logo (24px mobile / 40px tablet+), divisor e assinatura (ocultos no mobile) | — |
| `[data-no-logo]`, `[data-no-sign]` | ocultam imagem / assinatura | `<header class="br-header" data-no-sign>` |
| `.header-actions` | ações à direita (`flex-end`) | — |
| `.header-links.dropdown` > `button[data-toggle="dropdown"]` + `.br-list` | links de acesso rápido; no desktop (≥ lg) o botão some e a lista aparece inline | — |
| `.header-functions.dropdown` > `button[data-toggle="dropdown"]` + `.br-list > .br-item > button.br-button.circle.small > i + span.text` | funcionalidades; no desktop vira ícones circulares (texto `.text` oculto) | — |
| `.dropdown.show` + `button.active` | estado aberto (aplicado pelo JS; ícone gira 180°) | — |
| `[data-no-links]`, `[data-no-functions]`, `[data-no-login]`, `[data-no-subtitle]`, `[data-no-search]` | ocultam os blocos correspondentes | `data-no-functions` |
| `.header-search-trigger > button[data-toggle="search"][data-target=".header-search"]` | abre a busca (mobile e compacto) | — |
| `.header-login > .header-sign-in > button.br-sign-in[data-trigger="login"]` + `.header-avatar` | área de autenticação; `.header-avatar` recebe o avatar/dropdown do usuário logado; `[data-trigger="logout"]` reverte | — |
| `.header-menu > .header-menu-trigger > button[data-toggle="menu"][data-target="#main-navigation"]` + `.header-info > .header-title + .header-subtitle` | botão do menu e título (fonte `base` → `up-02` tablet → `up-03` desktop) | — |
| `.header-search` > `.br-input.has-icon` + `button.search-close[data-dismiss="search"]` | busca (absoluta cobrindo o header no mobile; inline no desktop, `min-width: 385px`); `.active` exibe | — |
| `.br-notification` (dentro de `.dropdown`) | suporte a dropdown de notificações (ver componente notification) | — |

Ícones oficiais: `fa-ellipsis-v`, `fa-th`, `fa-search`, `fa-user`, `fa-bars`, `fa-times`, `fa-chart-bar`, `fa-headset`, `fa-comment`, `fa-adjust`.

## Estados e acessibilidade
- **Auto-init**: `core-init.js` executa `new BRHeader('br-header', el)`. Manual: `new core.BRHeader('br-header', el)`.
- **Requisito rígido**: o construtor guarda `this.menuTrigger = querySelector('[data-target="#main-navigation"]')` e depois chama `this.menuTrigger.addEventListener(...)` sem checar null. **Sem um elemento com `data-target="#main-navigation"` o JS lança `TypeError` e o header (busca, dropdowns, sticky) não funciona.** Mantenha o botão de menu com esse `data-target` exato (e um `br-menu` com `id="main-navigation"`).
- Dropdowns do header são implementados no próprio `BRHeader` (não no `Dropdown` genérico): clique alterna `.active` no botão e `.show` no `.dropdown`; clique fora (`mousedown` no documento) fecha; Espaço fecha quando aberto; foco no trigger de busca/menu fecha os dropdowns.
- Busca: `data-toggle="search"` adiciona `.active` em `.header-search` e foca o input; `data-dismiss="search"` ou Esc no input fecham.
- Login/logout: `data-trigger="login"` esconde `.header-sign-in` e mostra `.header-avatar` (via `d-none`); `data-trigger="logout"` faz o inverso. Preencha `.header-avatar` com `br-avatar` + dropdown (ver `avatar.md`).
- Acessibilidade: todos os botões circulares com `aria-label`; `<label>` do input de busca é visualmente oculto pelo CSS mas presente; use `<header>` semântico; título em `.header-title` (adicione `<h1>` na página, o header não o substitui).

## Integração com um projeto concreto (Fase 28/Plano 28-03, PCA CFC)
- `.header-search` (o `.br-input.has-icon` do `header-bottom`) vira um `<form id="main-searchbox" tabindex="-1" method="get" action="...">` — `id="main-searchbox"` é o alvo do skiplink ("Ir para a busca"), `tabindex="-1"` é o que permite o skiplink mover o FOCO de teclado até um `<form>` (não focável nativamente). `.header-search-trigger` (mobile/compacto) fica FORA do form, é só o botão `[data-toggle="search"]`.
- Para manter `_header.html` genérico (reusável por outro sistema gerado por `novo_projeto.py`), o `action` do form e a própria existência do bloco de busca vêm de uma chave de projeto (ex. `settings.DSGOV["BUSCA_URL_NAME"]`, o nome de uma rota `{% url %}` concreta) — sem essa chave, `[data-no-search]` em `.br-header` oculta o bloco (CSS já embutido no core, ver tabela de modificadores acima) e os dois blocos de busca nem são renderizados.
- `DSGOV["PERFIL_URL_NAME"]` (opcional, ex.: `"core:perfil"`): quando definido, o dropdown do avatar ganha o item **Meu perfil** antes de Administração/Sair, apontando para `{% url DSGOV.PERFIL_URL_NAME %}` (área do usuário: nome, trocar senha, sair). Sem a chave, nada muda.
- O menu do avatar é um `Dropdown` genérico (`dsgov.js`), não um dropdown do BRHeader: `dsgov.js` espelha o `hidden` do alvo em `.show` do wrapper/`.active` do gatilho — sem isso o CSS `.header-actions .dropdown:not(.show) .br-list{display:none}` (< 1280px) esconderia o menu em celular e janelas estreitas.

## Erros comuns
- Omitir o botão de menu ou trocar `data-target="#main-navigation"` por outro id: `TypeError: Cannot read properties of null (reading 'addEventListener')` e nada no header funciona.
- Usar `.br-input.input-button` na busca: o SCSS do header posiciona `.br-input.has-icon .br-button.circle`.
- Colocar os blocos fora de `.header-top`/`.header-bottom` ou sem `.container-lg`: responsividade e alinhamentos quebram.
- Esquecer a classe `dropdown` no wrapper de `header-links`/`header-functions`: o JS busca `.dropdown [data-toggle="dropdown"]`.
- Colocar texto direto nos botões de `header-functions` sem `<span class="text">`: no desktop o texto não é ocultado e o ícone circular estoura.
- Envolver `br-header` em `.container`: ele deve ocupar 100% da largura (a limitação é interna).

## Fonte
- https://www.gov.br/ds/components/header?tab=designer (markdown bruto: https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/header/header.md)
- https://www.gov.br/ds/components/header?tab=desenvolvedor (SPA; markup dos exemplos locais)
- `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/header/examples.html`
- `/opt/web/pca/node_modules/@govbr-ds/core/src/components/header/_mixins.scss`
- `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/header/header.js`, `dist/core-init.js`
