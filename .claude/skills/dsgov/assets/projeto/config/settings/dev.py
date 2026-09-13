from .base import *  # noqa: F403

DEBUG = env.bool("DEBUG", default=True)  # noqa: F405
ALLOWED_HOSTS = ["*"]

# Em dev não há collectstatic: serve direto de STATICFILES_DIRS, sem manifest.
STORAGES = {  # noqa: F405
    **STORAGES,  # noqa: F405
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
WHITENOISE_USE_FINDERS = True

SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
