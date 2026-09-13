# Configuração

Toda configuração do sistema é feita por variáveis de ambiente (`django-environ`), lidas de um
arquivo `.env` na raiz do projeto (`environ.Env.read_env(BASE_DIR / ".env")`,
`config/settings/base.py`) — nenhuma delas tem valor real neste repositório;
`.env.example` na raiz documenta todas com placeholders seguros. Nenhum
valor abaixo é um segredo de produção.

## Variáveis lidas por `config/settings/*.py`

| Variável | Finalidade | Obrigatória? | Exemplo seguro | Default |
|---|---|---|---|---|
| `SECRET_KEY` | Chave criptográfica do Django (sessões, tokens CSRF) | **Sim** | `python3 -c "import secrets; print(secrets.token_urlsafe(50))"` | nenhum — falha ao subir sem ela |
| `DJANGO_SETTINGS_MODULE` | Qual módulo de settings carregar (`config.settings.dev`/`.prod`) | Não | `config.settings.prod` | `config.settings.dev` (`manage.py`) |
| `DEBUG` | Modo debug (stacktraces, `ALLOWED_HOSTS=["*"]`) | Não | `false` | `True` (`dev.py`) |
| `DATABASE_URL` | String de conexão Postgres (`env.db`) | **Sim** | `postgres://pca:senha@db:5432/pca` | nenhum |
| `CONN_MAX_AGE` | Segundos de reuso de conexão persistente com o Postgres | Não | `60` | `60` |
| `ALLOWED_HOSTS` | Hosts aceitos em produção (`env.list`) | Recomendada em produção | `meudominio.gov.br` | `[]` (mais `127.0.0.1`, sempre adicionado em `prod.py` para o healthcheck interno) |
| `CSRF_TRUSTED_ORIGINS` | Origens confiáveis para POST sob HTTPS via proxy | Recomendada em produção | `https://meudominio.gov.br` | `[]` |
| `SECURE_SSL_REDIRECT` | Redireciona HTTP→HTTPS (exceto `/healthz`) | Não | `true` | `True` (`prod.py`) |
| `SECURE_HSTS_SECONDS` | `max-age` do cabeçalho HSTS | Não | `3600` | `3600` (conservador — ver [Segurança](seguranca.md)) |
| `SESSION_COOKIE_AGE` | Duração da sessão autenticada, em segundos | Não | `28800` (8 h) | `28800` |
| `AXES_COOLOFF_MINUTES` | Minutos de bloqueio do `django-axes` após 5 falhas de login | Não | `15` | `15` |
| `PCA_DIAS_PROXIMOS_VENCIMENTO` | Dias corridos até `prazo_entrega` que classificam um item "próximo do vencimento" | Não | `15` | `15` |
| `DSGOV_ORGAO` | Nome do órgão exibido na casca (rodapé, tela "Sobre") | Não | `Órgão Público Exemplo` | `Órgão` |
| `DSGOV_ORGAO_SIGLA` | Sigla do órgão | Não | `OPE` | `ÓRGÃO` |
| `DSGOV_SISTEMA` | Nome do sistema exibido no header/título | Não | `Sistema de Acompanhamento do Plano de Contratações Anual` | `Sistema de Acompanhamento do Plano de Contratações Anual` |
| `DSGOV_SISTEMA_SUBTITULO` | Subtítulo opcional do sistema | Não | (vazio) | `""` |
| `DSGOV_LOGO` | Caminho estático da logo institucional | Não | (vazio = fallback de sigla em texto) | `""` |
| `DSGOV_RODAPE_TEXTO` | Texto do rodapé da casca | Não | `Sistema de Acompanhamento do Plano de Contratações Anual` | mesmo texto |
| `DSGOV_RODAPE_TIMBRADO` | Texto timbrado só na impressão do relatório de movimentação | Não | (vazio) | `""` |

## Variáveis só do `compose.yml`/`entrypoint.sh` (sem `env()` em Python)

| Variável | Finalidade | Obrigatória? | Exemplo seguro | Default |
|---|---|---|---|---|
| `WEB_BIND_ADDRESS` | Endereço de bind da porta do container `web` no host | **Sim** | `127.0.0.1` (nunca `0.0.0.0`) | nenhum |
| `WEB_PORT` | Porta do host mapeada para o container `web` | **Sim** | `8000` | nenhum |
| `POSTGRES_DB` | Nome do banco Postgres | **Sim** | `pca` | nenhum |
| `POSTGRES_USER` | Usuário Postgres | **Sim** | `pca` | nenhum |
| `POSTGRES_PASSWORD` | Senha do Postgres — deve coincidir com a senha em `DATABASE_URL` | **Sim** | `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` | nenhum |
| `PGDATA_VOLUME` | Nome do volume Docker externo que guarda o banco (nunca apagado por `down -v`) | Não | `pca_pgdata` | `pca_pgdata` |
| `GUNICORN_WORKERS` | Nº de processos worker do Gunicorn | Não | `3` | `3` (`entrypoint.sh`) |
| `GUNICORN_THREADS` | Nº de threads por worker (worker-class `gthread`) | Não | `4` | `4` (`entrypoint.sh`) |
| `GUNICORN_TIMEOUT` | Timeout de requisição do Gunicorn, em segundos | Não | `60` | `60` (`entrypoint.sh`) |
| `R2_ACCESS_KEY_ID` | Credencial de acesso do armazenamento S3-compatível do backup | Só para o serviço `backup` | `replace-with-access-key-id` | nenhum |
| `R2_SECRET_ACCESS_KEY` | Credencial secreta do armazenamento do backup | Só para o serviço `backup` | `replace-with-secret-access-key` | nenhum |
| `R2_ENDPOINT` | Endpoint S3-compatível do armazenamento do backup | Só para o serviço `backup` | `https://<id-da-conta>.r2.cloudflarestorage.com` | nenhum |
| `R2_BUCKET` | Nome do bucket de destino do backup | Só para o serviço `backup` | `replace-with-bucket-name` | nenhum |

As quatro variáveis `R2_*` usam o prefixo herdado do exemplo real de produção (Cloudflare R2),
mas **qualquer destino compatível com `rclone`** funciona — ver [Arquitetura](arquitetura.md) e
[Operação](operacao.md).

## Nenhum valor real

`.env.example` não contém nenhuma senha, chave ou domínio real — só placeholders
(`replace-with-...`) e defaults neutros. Gere `SECRET_KEY` e `POSTGRES_PASSWORD` novos para cada
instalação; nunca reaproveite um segredo de outro ambiente.

**Fontes verificadas:** `config/settings/base.py`, `config/settings/dev.py`,
`config/settings/prod.py`, `compose.yml`, `entrypoint.sh`, `.env.example`, `manage.py`.
