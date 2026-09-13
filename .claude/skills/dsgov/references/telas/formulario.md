# Tela: Formulário (criar e editar)

Um só template para criar e editar (`<modelo>_formulario.html`), largura `col-md-8`, `{{ form }}`,
rodapé `dsgov/_acoes_formulario.html` (Cancelar à esquerda do primário "Salvar").

Regras:
- Campos obrigatórios têm asterisco vermelho no rótulo (o renderer faz isso). Não escreva "(obrigatório)".
- Ajuda curta via `help_text` do model/form; aparece abaixo do campo.
- Erros: por campo, abaixo dele, como `feedback danger`; gerais, no topo, como `br-message danger`.
  Depois de `POST` inválido a página volta com os valores preenchidos. Nada de alert() ou validação
  só no navegador (o `novalidate` do form é proposital).
- Seções: quando o formulário passa de 8 campos, agrupe com `<fieldset><legend>` (o DS estiliza) e
  deixe uma linha em branco (`mb-4`) entre grupos. Mais de 3 seções: considere `br-wizard`
  (`telas/wizard.md`).
- Campos dependentes (cidade depende de UF): recarregue o fragmento do campo com HTMX
  (`hx-get` no primeiro campo, `hx-target` no wrapper do segundo, view devolvendo
  `{{ form.cidade.as_field_group }}`). O `dsgov.js` reinicializa o `br-select` recém-chegado.
- Sucesso: `messages.success` e redirect para o detalhe (nunca fica na tela de formulário).
- Confirmação de exclusão é uma página própria (`<modelo>_confirmar_exclusao.html`), com
  `br-message warning`, Cancelar e "Confirmar exclusão" (`primary`, ícone lixeira). Sem modal.
- Registros filhos 1:N (números SEI de um processo, telefones de um contato): editam-se DENTRO do
  formulário do pai, nunca por rota avulsa a partir do detalhe. `inlineformset_factory(Pai,
  Filho, fields=[…], extra=2, can_delete=True)` renderizado no `<fieldset>` da seção a que pertence:
  `br-table` com uma linha por filho (`br-input` do campo + `br-checkbox` "Excluir") e as linhas
  `extra` vazias para incluir; `{{ formset.management_form }}` dentro do `<form>`. A view valida
  `form` E `formset` e salva os dois na mesma transação (e sob o mesmo token de versão, se houver);
  erro em qualquer um devolve a página inteira com os valores. Nada persiste antes de "Salvar".
