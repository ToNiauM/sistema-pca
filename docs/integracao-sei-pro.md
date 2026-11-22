# Integração do PCA com as extensões SEI Pro (sem robô)

Plano escrito em 2026-10-09, na sessão que criou as extensões **SEI Pro Gelic** e **SEI Pro CFC**
(repositório `/home/ToNiauM/dev/sei-pro`, privado `github.com/ToNiauM/sei-pro-gelic`; retomada em
`docs/gelic/notas internas de lá). Este arquivo é o ponto de partida do lado do PCA.

## Decisões do usuário

- O **branch `gera`** (`~/ativos/pca-cfc-gera`, app `apps/gera`, fases 42–47) **será descontinuado**:
  a construção das peças (DFD, TR, mapa de preços, memorando ao Delic, termos) passou para a extensão
  **SEI Pro CFC**, com paridade com o motor `apps/gera/motor/preencher.py`. As fases 44–47 do gera não
  devem continuar aqui.
- O **sistema do PCA** (`pca.sistemascfc.org`, branch `teste`) continua como base dos dados do PCA.
  *Confirmar com o usuário antes de começar.*
- O **robô SEI** (`apps/pca/sei/`, serviço `robo`, Playwright, login da Gelic em `SEI_USUARIO/SEI_SENHA`)
  deve ser **aposentado**. Hoje ele faz força bruta: entra no SEI com senha guardada no servidor e varre
  os processos. A extensão já está dentro do SEI na sessão de quem trabalha, então ela informa o PCA.

## O que o robô faz hoje (a ser substituído)

- Para cada `ProcessoSEI.numero_sei` lê a árvore, o histórico e o contrato (`coletor.py`, `extracao.py`).
- `regras.propor()` propõe 5 campos: `data_assinatura_contrato`, `numero_instrumento_contratual`,
  `instrumento_contratual`, `valor_contratado`, `data_recebimento_gelic`. `aplicador.aplicar()` grava por
  `services.registrar_acompanhamento` e marca CONCLUIDO quando o contrato tem as duas assinaturas.
- Também atualiza `Processo.unidade_sei_atual` / `unidade_sei_atual_desde`.
- Guarda as coletas em JSON (`data/sei/`), roda por cron (`sei_sincronizar`) e pelo admin (`sei_atender`).

## Desenho proposto

```
SEI (navegador de quem trabalha) → extensão calcula a etapa da Gelic e lê o contrato, o valor e a unidade
        │  POST com fatos e evidência (nº SEI do documento de onde saiu cada valor)
        ▼
PCA (Django): API JSON pequena, token pessoal → regras.propor / aplicador já existentes
```

### API (JSON, sem DRF se não precisar)

| Método | Rota | Para quê |
|---|---|---|
| GET | `/api/sei/processo?sei=<protocolo>` | item(ns) do PCA ligado(s) ao processo: `item_pca`, `exercicio`, `descricao_objeto`, `valor_estimado`, `unidade`, `grau_prioridade`, `mes_previsto`, `situacao`. Usado pelo DFD do SEI Pro CFC (gancho `GANCHOS_CFC.dadosDoPca`) e pelo item A04 do checklist da Gelic ("demanda fora do PCA") |
| POST | `/api/sei/observacoes` | a extensão informa: `{protocolo, etapa (id do rito da Gelic), unidade_atual, observado_em, campos: {data_assinatura_contrato?, numero_instrumento_contratual?, instrumento_contratual?, valor_contratado?, data_recebimento_gelic?}, evidencias: {campo: {sei, trecho?}}}`. O PCA aplica com as regras do robô, como **proposta a confirmar** ou direto (configurável) |
| GET | `/api/sei/saude` | versão da API, para a extensão saber se pode usar |

- **Autenticação:** token pessoal por usuário (gerado na página do usuário no PCA, guardado como hash),
  enviado em `Authorization: Bearer`. Nada de senha do SEI.
- **CORS:** só as origens `chrome-extension://<id>` das duas extensões (listadas em settings); responder
  `OPTIONS`. Rate limit simples por token.
- **Auditoria:** cada observação vira `Acompanhamento` com origem "extensão", o usuário do token e as
  evidências; nunca apagar dado manual (respeitar `situacao_manual`).
- **Idempotência:** a mesma observação (protocolo + campos iguais) não gera novo acompanhamento.
- **MCP (depois):** expor as ferramentas do assistente (fase 39: `consultar_processos`, `ficha`,
  `contratos_a_vencer`…) como servidor MCP, por cima da mesma camada, para o Agente de IA das
  extensões perguntar ao PCA.

### Lado da extensão (repositório sei-pro)

- `GANCHOS_CFC.dadosDoPca` (já existe, vazio) passa a chamar o GET para pré-preencher o DFD.
- Um módulo novo envia o POST quando um processo ligado ao PCA é aberto (o selo já calcula a etapa) e um
  botão "Atualizar PCA" no Controle de Processos faz em lote os processos visíveis, como o "Calcular
  etapas".
- Endereço da API e token ficam nas opções da extensão; sem eles, nada é enviado.

## Limite e transição

- Processo que ninguém abre não atualiza sozinho. O botão em lote cobre isso. Se for preciso atualizar
  tudo de madrugada, manter o robô só para esse caso, bem mais leve, até a equipe se acostumar.
- Ordem: (1) API + testes aqui; (2) módulo na extensão; (3) rodar os dois em paralelo e comparar
  propostas; (4) desligar o `robo` e remover `SEI_USUARIO/SEI_SENHA` do `.env`.

## Perguntas em aberto para o usuário

1. O sistema do PCA continua (só o gera é descontinuado)?
2. Aplicar as observações direto ou como proposta para confirmar?
3. O DFD deve sair do item do PCA pelo `item_pca` informado pelo demandante ou pelo processo SEI já
   ligado?
