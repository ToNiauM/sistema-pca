# PCA CFC — Acompanhamento do Plano de Contratações Anual

## O que é

Aplicação web PWA que substitui a planilha Excel usada hoje pelo Conselho Federal
de Contabilidade (CFC) para acompanhar o Plano de Contratações Anual — no
exercício 2026, 154 itens e cerca de R$ 186 milhões planejados, distribuídos
entre 18 unidades organizacionais (medição de 28/08/2026). No lugar de uma aba
que cresce uma coluna de texto livre a cada reunião mensal, o sistema dá à
equipe do PCA dashboards e tabela editável, e dá ao presidente e ao corpo
funcional do CFC uma visão de leitura do andamento.

## Objetivo e motivação

Hoje o acompanhamento do PCA é feito em uma planilha Excel única que cresce
horizontalmente: cada reunião mensal de acompanhamento vira uma nova coluna de
texto livre. Essa planilha mistura formatos de data e valor, guarda metadados
dentro do próprio identificador do item, e registra como dado estados que
poderiam ser calculados a partir do histórico.

O objetivo do sistema é substituir essa planilha por uma aplicação web com
dashboards e leitura imediata de plano versus execução — acompanhando
o item desde o planejamento no PCA, passando pelo funil processual até a
entrega ao Delic, e daí pela execução contratual (modalidade, contrato,
fornecedor, vigência, valor contratado) até a publicação em SPW, WordPress e
Dados Abertos.

O critério que resume esse objetivo: "A equipe conduz a reunião mensal de
acompanhamento inteiramente dentro do sistema — editando no ato, sem abrir a
planilha."

## O que o sistema faz

- Dashboard analítico com KPIs clicáveis, gráficos ECharts e filtros globais.
- KPI e filtro de compromissos remarcados, com drill-down.
- Tabela de leitura com busca, filtros, ordenação e paginação server-side, e
  edição inline para o perfil `editor`.
- Export do resultado filtrado em CSV e XLSX.
- Detalhe do processo com timeline de acompanhamento e cadeia de prazos
  prometidos, cobrindo o funil do planejamento no PCA até a entrega ao Delic.
- Bloco de execução contratual — modalidade, contrato, fornecedor, vigência,
  valor contratado — e marcos de publicação em SPW, WordPress e Dados Abertos.
- Exportar o banco inteiro em XLSX (uma aba por tabela) pelo Django Admin,
  editar e reimportar com relatório de diferenças, confirmação e backup
  automático.

## Para quem não é da área

Um Plano de Contratações Anual (PCA) é a lista de tudo o que um órgão público
planeja comprar ou contratar durante um ano — cada item tem um prazo previsto
e um responsável. É um instrumento exigido pela legislação de licitações, e
qualquer atraso ou mudança nele precisa ficar registrado.

O CFC precisa acompanhar esse plano mês a mês para saber o que está atrasado,
o que já foi contratado e quanto do valor planejado já virou contrato real.
Hoje esse acompanhamento acontece numa reunião mensal em que a equipe revisa
item por item numa planilha que só cresce — cada reunião vira uma coluna nova,
e descobrir a situação atual de um item exige ler várias colunas de texto
livre em sequência.

Este sistema resolve isso trocando a planilha por um lugar único onde a
equipe atualiza a situação de cada item na hora da própria reunião, e onde o
presidente e o corpo funcional do CFC acompanham o andamento sem precisar
pedir a planilha a ninguém. Ao longo do processo, alguns termos aparecem: o
**Delic** é o setor do CFC responsável pela condução das licitações e
contratações; o **SPW** é o sistema onde o CFC registra formalmente contratos
e execução orçamentária; **Dados Abertos** é o portal onde o CFC publica essas
informações para consulta pública, em cumprimento à transparência exigida de
órgãos públicos.

## Para profissionais de TI

**Stack** (versões em `requirements.txt`): Django 5.2 LTS, SQLite (arquivo
único), Django Templates + HTMX + Alpine.js + Tailwind CSS, ECharts,
SortableJS, Gunicorn, Docker Compose. Principais pacotes Python:
django-environ (configuração via variáveis de ambiente),
django-simple-history (auditoria automática), django-axes (proteção de
login), django-htmx, argon2-cffi (hasher de senha), whitenoise (estáticos),
openpyxl (import/export de planilha) e django-ipware. O build do Tailwind
roda em `node:20-alpine` dentro do `Dockerfile`; não há um `package.json` de
aplicação JS separado — Tailwind é a única etapa de build de front-end.

### Instalação

1. Clone o repositório: `https://github.com/ToNiauM/pca`.
2. Copie `.env.example` para `.env` e preencha, no mínimo: `SECRET_KEY`
   (gerado especificamente para este ambiente, nunca reaproveitado de outro).
   `DATABASE_URL` já vem com o default correto
   (`sqlite:////app/data/db.sqlite3`) — não há usuário/senha de banco para
   configurar.
3. Crie o volume externo do banco **antes** de subir qualquer serviço — este
   passo não é opcional, o volume `pca_data` é declarado `external: true` em
   `compose.yml` e não é criado implicitamente pelo Compose:
   ```
   docker volume create <valor de DATA_VOLUME, default pca_data>
   ```
4. Suba os serviços:
   ```
   docker compose up -d
   ```

O `entrypoint.sh` já roda `python manage.py migrate --noinput` e sobe o
Gunicorn automaticamente — não há passo manual de migração. O
`collectstatic` já roda durante o build da imagem no `Dockerfile` — também
não há passo manual para ele. Para confirmar que o serviço `web` subiu
corretamente, use o healthcheck real da aplicação:

```
curl -fsS http://127.0.0.1:<WEB_PORT>/healthz
```

que deve responder `{"status": "ok"}`.

Este passo a passo cobre apenas subir um ambiente a partir de um `.env`
configurado. Para o runbook completo de migração para uma VM limpa —
detecção de distro, instalação de Docker, Nginx, certificado TLS e
configuração de Cloudflare — ver [`ops/MIGRACAO.md`](ops/MIGRACAO.md).

### Variáveis de ambiente

Todas definidas em `.env.example` (arquivo versionado, sem valores reais):

| Variável | Uso |
|---|---|
| `SECRET_KEY` | Chave de assinatura do Django |
| `DEBUG` | Ativa modo de depuração |
| `DJANGO_SETTINGS_MODULE` | `config.settings.dev` local / `config.settings.prod` produção |
| `ALLOWED_HOSTS` | Hosts permitidos pelo Django |
| `CSRF_TRUSTED_ORIGINS` | Origens confiáveis para CSRF |
| `SESSION_COOKIE_AGE` | Duração da sessão |
| `AXES_COOLOFF_MINUTES` | Janela de bloqueio do django-axes após tentativas de login falhas |
| `WEB_BIND_ADDRESS` | Endereço de bind do serviço `web` (deve ficar em `127.0.0.1`) |
| `WEB_PORT` | Porta publicada do serviço `web` |
| `SECURE_SSL_REDIRECT` | Redireciona HTTP para HTTPS |
| `SECURE_HSTS_SECONDS` | Duração do HSTS |
| `DATABASE_URL` | URL do arquivo SQLite (`sqlite:////app/data/db.sqlite3`, 4 barras = caminho absoluto) |
| `DATA_VOLUME` | Nome do volume externo que guarda `db.sqlite3` (e `-wal`/`-shm` ao lado; default `pca_data`) |
| `R2_ACCESS_KEY_ID` | Credencial de acesso ao Cloudflare R2 (backup) |
| `R2_SECRET_ACCESS_KEY` | Credencial de acesso ao Cloudflare R2 (backup) |
| `R2_ENDPOINT` | Endpoint do Cloudflare R2 (backup) |
| `R2_BUCKET` | Bucket do Cloudflare R2 (backup) |

As quatro últimas (`R2_*`) são opcionais — só são necessárias para o serviço
`backup` e para restaurar um dump diretamente do R2.

### Restore do banco

O backup diário roda via `sqlite3 <arquivo> ".backup"` (cópia consistente do
arquivo mesmo com o modo WAL ativo e escritores concorrentes) seguido de
`gzip`, enviado por `rclone` para `r2:${R2_BUCKET}/daily/` todo dia, e também
para `r2:${R2_BUCKET}/weekly/` aos domingos. A retenção é de 7 pontos diários
e 4 pontos semanais.

Sequência de restore (a aplicação fica parada durante a cópia — não há mais
`pg_restore` nem role de banco):

1. Pare o serviço `web`:
   ```
   docker compose stop web
   ```
2. Copie o `.sqlite3.gz` mais recente do R2 (variáveis `RCLONE_CONFIG_R2_*`
   exportadas a partir de `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` e
   `R2_ENDPOINT`):
   ```
   rclone copy "r2:${R2_BUCKET}/daily/<arquivo>.sqlite3.gz" .
   ```
3. Descompacte e copie o arquivo para dentro do volume `pca_data`, usando um
   container descartável (nunca a árvore de trabalho — o arquivo real só
   existe dentro do volume):
   ```
   docker run --rm \
     -v "${DATA_VOLUME:-pca_data}:/data" \
     -v "$(pwd)/<arquivo>.sqlite3.gz:/tmp/restore.sqlite3.gz:ro" \
     busybox sh -c "gunzip -c /tmp/restore.sqlite3.gz > /data/db.sqlite3"
   ```
4. Suba o serviço de novo — o `entrypoint.sh` já roda a migration, não é
   preciso rodar `migrate` manualmente:
   ```
   docker compose up -d web
   ```
5. Valide com o healthcheck:
   ```
   curl -fsS http://127.0.0.1:${WEB_PORT}/healthz
   ```

Não há extensão/ICU para configurar: a ordenação pt-BR e a busca sem acento
são funções Python registradas em `core/db.py` a cada conexão, não recursos
do banco em si.

Este é um resumo operacional. A prova reexecutável deste procedimento —
incluindo os dois "gates" (o volume externo sobrevive a `down -v`; o arquivo
restaurado bate contagem com a origem) — é
[`ops/backup/ensaio_restore_local.sh`](ops/backup/ensaio_restore_local.sh); o
runbook completo de migração para uma VM nova é
[`ops/MIGRACAO.md`](ops/MIGRACAO.md).

## Licença

O código e a documentação do PCA CFC são distribuídos sob a licença
[AGPL-3.0](LICENSE), com Copyright © 2026 Antônio Rodrigues de Sousa Júnior.
Os dados do PCA pertencem ao Conselho Federal de Contabilidade (CFC) e não
estão abrangidos por essa licença. Componentes de terceiros mantêm suas
próprias licenças.

## Documentação

- Manual do usuário: <https://toniaum.github.io/sistema-pca/>
- Documentação técnica: <https://toniaum.github.io/sistema-pca/tecnica/>
