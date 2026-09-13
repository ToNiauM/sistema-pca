# mantém só os N arquivos mais recentes num destino remoto (ordenado pela data real no R2)
manter_ultimos() {
    destino="$1"
    manter="$2"
    listagem=$(rclone lsf "r2:${R2_BUCKET}/${destino}/" --format tp --separator ";" 2>/dev/null | sort -r)
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
            rclone delete "r2:${R2_BUCKET}/${destino}/${caminho}"
        done
}
