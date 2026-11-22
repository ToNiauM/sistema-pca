# Função de retenção — extraída de backup_container.sh para ser testável isoladamente
# (Fase 9). Este arquivo só DEFINE a função; nenhum código
# de nível superior é executado ao ser carregado via `.` (source). Chamado por
# backup_container.sh (container, "daily"/"weekly"), backup.sh (host, "sqlite/daily"/"sqlite/weekly") e por testar_retencao.sh (ensaio
# isolado, prefixo descartável).
#
# Mantém somente os N arquivos mais recentes num destino remoto. Usa
# `--format tp` (modtime;path, separados por ";") para ordenar pela data
# real do objeto no R2 — não pelo nome do arquivo — e `sort -r` traz os mais
# recentes primeiro; tudo depois da linha N é excedente e é apagado.
manter_ultimos() {
    destino="$1"
    manter="$2"
    remoto="${REMOTO:-r2}"
    listagem=$(rclone lsf "${remoto}:${R2_BUCKET}/${destino}/" --format tp --separator ";" 2>/dev/null | sort -r)
    total=$(printf '%s\n' "${listagem}" | grep -c . || true)
    if [ "${total}" -le "${manter}" ]; then
        echo "[backup] ${destino}: ${total} arquivo(s), dentro da retenção de ${manter}"
        return 0
    fi
    echo "[backup] ${destino}: ${total} arquivo(s), mantendo os ${manter} mais recentes"
    printf '%s\n' "${listagem}" | tail -n "+$((manter + 1))" | \
        while IFS=';' read -r _modtime caminho; do
            [ -z "${caminho}" ] && continue
            echo "[backup] removendo ${destino}/${caminho}"
            rclone delete "${remoto}:${R2_BUCKET}/${destino}/${caminho}"
        done
}
