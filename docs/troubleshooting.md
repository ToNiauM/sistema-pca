# Troubleshooting

| Sintoma | Causa provável | Diagnóstico/correção |
|---|---|---|
| 502 atrás do Nginx | Gunicorn não subiu (erro de migration, `SECRET_KEY` ausente) ou SELinux bloqueando a conexão do Nginx ao loopback (família RHEL) | `docker compose logs web`; na família RHEL, confirme `getsebool httpd_can_network_connect` (precisa estar `on`, ver `ops/MIGRACAO.md`) |
| Loop de redirect HTTPS | Um CDN/WAF na frente fala HTTP com a origem enquanto `SECURE_SSL_REDIRECT` (`config/settings/prod.py`) devolve 301 para HTTPS — o CDN segue o 301 fazendo nova requisição HTTP, e o ciclo se repete | Configure o CDN em modo "TLS full/strict" (certificado válido na origem via Let's Encrypt), nunca um modo que fale HTTP puro com a origem (`ops/nginx/pca.conf` documenta isso no comentário do topo) |
| CSRF falha em produção (usuário logado recebe "Verificação CSRF falhou") | Token velho por bfcache/"Voltar" depois de um login/logout (`rotate_token()`), ou `CSRF_COOKIE_HTTPONLY` alterado para `True` | `CSRF_COOKIE_HTTPONLY` precisa continuar `False` — `htmx:configRequest` (`core/static/dsgov/js/dsgov.js`) lê o cookie a cada requisição, nunca um header estático; `core.views.csrf_failure_view` já trata o caso comum reapresentando o login com token novo |
| Healthcheck do compose fica `unhealthy` mesmo com o app respondendo | `SECURE_SSL_REDIRECT` sem a exceção de `/healthz`, ou `start_period` insuficiente para `migrate` + subida do Gunicorn | Confirme `SECURE_REDIRECT_EXEMPT = [r"^healthz$"]` em `config/settings/prod.py`; `docker compose ps` mostra o tempo decorrido, `start_period: 120s` já cobre o caso comum |
| `migrate` falha em banco vazio (`unaccent` / extensão ausente) | A extensão `unaccent` do PostgreSQL exige um usuário com privilégio para criar extensão — não roda em SQLite, e falha num Postgres sem esse privilégio | Confirme que `DATABASE_URL` aponta para PostgreSQL (nunca SQLite) e que `POSTGRES_USER` é superuser do banco de destino (`apps/pca/migrations/0002_unaccent.py` exige isso) |
| `docker compose down -v` "apagou" o banco | O volume `pgdata` foi criado sem ser externo antes desta versão, ou `PGDATA_VOLUME` foi trocado sem recriar o volume | `compose.yml` já declara `pgdata` como `external: true` — confirme com `docker volume inspect "${PGDATA_VOLUME:-pca_pgdata}"` que o volume existe e tem o nome esperado antes de qualquer `down -v` |
| `manage.py test` trava ou falha em `unaccent` | Suíte rodando contra SQLite em vez de PostgreSQL | Rode sempre dentro do container `web` (`docker compose exec web python manage.py test`), nunca fora do compose com um `DATABASE_URL` local diferente |

**Fontes verificadas:** `config/settings/prod.py` (`SECURE_SSL_REDIRECT`,
`SECURE_REDIRECT_EXEMPT`), `ops/nginx/pca.conf`, `core/static/dsgov/js/dsgov.js`
(`htmx:configRequest`), `core/views.py` (`csrf_failure_view`), `compose.yml` (healthcheck,
volume externo), `apps/pca/migrations/0002_unaccent.py`, `ops/MIGRACAO.md` (SELinux/firewalld).
