/* pca-tabler.js — comportamentos da casca Tabler (PCA_DESIGN=tabler). Substitui o dsgov.js:
 * o Bootstrap embutido no tabler.min.js cuida de dropdown, collapse, modal, tabs, alertas e offcanvas
 * por atributos data-bs-* (delegados no document, então funcionam também no conteúdo trocado pelo HTMX).
 * Aqui fica só o que é do sistema: CSRF do HTMX, sessão expirada, tooltips/popovers após troca parcial,
 * mensagens de sucesso que somem, atalho da busca, rolagem preservada, composer do assistente e a
 * seleção de linhas em tabelas. */
(function () {
  "use strict";

  /* ---------- CSRF do HTMX: lido do cookie a cada requisição (o Django gira o token no login/logout) ---------- */
  function lerCookie(nome) {
    var m = document.cookie.match("(^|;)\\s*" + nome + "\\s*=\\s*([^;]+)");
    return m ? decodeURIComponent(m.pop()) : null;
  }
  document.addEventListener("htmx:configRequest", function (ev) {
    var token = lerCookie("csrftoken");
    if (token) ev.detail.headers["X-CSRFToken"] = token;
  });

  /* Sessão expirada numa troca parcial: vai para o login em vez de enfiar a página de login no meio da tela. */
  document.addEventListener("htmx:beforeSwap", function (ev) {
    var xhr = ev.detail.xhr;
    if (xhr && xhr.status === 403 && xhr.getResponseHeader("HX-Login") === "1") {
      ev.detail.shouldSwap = false;
      window.location.href = "/login/?next=" + encodeURIComponent(window.location.pathname);
    }
  });

  /* ---------- Tooltips e popovers do Bootstrap (inclusive no conteúdo que chega pelo HTMX) ---------- */
  function iniciar(raiz) {
    raiz = raiz || document;
    var bs = window.bootstrap || (window.tabler && window.tabler.bootstrap);
    if (bs) {
      raiz.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(function (el) { bs.Tooltip.getOrCreateInstance(el); });
      raiz.querySelectorAll('[data-bs-toggle="popover"]').forEach(function (el) { bs.Popover.getOrCreateInstance(el); });
    }
    fecharMensagensDeSucesso(raiz);
    processarTabelas(raiz);
  }
  function fecharMensagensDeSucesso(raiz) {
    raiz.querySelectorAll(".alert-success[data-auto-fechar]").forEach(function (msg) {
      if (msg.dataset.timer) return;
      msg.dataset.timer = "1";
      setTimeout(function () { msg.classList.remove("show"); setTimeout(function () { msg.remove(); }, 200); }, 8000);
    });
  }

  /* ---------- Tabela limpa + coluna "Ações" fixa (mesma regra do dsgov.js) ----------
     A grade estilo Excel com colunas ajustáveis saiu: a tabela fica com o visual
     do Tabler (só linhas horizontais, títulos à esquerda). Fica só a coluna "Ações" (último <th> com esse
     rótulo ou `.pca-col-acoes`), fixa à direita e sempre visível enquanto a tabela rola na horizontal. */
  function ehColunaAcoes(th) {
    if (th.classList.contains("pca-col-acoes")) return true;
    return /^(Ações\s*)+$/.test((th.textContent || "").replace(/\s+/g, " ").trim());
  }
  function fixarColunaAcoes(tabela) {
    var linha = tabela.querySelector("thead tr:last-child");
    var ths = linha ? linha.children : [];
    var ultimo = ths[ths.length - 1];
    if (!ultimo || !ehColunaAcoes(ultimo) || tabela.classList.contains("pca-cal")) return;
    ultimo.classList.add("pca-col-fixa");
    tabela.querySelectorAll("tbody tr, tfoot tr").forEach(function (tr) {
      if (tr.children.length === ths.length) tr.children[tr.children.length - 1].classList.add("pca-col-fixa");
    });
  }

  /* ---------- Ordenação de tabela por clique no cabeçalho ----------
     Mesmo mecanismo de dsgov.js, vocabulário Tabler: `<th>` com `a.table-sort-link` dentro
     (Processos, ordenação no SERVIDOR via `core/templatetags/ui.py::_cabecalho`) é pulado. Nas
     demais tabelas: clicar (ou Enter/Espaço com foco no `<th>`) ordena o `<tbody>` no CLIENTE,
     ciclo de dois estados (nunca volta a "none" depois do primeiro clique); ordenar por uma
     coluna nova reseta as OUTRAS colunas ordenáveis da mesma tabela. Tabela inteira fica de fora
     quando o `<tbody>` tem rowspan/colspan ou `<th>` (rótulo de linha/subtotal), e a grade do
     calendário (`table.pca-cal`) — colunas de dia da semana, ordenar quebraria o sentido da
     grade mesmo sem rowspan/colspan. Não é persistida (efêmera). */
  function tabelaElegivelParaOrdenar(tabela) {
    if (tabela.classList.contains("pca-cal")) return false;
    var tbody = tabela.querySelector("tbody");
    if (!tbody) return false;
    var linhas = tbody.querySelectorAll("tr");
    for (var i = 0; i < linhas.length; i++) {
      var celulas = linhas[i].children;
      for (var j = 0; j < celulas.length; j++) {
        if (celulas[j].tagName === "TH") return false;
        if (celulas[j].hasAttribute("rowspan") || celulas[j].hasAttribute("colspan")) return false;
      }
    }
    return true;
  }

  function valorComparavelCelula(td) {
    if (!td) return { numero: null, texto: "" };
    if (td.hasAttribute("data-valor")) {
      var bruto = td.getAttribute("data-valor");
      var numeroBruto = parseFloat(bruto);
      return isNaN(numeroBruto) ? { numero: null, texto: bruto } : { numero: numeroBruto, texto: bruto };
    }
    var texto = (td.textContent || "").trim();
    var candidato = texto.replace(/^R\$\s*/, "").replace(/\s*%$/, "").trim();
    if (/^-?\d{1,3}(\.\d{3})*(,\d+)?$/.test(candidato) || /^-?\d+(,\d+)?$/.test(candidato)) {
      return { numero: parseFloat(candidato.replace(/\./g, "").replace(",", ".")), texto: texto };
    }
    var comoData = texto.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
    if (comoData) {
      var data = new Date(Number(comoData[3]), Number(comoData[2]) - 1, Number(comoData[1]));
      return { numero: data.getTime(), texto: texto };
    }
    return { numero: null, texto: texto };
  }

  function compararValoresCelula(a, b) {
    if (a.numero !== null && b.numero !== null) return a.numero - b.numero;
    return a.texto.localeCompare(b.texto, "pt-BR", { numeric: true, sensitivity: "base" });
  }

  function proximoEstadoOrdenacao(estado) {
    return estado === "ascending" ? "descending" : "ascending";
  }

  function classeIcone(estado) {
    return estado === "ascending" ? "ti-sort-ascending" : estado === "descending" ? "ti-sort-descending" : "ti-arrows-sort";
  }

  function aplicarIconeOrdenacao(th, estado) {
    var icone = th.querySelector(".pca-icone-ordenar");
    if (!icone) return;
    icone.classList.remove("ti-arrows-sort", "ti-sort-ascending", "ti-sort-descending");
    icone.classList.add(classeIcone(estado));
  }

  function resetarOutrasColunasOrdenaveis(tabela, thAtivo) {
    tabela.querySelectorAll("thead th.pca-th-ordenavel").forEach(function (th) {
      if (th === thAtivo) return;
      th.setAttribute("aria-sort", "none");
      aplicarIconeOrdenacao(th, "none");
    });
  }

  function ordenarTabelaPorColuna(tabela, th) {
    var tbody = tabela.querySelector("tbody");
    if (!tbody) return;
    var indiceColuna = Array.prototype.indexOf.call(th.parentNode.children, th);
    var estado = proximoEstadoOrdenacao(th.getAttribute("aria-sort") || "none");
    var sinal = estado === "ascending" ? 1 : -1;
    var linhas = Array.prototype.slice.call(tbody.querySelectorAll("tr"));
    linhas.sort(function (linhaA, linhaB) {
      var valorA = valorComparavelCelula(linhaA.children[indiceColuna]);
      var valorB = valorComparavelCelula(linhaB.children[indiceColuna]);
      return sinal * compararValoresCelula(valorA, valorB);
    });
    resetarOutrasColunasOrdenaveis(tabela, th);
    th.setAttribute("aria-sort", estado);
    aplicarIconeOrdenacao(th, estado);
    linhas.forEach(function (linha) { tbody.appendChild(linha); });
  }

  function prepararTabelaOrdenavel(tabela) {
    tabela.querySelectorAll("thead th").forEach(function (th) {
      if (th.classList.contains("column-collapse") || th.classList.contains("column-checkbox")) return;
      if (th.querySelector("a.table-sort-link") || th.classList.contains("pca-col-fixa")) return;
      th.classList.add("pca-th-ordenavel");
      th.setAttribute("tabindex", "0");
      th.setAttribute("role", "button");
      th.setAttribute("aria-sort", "none");
      var icone = document.createElement("i");
      icone.className = "ti ti-arrows-sort ms-1 opacity-50 pca-icone-ordenar";
      icone.setAttribute("aria-hidden", "true");
      th.appendChild(icone);
    });
  }

  document.addEventListener("click", function (ev) {
    var th = ev.target && ev.target.closest && ev.target.closest("th.pca-th-ordenavel");
    if (!th) return;
    var tabela = th.closest("table");
    if (!tabela) return;
    ordenarTabelaPorColuna(tabela, th);
  });

  document.addEventListener("keydown", function (ev) {
    if (ev.key !== "Enter" && ev.key !== " " && ev.key !== "Spacebar") return;
    var th = ev.target && ev.target.matches && ev.target.matches("th.pca-th-ordenavel") ? ev.target : null;
    if (!th) return;
    var tabela = th.closest("table");
    if (!tabela) return;
    ev.preventDefault();
    ordenarTabelaPorColuna(tabela, th);
  });

  function processarTabelas(raiz) {
    raiz.querySelectorAll("table.table").forEach(function (tabela) {
      if (tabela.dataset.pcaPronto) return;
      tabela.dataset.pcaPronto = "1";
      fixarColunaAcoes(tabela);
      if (tabelaElegivelParaOrdenar(tabela)) prepararTabelaOrdenavel(tabela);
    });
  }

  document.addEventListener("DOMContentLoaded", function () { iniciar(document); });
  document.addEventListener("htmx:afterSettle", function (ev) { iniciar(ev.detail && ev.detail.elt ? ev.detail.elt.parentNode || document : document); });

  /* ---------- Indicador de carregamento do HTMX na barra do topo ---------- */
  document.addEventListener("htmx:beforeRequest", function () { document.body.classList.add("pca-carregando"); });
  ["htmx:afterRequest", "htmx:responseError", "htmx:sendError"].forEach(function (nome) {
    document.addEventListener(nome, function () { document.body.classList.remove("pca-carregando"); });
  });

  /* ---------- Atalho Alt+Shift+P: foco na busca do topo (não rouba o foco de um modal aberto) ---------- */
  document.addEventListener("keydown", function (ev) {
    if (ev.repeat || ev.isComposing) return;
    if (!(ev.altKey && ev.shiftKey && ev.code === "KeyP")) return;
    if (document.activeElement && document.activeElement.closest && document.activeElement.closest(".modal.show")) return;
    var campo = document.getElementById("busca-header");
    if (!campo) return;
    ev.preventDefault();
    campo.focus();
    campo.select();
  });

  /* ---------- Rolagem preservada ao reenviar um <form method=get> da própria tela (sem HTMX) ---------- */
  function chaveRolagem(p) { return "pca-scroll:" + p; }
  document.addEventListener("submit", function (ev) {
    var form = ev.target;
    if (!form || form.tagName !== "FORM" || (form.method || "get").toLowerCase() !== "get") return;
    if (form.hasAttribute("hx-get") || form.hasAttribute("hx-post") || form.hasAttribute("hx-boost")) return;
    try { sessionStorage.setItem(chaveRolagem(location.pathname), String(window.scrollY)); } catch (e) { /* sem sessionStorage */ }
  });
  document.addEventListener("DOMContentLoaded", function () {
    var valor;
    try { valor = sessionStorage.getItem(chaveRolagem(location.pathname)); sessionStorage.removeItem(chaveRolagem(location.pathname)); } catch (e) { return; }
    if (valor === null) return;
    try { if (!document.referrer || new URL(document.referrer).pathname !== location.pathname) return; } catch (e) { return; }
    window.scrollTo(0, parseInt(valor, 10) || 0);
  });

  /* ---------- Modal: ao salvar, fecha e volta para o MESMO ponto da tela (mesma regra do dsgov.js) ----------
     Ao abrir (`hx-get` → `#modal-acompanhamento`) lembra o elemento com id mais próximo de quem abriu (linha `#item-N`,
     seção da ficha); ao enviar, guarda onde ele estava na janela. Depois da troca de `#listagem` (tabela) ou da página
     nova (ficha), rola até ele voltar ao mesmo ponto, mesmo com a mensagem de sucesso entrando acima. Expira em 30 s. */
  var CHAVE_MODAL = "pca-rolagem-modal";
  var ancoraModal = null;
  function lerRolagemModal() {
    try {
      var e = JSON.parse(sessionStorage.getItem(CHAVE_MODAL) || "null");
      return e && e.p === location.pathname && Date.now() - e.t <= 30000 ? e : null;
    } catch (err) { return null; }
  }
  function restaurarRolagemModal(limpar) {
    var e = lerRolagemModal();
    if (!e) return;
    var el = e.id && document.getElementById(e.id);
    if (el && typeof e.topo === "number") window.scrollBy(0, el.getBoundingClientRect().top - e.topo);
    else window.scrollTo(0, e.y || 0);
    if (limpar) { try { sessionStorage.removeItem(CHAVE_MODAL); } catch (err) { /* sem sessionStorage */ } }
  }
  document.addEventListener("htmx:beforeRequest", function (ev) {
    var d = ev.detail || {};
    if (!d.elt || !d.target || d.target.id !== "modal-acompanhamento") return;
    if (!d.elt.closest("#modal-acompanhamento")) { var comId = d.elt.closest("[id]"); ancoraModal = comId ? comId.id : null; return; }
    if (d.elt.id !== "form-acompanhamento") return;
    var el = ancoraModal && document.getElementById(ancoraModal);
    try {
      sessionStorage.setItem(CHAVE_MODAL, JSON.stringify({ p: location.pathname, id: el ? ancoraModal : null, topo: el ? el.getBoundingClientRect().top : null, y: window.scrollY, t: Date.now() }));
    } catch (err) { /* sem sessionStorage */ }
  });
  document.addEventListener("htmx:afterSettle", function (ev) {
    var alvo = ev.detail && (ev.detail.target || ev.detail.elt);
    if (alvo && alvo.id === "listagem") restaurarRolagemModal(true);
  });
  document.addEventListener("DOMContentLoaded", function () { restaurarRolagemModal(false); });
  window.addEventListener("load", function () { restaurarRolagemModal(true); });

  /* ---------- Composer do assistente: Enter envia; Shift/Alt+Enter quebram linha; o campo cresce ---------- */
  function composer(el) { return el && el.matches && el.matches("textarea[data-composer]") ? el : null; }
  document.addEventListener("keydown", function (ev) {
    var t = composer(ev.target);
    if (!t || ev.key !== "Enter" || ev.isComposing) return;
    if (window.matchMedia && matchMedia("(pointer: coarse)").matches) return;
    if (ev.altKey || ev.shiftKey) {
      ev.preventDefault();
      t.setRangeText("\n", t.selectionStart, t.selectionEnd, "end");
      t.dispatchEvent(new Event("input", { bubbles: true }));
      return;
    }
    if (!t.form) return;
    ev.preventDefault();
    if (typeof t.form.requestSubmit === "function") t.form.requestSubmit();
    else t.form.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
  });
  function redimensionar(t) {
    var teto = t.dataset.composerMax || "40vh";
    var px = /vh$/.test(teto) ? innerHeight * parseFloat(teto) / 100 : parseFloat(teto) || innerHeight * 0.4;
    t.style.height = "auto";
    t.style.height = Math.min(t.scrollHeight, px) + "px";
  }
  document.addEventListener("input", function (ev) { var t = composer(ev.target); if (t) redimensionar(t); });
  function restaurarComposer(raiz) { if (raiz && raiz.querySelectorAll) raiz.querySelectorAll("textarea[data-composer]").forEach(function (t) { t.style.height = ""; }); }
  document.addEventListener("htmx:afterSwap", function (ev) { restaurarComposer(ev.detail && ev.detail.target); });
  document.addEventListener("reset", function (ev) { if (ev.target && ev.target.tagName === "FORM") restaurarComposer(ev.target); }, true);

  /* ---------- Seleção de linhas: data-selecionar-todos="grupo" marca os data-selecao="grupo" ---------- */
  function atualizarSelecao(grupo) {
    var filhos = Array.from(document.querySelectorAll('[data-selecao="' + grupo + '"]'));
    var n = filhos.filter(function (c) { return c.checked; }).length;
    document.querySelectorAll('[data-selecionar-todos="' + grupo + '"]').forEach(function (p) {
      p.checked = filhos.length > 0 && n === filhos.length; p.indeterminate = n > 0 && n < filhos.length;
    });
    document.querySelectorAll('[data-contagem-selecao="' + grupo + '"]').forEach(function (el) { el.textContent = n; });
    filhos.forEach(function (c) { var tr = c.closest("tr"); if (tr) tr.classList.toggle("table-active", c.checked); });
  }
  document.addEventListener("change", function (ev) {
    var el = ev.target;
    if (el.dataset && el.dataset.selecionarTodos) {
      document.querySelectorAll('[data-selecao="' + el.dataset.selecionarTodos + '"]').forEach(function (c) { if (!c.disabled) c.checked = el.checked; });
      atualizarSelecao(el.dataset.selecionarTodos);
    } else if (el.dataset && el.dataset.selecao) {
      atualizarSelecao(el.dataset.selecao);
    }
  });

  /* ---------- Aparência por usuário: claro/escuro, cor principal, tom de base e cantos ----------
   * O ui/_tema.html já aplicou a escolha antes de a página pintar. Aqui: o painel "Personalizar aparência"
   * muda a tela na hora e grava na conta em segundo plano (POST core:aparencia); o navegador guarda uma
   * cópia para a tela de login. Toda mudança que afeta cores dispara "pca:tema" (os gráficos se redesenham). */
  var raiz = document.documentElement;
  var sistemaEscuro = window.matchMedia ? matchMedia("(prefers-color-scheme: dark)") : null;
  var PADRAO = { tema: "auto", cor: "blue", base: "slate", cantos: "1" };
  function lerAparencia() {
    try { return Object.assign({}, PADRAO, JSON.parse(localStorage.getItem("pca-aparencia") || "{}")); }
    catch (e) { return Object.assign({}, PADRAO); }
  }
  var aparencia = lerAparencia();
  function avisarGraficos() {
    document.dispatchEvent(new CustomEvent("pca:tema", { detail: { tema: raiz.getAttribute("data-bs-theme") } }));
  }
  function aplicarAparencia(a) {
    var escuro = a.tema === "escuro" || (a.tema !== "claro" && !!(sistemaEscuro && sistemaEscuro.matches));
    var antes = [raiz.getAttribute("data-bs-theme"), raiz.getAttribute("data-bs-theme-primary"), raiz.getAttribute("data-bs-theme-base")].join();
    raiz.setAttribute("data-bs-theme", escuro ? "dark" : "light");
    raiz.setAttribute("data-bs-theme-primary", a.cor);
    raiz.setAttribute("data-bs-theme-base", a.base);
    raiz.setAttribute("data-bs-theme-radius", a.cantos);
    try { localStorage.setItem("pca-aparencia", JSON.stringify(a)); } catch (e) {}
    var form = document.querySelector("[data-aparencia]");
    if (form) ["tema", "cor", "base", "cantos"].forEach(function (campo) {
      var marcado = form.querySelector('input[name="' + campo + '"][value="' + a[campo] + '"]');
      if (marcado) marcado.checked = true;
    });
    var depois = [raiz.getAttribute("data-bs-theme"), a.cor, a.base].join();
    if (antes !== depois) avisarGraficos();
  }
  var gravacao = null;
  function gravarAparencia(a) {
    var form = document.querySelector("[data-aparencia]");
    if (!form) return;
    var status = form.querySelector("[data-aparencia-status]");
    clearTimeout(gravacao);
    gravacao = setTimeout(function () {
      var dados = new FormData();
      Object.keys(a).forEach(function (k) { dados.append(k, a[k]); });
      if (status) status.textContent = "Salvando…";
      fetch(form.action, { method: "POST", body: dados, credentials: "same-origin",
        headers: { "Accept": "application/json", "X-CSRFToken": lerCookie("csrftoken") || "" } })
        .then(function (r) { if (status) status.textContent = r.ok ? "Salvo na sua conta." : "Não foi possível salvar."; })
        .catch(function () { if (status) status.textContent = "Não foi possível salvar."; });
    }, 400);
  }
  document.addEventListener("change", function (ev) {
    var form = ev.target.closest && ev.target.closest("[data-aparencia]");
    if (!form || !ev.target.name || !(ev.target.name in PADRAO)) return;
    aparencia[ev.target.name] = ev.target.value;
    aplicarAparencia(aparencia);
    gravarAparencia(aparencia);
  });
  document.addEventListener("submit", function (ev) {
    if (!ev.target.matches || !ev.target.matches("[data-aparencia]")) return;
    ev.preventDefault();
    gravarAparencia(aparencia);
  });
  document.addEventListener("click", function (ev) {
    if (!ev.target.closest || !ev.target.closest("[data-aparencia-padrao]")) return;
    aparencia = Object.assign({}, PADRAO);
    aplicarAparencia(aparencia);
    gravarAparencia(aparencia);
  });
  if (sistemaEscuro && sistemaEscuro.addEventListener) sistemaEscuro.addEventListener("change", function () { if (aparencia.tema === "auto") aplicarAparencia(aparencia); });
  /* Papel é claro: imprime sempre no tema claro e volta ao que estava depois */
  var temaAntesDeImprimir = null;
  window.addEventListener("beforeprint", function () {
    temaAntesDeImprimir = raiz.getAttribute("data-bs-theme");
    if (temaAntesDeImprimir === "dark") { raiz.setAttribute("data-bs-theme", "light"); avisarGraficos(); }
  });
  window.addEventListener("afterprint", function () {
    if (temaAntesDeImprimir === "dark") { raiz.setAttribute("data-bs-theme", "dark"); avisarGraficos(); }
    temaAntesDeImprimir = null;
  });

  /* Ficha do processo abre na MESMA aba (aba nova fazia o Chrome jogar o link para o app instalado — PWA — e o
     usuário saía do navegador). Para não perder o lugar: ao clicar num processo fora da ficha, guarda (só nesta aba)
     de onde veio e a rolagem; na ficha, "Voltar" leva de volta para lá; ao chegar, a rolagem é restaurada. Da tabela
     de processos o "Voltar" continua o do servidor (filtros + âncora da linha). Delegado: vale para o HTMX também. */
  var FICHA = /^\/processo\/\d+\/\d+\/?$/;
  var CHAVE_ORIGEM = "pca-origem-ficha";
  function naFicha() { return /^\/processo\//.test(window.location.pathname); }
  function lerOrigem() { try { return JSON.parse(sessionStorage.getItem(CHAVE_ORIGEM) || "null"); } catch (e) { return null; } }
  document.addEventListener("click", function (ev) {
    var a = ev.target.closest && ev.target.closest("a[href]");
    if (!a || naFicha()) return;
    var url;
    try { url = new URL(a.href, window.location.href); } catch (e) { return; }
    if (url.origin !== window.location.origin || !FICHA.test(url.pathname)) return;
    try { sessionStorage.setItem(CHAVE_ORIGEM, JSON.stringify({ url: window.location.href, y: window.scrollY })); } catch (e) { /* sem sessionStorage */ }
  }, true);
  document.addEventListener("DOMContentLoaded", function () {
    var origem = lerOrigem();
    if (!origem) return;
    var destino;
    try { destino = new URL(origem.url); } catch (e) { return; }
    if (naFicha()) {
      var voltar = document.querySelector("a[data-voltar]");
      if (voltar && destino.pathname !== "/tabela") voltar.href = origem.url;
      return;
    }
    /* chegou de volta à página de origem vindo de uma ficha: mesma rolagem de antes */
    var deFicha = false;
    try { deFicha = !!document.referrer && /^\/processo\//.test(new URL(document.referrer).pathname); } catch (e) { /* referrer inválido */ }
    if (deFicha && destino.href.split("#")[0] === window.location.href.split("#")[0]) {
      try { sessionStorage.removeItem(CHAVE_ORIGEM); } catch (e) { /* sem sessionStorage */ }
      if (!window.location.hash) window.scrollTo(0, origem.y || 0);
    }
  });

  /* Cartão de filtros recolhível da tela Processos: o botão `[data-alternar-filtros]` usa o
     collapse do Bootstrap; aqui só o rótulo ("Ocultar filtros"/"Mostrar filtros") e a memória da escolha, por
     pessoa, no localStorage (só "aberto"/"recolhido", nada vai ao servidor). Sem escolha guardada, o cartão abre a
     partir de 1280px e nasce recolhido abaixo disso. Os eventos do "Mais filtros" (collapse dentro do cartão)
     sobem até aqui e são ignorados pela checagem do alvo. */
  var CHAVE_FILTROS = "pca:painel:painel-filtros";
  function rotularFiltros(botao, aberto) {
    var rotulo = botao.querySelector("[data-rotulo]");
    var texto = botao.getAttribute(aberto ? "data-rotulo-aberto" : "data-rotulo-fechado");
    if (rotulo && texto) rotulo.textContent = texto;
  }
  document.addEventListener("DOMContentLoaded", function () {
    var botao = document.querySelector("[data-alternar-filtros]");
    var painel = botao && document.getElementById(botao.getAttribute("aria-controls"));
    if (!painel) return;
    var guardado = null;
    try { guardado = localStorage.getItem(CHAVE_FILTROS); } catch (e) { /* sem localStorage */ }
    var aberto = guardado ? guardado === "aberto" : (window.matchMedia ? window.matchMedia("(min-width: 1280px)").matches : true);
    painel.classList.toggle("show", aberto);
    botao.classList.toggle("collapsed", !aberto);
    botao.setAttribute("aria-expanded", aberto ? "true" : "false");
    rotularFiltros(botao, aberto);
    function guardar(ev, estado) {
      if (ev.target !== painel) return;
      rotularFiltros(botao, estado);
      try { localStorage.setItem(CHAVE_FILTROS, estado ? "aberto" : "recolhido"); } catch (e) { /* sem localStorage */ }
    }
    painel.addEventListener("show.bs.collapse", function (ev) { guardar(ev, true); });
    painel.addEventListener("hide.bs.collapse", function (ev) { guardar(ev, false); });
  });

  window.pca = Object.assign(window.pca || {}, { iniciar: iniciar, aparencia: aplicarAparencia });
})();
