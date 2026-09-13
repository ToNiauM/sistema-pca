# Estrutura fixa da página

Todo sistema gerado pela skill herda de `core/templates/base.html`, que reproduz o **Template Base**
oficial do DS (`@govbr-ds/core/dist/templates/base/base.html`) com menu lateral off-canvas. A ordem dos
blocos é imutável e cada bloco é um partial em `core/templates/dsgov/`:

```
<body>
  _skiplink.html      nav.br-skiplink  — 4 atalhos (conteúdo, menu, busca, rodapé) com accesskey 1-4
  _header.html        header.br-header#header[data-sticky]
                        header-top:    logo do órgão | divisor | assinatura (nome do órgão)
                                       header-actions: Acesso Rápido (dropdown) · Funcionalidades (dropdown) ·
                                                       busca · login/avatar
                        header-bottom: botão menu (fa-bars) · header-title (nome do sistema) · header-subtitle
                                       · header-search
  main#main.d-flex.flex-fill.mb-5 > .container-lg.d-flex > .row
    _menu.html        div.br-menu#main-navigation  — menu lateral com os módulos (menu-folder / menu-item)
    div.col.mb-5
      _breadcrumb.html nav.br-breadcrumb — casa + trilha; último item data-active
      _mensagens.html  div#mensagens — django.contrib.messages como br-message
      div.main-content.pl-sm-3.mt-4#main-content
        {% block conteudo %}
  _footer.html        footer.br-footer#footer — logo, nome do órgão, links institucionais, texto legal
  div.br-cookiebar.default.d-none  (presente, inerte)
  scripts: core.min.js → htmx.min.js → echarts.min.js (só se a página tem gráfico) → dsgov.js → echarts-dsgov.js
```

Ordem dos CSS no `<head>`: `fontes.css` → `core.min.css` → `all.min.css` (Font Awesome) → `dsgov.css`.

Inicialização do JavaScript do DS: o `core.min.js` 3.7.0 só exporta os construtores (`core.BRSelect`,
`core.BRMenu`...) e **não inicializa nada sozinho**; `dsgov.js` faz isso no carregamento e a cada troca
do HTMX. Por isso um componente novo num fragmento HTMX funciona sem código extra, e por isso não se
usa `core-init.js` (ele carrega exemplos da documentação e quebra sem eles). Nunca chame `new core.X`
à mão em template; se um componente não está na lista de `dsgov.js`, é porque não precisa de JS.

CSS: não existe `<style>` em template e não existe outro arquivo CSS do projeto além de `dsgov.css`,
que só tem alturas de gráfico e ajustes que o DS não cobre (lista fechada; ver `verificador.md`).

## O que é configurável (via `settings.DSGOV`)

```python
DSGOV = {
    "ORGAO": "Conselho Federal de Contabilidade",   # assinatura do header e footer
    "ORGAO_SIGLA": "CFC",
    "SISTEMA": "Controle de Diárias",              # header-title
    "SISTEMA_SUBTITULO": "Gestão de viagens a serviço",  # header-subtitle (opcional)
    "LOGO": "img/logo-orgao.svg",                   # caminho em static; se vazio, exibe a sigla em texto
    "LINKS_ACESSO_RAPIDO": [("Portal do órgão", "https://..."), ("Ouvidoria", "https://...")],
    "RODAPE_TEXTO": "Todo o conteúdo deste sistema está sob a licença ...",
}
```

O **menu** vem de `core/menu.py` (função `itens(request)` devolvendo lista de dicts com `rotulo`, `icone`,
`url`, `filhos`, `permissao`). A view não mexe no menu; o context processor `dsgov` injeta tudo.

## Página padrão de conteúdo

Dentro de `{% block conteudo %}` a hierarquia é sempre:

```django
{% block conteudo %}
<div class="d-flex align-items-center mb-4">           {# cabeçalho da página #}
  <h1 class="mb-0">Título da tela</h1>
  <div class="ml-auto">{# ações primárias da página: 1 botão primary, no máximo 1 secondary #}</div>
</div>
... blocos da tela (ver references/telas/) ...
{% endblock %}
```

- Um único `h1` por página, igual ao último item do breadcrumb e ao `<title>`.
- Botão **primary** é único por tela (a ação principal). Ações secundárias são `secondary`; ações
  terciárias (cancelar, voltar) são `br-button` sem ênfase.
- Botões de ação em linha de tabela: `br-button circle small` com `aria-label`, ícone do vocabulário fixo.
- Larguras: formulários e detalhes ocupam `col-md-8` (nunca a largura toda em desktop); tabelas e
  dashboards ocupam `col-12`.
- Espaço entre seções: `mb-4`. Entre campos: `mb-3`. Entre cards na mesma linha: `mb-3` no col.

## Breadcrumb

Cada view informa `trilha = [("Processos", url), ("Editar", None)]` no contexto; o último item é a tela
atual (sem link). O primeiro item é sempre a casa (`fa-home`) apontando para o dashboard.

## Responsividade

Nada a decidir: o menu vira off-canvas abaixo de 992px por conta do DS, a tabela ganha rolagem
horizontal, os cards de KPI caem para 2 e depois 1 por linha pelas classes `col-sm-6 col-md-3`.

## Container: sempre `container-lg`

Terceiro ponto de extensão que um projeto concreto tinha sobre a skill, ao lado de
`settings.DSGOV` e de `core/menu.py::itens()`/`trilha` (ver `references/django.md`) — REVOGADO em
`[quick 260911-p8u]`. A variante fluida (`casca_fluida`, chave de contexto que trocava
`container-lg` por `container-fluid` no wrapper `<main id="main"> > div`) deixou de existir:
`.container-fluid` não define largura máxima nenhuma, então em monitores grandes o conteúdo
esticava até a borda da janela — o oposto do padrão gov.br, que concentra tudo dentro de margens
generosas. `container-lg` já resolve isso via `--grid-maxwidth` do `core.min.css`: 1240px entre
992 e 1599px (`--grid-breakpoint-lg` 1280px menos `--grid-desktop-margin` 40px), 1560px a partir
de 1600px (`--grid-breakpoint-xl` 1600px menos `--grid-tv-margin` 40px).

```django
<main class="d-flex flex-fill mb-5" id="main">
  <div class="container-lg d-flex">
```

`base.html` volta a ter só `container-lg`, sem condicional — não existe mais nenhuma chave de
contexto de largura ao lado de `settings.DSGOV` e `core/menu.py::itens()`/`trilha`; qualquer
sistema gerado por esta skill a partir de agora usa sempre a largura concentrada, sem exceção.

## Menu expandido em telas grandes (≥ 992px)

O `.br-menu` puro (sem a variante `push` do `core.min.js` — este projeto NUNCA usa `push`, só a
classe base `br-menu`, ver `_menu.html`) é off-canvas em QUALQUER largura por padrão do DS: abrir
`#main-navigation` cobre a tela inteira com `.menu-container{position:fixed;inset:0}` mais um
`.menu-scrim` escuro, deixando visível só a coluna estreita do `.menu-panel` (`col-sm-4 col-lg-3`)
à esquerda. Correto no celular; ruim em telas grandes, onde bloquear o resto do conteúdo obriga
fechar o menu para continuar navegando, mesmo sobrando espaço de tela. `[quick 260911-p8u]`
resolveu isso: a partir de 992px, o `.menu-scrim` some e o `.menu-container` vira
`pointer-events: none` (restaurado em `.menu-panel` com `pointer-events: auto`) — o menu continua
fixo na tela e com scroll próprio (`.menu-panel` já era `position: relative`/`overflow: auto`,
nada mudou aí), mas o clique atravessa até o conteúdo principal em vez de ser bloqueado pelo
retângulo vazio do `.menu-container`. Abaixo de 992px nada muda: off-canvas com scrim bloqueante,
contrato mobile do DS intacto. Implementação: bloco `@media (min-width: 992px)` no final de
`dsgov.css`, três regras por seletor de ID (`#main-navigation.active .menu-container/.menu-panel/
.menu-scrim`) — sem tocar `dsgov.js`, sem classe CSS nova, sem `!important`.

## Contratos de espaçamento (fixos para toda composição de página)

Três distâncias cobrem toda composição de layout desta família de telas — não decidir de novo a
cada tela nova:

| Distância | Uso | Utilitário DS | Token |
|---|---|---|---|
| 24 px | Entre seções de uma página (blocos, cards empilhados) | `mb-4`/`mt-4` | `spacing-scale-3x` |
| 16 px | Entre campos de um formulário/filtro | `mb-3` | `spacing-scale-2x` |
| ≥ 8 px | Entre ações/botões adjacentes na mesma linha | `mr-2`/`ml-2`/`gap-2` | `spacing-scale-base` |

`mr-1`/`ml-1` é reservado para o espaço ícone-rótulo DENTRO de um único controle (ex.: ícone e
texto do mesmo botão) — nunca entre dois botões ou ações distintas, que sempre usam o espaçamento
de 8 px acima.

## Breakpoints (únicos usados em qualquer grid de composição)

O DS expõe 576/768/992/1200/1600 nas classes `col-{sm,md,lg,xl,xxl}-*`, mas toda decisão de grid
de composição de página (quantas colunas por linha, quando empilhar) usa só quatro breakpoints:
**576, 992, 1280, 1600 px**. 768 nunca é usado como ponto de quebra de composição — é só uma
largura de teste de regressão visual (tablet retrato), não um breakpoint de decisão de layout.
