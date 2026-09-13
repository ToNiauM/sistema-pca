// helper CDP compartilhado por matriz-telas.mjs e interacoes.mjs: conexão
// WebSocket/Chrome DevTools Protocol, para não duplicar código entre os dois
// requisitos: container web na porta 12011, Chromium headless_shell instalado
// VERIFICACAO_REPO_DIR: diretório onde rodar docker compose exec (default: cwd)
import { spawn } from "node:child_process";
import { execFileSync } from "node:child_process";

export const BASE = "http://127.0.0.1:12011";
const BIN = `${process.env.HOME}/.cache/ms-playwright/chromium_headless_shell-1187/chrome-linux/headless_shell`;

/** Extrai o cookie de sessão autenticando via django.test.Client dentro do container de dev. */
export function obterSessao() {
  const py = [
    "import django",
    "django.setup()",
    "from django.test import Client",
    "from django.contrib.auth import get_user_model",
    "U = get_user_model()",
    "u = U.objects.filter(is_superuser=True).first() or U.objects.first()",
    "c = Client()",
    "c.force_login(u)",
    "print(c.cookies['sessionid'].value)",
  ].join("\n");
  const out = execFileSync(
    "docker",
    [
      "compose", "exec", "-T",
      "-e", "DJANGO_SETTINGS_MODULE=config.settings.dev",
      "-e", "SECURE_SSL_REDIRECT=false",
      "web", "python", "-c", py,
    ],
    { cwd: process.env.VERIFICACAO_REPO_DIR || process.cwd(), encoding: "utf8" }
  );
  return out.trim();
}

/** Abre uma sessão CDP contra um Chromium headless novo, autenticada com o
 * cookie de sessão informado. Retorna helpers (evaluate/abrir/esperar/
 * screenshot/click) e uma função `fechar()` para encerrar o processo. */
export async function abrirSessaoCDP(sessionCookie) {
  const proc = spawn(
    BIN,
    ["--headless", "--no-sandbox", "--disable-gpu", "--remote-debugging-port=0", "--hide-scrollbars", "about:blank"],
    { stdio: ["ignore", "ignore", "pipe"] }
  );
  const wsUrl = await new Promise((res, rej) => {
    let buf = "";
    proc.stderr.on("data", (d) => {
      buf += d;
      const m = buf.match(/DevTools listening on (ws:\/\/\S+)/);
      if (m) res(m[1]);
    });
    proc.on("exit", (c) => rej(new Error("chrome saiu: " + c + "\n" + buf)));
    setTimeout(() => rej(new Error("timeout devtools\n" + buf)), 15000);
  });
  const ws = new WebSocket(wsUrl);
  await new Promise((r) => (ws.onopen = r));
  let id = 0;
  const pend = new Map();
  const waiters = [];
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pend.has(msg.id)) {
      const { res, rej } = pend.get(msg.id);
      pend.delete(msg.id);
      msg.error ? rej(new Error(JSON.stringify(msg.error))) : res(msg.result);
    } else if (msg.method) {
      for (const w of [...waiters]) {
        if (w.method === msg.method && (!w.sessionId || w.sessionId === msg.sessionId)) {
          waiters.splice(waiters.indexOf(w), 1);
          w.res(msg.params);
        }
      }
    }
  };
  const send = (method, params = {}, sessionId) =>
    new Promise((res, rej) => {
      const i = ++id;
      pend.set(i, { res, rej });
      ws.send(JSON.stringify({ id: i, method, params, sessionId }));
    });
  const waitFor = (method, sessionId) => new Promise((res) => waiters.push({ method, sessionId, res }));

  const { targetId } = await send("Target.createTarget", { url: "about:blank" });
  const { sessionId: sid } = await send("Target.attachToTarget", { targetId, flatten: true });
  await send("Page.enable", {}, sid);
  await send("Runtime.enable", {}, sid);
  await send("Network.enable", {}, sid);
  await send("Network.setExtraHTTPHeaders", { headers: { "X-Forwarded-Proto": "https" } }, sid);
  await send("Network.setCookie", { name: "sessionid", value: sessionCookie, domain: "127.0.0.1", path: "/", secure: false }, sid);

  const evaluate = async (expr) => {
    const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true }, sid);
    if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails));
    return r.result.value;
  };
  const abrir = async (url) => {
    const p = waitFor("Page.loadEventFired", sid);
    await send("Page.navigate", { url }, sid);
    await p;
  };
  const esperar = (ms) => new Promise((r) => setTimeout(r, ms));
  const estabilizar = async (ms = 900) => {
    await evaluate("customElements.whenDefined('br-menu').then(()=>true).catch(()=>true)");
    await esperar(ms);
  };
  const setViewport = (width, height = 1400) =>
    send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: width < 768 }, sid);
  const screenshot = async (path, opts = {}) => {
    const s = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true, ...opts }, sid);
    const { writeFileSync } = await import("node:fs");
    writeFileSync(path, Buffer.from(s.data, "base64"));
  };
  const clicarEm = async (x, y) => {
    await send("Input.dispatchMouseEvent", { type: "mouseMoved", x, y }, sid);
    await send("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", clickCount: 1 }, sid);
    await send("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", clickCount: 1 }, sid);
  };
  const ligarCapturaDeRede = () => {
    const requisicoes = [];
    send("Network.setCacheDisabled", { cacheDisabled: true }, sid);
    ws.addEventListener("message", (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.method === "Network.requestWillBeSent" && msg.sessionId === sid) {
        requisicoes.push(msg.params.request.url);
      }
    });
    return requisicoes;
  };
  const fechar = () => {
    ws.close();
    proc.kill();
  };
  return { evaluate, abrir, esperar, estabilizar, setViewport, screenshot, clicarEm, ligarCapturaDeRede, fechar, send, sid };
}

export const LARGURAS_CANONICAS = [390, 600, 768, 1024, 1280, 1440, 1920, 360, 412];
export const TELAS = [
  { nome: "dashboard", url: "/" },
  { nome: "calendario", url: "/calendario" },
  { nome: "tabela", url: "/tabela" },
  { nome: "resumo-uo", url: "/resumo-uo" },
  { nome: "analise", url: "/analise" },
];
