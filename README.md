# Sistema de Acompanhamento do Plano de Contratações Anual

![Licença](https://img.shields.io/badge/licença-MIT-blue)
![Versão](https://img.shields.io/badge/versão-0.1.0-informational)

## O que é

Aplicação web (PWA) para órgãos públicos sujeitos à Lei 14.133/2021 acompanharem o Plano de
Contratações Anual (PCA) — do planejamento de cada item, pelo funil processual interno, até a
execução contratual (modalidade, contrato, fornecedor, vigência, valor contratado) e a publicação
nos canais de transparência do órgão.

Ela substitui a planilha de acompanhamento que a maioria dos órgãos usa hoje — uma aba que cresce
uma coluna de texto livre a cada reunião mensal — por dashboards, kanban e tabela editável. A
equipe conduz a reunião mensal de acompanhamento inteiramente dentro do sistema, editando no ato,
sem abrir planilha nenhuma.

## Principais funcionalidades

- Dashboard analítico com KPIs clicáveis, gráficos (ECharts) e filtros globais.
- Tabela de leitura com busca, filtros, ordenação e paginação server-side, com edição inline para
  o perfil `editor`.
- Detalhe do processo com timeline de acompanhamento e cadeia de prazos.
- Bloco de execução contratual (modalidade, contrato, fornecedor, vigência, valor contratado) e
  marcos de publicação.
- Export do resultado filtrado em CSV e XLSX.
- Import de planilha para virada de exercício, com relatório de conferência.
- Histórico automático de alterações (auditoria) e autenticação por perfil.

## Stack

Python 3.12 · Django 5.2 LTS · PostgreSQL 17 · Django Templates + HTMX + ECharts, no padrão de
componentes DSGov 3.7 (Padrão Digital de Governo) · Gunicorn · Docker Compose.

Sem API REST/GraphQL formal, sem fila assíncrona (Celery/Redis) — server-rendered de ponta a
ponta. Ver [Visão geral](docs/visao-geral.md) para a lista completa de dependências e rotas.

## Requisitos

- Docker e Docker Compose.
- Linux containers (em Windows Server, via Hyper-V ou WSL 2 — não containers Windows).
- VM de referência: 2 vCPU / 4 GB de RAM / 40 GB de disco (folga confortável para o volume de
  dados típico de um PCA).

## Instalação rápida

```sh
git clone https://github.com/ToNiauM/sistema-pca.git
cd sistema-pca
cp .env.example .env
# edite .env: defina SECRET_KEY, POSTGRES_PASSWORD e DATABASE_URL
docker volume create pca_pgdata
docker compose up -d
docker compose exec web python manage.py createsuperuser
```

Acesse `http://127.0.0.1:8000`.

Para o runbook completo de instalação numa VM limpa (detecção de distro, Nginx, TLS, backup), veja
[`ops/MIGRACAO.md`](ops/MIGRACAO.md).

## Documentação completa

A documentação técnica completa (arquitetura, modelo de dados, fluxos de negócio, configuração,
deployment, operação, segurança) está em [`docs/`](docs/index.md) e é publicada via GitHub Pages
em **<https://toniaum.github.io/sistema-pca/>**.

<!-- O link do GitHub Pages só fica acessível depois que o repositório se torna público
     (Settings → Pages → Source: GitHub Actions) — até lá, use docs/index.md diretamente. -->

## Licença

Distribuído sob a licença MIT. Veja [`LICENSE`](LICENSE) — © 2026 Antônio Rodrigues de Sousa
Júnior.

## Status e versionamento

Versão atual: **0.1.0** (primeira publicação pública). Veja [`CHANGELOG.md`](CHANGELOG.md) para o
histórico de mudanças.
