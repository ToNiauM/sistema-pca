# Prints do manual do usuário

Regera as imagens de `manual/docs/img/` a partir de uma **cópia mascarada** do banco, servida por
uma instância **descartável** da casca oficial DSGov (gov.br, `PCA_DESIGN=dsgov`). Este README não é publicado (fica fora de
`manual/docs/`).

## Pré-requisitos

- O serviço `web` do compose no ar (é dele que sai a cópia do banco, só por leitura).
- As imagens locais `toniaum/pca-cfc:dev` (instância descartável) e `toniaum/pca-cfc-robo:dev`
  (Playwright + Chromium). Nada é instalado nem baixado (`--pull never`).

## Como rodar

Da raiz do repositório:

```
bash manual/capturas/capturar.sh                      # todas as cenas
bash manual/capturas/capturar.sh --cenas a03-inicio   # só algumas (ids separados por vírgula)
bash manual/capturas/capturar.sh --manter             # deixa a instância e os textos para conferir
bash manual/capturas/capturar.sh --derrubar           # limpa o que o --manter deixou
```

O script: copia o banco do `web` (`sqlite3` backup com a origem em modo leitura) para um diretório
temporário fora do repositório; sobe `pca-manual-web` em `127.0.0.1:12090-12099` com um ambiente
próprio (nunca o `.env` do projeto: SECRET_KEY aleatória, SEI fictício, Assistente desligado); roda
`preparar.py` (máscara, personas, solicitações de exemplo) e `capturar.py` (prints, textos, conferência
de vazamento); copia os PNGs para `manual/docs/img/<parte>/` só se a conferência passar; e remove
container, cópia e ambiente ao final.

Depois de rodar, **abra cada PNG novo** antes de commitar: o site é público.

## Nomes extras

`~/.config/pca-manual/nomes-extras.txt` (fora do repositório, `chmod 600`, NUNCA versionar): um nome
de pessoa por linha, para nomes que aparecem em textos livres e não são de usuários do sistema. O
`preparar.py` imprime na tela os "candidatos a nome" que sobraram depois da máscara; todo nome de
pessoa física da lista vai para esse arquivo e roda-se de novo.

## Guardas

- `preparar.py` só roda com `PCA_MANUAL_DESCARTAVEL=1`, banco em `/app/data/db.sqlite3` e a marca
  `/app/data/.copia-descartavel-manual` (que só existe na cópia); recusa rodar duas vezes.
- `capturar.py` sai 1 se o texto de alguma cena trouxer nome real, fornecedor com nome de pessoa
  física ou e-mail fora de `@example.org` — e então nada é copiado para o repositório.
- Nunca capturar "Sobre o sistema", Administração ou "Meu perfil".

## Casca

Os prints são da casca **oficial DSGov** (gov.br, `PCA_DESIGN=dsgov`). O menu lateral (`br-menu`) começa
fechado: as cenas de menu o abrem pelo botão ☰ (`#navigation`). Listas de escolha são `br-select`
(input de exibição + rádios): use a ação `_escolher(campo, valor)`; caixas e rádios são marcados
pelo rótulo (`marcar`).

## Acrescentar uma cena

Em `capturar.py`, acrescente uma entrada ao dicionário `CENAS`: `parte` (`areas`/`diretoria`),
`persona` (`ana` solicitante, `bruno` leitura, `carla` equipe do PCA, `daniel` diretoria, `eva`
primeiro acesso, `None` sem login), `url` (chave de `cenario["urls"]`, caminho começando com `/` ou
função que recebe o cenário), `acoes` (só abrir/preencher, nunca enviar), `recorte` (`None` = tela,
`"pagina"` = página inteira, seletor CSS = só o elemento) e `legenda`. Depois use o PNG na página do
manual com `<figure markdown="span">` e `<figcaption>`.

## Cenas

Personas (fictícias, criadas na cópia): `ana` (unidade/solicitante, ligada à unidade com mais itens
que aceitam pedido de prazo e valor), `bruno` (leitura), `carla` (equipe do PCA), `daniel`
(diretoria) e `eva` (solicitante no primeiro acesso). As solicitações de exemplo (em análise,
aprovada, aprovada com ajuste, recusada, desistida, prejudicada, cancelamento e inclusões) são
criadas pelos serviços de `apps.solicitacoes` em `preparar.py::semear_solicitacoes`.

| Cena | Persona | Tela |
|---|---|---|
| `a01-entrar` | — | Tela de entrada (recorte) |
| `a02-primeiro-acesso` | eva | Troca de senha obrigatória |
| `a03-inicio` | ana | Página inicial |
| `a04-menu` | ana | Menu (☰) aberto, com Análises e Solicitações abertas (recorte) |
| `a05-processos` | ana | Processos filtrados pela unidade |
| `a06-ficha` | ana | Ficha do item com Solicitar alteração |
| `a07-ficha-solicitacoes` | ana | Aba Solicitações da ficha (recorte) |
| `a08-resumo-unidade` | ana | Resumo por unidade |
| `a09-painel` | ana | Análises → Painel |
| `a10-nova` | ana | Nova solicitação (escolha) |
| `a11-nova-alteracao` | ana | Pedido de prazo e valor preenchido |
| `a12-nova-cancelamento` | ana | Bloco Cancelamento marcado (recorte) |
| `a13-nova-inclusao` | ana | Pedido de inclusão preenchido |
| `a14-minhas` | ana | Minhas solicitações |
| `a15-detalhe-em-analise` | ana | Solicitação em análise (fora do exercício) |
| `a16-detalhe-decidida` | ana | Solicitação aprovada + aprovada com ajuste |
| `a17-menu-leitura` | bruno | Menu do perfil de leitura (recorte) |
| `d01-inicio-pendencias` | daniel | Página inicial com o aviso de pendências |
| `d02-menu-para-avaliar` | daniel | Menu com Para avaliar (N) (recorte) |
| `d03-para-avaliar` | daniel | Fila Para avaliar da diretoria |
| `d04-para-avaliar-equipe` | carla | Fila Para avaliar da equipe |
| `d05-avaliar-ajuste` | daniel | Parte de valor com Aprovar com ajuste preenchido (recorte) |
| `d06-avaliar-inclusao` | daniel | Inclusão em análise (só aprovar/recusar) |
| `d07-inclusao-aprovada` | daniel | Inclusão aprovada |
| `d08-item-incluido` | daniel | Ficha do item criado |
| `d09-historico` | carla | Aba Acompanhamentos da ficha com o prazo aprovado (recorte) |
| `d10-prejudicada` | daniel | Solicitação prejudicada |
| `d11-todas` | daniel | Todas as solicitações |
| `d12-relatorio-solicitacoes` | carla | Seção 6 do relatório da reunião (faixa) |
| `d13-analises` | daniel | Painel com o menu aberto em Análises (Fluxo de caixa, Estatísticas) |
