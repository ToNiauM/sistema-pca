# Formato do `sistema.yaml`

É o único lugar onde o pedido do usuário vira estrutura. Traduza o que ele descreveu para este arquivo,
mostre-o de volta em uma frase por módulo ("Diárias: servidor, destino, datas, valor, situação com 4
estados") e rode o gerador. Tudo o que não está aqui (cores, layout, componentes) não é decisão sua.

```yaml
sistema: Controle de Diárias          # informativo; o nome oficial vem do scaffold (settings.DSGOV)
apps:
  - nome: diarias                     # slug do app → apps/diarias, prefixo de URL /diarias/
    rotulo: Diárias                   # nome no menu lateral (se o app tiver 1 modelo, o menu usa o plural do modelo)
    icone: fas fa-plane               # Font Awesome 5 (ver vocabulário em tokens.md); padrão fas fa-folder
    modelos:
      - nome: Diaria                  # classe Python (sem acento)
        rotulo: Diária                # singular exibido
        rotulo_plural: Diárias        # título da listagem, breadcrumb, menu
        genero: f                     # f (Nova diária, cadastrada) ou m (Novo documento, cadastrado); padrão f
        campo_str: destino            # campo usado em __str__ (padrão: primeiro texto/fk)
        campos:
          - {nome: servidor, tipo: fk, para: Servidor, rotulo: Servidor, exibir: nome}
          - {nome: destino, tipo: texto, max: 120, rotulo: Destino}
          - {nome: motivo, tipo: texto_longo, rotulo: Motivo da viagem, obrigatorio: false}
          - {nome: data_ida, tipo: data, rotulo: Data de ida}
          - {nome: valor, tipo: moeda, rotulo: Valor total, ajuda: "Inclui adicional de deslocamento"}
          - nome: situacao
            tipo: escolha
            rotulo: Situação
            padrao: solicitada
            opcoes: [[solicitada, Solicitada], [aprovada, Aprovada], [paga, Paga], [cancelada, Cancelada]]
            status: {solicitada: pendente, aprovada: andamento, paga: concluido, cancelada: cancelado}
        listagem:
          colunas: [servidor, destino, data_ida, valor, situacao]   # até 6; a 1ª vira link para o detalhe
          busca: [destino, servidor.nome]                            # icontains; "a.b" atravessa FK
          filtros: [situacao, servidor]                              # só campos escolha, fk ou booleano
          ordenacao: -data_ida                                       # ordenação inicial
        detalhe: [servidor, destino, motivo, data_ida, valor, situacao]   # padrão: todos os campos
```

## Tipos de campo

| tipo | Django | Formulário (DS) | Coluna |
|---|---|---|---|
| `texto` (`max`, padrão 200) | CharField | br-input | texto |
| `texto_longo` | TextField | br-textarea (linha inteira) | texto |
| `inteiro` | IntegerField | br-input type=number, meia largura | número à direita |
| `decimal` | DecimalField 14,2 | br-input number step .01 | número |
| `moeda` | DecimalField 14,2 | br-input number | `R$ 1.234,56` |
| `percentual` | DecimalField 6,2 | br-input number | `12,5%` |
| `data` | DateField | br-input type=date | `dd/mm/aaaa` |
| `data_hora` | DateTimeField | br-input type=datetime-local | `dd/mm/aaaa hh:mm` |
| `booleano` | BooleanField | br-checkbox | Sim/Não |
| `email` | EmailField | br-input type=email | texto |
| `cpf` / `cnpj` | CharField | br-input | texto (formate com os filtros `cpf`/`cnpj`) |
| `arquivo` | FileField | br-upload | texto |
| `escolha` (`opcoes`, `padrao`, `status`) | CharField + TextChoices | br-select (radios) | texto, ou **br-tag status** se houver `status` |
| `fk` (`para`, `exibir`, `relacao`) | ForeignKey PROTECT | br-select (radios) | `__str__` do relacionado |

Atributos comuns: `rotulo`, `obrigatorio` (padrão true), `unico`, `ajuda`, `padrao`, `col` (largura no
formulário, ex.: `col-md-4`; o padrão é linha inteira para textos e meia linha para números/datas/booleanos).

`status` mapeia cada opção para uma chave semântica de cor da `br-tag status`. As chaves aceitas são
fixas: `sucesso|concluido|ativo` (verde), `alerta|pendente` (amarelo), `erro|atrasado` (vermelho),
`info|andamento` (azul), `cancelado|neutro|inativo` (cinza). Não existem outras.

## O que o gerador produz por modelo

- `models.py`: campos, `criado_em`/`atualizado_em`, `Meta` com verbose e ordering, `__str__`,
  `get_absolute_url`, `<campo>_chave()` para campos com `status`.
- `forms.py`: `ModelForm` com widgets do tipo certo e um `clean()` vazio para regras entre campos.
- `views.py`: `Listar*` (busca, filtros, ordenação, paginação, resposta parcial HTMX), `Criar*`,
  `Editar*`, `Detalhe*`, `Excluir*`, todas com `PermissionRequiredMixin` nas permissões padrão do Django,
  mensagens de sucesso e breadcrumb.
- `urls.py`: `<app>:<modelo>_listar|_novo|_detalhe|_editar|_excluir`.
- `templates/<app>/`: `<modelo>_listar.html`, `_<modelo>_tabela.html`, `<modelo>_formulario.html`,
  `<modelo>_detalhe.html`, `<modelo>_confirmar_exclusao.html`.
- `tests.py`: as telas respondem 200 e usam componentes do DS.
- Registro em `INSTALLED_APPS`, `config/urls.py` e `core/menu.py`.

## Depois de gerar (aqui entra a inteligência)

1. Regras de negócio em `forms.py` (`clean`), `models.py` (métodos, `save`, propriedades) e, quando o fluxo
   exigir, views de ação específicas (aprovar, cancelar) que redirecionam para o detalhe com `messages`.
2. Dashboard em `core/views.py::inicio` com `core/graficos.py` (ver `telas/dashboard.md`).
3. Permissões finas: grupos do Django; o menu já esconde itens sem permissão.
4. Testes de regra de negócio ao lado dos testes gerados.
5. `verificar.py` limpo antes de entregar.

Rodar o gerador de novo é seguro: arquivos existentes são mantidos (use `--forcar` para sobrescrever) e os
registros não se duplicam.
