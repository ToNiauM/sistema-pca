# br-tooltip

Alerta flutuante (tooltip e popover) do Design System gov.br, @govbr-ds/core 3.7.0. Depende do vendor **Popper.js** (embutido em `core.js`). Comportamento em `dist/components/tooltip/tooltip.js` (classe `BRTooltip`), instanciado automaticamente por `core-init.js` para todo `.br-tooltip`. Existe também o **utilitário JS Tooltip** (`dist/partial/js/behavior/tooltip.js`) acionado por `data-tooltip-text`/`data-tooltip-target`.

Aviso da documentação oficial: o componente está marcado como **obsoleto/depreciado** ("mantido apenas para compatibilidade"); a recomendação é migrar para o utilitário JS Tooltip.

## Quando usar / quando não usar

- Use para agregar detalhes a elementos da interface ou exibir informação que não precisa estar visível de imediato (explicar ícone, dar feedback de ação).
- Tipo padrão: aparece no `mouseover`/foco, texto curto e conciso. Tipo popover: fica visível até ser fechado, aceita título, imagem, ícone, botão ou link.
- Não use o título sozinho como texto informativo; não confie só na cor (informativo/sucesso/alerta/erro) para transmitir o significado.
- Um tooltip por vez na tela; uso excessivo irrita. Se for preciso explicar um fluxo, prefira tutorial ou guia interativo.
- Em mobile (4 colunas) não há mouseover: acionamento só por clique/foco; ofereça sempre alternativa de acesso ao conteúdo do popover.

## HTML canônico

O `.br-tooltip` deve vir **imediatamente após** o elemento ativador (o JS usa `component.previousSibling.previousSibling`, isto é, o irmão anterior de elemento):

```html
<div class="mb-3">
  <a class="h5" href="javascript:void(0);">Informação</a>
  <div class="br-tooltip" role="tooltip" info="info" place="top"><span class="text" role="tooltip">Fulano de Tal da Silva</span><span class="subtext">Diretor Presidente</span></div>
</div>
```

Popover com fechar (o botão `.close` com `fas fa-times` e a `.arrow` são criados pelo JS):

```html
<div class="mb-3">
  <a class="h5" href="javascript:void(0);">Cadastro</a>
  <div class="br-tooltip" role="tooltip" success="success" popover="popover" timer="5000" place="bottom">
    <div class="popover-header"><span class="text">Cadastro concluído!</span></div>
    <div class="popover-body"><span class="subtext">Para verificar mais detalhes a respeito do seu acesso, clique no link abaixo.</span></div>
    <div class="popover-footer"><a class="link" href="javascript:void(0)">Clique aqui</a></div>
  </div>
</div>
```

## Variantes e modificadores

| Classe/atributo | Efeito | Exemplo |
| --- | --- | --- |
| `br-tooltip` + `role="tooltip"` | Balão `position: absolute`, `max-width: 240px`, padding `--spacing-scale-2x`, `border-radius: 4px`, sombra, `opacity: 0; visibility: hidden` até receber `data-show`; fundo padrão `--color-info` | `<div class="br-tooltip" role="tooltip">` |
| `info="info"` (ou omitido) | Fundo e seta `var(--color-info)` (`--blue-warm-vivid-60`) | `<div class="br-tooltip" info="info">` |
| `success="success"` | Fundo e seta `var(--color-success)` | `<div class="br-tooltip" success="success">` |
| `warning="warning"` | Fundo e seta `var(--color-warning)`, texto escuro | `<div class="br-tooltip" warning="warning">` |
| `error="error"` | Fundo e seta `var(--color-danger)` | `<div class="br-tooltip" error="error">` |
| `place="top|right|bottom|left"` | Posição via Popper (padrão `top`; `right`/`left` caem para `top` se não couber na viewport) | `<div class="br-tooltip" place="right">` |
| `timer="MS"` | Oculta automaticamente após MS milissegundos | `<div class="br-tooltip" timer="10000">` |
| `active="active"` | Lido pelo construtor (`this.active`) para indicar exibição no carregamento; em 3.7.0 o `BRTooltip` só armazena o valor (não chama `_show`) | `<div class="br-tooltip" active="active" timer="10000">` |
| `popover="popover"` | Tipo popover: `max-width: 320px; min-width: 240px`, botão `.close` gerado pelo JS; fecha só pelo botão (não em `mouseleave`/`blur`) | `<div class="br-tooltip" popover="popover">` |
| `span.text` | Texto principal: `--font-size-scale-base` semi-bold | `<span class="text" role="tooltip">Título</span>` |
| `span.subtext` | Texto secundário: `--font-size-scale-down-01` medium | `<span class="subtext">Detalhe</span>` |
| `a.link` | Link dentro do popover, sublinhado, alinhado à direita | `<a class="link" href="…">Clique aqui</a>` |
| `popover-header` / `popover-body` / `popover-footer` | Cabeçalho (centralizado, `min-width: 180px`), corpo (`--font-size-scale-down-01`) e rodapé (centralizado; botões/links) | `<div class="popover-footer"><button class="br-button primary" type="button"><span>Atualizar</span></button></div>` |
| `popover-image` + `div` irmão | Imagem à esquerda (`max-width: 45%`, borda 3px branca) e coluna de texto (`width: 65%`) | `<div class="popover-image"><img src="…" alt="Avatar"/></div><div class="div"><div class="popover-header">…</div><div class="popover-body">…</div></div>` |
| `popover-icon` + `div` irmão | Ícone grande à esquerda (`fas fa-ban fa-3x`, `fa-exclamation-triangle fa-3x`) e coluna de texto | `<div class="popover-icon"><i class="fas fa-ban fa-3x" aria-hidden="true"></i></div><div class="div">…</div>` |
| `.arrow` / `[data-popper-arrow]` | Seta de 8px gerada pelo JS; posicionada por `[data-popper-placement^=top|bottom|left|right] > .arrow` | gerado automaticamente |
| `[data-show]` | Estado visível (adicionado pelo JS): `opacity: 1; visibility: visible` com animação `fadeInOpacity` 0.5s | gerado automaticamente |
| `.br-tooltip.br-notification` | Modo notificação (usado pelo `br-header`): `strategy: fixed`, posição abaixo do ativador, atributo `notification` adicionado pelo JS | uso interno |
| Utilitário: `data-tooltip-text="…"` no ativador | O `core-init.js` cria um `.br-tooltip.sample` com o texto (`place` top, tipo info) via `partial/js/behavior/tooltip.js`; não requer markup do balão | `<a href="#" data-tooltip-text="Texto de Informação!"><img src="…" alt="Avatar"/></a>` |
| Utilitário: `data-tooltip-target="#id"` + `.br-tooltip.utilities[data-toggle="tooltip"]` | Ativador aponta para um balão existente; a classe `utilities` só marca o balão para o `core-init.js` não instanciar `BRTooltip` duas vezes (não há CSS para `.utilities` nem `.sample`) | `<a href="#" data-tooltip-target="#dica"> … <div class="br-tooltip utilities" id="dica" role="tooltip" data-toggle="tooltip" info="info" place="top"><span class="text">…</span></div>` |

Os exemplos oficiais usam os atributos duplicados (`info="info"`, `popover="popover"`); o CSS seleciona por presença do atributo (`[popover]`, `[success]`, …), então `<div class="br-tooltip" popover success>` também funciona (forma usada na doc de desenvolvedor).

## Estados e acessibilidade

- Inicialização automática: `core-init.js` faz `new BRTooltip('br-tooltip', el)` para cada `.br-tooltip`; a doc recomenda excluir os do utilitário: `document.querySelectorAll('.br-tooltip:not(.utilities)')`. Com `core.min.js`: `new core.BRTooltip('br-tooltip', el)`.
- Ativador = irmão anterior do `.br-tooltip`. O JS registra `mouseenter`, `click` e `focus` para mostrar e `mouseleave`/`blur` para esconder (exceto popover, que só fecha pelo `.close`). Mostrar = `display: unset`, `data-show`, `z-index: 99`, `visibility: visible`; esconder = remove `data-show`, `z-index: -1`, `visibility: hidden`.
- Popover: o JS injeta `<button type="button" class="close"><i class="fas fa-times"></i></button>` sem `aria-label`; adicione texto acessível por CSS/JS próprio se necessário. Ao fechar, alterna `fa-angle-down`/`fa-angle-up` em `button svg` do ativador (uso com dropdowns) e o atributo `active` do ativador.
- ARIA: `role="tooltip"` no balão (exemplos oficiais também repetem em `span.text`). Para associar ao ativador use `aria-describedby="ID"` apontando ao balão; o JS não faz isso. Ativador deve ser focável (`a`, `button`) para funcionar por teclado (`Tab` mostra, `Shift+Tab`/perda de foco esconde).
- O `BRTab` esconde todos os `.br-tooltip` da página ao perder o foco em um botão de aba.
- Nenhum evento customizado é disparado.

## Erros comuns

- Colocar o `.br-tooltip` antes do ativador, ou separado dele por outro elemento: `previousSibling.previousSibling` aponta para o elemento errado (ou `null`, gerando erro em `addEventListener`).
- Ativador não focável (`span`, `div`) sem `tabindex`: tooltip só abre com mouse.
- Esquecer `popover="popover"` (ou `popover`) em conteúdo rico: o balão fecha no `mouseleave` antes do usuário clicar no botão/link.
- Colocar `place` inválido (ex.: `place="up"`): cai para `top` silenciosamente.
- Usar `type="success"` ou classe `.success` em vez do atributo `success`: o CSS do tooltip só reconhece atributos.
- Adicionar manualmente `.arrow` ou `.close`: o JS acrescenta outra seta (`data-popper-arrow`) e outro botão.
- Instanciar `BRTooltip` para balões do utilitário (`.utilities`) além do `core-init.js`: listeners duplicados.

## Fonte

- https://www.gov.br/ds/components/tooltip?tab=designer
- https://www.gov.br/ds/components/tooltip?tab=desenvolvedor
- https://www.gov.br/ds/utilitarios/js/tooltip
- https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/tooltip/tooltip.md
- https://docs-ds.estaleiro.serpro.gov.br/govbr-ds-core/docs/components/tooltip/tooltip-dev.md
- https://docs-ds.estaleiro.serpro.gov.br/govbr-ds-core/docs/components/tooltip/tooltip.md (aviso de depreciação e dependência Popper)
- Local: `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/tooltip/examples.html`, `dist/components/tooltip/examples/*.html`, `dist/components/tooltip/tooltip.js`, `dist/util/tooltip/examples.html`, `dist/partial/js/behavior/tooltip.js`, `src/components/tooltip/_mixins.scss`, `dist/core-init.js`, `dist/core.css`
