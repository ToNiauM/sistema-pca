# br-card

## Quando usar / quando não usar
- Use para agrupar conteúdo coeso sobre **um único assunto** (texto, mídia, ações) de forma escaneável, com hierarquia clara: título no topo, conteúdo no centro, ações (botões/ícones) no rodapé.
- Um card é independente e individual: **não coloque card dentro de card**, não mescle nem divida cards.
- Conteúdo limitado: só o essencial, com caminho para detalhes (expansão, link). Um card **nunca deve ter rolagem interna** na regra de design (a variante `h-fixed` existe no CSS, use com parcimônia).
- Estados permitidos: hover (`.hover`), desabilitado (`.disabled`) e arrastando.
- Não use como container genérico de layout/página (use grid/`container`) nem como substituto de `br-list` para listas longas.

## HTML canônico
```html
<div class="br-card">
  <div class="card-header">
    <div class="d-flex">
      <span class="br-avatar mt-1" title="Maria Amorim">
        <span class="content"><img src="/img/maria.jpg" alt="Foto de Maria Amorim"/></span>
      </span>
      <div class="ml-3">
        <div class="text-weight-semi-bold text-up-02">Maria Amorim</div>
        <div>UX Designer</div>
      </div>
      <div class="ml-auto">
        <button class="br-button circle" type="button" aria-label="Mais opções">
          <i class="fas fa-ellipsis-v" aria-hidden="true"></i>
        </button>
      </div>
    </div>
  </div>
  <div class="card-content">
    <p>Texto principal do card, curto e objetivo.</p>
  </div>
  <div class="card-footer">
    <div class="d-flex">
      <div>
        <button class="br-button" type="button">Ver detalhes</button>
      </div>
      <div class="ml-auto">
        <button class="br-button circle" type="button" aria-label="Favoritar">
          <i class="fas fa-heart" aria-hidden="true"></i>
        </button>
        <button class="br-button circle" type="button" aria-label="Compartilhar">
          <i class="fas fa-share-alt" aria-hidden="true"></i>
        </button>
      </div>
    </div>
  </div>
</div>
```

Card com expansão (collapse) — exemplo oficial:
```html
<div class="card-footer">
  <div class="text-right">
    <button class="br-button circle" type="button" aria-label="Expandir ou recolher conteúdo adicional"
            data-toggle="collapse" data-target="card-expandido" aria-controls="card-expandido"
            aria-expanded="false" data-visible="false">
      <i class="fas fa-chevron-down" aria-hidden="true"></i>
    </button>
  </div>
  <div id="card-expandido" hidden="hidden">
    <div class="br-list mt-3">
      <div class="br-item">Conteúdo adicional</div>
    </div>
  </div>
</div>
```

## Variantes e modificadores
| classe/atributo | efeito | exemplo |
| --- | --- | --- |
| `.br-card` | superfície: fundo `--background`, `box-shadow: --surface-shadow-sm`, `margin-bottom: 2x`, `--card-padding: 2x` | `<div class="br-card">` |
| `.card-header` | padding `2x 2x 0` | cabeçalho (avatar, título, ação) |
| `.card-content` | padding `2x`; último filho sem margem inferior | corpo (texto/imagem) |
| `.card-footer` | padding `0 2x 2x` | ações |
| `.front .header/.content/.footer` | equivalentes legados para card com verso (flip) | — |
| `.hover` | aplica gradiente de hover sobre todo o card | `class="br-card hover"` |
| `.h-fixed` | `.card-content` com `max-height: 250px` e rolagem (`--card-height-fixed`); footer ganha padding-top | `class="br-card h-fixed"` (dê `tabindex="0"` ao `.card-content`) |
| `.disabled` | JS marca `aria-hidden="true"` e adiciona `disabled` a todos `button/input/select/textarea` internos | `class="br-card disabled"` |
| `.inverted` / `.dark-mode` | tema escuro (mixin `dark-mode`) | `class="br-card dark-mode"` |
| `[data-toggle="collapse"][data-target="id"]` (em botão interno) | expansão via comportamento Collapse; ícones `fa-chevron-down` ⇄ `fa-chevron-up` | ver exemplo |
| `button.flip` (interno) + `[flipped="on|off"]` (na raiz) | JS alterna o atributo `flipped` do card ao clicar | `<button class="br-button circle flip">` |
| `img`/`a` internos | JS força `draggable="false"`; o card dispara `dragstart` com seu id | — |

Não existem densidades (`small/large`) nem `block`/`circle` para o card.

## Estados e acessibilidade
- **Auto-init**: `core-init.js` executa `new BRCard('br-card', el)` para cada `.br-card`. Manual: `new core.BRCard('br-card', el, 'meuId')`.
- **Atenção**: o construtor faz `component.setAttribute('id', 'card' + id)`. Com o auto-init o terceiro argumento não é passado, então **todo `.br-card` recebe `id="cardundefined"`**, sobrescrevendo qualquer `id` que você tenha colocado. Não dependa de `id` na raiz do card; use `data-*` ou um wrapper.
- Collapse: trigger com `data-toggle="collapse"` e `data-target="<id sem #>"`; alvo com `hidden`. O Collapse define `aria-controls`, `aria-expanded`, `data-visible` no trigger, `aria-hidden` no alvo, `tabindex="0"`, aceita Enter/Espaço e fecha com Esc (devolvendo o foco ao trigger).
- `.disabled`: além do visual, o JS coloca `aria-hidden="true"` no card inteiro — o conteúdo deixa de ser lido por leitores de tela.
- Card com rolagem (`h-fixed`): o exemplo oficial coloca `tabindex="0"` no `.card-content` para permitir rolagem por teclado.
- Botões circulares internos precisam de `aria-label`.

## Erros comuns
- Usar `.card-body`, `.card-title` (Bootstrap): as áreas válidas são `card-header`, `card-content`, `card-footer`.
- Confiar em `id` próprio no `.br-card` (ex.: para âncoras ou `aria-controls`): o JS o substitui por `cardundefined`.
- Aninhar `.br-card` dentro de `.br-card`: viola a regra de design e duplica sombras/margens.
- Alvo do collapse sem `hidden` inicial ou `data-target` com `#`: o comportamento não acha o alvo / abre invertido.
- Colocar padding manual no `.br-card` além dos internos: dobra o espaçamento (`--card-padding`).
- Esquecer `margin-bottom` já embutido (2x) ao empilhar cards em colunas: não adicione `mb-*` extra sem necessidade.

## Fonte
- https://www.gov.br/ds/components/card?tab=designer (markdown bruto: https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/card/card.md)
- https://www.gov.br/ds/components/card?tab=desenvolvedor (SPA; markup dos exemplos locais)
- `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/card/examples.html`
- `/opt/web/pca/node_modules/@govbr-ds/core/src/components/card/_mixins.scss`
- `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/card/card.js`, `dist/partial/js/behavior/collapse.js`, `dist/core-init.js`
