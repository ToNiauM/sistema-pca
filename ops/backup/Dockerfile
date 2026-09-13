# mesma versão do postgres do serviço db, evita divergência de versão no dump
FROM postgres:17-alpine

RUN apk add --no-cache curl unzip dcron tzdata

# versão do rclone fixada por checksum; ARG sem prefixo RCLONE_ (rclone lê
# qualquer env RCLONE_<FLAG> como config, RCLONE_VERSION quebraria "rclone version")
ARG PIN_RCLONE_VERSION=v1.68.2
RUN set -eu; \
    cd /tmp; \
    curl -fsSO "https://downloads.rclone.org/${PIN_RCLONE_VERSION}/rclone-${PIN_RCLONE_VERSION}-linux-amd64.zip"; \
    curl -fsSO "https://downloads.rclone.org/${PIN_RCLONE_VERSION}/SHA256SUMS"; \
    grep " rclone-${PIN_RCLONE_VERSION}-linux-amd64.zip\$" SHA256SUMS | sha256sum -c -; \
    unzip -q "rclone-${PIN_RCLONE_VERSION}-linux-amd64.zip"; \
    cp "rclone-${PIN_RCLONE_VERSION}-linux-amd64/rclone" /usr/bin/rclone; \
    chmod 755 /usr/bin/rclone; \
    chown root:root /usr/bin/rclone; \
    rm -rf /tmp/rclone-* /tmp/SHA256SUMS; \
    rclone version

COPY retencao.sh /retencao.sh
COPY testar_retencao.sh /testar_retencao.sh
COPY backup.sh /backup.sh
RUN chmod +x /backup.sh /retencao.sh /testar_retencao.sh

ENV TZ=America/Sao_Paulo

# agenda diária às 03:00 America/Sao_Paulo; saída vai para o stdout do container
RUN echo "0 3 * * * /backup.sh >> /proc/1/fd/1 2>> /proc/1/fd/2" > /etc/crontabs/root

CMD ["crond", "-f", "-d", "8"]
