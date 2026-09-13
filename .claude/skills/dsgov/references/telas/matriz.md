# Tela: Matriz de indicadores (tabela cruzada)

Para "linha × vários indicadores agrupados" (unidade × previsto/tipo/meta; mês × situação). É uma
`br-table small` com a classe `dsgov-matriz` — nunca uma `br-table` genérica com "n (x%)" em cada
célula, e nunca CSS próprio. Anatomia fixa:

1. Título `h2` da seção (o `h1` é da página) e, à direita, `br-tab` **Absolutos | Percentuais**
   quando existirem os dois modos: dois `tab-panel`, cada um com a matriz completa (sem JS além do
   `BRTab` do core; o servidor renderiza os dois).
2. `thead` em dois níveis: 1ª linha com os grupos (`<th scope="colgroup" colspan="n" class="dsgov-grupo">`),
   2ª linha com os indicadores (`<th scope="col" class="dsgov-numero">`), abreviações em `<abbr title>`.
   O rótulo de linha usa `rowspan="2"` e a classe `dsgov-rotulo-linha` (fica fixo ao rolar no celular).
3. `tbody`: 1ª célula é `<th scope="row" class="dsgov-rotulo-linha">` com link para o recorte da linha;
   cada número é `td.dsgov-numero` com `<a>` para a tabela filtrada (o CSS tira o sublinhado e devolve
   no hover/foco) e `aria-label` "linha, indicador: valor — abrir a tabela filtrada". Zero fica como `0`,
   indefinido como `—`, nunca `0 (—)`.
4. Primeira coluna de cada grupo leva `dsgov-separador`; a coluna-chave do grupo (Ativos, Meta) leva
   `dsgov-destaque`. Cor semântica só por utilitário e só onde tem significado:
   `text-green-cool-vivid-50` (concluído/no prazo), `text-blue-warm-vivid-70` (em tramitação),
   `text-red-vivid-50` (fora do prazo), `text-gray-70` (cancelado).
5. `tfoot` com a linha TOTAL (mesmos links, agregados).
6. Legenda das abreviações em `p.text-down-01.text-gray-70` logo abaixo; "Exportar XLSX" como
   `br-button secondary` no cabeçalho da página.

```django
<div class="br-tab" data-counter="false">
  <nav class="tab-nav" aria-label="Modo da matriz"><ul role="tablist">
    <li class="tab-item active" role="presentation"><button type="button" role="tab" id="tab-abs" data-panel="painel-abs" aria-controls="painel-abs" aria-selected="true"><span class="name">Absolutos</span></button></li>
    <li class="tab-item" role="presentation"><button type="button" role="tab" id="tab-pct" data-panel="painel-pct" aria-controls="painel-pct" aria-selected="false"><span class="name">Percentuais</span></button></li>
  </ul></nav>
  <div class="tab-content">
    <div class="tab-panel active" id="painel-abs" role="tabpanel" aria-labelledby="tab-abs">
      <div class="br-table small dsgov-matriz">
        <div class="table-header"></div>
        <table>
          <caption class="sr-only">Resumo por unidade — valores absolutos</caption>
          <thead>
            <tr><th scope="col" rowspan="2" class="dsgov-rotulo-linha">Unidade</th>
                <th scope="colgroup" colspan="3" class="dsgov-grupo dsgov-separador">Previsto</th>
                <th scope="colgroup" colspan="3" class="dsgov-grupo dsgov-separador">Por tipo</th></tr>
            <tr><th scope="col" class="dsgov-numero dsgov-separador">Total</th><th scope="col" class="dsgov-numero">Cancelados</th><th scope="col" class="dsgov-numero dsgov-destaque">Ativos</th>
                <th scope="col" class="dsgov-numero dsgov-separador"><abbr title="Nova contratação">NC</abbr></th><th scope="col" class="dsgov-numero"><abbr title="Renovação">RN</abbr></th><th scope="col" class="dsgov-numero"><abbr title="Vigente">VG</abbr></th></tr>
          </thead>
          <tbody>
            {% for l in linhas %}
            <tr><th scope="row" class="dsgov-rotulo-linha"><a href="{{ l.url }}">{{ l.rotulo }}</a></th>
                <td class="dsgov-numero dsgov-separador"><a href="{{ l.url_total }}" aria-label="{{ l.rotulo }}, total previsto: {{ l.total }} — abrir a tabela filtrada">{{ l.total }}</a></td>
                <td class="dsgov-numero text-gray-70"><a href="{{ l.url_cancelados }}">{{ l.cancelados }}</a></td>
                <td class="dsgov-numero dsgov-destaque"><a href="{{ l.url_ativos }}">{{ l.ativos }}</a></td>
                ...</tr>
            {% endfor %}
          </tbody>
          <tfoot><tr><th scope="row" class="dsgov-rotulo-linha">TOTAL</th><td class="dsgov-numero dsgov-separador">…</td>…</tr></tfoot>
        </table>
      </div>
    </div>
    <div class="tab-panel" id="painel-pct" role="tabpanel" aria-labelledby="tab-pct">… mesma matriz com percentuais (`51,3%`) …</div>
  </div>
</div>
<p class="text-down-01 text-gray-70 mt-2">NC = Nova contratação · RN = Renovação · VG = Vigente</p>
```

Regras: até ~14 colunas numéricas; acima disso divida em duas matrizes. Em celular a matriz rola
horizontalmente com o rótulo de linha fixo (não há o que decidir). `data-counter="false"` no `br-tab`
evita o contador de abas.
