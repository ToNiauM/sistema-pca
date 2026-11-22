/* dsgov.js — cola entre Django, HTMX e o JavaScript do DSGov (@govbr-ds/core 3.7.0).
 *
 * O core.min.js do DS 3.7.0 exporta os construtores (window.core.BRSelect etc.) mas NÃO inicializa
 * nada sozinho (só o core-init.js faz isso, e ele traz junto os exemplos da documentação e quebra
 * quando falta algum elemento). Este arquivo é a única inicialização: no carregamento, instancia
 * cada componente .br-* do documento; a cada troca do HTMX, instancia só o que chegou no fragmento.
 *
 * Também: CSRF do Django em toda requisição HTMX (lido do cookie a cada vez, porque o Django
 * rotaciona o token no login/logout), redirecionamento correto quando a sessão expira, e
 * fechamento automático das mensagens de sucesso.
 *
 * Não edite este arquivo no projeto; ele é padrão do padrão DSGov.
 */
(function () {
  "use strict";

  /* ---------- CSRF ---------- */
  function lerCookie(nome) {
    var m = document.cookie.match("(^|;)\\s*" + nome + "\\s*=\\s*([^;]+)");
    return m ? decodeURIComponent(m.pop()) : null;
  }
  document.addEventListener("htmx:configRequest", function (ev) {
    var token = lerCookie("csrftoken");
    if (token) ev.detail.headers["X-CSRFToken"] = token;
  });

  /* Sessão expirada durante uma troca parcial: a resposta é a página de login inteira.
     O middleware HtmxRedirectMiddleware do core já converte em HX-Redirect; este é o cinto
     de segurança do lado do navegador. */
  document.addEventListener("htmx:beforeSwap", function (ev) {
    var xhr = ev.detail.xhr;
    if (xhr && xhr.status === 403 && xhr.getResponseHeader("HX-Login") === "1") {
      ev.detail.shouldSwap = false;
      window.location.href = "/login/?next=" + encodeURIComponent(window.location.pathname);
    }
  });

  /* ---------- Reinicialização dos componentes do DS ---------- */
  /* Componentes que precisam de JS e a assinatura do construtor exportado em window.core. */
  var COMPONENTES = [
    [".br-header", "BRHeader"],
    [".br-menu", "BRMenu"],
    [".br-footer", "BRFooter"],
    [".br-input", "BRInput"],
    [".br-textarea", "BRTextarea"],
    [".br-checkbox", "BRCheckbox"],
    [".br-select", "BRSelect"],
    [".br-datetimepicker", "BRDateTimePicker"],
    [".br-upload", "BRUpload"],
    [".br-message", "BRAlert"],
    [".br-tab", "BRTab"],
    [".br-tag", "BRTag"],
    [".br-tooltip", "BRTooltip"],
    [".br-pagination", "BRPagination"],
    [".br-list:not([data-sub])", "BRList"],
    [".br-item", "BRItem"],
    [".br-step", "BRStep"],
    [".br-wizard", "BRWizard"],
    [".br-notification", "BRNotification"],
    [".br-breadcrumb", "BRBreadcrumb"],
    [".br-accordion", "BRAccordion"],
    [".br-modal", "BRModal"],
  ];

  function iniciar(raiz) {
    if (!window.core || !raiz || !raiz.querySelectorAll) return;
    /* Tabelas e cards recebem um índice sequencial (usado em ids internos). */
    var seq = Date.now() % 100000;
    raiz.querySelectorAll(".br-table").forEach(function (el, i) {
      if (el.dataset.dsgovInit) return;
      el.dataset.dsgovInit = "1";
      try { new window.core.BRTable("br-table", el, seq + i); } catch (e) { console.warn("dsgov: br-table", e); }
    });
    raiz.querySelectorAll(".br-card").forEach(function (el, i) {
      if (el.dataset.dsgovInit) return;
      el.dataset.dsgovInit = "1";
      try { new window.core.BRCard("br-card", el, seq + i); } catch (e) { console.warn("dsgov: br-card", e); }
    });
    COMPONENTES.forEach(function (par) {
      var seletor = par[0], nome = par[1];
      var Ctor = window.core[nome];
      if (!Ctor) return;
      var nomeClasse = seletor.slice(1).split(":")[0];
      /* Fase 28 — o popover do calendário usa a MESMA
         classe `.br-tooltip` (visual do DS), mas tem comportamento PRÓPRIO
         (ver bloco "Popover do calendário" abaixo): excluído aqui para o
         BRTooltip (depreciado, sem "clique fixa"/Esc global) nunca instanciar
         duas vezes o mesmo balão. */
      var seletorEfetivo = seletor === ".br-tooltip" ? seletor + ":not([data-popover-calendario])" : seletor;
      raiz.querySelectorAll(seletorEfetivo).forEach(function (el) {
        if (el.dataset.dsgovInit) return;
        el.dataset.dsgovInit = "1";
        try {
          if (nome === "BRDateTimePicker") new Ctor("br-datetimepicker", el, {});
          /* BRUpload exige um callback de upload; sem ele o "Carregando..." nunca some e o arquivo
             nunca é listado. O envio real é o submit do formulário, então o callback só resolve. */
          else if (nome === "BRUpload") new Ctor("br-upload", el, function () { return Promise.resolve(); });
          else new Ctor(nomeClasse, el);
        } catch (e) { console.warn("dsgov: " + seletor, e); }
      });
    });
    /* Dropdowns por atributo (avatar do usuário, menus avulsos). O core 3.7.0 não exporta BRAvatar;
       BRHeader cuida dos dropdowns de Acesso Rápido/Funcionalidades e BRTable do menu de densidade. */
    raiz.querySelectorAll('[data-toggle="dropdown"]').forEach(function (btn) {
      if (btn.dataset.dsgovInit || !window.core.Dropdown) return;
      if (btn.closest(".header-links") || btn.closest(".header-functions") || btn.closest(".br-table")) return;
      btn.dataset.dsgovInit = "1";
      try {
        var icones = btn.querySelector(".br-avatar") ? { iconToShow: "fa-caret-down", iconToHide: "fa-caret-up" } : {};
        new window.core.Dropdown(Object.assign({ trigger: btn }, icones)).setBehavior();
        sincronizarDropdown(btn);
      } catch (e) { console.warn("dsgov: dropdown", e); }
    });
    processarTabelas(raiz);
  }

  /* Ponte entre o Dropdown genérico e o CSS do header. O core.min.css esconde
     `.br-header .header-actions .dropdown:not(.show) .br-list` abaixo de 1280px. O Dropdown do
     core alterna o atributo `hidden` do alvo e a classe `dropdown` no PAI do alvo (só enquanto
     aberto), mas nunca põe `.show` nesse pai — isso é o BRHeader, que só cuida de Acesso Rápido/
     Funcionalidades (e o logout dele remove `.show` de `.avatar`, confirmando que é ali que a
     classe deve viver). Sem esta ponte o menu do avatar (e o "Sair") nunca aparecia em celular
     nem em janela estreita. Espelha `hidden` do alvo em `.show` do pai e `.active` do gatilho
     (estado aberto de references/componentes/header.md). Clique fora já é tratado pelo próprio
     Dropdown do core (`_hideDropdown`). */
  function sincronizarDropdown(btn) {
    var alvo = document.getElementById(btn.getAttribute("data-target") || "");
    if (!alvo || !alvo.parentElement) return;
    var pai = alvo.parentElement;
    function espelhar() {
      var aberto = !alvo.hasAttribute("hidden");
      btn.classList.toggle("active", aberto);
      pai.classList.toggle("show", aberto);
    }
    new MutationObserver(espelhar).observe(alvo, { attributes: true, attributeFilter: ["hidden"] });
    espelhar();
  }

  /* ---------- Tabela: br-table canônica + coluna de ações fixa ----------
     A grade estilo Excel com colunas ajustáveis saiu: a tabela segue o
     visual do DS (só linhas horizontais, títulos à esquerda, realce da linha no hover). Fica só a
     coluna de ações (`.dsgov-acoes` ou último <th> "Ações"), fixa à direita e sempre visível
     enquanto a tabela rola na horizontal. */
  function ehColunaAcoes(th) {
    if (th.classList.contains("dsgov-acoes")) return true;
    return /^(Ações\s*)+$/.test((th.textContent || "").replace(/\s+/g, " ").trim());
  }

  function fixarColunaAcoes(tabela) {
    var linha = tabela.querySelector("thead tr:last-child");
    var ths = linha ? linha.children : [];
    var ultimo = ths[ths.length - 1];
    if (!ultimo || !ehColunaAcoes(ultimo)) return;
    ultimo.classList.add("dsgov-col-fixa");
    tabela.querySelectorAll("tbody tr, tfoot tr").forEach(function (tr) {
      if (tr.children.length === ths.length) tr.children[tr.children.length - 1].classList.add("dsgov-col-fixa");
    });
  }

  /* ---------- Ordenação de tabela por clique no cabeçalho ----------
     `<th>` que já tem `a.dsgov-ordenar` dentro (Processos, ordenação no SERVIDOR via
     `apps/pca/templatetags/pca_listagem.py::ordenar_por_tabela`) é pulado — o mecanismo abaixo
     nunca duplica aquele clique. Nas demais tabelas: clicar (ou Enter/Espaço com foco no `<th>`)
     ordena o `<tbody>` no CLIENTE, ciclo de dois estados (ascendente/descendente, nunca volta a
     "none" depois do primeiro clique — mesma regra de `ordenar_por_tabela`); ordenar por uma
     coluna nova reseta o ícone/aria-sort de todas as OUTRAS colunas ordenáveis da mesma tabela.
     Tabela inteira fica de fora quando o `<tbody>` tem
     qualquer célula com `rowspan`/`colspan` ou qualquer `<th>` (sinal de rótulo de linha/subtotal
     — ex.: `_resumo_uo_detalhamento.html`), e também a grade do calendário (`.dsgov-calendario`,
     no `.br-table` que envolve a tabela): embora as células do calendário sejam `<td>` simples,
     sem rowspan/colspan, ordenar por coluna (dia da semana) quebraria o sentido da grade — cada
     coluna representa um dia fixo do calendário, não um valor comparável entre linhas. Não é
     persistida (comportamento efêmero). */
  function tabelaElegivelParaOrdenar(brTable, tabela) {
    if (brTable.classList.contains("dsgov-calendario")) return false;
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

  function aplicarIconeOrdenacao(th, estado) {
    var icone = th.querySelector(".dsgov-icone-ordenar");
    if (!icone) return;
    icone.classList.remove("fa-sort", "fa-sort-up", "fa-sort-down");
    icone.classList.add(estado === "ascending" ? "fa-sort-up" : estado === "descending" ? "fa-sort-down" : "fa-sort");
  }

  function resetarOutrasColunasOrdenaveis(tabela, thAtivo) {
    tabela.querySelectorAll("thead th.dsgov-th-ordenavel").forEach(function (th) {
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
      if (th.querySelector("a.dsgov-ordenar") || th.classList.contains("dsgov-col-fixa")) return;
      th.classList.add("dsgov-th-ordenavel");
      th.setAttribute("tabindex", "0");
      th.setAttribute("role", "button");
      th.setAttribute("aria-sort", "none");
      var icone = document.createElement("i");
      icone.className = "fas fa-sort dsgov-icone-ordenar";
      icone.setAttribute("aria-hidden", "true");
      th.appendChild(icone);
    });
  }

  document.addEventListener("click", function (ev) {
    var th = ev.target && ev.target.closest && ev.target.closest("th.dsgov-th-ordenavel");
    if (!th) return;
    var tabela = th.closest("table");
    if (!tabela) return;
    ordenarTabelaPorColuna(tabela, th);
  });

  document.addEventListener("keydown", function (ev) {
    if (ev.key !== "Enter" && ev.key !== " " && ev.key !== "Spacebar") return;
    var th = ev.target && ev.target.closest && ev.target.matches && ev.target.matches("th.dsgov-th-ordenavel")
      ? ev.target
      : null;
    if (!th) return;
    var tabela = th.closest("table");
    if (!tabela) return;
    ev.preventDefault();
    ordenarTabelaPorColuna(tabela, th);
  });

  function processarTabelas(raiz) {
    raiz.querySelectorAll(".br-table").forEach(function (brTable) {
      var tabela = brTable.querySelector("table");
      if (!tabela || tabela.dataset.dsgovPronto) return;
      tabela.dataset.dsgovPronto = "1";
      if (!brTable.classList.contains("dsgov-calendario")) fixarColunaAcoes(tabela);
      if (tabelaElegivelParaOrdenar(brTable, tabela)) prepararTabelaOrdenavel(tabela);
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    iniciar(document);
    fecharMensagensDeSucesso(document);
  });

  document.addEventListener("htmx:afterSettle", function (ev) {
    var alvo = ev.detail && ev.detail.elt;
    if (!alvo) return;
    iniciar(alvo);
    /* Trocas out-of-band (mensagens, contadores) chegam em outros alvos. */
    document.querySelectorAll("[hx-swap-oob], [data-dsgov-reinit]").forEach(iniciar);
    fecharMensagensDeSucesso(alvo);
  });

  /* ---------- Mensagens ---------- */
  function fecharMensagensDeSucesso(raiz) {
    raiz.querySelectorAll(".br-message.success").forEach(function (msg) {
      if (msg.dataset.dsgovTimer) return;
      msg.dataset.dsgovTimer = "1";
      setTimeout(function () { msg.remove(); }, 8000);
    });
  }

  /* ---------- Menu lateral: marca o item ativo pela URL ---------- */
  document.addEventListener("DOMContentLoaded", function () {
    var caminho = window.location.pathname;
    var melhor = null, tamanho = 0;
    document.querySelectorAll("#main-navigation a.menu-item[href]").forEach(function (a) {
      var href = a.getAttribute("href");
      if (href && href !== "/" && caminho.indexOf(href) === 0 && href.length > tamanho) { melhor = a; tamanho = href.length; }
      if (href === "/" && caminho === "/") melhor = a;
    });
    if (melhor) { melhor.classList.add("active"); melhor.setAttribute("aria-current", "page"); }
  });

  /* ---------- Atalho de busca: Alt+Shift+P ---------- */
  /* Um único listener, registrado uma vez no carregamento do arquivo —
     NUNCA dentro de iniciar(), que roda de novo a cada troca HTMX. Abre e
     focaliza a busca do header sem navegar nem apagar formulários; devolve
     o foco anterior ao fechar; respeita o modal de acompanhamento aberto
     (o atalho não retira o foco de um formulário em edição); funciona por
     clique/toque (reaproveita o [data-toggle="search"] que o BRHeader já
     sabe abrir/focar, sem lógica própria de abrir/fechar aqui). F5/F7 do
     navegador intactos: só reage a Alt+Shift+P (KeyP). */
  var focoAntesDaBusca = null;

  function dentroDeModalAberto(elemento) {
    return !!(
      elemento &&
      typeof elemento.closest === "function" &&
      (elemento.closest("#modal-acompanhamento") || elemento.closest(".br-modal.active"))
    );
  }

  document.addEventListener("keydown", function (ev) {
    if (ev.repeat || ev.isComposing) return;
    if (!(ev.altKey && ev.shiftKey && ev.code === "KeyP")) return;
    if (dentroDeModalAberto(document.activeElement)) return;
    var botaoBusca = document.querySelector('[data-toggle="search"]');
    if (!botaoBusca) return;
    ev.preventDefault();
    focoAntesDaBusca = document.activeElement;
    botaoBusca.click();
    var campoBusca = document.getElementById("busca-header");
    if (campoBusca && document.activeElement !== campoBusca) campoBusca.focus();
  });

  function devolverFocoDaBusca() {
    if (focoAntesDaBusca && typeof focoAntesDaBusca.focus === "function") {
      focoAntesDaBusca.focus();
    }
    focoAntesDaBusca = null;
  }

  document.addEventListener("click", function (ev) {
    if (ev.target && ev.target.closest && ev.target.closest('[data-dismiss="search"]')) {
      devolverFocoDaBusca();
    }
  });

  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape" && document.activeElement && document.activeElement.id === "busca-header") {
      devolverFocoDaBusca();
    }
  });

  /* ---------- Popover do calendário ---------- */
  /* Comportamento PRÓPRIO — NUNCA a inicialização automática do BRTooltip
     (depreciado, sem semântica de "clique fixa aberto" nem Esc global,
     references/componentes/tooltip.md): mostrar em hover/foco, fixar em
     clique/Enter/toque (um por vez — fixar um fecha qualquer outro), Esc ou
     "Fechar detalhes" fecham e devolvem o foco ao ativador, `mouseenter` no
     próprio popover cancela o fechamento (conteúdo acessível ao mover o
     ponteiro para dentro dele). Delegado em `document` (registrado uma
     única vez, fora de `iniciar()`) — cobre qualquer ativador presente no
     carregamento (o Calendário nunca usa HTMX/troca parcial). O marcador
     `[data-popover-calendario]` está TANTO no ativador quanto no próprio
     `.br-tooltip` — nunca o atributo HTML5 nativo `popover` (Popover API):
     navegadores com suporte nativo aplicam `display: none !important` via
     UA stylesheet a todo `[popover]` não aberto via `.showPopover()`, uma
     regra de origem UA que nenhum CSS de autor (nem `!important`) consegue
     sobrepor — o popover ficaria permanentemente invisível sem chamar essa
     API, que este comportamento não usa. */
  function ativadorPopoverCalendario(elemento) {
    return elemento && typeof elemento.closest === "function"
      ? elemento.closest("[data-popover-calendario]")
      : null;
  }

  function popoverDoAtivador(ativador) {
    if (!ativador || !ativador.getAttribute) return null;
    var id = ativador.getAttribute("aria-describedby");
    return id ? document.getElementById(id) : null;
  }

  function ativadorDoPopover(popover) {
    if (!popover || !popover.id) return null;
    return document.querySelector('[aria-describedby="' + popover.id + '"]');
  }

  function fecharTodosOsPopoversCalendario(excetoPopover) {
    document.querySelectorAll(".br-tooltip[data-popover-calendario][data-show]").forEach(function (popover) {
      if (popover === excetoPopover) return;
      popover.removeAttribute("data-show");
      popover.removeAttribute("data-fixado");
    });
  }

  function posicionarPopoverCalendario(popover, ativador) {
    /* `position: fixed` (dsgov.css) escapa do `overflow: hidden` da célula
       — sem Popper (BRTooltip está excluído), o posicionamento é o mínimo
       necessário: logo abaixo do ativador, clampado à viewport para nunca
       vazar pela direita/embaixo. */
    if (!popover || !ativador || typeof ativador.getBoundingClientRect !== "function") return;
    var retanguloAtivador = ativador.getBoundingClientRect();
    var largura = popover.offsetWidth || 320;
    var altura = popover.offsetHeight || 0;
    var esquerda = Math.min(
      Math.max(retanguloAtivador.left, 8),
      window.innerWidth - largura - 8
    );
    var topo = retanguloAtivador.bottom + 4;
    if (altura && topo + altura > window.innerHeight - 8) {
      topo = Math.max(retanguloAtivador.top - altura - 4, 8);
    }
    popover.style.left = esquerda + "px";
    popover.style.top = topo + "px";
  }

  function mostrarPopoverCalendario(popover, ativador) {
    if (!popover) return;
    popover.setAttribute("data-show", "data-show");
    posicionarPopoverCalendario(popover, ativador || ativadorDoPopover(popover));
  }

  function esconderPopoverCalendario(popover) {
    if (!popover) return;
    popover.removeAttribute("data-show");
    popover.removeAttribute("data-fixado");
  }

  function fixarPopoverCalendario(popover) {
    if (!popover) return;
    fecharTodosOsPopoversCalendario(popover);
    mostrarPopoverCalendario(popover);
    popover.setAttribute("data-fixado", "data-fixado");
  }

  /* Mostrar em hover/foco (capture: mouseenter/focus não borbulham). */
  document.addEventListener("mouseenter", function (ev) {
    var ativador = ativadorPopoverCalendario(ev.target);
    if (ativador) { mostrarPopoverCalendario(popoverDoAtivador(ativador)); return; }
    var popover = ev.target && ev.target.closest && ev.target.closest(".br-tooltip[data-popover-calendario]");
    if (popover) mostrarPopoverCalendario(popover);
  }, true);

  document.addEventListener("focus", function (ev) {
    var ativador = ativadorPopoverCalendario(ev.target);
    if (ativador) mostrarPopoverCalendario(popoverDoAtivador(ativador));
  }, true);

  /* Esconder ao sair, exceto quando fixado ou quando o ponteiro entrou no
     próprio popover ("conteúdo acessível ao mover o ponteiro
     para dentro dele"). */
  document.addEventListener("mouseleave", function (ev) {
    var ativador = ativadorPopoverCalendario(ev.target);
    var popover = ativador ? popoverDoAtivador(ativador)
      : (ev.target && ev.target.closest && ev.target.closest(".br-tooltip[data-popover-calendario]"));
    if (!popover || popover.hasAttribute("data-fixado")) return;
    esconderPopoverCalendario(popover);
  }, true);

  /* Perder o foco (Tab para fora) fecha, salvo quando o foco migrou para
     dentro do próprio popover (ex. "Ver mais"/"Fechar detalhes") ou o
     popover está fixado. */
  document.addEventListener("focusout", function (ev) {
    var ativador = ativadorPopoverCalendario(ev.target);
    if (!ativador) return;
    var popover = popoverDoAtivador(ativador);
    if (!popover || popover.hasAttribute("data-fixado")) return;
    setTimeout(function () {
      if (popover.hasAttribute("data-fixado")) return;
      if (popover.contains(document.activeElement) || document.activeElement === ativador) return;
      esconderPopoverCalendario(popover);
    }, 0);
  }, true);

  /* Clique/toque no ativador FIXA (nunca navega com JS ativo — "Ver mais",
     um <a> normal dentro do popover, é o caminho de navegação); clique no
     botão "Fechar detalhes" fecha e devolve o foco ao ativador. */
  document.addEventListener("click", function (ev) {
    var botaoFechar = ev.target && ev.target.closest && ev.target.closest("[data-fechar-popover-calendario]");
    if (botaoFechar) {
      var popoverFechar = botaoFechar.closest(".br-tooltip[data-popover-calendario]");
      var ativadorFechar = ativadorDoPopover(popoverFechar);
      esconderPopoverCalendario(popoverFechar);
      if (ativadorFechar) ativadorFechar.focus();
      return;
    }
    var ativador = ativadorPopoverCalendario(ev.target);
    if (!ativador) return;
    ev.preventDefault();
    fixarPopoverCalendario(popoverDoAtivador(ativador));
  });

  /* Enter no ativador com foco também fixa (mesmo efeito do clique). */
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape") {
      var aberto = document.querySelector(".br-tooltip[data-popover-calendario][data-show]");
      if (!aberto) return;
      var ativadorAberto = ativadorDoPopover(aberto);
      esconderPopoverCalendario(aberto);
      if (ativadorAberto) ativadorAberto.focus();
      return;
    }
    if (ev.key !== "Enter") return;
    var ativador = ativadorPopoverCalendario(document.activeElement);
    if (!ativador || ativador !== document.activeElement) return;
    ev.preventDefault();
    fixarPopoverCalendario(popoverDoAtivador(ativador));
  });

  /* ---------- aria-expanded do acordeão (Fase 28) ---------- */
  /* references/componentes/accordion.md documenta a lacuna: "O JS não
     gerencia aria-expanded; adicione aria-expanded="false" e atualize por
     conta própria (ou aceite a lacuna)" — o `core.min.js` só alterna o
     atributo `active` no `.item` (CSS puro exibe/esconde o `.content`
     irmão), nunca `aria-expanded` do `button.header`. Sem isto, um leitor
     de tela nunca anuncia "expandido"/"recolhido" nos acordeões "Colunas"
     e "Mais filtros" (achado da matriz de acessibilidade de fechamento) — listener em `document` (bubbling), registrado depois do
     clique já ter alternado `active` (a ordem de disparo do próprio
     browser: o listener do vendor, ligado direto no botão, sempre roda
     antes de um listener delegado em `document` no mesmo evento de
     clique). Sincroniza TODOS os botões do MESMO `.br-accordion` a cada
     clique — cobre também o modo `single` do vendor (abrir um item fecha
     os demais). */
  document.addEventListener("click", function (ev) {
    var botao = ev.target && ev.target.closest && ev.target.closest(".br-accordion button.header");
    if (!botao) return;
    var raiz = botao.closest(".br-accordion");
    if (!raiz) return;
    raiz.querySelectorAll(".item > button.header").forEach(function (b) {
      var item = b.closest(".item");
      b.setAttribute("aria-expanded", item && item.hasAttribute("active") ? "true" : "false");
    });
  });

  /* ---------- Restauração de rolagem em <form method=get> sem HTMX ----------
     Telas que recarregam a página inteira a cada troca de filtro
     (Calendário/Análises/Resumo por unidade/Início, HTMX é exceção,
     não regra) voltavam ao topo a cada submissão — o "pisca" relatado pelo
     usuário. `/tabela` (o único form com `hx-get`) já preserva rolagem
     sozinha via HTMX/hx-push-url e é excluída por guarda explícita abaixo.
     `sessionStorage` (por aba, some ao fechar) guarda só um número (posição
     de rolagem) por pathname — nenhum dado pessoal, nunca enviado ao
     servidor. Restaura só quando `document.referrer` aponta para o MESMO
     pathname (troca de filtro na própria tela); chegar por essas telas pelo
     menu (referrer diferente ou ausente) nunca restaura rolagem de uma
     visita anterior não relacionada. */
  if (window.history && "scrollRestoration" in window.history) {
    window.history.scrollRestoration = "auto";
  }

  function chaveRolagem(pathname) {
    return "dsgov-scroll:" + pathname;
  }

  document.addEventListener("submit", function (ev) {
    var form = ev.target;
    if (!form || form.tagName !== "FORM") return;
    if ((form.method || "get").toLowerCase() !== "get") return;
    if (
      form.hasAttribute("hx-get") ||
      form.hasAttribute("hx-post") ||
      form.hasAttribute("hx-boost")
    ) {
      // `/tabela` é o único form com `hx-get` — já preserva rolagem sozinha
      // via HTMX/hx-push-url (medido, sem regressão desta guarda).
      return;
    }
    try {
      window.sessionStorage.setItem(
        chaveRolagem(window.location.pathname),
        String(window.scrollY)
      );
    } catch (e) {
      // sessionStorage indisponível (modo privado/quota) — sem rolagem
      // restaurada, sem quebrar a submissão.
    }
  });

  document.addEventListener("DOMContentLoaded", function () {
    var chave = chaveRolagem(window.location.pathname);
    var valor;
    try {
      valor = window.sessionStorage.getItem(chave);
      window.sessionStorage.removeItem(chave);
    } catch (e) {
      return;
    }
    if (valor === null) return;
    var referrerMesmoPathname = false;
    try {
      referrerMesmoPathname =
        document.referrer &&
        new URL(document.referrer).pathname === window.location.pathname;
    } catch (e) {
      referrerMesmoPathname = false;
    }
    if (!referrerMesmoPathname) return;
    window.scrollTo(0, parseInt(valor, 10) || 0);
  });

  /* ---------- Modal: ao salvar, fecha e volta para o MESMO ponto da tela ----------
     Regra única para DSGov e Tabler (o mesmo bloco vive em `pca-tabler.js`).
     Ao abrir o modal (`hx-get` com alvo `#modal-acompanhamento`), lembra o
     elemento com `id` mais próximo de quem abriu (a linha `#item-N` na
     tabela, a seção na ficha); ao enviar o formulário do modal, guarda em
     `sessionStorage` onde esse elemento estava na janela e a rolagem. Depois
     do sucesso — troca de `#listagem` (tabela, `HX-Location`) ou página
     nova (ficha, `HX-Redirect`) — rola até o elemento voltar exatamente ao
     mesmo ponto, mesmo que a mensagem de sucesso tenha entrado acima dele.
     Sem o elemento, volta à mesma rolagem. Expira em 30 s e só vale no
     mesmo pathname — nunca reaplica uma rolagem velha. */
  var CHAVE_MODAL = "pca-rolagem-modal";
  var ancoraModal = null;

  function lerRolagemModal() {
    try {
      var e = JSON.parse(window.sessionStorage.getItem(CHAVE_MODAL) || "null");
      if (!e || e.p !== window.location.pathname || Date.now() - e.t > 30000) return null;
      return e;
    } catch (err) {
      return null;
    }
  }

  function restaurarRolagemModal(limpar) {
    var e = lerRolagemModal();
    if (!e) return;
    var el = e.id && document.getElementById(e.id);
    if (el && typeof e.topo === "number") {
      window.scrollBy(0, el.getBoundingClientRect().top - e.topo);
    } else {
      window.scrollTo(0, e.y || 0);
    }
    if (limpar) {
      try { window.sessionStorage.removeItem(CHAVE_MODAL); } catch (err) { /* sem sessionStorage */ }
    }
  }

  document.addEventListener("htmx:beforeRequest", function (ev) {
    var d = ev.detail || {};
    if (!d.elt || !d.target || d.target.id !== "modal-acompanhamento") return;
    if (!d.elt.closest("#modal-acompanhamento")) {
      var comId = d.elt.closest("[id]");
      ancoraModal = comId ? comId.id : null;
      return;
    }
    if (d.elt.id !== "form-acompanhamento") return;
    var el = ancoraModal && document.getElementById(ancoraModal);
    try {
      window.sessionStorage.setItem(CHAVE_MODAL, JSON.stringify({
        p: window.location.pathname,
        id: el ? ancoraModal : null,
        topo: el ? el.getBoundingClientRect().top : null,
        y: window.scrollY,
        t: Date.now()
      }));
    } catch (err) {
      // sessionStorage indisponível — fecha sem restaurar, sem quebrar o envio.
    }
  });

  document.addEventListener("htmx:afterSettle", function (ev) {
    var alvo = ev.detail && (ev.detail.target || ev.detail.elt);
    if (alvo && alvo.id === "listagem") restaurarRolagemModal(true);
  });
  document.addEventListener("DOMContentLoaded", function () { restaurarRolagemModal(false); });
  window.addEventListener("load", function () { restaurarRolagemModal(true); });

  /* ---------- Composer de chat: Enter envia, Alt+Enter/Shift+Enter quebram
     linha, textarea cresce ----------
     Genérico, ativado por atributo — nunca por id de um sistema específico:
     qualquer `textarea[data-composer]` dentro de um `form`, delegado em
     `document` (funciona mesmo quando o elemento chega depois, por HTMX).
     Enter (sem modificador) dispara `form.requestSubmit()` — o htmx escuta o
     submit normal, então `hx-post` continua valendo. Shift+Enter não foi
     pedido, mas é o atalho que ChatGPT/Claude/Gemini usam para quebrar
     linha — sem ele, quem tem o dedo treinado nesses produtos envia a
     mensagem pela metade. Em toque (`pointer: coarse`, teclado virtual sem
     tecla Alt) Enter NUNCA envia — só o botão.

     Alt+Enter/Shift+Enter inserem a quebra de linha por conta própria
     (`setRangeText`), em vez de confiar no comportamento nativo do
     navegador: medido nesta quick que o Chromium NÃO trata Alt+Enter como
     comando de edição "inserir parágrafo" dentro de um `<textarea>` — o
     evento chega, mas nenhum caractere é inserido (Shift+Enter funciona
     nativamente; Alt+Enter, não, provavelmente por reserva de atalho do
     próprio navegador). Tratar os dois do mesmo jeito evita um atalho que
     simplesmente não faz nada em parte dos navegadores. */
  function textareaComposer(elemento) {
    return elemento && elemento.matches && elemento.matches("textarea[data-composer]")
      ? elemento
      : null;
  }

  document.addEventListener("keydown", function (ev) {
    var textarea = textareaComposer(ev.target);
    if (!textarea || ev.key !== "Enter" || ev.isComposing) return;
    if (window.matchMedia && window.matchMedia("(pointer: coarse)").matches) return;
    if (ev.altKey || ev.shiftKey) {
      ev.preventDefault();
      var inicio = textarea.selectionStart, fim = textarea.selectionEnd;
      textarea.setRangeText("\n", inicio, fim, "end");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
      return;
    }
    var form = textarea.form;
    if (!form) return;
    ev.preventDefault();
    if (typeof form.requestSubmit === "function") form.requestSubmit();
    else form.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
  });

  /* Cresce a cada `input` até um teto (`data-composer-max`, padrão 40vh) e
     volta à altura base (`style.height` limpo) depois de um envio bem-
     sucedido — `htmx:afterSwap` alcançando o composer (troca parcial que
     preserva ou recria o elemento) ou `reset` nativo do form. */
  function redimensionarComposer(textarea) {
    var teto = textarea.dataset.composerMax || "40vh";
    var tetoPx = /vh$/.test(teto)
      ? (window.innerHeight * parseFloat(teto)) / 100
      : parseFloat(teto) || window.innerHeight * 0.4;
    textarea.style.height = "auto";
    textarea.style.height = Math.min(textarea.scrollHeight, tetoPx) + "px";
  }

  document.addEventListener("input", function (ev) {
    var textarea = textareaComposer(ev.target);
    if (textarea) redimensionarComposer(textarea);
  });

  function restaurarAlturaComposer(raiz) {
    if (!raiz || !raiz.querySelectorAll) return;
    raiz.querySelectorAll("textarea[data-composer]").forEach(function (textarea) {
      textarea.style.height = "";
    });
  }

  document.addEventListener("htmx:afterSwap", function (ev) {
    restaurarAlturaComposer(ev.detail && ev.detail.target);
  });

  document.addEventListener(
    "reset",
    function (ev) {
      if (ev.target && ev.target.tagName === "FORM") restaurarAlturaComposer(ev.target);
    },
    true
  );

  /* ---------- Painel recolhível ----------
     Botão `[data-alternar-painel]` com `aria-controls="<id do painel>"`: alterna `hidden` no painel, a
     classe `dsgov-painel-recolhido` na linha que o contém (o dsgov.css alarga a coluna irmã a partir de
     1280px), `aria-expanded` e o rótulo (`data-rotulo-aberto`/`data-rotulo-fechado` no `[data-rotulo]` do
     botão). A escolha fica no `localStorage` de quem usa, por painel (só "aberto"/"recolhido", nada vai ao
     servidor); sem escolha guardada, o painel abre a partir de 1280px (coluna ao lado da lista) e nasce
     recolhido abaixo disso, onde ficaria em cima da lista. Sem `localStorage` (modo privado), vale a regra
     da largura. */
  var CHAVE_PAINEL = "dsgov:painel:";

  function lerPainel(id) {
    try { return window.localStorage.getItem(CHAVE_PAINEL + id); } catch (e) { return null; }
  }

  function gravarPainel(id, aberto) {
    try { window.localStorage.setItem(CHAVE_PAINEL + id, aberto ? "aberto" : "recolhido"); } catch (e) { /* sem localStorage */ }
  }

  function painelDoBotao(botao) {
    var id = botao.getAttribute("aria-controls");
    return id ? document.getElementById(id) : null;
  }

  function aplicarPainel(botao, painel, aberto) {
    painel.hidden = !aberto;
    if (painel.parentElement) painel.parentElement.classList.toggle("dsgov-painel-recolhido", !aberto);
    botao.setAttribute("aria-expanded", aberto ? "true" : "false");
    var rotulo = botao.querySelector("[data-rotulo]");
    var texto = botao.getAttribute(aberto ? "data-rotulo-aberto" : "data-rotulo-fechado");
    if (rotulo && texto) rotulo.textContent = texto;
  }

  document.addEventListener("DOMContentLoaded", function () {
    var largo = window.matchMedia ? window.matchMedia("(min-width: 1280px)").matches : true;
    document.querySelectorAll("[data-alternar-painel]").forEach(function (botao) {
      var painel = painelDoBotao(botao);
      if (!painel) return;
      var guardado = lerPainel(painel.id);
      aplicarPainel(botao, painel, guardado ? guardado === "aberto" : largo);
    });
  });

  document.addEventListener("click", function (ev) {
    var botao = ev.target && ev.target.closest && ev.target.closest("[data-alternar-painel]");
    if (!botao) return;
    var painel = painelDoBotao(botao);
    if (!painel) return;
    var aberto = painel.hidden;
    aplicarPainel(botao, painel, aberto);
    gravarPainel(painel.id, aberto);
  });

  window.dsgov = { iniciar: iniciar };
})();
