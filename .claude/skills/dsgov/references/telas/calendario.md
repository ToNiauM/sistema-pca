# Tela: Calendário (mensal e anual)

Para prazos/eventos por dia. Uma grade de **7 colunas** (D S T Q Q S S) por mês, como `br-table small`
com a classe `dsgov-calendario`, dentro de um `br-card`; **nunca** a `br-table` genérica com rolagem
(o CSS da skill fixa o layout e desliga o `overflow` do `.responsive`). Controles no topo, à direita
do `h1`, num único `<form method="get">`: `br-select` de visão (Mensal | Anual), mês (na mensal),
exercício, e o filtro de situação (`br-select`); botão terciário "Aplicar". A legenda é informativa,
em `br-tag status` + texto (`<span class="br-tag status bg-success small" aria-hidden="true"></span> Concluído`),
não é um grupo de botões.

**Anual** (`div.row.dsgov-calendario-anual`): 12 cards `col-sm-6 col-lg-3`, título do mês em `h2.text-up-01`
com link para a visão mensal daquele mês. Cada dia com evento mostra o número do dia como link para a
tabela filtrada por aquele dia, a contagem embaixo e até 3 pontos de situação (`br-tag status bg-*
small`); dias de outros meses levam `dsgov-fora-do-mes`; o dia corrente leva `dsgov-hoje`.

**Mensal** (`div.dsgov-calendario-mensal`): um só card `col-12`, células altas com `ul` de até 3 itens
(`Item N` como link para o detalhe, precedido do ponto de situação) e "+n" como link para a tabela
filtrada pelo dia. Cabeçalhos dos dias em `<th scope="col" abbr="Segunda">S</th>`.

```django
<div class="br-card"><div class="card-header"><h2 class="text-up-01 mb-0"><a href="{{ mes.url }}">{{ mes.nome }}</a></h2></div>
<div class="card-content">
  <div class="br-table small dsgov-calendario">
    <div class="table-header"></div>
    <table>
      <caption class="sr-only">{{ mes.nome }} de {{ ano }}</caption>
      <thead><tr>{% for d in dias_semana %}<th scope="col" abbr="{{ d.nome }}">{{ d.sigla }}</th>{% endfor %}</tr></thead>
      <tbody>
        {% for semana in mes.semanas %}<tr>
          {% for dia in semana %}
          <td class="{% if dia.fora_do_mes %}dsgov-fora-do-mes{% endif %}{% if dia.hoje %} dsgov-hoje{% endif %}">
            {% if dia.total %}<a href="{{ dia.url }}" aria-label="{{ dia.data|date:'d/m' }}: {{ dia.total }} prazo(s)">{{ dia.numero }}</a>
              <div class="text-down-01">{{ dia.total }}{% for s in dia.situacoes %}<span class="br-tag status {{ s.classe }} small" title="{{ s.rotulo }}" aria-hidden="true"></span>{% endfor %}</div>
            {% else %}{{ dia.numero }}{% endif %}
          </td>
          {% endfor %}
        </tr>{% endfor %}
      </tbody>
    </table>
  </div>
</div></div>
```

Cores dos pontos: `bg-success` (concluído/no prazo), `bg-info` (em tramitação), `bg-danger`
(atrasado), `bg-warning` (pendente), `bg-gray-40` (cancelado) — as mesmas de `br-tag status` e de
`CORES_STATUS`; a situação também aparece em texto (title/aria-label e na tabela filtrada).

## Grade uniforme, alturas e limite de itens (Fase 28/Plano 28-07, D-28-37/38/39/40)

**42 células sempre** (6 semanas × 7 dias), inclusive fevereiro: `Calendar.monthdatescalendar`
devolve 4, 5 OU 6 semanas conforme o mês/ano — o backend completa com semanas REAIS (continuação
cronológica a partir do último dia já listado, nunca uma data inventada) até fechar em 6. Células
de preenchimento (`dia.fora_do_mes`) nunca repetem eventos de meses vizinhos.

**Meses por linha (anual):** `col-12 col-md-6 col-lg-4 col-xl-3` — 1 (<992px) / 2 (992–1279px) /
3 (1280–1599px) / 4 (≥1600px). Substitui os 4 por linha fixos em 1280px de versões anteriores.

**Identificação dentro da célula:** número do dia (link de drill-down, inalterado) + identificação
NUMÉRICA de cada item visível (sem o texto "Item" na apresentação compacta — só o número, com o
ponto de situação ao lado — o prefixo "Item N: objeto" continua no `aria-label` para leitor de
tela) + "+N" para os ocultos, mesmo link de drill-down por dia. Limite CENTRALIZADO no backend
(nunca `|slice` no template): **1 item + "+N" na visão anual**, **3 itens + "+N" na mensal**.
Ordem sempre por `item_pca`/`id` — estável entre requisições, nunca a ordem incidental do banco.

**Alturas fixas** (`overflow: hidden` — o limite de itens já resolvido em Python garante que o
conteúdo nunca precisa ser cortado por CSS, só protegido contra excesso):

| Visão  | Ponteiro | Toque (`@media (pointer: coarse)`, alvos ≥ 40px) |
|--------|----------|---------------------------------------------------|
| Anual  | 80px     | 112px                                              |
| Mensal | 128px    | 192px                                               |

## Popover de leitura (Fase 28/Plano 28-07, D-28-41/42)

Cada item (anual e mensal) é um `<a class="dsgov-calendario-item" data-popover-calendario
aria-describedby="popover-calendario-{id}">` seguido IMEDIATAMENTE (irmão, mesma exigência
estrutural do `.br-tooltip` nativo) de um `<div class="br-tooltip" role="dialog"
aria-modal="false" data-popover-calendario id="popover-calendario-{id}">` com
`popover-header`/`popover-body`/`popover-footer` (Item + Objeto, UO + Valor previsto + Valor
contratado quando preenchido — "0" aparece, só ausência real vira reticência — e os links
"Ver mais"/"Fechar detalhes"). **Nunca a inicialização automática do `BRTooltip`** (depreciado,
sem semântica de "clique fixa"/Esc global — `references/componentes/tooltip.md`): `dsgov.js`
exclui `[data-popover-calendario]` da seleção `.br-tooltip` do loop de `COMPONENTES` e implementa
comportamento próprio (mostrar em hover/foco, fixar em clique/Enter/toque — um por vez — Esc/
"Fechar detalhes" fecham e devolvem o foco; `mouseenter` no próprio popover cancela o
fechamento). **Deviation Rule 1 (bug evitado):** o marcador do popover NUNCA usa o atributo HTML5
nativo `popover` (Popover API) — navegadores modernos aplicam `display: none !important` via
UA stylesheet a qualquer elemento `[popover]` que não tenha sido explicitamente aberto via
`.showPopover()`, uma regra `!important` de origem UA que nenhum CSS de autor (nem `!important`)
consegue sobrepor; sem chamar essa API, o popover ficaria permanentemente invisível em
navegadores com suporte nativo. O efeito visual "popover" do DS (`max-width:320px`) é replicado
por uma regra equivalente sobre `.br-tooltip[data-popover-calendario]`, e o posicionamento usa
`position: fixed` (calculado em JS a partir do `getBoundingClientRect` do ativador) em vez do
`position: absolute` padrão do componente, para escapar do `overflow: hidden` da célula.

"+N" abre `/tabela` com o MESMO dia (`dia_calendario`) e a MESMA seleção de situações da legenda
(`condicao_legenda`, agora um parâmetro canônico de `apps.pca.filtros.PARAMETROS_FILTRO` — união
nunca interseção entre Cancelados e as situações efetivas marcadas, D-28-42): como
`querystring_filtros` já propaga qualquer parâmetro canônico ativo, nenhuma montagem extra é
necessária no href de `celula.url`.
