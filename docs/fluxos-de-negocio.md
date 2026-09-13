# Fluxos de negócio

## Ciclo de vida de um item do PCA

1. **Planejamento** — um item nasce em `pca:criar_processo` (`views_processo.criar_processo_view`)
   com `item_pca` alocado por `ProcessoAlocador` (chave natural única por exercício) e os campos
   de planejamento (`descricao_objeto`, `tipo`, `categoria`, `unidade_organizacional`,
   `valor_estimado`, `mes_previsto`, `data_inclusao_pca`, `grau_prioridade`, `classificacao`).
2. **Funil processual interno** — datas de envio/recebimento (`data_envio_gelic`,
   `data_recebimento_gelic`) e prazo de entrega (`prazo_entrega`) são preenchidas conforme o
   processo avança; `apps/pca/regras_situacao.py::situacao_por_eventos()` deriva `situacao`
   automaticamente a cada fato gravado (nunca por comparação de "hoje").
3. **Execução contratual** — modalidade, contrato, fornecedor (CNPJ/razão social), vigência e
   valor contratado entram no bloco de execução (colunas 25–39 de `Processo`), opcional e
   nullable até serem preenchidas.
4. **Publicação** — três datas de lançamento marcam a publicação nos canais de transparência do
   órgão: `data_lancamento_spw`, `data_lancamento_wordpress`, `data_lancamento_dados_abertos`.
5. **Encerramento/virada de exercício** — ao fim do ano, o wizard de virada (`pca:virada` →
   `virada_ajustar` → `virada_revisar` → `virada_confirmar`) cria os itens do próximo exercício a
   partir de um `RascunhoVirada`, com revisão item a item antes de confirmar.

## Reunião mensal e registro de acompanhamento

Uma `Reuniao` é entidade no banco (`data`, `exercicio`, `condutor`, `situacao` aberta/fechada);
no máximo uma fica `ABERTA` por vez (`UniqueConstraint` condicional). O modal "Registrar
acompanhamento" (`pca:acompanhamento_modal`, único `br-modal` do sistema) chama
`apps.pca.services.registrar_acompanhamento()`, que:

- Se `usar_reuniao_corrente=True` (padrão) e nenhuma reunião for passada explicitamente, associa
  o novo `Acompanhamento` à reunião `ABERTA` (`reuniao_corrente()`); sem nenhuma aberta, usa a
  data de hoje e nenhuma reunião.
- Grava uma promessa de prazo (`prazo_prometido`) e/ou uma nova situação (`situacao_novo`).
- Marca `transicao_manual=True` **somente** quando `situacao_novo` vem de uma via não-automática
  (o modal de transição de situação, `pca:transicao_processo`) — nunca quando vem de
  `aplicar_regras_automaticas` (que sempre usa `tipo_evento=AUTOMATICO`).

**Precedência manual (D-29-26):** ao registrar só uma nova promessa de prazo, sem escolher
situação explicitamente, o serviço reavalia a situação com a mesma regra de
`aplicar_regras_automaticas()` — mas **só se não existir nenhuma transição manual anterior**
(`processo.acompanhamentos.filter(transicao_manual=True).exists()`). Existindo, a situação
atribuída manualmente é preservada; "manual vence, automático não reverte".

## Transição de situação e de estado

- `situacao` (eixo `Situacao`: no_prazo/atrasado/em_tramitacao/concluido) muda por
  `pca:transicao_processo` (modal, marca `transicao_manual=True`) ou automaticamente por
  `aplicar_regras_automaticas()` a cada edição de campo relevante — nunca grava `atrasado`
  automaticamente (correção de leitura, não escrita).
- `estado` (eixo `Estado`: ativo/cancelado) só muda pelo Django Admin
  (`apps.pca.services.alterar_estado()`), chamado por `ProcessoAdmin.save_model` — nenhuma view
  de usuário final altera `estado`.

## Estado canônico da listagem

A tela Processos (`pca:tabela`) persiste seu estado (filtros, ordenação, página) em sessão
(`request.session[CHAVE_SESSAO_ESTADO_TABELA]`), a partir da querystring canônica
(`querystring_tabela(request.GET)`, `apps/pca/filtros.py`). Uma navegação de volta ao menu, sem
querystring, redireciona para o último estado salvo — nenhum filtro se perde ao circular pela
casca. A seleção de colunas por seção (`colunas_por_secao()`, `apps/pca/colunas.py`) tem
persistência própria e independente, em outra chave de sessão. O detalhe do processo
(`pca:detalhe_processo`) navega Anterior/Próximo seguindo exatamente a mesma ordenação da
tabela (`_ordenar_para_tabela`), não uma ordem própria.

## Colunas por seção

`apps/pca/colunas.py::COLUNAS_PADRAO` é o registro único de colunas, compartilhado entre a tela
(`/tabela`) e a exportação XLSX (`apps/pca/exportacao.py`) — antes deste módulo os dois tinham
registros divergentes. Cada `Coluna` declara uma `secao` (as mesmas 4 seções do formulário de
processo), usada para agrupar o seletor "Colunas" em fieldsets.

## Import e export

- **Import** (`apps/pca/importacao/executor.py::executar_import()`), disparado por
  `manage.py importar_pca` (CLI) ou pela tela de importação do Admin — sempre com histórico
  (`bulk_create_with_history`, nunca `use_bulk=True` do `django-import-export`, que desligaria
  `post_save`), idempotente em reexecução (chave natural `origem_hash` do `Acompanhamento`), e
  sempre emite um relatório de conferência nominal, mesmo sob `--dry-run`. O arquivo padrão é
  `apps/pca/fixtures/modelo-controle-exemplo.xlsx` — a fixture anonimizada de exemplo, não dado
  real de nenhum órgão.
- **Export** (`apps/pca/exportacao.py::exportar_csv()`/`exportar_xlsx()`) usa o mesmo registro de
  colunas da tela, respeitando os filtros/colunas selecionados; `apps/pca/exportacao_resumo_uo.py`
  faz o mesmo para o resumo por unidade organizacional. Ambos síncronos, sem fila.

## Dashboards, análises, calendário e resumo por UO

`core:inicio` é o painel único (fusão de "Início" e "Dashboard"); `pca:analise` cobre gráficos que
não cabem no painel; `pca:calendario` mostra prazos por mês; `pca:resumo_uo` agrega por unidade
organizacional. As quatro recarregam a página inteira a cada troca de filtro (sem HTMX) — só
`pca:tabela` e o modal de acompanhamento usam HTMX. Toda agregação usa `annotate`/`aggregate` do
ORM (`ProcessoQuerySet.para_listagem()`), nunca soma em Python.

## Busca

`pca:busca` é o alvo do campo de busca global do header (configurado em
`settings.DSGOV["BUSCA_URL_NAME"]`) — busca ampla sobre descrição, justificativa e números SEI.

## PWA

`core:manifest`/`core:service_worker` servem `manifest.json`/`sw.js`; o nome do cache
(`pca-static-vN`, `core/views.py`) sobe a cada mudança de estático — hoje `pca-static-v44`.

**Fontes verificadas:** `apps/pca/regras_situacao.py`, `apps/pca/services.py`,
`apps/pca/importacao/executor.py`, `apps/pca/exportacao.py`, `apps/pca/colunas.py`,
`apps/pca/views.py`, `apps/pca/views_processo.py`, `apps/pca/urls.py`, `core/views.py`.
