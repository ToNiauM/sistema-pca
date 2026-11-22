"""Coletor de dados do SEI/CFC — promoção de
notas internas do projeto a código de produção.

Só Playwright + `apps.pca.sei.extracao`, sem ORM, sem `django.db`. O import
de `playwright` é PREGUIÇOSO (dentro de `coletar()`), para que este módulo
seja importável — embora não executável — no container `web`, que nunca
ganha Playwright instalado (o alvo `robo` do `Dockerfile` é o único que o
instala, via `requirements-robo.txt`).

Função pública única: `coletar(alvos)`. `alvos` é uma lista de
`{"item_pca": int, "exercicio": int, "numero_sei": str}` — um número SEI por
entrada; um item com N números aparece N vezes na lista. Devolve o envelope
`{"executado_em", "login", "processos": [...], "metricas": {...}}`, com
`item_pca`/`exercicio` carimbados em cada processo coletado.

O resto — seletores, espera de frames, paginação do histórico, árvore,
`_marcos` — é promovido como está do spike, já provado pela prova de acesso
(notas internas do projeto, veredito PASS).
"""

from __future__ import annotations

import html as html_mod
import re
import time
import urllib.parse
from datetime import datetime, timezone

from django.utils import timezone as django_timezone

from apps.pca.sei import montagem
from apps.pca.sei.extracao import (
    PROCESSOS_POR_LOTE,
    RE_CONTRATUAL,
    VERSAO_EXTRACAO_DOCUMENTO,
    deve_bloquear_recurso,
    tipo_documento,
)

BASE = "https://sei.cfc.org.br/sei/"
HOSTS = {"sei.cfc.org.br", "sip.cfc.org.br"}
RE_PROTOCOLO = re.compile(r"^(?P<rotulo>.*?)\s*\(?(?P<protocolo>\d{6,8})\)?\s*$")
RE_REGISTROS = re.compile(r"\((\d+)\s+registros?\b", re.I)
RE_INTERVALO = re.compile(r"\(\d+\s+registros?\s*-\s*(\d+)\s+a\s+\d+\)", re.I)
RE_ONCLICK_HIST = re.compile(r"consultarAndamento\('([^']+)'")
# Link de download do anexo externo, dentro do HTML
# RENDERIZADO (já com `html.unescape`) do frame `arvore_processar_html` —
# nunca aparece no atributo `src` do iframe (ver CONTEXT do plano).
RE_LINK_DOWNLOAD_ANEXO = re.compile(
    r"controlador\.php\?acao=documento_download_anexo[^\"'<>\s]*", re.I
)
# RE_HIST_ASSINADO/RE_ANON_POR/RE_ANON_USUARIO/RE_REMESSA movidas para
# `apps/pca/sei/montagem.py` (Fase 42) — usadas só por `marcos()`/`_anon()`,
# que também se mudaram para lá.

TIMEOUT_PADRAO_S = 30
PAUSA_ENTRE_PROCESSOS_S = 1.0

JS_ARVORE = """
() => {
  const out = [];
  for (const a of document.querySelectorAll("a[id^='anchor']")) {
    const m = /^anchor(\\d+)$/.exec(a.id);
    if (!m) continue;
    const ass = document.getElementById('anchorA' + m[1]);
    let tip = '';
    if (ass) { tip = ass.title || ''; const img = ass.querySelector('img[title]'); if (img) tip = tip || img.title; }
    out.push({id: m[1], texto: (a.innerText || '').replace(/\\s+/g, ' ').trim(), href: a.getAttribute('href') || '',
              title: a.title || '', tip});
  }
  const aguarde = document.querySelectorAll("a[id^='anchorAGUARDE']").length;
  return {anchors: out, aguarde};
}
"""
JS_TABELA = """
() => {
  const t = document.getElementById('tblHistorico');
  if (!t) return null;
  const linhas = [];
  for (const tr of t.querySelectorAll('tr')) {
    const tds = tr.querySelectorAll('td');
    if (tds.length < 4) continue;
    linhas.push([tds[0].innerText.trim(), tds[1].innerText.trim(), tds[3].innerText.replace(/\\s+/g, ' ').trim()]);
  }
  const prox = document.getElementById('lnkInfraProximaPaginaSuperior');
  const anc = document.getElementById('ancTipoHistorico');
  return {linhas, prox: !!(prox && prox.offsetParent !== null), tipo: anc ? anc.innerText.trim() : '',
          texto: (document.body.innerText || '').slice(0, 400)};
}
"""


# ----------------------------------------------------------------- utilidades

def url_publica(url):
    u = urllib.parse.urlsplit(url)
    query = urllib.parse.urlencode([(k, v) for k, v in urllib.parse.parse_qsl(u.query)
                                    if k in ("acao", "id_procedimento", "id_documento")])
    return urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, query, ""))


def acao_de(url):
    return urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).get("acao", [""])[0]


def esperar(condicao, timeout_s, intervalo=0.3, erro="tempo esgotado"):
    fim = time.monotonic() + timeout_s
    while time.monotonic() < fim:
        r = condicao()
        if r:
            return r
        time.sleep(intervalo)
    raise TimeoutError(erro)


class Rede:
    def __init__(self):
        self.bytes = 0
        self.requisicoes = 0

    def registrar(self, request):
        self.requisicoes += 1
        try:
            s = request.sizes()
            self.bytes += int(s.get("responseBodySize", 0)) + int(s.get("responseHeadersSize", 0))
        except Exception:
            pass

    def somar(self, n):
        self.requisicoes += 1
        self.bytes += n


# ------------------------------------------------------------------- navegador

_SELETOR_OVERLAY_NOVIDADES = ".sparkling-modal-overlay"
_SELETOR_FECHAR_NOVIDADES = "div[id^=divInfraSparklingModalClose] a"


class SEI:
    def __init__(self, context, rede, timeout_s):
        self.ctx = context
        self.rede = rede
        self.t = timeout_s
        self.p1 = context.new_page()
        self.p2 = context.new_page()
        for p in (self.p1, self.p2):
            p.set_default_timeout(timeout_s * 1000)
            p.on("requestfinished", rede.registrar)

    def _frame(self, nome):
        """`page.frame(name=)` só casa o atributo name; os iframes do SEI têm apenas id e o
        SEI preenche o src por JS depois do load — o Frame vem do próprio elemento."""
        el = self.p1.locator(f"#{nome}").first.element_handle(timeout=self.t * 1000)
        f = el.content_frame() if el else None
        if f is None:
            raise RuntimeError(f"frame {nome} ausente")
        return f

    def frame_arvore(self):
        return self._frame("ifrArvore")

    # --- login ---
    def fechar_modal_novidades(self):
        """Popup "Novidades" (`div[id^=divInfraSparklingModalContainer]`, overlay
        `.sparkling-modal-overlay`, z-index 999999999) que o SEI passou a abrir logo após o
        login — intercepta qualquer clique/Enter na página inteira até ser fechado. Chamado de
        `login()` imediatamente após a confirmação de `#txtPesquisaRapida`; best-effort, NUNCA
        propaga excecao — ausência do popup (caso normal) devolve `False` sem clicar em nada."""
        try:
            overlay = self.p1.locator(_SELETOR_OVERLAY_NOVIDADES).first
            if overlay.count() == 0 or not overlay.is_visible(timeout=500):
                return False
        except Exception:
            return False
        try:
            self.p1.locator(_SELETOR_FECHAR_NOVIDADES).first.click(timeout=2000)
        except Exception:
            try:
                self.p1.keyboard.press("Escape")
            except Exception:
                pass
        try:
            overlay.wait_for(state="hidden", timeout=3000)
        except Exception:
            pass
        return True

    def login(self, cfg):
        url = cfg.get("SEI_LOGIN_URL", BASE)
        if urllib.parse.urlsplit(url).scheme != "https" or urllib.parse.urlsplit(url).hostname not in HOSTS:
            raise ValueError("destino de login inesperado")
        self.p1.goto(url, wait_until="domcontentloaded")
        if urllib.parse.urlsplit(self.p1.url).hostname not in HOSTS:
            raise ValueError("redirecionamento inesperado")
        recusado = []

        def dialogo(d):
            if "inválid" in d.message.casefold():
                recusado.append(True)
            d.dismiss()

        self.p1.on("dialog", dialogo)
        self.p1.select_option("#selOrgao", label=cfg.get("SEI_ORGAO", "CFC"))
        self.p1.fill("#txtUsuario", cfg["SEI_USUARIO"])
        self.p1.fill("#pwdSenha", cfg["SEI_SENHA"])
        self.p1.click("#sbmAcessar")
        try:
            self.p1.wait_for_selector("#txtPesquisaRapida")
        except Exception:
            return {"autenticado": False, "erro": "credenciais_recusadas" if recusado else "login_nao_confirmado"}
        novidades_fechadas = False
        try:
            novidades_fechadas = self.fechar_modal_novidades()
        except Exception:
            pass
        unidade = ""
        try:
            unidade = self.p1.locator("#lnkInfraUnidade").first.inner_text(timeout=3000).strip()
        except Exception:
            pass
        return {"autenticado": urllib.parse.urlsplit(self.p1.url).hostname == "sei.cfc.org.br",
                "unidade": unidade, "url": url_publica(self.p1.url),
                "novidades_fechadas": novidades_fechadas}

    def logout(self):
        try:
            self.p1.click("#lnkInfraSairSistema", timeout=5000)
        except Exception:
            pass

    # --- pesquisa e árvore ---
    def abrir_processo(self, numero):
        campo = self.p1.locator("#txtPesquisaRapida")
        campo.fill(numero)
        with self.p1.expect_navigation(wait_until="domcontentloaded"):
            campo.press("Enter")
        titulo = self.p1.title().strip()
        info = {"titulo": titulo, "url_acao": acao_de(self.p1.url), "titulo_confere": titulo == f"SEI - {numero}"}
        if not info["titulo_confere"]:
            info["arvore_presente"] = self.p1.locator("#ifrArvore").count() > 0
            return info
        arvore = esperar(lambda: self._arvore_pronta(), self.t, erro="árvore não carregou")
        raiz = [a for a in arvore["anchors"] if a["texto"] == numero]
        info["numero_na_arvore"] = bool(raiz)
        if raiz:
            info["id_procedimento"] = raiz[0]["id"]
        return info

    def _arvore_pronta(self):
        try:
            f = self.frame_arvore()
            r = f.evaluate(JS_ARVORE)
        except Exception:
            return None
        return r if r["anchors"] else None

    def url_historico(self):
        f = self.frame_arvore()
        onclick = f.locator("a:has-text('Consultar Andamento')").first.get_attribute("onclick") or ""
        m = RE_ONCLICK_HIST.search(onclick)
        if not m:
            raise RuntimeError("link Consultar Andamento sem URL")
        return urllib.parse.urljoin(BASE, m.group(1))

    def abrir_todas_pastas(self):
        f = self.frame_arvore()
        botao = f.locator("img[title='Abrir todas as Pastas']")
        if not botao.count():
            return {"botao": False}
        antes = f.evaluate(JS_ARVORE)
        botao.first.click()
        estados = []

        def estavel():
            r = self._arvore_pronta()
            if not r or r["aguarde"]:
                return None
            estados.append(len(r["anchors"]))
            if len(estados) >= 2 and estados[-1] == estados[-2] and estados[-1] > len(antes["anchors"]):
                return r
            return None

        r = esperar(estavel, self.t, intervalo=0.5, erro="pastas não terminaram de abrir")
        return {"botao": True, "anchors_antes": len(antes["anchors"]), "anchors_depois": len(r["anchors"])}

    def documentos(self, id_procedimento):
        docs = []
        for a in self.frame_arvore().evaluate(JS_ARVORE)["anchors"]:
            if a["id"] == id_procedimento or not a["texto"]:
                continue
            m = RE_PROTOCOLO.match(a["texto"])
            rotulo, protocolo = (m.group("rotulo"), m.group("protocolo")) if m else (a["texto"], None)
            tip = a["tip"]
            cancelado = a["href"] == "about:blank" or a["title"].startswith("Documento Cancelado")
            docs.append({"id_documento": a["id"], "protocolo": protocolo, "rotulo": rotulo,
                         "cancelado": cancelado,
                         "motivo_cancelamento": a["title"].split(":", 1)[1].strip(" .") if cancelado and ":" in a["title"] else None,
                         "assinado_na_arvore": tip.startswith("Assinado"),
                         "assinantes_externos_na_arvore": tip.count("Usuário Externo"),
                         "contratual": bool(RE_CONTRATUAL.match(rotulo))})
        return docs

    # --- histórico (aba 2) — só marcos, nunca as linhas cruas (produção nunca
    # grava o histórico completo, diferente do spike que aceitava
    # --andamentos-completos para depuração).
    def _pagina_inicial_completa(self, url) -> tuple[dict, int | None]:
        """Extraído de `historico()` (Fase 34): navega até `url`, troca de modo
        resumido→completo quando necessário e corrige a página inicial da sessão — tudo o que
        precede a paginação, sem paginar além da 1ª página completa. Devolve `(tab, anunciado)`;
        `tab` carrega ainda as chaves internas `_resumido`/`_pagina_inicial_corrigida` (nunca
        vindas de `JS_TABELA`) para que `historico()` monte seu `resultado` sem duplicar esta
        lógica. `historico_resumo()` usa só `tab["linhas"]`/`anunciado`, ignorando as duas."""
        self.p2.goto(url, wait_until="domcontentloaded")
        tab = esperar(self._tabela, self.t, erro="tabela do histórico ausente")
        m = RE_REGISTROS.search(tab["texto"])
        resumido_info = None
        if "completo" in tab["tipo"]:  # estamos no resumido; link oferece o completo
            resumido_info = {"linhas": len(tab["linhas"]), "anunciado": int(m.group(1)) if m else None}
            antes = tab["linhas"]
            self.p2.locator("#ancTipoHistorico").click()
            tab = esperar(lambda: self._tabela_mudou(antes, tipo_esperado="resumido"), self.t,
                          erro="histórico completo não carregou")
            m = RE_REGISTROS.search(tab["texto"])
        elif "resumido" not in tab["tipo"]:
            raise RuntimeError(f"modo do histórico não identificado: {tab['tipo']!r}")
        anunciado = int(m.group(1)) if m else None
        # O SEI também lembra a PÁGINA da paginação na sessão: se o processo anterior terminou
        # na página k e este tem página k, o histórico abre em k — voltar à primeira.
        pagina_inicial_corrigida = False
        mi = RE_INTERVALO.search(tab["texto"])
        if mi and int(mi.group(1)) != 1:
            primeira = tab["linhas"][0]
            self.p2.evaluate("infraAcaoPaginar('=', 0, 'Infra', null)")
            tab = esperar(lambda: self._tabela_mudou_primeira(primeira), self.t, erro="volta à 1ª página falhou")
            mi = RE_INTERVALO.search(tab["texto"])
            if not mi or int(mi.group(1)) != 1:
                raise RuntimeError("histórico não voltou à primeira página")
            pagina_inicial_corrigida = True
        tab["_resumido"] = resumido_info
        tab["_pagina_inicial_corrigida"] = pagina_inicial_corrigida
        return tab, anunciado

    def historico(self, url):
        """O SEI lembra na sessão o último modo escolhido (verHistorico): a página pode
        abrir já em 'completo' — o texto do link #ancTipoHistorico diz em qual modo estamos."""
        tab, anunciado = self._pagina_inicial_completa(url)
        resultado = {}
        if tab["_resumido"] is not None:
            resultado["resumido"] = tab["_resumido"]
        if tab["_pagina_inicial_corrigida"]:
            resultado["pagina_inicial_corrigida"] = True
        todas = list(tab["linhas"])
        paginas = 1
        while tab["prox"]:
            # Espera pelo intervalo "(N registros - a a b)" seguinte, não pela 1ª linha: com
            # andamentos repetidos a 1ª linha da página k+1 pode ser igual à da página k.
            esperado = len(todas) + 1
            self.p2.locator("#lnkInfraProximaPaginaSuperior").first.click()
            tab = esperar(lambda: self._tabela_no_intervalo(esperado), self.t, erro="paginação não avançou")
            paginas += 1
            todas.extend(tab["linhas"])
            if paginas > 50:
                raise RuntimeError("paginação acima de 50 páginas")
        chaves = [str(l) for l in todas]
        resultado["completo"] = {
            "linhas": len(todas), "anunciado": anunciado, "paginas": paginas,
            "confere_com_anunciado": anunciado == len(todas),
            "linhas_duplicadas_exatas": len(chaves) - len(set(chaves)),
        }
        resultado["marcos"] = self._marcos(todas)
        return resultado

    def historico_resumo(self, url) -> dict:
        """Fase 34: só a 1ª página do histórico COMPLETO, sem paginar, sem
        `abrir_todas_pastas`, sem `documentos`/`ler_documento` — o sinal barato de "nada mudou"
        (spec §2 ponto 1). Devolve `{"registros": <total anunciado>, "primeiro": {"data_hora",
        "unidade", "descricao"} | None}` — `primeiro` é a 1ª linha da 1ª página tal como o SEI a
        lista (mais recente primeiro), diferente do `primeiro` de `_marcos` (mais antigo)."""
        tab, anunciado = self._pagina_inicial_completa(url)
        primeiro = None
        if tab["linhas"]:
            linha = tab["linhas"][0]
            primeiro = {"data_hora": linha[0], "unidade": linha[1], "descricao": montagem._anon(linha[2])}
        return {"registros": anunciado, "primeiro": primeiro}

    def _tabela(self):
        """None enquanto a página ainda navega (contexto destruído) ou sem tabela."""
        try:
            return self.p2.evaluate(JS_TABELA)
        except Exception:
            return None

    def _tabela_mudou(self, antes, tipo_esperado):
        tab = self._tabela()
        if tab and tipo_esperado in tab["tipo"] and tab["linhas"] and (
                tab["linhas"] != antes or len(tab["linhas"]) != len(antes)):
            return tab
        return None

    def _tabela_no_intervalo(self, inicio):
        tab = self._tabela()
        if not tab or not tab["linhas"]:
            return None
        mi = RE_INTERVALO.search(tab["texto"])
        return tab if mi and int(mi.group(1)) == inicio else None

    def _tabela_mudou_primeira(self, primeira):
        tab = self._tabela()
        return tab if tab and tab["linhas"] and tab["linhas"][0] != primeira else None

    @classmethod
    def _marcos(cls, linhas):
        """Delega a `apps.pca.sei.montagem.marcos` (Fase 42) —
        a lógica em si (e `_anon`) se mudou para lá, módulo puro reusado
        pelo futuro POST `/api/sei/coleta`. Assinatura preservada
        (`cls._marcos(linhas)`) para não quebrar as chamadas existentes."""
        return montagem.marcos(linhas)

    # --- anexo externo --------------------------------
    def _frame_por_url(self, contem):
        """Primeiro frame de `self.p1.frames` cuja `.url` contém `contem`,
        ou `None` — nunca lança (`.url` pode ser `None`/ausente em frame
        ainda não navegado)."""
        for f in self.p1.frames:
            try:
                # Frame desmontado (o SEI troca o `ifrVisualizacao` logo
                # após o clique) continua na lista até o Playwright processar
                # o evento — devolvê-lo faz toda leitura falhar com "Frame
                # was detached" (achado ao vivo, item 58, 02/10/2026).
                if f.is_detached():
                    continue
            except Exception:
                pass
            try:
                url = f.url or ""
            except Exception:
                url = ""
            if contem in url:
                return f
        return None

    def _link_anexo_externo(self):
        """Link `controlador.php?acao=documento_download_anexo...` dentro
        do HTML renderizado do frame `arvore_processar_html` (nunca no
        `src` do iframe — ver CONTEXT do plano). `None` quando o frame
        nunca aparece, ou `#divArvoreHtml` nunca contém o link — nunca
        lança."""
        def localizar():
            frame = self._frame_por_url("arvore_processar_html")
            if frame is None:
                return None
            try:
                html_renderizado = frame.locator("#divArvoreHtml").first.inner_html(timeout=500)
            except Exception:
                return None
            html_decodificado = html_mod.unescape(html_renderizado)
            m = RE_LINK_DOWNLOAD_ANEXO.search(html_decodificado)
            return m.group(0) if m else None

        # Nunca `esperar()` aqui: o `time.sleep` dele não deixa o Playwright
        # processar eventos, e `p1.frames` fica preso no frame já
        # desmontado — o link nunca aparecia no SEI real (item 58,
        # 02/10/2026). `p1.wait_for_timeout` espera bombeando os eventos.
        fim = time.monotonic() + self.t / 2
        while True:
            link = localizar()
            if link:
                return link
            if time.monotonic() >= fim:
                return None
            pausa = getattr(self.p1, "wait_for_timeout", None)
            if pausa is not None:
                pausa(300)
            else:
                time.sleep(0.3)

    def baixar_anexo_externo(self):
        """Baixa o anexo externo localizado por `_link_anexo_externo` —
        `None` quando o link não foi encontrado. Devolve `(corpo, content_
        type, status)`, somando os bytes em `self.rede` (mesmo padrão do
        download HTML de `ler_documento`)."""
        link = self._link_anexo_externo()
        if link is None:
            return None
        # `link` já veio decodificado de `_link_anexo_externo` (o
        # `html.unescape` já foi aplicado sobre o HTML renderizado antes da
        # busca pela regex) — nenhum unescape adicional aqui.
        url = urllib.parse.urljoin(BASE, link)
        r = self.ctx.request.get(url, max_redirects=3)
        corpo = r.body()
        self.rede.somar(len(corpo))
        return corpo, r.headers.get("content-type", ""), r.status

    # --- documentos (clique na árvore + busca do src) ---
    def ler_documento(self, doc, numero_processo=None):
        info = {k: doc[k] for k in ("id_documento", "protocolo", "rotulo", "assinantes_externos_na_arvore")}
        # tipo do documento é derivado só do rótulo (independente do conteúdo
        # ter sido lido ou não) — acrescentado ao retorno em todos os ramos.
        info["tipo"] = tipo_documento(doc["rotulo"])
        if doc["cancelado"]:
            # href="about:blank" e title "Documento Cancelado: <motivo>" — o clique nunca carrega nada.
            info["conteudo"] = "cancelado"
            info["motivo_cancelamento"] = doc["motivo_cancelamento"]
            # Indisponível explícito (nunca None implícito por
            # ausência de chave): sem OCR/PDF, um documento cancelado nunca
            # tem corpo para indexar.
            info["texto_corpo"] = None
            info["versao_extracao"] = VERSAO_EXTRACAO_DOCUMENTO
            return info
        marca = f"id_documento={doc['id_documento']}"

        def frame_do_documento():
            """O frame de conteúdo navega para arvore_visualizar&id_documento=<id>; depois o
            SEI preenche o src do ifrVisualizacao: documento_visualizar (HTML interno) ou
            arvore_processar_html (externo/PDF, sem id_documento)."""
            try:
                f = self._frame("ifrConteudoVisualizacao")
                if marca not in f.url:
                    return None
                src = f.locator("#ifrVisualizacao").first.get_attribute("src", timeout=1000) or ""
            except Exception:
                return None
            if not src or "blank" in src:
                return None
            if acao_de(src) == "documento_visualizar" and marca not in src:
                return None  # src ainda do documento anterior
            return src

        for tentativa in (1, 2):
            self.frame_arvore().locator(f"a#anchor{doc['id_documento']}").first.click()
            try:
                src = urllib.parse.urljoin(BASE, esperar(frame_do_documento, self.t / 2 if tentativa == 1 else self.t,
                                                          erro="src do documento não apareceu"))
                break
            except TimeoutError:
                if tentativa == 2:
                    raise
                info["clique_repetido"] = True
        info["acao_conteudo"] = acao_de(src)
        if info["acao_conteudo"] != "documento_visualizar":
            # Defaults do externo nunca baixado (`montagem.montar_documento`
            # sem `html`/`pdf_bytes`) — o ramo PDF abaixo os sobrescreve
            # quando o anexo é baixado com sucesso.
            info.update(montagem.montar_documento(
                id_documento=doc["id_documento"], protocolo=doc["protocolo"], rotulo=doc["rotulo"],
                assinantes_externos_na_arvore=doc["assinantes_externos_na_arvore"],
            ))
            # (Contrato) + (Termo
            # Aditivo) — só documento externo cujo rótulo começa com
            # "Contrato" ou "Termo Aditivo" é baixado e lido como PDF;
            # qualquer outro tipo externo (Apostilamento/etc.) permanece
            # "externo_nao_baixado" byte a byte. Falha de rede/parse aqui
            # NUNCA propaga — degrada para o comportamento de hoje.
            if info["tipo"] in ("contrato", "termo_aditivo"):
                try:
                    baixado = self.baixar_anexo_externo()
                except Exception:
                    baixado = None
                if baixado is not None:
                    corpo_pdf, content_type, status = baixado
                    info["http_status"] = status
                    info["bytes"] = len(corpo_pdf)
                    if "pdf" in (content_type or "").lower() or corpo_pdf[:4] == b"%PDF":
                        info.update(montagem.montar_documento(
                            id_documento=doc["id_documento"], protocolo=doc["protocolo"],
                            rotulo=doc["rotulo"],
                            assinantes_externos_na_arvore=doc["assinantes_externos_na_arvore"],
                            pdf_bytes=corpo_pdf, numero_processo=numero_processo,
                        ))
            return info
        r = self.ctx.request.get(src, max_redirects=3)
        corpo = r.body()
        self.rede.somar(len(corpo))
        ct = r.headers.get("content-type", "")
        info["http_status"] = r.status
        if "html" not in ct:
            info["conteudo"] = f"nao_html:{ct.split(';')[0]}"
            info["bytes"] = len(corpo)
            # Não HTML (PDF/imagem/etc.) — sem OCR, indisponível explícito:
            #nunca deixado ausente por engano. Caso puramente
            # do robô (depende do content-type da resposta HTTP), fora do
            # contrato da extensão — não passa por `montagem`.
            info["texto_corpo"] = None
            info["versao_extracao"] = VERSAO_EXTRACAO_DOCUMENTO
            return info
        texto_html_decodificado = corpo.decode("iso-8859-1" if "iso-8859-1" in ct else "utf-8", errors="replace")
        info["bytes"] = len(corpo)
        info.update(montagem.montar_documento(
            id_documento=doc["id_documento"], protocolo=doc["protocolo"], rotulo=doc["rotulo"],
            assinantes_externos_na_arvore=doc["assinantes_externos_na_arvore"],
            html=texto_html_decodificado,
        ))
        return info


# ------------------------------------------------------------------- coleta

_TIPOS_ASSINATURA_DUPLA = {"contrato", "termo_aditivo"}


def _documento_definitivo(info: dict) -> bool:
    """Fase 34: só leituras DEFINITIVAS entram em `cache["documentos"]` — HTML com
    assinatura completa para o tipo (contrato/aditivo exigem `assinado_cfc` E
    `assinado_externo`; apostilamento só `assinado_cfc`) e, quando há `valor`,
    `valor["confere"] is True`. Unilateral/`externo_nao_baixado`/`cancelado`/
    `valor_nao_confere`/qualquer outro tipo (inclusive `None`) nunca entram — são relidos.

    `conteudo == "pdf"` (anexo externo "Contrato..." lido
    com sucesso) entra na mesma disciplina do HTML — `tipo="contrato"` já
    está em `_TIPOS_ASSINATURA_DUPLA`, então a checagem de assinatura
    dupla abaixo se aplica sem mudança nenhuma; `pdf_sem_texto`/
    `pdf_outro_orgao`/`pdf_sem_assinatura_digital` nunca entram (não é
    `"html"` nem `"pdf"`)."""
    if info.get("conteudo") not in ("html", "pdf"):
        return False
    tipo = info.get("tipo")
    if tipo in _TIPOS_ASSINATURA_DUPLA:
        if not (info.get("assinado_cfc") and info.get("assinado_externo")):
            return False
    elif tipo == "apostilamento":
        if not info.get("assinado_cfc"):
            return False
    else:
        return False
    valor = info.get("valor")
    if valor is not None and valor.get("confere") is not True:
        return False
    return True


def _linha_progresso_item(item_pca, k, total, r) -> str:
    """Uma linha por processo, formato exato de coletado/pulado/erro.
    Pulo por coleta recente da extensão (Fase 42) ganha texto
    próprio, SEM mudar o texto do atalho de pulo antigo — ambos continuam
    reconhecidos como "pulado" por `execucoes.interpretar_linha_progresso`."""
    if r.get("resultado") == "erro":
        return f"item {item_pca} ({k}/{total}): erro — {r.get('erro', '')}"
    if r.get("motivo_pulo") == "extensao_recente":
        return f"item {item_pca} ({k}/{total}): pulado (coleta recente da extensão)"
    if r.get("pulado"):
        return f"item {item_pca} ({k}/{total}): pulado (sem mudança no histórico)"
    return f"item {item_pca} ({k}/{total}): coletado em {r.get('duracao_s')} s"


def _linha_progresso_final(coletados, pulados, erros, duracao_s) -> str:
    """Linha de resumo final, formato exato."""
    return f"coleta concluída: {coletados} coletados, {pulados} pulados, {erros} erros em {duracao_s} s"


def _linha_progresso_resolver_item(numero, k, total, r) -> str:
    """Uma linha por número SEI resolvido, espelhando `_linha_progresso_item`.
"""
    if r.get("resultado") == "erro":
        return f"SEI {numero} ({k}/{total}): erro — {r.get('erro', '')}"
    if r.get("resultado") == "nao_encontrado":
        return f"SEI {numero} ({k}/{total}): não encontrado"
    return f"SEI {numero} ({k}/{total}): resolvido"


def _linha_progresso_resolver_final(resolvidos, nao_encontrados, erros) -> str:
    """Linha de resumo final de `resolver_links`, espelhando
    `_linha_progresso_final`."""
    return (
        f"resolução concluída: {resolvidos} resolvidos, "
        f"{nao_encontrados} não encontrados, {erros} erros"
    )


def _documentos_desatualizados(anterior: dict | None) -> bool:
    """Fase 39 (A10) — `True` quando algum documento de
    `anterior["documentos_contratuais"]` tem `versao_extracao` diferente da
    atual (cache antigo, sem `texto_corpo`) — o sinal que faz
    `--reprocessar-documentos` atravessar o atalho de pulo mesmo com
    `registros`/`primeiro` inalterados. `anterior` ausente/sem a chave ->
    `False` (nada a reprocessar)."""
    if not anterior:
        return False
    for doc in anterior.get("documentos_contratuais") or []:
        if doc.get("versao_extracao") != VERSAO_EXTRACAO_DOCUMENTO:
            return True
    return False


def _marcos_desatualizados(anterior: dict | None) -> bool:
    """`True` quando `anterior["andamentos"]["marcos"]` existe mas NÃO
    tem a chave `"ultima_remessa"` (cache gravado antes desta quick, sem o marco de
    remessa) — força `coletar_um` a atravessar o atalho de pulo e recoletar o histórico
    completo, mesmo com `registros`/`primeiro` inalterados, para que `unidade_sei_atual`
    seja recalculada pela regra nova já na PRÓXIMA varredura, sem nenhuma flag/ação manual.
    `anterior`/`andamentos`/`marcos` ausentes -> `False` (nada a corrigir — a condição "sem
    cache anterior" do `if` de pulo já cobre esse caso)."""
    if not anterior:
        return False
    marcos = (anterior.get("andamentos") or {}).get("marcos")
    if marcos is None:
        return False
    # 29/09/2026 — mesma regra para `recebimentos_gelic_delic` (cache anterior ao marco).
    return "ultima_remessa" not in marcos or "recebimentos_gelic_delic" not in marcos


def _aditivo_externo_pendente(anterior: dict | None) -> bool:
    """`True` quando `anterior["documentos_contratuais"]` tem um
    documento `tipo=="termo_aditivo"` ainda `conteudo=="externo_nao_baixado"` (nunca
    baixado como PDF, porque o cache foi gravado ANTES desta quick) — força `coletar_um`
    a atravessar o atalho de pulo e reler a árvore do processo, mesmo com
    `registros`/`primeiro` idênticos, SEM exigir `reprocessar_documentos=True` (que relê
    documentos de TODOS os processos, não é o requisito aqui).

    Incondicional, mesmo padrão de `_marcos_desatualizados` (sem nenhum gate de
    `reprocessar_documentos`) — e pelo mesmo motivo: `_documentos_desatualizados` só pesa
    dentro de `reprocessar_documentos and ...`, então bumpar `VERSAO_EXTRACAO_DOCUMENTO`
    não bastaria por si só para "reler no próximo on-demand/diário sem a flag". Não bumpa
    `VERSAO_EXTRACAO_DOCUMENTO` nesta quick: nenhum cache anterior a ela tem um Termo
    Aditivo com `conteudo=="pdf"` para migrar — o schema novo só passa a existir para
    documentos nunca lidos antes.

    Documento já lido como PDF (`conteudo` em `"pdf"`/`"pdf_sem_texto"`/
    `"pdf_outro_orgao"`/`"pdf_sem_assinatura_digital"`) ou `tipo != "termo_aditivo"`
    (inclusive `"contrato"`, que já era baixado antes desta quick) -> `False` para esse
    documento. `anterior` ausente/`None`/`{}`/sem a chave -> `False`. Nunca lança."""
    if not anterior:
        return False
    for doc in anterior.get("documentos_contratuais") or []:
        if doc.get("tipo") == "termo_aditivo" and doc.get("conteudo") == "externo_nao_baixado":
            return True
    return False


def _documento_anterior(cache, anterior_processo, id_documento):
    """Entrada anterior de um documento, em QUALQUER uma das duas
    representações do cache (Fase 39): primeiro
    `cache["documentos"][id_documento]` (só documentos definitivos vivem
    aí); na ausência, procura em `anterior_processo["documentos_
    contratuais"]` (documento unilateral, que só existe na representação
    por processo). `None` quando não há nenhuma das duas."""
    doc_cache = (cache or {}).get("documentos", {}).get(id_documento)
    if doc_cache is not None:
        return doc_cache
    for doc in (anterior_processo or {}).get("documentos_contratuais") or []:
        if doc.get("id_documento") == id_documento:
            return doc
    return None


def coletar_um(
    sei,
    numero,
    cache=None,
    forcar=False,
    reprocessar_documentos=False,
    extensao=None,
    pular_se_extensao_h=24.0,
):
    """`cache` (Fase 34) é o dict `{"processos": {...}, "documentos": {...}}` de
    `execucoes.ler_cache()`, mutado por referência — quem grava em disco é o comando chamador,
    uma vez, ao final. `cache=None` desliga a lógica de pulo/gravação por completo (nenhum
    chamador de produção passa `None`; só testes que não se importam com cache o fazem).
    `forcar=True` ignora o atalho de pulo mesmo com `registros`/`primeiro` batendo — mas
    SOZINHO não relê documentos definitivos já no cache (A10): quem migra cache antigo sem
    `texto_corpo`/`nome` é `reprocessar_documentos=True` (Fase 39), que (1) também
    atravessa o atalho de pulo quando o cache anterior tem documento com `versao_extracao`
    desatualizada (`_documentos_desatualizados`) e (2) relê todo documento contratual cujo
    cache (por processo OU por `id_documento`) ainda não está na versão atual — preservando a
    entrada anterior (nunca corpo vazio) quando a releitura falha.

    `extensao`/`pular_se_extensao_h` (Fase 42) — `extensao` é o dict de
    `execucoes.ler_extensao()`. Quando `not forcar` e `extensao` tem uma entrada para `numero`
    recebida há MENOS de `pular_se_extensao_h` horas, `coletar_um` pula o número por INTEIRO —
    nem `sei.abrir_processo` chega a ser chamado — e reconstrói `r` a partir da `coleta`
    armazenada naquela entrada (mesmo princípio do atalho de pulo existente abaixo, mas
    ANTERIOR a ele: aquele atalho só decide depois de abrir o processo e ler o histórico;
    este decide antes de qualquer chamada ao SEI). `pular_se_extensao_h <= 0` desliga esse
    pulo por completo (preserva o comportamento anterior à Fase 42)."""
    if not forcar and extensao and pular_se_extensao_h > 0:
        entrada_extensao = extensao.get("processos", {}).get(numero)
        if entrada_extensao:
            recebido_em = datetime.fromisoformat(entrada_extensao["recebido_em"])
            horas_passadas = (django_timezone.now() - recebido_em).total_seconds() / 3600
            if horas_passadas < pular_se_extensao_h:
                coleta = entrada_extensao.get("coleta") or {}
                r = {
                    "numero": numero,
                    "pulado": True,
                    "motivo_pulo": "extensao_recente",
                    "duracao_s": 0.0,
                }
                for chave in ("total_documentos", "andamentos", "documentos_contratuais", "resultado"):
                    r[chave] = coleta.get(chave)
                return r

    inicio = time.monotonic()
    r = {"numero": numero, "etapas_s": {}}
    marca = [time.monotonic()]

    def etapa(nome):
        agora = time.monotonic()
        r["etapas_s"][nome] = round(agora - marca[0], 2)
        marca[0] = agora

    try:
        r["abertura"] = sei.abrir_processo(numero)
        etapa("abertura")
        if not r["abertura"].get("titulo_confere"):
            r["resultado"] = "nao_encontrado"
        elif not r["abertura"].get("id_procedimento"):
            r["resultado"] = "arvore_sem_raiz"
        else:
            url_hist = sei.url_historico()
            resumo = sei.historico_resumo(url_hist)
            etapa("historico_resumo")
            anterior = (cache or {}).get("processos", {}).get(numero)
            if (
                not forcar
                and anterior
                and anterior.get("registros") == resumo["registros"]
                and anterior.get("primeiro") == resumo["primeiro"]
                and not (reprocessar_documentos and _documentos_desatualizados(anterior))
                # Incondicional (não depende de `reprocessar_documentos`)
                # — um cache anterior a esta quick nunca é reaproveitado pelo atalho de
                # pulo, mesmo com registros/primeiro idênticos.
                and not _marcos_desatualizados(anterior)
                # Mesmo padrão incondicional — um Termo Aditivo
                # externo ainda `externo_nao_baixado` força a releitura da árvore do
                # processo, mesmo sem `reprocessar_documentos=True`.
                and not _aditivo_externo_pendente(anterior)
            ):
                # Nada mudou desde a última coleta completa: reconstrói o resultado
                # anterior em vez de abrir pastas/documentos — `regras.propor()` (§3.3)
                # não diferencia processo pulado de coletado, então as chaves precisam ser
                # exatamente as mesmas de uma coleta completa.
                for chave in (
                    "pastas", "total_documentos", "andamentos", "documentos_contratuais", "resultado",
                ):
                    r[chave] = anterior.get(chave)
                r["pulado"] = True
            else:
                r["pastas"] = sei.abrir_todas_pastas()
                etapa("arvore")
                docs = sei.documentos(r["abertura"]["id_procedimento"])
                r["total_documentos"] = len(docs)
                r["andamentos"] = sei.historico(url_hist)
                etapa("historico")
                r["documentos_contratuais"] = []
                for d in docs:
                    if d["contratual"]:
                        r["documento_em_leitura"] = {"id_documento": d["id_documento"], "rotulo": d["rotulo"]}
                        doc_cache = (cache or {}).get("documentos", {}).get(d["id_documento"])
                        # Fase 39: doc_cache só é reaproveitado direto quando
                        # não estamos reprocessando OU ele já está na versão de extração
                        # atual — cache desatualizado cai no ramo de releitura abaixo.
                        if doc_cache is not None and (
                            not reprocessar_documentos
                            or doc_cache.get("versao_extracao") == VERSAO_EXTRACAO_DOCUMENTO
                        ):
                            r["documentos_contratuais"].append({**doc_cache, "do_cache": True})
                        else:
                            anterior_doc = _documento_anterior(cache, anterior, d["id_documento"])
                            if reprocessar_documentos and anterior_doc is not None:
                                # Releitura de migração: falha preserva a entrada
                                # anterior (nunca corpo vazio) — o comando chamador
                                # conta essas entradas por `reprocessamento_erro`.
                                try:
                                    lido = sei.ler_documento(d, numero_processo=numero)
                                except Exception as exc:
                                    lido = dict(anterior_doc)
                                    lido["reprocessamento_erro"] = (
                                        f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}"
                                    )
                                    lido["do_cache"] = True
                                r["documentos_contratuais"].append(lido)
                            else:
                                r["documentos_contratuais"].append(sei.ler_documento(d, numero_processo=numero))
                r.pop("documento_em_leitura", None)
                etapa("documentos")
                r["resultado"] = "ok"
                if cache is not None:
                    cache.setdefault("processos", {})[numero] = {
                        "registros": resumo["registros"],
                        "primeiro": resumo["primeiro"],
                        "coletado_em": django_timezone.localtime().isoformat(),
                        "id_procedimento": r["abertura"].get("id_procedimento"),
                        "pastas": r.get("pastas"),
                        "total_documentos": r.get("total_documentos"),
                        "andamentos": r.get("andamentos"),
                        "documentos_contratuais": r["documentos_contratuais"],
                        "resultado": r["resultado"],
                    }
                    for doc in r["documentos_contratuais"]:
                        if doc.get("do_cache"):
                            continue
                        if _documento_definitivo(doc):
                            entrada = {k: v for k, v in doc.items() if k != "do_cache"}
                            entrada["lido_em"] = django_timezone.localtime().isoformat()
                            cache.setdefault("documentos", {})[doc["id_documento"]] = entrada
    except Exception as exc:
        r["resultado"] = "erro"
        r["erro"] = f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}"
    r["duracao_s"] = round(time.monotonic() - inicio, 2)
    return r


def _novo_contexto(browser):
    """Novo contexto do navegador, com bloqueio de imagens/fontes (§8.1
    ponto 3, `extracao.deve_bloquear_recurso`) já registrado."""
    context = browser.new_context(locale="pt-BR")

    def _rotear(route):
        if deve_bloquear_recurso(route.request.resource_type):
            route.abort()
        else:
            route.continue_()

    context.route("**/*", _rotear)
    return context


def coletar(
    alvos: list[dict],
    cache: dict | None = None,
    forcar: bool = False,
    progresso=None,
    reprocessar_documentos: bool = False,
    extensao: dict | None = None,
    pular_se_extensao_h: float = 24.0,
) -> dict:
    """Coleta os processos SEI de `alvos` (`[{"item_pca", "exercicio",
    "numero_sei"}, ...]`, um número por entrada). Devolve
    `{"executado_em", "login", "processos": [...], "metricas": {...}}`, com
    `item_pca`/`exercicio` carimbados em cada processo. Credenciais lidas de
    `settings.SEI_*` (nunca de argumento de linha de comando em produção,
    nunca logadas). Bloqueia estáticos e recicla o contexto do navegador a
    cada `PROCESSOS_POR_LOTE` itens (§8.1). Sessão única, logout ao final de
    toda execução, inclusive em erro fatal.

    `cache`/`forcar` (Fase 34) repassados a `coletar_um` — `coletar`
    NÃO cria um cache novo quando `cache is None` nem inclui `cache` no
    envelope de retorno; quem grava em disco, uma vez ao final, é o comando
    chamador. `progresso`, opcional, `callable(str)`, recebe uma
    linha por processo (coletado/pulado/erro) mais uma linha final de
    resumo. `reprocessar_documentos` (Fase 39) repassado a
    `coletar_um` — migra o cache antigo (sem `texto_corpo`/`nome`) sem
    aplicar nada ao PCA. `extensao`/`pular_se_extensao_h` (Fase 42, Plano
    42-05) repassados a `coletar_um` por `alvo`, sem nenhuma outra
    mudança no loop — pulam número por número já informado recentemente
    pelas extensões SEI Pro.
    """
    from django.conf import settings  # import local — settings só configurado em runtime
    from playwright.sync_api import sync_playwright  # import preguiçoso — nunca no topo do módulo

    cfg = {
        "SEI_USUARIO": settings.SEI_USUARIO,
        "SEI_SENHA": settings.SEI_SENHA,
        "SEI_LOGIN_URL": settings.SEI_LOGIN_URL,
        "SEI_ORGAO": settings.SEI_ORGAO,
    }
    rede = Rede()
    t0 = time.monotonic()
    saida = {"executado_em": datetime.now(timezone.utc).isoformat(), "login": None, "processos": []}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        sei = None
        try:
            context = _novo_contexto(browser)
            sei = SEI(context, rede, TIMEOUT_PADRAO_S)
            login_info = sei.login(cfg)
            login_info["duracao_s"] = round(time.monotonic() - t0, 2)
            saida["login"] = login_info
            if login_info.get("autenticado"):
                processados_no_lote = 0
                idx = 0
                while idx < len(alvos):
                    alvo = alvos[idx]
                    if processados_no_lote >= PROCESSOS_POR_LOTE:
                        # Reciclagem de contexto (§8.1 ponto 2): fecha e reabre
                        # a cada PROCESSOS_POR_LOTE itens, para o pico de RAM
                        # ficar perto do custo de um processo grande, não do
                        # acumulado da varredura inteira.
                        context.close()
                        context = _novo_contexto(browser)
                        sei = SEI(context, rede, TIMEOUT_PADRAO_S)
                        relogin = sei.login(cfg)
                        if not relogin.get("autenticado"):
                            # Sessão perdida na reciclagem: marca os itens
                            # restantes como erro e segue — nunca trava a
                            # varredura inteira por um re-login que falhou.
                            for restante in alvos[idx:]:
                                saida["processos"].append({
                                    "numero": restante["numero_sei"],
                                    "item_pca": restante["item_pca"],
                                    "exercicio": restante["exercicio"],
                                    "resultado": "erro",
                                    "erro": "relogin_falhou_apos_reciclagem_de_contexto",
                                })
                            break
                        processados_no_lote = 0
                    r = coletar_um(
                        sei,
                        alvo["numero_sei"],
                        cache=cache,
                        forcar=forcar,
                        reprocessar_documentos=reprocessar_documentos,
                        extensao=extensao,
                        pular_se_extensao_h=pular_se_extensao_h,
                    )
                    r["item_pca"] = alvo["item_pca"]
                    r["exercicio"] = alvo["exercicio"]
                    saida["processos"].append(r)
                    if progresso is not None:
                        progresso(_linha_progresso_item(alvo["item_pca"], idx + 1, len(alvos), r))
                    processados_no_lote += 1
                    idx += 1
                    time.sleep(PAUSA_ENTRE_PROCESSOS_S)
        finally:
            if sei is not None:
                try:
                    sei.logout()
                except Exception:
                    pass
            browser.close()

    ok = [x for x in saida["processos"] if x.get("resultado") == "ok"]
    saida["metricas"] = {
        "duracao_total_s": round(time.monotonic() - t0, 1),
        "processos": len(saida["processos"]),
        "ok": len(ok),
        "media_s_por_processo_ok": round(sum(x["duracao_s"] for x in ok) / len(ok), 1) if ok else None,
        "max_s_por_processo": max((x.get("duracao_s", 0) for x in saida["processos"]), default=None),
        "rede_total_mb": round(rede.bytes / 1e6, 2),
        "requisicoes": rede.requisicoes,
    }
    if progresso is not None:
        coletados = sum(
            1 for p in saida["processos"] if p.get("resultado") == "ok" and not p.get("pulado")
        )
        pulados = sum(1 for p in saida["processos"] if p.get("pulado"))
        erros = sum(1 for p in saida["processos"] if p.get("resultado") == "erro")
        progresso(_linha_progresso_final(coletados, pulados, erros, saida["metricas"]["duracao_total_s"]))
    return saida


def _resolver_um(sei, numero) -> dict:
    """Resolução BARATA de um número SEI: só
    `abrir_processo` + (`abrir_todas_pastas` + `documentos()` filtrados a
    `contratual=True`) quando `titulo_confere` — NUNCA `historico`/
    `historico_resumo`/`ler_documento`. Mesma extração de mensagem de erro
    truncada de `coletar_um`."""
    r = {"numero": numero}
    try:
        r["abertura"] = sei.abrir_processo(numero)
        if not r["abertura"].get("titulo_confere"):
            r["resultado"] = "nao_encontrado"
        else:
            sei.abrir_todas_pastas()
            docs = sei.documentos(r["abertura"].get("id_procedimento"))
            r["documentos_contratuais"] = [d for d in docs if d["contratual"]]
            r["resultado"] = "ok"
    except Exception as exc:
        r["resultado"] = "erro"
        r["erro"] = f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}"
    return r


def resolver_links(numeros: list[str], progresso=None) -> dict:
    """Resolvedor barato de hiperlinks SEI (coberto por
    `sei_resolver_links`): MESMO envelope de `coletar()`
    (`{"executado_em", "login", "processos": [...]}`), mas cada item só faz
    `abrir_processo` + (`abrir_todas_pastas` + `documentos()`) — sem
    histórico, sem `ler_documento`. Login/logout uma única vez para toda a
    lista, sem reciclagem de contexto/lote (listas de pendentes são
    pequenas). Import de `playwright`/`django.conf.settings` só aqui dentro,
    igual a `coletar()`.

    `progresso`, opcional, `callable(str)`,
    recebe uma linha por número SEI (resolvido/não encontrado/erro) mais uma
    linha final de resumo — mesmo contrato de `coletar()`, mas
    `resolver_links` NUNCA participa do lock `em_execucao` (só
    `sei_sincronizar` participa); quem chama `progresso` aqui é só
    `sei_resolver_links`, para stdout + log próprio."""
    from django.conf import settings  # import local — settings só configurado em runtime
    from playwright.sync_api import sync_playwright  # import preguiçoso — nunca no topo do módulo

    cfg = {
        "SEI_USUARIO": settings.SEI_USUARIO,
        "SEI_SENHA": settings.SEI_SENHA,
        "SEI_LOGIN_URL": settings.SEI_LOGIN_URL,
        "SEI_ORGAO": settings.SEI_ORGAO,
    }
    rede = Rede()
    saida = {"executado_em": datetime.now(timezone.utc).isoformat(), "login": None, "processos": []}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        sei = None
        try:
            context = _novo_contexto(browser)
            sei = SEI(context, rede, TIMEOUT_PADRAO_S)
            login_info = sei.login(cfg)
            saida["login"] = login_info
            if login_info.get("autenticado"):
                for idx, numero in enumerate(numeros):
                    saida["processos"].append(_resolver_um(sei, numero))
                    if progresso is not None:
                        progresso(_linha_progresso_resolver_item(
                            numero, idx + 1, len(numeros), saida["processos"][-1]
                        ))
                    time.sleep(PAUSA_ENTRE_PROCESSOS_S)
        finally:
            if sei is not None:
                try:
                    sei.logout()
                except Exception:
                    pass
            browser.close()

    if progresso is not None:
        resolvidos = sum(1 for p in saida["processos"] if p.get("resultado") == "ok")
        nao_encontrados = sum(
            1 for p in saida["processos"] if p.get("resultado") == "nao_encontrado"
        )
        erros = sum(1 for p in saida["processos"] if p.get("resultado") == "erro")
        progresso(_linha_progresso_resolver_final(resolvidos, nao_encontrados, erros))

    return saida
