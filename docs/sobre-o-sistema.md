# Sobre o sistema e o autor

## Quem fez

O PCA CFC foi criado por **Antônio Rodrigues de Sousa Júnior**, o **Toninho**, empregado do
Conselho Federal de Contabilidade. Toninho é hoje **pregoeiro do CFC**; antes, foi por oito
anos supervisor do extinto setor de Patrimônio.

É **contador**, especialista em **terceirização de mão de obra** e em **desenvolvimento de
sistemas com Python**, e está concluindo o **MBA em Data Science and Analytics pela USP/Esalq**.

## Por que o sistema existe

O acompanhamento do Plano de Contratações Anual era feito em planilha, como na maioria dos
órgãos — uma aba que ganhava uma coluna de texto livre a cada reunião mensal. A construção
do sistema foi solicitada por **Eunice, Gerente Executiva da GEX-LIC**, chefia de Toninho,
para conduzir a reunião mensal de acompanhamento inteiramente dentro de uma ferramenta:
editando no ato, com dashboards, kanban e histórico, e dando ao presidente e ao corpo
funcional uma visão de leitura do andamento.

## Como foi construído

A arquitetura é Django + SQLite, com a identidade visual do Design System do governo
federal (gov.br/ds), e roda em contêineres Docker.

**O assistente** (este chat) é um agente construído no próprio sistema: consulta os dados do
PCA por ferramentas sobre o banco, com as mesmas permissões de quem pergunta, e busca em
texto livre (acompanhamentos, documentos do SEI e esta documentação) por embeddings
guardados num índice SQLite separado. O modelo de linguagem é fornecido por API externa; o
assistente não informa qual modelo usa.

## Licença

O **código** do PCA CFC é software livre sob licença **AGPL-3.0**, com Toninho como titular dos
direitos autorais (Copyright © 2026 Antônio Rodrigues de Sousa Júnior). Os **dados** do PCA
— processos, contratos, acompanhamentos — pertencem ao CFC e **não** estão cobertos pela
licença.

## Contato

Melhorias são bem-vindas. Para sugerir uma ou reportar um erro, mande um **WhatsApp para
(61) 98209-8525**. E-mails: institucional **antonio.junior@cfc.org.br** · pessoal
**toniaum@gmail.com**.
