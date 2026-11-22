#!/bin/sh
# Aplica a receita dumpdata->loaddata contra o banco SQLite do
# serviço `web` já em pé. Recebe o caminho (no HOST) de um dump `.json`
# gerado por `gerar_dump_postgres.sh`, copia para dentro do container,
# carrega e REMOVE a cópia de dentro do container ao final — nunca deixa um
# arquivo com e-mails de usuários residente na imagem/volume.
#
# Não reinicia `web`: a aplicação lê o banco a cada request, não precisa de
# restart depois de um `loaddata`.
#
# Uso: ops/migracao_sqlite/restaurar_sqlite.sh <caminho-do-dump.json> [--force]
#
# Revisão da Fase 31: recusa carregar num banco que já tem
# dados (a receita pressupõe "no SQLite vazio já migrado") a menos
# que `--force` seja passado, e sempre tira uma cópia de segurança do
# db.sqlite3 atual antes do loaddata. `umask 077` — qualquer
# arquivo criado por este script já nasce com permissão restrita.
set -eu
umask 077

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
    echo "uso: $0 <caminho-do-dump.json> [--force]" >&2
    exit 1
fi

DUMP_HOST="$1"
FORCA="${2:-}"
if [ -n "${FORCA}" ] && [ "${FORCA}" != "--force" ]; then
    echo "uso: $0 <caminho-do-dump.json> [--force]" >&2
    exit 1
fi

if [ ! -f "${DUMP_HOST}" ]; then
    echo "[restaurar_sqlite] arquivo não encontrado: ${DUMP_HOST}" >&2
    exit 1
fi

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "${REPO_DIR}"

DESTINO_DIR="/home/ToNiauM/ativos/docker/pca-cfc-dumps"
CARIMBO=$(date +%Y%m%d_%H%M%S)
ARQUIVO_CONTAINER="/app/ops/relatorios/$(basename "${DUMP_HOST}")"
BACKUP_CONTAINER="/app/ops/relatorios/pre-restore-${CARIMBO}.sqlite3"
BACKUP_HOST="${DESTINO_DIR}/pre-restore-${CARIMBO}.sqlite3"

# Revisão da Fase 31 (MD-03): `trap ... EXIT` garante a limpeza dos
# arquivos temporários dentro do container em QUALQUER saída (sucesso,
# `loaddata` com conflito de natural key, ou qualquer erro no meio) — antes,
# a remoção era o último comando do script, e `set -eu` abortava antes dela
# se algo no meio falhasse, deixando dado pessoal residente no container.
#
cleanup() {
    docker compose exec -T web rm -f "${ARQUIVO_CONTAINER}" "${BACKUP_CONTAINER}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "[restaurar_sqlite] verificando se o banco de destino já migrado está vazio"
# --no-imports -v 0: sem isto, o `shell` do Django 5.2 tenta importar todo
# INSTALLED_APPS no namespace e imprime um resumo ("N objects imported
# automatically...") ANTES do print do count — ruído que contaminaria
# ${CONTAGEM} e quebraria a comparação abaixo.
CONTAGEM=$(docker compose exec -T web python manage.py shell --no-imports -v 0 -c \
    "from apps.pca.models import Processo; print(Processo.objects.count())" | tr -d '\r')
if [ "${CONTAGEM}" != "0" ] && [ "${FORCA}" != "--force" ]; then
    echo "[restaurar_sqlite] banco de destino já tem ${CONTAGEM} Processo(s) — aborta (use --force para sobrescrever mesmo assim)." >&2
    exit 1
fi

echo "[restaurar_sqlite] cópia de segurança do db.sqlite3 atual antes do loaddata"
# `sqlite3` CLI não está na imagem `web` (só na do serviço `backup`) — usa a
# mesma API de backup (segura com WAL ativo, faz checkpoint internamente)
# via o módulo `sqlite3` da stdlib do Python, já presente na imagem.
docker compose exec -T web python -c "
import sqlite3
origem = sqlite3.connect('/app/data/db.sqlite3')
destino = sqlite3.connect('${BACKUP_CONTAINER}')
origem.backup(destino)
destino.close()
origem.close()
"
docker compose cp "web:${BACKUP_CONTAINER}" "${BACKUP_HOST}"
chmod 600 "${BACKUP_HOST}"
echo "[restaurar_sqlite] cópia de segurança pré-restore em ${BACKUP_HOST}"

echo "[restaurar_sqlite] copiando ${DUMP_HOST} para dentro do container web"
# `docker compose cp` foi tentado primeiro e falhou de forma intermitente com
# "mounted volume is marked read-only" contra este destino — /app/ops/
# relatorios é um volume anônimo próprio, mas fica ANINHADO dentro do bind
# ":ro" de /app (compose.override.yml de dev); a resolução de mount do `cp`
# do Docker Engine não conseguiu de forma confiável a esse volume mais
# interno (reproduzido: funcionou uma vez, falhou depois de um simples
# `stop`/`up -d` do mesmo serviço, sem nenhuma mudança de configuração).
# `exec -T ... sh -c "cat > arquivo"` grava pelo próprio processo do
# container (mesma chamada que qualquer escrita da aplicação faz), sem
# passar pela API de cópia de arquivo do Engine — não reproduz o problema.
docker compose exec -T web sh -c "cat > '${ARQUIVO_CONTAINER}'" < "${DUMP_HOST}"

echo "[restaurar_sqlite] loaddata dentro do container (SQLite em /app/data/db.sqlite3)"
docker compose exec -T web python manage.py loaddata "${ARQUIVO_CONTAINER}"

echo "[restaurar_sqlite] concluído — confira as contagens por modelo antes de seguir"
echo "[restaurar_sqlite] em caso de problema, a cópia pré-restore está em ${BACKUP_HOST}"
