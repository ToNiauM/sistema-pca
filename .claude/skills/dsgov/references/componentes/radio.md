# br-radio

## Quando usar / quando não usar

- **Use** quando o usuário deve selecionar **apenas uma** opção em uma lista de opções mutuamente exclusivas; todas as opções ficam visíveis.
- **Não use** quando várias opções podem ser marcadas (use `br-checkbox`) nem para ligado/desligado (use `br-switch`).
- **Não use** para listas muito extensas: avalie o `br-select`.
- Preceda a lista com um **rótulo** e, se necessário, um texto auxiliar; prefira disposição em **uma coluna**; use no máximo uma mensagem de *feedback* para todo o grupo, abaixo do último item.
- Textos descritivos curtos (até ~7 palavras), em frase (primeira letra maiúscula), nunca em caixa alta.

## HTML canônico

Exemplo oficial (`dist/components/radio/examples/radio-default.html`), com rótulo, texto auxiliar, opções e mensagem de feedback:

```html
<fieldset>
  <legend class="label mb-0">Tipo de documento</legend>
  <p class="help-text">Selecione apenas uma opção</p>
  <div class="br-radio">
    <input id="doc-cpf" type="radio" name="documento" value="cpf"/>
    <label for="doc-cpf">CPF</label>
  </div>
  <div class="br-radio">
    <input id="doc-cnpj" type="radio" name="documento" value="cnpj" checked="checked"/>
    <label for="doc-cnpj">CNPJ</label>
  </div>
  <div class="br-radio">
    <input id="doc-passaporte" type="radio" name="documento" value="passaporte"/>
    <label for="doc-passaporte">Passaporte</label>
  </div>
  <div class="mt-3">
    <span class="feedback warning" role="alert"><i class="fas fa-exclamation-triangle" aria-hidden="true"></i>Selecione um tipo de documento</span>
  </div>
</fieldset>
```

> O exemplo oficial usa `<p class="label mb-0">Rótulo</p>` e `<p class="help-text">`; `fieldset`/`legend` é a forma acessível equivalente de agrupar. `.label` existe no `core.css`; `.help-text` **não** tem regra no `core.css` 3.7.0 (aparece no exemplo oficial, mas sem estilo próprio).

## Variantes e modificadores

| Classe / atributo | Efeito | Exemplo |
| --- | --- | --- |
| `br-radio` | Container (obrigatório): `display:block`; `input` invisível (`opacity:0; position:absolute`); `label` com círculo de 24px (`--radio-size`) desenhado em `::before`; bolinha de 16px (`--radio-bullet-size`) em `::after` quando `:checked`. Radios irmãos consecutivos ganham `margin-top: --spacing-scale-base`. | `<div class="br-radio">` |
| `input[type=radio]` + `label[for]` | Estrutura obrigatória: o `label` deve vir **imediatamente após** o `input` (seletor `input + label`). `label` com `font-weight: medium`. | ver HTML canônico |
| `label` vazio (`:empty`) | Radio sem texto (ex.: em tabela): zera o padding do label; mantenha `aria-label` no `input`. | `<input id="r1" type="radio" aria-label="Selecionar linha 1"/><label for="r1"></label>` |
| `hidden-label` | Classe reconhecida no CSS (`.br-radio:not(.hidden-label)`), usada em contextos internos (ex.: itens de `br-select`) para esconder o texto e manter só a caixa. | `<div class="br-radio hidden-label">` |
| `valid` / `is-valid` / `[valid]` | Borda do círculo em `--success`. | `<div class="br-radio valid">` |
| `invalid` / `is-invalid` / `[invalid]` | Borda do círculo em `--danger`. O CSS também reage a `input:invalid` nativo. | `<div class="br-radio invalid">` |
| `disabled` (classe) + `disabled` (atributo no input) | Estado desativado. A classe no container é a documentada; o atributo no `input` é obrigatório para desativar de fato (o CSS usa `:not(:disabled)` no hover). | `<div class="br-radio disabled"><input … disabled="disabled"/>` |
| `checked` | Estado selecionado (atributo nativo). | `<input … checked="checked"/>` |
| `small` / `is-small` / `[small]` | **Depreciado** (comentário "TODO: remover"): círculo de `--spacing-scale-2xh` (20px) e bolinha de 10px. | `<div class="br-radio small">` |
| `inverted` / `dark-mode` | Texto do label em `--color-dark` para uso em fundo escuro. | `<div class="br-radio inverted">` |
| Listagem horizontal | Não há classe `inline`; use utilitários: envolva cada radio em `<div class="d-inline-block mr-5">` (exemplo oficial). Dentro de modal o exemplo usa `d-block` + `mt-1`. | `<div class="d-inline-block mr-5"><div class="br-radio">…</div></div>` |
| `feedback` + `warning|danger|success|info` | Mensagem contextual do grupo, com `role="alert"` e ícone FA (`fas fa-exclamation-triangle`, `fas fa-times-circle`, `fas fa-check-circle`, `fas fa-info-circle`). | `<span class="feedback danger" role="alert">…</span>` |

## Estados e acessibilidade

- **CSS puro**: não existe `dist/components/radio/radio.js` nem `BRRadio`; o `core-init.js` não instancia nada para `.br-radio`. Os seletores `.br-radio input` que aparecem em `core-init.js` pertencem a `BRSelect`/`BRList`/`BRItem`, que usam radios internamente.
- **Estados** (designer): não selecionado (padrão), hover (`input:hover:not(:disabled) + label::before` com camada `--hover`), selecionado (`:checked`), foco (`input:focus-visible + label::before` recebe o anel de foco `focus-soft`), inválido, válido, desativado.
- **Teclado**: nativo do `<input type="radio">` — Tab entra no grupo, setas ↑/↓/←/→ trocam a opção, Espaço seleciona. Manter o mesmo `name` em todas as opções do grupo é o que cria a exclusividade e a navegação por setas.
- **ARIA**: `id`/`for` pareados em cada opção; agrupe com `fieldset`/`legend` (ou `role="radiogroup"` + `aria-labelledby`); radio sem texto precisa de `aria-label` no `input`; mensagem de erro com `role="alert"` e, idealmente, `aria-describedby` no input apontando para ela. Ícones decorativos com `aria-hidden="true"`.
- **Dependências**: nenhuma além de Font Awesome 5 para o ícone do feedback.

## Erros comuns

- Colocar o `label` antes do `input`, ou outro elemento entre eles: todo o desenho depende de `input + label::before/::after`, então o radio simplesmente não aparece.
- `id` do `input` diferente do `for` do `label` (ou `id` duplicado): o clique no texto deixa de selecionar e o círculo fica sem alvo.
- Opções do mesmo grupo com `name` diferentes: passam a ser selecionáveis simultaneamente e perdem a navegação por setas.
- Só a classe `disabled` no container sem o atributo `disabled` no `input` (continua clicável) — ou vice-versa (perde o visual).
- Tentar `inline`/`horizontal` como classe: não existe; use `d-inline-block mr-5` por item.
- Mensagem de feedback por opção em vez de uma por grupo, ou sem `role="alert"`.

## Fonte

- https://www.gov.br/ds/components/radio?tab=designer
- https://www.gov.br/ds/components/radio?tab=desenvolvedor
- https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/radio/radio.md
- https://docs-ds.estaleiro.serpro.gov.br/govbr-ds-core/docs/components/radio/radio-dev.md
- Local: `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/radio/examples.html`, `dist/components/radio/examples/*.html`, `src/components/radio/_mixins.scss`, `dist/core.css`, `dist/core-init.js`
