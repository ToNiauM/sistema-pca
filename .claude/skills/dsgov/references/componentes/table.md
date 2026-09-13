# br-table

Tabela de dados do Design System gov.br (@govbr-ds/core 3.7.0). O componente é um `<div class="br-table">` que envolve uma barra de título (`.table-header`), um `<table>` HTML semântico e um rodapé (`.table-footer`) que abriga um `br-pagination` contextual. O JS (`BRTable`) adiciona busca, seleção de linhas com barra contextual, expansão de linhas (collapse), troca de densidade e o wrapper responsivo.

## Quando usar / quando não usar

- **Use** para organizar dados em linhas e colunas de forma intuitiva, com estrutura lógica (hierarquia ou ordem alfabética) que facilite a comparação e a leitura.
- **Use** o cabeçalho (`<thead>`) sempre: ele é obrigatório e descreve o conteúdo de cada coluna. Nomes de coluna devem ser curtos (preferencialmente menores que os dados da coluna).
- **Use** a barra de título apenas para um título curto de uma linha e até 4 ícones de ação lado a lado; com mais de 4 ações, agrupe em um menu flutuante acionado pelo botão `fas fa-ellipsis-v`.
- **Prefira tabelas simples**: cabeçalhos com vários níveis (agrupamento de colunas/linhas) confundem leitores de tela. Use `rowspan`/`colspan` com `scope="colgroup"`/`scope="rowgroup"` só quando indispensável.
- **Não use** conteúdo complexo dentro da linha expandida (outra tabela, cards, etc.); o conteúdo adicional deve ser simples, normalmente uma lista.
- **Não use** colunas com células vazias nem rótulos de cabeçalho na cor interativa quando a coluna não permitir ordenação.

## HTML canônico

Variante completa oficial (busca, seleção, expansão de linha, densidade e paginação contextual no rodapé). Os sufixos numéricos dos `id` são aleatórios no gerador oficial; o essencial é que sejam únicos na página e que `for`, `data-target`, `aria-controls` e `aria-describedby` apontem para eles.

```html
<div class="br-table" data-search="data-search" data-selection="data-selection" data-collapse="data-collapse" data-random="data-random">
  <div class="table-header">
    <div class="top-bar">
      <div class="table-title">Título da Tabela</div>
      <div class="actions-trigger text-nowrap">
        <button class="br-button circle" type="button" id="button-dropdown-density" title="Ver mais opções" data-toggle="dropdown" data-target="target01-5398" aria-label="Definir densidade da tabela" aria-haspopup="true" aria-live="polite"><i class="fas fa-ellipsis-v" aria-hidden="true"></i>
        </button>
        <div class="br-list" id="target01-5398" role="menu" aria-labelledby="button-dropdown-density" hidden="hidden">
          <button class="br-item" type="button" data-density="small" role="menuitem">Densidade alta</button><span class="br-divider"></span>
          <button class="br-item" type="button" data-density="medium" role="menuitem">Densidade média</button><span class="br-divider"></span>
          <button class="br-item" type="button" data-density="large" role="menuitem">Densidade baixa</button>
        </div>
      </div>
      <div class="search-trigger">
        <button class="br-button circle" type="button" id="button-input-search" data-toggle="search" aria-label="Abrir busca" aria-controls="table-searchbox-5398"><i class="fas fa-search" aria-hidden="true"></i>
        </button>
      </div>
    </div>
    <div class="search-bar">
      <div class="br-input">
        <label for="table-searchbox-5398">Buscar na tabela</label>
        <input id="table-searchbox-5398" type="search" placeholder="Buscar na tabela" aria-labelledby="button-input-search" aria-label="Buscar na tabela"/>
        <button class="br-button" type="button" aria-label="Buscar"><i class="fas fa-search" aria-hidden="true"></i>
        </button>
      </div>
      <button class="br-button circle" type="button" data-dismiss="search" aria-label="Fechar busca"><i class="fas fa-times" aria-hidden="true"></i>
      </button>
    </div>
    <div class="selected-bar">
      <div class="info"><span class="count">0</span><span class="text">item selecionado</span></div>
      <div class="actions-trigger text-nowrap">
        <button class="br-button circle inverted" type="button" id="button-dropdown-selection" data-toggle="dropdown" data-target="target02-5398" aria-controls="target02-5398" aria-label="Ver mais opções de ação" aria-haspopup="true"><i class="fas fa-ellipsis-v" aria-hidden="true"></i>
        </button>
        <div class="br-list" id="target02-5398" role="menu" aria-labelledby="button-dropdown-selection" hidden="hidden">
          <button class="br-item" type="button" role="menuitem">Ação 1</button><span class="br-divider"></span>
          <button class="br-item" type="button" role="menuitem">Ação 2</button>
        </div>
      </div>
    </div>
  </div>
  <table>
    <caption>Título da Tabela</caption>
    <thead>
      <tr>
        <td class="column-collapse" scope="col" aria-hidden="true"></td>
        <th class="column-checkbox" scope="col">
          <div class="br-checkbox hidden-label">
            <input id="check-all-5398" name="check-all-5398" type="checkbox" aria-label="Selecionar tudo" data-parent="check-01-5398"/>
            <label for="check-all-5398">Selecionar todas as linhas</label>
          </div>
        </th>
        <th scope="col">Título coluna 1</th>
        <th scope="col">Título coluna 2</th>
        <th scope="col">Título coluna 3</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>
          <button class="br-button circle small" type="button" id="button-line-1-5398" aria-label="Expandir/Retrair linha 1" data-toggle="collapse" data-target="collapse-1-4-5398" aria-describedby="collapse-1-4-5398"><i class="fas fa-chevron-down" aria-hidden="true"></i>
          </button>
        </td>
        <td>
          <div class="br-checkbox hidden-label">
            <input id="check-line-1-5398" name="check-line-1-5398" type="checkbox" aria-label="Selecionar linha 1" data-child="check-01-5398"/>
            <label for="check-line-1-5398">Selecionar linha 1</label>
          </div>
        </td>
        <td data-th="Título coluna 1">Linha 1 coluna 1</td>
        <td data-th="Título coluna 2">Linha 1 coluna 2</td>
        <td data-th="Título coluna 3">Linha 1 coluna 3</td>
      </tr>
      <tr class="collapse">
        <td id="collapse-1-4-5398" aria-hidden="true" hidden="hidden" colspan="6">Conteúdo adicional da linha 1.</td>
      </tr>
      <tr>
        <td>
          <button class="br-button circle small" type="button" id="button-line-2-5398" aria-label="Expandir/Retrair linha 2" data-toggle="collapse" data-target="collapse-2-4-5398" aria-describedby="collapse-2-4-5398"><i class="fas fa-chevron-down" aria-hidden="true"></i>
          </button>
        </td>
        <td>
          <div class="br-checkbox hidden-label">
            <input id="check-line-2-5398" name="check-line-2-5398" type="checkbox" aria-label="Selecionar linha 2" data-child="check-01-5398"/>
            <label for="check-line-2-5398">Selecionar linha 2</label>
          </div>
        </td>
        <td data-th="Título coluna 1">Linha 2 coluna 1</td>
        <td data-th="Título coluna 2">Linha 2 coluna 2</td>
        <td data-th="Título coluna 3">Linha 2 coluna 3</td>
      </tr>
      <tr class="collapse">
        <td id="collapse-2-4-5398" aria-hidden="true" hidden="hidden" colspan="6">Conteúdo adicional da linha 2.</td>
      </tr>
    </tbody>
  </table>
  <div class="table-footer">
    <nav class="br-pagination" aria-label="paginação" data-total="50" data-current="1" data-per-page="20">
      <div class="pagination-per-page">
        <div class="br-select">
          <div class="br-input">
            <label for="per-page-selection-random-12162">Exibir</label>
            <input id="per-page-selection-random-12162" type="text" placeholder=" "/>
            <button class="br-button" type="button" aria-label="Exibir lista" tabindex="-1" data-trigger="data-trigger"><i class="fas fa-angle-down" aria-hidden="true"></i>
            </button>
          </div>
          <div class="br-list" tabindex="0">
            <div class="br-item" tabindex="-1">
              <div class="br-radio">
                <input id="per-page-10-random-12162" type="radio" name="per-page-random-12162" value="per-page-10-random-12162" checked="checked"/>
                <label for="per-page-10-random-12162">10</label>
              </div>
            </div>
            <div class="br-item" tabindex="-1">
              <div class="br-radio">
                <input id="per-page-20-random-12162" type="radio" name="per-page-random-12162" value="per-page-20-random-12162"/>
                <label for="per-page-20-random-12162">20</label>
              </div>
            </div>
            <div class="br-item" tabindex="-1">
              <div class="br-radio">
                <input id="per-page-30-random-12162" type="radio" name="per-page-random-12162" value="per-page-30-random-12162"/>
                <label for="per-page-30-random-12162">30</label>
              </div>
            </div>
          </div>
        </div>
      </div><span class="br-divider d-none d-sm-block mx-3"></span>
      <div class="pagination-information d-none d-sm-flex"><span class="current">1</span>&ndash;<span class="per-page">20</span>&nbsp;de&nbsp;<span class="total">50</span>&nbsp;itens</div>
      <div class="pagination-go-to-page d-none d-sm-flex ml-auto">
        <div class="br-select">
          <div class="br-input">
            <label for="go-to-selection-random-83077">Página</label>
            <input id="go-to-selection-random-83077" type="text" placeholder=" "/>
            <button class="br-button" type="button" aria-label="Exibir lista" tabindex="-1" data-trigger="data-trigger"><i class="fas fa-angle-down" aria-hidden="true"></i>
            </button>
          </div>
          <div class="br-list" tabindex="0">
            <div class="br-item" tabindex="-1">
              <div class="br-radio">
                <input id="go-to-1-random-83077" type="radio" name="go-to-random-83077" value="go-to-1-random-83077" checked="checked"/>
                <label for="go-to-1-random-83077">1</label>
              </div>
            </div>
            <div class="br-item" tabindex="-1">
              <div class="br-radio">
                <input id="go-to-2-random-83077" type="radio" name="go-to-random-83077" value="go-to-2-random-83077"/>
                <label for="go-to-2-random-83077">2</label>
              </div>
            </div>
            <div class="br-item" tabindex="-1">
              <div class="br-radio">
                <input id="go-to-3-random-83077" type="radio" name="go-to-random-83077" value="go-to-3-random-83077"/>
                <label for="go-to-3-random-83077">3</label>
              </div>
            </div>
          </div>
        </div>
      </div><span class="br-divider d-none d-sm-block mx-3"></span>
      <div class="pagination-arrows ml-auto ml-sm-0">
        <button class="br-button circle" type="button" aria-label="Voltar página"><i class="fas fa-angle-left" aria-hidden="true"></i>
        </button>
        <button class="br-button circle" type="button" aria-label="Página seguinte"><i class="fas fa-angle-right" aria-hidden="true"></i>
        </button>
      </div>
    </nav>
  </div>
</div>
```

**Obrigatório:** todo `.br-table` precisa de `<div class="table-header"></div>` (pode ser vazio) antes do `<table>` — o `BRTable` do core 3.7.0 lança erro sem ele e REMOVE a tabela do DOM depois de carregada (achado em 09/09/2026, invisível em testes Django, visível só no navegador). Tabela mínima (sem JS além do wrapper responsivo): `<div class="br-table"><div class="table-header"></div><table><caption>…</caption><thead><tr><th scope="col">…</th></tr></thead><tbody><tr><td>…</td></tr></tbody></table></div>`. A barra de título (`.table-header`) e o rodapé (`.table-footer`) são opcionais.

### Estrutura em blocos

| Bloco | Seletor | Conteúdo |
| --- | --- | --- |
| Barra de título | `.br-table > .table-header > .top-bar` | `.table-title` (título, ocupa o espaço restante) + `.actions-trigger.text-nowrap` (botão `br-button circle` com `data-toggle="dropdown"` + `.br-list[role=menu]`) + `.search-trigger` (botão `data-toggle="search"`). |
| Barra de busca | `.table-header > .search-bar` | Sobreposta ao `.top-bar` (position absolute, 56px de altura). Contém `.br-input` com `input[type=search]` e botão `fas fa-search`, mais um `br-button circle` com `data-dismiss="search"` (`fas fa-times`). Fica oculta até receber `.show`. |
| Barra contextual (seleção) | `.table-header > .selected-bar` (alias `.selection-bar`) | `.info` com `<span class="count">` e `<span class="text">` + `.actions-trigger` com botão `br-button circle inverted` e `.br-list`. Fundo `--interactive-light`, aparece com `.show` quando há linhas selecionadas. |
| Tabela | `.br-table > .responsive > table` | O JS cria automaticamente o `div.responsive` (overflow: auto) em volta do `<table>`. `<caption>` é visualmente oculto (opacity 0, absolute), mas lido por leitores de tela. |
| Coluna de expansão | `thead td.column-collapse` (40px, fundo `--background-alternative`) e `tbody td` com `br-button circle small` `data-toggle="collapse"` | Linha seguinte `tr.collapse > td[hidden][colspan]` é o alvo. |
| Coluna de seleção | `thead th.column-checkbox` (24px) com `br-checkbox hidden-label` `data-parent` e `tbody td` com `br-checkbox hidden-label` `data-child` | O `hidden-label` esconde o texto do label mantendo-o acessível. |
| Rodapé | `.br-table > .table-footer` | Um `nav.br-pagination` contextual (ver `pagination.md`). O `.br-list` dos selects abre para cima (`bottom: 100%`) e o ícone do botão do select é girado 180°. |

## Variantes e modificadores

| Classe / atributo | Efeito | Exemplo |
| --- | --- | --- |
| `.br-table` | Container obrigatório. Define `--table-padding: var(--spacing-scale-3x)` e `--table-row-size: var(--table-row-medium)`. | `<div class="br-table">…</div>` |
| `.br-table.small` | Densidade alta: `--table-row-size: var(--spacing-scale-base)` (8px de padding vertical nas células). Aplicada também pelo JS ao clicar em `[data-density="small"]`. | `<div class="br-table small">` |
| `.br-table.medium` | Densidade média (padrão): `--table-row-size: var(--spacing-scale-2x)` (16px). | `<div class="br-table medium">` |
| `.br-table.large` | Densidade baixa: `--table-row-size: var(--spacing-scale-3x)` (24px). | `<div class="br-table large">` |
| `.br-table.inverted` / `.br-table.dark-mode` | Fundo escuro: aplica o mixin dark-mode (cores claras) e o dark-mode da paginação; `th`, `td.column-collapse` ficam com `--background-dark`. Use dentro de um container escuro, ex.: `bg-blue-warm-vivid-90`. | `<div class="bg-blue-warm-vivid-90"><div class="br-table inverted">…</div></div>` |
| `.br-table.no-hover` | Remove o realce de linha ao passar o mouse (para tabelas sem interatividade). | `<div class="br-table no-hover">` |
| `data-search` | Habilita o comportamento de busca no JS (`this.component.dataset.search`). Qualquer valor não vazio funciona; o exemplo oficial usa `data-search="data-search"`. Exige `[data-toggle="search"]`, `.search-bar` com `input` e `[data-dismiss="search"]`, caso contrário o JS registra `console.error`. | `<div class="br-table" data-search="data-search">` |
| `data-selection` | Marcador da variante com coluna de checkboxes (documentado como "necessário para seleção de linhas"). Na versão 3.7.0 o JS não lê este atributo: a seleção é ligada a qualquer `tbody [type="checkbox"]` presente; e o CSS compilado não possui regra `[data-selection]`. Mantenha-o por compatibilidade com a documentação. | `data-selection="data-selection"` |
| `data-collapse` | Marcador da variante com linhas expansíveis. Também não é lido pelo JS 3.7.0 (a expansão é ligada a todo `[data-toggle="collapse"]` dentro do componente). | `data-collapse="data-collapse"` |
| `data-random` | Presente nos exemplos oficiais (gerador de ids aleatórios da documentação). Sem efeito no JS/CSS distribuídos. | `data-random="data-random"` |
| `[data-toggle="dropdown"]` + `data-target="<id>"` | Botão que abre um `.br-list` irmão com esse `id` (menu de densidade ou de ações). O JS usa o behavior Dropdown: alterna `hidden`, `aria-expanded`, `data-visible`, adiciona `.dropdown` ao pai e alterna as classes `fa-chevron-down`/`fa-chevron-up` em todo `i.fas` do botão (a classe original `fa-ellipsis-v` permanece; qual glifo aparece depende da ordem das regras do Font Awesome). | ver HTML canônico |
| `[data-density="small|medium|large"]` | Itens do menu de densidade. Ao clicar, o JS remove `small medium large` do `.br-table` e adiciona o valor, depois fecha o dropdown. | `<button class="br-item" data-density="large" role="menuitem">Densidade baixa</button>` |
| `[data-toggle="search"]` / `[data-dismiss="search"]` | Abre/fecha a barra de busca: adiciona `.show` ao `.search-bar` e ao `.table-header` (que oculta o `.top-bar` via opacity 0), foca o input; ao fechar limpa o valor e devolve o foco ao gatilho. `Esc` no input também fecha. | ver HTML canônico |
| `[data-toggle="collapse"]` + `data-target="<id>"` | Botão da célula de expansão. Alvo é a célula `td#<id>` com `hidden`/`aria-hidden` na linha `tr.collapse`. Alterna `hidden`, `aria-expanded`, `aria-controls`, `data-visible` e o ícone `fa-chevron-down` ↔ `fa-chevron-up`. | `<button class="br-button circle small" data-toggle="collapse" data-target="collapse-1">` |
| `tr.collapse` | Marcador da linha que abriga o conteúdo expandido. Não possui regra CSS própria; a ocultação vem de `td[hidden]`. Use `colspan` igual ao total de colunas (incluindo colapso e checkbox). | `<tr class="collapse"><td id="collapse-1" hidden colspan="6">…</td></tr>` |
| `td.column-collapse` | Célula vazia do `thead` acima da coluna de botões de expansão (largura 40px, fundo alternativo). Use `aria-hidden="true"`. | `<td class="column-collapse" scope="col" aria-hidden="true"></td>` |
| `th.column-checkbox` | Célula do `thead` da coluna de seleção (24px). | `<th class="column-checkbox" scope="col">` |
| `.br-checkbox.hidden-label` | Esconde visualmente o texto do label do checkbox de seleção. | ver HTML canônico |
| `data-parent="<grupo>"` / `data-child="<grupo>"` | Checkgroup (behavior do `br-checkbox`, não do `br-table`): o checkbox pai marca/desmarca os filhos e assume estado indeterminado quando só parte está marcada. | `<input type="checkbox" data-parent="check-01">` … `<input type="checkbox" data-child="check-01">` |
| `tr.is-selected` (aplicada pelo JS) | Linha selecionada: fundo `--selected`, tokens de cor invertidos. O JS também adiciona `.is-inverted` ao `.br-checkbox` da linha. | gerado pelo JS ao marcar o checkbox |
| `.selected-bar.show` / `.selection-bar.show` | Exibe a barra contextual (display: flex) quando `count > 0`. O JS atualiza `.info .count` e `.info .text` ("item selecionado" / "itens selecionados"). | gerado pelo JS |
| `[data-toggle="check-all"]` / `.select-all` | Botão opcional dentro de `.selected-bar .info` que marca/desmarca todas as linhas (`_checkAllTable`). | `<button class="br-button" data-toggle="check-all">Selecionar tudo</button>` |
| `.headers` / `.clone-headers .item` | Seletores herdados para cabeçalho clonado fixo (scroll). Existem no CSS (`.br-table.small .headers`, `.br-table.large .clone-headers .item`) mas nenhum exemplo 3.7.0 os usa; o método `_makeScroller` que criaria `.scroller` não é invocado. | — |
| `th.border-top` / `.border-right` / `.border-bottom` / `.border-left` | Bordas manuais para tabelas irregulares (agrupamento de colunas/linhas); as colunas do cabeçalho não têm separadores por padrão. | `<th class="border-right border-bottom" colspan="2" scope="colgroup">Contato</th>` |
| `td[data-th="…"]` | Presente nos exemplos oficiais com o nome da coluna; não há regra CSS em 3.7.0, serve como gancho para layouts empilhados customizados. | `<td data-th="Nome">João</td>` |
| `title="…"` no `.br-table` | Usado nos exemplos de tabelas irregulares como descrição do container. | `<div class="br-table" title="Tabela irregular 1">` |

Tokens de densidade (SCSS `table-tokens`):

| Token | Valor |
| --- | --- |
| `--table-row-small` | `var(--spacing-scale-base)` = 8px |
| `--table-row-medium` | `var(--spacing-scale-2x)` = 16px |
| `--table-row-large` | `var(--spacing-scale-3x)` = 24px |
| `--table-padding` (horizontal) | `var(--spacing-scale-3x)` = 24px |

Estilos base do `<table>` (definidos globalmente em `core.css`, não só dentro de `.br-table`): `border-collapse: collapse; width: 100%`; `th` com fundo `--background-alternative` e `--font-weight-semi-bold`; `td` com `--font-weight-medium`; `tbody th, tbody td` com borda inferior 1px `--gray-20`; `tr:hover td` com sobreposição translúcida de hover; `tr.is-selected td` com fundo `--selected`.

### Tabelas irregulares (agrupamento)

Agrupamento por linhas (exemplo oficial `table-irregular-1.html`):

```html
<div class="br-table" title="Tabela irregular 1">
  <div class="table-header">
    <div class="top-bar">
      <div class="table-title">Tabela irregular 1</div>
      <div class="actions-trigger text-nowrap">
        <button class="br-button circle" type="button" id="button-dropdown-density-2" title="Ver mais opções" data-toggle="dropdown" data-target="target01-87926" aria-label="Definir densidade da tabela" aria-haspopup="true" aria-live="polite"><i class="fas fa-ellipsis-v" aria-hidden="true"></i></button>
        <div class="br-list" id="target01-87926" role="menu" aria-labelledby="button-dropdown-density-2" hidden="hidden">
          <button class="br-item" type="button" data-density="small" role="menuitem">Densidade alta</button><span class="br-divider"></span>
          <button class="br-item" type="button" data-density="medium" role="menuitem">Densidade média</button><span class="br-divider"></span>
          <button class="br-item" type="button" data-density="large" role="menuitem">Densidade baixa</button>
        </div>
      </div>
    </div>
  </div>
  <table><colgroup span="3"></colgroup>
    <thead>
      <tr>
        <th class="border-bottom" scope="col">Nome do pôster</th>
        <th class="border-bottom border-left" scope="col">Cor</th>
        <th class="border-bottom border-left" colspan="3" scope="colgroup">Tamanhos disponíveis</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <th class="border-right" rowspan="3" scope="rowgroup">Zodíaco</th>
        <td>Colorido</td><td>A2</td><td>A3</td><td>A4</td>
      </tr>
      <tr><td>Preto e branco</td><td>A1</td><td>A2</td><td>A3</td></tr>
      <tr><td>Sépia</td><td>A3</td><td>A4</td><td>A5</td></tr>
    </tbody>
    <tbody>
      <tr>
        <th class="border-right" rowspan="2" scope="rowgroup">Anjos</th>
        <td>Preto e branco</td><td>A1</td><td>A3</td><td>A4</td>
      </tr>
      <tr><td>Sépia</td><td>A2</td><td>A3</td><td>A5</td></tr>
    </tbody>
  </table>
</div>
```

Agrupamento por colunas (`table-irregular-2.html`): duas linhas no `<thead>`; a primeira com `<th rowspan="2" scope="rowgroup" class="border-right">` e `<th colspan="N" scope="colgroup" class="border-right border-bottom">`, a segunda com os `<th scope="col" class="border-right">` individuais. Declare `<col>`/`<colgroup span="N">` antes do `<thead>`.

## Estados e acessibilidade

- **Inicialização**: `core-init.js` instancia automaticamente todos os `.br-table` (`new BRTable('br-table', el, index)`). Se você carregar apenas `core.min.js`, instancie manualmente:

```javascript
const tableList = []
for (const [index, brTable] of window.document.querySelectorAll('.br-table').entries()) {
  tableList.push(new core.BRTable('br-table', brTable, index))
}
```

- **O que o JS faz no construtor**: procura `.header, .table-header` e o `<table>`; envolve a tabela em `div.responsive` (se ainda não existir); liga dropdowns (`[data-toggle="dropdown"]`), collapses (`[data-toggle="collapse"]`), busca (se `data-search`), densidade (`[data-density]`) e seleção (`tbody [type="checkbox"]`, `.selected-bar`, `[data-toggle="check-all"]`). Se não houver `.table-header` (nem `.header`), `this._header` é `null` e `_makeResponsiveTable` lança erro ao chamar `.after()`. Para tabelas sem barra de título, inclua um `<div class="table-header"></div>` vazio ou envolva o `<table>` manualmente em `<div class="responsive">` (quando `.responsive` já existe o JS pula essa etapa).
- **Semântica HTML obrigatória**: `<caption>` com o título (visualmente oculto pelo CSS), `<thead>` com `<th scope="col">`, `<tbody>`; em tabelas irregulares use `scope="colgroup"`/`scope="rowgroup"` e `rowspan`/`colspan`. Cabeçalhos de linha vão em `<th scope="row">`/`rowgroup`.
- **Busca**: gatilho `[data-toggle="search"]` recebe `aria-expanded="false"` na inicialização e `"true"` ao abrir; use `aria-controls` apontando para o `id` do input e `aria-label="Abrir busca"`. O botão de fechar usa `data-dismiss="search"` e `aria-label="Fechar busca"`. Teclado: `Esc` dentro do input fecha e devolve o foco ao gatilho. A filtragem das linhas pelo texto digitado **não** é implementada pelo core; o JS só abre/fecha a barra.
- **Dropdowns (densidade/ações)**: botão com `data-toggle="dropdown"`, `data-target`, `aria-haspopup="true"`, `aria-label`; lista `.br-list` com `role="menu"`, `aria-labelledby` (id do botão) e `hidden`. Itens são `<button class="br-item" role="menuitem">`. O behavior define `aria-controls`, `aria-expanded`, `data-visible`, `tabindex="0"` no gatilho; `ArrowUp`/`ArrowDown` navegam entre os `[role="menuitem"]`, `Esc` fecha e devolve o foco, clique fora fecha.
- **Expansão de linha**: botão `br-button circle small` com `data-toggle="collapse"`, `data-target` e `aria-describedby` apontando para o `td` de conteúdo, `aria-label="Expandir/Retrair …"`. O alvo começa com `hidden="hidden"` e `aria-hidden="true"`; o JS alterna `hidden`/`aria-hidden` e o ícone `fas fa-chevron-down` ↔ `fas fa-chevron-up`. `Enter`/`Espaço` no botão ativam; `Esc` dentro do conteúdo expandido fecha e devolve o foco.
- **Seleção**: checkboxes `br-checkbox hidden-label` com `aria-label` descritivo em cada linha e `aria-label="Selecionar tudo"` no cabeçalho. O sincronismo pai/filhos (`data-parent`/`data-child`, estado indeterminado) vem do behavior Checkgroup do `br-checkbox`. Ao marcar uma linha, o `BRTable` adiciona `tr.is-selected`, incrementa `.selected-bar .info .count`, ajusta o texto singular/plural e exibe a barra (`.show`). Quando todas as linhas estão marcadas, o checkbox de `.headers [type="checkbox"]` (se existir) é marcado; caso contrário recebe `.is-checking` no pai (estado parcial).
- **Densidade**: botões `[data-density]` dentro de `.actions-trigger .br-list`; após o clique o JS remove `.dropdown` do `.actions-trigger`, define `hidden`, `data-visible="false"` e `aria-expanded="false"` na lista. Rótulos oficiais em português: "Densidade alta" (small), "Densidade média" (medium), "Densidade baixa" (large).
- **Paginação do rodapé**: é um `br-pagination` contextual e é inicializado pelo próprio `core-init.js` (`.br-pagination`); os `br-select` internos são inicializados por `BRSelect`. O core não faz a paginação dos dados — `data-total`, `data-current`, `data-per-page` são informativos para a sua aplicação.
- **Estados visuais** (CSS): hover na linha (`tr:hover td`, desativado com `.no-hover`), selecionada (`tr.is-selected`), fundo escuro (`.inverted`/`.dark-mode`). Estados de ordenação (ícones `fa-sort`, `fa-sort-up`, `fa-sort-down` descritos no guia de design) **não** possuem CSS/JS no core 3.7.0; implemente na aplicação.
- **Ícones Font Awesome 5 usados**: `fas fa-ellipsis-v` (menus), `fas fa-search` (busca), `fas fa-times` (fechar busca), `fas fa-chevron-down`/`fas fa-chevron-up` (expandir/retrair), `fas fa-angle-down` (selects da paginação), `fas fa-angle-left`/`fas fa-angle-right` (setas de página). Sempre com `aria-hidden="true"`.

## Erros comuns

- **Colocar `<table>` sem o wrapper `.br-table`** ou, inversamente, colocar a tabela dentro de `.table-header`. A ordem correta é `.br-table > (.table-header, table, .table-footer)`; o JS insere `div.responsive` logo após o `.table-header`.
- **Barra de busca fora do `.table-header`**: `.search-bar` e `.selected-bar` são posicionadas de forma absoluta sobre o `.top-bar` e dependem de `.table-header { position: relative }`. Fora dele aparecem no lugar errado e `.table-header.show` não oculta o título.
- **`data-target` diferente do `id` do alvo** (dropdown ou collapse) — o behavior faz `document.querySelector('#' + data-target)`; ids duplicados na página abrem a lista/linha errada. Gere ids únicos por tabela.
- **`colspan` da linha `tr.collapse` menor que o número real de colunas** (esqueça de contar `column-collapse` e `column-checkbox`): o conteúdo expandido fica desalinhado e a borda quebra.
- **Usar `<div class="br-checkbox">` sem `hidden-label`** na coluna de seleção: o texto do label aparece e a coluna de 24px estoura. Também não omita o `<label>` — ele é o alvo clicável e a acessibilidade do checkbox.
- **Aplicar `small|medium|large` no `<table>`** em vez do `.br-table`: a densidade é lida em `.br-table.small` etc. O mesmo vale para `inverted`/`dark-mode` e `no-hover`.
- **Esperar filtragem/ordenação/paginação automática**: o core só cuida da UI (abrir busca, selecionar linhas, expandir, trocar densidade). Filtrar linhas, ordenar colunas e paginar os dados é responsabilidade da aplicação.
- **Usar a paginação padrão (`<ul>` com `.page`) dentro de `.table-footer`**: o rodapé foi desenhado para a variante contextual (`.pagination-per-page`, `.pagination-information`, `.pagination-go-to-page`, `.pagination-arrows`), com listas abrindo para cima.

## Fonte

- https://www.gov.br/ds/components/table?tab=designer
- https://www.gov.br/ds/components/table?tab=desenvolvedor
- Markdown bruto (designer): https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/table/table.md
- Markdown bruto (desenvolvedor): https://docs-ds.estaleiro.serpro.gov.br/govbr-ds-core/docs/components/table/table-dev.md
- Exemplos oficiais locais: `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/table/examples.html`, `dist/components/table/examples/table.html`, `table-irregular-1.html`, `table-irregular-2.html`
- JS: `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/table/table.js`, `dist/partial/js/behavior/collapse.js`, `dist/partial/js/behavior/dropdown.js`, `dist/partial/js/behavior/checkgroup.js`, `dist/core-init.js`
- SCSS: `/opt/web/pca/node_modules/@govbr-ds/core/src/components/table/_table.scss`, `_mixins.scss`; estilos base de `table` em `src/partial/scss/utilities/_typography.scss`
- CSS compilado verificado: `/opt/web/pca/node_modules/@govbr-ds/core/dist/core.css`
- W3C, Tables with irregular headers: https://www.w3.org/WAI/tutorials/tables/irregular/
