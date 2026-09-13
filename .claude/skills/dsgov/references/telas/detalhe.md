# Tela: Detalhe de um registro

`<modelo>_detalhe.html`: `h1` = `__str__` do objeto; à direita, "Editar" (`primary`) e "Excluir"
(`secondary`). Card com `dl.dsgov-detalhe` em 2 colunas (`col-sm-6`), campos longos em `col-12`.
Abaixo, linha discreta de auditoria ("Cadastrado em … · Atualizado em …") e botão terciário "Voltar".

Regras:
- Ações de fluxo (aprovar, cancelar, pagar) entram no mesmo grupo de botões, à esquerda de Editar,
  como `br-button secondary` com ícone; cada uma é um `<form method="post">` de uma linha.
  Só a ação principal do estado atual pode ser `primary`, e nesse caso Editar vira `secondary`.
- Registros relacionados (itens de um pedido, histórico): uma seção `h2` abaixo do card, com
  `br-table` simples (sem busca/paginação) ou `br-list`, nunca cards aninhados.
- Abas (`br-tab`) só quando há 3 ou mais seções relacionadas com muito conteúdo.

## Variante ficha (padrão PNCP)

Para registros com muitos campos agrupados por assunto (uma contratação, um processo, um
convênio), use a **ficha** no lugar do card único: é o layout da página de edital do Portal
Nacional de Contratações Públicas (que roda sobre o próprio govbr-ds). Nenhum CSS novo — só
utilitários do `core.min.css`. A view continua entregando `trilha` e, por seção, uma lista de
pares `(rótulo, valor, largo)`; o template não decide rótulo nenhum.

Anatomia, de cima para baixo:

1. `h1` curto e identificador ("Edital nº 31/2026", "Item 12/2026") — o texto longo (objeto,
   descrição) NÃO vai no título: vira o primeiro par em largura total.
2. `<em>` "Última atualização dd/mm/aaaa" logo abaixo do `h1` (substitui a linha de auditoria do
   rodapé).
3. Linha de `br-tag` com o estado do registro (situação, tipo, origem); depois as ações, mesmas
   regras da tela padrão (uma `primary`), empilhadas abaixo de 576 px (`flex-column flex-sm-row`).
4. **Quadros de destaque** (até três): valores e prazo decisivos. Título em caixa alta e negrito,
   valor embaixo. Valor ausente = "Não informado", nunca zero.
5. **Seções** (`h2`), separadas por `br-divider`, sem card por seção. Pares "`Rótulo:` valor" na
   mesma linha (`<p><strong>Rótulo:</strong> valor</p>`), dois por linha a partir de `md`, texto
   longo em `col-12`.
6. Registros relacionados (histórico, itens, arquivos) como seções `h2` + `br-table` no fim, na
   ordem de leitura. `br-tab` só se forem 3+ e longos.
7. Rodapé: "Voltar" terciário (+ Anterior/Próximo quando há navegação). "Voltar"/Anterior/
   Próximo e as ações de fluxo (Editar, transições de estado) preservam a MESMA querystring
   canônica recebida da listagem (ver `django.md` § "Estado canônico de listagem e restauração
   de rolagem") — campo oculto `querystring_retorno` quando a ação usa `action=`/`hx-post`
   explícito (não herda a querystring da URL na submissão).

```html
<div class="d-flex flex-wrap align-items-start mb-3">
  <div>
    <h1 class="mb-1">Item 12/2026</h1>
    <p class="mb-2"><em>Última atualização 02/09/2026</em></p>
    <p class="mb-0">
      <span class="br-tag status bg-success"><span>No prazo</span></span>
      <span class="br-tag"><span>Nova contratação</span></span>
    </p>
  </div>
  <div class="ml-auto d-flex flex-column flex-sm-row flex-wrap align-items-sm-center">
    <a class="br-button secondary mb-2 mb-sm-0 mr-sm-2" href="…"><i class="fas fa-calendar-check mr-1" aria-hidden="true"></i>Registrar acompanhamento</a>
    <a class="br-button primary" href="…"><i class="fas fa-pen mr-1" aria-hidden="true"></i>Editar</a>
  </div>
</div>

<div class="row mb-4">
  <div class="col-12 col-md-4 mb-3">
    <div class="bg-cyan-vivid-20 p-3 rounder-sm">
      <p class="text-bold text-up-01 mb-2">VALOR PREVISTO</p>
      <p class="text-up-02 mb-0">R$ 1.215.575,31</p>
    </div>
  </div>
  <div class="col-12 col-md-4 mb-3">
    <div class="bg-mint-vivid-20 p-3 rounder-sm">
      <p class="text-bold text-up-01 mb-2">VALOR CONTRATADO</p>
      <p class="text-up-02 mb-0">Não informado</p>
    </div>
  </div>
  <div class="col-12 col-md-4 mb-3">
    <div class="bg-blue-warm-vivid-5 p-3 rounder-sm">
      <p class="text-bold text-up-01 mb-2">PRAZO ATUAL</p>
      <p class="text-up-02 mb-0">29/10/2026 <span class="text-base">(vence em 48 dias)</span></p>
    </div>
  </div>
</div>

<h2 class="text-up-01 mb-3">Planejamento</h2>
<div class="row">
  <div class="col-12"><p class="mb-2"><strong>Objeto:</strong> Contratação de empresa especializada …</p></div>
  <div class="col-12 col-md-6"><p class="mb-2"><strong>Unidade:</strong> Gerência de TI</p></div>
  <div class="col-12 col-md-6"><p class="mb-2"><strong>Prazo inicial:</strong> 30/06/2026</p></div>
</div>
<span class="br-divider my-3"></span>

<h2 class="text-up-01 mb-3">Execução contratual</h2>
<div class="row">
  <div class="col-12 col-md-6"><p class="mb-2"><strong>Modalidade:</strong> Pregão eletrônico</p></div>
  <div class="col-12 col-md-6"><p class="mb-2"><strong>SPW:</strong> Não informado <span class="br-tag warning"><span>pendente há 12 dias</span></span></p></div>
</div>
<span class="br-divider my-3"></span>

<h2 class="text-up-01 mb-3">Histórico</h2>
<div class="br-table"> … `componentes/table.md`, sem busca nem paginação … </div>

<a class="br-button" href="…"><i class="fas fa-arrow-left mr-1" aria-hidden="true"></i>Voltar</a>
```

Regras da variante:
- Rótulo e valor no MESMO `<p>` — leitor de tela lê "Rótulo: valor" na ordem visual. Não use
  `dl.dsgov-detalhe` aqui (a ficha e o card padrão não se misturam na mesma página).
- Cores dos quadros só por utilitário `bg-{família}-{passo}` do core (`tokens.md`): ciano/menta
  para valores, `blue-warm-vivid-5` para prazo. Nunca hex, nunca `style=`.
- Sem `br-card` aninhado, sem QR code (exige biblioteca), sem `hx-*`.
- Seções com todos os valores ausentes ainda aparecem (a ausência é informação).
