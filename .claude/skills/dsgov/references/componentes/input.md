# br-input

## Quando usar / quando não usar
- Use para entrada de texto curto e objetivo (nome, e-mail, CPF, senha) e para campos de busca por palavra-chave.
- Rótulo (`label`) acima do campo por padrão; **rótulo lateral** (`input-inline`) quando o espaço horizontal permitir; nunca sem rótulo acessível (use `sr-only` se precisar esconder).
- Tipo **destaque** (`input-highlight`) para busca principal com maior altura (56px) e fundo cinza.
- Densidades: `small` (32px, alta), padrão (40px), `large` (48px, baixa).
- Mensagens de estado (`success/danger/warning/info`) com `span.feedback` logo abaixo; texto auxiliar em `<p>` para prevenir erros.
- Não use para textos longos (`br-textarea`), escolhas fechadas (`br-select`, `br-radio`) nem datas (`br-datetimepicker`).

## HTML canônico
```html
<div class="br-input">
  <label for="nome-completo">Nome completo</label>
  <input id="nome-completo" name="nome" type="text" placeholder="Digite seu nome"/>
  <p>Informe nome e sobrenome como no documento.</p>
</div>
```

Variações oficiais:
```html
<!-- Com ícone à esquerda -->
<div class="br-input">
  <label for="login">Login</label>
  <div class="input-group">
    <div class="input-icon"><i class="fas fa-user-tie" aria-hidden="true"></i></div>
    <input id="login" type="text" placeholder="Usuário"/>
  </div>
</div>

<!-- Senha com botão exibir/ocultar (JS do componente) -->
<div class="br-input input-button">
  <label for="senha">Senha</label>
  <input id="senha" type="password" placeholder="Digite sua senha"/>
  <button class="br-button" type="button" aria-label="Exibir senha" role="switch" aria-checked="false">
    <i class="fas fa-eye" aria-hidden="true"></i>
  </button>
</div>

<!-- Estado de erro -->
<div class="br-input danger">
  <label for="cpf">CPF</label>
  <input id="cpf" type="text" placeholder="Somente números" aria-describedby="cpf-erro"/>
  <span class="feedback danger" role="alert" id="cpf-erro"><i class="fas fa-times-circle" aria-hidden="true"></i>CPF inválido</span>
</div>

<!-- Rótulo lateral -->
<div class="br-input input-inline">
  <div class="input-label"><label class="text-nowrap" for="cep">CEP</label></div>
  <div class="input-content"><input id="cep" type="text" placeholder="00000-000"/></div>
</div>

<!-- Destaque com busca -->
<div class="br-input input-button input-highlight">
  <label class="sr-only" for="busca">Buscar</label>
  <input id="busca" type="search" placeholder="O que você procura?"/>
  <button class="br-button" type="button" aria-label="Buscar"><i class="fas fa-search" aria-hidden="true"></i></button>
</div>
```

## Variantes e modificadores
| classe/atributo | efeito | exemplo |
| --- | --- | --- |
| `.br-input` | wrapper `position:relative`, light-mode; `input` com altura `--input-size` (40px), borda `--border-color-alternative`, raio `sm`, fonte `up-01` medium | raiz |
| `label` + `input[id]` | rótulo acima (`margin-top: half` no input) | obrigatório |
| `p` (após input) | texto auxiliar | opcional |
| `.small` / `[data-small]` | 32px | `class="br-input small"` |
| `.medium` / `[data-medium]` | 40px (padrão) | — |
| `.large` / `[data-large]` | 48px | `class="br-input large"` |
| `.input-inline` > `.input-label` + `.input-content` | rótulo lateral (flex) | ver exemplo |
| `.input-group` > `.input-icon > i` + `input` | ícone ilustrativo à esquerda (padding-left `5x`) | ver exemplo |
| `.input-button` + `button.br-button` (após o input) | botão de ação interno à direita (32px, circular, `float:right`); input ganha padding-right `5x` | ver exemplo |
| `.has-icon` + `button.br-button.circle` | **compatibilidade** (usado por `br-header` e `br-datetimepicker`); prefira `input-button` em campos comuns | — |
| `.input-highlight` | altura 56px, fundo `--gray-2`, sem borda, paddings maiores | `class="br-input input-highlight"` |
| `.success` / `.danger` / `.warning` / `.info` (ou `[data-success]`…) | borda 2px na cor do estado | `class="br-input danger"` |
| `span.feedback.{success|danger|warning|info}[role="alert"]` | mensagem contextual; ícones `fa-check-circle`, `fa-times-circle`, `fa-exclamation-triangle`, `fa-info-circle` | ver exemplo |
| `input[disabled]` | desabilitado (mixin global `disabled`); exemplo oficial acompanha `feedback warning` "Campo Desabilitado" | — |
| `.inverted` / `.dark-mode` | label em `--color-dark`, foco `--focus-color-dark` (fundo escuro) | `class="br-input dark-mode"` |
| `input.search-autocomplete` | ativa autocomplete do JS (lista `.search-items > div`, item ativo `.is-active`) | requer `setAutocompleteData([...])` |
| `.br-list` (dentro de `.br-input`) | lista flutuante de sugestões (sombra `md`, `max-height:530px`) | usado pelo select/autocomplete |

## Estados e acessibilidade
- **Auto-init**: `core-init.js` executa `new BRInput('br-input', el)` para cada `.br-input`. Manual: `const i = new core.BRInput('br-input', el)`; para autocomplete: `i.setAutocompleteData(['Item 1','Item 2'])`.
- **Senha**: para `input[type="password"]` não desabilitado, clique em qualquer `.br-button` irmão alterna `fa-eye` ⇄ `fa-eye-slash`, `type` password⇄text e `aria-checked` nos botões com `aria-label="Exibir senha"` (o texto do `aria-label` é usado como seletor — mantenha exatamente). Use `role="switch"`.
- **Autocomplete**: `input` filtra `dataList` por prefixo; ↑/↓ movem `.is-active`, Enter seleciona (`keyCode` 13/38/40).
- Estados CSS: hover (mixin `hover("color")`), foco `focus-soft` em `:focus/:focus-visible`, cores de estado por classe; desabilitado pelo atributo nativo.
- Sempre: `label[for]` pareado com `input[id]`; `aria-describedby` apontando para o `id` do `.feedback` ou do `<p>` auxiliar; `aria-label` nos botões internos; `<i aria-hidden="true">`.
- Placeholder não substitui o rótulo.

## Erros comuns
- Colocar o botão **antes** do input ou fora do `.br-input`: o posicionamento usa `float:right` + `margin-top` negativo após o input.
- Ícone à esquerda sem `.input-group`/`.input-icon`: o input não recebe o padding e o ícone sobrepõe o texto.
- Usar `.is-invalid`/`.error`: as classes de estado são `danger`, `success`, `warning`, `info`.
- Trocar o `aria-label="Exibir senha"` por outro texto: o JS deixa de atualizar `aria-checked`.
- Label ausente ou `for` errado em `input-highlight` com `sr-only`: perde o nome acessível.
- Definir `height` no input: quebra as densidades (`--input-size`).

## Fonte
- https://www.gov.br/ds/components/input?tab=designer (markdown bruto: https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/input/input.md)
- https://www.gov.br/ds/components/input?tab=desenvolvedor (SPA; markup dos exemplos locais)
- `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/input/examples.html`
- `/opt/web/pca/node_modules/@govbr-ds/core/src/components/input/_mixins.scss`
- `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/input/input.js`, `dist/core-init.js`
