# br-datetimepicker

## Quando usar / quando não usar
- Use para o usuário informar data, hora ou data+hora com apoio de calendário/relógio; três variações: **DateTimePicker** (data e hora), **Datepicker** (só data), **Timepicker** (só hora, formato 24h, padrão 00:00).
- Suporta **intervalo** de datas (`data-mode="range"`).
- Meses e dias em português (pt-br embutido via flatpickr); domingo como primeiro dia da semana.
- Sempre permita digitação direta no campo (o componente aplica máscara `dd/mm/aaaa`); o botão de calendário é auxiliar.
- Não use para datas muito distantes (ano de nascimento) sem configurar `minDate/maxDate`, nem para campos que exigem só ano/mês.

## HTML canônico
```html
<div class="br-datetimepicker" data-mode="single" data-type="text">
  <div class="br-input has-icon">
    <label for="data-inicio">Data de início</label>
    <input id="data-inicio" type="text" placeholder="exemplo: 02/02/2024" data-input="data-input"/>
    <button class="br-button circle small" type="button" aria-label="Abrir calendário"
            data-toggle="data-toggle" id="data-inicio-btn" tabindex="-1" aria-hidden="true">
      <i class="fas fa-calendar-alt" aria-hidden="true"></i>
    </button>
  </div>
</div>
```

Variações oficiais:
```html
<!-- Intervalo -->
<div class="br-datetimepicker" data-mode="range" data-type="text"> … placeholder="exemplo: 02/02/2024 até 03/02/2025" … </div>
<!-- Hora -->
<div class="br-datetimepicker" data-mode="single" data-type="time">
  <div class="br-input has-icon">
    <label for="hora">Horário</label>
    <input id="hora" type="time" placeholder="exemplo: 02:40" data-input="data-input"/>
    <button class="br-button circle small" type="button" aria-label="Abrir seletor de hora" data-toggle="data-toggle" tabindex="-1" aria-hidden="true"><i class="fas fa-clock" aria-hidden="true"></i></button>
  </div>
</div>
<!-- Data e hora -->
<div class="br-datetimepicker" data-mode="single" data-type="datetime-local"> … <input type="datetime-local" placeholder="exemplo: 02/02/2024 02:02" data-input="data-input"/> … </div>
<!-- Configuração extra do flatpickr via atributo -->
<div class="br-datetimepicker" data-mode="single" data-type="text" datetimepicker-config="minDate: '15/04/2022'"> … </div>
```

## Variantes e modificadores
| classe/atributo | efeito | exemplo |
| --- | --- | --- |
| `.br-datetimepicker` | raiz; herda dark-mode do input; `input[disabled] {cursor:not-allowed}` | `<div class="br-datetimepicker">` |
| `data-mode="single"` / `"range"` | modo do flatpickr; `range` aplica máscara `dd/mm/aaaa até dd/mm/aaaa` | `data-mode="range"` |
| `data-type="text"` (ou ausente) | data `d/m/Y`, com calendário | padrão |
| `data-type="date"` | idem `text` com máscara de data | — |
| `data-type="time"` | só hora `H:i`, `noCalendar`, máscara `hh:mm` | `type="time"` no input |
| `data-type="datetime-local"` | `d/m/Y H:i`, calendário + hora | `type="datetime-local"` no input |
| `data-type="datetime-range"` | intervalo de datas (máscara de range) | — |
| `datetimepicker-config="chave: 'valor', chave2: 'valor2'"` | opções do flatpickr parseadas por vírgula/dois-pontos (ex.: `minDate`, `maxDate`) | `datetimepicker-config="minDate: '15/04/2022'"` |
| `.br-input.has-icon` (interno) | input com botão circular sobreposto à direita (compatibilidade) | obrigatório |
| `input[data-input]` | elemento que o flatpickr (`wrap:true`) usa como campo | obrigatório |
| `button[data-toggle]` | elemento que abre o calendário (`wrap:true`) | obrigatório |
| `.br-input.has-icon.disabled` + `input[disabled]` + `button[disabled]` | estado desabilitado | ver exemplos |
| `.br-datetimepicker.inverted` / `.dark-mode` | labels em `--color-dark` (fundo escuro) | — |
| `.flatpickr-calendar` | popup estilizado pelo DS (sombra `md`, dias 24px, hoje em laranja, selecionado `--selected`, setas `br-button circle small` com `fa-chevron-left/right`, `fa-chevron-up/down` nas horas) | gerado |

Ícones oficiais: `fas fa-calendar-alt` (data), `fas fa-clock` (hora).

## Estados e acessibilidade
- **Auto-init**: `core-init.js` executa `new BRDateTimePicker('br-datetimepicker', el, {})`. Manual: `new core.BRDateTimePicker('br-datetimepicker', el, {minDate:'…'})` (4º parâmetro opcional: locale flatpickr, padrão pt).
- Depende do **flatpickr** já empacotado em `core.js` (não instale separado). `allowInput:true` → o campo aceita digitação; `blur`/`keyup` sincronizam com o calendário.
- O JS marca todo `.br-button` interno com `aria-hidden="true"` e `tab-index="-1"`: o botão é só apoio visual; a interação acessível é pelo input (por isso o exemplo oficial já traz `tabindex="-1"` e `aria-hidden`). Mantenha `aria-label` mesmo assim.
- Texto auxiliar: use `<p id="ajuda-data">…</p>` e `aria-describedby="ajuda-data"` no input (exemplo oficial).
- Máscaras: só dígitos; barras/`:`/separador inseridos automaticamente; `maxlength` ajustado por tipo.
- Dias do calendário recebem `tabindex="1"` ao abrir (comportamento do JS); Esc fecha (flatpickr).

## Erros comuns
- Trocar `.has-icon` por `.input-button`: o botão desalinha (o DS ainda usa `has-icon` para este componente).
- Esquecer `data-input` no input ou `data-toggle` no botão: com `wrap:true` o flatpickr não encontra os elementos e nada abre.
- Colocar `type="date"` nativo no input com `data-type="text"`: o navegador exibe o seletor nativo por cima; os exemplos usam `type="text"` para data.
- Sintaxe errada em `datetimepicker-config` (JSON com chaves/aspas duplas): o parser espera `chave: 'valor'` separados por vírgula.
- Vários `.br-datetimepicker` com o mesmo `id` de input: quebra o `for` do label.
- Estilizar `.flatpickr-*` por conta própria: o DS já cobre; conflitos comuns com CSS do flatpickr original.

## Fonte
- https://www.gov.br/ds/components/datetimepicker?tab=designer (markdown bruto: https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/datetimepicker/datetimepicker.md)
- https://www.gov.br/ds/components/datetimepicker?tab=desenvolvedor (SPA; markup dos exemplos locais)
- `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/datetimepicker/examples.html`
- `/opt/web/pca/node_modules/@govbr-ds/core/src/components/datetimepicker/_mixins.scss`, `_datetimepicker.scss`
- `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/datetimepicker/datetimepicker.js`
