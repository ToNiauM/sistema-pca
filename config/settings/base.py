from datetime import timedelta
from pathlib import Path

import environ


BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")

INSTALLED_APPS = [
    "whitenoise.runserver_nostatic",
    # PcaAdminConfig troca o AdminSite padrão pelo PcaAdminSite via `default_site`.
    "core.apps.PcaAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.postgres",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.forms",
    "django_htmx",
    "simple_history",
    "axes",
    "core",
    "apps.catalogo",
    "apps.pca",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # DENY por padrão: sistema nunca é embutido em iframe.
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # HistoryRequestMiddleware e HtmxMiddleware entram propositalmente entre
    # AuthenticationMiddleware e MessageMiddleware.
    "simple_history.middleware.HistoryRequestMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    # Logo depois do HtmxMiddleware, que popula request.htmx.
    "core.middleware.HtmxRedirectMiddleware",
    "axes.middleware.AxesMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    # Django 5.1+: bloqueia por padrão qualquer rota sem @login_not_required.
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    # Sempre por último: precisa de request.user já resolvido. O redirect()
    # sobe até HtmxRedirectMiddleware, que converte em HX-Redirect se for htmx.
    "core.middleware.TrocaSenhaObrigatoriaMiddleware",
]

AUTH_USER_MODEL = "core.Usuario"

# Argon2 no topo dos hashers de senha.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

# Axes sempre antes do ModelBackend padrão.
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = timedelta(minutes=env.int("AXES_COOLOFF_MINUTES", default=15))
# Bloqueio pela combinação usuário+IP, nunca pelo usuário isolado — evita
# que alguém trave a conta de outra pessoa só sabendo o e-mail dela.
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
# Django sempre usa o kwarg literal "username" em authenticate(), mesmo com
# USERNAME_FIELD="email" no User customizado. Sem esta linha, o axes grava
# toda tentativa falha com username=None e nunca bloqueia.
AXES_USERNAME_FORM_FIELD = "username"
# Por padrão o AxesMiddleware substitui a resposta de qualquer view por uma
# página de bloqueio genérica; aqui o fragmento de bloqueio precisa manter
# HTTP 200 para a convenção htmx.
AXES_LOCKOUT_CALLABLE = "core.axes_lockout.resposta_bloqueio"

LOGIN_URL = "/login/"

# Sessão de 8h de inatividade, sobrescrevível por env.
SESSION_COOKIE_AGE = env.int("SESSION_COOKIE_AGE", default=28800)
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

# Dias corridos até `prazo_entrega` que classificam um processo NO PRAZO
# como "próximo do vencimento". Configurável, nunca constante em código.
PCA_DIAS_PROXIMOS_VENCIMENTO = env.int("PCA_DIAS_PROXIMOS_VENCIMENTO", default=15)
# Sem isto, o Django só recalcula a expiração da sessão na escrita — uma
# navegação só de leitura derrubaria a sessão mesmo com o usuário ativo.
SESSION_SAVE_EVERY_REQUEST = True

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [
            BASE_DIR / "core" / "templates",
            # A tela administrativa de importação não altera a casca do app.
            BASE_DIR / "apps" / "pca" / "importacao" / "templates",
        ],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.usuario_atual",
                "apps.pca.context_processors.exercicios_disponiveis",
                "core.context_processors.dsgov",
            ],
        },
    },
]

# FORM_RENDERER da skill dsgov: {{ form }}/{{ form.campo }} produzem o
# HTML canônico do DS (br-input/br-select/br-textarea...).
FORM_RENDERER = "core.forms.renderer.DSGovFormRenderer"

# Identidade visual e menu da casca dsgov, consumidos por
# core.context_processors.dsgov / core/templates/dsgov/_header.html,_footer.html,_menu.html.
# Valores institucionais vêm de variáveis de ambiente com defaults neutros;
# theme-color do manifest é "#1351b4", único hex admitido pelo verificador.
DSGOV = {
    "ORGAO": env("DSGOV_ORGAO", default="Órgão"),
    "ORGAO_SIGLA": env("DSGOV_ORGAO_SIGLA", default="ÓRGÃO"),
    "SISTEMA": env(
        "DSGOV_SISTEMA",
        default="Sistema de Acompanhamento do Plano de Contratações Anual",
    ),
    "SISTEMA_SUBTITULO": env("DSGOV_SISTEMA_SUBTITULO", default=""),
    # Vazio cai no fallback de sigla em texto de _header.html (template
    # congelado pela skill, já trata DSGOV.LOGO falsy — não editar).
    "LOGO": env("DSGOV_LOGO", default=""),
    # Lista de tuplas (rótulo, url); o loop de _header.html tolera lista vazia.
    "LINKS_ACESSO_RAPIDO": [],
    "RODAPE_TEXTO": env(
        "DSGOV_RODAPE_TEXTO",
        default="Sistema de Acompanhamento do Plano de Contratações Anual",
    ),
    # Timbrado só na impressão do relatório de movimentação — vazio por
    # padrão; cada instalação informa o texto oficial do seu próprio rodapé.
    "RODAPE_TIMBRADO": env("DSGOV_RODAPE_TIMBRADO", default=""),
    # Item "Meu perfil" no dropdown do avatar; opcional — sem a chave, o
    # header não mostra o item.
    "PERFIL_URL_NAME": "core:perfil",
    "ITENS_POR_PAGINA": 20,
    "OPCOES_POR_PAGINA": (10, 20, 50),
    # Rota que responde pela busca global do header; ausente =
    # `data-no-search` (busca oculta), nunca erro de template.
    "BUSCA_URL_NAME": "pca:busca",
}

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {"default": env.db("DATABASE_URL")}

# Conexões persistentes com o Postgres; CONN_HEALTH_CHECKS testa a conexão
# antes de reusar. Default via env preserva a portabilidade.
DATABASES["default"]["CONN_MAX_AGE"] = env.int("CONN_MAX_AGE", default=60)
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "UserAttributeSimilarityValidator"
        ),
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "core" / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# A confirmação da importação administrativa transporta a planilha em Base64.
# Com multipart/form-data, 10 MiB de arquivo ocupam pouco mais de 13,3 MiB
# no campo oculto; 16 MiB deixam margem para o envelope multipart e os
# demais campos, sem aceitar arquivos maiores que o validado no formulário.
DATA_UPLOAD_MAX_MEMORY_SIZE = 16 * 1024 * 1024

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SESSION_COOKIE_SECURE = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = False  # htmx lê o cookie; True quebra as escritas.
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_USE_SESSIONS = False
# Token velho (bfcache/"Voltar" após rotate_token(), ou aba de login
# esquecida aberta) nunca cai na página crua "Verificação CSRF falhou".
CSRF_FAILURE_VIEW = "core.views.csrf_failure_view"

# Sem isto, o filtro require_debug_true do LOGGING padrão descarta
# django.security.csrf/django.request com DEBUG=False, e os logs nunca
# mostram o motivo real de um 403/500. Sem corpo de requisição nem
# credenciais no log.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
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
