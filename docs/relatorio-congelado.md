# Relatório da reunião congelado

O relatório da reunião de acompanhamento é guardado **como um commit**: ao fechar a reunião, os **fatos**
do relatório são gravados de forma imutável e versionada, e a tela os apresenta com o código e o template
**atuais**. Texto voltado ao usuário: `manual/docs/diretoria/relatorio.md`. Operação (backfill):
[`operacao.md`](operacao.md#relatorios-congelados-da-reuniao).

## Fatos × apresentação

`apps/pca/relatorio_reuniao.py` tem duas metades:

- `apurar_relatorio(exercicio, reuniao, de, ate, usuario, hoje)` devolve só **fatos**, em JSON puro:
  linhas, somas, contagens, datas ISO, o "hoje" da apuração, ids e nomes (ano do exercício, id, data e
  ordinal da reunião, condutor), `gerado_por`/`gerado_em`, as linhas das solicitações, do resumo por
  unidade e dos anexos, e os textos de linha já compostos a partir do histórico ("Situação: A → B
  (data)"). Valores monetários e percentuais vão como `str` (nada de `Decimal` nem instância de modelo).
  Não leva gráficos, numeração de tabelas e figuras, nem parágrafos compostos.
- `apresentar_relatorio(fatos)` monta o contexto do template (`pca/_relatorio_reuniao_documento.html`):
  textos corridos, os quatro cartões de situação (`cartoes_situacao`), a geometria dos gráficos de colunas
  (`_grafico_colunas`: viewBox de 604 px = 16 cm a 1:1, coordenadas absolutas, rótulos inclinados a 45° quando
  não cabem na fatia da coluna; `_colunas_por_unidade` agrupa em "Outras N unidades" só acima de 20 unidades),
  a numeração de quadros, tabelas e gráficos (`quadros`, `tabelas`, `graficos`), "R$" com espaço fixo. Não toca
  no banco. O documento tem dois gráficos (valor previsto × contratado e itens ativos por unidade, em
  `pca/_relatorio_reuniao_colunas.html`) e a fonte única é a Calibri (pilha Calibri, Carlito, Liberation Sans,
  Arial); com isso as versões congeladas antigas passaram a sair no desenho novo sem tocar nos fatos.

Por isso melhorias de apresentação (gráficos, fontes) valem também para reuniões antigas, e números, itens e
textos de linha nunca mudam. `montar_relatorio_reuniao` = `apresentar_relatorio(apurar_relatorio(...))`
(prévia ao vivo e testes). Os fatos têm `versao_fatos`; mudança incompatível no formato exige que
`apresentar_relatorio` continue lendo as versões antigas.

**Relatório de período.** Com datas livres (`de` e `ate` no GET) a view apura com `reuniao=None`: título
"Relatório de acompanhamento do PCA {ano}", sem ordinal, condutor, quadro de indicadores da reunião nem seção
de registros (as seções seguintes sobem de número, `r.secoes`, e os cartões de situação passam a ser o Quadro 1,
`r.quadros`), e sem a frase de "não há reunião cadastrada".

## Modelo `RelatorioCongelado`

Uma linha por versão: `reuniao`, `versao` (única por reunião), `de`, `ate`, `corte`, `dados` (JSON dos
fatos), `hash`, `origem` (`fechamento` | `reconstrucao`), `observacao`, `criado_em`, `criado_por`.

- **Hash.** sha256 do JSON canônico (`json.dumps(..., sort_keys=True, ensure_ascii=False,
  separators=(",", ":"))`, ver `json_canonico` em `apps/pca/models.py`); `hash_curto` são os 7 primeiros
  caracteres. No `save()` os fatos passam por uma ida e volta JSON antes do hash, para o valor recalculado
  depois de ler do banco ser o mesmo. A tela recalcula a cada exibição (`integro`); se não bate, mostra o
  aviso de integridade e **não renderiza** o relatório.
- **Imutável.** `save()` de linha existente, `delete()`, `queryset.update()` e `queryset.delete()` levantam
  `RelatorioImutavel`; o Admin é só leitura (sem add/change/delete, nem para superusuário). `criado_por` é
  `PROTECT` (um `SET_NULL` alteraria a linha congelada), e `Reuniao.relatorios_congelados` também é
  `PROTECT`: reunião com versão não pode ser apagada. SQL cru continua podendo alterar a linha (o hash
  existe para acusar isso). Sem `HistoricalRecords`: a própria linha é o registro.

## Gancho de fechamento

`apps/pca/signals.py` (ligado em `PcaConfig.ready()`): `pre_save` de `Reuniao` guarda a situação anterior e
`post_save` agenda, em `transaction.on_commit(..., robust=True)`, `congelamento.congelar_no_fechamento`
quando a reunião passa de ABERTA para FECHADA (Admin, serviço ou shell). Criar a reunião já FECHADA (o
importador) não congela, nem FECHADA→FECHADA, nem `save(update_fields=[...])` sem `situacao`.
`queryset.update(situacao=...)` não dispara signal: a tela reconstitui depois (abaixo). Uma falha na apuração
é registrada em log e engolida: o fechamento já foi commitado.

**Período de fechamento.** `de` = dia seguinte à reunião anterior (ou 01/01 do exercício); `ate` =
`max(data da reunião, hoje)` — o mesmo período da prévia. O `corte` gravado é o instante do fechamento. Reabrir
e fechar de novo cria a versão n+1.

## Tela

`apps/pca/views_relatorio_movimentacao.py`, mesma URL e permissão (`pca.view_acompanhamento`),
`Cache-Control: private, no-store`:

- reunião **FECHADA**, sem datas no GET: renderiza os fatos da versão mais recente (ou `?versao=n`; inválida
  → aviso e a mais recente) sem recalcular; carimbo "Versão a1b2c3d · congelada em … por … (versão n de m)" e
  lista "Versões deste relatório". Sem versão alguma, `congelamento.reconstituir` cria a versão 1 (origem
  `reconstrucao`) na primeira abertura;
- reunião **ABERTA**, sem datas: ao vivo, com a prévia ("Prévia — a reunião está aberta; este relatório muda
  até ser fechada") e as versões anteriores se foi reaberta;
- **período livre** com `ate` no passado: `checkout.apurar_no_corte` sobre o banco como estava no fim do dia
  `ate` (America/Sao_Paulo), sem gravar versão, "Dados até DD/MM/AAAA"; com `ate` ≥ hoje, ao vivo. Falha do
  checkout vira mensagem de erro na tela (status 200, um só `h1`).

A casca (DSGov ou Tabler) é escolhida **na renderização**; os fatos guardados não dependem dela.

## Checkout: o banco em uma data

`apps/pca/checkout.py`. `copia_no_corte(corte)` é um context manager que entrega `(caminho, avisos)`:

1. copia o arquivo SQLite ativo para um temporário (`mkstemp`, 0600) pela API de backup do `sqlite3`; o
   temporário e seus `-wal`/`-shm` somem ao sair do contexto;
2. na cópia, para cada modelo com `HistoricalRecords` (todos, menos `core.Usuario`): apaga as linhas de
   histórico com `history_date` > corte; fica a **última linha por objeto**
   (`ROW_NUMBER() OVER (PARTITION BY pk ORDER BY history_date DESC, history_id DESC)`); se essa última linha
   é `-` (apagado), o objeto **não volta**; esvazia a tabela principal e a reinsere a partir dessas linhas
   (objeto sem linha ≤ corte some). Colunas que existem só na tabela principal (sem espelho no histórico)
   vêm da linha atual; se faltar a linha atual e a coluna for obrigatória, a linha é pulada e contada em
   `avisos`. Sem `foreign_keys` na cópia;
3. apaga as reuniões com `data` > dia local do corte.

`apurar_no_corte(...)` roda `manage.py relatorio_checkout` num **subprocesso** (lista de argumentos, sem
shell, `timeout=45` s, abaixo dos 60 s do gunicorn) com `DATABASE_URL=sqlite:///<cópia>` no ambiente, e lê os
fatos em JSON do stdout. A conexão do worker nunca é trocada. O comando é somente leitura, **recusa**
(`CommandError`) qualquer `--banco` diferente do banco ativo, e roda com o relógio parado no corte
(`django.utils.timezone.now` fixo), para `hoje`, `agora` e os `localdate()` das anotações verem a data do
corte. Reunião que não existe na cópia (data > corte) vira `reuniao=None`.

**Limites conhecidos.** Tabelas sem histórico (catálogo, ProcessoSEI, Usuário, Reuniao) ficam como estão hoje
(Reuniao só é filtrada por data); relações M2M não são reconstruídas.

## Backfill: `congelar_relatorios`

Toda reunião FECHADA sem versão ganha a versão 1 (origem `reconstrucao`, `criado_por` vazio), com corte no
fim do dia da reunião. Reunião **anterior ao primeiro registro de histórico** (a planilha importada em
30/07/2026) leva o corte no fim do dia desse primeiro registro e a observação "Reconstituído a partir da
planilha importada em DD/MM/AAAA: o sistema não tinha dados na data desta reunião.". `--dry-run` lista
período, corte e observação sem cópia nem subprocesso; é idempotente. Ver [`operacao.md`](operacao.md).
