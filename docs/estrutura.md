# Estrutura do projeto

Monólito modular: `config/` + `core/` + `compose.yml` + `Dockerfile` + `ops/` são boilerplate
replicável (pago uma vez); o domínio do PCA vive inteiramente em `apps/`. Nenhuma dessas
responsabilidades se mistura — ver `CLAUDE.md` § Constraints, "Estrutura de repositório".

| Diretório | Responsabilidade |
|---|---|
| `apps/pca/` | Domínio principal: models (`Processo`, `Acompanhamento`, `ProcessoSEI`, `Reuniao`...), views, regras de situação, import/export, navegação, colunas, filtros, testes (56 arquivos) |
| `apps/catalogo/` | Vocabulário de domínio: `Exercicio` e as 8 tabelas de catálogo (`Unidade`, `Categoria`, `Tipo`, `GrauPrioridade`, `Classificacao`, `Modalidade`, `InstrumentoContratual`, `SituacaoNormalizada`) |
| `core/` | Boilerplate replicável: usuário customizado (`Usuario`, e-mail como login), autenticação, casca visual (templates `dsgov/`), Admin, PWA (manifest/service worker), middlewares, testes-guarda |
| `config/` | `settings/{base,dev,prod}.py`, `urls.py`, `wsgi.py` — nenhum código de domínio |
| `ops/` | `ops/dsgov/verificar.py` (verificador de conformidade DSGov versionado), `ops/backup/` (scripts de backup/restore/retenção), `ops/nginx/pca.conf` (proxy de referência), `ops/MIGRACAO.md` (runbook de deployment), `ops/gerar_icones_pwa.py`, `ops/verificacao/` (harness Playwright genérico) |
| `.claude/skills/dsgov/` | Cópia da skill DSGov (sem o vendor de ~4 MB, já presente em `core/static/dsgov/vendor/`) — `SKILL.md`, `references/` (contrato de cada componente), `scripts/verificar.py`/`novo_projeto.py` |
| `docs/` | Esta documentação técnica (MkDocs Material) |

Diretórios que não fazem parte do domínio nem do boilerplate replicável, mas existem por
necessidade operacional:

| Diretório | Papel |
|---|---|
| `templates/` | Mount point vazio (`compose.yml` monta `./templates:/app/templates:ro`) — extensão de template sem rebuild de imagem, se necessário |
| `staticfiles/` | Recriado em build-time pelo `Dockerfile` (`collectstatic`); não existe no repositório |

Este capítulo lista responsabilidades, não uma árvore de arquivos completa — para o detalhamento
de cada app, veja [Modelo de dados](modelo-de-dados.md) e [Fluxos de negócio](fluxos-de-negocio.md).

**Fontes verificadas:** `CLAUDE.md` (seções Constraints e Architecture), `compose.yml`,
`Dockerfile`, listagem de `apps/pca/tests/`, `.claude/skills/dsgov/VENDOR-NOTA.md`.
