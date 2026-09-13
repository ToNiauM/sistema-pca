# br-magic-button (resumo)

## Quando usar / quando não usar
- Use para **iniciar/encerrar fluxos relevantes** ou como *call-to-action* de conversão, inclusive como botão flutuante visível independentemente da rolagem.
- Idealmente **um único** magic button por site/aplicativo, em área nobre (topo/base à direita ou base centro), com área de respiro para não competir com outros botões.
- Dois formatos: **pílula** (com rótulo) e **redondo** (só ícone, `aria-label` obrigatório). Densidades `small/medium/large`.
- Estados: hover, pressionado, foco. **Nunca** desabilitado (se precisar desabilitar, use `br-button` primário/secundário).
- Não use para ações corriqueiras, secundárias ou pertencentes a outro componente — o `br-button` pode substituir o magic button, o contrário não.

## HTML canônico
```html
<!-- Pílula -->
<div class="br-magic-button">
  <button class="br-button" type="button">Solicitar serviço</button>
</div>

<!-- Redondo -->
<div class="br-magic-button">
  <button class="br-button circle" type="button" aria-label="Adicionar ao carrinho">
    <i class="fas fa-cart-plus" aria-hidden="true"></i>
  </button>
</div>
```

## Variantes e modificadores
| classe/atributo | efeito | exemplo |
| --- | --- | --- |
| `.br-magic-button` | superfície de apoio: `inline-flex`, fundo `--gray-5`, `border-radius:100em`, sombra `md`, altura `--magic-support-size` (64px) e padding = (suporte − botão)/2 | wrapper obrigatório |
| `.br-magic-button .br-button` | botão interno: fundo `--interactive-alternative` (verde), texto `--color-dark`, fonte `up-02` semi-bold, altura `--magic-size` (56px), hover/active em `color-dark` | filho obrigatório |
| `.br-button.circle` (interno) | formato redondo; ícones `--icon-size-lg` | `<button class="br-button circle" aria-label>` |
| `.small` (no wrapper) | botão `4xh` (36px) / suporte `7x` (56px) | `class="br-magic-button small"` |
| `.medium` (no wrapper) | botão `5xh` (44px) / suporte `8x` (64px) — padrão | `class="br-magic-button medium"` |
| `.large` (no wrapper) | botão `6xh` (52px) / suporte `9x` (72px) | `class="br-magic-button large"` |

Não há `primary/secondary`, `block`, `inverted` nem `disabled` para o magic button.

## Estados e acessibilidade
- Sem JS: nada a instanciar.
- Botão redondo precisa de `aria-label`; ícone `aria-hidden="true"`.
- Foco: `--focus-offset` calculado para o anel contornar o suporte; não remova o outline.
- Se for flutuante, posicione o wrapper (`position:fixed; bottom/right`) e garanta que não cubra conteúdo essencial nem o cookiebar.

## Erros comuns
- Usar `.br-magic-button` direto no `<button>` sem o wrapper `div`: perde a superfície de apoio e a sombra.
- Aplicar `primary/secondary` ao botão interno: sobrescreve o verde característico.
- Desabilitar (`disabled`): proibido pela documentação; troque por `br-button`.
- Mais de um magic button na mesma tela: perde o destaque exclusivo.
- Colocar `small/large` no botão em vez do wrapper: os tokens ficam no `.br-magic-button`.

## Fonte
- https://www.gov.br/ds/components/magicbutton?tab=designer (markdown bruto: https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/magicbutton/magicbutton.md)
- https://www.gov.br/ds/components/magicbutton?tab=desenvolvedor (SPA; markup dos exemplos locais)
- `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/magicbutton/examples.html`
- `/opt/web/pca/node_modules/@govbr-ds/core/src/components/magicbutton/_mixins.scss`, `_magicbutton.scss`, `src/components/button/_mixins.scss` (mixin `button-magicbutton`)
