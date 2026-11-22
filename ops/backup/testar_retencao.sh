#!/bin/sh
# Ensaio isolado da retenção — prova por execução real (não só leitura de
# código) que manter_ultimos() realmente poda o excedente quando o limiar é
# ultrapassado (Fase 9). Usa a MESMA função de
# ops/backup/retencao.sh, sem duplicar lógica, contra um prefixo descartável
# do mesmo bucket — nunca contra daily/ ou weekly/ reais. Agnóstica de
# formato de arquivo (arquivos sintéticos vazios); segue valendo sem
# alteração desde a troca de pg_dump/.dump para sqlite3/.sqlite3.gz (Fase 31).
set -eu

. "$(dirname "$0")/retencao.sh"

PREFIXO_TESTE="_retention_test"

# Trava contra apagar dados reais por engano: nenhum argumento deste ensaio
# pode ser literalmente "daily" ou "weekly".
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
    # synthetic-9 fica com a data mais recente (1 dia atrás);
    # synthetic-1 com a mais antiga (9 dias atrás). `touch -d "-N days"` não
    # é entendido pelo busybox do Alpine (só GNU coreutils) — usa-se
    # aritmética de epoch (`@segundos`), que o parser de data do busybox
    # aceita tanto em `date -d` quanto em `touch -d`.
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
