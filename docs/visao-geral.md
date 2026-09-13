# Visão geral

## Propósito

O Sistema PCA substitui uma planilha de acompanhamento por uma aplicação web: dashboards,
tabela editável e histórico auditável para a equipe responsável pelo Plano de Contratações Anual,
e uma visão de leitura do andamento para a gestão e o corpo funcional. O item é acompanhado por
todo o percurso — do planejamento, pelo funil processual interno, até a execução contratual e a
publicação nos canais de transparência do órgão.

## Funcionalidades principais

Cada linha abaixo corresponde a uma rota nomeada de `apps/pca/urls.py` (30 rotas) ou
`core/urls.py` (8 rotas) — 45 rotas ao todo, somando as 7 de `config/urls.py` (admin, healthz,
includes e o redirect histórico `raiz`).

| Funcionalidade | Rota (namespace:nome) |
|---|---|
| Painel/dashboard (Início) | `core:inicio` |
| Tabela de processos (busca/filtros/paginação via HTMX) | `pca:tabela` |
| Busca global | `pca:busca` |
| Calendário de prazos | `pca:calendario` |
| Resumo por unidade organizacional | `pca:resumo_uo` |
| Análises (gráficos ECharts) | `pca:analise` |
| Relatório de movimentação (histórico entre duas datas) | `pca:relatorio_movimentacao` |
| Criar/editar processo | `pca:criar_processo` / `pca:editar_processo` |
| Detalhe do processo (ficha) | `pca:detalhe_processo` |
| Alterar situação | `pca:transicao_processo` |
| Registrar acompanhamento (modal) | `pca:acompanhamento_modal` |
| Reuniões de acompanhamento | `pca:reuniao_listagem` / `pca:criar_reuniao` |
| Exportação (CSV/XLSX, tabela e resumo por UO) | `pca:exportar`, `pca:exportar_csv`, `pca:exportar_xlsx`, `pca:exportar_resumo_uo_xlsx` |
| Virada de exercício (wizard de 3 etapas) | `pca:virada`, `pca:virada_ajustar`, `pca:virada_revisar`, `pca:virada_confirmar` e rotas correlatas |
| Gestão de exercícios | `pca:gerenciar_exercicios`, `pca:encerrar` |
| Autenticação, perfil, troca de senha | `core:login`, `core:logout`, `core:perfil`, `core:trocar_senha` |
| PWA (manifest, service worker) | `core:manifest`, `core:service_worker` |
| Health check | `healthz` (`config/urls.py`) |
| Django Admin | `admin/` (`config/urls.py`) |

**Não existe API REST/GraphQL formal** — nenhuma dependência DRF está instalada
(`requirements.txt`), nenhuma rota `api/` existe. Toda interação é HTML/HTMX server-rendered.

## Stack tecnológica

Python 3.12+ · Django 5.2 LTS (`Django==5.2.16`) · PostgreSQL 17 · Django Templates + HTMX 2.0.10
+ ECharts, no padrão da skill `dsgov` (`.claude/skills/dsgov`, DSGov 3.7.0 core puro — sem
`@govbr-ds/webcomponents`, sem Stencil, sem Shadow DOM, sem Alpine.js) · Gunicorn (`gunicorn==26.0.0`,
worker-class `gthread`) · Docker Compose.

Dependências Python completas (`requirements.txt`, 12 linhas): `Django==5.2.16`,
`psycopg[binary]==3.3.4`, `django-environ==0.14.0`, `django-simple-history==3.13.0`,
`django-axes==8.3.1`, `django-htmx==1.28.0`, `argon2-cffi==25.1.0`, `whitenoise==6.12.0`,
`gunicorn==26.0.0`, `openpyxl==3.1.5`, `django-ipware==7.0.1`, `freezegun==1.5.5`.

Sem Redis, sem Celery, sem fila de tarefas assíncrona — confirmado por
`grep -ri redis\|celery requirements.txt compose.yml config/settings/*.py`, retorno vazio. Toda
agregação usa o ORM (`annotate`/`aggregate`), nunca Python puro; exportações são síncronas.

## Organização geral

Monólito modular: `apps/` concentra o domínio (`apps/pca`, `apps/catalogo`), `core/` e `config/`
são boilerplate replicável (autenticação, casca visual, PWA, Admin, histórico). Ver
[Estrutura do projeto](estrutura.md) para o detalhamento por diretório e
[Arquitetura](arquitetura.md) para a topologia de contêineres.

**Fontes verificadas:** `apps/pca/urls.py`, `core/urls.py`, `config/urls.py`, `requirements.txt`,
`CLAUDE.md` (seção Technology Stack).
