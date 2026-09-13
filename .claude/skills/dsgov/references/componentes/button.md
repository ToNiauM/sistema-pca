# br-button

## Quando usar / quando não usar
- Use para ações interativas reconhecíveis de imediato: executar ações, enviar formulários, navegar em fluxos. Planeje a hierarquia: **primário** (ação principal, um por contexto), **secundário** (alternativa), **terciário** (ações de menor ênfase, ícones circulares).
- Tipo **padrão** (rótulo obrigatório, ícone opcional à esquerda) e tipo **circular** (só ícone; `aria-label` obrigatório).
- Comportamento **bloco** (`block`) ocupa 100% da largura — útil em mobile e formulários.
- Densidades: `large` (48px, baixa), padrão/`medium` (40px), `small` (32px, alta), `xsmall` (24px).
- Não use `br-button` como link de texto corrido (use `<a>` simples) nem como *call-to-action* de conversão flutuante (use `br-magic-button`).
- Rótulos curtos, verbo no imperativo ("Salvar", "Enviar"); evite mais de um primário por tela.

## HTML canônico
```html
<button class="br-button primary" type="button">Salvar</button>
<button class="br-button secondary" type="button">Cancelar</button>
<button class="br-button" type="button">Terciário</button>

<!-- Com ícone à esquerda -->
<button class="br-button primary" type="button">
  <i class="fas fa-save" aria-hidden="true"></i> Salvar
</button>

<!-- Circular (somente ícone) -->
<button class="br-button circle" type="button" aria-label="Editar">
  <i class="fas fa-edit" aria-hidden="true"></i>
</button>
```

## Variantes e modificadores
| classe/atributo | efeito | exemplo |
| --- | --- | --- |
| `.br-button` | base: `inline-flex`, altura `--button-size` (40px), `border-radius: 100em` (pílula), fonte `up-01` semi-bold, cor `--interactive`, fundo transparente (= terciário) | `<button class="br-button">` |
| `a.br-button` | mesma aparência em link (`text-decoration:none !important`) | `<a class="br-button" href="…">` |
| `.primary` / `.is-primary` / `[primary]` | fundo `--interactive-light` (azul), texto `--color-dark` (branco) | `class="br-button primary"` |
| `.secondary` / `.is-secondary` / `[secondary]` | fundo `--background-light`, borda 1px `--interactive` | `class="br-button secondary"` |
| (sem ênfase) | **terciário**: só texto/ícone azul | `class="br-button"` |
| `.circle` / `.is-circle` / `[circle]` | `border-radius:50%`, `padding:0`, `width = --button-size` | `class="br-button circle"` |
| `.block` | `width:100%` | `class="br-button block primary"` |
| `.block-sm/-md/-lg/-xl` | bloco a partir do breakpoint | `class="br-button block-md"` |
| `.auto-sm/-md/-lg/-xl` | volta a `width:auto` a partir do breakpoint | `class="br-button block auto-lg"` |
| `.xsmall` / `.is-xsmall` / `[xsmall]` | 24px | — |
| `.small` / `.is-small` / `[small]` | 32px (alta densidade) | `class="br-button small"` |
| `.medium` / `.is-medium` / `[medium]` | 40px (padrão) | — |
| `.large` / `.is-large` / `[large]` | 48px (baixa densidade) | `class="br-button large"` |
| `.danger` / `.success` / `.info` (+ `is-*`, `[attr]`) | fundo da cor de estado, texto branco | `class="br-button danger"` |
| `.warning` (+ `is-warning`, `[warning]`) | fundo `--warning`, texto `--color-light` (escuro) | `class="br-button warning"` |
| `:disabled` | `cursor:not-allowed`; sem hover/focus/active; aparência via mixin global `disabled` | `<button class="br-button primary" disabled>` |
| `.active` / `.is-active` / `[active]` | estado ativado/toggle: fundo `--active`, texto `--color-dark` | `class="br-button primary active"` |
| `.loading` | texto transparente, `cursor:progress`, spinner via `::before` (borda `--interactive`; nos primary/danger/success/info a borda usa `--background`) | `class="br-button primary loading"` |
| `.inverted` / `.is-inverted` / `[inverted]` / `.dark-mode` | para fundo escuro: terciário fica `--interactive-dark`; primary inverte (fundo claro, texto escuro); secondary fundo `--background-dark`; `.active` fundo claro texto `--active` | `class="br-button primary dark-mode"` |

Ícones dos exemplos oficiais: `fas fa-city` (ilustrativo). Ícone dentro de botão padrão vai **antes** do texto.

## Estados e acessibilidade
- **Sem JS**: `br-button` não tem classe `BRButton`; nada a instanciar. Estados hover/focus/active são CSS (`--focus-offset: half`, mixins `focus`, `hover`, `active` apenas em `:not(:disabled)`).
- Sempre `type="button"` fora de submit de formulário; `type="submit"` apenas no botão de envio.
- Botão circular: **obrigatório** `aria-label` descritivo e `aria-hidden="true"` no `<i>`.
- Estado `loading`: adicione também `disabled` ou `aria-busy="true"` para bloquear cliques repetidos (o CSS não impede o clique).
- Toggle (`.active`): use `aria-pressed="true|false"` para comunicar o estado.
- Foco: o DS desenha `outline` próprio via mixin `focus` (`:focus-visible`/`.focus-visible`); não aplique `outline:none`.
- Em fundo escuro use `dark-mode`/`inverted` para manter contraste do texto (`--interactive-dark`).

## Erros comuns
- Usar `<div class="br-button">`: perde semântica, foco e teclado; use `<button>` ou `<a href>`.
- Circular sem `aria-label`: ícone `aria-hidden` deixa o botão sem nome acessível.
- Escrever `class="br-button btn-primary"` ou `br-button--primary` (nomenclatura Bootstrap/BEM): as classes válidas são `primary`, `secondary`, `circle`, `block`, `small`, `large`, etc., sem prefixo.
- Colocar texto em botão `.circle`: `padding:0` e `width` fixa cortam o rótulo.
- Definir `height`/`border-radius` manualmente: sobrescreve `--button-size`/`--button-radius` e quebra as densidades.
- Usar `.loading` sem `disabled`: o usuário pode clicar novamente durante o carregamento.
- Combinar `secondary` com `dark-mode` sobre fundo claro: fica invisível (fundo `--background-dark`).

## Botão "Copiar" (relatório com fragmento copiável)

Botão `br-button secondary` que usa a Clipboard API (`navigator.clipboard.write`, com fallback
`writeText`) num `<script>` inline em `{% block scripts %}` para copiar um fragmento HTML limpo
para a área de transferência — sem lib nova, sem CDN. Padrão completo (par com "Imprimir", partial
copiável, allowlist de tags): `references/telas/relatorio.md`.

## Fonte
- https://www.gov.br/ds/components/button?tab=designer (markdown bruto: https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/button/button.md)
- https://www.gov.br/ds/components/button?tab=desenvolvedor (SPA; markup dos exemplos locais)
- `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/button/examples.html`
- `/opt/web/pca/node_modules/@govbr-ds/core/src/components/button/_mixins.scss`, `_button.scss`
