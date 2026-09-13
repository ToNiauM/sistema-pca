# Deployment

## Topologia real

```
Internet → Proxy HTTPS (Nginx do host, IIS/ARR ou outro) → Gunicorn em 127.0.0.1:${WEB_PORT} → PostgreSQL 17
                                                          ↘ Serviço `backup` (pg_dump + rclone) → armazenamento S3-compatível (opcional)
```

O runbook completo, testado passo a passo numa VM limpa (Debian/Ubuntu, família RHEL ou qualquer
outra distro via script oficial do Docker), está em `ops/MIGRACAO.md` (raiz do repositório) —
este capítulo resume os pontos que um mantenedor precisa decidir antes de seguir aquele runbook.

## Containers Linux — sem build nativo para Windows

A imagem (`Dockerfile`, `python:3.12-slim`) é um container **Linux**. Em Windows Server, isso
exige Hyper-V ou WSL 2 (Docker Desktop ou Docker Engine sobre WSL 2) — não existe build nativo
Windows deste projeto.

## Volume externo do banco

`compose.yml` declara `pgdata` como volume **externo** (`external: true`,
`name: ${PGDATA_VOLUME:-pca_pgdata}`) — precisa ser criado manualmente antes do primeiro
`docker compose up -d`:

```sh
docker volume create "${PGDATA_VOLUME:-pca_pgdata}"
```

Sem isso, `docker compose down -v` apagaria o banco junto — é exatamente o cenário que motivou
declarar o volume como externo.

## Proxy reverso e HTTPS

`ops/nginx/pca.conf` é o template de referência do proxy: recebe HTTPS na borda, encaminha para
`http://127.0.0.1:${WEB_PORT}` com `Host`/`X-Forwarded-Proto` sempre definidos pelo próprio Nginx
(nunca repassando o que o cliente mandou). Um CDN/WAF na frente do proxy (o exemplo real de
produção usa Cloudflare) é **opcional e substituível** por qualquer proxy HTTPS equivalente — se
usado, o modo TLS entre o CDN e a origem precisa ser "full end-to-end" (certificado válido na
origem via Let's Encrypt/certbot); um modo que fale HTTP com a origem entra em loop de redirect
com `SECURE_SSL_REDIRECT` (ver [Troubleshooting](troubleshooting.md)).

## Estáticos

Coletados em build-time pelo `Dockerfile` (`collectstatic --noinput`, com
`DJANGO_SETTINGS_MODULE=config.settings.prod` e um `SECRET_KEY`/`DATABASE_URL` de build
descartáveis) — não há etapa manual de `collectstatic` em produção.

## Backup

Serviço `backup` do `compose.yml`: `pg_dump --format=custom` diário, enviado via `rclone` para um
destino S3-compatível (`RCLONE_CONFIG_R2_*`, `R2_BUCKET`) — Cloudflare R2 é só o exemplo usado em
produção, **opcional e substituível** por qualquer remoto que `rclone` suporte. Retenção de 7
diários / 4 semanais (`ops/backup/retencao.sh`). Ver [Operação](operacao.md), seção Recovery.

## Reinicialização e atualização de versão

| Mudança | Comando |
|---|---|
| Só reiniciar (sem mudança de código/dependência) | `docker compose restart web` |
| Código Python/template mudou | `docker compose build web && docker compose up -d web` |
| Nova versão publicada (git pull) | `git pull` → `docker compose build web` → `docker compose up -d` → migrations rodam sozinhas no `entrypoint.sh` |
| Estático mudou (CSS/JS/imagem) | bump manual de `pca-static-vN` em `core/views.py` antes do build — o service worker do PWA só invalida o cache antigo quando o nome muda |

Sem downtime de banco em uma atualização normal — só o container `web` é reconstruído/reiniciado;
`db` continua rodando.

## Health check

`GET /healthz` (`core/views.py::healthz`) roda `SELECT 1` no banco e responde `{"status": "ok"}`
(200) ou `{"status": "error"}` (503). `compose.yml` usa esse endpoint como `healthcheck` do
serviço `web`; `SECURE_REDIRECT_EXEMPT` em `config/settings/prod.py` evita que
`SECURE_SSL_REDIRECT` quebre essa checagem interna (que bate direto em HTTP, sem passar pelo
proxy).

## Referência de capacidade

Medido em ambiente de validação: pico de ~255 MB de RAM para o container `web`, ~551 MB para
`db`, banco com ~14 MB de dados, imagens Docker somando ~1 GB. Uma VM de referência com **2
vCPU / 4 GB de RAM / 40 GB de disco** comporta a aplicação com folga.

**Fontes verificadas:** `compose.yml`, `Dockerfile`, `entrypoint.sh`, `ops/nginx/pca.conf`,
`ops/MIGRACAO.md`, `ops/backup/backup.sh`, `ops/backup/retencao.sh`, `core/views.py` (`healthz`,
`pca-static-v44`), `config/settings/prod.py` (`SECURE_REDIRECT_EXEMPT`).
