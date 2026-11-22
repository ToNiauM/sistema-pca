# Deployment

Referência de configuração relacionada a banco de dados. O passo a passo
completo de deploy (VM limpa, Docker, Nginx, TLS, Cloudflare) está em
[`ops/MIGRACAO.md`](../ops/MIGRACAO.md) — este documento não duplica o
runbook, só a parte de variáveis/volume que qualquer deploy precisa acertar.

## Variáveis de ambiente (banco)

Definidas em [`.env.example`](../.env.example):

| Variável | Uso |
|---|---|
| `DATABASE_URL` | URL do arquivo SQLite: `sqlite:////app/data/db.sqlite3` (4 barras = caminho absoluto dentro do container). Default já correto — normalmente não precisa mudar. |
| `DATA_VOLUME` | Nome do volume Docker externo que guarda `db.sqlite3` (e `-wal`/`-shm` ao lado). Default `pca_data`. |

Nenhuma outra variável de banco existe — não há usuário, senha, host nem
porta para configurar (a diferença mais visível para quem migrou de um
`.env` anterior ao PostgreSQL: `POSTGRES_DB`/`POSTGRES_USER`/
`POSTGRES_PASSWORD`/`PGDATA_VOLUME` saíram, `DATA_VOLUME` entrou).

## Passo a passo resumido (ver `ops/MIGRACAO.md` Passos 2-5 para o runbook completo)

1. **Criar o volume externo antes de qualquer `docker compose up`:**
   ```sh
   docker volume create "${DATA_VOLUME:-pca_data}"
   ```
   Este passo não é opcional — `pca_data` é declarado `external: true` em
   [`compose.yml`](../compose.yml), então o Compose não o cria implicitamente,
   e o volume externo nunca é apagado por `docker compose down -v`.

2. **Instalação nova (banco vazio):** basta `docker compose up -d` — o
   `entrypoint.sh` roda `migrate --noinput` e o schema nasce do zero dentro
   do volume.

3. **Migrando dados existentes:** copie o arquivo `.sqlite3` (de um backup
   `.backup`+`gzip`, ou de um `dumpdata`/`loaddata` vindo de um PostgreSQL
   antigo — ver [`ops/migracao_sqlite/README.md`](../ops/migracao_sqlite/README.md))
   para dentro do volume **antes** do primeiro `docker compose up -d`. Detalhe
   completo do comando de cópia em
   [`docs/operacao.md`](operacao.md#backuprestore) e no
   [`README.md`](../README.md#restore-do-banco) do projeto.

4. **Validar:** `curl -fsS http://127.0.0.1:${WEB_PORT}/healthz` deve
   responder `{"status": "ok"}`.

## Mais de um domínio (ou troca de domínio)

O sistema não sabe em que domínio está — quem decide é o `.env` + o proxy. Para servir
o mesmo container em dois domínios (caso real do CFC desde 21/09/2026: o domínio
histórico e o atual apontam para a mesma aplicação), ou para trocar de domínio:

1. `.env`: os dois hosts em `ALLOWED_HOSTS` (separados por vírgula) e as duas origens
   `https://…` em `CSRF_TRUSTED_ORIGINS`. `config.settings.prod` lê os dois como lista.
2. `docker compose up -d web` — o `.env` só é lido na **recriação** do container;
   `restart` não basta.
3. No Nginx do host, um `server` por domínio (o de [`ops/nginx/pca.conf`](../ops/nginx/pca.conf)
   duplicado com o outro `server_name`/certificado), ambos com o mesmo `proxy_pass` para a
   porta do `web`. `nginx -t && systemctl reload nginx`.
4. Provar com um POST real pelo domínio novo (ex.: login com senha inválida → 200 com o
   formulário, nunca 403): é isso que confirma `CSRF_TRUSTED_ORIGINS`.

Nada mais muda — sessão, PWA/service worker e links internos são relativos ao host da
requisição. Não há passo no banco.

## O que NÃO existe mais neste deploy

Comparado a um deploy anterior à Fase 31 (PostgreSQL 17): sem serviço `db` no
`compose.yml`, sem `initdb`/ICU para configurar, sem `pg_dump`/`pg_restore`,
sem role/usuário de banco, sem porta de banco para abrir/fechar no firewall.
O `web` e o `backup` são os únicos dois serviços que tocam o arquivo do
banco, ambos montando o mesmo volume `pca_data`.

## Assistente do PCA (Fase 39)

Variáveis obrigatórias/opcionais e tabela completa em
[`docs/operacao.md#assistente-do-pca-fase-39`](operacao.md#assistente-do-pca-fase-39) —
aqui só o que muda no runbook de implantação:

- **Obrigatória para habilitar**: `IA_API_KEY` (vazia = assistente desabilitado, sem
  quebrar `check`/testes/`collectstatic`/sincronização com o SEI). Demais `IA_*` têm default seguro.
- **`GUNICORN_TIMEOUT=150`** — o prazo interno do assistente é de até 90s; o worker
  precisa de folga sobre esse prazo. Ajustar **também** o `proxy_read_timeout` do Nginx
  do host (amostra em [`ops/nginx/pca.conf`](../ops/nginx/pca.conf); o executor não
  altera o proxy real).
- **Rebuild de dependências**: `docker compose build web robo && docker compose up -d
  web robo` — `web` e `robo` compartilham `requirements.txt`/`requirements-robo.txt`, e
  o serviço `robo` herda `openai`/`numpy`/`markdown-it-py` mesmo não usando o assistente
  diretamente (ele só consome a fila de reindexação).
- **Rede**: `web` e `robo` precisam de saída HTTPS (443) para `api.openai.com` — nenhuma
  porta de entrada nova.
- **Volume `pca_data`**: passa a conter também `ia/` (índice/estado/conversas/fila do
  assistente). **`ia/` é inteiramente RECONSTRUÍVEL** — migração de host continua sendo
  só `db.sqlite3` + `.env`; rodar `ia_indexar --completo` no destino é opcional (reduz o
  intervalo até a primeira resposta ficar com dados de busca semântica, mas o assistente
  já funciona sem índice para as ferramentas que não usam `buscar_texto`). Nenhum passo
  manual adicional além desse — o invariante de portabilidade do projeto (zero passo além
  de copiar o banco + `.env` + subir os containers) continua valendo.

## Extensões SEI Pro (Fase 42)

A extensão de navegador `sei-pro` envia ao PCA a coleta bruta de um processo SEI (histórico +
documentos) por uma API JSON própria, autenticada por token pessoal — aplicada pelas MESMAS
regras do robô SEI (`montagem.py`/`regras.propor`/`aplicador.aplicar`). Contrato completo:
[`docs/api-extensao-sei.md`](api-extensao-sei.md).

- **Migração nova**: `core` ganha `core/migrations/0007_token_api.py` (model `TokenApi` — token
  pessoal por usuário, só o hash sha256 persistido). Aplicada pelo `migrate --noinput` do
  `entrypoint.sh` na próxima subida do `web`, **sem passo manual de schema** — mesma mecânica de
  sempre, só precisa do `restart`/`up -d web` que já é o gate humano desta fase (ver "Implantação
  (gate humano)" abaixo).
- **Três variáveis novas de `.env`** (ver `.env.example`):

  | Variável | Default | Uso |
  |---|---|---|
  | `API_ORIGENS_EXTENSAO` | `https://sei.cfc.org.br` | Origem HTTP permitida pelo CORS restrito a `/api/` (`core/middleware.py::CorsExtensaoMiddleware`) — além dela, a origem `chrome-extension://[a-p]{32}` (extensão instalada) sempre é aceita. |
  | `API_MAX_CORPO_MB` | `10` | Teto de tamanho do corpo JSON aceito por `POST /api/sei/coleta` (`corpo_dentro_do_limite`) — acima disso, `413`. |
  | `SEI_PULAR_SE_EXTENSAO_H` | `24` | Horas de validade de uma coleta da extensão para o robô pular (sem abrir o navegador) aquele número SEI na próxima varredura — `0` (ou qualquer valor `<= 0`) desliga o pulo por completo. |

- **Nota do proxy**: `client_max_body_size 12m` precisa existir no `location /api/` do Nginx do
  host — acima de `API_MAX_CORPO_MB` (10 MB) por causa do PDF em base64 que pode compor o corpo
  do `POST /api/sei/coleta`. Amostra versionada em
  [`ops/nginx/pca.conf`](../ops/nginx/pca.conf) — **o executor não altera o proxy real**, só a
  amostra (mesma frase/mesmo padrão da seção do Assistente, Fase 39, acima).
- **Nada no volume `pca_data` muda de estrutura além da tabela nova**: `data/sei/extensao.json`
  é mais um arquivo irmão de `cache.json`/`links.json` (ver
  [`docs/operacao.md`](operacao.md), seção "`data/sei/`"), reconstruível, fora da
  retenção/backup diário, sem exigir passo de migração de dado nenhum.
