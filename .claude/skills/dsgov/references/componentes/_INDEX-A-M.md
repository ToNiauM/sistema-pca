# Índice de componentes (A–M) — Design System gov.br, @govbr-ds/core 3.7.0

Cada arquivo traz: quando usar, HTML canônico copiável, tabela de modificadores verificados no SCSS/CSS, estados/ARIA/`data-*` esperados pelo JS (e se o `core-init.js` inicializa automaticamente) e erros comuns.

Observações gerais válidas para todos:
- A documentação em https://www.gov.br/ds/ é uma SPA Angular; o conteúdo da aba *designer* foi lido no markdown bruto em `https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/<name>/<name>.md`. A aba *desenvolvedor* não tem fonte estática; o markup canônico vem de `dist/components/<name>/examples.html` do pacote local.
- `dist/core-init.js` auto-inicializa **todos** os componentes com JS (`new core.BRXxx('br-xxx', el)`); se você carregar apenas `dist/core.js`, instancie manualmente. Componentes sem JS: button, divider, loading, magic-button.
- Ícones: Font Awesome 5 (`fas fa-*`, `fab fa-*`) com `aria-hidden="true"`.

| componente | propósito | arquivo |
| --- | --- | --- |
| accordion | Seções empilháveis que expandem/recolhem para reduzir densidade de conteúdo (atributos `single`, `negative`). | [accordion.md](./accordion.md) |
| avatar | Representação circular do usuário (ícone, foto ou letra) em 3 densidades, opcionalmente acionador de dropdown. | [avatar.md](./avatar.md) |
| breadcrumb | Trilha de navegação hierárquica com botão Home, truncamento automático e dropdown dos níveis intermediários. | [breadcrumb.md](./breadcrumb.md) |
| button | Botão de ação com ênfases primária/secundária/terciária, formatos padrão/circular/bloco, densidades e estados (sem JS). | [button.md](./button.md) |
| card | Superfície que agrupa conteúdo coeso em header/content/footer, com hover, expansão (collapse), desabilitado e altura fixa. | [card.md](./card.md) |
| checkbox | Seleção de uma ou mais opções, com validação, rótulo oculto e estado intermediário sincronizado (`data-parent`/`data-child`). | [checkbox.md](./checkbox.md) |
| cookiebar | Barra/modal de consentimento de cookies (LGPD) renderizada pelo JS a partir de JSON (resumo). | [cookiebar.md](./cookiebar.md) |
| datetimepicker | Campo de data, hora ou data+hora (e intervalo) baseado em flatpickr, com máscara e calendário estilizado. | [datetimepicker.md](./datetimepicker.md) |
| divider | Linha separadora horizontal/vertical, tracejada, em 3 espessuras, com variante para fundo escuro (sem JS). | [divider.md](./divider.md) |
| footer | Rodapé institucional com logo, mapa do site em colunas (acordeão no mobile), redes sociais, assinaturas e licença. | [footer.md](./footer.md) |
| header | Cabeçalho do site/sistema com logo, assinatura, título, acesso rápido, funcionalidades, busca, login e botão de menu; tipos padrão/compacto e `data-sticky`. | [header.md](./header.md) |
| input | Campo de texto com rótulo, ícone, botão interno, densidades, destaque, estados de validação e alternância de senha. | [input.md](./input.md) |
| item | Unidade de listas/menus (div, link ou botão) com grid interna, seleção via checkbox/radio e estados selected/active. | [item.md](./item.md) |
| list | Lista vertical/horizontal de `br-item` com header, dividers, densidades e agrupamento por rótulo, separador ou expansão. | [list.md](./list.md) |
| loading | Indicador de carregamento indeterminado (24/44px) ou determinado com porcentagem (`data-progress`) (sem JS). | [loading.md](./loading.md) |
| magicbutton | Botão de destaque (call-to-action) em superfície de apoio, formatos pílula/redondo e 3 densidades (resumo, sem JS). | [magicbutton.md](./magicbutton.md) |
| menu | Menu de navegação principal (off-canvas ou push) com pastas expansíveis, subníveis, header/footer, e menu contextual. | [menu.md](./menu.md) |
| message | Mensagens de feedback padrão (`br-message` info/success/warning/danger com fechar) e contextuais (`feedback`). | [message.md](./message.md) |
