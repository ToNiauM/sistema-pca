#!/bin/sh
# backup diário pg_dump -> Cloudflare R2, retenção 7 diários / 4 semanais
# credenciais só por variável de ambiente (RCLONE_CONFIG_R2_*, R2_BUCKET, DB_*)
set -eu

. "$(dirname "$0")/retencao.sh"

DATA=$(date +%Y-%m-%d_%H%M%S)
DIA_SEMANA=$(date +%u)  # 1=segunda .. 7=domingo
ARQUIVO="/tmp/pca_${DATA}.dump"

echo "[backup] iniciando dump de ${DB_NAME}@${DB_HOST} em ${ARQUIVO}"
pg_dump --format=custom --host="${DB_HOST}" --username="${DB_USER}" "${DB_NAME}" > "${ARQUIVO}"

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
