#!/bin/sh
# Gera o dumpdata JSON do Postgres de dev AINDA vivo — a receita de
# migração dos dados existentes para SQLite. Roda dentro do container web
# (que ainda aponta para o Postgres neste momento), copia o JSON para fora
# da árvore versionada e calcula checksum, no mesmo diretório onde já ficam
# os dumps .dump de segurança (/home/ToNiauM/ativos/docker/pca-cfc-dumps/).
#
# Precisa ser executado com o serviço `db` do compose.yml AINDA de pé — antes
# de qualquer edição de infra desta fase (ver /estratégia
# de ordem obrigatória).
set -eu
# Revisão da Fase 31: qualquer arquivo criado por este script
# (dump/checksum) já nasce com permissão restrita (0600), sem depender da
# janela entre a criação e o `chmod 600` explícito mais abaixo.
umask 077

DESTINO_DIR="/home/ToNiauM/ativos/docker/pca-cfc-dumps"
CARIMBO=$(date +%Y%m%d_%H%M%S)
ARQUIVO_CONTAINER="/app/ops/relatorios/pca-dumpdata.json"
ARQUIVO_FINAL="${DESTINO_DIR}/pca-dumpdata-${CARIMBO}.json"

# Revisão da Fase 31 (MD-03): `trap ... EXIT` garante a limpeza do arquivo
# temporário dentro do container em QUALQUER saída (sucesso, erro do
# `docker compose cp` ou de qualquer comando seguinte) — antes, a remoção
# era o último comando do script, e `set -eu` abortava antes dela se algo
# no meio falhasse, deixando um dump com e-mails de usuários residente no
# container.
cleanup() {
    docker compose exec -T web rm -f "${ARQUIVO_CONTAINER}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "[dump] gerando dumpdata dentro do container web (Postgres ainda ativo)"
docker compose exec -T web python manage.py dumpdata \
    --natural-foreign --natural-primary \
    --exclude contenttypes --exclude auth.permission \
    --exclude sessions --exclude admin.logentry --exclude axes \
    --indent 0 -o "${ARQUIVO_CONTAINER}"

echo "[dump] copiando para ${ARQUIVO_FINAL}"
docker compose cp "web:${ARQUIVO_CONTAINER}" "${ARQUIVO_FINAL}"

echo "[dump] permissões restritas (dados pessoais: e-mail de usuários)"
chmod 600 "${ARQUIVO_FINAL}"

echo "[dump] gerando checksum"
( cd "${DESTINO_DIR}" && sha256sum "$(basename "${ARQUIVO_FINAL}")" > "$(basename "${ARQUIVO_FINAL}").sha256" )

# A remoção de dentro do container acontece pelo `trap cleanup EXIT` acima,
# em qualquer saída (sucesso ou erro) — não só no caminho feliz.
echo "[dump] concluído: ${ARQUIVO_FINAL}"
