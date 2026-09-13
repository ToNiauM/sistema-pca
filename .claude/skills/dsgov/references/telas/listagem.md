# Tela: Listagem (CRUD)

Gerada por `gerar_app.py`; a view herda de `ListagemView`. Anatomia fixa, de cima para baixo:

1. Cabeçalho da página: `h1` (plural do modelo) e, à direita, o único botão `primary` ("Nova diária").
2. Linha de busca e filtros: `br-input has-icon` de busca (`col-md-5`) + até 3 `br-select` de filtro
   (`col-md-3` cada). Envio por HTMX para `#listagem`. Mais de 3 filtros: mova os menos usados para o final
   e aceite uma segunda linha; nunca um painel lateral.
3. Chips dos filtros ativos (`br-tag interaction`) com "Limpar filtros".
4. `br-table`: título com contagem de registros, menu de densidade, cabeçalhos ordenáveis, coluna de
   ações fixa à direita (ver, editar, excluir como `br-button circle small` com ícones do vocabulário),
   estado vazio em uma linha.
5. Rodapé com `br-pagination` (10/20/50 por página, "1–20 de 137 itens", setas, números em desktop).

Regras:
- Até 6 colunas visíveis; a primeira é link para o detalhe. Números e moeda alinhados à direita
  (`dsgov-numero`). Datas `dd/mm/aaaa`. Status sempre como `br-tag status`.
- O link/ação "Ver" da linha carrega a querystring canônica da listagem (filtro+ordenação+
  página+colunas — ver `django.md` § "Estado canônico de listagem e restauração de rolagem"),
  para que Anterior/Próximo e "Voltar" no detalhe percorram a MESMA sequência filtrada; a `<tr>`
  da linha recebe `id="item-<pk>"` para que "Voltar" ancore de volta na linha visitada, sem JS.
- Nunca edição inline; editar é sempre a tela de formulário.
- Seleção em lote: só quando existe uma ação em massa real. Nesse caso use `data-selection` na
  `br-table` com `br-checkbox hidden-label` por linha e a `selected-bar` do componente oficial
  (ver `componentes/table.md`); a ação em massa é um POST com os ids.
- Exportar (CSV/XLSX) é um `br-button secondary` ao lado do primário, apontando para uma view que
  responde com o arquivo respeitando os filtros atuais (`{% url_com %}` sem `pagina`).
- Em celular a tabela rola horizontalmente; nada a fazer.
