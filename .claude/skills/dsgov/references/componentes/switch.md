# br-switch

Controle interruptor (liga/desliga) do Design System gov.br, versão @govbr-ds/core 3.7.0. Componente **somente CSS**: não existe `dist/components/switch/switch.js`, nenhuma classe `BRSwitch` é exportada em `core.js` e `core-init.js` não o instancia. Todo o comportamento vem do `<input type="checkbox">` nativo.

## Quando usar / quando não usar

- Use para alternar rapidamente entre **dois estados** (ligado/desligado, concordo/discordo) cujo efeito é **imediato**, sem botão "Salvar" ou "Enviar" (ex.: preferências e configurações).
- Não use em formulários longos com outros campos que dependem de um botão "Enviar": o usuário fica em dúvida se a alternância já teve efeito. Nesses casos prefira `br-checkbox`.
- Rótulos (`switch-data`) devem ser curtos (até três termos), sempre em pares (nunca só para um estado) e sempre na mesma posição; reserve espaço para o rótulo mais longo para o componente não "pular".
- Quando vários switches formam um grupo, associe-os a um `br-checkbox` principal (selecionar/desselecionar todos, estado intermediário).
- Em dispositivos touch prefira a densidade baixa (`large`), que tem maior área de toque.

## HTML canônico

```html
<div class="br-switch" role="presentation">
  <input id="switch-notificacoes" type="checkbox" name="switch-notificacoes" role="switch" checked="checked"/>
  <label for="switch-notificacoes">Receber notificações por e-mail</label>
  <div class="switch-data" data-enabled="Ligado" data-disabled="Desligado"></div>
</div>
```

Ordem obrigatória dos filhos: `input` → `label` → (opcional) `.switch-data`. O CSS depende dos seletores `input + label` e `input ~ .switch-data`.

## Variantes e modificadores

| Classe/atributo | Efeito | Exemplo |
| --- | --- | --- |
| `br-switch` (padrão, label à esquerda) | Container `inline-flex`; trilho de 52×30px (médio) desenhado em `label::before`, chave de 22px em `label::after`, à direita do texto do label | `<div class="br-switch" role="presentation">…</div>` |
| `right` | Label à direita do trilho (`padding-left` no label, trilho em `left: 0`) | `<div class="br-switch right">` |
| `top` | Label acima do trilho (`min-height` dobra, trilho em `bottom: 0; left: 0`) | `<div class="br-switch top">` |
| `small` | Densidade alta: trilho 40×24px, chave 16px, ícone `--icon-size-xs` | `<div class="br-switch small">` |
| `medium` | Densidade média (igual ao padrão): 52×30px, chave 22px, ícone `--icon-size-sm` | `<div class="br-switch medium">` |
| `large` | Densidade baixa: trilho 64×36px, chave 28px, ícone `--icon-size-base` | `<div class="br-switch large">` |
| `icon` | Desenha ícone Font Awesome 5 dentro da chave: `\f00d` (fa-times) desligado, `\f00c` (fa-check) ligado; fonte "Font Awesome 5 Free" peso black | `<div class="br-switch icon">` |
| `.switch-data` + `data-enabled` / `data-disabled` | Rótulo textual ao lado do trilho via `content: attr(...)`: mostra `data-disabled` desmarcado e `data-enabled` marcado | `<div class="switch-data" data-enabled="Ligado" data-disabled="Desligado"></div>` |
| `disabled` (classe no container) + `disabled` no input | Regra global `.disabled { cursor: not-allowed; opacity: var(--disabled) }` e `.disabled * { pointer-events: none }`; hover/active só se aplicam a `input:not([disabled])` | `<div class="br-switch disabled"><input … disabled="disabled"/>…` |
| `inverted` ou `dark-mode` | Texto do label e do container em `--color-dark` (para fundos escuros) | `<div class="br-switch dark-mode">` |
| `checked="checked"` no input | Chave vai para a direita e assume `--on` (`--blue-warm-vivid-40`); desmarcado usa `--off` (`--gray-20`) | `<input … checked="checked"/>` |

Não existe classe `.br-switch.disabled` específica no `core.css`; o exemplo oficial usa a classe `disabled` no container (regra global) **e** o atributo `disabled` no input.

## Estados e acessibilidade

- Use `role="presentation"` no container e `role="switch"` no `<input type="checkbox">` (é o padrão dos exemplos oficiais). O estado é lido pelo leitor de tela a partir de `checked`.
- `id` no input e `for` no label são obrigatórios: o input tem `opacity: 0; position: absolute`, então o label é o único alvo clicável. Label vazio (`label:empty`) é aceito pelo CSS (reduz o padding), mas nesse caso forneça `aria-label` no input.
- Teclado: nativo do checkbox — `Tab` foca, `Espaço` alterna. O foco visível é desenhado em `label::before` via `input:focus-visible + label` (mixin `focus-soft`).
- Hover e pressionado: gradiente sobre o trilho com `--hover`/`--pressed`, somente quando `input:not([disabled])`.
- Nenhum JavaScript é necessário. `core-init.js` não faz nada com `.br-switch`, e `core.js` não expõe `core.BRSwitch`. Ouça o evento nativo `change` do input se precisar reagir.

## Erros comuns

- Colocar o `label` antes do `input`: os seletores `input + label` e `input:checked + label::after` deixam de casar e o trilho não aparece.
- Esquecer `for`/`id`: como o input é invisível, o usuário não consegue alternar clicando.
- Usar `<span>` ou outro elemento em vez de `.switch-data` com `data-enabled`/`data-disabled`, ou colocar texto dentro dele (o texto vem de `::before`, o elemento deve ficar vazio).
- Aplicar `small`/`large` no `input` ou no `label` em vez do container `.br-switch`.
- Usar rótulo para apenas um estado ou trocar a posição do rótulo entre componentes da mesma tela (diretriz de design).
- Colocar `disabled` só na classe do container sem o atributo no input: visualmente esmaece, mas o checkbox continua alterável por teclado.

## Fonte

- https://www.gov.br/ds/components/switch?tab=designer
- https://www.gov.br/ds/components/switch?tab=desenvolvedor
- https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/switch/switch.md
- https://docs-ds.estaleiro.serpro.gov.br/govbr-ds-core/docs/components/switch/switch-dev.md
- Local: `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/switch/examples.html`, `dist/components/switch/examples/*.html`, `src/components/switch/_mixins.scss`, `dist/core.css`
