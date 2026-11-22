# Backup do SQLite pelo host (cron) — como funciona e como restaurar

Desde 15/09/2026 o banco do PCA é um arquivo SQLite (`/app/data/db.sqlite3` no container `web`,
volume Docker `pca-cfc_data`). O backup roda **no host**, por cron, com `ops/backup/backup.sh`.
A versão para rodar dentro de um container (`backup_container.sh`, serviço `backup` do compose)
continua no repositório, mas fica fora do `up` padrão neste ambiente para não duplicar o upload.

## O que roda

`crontab -e` do operador (`ToNiauM`):

```
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
30 2 * * * /home/ToNiauM/ativos/docker/pca-cfc/ops/backup/backup.sh >> /home/ToNiauM/ativos/docker/pca-cfc-dumps/sqlite/backup.log 2>&1
```

Todo dia às 02:30 o script:

1. tira uma cópia **consistente** do banco pela API `.backup` do sqlite3, dentro do container
   (segura mesmo com WAL ativo e com alguém gravando);
2. confere `PRAGMA integrity_check` e conta processos — cópia vazia ou corrompida aborta antes do upload;
3. `gzip -9`, `gzip -t`, `sha256`;
4. envia para `pca/sqlite/daily/` no Cloudflare R2 (aos domingos também para `pca/sqlite/weekly/`);
5. aplica retenção **só** em `sqlite/`: 7 diários, 4 semanais (`retencao.sh`). Os dumps Postgres
   antigos em `daily/` e `weekly/` na raiz do bucket não são tocados — são o rollback fora da máquina;
6. mantém os 7 últimos `.gz` também em `/home/ToNiauM/ativos/docker/pca-cfc-dumps/sqlite/` (permissão 600).

Credenciais: só as quatro `R2_*` do `.env` do projeto (600). O rclone usa um remoto chamado
`pcar2` definido inteiramente por variáveis de ambiente — não lê nem altera o
`~/.config/rclone/rclone.conf` do operador (que tem um remoto `r2` para outro bucket).

## Conferir

```bash
tail -20 /home/ToNiauM/ativos/docker/pca-cfc-dumps/sqlite/backup.log        # última execução
ls -l /home/ToNiauM/ativos/docker/pca-cfc-dumps/sqlite/                      # cópias locais
```

Listar o que está no bucket sem depender do `rclone.conf` (mesmas variáveis do script):

```bash
cd /home/ToNiauM/ativos/docker/pca-cfc && set -a && eval "$(grep -E '^R2_' .env)" && set +a
export RCLONE_CONFIG_PCAR2_TYPE=s3 RCLONE_CONFIG_PCAR2_PROVIDER=Cloudflare RCLONE_CONFIG_PCAR2_NO_CHECK_BUCKET=true \
       RCLONE_CONFIG_PCAR2_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" RCLONE_CONFIG_PCAR2_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY" \
       RCLONE_CONFIG_PCAR2_ENDPOINT="$R2_ENDPOINT"
rclone lsf pcar2:$R2_BUCKET/sqlite/daily/ --format tsp
```

Rodar na mão (mesmo comando do cron): `/home/ToNiauM/ativos/docker/pca-cfc/ops/backup/backup.sh`.

## Restaurar

1. Escolher o arquivo (local em `/home/ToNiauM/ativos/docker/pca-cfc-dumps/sqlite/` ou baixado do bucket com
   `rclone copy pcar2:pca/sqlite/daily/<nome>.gz /tmp/`).
2. Descompactar e conferir: `gunzip -k /tmp/<nome>.gz && python3 -c "import sqlite3;print(sqlite3.connect('/tmp/<nome>').execute('pragma integrity_check').fetchone())"`.
3. Parar a aplicação, trocar o arquivo, subir:
   ```bash
   cd /home/ToNiauM/ativos/docker/pca-cfc
   docker compose stop web
   docker compose run --rm --no-deps -T web sh -c 'rm -f /app/data/db.sqlite3-wal /app/data/db.sqlite3-shm; cat > /app/data/db.sqlite3' < /tmp/<nome>
   docker compose up -d web
   curl -s -H 'X-Forwarded-Proto: https' http://127.0.0.1:12011/healthz
   ```
   (`docker cp` não serve aqui: o bind `:ro` do dev faz ele falhar; o `cat` via stdin funciona.)
4. Conferir no navegador que a contagem de processos bate com a do dia do backup.

Antes de sobrescrever um banco que ainda tem valor, tire uma cópia dele: basta rodar o
`backup.sh` uma vez — ele deixa o `.gz` em `/home/ToNiauM/ativos/docker/pca-cfc-dumps/sqlite/`.

## Se o cron não rodar

- `grep CRON /var/log/syslog | tail` (ou `journalctl -u cron`) mostra se disparou;
- o script exige `docker compose` acessível ao usuário do cron (grupo `docker`) e o container
  `web` de pé — se o `web` estiver parado, ele falha em "cópia consistente" e o log diz isso;
- dois disparos simultâneos são impedidos por `flock` (`/tmp/pca-backup.lock`).
