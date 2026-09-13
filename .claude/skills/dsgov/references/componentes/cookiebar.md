# br-cookiebar (resumo)

## Quando usar / quando não usar
- **Obrigatório** em sites/aplicativos do Governo que coletam ou tratam dados do usuário (LGPD, Lei 13.709/18); aparece na tela inicial e permanece visível até o consentimento/revogação.
- Prefira o padrão **opt-out** (usuário decide desligar grupos de cookies); use **opt-in** apenas em casos restritos.
- Se a política de cookies mudar depois do aceite, exiba o cookiebar novamente explicando o motivo.
- Texto claro e sem jargão técnico; ofereça links para detalhamento legal e canal de contato.
- Não use para avisos genéricos (use `br-message`) nem como modal de termos de uso.

## HTML canônico
O componente é **renderizado inteiramente pelo JS** a partir de um JSON. No HTML fica apenas o container:
```html
<div class="br-cookiebar default d-none" tabindex="-1"></div>
```
Instanciação (obrigatória, com o seu JSON — o `core-init.js` só instancia com um JSON de exemplo):
```html
<script src="/node_modules/@govbr-ds/core/dist/core.min.js"></script>
<script>
  const json = `[{"lang":"pt-br","allOptOut":true,"acceptButton":"Aceitar",
    "optOutButton":"Definir Cookies","optInButton":"Ver Política de Cookies",
    "infoText":"Utilizamos cookies para melhorar sua experiência…","mainTitle":"Respeitamos a sua privacidade",
    "lastUpdate":"01/02/2021", /* … grupos/cookies conforme jsonData.js … */ }]`;
  for (const el of document.querySelectorAll('.br-cookiebar')) {
    new core.BRCookiebar({
      name: 'br-cookiebar',
      component: el,
      json,
      lang: 'pt-br',
      mode: 'default',           // 'default' (barra) | 'open' (modal aberto)
      callback: (saida) => { /* JSON de saída com escolhas do usuário */ },
    })
  }
</script>
```
Alternativa sem HTML base: `core.BRCookiebar.createCookiebar(json, callback)` (estático).

## Variantes e modificadores
| classe/atributo | efeito | exemplo |
| --- | --- | --- |
| `.br-cookiebar` | raiz `position:fixed` cobrindo a tela, `z-index: layer-4`, sombra `lg-up` | `<div class="br-cookiebar">` |
| `.default` | modo barra (`top:unset`, só `.info-text` + ações; esconde `.entry-content`, `.main-content`, `.complementary-content`) | `class="br-cookiebar default"` |
| `mode: 'open'` (opção JS) | abre direto o modal completo com grupos/cookies | `new core.BRCookiebar({mode:'open',…})` |
| `.d-none` | utilitário inicial; o JS remove ao exibir | — |
| `tabindex="-1"` | permite foco programático no container (role dialog) | — |
| estrutura gerada | `.br-modal > .br-card > .wrapper`, `.br-modal-header.entry-content > .br-modal-title + .last-update + button.br-button.close`, `.info-text`, `.br-list.main-content > .br-item.group-info` (+ `.group-name`, `.group-size`, `.cookies-checked`, `.group-description`), `.br-list.cookie-info > .br-card`, `.br-list.complementary-content`, `.br-modal-footer.actions > .br-button.secondary + .br-button.primary`, `.br-switch.small.icon`, `.br-checkbox`, `span.feedback.warning` | não edite à mão |
| ícones gerados | `fas fa-angle-down` (expandir grupo), `fa-times` (fechar), `fa-exclamation-triangle` (aviso), `fa-external-link-alt` (link externo) | — |

Seletores que o JS usa (`selectors.js`): `.actions .br-button.primary` (aceitar), `.actions .br-button.secondary` (definir/política), `.br-modal-header .br-button.close`, `.main-content .br-checkbox input[data-parent]`, `.br-switch input[type="checkbox"]`, etc.

## Estados e acessibilidade
- O JS define na raiz `role="dialog"`, `aria-modal="true"`, `aria-describedby="info-t"`, `aria-label="Componente para definição de Cookies"`.
- Grupos expandem/retraem com `aria-label` "Expandir/Retrair o grupo de Cookies …"; seleção em lote usa `Checkgroup` (`data-parent`/`data-child`) com `br-switch`.
- Requer o CSS completo (`core.css`) porque usa `br-modal`, `br-card`, `br-list`, `br-switch`, `br-checkbox`, `feedback`.
- Se você carrega `core-init.js` em produção, ele instancia o cookiebar com o **JSON de exemplo** (`jsonData.js`, texto lorem ipsum). Use `core.js` + instanciação manual.
- Callback recebe o JSON de saída (string) com as escolhas; persistir o consentimento é responsabilidade da aplicação.

## Erros comuns
- Deixar o `core-init.js` em produção e ver textos "Exercitation et proident": o JSON de exemplo está sendo usado.
- Esquecer `d-none` inicial: pode piscar antes do JS.
- Passar `json` como objeto já parseado quando a classe espera a string (o exemplo oficial passa template string) — verifique `CookiebarData`.
- Alterar o HTML gerado à mão: o JS depende dos seletores fixos de `selectors.js`.
- Carregar só `core-lite.css`: faltam modal/switch e o layout quebra.

## Fonte
- https://www.gov.br/ds/components/cookiebar?tab=designer (markdown bruto: https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/cookiebar/cookiebar.md)
- https://www.gov.br/ds/components/cookiebar?tab=desenvolvedor (SPA; markup dos exemplos locais)
- `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/cookiebar/examples.html`, `cookiebar.js`, `selectors.js`, `cookiebar-templates.js`, `jsonData.js`
- `/opt/web/pca/node_modules/@govbr-ds/core/src/components/cookiebar/_mixins.scss`, `dist/core-init.js`
