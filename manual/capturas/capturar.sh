#!/usr/bin/env bash
# Regera os prints do manual do usuário (manual/docs/img/**) a partir de uma CÓPIA mascarada do
# banco, servida por uma instância DESCARTÁVEL da casca DSGov (a oficial, PCA_DESIGN=dsgov). Rodar da raiz do repositório:
#
#   bash manual/capturas/capturar.sh [--cenas a01-entrar,a03-inicio] [--manter]
#   bash manual/capturas/capturar.sh --derrubar
#
#   --cenas      só as cenas listadas (ids separados por vírgula); sem ela, todas.
#   --manter     não limpa ao final: a instância fica no ar em 127.0.0.1:<porta> e os textos e
#                menus capturados ficam no diretório temporário, para conferir.
#   --derrubar   só remove o que um --manter anterior deixou e sai.
#
# Variáveis: MANUAL_TMP (diretório temporário, fora do repositório), MANUAL_PORTA (padrão: a
# primeira livre de 12090 a 12099), MANUAL_NOMES_EXTRAS (padrão
# ~/.config/pca-manual/nomes-extras.txt — um nome de pessoa por linha, fora do repositório).
#
# Nunca toca o banco de verdade além de LER uma cópia (sqlite3 backup em modo leitura); nunca usa o
# volume de dados do compose na instância descartável; nunca docker compose -f/pull/rmi/prune/tag/build.
set -euo pipefail

NOME_CONTAINER=pca-manual-web
IMAGEM_WEB=toniaum/pca-cfc:dev
IMAGEM_ROBO=toniaum/pca-cfc-robo:dev
ESTADO="${TMPDIR:-/tmp}/pca-manual.ultimo"
MARCA=.pca-manual-tmp

CENAS=""
MANTER=0
DERRUBAR=0
while [ $# -gt 0 ]; do
  case "$1" in
    --cenas) CENAS="${2:?--cenas precisa de uma lista}"; shift 2 ;;
    --cenas=*) CENAS="${1#*=}"; shift ;;
    --manter) MANTER=1; shift ;;
    --derrubar) DERRUBAR=1; shift ;;
    -h|--help) sed -n '2,19p' "$0"; exit 0 ;;
    *) echo "opção desconhecida: $1" >&2; exit 2 ;;
  esac
done

if [ ! -f manage.py ] || [ ! -d manual/capturas ]; then
  echo "Rode da raiz do repositório pca-cfc (onde estão manage.py e manual/capturas)." >&2
  exit 2
fi
RAIZ="$(pwd -P)"

limpar() {
  local tmp="${1:-}"
  if docker rm -fv "$NOME_CONTAINER" >/dev/null 2>&1; then
    echo "removido: container $NOME_CONTAINER (e os volumes anônimos dele)"
  fi
  if [ -n "$tmp" ] && [ -d "$tmp" ]; then
    if [ -f "$tmp/$MARCA" ]; then
      # A cópia do banco (e o -wal/-shm) e a saída foram gravadas pelo root dos containers.
      docker run --rm --pull never --entrypoint sh -v "$tmp:/x" "$IMAGEM_WEB" \
        -c 'rm -rf /x/data /x/saida /x/manual.env /x/vazio.env'
      rm -rf "$tmp"
      echo "removido: $tmp (cópia do banco, ambiente, textos e prints temporários)"
    else
      echo "AVISO: $tmp não tem a marca $MARCA; não apaguei nada nele." >&2
    fi
  fi
  rm -f "$ESTADO"
}

if [ "$DERRUBAR" = 1 ]; then
  TMP_ANTERIOR=""
  [ -f "$ESTADO" ] && TMP_ANTERIOR="$(cat "$ESTADO")"
  limpar "$TMP_ANTERIOR"
  echo "Nada mais da instância descartável do manual ficou para trás."
  exit 0
fi

if [ -n "$(docker ps -aq --filter "name=^${NOME_CONTAINER}$")" ]; then
  echo "Já existe um container $NOME_CONTAINER (de um --manter?). Rode: bash $0 --derrubar" >&2
  exit 2
fi

# --- diretório temporário (fora do repositório, nosso pela marca) --------------------------
if [ -z "${MANUAL_TMP:-}" ]; then
  MANUAL_TMP="$(mktemp -d "${TMPDIR:-/tmp}/pca-manual.XXXXXX")"
else
  mkdir -p "$MANUAL_TMP"
  MANUAL_TMP="$(cd "$MANUAL_TMP" && pwd -P)"
fi
case "$MANUAL_TMP" in
  /*) ;;
  *) echo "MANUAL_TMP precisa ser absoluto." >&2; exit 2 ;;
esac
if [ "$MANUAL_TMP" = "/" ] || [ "$MANUAL_TMP" = "$HOME" ] || [ "$MANUAL_TMP" = "$(cd "$HOME" && pwd -P)" ]; then
  echo "MANUAL_TMP não pode ser / nem a pasta pessoal." >&2; exit 2
fi
case "$MANUAL_TMP/" in
  "$RAIZ"/*) echo "MANUAL_TMP não pode ficar dentro do repositório." >&2; exit 2 ;;
esac
if [ -n "$(ls -A "$MANUAL_TMP")" ] && [ ! -f "$MANUAL_TMP/$MARCA" ]; then
  echo "MANUAL_TMP ($MANUAL_TMP) não está vazio nem é nosso." >&2; exit 2
fi
touch "$MANUAL_TMP/$MARCA"
echo "$MANUAL_TMP" > "$ESTADO"

if [ "$MANTER" = 1 ]; then
  trap 'echo; echo "--manter: nada foi removido. Para limpar: bash manual/capturas/capturar.sh --derrubar"' EXIT
else
  trap 'limpar "$MANUAL_TMP"' EXIT
fi

# --- porta livre em 127.0.0.1 ----------------------------------------------------------------
if [ -z "${MANUAL_PORTA:-}" ]; then
  for p in $(seq 12090 12099); do
    if [ -z "$(ss -ltnH "sport = :$p")" ]; then MANUAL_PORTA="$p"; break; fi
  done
fi
[ -n "${MANUAL_PORTA:-}" ] || { echo "Nenhuma porta livre de 12090 a 12099." >&2; exit 1; }

# --- nomes extras (fora do repositório) -----------------------------------------------------
MANUAL_NOMES_EXTRAS="${MANUAL_NOMES_EXTRAS:-$HOME/.config/pca-manual/nomes-extras.txt}"
EXTRAS=()
if [ -f "$MANUAL_NOMES_EXTRAS" ]; then
  EXTRAS=(-v "$MANUAL_NOMES_EXTRAS:/manual/extras.txt:ro")
  echo "nomes extras: $(grep -c . "$MANUAL_NOMES_EXTRAS" || true) linha(s)"
fi

# --- cópia do banco do serviço web (só leitura na origem) ----------------------------------
mkdir -p "$MANUAL_TMP/data" "$MANUAL_TMP/saida"
echo "copiando o banco do serviço web (sqlite3 backup, origem em modo leitura)..."
docker compose exec -T web python - <<'PY'
import os
import sqlite3

import django

django.setup()
from django.conf import settings

nome = settings.DATABASES["default"]["NAME"]
destino = "/tmp/pca-manual-copia.sqlite3"
if os.path.exists(destino):
    os.remove(destino)
origem = sqlite3.connect(f"file:{nome}?mode=ro", uri=True)
copia = sqlite3.connect(destino)
with copia:
    origem.backup(copia)
copia.close()
origem.close()
print("cópia feita:", os.path.getsize(destino), "bytes")
PY
docker compose cp web:/tmp/pca-manual-copia.sqlite3 "$MANUAL_TMP/data/db.sqlite3" >/dev/null
docker compose exec -T web rm -f /tmp/pca-manual-copia.sqlite3
INTEGRIDADE="$(sqlite3 "$MANUAL_TMP/data/db.sqlite3" 'PRAGMA integrity_check')"
[ "$INTEGRIDADE" = ok ] || { echo "cópia corrompida: $INTEGRIDADE" >&2; exit 1; }
touch "$MANUAL_TMP/data/.copia-descartavel-manual"

# --- ambiente próprio (NUNCA o .env do projeto) ---------------------------------------------
: > "$MANUAL_TMP/vazio.env"
umask_antigo="$(umask)"; umask 077
cat > "$MANUAL_TMP/manual.env" <<EOF
DJANGO_SETTINGS_MODULE=config.settings.dev
DEBUG=false
SECRET_KEY=$(python3 -c 'import secrets;print(secrets.token_urlsafe(50))')
DATABASE_URL=sqlite:////app/data/db.sqlite3
PCA_DESIGN=dsgov
SECURE_SSL_REDIRECT=false
IA_API_KEY=
IA_API_KEY_EMBED=
IA_ROBO_ATIVO=false
SEI_USUARIO=descartavel
SEI_SENHA=descartavel
TZ=America/Sao_Paulo
GUNICORN_WORKERS=2
PCA_MANUAL_DESCARTAVEL=1
EOF
umask "$umask_antigo"
chmod 600 "$MANUAL_TMP/manual.env"

# O base.py lê /app/.env; o arquivo vazio montado por cima garante que nenhuma credencial real
# (SEI, R2, IA) chegue à instância descartável.
MONTAGENS=(
  -v "$RAIZ:/app:ro"
  -v "$MANUAL_TMP/vazio.env:/app/.env:ro"
)

# --- instância descartável -------------------------------------------------------------------
echo "subindo $NOME_CONTAINER em 127.0.0.1:$MANUAL_PORTA (casca DSGov, cópia mascarada)..."
docker run -d --pull never --name "$NOME_CONTAINER" \
  -p "127.0.0.1:$MANUAL_PORTA:8000" \
  --env-file "$MANUAL_TMP/manual.env" \
  "${MONTAGENS[@]}" \
  -v /app/staticfiles -v /app/ops/relatorios \
  -v "$MANUAL_TMP/data:/app/data" \
  "${EXTRAS[@]}" \
  --entrypoint /bin/sh "$IMAGEM_WEB" \
  -c 'python manage.py collectstatic --noinput --clear >/dev/null && exec /app/entrypoint.sh' >/dev/null

pronto=0
for _ in $(seq 1 90); do
  if curl -fsS "http://127.0.0.1:$MANUAL_PORTA/healthz" >/dev/null 2>&1; then pronto=1; break; fi
  sleep 2
done
if [ "$pronto" != 1 ]; then
  docker logs --tail 50 "$NOME_CONTAINER" >&2 || true
  echo "a instância descartável não respondeu em 180 s" >&2
  exit 1
fi

# --- máscara, personas e solicitações de exemplo (só na cópia) ------------------------------
docker exec -w /app "$NOME_CONTAINER" python manual/capturas/preparar.py

# --- prints ----------------------------------------------------------------------------------
ARGS=()
[ -n "$CENAS" ] && ARGS=(--cenas "$CENAS")
docker run --rm --pull never --network "container:$NOME_CONTAINER" \
  --env-file "$MANUAL_TMP/manual.env" \
  -e MANUAL_BASE=http://127.0.0.1:8000 -e MANUAL_DONO="$(id -u):$(id -g)" \
  "${MONTAGENS[@]}" \
  -v "$MANUAL_TMP/data:/app/data:ro" \
  -v "$MANUAL_TMP/saida:/saida" \
  "${EXTRAS[@]}" \
  -w /app --entrypoint python "$IMAGEM_ROBO" manual/capturas/capturar.py "${ARGS[@]}"

# Só chega aqui com saída 0 (conferência de vazamento passou).
for parte in areas diretoria; do
  if compgen -G "$MANUAL_TMP/saida/img/$parte/*.png" >/dev/null; then
    mkdir -p "manual/docs/img/$parte"
    cp "$MANUAL_TMP/saida/img/$parte/"*.png "manual/docs/img/$parte/"
    echo "copiados: $(ls "$MANUAL_TMP/saida/img/$parte/"*.png | wc -l) print(s) para manual/docs/img/$parte/"
  fi
done

if [ "$MANTER" = 1 ]; then
  echo "instância: http://127.0.0.1:$MANUAL_PORTA/  ·  textos e menus: $MANUAL_TMP/saida/textos/"
fi
