# br-textarea

Campo de texto multilinhas do Design System gov.br, @govbr-ds/core 3.7.0. Comportamento (contador de caracteres) em `dist/components/textarea/textarea.js` (classe `BRTextArea`, exportada como `core.BRTextarea`), instanciado automaticamente por `core-init.js` para todo `.br-textarea`.

## Quando usar / quando não usar

- Use quando a entrada textual for relativamente longa e exigir múltiplas linhas; para uma linha use `br-input`.
- Dimensione a área próximo ao tamanho esperado do texto; em grid de 4 colunas (mobile) ocupe toda a largura e mantenha tamanho fixo.
- Label no topo por padrão; posicionamento à esquerda é alternativa, mas mantenha o mesmo padrão em toda a página.
- Placeholder deve trazer informação mais completa que o label (ex.: formato esperado); texto auxiliar complementa quando label e placeholder não bastam.
- Feedback de erro/sucesso/alerta/informação vem pelo elemento `.feedback` (mesma anatomia do `br-input`), nunca só pela cor da borda.

## HTML canônico

```html
<div class="br-textarea">
  <label for="textarea-justificativa">Justificativa</label>
  <textarea id="textarea-justificativa" aria-controls="textarea-justificativa-limite" placeholder="Descreva o motivo da solicitação" maxlength="300"></textarea>
  <div class="text-base mt-1"><span class="limit" aria-live="polite">Limite máximo de <strong>300</strong> caracteres</span><span class="current" aria-live="polite" role="status" id="textarea-justificativa-limite"></span></div>
</div>
```

Versão simples (sem contador): substitua o último `div` por `<p class="text-base mt-1">Texto auxiliar ao preenchimento.</p>`.

## Variantes e modificadores

| Classe/atributo | Efeito | Exemplo |
| --- | --- | --- |
| `br-textarea` | Container; `label` em bloco com `margin-bottom: var(--spacing-scale-half)`; `textarea` com fundo `--background-light`, borda 1px `--border-color-alternative`, `border-radius: 6px`, `font-size: var(--font-size-scale-up-01)` medium, `width: 100%`, padding `--textarea-padding` | `<div class="br-textarea">…</div>` |
| `small` ou `[data-small]` | Densidade alta: padding `--spacing-scale-base` | `<div class="br-textarea small">` |
| `medium` ou `[data-medium]` | Densidade média (padrão): padding `--spacing-scale-baseh` | `<div class="br-textarea medium">` |
| `large` ou `[data-large]` | Densidade baixa: padding `--spacing-scale-2x` | `<div class="br-textarea large">` |
| `success` / `danger` / `warning` / `info` (ou `[data-success]` etc.) | Borda do `textarea` com 2px na cor do estado (`var(--success)`, `var(--danger)`, `var(--warning)`, `var(--info)`) | `<div class="br-textarea danger">` |
| `span.feedback.success|danger|warning|info` + `role="alert"` | Mensagem de feedback abaixo do campo, com ícone FA5: `fas fa-check-circle` (sucesso), `fa-times-circle` (erro), `fa-exclamation-triangle` (alerta), `fa-info-circle` (informação) | `<span class="feedback danger" role="alert"><i class="fas fa-times-circle" aria-hidden="true"></i><span>Campo com erro</span></span>` |
| `disabled` no `textarea` | Regra global `[disabled] { opacity: var(--disabled); cursor: not-allowed }`; exemplo oficial acompanha `feedback warning` "Campo desabilitado" | `<textarea id="t7" disabled="disabled"></textarea>` |
| `dark-mode` ou `inverted` | Label e container em `--color-dark`, foco `--focus-color-dark`, texto do `textarea` em `--color-light`; usar sobre fundo escuro (`bg-gray-60`, `p-3`) | `<div class="p-3 bg-gray-60"><div class="br-textarea dark-mode">…` |
| `p.text-base.mt-1` | Texto auxiliar abaixo do campo (utilitários de tipografia e margem) | `<p class="text-base mt-1">Texto auxiliar ao preenchimento.</p>` |
| `maxlength` + `.limit` + `.current` | Contador **com limite**: o JS reescreve `.limit` ("Limite máximo de N caracteres") e `.current` ("Restam N caracteres") | ver HTML canônico |
| `.characters` (sem `maxlength`) | Contador **sem limite**: o JS reescreve com "N caracteres digitados" | `<div class="text-base mt-1"><span class="characters" aria-live="assertive"><strong>0</strong> caracteres digitados</span></div>` |
| Label à esquerda | Não há classe própria: usa grid `row` > `col-auto pt-half` (label) + `col` (textarea e texto auxiliar) dentro do `.br-textarea` | `<div class="br-textarea"><div class="row"><div class="col-auto pt-half"><label for="t">Label</label></div><div class="col"><textarea id="t"></textarea></div></div></div>` |

`limit`, `current` e `characters` são apenas ganchos de JS (não há regras CSS para elas em `core.css`).

## Estados e acessibilidade

- Inicialização automática: `core-init.js` executa `new BRTextArea('br-textarea', el)` para cada `.br-textarea`. Com `core.min.js`: `new core.BRTextarea('br-textarea', el)` (a documentação escreve `BRTextArea`; o export em `core.js` é `BRTextarea`). O construtor exige um `<textarea>` dentro do container.
- O que o JS faz: em `keyup` no container e `focus` no `textarea`, lê `textarea.textLength` e `maxlength`; se existe `.characters` escreve "N caracteres digitados"; senão, se existe `.limit`/`.current`, escreve "Restam N caracteres" em `.current` e restaura "Limite máximo de N caracteres" em `.limit` quando o campo volta a zero.
- `label for` + `id` obrigatórios. Para o contador com limite use `aria-controls` no `textarea` apontando ao `id` do `.current` (que tem `role="status"` e `aria-live="polite"`).
- Foco: `focus-soft` no `textarea` (`:focus`, `:focus-visible`, `.focus-visible`); hover escurece a borda/texto (`hover("color")`).
- Feedback com `role="alert"`; a borda colorida (classe de estado no container) deve vir acompanhada do `.feedback` correspondente.
- Redimensionamento é o nativo do navegador; para tamanho fixo use `style="resize: none"` (não há utilitário próprio).
- Nenhum evento customizado; use `input`/`change` nativos.

## Erros comuns

- Colocar a classe de estado (`danger`, `small`, `dark-mode`) no `textarea` em vez do container `.br-textarea`: os seletores são `.br-textarea.danger textarea`.
- Usar `.feedback` fora do `.br-textarea` ou sem `role="alert"`; ou usar `br-message` no lugar do `.feedback` inline.
- Contador com `maxlength` mas sem `.limit`/`.current` (ou com `.characters` junto): o JS prioriza `.characters` e ignora o limite.
- Esquecer o `<strong>` no texto inicial do contador ou escrever texto próprio: o JS sobrescreve o `innerHTML` com o formato dele ("Restam **N** caracteres").
- Instanciar o componente em um `.br-textarea` sem `<textarea>`: `_setKeyup` lança erro (querySelector null).
- Label à esquerda sem `pt-half` no `col-auto`: o label desalinha do topo do campo.

## Fonte

- https://www.gov.br/ds/components/textarea?tab=designer
- https://www.gov.br/ds/components/textarea?tab=desenvolvedor
- https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/textarea/textarea.md
- https://docs-ds.estaleiro.serpro.gov.br/govbr-ds-core/docs/components/textarea/textarea-dev.md
- Local: `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/textarea/examples.html`, `dist/components/textarea/examples/*.html`, `dist/components/textarea/textarea.js`, `src/components/textarea/_mixins.scss`, `dist/core-init.js`, `dist/core.css`
