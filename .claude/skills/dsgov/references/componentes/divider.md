# br-divider

## Quando usar / quando não usar
- Use para separar seções de conteúdo quando o espaço em branco não for suficiente para indicar a separação.
- Use com moderação: deve ser visível, mas não competir com o conteúdo; prefira criar agrupamentos em vez de separar itens individualmente.
- Não use para circundar um item (use bordas) nem como elemento decorativo.
- Pode "sangrar" (sem margens) dentro de outros componentes (`br-list`, `br-card`, `br-footer`).
- Em fundo escuro use `inverted`/`dark-mode`; evite cores aleatórias.

## HTML canônico
```html
<p>Primeiro bloco de conteúdo.</p>
<span class="br-divider my-3"></span>
<p>Segundo bloco de conteúdo.</p>

<!-- Vertical: o pai precisa ser flex -->
<div class="d-flex">
  <p>Coluna A</p>
  <span class="br-divider vertical mx-3"></span>
  <p>Coluna B</p>
</div>
```

## Variantes e modificadores
| classe/atributo | efeito | exemplo |
| --- | --- | --- |
| `.br-divider` | `display:block`, `border-top: --divider-size (sm) solid --border-color` | `<span class="br-divider"></span>` |
| `hr` | recebe o mesmo estilo automaticamente, com `margin: 2x 0` | `<hr/>` |
| `.vertical` | `border-right` em vez de `border-top`, `align-self:stretch` (usar dentro de flex) | `class="br-divider vertical"` |
| `.dashed` | `border-style: dashed` | `class="br-divider dashed"` |
| `.sm` / `.md` / `.lg` | espessura `--surface-width-sm/md/lg` | `class="br-divider md"` |
| `.inverted` / `.dark-mode` | linha branca (`--border-color: --pure-0`) para fundo escuro | `class="br-divider inverted"` |
| `.content` | divisor com texto central: `display:flex`, pseudo-elementos `::before/::after` fazem as linhas | `<div class="br-divider content">ou</div>` |
| `.vertical.content` | idem em coluna | — |
| utilitários `my-3`, `mx-3`, `d-md-none` | espaçamento/visibilidade (usados nos exemplos e no footer) | `class="br-divider my-3"` |

Não há JS nem estados (hover/focus/disabled).

## Estados e acessibilidade
- Sem JS: nenhuma classe `BRDivider`; nada a instanciar.
- Elemento puramente visual: use `<span>` (ou `<hr>` quando houver separação semântica de seções). Leitores de tela ignoram o `span`; o `hr` é anunciado como separador.
- Se usar `<div class="br-divider">` dentro de listas com `role="list"`, ele fica entre `listitem`s sem role — aceitável, mas prefira `span`.
- Contraste: em fundo escuro use `inverted` para manter a linha visível.

## Erros comuns
- `vertical` fora de um container `display:flex`: a linha não aparece (`align-self:stretch` sem altura).
- Definir `height`/`border` manualmente: sobrescreve `--divider-size` e a cor do DS.
- Usar `<hr class="br-divider">` esperando margens zero: `hr` traz `margin: 2x 0` próprio.
- Esquecer `d-md-none` nos dividers de sub-listas do footer (o layout desktop já separa as colunas).
- Usar `.content` sem texto: as duas linhas ficam com um espaço vazio no meio.

## Fonte
- https://www.gov.br/ds/components/divider?tab=designer (markdown bruto: https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/divider/divider.md)
- https://www.gov.br/ds/components/divider?tab=desenvolvedor (SPA; markup dos exemplos locais)
- `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/divider/examples.html`
- `/opt/web/pca/node_modules/@govbr-ds/core/src/components/divider/_mixins.scss`, `_divider.scss`
