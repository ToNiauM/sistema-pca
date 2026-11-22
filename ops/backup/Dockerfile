# postgres:17-alpine — imagem base mantida por decisão do usuário
# mesmo sem mais servir Postgres; só ganha o pacote sqlite (binário sqlite3
# CLI) para o `.backup` do banco em arquivo único.
FROM postgres:17-alpine

RUN apk add --no-cache curl unzip dcron tzdata sqlite

# Versão fixada explicitamente — nunca `curl | bash` sem pin em produção
# (Assumption A5). O script oficial de install.sh do rclone
# NÃO aceita um argumento de versão (só aceita "beta" opcionalmente) — ele
# sempre instala o "current" (latest). Por isso o download é feito direto
# do release fixado em downloads.rclone.org, com verificação de checksum
# contra o SHA256SUMS publicado pelo próprio projeto para essa versão.
# Trocar a versão aqui (no ARG) é a única forma de atualizar o rclone desta
# imagem. Nome do ARG deliberadamente NÃO prefixado com "RCLONE_" — o
# próprio binário rclone lê qualquer env var RCLONE_<FLAG> como config de
# flag (ex.: RCLONE_VERSION vira a flag booleana --version), e o ARG do
# Dockerfile também fica exposto como env var dentro do RUN; um ARG chamado
# RCLONE_VERSION faz `rclone version` falhar com
# "Invalid value when setting --version from environment variable" —
# confirmado empiricamente nesta revisão.
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
COPY backup_container.sh /backup.sh
RUN chmod +x /backup.sh /retencao.sh /testar_retencao.sh

ENV TZ=America/Sao_Paulo

# Agenda diária às 03:00 America/Sao_Paulo via dcron. O crontab roda como
# root (postgres:17-alpine não tem outro usuário com HOME configurado para
# dcron), a saída vai para stdout do container (visível em
# `docker compose logs backup`).
RUN echo "0 3 * * * /backup.sh >> /proc/1/fd/1 2>> /proc/1/fd/2" > /etc/crontabs/root

CMD ["crond", "-f", "-d", "8"]
