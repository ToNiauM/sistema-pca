# br-upload

Envio de arquivos (clique ou arrastar-e-soltar) do Design System gov.br, @govbr-ds/core 3.7.0. Comportamento em `dist/components/upload/upload.js` (classe `BRUpload`), instanciado automaticamente por `core-init.js` para todo `.br-upload`, com um callback de upload de exemplo (`setTimeout` de 500 ms) que **deve ser substituído** pela chamada real ao servidor.

## Quando usar / quando não usar

- Use dentro de formulários (ou isolado) para o usuário selecionar um ou mais arquivos e enviá-los ao servidor; o usuário pode clicar ou arrastar arquivos para a área tracejada.
- Texto do placeholder ("Selecione o arquivo" / "Selecione o(s) arquivo(s)") e o ícone `fa-upload` são fixos; o label segue o padrão "Envio de arquivos", "Envio de imagens", "Envio de documentos" etc.
- Envio único: label "Envio de arquivo"; ao enviar outro, o novo substitui o anterior com aviso. Envio múltiplo exige `multiple` no input.
- Erros (formato, tamanho, falha) devem ser tratados com mensagem `.feedback` abaixo do componente, arquivo a arquivo quando houver vários; nomes longos são truncados com tooltip do nome completo.
- Em 4 colunas (mobile) não há arrastar-e-soltar: a única forma é o toque/clique no componente.

## HTML canônico

```html
<div class="br-upload">
  <label class="upload-label" for="upload-documentos"><span>Envio de documentos</span></label>
  <input class="upload-input" id="upload-documentos" type="file" multiple="multiple" aria-hidden="null" aria-label="enviar arquivo"/>
  <div class="upload-list"></div>
</div>
<p class="text-base mt-1">Clique ou arraste os arquivos para cima do componente Upload.</p>
```

Após a inicialização o JS reordena os filhos e insere o botão: `label` → `input` (oculto por CSS) → `<button class="upload-button" type="button" aria-hidden="true"><i class="fas fa-upload" aria-hidden="true"></i><span>Selecione o(s) arquivo(s)</span></button>` → `.upload-list`.

## Variantes e modificadores

| Classe/atributo | Efeito | Exemplo |
| --- | --- | --- |
| `br-upload` | Container; `input` filho fica `display: none` | `<div class="br-upload">` |
| `label.upload-label` | Label do componente (`upload-label` não tem regra própria em `core.css`; é o gancho do JS `querySelector('label')`) | `<label class="upload-label" for="x"><span>Envio de arquivo</span></label>` |
| `input.upload-input[type="file"]` | Entrada de arquivos; gancho do JS (`.upload-input`) | `<input class="upload-input" id="x" type="file"/>` |
| `multiple="multiple"` no input | Vários arquivos; texto do botão vira "Selecione o(s) arquivo(s)"; sem `multiple` o envio de 2+ arquivos gera erro "É permitido o envio de somente 1 arquivo." e um novo arquivo substitui o anterior com aviso | `<input class="upload-input" type="file" multiple="multiple"/>` |
| `div.upload-list` | Lista de arquivos (`max-width: 550px`); o JS preenche com `div.br-item.d-flex` contendo `.content.text-primary-default.mr-auto` (nome truncado com `text-overflow: ellipsis`, `width: 70%`), um `.br-tooltip[info][place=top]` com o nome completo e `.support.mr-n2` com tamanho (`span.mr-1`, ex. "1.20 MB") e botão `button.br-button[circle]` com `i.fa.fa-trash` e `aria-label="apagar arquivo NOME"` | `<div class="upload-list"></div>` |
| `.upload-button` (gerado) | Botão tracejado: tokens de `br-button`, `border: var(--surface-width-sm) dashed var(--interactive)`, `border-radius: var(--surface-rounder-sm)`, itálico, `max-width: 550px`, `width: 100%`, texto à esquerda; estados de `button-states` | gerado pelo JS |
| `dragging` (classe adicionada pelo JS) | Durante `dragenter`/`dragover` no botão: gradiente de hover sobre o botão | automático |
| `data-danger` / `data-success` / `data-warning` / `data-info` (ou classes `danger`, `success`, `warning`, `info`) no `.br-upload` | Borda do `.upload-button` na cor do estado; o JS define `data-<status>` ao emitir feedback e remove ao atualizar a lista | `<div class="br-upload" data-danger="data-danger">` |
| `.feedback.danger|warning|info|success.mt-1[role="alert"]` | Mensagem de feedback (irmã do `.br-upload` no exemplo oficial; o JS a insere **antes** de `.upload-list`) com ícone FA5 `fas fa-times-circle` / `fa-exclamation-triangle` / `fa-info-circle` / `fa-check-circle` | `<span class="feedback danger mt-1" role="alert"><i class="fas fa-times-circle" aria-hidden="true"></i>Os arquivos devem ser no formato PNG ou JPG e ter no máximo 100MB.</span>` |
| `disabled="disabled"` no `.br-upload` **e** no input | Regra global `[disabled] { opacity: var(--disabled); cursor: not-allowed }`; o JS marca o `.upload-button` como `disabled` e insere `<span class="feedback warning mt-1" role="alert">…Upload desabilitado</span>` após o componente | `<div class="br-upload" disabled="disabled">…<input class="upload-input" type="file" disabled="disabled"/>` |
| `p.text-base.mt-1` logo após o `.br-upload` | Texto auxiliar; o JS o esconde (`display: none`) enquanto houver arquivos na lista e o restaura quando a lista esvazia (usa `document.querySelector('.text-base')`, o primeiro da página) | `<p class="text-base mt-1">Clique ou arraste…</p>` |

Ícones Font Awesome 5: `fas fa-upload` (botão), `fa fa-trash` (remover, gerado), ícones dos feedbacks acima. Não existem em `core.css` as classes `upload-label` e `upload-input` (só ganchos) nem regra `[loading]`: o indicador "Carregando..." que o JS injeta (`<div sm loading class="my-3"><span class="cargas">Carregando...</span></div>`) não recebe estilo do `br-loading` em 3.7.0.

## Estados e acessibilidade

- Inicialização: `core-init.js` executa `new BRUpload('br-upload', el, uploadTimeout)` onde `uploadTimeout` retorna uma `Promise` resolvida após 500 ms. Em produção instancie você mesmo com `core.min.js`: `new core.BRUpload('br-upload', el, () => fetch('/api/upload', …))`; o callback é chamado **uma vez por arquivo** (sem argumentos) e, quando a Promise resolve, o item é renderizado na lista. Se `core-init.js` também estiver carregado, haverá dupla instanciação.
- Fluxo do JS: `change` no input ou `drop` no botão → `_handleFiles` → valida único/múltiplo → concatena em `_fileArray` → `_updateFileList` (mostra loading, chama o callback, renderiza `br-item` com tooltip e botão lixeira). Remover: `_removeFile` reconstrói `input.files` via `DataTransfer` (múltiplo) ou zera `input.value` (único). Ao remover, lista, status e feedbacks são limpos.
- Acessibilidade do markup oficial: `label for` + `id`; `aria-label="enviar arquivo"` no input (o exemplo oficial traz `aria-hidden="null"`, valor inválido que equivale a não oculto). O botão gerado tem `aria-hidden="true"`, portanto o foco de teclado deve ir ao `input` (que está `display: none` e, logo, não é focável): na prática o componente **não é operável por teclado** sem ajustes próprios (ex.: remover `display: none` do input visualmente escondendo-o).
- Feedback gerado: `div.feedback.<status>.mt-1` com `role="alert"`, `aria-live="assertive"` e `aria-label` com o texto.
- Estados visuais: hover/pressed/foco do `.upload-button` (tokens `br-button`), `dragging` na área, borda verde (`data-success`) etc.
- Nenhum evento customizado; o `input.files` reflete a lista atual (após remoções, no modo múltiplo).

## Erros comuns

- Omitir `div.upload-list`: `_fileList` fica `null` e o JS quebra ao renderizar.
- Esquecer o callback de upload ao instanciar manualmente: `_uploadFiles` indefinido → o loading aparece e o arquivo nunca é listado.
- Manter `core-init.js` em produção: o upload real nunca acontece (callback é um `setTimeout`) e o componente é instanciado duas vezes se você também o instanciar.
- Inserir o `.upload-button` no HTML: o JS cria outro botão.
- Colocar o `p.text-base` antes do componente ou outro `.text-base` antes na página: o JS pega o primeiro `.text-base` do documento e pode esconder o elemento errado.
- Usar `br-message` como feedback dentro do componente: o padrão é `.feedback.<status>` com ícone FA5 e `role="alert"`; o JS remove qualquer `.feedback` interno ao processar novos arquivos.
- Marcar `disabled` só no input: a opacidade global vem do atributo no container `.br-upload`.

## Fonte

- https://www.gov.br/ds/components/upload?tab=designer
- https://www.gov.br/ds/components/upload?tab=desenvolvedor
- https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/upload/upload.md
- https://docs-ds.estaleiro.serpro.gov.br/govbr-ds-core/docs/components/upload/upload-dev.md
- Local: `/opt/web/pca/node_modules/@govbr-ds/core/dist/components/upload/examples.html`, `dist/components/upload/examples/*.html`, `dist/components/upload/upload.js`, `src/components/upload/_mixins.scss`, `dist/core-init.js`, `dist/core.css`
