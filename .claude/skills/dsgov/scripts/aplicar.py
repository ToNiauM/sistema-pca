#!/usr/bin/env python3
"""Aplica o padrão DSGov (skill dsgov) a um projeto Django EXISTENTE.

Uso:
    python3 <skill>/scripts/aplicar.py <raiz-do-projeto> [--app-core core] [--sobrescrever]

O que faz:
  1. Copia para <app-core>/ os módulos da skill que não existem: listagem.py, graficos.py, menu.py,
     middleware.py, context_processors.py, forms/renderer.py, templatetags/dsgov.py.
  2. Copia os templates (base.html, dsgov/*, core/login.html, core/erro.html, core/inicio.html) e os
     estáticos (core/static/dsgov/** com os vendors congelados).
  3. Imprime, sem editar, o bloco de settings/urls que precisa entrar no projeto (o projeto existente
     tem convenções próprias; editar settings às cegas é pior do que pedir 6 linhas).
Arquivos existentes só são substituídos com --sobrescrever. Rode verificar.py depois de adaptar as telas.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
MODELO = SKILL / "assets/projeto/core"
sys.path.insert(0, str(SKILL / "scripts"))
from novo_projeto import copiar_vendor  # noqa: E402

MODULOS = ["listagem.py", "graficos.py", "menu.py", "middleware.py", "context_processors.py",
           "forms/__init__.py", "forms/renderer.py", "templatetags/__init__.py", "templatetags/dsgov.py"]
TEMPLATES = ["templates/base.html", "templates/core/login.html", "templates/core/erro.html", "templates/core/inicio.html"]


def copiar(origem: Path, destino: Path, sobrescrever: bool):
    if destino.exists() and not sobrescrever:
        print(f"  mantido  {destino}")
        return
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(origem, destino)
    print(f"  copiado  {destino}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("raiz", type=Path)
    ap.add_argument("--app-core", default="core", help="app onde ficam layout e utilitários (padrão: core)")
    ap.add_argument("--sobrescrever", action="store_true")
    args = ap.parse_args()
    raiz = args.raiz.resolve()
    core = raiz / args.app_core
    if not (raiz / "manage.py").exists():
        sys.exit(f"não parece um projeto Django (sem manage.py): {raiz}")
    core.mkdir(exist_ok=True)

    print("== módulos Python")
    for m in MODULOS:
        copiar(MODELO / m, core / m, args.sobrescrever)
    print("== templates")
    for t in TEMPLATES:
        copiar(MODELO / t, core / t, args.sobrescrever)
    for t in sorted((MODELO / "templates/dsgov").rglob("*.html")):
        copiar(t, core / "templates/dsgov" / t.relative_to(MODELO / "templates/dsgov"), args.sobrescrever)
    print("== estáticos")
    for e in sorted((MODELO / "static/dsgov").rglob("*")):
        if e.is_file():
            copiar(e, core / "static/dsgov" / e.relative_to(MODELO / "static/dsgov"), True)
    copiar_vendor(raiz if args.app_core == "core" else raiz)  # vendor sempre em core/static/dsgov/vendor
    if args.app_core != "core":
        shutil.move(str(raiz / "core/static/dsgov/vendor"), str(core / "static/dsgov/vendor"))

    a = args.app_core
    print(f"""
== Falta fazer à mão (settings.py / urls.py):

INSTALLED_APPS += ["django.forms", "django_htmx"]           # + "{a}" se ainda não estiver
MIDDLEWARE: após AuthenticationMiddleware, adicionar
    "django_htmx.middleware.HtmxMiddleware",
    "{a}.middleware.HtmxRedirectMiddleware",
TEMPLATES[0]["OPTIONS"]["context_processors"] += ["{a}.context_processors.dsgov"]
FORM_RENDERER = "{a}.forms.renderer.DSGovFormRenderer"
STATICFILES_DIRS deve incluir BASE_DIR / "{a}" / "static"
DSGOV = {{ "ORGAO": "...", "ORGAO_SIGLA": "...", "SISTEMA": "...", "SISTEMA_SUBTITULO": "", "LOGO": "",
          "LINKS_ACESSO_RAPIDO": [], "RODAPE_TEXTO": "...", "ITENS_POR_PAGINA": 20, "OPCOES_POR_PAGINA": (10, 20, 50) }}
LANGUAGE_CODE = "pt-br"; USE_THOUSAND_SEPARATOR = True; DATE_FORMAT = "d/m/Y"

urls.py: as rotas core:inicio, core:login e core:logout são referenciadas pelos partials.
   Se o projeto já tem login próprio, aponte os nomes: path("login/", sua_view, name="login") dentro de um
   include com app_name="core", ou edite dsgov/_header.html e _breadcrumb.html para os nomes existentes.

Depois: pip install django-htmx django-environ (se faltar); mude cada template de página para
{{% extends "base.html" %}} + {{% block conteudo %}}; substitua HTML de formulário por {{{{ form }}}};
listagens herdam de {a}.listagem.ListagemView. Por fim: python3 {SKILL}/scripts/verificar.py {raiz}
""")


if __name__ == "__main__":
    main()
