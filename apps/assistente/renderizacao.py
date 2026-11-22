"""Renderização fechada da resposta do modelo (A04).

`MarkdownIt("zero")` com SÓ `paragraph`/`emphasis`/`list`/`backticks`
habilitadas: HTML, links, imagens e autolinks do modelo NUNCA viram
elemento ativo — saem como texto escapado. `mark_safe` só aparece neste
módulo."""

from __future__ import annotations

from django.utils.html import escape
from django.utils.safestring import SafeString, mark_safe
from markdown_it import MarkdownIt

# Markdown permitido: parágrafo, negrito/itálico, listas, código
# inline e (29/09/2026) tabela — a célula passa pelas mesmas regras, então HTML
# e links dentro dela continuam texto. `html=False` garante que qualquer tag HTML do modelo saia
# escapada; sem `link`/`image`/`autolink`/`linkify`, `[t](url)`,
# `![alt](src)` e `<http://…>` nunca viram `<a>`/`<img>`.
_REGRAS_PERMITIDAS = ("paragraph", "emphasis", "list", "backticks", "table")

# (Fase 39) — `renderizar_documento` é para os arquivos do MANIFESTO
# (autorados no repositório, nunca saída do modelo): além do conjunto
# fechado acima, habilita `heading` (h2/h3) e `link`. Continua `html=False`
# e sem `image` — link só com esquema http/https (`validate_link` abaixo);
# qualquer outro esquema (`javascript:`, `data:`...) vira texto puro.
_REGRAS_PERMITIDAS_DOCUMENTO = _REGRAS_PERMITIDAS + ("heading", "link")
_ESQUEMAS_LINK_PERMITIDOS = ("http://", "https://")

_URL_SEI_PREFIXO = "https://sei.cfc.org.br/"


def _montar_renderer() -> MarkdownIt:
    md = MarkdownIt("zero")
    md.enable(list(_REGRAS_PERMITIDAS))
    md.options["html"] = False
    return md


def _validar_link_documento(url: str) -> bool:
    return url.startswith(_ESQUEMAS_LINK_PERMITIDOS)


def _montar_renderer_documento() -> MarkdownIt:
    md = MarkdownIt("zero")
    md.enable(list(_REGRAS_PERMITIDAS_DOCUMENTO))
    md.options["html"] = False
    # `validateLink` (nome exato do método do markdown-it-py) — sobrescrito
    # na INSTÂNCIA para aceitar só http(s), mesmo que o default da lib já
    # bloqueie esquemas óbvios como `javascript:` (defesa em profundidade).
    md.validateLink = _validar_link_documento
    return md


_MD = _montar_renderer()
_MD_DOCUMENTO = _montar_renderer_documento()


def _envolver_tabelas(html: str) -> str:
    """Tabela da resposta com a cara da casca ativa e rolagem lateral quando larga. O modelo não
    consegue produzir `<table>` literal (html=False escapa), então só o markdown-it gera essas tags."""
    from django.conf import settings

    if getattr(settings, "PCA_DESIGN", "dsgov") == "tabler":
        abre, fecha = '<div class="table-responsive my-2"><table class="table table-sm table-bordered">', "</table></div>"
    else:
        abre, fecha = '<div class="br-table small my-2"><div class="responsive"><table>', "</table></div></div>"
    return html.replace("<table>", abre).replace("</table>", fecha)


def renderizar_resposta(texto_md: str) -> SafeString:
    if not texto_md:
        return mark_safe("")
    return mark_safe(_envolver_tabelas(_MD.render(texto_md)))


def renderizar_documento(texto_md: str) -> SafeString:
    """Variante para os 3 arquivos do manifesto (`docs/*.md`) —
    conteúdo autorado no repositório, não saída do modelo: habilita
    `heading`/`link` (só http/https; qualquer outro esquema vira texto),
    continua `html=False`, sem `image`."""
    if not texto_md:
        return mark_safe("")
    return mark_safe(_MD_DOCUMENTO.render(texto_md))


def renderizar_referencias(referencias: list[dict]) -> SafeString:
    """`<ul>` com `<a>` SÓ para URLs relativas (vindas de `reverse()`, que
    começam com `/`) ou com o prefixo HTTPS do host SEI configurado;
    qualquer outra URL vira texto sem link."""
    if not referencias:
        return mark_safe("")
    itens_html = []
    for referencia in referencias:
        rotulo = escape(referencia.get("rotulo", ""))
        url = referencia.get("url") or ""
        if url.startswith("/") or url.startswith(_URL_SEI_PREFIXO):
            itens_html.append(f'<li><a href="{escape(url)}">{rotulo}</a></li>')
        else:
            itens_html.append(f"<li>{rotulo}</li>")
    return mark_safe("<ul>" + "".join(itens_html) + "</ul>")
