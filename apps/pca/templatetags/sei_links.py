"""Filtros de hiperlink SEI — vocabulário de domínio,
não pertence a `core/templatetags/dsgov.py` (fixo do padrão DSGov), mesmo padrão
de `pca_listagem.py`.

Mapa `data/sei/links.json` lido do disco só quando o `mtime` muda
(`functools.lru_cache`) — nunca 1 leitura por linha da tabela.

IMPORTANTE: `linkar_sei` é usado junto de `linebreaksbr`, e SEMPRE antes
dele — a ordem é `|linkar_sei|linebreaksbr`, nunca o contrário, senão
`linebreaksbr` re-escapa as tags que `linkar_sei` acabou de inserir.
"""

from __future__ import annotations

import functools
import re

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

from apps.pca.sei import execucoes

register = template.Library()

_URL_PROCEDIMENTO = (
    "https://sei.cfc.org.br/sei/controlador.php?acao=procedimento_trabalhar&id_procedimento={}"
)
# Não existe link direto para DOCUMENTO do SEI: `documento_visualizar` só abre com o `infra_hash` da sessão
# de quem está logado, e de fora o SEI responde "Link sem assinatura". Todo documento aponta para o
# PROCESSO dele (`procedimento_trabalhar`, que o SEI aceita sem hash) — decisão do usuário em 2026-09-23.

# Fase 39 — alias público, para que o Assistente do PCA
# (`apps.assistente.ferramentas`/`fontes`) importe o host do SEI daqui em
# vez de repeti-lo como string literal.
URL_PROCEDIMENTO = _URL_PROCEDIMENTO


def url_processo_sei(numero_sei, mapa=None):
    """Link do processo SEI `numero_sei` (o único tipo de link do SEI que funciona fora da sessão), ou
    `None` quando o processo ainda não foi resolvido no mapa `links.json`."""
    mapa = mapa if mapa is not None else _mapa_links()
    id_procedimento = (mapa.get("processos", {}).get(numero_sei) or {}).get("id_procedimento")
    return _URL_PROCEDIMENTO.format(id_procedimento) if id_procedimento else None

RE_NUMERO_PROCESSO = re.compile(r"\d{14}\.\d{6}/\d{4}-\d{2}")
RE_PROTOCOLO_LIVRE = re.compile(r"SEI\s*n[ºo°]?\s*(\d{7})|\((\d{7})\)", re.I)


def _mtime_links() -> float:
    caminho = execucoes.diretorio_base() / "links.json"
    try:
        return caminho.stat().st_mtime
    except OSError:
        return 0.0


@functools.lru_cache(maxsize=8)
def _links_cache(mtime: float) -> dict:
    return execucoes.ler_links()


def _mapa_links() -> dict:
    return _links_cache(_mtime_links())


@register.filter
def link_sei(numero_sei):
    """Número de processo SEI como link clicável (`<a>` para
    `procedimento_trabalhar`), texto puro sem entrada no mapa, ou o texto
    marcado com a tag "não encontrado no SEI" quando a resolução já rodou e
    não achou o processo."""
    if not numero_sei:
        return numero_sei
    entrada = _mapa_links().get("processos", {}).get(numero_sei)
    if not entrada:
        return numero_sei
    if entrada.get("nao_encontrado"):
        return mark_safe(
            f'{escape(numero_sei)} <span class="br-tag"><span>não encontrado no SEI</span></span>'
        )
    id_procedimento = entrada.get("id_procedimento")
    if id_procedimento:
        url = _URL_PROCEDIMENTO.format(id_procedimento)
        return mark_safe(f'<a href="{escape(url)}" target="_blank" rel="noopener">{escape(numero_sei)}</a>')
    return numero_sei


@register.filter
def linkar_sei(texto):
    """Transforma números de processo SEI e protocolos de documento citados
    em texto livre em links clicáveis, quando resolvidos em `links.json`.
    Escapa PRIMEIRO (os dois regex só casam dígitos/pontuação, nunca `<>&`,
    então a ordem escapar->substituir é segura)."""
    if not texto:
        return texto
    mapa = _mapa_links()
    escapado = escape(texto)

    def _sub_numero(m: re.Match) -> str:
        numero = m.group(0)
        entrada = mapa.get("processos", {}).get(numero)
        id_procedimento = entrada.get("id_procedimento") if entrada else None
        if not id_procedimento:
            return numero
        url = _URL_PROCEDIMENTO.format(id_procedimento)
        return f'<a href="{escape(url)}" target="_blank" rel="noopener">{numero}</a>'

    def _sub_protocolo(m: re.Match) -> str:
        trecho = m.group(0)
        protocolo = m.group(1) or m.group(2)
        entrada = mapa.get("documentos", {}).get(protocolo)
        # Documento citado abre o processo dele (ver nota sobre `documento_visualizar` no topo).
        url = url_processo_sei(entrada.get("numero_sei"), mapa) if entrada else None
        if not url:
            return trecho
        return f'<a href="{escape(url)}" target="_blank" rel="noopener">{trecho}</a>'

    resultado = RE_NUMERO_PROCESSO.sub(_sub_numero, escapado)
    resultado = RE_PROTOCOLO_LIVRE.sub(_sub_protocolo, resultado)
    return mark_safe(resultado)
