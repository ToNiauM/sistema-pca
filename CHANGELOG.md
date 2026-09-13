# Changelog

Todas as mudanças notáveis deste projeto são documentadas neste arquivo.

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/), e este projeto adere
ao [Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [0.1.0] - 2026-09-12

Primeira publicação pública. Esta entrada descreve o sistema tal como publicado — não é um
histórico de desenvolvimento interno (o projeto foi construído ao longo de várias fases num
repositório de origem privado, cujo histórico de commits não foi trazido para este repositório).

### Adicionado

- Dashboard analítico com KPIs clicáveis, gráficos (ECharts) e filtros globais.
- Tabela de leitura com busca, filtros, ordenação, paginação server-side e edição inline.
- Detalhe do processo com timeline de acompanhamento e cadeia de prazos.
- Bloco de execução contratual (modalidade, contrato, fornecedor, vigência, valor contratado) e
  marcos de publicação.
- Export do resultado filtrado em CSV e XLSX.
- Import de planilha para virada de exercício, com relatório de conferência.
- Autenticação por perfil (Argon2, `django-axes`), histórico automático de alterações.
- PWA instalável (manifest, service worker).
- Casca visual no padrão de componentes DSGov 3.7 (Padrão Digital de Governo).
- Documentação técnica completa em `docs/` (MkDocs Material), publicada via GitHub Pages.
- Site de documentação (MkDocs Material) com navegação por seções, modo escuro e página inicial com cartões.
- CI (`ci.yml`) com PostgreSQL 17, suíte de testes e verificador de conformidade DSGov.

[0.1.0]: https://github.com/ToNiauM/sistema-pca/releases/tag/v0.1.0
