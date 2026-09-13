#!/usr/bin/env python3
"""Cria um projeto Django novo já no padrão DSGov (skill dsgov).

Uso:
    python3 <skill>/scripts/novo_projeto.py <pasta-destino> --sistema "Controle de Diárias" \
        --orgao "Nome do Órgão" --sigla ORG [--subtitulo "..."] [--yaml sistema.yaml]

Copia assets/projeto (config, core, compose, Dockerfile...), copia os ativos congelados (DSGov 3.7.0,
Font Awesome 5, fontes Rawline/Raleway, HTMX, ECharts) para core/static/dsgov/vendor, gera .env com
SECRET_KEY aleatória, cria as migrações do core e, se --yaml for informado, gera os módulos.
Determinístico: o mesmo comando produz sempre a mesma estrutura.
"""

from __future__ import annotations

import argparse
import re
import secrets
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
MODELO = SKILL / "assets/projeto"
VENDOR = SKILL / "assets/vendor"


def slug(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-zA-Z0-9]+", "_", t).strip("_").lower()


def copiar_vendor(destino: Path):
    v = destino / "core/static/dsgov/vendor"
    v.mkdir(parents=True, exist_ok=True)
    (v / "govbr-ds").mkdir(exist_ok=True)
    for f in ("core.min.css", "core.min.js", "core-tokens.css", "LICENSE"):
        shutil.copy(VENDOR / "govbr-ds/3.7.0" / f, v / "govbr-ds" / f)
    shutil.copytree(VENDOR / "fontawesome/5.15.4", v / "fontawesome", dirs_exist_ok=True)
    shutil.copytree(VENDOR / "fonts", v / "fonts", dirs_exist_ok=True)
    (v / "htmx").mkdir(exist_ok=True)
    shutil.copy(VENDOR / "htmx/2.0.10/htmx.min.js", v / "htmx/htmx.min.js")
    (v / "echarts").mkdir(exist_ok=True)
    for f in ("echarts.min.js", "LICENSE"):
        shutil.copy(VENDOR / "echarts/5.5.0" / f, v / "echarts" / f)
    (v / "VERSOES.txt").write_text(
        "Ativos congelados pela skill dsgov. Não atualize sem atualizar a skill.\n"
        "@govbr-ds/core 3.7.0 · Font Awesome Free 5.15.4 · Rawline (cdngovbr-ds) · Raleway (Google Fonts, variável) ·"
        " htmx 2.0.10 · Apache ECharts 5.5.0\n", encoding="utf-8")


def substituir(destino: Path, mapa: dict[str, str]):
    for arq in destino.rglob("*"):
        if not arq.is_file() or "vendor" in arq.parts or arq.suffix in (".woff2", ".png", ".ico", ".svg", ".jpg"):
            continue
        try:
            texto = arq.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        novo = texto
        for chave, valor in mapa.items():
            novo = novo.replace(chave, valor)
        if novo != texto:
            arq.write_text(novo, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("destino", type=Path)
    ap.add_argument("--sistema", required=True, help='nome do sistema, ex.: "Controle de Diárias"')
    ap.add_argument("--orgao", required=True, help='nome do órgão, ex.: "Conselho Federal de Contabilidade"')
    ap.add_argument("--sigla", required=True, help="sigla do órgão, ex.: ORG")
    ap.add_argument("--subtitulo", default="")
    ap.add_argument("--yaml", type=Path, help="sistema.yaml para gerar os módulos em seguida")
    ap.add_argument("--sem-migracoes", action="store_true")
    args = ap.parse_args()

    destino = args.destino.resolve()
    if destino.exists() and any(destino.iterdir()):
        print(f"pasta não vazia: {destino}", file=sys.stderr)
        sys.exit(2)
    projeto = slug(destino.name)

    print(f"== criando {destino} (projeto {projeto})")
    shutil.copytree(MODELO, destino, dirs_exist_ok=True)
    copiar_vendor(destino)
    substituir(destino, {
        "__PROJETO__": projeto,
        "__SISTEMA__": args.sistema,
        "__ORGAO__": args.orgao,
        "__ORGAO_SIGLA__": args.sigla,
    })
    env = (destino / ".env.example").read_text(encoding="utf-8")
    env = env.replace("troque-por-um-segredo-longo-e-aleatorio", secrets.token_urlsafe(50))
    env = env.replace("DSGOV_SISTEMA_SUBTITULO=", f"DSGOV_SISTEMA_SUBTITULO={args.subtitulo}")
    # dev local sem Docker: SQLite. Para Postgres, descomente a DATABASE_URL.
    env = env.replace("\nDATABASE_URL=postgres", "\n# DATABASE_URL=postgres")
    (destino / ".env").write_text(env, encoding="utf-8")
    if args.subtitulo:
        base = destino / "config/settings/base.py"
        base.write_text(base.read_text(encoding="utf-8").replace('env("DSGOV_SISTEMA_SUBTITULO", default="")',
                        f'env("DSGOV_SISTEMA_SUBTITULO", default="{args.subtitulo}")'), encoding="utf-8")

    if not args.sem_migracoes:
        print("== makemigrations core")
        r = subprocess.run([sys.executable, "manage.py", "makemigrations", "core"], cwd=destino, check=False)
        if r.returncode != 0:
            print(f"AVISO: makemigrations falhou com {sys.executable}; rode com o Python do projeto (venv) ou "
                  "`python manage.py makemigrations core` depois de instalar requirements-dev.txt.")
    if args.yaml:
        subprocess.run([sys.executable, str(SKILL / "scripts/gerar_app.py"), str(destino), str(args.yaml.resolve())] +
                       (["--sem-migracoes"] if args.sem_migracoes else []), check=False)

    print(f"""
== pronto: {destino}

Próximos passos (dev local, SQLite):
    cd {destino}
    python -m venv .venv && . .venv/bin/activate
    pip install -r requirements-dev.txt
    python manage.py migrate
    python manage.py createsuperuser
    python manage.py runserver

Docker + PostgreSQL: edite .env (DATABASE_URL, POSTGRES_*), `docker volume create {projeto}_pgdata`, `docker compose up -d --build`.
Antes de entregar qualquer tela: python3 {SKILL / 'scripts/verificar.py'} {destino}
""")


if __name__ == "__main__":
    main()
