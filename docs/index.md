# Sistema de Acompanhamento do Plano de Contratações Anual

O **Sistema PCA** é uma aplicação web (PWA) para acompanhar o Plano de Contratações Anual (PCA)
de um órgão público sujeito à Lei 14.133/2021 — do planejamento de cada item, pelo funil
processual interno, até a execução contratual (modalidade, contrato, fornecedor, vigência, valor
contratado) e a publicação nos canais de transparência do órgão. É server-rendered (Django
Templates + HTMX), CRUD-pesado, com autenticação por perfil e import de planilha — sem API REST
formal e sem fila assíncrona (ver [Arquitetura](arquitetura.md)).

O vocabulário de domínio herdado do órgão onde o sistema nasceu (siglas de setores internos,
sistemas de publicação) permanece intacto no código — trocar de órgão é questão de dado
(catálogo de unidades organizacionais e demais tabelas de vocabulário), não de código. Ver
[Glossário](glossario.md).

## Por onde começar

<div class="grid cards" markdown>

-   :material-compass-outline:{ .lg .middle } **Visão geral**

    ---

    O que o sistema faz e com que tecnologia.

    [:octicons-arrow-right-24: Abrir](visao-geral.md)

-   :material-laptop:{ .lg .middle } **Desenvolvimento local**

    ---

    Subir o projeto localmente com Docker Compose.

    [:octicons-arrow-right-24: Abrir](desenvolvimento-local.md)

-   :material-sitemap-outline:{ .lg .middle } **Arquitetura**

    ---

    Topologia de contêineres e processos.

    [:octicons-arrow-right-24: Abrir](arquitetura.md)

-   :material-database-outline:{ .lg .middle } **Modelo de dados**

    ---

    Models e diagrama de entidades.

    [:octicons-arrow-right-24: Abrir](modelo-de-dados.md)

-   :material-rocket-launch-outline:{ .lg .middle } **Deployment**

    ---

    Publicar numa VM nova.

    [:octicons-arrow-right-24: Abrir](deployment.md)

-   :material-cog-outline:{ .lg .middle } **Operação**

    ---

    Logs, backup e restore em produção.

    [:octicons-arrow-right-24: Abrir](operacao.md)

-   :material-tune-variant:{ .lg .middle } **Configuração**

    ---

    Toda variável de ambiente lida pelo sistema.

    [:octicons-arrow-right-24: Abrir](configuracao.md)

-   :material-source-pull:{ .lg .middle } **Contribuição**

    ---

    Como contribuir com código ou documentação.

    [:octicons-arrow-right-24: Abrir](contribuicao.md)

</div>

!!! info "Versão"
    Esta documentação descreve a versão **0.1.0**. Veja o histórico completo de mudanças no
    [CHANGELOG](https://github.com/ToNiauM/sistema-pca/blob/main/CHANGELOG.md).

## Convenções de código

Este site cobre arquitetura, dados, operação e domínio. Para as convenções de código do dia a dia
(padrão de componentes DSGov, regras de escrita, testes-guarda), veja `CLAUDE.md` na raiz do
repositório — ele é a fonte da verdade para quem desenvolve.
