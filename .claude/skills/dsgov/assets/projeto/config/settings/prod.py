from .base import *  # noqa: F403

DEBUG = False
# 127.0.0.1 sempre presente: é o que o healthcheck do compose usa.
ALLOWED_HOSTS = list(set(env.list("ALLOWED_HOSTS", default=[]) + ["127.0.0.1"]))  # noqa: F405

# Atrás de proxy reverso (nginx/Cloudflare) que repassa X-Forwarded-Proto.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)  # noqa: F405
SECURE_REDIRECT_EXEMPT = [r"^healthz$"]
USE_X_FORWARDED_HOST = False
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])  # noqa: F405

# HSTS curto até o TLS estar comprovadamente estável; suba depois.
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=3600)  # noqa: F405
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]

AXES_IPWARE_PROXY_COUNT = env.int("AXES_IPWARE_PROXY_COUNT", default=1)  # noqa: F405
AXES_IPWARE_META_PRECEDENCE_ORDER = ("HTTP_X_FORWARDED_FOR", "REMOTE_ADDR")
