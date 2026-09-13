# br-menu

## Quando usar / quando não usar
- **Menu principal**: acesso a todas as áreas/páginas do site/sistema, com links categorizados em seções e subseções (até 4 camadas nos exemplos). Deve ser acessível de qualquer página (acionado pelo botão do `br-header`).
- **Menu contextual** (`contextual`): navegação auxiliar de páginas internas/âncoras; simples, sem subníveis, camada zero (sem sombra); funciona independente do principal — não repita links nos dois.
- Localização: **flutuante/off-canvas** (padrão, com scrim) ou **fixo/push** (`push`, empurra o conteúdo e fica na lateral).
- Agrupe itens por expansão (`menu-folder`), por rótulos (item sem link) ou por dividers (`.divider`). Use o estado **ativo** para indicar "onde estou".
- Rótulos curtos, sem quebra de linha; não esconda o menu quando houver espaço para exibi-lo.

## HTML canônico
```html
<!-- Acionador (normalmente dentro do br-header) -->
<button class="br-button small circle" type="button" aria-label="Menu" data-toggle="menu" data-target="#main-navigation">
  <i class="fas fa-bars" aria-hidden="true"></i>
</button>

<div class="br-menu" id="main-navigation">
  <div class="menu-container">
    <div class="menu-panel">
      <div class="menu-header">
        <div class="menu-title">
          <img src="/img/logo.png" alt="Logo do órgão"/><span>Nome do Sistema</span>
        </div>
        <div class="menu-close">
          <button class="br-button circle" type="button" aria-label="Fechar o menu" data-dismiss="menu">
            <i class="fas fa-times" aria-hidden="true"></i>
          </button>
        </div>
      </div>
      <nav class="menu-body" role="tree">
        <div class="menu-folder">
          <a class="menu-item" href="javascript:void(0)" role="treeitem">
            <span class="icon"><i class="fas fa-bell" aria-hidden="true"></i></span>
            <span class="content">Serviços</span>
          </a>
          <ul>
            <li><a class="menu-item" href="/servicos/cpf" role="treeitem"><span class="icon"><i class="fas fa-id-card" aria-hidden="true"></i></span><span class="content">CPF</span></a></li>
            <li>
              <a class="menu-item" href="javascript:void(0)" role="treeitem"><span class="icon"><i class="fas fa-address-book" aria-hidden="true"></i></span><span class="content">Cadastros</span></a>
              <ul>
                <li><a class="menu-item" href="/cadastros/pf" role="treeitem"><span class="content">Pessoa física</span></a></li>
                <li><a class="menu-item" href="/cadastros/pj" role="treeitem"><span class="content">Pessoa jurídica</span></a></li>
              </ul>
            </li>
          </ul>
        </div>
        <a class="menu-item divider" href="/ajuda" role="treeitem">
          <span class="icon"><i class="fas fa-question-circle" aria-hidden="true"></i></span>
          <span class="content">Ajuda</span>
        </a>
      </nav>
      <div class="menu-footer">
        <div class="menu-logos"><img src="/img/logo-parceiro.png" alt="Parceiro"/></div>
        <div class="menu-links">
          <a href="https://www.gov.br"><span class="mr-1">gov.br</span><i class="fas fa-external-link-square-alt" aria-hidden="true"></i></a>
        </div>
        <div class="social-network">
          <div class="social-network-title">Redes Sociais</div>
          <div class="d-flex">
            <a class="br-button circle" href="https://facebook.com/…" aria-label="Facebook"><i class="fab fa-facebook-f" aria-hidden="true"></i></a>
            <a class="br-button circle" href="https://twitter.com/…" aria-label="Twitter"><i class="fab fa-twitter" aria-hidden="true"></i></a>
          </div>
        </div>
        <div class="menu-info">
          <div class="text-center text-down-01">Todo o conteúdo deste site está publicado sob a licença <strong>Creative Commons Atribuição-SemDerivações 3.0</strong></div>
        </div>
      </div>
    </div>
    <div class="menu-scrim" data-dismiss="menu" tabindex="0"></div>
  </div>
</div>
```

Menu contextual (exemplo oficial):
```html
<div class="br-menu contextual">
  <div class="menu-trigger d-sm-none">
    <button class="br-button primary block py-4" type="button" data-toggle="contextual" aria-expanded="false">
      <span class="mr-1">Menu Contextual</span><i class="fas fa-chevron-up ml-5" aria-hidden="true"></i>
    </button>
  </div>
  <div class="menu-container d-sm-block">
    <div class="menu-panel col-sm-3">
      <nav class="menu-body">
        <div class="menu-folder">
          <div class="menu-item"><span class="content">AGRUPAMENTO 1</span></div>
          <ul>
            <li><a class="menu-item" href="#secao-1"><span class="content">Item 1</span></a></li>
            <li><a class="menu-item" href="#secao-2"><span class="content">Item 2</span></a></li>
          </ul>
        </div>
      </nav>
    </div>
    <div class="menu-scrim" data-dismiss="menu" tabindex="0"></div>
  </div>
</div>
```

## Variantes e modificadores
| classe/atributo | efeito | exemplo |
| --- | --- | --- |
| `.br-menu#id` | raiz; `id` **obrigatório** (o JS localiza o acionador por `[data-target="#id"]`) | `<div class="br-menu" id="main-navigation">` |
| `.menu-container` | `display:none`; quando `.active`: `position:fixed` cobrindo a tela, `z-index: layer-3` | — |
| `.menu-scrim[data-dismiss="menu"][tabindex="0"]` | fundo escuro (`--surface-overlay-scrim`) que fecha o menu | — |
| `.menu-panel` | painel branco 100vh em coluna; no off-canvas recebe `col-sm-4 col-lg-3` (ou `data-breakpoints`) | — |
| `[data-breakpoints="col-sm-4 col-lg-3"]` (na raiz) | classes de largura aplicadas ao painel (padrão `col-sm-4 col-lg-3`) | `data-breakpoints="col-md-5 col-xl-3"` |
| `.menu-header` > `.menu-title` (img + span) + `.menu-close > button[data-dismiss="menu"]` | cabeçalho com borda inferior; logo máx. 40px | — |
| `nav.menu-body[role="tree"]` | corpo; reseta `ul/li`; `> .divider` ganha borda inferior | — |
| `.menu-folder` > `a.menu-item` + `ul > li > a.menu-item` | pasta expansível (JS adiciona `.drop-menu`, ícone `.support > i.fas.fa-chevron-down`, `aria-haspopup`); nível 2 com fundo `--gray-2` e padding-left `5x` | ver canônico |
| `.drop-menu.active` | pasta aberta: `ul` visível, ícone girado 180° | classe do JS |
| `li > a.menu-item + ul` (fora de pasta) | **side-menu**: JS adiciona `.side-menu`, ícone `fa-angle-right`, `role="none"`; ao abrir mostra só o subnível (item vira "voltar") | ver canônico (Camada 2 → 3) |
| `.side-menu.active` | subnível aberto (item em row-reverse, semi-bold, cor `--active`) | classe do JS |
| `.menu-item` > `span.icon` + `span.content` (+ `span.support`) | item flex, padding `--menu-item-padding 2x`; `a.menu-item` cor `--interactive` | — |
| `.menu-item.divider` | item de 1º nível com separador | `class="menu-item divider"` |
| `div.menu-item` (sem link) | rótulo de agrupamento (não interativo) | `<div class="menu-item"><span class="content">RÓTULO</span></div>` |
| `a.menu-item.active` | página atual: fundo `--active`, texto `--color-dark` | `class="menu-item active"` |
| `.menu-item[hidden]` / `:disabled` | oculto / desabilitado | — |
| `.small` / `.medium` / `.large` (na raiz) | padding vertical dos itens `base` / `2x` / `3x` (densidades alta/padrão/baixa) | `class="br-menu small"` |
| `.push` | menu fixo lateral: sem scrim/trigger, sem z-index alto; `menu-header`/`menu-footer` só aparecem com `data-visible="true"`; JS adiciona `col-sm-4 col-lg-3 px-0` ao abrir | `<div class="br-menu push" id="push">` |
| `.contextual` | menu contextual: `.menu-trigger > button[data-toggle="contextual"]` fixo na base no mobile (`< md`); painel estático em ≥ md; `--menu-zindex` menor; sem sombra | ver exemplo |
| `.active` (na raiz) | menu aberto (JS; também `aria-expanded="true"`) | `class="br-menu push active"` |
| `.menu-footer` > `.menu-logos`, `.menu-links`, `.social-network` (+ `.social-network-title`), `.menu-info` | rodapé; bordas automáticas entre seções; `.menu-social`/`.sharegroup` **depreciados** | — |
| `[data-dismiss="menu"]` | qualquer elemento que fecha o menu (botão fechar, scrim) | — |
| `[data-toggle="menu"][data-target="#id"]` | acionador externo | — |
| utilitários `shadow-lg-right`, `position-static`, `h-auto` | usados nos exemplos de `push active` embutidos na página | — |

Ícones oficiais: `fa-bars` (abrir), `fa-times` (fechar), `fa-chevron-down` (pasta, injetado), `fa-angle-right` (side-menu, injetado), `fa-chevron-up` (trigger contextual), `fa-external-link-square-alt` (links externos), `fab fa-*` (redes).

## Estados e acessibilidade
- **Auto-init**: `core-init.js` executa `new BRMenu('br-menu', el)` para cada `.br-menu`. Manual: `new core.BRMenu('br-menu', el)`.
- Abertura/fechamento: clique ou Enter/Espaço no `[data-target="#id"]` alterna `.active` na raiz e `aria-expanded`; `[data-dismiss="menu"]` fecha; Esc fecha (teclado tratado na raiz). Ao abrir, o foco vai para o primeiro `.menu-item` visível (`_focusOnFirstVisibleItem`).
- ARIA gerada pelo JS: `menu-body` `role="tree"` (ou `menubar`), itens `treeitem`/`menuitem`, `ul` de pastas `role="tree"` + `aria-label` com o texto do item, `ul` de side-menu `role="group"`, itens com subnível `aria-haspopup="true"` e `aria-expanded`. Você pode pré-escrever `role="tree"`/`treeitem` (exemplos oficiais fazem) — o JS não conflita.
- Navegação por teclado: setas ↑/↓ entre itens visíveis (`_navigateToNextElment`), Enter/Espaço abrem pasta/subnível, Esc volta/fecha.
- Contextual: em `< 992px` o JS adiciona `mb-5` ao `body` para o trigger fixo não cobrir conteúdo.
- `menu-header`/`menu-footer` no `push` só aparecem em ≥ sm com `data-visible="true"`.

## Erros comuns
- Raiz sem `id` ou `data-target` sem `#`: o JS faz `querySelector('[data-target="#<id>"]')` → acionador não encontrado, menu nunca abre.
- Pasta com `ul` fora do `.menu-folder`, ou `a.menu-item + ul` dentro de pasta esperando side-menu: `menu-folder > a + ul` vira drop-menu; `li > a + ul` vira side-menu — a estrutura decide o comportamento.
- Escrever manualmente `<span class="support">` com ícone: o JS só injeta se não existir; ícone errado não gira.
- Esquecer `.menu-scrim[data-dismiss="menu"]`: clique fora não fecha e o fundo não escurece.
- Usar `.push` sem colocá-lo em uma coluna do layout: ele ocupa a largura do container onde estiver (o JS adiciona `col-sm-4 col-lg-3`).
- Colocar o `br-menu` dentro do `br-header`: o `position:fixed` funciona, mas o header tem `overflow`/sombra e z-index próprios; deixe o menu como irmão do header no `body`.

## Fonte
- https://www.gov.br/ds/components/menu?tab=designer (markdown bruto: https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/menu/menu.md)
- https://www.gov.br/ds/components/menu?tab=desenvolvedor (SPA; markup dos exemplos locais)
- `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/menu/examples.html`
- `/opt/web/pca/node_modules/@govbr-ds/core/src/components/menu/_mixins.scss`
- `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/menu/menu.js`, `dist/core-init.js`
