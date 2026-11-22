# Análises — fluxo de caixa, estatísticas e prazos

Guia de usuário das Fases 36 e 37. O menu **Análises** é uma pasta com quatro telas:
**Painel** (a tela de sempre, aberta a todo autenticado), **Fluxo de caixa**, **Estatísticas**
e **Prazos** — estas três últimas restritas a quem tem a permissão `pca.ver_analises`
(ver "Acesso" abaixo; a Fase 36 restringia só Prazos, a Fase 37 estendeu a restrição às três).
Nenhuma tela grava dado sozinha, exceto o "renovar?"/"não renovar?" de Prazos e as ações de
simulação/cenário do Fluxo de caixa (que gravam só no rascunho da sessão do próprio usuário, ou
em um cenário nomeado quando ele pede explicitamente) — o resto é cálculo por requisição,
recarregado a cada troca de filtro.

## O que é cada tela

- **Painel** — os KPIs e gráficos que já existiam antes da Fase 36. Sempre visível.
- **Fluxo de caixa** (`/analise/fluxo`) — quanto o CFC tem comprometido mês a mês até
  31/12 do exercício corrente e ano a ano pelo restante do exercício corrente mais os 5
  exercícios seguintes, separado em quatro camadas empilhadas. Desde a Fase 37, tem recorte
  por ano/mês com lista de contratações, memória de cálculo por item, simulação de variáveis
  e cenários salvos (ver seções abaixo), além do CSV de parcelas de sempre e um relatório
  XLSX novo.
- **Estatísticas** (`/analise/estatisticas`) — execução financeira por unidade, desvio entre
  valor estimado e contratado por modalidade, concentração de valor (Pareto/top 10
  fornecedores), faixas de duração de vigência, vencimentos por trimestre e perfil de valor
  × modalidade.
- **Prazos** (`/analise/prazos`) — a seção **Contratos a vencer** no topo (itens com contrato e
  vigência informada, destino em N+1, ação de renovação — ver seção abaixo), lead time por
  etapa (Gelic → assinatura → conclusão), curva de sobrevivência Kaplan–Meier e score de risco
  de atraso por item aberto.

## Camadas do fluxo de caixa

A projeção de desembolso é sempre a soma de até quatro camadas, empilhadas no gráfico e na
tabela. A Fase 37 corrigiu a aritmética das quatro (`melhorias.md` M01/M02/M03/M05/M10) sem
mudar o que cada camada representa:

1. **Contratado** — o valor já assinado. Um contrato de periodicidade **"global"** (a soma
   inteira cobre um período, ex. um Aditivo de R$ 120.000,00 de 15/01 a 14/01 do ano
   seguinte) é distribuído por **peso de dias**: cada competência recebe
   `valor_total × (dias da competência dentro do período ÷ dias TOTAIS do período)` — nunca
   mais meses de calendário — de modo que a soma das parcelas bate exatamente com o valor
   contratado, até o centavo, em qualquer vigência (M01). Um contrato **"mensal"** (parcela
   fixa por mês, ex. R$ 1.000,00/mês) lança o valor mensal **literal** em cada competência,
   sem nenhum rateio — nunca mais tratado como se fosse "global" dividido por 12 (M03).
   Contratos de entrega única concentram 100% no mês de vigência-fim, ou 30 dias após a
   assinatura quando não há vigência cadastrada. Um item com **mais de um contrato
   independente** (identificados pelo campo "Instrumento" de cada evento financeiro — ex. um
   contrato principal mais um apostilamento com instrumento próprio) soma os dois por mês,
   nunca substitui um pelo outro; em caso de dois eventos valendo para a mesma data, vale o
   de maior id (o mais recente) — M05.
2. **Renovação prevista** — a continuidade presumida de um contrato continuado, quando o
   campo "Renovação prevista" do Processo está marcado e o fim da vigência atual cai dentro
   do horizonte único (restante do exercício corrente + 5 exercícios seguintes). A renovação
   passou a receber o **mesmo reajuste projetado** que o contrato original receberia se
   continuasse — antes ficava congelada no valor da última parcela, subestimando o
   comprometido futuro (M02).
3. **Reajuste projetado** — só a *diferença* que o índice de reajuste (`IndiceReajuste`,
   IPCA por padrão) acrescenta no aniversário da vigência, composto ano a ano. A data-base do
   reajuste passa a ser redefinida a cada **evento real** registrado pela sincronização com o
   SEI (um reajuste ou repactuação de fato assinado) — um evento real em janeiro nunca mais soma, no
   mesmo mês, o reajuste projetado por cima do reajuste que já aconteceu de verdade (M02).
4. **Planejado** — itens do PCA que ainda não têm valor contratado, com início estimado a
   partir do mês previsto ou do prazo vigente mais o "lead time" mediano (histórico de
   quanto tempo leva do recebimento no Gelic até a assinatura, por estrato); preserva os
   centavos originais do valor estimado, sem arredondamento intermediário.

Cada camada só aparece com valor quando há dado suficiente para calculá-la — a ausência de
uma camada num item específico é normal (ex.: um item planejado não tem "Contratado"). Quando
o índice de reajuste não tem percentual cadastrado para um ano-alvo, o sistema **nunca zera
silenciosamente** a projeção: usa o último ano conhecido como aproximação e registra o fato em
"Premissas" — mesmo quando não há absolutamente nenhum ano cadastrado para aquele índice
(M10).

## Cenários (base/contratado/sem reajuste/sem renovação)

O seletor "Cenário" do formulário de filtros troca quais camadas entram na soma, sem alterar
nenhum dado — não confundir com "Cenário salvo" (ver seção própria abaixo, um recurso
diferente, introduzido na Fase 37):

- **Base** — as quatro camadas (1+2+3+4). É o cenário padrão de reunião.
- **Contratado** — só o que já está assinado (camada 1), o piso conservador.
- **Sem reajuste** — contratado + renovação + planejado (1+2+4), índice de reajuste zerado.
- **Sem renovação** — contratado + reajuste + planejado (1+3+4), sem presumir continuidade.

## Premissas e itens sem dado

No rodapé da tela Fluxo de caixa (e, de forma equivalente, em Prazos/Estatísticas) há dois
blocos:

- **"Itens sem dado"** — processos que não entraram na projeção porque falta uma informação
  mínima (ex.: vigência ausente num contrato "único"), com o motivo explícito.
- **"Premissas"** — hipóteses assumidas quando o dado exato não existe: regime de execução
  "presumido" (continuado/único, deduzido da duração da vigência quando o campo está em
  branco), índice de reajuste do último ano conhecido repetido para anos futuros sem
  percentual cadastrado (ou o aviso explícito de que nenhum ano está cadastrado — M10), lead
  time padrão de 90 dias quando não há histórico suficiente do estrato (menos de 5 casos
  concluídos). Cada texto é consolidado por (índice, ano-alvo) — no máximo 1 linha por
  combinação, nunca 1 linha por item × mês.

Todo número preditivo (reajuste projetado, lead time, score de risco, data provável) cita o
método e o `n` (quantidade de casos) usado — números sem base estatística suficiente caem
para uma estimativa geral, nunca aparecem como se fossem precisos.

## Recorte e drill-down

Desde a Fase 37, a tela `/analise/fluxo` aceita um recorte por **ano** (do exercício corrente
até +5) e, opcionalmente, **mês** — parâmetros `ano`/`mes` na URL:

- Um card de KPI extra ("Projeção `<recorte>`") mostra o total do recorte, com a composição
  pelas 4 camadas.
- Chips removíveis (Ano/Mês) e "Limpar filtros" ao lado do recorte ativo.
- **Drill-down**: clicar numa barra do gráfico mensal preenche `?ano=A&mes=M`; numa barra do
  gráfico anual preenche `?ano=A`; numa célula de ano da tabela UO × ano preenche
  `?ano=A&uo=U`.
- A lista **"Contratações neste recorte"** mostra, para o ano/mês selecionado, cada item que
  compõe o total — agrupada por item, ordenada por valor decrescente, paginada, com link
  "Ficha" (para o processo) e link **"Memória"** (para a memória de cálculo do item, ver
  abaixo) lado a lado.

Ano/mês inválidos (fora do intervalo permitido) são simplesmente ignorados, nunca produzem
erro.

## Memória de cálculo

Cada item tem uma página própria de memória de cálculo:
`/analise/fluxo/memoria/<item_pca>` (link "Memória" na lista "Contratações neste recorte" e
link "Memória de cálculo" na seção "Execução contratual" da ficha do item). Quatro blocos:

1. **Fonte e eventos considerados** — os eventos financeiros/contratos que entraram no
   cálculo do item.
2. **Eventos descartados** — o que foi visto pelo motor mas não usado (ex.: um valor com
   `confere = Não` na sincronização com o SEI nunca entra na série de valores, mas também nunca é apagado —
   ver "Limites conhecidos" abaixo).
3. **Premissas aplicadas a este item** — quando o índice de reajuste do item específico usa
   uma aproximação.
4. **Parcelas** — competência × camada × valor × fórmula em texto (ex. "Contratado
   (principal): R$ 1.000,00"), com total por camada ao final. Os totais desta tabela
   conciliam exatamente com as parcelas do item na tela de Fluxo de caixa — a memória lê os
   mesmos dados já calculados, nunca recalcula nada por conta própria.

Quando há uma simulação ativa (rascunho ou cenário salvo selecionado), a seção "Parcelas" se
duplica: Oficial × Simulado lado a lado, com `br-tag` "alterado" em cada linha que diverge.

Um item sem dado suficiente para gerar projeção mostra aviso na própria página, nunca 404.

## Simulação

No painel "Simular" (accordion) da tela de Fluxo de caixa, o usuário altera, **por padrão sem
afetar o oficial**, seis variáveis:

1. **Índice de reajuste por ano** — sobrescreve o percentual de um ano específico.
2. **Excluir um item** da lista de contratações (e reincluir depois).
3. **Alternar a renovação prevista** de um item, só dentro da simulação.
4. **Alterar o valor** de um item (contratado ou estimado).
5. **Alterar o início planejado** de um item (só itens ainda sem contrato).
6. **Lead time padrão** (dias), usado quando não há histórico suficiente do estrato.

Cada ação grava um rascunho em `request.session["fluxo_ajustes"]` — nunca no banco, nunca
visível para outro usuário. A faixa "Simulação ativa" aparece sempre que o rascunho tem algo
alterado, com a lista das variáveis mexidas; "Voltar ao oficial" limpa o rascunho
imediatamente. Com o rascunho ativo, KPIs, tabela anual, tabela UO × ano, gráfico anual e
memória de cálculo passam a mostrar **Oficial × Simulado × Diferença** lado a lado (o "%
contratado" continua só oficial — dividir por um denominador que muda com a simulação tornaria
a leitura ambígua).

## Cenários salvos

Um rascunho de simulação pode ser salvo com nome, para reabrir depois ou levar para a reunião
seguinte — o seletor "Cenário salvo" (distinto do seletor "Cenário" de base/contratado/sem
reajuste/sem renovação, ver acima) lista **Oficial**, o **rascunho da sessão** (quando há um) e
os cenários já salvos do exercício:

- **Salvar como novo** — grava o rascunho atual como um `CenarioFluxo` nomeado.
- **Carregar no rascunho** — copia um cenário salvo de volta para o rascunho da sessão (o
  cenário em si só muda quando o usuário aciona "Salvar" de novo — selecionar um cenário no
  seletor e aplicar filtro só EXIBE a comparação, sem alterar o rascunho).
- **Salvar (sobrescrever com o rascunho atual)** — grava as mudanças do rascunho de volta no
  mesmo cenário.
- **Excluir** — só por página de confirmação própria, nunca por um clique direto.

Sobrescrever e excluir exigem ser o **autor** do cenário ou **superusuário** — qualquer outro
usuário recebe 403 explícito, nunca um 404 nem um apagamento silencioso.

## Relatório XLSX

Ao lado do CSV de sempre, o botão "Baixar XLSX" gera um relatório de **5 abas** do cenário
projetado (oficial, ou oficial × simulado quando há comparação ativa), preservando o
filtro/recorte/cenário/simulação da tela no momento do download:

1. **Resumo** — identificação do relatório (exercício, cenário, índice, simulação, data de
   geração) e os totais principais.
2. **Anual** — uma linha por (ano, camada) do mesmo horizonte único da tela.
3. **Contratações** — a mesma lista "Contratações neste recorte" da tela.
4. **Parcelas** — uma linha por parcela projetada, casada com o simulado quando há
   comparação ativa (item excluído da simulação fica em branco na coluna Simulado, nunca
   como zero — célula vazia é a única forma honesta de dizer "esta parcela não existe no
   cenário simulado").
5. **Memória** — uma linha por linha de memória de cálculo de cada item do mesmo recorte.

Todo texto derivado de entrada do usuário (nome/descrição de cenário) é neutralizado contra
injeção de fórmula antes de entrar numa célula.

## Contratos a vencer

Seção nova da Fase 38, primeira depois do título de **Prazos**. Substitui a antiga listagem por
horizonte de vencimento (90, 180 e 365 dias) — corrige o defeito M07 (`melhorias.md`): contratos
vigentes concluídos deixavam de aparecer.

### Quem entra

Todo item do PCA com `estado = ativo`, `vigencia_fim` informada e `regime_execucao` diferente
de "execução única" (regime em branco entra). A população **não filtra** por `situacao`, `tipo`
nem pela decisão de renovação — um item já marcado `concluído` que tenha contrato vigente
**aparece** (era exatamente o defeito M07). Uma linha por item do PCA, não por instrumento
financeiro. Contratos vencidos ficam no topo, do mais antigo para o mais recente, com a tag
**Vencido** — a tag é só um alerta de prazo, não uma declaração de situação jurídica do
processo. Contrato com início de vigência ainda no futuro recebe o apoio "Vigência ainda não
iniciada".

### O destino em N+1

Cada item recebe um destino no exercício seguinte (N+1), calculado por
`apps/pca/projecao/virada.py::destino()` a partir da vigência e da renovação prevista:

| Condição | Destino (rótulo) | O que significa |
|---|---|---|
| Vigência já encerrada (antes de hoje) | **Vencido** | Vigência encerrada antes de hoje — pendência: registrar a prorrogação ou encerrar. Não é declaração de situação jurídica atual. |
| Vence em N, renovação prevista = Não | **Encerra em N** | Renovação não prevista — sem possibilidade legal ou sem interesse. Não entra no PCA N+1. |
| Vence em N, renovação prevista = Sim | **Renovação em N** | Aditivo/renovação ainda a registrar; o destino em N+1 depende da nova vigência. |
| Vence em N+1, renovação prevista = Sim | **Renovação em N+1** | Entra no PCA N+1 como Renovação, no prazo, mês previsto = mês do vencimento. |
| Vence em N+1, renovação prevista = Não | **Encerra em N+1** | Entra no PCA N+1 como Vigente (concluído) e consome orçamento até vencer; renovação não prevista. |
| Vence depois de N+1 | **Vigente em N+1** | Entra no PCA N+1 como Vigente (concluído); vence depois de N+1. |

Um contrato renovado em N por mais 12 meses, que volte a vencer em N+1, nasce em N+1 como
**Renovação**, no prazo — nunca como "Vigente": o que decide é a vigência corrente, não o fato
de já ter sido renovado antes (renovação encadeada). "Renovação prevista = Não" significa "não
há mais possibilidade legal de prorrogação, ou não há interesse" — não é um campo novo, é o
mesmo booleano `renovacao_prevista` de sempre, marcado pela equipe nesta própria tela.

A geração de fato dos itens do PCA N+1 — tipo, situação, mês previsto (= mês do vencimento) e
valor projetado pelo motor do fluxo de caixa — é da **Fase 40**; esta tela só mostra o destino e
permite decidir a renovação.

### Os cinco indicadores

- **Itens com contrato** — o total da população do recorte (soma sempre igual às quatro
  categorias a seguir).
- **Vencidos ou encerram em N** — Vencido + Encerra em N.
- **Renovação em N** — aditivo ainda a registrar neste exercício.
- **Renovações em N+1** — o que já se sabe que renova no exercício seguinte.
- **Vigentes em N+1** — Encerra em N+1 + Vigente em N+1 (contratos que seguem vigentes,
  independentemente de renovarem depois).

A base dos cinco cards é o exercício, as unidades selecionadas e os filtros **Vence**/
**Renovação prevista** — o filtro de **Destino** só recorta a tabela abaixo, não os cards.
Clicar em um dos quatro cards de categoria aplica o grupo de destino correspondente e reinicia a
paginação; clicar no total "Itens com contrato" limpa os filtros de destino.

### Filtros

- **Vence**: Todos (padrão) / Vencidos / Até 90 dias / Até 180 dias / Até 365 dias / Até 31/12
  de N / Até 31/12 de N+1. Os horizontes em dias são inclusivos e não incluem os já vencidos; os
  cortes anuais (N, N+1) incluem os vencidos; um item cuja vigência termina hoje **não** está
  vencido.
- **Renovação prevista**: Todas / Sim / Não.
- **Destino**: Todos ou uma das seis chaves da tabela acima.
- Valor inválido em qualquer filtro na URL é ignorado, com um aviso — nunca quebra a página.
  "Limpar filtros" mantém o exercício e as unidades selecionadas, só remove Vence/Renovação/
  Destino/página.

### Marcar/Desmarcar renovação

Cada linha tem um botão de ação, visível só para quem tem permissão de editar. O botão alterna a
renovação prevista nos dois sentidos ("Marcar renovação" ↔ "Desmarcar renovação"), grava a
mudança no histórico do próprio item (sem criar um acompanhamento novo) e a tela volta com
exatamente os mesmos filtros que estavam ativos. A mensagem de confirmação já diz o novo destino
em N+1 do item. Se, depois da mudança, o item deixar de atender ao filtro de Renovação ou de
Destino que estava aplicado, ele sai da lista e a mensagem oferece um link "Remover esses
filtros" para trazê-lo de volta.

## Gerar itens de N+1

Ação da Fase 40 (`apps/pca/servicos/geracao_n1.py`) — gera de fato os itens do PCA N+1 a partir
dos contratos vigentes de N, na regra de destino descrita acima. Ação PRÓPRIA, distinta do
wizard de virada de exercício: funciona com N+1 já cadastrado (o caso real — 2027 existe, vazio)
e é reexecutável sem duplicar.

**Quem pode.** Só superusuário **e** com a permissão `pca.gerir_exercicio` — mais restrito que a
virada, que só exige a permissão. O botão "Gerar itens de N+1" aparece na tela Prazos (ao lado do
título "Contratos a vencer") e em Gerenciar exercícios (linha do exercício aberto mais recente);
ninguém mais vê ou consegue acionar a rota (403).

**O que entra.** Exatamente a população desta seção — item ativo, com vigência informada e
regime diferente de execução única — classificada pelo destino acima. Só **Renovação em N+1**,
**Encerra em N+1** e **Vigente em N+1** geram item; os demais destinos não geram nada nesta ação
(mudam a renovação prevista ou a vigência aqui em Prazos antes de gerar, se precisarem entrar).

**O que nasce.** Renovação em N+1 → tipo Renovação, situação "No prazo", mês previsto = mês do
vencimento. Encerra/Vigente em N+1 → tipo Vigente, situação "Concluído", mês previsto = mês do
vencimento (Encerra) ou o mês previsto da origem, ou janeiro na ausência (Vigente). O catálogo
precisa ter os tipos "Renovação" e "Vigente" cadastrados — faltando um dos dois, a prévia mostra
o erro e a geração não escreve nada.

**Valor.** `valor_estimado` do item novo é a soma das parcelas do motor de fluxo de caixa (Fase
37) para o item de origem com competência em N+1, camadas Contratado + Renovação prevista +
Reajuste projetado (nunca Planejado) — uma única projeção por prévia/geração, não uma por item.
Sem parcela em N+1 (item sem projeção ou soma zero), o valor cai no `valor_estimado` da própria
origem, e a linha da prévia mostra "valor estimado de N (sem projeção)".

**Idempotência e origem.** A chave é `origem` (o FK já existente) × exercício N+1: um item de N
que já tem derivado em N+1 aparece na prévia como "já gerado — item X" e não é criado de novo.
Não há campo/flag nova nem migração — a proveniência fica só em `origem` e no histórico
(`simple_history`, motivo "Geração N+1 a partir de contratos (Fase 40)"). O `item_pca` do novo
item continua do maior já existente em N+1, na ordem de vencimento da população — nunca renumera
o que já está lá. N (a origem) nunca é alterado por esta ação.

**Campos copiados.** Objeto, justificativa, UO, categoria, modalidade e todo o bloco de execução
contratual (instrumento, valor contratado, fornecedor, vigência, datas de lançamento) — os três
destinos sempre têm contrato. O item nasce com estado ativo, datas de PCA/Gelic em branco,
situação SEI em branco e sem nenhum número de SEI (o processo do aditivo/nova contratação é
outro, a coletar depois). Se o exercício N+1 ainda não existir, a geração cria-o aberto; se já
existir (aberto ou fechado), usa-o como está — a situação do exercício nunca muda por esta ação.

**Fluxo.** Prévia (GET, só leitura) → confirmar (POST) → `messages.success` com a faixa de itens
gerados → tabela de Processos já filtrada por N+1. Sem nada a gerar (segunda execução, ou
recorte já coberto), a confirmação avisa "Nada a gerar" e volta para a própria prévia — sem
criar nada.

## Acesso

As telas **Fluxo de caixa**, **Estatísticas** e **Prazos**, mais a ação de alternar
"renovar?"/"não renovar?", exigem a permissão `pca.ver_analises` (403 explícito para quem não
tem, nunca um redirecionamento silencioso) — concedida pelo Django Admin ao atribuir o usuário
ao grupo **"dirigentes"** (ou qualquer outro grupo/permissão individual que carregue
`pca.ver_analises`). O **Painel** continua aberto a todo autenticado. O menu lateral só lista
os destinos que o usuário tem permissão de abrir.

**Prazos** exige `pca.ver_analises` E `pca.view_acompanhamento`; a ação Marcar/Desmarcar
renovação exige as duas MAIS `pca.editar_pca`. Quem tem as duas de leitura e não tem
`editar_pca` vê a tabela sem a coluna Ação. O menu e a futura ferramenta do assistente usam a
mesma dupla.

## Como conferir contra a planilha do orçamento

Procedimento de aceite (spec `2026-09-19-fluxo-de-caixa-simulacao-design.md` §10,
`melhorias.md` §6), para repetir em toda reunião mensal:

1. Abra `Análises → Fluxo de caixa`, cenário "Base" (padrão), sem simulação ativa.
2. Compare o KPI **"A pagar até 31/12/{ano}"** e a **"Projeção {ano+1}"** com os totais que a
   planilha do orçamento projeta, item a item — não basta comparar o total agregado.
3. Confira que o **mesmo recorte** aparece com o mesmo total no KPI, no gráfico, na tabela e
   no XLSX baixado.
4. Se a diferença passar de 5%, abra "Itens sem dado" e "Premissas", e a memória de cálculo do
   item divergente — toda divergência relevante deve ter explicação ali. Sem explicação
   suficiente, ou premissa que pareça errada, é sinal de dado incorreto no Processo ou de um
   caso que o cálculo ainda não cobre — registre o ajuste para tratar depois, sem travar a
   reunião.
5. Revise uma amostra contratual (contrato simples, aditivo, evento mensal, evento anual,
   apostilamento, item com dois contratos, evento retroativo) pela memória de cálculo.
6. Rastreie um número do KPI até a lista de contratações, até a memória de cálculo, até o
   instrumento (protocolo SEI) que sustenta o valor.
7. Verifique a operação por perfil: quem não tem `ver_analises` recebe 403 nas 3 URLs e não vê
   os destinos no menu; quem tem, acessa normalmente.

## Limites conhecidos

Para não esperar o que esta fase não constrói:

- **Pagamento/empenho realizado** — a projeção usa valor contratado e série de eventos da
  sincronização com o SEI, não o que já foi de fato pago ou empenhado (não há fonte disso hoje).
- **Deságio estimado → contratado** — não há um preditivo de quanto o valor final tende a
  cair em relação ao estimado.
- **Cronograma manual por parcela** — a distribuição mensal é sempre calculada (por peso de
  dias ou literal, conforme a periodicidade), nunca editável parcela a parcela.
- **Alerta por e-mail** de vincendos ou de score de risco alto — hoje só existe na tela, sem
  notificação automática.
- **Apostilamento com valor bruto ausente nunca vira `EventoFinanceiro`** — quando a sincronização
  com o SEI não consegue extrair um valor com `confere = Sim` de um apostilamento, o documento é
  descartado da série de valores, mas continua registrado como "evento descartado" na memória
  de cálculo do item, nunca como se nada tivesse sido encontrado.
- **Contratos distintos do mesmo item compartilham a vigência do Processo** — quando um item
  tem mais de um contrato independente (ex. contrato principal + apostilamento com
  instrumento próprio), os dois cadeias somam valores separadamente, mas usam a mesma
  vigência inicial/final cadastrada no `Processo` — o modelo de dados desta fase não grava
  vigência por instrumento.
