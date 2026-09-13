# br-checkbox

## Quando usar / quando não usar
- Use para o usuário selecionar **uma ou mais** opções em uma lista; se apenas uma opção for permitida, use `br-radio`; se a lista for muito extensa, avalie `br-select`.
- Serve para respostas sim/não ("Lembrar senha?"); para ligado/desligado considere `br-switch`.
- Antes da lista, apresente rótulo e breve descrição do conjunto de opções; textos curtos, verbo no imperativo.
- Pode ser usado **sem texto** (`hidden-label`) para seleção de linhas em tabelas/listas, mantendo `aria-label`.
- Estado **intermediário** para "selecionar tudo" com filhos parcialmente marcados (`data-parent`/`data-child`).
- Prefira disposição em uma coluna; em várias colunas mantenha larguras/alturas iguais.

## HTML canônico
```html
<p class="label mb-0">Interesses</p>
<p class="text-down-01">Selecione uma ou mais opções</p>

<div class="br-checkbox">
  <input id="interesse-saude" name="interesses" type="checkbox" value="saude"/>
  <label for="interesse-saude">Saúde</label>
</div>
<div class="br-checkbox">
  <input id="interesse-educacao" name="interesses" type="checkbox" value="educacao" checked="checked"/>
  <label for="interesse-educacao">Educação</label>
</div>
<div class="br-checkbox">
  <input id="interesse-trabalho" name="interesses" type="checkbox" value="trabalho"/>
  <label for="interesse-trabalho">Trabalho</label>
</div>
```

Grupo com estado intermediário (exemplo oficial):
```html
<div class="br-checkbox">
  <input id="check-todos" name="check-todos" type="checkbox" aria-label="Selecionar tudo"
         checked="checked" indeterminate="indeterminate" data-parent="grupo-1"/>
  <label for="check-todos">Selecionar tudo</label>
</div>
<div class="br-checkbox">
  <input id="check-01" name="check-01" type="checkbox" checked="checked" data-child="grupo-1"/>
  <label for="check-01">Opção 1</label>
</div>
<div class="br-checkbox">
  <input id="check-02" name="check-02" type="checkbox" data-child="grupo-1"/>
  <label for="check-02">Opção 2</label>
</div>
```

## Variantes e modificadores
| classe/atributo | efeito | exemplo |
| --- | --- | --- |
| `.br-checkbox` | wrapper `display:flex; position:relative`; irmãos consecutivos ganham `margin-top: base` | `<div class="br-checkbox">` |
| `input[type="checkbox"]` | input nativo com `opacity:0; position:absolute` (continua focável/clicável) | — |
| `input + label` | rótulo desenha a caixa (`::before` 24px, raio 4px, borda `--border-color`) e o check (`::after`) | `<label for="…">` |
| `input:checked + label::after` | marca de seleção (borda `--selected` rotacionada) | — |
| `input[indeterminate]` / `:indeterminate` | caixa preenchida `--selected` com traço branco | `indeterminate="indeterminate"` |
| `input[data-parent="X"]` | checkbox "pai" de um checkgroup (JS `Checkgroup`) | `data-parent="grupo-1"` |
| `input[data-child="X"]` | filhos do grupo `X` (podem estar em qualquer lugar do documento) | `data-child="grupo-1"` |
| `input[data-checked-label]` / `[data-unchecked-label]` | textos alternados no rótulo do pai (padrão: mantém o texto do label) | `data-checked-label="Desmarcar tudo"` |
| `.hidden-label` | esconde visualmente o texto do label (mantém para leitores de tela via `aria-label` no input) | `<div class="br-checkbox hidden-label">` |
| `.disabled` (wrapper) + `input[disabled]` | estado desabilitado (mixin `disabled` no label) | `<div class="br-checkbox disabled"><input disabled>` |
| `.invalid` / `.is-invalid` / `[invalid]` | borda `--danger` (também quando marcado) | `<div class="br-checkbox invalid">` |
| `.valid` / `.is-valid` / `[valid]` | borda `--success` | `<div class="br-checkbox valid">` |
| `input:invalid` | validação nativa HTML5 também pinta borda `--danger` | `required` |
| `.small` / `.is-small` / `[small]` | caixa 20px (`--spacing-scale-2xh`) — marcado como **TODO remover** no SCSS | evite |
| `.inverted` / `.dark-mode` | texto do label em `--color-dark` (fundo escuro) | `<div class="br-checkbox dark-mode">` |
| `span.feedback.warning[role="alert"]` | mensagem contextual abaixo do grupo (`fas fa-exclamation-triangle`) | ver `message.md` |
| `p.label` + `p.text-down-01` | rótulo e informações adicionais do grupo (utilitários) | ver canônico |

Layout horizontal: envolva cada `.br-checkbox` em `<div class="d-inline-block mr-5">`.

## Estados e acessibilidade
- **Auto-init**: `core-init.js` instancia `new BRCheckbox('br-checkbox', el)` para cada `.br-checkbox`; o único comportamento é procurar `input[type="checkbox"][data-parent]` **dentro do wrapper** e criar um `Checkgroup`. Manual: `new core.BRCheckbox('br-checkbox', el)`.
- Checkgroup: clique no pai marca/desmarca todos `[data-child="X"]`; mudanças nos filhos recalculam o pai (todos marcados → checked; nenhum → unchecked; parcial → `indeterminate` atributo + propriedade). O JS também define `aria-label` do pai com o texto do label. O atributo `indeterminate` no HTML é lido na inicialização (`parent.indeterminate = hasAttribute('indeterminate')`).
- `id`/`for` pareados são obrigatórios: o label é o alvo de clique e quem desenha a caixa.
- Sem texto visível: use `hidden-label` **e** `aria-label` no input (exemplo oficial em listas/tabelas).
- Foco: `:focus-visible` no input aplica `focus-soft` no `label::before`. Hover pinta a caixa com gradiente `--interactive-light-rgb`.
- Erro: além de `.invalid`, associe a mensagem com `aria-describedby` apontando para o `id` do `.feedback`.

## Erros comuns
- Colocar o `<label>` **antes** do `<input>` ou envolver o input no label: todo o CSS usa `input + label`; a caixa não aparece.
- Esquecer `id` no input ou `for` no label: a caixa desenhada não é clicável.
- Usar `.br-checkbox` sem wrapper (classe direto no input): a raiz precisa ser o `div`.
- Estado intermediário só com `indeterminate` no HTML sem `data-parent`/`data-child`: fica estático, sem sincronização.
- `data-parent` em wrapper diferente do input: o JS procura `input[data-parent]` dentro de cada `.br-checkbox`; os filhos (`data-child`) podem estar fora, o pai não.
- Aplicar `disabled` só no wrapper (`.disabled`) sem o atributo no input: o campo continua interativo.

## Fonte
- https://www.gov.br/ds/components/checkbox?tab=designer (markdown bruto: https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/checkbox/checkbox.md)
- https://www.gov.br/ds/components/checkbox?tab=desenvolvedor (SPA; markup dos exemplos locais)
- `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/checkbox/examples.html`
- `/opt/web/pca/node_modules/@govbr-ds/core/src/components/checkbox/_mixins.scss`
- `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/checkbox/checkbox.js`, `dist/partial/js/behavior/checkgroup.js`
