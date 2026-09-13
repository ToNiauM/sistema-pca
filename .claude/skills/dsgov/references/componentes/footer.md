# br-footer

## Quando usar / quando não usar
- Use como elemento de "fechamento" de toda página: mapa do site (categorias com links), logo, redes sociais, logos de assinatura e informação legal/licença.
- Layout consistente, previsível e igual em todas as páginas do projeto.
- Dois temas: **fundo escuro** (padrão) e **fundo claro** (`inverted`), escolhidos conforme o header/identidade.
- Em telas < 992px as categorias viram acordeão (uma aberta por vez); o JS cuida disso.
- Não use para navegação primária ou ações críticas; não coloque formulários complexos.

## HTML canônico
```html
<footer class="br-footer">
  <div class="container-lg">
    <div class="logo"><img src="/img/logo-negative.png" alt="Nome do órgão"/></div>
    <div class="br-list horizontal" data-toggle="data-toggle" data-sub="data-sub">
      <div class="col-2">
        <a class="br-item header" href="javascript:void(0)">
          <div class="content text-down-01 text-bold text-uppercase">Serviços</div>
          <div class="support"><i class="fas fa-angle-down" aria-hidden="true"></i></div>
        </a>
        <div class="br-list">
          <span class="br-divider d-md-none"></span>
          <a class="br-item" href="/servicos/cpf"><div class="content">Consulta de CPF</div></a>
          <a class="br-item" href="/servicos/cnpj"><div class="content">Consulta de CNPJ</div></a>
          <span class="br-divider d-md-none"></span>
        </div>
      </div>
      <div class="col-2">
        <a class="br-item header" href="javascript:void(0)">
          <div class="content text-down-01 text-bold text-uppercase">Institucional</div>
          <div class="support"><i class="fas fa-angle-down" aria-hidden="true"></i></div>
        </a>
        <div class="br-list">
          <span class="br-divider d-md-none"></span>
          <a class="br-item" href="/sobre"><div class="content">Sobre o órgão</div></a>
          <a class="br-item" href="/contato"><div class="content">Contato</div></a>
          <span class="br-divider d-md-none"></span>
        </div>
      </div>
      <!-- até 6 colunas col-2 -->
    </div>
    <div class="d-none d-sm-block">
      <div class="row align-items-end justify-content-between py-5">
        <div class="col">
          <div class="social-network">
            <div class="social-network-title">Redes Sociais</div>
            <div class="d-flex">
              <a class="br-button circle" href="https://facebook.com/…" aria-label="Facebook"><i class="fab fa-facebook-f" aria-hidden="true"></i></a>
              <a class="br-button circle" href="https://twitter.com/…" aria-label="Twitter"><i class="fab fa-twitter" aria-hidden="true"></i></a>
              <a class="br-button circle" href="https://linkedin.com/…" aria-label="LinkedIn"><i class="fab fa-linkedin-in" aria-hidden="true"></i></a>
              <a class="br-button circle" href="https://wa.me/…" aria-label="WhatsApp"><i class="fab fa-whatsapp" aria-hidden="true"></i></a>
            </div>
          </div>
        </div>
        <div class="col assigns text-right">
          <img class="ml-4" src="/img/logo-assign-negative.png" alt="Assinatura institucional"/>
        </div>
      </div>
    </div>
  </div>
  <span class="br-divider my-3"></span>
  <div class="container-lg">
    <div class="info">
      <div class="text-down-01 text-medium pb-3">Todo o conteúdo deste site está publicado sob a licença <strong>Creative Commons Atribuição-SemDerivações 3.0</strong>.</div>
    </div>
  </div>
</footer>
```

## Variantes e modificadores
| classe/atributo | efeito | exemplo |
| --- | --- | --- |
| `footer.br-footer` | fundo `--background-dark` (mixin `dark-mode`), borda superior 1px, padding `6x 0 0` | `<footer class="br-footer">` |
| `.inverted` / `[inverted]` | tema claro (`--background-light`, mixin `light-mode`); use logos "positive" | `<footer class="br-footer inverted">` |
| `.no-divider` | remove borda superior e padding-top | `class="br-footer no-divider"` |
| `.logo > img` | logo (máx. 180×48px), padding-bottom 6x | — |
| `.br-list.horizontal[data-toggle][data-sub]` | mapa do site em flex-wrap; `data-sub` impede o `BRList` genérico de inicializar (o footer controla) | obrigatório |
| `.col-2` | coluna de categoria (`flex-grow:0`, 100% em < sm) — até 6 | — |
| `a.br-item.header` | título da categoria; `.content` + `.support > i.fas.fa-angle-down` | — |
| `.br-item.header.active` + `.br-list` | (mobile) borda inferior nas colunas abertas | classe `active` aplicada pelo JS |
| `.br-list` (interna) > `a.br-item > .content` | links da categoria; itens com `min-height: 4em`, máx. 2 linhas | — |
| `span.br-divider.d-md-none` | separadores só no mobile | — |
| `.social-network` > `.social-network-title` + `a.br-button.circle` | redes sociais (título uppercase extra-bold; ícones `fab fa-facebook-f`, `fa-twitter`, `fa-linkedin-in`, `fa-whatsapp`) | — |
| `.assigns > img` | logos de assinatura (máx. 180×46px) | — |
| `.info` | área de licença centralizada (`text-align:center`) | — |
| `.d-none.d-sm-block > .row.align-items-end.justify-content-between.py-5` | wrapper das informações secundárias (o SCSS ajusta esse seletor exato) | mantenha as classes |

Não há densidades (`small/large`) nem `circle/block` para o footer.

## Estados e acessibilidade
- **Auto-init**: `core-init.js` executa `new BRFooter('br-footer', el)`. Manual: `new core.BRFooter('br-footer', el)`. O `BRList` **não** deve inicializar a lista do footer — por isso `data-sub` (core-init usa `.br-list:not([data-sub])`).
- Comportamento (`< 992px`): `.br-list` internas começam com `display:none`; clique ou Enter em qualquer `.br-item` da lista horizontal alterna a `.br-list` da coluna (`.col-2`) e fecha as demais; ícone `fa-angle-down` ⇄ `fa-angle-up`. Em `resize` ≥ 992px todas voltam a `display:block`.
- O JS define no elemento pai do alvo clicado `id="list-NNNN"`, `data-visible`, `aria-expanded`, `aria-label="expandido|recolhido"`, `aria-controls`, `data-group="group1"`, `data-target` (gerados dinamicamente — não precisa escrever).
- Semântica: use `<footer>` como raiz. Ícones sociais são `a.br-button.circle` com `aria-label` obrigatório e `<i aria-hidden="true">`.
- O `a.br-item.header` usa `href="javascript:void(0)"` nos exemplos (ele só abre/fecha no mobile); em desktop pode apontar para a página da categoria.
- Imagens de logo precisam de `alt` significativo (os exemplos usam "Imagem" — melhore).

## Erros comuns
- Esquecer `data-sub` na `.br-list.horizontal`: o `BRList` genérico também inicializa e conflita com o `BRFooter`.
- Colunas sem `.col-2` (ex.: `.col-md-2`): o JS sobe até 3 níveis procurando `.col-2` para achar a coluna; sem ela o acordeão mobile falha.
- Colocar o ícone fora de `.support` ou usar `fa-chevron-down`: o JS alterna apenas `fa-angle-down/up` no primeiro `<i>` da coluna.
- Usar tema `inverted` com logos "negative" (brancos): somem no fundo claro.
- Remover `.d-none.d-sm-block` do bloco secundário: aparece no mobile e o SCSS de padding específico deixa de valer.
- Aninhar o `br-footer` dentro de `.container`: ele já traz `.container-lg` internos e o fundo deve ocupar toda a largura.

## Fonte
- https://www.gov.br/ds/components/footer?tab=designer (markdown bruto: https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/footer/footer.md)
- https://www.gov.br/ds/components/footer?tab=desenvolvedor (SPA; markup dos exemplos locais)
- `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/footer/examples.html`
- `/opt/web/pca/node_modules/@govbr-ds/core/src/components/footer/_mixins.scss`, `_footer.scss`
- `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/footer/footer.js`, `dist/core-init.js`
