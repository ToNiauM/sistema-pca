# Glossário

O vocabulário de domínio abaixo (siglas de setores internos e sistemas de publicação) é herdado
do órgão onde este sistema nasceu — permanece no código como nome de campo, comentário e rótulo
de tela porque trocá-lo exigiria migração e renomeação ampla, fora do escopo desta versão inicial.
**Nenhum desses termos é código de outro órgão: é vocabulário.** Adaptar este sistema a outra
instituição não exige alterar `apps/catalogo` nem `apps/pca` — só importar uma planilha (ou
cadastrar pelo Django Admin) com os valores do novo órgão.

| Termo | Significado neste sistema |
|---|---|
| **Gelic** | Setor interno do órgão de origem que recebe os processos para a etapa seguinte do funil de contratação. Aparece como `Processo.data_envio_gelic`/`data_recebimento_gelic` (`apps/pca/models.py`) — a entrega e o recebimento por esse setor são dois dos fatos que `apps/pca/regras_situacao.py` usa para derivar automaticamente a `situacao` do processo (ex.: recebimento preenchido ⇒ "em tramitação"). |
| **Delic** | Nome anterior do mesmo setor hoje chamado de Gelic no schema atual — sobrevive só em comentários de código e em um título de seção do relatório de conferência de import (`apps/pca/importacao/relatorio.py`), não em nenhum campo de model. Um órgão diferente pode ter (ou não) um setor equivalente; o nome não é normativo. |
| **SEI** | Sistema Eletrônico de Informações — o número de processo administrativo eletrônico associado a um item do PCA. Modelado como relação 1:N (`ProcessoSEI`, `apps/pca/models.py`): uma célula de planilha podia carregar 0, 1 ou vários números SEI para o mesmo item. |
| **SPW** | Sistema interno de publicação/registro de contratos do órgão de origem — `Processo.data_lancamento_spw` marca quando o item foi lançado nesse sistema. O nome não é expandido no código-fonte deste repositório; cada instalação pode reaproveitar o campo apontando para seu próprio sistema equivalente, ou simplesmente não preenchê-lo (é opcional/nullable). |
| **WordPress** | O site público de transparência do órgão de origem, construído sobre WordPress — `Processo.data_lancamento_wordpress` marca a publicação nesse canal. Qualquer CMS equivalente de outra instituição pode reaproveitar o mesmo campo. |
| **Dados Abertos** | Portal/canal de dados abertos do órgão de origem — `Processo.data_lancamento_dados_abertos` marca a publicação nesse canal (Lei de Acesso à Informação e política de dados abertos do setor público). |
| **PNCP** | Portal Nacional de Contratações Públicas (Lei 14.133/2021) — a "ficha PNCP" citada em comentários de `apps/pca/views_processo.py`/`apps/pca/relatorio_movimentacao.py` é o nome interno da tela de detalhe do processo (`pca:detalhe_processo`), não uma integração real com o portal: o sistema não envia nem recebe dados do PNCP automaticamente neste MVP. |
| **PCA** | Plano de Contratações Anual (Lei 14.133/2021, art. 12) — o documento que todo órgão público sujeito à lei elabora anualmente; este sistema existe para acompanhar sua execução. |
| **Exercício** | O ano de vigência de um PCA (`apps.catalogo.models.Exercicio`) — cada ano tem seu próprio conjunto de processos, isolados por `UniqueConstraint(exercicio, item_pca)`. |

## Catálogo é dado, não código

O catálogo de Unidades Organizacionais, Tipos, Categorias, Graus de Prioridade, Classificações,
Modalidades, Instrumentos Contratuais e Situações Normalizadas (`apps/catalogo/models.py`, 8
tabelas que herdam `DominioBase`) **é dado, carregado pela importação da planilha ou cadastrado
pelo Django Admin — não código.** Adaptar este sistema a outro órgão não exige alterar
`apps/catalogo`: basta importar uma planilha (ou cadastrar manualmente) com os valores do novo
órgão. O mesmo vale para o vocabulário Gelic/SEI/SPW/WordPress/Dados Abertos acima: são nomes de
campo e de rótulo de tela, não integrações obrigatórias — um órgão sem um SPW equivalente
simplesmente deixa o campo em branco.

**Fontes verificadas:** `apps/pca/models.py` (campos `data_envio_gelic`,
`data_recebimento_gelic`, `data_lancamento_spw`, `data_lancamento_wordpress`,
`data_lancamento_dados_abertos`, `ProcessoSEI`), `apps/pca/importacao/relatorio.py` (título
"Entrega ao Delic"), `apps/pca/views_processo.py`/`apps/pca/relatorio_movimentacao.py`
(comentários "ficha PNCP"), `apps/catalogo/models.py` (`DominioBase` e as 8 subclasses).

!!! note "Nota de rastreabilidade"
    O termo "Projur" citado no briefing original desta documentação não foi encontrado em
    nenhum arquivo do código deste repositório (`grep -rn Projur apps/ core/` não retorna
    nenhuma ocorrência) — por isso não aparece na tabela acima. Documentar um termo sem
    comprová-lo no código violaria o requisito de rastreabilidade desta fase (nenhuma afirmação
    presumida).
