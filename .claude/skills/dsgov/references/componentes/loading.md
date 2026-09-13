# br-loading

## Quando usar / quando não usar
- Use para dar feedback durante processamento (envio de formulário, upload, carregamento de dados).
- **Indeterminado pequeno** (24px, padrão): dentro de/associado a componentes (botão, tabela, lista), pouca ênfase.
- **Indeterminado médio** (`medium`, 44px): no corpo da página ou bloqueando a tela (com `br-scrim`).
- **Determinado** (`data-progress`, 84px): quando se conhece a progressão 0–100%; pode ter botão Cancelar e rótulo.
- Não use para esperas instantâneas (< 300ms) nem substitua por ícones estáticos.

## HTML canônico
```html
<!-- Indeterminado pequeno (padrão) -->
<div class="br-loading" role="progressbar" aria-label="Carregando dados"></div>

<!-- Indeterminado médio -->
<div class="br-loading medium" role="progressbar" aria-label="Carregando página"></div>

<!-- Determinado (75%) -->
<div class="br-loading" role="progressbar" data-progress="75" aria-label="Enviando arquivo"
     aria-valuemin="0" aria-valuenow="75" aria-valuemax="100">
  <div class="br-loading-mask full">
    <div class="br-loading-fill"></div>
  </div>
  <div class="br-loading-mask">
    <div class="br-loading-fill"></div>
  </div>
</div>
```

## Variantes e modificadores
| classe/atributo | efeito | exemplo |
| --- | --- | --- |
| `.br-loading` | spinner via `::before` (borda 2px `--interactive`, animação `spinAround` 1.3s), tamanho `--loading-size` = 24px, `z-index: layer-4` | raiz |
| `.loading` | alias legado (compatibilidade; a remover) | evite |
| `.medium` | `--loading-size` = 44px, borda 4px | `class="br-loading medium"` |
| `[data-progress="N"]` (1–100) | modo determinado: 84px, anel de fundo `--border-color`, número `N%` no centro via `::after` (`content: attr(data-progress) "%"`), rotação estática por classe gerada | `data-progress="75"` |
| `.br-loading-mask` / `.br-loading-mask.full` | metades do anel (clip) | filhos obrigatórios no determinado |
| `.br-loading-fill` | preenchimento `--interactive` rotacionado `N*1.8deg` (animação `fill` 2s) | — |
| `.br-button.loading` | spinner dentro de botão (ver `button.md`); a regra de tamanho **não** se aplica a `.br-button` | — |
| `.br-modal-body.loading` | centraliza loading no corpo de modal (`min-height:160px`) | — |
| `--loading-indetermined-color` | token para trocar a cor do spinner | `style="--loading-indetermined-color: #fff"` |

Não há JS, `inverted` nem `small` explícito (o pequeno é o padrão).

## Estados e acessibilidade
- Sem JS: nenhuma classe `BRLoading`; para progresso, atualize `data-progress` e `aria-valuenow` via seu código.
- `role="progressbar"` e `aria-label` sempre; no determinado inclua `aria-valuemin/now/max`. Considere `aria-live="polite"` em um texto próximo ("Carregando…") para leitores de tela.
- Quando bloquear a tela use `br-scrim` e mova o foco para o loading ou impeça interação (`aria-busy="true"` no container).
- `data-progress` só aceita inteiros 1–100 (classes geradas `[data-progress="1"]…"100"`); `0` não tem rotação definida.

## Erros comuns
- Usar `data-progress` sem os dois `.br-loading-mask > .br-loading-fill`: aparece só o número sem anel (`:not(:empty)` controla o estilo).
- Aplicar `.small`: não existe; o pequeno é o padrão sem classe.
- Colocar `br-loading` dentro de `.br-button` esperando o tamanho 24px: a regra exclui `.br-button`; use `.br-button.loading`.
- Definir `width/height` na raiz: quebra o cálculo `calc(50% - size/2)` do `::before`.
- Esquecer `role`/`aria-label`: elemento vazio sem nome acessível.

## Fonte
- https://www.gov.br/ds/components/loading?tab=designer (markdown bruto: https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/loading/loading.md)
- https://www.gov.br/ds/components/loading?tab=desenvolvedor (SPA; markup dos exemplos locais)
- `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/loading/examples.html`
- `/opt/web/pca/node_modules/@govbr-ds/core/src/components/loading/_mixins.scss`, `_loading.scss`
