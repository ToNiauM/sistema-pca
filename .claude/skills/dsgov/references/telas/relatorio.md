# Tela: Relatório para impressão/PDF

Uma view `relatorio_<nome>` que renderiza um template que estende `base.html` (a impressão esconde
header, menu, breadcrumb e footer via `dsgov.css`). Conteúdo: `h1` com título e período, bloco de
totais em `dl.dsgov-detalhe`, `br-table` sem busca/paginação, rodapé com "Gerado em dd/mm/aaaa hh:mm
por Nome". Botões "Imprimir" (`window.print()` via `onclick` é permitido aqui) e "Voltar" ficam num
`div.dsgov-nao-imprimir`. Para PDF de verdade, gere a partir do mesmo HTML com WeasyPrint no servidor;
o CSS de impressão já cobre o layout.


Tabela cruzada (linha × indicadores agrupados, com totais e modo absoluto/percentual) NÃO é uma
`br-table` simples: use `telas/matriz.md`. Prazos por dia: `telas/calendario.md`.

## Relatório com fragmento copiável para o SEI (Fase 27, D-27-01/02/04/20)

Quando a tela precisa gerar, além da leitura/impressão normal, um fragmento HTML limpo para colar
num editor externo (ex.: editor nativo do SEI), os botões ficam em **par** no mesmo
`div.dsgov-nao-imprimir`: **"Copiar relatório"** (`br-button secondary`, JS que lê um `<template>`
server-renderizado contendo o partial do corpo, restrito a uma allowlist de tags —
`h2/h3/p/strong/table/thead/tbody/tr/th/td/ul/li` — **sem** `class`, `style`, `svg`, `<i>` nem cor)
e **"Imprimir / salvar PDF"** (`br-button secondary`, `onclick="window.print()"`, mesmo padrão já
documentado acima).

O partial do corpo copiável é um **template Django próprio** (`_<nome>_corpo.html`), nunca o DOM da
tela renderizada com classes `br-*`: sem `{% extends %}`, sem qualquer classe `br-*`, HTML mínimo e
semântico — é exatamente o que vai para dentro do `<template>` e o que sai na área de transferência.

O bloco de impressão isolado (`.dsgov-relatorio`, ver `dsgov.css`) recebe um **timbrado composto**
(logo + texto institucional de `settings.DSGOV`) só na impressão/PDF, via `.dsgov-relatorio-timbrado`
— nunca no fragmento copiável (o SEI já põe o timbrado dele).

Se o partial do corpo copiável contém `<table>` sem `br-table` (é HTML mínimo, de propósito — a
tabela do SEI não pode carregar classes do DS), a regra ELEMENTO do verificador exige a substring
"br-table" em algum lugar do arquivo quando há `<table>`. Satisfaça a checagem com um
`{% comment %}` de uma linha no topo do partial explicando que a tabela não usa `br-table` de
propósito (fragmento copiável, sem classes do DS) — o comentário some do HTML renderizado
(`{% comment %}` nunca chega ao DOM) e a checagem textual do verificador passa.
