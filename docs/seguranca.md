# Segurança

## Gerenciamento de segredos

Toda configuração sensível (`SECRET_KEY`, `POSTGRES_PASSWORD`, credenciais de backup) vem de
variáveis de ambiente via `django-environ` (`environ.Env.read_env(BASE_DIR / ".env")`,
`config/settings/base.py`) — nunca hardcoded no código. `.env` nunca é commitado (`.gitignore`);
`.env.example` só contém placeholders. Ver [Configuração](configuracao.md) para a tabela
completa.

## Permissões

Além de `is_staff`/`is_superuser` (acesso ao Django Admin), o modelo `Processo` declara duas
permissões próprias (`apps/pca/models.py`, `Processo.Meta.permissions`):

- `pca.editar_pca` — editar processos e registrar acompanhamento.
- `pca.gerir_exercicio` — criar, abrir e fechar exercícios do PCA (inclui todo o wizard de virada
  de exercício).

Views que alteram dados de negócio exigem essas permissões via `@permission_required(...,
raise_exception=True)` — nunca um `if request.user.is_staff` solto. Um usuário sem nenhuma das
duas ainda pode ler todas as telas (dashboards, tabela, calendário, análises), pois o sistema é
100% autenticado, mas apenas leitura.

## Autenticação

- **Hash de senha:** Argon2 no topo de `PASSWORD_HASHERS`, PBKDF2 como fallback de leitura
  (nunca de gravação) — `config/settings/base.py`.
- **Login por e-mail:** `core.Usuario` usa `USERNAME_FIELD = "email"` (`core/models.py`) — não há
  `username`.
- **Bloqueio de força bruta:** `django-axes`, `AXES_FAILURE_LIMIT = 5`,
  `AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]` (bloqueio pela combinação, nunca só
  pelo usuário — evita que alguém trave a conta de outra pessoa só sabendo o e-mail dela),
  `AXES_COOLOFF_MINUTES` configurável (default 15 minutos).
- **Troca de senha obrigatória:** `Usuario.senha_temporaria` (migration `core.0004`) força a
  troca no primeiro acesso — `TrocaSenhaObrigatoriaMiddleware` intercepta qualquer navegação até
  a senha ser trocada, sem exceção nem para o próprio superusuário.

## Exposição de rede

- O container `web` nunca expõe `0.0.0.0` diretamente: `WEB_BIND_ADDRESS` deve ser sempre
  `127.0.0.1` — só o proxy do host alcança a aplicação.
- O container `db` também só expõe a porta em loopback (`127.0.0.1:15433:5432`,
  `compose.yml`) — o Postgres nunca é alcançável de fora do host.

## HTTPS e cabeçalhos de segurança

- `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")` e
  `SECURE_SSL_REDIRECT` (`config/settings/prod.py`) — o proxy do host escreve
  `X-Forwarded-Proto` ele mesmo; o Django nunca confia em cabeçalho vindo direto do cliente
  (`USE_X_FORWARDED_HOST = False`).
- `SECURE_REDIRECT_EXEMPT = [r"^healthz$"]` — evita que o healthcheck interno do compose (HTTP
  puro, direto no `127.0.0.1:8000`) entre em loop de redirect.
- `SECURE_HSTS_SECONDS` **conservador por padrão** (3600s = 1h, não 31536000 = 1 ano): um
  `max-age` longo é irreversível pelo próprio tempo que ele declara — o valor só deve subir depois
  do TLS confirmado estável no host definitivo. `SECURE_HSTS_INCLUDE_SUBDOMAINS`/
  `SECURE_HSTS_PRELOAD` ficam `False` de propósito (o domínio de produção pode ser compartilhado
  por outros subdomínios que este projeto não controla) — os avisos `security.W005`/`W021`
  correspondentes são silenciados explicitamente (`SILENCED_SYSTEM_CHECKS`), não esquecidos.
- Cookies: `SESSION_COOKIE_SECURE = True`, `SESSION_COOKIE_SAMESITE = "Lax"`,
  `CSRF_COOKIE_SECURE = True`, `CSRF_COOKIE_SAMESITE = "Lax"`.
- `CSRF_COOKIE_HTTPONLY = False` **de propósito** — o HTMX precisa ler o cookie do token a cada
  requisição (`htmx:configRequest`, `core/static/dsgov/js/dsgov.js`), porque um `hx-headers`
  estático congelaria um token que o Django roda `rotate_token()` a cada login/logout. Mudar isto
  para `True` quebra toda escrita HTMX do sistema.

## Cuidados de produção

`DEBUG = False` (`config/settings/prod.py`, nunca sobrescrito por variável de ambiente) e
`ALLOWED_HOSTS` restrito ao(s) domínio(s) reais mais `127.0.0.1` (necessário para o healthcheck
interno). `X-Frame-Options: DENY` via `XFrameOptionsMiddleware` — o sistema nunca é embutido em
iframe.

## Auditoria e Django Admin

`django-simple-history` registra automaticamente `Processo`/`Acompanhamento`/`Usuario`. Um
superusuário pode editar ou apagar qualquer registro pelo Django Admin, **inclusive linhas
históricas** — a trilha `simple_history` continua automática nas telas do sistema, mas deixa de
ser imutável no Admin. Isso é uma decisão explícita de projeto (superusuário como operador de
última instância), não uma lacuna: qualquer instalação que precise de imutabilidade estrita
precisa restringir o acesso de superusuário ao Admin por fora do próprio Django.

**Fontes verificadas:** `config/settings/base.py`, `config/settings/prod.py`,
`apps/pca/models.py` (`Processo.Meta.permissions`), `apps/pca/views.py`/`views_processo.py`
(`@permission_required`), `core/models.py`, `core/middleware.py`
(`TrocaSenhaObrigatoriaMiddleware`), `core/migrations/0004_usuario_senha_temporaria.py`,
`core/static/dsgov/js/dsgov.js`.
