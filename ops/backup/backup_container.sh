#!/bin/sh
# Versão CONTAINER do backup (serviço `backup` do compose, copiado para /backup.sh na imagem).
# O backup do ambiente atual roda no HOST por cron: ops/backup/backup.sh.
# Backup diário sqlite3 .backup + gzip -> Cloudflare R2, retenção 7 diários /
# 4 semanais (formato trocado de pg_dump para SQLite na
# Fase 31). Toda credencial vem de variável de ambiente
# (RCLONE_CONFIG_R2_*, R2_BUCKET, SQLITE_PATH) — nada de valor de host no
# código (do plano).
set -eu

. "$(dirname "$0")/retencao.sh"

DATA=$(date +%Y-%m-%d_%H%M%S)
DIA_SEMANA=$(date +%u)  # 1=segunda .. 7=domingo
COPIA="/tmp/pca_${DATA}.sqlite3"
ARQUIVO="${COPIA}.gz"

echo "[backup] copiando ${SQLITE_PATH} para ${COPIA} (.backup, consistente mesmo com WAL ativo)"
sqlite3 "${SQLITE_PATH}" ".backup '${COPIA}'"

echo "[backup] compactando ${COPIA}"
gzip "${COPIA}"

echo "[backup] enviando para r2:${R2_BUCKET}/daily/"
rclone copy "${ARQUIVO}" "r2:${R2_BUCKET}/daily/"

if [ "${DIA_SEMANA}" = "7" ]; then
    echo "[backup] domingo — enviando também para r2:${R2_BUCKET}/weekly/"
    rclone copy "${ARQUIVO}" "r2:${R2_BUCKET}/weekly/"
fi

manter_ultimos "daily" 7
manter_ultimos "weekly" 4

rm -f "${ARQUIVO}"
echo "[backup] concluído"
