# Arquitetura

## Topologia

Desde a Fase 31 não existe serviço `db` — o banco é um arquivo SQLite único,
dentro do mesmo volume do serviço `web`:

```
Internet → Cloudflare → Nginx (host) → Gunicorn (web, loopback 127.0.0.1)
                                              │
                                     /app/data/db.sqlite3
                                     (volume Docker externo pca_data)
                                              │
                                     serviço `backup` (mesmo volume,
                                     montado em /data)
```

`web` e `backup` (ver [`compose.yml`](../compose.yml)) montam o mesmo volume
externo `pca_data` — `web` em `/app/data`, `backup` em `/data`. O volume é
declarado `external: true` (`name: ${DATA_VOLUME:-pca_data}`) exatamente como
o antigo `pgdata` do PostgreSQL: `docker compose down -v` nunca o apaga. Os
arquivos `db.sqlite3-wal`/`db.sqlite3-shm` (exigidos pelo modo WAL) vivem ao
lado do `.sqlite3` no mesmo volume — nunca dentro da árvore de trabalho, que
em dev é montada `:ro`.

Só o Nginx do host fala com o Gunicorn (loopback); o app nunca fica exposto
diretamente. Ver [`ops/nginx/pca.conf`](../ops/nginx/pca.conf) para o template
de proxy e [`docs/deployment.md`](deployment.md) para as variáveis de
configuração.

## Modelo de dados — collation e busca sem acento

Três recursos que o PostgreSQL 17 resolvia com extensão/ICU/role de banco
agora são **funções Python registradas na conexão SQLite**, em
[`core/db.py`](../core/db.py), via o sinal `connection_created` de Django
(conectado em `core/apps.py::CoreConfig.ready()`, só quando
`connection.vendor == "sqlite"`):

- **`unaccent(texto)`** — remove diacríticos via `unicodedata.normalize("NFKD",
  ...)` + `casefold()`. Substitui a extensão `unaccent` do PostgreSQL.
  Registrada como `Transform` bilateral (`core.db.Unaccent`) em `CharField`/
  `TextField` — `apps/pca/busca.py` continua usando `__unaccent__icontains`
  sem nenhuma mudança de assinatura.
- **Collation `ptbr`** — ordena por `(unaccent(casefold(x)), x)`, com o texto
  original como desempate estável. Substitui a collation ICU `pt-BR` que o
  `POSTGRES_INITDB_ARGS` inicializava no PostgreSQL. Aplicada via
  `Collate(F(campo), "ptbr")` nos `order_by`/`Meta.ordering` de campos de
  texto voltados ao usuário (nomes de UO, rótulos de catálogo).
- **`DiasEntre(Func)`** — diferença inteira de dias entre duas datas
  (`CAST(julianday(a) - julianday(b) AS INTEGER)` no SQLite,
  `(a - b)` no PostgreSQL) — substitui `Extract(DurationField)`, que o SQLite
  não suporta nativamente.

Para adicionar um novo campo de texto pesquisável, use os mesmos lookups já
registrados (`__unaccent__icontains`) — não é preciso registrar nada de novo.
Para um novo `order_by`/`Meta.ordering` por nome, use
`Collate(F("campo"), "ptbr")`, o mesmo padrão já aplicado aos 7 pontos
convertidos no plano (ver `apps/pca/filtros.py`,
`apps/pca/forms_listagem.py`, `apps/pca/resumo_uo.py`,
`apps/catalogo/models.py::DominioBase.Meta.ordering`).

`core/db.py` também expõe `quantizar_soma()` — corrige o ruído de ponto
flutuante que o `SUM()` nativo do SQLite introduz sobre colunas
`DecimalField` (o PostgreSQL soma como `NUMERIC` exato); todo `.aggregate()`/
`.annotate()` com `Sum()` sobre um campo monetário passa por essa função antes
de chegar à tela.
