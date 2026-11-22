from .base import *  # noqa: F403


DEBUG = False
# 127.0.0.1 sempre presente: é quem o healthcheck interno do compose usa
# (`curl http://127.0.0.1:8000/healthz`, ver compose.yml) — sem isto, o
# próprio healthcheck do serviço web falharia por Host inválido assim que
# DEBUG=False ativa a checagem estrita de ALLOWED_HOSTS.
ALLOWED_HOSTS = list(
    set(env.list("ALLOWED_HOSTS", default=[]) + ["127.0.0.1"])  # noqa: F405
)

# O app roda em 127.0.0.1:8000 atrás do nginx do host (e do Cloudflare na
# borda). O nginx repassa `X-Forwarded-Proto $scheme`; sem esta linha o
# Django enxerga toda requisição como HTTP e entra em loop de redirect com
# SECURE_SSL_REDIRECT.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)  # noqa: F405
# O healthcheck interno do compose bate em /healthz via HTTP puro, direto no
# 127.0.0.1:8000 (nunca passa pelo nginx/Cloudflare) — sem esta exceção,
# SECURE_SSL_REDIRECT devolveria 301 para o próprio healthcheck e o compose
# marcaria o container unhealthy eternamente correlato).
SECURE_REDIRECT_EXEMPT = [r"^healthz$"]
# Nginx do host escreve Host e X-Forwarded-Proto ele mesmo (ops/nginx/pca.conf);
# nunca confiar em X-Forwarded-Host vindo do cliente.
USE_X_FORWARDED_HOST = False

# Precisa do esquema (https://), não só o host — exigência do Django para o
# CSRF sob HTTPS via proxy.
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])  # noqa: F405

# HSTS conservador de 1h na fase de validação (do threat model):
# max-age longo é irreversível pelo próprio max-age, e o §11 do documento de requisitos prevê
# migração de host para o CFC — 3600s deixa a janela de arrependimento em
# uma hora. Só sobe depois do TLS confirmado estável no host definitivo.
# includeSubDomains/preload ficam False de propósito: analisedados.online é
# compartilhado por ~27 subdomínios e nenhum deles deve ser arrastado por
# uma decisão tomada aqui. Com ambos em False o cabeçalho atinge somente
# pca.analisedados.online — o irmão ao lado não é afetado.
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=3600)  # noqa: F405
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
# W005/W021 são exatamente os dois avisos que includeSubDomains=False e
# preload=False produzem. São a consequência esperada da decisão acima, não
# um descuido: silenciados explicitamente para que `check --deploy` continue
# em zero warnings e qualquer aviso novo apareça de verdade.
SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]

# atrás de Cloudflare + Nginx do host. AXES_IPWARE_PROXY_COUNT sozinho
# é um no-op silencioso: o default do django-axes para
# AXES_IPWARE_META_PRECEDENCE_ORDER é só ("REMOTE_ADDR",), que ignora por
# completo X-Forwarded-For. Sem as duas linhas juntas (mais django-ipware
# instalado — ver requirements.txt), a resolução de IP cai para None em vez
# do IP do cliente, o que colapsaria
# AXES_LOCKOUT_PARAMETERS=[["username","ip_address"]] de volta a "só por
# usuário", em silêncio (Pattern 3, PITFALLS §).
#
# QA de segurança 30/09/2026 (achado A1): a topologia real tem só 1 salto de
# proxy CONFIÁVEL a descartar, não 2. O Cloudflare insere o IP do cliente
# como ele o vê, e o nginx do host só ACRESCENTA o IP da borda Cloudflare
# via `$proxy_add_x_forwarded_for` (ops/nginx/pca.conf) — ele não é um
# segundo salto independente, é o mesmo salto que o Cloudflare já é. Uma
# requisição legítima chega ao Django com EXATAMENTE 2 entradas no
# X-Forwarded-For ("<ip-do-cliente>, <ip-da-borda-cloudflare>"), ou seja
# 1 proxy confiável a descartar (`AXES_IPWARE_PROXY_COUNT=1`). Com
# `proxy_count=2` (valor anterior), essa requisição de 2 entradas falhava a
# validação de contagem exata do django-ipware e resolvia sempre `None` —
# o bloqueio por IP virava "só por usuário" (qualquer pessoa trava a conta
# de qualquer um sabendo o e-mail) e um XFF forjado de 3 entradas resolvia
# EXATAMENTE ao valor que o atacante escolheu, permitindo força bruta
# ilimitada variando o IP forjado. `axes.helpers.get_client_ip_address`
# roda o django-ipware em modo estrito (`ipw.get_client_ip(meta, True)`,
# hardcoded na própria lib) — por isso, com `proxy_count=1`, um XFF forjado
# (3+ entradas) agora falha a validação de contagem exata e resolve para
# `None` (um bucket `(username, None)` compartilhado, ainda sujeito ao
# mesmo limite de `AXES_FAILURE_LIMIT`), nunca mais para o valor que o
# atacante escolheu — a propriedade de segurança que A1 exige, mesmo que o
# valor resolvido não seja literalmente "o IP do cliente" nesse caso
# forjado. Recomendação adicional (não implementada nesta quick,
# infraestrutura fora do repositório): restringir no nginx do host a
# origem aceita ao Cloudflare.
AXES_IPWARE_PROXY_COUNT = 1
AXES_IPWARE_META_PRECEDENCE_ORDER = ("HTTP_X_FORWARDED_FOR", "REMOTE_ADDR")
