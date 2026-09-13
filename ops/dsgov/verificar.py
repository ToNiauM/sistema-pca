#!/usr/bin/env python3
"""Verificador de conformidade com o DSGov — cópia versionada do
`~/.claude/skills/dsgov/scripts/verificar.py`. BLOQUEANTE: saída 1 se
houver erro.

Invariante de portabilidade: `CORE_CSS`/`FA_CSS`/`SKILL_CSS_DIR` abaixo
apontam para `core/static/dsgov/**` deste repositório, nunca para
`~/.claude/skills/dsgov`. A suíte (`test_dsgov_conformidade.py`) não pode
depender de `~/.claude` para passar; pode usá-lo só para auditar (segundo
teste, pulado quando a skill não está instalada no host). Resto do arquivo
idêntico ao original — mesmas 10 regras, nenhuma lógica nova.

Uso:
    python3 ops/dsgov/verificar.py <raiz-do-projeto> [--json] [--avisos-como-erros]

O que ele garante (cada regra tem um código que aparece no relatório):
  CLASSE     toda classe CSS usada em template existe no core.min.css do DS 3.7.0, no Font Awesome 5,
             no dsgov.css da skill ou na lista de exceções técnicas (htmx-*, sr-only...).
  ESTILO     nenhum style="..." inline e nenhum <style> em template.
  COR        nenhum hex de cor em template (exceto theme-color do base.html).
  CDN        nenhum <link>/<script> apontando para http(s) externo; CSS/JS só os fixos da skill.
  CSS        nenhum .css no projeto além dos da skill; dsgov.css e fontes.css intactos.
  FONTE      nenhum font-family em template.
  ESTRUTURA  base.html com os partials na ordem; páginas estendem base.html; um <h1> por página.
  ELEMENTO   <button> sempre br-button/br-sign-in/br-item; <select> nativo proibido (use o renderer);
             <table> sempre dentro de .br-table; <input> fora de wrapper do DS.
  ICONE      <i class="fa..."> sem aria-hidden (aviso).
  PRIMARIO   mais de um br-button primary no mesmo template de página (aviso).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

# Raiz deste repositório (`ops/dsgov/../..`), não a pasta da skill; os 3
# caminhos abaixo refletem a árvore real vendorizada, conferida em disco.
RAIZ_REPO = Path(__file__).resolve().parent.parent.parent
CORE_CSS = RAIZ_REPO / "core/static/dsgov/vendor/govbr-ds/core.min.css"
FA_CSS = RAIZ_REPO / "core/static/dsgov/vendor/fontawesome/css/all.min.css"
SKILL_CSS_DIR = RAIZ_REPO / "core/static/dsgov/css"

EXCECOES = {
    # utilidades técnicas sem CSS próprio (hooks de JS do DS presentes nos exemplos oficiais)
    "htmx-indicator", "htmx-request", "htmx-added", "htmx-settling", "htmx-swapping",
    "per-page", "total", "current", "search-trigger", "name", "limit", "characters", "not-found",
    "help-text", "upload-label", "upload-input", "upload-list", "notification-tooltip",
    "template-base", "main-content", "results", "label", "header-avatar", "header-sign-in", "header-login",
    "menu-close", "menu-title", "menu-header", "menu-footer", "menu-info", "menu-scrim", "menu-body", "menu-panel", "menu-container",
    # classes de estado que o JS do DS aplica dinamicamente
    "active", "is-active", "is-selected", "selected", "expanded", "highlighted", "focus-visible",
}
CSS_PERMITIDOS = {"fontes.css", "core.min.css", "all.min.css", "dsgov.css"}
JS_PERMITIDOS = {"core.min.js", "htmx.min.js", "echarts.min.js", "dsgov.js", "echarts-dsgov.js"}
PARTIAIS_ORDEM = ["dsgov/_skiplink.html", "dsgov/_header.html", "dsgov/_menu.html",
                  "dsgov/_breadcrumb.html", "dsgov/_mensagens.html", "dsgov/_footer.html"]
IGNORAR_DIRS = {"node_modules", "staticfiles", ".venv", "venv", ".git", "__pycache__", "vendor", "migrations", "admin"}

RE_TAG_DJANGO = re.compile(r"\{%.*?%\}|\{\{.*?\}\}|\{#.*?#\}", re.S)
RE_CLASS_ATTR = re.compile(r'class\s*=\s*"([^"]*)"|class\s*=\s*\'([^\']*)\'', re.I)
RE_HEX = re.compile(r"#(?:[0-9a-fA-F]{3}){1,2}\b")


def classes_do_css(caminho: Path) -> set[str]:
    css = caminho.read_text(encoding="utf-8", errors="ignore")
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    # remove blocos de declaração (repetidamente, para @media aninhado)
    anterior = None
    while anterior != css:
        anterior = css
        css = re.sub(r"\{[^{}]*\}", "{}", css)
    return set(re.findall(r"\.(-?[_a-zA-Z][\w-]*)", css.replace("\\", "")))


def classes_no_template(texto: str) -> list[tuple[int, str]]:
    """[(linha, classe)] já sem tags Django dentro do atributo."""
    saida = []
    for m in RE_CLASS_ATTR.finditer(texto):
        bruto = m.group(1) if m.group(1) is not None else m.group(2)
        limpo = RE_TAG_DJANGO.sub(" ", bruto)
        linha = texto.count("\n", 0, m.start()) + 1
        for c in limpo.split():
            saida.append((linha, c))
    return saida


class Relatorio:
    def __init__(self):
        self.erros: list[dict] = []
        self.avisos: list[dict] = []

    def erro(self, arquivo, linha, regra, msg):
        self.erros.append({"arquivo": str(arquivo), "linha": linha, "regra": regra, "mensagem": msg})

    def aviso(self, arquivo, linha, regra, msg):
        self.avisos.append({"arquivo": str(arquivo), "linha": linha, "regra": regra, "mensagem": msg})


def linha_de(texto: str, pos: int) -> int:
    return texto.count("\n", 0, pos) + 1


def verificar_template(arq: Path, raiz: Path, permitidas: set[str], rel: Relatorio):
    texto = arq.read_text(encoding="utf-8", errors="ignore")
    rel_path = arq.relative_to(raiz)
    e_pagina = not arq.name.startswith("_") and "dsgov/" not in str(rel_path).replace("\\", "/") and arq.name != "base.html"

    # CLASSE
    for linha, c in classes_no_template(texto):
        if c in permitidas or c in EXCECOES:
            continue
        if c.startswith("fa-") or c in ("fa", "fas", "far", "fab"):
            continue
        rel.erro(rel_path, linha, "CLASSE", f'classe "{c}" não existe no DSGov 3.7.0 nem no dsgov.css')

    # ESTILO
    for m in re.finditer(r"\sstyle\s*=", texto):
        rel.erro(rel_path, linha_de(texto, m.start()), "ESTILO", "atributo style inline é proibido; use classes do DS")
    for m in re.finditer(r"<style\b", texto, re.I):
        rel.erro(rel_path, linha_de(texto, m.start()), "ESTILO", "<style> em template é proibido")

    # COR
    sem_django = RE_TAG_DJANGO.sub("", texto)
    for m in RE_HEX.finditer(sem_django):
        trecho = sem_django[max(0, m.start() - 60): m.start()]
        if "theme-color" in trecho:
            continue
        # ignora âncoras (#main-content) e ids: exige contexto de cor (aspas/dois-pontos antes)
        antes = sem_django[max(0, m.start() - 1): m.start()]
        if antes in ('"', "'", ":", " ", "(") and re.fullmatch(r"#(?:[0-9a-fA-F]{3}){1,2}", m.group(0)):
            palavra = re.search(r"[#\w-]+", sem_django[m.start():]).group(0)
            if palavra.lower() == m.group(0).lower():
                rel.erro(rel_path, linha_de(sem_django, m.start()), "COR", f"cor {m.group(0)} solta no template; cores só via tokens/classes do DS")

    # CDN / arquivos fixos
    for m in re.finditer(r'<(link|script)\b[^>]*?(?:href|src)\s*=\s*"([^"]+)"', texto, re.I):
        url = m.group(2)
        if url.startswith(("http://", "https://", "//")):
            rel.erro(rel_path, linha_de(texto, m.start()), "CDN", f"recurso externo proibido: {url}")
            continue
        nome = url.split("'")[1].split("/")[-1] if "{% static" in url else url.split("/")[-1]
        if m.group(1).lower() == "link" and "stylesheet" in m.group(0) and nome not in CSS_PERMITIDOS:
            rel.erro(rel_path, linha_de(texto, m.start()), "CDN", f"CSS fora da lista fixa da skill: {nome}")
        if m.group(1).lower() == "script" and nome and nome not in JS_PERMITIDOS:
            rel.erro(rel_path, linha_de(texto, m.start()), "CDN", f"JS fora da lista fixa da skill: {nome}")

    # FONTE
    for m in re.finditer(r"font-family", texto, re.I):
        rel.erro(rel_path, linha_de(texto, m.start()), "FONTE", "font-family em template é proibido (Rawline vem do DS)")

    # ELEMENTO
    for m in re.finditer(r"<button\b[^>]*>", texto, re.I):
        tag = m.group(0)
        if not re.search(r'class\s*=\s*"[^"]*\b(br-button|br-sign-in|br-item|step-progress-btn|wizard-progress-btn|header|tab-item)\b', tag):
            rel.erro(rel_path, linha_de(texto, m.start()), "ELEMENTO", "<button> sem br-button (ou br-sign-in/br-item)")
    for m in re.finditer(r"<select\b", texto, re.I):
        rel.erro(rel_path, linha_de(texto, m.start()), "ELEMENTO", "<select> nativo proibido; use {{ form.campo }} (br-select do renderer)")
    if re.search(r"<table\b", texto, re.I) and "br-table" not in texto:
        rel.erro(rel_path, 1, "ELEMENTO", "<table> fora de <div class=\"br-table\">")
    for m in re.finditer(r"<(input|textarea)\b[^>]*>", texto, re.I):
        tag = m.group(0)
        if re.search(r'type\s*=\s*"(hidden|submit)"', tag):
            continue
        antes = texto[max(0, m.start() - 600): m.start()]
        if not re.search(r"br-(input|select|checkbox|radio|switch|textarea|upload|datetimepicker)", antes):
            rel.erro(rel_path, linha_de(texto, m.start()), "ELEMENTO", f"<{m.group(1)}> fora de wrapper do DS (br-input, br-checkbox...); prefira {{{{ form.campo }}}}")

    # ICONE
    for m in re.finditer(r"<i\b[^>]*class\s*=\s*\"[^\"]*\bfa[sbr]?\b[^\"]*\"[^>]*>", texto, re.I):
        if "aria-hidden" not in m.group(0):
            rel.aviso(rel_path, linha_de(texto, m.start()), "ICONE", 'ícone sem aria-hidden="true"')

    # ESTRUTURA
    if arq.name == "base.html" and str(rel_path).endswith("templates/base.html"):
        pos = [texto.find(p) for p in PARTIAIS_ORDEM]
        if any(p < 0 for p in pos):
            faltando = [p for p, i in zip(PARTIAIS_ORDEM, pos) if i < 0]
            rel.erro(rel_path, 1, "ESTRUTURA", f"base.html sem os partials obrigatórios: {', '.join(faltando)}")
        elif pos != sorted(pos):
            rel.erro(rel_path, 1, "ESTRUTURA", "partials do base.html fora da ordem fixa")
    if e_pagina:
        if "<!DOCTYPE html>" in texto or "<!doctype html>" in texto:
            # página autônoma (login): precisa carregar os partials de identidade
            for parcial in ("dsgov/_header.html", "dsgov/_footer.html"):
                if parcial not in texto:
                    rel.erro(rel_path, 1, "ESTRUTURA", f"página autônoma sem {{% include \"{parcial}\" %}}")
        elif "{% extends" not in texto:
            rel.erro(rel_path, 1, "ESTRUTURA", "template de página não estende base.html")
        h1 = len(re.findall(r"<h1\b", texto, re.I))
        if h1 > 1:
            rel.erro(rel_path, 1, "ESTRUTURA", f"{h1} <h1> na mesma página; deve haver exatamente um")
        primarios = len(re.findall(r'class\s*=\s*"[^"]*\bbr-button\b[^"]*\bprimary\b', texto))
        if primarios > 1:
            rel.aviso(rel_path, 1, "PRIMARIO", f"{primarios} botões primary no mesmo template; a ação principal é única")


def verificar_css(raiz: Path, rel: Relatorio):
    for css in raiz.rglob("*.css"):
        partes = set(css.parts)
        if partes & IGNORAR_DIRS:
            continue
        if css.name in ("dsgov.css", "fontes.css") and css.parent.name == "css" and css.parent.parent.name == "dsgov":
            oficial = SKILL_CSS_DIR / css.name
            if oficial.exists() and hashlib.sha256(css.read_bytes()).hexdigest() != hashlib.sha256(oficial.read_bytes()).hexdigest():
                rel.erro(css.relative_to(raiz), 1, "CSS", f"{css.name} foi modificado; ele é congelado pela skill")
            continue
        rel.erro(css.relative_to(raiz), 1, "CSS", "arquivo CSS do projeto fora da skill; todo estilo vem do DS")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("raiz", type=Path)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--avisos-como-erros", action="store_true")
    args = ap.parse_args()
    raiz = args.raiz.resolve()
    if not raiz.exists():
        print(f"pasta não encontrada: {raiz}", file=sys.stderr)
        sys.exit(2)

    permitidas = classes_do_css(CORE_CSS) | classes_do_css(FA_CSS)
    for css in SKILL_CSS_DIR.glob("*.css"):
        permitidas |= classes_do_css(css)

    rel = Relatorio()
    templates = [p for p in raiz.rglob("*.html") if not (set(p.parts) & IGNORAR_DIRS) and "templates" in p.parts]
    for arq in sorted(templates):
        verificar_template(arq, raiz, permitidas, rel)
    verificar_css(raiz, rel)

    erros = rel.erros + (rel.avisos if args.avisos_como_erros else [])
    avisos = [] if args.avisos_como_erros else rel.avisos
    if args.json:
        print(json.dumps({"erros": erros, "avisos": avisos, "templates": len(templates)}, ensure_ascii=False, indent=2))
    else:
        for e in erros:
            print(f"ERRO   {e['arquivo']}:{e['linha']}: [{e['regra']}] {e['mensagem']}")
        for a in avisos:
            print(f"aviso  {a['arquivo']}:{a['linha']}: [{a['regra']}] {a['mensagem']}")
        print(f"\n{len(templates)} templates verificados · {len(erros)} erro(s) · {len(avisos)} aviso(s)")
        print("CONFORME ao DSGov." if not erros else "NÃO CONFORME: corrija os erros acima antes de entregar.")
    sys.exit(1 if erros else 0)


if __name__ == "__main__":
    main()
