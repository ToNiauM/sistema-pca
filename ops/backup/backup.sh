#!/usr/bin/env bash
# Backup diário do SQLite do PCA a partir do HOST (cron), para o Cloudflare R2.
#
# - cópia consistente via API .backup do sqlite3 (dentro do container web —
#   funciona com WAL ativo e com o sistema escrevendo)
# - gzip + verificação (gzip -t, PRAGMA integrity_check) ANTES do upload
# - <bucket>/sqlite/daily/ todo dia; <bucket>/sqlite/weekly/ aos domingos (remoto pcar2, só por ambiente)
# - retenção 7 diários / 4 semanais só no prefixo sqlite/ (retencao.sh)
# - cópia local dos últimos 7 em /home/ToNiauM/ativos/docker/pca-cfc-dumps/sqlite/
#
# Credenciais: só no .env do projeto (R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY,
# R2_ENDPOINT, R2_BUCKET). Nada é ecoado.
set -euo pipefail
umask 077

PROJETO="${PROJETO:-/home/ToNiauM/ativos/docker/pca-cfc}"
DESTINO_LOCAL="${DESTINO_LOCAL:-/home/ToNiauM/ativos/docker/pca-cfc-dumps/sqlite}"
MANTER_LOCAL="${MANTER_LOCAL:-7}"
SQLITE_NO_CONTAINER="${SQLITE_NO_CONTAINER:-/app/data/db.sqlite3}"
PREFIXO="${PREFIXO:-sqlite}"

log() { printf '%s [backup-sqlite] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
falha() { log "ERRO: $*"; exit 1; }

# uma execução por vez
exec 9>"/tmp/pca-backup.lock"
flock -n 9 || falha "outra execução em andamento"

cd "$PROJETO"
[ -f .env ] || falha ".env não encontrado em $PROJETO"

# lê só as R2_* do .env, sem executar o arquivo
while IFS='=' read -r chave valor; do
    case "$chave" in
        R2_ACCESS_KEY_ID|R2_SECRET_ACCESS_KEY|R2_ENDPOINT|R2_BUCKET) export "$chave=$valor" ;;
    esac
done < <(grep -E '^R2_[A-Z_]+=' .env)
for v in R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY R2_ENDPOINT R2_BUCKET; do
    [ -n "${!v:-}" ] || falha "$v vazio no .env"
done
case "$R2_ENDPOINT" in *invalid*) falha "R2_ENDPOINT é placeholder" ;; esac

# remoto "pcar2" definido SÓ por ambiente — nome exclusivo para não colidir com o
# remoto "r2" do ~/.config/rclone/rclone.conf do operador (outro bucket)
REMOTO="pcar2"
export RCLONE_CONFIG_PCAR2_TYPE=s3
export RCLONE_CONFIG_PCAR2_PROVIDER=Cloudflare
export RCLONE_CONFIG_PCAR2_NO_CHECK_BUCKET=true
export RCLONE_CONFIG_PCAR2_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID"
export RCLONE_CONFIG_PCAR2_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY"
export RCLONE_CONFIG_PCAR2_ENDPOINT="$R2_ENDPOINT"

# retenção compartilhada com o backup.sh do container
# shellcheck source=retencao.sh
. "$PROJETO/ops/backup/retencao.sh"   # usa $REMOTO (default r2 no container)

mkdir -p "$DESTINO_LOCAL"
DATA=$(date +%Y-%m-%d_%H%M%S)
DIA_SEMANA=$(date +%u)
NOME="pca_${DATA}.sqlite3"
COPIA="$DESTINO_LOCAL/$NOME"
ARQUIVO="$COPIA.gz"
TMP_CONTAINER="/tmp/backup_${DATA}.sqlite3"

limpar() {
    docker compose exec -T web rm -f "$TMP_CONTAINER" >/dev/null 2>&1 || true
    rm -f "$COPIA"
}
trap limpar EXIT

log "cópia consistente de $SQLITE_NO_CONTAINER (sqlite3 .backup dentro do container)"
docker compose exec -T web python - "$SQLITE_NO_CONTAINER" "$TMP_CONTAINER" <<'PY'
import sqlite3, sys
origem, destino = sys.argv[1], sys.argv[2]
with sqlite3.connect(origem) as s, sqlite3.connect(destino) as d:
    s.backup(d)
PY
# stream via exec/stdout — `docker cp` falha com o bind :ro do dev
docker compose exec -T web cat "$TMP_CONTAINER" > "$COPIA"

log "verificando integridade da cópia"
INTEGRIDADE=$(python3 - "$COPIA" <<'PY'
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
print(c.execute("PRAGMA integrity_check").fetchone()[0])
print(c.execute("select count(*) from pca_processo").fetchone()[0])
PY
)
STATUS=$(printf '%s\n' "$INTEGRIDADE" | sed -n 1p)
PROCESSOS=$(printf '%s\n' "$INTEGRIDADE" | sed -n 2p)
[ "$STATUS" = "ok" ] || falha "integrity_check devolveu: $STATUS"
[ "${PROCESSOS:-0}" -gt 0 ] || falha "cópia sem processos ($PROCESSOS) — abortando"

gzip -9 "$COPIA"
gzip -t "$ARQUIVO" || falha "gzip corrompido"
sha256sum "$ARQUIVO" | awk '{print $1}' > "$ARQUIVO.sha256"
TAMANHO=$(du -h "$ARQUIVO" | cut -f1)
log "cópia OK: $NOME.gz ($TAMANHO, $PROCESSOS processos, integrity_check ok)"

# --s3-no-head: o rclone 1.60 do Ubuntu faz um HEAD pós-upload com cabeçalho
# de checksum que o R2 responde 501; o PUT em si sempre completa. A conferência
# de integridade é feita abaixo por MD5 (ETag do R2 == md5 local).
RCLONE_OPTS=(--retries 5 --low-level-retries 10 --s3-no-head)
MD5_LOCAL=$(md5sum "$ARQUIVO" | awk '{print $1}')

enviar_e_conferir() {
    destino="$1"
    log "enviando para ${REMOTO}:${R2_BUCKET}/${destino}/"
    rclone copy "${RCLONE_OPTS[@]}" "$ARQUIVO" "${REMOTO}:${R2_BUCKET}/${destino}/"
    md5_remoto=$(rclone md5sum "${REMOTO}:${R2_BUCKET}/${destino}/$(basename "$ARQUIVO")" | awk '{print $1}')
    [ "$md5_remoto" = "$MD5_LOCAL" ] || falha "MD5 divergente em ${destino}/ (remoto=$md5_remoto local=$MD5_LOCAL)"
    log "conferido: MD5 remoto == local em ${destino}/"
}

enviar_e_conferir "${PREFIXO}/daily"
if [ "$DIA_SEMANA" = "7" ]; then
    log "domingo — cópia semanal"
    enviar_e_conferir "${PREFIXO}/weekly"
fi

# retenção SÓ no prefixo sqlite/ — daily/ e weekly/ da raiz (dumps Postgres) ficam intactos
manter_ultimos "${PREFIXO}/daily" 7
manter_ultimos "${PREFIXO}/weekly" 4

# cópia local: mantém os N mais recentes
ls -1t "$DESTINO_LOCAL"/pca_*.sqlite3.gz 2>/dev/null | tail -n "+$((MANTER_LOCAL + 1))" | while read -r antigo; do
    rm -f "$antigo" "$antigo.sha256"
done

log "concluído"
