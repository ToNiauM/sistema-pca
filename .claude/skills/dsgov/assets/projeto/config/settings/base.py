"""Configurações comuns a todos os ambientes (padrão da skill dsgov).

Portabilidade é invariante: nada depende do host. Tudo que varia entre ambientes vem de
variáveis de ambiente lidas por django-environ (.env na raiz em dev; ambiente real em produção).
"""

from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")

INSTALLED_APPS = [
    "whitenoise.runserver_nostatic",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "django.forms",  # necessário para o FORM_RENDERER TemplatesSetting achar os templates de widget
    "django_htmx",
    "axes",
    "core",
    # apps de domínio (adicione abaixo; o gerador `gerar_app.py` insere aqui)
    # __APPS__
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    # Depois do HtmxMiddleware (que popula request.htmx): converte redirects em HX-Redirect,
    # senão o formulário de login inteiro aparece dentro de um fragmento quando a sessão expira.
    "core.middleware.HtmxRedirectMiddleware",
    "axes.middleware.AxesMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    # Django 5.1+: toda rota exige login, salvo as marcadas com @login_not_required.
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
]

AUTH_USER_MODEL = "core.Usuario"

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

# Bloqueio de força bruta: 5 falhas da combinação usuário+IP → 15 min.
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = timedelta(minutes=env.int("AXES_COOLOFF_MINUTES", default=15))
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_USERNAME_FORM_FIELD = "username"
AXES_LOCKOUT_CALLABLE = "core.views.resposta_bloqueio"

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"

SESSION_COOKIE_AGE = env.int("SESSION_COOKIE_AGE", default=28800)  # 8h
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_SAVE_EVERY_REQUEST = True

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "core" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.dsgov",
            ],
        },
    },
]

# Todo {{ form }} e {{ form.campo }} sai no HTML do DSGov (br-input, br-select, br-checkbox...).
FORM_RENDERER = "core.forms.renderer.DSGovFormRenderer"

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {"default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}")}
DATABASES["default"]["CONN_MAX_AGE"] = env.int("CONN_MAX_AGE", default=60)
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True
USE_THOUSAND_SEPARATOR = True
DATE_FORMAT = "d/m/Y"
DATETIME_FORMAT = "d/m/Y H:i"
SHORT_DATE_FORMAT = "d/m/Y"
DATE_INPUT_FORMATS = ["%d/%m/%Y", "%Y-%m-%d"]
DATETIME_INPUT_FORMATS = ["%d/%m/%Y %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"]

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "core" / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SESSION_COOKIE_SECURE = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = False  # o dsgov.js lê o cookie para o HTMX; True quebra todas as escritas.
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_SAMESITE = "Lax"
# Token velho (bfcache/"Voltar" após rotate_token() no login/logout, ou aba
# de login esquecida aberta) nunca mais cai na página crua "Verificação
# CSRF falhou" do Django; ver core.views.csrf_failure_view (quick pca-cfc
# 260912-dpa, espelhado aqui).
CSRF_FAILURE_VIEW = "core.views.csrf_failure_view"

# Sem isto, o filtro `require_debug_true` do LOGGING padrão do Django
# descarta django.security.csrf/django.request com DEBUG=False, e
# `docker compose logs web` nunca mostra o motivo real de um 403/500. Sem
# corpo de requisição nem credenciais no log — só path e motivo.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "loggers": {
        "django.security.csrf": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}

MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"

# Identidade visual (o layout lê daqui; ver references/layout.md da skill dsgov).
DSGOV = {
    "ORGAO": env("DSGOV_ORGAO", default="__ORGAO__"),
    "ORGAO_SIGLA": env("DSGOV_ORGAO_SIGLA", default="__ORGAO_SIGLA__"),
    "SISTEMA": env("DSGOV_SISTEMA", default="__SISTEMA__"),
    "SISTEMA_SUBTITULO": env("DSGOV_SISTEMA_SUBTITULO", default=""),
    "LOGO": env("DSGOV_LOGO", default=""),  # caminho em static/, ex.: "img/logo.svg"; vazio = sigla em texto
    "LINKS_ACESSO_RAPIDO": [],  # lista de (rótulo, url) para o dropdown "Acesso Rápido"
    "RODAPE_TEXTO": env(
        "DSGOV_RODAPE_TEXTO",
        default="Sistema interno. Uso restrito a usuários autorizados.",
    ),
    "ITENS_POR_PAGINA": 20,
    "OPCOES_POR_PAGINA": (10, 20, 50),
}
