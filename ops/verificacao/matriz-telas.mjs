// matriz visual das telas x larguras canônicas via CDP; grava JSON + screenshot
// por célula em ops/verificacao/_evidencia/matriz/
// uso: node ops/verificacao/matriz-telas.mjs
import { mkdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { obterSessao, abrirSessaoCDP, LARGURAS_CANONICAS, TELAS } from "./_cdp.mjs";

// caminho relativo ao próprio script; cada execução grava por cima da anterior
const EVIDENCIA_DIR = fileURLToPath(new URL("./_evidencia/matriz", import.meta.url));
mkdirSync(EVIDENCIA_DIR, { recursive: true });

// função executada dentro do navegador: mede os critérios contra o DOM/CSS renderizado
const MEDIR_CELULA_JS = `(() => {
  const doc = document.documentElement;
  const viewportWidth = window.innerWidth;
  const resultado = {};

  // 1. Overflow horizontal — zero em qualquer largura.
  resultado.overflow = {
    scrollWidth: doc.scrollWidth,
    clientWidth: doc.clientWidth,
    passou: doc.scrollWidth === doc.clientWidth,
  };

  // 2. altura de botão — var(--button-small), exceto shape=circle e .pca-btn-segmento
  let alturaEsperada = 32; // fallback: 32px de altura padrão do botão
  const algumBotao = document.querySelector("br-button");
  if (algumBotao) {
    const valorVar = getComputedStyle(algumBotao).getPropertyValue("--button-small").trim();
    if (valorVar) {
      const probe = document.createElement("div");
      probe.style.cssText = "position:absolute;visibility:hidden;height:" + valorVar + ";width:0;";
      document.body.appendChild(probe);
      const medido = probe.getBoundingClientRect().height;
      probe.remove();
      if (medido > 0) alturaEsperada = medido;
    }
  }

  const botoes = [];
  document.querySelectorAll("br-button, a.br-button").forEach((el) => {
    let altura = null;
    if (el.tagName === "BR-BUTTON") {
      const part = el.shadowRoot && el.shadowRoot.querySelector('[part="button"]');
      if (part) altura = part.getBoundingClientRect().height;
    } else {
      altura = el.getBoundingClientRect().height;
    }
    if (altura === null || altura === 0) return; // não hidratado/oculto — ignora
    const excecaoCircle = el.getAttribute && el.getAttribute("shape") === "circle";
    const excecaoSegmento = el.classList.contains("pca-btn-segmento");
    const dentroDoPadrao = Math.abs(altura - alturaEsperada) <= 1;
    botoes.push({
      classes: el.className,
      tag: el.tagName.toLowerCase(),
      altura,
      excecaoCircle,
      excecaoSegmento,
      passou: dentroDoPadrao || excecaoCircle || (excecaoSegmento && altura <= alturaEsperada + 1),
    });
  });
  resultado.botoes = { alturaEsperada, itens: botoes, passou: botoes.every((b) => b.passou) };

  // 3. títulos de card <=2 palavras centralizados
  const titulos = [];
  document.querySelectorAll("br-card.module > div.text-uppercase.text-center").forEach((tit) => {
    const texto = tit.textContent.trim();
    const palavras = texto.split(/\\s+/).filter(Boolean);
    if (palavras.length > 2) return;
    const card = tit.closest("br-card.module");
    const rCard = card.getBoundingClientRect();
    const rTit = tit.getBoundingClientRect();
    const centroCard = rCard.left + rCard.width / 2;
    const centroTit = rTit.left + rTit.width / 2;
    titulos.push({
      texto,
      centroCard,
      centroTit,
      diff: Math.abs(centroCard - centroTit),
      passou: Math.abs(centroCard - centroTit) <= 2,
    });
  });
  resultado.titulos = { itens: titulos, passou: titulos.every((t) => t.passou) };

  // 4. pares de cards na mesma linha alinhados no topo (md e acima)
  const PARES = [
    ["Status", "Por UO"],
    ["Top 10", "Trimestral"],
    ["Adiamentos", "Vencimentos"],
  ];
  const tituloParaCard = {};
  document.querySelectorAll("br-card.module > div.text-uppercase.text-center").forEach((tit) => {
    tituloParaCard[tit.textContent.trim()] = tit.closest("br-card.module");
  });
  const pares = [];
  for (const [a, b] of PARES) {
    const ca = tituloParaCard[a];
    const cb = tituloParaCard[b];
    if (!ca || !cb) continue;
    const ra = ca.getBoundingClientRect();
    const rb = cb.getBoundingClientRect();
    const ladoALado = ra.right <= rb.left + 4 || rb.right <= ra.left + 4;
    pares.push({
      par: a + " / " + b,
      topA: ra.top,
      topB: rb.top,
      ladoALado,
      // só reprova se lado a lado e topo divergir
      passou: !ladoALado || Math.abs(ra.top - rb.top) <= 1,
    });
  }
  resultado.pares = { itens: pares, passou: pares.every((p) => p.passou) };

  // 5. canvas dos gráficos sangrado (left=0, width=viewport) abaixo de 768px
  const canvases = [];
  if (viewportWidth < 768) {
    document.querySelectorAll(".pca-dashboard-layout br-card.module [data-echart] canvas, .pca-col-span-md-12.module [data-echart] canvas, .pca-col-span-md-6.module [data-echart] canvas").forEach((c) => {
      const r = c.getBoundingClientRect();
      const donoId = c.closest("[data-echart]").id;
      canvases.push({
        id: donoId,
        left: r.left,
        width: r.width,
        viewportWidth,
        passou: Math.abs(r.left) <= 1 && Math.abs(r.width - viewportWidth) <= 1,
      });
    });
  }
  resultado.canvasSangrado = { itens: canvases, passou: canvases.every((c) => c.passou), aplicavel: viewportWidth < 768 };

  // 6. nenhum texto cortado por overflow interno (exclui scroll intencional)
  const cortados = [];
  document.querySelectorAll("body *").forEach((el) => {
    if (el.children.length > 0) return; // só folhas de texto
    if (!el.textContent || !el.textContent.trim()) return;
    const cs = getComputedStyle(el);
    if (cs.overflowX === "auto" || cs.overflowX === "scroll") return;
    if (el.scrollWidth > el.clientWidth + 2 && el.clientWidth > 0) {
      cortados.push({ texto: el.textContent.trim().slice(0, 60), classes: el.className, scrollWidth: el.scrollWidth, clientWidth: el.clientWidth });
    }
  });
  resultado.textoCortado = { itens: cortados.slice(0, 20), passou: cortados.length === 0 };

  // textoCortado é informativo -- não bloqueia passouTudo, exige leitura humana
  resultado.passouTudo =
    resultado.overflow.passou &&
    resultado.botoes.passou &&
    resultado.titulos.passou &&
    resultado.pares.passou &&
    resultado.canvasSangrado.passou;
  return resultado;
})()`;

async function main() {
  console.log("Obtendo cookie de sessão...");
  const sessao = obterSessao();
  console.log("Abrindo Chromium headless...");
  const cdp = await abrirSessaoCDP(sessao);

  const resultados = [];
  let falhas = 0;

  for (const tela of TELAS) {
    for (const largura of LARGURAS_CANONICAS) {
      const nomeCelula = `${tela.nome}-${largura}`;
      try {
        await cdp.setViewport(largura);
        await cdp.abrir(tela.url === "/" ? "http://127.0.0.1:12011/" : `http://127.0.0.1:12011${tela.url}`);
        await cdp.estabilizar(900);
        // espera adicional por canvas quando a tela tem gráfico (dashboard/análise)
        if (tela.nome === "dashboard" || tela.nome === "analise") {
          await cdp.esperar(400);
        }
        const medida = await cdp.evaluate(MEDIR_CELULA_JS);
        writeFileSync(`${EVIDENCIA_DIR}/${nomeCelula}.json`, JSON.stringify(medida, null, 2));
        await cdp.screenshot(`${EVIDENCIA_DIR}/${nomeCelula}.png`);
        resultados.push({ tela: tela.nome, largura, passou: medida.passouTudo, medida });
        if (!medida.passouTudo) {
          falhas++;
          console.log(`FALHOU: ${nomeCelula}`, JSON.stringify({
            overflow: medida.overflow.passou,
            botoes: medida.botoes.passou,
            titulos: medida.titulos.passou,
            pares: medida.pares.passou,
            canvasSangrado: medida.canvasSangrado.passou,
            textoCortado: medida.textoCortado.passou,
          }));
        } else {
          console.log(`OK: ${nomeCelula}`);
        }
      } catch (e) {
        falhas++;
        console.log(`ERRO em ${nomeCelula}:`, e.message);
        resultados.push({ tela: tela.nome, largura, passou: false, erro: e.message });
      }
    }
  }

  writeFileSync(`${EVIDENCIA_DIR}/_resumo.json`, JSON.stringify(resultados, null, 2));
  console.log(`\nTotal de células: ${resultados.length}, falhas: ${falhas}`);
  cdp.fechar();
  process.exit(falhas > 0 ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
