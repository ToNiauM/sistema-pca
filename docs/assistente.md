# Assistente do PCA

O Assistente é um chat, dentro do próprio sistema, que responde perguntas sobre o Plano de
Contratações Anual usando **só** os dados que o sistema já tem — nunca conhecimento externo,
nunca opinião jurídica. Toda resposta é fundamentada em ferramentas que consultam o banco com
as **mesmas permissões de quem pergunta**: quem não vê acompanhamentos ou análises na tela
também não recebe esse conteúdo do Assistente.

## O que ele faz

Responde perguntas em português sobre processos, prazos, contratos, fluxo de caixa e a
documentação oficial do sistema, sempre citando de onde veio a informação (referências e
data de atualidade). Não decide nada, não escreve nada no PCA — é **somente leitura**.

## Como perguntar

Escreva a pergunta como faria para uma pessoa da equipe. Alguns exemplos:

- "Quantos itens da Gecont estão atrasados?"
- "Quem assinou o contrato da Sollo e em que dia?"
- "O que ficou combinado em julho sobre o item 42?"
- "Como registro um acompanhamento?"
- "O que foi atualizado hoje?" / "O que mudou ontem?"
- "Quais itens estão sem processo SEI?"

O Assistente entende o exercício da página atual, mas você pode informar outro ano na própria
pergunta ("no PCA de 2025..."). Ao enviar, a caixa mostra "Digitando…" e a resposta entra na
conversa sem recarregar a página. No celular, a caixa de escrita fica presa ao rodapé da tela
enquanto a conversa rola por cima dela, como nos aplicativos de mensagem (WhatsApp/Telegram).
Em telas maiores, a conversa fica numa coluna central de leitura, sem esticar de borda a borda.
No teclado, **Enter** envia a pergunta e **Alt+Enter** (ou Shift+Enter) quebra linha sem enviar;
a caixa cresce com o texto até um teto. No toque (celular/tablet), Enter nunca envia — só o
botão de enviar.

## De onde vêm as respostas

O Assistente usa sete ferramentas, cada uma batendo direto no banco ou nos arquivos da
sincronização com o SEI — nunca "sql livre" e nunca um modelo de linguagem inventando números:

- **Consulta de processos** — número, situação, prazo e link, igual à tela Processos; também
  filtra por categoria do objeto (Material, Serviços ou Solução de TIC), para perguntas do
  tipo "o que é compra e o que é serviço", e pelos itens **sem processo SEI** (sem nenhum nº
  SEI cadastrado — esses itens nunca recebem atualização automática; tudo neles é lançado
  pela equipe).
- **Atualizações recentes** — o que mudou em cada item num dia ("hoje", "ontem", uma data) ou
  nos últimos N dias: o campo alterado (antes → depois), a origem (equipe, sincronização com o
  SEI ou acompanhamento) e o horário, lido do histórico de alterações.
- **Ficha do item** — campos públicos, instrumentos contratuais, signatários e, com permissão,
  os últimos acompanhamentos registrados nas reuniões.
- **Fluxo de caixa**, **contratos a vencer** e **memória de cálculo** — os mesmos números das
  telas de Análises, para quem tem a permissão de ver análises estratégicas.
- **Busca em texto livre** — acompanhamentos de reunião, o corpo dos instrumentos já coletados
  do SEI (contrato, termo aditivo, apostilamento) e esta própria documentação, por proximidade
  de significado (embeddings), não por palavra exata.

## Atualidade

Toda resposta termina com um rodapé de atualidade: "PCA consultado em ... · SEI: ... ·
Textos indexados em ...". A coleta do SEI **não é ao vivo** — é diária (sincronização automática
com o SEI) ou sob demanda (manual), então o rodapé sempre diz quando cada fonte foi consultada pela última
vez, nunca finge que é "agora" quando não é. Quando alguma parte da resposta vem do SEI, o
Assistente avisa: "Esta resposta reflete a coleta disponível; confira alterações posteriores
no documento do SEI."

O Assistente **reconsulta o PCA a cada pergunta**: uma edição feita agora num item (situação,
valor, acompanhamento) aparece já na próxima pergunta, mesmo dentro da mesma conversa — as
respostas anteriores servem só de contexto, nunca de fonte. Já os **textos** (acompanhamentos,
contratos/aditivos do SEI e documentação) entram na busca por assunto somente depois da
reindexação — automática toda manhã, após a sincronização com o SEI, ou manual pela ação
"Reindexar assistente" no Admin (superusuário). O rodapé "Textos indexados em" diz de quando
é essa foto.

## Limites

- Até 50 perguntas por usuário por dia (o limite renova à meia-noite).
- Até 1.000 caracteres por pergunta.
- Até 10 trocas de pergunta/resposta guardadas por conversa.
- A resposta pode levar até 90 segundos — não há streaming (a resposta aparece inteira, não
  palavra por palavra).

## O que ele não faz

- Não registra, edita nem apaga nada no PCA — quem grava é sempre uma pessoa, pela tela.
- Não dá opinião jurídica sobre prorrogação, licitação ou validade de contrato.
- Não acessa o SEI ao vivo — só o que a sincronização com o SEI já coletou.
- Não indexa o documento de requisitos, planilhas de trabalho nem a documentação técnica interna (arquitetura,
  deployment, operação) — só esta página e a "Sobre o sistema".

## Privacidade

A conversa é temporária: some no logout, ao abrir "Nova conversa" ou quando expira. O
provedor de IA (OpenAI) é usado com `store=False` na chamada — isso é um limite factual sobre
o que o sistema pede ao provedor, não uma promessa de retenção zero do lado dele. Nomes de
signatários de instrumentos contratuais públicos podem aparecer nas respostas (são dados
públicos do processo); e-mails de contas de usuário do sistema nunca aparecem.

## Como registro um acompanhamento?

O Assistente **não registra acompanhamento por você** — ele só lê e explica. Para registrar,
abra a tela Processos, entre na ficha do item e use o botão "Registrar acompanhamento"
(exige a permissão de editar o PCA). É a mesma ação de sempre, feita na tela, não no chat.
