from .base import *  # noqa: F403


DEBUG = env.bool("DEBUG", default=True)  # noqa: F405
ALLOWED_HOSTS = ["*"]

# base.py usa manifest hashing do WhiteNoise, que exige `collectstatic`
# prévio; aqui, storage simples direto do STATICFILES_DIRS, sem build.
STORAGES = {  # noqa: F405
    **STORAGES,  # noqa: F405
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

# Sem isto, WhiteNoiseMiddleware só serve o que está em STATIC_ROOT,
# populado por `collectstatic` (só roda no build de produção). Em dev/test,
# sem esse build, um GET real em /static/ cai nos finders do
# django.contrib.staticfiles em vez de STATIC_ROOT.
WHITENOISE_USE_FINDERS = True
