from .base import *  # noqa: F403


DEBUG = env.bool("DEBUG", default=True)  # noqa: F405
ALLOWED_HOSTS = ["*"]

# base.py fixa STORAGES["staticfiles"] com o manifest hashing do WhiteNoise
# (CompressedManifestStaticFilesStorage) — correto em produção, onde o
# Dockerfile roda `collectstatic` no build. Em dev/test, sem esse manifest,
# qualquer template com {% static %} levanta ValueError ("Missing
# staticfiles manifest entry"). Aqui, storage simples direto do
# STATICFILES_DIRS, sem exigir build prévio.
STORAGES = {  # noqa: F405
    **STORAGES,  # noqa: F405
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

# Sem isto, `WhiteNoiseMiddleware` só serve o que está em `STATIC_ROOT`
# (populado por `collectstatic`, que só roda no build da imagem de
# produção — Pitfall 19). Em dev/test, sem `collectstatic` prévio,
# `staticfiles/` nem existe: qualquer GET real por um caminho `/static/`
# (não um `{% static %}` resolvido em template) devolveria 404 mesmo com
# o arquivo presente em `STATICFILES_DIRS` — como a página offline
# precisa ser exercitada via `Client().get("/static/offline.html")`
# passando pela stack de middleware real (core.tests.test_pwa), o
# WhiteNoise precisa cair para os finders do `django.contrib.staticfiles`
# em vez do `STATIC_ROOT`. Produção não é afetada — este arquivo nunca
# carrega lá.
WHITENOISE_USE_FINDERS = True
