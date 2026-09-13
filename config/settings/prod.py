from .base import *  # noqa: F403


DEBUG = False
# 127.0.0.1 sempre presente: é quem o healthcheck interno do compose usa;
# sem isto, o healthcheck falharia por Host inválido com DEBUG=False.
ALLOWED_HOSTS = list(
    set(env.list("ALLOWED_HOSTS", default=[]) + ["127.0.0.1"])  # noqa: F405
)

# O app roda atrás de um proxy reverso que repassa X-Forwarded-Proto;
# sem esta linha o Django enxerga toda requisição como HTTP e entra em
# loop de redirect com SECURE_SSL_REDIRECT.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)  # noqa: F405
# O healthcheck interno do compose bate em /healthz via HTTP puro, direto
# no serviço — sem esta exceção, SECURE_SSL_REDIRECT devolveria 301 e o
# compose marcaria o container unhealthy.
SECURE_REDIRECT_EXEMPT = [r"^healthz$"]
# O proxy do host escreve Host e X-Forwarded-Proto ele mesmo; nunca confiar
# em X-Forwarded-Host vindo do cliente.
USE_X_FORWARDED_HOST = False

# Precisa do esquema (https://), não só o host — exigência do Django para
# CSRF sob HTTPS via proxy.
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])  # noqa: F405

# HSTS conservador na fase de validação: max-age longo é irreversível pelo
# próprio max-age. includeSubDomains/preload ficam False de propósito —
# ajuste para a topologia real do seu host quando o domínio for exclusivo.
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=3600)  # noqa: F405
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
# W005/W021 são os avisos que includeSubDomains=False e preload=False
# produzem — consequência esperada, silenciados para que `check --deploy`
# continue em zero warnings e qualquer aviso novo apareça de verdade.
SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]

# Proxy reverso na frente do app conta como um salto confiável de mais.
# AXES_IPWARE_PROXY_COUNT sozinho é um no-op: o default de
# AXES_IPWARE_META_PRECEDENCE_ORDER ignora X-Forwarded-For por completo.
# Sem as duas linhas juntas (mais django-ipware instalado), a resolução de
# IP cai para None e AXES_LOCKOUT_PARAMETERS=[["username","ip_address"]]
# colapsa de volta a "só por usuário", em silêncio.
AXES_IPWARE_PROXY_COUNT = 2
AXES_IPWARE_META_PRECEDENCE_ORDER = ("HTTP_X_FORWARDED_FOR", "REMOTE_ADDR")
