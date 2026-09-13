#!/bin/sh
# ensaio isolado: prova por execução real que manter_ultimos() poda o excedente
# usa a mesma função de retencao.sh, contra um prefixo descartável do bucket
set -eu

. "$(dirname "$0")/retencao.sh"

PREFIXO_TESTE="_retention_test"

# trava contra apagar dados reais: nenhum argumento pode ser "daily" ou "weekly"
for arg in "$@"; do
    case "${arg}" in
        daily|weekly)
            echo "[testar_retencao] recusando executar contra prefixo real '${arg}'" >&2
            exit 1
            ;;
    esac
done

DIR_TMP=$(mktemp -d)

limpar() {
    echo "[testar_retencao] limpando r2:${R2_BUCKET}/${PREFIXO_TESTE}/"
    rclone purge "r2:${R2_BUCKET}/${PREFIXO_TESTE}/" >/dev/null 2>&1 || true
    rm -rf "${DIR_TMP}"
}
trap limpar EXIT

echo "[testar_retencao] gerando 9 arquivos sintéticos vazios"
agora=$(date +%s)
i=1
while [ "${i}" -le 9 ]; do
    arquivo="${DIR_TMP}/synthetic-${i}.dump"
    : > "${arquivo}"
    # aritmética de epoch porque o busybox do Alpine não entende "touch -d -N days"
    dias_atras=$((10 - i))
    alvo=$((agora - dias_atras * 86400))
    touch -d "@${alvo}" "${arquivo}"
    i=$((i + 1))
done

echo "[testar_retencao] enviando os 9 arquivos para r2:${R2_BUCKET}/${PREFIXO_TESTE}/"
rclone copy "${DIR_TMP}" "r2:${R2_BUCKET}/${PREFIXO_TESTE}/"

manter_ultimos "${PREFIXO_TESTE}" 7

restantes=$(rclone lsf "r2:${R2_BUCKET}/${PREFIXO_TESTE}/" 2>/dev/null | sort)
total_restante=$(printf '%s\n' "${restantes}" | grep -c . || true)

echo "[testar_retencao] arquivos retidos:"
printf '%s\n' "${restantes}"
echo "restantes: ${total_restante}"
