# Operação

Organizado no modelo Request/Runtime/Data/Deployment/Observability/Recovery.

## Request

Toda requisição chega pelo proxy HTTPS (`ops/nginx/pca.conf`), que define `Host` e
`X-Forwarded-Proto` a partir da conexão real (nunca repassa o que o cliente mandou), e segue para
o Gunicorn em `127.0.0.1:${WEB_PORT}`. Páginas autenticadas devolvem
`Cache-Control: private, no-store` (presente em `core/views.py` e em várias views de
`apps/pca/`) — nenhuma página com dado de negócio é cacheável por proxy intermediário ou pelo
navegador.

## Runtime

Gunicorn, `worker-class gthread`, `--workers ${GUNICORN_WORKERS:-3} --threads
${GUNICORN_THREADS:-4}` — 3 processos × 4 threads = 12 slots de concorrência na mesma RAM que 3
workers síncronos ocupariam sozinhos, dimensionado para o pico de ~50 usuários simultâneos numa
reunião de acompanhamento. `--max-requests 1000 --max-requests-jitter 100` recicla workers
escalonadamente contra vazamento de memória. Ajustável via `GUNICORN_*` sem rebuild — só
`docker compose up -d` (os defaults ficam assados na imagem, em `entrypoint.sh`).

## Data

PostgreSQL 17, inicializado com `POSTGRES_INITDB_ARGS: "--locale-provider=icu --icu-locale=pt-BR
--encoding=UTF8"` (`compose.yml`) — colação ICU pt-BR desde a criação do volume; um volume
existente criado sem essas flags não pode ser corrigido depois sem recriar o banco. `CONN_MAX_AGE`
(default 60s) mantém conexões persistentes por thread do Gunicorn; `CONN_HEALTH_CHECKS = True`
evita erro em conexão morta após o TTL.

## Deployment

Ver [Deployment](deployment.md) para a topologia completa. `compose.yml` healthcheck do serviço
`web`: `curl -fsS http://127.0.0.1:8000/healthz`, com `start_period: 120s` (tempo de
`migrate --noinput` + subida do Gunicorn).

## Observability

`LOGGING` (`config/settings/base.py`) mantém dois loggers sempre ativos, mesmo com `DEBUG=False`
(diferente do filtro `require_debug_true` padrão do Django, que os descartaria em produção):

- `django.security.csrf`, nível `WARNING` — toda falha de CSRF é logada (path + motivo, nunca
  corpo da requisição nem credenciais).
- `django.request`, nível `WARNING` — erros 4xx/5xx tratados pelo Django.

Ambos com `propagate: False`, handler `console` (`docker compose logs web` é o ponto único de
leitura). `core.views.csrf_failure_view` (`CSRF_FAILURE_VIEW`) é quem decide a página amigável
mostrada ao usuário quando o token CSRF falha — nunca a página crua do Django.

## Recovery

**Backup:** serviço `backup` roda `ops/backup/backup.sh` — `pg_dump --format=custom` diário
enviado por `rclone copy` para `<remoto>:${R2_BUCKET}/daily/` e, aos domingos, também para
`/weekly/`; `ops/backup/retencao.sh::manter_ultimos()` mantém só os 7 diários e 4 semanais mais
recentes (ordenado pela data real do objeto no remoto, não pelo nome do arquivo).

**Restore:** sempre via `pg_restore --clean --if-exists --no-owner`, **nunca**
`psql < arquivo.sql` (perderia o formato customizado e a possibilidade de restore seletivo):

```sh
docker compose exec -T db pg_restore --clean --if-exists --no-owner \
  --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" - < "$DUMP_FILE"
```

`ops/backup/ensaio_restore_local.sh` automatiza um ensaio de restore local, e
`ops/backup/testar_retencao.sh` testa a lógica de retenção isoladamente, sem tocar no backup real.

**Fontes verificadas:** `config/settings/base.py` (`LOGGING`), `core/views.py`
(`csrf_failure_view`, `Cache-Control`), `compose.yml`, `entrypoint.sh`, `ops/backup/backup.sh`,
`ops/backup/retencao.sh`, `ops/backup/ensaio_restore_local.sh`, `ops/backup/testar_retencao.sh`.
