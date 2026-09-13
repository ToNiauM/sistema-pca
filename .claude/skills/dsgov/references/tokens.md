# Tokens do DSGov 3.7.0 (valores congelados)

Fonte: `assets/vendor/govbr-ds/3.7.0/core-tokens.css` (1.251 propriedades em `:root`). Tudo aqui
está no CSS já carregado por `core.min.css`; use sempre a **variável**, nunca o hex, em qualquer CSS
que porventura precise existir fora do DS (e a regra é: quase nunca precisa).

## Cores

Esquema de nomes: `--{familia}[-cool|-warm][-vivid]-{passo}`. Passos: 5, 10, 20 … 90. Os cinzas têm
ainda `--gray-1..4` (muito claros). Cada cor tem irmã `-rgb` (`--blue-warm-vivid-70-rgb: 19, 81, 180`).

### Marca e interação (a identidade do governo federal é a família Blue Warm Vivid)

| Token | Hex | Uso fixo |
|---|---|---|
| `--blue-warm-vivid-90` | `#071d41` | fundo escuro (`--background-dark`) |
| `--blue-warm-vivid-80` | `#0c326f` | `--active`, `--visited` |
| `--blue-warm-vivid-70` | `#1351b4` | **`--interactive`**: botões primários, links, ícones do header |
| `--blue-warm-vivid-60` | `#155bcb` | `--info` |
| `--blue-warm-vivid-50` | `#2670e8` | `--selected` |
| `--blue-warm-vivid-40` | `#5992ed` | `--on` (switch ligado) |
| `--blue-warm-vivid-30` | `#81aefc` | |
| `--blue-warm-vivid-20` | `#adcdff` | |
| `--blue-warm-vivid-10` | `#d4e5ff` | `--info-alternative`, linha selecionada |
| `--blue-warm-vivid-5`  | `#edf5ff` | fundo de destaque suave |
| `--blue-warm-20` | `#c5d4eb` | `--interactive-dark` (link sobre fundo escuro) |

### Neutros

| Token | Hex | Uso fixo |
|---|---|---|
| `--gray-90` | `#1b1b1b` | |
| `--gray-80` | `#333333` | **texto padrão** (`--color`) |
| `--gray-70` | `#555555` | subtítulo e assinatura no header |
| `--gray-60` | `#636363` | |
| `--gray-50` | `#757575` | |
| `--gray-40` | `#888888` | `--border-color-alternative` |
| `--gray-30` | `#adadad` | |
| `--gray-20` | `#cccccc` | **`--border-color`**, `--off` |
| `--gray-10` | `#e6e6e6` | |
| `--gray-5`  | `#f0f0f0` | `--background-alternative` (faixas zebradas, áreas secundárias) |
| `--gray-2`  | `#f8f8f8` | fundo do campo de busca do header |
| `--pure-0`  | `#ffffff` | `--background` |
| `--pure-100`| `#000000` | título do header |

### Feedback (únicos tokens semânticos de estado; não existe `--feedback-*`)

| Semântico | Aponta para | Hex | Alternativo (fundo) |
|---|---|---|---|
| `--success` | `--green-cool-vivid-50` | `#168821` | `--success-alternative` = `--green-cool-vivid-5` |
| `--warning` | `--yellow-vivid-20` | `#ffcd07` | `--warning-alternative` = `--yellow-vivid-5` |
| `--danger`  | `--red-vivid-50` | `#e52207` | `--danger-alternative` = `--red-vivid-10` |
| `--info`    | `--blue-warm-vivid-60` | `#155bcb` | `--info-alternative` = `--blue-warm-vivid-10` |
| `--focus-color` | `--gold-vivid-40` | | foco tracejado 4px, offset 4px (`--focus-style: dashed`) |

Classes utilitárias de cor existem para todas as famílias: `.bg-{familia}-{passo}`, `.text-{familia}-{passo}`
(ex.: `bg-blue-warm-vivid-70`, `text-pure-0`, `bg-gray-5`, `text-gray-70`). Tags de status usam
`br-tag status bg-success|bg-warning|bg-danger|bg-info`.

Tokens legados que ainda existem e o CSS do DS usa internamente: `--color-primary-default` (#1351b4),
`--color-primary-darken-01` (#0c326f), `--color-secondary-01..09` (branco → preto), `--color-support-01..11`.
Não os use em código novo; prefira os semânticos acima.

## Tipografia

```
--font-family-base: Rawline, Raleway, sans-serif
--font-size-scale-base: 14px            (1em; tudo o mais em em)
--font-size-scale-down-01: 11.662px  -02: 9.716px  -03: 8.106px
--font-size-scale-up-01: 16.8px  -02: 20.16px  -03: 24.192px  -04: 29.036px  -05: 34.832px  -06: 41.804px
--font-size-scale-up-07: 50.162px ... -11: 104.02px
--font-weight-light: 300  regular: 400  medium: 500  semi-bold: 600  bold: 700
--font-line-height-low: 1.15  medium: 1.45  high: 1.85
```

Escala Minor Third (razão 1,2). Regras fixas do DS:

| Elemento | Tamanho | Peso | Line-height | Margem inferior |
|---|---|---|---|---|
| h1 (título da página) | `up-06` | light (300) | low | `--spacing-scale-4x` |
| h2 (seção) | `up-05` | regular | low | `--spacing-scale-3x` |
| h3 | `up-04` | medium | low | `--spacing-scale-2x` |
| h4 | `up-03` | semi-bold | low | `--spacing-scale-2x` |
| h5 | `up-02` | bold | low | `--spacing-scale-2x` |
| h6 | `up-01` | bold | low | `--spacing-scale-2x` |
| corpo | base (14px) | regular | medium | |
| legendas/rodapé de tabela | `down-01` | regular | medium | |

Classes: `.text-up-01..07`, `.text-down-01..03`, `.text-base`, `.text-weight-{light|regular|medium|semi-bold|bold}`
(também `.text-bold`, `.text-medium`, `.text-semi-bold`), responsivas `.text-sm-up-02` etc., `.text-uppercase`,
`.text-center`, `.text-left`, `.text-right`, `.text-nowrap`.
Os elementos `h1..h6`, `p`, `ul`, `ol`, `a` já saem estilizados pelo `core.min.css`: não redefina.

## Espaçamento

Duas escalas. **Layout** (múltiplos de 8px) para margens, paddings e distância entre blocos.
**Ajuste** (múltiplos de 4px, sufixo `h`) apenas para texto e ícones.

```
--spacing-scale-half: 4px   --spacing-scale-base: 8px   --spacing-scale-baseh: 12px
--spacing-scale-2x: 16px    --spacing-scale-2xh: 20px   --spacing-scale-3x: 24px   --spacing-scale-3xh: 28px
--spacing-scale-4x: 32px    --spacing-scale-4xh: 36px   --spacing-scale-5x: 40px   --spacing-scale-5xh: 44px
--spacing-scale-6x: 48px    --spacing-scale-7x: 56px    --spacing-scale-8x: 64px   --spacing-scale-9x: 72px
--spacing-scale-10x: 80px
```

Classes utilitárias `m*`/`p*` com `t b l r x y` e os passos: `0`, `half`, `1` (=4px), `2` (=8px), `3` (=16px),
`4` (=24px), `5` (=32px), `6` (=40px), `2x`…`10x`, `2xh`…`10xh`, negativos `n1`…`n6`. Responsivas:
`mb-sm-3`, `px-md-4` etc. Exemplos usados pelos templates da skill: `mb-3` (16px entre campos),
`mb-4` (24px entre header e conteúdo), `mt-4` (24px), `mb-5` (32px depois do conteúdo).

## Superfície

```
--surface-width-sm: 1px  -md: 2px  -lg: 4px
--surface-rounder-sm: 4px  -md: 8px  -lg: 16px  -pill: 999em
--surface-opacity-xs: .16  -sm: .3  -md: .45  -lg: .65  -xl: .85
--surface-shadow-sm: 0 1px 6px rgba(0,0,0,.16)   -md: 0 3px 6px   -lg: 0 6px 6px   -xl: 0 9px 6px
--surface-overlay-scrim: rgba(0,0,0,.45)
--z-index-layer-1: 1000  -2: 2000  -3: 3000  -4: 4000
--duration-fast: .3s  --animation-ease: cubic-bezier(.25,.1,.25,1)
```

Classes: `.shadow-{none|sm|md|lg|xl}`, `.rounder-{none|sm|md|lg|pill}`, `.border-{solid|dashed}-{none|sm|md|lg}`.
Cards usam `--surface-shadow-sm` e `--surface-rounder-sm`; o header fixo vive na camada 3.

## Grid e breakpoints (não são os do Bootstrap)

| Nome | Largura mínima | Container | Colunas | Gutter | Margem |
|---|---|---|---|---|---|
| xs (celular retrato) | 0 | 100% | 4 | 16px | 8px |
| sm (celular paisagem/tablet) | **576px** | 536px | 8 | 24px | 40px |
| md (desktop) | **992px** | 952px | 12 | 24px | 40px |
| lg | **1280px** | 1200px | 12 | 24px | 40px |
| xl (TV) | **1600px** | 1560px | 12 | 40px | 40px |

Não existe ponto em 768px. `col-md-*` só entra em 992px. Classes: `.container-lg` (header, footer e main
usam este), `.container-fluid`, `.row`, `.col`, `.col-auto`, `.col-1..12`, `.col-{sm|md|lg|xl}-{n}`,
`.d-flex`, `.d-none`, `.d-sm-block`, `.d-sm-flex`, `.flex-fill`, `.align-items-{start|center|end}`,
`.justify-content-{start|center|end|between}`, `.ml-auto`.

## Densidade

`small` = alta (compacta), padrão = média, `large` = baixa. Alvo mínimo de 24px para mouse e 40px para
toque. Nos sistemas gerados pela skill a densidade padrão é a **média** em tudo; `small` só em botões
circulares de ação dentro de tabelas e no header (que já vêm assim nos templates).

## Ícones

Font Awesome 5 Free, estilos `fas` (solid) e `fab` (brands). Tamanhos: `fa-xs` 8px, `fa-sm` 12px, base 16px,
`fa-lg` 20px, `fa-2x` 32px, `fa-3x` 48px. Decorativos levam `aria-hidden="true"`; se o ícone é a única
informação, o elemento pai leva `aria-label`.

Vocabulário fixo do Padrão Mínimo: pesquisar `fa-search`, editar `fa-pen`, excluir `fa-trash`, visualizar
`fa-eye`, fechar `fa-times`, imprimir `fa-print`, atualizar `fa-sync`, limpar `fa-eraser`, bloquear `fa-lock`,
início `fa-home`, adicionar `fa-plus`, salvar `fa-save`, voltar `fa-arrow-left`, download `fa-download`,
filtro `fa-filter`, ordenar `fa-sort` / `fa-sort-up` / `fa-sort-down`, menu `fa-bars`, usuário `fa-user`,
sair `fa-sign-out-alt`, sucesso `fa-check-circle`, erro `fa-times-circle`, aviso `fa-exclamation-triangle`,
informação `fa-info-circle`, expandir `fa-chevron-down`, próximo `fa-angle-right`, anterior `fa-angle-left`.
