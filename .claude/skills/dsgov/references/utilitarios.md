# Utilitários CSS do Design System gov.br (@govbr-ds/core 3.7.0)

Cheat sheet completo dos utilitários **que não são componentes**: grid, espaçamento, tipografia, cores, display/flexbox, elevação (sombras e camadas), superfície (bordas, cantos, opacidade, overflow) e estados.

Todas as classes abaixo foram verificadas por `grep` em `/opt/web/pca/node_modules/@govbr-ds/core/dist/core.css` (build 3.7.0). Fontes SCSS: `src/partial/scss/configs/*.scss`, `src/partial/scss/utilities/*.scss`, `src/partial/scss/mixins/*.scss`. Valores concretos dos tokens vêm de `dist/core-tokens.css`.

Regras gerais:

- Quase todos os utilitários usam `!important` (espaçamento, texto, display, flexbox, cores). Eles vencem o CSS dos componentes.
- Sufixo de *breakpoint* (`-sm`, `-md`, `-lg`, `-xl`) sempre fica **entre o prefixo e o valor**: `mt-sm-3x`, `d-md-none`, `text-lg-center`, `justify-content-sm-between`. Aplica-se **a partir** do breakpoint (`min-width`), nunca "somente naquele".
- Fonte base: `--font-family-base: Rawline, Raleway, sans-serif`. O `body` recebe `font-size: 14px`, `font-weight: 400`, `line-height: 1.45`.
- Font Awesome 5 (`fas fa-*`) é a iconografia usada nos exemplos oficiais (CDN `font-awesome/5.11.2/css/all.min.css`).

---

## 1. Breakpoints

| Nome | Dispositivo (docs) | Faixa (px) | Media query gerada | Token |
| --- | --- | --- | --- | --- |
| `xs` | Smartphone Portrait | 0–575 | (padrão, sem media query) | `--grid-breakpoint-xs: 0` |
| `sm` | Smartphone Landscape / Tablet Portrait | 576–991 | `@media (min-width: 576px)` | `--grid-breakpoint-sm: 576px` |
| `md` | Tablet Landscape | 992–1279 | `@media (min-width: 992px)` | `--grid-breakpoint-md: 992px` |
| `lg` | Desktop | 1280–1599 | `@media (min-width: 1280px)` | `--grid-breakpoint-lg: 1280px` |
| `xl` | TV | ≥ 1600 | `@media (min-width: 1600px)` | `--grid-breakpoint-xl: 1600px` |

Tokens auxiliares: `--grid-breakpoint-sm-max-width: 536px`, `--grid-breakpoint-md-max-width: 952px`, `--grid-breakpoint-lg-max-width: 1200px`, `--grid-breakpoint-xl-max-width: 1560px`.

Mapeamento interno de nomes (usado pelos tokens de grid): `xs → portrait`, `sm/md → tablet`, `lg → desktop`, `xl → tv`.

---

## 2. Grid

### 2.1 Parâmetros da grid por dispositivo

| Grid | Breakpoint | Colunas | Gutter (`--grid-*-gutter`) | Margem lateral (`--grid-*-margin`) | Max-width (`--grid-*-maxwidth`) |
| --- | --- | --- | --- | --- | --- |
| portrait (4 col) | xs | 4 (`--grid-portrait-columns`) | 16px | 8px | 100% |
| tablet (8 col) | sm, md | 8 (`--grid-tablet-columns`) | 24px | 40px | 100% |
| desktop (12 col) | lg | 12 (`--grid-desktop-columns`) | 24px | 40px | 1200px |
| tv (12 col) | xl | 12 (`--grid-tv-columns`) | 40px | 40px | 1520px |

Observação: **as classes `.col-*` geradas vão sempre de 1 a 12** em todos os breakpoints (`make-columns($grid-desktop-columns)`); "4 colunas" e "8 colunas" são a recomendação de design para xs e sm/md, não um limite da CSS.

### 2.2 Containers

Todas as variantes têm `margin-left/right: auto`, `width: 100%`, `padding-left/right: var(--grid-margin)` e `max-width: var(--grid-maxwidth)`.

Valores compilados de `--grid-maxwidth` (fórmula `calc(breakpoint − margem)`):

| Classe | xs (<576) | sm (≥576) | md (≥992) | lg (≥1280) | xl (≥1600) |
| --- | --- | --- | --- | --- | --- |
| `container` | 100% | 536px (576−40) | 952px (992−40) | 1240px (1280−40) | 1560px (1600−40) |
| `container-sm` | 100% | 536px | 952px | 1240px | 1560px |
| `container-md` | 100% | 100% | 952px | 1240px | 1560px |
| `container-lg` | 100% | 100% | 100% | 1240px | 1560px |
| `container-xl` | 100% | 100% | 100% | 100% | 1560px |
| `container-fluid` | 100% | 100% | 100% | 100% | 100% |

Padding lateral (`--grid-margin`) em todos os containers: **8px** em xs, **40px** a partir de sm.

> A tabela da documentação oficial (aba Desenvolvedor > Grid) cita 912px/1200px/1520px; os valores acima são os efetivamente compilados em `core.css` 3.7.0.

### 2.3 Row e colunas

```html
<div class="container-lg">
  <div class="row">
    <div class="col-12 col-sm-6 col-lg-4">Coluna A</div>
    <div class="col-12 col-sm-6 col-lg-4">Coluna B</div>
    <div class="col-12 col-lg-4">Coluna C</div>
  </div>
</div>
```

| Classe | Efeito |
| --- | --- |
| `row` | `display:flex; flex-wrap:wrap; margin-left/right: calc(var(--grid-gutter) * -0.5)`. Gutter: 16px (xs), 24px (sm, md, lg), 40px (xl). |
| `col`, `[class*="col-"]` | `padding-left/right: calc(var(--grid-gutter) * 0.5); width:100%` |
| `col` | coluna proporcional: `flex: 1 0 0%; min-width: 8.3333%` |
| `col-1` … `col-12` | largura fixa `(n/12)*100%` (`flex-basis` + `max-width`) em todas as telas |
| `col-auto` | `flex: 0 0 auto; width: auto` (largura do conteúdo) |
| `col-sm`, `col-md`, `col-lg`, `col-xl` | proporcional a partir do breakpoint; antes dele ocupa 100% |
| `col-sm-1…12`, `col-md-1…12`, `col-lg-1…12`, `col-xl-1…12` | largura fixa a partir do breakpoint; antes dele 100% |
| `col-sm-auto`, `col-md-auto`, `col-lg-auto`, `col-xl-auto` | largura do conteúdo a partir do breakpoint |

> **Não existe** `col-auto-sm` (grafia que aparece na doc oficial); a classe compilada é `col-sm-auto`.

Regras da doc: `row` e `col` só funcionam dentro de um `container*`; `row` pode ser usado sozinho dentro do container para "encaixar" conteúdo na largura das colunas; não use `col-*` fora de `row` (o `padding` do gutter fica sem a margem negativa da `row`).

---

## 3. Espaçamento (`m-*`, `p-*`)

### 3.1 Escala de tokens

Base `$spacer = 8px`. Duas escalas: **Layout** (múltiplos de 8px) e **Ajuste** (múltiplos de 8px + 4px; a doc de design restringe a escala Ajuste a textos e ícones).

| Token | Valor | Escala |
| --- | --- | --- |
| `--spacing-scale-default` | 0 | — |
| `--spacing-scale-half` | 4px | Ajuste |
| `--spacing-scale-base` | 8px | Layout |
| `--spacing-scale-baseh` | 12px | Ajuste |
| `--spacing-scale-2x` | 16px | Layout |
| `--spacing-scale-2xh` | 20px | Ajuste |
| `--spacing-scale-3x` | 24px | Layout |
| `--spacing-scale-3xh` | 28px | Ajuste |
| `--spacing-scale-4x` | 32px | Layout |
| `--spacing-scale-4xh` | 36px | Ajuste |
| `--spacing-scale-5x` | 40px | Layout |
| `--spacing-scale-5xh` | 44px | Ajuste |
| `--spacing-scale-6x` | 48px | Layout |
| `--spacing-scale-6xh` | 52px | Ajuste |
| `--spacing-scale-7x` | 56px | Layout |
| `--spacing-scale-7xh` | 60px | Ajuste |
| `--spacing-scale-8x` | 64px | Layout |
| `--spacing-scale-8xh` | 68px | Ajuste |
| `--spacing-scale-9x` | 72px | Layout |
| `--spacing-scale-9xh` | 76px | Ajuste |
| `--spacing-scale-10x` | 80px | Layout |
| `--spacing-scale-10xh` | 84px | Ajuste |

### 3.2 Sufixos de tamanho aceitos nas classes

Há **dois vocabulários equivalentes** que coexistem no CSS: nomes da escala (`half`, `base`, `2x`…) e números "estilo Bootstrap" (`0`–`6`).

| Sufixo | Resolve para | px |
| --- | --- | --- |
| `0` | `--spacing-scale-default` | 0 |
| `half` **ou** `1` | `--spacing-scale-half` | 4px |
| `base` **ou** `2` | `--spacing-scale-base` | 8px |
| `baseh` | `--spacing-scale-baseh` | 12px |
| `2x` **ou** `3` | `--spacing-scale-2x` | 16px |
| `2xh` | `--spacing-scale-2xh` | 20px |
| `3x` **ou** `4` | `--spacing-scale-3x` | 24px |
| `3xh` | `--spacing-scale-3xh` | 28px |
| `4x` **ou** `5` | `--spacing-scale-4x` | 32px |
| `4xh` | `--spacing-scale-4xh` | 36px |
| `5x` **ou** `6` | `--spacing-scale-5x` | 40px |
| `5xh` … `10xh` | `--spacing-scale-5xh` … `--spacing-scale-10xh` | 44…84px |
| `6x` … `10x` | `--spacing-scale-6x` … `--spacing-scale-10x` | 48…80px |
| `auto` (só margin) | `auto` | — |

Atenção: **`m-3` = 16px** (não 24px) e **`m-4` = 24px**, pois o mapa numérico é 1→half, 2→base, 3→2x, 4→3x, 5→4x, 6→5x. Não existem `m-7`, `m-8`… numéricos; a partir daí use `6x`, `7x`, etc.

### 3.3 Formato da classe

`{m|p}{t|b|l|r|x|y|∅}{-sm|-md|-lg|-xl|∅}-{tamanho}`

| Trecho | Significado |
| --- | --- |
| `m` / `p` | margin / padding |
| `t`, `b`, `l`, `r` | top, bottom, left, right |
| `x` | left + right |
| `y` | top + bottom |
| (sem direção) | todos os lados |
| `-n{tamanho}` | valor **negativo** (`calc(valor * -1)`), ex.: `mt-n2x`, `mx-n3`, `m-n1`. Não existe para `0` nem `auto`. Vale para margin **e** padding (gerado pelo mixin, embora padding negativo seja inválido em CSS). |

Exemplos verificados: `m-0`, `m-half`, `m-base`, `m-baseh`, `m-2x`, `m-10xh`, `mt-3x`, `mb-2`, `px-half`, `py-base`, `mx-auto`, `m-auto`, `ml-auto`, `mr-auto`, `mt-n1`, `mt-n2x`, `mb-sm-2`, `mt-md-3x`, `px-lg-2x`, `p-xl-5x`, `pt-sm-half`, `p-sm-0`.

Exemplo oficial (util/espacamento):

```html
<div class="bg-support-02 px-half rounder-sm text-weight-bold mx-3">mx-3</div>
```

---

## 4. Tipografia

### 4.1 Escala de tamanho (`text-*`)

Base 14px, razão ~1.2 (escala "minor third").

| Classe | Token | em | px compilado |
| --- | --- | --- | --- |
| `text-down-03` | `--font-size-scale-down-03` | 0.579 | 8.106px |
| `text-down-02` | `--font-size-scale-down-02` | 0.694 | 9.716px |
| `text-down-01` | `--font-size-scale-down-01` | 0.833 | 11.662px |
| `text-base` | `--font-size-scale-base` | 1 | 14px |
| `text-up-01` | `--font-size-scale-up-01` | 1.2 | 16.8px |
| `text-up-02` | `--font-size-scale-up-02` | 1.44 | 20.16px |
| `text-up-03` | `--font-size-scale-up-03` | 1.728 | 24.192px |
| `text-up-04` | `--font-size-scale-up-04` | 2.074 | 29.036px |
| `text-up-05` | `--font-size-scale-up-05` | 2.488 | 34.832px |
| `text-up-06` | `--font-size-scale-up-06` | 2.986 | 41.804px |
| `text-up-07` | `--font-size-scale-up-07` | 3.583 | 50.162px |
| `text-up-08` | `--font-size-scale-up-08` | 4.3 | 60.2px |
| `text-up-09` | `--font-size-scale-up-09` | 5.16 | 72.24px |
| `text-up-10` | `--font-size-scale-up-10` | 6.192 | 86.688px |
| `text-up-11` | `--font-size-scale-up-11` | 7.43 | 104.02px |

Com breakpoint: `text-sm-up-01`, `text-md-base`, `text-lg-up-03`, etc. A doc de design recomenda usar até `up-07`.

### 4.2 Peso (`text-weight-*`)

Cada peso tem **duas classes equivalentes**: `text-weight-{peso}` e `text-{peso}`.

| Classe | Peso |
| --- | --- |
| `text-weight-thin` / `text-thin` | 100 |
| `text-weight-extra-light` / `text-extra-light` | 200 |
| `text-weight-light` / `text-light` | 300 |
| `text-weight-regular` / `text-regular` | 400 |
| `text-weight-medium` / `text-medium` | 500 |
| `text-weight-semi-bold` / `text-semi-bold` | 600 |
| `text-weight-bold` / `text-bold` | 700 |
| `text-weight-extra-bold` / `text-extra-bold` | 800 |
| `text-weight-black` / `text-black` | 900 |

Com breakpoint: `text-sm-weight-bold`, `text-lg-bold`. Prefira `text-weight-*` (é a forma documentada; `text-light`/`text-black` colidem semanticamente com nomes de cor).

Line-height tokens: `--font-line-height-low: 1.15`, `--font-line-height-medium: 1.45`, `--font-line-height-high: 1.85` (não há classe utilitária de line-height).

### 4.3 Alinhamento, quebra e transformação

| Classe | Efeito |
| --- | --- |
| `text-left`, `text-center`, `text-right`, `text-justify` | `text-align` (elemento precisa ser block/inline-block) |
| `text-wrap` | `white-space: normal` |
| `text-nowrap` | `white-space: nowrap` |
| `text-truncate` | `overflow:hidden; text-overflow:ellipsis; white-space:nowrap` |
| `text-break` | `word-break: break-word; word-wrap: break-word` |
| `text-lowercase`, `text-uppercase`, `text-capitalize` | `text-transform` |

Todas aceitam breakpoint: `text-sm-center`, `text-lg-right`, `text-md-truncate`, `text-xl-uppercase`.

### 4.4 Estilos tipográficos por classe (independentes da tag)

| Classe | Estilo (≥ sm / < sm) |
| --- | --- |
| `h1` | up-06 light, margin-bottom 4x / xs: up-04 medium, mb 2xh |
| `h2` | up-05 regular, mt 3xh, mb 2xh, padding-bottom 2xh / xs: up-03 semi-bold |
| `h3` | up-04 medium, mt 3xh, mb 2xh / xs: up-02 bold |
| `h4` | up-03 semi-bold, mt 3xh, mb 2xh / xs: up-01 bold, mt 2x |
| `h5` | up-02 bold, uppercase, mt 3xh, mb 2x / xs: base extra-bold, mt 2x |
| `h6` | up-01 extra-bold, uppercase, mt 3xh, mb 2x / xs: down-01 extra-bold |
| `label` | base semi-bold, line-height medium, mb half |
| `legend` | up-01 semi-bold, line-height low, mt/mb 2x |
| `placeholder` | base regular itálico, cor `--color-light` |
| `input` | up-01 medium, line-height low |
| `code` | monospace, base medium, fundo `--gray-5`, radius 4px, padding half |
| `pre` | fundo `--gray-5`, padding 2x |
| `mark` | fundo `--red-warm-vivid-10` |
| `fieldset` | sem borda, mb 5x |

Todos os `h1`–`h6` usam `line-height: var(--font-line-height-low)` (1.15) e `color: var(--color)`. `p` tem `font-size: base` (xs) e `up-01` (≥ sm), `margin-bottom: 2x`.

```html
<p class="h1">Texto com estilo de H1</p>
<span class="text-up-02 text-weight-semi-bold text-uppercase">Destaque</span>
```

---

## 5. Cores (`text-*`, `bg-*`, `border-*`)

Prefixos: `bg-{cor}` (define `background` e também `--background`), `text-{cor}` (`color`), `border-{cor}` (`border-color`; **não cria a borda** — combine com `border-solid-sm` etc.).

### 5.1 Cores semânticas (legado "br-colors")

| Sufixo | Token / valor | bg-* muda texto p/ claro? |
| --- | --- | --- |
| `primary-pastel-01` | `--color-primary-pastel-01: #c5d4eb` | não |
| `primary-pastel-02` | `--color-primary-pastel-02: #dbe8fb` | não |
| `primary-lighten-01` | `--color-primary-lighten-01: #2670e8` | sim |
| `primary-lighten-02` | `--color-primary-lighten-02: #5992ed` | sim |
| `primary-default` | `--color-primary-default: #1351b4` | sim |
| `primary-darken-01` | `--color-primary-darken-01: #0c326f` | sim |
| `primary-darken-02` | `--color-primary-darken-02: #071d41` | sim |
| `secondary-01` … `secondary-09` | `#fff`, `#f8f8f8`, `#ededed`, `#ccc`, `#9e9d9d`, `#888`, `#555`, `#333`, `#000` | sim em 06–09 |
| `highlight` | `--color-highlight: #268744` | sim |
| `support-01` … `support-11` | `#36a191`, `#f2e317`, `#db4800`, `#a26739`, `#40e0d0`, `#48cbeb`, `#c72487`, `#63007f`, `#f08080`, `#ff8c00`, `#fdf5e6` | sim em 01, 03, 04, 07, 08 |

"Muda texto p/ claro" = a classe `bg-*` aplica o mixin `dark-mode` (redefine `--color`, `--interactive`, `--focus`, `--hover` para as versões *dark*), então textos, links e botões dentro do bloco ficam legíveis sobre fundo escuro.

Exemplos: `text-primary-default`, `bg-primary-default`, `text-secondary-08`, `bg-secondary-02`, `bg-highlight`, `border-secondary-04`.

### 5.2 Cores de estado

| Sufixo | Token | Valor |
| --- | --- | --- |
| `interactive` | `--interactive` → `--blue-warm-vivid-70` | `#1351b4` |
| `interactive-dark` | `--interactive-dark` → `--blue-warm-20` | `#c5d4eb` |
| `danger` | `--danger` → `--red-vivid-50` | `#e52207` |
| `warning` | `--warning` → `--yellow-vivid-20` | `#ffcd07` |
| `success` | `--success` → `--green-cool-vivid-50` | `#168821` |
| `info` | `--info` → `--blue-warm-vivid-60` | `#155bcb` |

Exemplos oficiais: `bg-interactive`, `border-solid-sm border-danger`, `text-success`, `text-info`.

### 5.3 Paleta completa (nome-família-tom)

Formato `{bg|text|border}-{família}-{tom}`. Ex.: `bg-blue-warm-vivid-70`, `text-gray-80`, `border-gray-20`, `bg-pure-0`.

| Família | Tons disponíveis |
| --- | --- |
| `pure` | 0 (`#fff`), 100 (`#000`) |
| `gray`, `gray-cool`, `gray-warm` | 1, 2, 3, 4, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90 |
| `blue`, `blue-cool`, `blue-warm`, `blue-warm-vivid`, `cyan`, `gold`, `green`, `green-cool`, `green-warm`, `indigo`, `indigo-cool`, `indigo-warm`, `magenta`, `mint`, `mint-cool`, `orange`, `orange-warm`, `red`, `red-cool`, `red-warm`, `violet`, `violet-warm`, `yellow` | 5, 10, 20, 30, 40, 50, 60, 70, 80, 90 |
| `blue-vivid`, `blue-cool-vivid`, `cyan-vivid`, `gold-vivid`, `green-vivid`, `green-cool-vivid`, `green-warm-vivid`, `indigo-vivid`, `indigo-cool-vivid`, `indigo-warm-vivid`, `magenta-vivid`, `mint-vivid`, `mint-cool-vivid`, `orange-vivid`, `orange-warm-vivid`, `red-vivid`, `red-cool-vivid`, `red-warm-vivid`, `violet-vivid`, `violet-warm-vivid`, `yellow-vivid` | 5, 10, 20, 30, 40, 50, 60, 70, 80 (sem 90) |

Valores de referência: `--gray-2: #f8f8f8`, `--gray-5: #f0f0f0`, `--gray-20: #ccc`, `--gray-80: #333`, `--blue-warm-vivid-70: #1351b4` (cor primária/interativa), `--blue-warm-vivid-80: #0c326f`, `--blue-warm-vivid-90` (fundo dark).

Tokens de superfície usados pelos componentes: `--background: var(--pure-0)`, `--background-alternative: var(--gray-5)`, `--color: var(--gray-80)`, `--color-dark: var(--pure-0)`, `--border-color: var(--gray-20)`, `--selected: var(--blue-warm-vivid-50)`.

> `dark-mode` e `inverted` **não são utilitários globais**: só existem como modificadores de componentes (`.br-button.dark-mode`, `.br-card.inverted`, etc.). Para um bloco de fundo escuro com texto claro use `bg-primary-darken-02`, `bg-secondary-08`, etc., que já aplicam o mixin dark-mode.

---

## 6. Display e Flexbox

### 6.1 Display

`d-{valor}` e `d-{bp}-{valor}` com valores `none`, `block`, `flex`, `inline`, `inline-block`, `inline-flex`.

```html
<div class="d-none d-sm-block">Aparece a partir de 576px</div>
<div class="d-block d-lg-none">Somente até 1279px</div>
<div class="d-flex align-items-center justify-content-between">…</div>
```

### 6.2 Flexbox — contêiner (com `d-flex` ou `d-inline-flex`)

| Grupo | Classes | Valores CSS |
| --- | --- | --- |
| direção | `flex-row`, `flex-row-reverse`, `flex-column`, `flex-column-reverse` | `flex-direction` |
| justify | `justify-content-start`, `-end`, `-center`, `-between`, `-around`, `-evenly` | flex-start, flex-end, center, space-between, space-around, space-evenly |
| align-items | `align-items-start`, `-end`, `-center`, `-baseline`, `-stretch` | |
| align-content | `align-content-start`, `-end`, `-center`, `-between`, `-around`, `-evenly`, `-stretch` | |
| wrap | `flex-wrap`, `flex-nowrap`, `flex-wrap-reverse` | `flex-wrap` |

### 6.3 Flexbox — filhos

| Classes | Efeito |
| --- | --- |
| `align-self-start`, `-end`, `-center`, `-baseline`, `-stretch` | `align-self` |
| `flex-fill` | `flex: 1 1 auto` |
| `flex-grow-0`, `flex-grow-1` | `flex-grow` |
| `flex-shrink-0`, `flex-shrink-1` | `flex-shrink` |
| `order-0` … `order-12` | `order` |

Breakpoints: o sufixo entra **após o prefixo do grupo**: `flex-sm-column`, `justify-content-lg-between`, `align-items-md-center`, `align-self-sm-end`, `flex-sm-fill`, `flex-grow-lg-1`, `flex-shrink-md-0`, `flex-sm-nowrap`, `order-sm-2`, `align-content-xl-stretch`.

---

## 7. Elevação (sombras e camadas)

### 7.1 Sombras `shadow-*`

Fórmula: `offset-x offset-y blur rgba(var(--surface-shadow-color), 0.16)` com `--surface-shadow-color: var(--rgb-secondary-09)` (preto) e blur fixo `--surface-blur-lg: 6px`.

| Tamanho | Offset |
| --- | --- |
| `sm` | 1px (`--surface-offset-sm`) |
| `md` | 3px |
| `lg` | 6px |
| `xl` | 9px |

| Classe | Direção da sombra |
| --- | --- |
| `shadow-none` | remove |
| `shadow-sm`, `shadow-md`, `shadow-lg`, `shadow-xl` | para baixo (padrão) |
| `shadow-{t}-up` | para cima |
| `shadow-{t}-right`, `shadow-{t}-left` | lateral |
| `shadow-{t}-inset` | interna, borda inferior |
| `shadow-{t}-inset-up`, `shadow-{t}-inset-right`, `shadow-{t}-inset-left` | interna, outras bordas |

(`{t}` = `sm`, `md`, `lg`, `xl`.) Exemplo oficial: `<div class="p-1 shadow-md">…</div>`.

### 7.2 Camadas `layer-*`

| Classe | z-index |
| --- | --- |
| `layer-0` | 0 |
| `layer-1` | 1000 |
| `layer-2` | 2000 |
| `layer-3` | 3000 |
| `layer-4` | 4000 |

Só tem efeito com `position` diferente de `static`.

### 7.3 Opacidade `opacity-*`

| Classe | opacity |
| --- | --- |
| `opacity-none` | 0 |
| `opacity-xs` | 0.16 |
| `opacity-sm` | 0.3 |
| `opacity-md` | 0.45 |
| `opacity-lg` | 0.65 |
| `opacity-xl` | 0.85 |
| `opacity-default` | 1 |

---

## 8. Superfície: bordas, cantos, overflow

### 8.1 Bordas

| Classe | CSS |
| --- | --- |
| `border-solid-none`, `border-dashed-none` | `border: 0 solid/dashed var(--color-secondary-06)` |
| `border-solid-sm`, `border-dashed-sm` | `border: 1px …` |
| `border-solid-md`, `border-dashed-md` | `border: 2px …` |
| `border-solid-lg`, `border-dashed-lg` | `border: 4px …` |
| `border-top`, `border-right`, `border-bottom`, `border-left` | `border-{lado}: var(--border-width) var(--border-style) var(--border-color)` = `1px solid var(--gray-20)` |
| `border-{cor}` | apenas `border-color` (ver §5) |

Cor padrão das bordas `border-solid-*`: `--color-secondary-06` (`#888`). Para trocar: `border-solid-sm border-gray-20`.

Tokens de espessura: `--surface-width-none: 0`, `-sm: 1px`, `-md: 2px`, `-lg: 4px`.

### 8.2 Cantos arredondados `rounder-*`

| Classe | border-radius (`--surface-rounder-*`) |
| --- | --- |
| `rounder-none` | 0 |
| `rounder-sm` | 4px |
| `rounder-md` | 8px |
| `rounder-lg` | 16px |
| `rounder-pill` | 999em |

A classe também define `--radius`, variável lida por alguns componentes.

### 8.3 Overflow

`overflow-auto`, `overflow-hidden` e com breakpoint `overflow-{sm|md|lg|xl}-auto`, `overflow-{bp}-hidden`.

### 8.4 Scrims de superfície (classes utilitárias, distintas do componente `br-scrim`)

| Classe | Efeito |
| --- | --- |
| `overlay-scrim` | `background: rgba(var(--rgb-secondary-09), 0.45)` (foco) |
| `overlay-text` | gradiente transparente → preto (legibilidade sobre imagem) |

---

## 9. Estados globais

| Classe / seletor | Efeito |
| --- | --- |
| `[disabled]`, `.disabled` | `cursor: not-allowed; opacity: var(--disabled)` no elemento e `pointer-events: none` em todos os descendentes |
| `highlight` | fundo/texto de destaque (`--status-highlight-*`), padding horizontal half |
| `dragged` | fundo e sombra de item arrastado |

---

## 10. Movimento (tokens; classes de easing e duração)

Tokens: `--duration-fast: 0.3s`, `--duration-moderate: 0.5s`, `--duration-slow: 0.8s`. As classes de `animation-timing-function` e de duração são geradas por `utilities/_motion.scss` a partir dos mapas `$easings`/`durations`; consulte `dist/util/movimento/examples.html` antes de usar (não cobertas neste cheat sheet).

---

## 11. Receitas rápidas

```html
<!-- Página base: container + título + parágrafo -->
<main class="container-lg py-5x">
  <h1 class="mb-3x">Título da página</h1>
  <p class="text-up-01 text-secondary-07">Subtítulo em cinza.</p>
</main>

<!-- Barra de ações alinhada à direita, responsiva -->
<div class="d-flex flex-column flex-sm-row justify-content-sm-end align-items-sm-center mt-3x">
  <button class="br-button secondary mb-2 mb-sm-0 mr-sm-2" type="button">Cancelar</button>
  <button class="br-button primary" type="button">Salvar</button>
</div>

<!-- Cartão manual -->
<div class="bg-pure-0 border-solid-sm border-gray-20 rounder-md shadow-sm p-3x">…</div>

<!-- Faixa escura com texto claro automático -->
<section class="bg-primary-darken-02 py-5x">
  <p class="text-up-03 text-weight-semi-bold m-0">Texto fica branco pelo mixin dark-mode</p>
</section>

<!-- Ocultar em mobile, mostrar de tablet em diante -->
<aside class="d-none d-sm-block col-sm-4">…</aside>
```

---

## 12. Fontes

- Docs designer: https://www.gov.br/ds/fundamentos-visuais/grid , https://www.gov.br/ds/fundamentos-visuais/espacamento , https://www.gov.br/ds/fundamentos-visuais/tipografia , https://www.gov.br/ds/fundamentos-visuais/cores , https://www.gov.br/ds/fundamentos-visuais/elevacao , https://www.gov.br/ds/fundamentos-visuais/superficie
- Markdown bruto (aba Desenvolvedor / "códigos"): https://docs-ds.estaleiro.serpro.gov.br/govbr-ds-core/docs/fundamentos-visuais/{grid,espacamento,tipografia,cores,elevacao,superficie}/{nome}-dev.md ; aba Designer: https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/fundamentos-visuais/{nome}/{nome}.md
- Exemplos oficiais locais: `/opt/web/pca/node_modules/@govbr-ds/core/dist/util/{grid,espacamento,tipografia,textos,cores,display,flexbox,elevacao,arredondamento,bordas,overflow}/examples.html`
- SCSS: `/opt/web/pca/node_modules/@govbr-ds/core/src/partial/scss/configs/{_grid,_spacing,_typography,_colors,_elevation,_surface}.scss`, `utilities/{_grid,_spacing,_text,_typography,_colors,_display,_flexbox,_elevation,_surface,_overflow,_states}.scss`, `mixins/{_grid,_spacing,_text,_colors}.scss`
- Tokens compilados: `/opt/web/pca/node_modules/@govbr-ds/core/dist/core-tokens.css`; CSS final: `dist/core.css`
