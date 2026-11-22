"""Tira os prints do manual do usuário na instância descartável (Playwright + Chromium headless).

Roda na imagem do robô (`toniaum/pca-cfc-robo:dev`, que já traz Playwright e Chromium), chamado
por `capturar.sh` na rede da instância descartável. Só stdlib + playwright; nunca envia formulário.

    python manual/capturas/capturar.py [--cenas a01-entrar,a03-inicio]

Entradas: /app/data/manual-mascara/{cenario,sessoes}.json, reais.txt e evitar.txt (gerados pelo
preparar.py na cópia) e /manual/extras.txt (opcional). Saídas em /saida: img/<parte>/<cena>.png,
textos/<cena>.txt e textos/menu-<persona>.txt. Sai 1 se algum texto capturado trouxer nome real
ou e-mail fora de @example.org — e então o capturar.sh não copia nada para o repositório.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import struct
import sys
import unicodedata
import zlib
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.environ.get("MANUAL_BASE", "http://127.0.0.1:8000").rstrip("/")
DADOS = Path("/app/data/manual-mascara")
EXTRAS = Path("/manual/extras.txt")
SAIDA = Path("/saida")
LARGURA, ALTURA = 1440, 900


# --- Cenas -----------------------------------------------------------------------------------
# id → parte, persona (None = sem login), url (chave de cenario["urls"] ou caminho que começa com
# "/"), acoes (lista de passos que só abrem/preenchem — nunca enviam), recorte (None = a tela,
# "pagina" = a página inteira, seletor CSS = só o elemento) e legenda (vai para o texto do manual).

def _abrir_grupo(rotulo):
    """Abre o menu lateral (br-menu, fechado por padrão na casca DSGov) e a pasta `rotulo`."""
    return {"abrir_grupo": rotulo}


def _escolher(campo, valor):
    """Escolhe uma opção num br-select (input de exibição + lista de rádios) sem enviar nada."""
    return {"escolher_br": campo, "valor": valor}


def _solicitacao(chave):
    return lambda cenario: cenario["solicitacoes"][chave]["url"]


def _item_da_solicitacao(chave):
    return lambda cenario: cenario["solicitacoes"][chave]["item"]["url"]


def _form(chave):
    return lambda cenario: cenario["formulario"][chave]


MENU = "#main-navigation .menu-panel"
PARTE_VALOR = '#main-content .br-card:has(input[type="text"][name$="-valor_ajuste"])'

CENAS = {
    # --- Para as áreas -----------------------------------------------------------------------
    "a01-entrar": {
        "parte": "areas", "persona": None, "url": "login",
        "recorte": None,
        "legenda": "Tela de entrada: e-mail institucional e senha.",
    },
    "a02-primeiro-acesso": {
        "parte": "areas", "persona": "eva", "url": "inicio", "recorte": None,
        "legenda": "No primeiro acesso, o sistema pede uma senha nova antes de qualquer outra tela.",
    },
    "a03-inicio": {
        "parte": "areas", "persona": "ana", "url": "inicio", "recorte": None,
        "legenda": "Página inicial de quem é de uma unidade.",
    },
    "a04-menu": {
        "parte": "areas", "persona": "ana", "url": "inicio",
        "acoes": [_abrir_grupo("Solicitações"), _abrir_grupo("Análises")],
        "recorte": MENU,
        "legenda": "Menu de quem é de uma unidade, com as pastas Análises e Solicitações abertas.",
    },
    "a05-processos": {
        "parte": "areas", "persona": "ana", "url": "processos_unidade", "recorte": None,
        "legenda": "Processos filtrados pela unidade.",
    },
    "a06-ficha": {
        "parte": "areas", "persona": "ana", "url": "ficha_exemplo", "recorte": None,
        "legenda": "Ficha do item, com o botão Solicitar alteração.",
    },
    "a07-ficha-solicitacoes": {
        "parte": "areas", "persona": "ana", "url": "ficha_exemplo",
        "acoes": [{"clicar": "#aba-solicitacoes"}], "recorte": '.br-tab:has(#aba-solicitacoes)',
        "legenda": "Aba Solicitações da ficha do item.",
    },
    "a08-resumo-unidade": {
        "parte": "areas", "persona": "ana", "url": "resumo_uo", "recorte": None,
        "legenda": "Resumo por unidade.",
    },
    "a09-painel": {
        "parte": "areas", "persona": "ana", "url": "analise", "recorte": None,
        "legenda": "Análises → Painel.",
    },
    "a10-nova": {
        "parte": "areas", "persona": "ana", "url": "nova", "recorte": None,
        "legenda": "Nova solicitação: escolha entre alterar/cancelar um item ou incluir um item novo.",
    },
    "a11-nova-alteracao": {
        "parte": "areas", "persona": "ana", "url": "nova_item",
        "acoes": [
            {"preencher": "#id_prazo_entrega", "valor": _form("prazo")},
            {"preencher": "#id_valor_estimado", "valor": _form("valor")},
            {"preencher": "#id_justificativa",
             "valor": "A área técnica precisa de mais prazo para concluir o termo de referência "
                      "e a pesquisa de preços indicou valores acima do estimado."},
        ],
        "recorte": "pagina",
        "legenda": "Pedido de alteração de prazo e valor, preenchido.",
    },
    "a12-nova-cancelamento": {
        "parte": "areas", "persona": "ana", "url": "nova_item",
        "acoes": [{"marcar": "#id_cancelamento"}],
        "recorte": {"de": '#main-content h2:text-is("Cancelamento"), #main-content :text-is("Cancelamento")',
                    "ate": '#main-content .br-message:has-text("Para quem vai cada parte")', "texto": "#main-content"},
        "legenda": "Bloco Cancelamento: pedido sozinho, sem outras alterações.",
    },
    "a13-nova-inclusao": {
        "parte": "areas", "persona": "ana", "url": "nova_inclusao",
        "acoes": [
            {"preencher": "#id_descricao_objeto",
             "valor": "Contratação de serviço de manutenção do mobiliário da unidade"},
            _escolher("tipo", lambda c: str(c["formulario"]["tipo_id"])),
            _escolher("categoria", lambda c: str(c["formulario"]["categoria_id"])),
            {"preencher": "#id_valor_estimado", "valor": "30.000,00"},
            _escolher("mes_previsto", "12"),
            {"preencher": "#id_justificativa",
             "valor": "O mobiliário não tem contrato de manutenção e vários itens estão danificados."},
        ],
        "recorte": "pagina",
        "legenda": "Pedido de inclusão de item novo, preenchido.",
    },
    "a14-minhas": {
        "parte": "areas", "persona": "ana", "url": "minhas", "recorte": "pagina",
        "legenda": "Minhas solicitações: abas Todas, Em análise e Decididas.",
    },
    "a15-detalhe-em-analise": {
        "parte": "areas", "persona": "ana", "url": _solicitacao("fora_exercicio"), "recorte": "pagina",
        "legenda": "Solicitação em análise, com a opção de desistir.",
    },
    "a16-detalhe-decidida": {
        "parte": "areas", "persona": "ana", "url": _solicitacao("mista_ajuste"), "recorte": "pagina",
        "legenda": "Solicitação decidida: uma parte aprovada e outra aprovada com ajuste.",
    },
    "a17-menu-leitura": {
        "parte": "areas", "persona": "bruno", "url": "inicio",
        "acoes": [_abrir_grupo("Análises")],
        "recorte": MENU,
        "legenda": "Menu do perfil de leitura: sem a pasta Solicitações.",
    },
    # --- Para a diretoria --------------------------------------------------------------------
    "d01-inicio-pendencias": {
        "parte": "diretoria", "persona": "daniel", "url": "inicio", "recorte": None,
        "legenda": "Página inicial da diretoria, com o aviso de solicitações para avaliar.",
    },
    "d02-menu-para-avaliar": {
        "parte": "diretoria", "persona": "daniel", "url": "inicio",
        "acoes": [_abrir_grupo("Solicitações"), _abrir_grupo("Análises")],
        "recorte": MENU,
        "legenda": "Menu da diretoria: Para avaliar com o número de pendências.",
    },
    "d03-para-avaliar": {
        "parte": "diretoria", "persona": "daniel", "url": "avaliar", "recorte": "pagina",
        "legenda": "Para avaliar (diretoria): cartões do alto e a fila de partes.",
    },
    "d04-para-avaliar-equipe": {
        "parte": "diretoria", "persona": "carla", "url": "avaliar", "recorte": "pagina",
        "legenda": "Para avaliar (equipe do PCA): só prazo e mês.",
    },
    "d05-avaliar-ajuste": {
        "parte": "diretoria", "persona": "daniel", "url": _solicitacao("diretoria_valor_objeto"),
        "acoes": [
            {"marcar": f'{PARTE_VALOR} input[type="radio"][value="ajuste"]'},
            {"preencher": f'{PARTE_VALOR} input[name$="-valor_ajuste"]', "valor": _form("valor_ajuste_b")},
            {"preencher": f'{PARTE_VALOR} textarea[name$="-motivo"]',
             "valor": "Aprovado um acréscimo menor, dentro da disponibilidade orçamentária."},
        ],
        "recorte": PARTE_VALOR,
        "legenda": "Decisão de uma parte: Aprovar com ajuste, com o valor concedido e o motivo.",
    },
    "d06-avaliar-inclusao": {
        "parte": "diretoria", "persona": "daniel", "url": _solicitacao("inclusao_em_analise"),
        "recorte": "pagina",
        "legenda": "Inclusão de item novo: só aprovar ou recusar.",
    },
    "d07-inclusao-aprovada": {
        "parte": "diretoria", "persona": "daniel", "url": _solicitacao("inclusao_aprovada"),
        "recorte": "pagina",
        "legenda": "Inclusão aprovada: a solicitação aponta o item criado.",
    },
    "d08-item-incluido": {
        "parte": "diretoria", "persona": "daniel", "url": _item_da_solicitacao("inclusao_aprovada"),
        "recorte": None,
        "legenda": "O item criado pela inclusão, com o próximo número do PCA.",
    },
    "d09-historico": {
        "parte": "diretoria", "persona": "carla", "url": _item_da_solicitacao("mista_ajuste"),
        "recorte": '.br-tab:has(#aba-acompanhamentos)',
        "legenda": "Acompanhamentos do item: o prazo aprovado entra como acompanhamento.",
    },
    "d10-prejudicada": {
        "parte": "diretoria", "persona": "daniel", "url": _solicitacao("prejudicada"),
        "recorte": "pagina",
        "legenda": "Parte prejudicada: o item foi cancelado enquanto o pedido estava em análise.",
    },
    "d11-todas": {
        "parte": "diretoria", "persona": "daniel", "url": "minhas", "recorte": "pagina",
        "legenda": "Todas as solicitações.",
    },
    "d12-relatorio-solicitacoes": {
        "parte": "diretoria", "persona": "carla", "url": "relatorio",
        "recorte": {"de": 'h2.abnt-secao:has-text("SOLICITAÇÕES DAS UNIDADES")',
                    "ate": "#relatorio-anexo-1", "texto": "#relatorio-documento"},
        "legenda": "Seção Solicitações das unidades do relatório da reunião.",
    },
    "d13-analises": {
        "parte": "diretoria", "persona": "daniel", "url": "analise",
        "acoes": [_abrir_grupo("Análises")],
        "recorte": None,
        "legenda": "Análises para a diretoria: Painel, Fluxo de caixa e Estatísticas.",
    },
}


# --- Utilidades ------------------------------------------------------------------------------

def normalizar(texto: str) -> str:
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", texto or "") if not unicodedata.combining(c)
    )
    return " ".join(sem_acento.casefold().split())


def recomprimir_png(caminho: Path) -> None:
    """Sem perda: junta os IDAT, recomprime com zlib nível 9 e regrava os CRCs."""
    dados = caminho.read_bytes()
    assinatura, pos = dados[:8], 8
    pedacos, idat = [], b""
    while pos < len(dados):
        (tamanho,) = struct.unpack(">I", dados[pos:pos + 4])
        tipo = dados[pos + 4:pos + 8]
        corpo = dados[pos + 8:pos + 8 + tamanho]
        pos += 12 + tamanho
        if tipo == b"IDAT":
            idat += corpo
            if not any(t == b"IDAT" for t, _ in pedacos):
                pedacos.append((b"IDAT", None))
        else:
            pedacos.append((tipo, corpo))
    novo_idat = zlib.compress(zlib.decompress(idat), 9)
    saida = bytearray(assinatura)
    for tipo, corpo in pedacos:
        corpo = novo_idat if tipo == b"IDAT" else corpo
        saida += struct.pack(">I", len(corpo)) + tipo + corpo
        saida += struct.pack(">I", zlib.crc32(tipo + corpo) & 0xFFFFFFFF)
    if len(saida) < len(dados):
        caminho.write_bytes(bytes(saida))


def carregar_reais():
    linhas = []
    for arquivo in (DADOS / "reais.txt", DADOS / "evitar.txt", EXTRAS):
        if arquivo.exists():
            for linha in arquivo.read_text(encoding="utf-8").splitlines():
                linha = linha.split("#", 1)[0].strip()
                if linha:
                    linhas.append(linha)
    nomes = sorted({normalizar(l) for l in linhas if "@" not in l and len(normalizar(l).split()) >= 2})
    emails = sorted({l.lower() for l in linhas if "@" in l})
    return nomes, emails


RE_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def conferir_vazamento(textos: dict) -> list:
    nomes, emails = carregar_reais()
    achados = []
    padroes = [(n, re.compile(r"(?<!\w)" + re.escape(n).replace(r"\ ", r"\s+") + r"(?!\w)")) for n in nomes]
    for cena, texto in textos.items():
        norm = normalizar(texto)
        for nome, padrao in padroes:
            m = padrao.search(norm)
            if m:
                ini = max(0, m.start() - 30)
                achados.append((cena, "nome real", norm[ini:m.end() + 30]))
        for m in RE_EMAIL.finditer(texto):
            if not m.group(0).lower().endswith("@example.org"):
                achados.append((cena, "e-mail", m.group(0)))
        baixo = texto.lower()
        for email in emails:
            if email in baixo:
                achados.append((cena, "e-mail real", email))
    return achados


# --- Captura ---------------------------------------------------------------------------------

def resolver_url(cenario, url):
    if url.startswith("/"):
        return BASE + url
    return BASE + cenario["urls"][url]


def executar_acoes(pagina, acoes, cenario):
    for acao in acoes or []:
        acao = {k: (v(cenario) if callable(v) else v) for k, v in acao.items()}
        if "abrir_grupo" in acao:
            abrir_pasta_do_menu(pagina, acao["abrir_grupo"])
        elif "escolher_br" in acao:
            campo = acao["escolher_br"]
            pagina.locator(f"#id_{campo}_exibicao").first.click()
            pagina.wait_for_timeout(300)
            pagina.locator(f'input[name="{campo}"][value="{acao["valor"]}"] + label').first.click()
            pagina.wait_for_timeout(300)
            pagina.locator("#main-content h1").first.click()  # fecha a lista
        elif "clicar" in acao:
            pagina.locator(acao["clicar"]).first.click()
        elif "preencher" in acao:
            pagina.locator(acao["preencher"]).first.fill(acao["valor"])
        elif "escolher" in acao:
            pagina.locator(acao["escolher"]).first.select_option(acao["valor"])
        elif "marcar" in acao:
            # br-checkbox/br-radio escondem o input nativo: clica-se no rótulo dele.
            caixa = pagina.locator(acao["marcar"]).first
            pagina.locator(f'label[for="{caixa.get_attribute("id")}"]').first.click()
        elif "esperar" in acao:
            pagina.wait_for_timeout(acao["esperar"])
        elif "rolar" in acao:
            pagina.locator(acao["rolar"]).first.scroll_into_view_if_needed()
        else:
            raise ValueError(f"ação desconhecida: {acao}")
    pagina.wait_for_timeout(400)  # transições do Bootstrap (collapse/abas)


def novo_contexto(navegador, sessoes, persona):
    contexto = navegador.new_context(
        viewport={"width": LARGURA, "height": ALTURA},
        device_scale_factor=1,
        locale="pt-BR",
        timezone_id="America/Sao_Paulo",
        extra_http_headers={"X-Forwarded-Proto": "https"},
    )
    if persona:
        contexto.add_cookies([{
            "name": sessoes["cookie"],
            "value": sessoes["personas"][persona],
            "url": BASE,
            "secure": False,
            "httpOnly": True,
        }])
    return contexto


def abrir_menu(pagina):
    """O br-menu da casca DSGov começa fechado; o botão ☰ do cabeçalho (#navigation) o abre."""
    if "active" not in (pagina.locator("#main-navigation").get_attribute("class") or ""):
        pagina.locator("#navigation").click()
        pagina.wait_for_timeout(600)


def abrir_pasta_do_menu(pagina, rotulo):
    abrir_menu(pagina)
    pasta = pagina.locator(
        f'#main-navigation .menu-folder:has(> a.menu-item:has-text("{rotulo}"))'
    )
    if pasta.count() and not pasta.first.locator("ul").first.is_visible():
        pasta.first.locator("> a.menu-item").click()
        pagina.wait_for_timeout(600)  # fim da animação da pasta


def capturar_menu(pagina, cenario, persona):
    pagina.goto(resolver_url(cenario, "inicio"), wait_until="networkidle")
    abrir_menu(pagina)
    for rotulo in pagina.locator("#main-navigation .menu-folder > a.menu-item").all_inner_texts():
        abrir_pasta_do_menu(pagina, rotulo.strip())
    texto = pagina.locator("#main-navigation .menu-body").inner_text()
    (SAIDA / "textos" / f"menu-{persona}.txt").write_text(texto, encoding="utf-8")
    return texto


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cenas", default="")
    args = parser.parse_args()
    escolhidas = [c.strip() for c in args.cenas.split(",") if c.strip()] or list(CENAS)
    desconhecidas = [c for c in escolhidas if c not in CENAS]
    if desconhecidas:
        print(f"cenas desconhecidas: {', '.join(desconhecidas)}", file=sys.stderr)
        return 2

    cenario = json.loads((DADOS / "cenario.json").read_text(encoding="utf-8"))
    sessoes = json.loads((DADOS / "sessoes.json").read_text(encoding="utf-8"))
    (SAIDA / "textos").mkdir(parents=True, exist_ok=True)

    textos = {}
    falhas = []
    with sync_playwright() as p:
        # O formato dos campos de data (dd/mm/aaaa) vem do idioma do processo, não do contexto.
        navegador = p.chromium.launch(args=["--lang=pt-BR"], env={
            **os.environ, "LANG": "pt_BR.UTF-8", "LANGUAGE": "pt_BR:pt", "LC_ALL": "pt_BR.UTF-8",
        })
        contextos = {}
        try:
            personas_usadas = {CENAS[c]["persona"] for c in escolhidas} - {None, "eva"}
            for persona in sorted(personas_usadas):
                contextos[persona] = novo_contexto(navegador, sessoes, persona)
                pagina = contextos[persona].new_page()
                textos[f"menu-{persona}"] = capturar_menu(pagina, cenario, persona)
                pagina.close()
            for cena_id in escolhidas:
                cena = CENAS[cena_id]
                persona = cena["persona"]
                contexto = contextos.get(persona)
                if contexto is None:
                    contexto = contextos[persona] = novo_contexto(navegador, sessoes, persona)
                pagina = contexto.new_page()
                pagina.set_viewport_size({"width": LARGURA, "height": cena.get("altura", ALTURA)})
                try:
                    url = cena["url"](cenario) if callable(cena["url"]) else cena["url"]
                    pagina.goto(resolver_url(cenario, url), wait_until="networkidle")
                    executar_acoes(pagina, cena.get("acoes"), cenario)
                    destino = SAIDA / "img" / cena["parte"] / f"{cena_id}.png"
                    destino.parent.mkdir(parents=True, exist_ok=True)
                    recorte = cena.get("recorte")
                    if recorte is None:
                        pagina.screenshot(path=str(destino))
                        texto = pagina.locator("body").inner_text()
                    elif recorte == "pagina":
                        # A página inteira numa tela da altura dela (o menu lateral acompanha).
                        altura = pagina.evaluate("() => document.documentElement.scrollHeight")
                        pagina.set_viewport_size({"width": LARGURA, "height": max(altura, ALTURA)})
                        pagina.wait_for_timeout(300)
                        pagina.screenshot(path=str(destino))
                        texto = pagina.locator("body").inner_text()
                    elif isinstance(recorte, dict):
                        # Faixa da página entre dois elementos irmãos (seção de um documento longo); o
                        # texto conferido é o da faixa.
                        de = pagina.locator(recorte["de"]).first.bounding_box()
                        ate = pagina.locator(recorte["ate"]).first.bounding_box()
                        caixa = pagina.locator(recorte["texto"]).first.bounding_box()
                        rolagem = pagina.evaluate("() => window.scrollY")
                        pagina.screenshot(path=str(destino), full_page=True, clip={
                            "x": caixa["x"], "y": de["y"] + rolagem - 16,
                            "width": caixa["width"], "height": ate["y"] - de["y"],
                        })
                        texto = pagina.locator(recorte["de"]).first.evaluate(
                            """(inicio, fim) => { let t = '', e = inicio, n = 0;
                                const para = (x) => { try { return x.matches(fim); } catch (err) { return false; } };
                                while (e && !para(e) && n++ < 40) { t += e.innerText + '\\n'; e = e.nextElementSibling; }
                                return t; }""", recorte["ate"])
                    else:
                        alvo = pagina.locator(recorte).first
                        alvo.scroll_into_view_if_needed()
                        alvo.screenshot(path=str(destino))
                        texto = alvo.inner_text()
                    recomprimir_png(destino)
                    (SAIDA / "textos" / f"{cena_id}.txt").write_text(
                        f"# {pagina.url}\n{texto}", encoding="utf-8"
                    )
                    textos[cena_id] = texto
                    print(f"ok  {cena_id:28s} {destino.stat().st_size // 1024:5d} KB  {pagina.url}")
                except Exception as erro:  # noqa: BLE001 — registrar e seguir para as outras cenas
                    falhas.append((cena_id, str(erro).splitlines()[0]))
                    print(f"ERRO {cena_id}: {erro}", file=sys.stderr)
                finally:
                    pagina.close()
        finally:
            navegador.close()

    achados = conferir_vazamento(textos)
    dono = os.environ.get("MANUAL_DONO", "")
    if dono:
        uid, gid = (int(x) for x in dono.split(":"))
        for raiz, pastas, arquivos in os.walk(SAIDA):
            for nome in pastas + arquivos:
                os.chown(os.path.join(raiz, nome), uid, gid)
    if achados:
        print("\nVAZAMENTO — nada será copiado para o repositório:", file=sys.stderr)
        for cena, tipo, trecho in achados:
            print(f"  {cena}: {tipo}: …{trecho}…", file=sys.stderr)
        return 1
    if falhas:
        print(f"\n{len(falhas)} cena(s) falharam: {', '.join(c for c, _ in falhas)}", file=sys.stderr)
        return 1
    print(f"\nconferência de vazamento: ok ({len(textos)} texto(s) conferidos)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
