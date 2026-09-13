# br-sign-in

## Quando usar / quando não usar

- **Use** como botão de autenticação que leva o usuário à área de login (acesso único gov.br ou provedores alternativos) quando é preciso restringir/controlar acesso, personalizar conteúdo ou proteger dados do usuário.
- Três **tipos**: **Interno** (exclusivo do próprio login gov.br: ícone `fa-user` + "Entrar"), **Externo** (demais soluções que usam o acesso gov.br: "Entrar com" + assinatura gov.br em texto `text-black` ou imagem à direita) e **Icônico** (`circle`, só ícone; comum para redes sociais).
- Rótulo curto (até três palavras), **nunca com quebra de linha**; imagem institucional com altura máxima de 20px e largura múltipla de 4px.
- Mantenha o sign-in próximo aos campos de login e ofereça cadastro tradicional, dúvidas frequentes e recuperação de senha. Em mobile use densidade **baixa** (`large`) e comportamento **bloco**.
- **Não use** para ações genéricas (use `br-button`) nem, no tipo interno, fora do contexto do login gov.br (evita repetir o logo no header).

## HTML canônico

Tipo externo com texto, ênfase primária (exemplo oficial `signin-tipo2.html`):

```html
<button class="br-sign-in primary" type="button">Entrar com&nbsp;<span class="text-black">gov.br</span></button>
```

Tipo interno (exclusivo do gov.br), tipo externo com imagem e tipo icônico:

```html
<!-- Interno -->
<button class="br-sign-in primary" type="button"><i class="fas fa-user" aria-hidden="true"></i>Entrar</button>

<!-- Externo com imagem (ênfase secundária) -->
<button class="br-sign-in" type="button">Entrar com&nbsp;<img src="https://www.gov.br/++theme++padrao_govbr/img/govbr-colorido-b.png" alt="gov.br"/></button>

<!-- Icônico -->
<button class="br-sign-in primary circle" type="button" aria-label="Entrar com gov.br"><i class="fas fa-user" aria-hidden="true"></i></button>
```

## Variantes e modificadores

O seletor CSS é `.br-sign-in, .br-button.sign-in` e ele herda **todas** as regras de `br-button` (mixin `button-configs`) mais os tokens de sign-in. A forma canônica nos exemplos 3.7.0 é `class="br-sign-in …"`; a doc de desenvolvedor mostra a forma equivalente `class="br-button sign-in …"`.

| Classe / atributo | Efeito | Exemplo |
| --- | --- | --- |
| `br-sign-in` | Botão com `--background: var(--gray-2)` (ênfase secundária padrão), `padding: 0 --spacing-scale-2x`, `img { max-height: 20px }` (`--sign-in-img`). Altura padrão 40px (média). | `<button class="br-sign-in">` |
| `primary` / `is-primary` / `[primary]` | Ênfase primária: fundo `--blue-warm-vivid-70`, texto/ícone `--gray-2`. | `<button class="br-sign-in primary">` |
| `secondary` / `is-secondary` / `[secondary]` | Ênfase secundária explícita (igual ao padrão sem classe): fundo `--gray-2`, texto `--blue-warm-vivid-70`. | `<button class="br-sign-in secondary">` |
| `circle` / `is-circle` / `[circle]` | Tipo icônico (redondo, só ícone). **Exige `aria-label`**. | `<button class="br-sign-in circle" aria-label="Entrar">` |
| `block` / `is-block`* / `[block]` | Ocupa 100% da largura (comportamento bloco). Variantes responsivas: `block-sm`, `block-md`, `block-lg`, `block-xl` (bloco a partir do breakpoint) e `auto-sm|md|lg|xl` (volta a largura automática). | `<button class="br-sign-in block">` |
| `small` / `is-small` / `[small]` | Densidade alta: altura 32px, raio 16px. | `<button class="br-sign-in small primary">` |
| `medium` / `is-medium` / `[medium]` | Densidade média (padrão): 40px, raio 20px. | `<button class="br-sign-in medium primary">` |
| `large` / `is-large` / `[large]` | Densidade baixa: 48px, raio 24px. | `<button class="br-sign-in large primary">` |
| `xsmall` / `is-xsmall` / `[xsmall]` | Herdado de `br-button` (24px); não aparece nas diretrizes de sign-in. | — |
| `inverted` / `is-inverted` / `[inverted]` / `dark-mode` | Fundo escuro: `--background: var(--background-dark)`; combinações `inverted.primary` (fundo `--blue-warm-20`, texto `--blue-warm-vivid-90`) e `inverted.secondary` (fundo `--blue-warm-vivid-90`, texto `--blue-warm-20`). | `<div class="bg-primary-darken-02 p-3"><button class="br-sign-in primary inverted">` |
| `active` / `is-active` / `[active]` | Estado ativo/pressionado (herdado de button). | — |
| `loading` | Estado carregando (spinner via `::before`, herdado de button). | `<button class="br-sign-in primary loading">` |
| `disabled` (atributo) | Desativado (`:disabled`, opacidade reduzida, sem hover). | `<button class="br-sign-in" disabled>` |
| `success` / `warning` / `danger` / `info` (+ `is-*`, `[*]`) | Cores de status herdadas de `br-button`; existem no CSS mas **não** fazem parte das diretrizes do sign-in. | — |
| `text-black` (no `<span>` da assinatura) | Peso *black* para o nome institucional "gov.br" quando não há imagem. | `Entrar com&nbsp;<span class="text-black">gov.br</span>` |
| `<img alt="gov.br">` | Assinatura institucional à direita do rótulo; altura máx. 20px. | ver HTML canônico |
| `<i class="fas fa-user" aria-hidden="true">` | Ícone de usuário obrigatório no tipo interno e no icônico; sempre à esquerda do rótulo. | — |

\* `is-block` não foi encontrado no `core.css`; use `block`.

## Estados e acessibilidade

- **CSS puro**: não há `dist/components/signin/signin.js`, não existe `BRSignIn` e o `core-init.js` não faz nada com `.br-sign-in`. Nenhum `data-*` é necessário.
- **Estados** herdados de `br-button`: padrão, hover (camada `--hover`), foco visível (`:focus-visible`/`.focus-visible` com anel de foco), ativo, `loading`, `:disabled`.
- **ARIA**: no tipo icônico (`circle`) o botão precisa de `aria-label` descritivo e o `<i>` de `aria-hidden="true"`. Nos tipos com texto, o rótulo visível já é o nome acessível; a imagem precisa de `alt` significativo ("gov.br"). Se o rótulo não explicar a ação, use `title` + tooltip.
- **Teclado**: nativo do `<button>` (Tab, Enter/Espaço). Sempre `type="button"` fora de formulários (ou `type="submit"` quando dispara o envio).
- **Dependências**: Button (mixins), Font Awesome 5 (`fas fa-user`).

## Erros comuns

- Usar `<a>` ou `<div>` sem `type="button"`/semântica de botão; ou omitir `aria-label` no tipo `circle`.
- Quebrar o rótulo em duas linhas ou usar rótulos longos; o botão deve ter largura variável, altura fixa por densidade.
- Imagem institucional maior que 20px de altura ou sem `alt`.
- Usar o tipo interno (`fa-user` + "Entrar") em soluções externas ao login gov.br, ou o externo sem a assinatura "gov.br" (`text-black` ou `<img>`).
- Colocar `inverted` sem fundo escuro (o botão fica com contraste invertido sobre fundo claro) ou esquecer `inverted` sobre fundo escuro.
- Esperar `is-block` ou `inline`: não existem; use `block`, `block-md`, etc.

## Fonte

- https://www.gov.br/ds/components/signin?tab=designer
- https://www.gov.br/ds/components/signin?tab=desenvolvedor
- https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/signin/signin.md
- https://docs-ds.estaleiro.serpro.gov.br/govbr-ds-core/docs/components/signin/signin-dev.md
- Local: `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/signin/examples.html`, `dist/components/signin/examples/*.html`, `src/components/signin/_signin.scss`, `src/components/signin/_mixins.scss`, `dist/core.css`
