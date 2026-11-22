# Migração de dados: Postgres → SQLite

Receita para a **produção** (`/home/ToNiauM/pausados/docker/pca`) executar quando o usuário decidir migrar de
PostgreSQL para SQLite (fora desta fase — a Fase 31 só prova a receita em dev, contra os
dados reais de 11/09/2026). Não confundir com `ops/MIGRACAO.md` (migração para uma VM nova,
já em SQLite); este documento é só sobre a troca de backend de um ambiente que já está de pé
em Postgres.

## Passo a passo

1. **Gerar o dump com o Postgres de produção AINDA vivo** (antes de qualquer troca de
   `compose.yml`/`.env`):
   ```sh
   ops/migracao_sqlite/gerar_dump_postgres.sh
   ```
   Roda `manage.py dumpdata --natural-foreign --natural-primary --exclude contenttypes
   --exclude auth.permission --exclude sessions --exclude admin.logentry --exclude axes
   --indent 0 -o <arquivo>.json` dentro do container `web`, copia o resultado para fora da
   árvore versionada (`/home/ToNiauM/ativos/docker/pca-cfc-dumps/`, mesmo diretório dos `.dump` de segurança),
   grava checksum `.sha256` e aplica `chmod 600` (o arquivo contém e-mails reais de
   `core.Usuario`).

2. **Trocar a infra de produção para a versão SQLite** — deploy do código desta fase
   (`compose.yml` sem serviço `db`, volume `pca_data`, `.env` com `DATABASE_URL=sqlite:///
   /app/data/db.sqlite3`). `docker compose up -d` sobe `web` saudável com um `db.sqlite3`
   vazio (schema aplicado do zero por `migrate --noinput`, já disparado pelo entrypoint).

3. **Copiar o `.json` gerado no Passo 1 para o host do novo ambiente** (o mesmo arquivo,
   nenhuma regeneração — `scp`/`rsync` a partir de `/home/ToNiauM/ativos/docker/pca-cfc-dumps/`).

4. **Carregar os dados** com o script reexecutável desta pasta:
   ```sh
   ops/migracao_sqlite/restaurar_sqlite.sh /caminho/para/pca-dumpdata-<carimbo>.json
   ```
   Copia o `.json` para dentro do container `web` (via `exec ... cat > arquivo` — ver
   ressalva abaixo), roda `manage.py loaddata`, e REMOVE a cópia de dentro do container ao
   final — o arquivo com e-mails nunca fica residente na imagem/volume além da execução.
Não reinicia `web` (a aplicação lê o banco a cada request).

   **Ressalva encontrada na prática:** `docker compose cp` para dentro do
   container falhou de forma intermitente com `mounted volume is marked read-only` contra
   `/app/ops/relatorios` — esse caminho é um volume anônimo próprio, mas fica ANINHADO dentro
   do bind `:ro` de `/app` que o `compose.override.yml` de dev usa; a resolução de mount do
   `cp` do Docker Engine não lida de forma confiável com esse aninhamento (reproduzido: um
   `docker compose cp` funcionou antes de um `stop`/`up -d` do mesmo serviço e falhou depois,
   sem nenhuma mudança de configuração — `docker inspect` seguia mostrando o mount como
   gravável). `restaurar_sqlite.sh` usa `docker compose exec -T web sh -c "cat > arquivo" <
   arquivo-no-host` em vez de `cp` — grava pelo próprio processo do container, sem passar
   pela API de cópia de arquivo do Engine, e não reproduziu o problema em nenhuma das
   execuções seguintes (incluindo a prova de reexecutabilidade do Passo "Reexecutabilidade"
   abaixo). Se a produção usar `docker compose cp` manualmente em vez do script, watch para o
   mesmo sintoma; a correção é a mesma (stream via `exec`/stdin).

5. **Conferir as contagens por modelo antes/depois** — mesmo padrão de
   `ops/backup/ensaio_restore_local.sh`:
   ```sh
   docker compose exec -T web python manage.py shell -c "
   from django.contrib.auth import get_user_model
   from apps.catalogo.models import (
       Categoria, Classificacao, Exercicio, GrauPrioridade,
       InstrumentoContratual, Modalidade, SituacaoNormalizada, Tipo, Unidade,
   )
   from apps.pca.models import (
       Acompanhamento, EventoImportacao, HistoricalAcompanhamento,
       HistoricalProcesso, Processo, ProcessoAlocador, ProcessoSEI, Reuniao,
   )
   from django.contrib.auth.models import Group
   from core.models import HistoricalUsuario

   modelos = [
       Group, Categoria, Classificacao, Exercicio, GrauPrioridade,
       InstrumentoContratual, Modalidade, SituacaoNormalizada, Tipo, Unidade,
       HistoricalUsuario, get_user_model(), Acompanhamento, EventoImportacao,
       HistoricalAcompanhamento, HistoricalProcesso, Processo,
       ProcessoAlocador, ProcessoSEI, Reuniao,
   ]
   for m in modelos:
       print(f'{m._meta.app_label}.{m._meta.model_name}', m.objects.count())
   "
   ```
   As 19 linhas devem bater exatamente com as contagens do Postgres de origem (lidas do
   mesmo volume antes do Passo 2, com o container Postgres parado de novo em seguida — nunca
   os dois bancos rodando ao mesmo tempo por mais tempo que o necessário para a leitura).

6. **Smoke test de login real**: acessar `/` e `/tabela` com um usuário real recém-carregado
   (login por e-mail/senha, não `force_login`); fazer uma edição real (ex.: "Registrar
   acompanhamento" em qualquer item) e confirmar que o item ganhou uma nova linha na timeline
   — prova de que `simple_history` grava com o autor correto contra o SQLite recém-carregado.

## Ressalva de natural keys — o que a Fase 31 encontrou na prática

`simple_history` (`HistoricalProcesso`/`HistoricalAcompanhamento`) usa `history_id` como PK
própria — não a mesma natural key do modelo vivo (`Processo`/`Acompanhamento`). Na prática,
`--natural-primary --natural-foreign` no `dumpdata` **não gerou nenhum conflito de PK/natural
key nos dois modelos históricos**: o `loaddata` os carrega pela PK numérica normal
(`history_id`), sem passar por `natural_key()`/`get_by_natural_key()` (esses modelos não
implementam esses métodos). O ensaio de ponta a ponta (dump de 3076 registros/19
modelos) carregou os 895 `HistoricalAcompanhamento` e os 648 `HistoricalProcesso` sem erro,
com contagens batendo exatamente contra o Postgres de origem.

`axes` já sai do dump por `--exclude axes` (dado operacional de rate-limit, não histórico de
negócio) — nenhum ajuste adicional foi necessário para ele.

**Se a produção encontrar um conflito que este ensaio não encontrou** (ex.: dados legados com
natural keys duplicadas que o dataset de dev não tinha), a correção recomendada é
excluir `--natural-primary` especificamente para os apps que dão conflito, mantendo
`--natural-foreign` para preservar as referências entre tabelas — regenerar o dump com
`gerar_dump_postgres.sh` ajustado e repetir o `loaddata`.

## Reexecutabilidade

O script `restaurar_sqlite.sh` foi provado reexecutável do zero: banco SQLite resetado
(volume recriado vazio, `migrate --noinput`) e o mesmo dump recarregado, produzindo as mesmas
19 contagens.
