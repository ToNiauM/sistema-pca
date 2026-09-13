# ops/verificacao/ — harness de verificação visual/funcional

Scripts Node + Chrome DevTools Protocol (CDP): auth via `django.test.Client`,
Chromium headless real, medição de `getBoundingClientRect()`/
`getComputedStyle()` no DOM já hidratado.

## Pré-requisitos

1. Container `web` no ar na porta 12011: `docker compose up -d web`
   (rebuild antes se você mudou template/CSS/estático:
   `docker compose build web && docker compose up -d web`).
2. Chromium headless_shell instalado em
   `~/.cache/ms-playwright/chromium_headless_shell-1187/chrome-linux/headless_shell`
   — se faltar, reinstalar com
   `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-x64 npx playwright install chromium --with-deps`
   (o override é obrigatório neste host, Ubuntu 26.04, não suportado
   nativamente pelo Playwright — CLAUDE.md §3).
3. Node 18+ no host (usa `WebSocket` global e ESM nativo).

## Scripts

- **`_cdp.mjs`** — helper compartilhado: abre uma sessão CDP contra um
  Chromium headless novo, injeta o cookie de sessão (`django.test.Client
  ().force_login`, extraído de dentro do container via
  `docker compose exec`), manda `X-Forwarded-Proto: https` em toda
  requisição (o app roda atrás de proxy mesmo em dev) e expõe helpers
  (`evaluate`, `abrir`, `estabilizar`, `setViewport`, `screenshot`,
  `clicarEm`, `ligarCapturaDeRede`). Não é executado diretamente.

- **`matriz-telas.mjs`** — mede as 5 telas (dashboard, calendário, tabela,
  resumo por UO, análise) nas 9 larguras canônicas do `24.1-CONTEXT.md`
  (390/600/768/1024/1280/1440/1920 + 360/412 mobile) contra os 6 critérios
  objetivos: overflow horizontal zero, altura de `br-button` = `var(--
  button-small)` (exceto `shape="circle"`/`.pca-btn-segmento`), títulos de
  card ≤2 palavras centralizados, pares de cards na mesma linha alinhados
  no topo, canvas dos gráficos sangrado <768px, texto cortado (informativo,
  não bloqueia). Grava um JSON + um PNG por célula em
  `/tmp/.../scratchpad/24.1-02-evidencia/matriz/` (caminho fixo no script;
  ajuste `EVIDENCIA_DIR` se rodar em outra máquina) e um `_resumo.json`
  agregado.

  ```bash
  PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-x64 node ops/verificacao/matriz-telas.mjs
  ```

- **`interacoes.mjs`** — exercita as 6 interações do `24.1-02-PLAN.md`:
  drill-down de cada gráfico clicável (rosca de status, barras por UO,
  mês, trimestre, vencimento de contratos) comparando o valor do ponto
  clicado com `paginator.count` de `/tabela`; abertura do modal a partir de
  uma linha de Adiamentos/Top 10; troca do seletor de dimensão da Análise
  sem nenhuma requisição de rede; abertura/fechamento dos accordions do
  Perfil no mobile; filtros de data (`recebido_de/ate`,
  `vigencia_fim_de/ate`) com valor inválido sem 500; navegação pelas 6
  entradas do menu preservando `querystring_filtros`. Grava um JSON
  consolidado em `/tmp/.../scratchpad/24.1-02-evidencia/interacoes/
  resultado.json`.

  ```bash
  PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-x64 node ops/verificacao/interacoes.mjs
  ```

- **`hidratacao-casca.mjs`** (Quick 260907-eud) — teste-guarda da corrida de
  hidratação diagnosticada em
  `.planning/debug/graficos-e-header-somem-apos-navegacao.md`: abre `/`
  autenticado sob `Emulation.setCPUThrottlingRate(6)` +
  `Network.emulateNetworkConditions` (perfil Slow 3G — latência 400ms,
  download 50 KB/s) + `Network.setCacheDisabled(true)`. DUAS etapas,
  não uma (achado do orquestrador: sob Slow 3G a 50 KB/s, o
  `echarts.min.js` de ~1 MB sozinho leva dezenas de segundos, e medir
  antes de o loader Stencil registrar os componentes só mede o elemento
  CRU — visível por não ter FOUC-guard ainda, não por estar hidratado):
  - **Etapa 1** (espera a carga, teto 90s): poll de
    `document.readyState === "complete"` **e**
    `typeof document.querySelector('br-header')?.componentOnReady ===
    "function"` (prova que o runtime Stencil já registrou o componente).
    Se não chegar lá em 90s, sai 1 com mensagem explícita — isso é falha
    do HARNESS/rede, não necessariamente do app, e é dito como tal.
  - **Etapa 2** (só então mede, 10s/200ms): a mesma medição de sempre —
    `visibility`/`getBoundingClientRect().height`/`hydrated`/`shadowRoot`
    de `br-header`, `#nav-visoes` e do ancestral custom element mais
    próximo do primeiro `[data-echart]`.

  Critério de saída 0, avaliado só sobre a etapa 2: ao final dos 10s os
  três visíveis com altura > 0, e nenhum TERMINOU a fase com `shadowRoot`
  montado e a classe `hydrated` ausente (o sintoma persistente — corrida
  perdida e ninguém esperando o componente). O tamanho da maior janela
  ruim (`*_janela_max_ms`) é gravado como informativo, não como critério:
  sob CPU 6x + 50 KB/s a hidratação do header levou 4,4s e a do menu 7,2s
  na 1ª medição real (Quick 260907-eud), atraso inerente ao download
  serial dos chunks lazy do DS. Grava a série temporal completa das duas
  etapas em JSON em `EVIDENCIA_DIR` (variável de ambiente; default
  `os.tmpdir()/pca-cfc-hidratacao-casca` — ajuste para
  rodar em outra máquina/sessão).

  ```bash
  PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-x64 node ops/verificacao/hidratacao-casca.mjs
  ```

## Convenções

- Nenhum dos scripts decide design: uma célula/interação que "parece
  errada" mas não viola nenhum critério documentado vira item do
  `24.1-visual-findings.md`, não é corrigida aqui.
- Os scripts saem com código 1 se alguma célula/interação/medição falhar
  um critério bloqueante (overflow, botão, drill-down incoerente, request
  de rede indevido, 500, elemento sem hidratar dentro do prazo), e 0 caso
  contrário — usável em CI futuro, se este projeto vier a ter um.
