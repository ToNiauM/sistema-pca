# Operação

## Backup/restore

O serviço `backup` (ver [`compose.yml`](../compose.yml)) roda diariamente:

```sh
sqlite3 "${SQLITE_PATH}" ".backup '/tmp/pca_<carimbo>.sqlite3'"
gzip /tmp/pca_<carimbo>.sqlite3
rclone copy <arquivo>.sqlite3.gz r2:${R2_BUCKET}/daily/
```

`.backup` produz uma cópia consistente do arquivo mesmo com o modo WAL ativo
e escritores concorrentes (ao contrário de uma cópia de arquivo crua, que
poderia capturar o `.sqlite3` no meio de uma transação). Aos domingos, o
mesmo arquivo também vai para `r2:${R2_BUCKET}/weekly/`. Retenção: 7 pontos
diários, 4 semanais (`ops/backup/retencao.sh`). Script completo:
[`ops/backup/backup.sh`](../ops/backup/backup.sh) (host, cron) — a versão do container é `backup_container.sh`.

### Restore

Resumo (ver [`README.md`](../README.md#restore-do-banco) para o passo a passo
completo com comandos): pare `web`, baixe o `.sqlite3.gz` desejado do R2,
descompacte e copie para dentro do volume `pca_data` com um container
descartável, suba `web` de novo. A prova reexecutável — volume externo
sobrevivendo a `down -v`, arquivo restaurado batendo contagem com a origem —
é [`ops/backup/ensaio_restore_local.sh`](../ops/backup/ensaio_restore_local.sh).

Se a origem ainda for um PostgreSQL vivo (não um backup `.sqlite3.gz`), use a
receita `dumpdata`/`loaddata` de
[`ops/migracao_sqlite/README.md`](../ops/migracao_sqlite/README.md) — cobre a
ressalva de natural keys e o script reexecutável
`ops/migracao_sqlite/restaurar_sqlite.sh`.

**Implantação da Fase 42 (extensões SEI Pro):** antes do `restart`/`up -d web` que aplica a
migração `0007_token_api.py`, faça um backup (`.backup`, como acima) do banco de produção —
checkpoint humano descrito em [`docs/deployment.md`](deployment.md), seção "Extensões SEI Pro
(Fase 42)".

## Exportar/importar o banco em XLSX

Acesso pelo Django Admin (`/admin/`), bloco **"Banco de dados"** no índice —
restrito a superuser (mesmo gate de site `PcaAdminSite.has_permission`,
mais uma checagem local em cada view).

**O que o export contém:** um único `.xlsx` com 19 abas — `_leia-me` (data do
export, versão do sistema, contagem de linhas por aba e as regras abaixo) mais
uma aba por modelo concreto de `catalogo`/`pca`/`core.Usuario` (18 tabelas).
Ficam de fora: modelos `Historical*` (a trilha `simple_history` continua
imutável nas telas do sistema — só o Admin, à parte, permite editá-la), tabelas
de infraestrutura (`sessions`, `axes`, `contenttypes`, `admin.LogEntry`),
`auth.Group`/`Permission`, o M2M de usuário (`groups`/`user_permissions`) e as
colunas `password`/`last_login` de `Usuario` — essas duas nunca aparecem no
arquivo, e mesmo que alguém acrescente as colunas manualmente antes de
reimportar, o valor gravado no banco não muda.

**Regra de upsert (por pk, primeira coluna de cada aba):** nunca apaga. Pk
vazio cria uma linha nova; pk preenchido mas inexistente no banco também cria
a linha, com esse pk explícito. Célula vazia é sempre valor NULO. Não renomeie
abas nem colunas — o import mapeia por nome exato do cabeçalho.

**Fluxo em 3 passos:**

1. **Exportar banco (XLSX)** baixa o arquivo.
2. Edite no Excel/LibreOffice e envie pelo formulário **Importar banco
   (XLSX)** — a tela mostra um relatório de diferenças campo a campo (até 50
   linhas detalhadas por aba, "+N mais" acima disso), sem gravar nada ainda.
3. O botão **Confirmar e gravar** só aparece quando o relatório não tem
   nenhum erro. Ao confirmar, o sistema relê e recalcula o relatório (defesa
   contra o banco ter mudado nesse intervalo), faz um backup automático do
   SQLite em `/app/data/backups/pre-import-AAAAMMDD_HHMMSS.sqlite3` **antes**
   de qualquer escrita, aplica tudo dentro de uma única transação (erro em
   qualquer linha desfaz o lote inteiro) e registra a autoria — `simple_
   history` grava `history_user`/motivo em cada linha alterada, e o índice do
   Admin mostra a ação em "Recent actions" via `LogEntry`.

## Troubleshooting

### "database is locked"

**Causa:** duas escritas concorrentes disputando o mesmo arquivo além do
tempo de espera configurado, ou um processo externo com o arquivo aberto em
modo exclusivo (por exemplo, um `sqlite3 db.sqlite3` interativo esquecido
aberto, ou uma cópia de arquivo feita sem `.backup` enquanto `web` escreve).

**Como diagnosticar:**
```sh
docker compose logs web | grep -i "database is locked"
```
Se o erro aparece só sob rajada de escritas simultâneas (reunião mensal com
vários editores ao mesmo tempo), é o cenário que as opções abaixo já mitigam
— confirme que elas continuam ativas antes de investigar mais. Se aparece
persistentemente com um único usuário, procure um processo externo com o
arquivo aberto (`lsof` dentro do container, ou verificar se algum `sqlite3`
interativo ficou aberto no volume).

**O que `config/settings/base.py` já faz para minimizar isso** (`OPTIONS` do
backend SQLite, só quando `ENGINE == "django.db.backends.sqlite3"`):

```python
DATABASES["default"]["OPTIONS"] = {
    "transaction_mode": "IMMEDIATE",   # evita deadlock leitor→escritor
    "timeout": 20,                     # segundos de espera pelo lock
    "init_command": (
        "PRAGMA journal_mode=WAL;"     # leitores não bloqueiam o escritor
        "PRAGMA synchronous=NORMAL;"
        "PRAGMA foreign_keys=ON;"
        "PRAGMA busy_timeout=20000;"   # espera 20s antes de levantar erro
    ),
}
```

O modo WAL (`journal_mode=WAL`) permite N leitores simultâneos a um escritor
sem bloqueio mútuo; `transaction_mode=IMMEDIATE` evita que duas transações de
escrita comecem como leitura e disputem a promoção para escrita ao mesmo
tempo (a causa mais comum de `SQLITE_BUSY` em Django); `busy_timeout=20000`
faz o SQLite esperar até 20s por um lock antes de desistir, em vez de falhar
na hora. Gunicorn continua em 3 workers × 4 threads — não reduza sem medir;
o gargalo real do SQLite é UM escritor por vez, não o número de conexões.

## Perfis e permissões
.
Dois grupos Django (`Group`), atribuídos pelo Admin →
Usuários → editar usuário → seção "Grupos":

- **`editor`** — `pca.editar_pca` (edita processo, move kanban, registra
  acompanhamento) + `pca.view_acompanhamento` (vê acompanhamentos e
  prazos). Nenhuma mudança percebida nesta quick.
- **`visualizador`** — nenhuma das duas (inclusive o grupo Gelic). Perde a
  leitura de tudo que é acompanhamento/prazo:
  - ficha do item: quadro "PRAZO ATUAL" e a seção "Acompanhamentos e
    prazos" (timeline) somem;
  - tabela de processos: colunas Prazo inicial, Prazo atual, Nº reuniões,
    Nº compromissos, Dias em atraso, Prazos remarcados e Situação última
    reunião somem do seletor "Colunas" e da tabela, mesmo que já
    estivessem salvas na preferência de sessão do usuário;
  - `/calendario`, `/reunioes` e o Relatório de movimentação passam a
    devolver 403;
  - os itens "Calendário", "Reuniões" e "Relatório de movimentação" somem
    do menu lateral.

  Situação do processo, funil, KPIs por situação e o número SEI (com link,
  ver abaixo) continuam visíveis a todo usuário autenticado — "situação do
  processo" não é acompanhamento.

Comando idempotente, sem migração — aplica `view_acompanhamento` ao grupo
`editor` (roda uma vez após restaurar/zerar o banco de dev, ou numa
produção nova):

```sh
docker compose exec -T web python manage.py configurar_grupos
```

### Registrar acompanhamento (modal)
,
19/09/2026. O modal "Registrar acompanhamento" (único
`br-modal` do sistema) é o procedimento da reunião mensal do PCA:
ao salvar ou cancelar, o sistema volta à tabela de Processos com os
filtros preservados e a linha do item em foco (`#item-<pk>`) — nunca para
a ficha do item, para que a equipe percorra a tabela item a item sem um
clique extra de "Voltar" a cada registro. Registrar um prazo novo reavalia
a situação: sem sobreposição manual nem fato que a fixe, um
item Atrasado/No prazo volta a No prazo; prazo já passado continua
Atrasado, com aviso.

A partir da tabela, salvar ou cancelar troca só a listagem (htmx
`HX-Location` → `#listagem`), sem recarregar a página nem mover o scroll;
o modal fecha porque o contêiner vive dentro da listagem. A partir da
ficha, volta à tabela por redirect (19/09/2026).

### Excluir acompanhamento (22/09/2026)

Só **superusuário com `pca.gerir_exercicio`** vê a coluna "Ações" e o link
"Excluir" em cada linha da tabela "Acompanhamentos e prazos" da ficha do
item — mais estrito que `pode_editar` (`pca.editar_pca`), de propósito: a
exclusão é procedimento excepcional, não parte do fluxo mensal da equipe.

O link abre uma página de confirmação (nunca modal, mesmo padrão de
"Excluir cenário" do fluxo de caixa): mostra data/tipo/texto/prazo da
linha e o efeito real da exclusão nos campos derivados do item (situação
atual, prazo vigente, prorrogações, atraso...), calculado apagando a
linha dentro de uma transação e desfazendo em seguida
(`transaction.atomic()` + `set_rollback(True)`) — a página nunca deixa
escrita persistida, só simula. Quando nenhum campo depende daquela linha,
a página diz isso explicitamente em vez de mostrar uma lista vazia.

"Sim, excluir" é um POST real que apaga a linha, registra a exclusão na
trilha `simple_history` (com autor) e volta para a própria ficha,
ancorada em `#acompanhamentos`. **A exclusão é definitiva e não pode ser
desfeita pela tela** — o caminho normal para corrigir um erro de
digitação continua sendo registrar uma linha nova com o valor certo (o
modal "Registrar acompanhamento" acima), não apagar a errada; a exclusão
existe para casos como duplicidade da sincronização com o SEI ou linha de teste, não para
correção de rotina.

### Proposta de texto e as duas portas de entrada (22/09/2026)

O modal "Registrar acompanhamento" pode ser aberto por duas portas — e a porta
decide o que acontece. Abrir pela **tabela** (reunião item a item) continua
colando a linha na reunião ABERTA, como sempre: a frase institucional
sai como "na reunião de DD/MM". Abrir pela **ficha** do item (o editor do PCA
corrigindo um dado fora de reunião) nunca amarra a uma reunião aberta — a
frase sai como "em DD/MM". Nenhum campo novo na tela decide isso; é a origem
do clique.

Ao abrir o modal, o campo Observação vem pré-preenchido com uma proposta de
texto (`apps.pca.mudancas.propor_texto`) montada a partir das mudanças que o
editor fez no item desde o último acompanhamento registrado — um fato por
campo, formatado com a mesma moeda/data da tela ("Valor estimado alterado de
R$ 120.000,00 para R$ 148.500,00."). Edições feitas pela sincronização com o SEI
nunca entram na proposta (ela já registra as próprias frases automaticamente). O texto é
só sugestão: editável à vontade, nunca gravado sozinho — no envio do
formulário, é sempre o que está escrito na hora que vale. Observação e
Justificativa também ganharam um `help_text` fixo com o padrão de escrita
esperado (um fato por frase com a fonte; a justificativa só o porquê, em
minúscula e sem ponto final).

## Sincronização com o SEI

Fase 32 (18/09/2026). A sincronização com o SEI (serviço `robo` do compose)
lê o SEI do CFC (Chromium autenticado via Playwright) e mantém em dia os
campos de tramitação contratual que hoje só existiam na planilha —
instrumento de contratação, datas de assinatura por papel, valor contratado
e recebimento no Gelic. Desenho
completo: documento interno de desenho.

**Regra de fonte da verdade:** o SEI manda nos campos de tramitação acima —
a sincronização sempre sobrescreve o que estiver desatualizado neles. O PCA
manda em item, área, objeto, justificativa, valores planejados, prazos e
tipo — a sincronização nunca toca esses campos. A situação do item nunca é
escrita direto pela sincronização: passa sempre por
`aplicar_regras_automaticas` (as mesmas regras da tela), respeitando a
transição manual — exceto quando o instrumento de contratação está assinado
pelo CFC **e** pelo contratado, caso em que a sincronização grava
`situação = concluído` mesmo por cima de uma transição manual ("uma vez
assinado, está concluído", decisão do usuário, 18/09/2026). Desde
25/09/2026 essa exceção não conclui uma renovação do ano sem contrato ou
termo aditivo assinado no próprio ano (regra de renovação × vigência).

**Item sem processo SEI (25/09/2026):** item sem nenhum nº SEI cadastrado é
pulado por inteiro — nem campos, nem regra de situação, nem acompanhamento
de pendência: não há de onde tirar informação, e a sincronização não
inventa. Cadastrado o número, o item volta a ser sincronizado na passada
seguinte. O Início mostra quantos itens estão "sem processo SEI" (card
"Sincronização com o SEI"), com link para a tabela filtrada
(`?sem_processo_sei=1`). O antigo campo "Situação do SEI" (Autuado/A
autuar/Não se aplica) foi removido — ter ou não processo SEI vem do próprio
número.

### Execução contratual completa (Fase 33)

Fase 33 (18/09/2026), extensão da Fase 32 sobre o mesmo instrumento de contratação. Além
dos campos acima, a sincronização passa a ler e gravar: razão social e CNPJ do contratado,
modalidade, nº da contratação e vigência início/fim. Desenho completo:
documento interno de desenho.

**Precedência:** o contrato preenche tudo; o termo aditivo só atualiza valor e
vigência (razão social/CNPJ apenas quando o contrato não os trouxe); o apostilamento
atualiza só o valor. Termo aditivo e apostilamento nunca alteram modalidade nem nº da
contratação já vindos do contrato.

**Vários contratos distintos no mesmo item:** quando mais de um contrato,
assinado por ambos os lados, com CNPJs diferentes, aparece no mesmo item, `valor_contratado`
soma o valor de cada contrato (cada um com sua própria cadeia de aditivos/apostilamentos);
razão social e CNPJ **não** são gravados automaticamente — pendência
`multiplos_contratados:<protocolos>` no lugar, com a evidência listando cada contrato e seu
valor. Data de assinatura, situação, modalidade e nº da contratação continuam vindo do
instrumento mais recente, normalmente.

**Pendências novas**, mesmo padrão das já existentes (chave estável na timeline, some
quando a causa deixar de existir na consulta seguinte):

| Pendência | Quando aparece |
|---|---|
| `contratado_invalido:<protocolo>` | CNPJ do contratado não passa no dígito verificador — razão social e CNPJ não são gravados |
| `modalidade_nao_mapeada:<protocolo>` | A modalidade lida no preâmbulo não mapeia para nenhum dos 7 rótulos do catálogo (`Modalidade.nome_normalizado`) |
| `vigencia_nao_lida:<protocolo>` | Nenhuma das formas de cláusula de prazo foi reconhecida no instrumento |
| `multiplos_contratados:<protocolos>` | Vários contratos distintos (CNPJs diferentes) assinados por ambos no mesmo item — ver acima |

**Teste de aceitação sobre banco zerado (18/09/2026):** o checkpoint humano deste fechamento
(itens 2, 6, 10 e 11 pelo Admin) rodou contra um banco de dev **zerado**, para reproduzir
uma primeira execução real sem histórico anterior — nunca contra o banco de produção.
Receita de limpeza usada (restaura `db.sqlite3.backup` por cima do banco de dev e limpa o
estado da sincronização com o SEI):

```sh
docker compose stop robo web
docker compose run --rm --no-deps --entrypoint sh web -c 'rm -f /app/data/db.sqlite3-wal /app/data/db.sqlite3-shm && cp /app/data/db.sqlite3.backup /app/data/db.sqlite3 && rm -f /app/data/sei/estado.json /app/data/sei/ultima_consulta.json /app/data/sei/cache.json'
docker compose start web robo
```

O banco de dev fica zerado depois deste teste — restaurar de novo a partir do `.backup`
(ou de um dump mais recente, ver "Restore" acima) é decisão do usuário, quando convier.

### Sem repetir a mesma frase (22/09/2026)

Diagnóstico: `regras.py` acrescenta a frase de assinatura do instrumento vencedor
("... assinado pelo CFC em ... e pelo contratado em ...") sempre que existe um
instrumento vencedor — ela descreve o ESTADO atual, não uma mudança. Como
`aplicador.py` gravava a evidência inteira a cada varredura em que QUALQUER
outro campo mudava (ex. `unidade_sei_atual`, que não gera evidência própria), a
mesma frase de assinatura voltava a aparecer na timeline mês após mês, mesmo
sem nada de novo a comentar. Medição no banco real em 22/09/2026: 443
acompanhamentos automáticos, 21 linhas redundantes (texto idêntico ao de outra
linha do mesmo processo, itens 1, 3, 5, 6, 7, 8 entre outros).

**Correção:** cada frase de evidência é filtrada contra as observações
automáticas já registradas no mesmo processo antes de gravar
(`aplicador._frases_novas`); sobrando zero frases novas, nenhum
`Acompanhamento` novo nasce — mas o campo alterado continua sendo gravado no
`Processo` normalmente (`itens_alterados` continua contando a mudança real). O
mesmo dedupe por texto cobre as pendências "Pendência SEI: ...", como uma
segunda camada resiliente à perda ou zeragem de `data/sei/estado.json` (o
dedupe por chave nesse arquivo continua sendo o caminho normal, mais barato).

**O histórico já gravado antes desta correção não foi apagado** (decisão do
usuário, 22/09/2026) — as 21 linhas redundantes de hoje permanecem na timeline;
a correção vale só das próximas varreduras em diante.

### Varredura incremental (Fase 34)

Fase 34 (18/09/2026), extensão das Fases 32/33 sobre a mesma varredura diária. A varredura
deixa de reler tudo a cada execução: só lê o que pode ter mudado desde a última vez. Em dia
sem novidade, o tempo/rede caem de ~26 min/1,1 GB para poucos minutos, com resultado
idêntico. Desenho completo:
documento interno de desenho.

**Cache (`data/sei/cache.json`, dentro do volume `pca_data`).** Guarda, por número SEI, o
total de registros anunciado pelo histórico completo e a primeira linha da primeira página
(`processos[<numero_sei>]`) — se os dois baterem na próxima varredura, o processo inteiro é
pulado, sem abrir pastas nem documentos. Guarda também, por `id_documento`
(`documentos[<id_documento>]`), o resultado de cada leitura **definitiva**: HTML com
assinatura completa para o tipo (contrato/aditivo exigem `assinado_cfc` **e**
`assinado_externo`; apostilamento só `assinado_cfc`) e, quando há valor,
`valor.confere == True`. Documento unilateral, externo não baixado, cancelado ou com valor
que não confere **nunca** entra no cache — é relido na próxima varredura, até ficar
definitivo. Reset: apagar `data/sei/cache.json` (a sincronização reconstrói do zero na próxima
execução, como se fosse a primeira varredura). A ação "Atualizar com o SEI" no Admin
(`sei_atender`) e `sei_coletar --forcar` sempre ignoram o cache e releem tudo do item —
"forçar releitura" quando alguém desconfiar de um resultado — mas o cache continua sendo
atualizado mesmo assim, para os demais processos se beneficiarem do atalho na próxima
varredura normal.

**Progresso no log.** Durante `sei_sincronizar`, cada processo imprime uma linha —
"item N (k/total): coletado em X s", "item N (k/total): pulado (sem mudança no histórico)"
ou "item N (k/total): erro — …" — mais o resumo final "coleta concluída: k coletados,
p pulados, e erros em T s". **Essas linhas só aparecem na saída do próprio comando**
(`docker compose exec -T robo python manage.py sei_sincronizar`, do jeito que o cron chama
o comando) — **não aparecem** em `docker compose logs -f robo`, porque o `exec` roda um
processo separado do laço `sei_atender` que o `logs -f` acompanha. Desde,
cada linha de progresso também é gravada em `data/sei/execucoes/<carimbo>.log` (mesma
pasta/retenção dos 60 mais recentes dos `.json`), útil para conferir uma varredura já
terminada sem ter guardado o stdout do `exec`. Enquanto a varredura está em andamento, o
mesmo progresso aparece ao vivo no card "Sincronização com o SEI" do Início (estado
`em_execucao`: item/k/total, percentual, contadores, tempo decorrido), atualizado por HTMX
a cada 15 s — só visível para quem tem `pca.editar_pca`/superusuário, mesma restrição de
sempre.

**Duas varreduras de prova (18/09/2026, checkpoint deste fechamento), tempo de referência:**

| Varredura | Cache | Duração | Processos | Rede | Resultado |
|---|---|---|---|---|---|
| 1ª (`2026-09-18-2118.json`) | vazio | 1816,7 s (30,3 min) | 108 coletados, 0 pulados, 2 erros (itens 17 e 79) | 1,26 GB, 36.924 requisições | 9 itens alterados, 2 pendências novas |
| 2ª (`2026-09-18-2148.json`) | cheio | 410,0 s (6,8 min) | 2 coletados (17 e 79, fora do cache pelo erro anterior), 108 pulados | 360 MB, 11.543 requisições | 0 itens alterados, 1 pendência nova (item 79, avaliado pela 1ª vez porque a 1ª varredura falhou nele) |

A rede da 2ª varredura ficou em ~360 MB, acima dos ~50 MB estimados na spec (§1/§6) — abrir
a árvore de cada processo custa mais do que o previsto, mesmo pulando documentos; possível
otimização futura, fora do escopo desta fase.

### Termo de apostilamento e série de valores (Fase 35)

Fase 35 (19/09/2026), extensão das Fases 32/33/34 sobre o mesmo instrumento de contratação. A
sincronização passa a **ler** o termo de apostilamento em vez de só extrair um valor solto: natureza
(reajuste, repactuação, dotação ou outro), par de valores anterior/novo, índice e percentual do
reajuste, periodicidade (mensal, anual ou global) e data-base, quando o termo traz uma
retroatividade explícita. Desenho completo:
documento interno de desenho.

**Regra de valor:** um apostilamento só entra na disputa de `valor_contratado` quando
`natureza` é reajuste ou repactuação, o valor novo confere (cifra × extenso) **e** a periodicidade
é global — explícita (`periodicidade == "global"`) ou, na ausência dela, confirmada pela âncora
"valor global"/"valor total" no trecho casado do termo. Reajuste mensal ou anual sem essa
confirmação nunca altera `valor_contratado` — vira pendência `apostilamento_sem_global`, registrada
para a futura fase de fluxo de caixa decidir se o valor mensal/anual pode ser anualizado a partir
da vigência do contrato. Apostilamento de alteração de dotação orçamentária (ou de natureza não
reconhecida) nunca entra na disputa e nunca gera pendência — só a evidência "Apostilamento
&lt;protocolo&gt;: alteração de dotação, sem efeito no valor." na timeline.

**Evidência encadeada:** quando mais de um documento contribuiu para o valor final
(contrato/aditivo seguido de um ou mais apostilamentos qualificados), a evidência do evento lista
a cadeia inteira — "Valor contratado: R$ 1.773.079,80 (contrato 0802566 R$ 1.500.000,00 → apost.
1º R$ 1.666.816,20 → apost. 2º R$ 1.773.079,80)." — em vez de só "antes/depois". Com um único
documento contribuindo, o formato antigo (antes/depois) continua o mesmo.

**Pendência nova**, mesmo padrão das já existentes (chave estável na timeline, some quando a
causa deixar de existir na consulta seguinte):

| Pendência | Quando aparece |
|---|---|
| `apostilamento_sem_global:<protocolo>` | Apostilamento de reajuste/repactuação com valor conferido, mas periodicidade mensal ou anual sem confirmação de valor global — fica para a fase de fluxo de caixa (ver acima) |

**Série de valores.** `regras.propor()` devolve, além de `alteracoes`/`evidencias`/
`pendencias`, a lista `serie_valores` — um item por documento com valor (contrato, aditivo ou
apostilamento, qualificado para a disputa ou não), com protocolo, tipo, data, valor,
periodicidade e natureza, em ordem cronológica. `aplicador.aplicar()` devolve essa lista em
`resumo["series"]`; `sei_sincronizar` grava em `execucoes/<carimbo>.json` (campo `series`, por
item) e `sei_atender` inclui no resultado do pedido atendido. **Nunca é gravada no banco** —
nenhum campo novo em `Processo`, nenhuma migração — é o insumo bruto que a futura fase de fluxo
de caixa vai consumir (ler do JSON de execução mais recente ou recalcular do cache).

**Achado da sondagem que muda a leitura de "global" na prática (17 termos reais
lidos):** a palavra "global" não aparece em NENHUM dos 17 apostilamentos lidos. O item 108 usa a
âncora "valor total anual da contratação" — `periodicidade="anual"`, nunca `"global"` — e a
hipótese original de "dotação pura" para os itens 43/50/57 foi refutada: os três são, na prática,
reajuste cifra a cifra, igual ao molde dominante (96/61/63 e outros 8). Sob a regra estrita de,
isso significa que 108, 96 e 43 tendem a cair em `apostilamento_sem_global` (não
reajustam `valor_contratado` automaticamente) até que o usuário decida, no aceite deste
fechamento, se "anual" deve contar como global quando a vigência do contrato é de 12 meses (ou
sempre) — decisão de negócio, não ampliada por conta própria nesta implementação (ver,
seção de desvios).

### Valor contratado: total × periódico, assinatura e "valor do contrato" (20/10/2026)

Correção do caso do item 64 (o robô gravava R$ 2.213,93, o valor **mensal** do contrato, em vez do
valor global). Quatro regras, todas em `apps/pca/sei/extracao.py`/`regras.py`:

1. **Leitura do valor do documento:** com mais de uma frase de preço no texto ("O valor mensal ... é
   de R$ X (...), perfazendo o valor total de R$ Y (...)"), vale a primeira **conferida e não
   periódica** (total/global/montante); o mensal/anual só quando é a única leitura conferida.
2. **Contrato/aditivo com valor só mensal ou anual nunca vira `valor_contratado`.** O documento
   continua contando para saber qual é o mais recente: se o mais recente com valor só traz
   mensal/anual, o robô **não grava nada** (fica o valor atual, nunca cai para o valor de um documento
   anterior, já superado) e registra a pendência `valor_sem_global`. Mensal/anual de documento já
   superado por outro mais recente com valor global não gera pendência.
3. **Apostilamento no molde "Valor do contrato: R$ X ... Novo valor do contrato: R$ Y"** conta como
   global quando o trecho não traz marca de período ("mensal", "mensais", "anual", "ao mês", "ao
   ano"...). E a forma "o novo valor global do contrato passa a ser de R$ Y" é lida — vale a última
   ocorrência, nunca os valores por período citados no mesmo termo.
4. **Assinatura exigida** (spec §4.1/§4.3): só disputa o valor, gera pendência de valor e entra na
   série o documento assinado — apostilamento pelo CFC; contrato, aditivo, OF e ata pelo CFC **e**
   pelo contratado. Minuta sem assinatura é ignorada; aditivo assinado só pelo CFC só vale quando o
   contratado assinar (até lá, `unilateral:<protocolo>`).
5. **Contrato com valores por item, sem valor global único** (decisão do usuário, 20/10/2026 — item
   18, Contrato nº 39/2026: "Para o ITEM 01 ... R$ 110.499,60; Para o ITEM 02 ... R$ 62.000,00; Para o
   ITEM 03 ... R$ 18.800,00"): quando as frases de preço são de dois ou mais itens/lotes/grupos
   distintos e nenhuma frase sem rótulo traz o valor global conferido, o robô **não grava nada** (o
   valor atual fica) e registra `valor_por_itens`, com o valor lido de cada item no texto da pendência
   — o valor contratado é preenchido à mão. Esse documento também fica fora da série de valores (o
   valor de um item não é o global do fluxo de caixa). Se o contrato traz, além dos itens, uma frase
   com o valor global, vale o global, como sempre.

Aditivo de prorrogação que só traz o valor **anual** continua em `valor_sem_global` (decisão do
usuário, 20/10/2026): o robô não anualiza nem soma — a pessoa confere e preenche.

| Pendência | Quando aparece |
|---|---|
| `valor_sem_global:<protocolo>` | O documento mais recente com valor (contrato/aditivo) só traz valor mensal ou anual — `valor_contratado` não é atualizado; conferir e preencher manualmente |
| `valor_por_itens:<protocolo>` | O documento mais recente com valor traz um valor por item (ITEM/LOTE/GRUPO) e nenhum valor global único — `valor_contratado` não é atualizado; somar os itens que valem e preencher manualmente |

**As regras 2, 3 (molde "valor do contrato") e 4 valem na próxima sincronização.** As leituras 1, 3
(forma "novo valor global") e 5 mudam a extração (`VERSAO_EXTRACAO_DOCUMENTO` 3 → 4): os documentos já
gravados no `cache.json` só são relidos com
`docker compose exec -T robo python manage.py sei_coletar --reprocessar-documentos` (lê o SEI, não
grava nada no PCA; a sincronização seguinte aplica). Documento ainda não definitivo (minuta, termo
sem assinatura) é relido sozinho quando o histórico do processo muda. Até o reprocessamento, o
contrato do item 18 ainda aparece com a leitura antiga (o valor anual do ITEM 01) e cai em
`valor_sem_global` — também sem gravar nada.

#### Correção pontual dos eventos financeiros (`sei_corrigir_eventos`)

A sincronização só **cria** eventos financeiros (`get_or_create` por processo + protocolo) — nunca
corrige nem apaga os que as regras antigas gravaram errado (o mensal do contrato do item 64, contratos
e aditivos assinados só pelo CFC, minuta sem assinatura, contrato por itens...). O comando
`sei_corrigir_eventos` reaplica as regras atuais sobre a coleta mais recente
(`data/sei/coletas/`, ou `--coleta <arquivo>`) e compara a série de valores com os eventos gravados:

- evento **do robô** cujo documento está na coleta mas não entra mais na série → **APAGAR** (o motivo
  sai na linha: "assinado só pelo CFC — falta a assinatura do contratado", "documento sem nenhuma
  assinatura (minuta)", "valores por item, sem valor global único — preencher à mão"...);
- evento do robô com `valor`/`valor_mensal`/`periodicidade` diferentes da leitura atual → **ALTERAR**
  (ex.: "o valor gravado era o mensal do instrumento; vale o total/global");
- nunca tocados: eventos **manuais**, eventos cujo documento não está na coleta, e os demais campos
  (data, tipo, natureza, instrumento). Eventos que faltam aparecem como "a próxima sincronização
  cria" — o comando não cria nada.

Documentos da coleta lidos por uma extração anterior são relidos do texto já gravado na coleta
(`texto_corpo`), sem abrir o SEI — o relatório já mostra a correção completa antes do
`--reprocessar-documentos`.

```sh
# 1) Simulação (padrão): só imprime o relatório — não grava evento, histórico, usuário nem lock
docker compose exec -T robo python manage.py sei_corrigir_eventos

# 2) Depois de conferir o relatório, gravar
docker compose exec -T robo python manage.py sei_corrigir_eventos --aplicar
```

Com `--aplicar`, o comando toma o lock do robô (`data/sei/em_execucao`; recusa se houver varredura em
andamento), grava tudo numa transação, evento a evento, e cada correção fica no histórico do evento
(Admin → Auditoria e histórico → histórico dos eventos financeiros) com autor "Robô SEI" e motivo
`sei_corrigir_eventos: <motivo>`. `valor_contratado` dos processos não é tocado. Pode rodar de novo
a qualquer momento: sem nada a corrigir, só imprime o resumo. Ordem recomendada: depois do
`sei_coletar --reprocessar-documentos` e da sincronização seguinte (assim os eventos que a
sincronização cria já saem com a leitura nova), simular, conferir, aplicar.

### Unidade atual no SEI

A sincronização agora também deriva "onde o processo está agora" a partir do histórico de andamento já
coletado (`apps.pca.sei.coletor.SEI._marcos`) — sem nenhuma consulta nova ao SEI. Dois campos
novos em `Processo`, ambos somente-leitura na ficha e no Admin: `unidade_sei_atual` (uma sigla) e
`unidade_sei_atual_desde` (data/hora da remessa mais recente).

**Regra vigente (22/09/2026):** `unidade_sei_atual`/`unidade_sei_atual_desde`
vêm da unidade de DESTINO da linha mais recente "Processo remetido pela unidade X" do histórico
(`marcos["ultima_remessa"]`, coluna da linha = destino, texto da descrição = só origem
informativa); sem nenhuma remessa (processo nunca saiu da unidade que o gerou), cai na unidade de
`marcos["primeiro"]`; sem nenhum andamento, o campo fica vazio (mostrado como "—" na ficha, não
"Não informado").

Nota histórica: isto substitui a regra /oy2 (unidade do "Processo recebido na
unidade" mais recente), que se provou errada — "recebido" só aparece quando alguém ABRE o processo
na unidade (nem toda unidade que recebe abre) e o marco antigo guardava só o PRIMEIRO recebimento
por unidade, perdendo processos que voltam a uma unidade já visitada. Uma coleta gravada antes da
(cache sem a chave `ultima_remessa`) é automaticamente re-coletada por completo
na primeira varredura incremental após o deploy — nenhuma ação manual necessária.

A tabela Processos (`/tabela`) ganha o filtro "Unidade no SEI" (dentro de "Mais filtros", opções
= siglas distintas de `unidade_sei_atual` no exercício corrente, igualdade simples) e a coluna
opcional "Unidade SEI" (seletor "Colunas", seção Processo, também exportada no XLSX).

### Os dois disparos

**1. Cron do host (varredura incremental, segunda a sexta, 04:00).** Instalado no
crontab do usuário do host em 19/09/2026, depois das duas varreduras de prova da Fase 34
(ver "Próximos passos"
abaixo). Linha exata para `crontab -e` (horário/dias conforme o crontab real do host —
`0 4 * * 1-5`, ajustado pelo usuário depois da decisão original "03:30, domingo a quinta"):

```sh
0 4 * * 1-5 cd /home/ToNiauM/ativos/docker/pca-cfc && docker compose exec -T robo python manage.py sei_sincronizar >> /home/ToNiauM/ativos/docker/pca-cfc-dumps/sei-cron.log 2>&1 && docker compose exec -T robo python manage.py ia_indexar >> /home/ToNiauM/ativos/docker/pca-cfc-dumps/sei-cron.log 2>&1
```

Fase 39 acrescenta `&& ia_indexar` ao fim da mesma linha — o `&&` shell garante que a
indexação do assistente só roda depois de uma sincronização SEI que saiu com código 0
(êxito); uma varredura que falhar não dispara a reindexação. **Nota datada (quick,
21/09/2026):** o `&& ia_indexar` só foi de fato instalado no crontab do host
nesta data — entre 19 e 21/09 o índice do assistente ficou parado na geração publicada em
19/09 22:40, e `buscar_texto` respondia com acompanhamentos/documentos SEI daquela foto
(sintoma relatado: "faço uma alteração e ele não reconhece"). Conferir sempre com
`crontab -l | grep ia_indexar`; sem essa linha, só a ação "Reindexar assistente" do Admin
atualiza o índice.

**Nota datada (22/09/2026, decisão do usuário):** além dessa linha diária, o crontab do host passou
a ter uma **indexação de hora em hora durante o expediente** — 7h às 17h, segunda a sexta, no
minuto 20 (para não largar junto com a varredura das 04:00, que já encadeia o próprio
`ia_indexar` e cobre a madrugada):

```sh
20 7-17 * * 1-5 docker compose exec -T robo python manage.py ia_indexar >> /home/ToNiauM/ativos/docker/pca-cfc-dumps/ia-indexar.log 2>&1
```

São 11 execuções por dia útil (~55 por semana) em vez de 24 por dia — fora do expediente ninguém
registra acompanhamento, e a varredura das 04:00 já indexa o que a sincronização trouxer do SEI.

Motivo: um acompanhamento registrado na reunião das 10h só era pesquisável por assunto
(`buscar_texto`) na manhã seguinte. Custo medido neste host em 22/09/2026 com 2.512 trechos
indexados: execução sem mudança leva **1,2 s** (4,1 s de ponta a ponta contando a subida do
processo), pico de **30 MB** de RSS e **zero token pago** — o índice compara hashes e só reembedda
o texto que mudou. Dados do PCA (valores, prazos, situação) nunca dependeram disso: as ferramentas
de ficha/listagem/fluxo leem o ORM ao vivo a cada pergunta. `ia_indexar` (sem
`--completo`) é incremental — só reembedda o que mudou desde a última geração, nunca
mexe em quota/conversas (ver "Assistente do PCA (Fase 39)" abaixo).

`exec -T` (não `run --rm`): o serviço `robo` já está de pé o tempo todo
(ver "O serviço `robo`" abaixo), então o cron só entra no container que já
existe.

**2. Ação "Atualizar com o SEI" no Admin (sob demanda, um item por vez).**
Em `/admin/pca/processo/`, só para superusuário: marque um ou mais
processos e execute a ação. Ela **só grava um pedido** em
`data/sei/pedidos/<exercicio>-<item_pca>.json` — não consulta o SEI nem
grava nada no PCA. Quem atende a fila, um pedido por vez, é o laço
`sei_atender` do serviço `robo`, permanente. Cancelados e itens sem número
SEI são ignorados com aviso na mensagem do Admin.

### O serviço `robo`

Serviço permanente do `compose.yml` (`restart: unless-stopped`,
`mem_limit`/`memswap_limit: 3g` — um vazamento mata o container `robo`,
nunca o host), rodando `python manage.py sei_atender` em laço. Sobe junto
com `web` num `docker compose up -d` normal, sem `profiles`. Em dev,
`compose.override.yml` monta a árvore `:ro` e usa uma tag própria, mesmo
padrão de `web`:

```yaml
robo:
  image: ${ROBO_IMAGE:-toniaum/pca-cfc-robo:dev}
  volumes:
    - .:/app:ro
    - /app/staticfiles
```

O volume anônimo em `/app/staticfiles` é obrigatório: sem ele, o bind mount
`:ro` esconde o `staticfiles/` já compilado (com manifesto) que está dentro
da imagem, e `core/views.py` precarrega caminhos estáticos no import do
módulo — derrubando `sei_atender` antes do primeiro laço
("Missing staticfiles manifest entry"). Diferente de `web`, `robo` nunca
serve HTTP, então não precisa recompilar a cada subida.

`docker compose build robo` só é necessário quando mudar `Dockerfile`,
`requirements-robo.txt` ou `entrypoint.sh` — instala Playwright e
`playwright install --with-deps chromium` no alvo `robo`; a imagem `web`
não muda.

**Fuso horário (18/09/2026):** `TZ=America/Sao_Paulo` nos serviços `web`/`robo` do
`compose.yml` — logs (`docker compose logs robo`) e os carimbos de nome/conteúdo dos
arquivos em `/app/data/sei/` (execuções, coletas, pedidos atendidos, cache) ficam na hora de
Brasília. O banco (`django.utils.timezone`, `USE_TZ = True`) continua gravando em UTC e
convertendo para exibição, sem mudança — a variável `TZ` do container não afeta o Django,
só o relógio do sistema operacional que os comandos da sincronização e os logs do Docker leem
diretamente.

### `data/sei/`

Todo o estado da sincronização com o SEI vive em arquivo, dentro do volume `pca_data`, sem
nenhuma migração:

- `coletas/<carimbo>.json` — o que o Chromium leu do SEI, antes de qualquer
  regra.
- `execucoes/<carimbo>.json` — resultado de cada `sei_sincronizar`
  (totais, itens alterados, pendências, erros, métricas). Desde a quick,
  a mesma pasta também guarda `execucoes/<carimbo>.log` (uma
  linha por evento de progresso, incluindo a linha final de resumo), sob a
  MESMA retenção de 60 mais recentes (pareada pelo carimbo, não contada em
  dobro).
- `pedidos/<exercicio>-<item_pca>.json` — fila da ação do Admin; um pedido
  por item (pedido novo sobrescreve o antigo do mesmo item).
- `pedidos/atendidos/<carimbo>-<item>.json` — pedidos já atendidos pelo
  `sei_atender`, com o resultado (`ok`/`erro`/`descartado_por_prazo`, campos
  alterados, pendências, mensagem).
- `estado.json` — pendências já avisadas uma vez na timeline (evita repetir
  o mesmo aviso a cada execução enquanto a pendência persistir).
- `ultima_consulta.json` — data/hora e resultado da última consulta de cada
  item, lida pela coluna "SEI: última consulta" do Admin e pelo rodapé "SEI: consultado
  em …" do Assistente. **Nota datada (21/09/2026):** até esta data só o
  atendimento sob demanda (`sei_atender`) gravava aqui, item a item; a varredura
  (`sei_sincronizar`) e o `sei_aplicar` passam a registrar em lote todos os itens visitados
  — "pulado (sem mudança no histórico)" conta como consulta `ok` (o histórico foi conferido),
  qualquer processo do item fora de `ok` marca `erro`. `--simular` nunca grava. A cobertura
  completa aparece após a primeira varredura seguinte à implantação.
- `em_execucao` — lock de 3h (varredura e atendimento sob demanda nunca
  rodam em paralelo).
- `cache.json` (Fase 34) — cache incremental: total de registros + primeira linha do
  histórico por processo, e o resultado de leitura de cada documento já **definitivo**
  (assinatura completa, valor conferido), indexado por `id_documento`. Ver "Varredura
  incremental (Fase 34)" acima. Regenerável do zero apagando o arquivo — nunca entra no
  backup diário, mesma nota de retenção dos demais arquivos desta lista. Desde a Fase 39,
  cada documento também guarda `texto_corpo` (HTML→texto, sem bloco de assinaturas/
  cabeçalho — é o que o Assistente do PCA indexa), `versao_extracao` e `hash_texto` —
  nunca HTML bruto. `sei_coletar --reprocessar-documentos` relê os documentos já em
  cache (nas duas representações, por processo e por `id_documento`) para preencher os
  três campos sem aplicar nada ao PCA; falha de releitura preserva a entrada anterior
  (nunca corpo vazio); segunda execução não relê o que já está atualizado.
- `links.json` — mapa `numero_sei` → `id_procedimento` e
  protocolo → `id_documento`, usado pelos filtros de template `link_sei`/
  `linkar_sei` (número SEI e protocolo citado em texto livre viram link
  clicável na tabela e na ficha do item). Mantido por `sei_resolver_links`
  e atualizado ao final de toda varredura (`sei_sincronizar`/`sei_atender`/
  `sei_coletar`) — **nunca apagado** pelo reset do `cache.json` nem pela
  restauração do banco; arquivo próprio, sobrevive aos dois.

Retenção: 60 arquivos mais recentes por tipo (`coletas/`, `execucoes/`,
`pedidos/atendidos/`). **Não entra no backup diário** (que só copia o
`.sqlite3`, ver "Backup/restore" acima) — é todo regenerável a partir do
SEI, a perda não é destrutiva.

### Onde ver o resultado

- **Timeline do item:** um evento Automático "SEI: ..." por alteração, com
  instrumento, datas de assinatura por papel, valor e o antes/depois de
  cada campo — mais o evento de `aplicar_regras_automaticas` quando houve
  mudança de situação.
- **Admin, coluna "SEI: última consulta"** em `/admin/pca/processo/`
  (data/hora e resultado, lidos de `ultima_consulta.json`).
- **Card "Sincronização com o SEI"**, no Início — só para quem tem
  `pca.editar_pca`/superusuário, logo abaixo dos indicadores (KPIs), antes dos gráficos
  (Fase 34). Quatro estados: nunca executado, ok, alerta (falha na última execução ou mais
  de 3 dias úteis sem executar), **em_execucao** (item corrente, k/total, percentual,
  contadores, tempo decorrido, atualizado por HTMX a cada 15 s enquanto a varredura roda); mostra também, em qualquer estado, "Último pedido pelo Admin:
  item N, DD/MM HH:MM, ok/erro" e "Pedidos atendidos hoje: N" (Fase 34,
  `execucoes.ultimo_pedido_atendido()`).
- **Logs do serviço:** `docker compose logs -f robo` — uma linha por etapa
  do atendimento (pedido recebido, login, coleta, aplicação ou erro), nunca
  com credenciais ou nomes de pessoas.
- **Arquivos de pedidos atendidos:** `data/sei/pedidos/atendidos/` (ver
  acima), para depuração pontual sem esperar a timeline.

### Comandos de depuração

```sh
# Coleta (não grava nada no banco), tudo ou um subconjunto de itens
docker compose exec -T robo python manage.py sei_coletar --itens 1,2,3

# Relê o corpo dos documentos já em cache (texto_corpo/versao_extracao/hash),
# sem aplicar nada ao PCA — usar após atualizar o extrator (Fase 39)
docker compose exec -T robo python manage.py sei_coletar --reprocessar-documentos

# Aplica um JSON de coleta já gravado, simulando (não grava nada)
docker compose exec -T robo python manage.py sei_aplicar --simular data/sei/coletas/<carimbo>.json

# Varredura completa simulada (coleta real + regras, sem gravar nada)
docker compose exec -T robo python manage.py sei_sincronizar --simular

# Correção pontual dos eventos financeiros gravados pelas regras antigas
# (20/10/2026): sem --aplicar só imprime o relatório; --aplicar grava
docker compose exec -T robo python manage.py sei_corrigir_eventos
docker compose exec -T robo python manage.py sei_corrigir_eventos --aplicar

# Assistente do PCA (Fase 39) — indexação incremental (padrão) ou completa
docker compose exec -T robo python manage.py ia_indexar
docker compose exec -T robo python manage.py ia_indexar --completo

# Assistente do PCA — limpeza sob demanda de conversas expiradas e
# metadados de quota (o serviço `robo` já faz isso a cada passagem do laço)
docker compose exec -T robo python manage.py ia_limpar

# Um único passo do laço de pedidos (uso manual, sem esperar os 5s do laço)
docker compose exec -T robo python manage.py sei_atender --uma-vez

# Resolve hiperlinks SEI pendentes — só os números
# ainda ausentes de links.json; --todos releitura tudo, mesmo já resolvido
docker compose exec -T robo python manage.py sei_resolver_links
docker compose exec -T robo python manage.py sei_resolver_links --todos
```

### Erros e o que fazer

| Situação | O que fazer |
|---|---|
| Login recusado no `docker compose logs robo` | Conferir as variáveis `SEI_*` no `.env`, depois `docker compose restart robo` |
| Três erros de login seguidos | O laço de `sei_atender` já espera 10 min antes de tentar de novo sozinho — não é preciso intervir |
| Pendência aparecendo na timeline ("assinado só pelo CFC", "valor não confere", etc.) | Normal — é a sincronização com o SEI avisando de algo que precisa de revisão humana no SEI ou no PCA; some da timeline quando a causa for resolvida e a pendência deixar de existir na próxima consulta |
| `sei_sincronizar`/ação do Admin devolvendo "execução em andamento" | Lock (`data/sei/em_execucao`) com menos de 3h — espere terminar; lock com mais de 3h é ignorado e sobrescrito automaticamente na próxima tentativa, não precisa apagar à mão |
| Trocou a senha do SEI | Editar a variável de senha correspondente no `.env` e `docker compose up -d robo` (recria o container lendo o `.env` novo; não precisa `build`) |

### Memória (medido em 18/09/2026, spec §8.1)

Servidor com 7,9 GB de RAM. `mem_limit`/`memswap_limit: 3g` no serviço
`robo` é a salvaguarda: um vazamento derruba o container, nunca o host.
Estimativas com as quatro medidas obrigatórias do desenho (reinício do
navegador a cada 25 processos, bloqueio de imagens/fontes, histórico só
por marcos, `mem_limit`):

- **Ocioso** (`sei_atender` esperando pedido): ~60 MB.
- **Atendendo um pedido do Admin** (um item): custo de um processo, ~1 GB
  por 20–30 s.
- **Varredura completa** (`sei_sincronizar`, ~111 números hoje): pico de
  1,2 a 1,8 GB, por ~25 minutos, uma vez por dia útil.

### Próximos passos (fora deste plano, decisão do usuário)

1. `docker compose up -d robo` já deixa `sei_atender` permanente (feito) — nada a fazer aqui além de manter o serviço de pé.
2. Uma primeira execução REAL de `sei_sincronizar` (sem `--simular`),
   conferida item a item na timeline.
3. Só depois desse teste, a linha de cron da seção "Os dois disparos" acima
   entra em `crontab -e` do host.

## Solicitações das unidades (Fase 43)

Texto voltado ao usuário: [`docs/solicitacoes.md`](solicitacoes.md) (também indexado pelo Assistente).
Aqui, só o que o administrador faz.

**Grupos** (criados pela migração `solicitacoes.0002`): `solicitante` (a unidade que pede; vê o PCA
inteiro em leitura e só pede nos itens das suas unidades), `diretoria` (decide inclusão, cancelamento,
valor e objeto) e o `editor` já existente (equipe do PCA: decide prazo e mês). Delegar a decisão da
diretoria = pôr a pessoa no grupo `diretoria` no Admin. **Vínculo usuário↔unidade**: Admin →
Usuários → editar usuário → seção "Unidades do usuário (para quem faz solicitações)" (várias por pessoa). Sem vínculo, o
solicitante não pede nada.

**Criar as contas de uma vez** — `importar_solicitantes`, a partir de uma planilha `.xlsx` ou `.csv`
com as colunas `nome`, `e-mail` e `unidades` (várias separadas por `;`):

```sh
# 0. A planilha entra no contêiner; o arquivo das senhas sai dele depois
docker compose cp solicitantes.xlsx web:/tmp/solicitantes.xlsx

# 1. Confere e conta, sem gravar nada (mostra a ação de cada linha)
docker compose exec -T web python manage.py importar_solicitantes /tmp/solicitantes.xlsx --dry-run

# 2. Cria. As senhas provisórias vão SÓ para o arquivo de --saida (CSV, permissão 600)
docker compose exec -T web python manage.py importar_solicitantes /tmp/solicitantes.xlsx \
  --saida /tmp/solicitantes-senhas.csv

# 3. Pega o arquivo das senhas e apaga as cópias de dentro do contêiner
docker compose cp web:/tmp/solicitantes-senhas.csv ./solicitantes-senhas.csv
docker compose exec -T web rm -f /tmp/solicitantes.xlsx /tmp/solicitantes-senhas.csv
```

- Tudo ou nada: unidade que não existe no cadastro, e-mail inválido ou repetido e nome ausente são
  listados e **nada é criado**. O nome da unidade casa sem acento e sem diferença de maiúsculas.
- Usuário novo: grupo `solicitante`, senha aleatória de 16 caracteres e troca obrigatória no 1º
  acesso (`senha_temporaria`). Usuário que já existe **não tem a senha tocada**; só ganha o grupo, o
  nome da planilha e os vínculos que faltam (vínculos nunca são removidos pelo comando).
- Idempotente: rodar de novo com a mesma planilha não muda nada nem gera senha.
- O arquivo de `--saida` precisa ficar **fora da árvore do projeto**, não pode já existir e é o único
  lugar onde as senhas aparecem (nunca no terminal nem em log). Entregue a cada pessoa e apague.

## Relatórios congelados da reunião

Detalhes de projeto em [`docs/relatorio-congelado.md`](relatorio-congelado.md). O que o administrador faz:
depois do deploy (a migração `pca.0035` roda sozinha no `entrypoint.sh`), congelar as reuniões que já
estavam fechadas, com os dados reconstituídos do histórico:

```sh
# 1. Lista o que seria congelado (período, corte e a observação de reunião anterior ao histórico); não grava
docker compose exec -T web python manage.py congelar_relatorios --dry-run

# 2. Congela. Idempotente: reunião que já tem versão fica de fora, então pode rodar de novo
docker compose exec -T web python manage.py congelar_relatorios
```

Cada reunião leva alguns segundos (cópia do banco e subprocesso, no máximo 45 s por reunião). Reuniões
fechadas daqui em diante são congeladas sozinhas no fechamento. Uma versão congelada **não se altera nem se
apaga**, nem pelo Admin; reunião com versão não pode ser apagada.

## Assistente do PCA (Fase 39)

### O que é e o que não faz

Chat autenticado, somente leitura, em `/assistente/` — pergunta em português, resposta
fundamentada exclusivamente em seis ferramentas executadas no servidor com as permissões
de quem pergunta (`consultar_processos`/`ficha`/`fluxo_de_caixa`/`contratos_a_vencer`/
`memoria_de_calculo`/`buscar_texto`). Nunca escreve no PCA, nunca dá opinião jurídica,
nunca inventa números fora das ferramentas. Ver
[`docs/assistente.md`](assistente.md) para o texto voltado ao usuário final (uso, limites,
quota, o que não faz) — é o mesmo texto indexado e citável pelo próprio assistente.

### Configuração

Variáveis em [`.env.example`](../.env.example) (bloco "Assistente do PCA"):

| Variável | Default | Uso |
|---|---|---|
| `IA_PROVEDOR` | `openai` | escolhe o adaptador de CHAT — `openai` ou `anthropic` |
| `IA_API_KEY` | vazio | **vazio desabilita o assistente inteiro** — menu oculto, rotas 404, `check`/sincronização com o SEI intactos; nunca informar a chave por mensagem, log ou pedido na fila |
| `IA_MODELO_ASSISTENTE` | `gpt-4o` | modelo de chat do assistente |
| `IA_MODELO_ROBO` / `IA_ROBO_ATIVO` | `gpt-4o-mini` / `False` | reservados para o leitor IA da sincronização com o SEI (fase futura) — não ativam nada nesta entrega |
| `IA_MODELO_EMBED` | `text-embedding-3-small` | modelo de embeddings do índice |
| `IA_PROVEDOR_EMBED` | `openai` | único valor aceito — Anthropic não tem API de embeddings |
| `IA_API_KEY_EMBED` | vazio | chave de embeddings; vazio reaproveita `IA_API_KEY` quando os dois provedores forem iguais |
| `IA_INDICE_PATH`/`IA_ESTADO_PATH`/`IA_CONVERSAS_PATH` | `<dir do banco PCA>/ia/{indice,estado,conversas}.sqlite3` | 3 SQLite auxiliares, fora do banco principal |
| `IA_MAX_PERGUNTAS_DIA` | `50` | quota diária por usuário |
| `IA_CONVERSA_TTL_S` | `28800` (8h) | limitado por `SESSION_COOKIE_AGE` — nunca sobrevive além da sessão |
| `IA_MAX_TOKENS_RESPOSTA` | `1500` | teto de tokens de saída por chamada |
| `IA_TIMEOUT_S` | `30` | timeout por chamada ao provedor |
| `IA_PRAZO_PERGUNTA_S` | `90` | orçamento total de tempo por pergunta (relógio monotônico) |

### Implantação

1. `.env`: `IA_API_KEY` (chave real) e `GUNICORN_TIMEOUT=150` — o prazo interno do
   assistente é de até 90s; o worker Gunicorn precisa de folga sobre esse prazo
   (`entrypoint.sh` já usa `${GUNICORN_TIMEOUT:-60}`, parametrizado sem rebuild).
2. `docker compose build web robo && docker compose up -d web robo` **uma vez**, na
   implantação das dependências novas (`openai`/`numpy`/`markdown-it-py` em
   `requirements.txt`, herdado por `requirements-robo.txt`) — respeitando
   `compose.override.yml`/a imagem de dev. Depois disso, mudança só de `.env` é
   `docker compose up -d web robo` (sem `build`).
3. Rede: os dois containers (`web` e `robo`) precisam de saída HTTPS (443) para
   `api.openai.com` — nenhuma porta de entrada nova, só saída.
4. Proxy do host: `proxy_read_timeout` do Nginx precisa ser ≥150s para `/assistente/`
   (mesma folga do item 1). **O executor não altera o proxy de produção** —
   [`ops/nginx/pca.conf`](../ops/nginx/pca.conf) é a amostra versionada; replicar
   manualmente no host.
5. Reprocessamento inicial do cache SEI (uma vez, só com autorização do usuário — é
   coleta real): `docker compose exec -T robo python manage.py sei_coletar --reprocessar-documentos`.
6. Primeira indexação (publica a geração 1 do índice):
   `docker compose exec -T robo python manage.py ia_indexar --completo`.

### Operação diária

- **Cron** (ver "Os dois disparos" acima): a linha existente de `sei_sincronizar` ganha
  `&& ia_indexar` ao final — a indexação só roda se a sincronização SEI saiu com sucesso.
- **Ação "Reindexar assistente"** no Django Admin (`/admin/pca/processo/`, só
  superusuário): grava um pedido em `data/ia/pedidos/`; nunca indexa dentro do request.
- **Fila `data/ia/pedidos/`**: estados `pendente`→`executando`→`concluido`/`erro`; o laço
  `sei_atender` consome no máximo um pedido de qualquer fila por passagem, com
  **prioridade SEI** (o pedido de reindexação só é atendido quando não há pedido SEI
  pendente) e lock de indexação separado do lock SEI (o `flock` de `indice.indexar` já é
  esse lock). Se a sincronização está ocupada numa coleta longa, o pedido de reindexação espera —
  isso é esperado, não um erro.
- **Limpeza automática**: a cada passagem do laço (mesmo sem `IA_API_KEY`), o serviço
  `robo` verifica se passaram 60s desde a última limpeza e, se sim, remove conversas expiradas e
  metadados de quota com mais de 7 dias — o dia atual da quota nunca é apagado.
- **Limpeza manual**: `docker compose exec -T robo python manage.py ia_limpar` faz o
  mesmo sob demanda, sem tocar o PCA.

### Arquivos auxiliares

`data/ia/{indice,estado,conversas}.sqlite3` (+ `-wal`/`-shm` de cada um), `pedidos/`
(fila de reindexação) e `ultima_limpeza` (marcador da limpeza periódica) — tudo dentro do
volume `pca_data`, listado em `.gitignore` (`data/ia/`). **Fora** do backup diário
(`ops/backup/backup.sh` copia só `db.sqlite3`), do export/import XLSX do Admin (nenhum
desses módulos lê/escreve `IA_*`) e do restore do banco PCA. Recuperação: reconstruir o
índice com `ia_indexar --completo`; `estado`/`conversas` não têm — nem precisam de —
backup (conversa é temporária por desenho; quota perde no máximo o dia corrente).

### Atualidade e limites

Rodapé em toda resposta ("PCA consultado em … · SEI: … · Textos indexados em …") é
adicionado pela aplicação, nunca pelo modelo — nunca promete "atualizado" quando a última
tentativa de coleta falhou. `store=False` no cliente OpenAI desliga o armazenamento de
estado da chamada no provedor; **não é garantia de retenção zero** em todas as camadas
operacionais do provedor (limite factual, não solução técnica deste sistema).
Pseudo-streaming por polling htmx desde 20/09/2026 — a
resposta chega em blocos a cada ~0,7s (etapa + texto parcial), não streaming letra a
letra de verdade; até 50 perguntas/usuário/dia; prazo interno de 90s por pergunta.

**Thread em segundo plano:** o POST devolve em menos de 1s (a chamada à
OpenAI sai do request para uma thread do servidor) — `GUNICORN_TIMEOUT=150` deixa de
ser crítico para o chat em si, mas continua recomendado (item 1 acima) para as demais
rotas. `--max-requests`/`--max-requests-jitter` do Gunicorn (reciclagem periódica do
worker) pode interromper uma resposta em curso — raro, mas possível: a rota de
polling detecta o lease de 120s vencido, marca a requisição como "interrompida" e
libera uma nova pergunta com mensagem clara; nenhuma pergunta fica travada para
sempre. Recarregar o Gunicorn com `docker compose exec -T web sh -c 'kill -HUP 1'`
(nunca `restart`) — uma resposta em andamento no momento do `HUP` sofre o mesmo
"interrompida" acima, não um erro silencioso.

### Custos

Tokens de entrada/saída por pergunta ficam registrados em `estado.sqlite3` (tabela
`quota`, colunas `tokens_entrada`/`tokens_saida`, por `usuario_id`/dia). Consulta de
exemplo (dentro do container, com `sqlite3 /app/data/ia/estado.sqlite3`):

```sql
SELECT usuario_id, dia, perguntas, tokens_entrada, tokens_saida FROM quota ORDER BY dia DESC;
```

Estimativa monetária **só com tabela de preços datada, nunca como garantia**: em
19/09/2026 o GPT-4o custava US$ 2,50/1M tokens de entrada e US$ 10/1M de saída
(cotação do provedor, sujeita a mudança). Não fixar um "custo por pergunta" — o número
varia com o histórico reenviado a cada rodada e com quantas ferramentas o modelo chama.

### Erros e o que fazer

| Situação | O que fazer |
|---|---|
| Menu "Assistente" some / rota 404 "não configurado" | `IA_API_KEY` vazia no `.env` — preencher e `docker compose up -d web robo` |
| 429 "limite de perguntas" | Quota diária (`IA_MAX_PERGUNTAS_DIA`) atingida — renova à meia-noite local; não é erro |
| 409 "pergunta em andamento" | Lease de 120s de uma requisição anterior ainda ativo — aguardar; nunca apagar `estado.sqlite3` para "destravar" |
| Página "Assistente temporariamente indisponível" (503) | Um dos 3 SQLite auxiliares está corrompido/inacessível — para o índice, `ia_indexar --completo` reconstrói; para `estado`/`conversas`, conferir permissões do arquivo (deve ser `0600`, diretório `0700`) ou mover o arquivo corrompido para reconstrução automática — **nunca apagar `estado.sqlite3` no meio do dia sem registrar**, isso zera a quota de todo mundo |
| Fila com pedido "erro sem_chave" | `IA_API_KEY` ausente no momento em que o serviço `robo` tentou consumir o pedido — preencher o `.env` e reenviar a ação "Reindexar assistente" |



- Arquitetura/topologia: [`docs/arquitetura.md`](arquitetura.md)
- Deploy/configuração: [`docs/deployment.md`](deployment.md)
- Runbook completo de migração para VM nova: [`ops/MIGRACAO.md`](../ops/MIGRACAO.md)
- Sincronização com o SEI: documento interno de desenho
- Sincronização com o SEI — varredura incremental (Fase 34): documento interno de desenho
