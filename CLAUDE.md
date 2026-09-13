## Project

**Sistema de Acompanhamento do Plano de Contratações Anual**

Aplicação web PWA para acompanhar o Plano de Contratações Anual (PCA) de um órgão público sujeito
à Lei 14.133/2021 — dashboards, kanban e tabela editável no lugar de uma planilha que cresce uma
coluna de texto livre a cada reunião de acompanhamento. Dá à equipe responsável pelo PCA uma
ferramenta de edição no ato, e ao corpo funcional/gestão uma visão de leitura do andamento.

O sistema acompanha o item por todo o percurso: do planejamento no PCA, pelo funil processual
interno, até a execução contratual — modalidade, contrato, fornecedor, vigência, valor contratado
— e a publicação nos canais de transparência do órgão (ex.: Dados Abertos). O vocabulário de
domínio (siglas de setores internos, sistemas de publicação) é o do órgão de origem deste
software; adapte-o ao seu — ver `docs/glossario.md` para o significado de cada termo e como
substituí-lo pelos equivalentes da sua instituição.

**Core Value:** A equipe conduz a reunião de acompanhamento inteiramente dentro do sistema —
editando no ato, sem abrir planilha.

### Constraints

- **Tech stack**: Python 3.12+ · Django 5.2 LTS · PostgreSQL 17 · Django Templates + HTMX 2.0.10 +
  ECharts, no padrão da skill `dsgov` (`.claude/skills/dsgov`, DSGov 3.7.0 core puro — ver
  `## Technology Stack`) · Gunicorn · Docker Compose. Sem integrações obrigatórias: o sistema é
  server-rendered, CRUD-pesado, com auth por perfil e import de planilha — o núcleo do Django, sem
  API REST/GraphQL formal.
- **Portabilidade (invariante)**: nenhuma dependência do host de origem. Toda configuração via
  variáveis de ambiente (`django-environ`). Migração completa = restaurar dump + `.env` +
  `docker compose up -d` + `migrate` + proxy/DNS. Qualquer passo adicional descoberto durante o
  desenvolvimento é acoplamento indevido e deve ser eliminado.
- **Desempenho**: dashboard abaixo de 2 s com até 500 processos. Agregações via ORM
  (`annotate`/`aggregate`), nunca em Python. Tabela paginada server-side. As propriedades derivadas
  de histórico (nº de reuniões, compromissos assumidos, prazo vigente, situação atual) não podem
  virar consulta por linha na listagem.
- **Localização**: `pt-br`, `America/Sao_Paulo`, `USE_TZ = True`, datas `DD/MM/AAAA`, moeda `R$` em
  formato pt-BR. Mês previsto é armazenado como inteiro 1–12, não como texto abreviado, para que
  ordene corretamente.
- **Segurança**: Argon2 no topo de `PASSWORD_HASHERS`; `django-axes` no login; cookies
  `Secure`/`HttpOnly`/`SameSite=Lax`; HSTS e `SECURE_PROXY_SSL_HEADER` atrás do proxy; `DEBUG =
  False` e `ALLOWED_HOSTS` restrito em produção; app em `127.0.0.1`, nunca exposto diretamente.
- **CSRF do HTMX via `htmx:configRequest`, não `hx-headers`**: um atributo `hx-headers` estático
  congela o token — o Django roda `rotate_token()` no login e no logout, e `hx-boost` não
  reescreve `<html>`/`<body>`. O token tem de ser lido do cookie a cada requisição. Consequência:
  `CSRF_COOKIE_HTTPONLY` precisa continuar `False`, ou toda escrita passa a falhar.
- **Estrutura de repositório**: `config/` + `core/` + `compose.yml` + `Dockerfile` + `ops/` são
  boilerplate replicável; o domínio vive apenas em `apps/`. Monólito modular — cada app Django é
  um domínio autocontido. Auth, admin, histórico, layout e infra pagos uma vez.
- **LGPD**: dados pessoais restritos a nome e e-mail de usuários, mais nomes eventualmente citados
  em observações. O bloco de execução contratual acrescenta CNPJ e razão social — pessoa jurídica,
  não dado pessoal sensível. Acesso 100% autenticado; superusuário edita e apaga qualquer registro
  pelo Django Admin, inclusive linhas de histórico — a trilha `simple_history` continua automática
  nas telas do sistema, mas deixa de ser imutável no Admin.

## Technology Stack

Django 5.2 + PostgreSQL 17 + HTMX 2.0.10 + ECharts, server-rendered, no padrão da **skill `dsgov`**
(`.claude/skills/dsgov`, DSGov 3.7.0 **core puro** — sem `@govbr-ds/webcomponents`, sem Stencil,
sem Shadow DOM, sem Alpine.js). A skill é a fonte da verdade; qualquer dúvida de padrão se resolve
lendo `.claude/skills/dsgov/SKILL.md` e `references/`, nunca escrevendo HTML de cabeça.

**Vendor congelado, versionado no git** (`core/static/dsgov/vendor/**`, copiado uma vez pelo
`aplicar.py`/`novo_projeto.py` da skill — sem estágio Node no `Dockerfile`, sem `npm` no build):
`@govbr-ds/core@3.7.0` (`core.min.css`/`core.min.js`), Font Awesome Free 5.15.4, Rawline
(cdngovbr-ds) + Raleway (Google Fonts, variável), htmx 2.0.10, Apache ECharts 5.5.0. `core/static/
dsgov/css/dsgov.css` (68 linhas) e `fontes.css` são congelados pela skill — hash comparado a cada
`verificar.py` (regra CSS); nunca editados neste repositório.

**Lista fixa de CSS/JS** (`core/templates/base.html`, ordem imutável): CSS `fontes.css` →
`core.min.css` → `all.min.css` (Font Awesome) → `dsgov.css`; JS `core.min.js` → `htmx.min.js` →
`dsgov.js` → (`echarts.min.js` → `echarts-dsgov.js`, só nas páginas com gráfico, `{% block
scripts %}`). Nenhum outro CSS/JS é permitido em template — `verificar.py` (regra CDN) rejeita
qualquer arquivo fora dessa lista.

**Guarda único:**
```
python3 ops/dsgov/verificar.py . --avisos-como-erros
```
`ops/dsgov/verificar.py` é a cópia versionada do verificador da skill (mesmas 10 regras, só
`CORE_CSS`/`FA_CSS`/`SKILL_CSS_DIR` reapontados para `core/static/dsgov/**` deste repositório —
invariante de portabilidade: a suíte nunca depende de nada fora do próprio repositório para
passar). `test_dsgov_conformidade.py` roda esta cópia sempre; se a skill original (com
`assets/vendor/`) também estiver instalada em outro caminho no host, um segundo teste exige que as
duas saídas concordem byte a byte (ver `.claude/skills/dsgov/VENDOR-NOTA.md`).

`settings.DSGOV` (identidade visual/textos da casca: `ORGAO`, `ORGAO_SIGLA`, `SISTEMA`,
`SISTEMA_SUBTITULO`, `LOGO`, `LINKS_ACESSO_RAPIDO`, `RODAPE_TEXTO`, `ITENS_POR_PAGINA`,
`OPCOES_POR_PAGINA` — configurável por variáveis de ambiente `DSGOV_*`, ver `.env.example`),
`core/menu.py::itens()` (menu lateral, alimentado por `apps.pca.navegacao.DESTINOS_OPERACIONAIS`)
e `trilha` (lista de tuplas `(rótulo, url|None)` no contexto de cada view — o último item, com
`url=None`, é a página corrente) são os três pontos de extensão que a skill espera de um projeto
concreto — ver `.claude/skills/dsgov/references/django.md`/`references/layout.md`.

## Conventions

### 1. Contrato dos componentes

O contrato de `@govbr-ds/webcomponents` (Shadow DOM, eventos Stencil em camelCase,
`br-menu`/`br-header`/`br-pagination` como Custom Elements) não existe neste repositório — zero
`<br-*>` Custom Element, zero Shadow DOM, zero Alpine.js. O HTML canônico de cada componente do DS
(CSS-only, classes puras sobre elementos nativos) vive em `.claude/skills/dsgov/
references/componentes/{table,select,input,textarea,checkbox,radio,tag,pagination,message,card,
accordion,tab,wizard,menu,header,footer,breadcrumb,signin,skiplink,button,list,item,divider,
tooltip,scrim}.md` — copiado e adaptado só em texto/dados, nunca escrito de cabeça. `dsgov.js`
(o único JS de comportamento próprio, congelado pela skill) inicializa `br-select`/`br-modal`/
`br-menu`/dropdowns/paginação a partir de HTML puro — nenhum componente precisa de `x-data`.

### 2. Regras de escrita

Todo elemento com equivalente no DS usa a classe `br-*` (do `core.min.css`, HTML canônico dos
`references/componentes/*.md` acima); nativo só onde a skill explicitamente admite (`<input
type="date">`/`<input type="file">` sem wrapper equivalente, JS inline em `relatorio.md`
— `onclick="window.print()"`). CSS próprio é PROIBIDO fora dos dois arquivos congelados da skill
(`core/static/dsgov/css/dsgov.css`/`fontes.css`, hash comparado por `verificar.py`); cor SÓ por
`var(--token)` do `core.min.css` (zero hex próprio, exceto `theme-color`/`#1351b4`, única exceção
que a própria skill admite). Comentário de template multilinha é sempre `{% comment %}` — o
`{# #}` do Django é de UMA linha só; usá-lo em várias linhas vaza o texto para dentro do
`<body>` renderizado (guarda: `test_templates_comentarios`). CSRF por `htmx:configRequest` (ver
`### Constraints`), nunca `hx-headers` estático — `dsgov.js` já implementa esse contrato.
`pca-static-vN` (nome do cache do service worker, `core/views.py:service_worker_view`) sobe a
cada mudança de estático. Escrita sempre por POST-redirect-GET com `django.contrib.messages`
(`HtmxRedirectMiddleware` converte em `HX-Redirect` quando é HTMX); verificação sempre por POST
real com `django.test.Client` (`force_login`, `HTTP_X_FORWARDED_PROTO="https"`, `HTTP_HOST`
permitido), nunca só grep de template.

### 3. Testes-guarda e como rodar

`test_dsgov_conformidade` (guarda único — roda `ops/dsgov/verificar.py --avisos-como-erros --json`
sobre o repositório inteiro e exige zero erros), `test_estrutura_paginas` (por página: exatamente
um `<h1>`, no máximo um `br-button primary`, `role="img"`+`aria-label` em todo `[data-grafico]`),
`test_templates_comentarios` (a regra do `{# #}` de uma linha). Comando do verificador, direto
(fora da suíte, para depuração rápida de um achado):
```
python3 ops/dsgov/verificar.py . --avisos-como-erros
```

Ambiente de desenvolvimento:
```
docker compose up -d
docker compose exec web python manage.py test
python3 ops/dsgov/verificar.py . --avisos-como-erros
```
Rebuilde a imagem (`docker compose build web && docker compose up -d web`) só quando mudar
`Dockerfile`, `requirements.txt`, `entrypoint.sh` ou `core/static/dsgov/**` — não há estágio Node
no build (o vendor é `COPY . .` normal). Ver `docs/desenvolvimento-local.md` para o passo a passo
completo, incluindo `createsuperuser` e a fixture de exemplo.

## Architecture

Monólito modular. `config/` + `core/` + `compose.yml` + `Dockerfile` + `ops/` = boilerplate
replicável, pago uma vez: auth por e-mail com Argon2/axes, casca da skill dsgov, PWA/service
worker, Admin, histórico, export, import de planilha, segurança verificada por teste (ver
`### Constraints`). Domínio SÓ em `apps/` (`apps/pca`, `apps/catalogo`...) — cada app Django é um
domínio autocontido. Agregação sempre no ORM (`annotate`/`aggregate`), nunca linha a linha em
Python; tabela paginada server-side (ver `### Constraints`, Desempenho).

**Casca:** toda página estende `core/templates/base.html` (byte-idêntico ao da skill, nunca
editado — "mudou `base.html` ou um partial de `dsgov/`" é sinal de que a tela saiu do padrão).
`base.html` inclui, nesta ordem fixa, `core/templates/dsgov/_skiplink.html` → `_header.html` →
`_menu.html` → `_breadcrumb.html` → `_mensagens.html` → `{% block conteudo %}` → `_footer.html`
(todos congelados, nunca editados). `_menu.html` lê `core/menu.py::itens(request)`;
`_breadcrumb.html` lê `trilha` (lista de tuplas `(rótulo, url|None)`) do contexto da view. HTMX é
a exceção, não a regra: só a tela Processos (`pca:tabela`, busca/filtros/paginação, `hx-get` para
`#listagem` + `hx-push-url`, resposta = `pca/_listagem.html` sem nenhum OOB) e o modal "Registrar
acompanhamento" (`_acompanhamento_modal.html`, único `br-modal` do sistema) usam HTMX;
Calendário/Análises/Resumo por unidade/Início (dashboard) recarregam a página inteira a cada
troca de filtro/período. Sem `hx-swap-oob` em lugar nenhum do sistema.

## Reaproveitamento do core

A skill `dsgov` já faz isso sozinha. Para um sistema novo com a mesma cara (exige a skill original
completa, COM `assets/vendor/`, instalada fora deste repositório — ver
`.claude/skills/dsgov/VENDOR-NOTA.md`):

```
python3 <skill-dsgov-completa>/scripts/novo_projeto.py <pasta-destino> \
  --sistema "Nome do Sistema" --orgao "Nome do Órgão" --sigla SIGLA [--subtitulo "..."] \
  [--yaml sistema.yaml]
```

Copia `config/`+`core/`+`compose.yml`+`Dockerfile` (`assets/projeto` da skill), vendoriza
`core/static/dsgov/vendor/**` (os mesmos ativos congelados usados por este projeto), gera `.env`
com `SECRET_KEY` aleatória e cria as migrações do `core`. Determinístico — o mesmo comando produz
sempre a mesma estrutura. Nenhuma fase de reskin, nenhuma pesquisa de componente (o contrato já
está fechado nos `references/` da skill), nenhuma vendorização manual, nenhum plano de
segurança/PWA (já pago no boilerplate e replicado pelo `novo_projeto.py`).

**O que muda por sistema:** `apps/` (o domínio novo, escrito seguindo
`.claude/skills/dsgov/references/django.md`), `settings.DSGOV` (`SISTEMA`/`SISTEMA_SUBTITULO`/
`LOGO`/`LINKS_ACESSO_RAPIDO`/`RODAPE_TEXTO`, configuráveis por `.env`), `manifest`/`theme-color`,
logo (`core/static/img/`), `ALLOWED_HOSTS`/`.env`, itens de `core/menu.py::itens()`.

## Documentação completa

Este arquivo cobre convenções de código para quem desenvolve. Para arquitetura, modelo de dados,
fluxos de negócio, configuração, deployment, operação, segurança e glossário do vocabulário de
domínio, veja `docs/` (publicado via GitHub Pages) — comece por `docs/index.md`.
