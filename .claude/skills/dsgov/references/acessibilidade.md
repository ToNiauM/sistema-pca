# Acessibilidade (obrigatória por lei: LBI art. 63, e-MAG, WCAG 2.1 AA)

O DS já entrega contraste, foco visível (tracejado dourado) e componentes com teclado. O que fica com
o desenvolvedor, e o verificador cobra parte:

- Um `h1` por página; hierarquia `h1 > h2 > h3` sem pular níveis.
- Todo ícone decorativo com `aria-hidden="true"`; botão só com ícone tem `aria-label` com verbo e
  objeto ("Editar diária de Maria").
- Todo campo tem `<label for>` (o renderer garante). Erros com `role="alert"`.
- Tabelas com `<caption>` (pode ser `sr-only`), `<th scope="col">`, `data-th` nas células.
- Links dizem para onde vão ("Ver todos os processos"), nunca "clique aqui".
- Gráficos com `role="img"` e `aria-label` resumindo o dado; o número também aparece em texto.
- Cor nunca é a única pista: status tem texto na tag; erro tem ícone e mensagem.
- Skiplinks e `accesskey` 1–4 já vêm do layout; não remova.
- Teste com teclado: Tab percorre header → menu → conteúdo → footer; Esc fecha menu e dropdowns.
