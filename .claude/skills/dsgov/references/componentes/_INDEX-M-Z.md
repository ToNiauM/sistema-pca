# Índice de componentes M–Z — Design System gov.br (@govbr-ds/core 3.7.0)

Cada arquivo segue a mesma estrutura: **Quando usar / quando não usar · HTML canônico · Variantes e modificadores · Estados e acessibilidade · Erros comuns · Fonte**. Os utilitários de layout, espaçamento, tipografia e cores (que não são componentes) estão em [`../utilitarios.md`](../utilitarios.md).

| Componente | Finalidade | Arquivo |
| --- | --- | --- |
| **br-modal** | Janela sobreposta à página (com scrim) que interrompe o fluxo para alertas, confirmações, termos ou entrada de dados contextual. | [modal.md](modal.md) |
| **br-notification** | Painel de notificações do usuário (aberto a partir do header/avatar), com cabeçalho, abas e lista de itens dispensáveis. | [notification.md](notification.md) |
| **br-pagination** | Navegação entre páginas de uma listagem, na forma completa (itens por página + "de X") ou compacta. | [pagination.md](pagination.md) |
| **br-radio** | Botão de opção para escolha única dentro de um grupo, com estados válido/inválido/desabilitado. | [radio.md](radio.md) |
| **br-scrim** | Camada de sobreposição (foco ou legibilidade) que escurece o fundo e hospeda a modal ou destaca conteúdo. | [scrim.md](scrim.md) |
| **br-select** | Lista suspensa de seleção única ou múltipla (`multiple`), com busca embutida gerada pelo JS. | [select.md](select.md) |
| **br-sign-in** | Botão de entrada/autenticação (gov.br) com variantes primária/secundária, circular, bloco e invertida. | [signin.md](signin.md) |
| **br-skiplink** | Links de "pular para" (conteúdo, menu, rodapé) visíveis somente ao receber foco, para acessibilidade por teclado. | [skiplink.md](skiplink.md) |
| **br-step** | Indicador de etapas de um processo (horizontal ou vertical) com rótulos, ícones e alertas por etapa. | [step.md](step.md) |
| **br-switch** | Interruptor liga/desliga para configurações com efeito imediato, em três densidades e com rótulos opcionais. | [switch.md](switch.md) |
| **br-tab** | Abas que alternam painéis de conteúdo no mesmo contexto, com ícones, contadores e densidades. | [tab.md](tab.md) |
| **br-table** | Tabela de dados com barra superior (título, busca, ações), seleção de linhas, colapso responsivo, densidade e paginação no rodapé. | [table.md](table.md) |
| **br-tag** | Etiqueta compacta para categorizar, contar, sinalizar status ou permitir seleção/remoção rápida. | [tag.md](tag.md) |
| **br-textarea** | Campo de texto multilinha com rótulo, contador de caracteres e estados de validação. | [textarea.md](textarea.md) |
| **br-tooltip** | Dica contextual flutuante (info/success/warning/error) posicionada via Popper, acionada por hover/focus/click. | [tooltip.md](tooltip.md) |
| **br-upload** | Área de envio de arquivos (único ou múltiplo) com lista de arquivos, remoção e feedback de status. | [upload.md](upload.md) |
| **br-wizard** | Assistente passo a passo (horizontal ou vertical) que combina indicador de progresso e painéis de formulário com botões Voltar/Avançar/Concluir. | [wizard.md](wizard.md) |

Fontes gerais: https://www.gov.br/ds/components/<nome>?tab=designer · https://www.gov.br/ds/components/<nome>?tab=desenvolvedor · exemplos oficiais locais em `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/<nome>/examples.html`.
