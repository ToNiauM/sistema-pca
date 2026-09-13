# br-tag

Etiqueta (sinalizador de status, quantidade, categoria ou informação curta) do Design System gov.br, @govbr-ds/core 3.7.0. Comportamento em `dist/components/tag/tag.js` (classe `BRTag`), instanciado automaticamente por `core-init.js` para todo `.br-tag`.

## Quando usar / quando não usar

- Use para informar, rotular, chamar atenção ou categorizar itens com palavras-chave, ícones ou cores; o label deve ser adjetivo ou substantivo (nunca verbo), de preferência uma só palavra e uma só cor por tag.
- Cinco tipos: interação (dispensável com botão fechar, ou persistente selecionável), texto, status, contagem e ícone. Somente a tag de interação é clicável e tem estados.
- Não misture tags de interação com tags estáticas no mesmo grupo, nem dispensáveis com persistentes; evite tags de interação ao lado de botões.
- Tags de ícone, de status sem label e de contagem acima de 999 (`999+`) exigem tooltip com a informação completa.
- Altura fixa: nunca duas linhas; texto acima de 100 caracteres deve ser truncado com reticências (e tooltip).

## HTML canônico

Tag de texto com ícone (variante mais comum):

```html
<span class="br-tag bg-mint-cool-vivid-70" aria-describedby="tag-situacao"><i class="fas fa-check" aria-hidden="true"></i><span id="tag-situacao">Homologado</span></span>
```

Tag de interação dispensável (com botão fechar acionado por `data-dismiss`):

```html
<span class="br-tag interaction" id="tag-filtro-01"><i class="fas fa-car" aria-hidden="true"></i><span id="tag-filtro-01-label">Carro</span>
  <button class="br-button inverted circle" type="button" aria-label="Fechar" aria-describedby="tag-filtro-01-label" data-dismiss="tag-filtro-01"><i class="fas fa-times" aria-hidden="true"></i></button>
</span>
```

## Variantes e modificadores

| Classe/atributo | Efeito | Exemplo |
| --- | --- | --- |
| `br-tag` (tag de texto) | `inline-flex`, fundo `--background-dark`, texto `--color-dark`, `border-radius: var(--surface-rounder-sm)`, `font-size: var(--font-size-scale-base)` medium, altura `--tag-size` (médio = `--spacing-scale-3xh`), padding horizontal `--spacing-scale-baseh`; ícone `<i>` como primeiro filho ganha `margin-right`; tags adjacentes ganham `margin-left: var(--spacing-scale-half)` | `<span class="br-tag bg-violet-warm-vivid-70"><span>Texto</span></span>` |
| `bg-*` (utilitário de cor) | Define a cor da superfície; exemplos oficiais usam `bg-danger`, `bg-warning`, `bg-success`, `bg-orange-vivid-50`, `bg-green-warm-vivid-50`, `bg-indigo-warm-vivid-50`, `bg-magenta-vivid-50`, `bg-orange-50`, `bg-violet-warm-vivid-70`, `bg-mint-cool-vivid-70` | `<span class="br-tag bg-danger">` |
| `success` / `danger` / `warning` / `info`, também `is-success` e `[success]` | Fundo `var(--success)` etc. (mixin `tag-colors`) | `<span class="br-tag is-warning">` |
| `is-primary` e demais chaves de `$br-colors` (`.is-<cor>`, `.<cor>`, `[<cor>]`) e `support-01`…`support-11` | Cores legadas do mixin `tag-colors`; `support-NN` só define `--tag-background` (não é aplicado a `background` pelo CSS) | `<span class="br-tag is-primary">` |
| `interaction` | Tag de interação dispensável: fundo `var(--interactive)`, `font-size: var(--font-size-scale-up-01)`, alturas maiores (`4x`/`5x`/`5xh`); o `.br-button` interno vira circular de `--spacing-scale-3xh` com hover/pressed | `<span class="br-tag interaction" id="t1">…<button class="br-button" data-dismiss="t1">…</button></span>` |
| `data-dismiss="ID"` (no botão interno) | O JS remove do DOM o elemento `#ID` ao clicar | `<button class="br-button circle inverted" type="button" aria-label="Fechar" data-dismiss="t1">` |
| `.br-button.close` (dentro da tag) | Alternativa legada: o JS remove a tag mais próxima ao clicar em qualquer ponto dela | `<button class="br-button close" type="button">` |
| `interaction-select` | Tag persistente (selecionável): container transparente, `input` (checkbox ou radio) invisível seguido de `label` estilizado como tag interativa, `cursor: pointer`, foco no `label` via `input:focus + label` | `<span class="br-tag interaction-select"><input id="tag01" type="checkbox" name="opcoes" value="a"/><label for="tag01"><i class="fas fa-bicycle" aria-hidden="true"></i><span>Bicicleta</span></label></span>` |
| `interaction-select.selected` | Estado selecionado: fundo `var(--selected)`, `padding-right` extra e "check" desenhado em `label::after`; o JS adiciona/remove `selected` conforme o `input` | `<span class="br-tag interaction-select selected"><input … checked="checked"/>…` |
| `input[type="radio"]` na `interaction-select` | Seleção única: o JS desmarca as demais tags com o mesmo `name` | `<input id="tag04" type="radio" name="veiculo" value="carro"/>` |
| `disabled` (classe) + `disabled` no input | Regra global `.disabled { opacity: var(--disabled); cursor: not-allowed }`; o input recebe `cursor: not-allowed` | `<span class="br-tag interaction-select selected disabled"><input … disabled="disabled" checked="checked"/>` |
| `status` | Bolinha de status: círculo (`border-radius: 50%`), borda 1px `--background-light`, sem padding; tamanhos `baseh`/`2x`/`3x` | `<span class="br-tag status bg-success small" title="Online"></span>` |
| `count` | Contador: pílula (`border-radius: 100em`), borda 1px, padding horizontal `--spacing-scale-base`; tamanhos `2xh`/`3x`/`3xh` | `<span class="br-tag count bg-danger" title="10 notificações não lidas"><span aria-hidden="true">10</span></span>` |
| `icon` | Tag só com ícone: círculo, ícone em `--icon-size-base` sem margem; tamanhos `3xh`/`4x`/`5xh` | `<span class="br-tag icon bg-magenta-vivid-50" title="Ícone de Carro"><i class="fas fa-car" aria-hidden="true"></i></span>` |
| `small` / `medium` / `large` | Densidade alta / padrão / baixa: troca `--tag-size` para `--tag-small`/`--tag-medium`/`--tag-large` (valores dependem do tipo, ver acima) | `<span class="br-tag small">` |

Ícones Font Awesome 5 usados nos exemplos oficiais: `fas fa-car`, `fa-search`, `fa-user`, `fa-bicycle`, `fa-ship`, `fa-times` (fechar). A classe `text` **não** existe no CSS: a tag de texto é a `br-tag` sem modificador de tipo.

## Estados e acessibilidade

- Inicialização automática: `core-init.js` faz `new BRTag('br-tag', el)` para cada `.br-tag`. Com `core.min.js` puro: `new core.BRTag('br-tag', el)`.
- O que o JS faz: (1) em `interaction-select`, se o `input` tem `checked` adiciona `selected` e, no `change`, alterna o atributo `checked` e a classe `selected` (desmarcando os irmãos de mesmo `name` se for radio); (2) `[data-dismiss="ID"]` remove `#ID`; (3) `.br-button.close` remove a própria tag.
- Tags de texto/status/contagem/ícone não são interativas: use `title` **ou** `aria-describedby` apontando para o `span` do texto (padrão dos exemplos). Em `count`, o número visível leva `aria-hidden="true"` e o `title` traz a frase completa ("10 Notificações não lidas").
- Tag dispensável: botão com `aria-label="Fechar"` e `aria-describedby` apontando ao `id` do label da tag. Teclado: `Tab` foca o botão, `Enter`/`Espaço` remove.
- Tag persistente: o foco fica no `input` oculto e é desenhado no `label` (`outline` com tokens `--focus-*`). `Espaço` alterna (checkbox) ou seleciona (radio). Só a tag de interação tem hover/pressed/foco; quando há botão fechar, esses estados ocorrem no botão.
- Nenhum evento customizado é disparado; ouça `change` do input (persistente) ou observe a remoção do nó (dispensável).

## Erros comuns

- Usar `<div class="br-tag text">` esperando um tipo "texto": `text` não existe no CSS; basta `br-tag` + cor.
- Esquecer o `label for` na `interaction-select` ou colocar o texto fora do `label`: o clique não seleciona e o check em `label::after` não aparece.
- Marcar `selected` manualmente sem `checked` no input (ou vice-versa): o JS sincroniza a partir do atributo `checked`, e o estado visual diverge do valor enviado no formulário.
- `data-dismiss` apontando para um `id` inexistente ou diferente do `id` da tag: o botão não remove nada.
- Colocar a cor com `style` ou classes de texto (`text-*`) em vez de `bg-*`; ou usar mais de uma cor/linha por tag.
- Tag de ícone, de status sem label ou `999+` sem `title`/tooltip: informação inacessível.
- Empilhar `br-tag` em uma `div` sem `d-flex align-items-center`: o espaçamento `& + &` funciona, mas o alinhamento vertical entre tamanhos diferentes se perde.

## Fonte

- https://www.gov.br/ds/components/tag?tab=designer
- https://www.gov.br/ds/components/tag?tab=desenvolvedor
- https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/tag/tag.md
- https://docs-ds.estaleiro.serpro.gov.br/govbr-ds-core/docs/components/tag/tag-dev.md
- Local: `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/tag/examples.html`, `dist/components/tag/examples/*.html`, `dist/components/tag/tag.js`, `src/components/tag/_mixins.scss`, `dist/core.css`
