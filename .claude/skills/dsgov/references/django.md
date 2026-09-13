# Django no padrão dsgov

Tudo abaixo já existe no projeto gerado. Esta página diz **como usar**, não como reescrever.

## Formulários: `{{ form }}` e nada mais

`FORM_RENDERER` aponta para `core.forms.renderer.DSGovFormRenderer`. Consequências:

- `{{ form }}` renderiza todos os campos em `.row` com colunas (`col-12` por padrão; `col-md-6` para
  números, datas e booleanos; sobrescreva com `widget.attrs["col"]`).
- Um campo isolado: `{{ form.campo.as_field_group }}` (com rótulo, ajuda, erro e wrapper do DS).
  `{{ form.campo }}` sozinho é só o `<input>` cru e vai reprovar no verificador quando fora de wrapper.
- Erros gerais (`non_field_errors`) viram `br-message danger` no topo do formulário.
- `Select` e `ModelChoiceField` viram `br-select` com radios; `SelectMultiple` vira `br-select multiple`
  com checkboxes. Um `<select>` nativo nunca aparece. Para listas grandes (mais de 200 opções), limite o
  queryset do campo no `__init__` do form; autocomplete não faz parte do padrão.
- Datas usam `<input type="date">` (o navegador exibe em pt-BR). Para o valor inicial aparecer, o widget
  deve ter `format="%Y-%m-%d"`, o que o gerador já faz. Ao criar forms à mão, copie isso.
- Upload: `enctype="multipart/form-data"` já está no template de formulário gerado.
- Layout do formulário: `col-md-8` em desktop, ações no rodapé via `dsgov/_acoes_formulario.html`
  (`url_cancelar` obrigatório no contexto). Não invente outro rodapé.

## Listagens: herde de `core.listagem.ListagemView`

Declare `model`, `template_name`, `template_parcial`, `titulo`, `busca_campos`, `ordenacoes`,
`ordenacao_padrao`, `filtros`, `colunas` e, se houver filtros, `opcoes_filtros()`. A view responde a:

| Parâmetro GET | Efeito |
|---|---|
| `q` | busca `icontains` em `busca_campos` (OR) |
| `<filtro>` | igualdade (ou `__in` quando repetido) no lookup de `filtros` |
| `ordenar` | chave de `ordenacoes`, com `-` para descendente; chaves desconhecidas são ignoradas |
| `pagina` | número da página |
| `por_pagina` | 10, 20 ou 50 (qualquer outro valor cai no padrão) |

Com cabeçalho `HX-Request`, devolve só `template_parcial` (a tabela + paginação), que o HTMX troca em
`#listagem`. Busca, filtros, ordenação e paginação todos usam esse mesmo alvo e `hx-push-url`, então a
URL do navegador sempre reflete o estado e pode ser copiada.

Colunas: `{"campo": "servidor.nome", "rotulo": "Servidor", "tipo": "texto|numero|moeda|percentual|data|booleano|status", "ordenar": "chave", "chave": "situacao_chave"}`.
`campo` aceita caminho com ponto e métodos sem argumentos (`get_situacao_display`). A primeira coluna
vira link para `get_absolute_url`.

## Template tags (`{% load dsgov %}`)

| Tag/filtro | Uso |
|---|---|
| `{% url_com pagina=3 %}` | URL atual preservando a querystring; `None` remove o parâmetro |
| `{% ordenar_por "valor" "Valor" %}` | cabeçalho ordenável com ícone e HTMX |
| `{% paginacao page_obj "#listagem" %}` | rodapé `br-pagination` completo |
| `{% tag_status rotulo chave %}` | `br-tag status` com cor semântica fixa |
| `valor\|moeda` `\|numero:2` `\|percentual` `\|data_br` `\|cpf` `\|cnpj` `\|ou_traco` | formatação pt-BR |
| `obj\|atributo:"a.b"` | acesso dinâmico |
| `obj\|exibir:coluna` | formata conforme `coluna["tipo"]` |

## Mensagens

`messages.success/error/warning/info(request, "...")` aparecem como `br-message` no topo do conteúdo,
já com ícone e botão fechar; as de sucesso somem sozinhas em 8 s. Sempre uma frase curta com ponto final:
"Diária cadastrada com sucesso." Não use mensagens para explicar regras; para isso há `help_text`.

## Breadcrumb e título

Cada view põe `trilha` no contexto: lista de `(rótulo, url)`; o último item tem `url=None`. `titulo`
alimenta `<title>` e o `h1` das telas geradas.

## Menu

`core/menu.py::itens(request)`. O gerador insere um item por app; edite só rótulo, ícone e ordem. Itens
com `permissao` somem para quem não tem a permissão. Não há segundo lugar para navegação.

## Autenticação e permissões

- Login em `/login/` (tela DS), logout via POST em `/logout/`, `LoginRequiredMiddleware` global.
- Área do usuário opcional: defina `settings.DSGOV["PERFIL_URL_NAME"]` (ex.: `"core:perfil"`) e o header mostra **Meu perfil** no dropdown do avatar; a página em si (nome, trocar senha, sair) é do projeto.
- Views geradas exigem as permissões padrão (`app.view_modelo` etc.). Crie grupos no admin
  ("Operador", "Gestor") e atribua permissões; não escreva checagens de perfil em template.
- Ações de fluxo (aprovar, cancelar) são views POST próprias com `PermissionRequiredMixin` ou
  `@permission_required`, que redirecionam para o detalhe com uma mensagem.

## Dashboard

`core/views.py::inicio` monta `kpis`, `graficos` e `pendencias` (ver `telas/dashboard.md`). Agregue com o
ORM (`annotate`, `aggregate`, `Count`, `Sum`); nunca itere registros em Python para somar.

## Localização

`pt-br`, `America/Sao_Paulo`, `USE_TZ`, datas `dd/mm/aaaa`, moeda `R$ 1.234,56`. Meses como inteiros no
banco. `USE_THOUSAND_SEPARATOR` ligado.

## Testes

`pytest` com `pytest-django` (`pytest.ini` já aponta para `config.settings.dev`). Os testes gerados checam
que as telas respondem e usam o DS. Some testes de regra de negócio. O verificador pode entrar no CI:
`python3 <skill>/scripts/verificar.py .` devolve código 1 em desvio.

## Estado canônico de listagem e restauração de rolagem

Duas peças reutilizáveis nascidas de um projeto concreto (PCA CFC, quick 260911-usq — "a
reunião mensal de acompanhamento percorre dezenas de itens filtrados em sequência; perder o
filtro a cada clique em Ver/Editar obriga a refiltrar o tempo todo").

**Querystring canônica de uma listagem.** Toda tela de listagem com filtro/ordenação/paginação
precisa de UMA função que reserialize só os parâmetros validados (nunca o GET cru) e sirva de
fonte única para qualquer link que devolva o usuário à MESMA listagem: link da linha para o
detalhe, Anterior/Próximo dentro do detalhe, "Voltar", a trilha até a listagem, e os redirects
PRG das ações de fluxo (editar, transição de estado). Cada parâmetro extra (ordenação, página,
tamanho de página, colunas visíveis) só entra na string quando a CHAVE está presente no GET —
nunca grava o padrão implícito. Sessão como fallback: a mesma querystring, gravada com a guarda
"só grava se diferir" (evita escrita de sessão a cada requisição idêntica), permite que sair da
listagem filtrada por outro caminho (menu, trilha de outra tela) e voltar por uma URL crua
restaure o mesmo estado — um GET vazio e não-htmx redireciona para o estado guardado. Uma ação
"Limpar filtros" precisa de um marcador explícito (`?limpar=1`) na própria querystring: sem ele,
o clique produz uma querystring vazia indistinguível de uma chegada crua pelo menu, e o filtro
"limpo" nunca fica gravado de verdade.

Para ações de fluxo cujo formulário tem `action=`/`hx-post` explícito (não herdam a querystring
da barra de endereço na submissão), propague a querystring de retorno por um campo oculto
(`<input type="hidden" name="querystring_retorno">`) em vez de depender só da URL: a view lê da
URL no GET (o link que trouxe o usuário) e do campo oculto no POST.

## Restauração de rolagem em telas de recarga completa

Nas telas sem HTMX (recarregam a página inteira a cada filtro — HTMX é exceção, não regra:
listagem com `hx-get`+`hx-push-url` já preserva posição/scroll sozinha, D-26-19/20), trocar um
filtro tradicionalmente volta ao topo — o "pisca" que o usuário nota de imediato. `dsgov.js`
(vendorizado, `core/static/dsgov/js/dsgov.js`) resolve isso de forma genérica, sem tocar nenhum
template dessas telas: um listener em `document` no evento `submit` grava `window.scrollY` em
`sessionStorage` por pathname, só para `<form method="get">` sem `hx-get`/`hx-post`/`hx-boost`
(a guarda que exclui a listagem HTMX); um segundo listener em `DOMContentLoaded` só restaura a
posição quando `document.referrer` aponta para o MESMO pathname (troca de filtro na própria
tela) — chegada por outro caminho (menu, outra tela) nunca herda rolagem de uma visita anterior
não relacionada. `sessionStorage` guarda só um número por aba, nunca enviado ao servidor.
