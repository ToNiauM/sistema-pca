# API do PCA para a extensão SEI Pro — contrato v1

**Versão:** 1 · **Data:** 09/10/2026 · **Fonte da verdade:**
documento interno de desenho

**Atualização v1.1 (10/10/2026):** vínculo de nº SEI a um item do PCA (`POST /vinculo`), ficha da
contratação (`GET`/`PUT /ficha`) e 3 campos novos em `GET /processo` (`modalidade`/`objeto`/
`unidade_sigla_sei`) — tudo aditivo, `GET /saude` continua `{"versao": 1}` (o cliente detecta as
rotas novas pelo path, não por número de versão). Fonte: documento interno de desenho.

Este é o único documento que o repositório `sei-pro` (extensão SEI Pro Gelic/CFC) precisa ler para
implementar o lado cliente. Mudança incompatível sobe para v2 num path novo (`/api/v2/sei/...`) —
v1 nunca quebra em produção enquanto houver extensão publicada consumindo-a.

## Visão geral

A extensão lê o material bruto de um processo direto na sessão do SEI (sem a senha da Gelic) e
envia ao PCA pelo mesmo caminho que o robô usaria: o PCA roda a mesma montagem/extração/regras de
negócio (`apps/pca/sei/montagem.py` → `apps/pca/sei/regras.py` → `apps/pca/sei/aplicador.py`) e
aplica o resultado direto no acompanhamento do item, com as mesmas proteções do robô
(`situacao_manual`, idempotência, trilha de histórico).

## Autenticação

Todas as rotas exigem um token pessoal no cabeçalho:

```
Authorization: Bearer <token>
```

O token é gerado em "Meu perfil" (tela do PCA), mostrado **uma única vez** no momento da geração —
o PCA guarda só o hash. Gerar um token novo revoga o anterior automaticamente (um token ativo por
usuário). Sem token, token inválido ou revogado → `401`.

## CORS

As rotas `/api/*` respondem `OPTIONS` e ecoam `Access-Control-Allow-Origin` só para as origens
permitidas:

- A origem fixa configurada em `API_ORIGENS_EXTENSAO` (`.env` do PCA; em produção,
  `https://sei.cfc.org.br` — o conteúdo que roda dentro da página do SEI).
- Qualquer `chrome-extension://<32 letras minúsculas a-p>` (padrão de ID de extensão não
  empacotada do Chrome) — IDs mudam por máquina/instalação; quem protege o acesso é o token, não a
  origem.

Métodos permitidos: `GET`, `POST`, `PUT` (v1.1 — `PUT` liberado para `/api/sei/ficha`). Cabeçalhos
permitidos: `Authorization`, `Content-Type`.

## Permissão `pca.instruir_contratacao` (grupo `demandante`)

v1.1 introduz a permissão `pca.instruir_contratacao` e o grupo `demandante`: quem está nesse grupo
consegue `POST /api/sei/vinculo` e `PUT /api/sei/ficha` **sem precisar de** `pca.editar_pca`. Quem
já tem `pca.editar_pca` (grupo `editor`) também grava nessas duas rotas — é um OR semântico
(`pode_instruir(usuario) = usuario.has_perm("pca.instruir_contratacao") or
usuario.has_perm("pca.editar_pca")`), nunca precisa entrar no grupo `demandante` para isso.
Pessoas entram no grupo `demandante` pelo Admin (o grupo é criado vazio pela migração).

## GET /api/sei/saude

Autenticação opcional.

- **Sem `Authorization`:** checagem de disponibilidade/versão — `{"versao": 1}`.
- **Com `Authorization: Bearer <token>`:** também valida o token, para a tela de configuração da
  extensão e para ela saber, antes de ler histórico e documentos, se pode enviar coleta —
  `{"versao": 1, "usuario": "<email>", "pode_enviar": <true se tem pca.editar_pca>, "pode_instruir":
  <true se pode_instruir(usuario)>}`. Token inválido ou revogado → `401`.

`pode_instruir` (v1.1) é `true` quando o usuário tem `pca.instruir_contratacao` OU
`pca.editar_pca` — reflete a mesma permissão exigida por `POST /vinculo` e `PUT /ficha`.

**Request:**

```
GET /api/sei/saude
```

**Resposta 200:**

```json
{"versao": 1}
```

Com token válido:

```json
{"versao": 1, "usuario": "fulano@cfc.org.br", "pode_enviar": true, "pode_instruir": true}
```

## GET /api/sei/processo

Busca o(s) item(ns) do PCA ligados a um processo SEI. Dois modos de busca, mutuamente exclusivos:

- `?sei=<número>` — pelo número do processo SEI (casamento por dígitos completos, qualquer
  formatação aceita: `90796110000019.000030/2025-74` e `90796110000019000030202574` casam igual).
- `?item=<n>&exercicio=<ano>` — pelo item do PCA diretamente (usado pelo DFD da extensão SEI Pro
  CFC quando o processo ainda não tem nº SEI vinculado).

Exige só usuário autenticado e ativo (sem exigir `pca.editar_pca` — rota de leitura).

**Campos novos (v1.1), em cada item, ao lado dos já existentes (nenhum campo da v1 foi removido):**

- `modalidade` (string ou `null`): rótulo da modalidade de contratação (`Processo.modalidade`),
  `null` quando o campo ainda não foi preenchido no planejamento.
- `objeto` (string): alias explícito de `descricao_objeto`, pedido pela extensão — mesmo valor.
- `unidade_sigla_sei` (string): mesmo valor do campo `unidade` já existente (o nome da unidade
  organizacional já é a sigla usada no SEI), republicado sob o nome que a extensão espera.

### Request — busca por `sei`

```
GET /api/sei/processo?sei=90796110000007.000036/2025-81
```

### Resposta 200 — busca por `sei`, com vínculo

```json
{
  "itens": [
    {
      "item_pca": 3,
      "exercicio": 2025,
      "descricao_objeto": "Contratação de serviços de limpeza predial",
      "valor_estimado": "165000.00",
      "unidade": "GECONT",
      "grau_prioridade": "Essencial",
      "mes_previsto": 3,
      "situacao": "CONCLUIDO",
      "situacao_rotulo": "Concluído",
      "numeros_sei": ["90796110000007.000036/2025-81"],
      "modalidade": "Pregão Eletrônico",
      "objeto": "Contratação de serviços de limpeza predial",
      "unidade_sigla_sei": "GECONT"
    }
  ],
  "ultima_coleta": {
    "registros": 42,
    "primeiro": {
      "data_hora": "13/04/2026 10:53",
      "unidade": "DELIC",
      "descricao": "Conclusão do processo na unidade"
    },
    "recebido_em": "2026-10-08T09:15:00-03:00",
    "origem": "robo"
  }
}
```

`ultima_coleta` aparece **só** na busca por `sei` — é o mesmo par `registros`/`primeiro` do atalho
de pulo do robô (`historico_resumo`), para a extensão decidir se precisa reler o histórico e os
documentos (sem mudança desde a última coleta, ela pode poupar o envio completo). `origem` indica
quem gravou a última coleta: `"robo"` (varredura) ou `"extensao"` (POST anterior). Na coleta da
extensão, `registros` = quantidade de andamentos enviados e `primeiro` = o andamento mais recente,
com a descrição anonimizada pela mesma regra do robô (`montagem._anon`) — compare com o seu
`primeiro` já anonimizado.

### Request — busca por `item`+`exercicio`, sem vínculo SEI ainda

```
GET /api/sei/processo?item=117&exercicio=2026
```

### Resposta 200 — busca por `item`+`exercicio`, sem vínculo

```json
{
  "itens": [
    {
      "item_pca": 117,
      "exercicio": 2026,
      "descricao_objeto": "Aquisição de licenças de software",
      "valor_estimado": "48000.00",
      "unidade": "CGTI",
      "grau_prioridade": "Importante",
      "mes_previsto": 6,
      "situacao": "EM_ANDAMENTO",
      "situacao_rotulo": "Em andamento",
      "numeros_sei": [],
      "modalidade": null,
      "objeto": "Aquisição de licenças de software",
      "unidade_sigla_sei": "CGTI"
    }
  ]
}
```

`situacao` é o código da situação; `situacao_rotulo` é o texto legível (ex.: `"Concluído"`), para a
extensão exibir sem manter um mapa de códigos.

### Resposta 200 — nenhum vínculo encontrado

```json
{"itens": []}
```

Lista vazia (nunca `404`) — a extensão, ao receber `itens: []` na busca por `sei`, deve oferecer a
busca por `item`+`exercicio` (da spec).

## POST /api/sei/coleta

Envia o material bruto de **um** processo SEI — a mesma extração que o robô faria, lida pela
extensão na sessão de quem trabalha. Exige `pca.editar_pca` (rota de escrita, equipe da Gelic) →
sem a permissão, `403`.

### Corpo do request

```json
{
  "numero": "90796110000007.000036/2025-81",
  "andamentos": [
    {
      "data_hora": "13/04/2026 10:53",
      "unidade": "DELIC",
      "descricao": "Conclusão do processo na unidade"
    },
    {
      "data_hora": "19/02/2026 16:50",
      "unidade": "DELIC",
      "descricao": "Assinado Documento 1210804 (Contrato) por fulano@externo.com.br"
    },
    {
      "data_hora": "05/09/2025 16:19",
      "unidade": "DELIC",
      "descricao": "Processo recebido na unidade DELIC"
    }
  ],
  "documentos": [
    {
      "id_documento": "1277038",
      "protocolo": "1210804",
      "rotulo": "Contrato nº 08/2026 - GOSHME x CFC",
      "assinantes_externos_na_arvore": 1,
      "contratual": true,
      "cancelado": false,
      "motivo_cancelamento": null,
      "conteudo": "html",
      "motivo": null,
      "html": "<html>...conteúdo do documento, tal como renderizado no SEI...</html>",
      "pdf_base64": null
    },
    {
      "id_documento": "1156099",
      "protocolo": "1094999",
      "rotulo": "Termo Aditivo 1/2026",
      "assinantes_externos_na_arvore": 0,
      "contratual": true,
      "cancelado": true,
      "motivo_cancelamento": "erro de autuação",
      "conteudo": "nao_lido",
      "motivo": "restrito",
      "html": null,
      "pdf_base64": null
    }
  ]
}
```

Campos do corpo:

- `numero` (string, obrigatório): número do processo SEI, em qualquer formatação — o PCA casa por
  dígitos completos contra `ProcessoSEI.numero_sei`.
- `andamentos` (lista, obrigatório): histórico **completo** do processo, as mesmas 3 colunas que o
  SEI lista (`data_hora`, `unidade`, `descricao` crua — sem anonimizar; `descricao` precisa manter
  o login com `@` quando presente, para o PCA distinguir assinatura externa), mais recente
  primeiro (ordem não importa, o PCA reordena). O PCA calcula os marcos e **não grava as linhas
  cruas** — só o resumo (marcos), igual ao que o robô já guarda em cache hoje.
- `documentos` (lista, obrigatório): um item por documento da árvore do processo (não só os
  contratuais — o PCA também usa a contagem total). Cada documento:
  - `id_documento` (string): identificador do documento no SEI.
  - `protocolo` (string): protocolo do documento.
  - `rotulo` (string): rótulo exibido na árvore (ex.: `"Contrato nº 08/2026"`) — o PCA deriva o
    tipo do instrumento (contrato/termo aditivo/apostilamento/etc.) a partir dele.
  - `assinantes_externos_na_arvore` (inteiro): contagem exibida pelo SEI na árvore.
  - `contratual` (booleano): se o documento é um instrumento de contratação. **Informativo** — o
    PCA recalcula pela regex `RE_CONTRATUAL` sobre o `rotulo` (mesma regra do robô) e ignora este
    campo. Só os contratuais pela regra do PCA entram na análise de assinatura/valor/vigência; dos
    demais, só contam para o total de documentos, e o `conteudo` nunca é considerado.
  - `cancelado` (booleano) + `motivo_cancelamento` (string ou `null`): quando `true`, o PCA nunca
    tenta ler conteúdo — grava só o cancelamento.
  - `conteudo` (string ou `null`, um de `"html"`, `"pdf"`, `"externo_nao_baixado"`, `"nao_lido"`):
    o que a extensão conseguiu ler. Documento não contratual: mandar `"nao_lido"` com `motivo:
    "nao_contratual"` (ou `null`) — nunca vira pendência.
    - `"html"`: o campo `html` vem preenchido com o conteúdo renderizado do documento.
    - `"pdf"`: o campo `pdf_base64` vem preenchido (documento externo, ex. anexo assinado fora do
      SEI, baixado pela extensão e codificado em base64).
    - `"externo_nao_baixado"`: documento externo contratual que o robô também não baixa (o robô só
      baixa o PDF de Contrato e Termo Aditivo externos; ex.: apostilamento externo). A extensão
      manda isso nos mesmos casos — paridade com `coletor.ler_documento`.
    - `"nao_lido"`: nem `html` nem `pdf_base64` vêm preenchidos — o campo `motivo` explica por quê:
      `"restrito"` (documento com acesso restrito: a extensão não envia o conteúdo) ou
      `"nao_contratual"`. O PCA trata um contratual `nao_lido` como o `externo_nao_baixado` do robô
      — mesmo efeito, nunca falha. Processo **sigiloso** é outra coisa: nunca é lido nem enviado
      (nem chega ao POST).
  - `html` (string ou `null`): preenchido só quando `conteudo == "html"`.
  - `pdf_base64` (string ou `null`): preenchido só quando `conteudo == "pdf"` — bytes do PDF
    codificados em base64 puro (sem prefixo `data:`).

Um número de processo SEI pode estar vinculado a mais de um item do PCA — o POST aplica a todos.

### Resposta 200

```json
{
  "itens": [
    {
      "item_pca": 3,
      "exercicio": 2025,
      "alterados": {
        "data_assinatura_contrato": [null, "2026-02-03"],
        "numero_instrumento_contratual": [null, "08/2026"]
      },
      "pendencias": [
        {"chave": "sem_acesso_documento:1210804", "texto": "Documento 1210804 não pôde ser lido (conteúdo externo); conferir manualmente se é o instrumento de contratação."}
      ]
    }
  ]
}
```

Formato do resumo do aplicador (`aplicador.aplicar`), filtrado por item: `alterados` é
`{campo: [antes, depois]}` só dos campos que mudaram (datas em ISO `AAAA-MM-DD`, valores
monetários como string decimal, ausente = `null`); `pendencias` lista avisos que não impedem a
aplicação (ex.: documento restrito nunca lido, valor que não confere com o extenso), cada um com
`chave` (identificador estável, deduplicado entre varreduras) e `texto` (legível). Reenviar a
mesma coleta sem mudança nenhuma devolve `alterados: {}` em todos os itens (idempotência — `propor` só aponta diferenças).

## POST /api/sei/vinculo

v1.1 — liga um nº SEI a um item do PCA (botão "Iniciar processo pelo PCA" da extensão). Exige
`pode_instruir` (ver seção acima) → sem ela, `403 {"erro": "sem_permissao"}`.

### Corpo do request

```json
{"item_pca": 117, "exercicio": 2026, "numero_sei": "90796110000019.000030/2025-74"}
```

Todos os três campos são obrigatórios (`item_pca`/`exercicio` inteiros, `numero_sei` string não
vazia); corpo inválido → `400 {"erro": "corpo_invalido", "detalhes": [...]}`.

- `item_pca`/`exercicio` que não casam nenhum `Processo` → `404 {"erro": "item_inexistente"}`.
- `numero_sei` já ligado a ESTE item (comparação por DÍGITOS completos, qualquer formatação) →
  `200 {"criado": false, "item": <mesmo formato de GET /processo>}` — idempotente, nunca duplica.
- `numero_sei` novo para este item → cria um `ProcessoSEI` e devolve
  `201 {"criado": true, "item": <...>}`.
- O MESMO `numero_sei` já ligado a OUTRO item diferente é permitido (um nº SEI pode estar em mais
  de um item do PCA) — nunca gera erro por isso, sempre cria/confirma para o item pedido.

## GET /api/sei/ficha

Lê a ficha da contratação (JSON livre, mantido pela extensão) de um item. Dois modos de busca,
mutuamente exclusivos, mesmo padrão de `GET /processo`: `?item=<n>&exercicio=<ano>` ou
`?sei=<número>`. Qualquer usuário autenticado lê — sem exigir `pode_instruir`.

### Resposta 200 — sem ficha gravada ainda

```json
{"item_pca": 117, "exercicio": 2026, "versao": 0, "dados": {}, "atualizado_em": null, "atualizado_por": null}
```

### Resposta 200 — com ficha gravada

```json
{
  "item_pca": 117,
  "exercicio": 2026,
  "versao": 2,
  "dados": {
    "esquema": 1,
    "respostas": {},
    "situacao": {
      "90796110000033.000076/2026-96": {
        "em": "2026-10-11T17:32:00.000Z",
        "completa": false,
        "proxima": "mapa_precos",
        "passos": [
          {"chave": "dfd", "rotulo": "DFD", "estado": "feito", "obrigatoria": true, "numero": "1593100"},
          {"chave": "termos_cientificacao", "rotulo": "Termos de cientificação", "estado": "em_elaboracao", "obrigatoria": false},
          {"chave": "mapa_precos", "rotulo": "Mapa de preços", "estado": "falta", "obrigatoria": true}
        ]
      }
    }
  },
  "atualizado_em": "2026-10-10T14:32:00-03:00",
  "atualizado_por": "fulano@cfc.org.br"
}
```

### Formato de `dados` (definido pela extensão, `esquema: 1`)

O PCA guarda `dados` sem interpretar; o formato é da extensão (SEI Pro CFC, r16, 11/10/2026 —
`~/dev/sei-pro/docs/gelic/2026-10-11-situacao-contrato-pca.md`):

- `esquema` (inteiro): versão do formato. Ficha sem `esquema` reconhecido é tratada pela extensão
  como formato desconhecido (só leitura; o selo não grava).
- `respostas` (objeto): respostas dos formulários das peças — o PCA não lê.
- `situacao` (objeto): **a situação da instrução, por nº SEI** (um item pode ter mais de um
  processo). Cada valor:
  - `em`: ISO 8601 em UTC, quando a situação foi calculada;
  - `completa` (booleano) e `proxima` (chave do próximo passo, ou `null`);
  - `passos`: lista de `{chave, rotulo, estado, obrigatoria, numero?}` — `estado` é `feito`
    (interna assinada, ou externa com arquivo), `em_elaboracao` ou `falta`; `rotulo` já vem pronto
    para tela (o PCA não mantém tabela de passos); `numero` é o protocolo SEI da peça, quando existe.
- Quem escreve `situacao`: só o SEI Pro CFC, ao abrir o processo, com `pode_instruir`, e só quando o
  roteiro muda. Ao gravar, preserva `respostas`, os outros processos e chaves desconhecidas, e trata
  o `409` relendo e tentando de novo (até 3 vezes).

- `item`/`exercicio`, ou `sei`, sem nenhum `Processo` correspondente → `404 {"erro": "item_inexistente"}`.
- `?sei=` vinculado a MAIS de um item → `409 {"erro": "sei_em_varios_itens", "itens": [{"item_pca":
  ..., "exercicio": ...}, ...]}` — nunca escolhe um item arbitrariamente.
- Nem `sei` nem `item`+`exercicio` informados → `400 {"erro": "corpo_invalido"}`.

## PUT /api/sei/ficha

Grava a ficha da contratação com controle otimista por versão. Exige `pode_instruir` → sem ela,
`403 {"erro": "sem_permissao"}`.

### Corpo do request

```json
{"item_pca": 117, "exercicio": 2026, "versao": 0, "dados": {"esquema": 1, "respostas": {}, "situacao": {}}}
```

- `item_pca`/`exercicio` inteiros obrigatórios; `versao` inteiro `>= 0` obrigatório; `dados`
  obrigatório e precisa ser um objeto JSON (não lista/string/número) → senão `400
  {"erro": "corpo_invalido", "detalhes": [...]}`.
- `dados` precisa caber em `settings.API_FICHA_MAX_KB` (padrão 512 KB) → acima disso, `413
  {"erro": "corpo_grande_demais"}`, nada é gravado.
- `item_pca`/`exercicio` sem `Processo` correspondente → `404 {"erro": "item_inexistente"}`.
- `versao` igual à atual (`0` para criar a primeira) → grava com `versao+1` e devolve `200` com a
  ficha gravada (mesmo formato do GET acima).
- `versao` DIFERENTE da atual → **nunca sobrescreve**: devolve `409 {"erro":
  "versao_desatualizada", "ficha": <ficha atual completa, mesmo formato do GET>}`.

## Tabela de erros

| Código | Situação | Corpo |
|---|---|---|
| 401 | Sem token, token inválido ou revogado | `{"erro": "nao_autenticado"}` |
| 403 | POST sem a permissão `pca.editar_pca`; `POST /vinculo` ou `PUT /ficha` sem `pode_instruir` | `{"erro": "sem_permissao"}` |
| 404 | `GET /processo` por `sei`/`item`+`exercicio` — reservado; hoje a rota nunca devolve 404 (lista vazia em `itens`, ver acima). `POST /coleta` com o processo sem NENHUM item vinculado no PCA | `{"erro": "processo_sem_item"}` |
| 404 | `GET`/`PUT /ficha` ou `POST /vinculo` sem o item/processo correspondente | `{"erro": "item_inexistente"}` |
| 400 | Corpo malformado (JSON inválido, campo obrigatório faltando ou de tipo errado) | `{"erro": "corpo_invalido", "detalhes": ["numero: campo obrigatório", "..."]}` |
| 409 | `GET /ficha` com `?sei=` em mais de um item | `{"erro": "sei_em_varios_itens", "itens": [...]}` |
| 409 | `PUT /ficha` com `versao` desatualizada | `{"erro": "versao_desatualizada", "ficha": {...}}` |
| 413 | Corpo acima do limite (`API_MAX_CORPO_MB`, padrão 10 MB — PDF em base64 pode ser grande, `POST /coleta`; `API_FICHA_MAX_KB`, padrão 512 KB, `PUT /ficha`) | `{"erro": "corpo_grande_demais"}` |
| 429 | Limite de 60 requisições/minuto por token excedido | `{"erro": "limite_requisicoes"}` |
| 500 | Falha interna ao montar/aplicar a coleta — nada é gravado (transação revertida) | `{"erro": "falha_interna"}` |

## Versionamento

Este documento descreve a **v1** do contrato (`/api/sei/...`). Qualquer mudança incompatível
(remover campo, mudar tipo, mudar significado) sobe para uma v2 num path novo
(`/api/v2/sei/...`), nunca quebrando v1 enquanto houver extensão publicada consumindo-a. Mudanças
aditivas (novo campo opcional, novo código de erro) podem entrar em v1 sem mudar o path.
