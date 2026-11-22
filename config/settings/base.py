import sys
import tempfile
from datetime import timedelta
from pathlib import Path

import environ


BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")

INSTALLED_APPS = [
    "whitenoise.runserver_nostatic",
    # PcaAdminConfig troca o AdminSite padrão pelo PcaAdminSite via `default_site` — config/urls.py não muda.
    "core.apps.PcaAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
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
    "apps.solicitacoes",
    "apps.assistente",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # DENY por padrão: o sistema é htmx e nunca é embutido em iframe; fecha o
    # clickjacking (check --deploy W002).
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.common.CommonMiddleware",
    # Fase 42 — só atua em "/api/"; as views da API
    # são csrf_exempt, então a ordem exata em relação a CsrfViewMiddleware
    # não importa, mas precisa vir antes de LoginRequiredMiddleware (ver
    # docstring em core/middleware.py::CorsExtensaoMiddleware).
    "core.middleware.CorsExtensaoMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # A ordem entre AuthenticationMiddleware e MessageMiddleware não é a
    # recomendação genérica do axes (que sugere AxesMiddleware logo após
    # AuthenticationMiddleware) — neste projeto HistoryRequestMiddleware e
    # HtmxMiddleware entram propositalmente entre os dois.
    "simple_history.middleware.HistoryRequestMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    # Logo depois do HtmxMiddleware, que é quem popula request.htmx (Pitfall 2).
    "core.middleware.HtmxRedirectMiddleware",
    "axes.middleware.AxesMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    # Django 5.1+: bloqueia por padrão qualquer rota sem @login_not_required.
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    # Precisa de request.user já resolvido pelo
    # AuthenticationMiddleware/LoginRequiredMiddleware. O redirect() comum
    # que ela emite sobe até HtmxRedirectMiddleware (mais cedo na lista),
    # que converte em HX-Redirect quando a requisição é htmx (plano).
    "core.middleware.TrocaSenhaObrigatoriaMiddleware",
    # Revisão da Fase 31 — por último: precisa de MessageMiddleware/
    # SessionMiddleware já configurados (mais cedo na lista) e, por estar
    # mais perto da view, tem a primeira chance de tratar `OperationalError`
    # ("database is locked") antes de qualquer outra middleware com
    # `process_exception` (chamadas de baixo para cima). Ver docstring em
    # core/middleware.py::BancoOcupadoMiddleware.
    "core.middleware.BancoOcupadoMiddleware",
    # QA de segurança 30/09/2026 (fluxos #13) — ÚLTIMO item: mais perto da
    # view, vê a resposta final de qualquer rota autenticada e só
    # completa o Cache-Control quando nenhuma view já decidiu um (ver
    # docstring em core/middleware.py::CacheControlAutenticadoMiddleware).
    "core.middleware.CacheControlAutenticadoMiddleware",
]

AUTH_USER_MODEL = "core.Usuario"

# Argon2 no topo — requisito de segurança do convenções do projeto.
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
# Bloqueio pela combinação usuário+IP, nunca pelo usuário isolado —
# evita que alguém trave a conta do presidente só sabendo o e-mail dele.
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
# Django SEMPRE usa o kwarg literal "username" em authenticate(), mesmo com
# USERNAME_FIELD="email" no User customizado (convenção documentada do
# Django). Sem esta linha, o axes usa o default (USERNAME_FIELD do model,
# "email") para procurar a credencial — uma chave que nunca existe no dict
# passado a authenticate() — e grava toda tentativa falha com username=None,
# quebrando silenciosamente o bloqueio por usuário+IP (verificado
# nesta revisão: sem isto, AxesBackend nunca bloqueia a 6ª tentativa).
AXES_USERNAME_FORM_FIELD = "username"
# AxesMiddleware, por padrão, substitui a resposta de QUALQUER view por uma
# página de bloqueio genérica sempre que request.axes_locked_out é True —
# mesmo quando a view já tratou o bloqueio corretamente (aqui, o fragmento
# em HTTP 200). Sem isto, essa página genérica sobrescreve o fragmento
# do login_view e quebra a convenção htmx (Pitfall 1) — descoberto ao testar
# a 6ª tentativa via HTTP nesta revisão do plano.
AXES_LOCKOUT_CALLABLE = "core.axes_lockout.resposta_bloqueio"

LOGIN_URL = "/login/"

# Sessão de 8h de inatividade, sobrescrevível por env.
SESSION_COOKIE_AGE = env.int("SESSION_COOKIE_AGE", default=28800)
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

# Fase 17 — "Próximos do vencimento" (Bloco B): dias corridos até
# `prazo_entrega` que classificam um processo NO PRAZO como "próximo do
# vencimento" (recorte transversal, não etapa de funil). Configurável, nunca
# constante em código — mesmo padrão `env.int(nome, default=N)` de
# AXES_COOLOFF_MINUTES/SESSION_COOKIE_AGE acima.
PCA_DIAS_PROXIMOS_VENCIMENTO = env.int("PCA_DIAS_PROXIMOS_VENCIMENTO", default=15)

# Fase 36 — índice padrão de reajuste projetado
# (`apps.pca.projecao.fluxo`) quando a tela não escolhe outro
# no seletor. `settings.DSGOV`/env, mesmo padrão `env(nome,
# default=...)` de AXES_COOLOFF_MINUTES/SESSION_COOKIE_AGE acima.
PCA_INDICE_REAJUSTE_PADRAO = env("PCA_INDICE_REAJUSTE_PADRAO", default="IPCA")

# Fase 32 — robô SEI: credenciais e alvo de login, lidos por
# `env()`, sem default para usuário/senha — o comando falha cedo
# com mensagem clara do django-environ quando faltam no `.env`; as duas
# chaves já existem no `.env` real deste projeto desde o spike
# notas internas do projeto. Nunca logado, nunca incluído no JSON de
# coleta/execução, nunca em mensagem de exceção (apps/pca/sei/coletor.py).
SEI_USUARIO = env("SEI_USUARIO")
SEI_SENHA = env("SEI_SENHA")
SEI_LOGIN_URL = env("SEI_LOGIN_URL", default="https://sei.cfc.org.br/sei/")
SEI_ORGAO = env("SEI_ORGAO", default="CFC")
SEI_DATA_DIR = env("SEI_DATA_DIR", default=str(BASE_DIR / "data" / "sei"))
SEI_USUARIO_TECNICO_EMAIL = env("SEI_USUARIO_TECNICO_EMAIL", default="robo-sei@pca.local")

# Fase 42 — API JSON para as extensões SEI Pro:
# `CorsExtensaoMiddleware` (core/middleware.py) só ecoa
# Access-Control-Allow-Origin para uma destas origens (mais
# `chrome-extension://[a-p]{32}`, sem setting — ID de extensão muda por
# máquina); `API_MAX_CORPO_MB` é o teto do corpo do POST (apps/pca/
# api/autenticacao.py::corpo_dentro_do_limite), acima de
# DATA_UPLOAD_MAX_MEMORY_SIZE (16 MB) para sobrar margem de leitura.
# Mesmo padrão `env(nome, default=...)` de AXES_COOLOFF_MINUTES/
# PCA_DIAS_PROXIMOS_VENCIMENTO acima.
API_ORIGENS_EXTENSAO = env.list("API_ORIGENS_EXTENSAO", default=["https://sei.cfc.org.br"])
API_MAX_CORPO_MB = env.int("API_MAX_CORPO_MB", default=10)

# (`PUT /api/sei/ficha`) — teto de tamanho do campo `dados`
# (JSON livre da extensão, V-5), medido como
# `len(json.dumps(dados).encode("utf-8"))`; acima disso, 413
# `corpo_grande_demais` sem gravar nada.
API_FICHA_MAX_KB = env.int("API_FICHA_MAX_KB", default=512)

# Fase 42 — robô e extensão convivem: uma varredura
# pula (sem abrir o navegador) qualquer número SEI com coleta de
# `extensao.json` mais recente que estas horas, usando essa coleta no lugar
# da do robô (`coletor.coletar_um`). `<= 0` desliga o pulo por completo,
# preservando o comportamento de antes da Fase 42. Mesmo padrão
# `env.float(nome, default=...)` das demais settings acima.
SEI_PULAR_SE_EXTENSAO_H = env.float("SEI_PULAR_SE_EXTENSAO_H", default=24.0)

# Sem isto, o Django só recalcula a expiração da sessão na ESCRITA, não na
# leitura — uma navegação só de leitura (dashboard/tabela) seria derrubada
# no meio da reunião mesmo com o usuário ativo (achado).
SESSION_SAVE_EVERY_REQUEST = True

ROOT_URLCONF = "config.urls"

# Design das telas (branch tabler): PCA_DESIGN=tabler põe tabler/templates/ na frente de tudo — cada
# template que existir lá (páginas, parciais dsgov/_*.html, forms) vence o do DSGov; sem a variável
# (ou PCA_DESIGN=dsgov) nada muda. Rotas, views, regras e banco são os mesmos nos dois designs.
PCA_DESIGN = env.str("PCA_DESIGN", default="dsgov").strip().lower()
# A suíte roda sempre no design de sempre (os testes de markup são o contrato dele), mesmo num container com
# PCA_DESIGN=tabler no .env; a casca Tabler tem os testes dela em core/tests/test_casca_tabler.py, que a liga por
# override_settings. PCA_DESIGN_TESTES=tabler força a suíte inteira na casca nova.
if len(sys.argv) > 1 and sys.argv[1] == "test":
    PCA_DESIGN = env.str("PCA_DESIGN_TESTES", default="dsgov").strip().lower()

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": ([BASE_DIR / "tabler" / "templates"] if PCA_DESIGN == "tabler" else []) + [
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
            ] + (["core.context_processors.ui"] if PCA_DESIGN == "tabler" else []),
        },
    },
]

# Fase 26 — FORM_RENDERER do padrão DSGov: {{ form }}/{{ form.campo }}
# produzem o HTML canônico do DS (br-input/br-select/br-textarea...).
FORM_RENDERER = ("core.forms.renderer.TablerFormRenderer" if PCA_DESIGN == "tabler"
                 else "core.forms.renderer.DSGovFormRenderer")

# Fase 26 — identidade visual e menu da casca dsgov (consumidos por
# core.context_processors.dsgov / core/templates/dsgov/_header.html,_footer.html,_menu.html).
# Marca continua do CFC (sem logo gov.br); theme-color/theme_color do manifest
# permanecem "#1351b4" (único hex admitido pelo verificador, já usado em
# core/views.py::manifest_view antes desta fase).
DSGOV = {
    "ORGAO": "Conselho Federal de Contabilidade",
    "ORGAO_SIGLA": "CFC",
    "SISTEMA": "PCA CFC",
    "SISTEMA_SUBTITULO": "Acompanhamento do Plano de Contratações Anual",
    "LOGO": "img/logo-cfc.png",
    "LINKS_ACESSO_RAPIDO": [("Portal do CFC", "https://cfc.org.br")],
    "RODAPE_TEXTO": "Conselho Federal de Contabilidade — Plano de Contratações Anual",
    # Rodapé no padrão do PNCP (`dsgov/_footer.html`): parágrafos
    # institucionais + "Sobre o sistema"; a busca do cabeçalho diz onde procura.
    "RODAPE_PARAGRAFOS": (
        "O PCA CFC acompanha o Plano de Contratações Anual do Conselho Federal de "
        "Contabilidade, do planejamento à publicação, item a item.",
        "As informações são registradas pela equipe do PCA e pelas unidades demandantes, "
        "com atualização automática a partir do SEI.",
    ),
    "SOBRE_URL_NAME": "core:sobre",
    "BUSCA_PLACEHOLDER": "Buscar no PCA",
    # Timbrado só na impressão do relatório de movimentação — placeholder
    # até o usuário informar o texto oficial do rodapé institucional. Nada inventado.
    "RODAPE_TIMBRADO": "Conselho Federal de Contabilidade — www.cfc.org.br",
    # Item "Meu perfil" no dropdown do avatar (dsgov/_header.html)
    # e destino da área do usuário (nome, trocar senha, sair). Opcional no padrão DSGov:
    # sem a chave, o header não mostra o item.
    "PERFIL_URL_NAME": "core:perfil",
    "ITENS_POR_PAGINA": 20,
    "OPCOES_POR_PAGINA": (10, 20, 50),
    # Fase 28 — ponto de extensão para o campo de
    # busca do header (`core/templates/dsgov/_header.html`, genérico e
    # reusável por outros sistemas gerados pelo padrão DSGov): o nome da rota
    # concreta deste projeto que responde pela busca global. Ausente =
    # `data-no-search` no header (busca oculta), nunca um erro de template.
    "BUSCA_URL_NAME": "pca:busca",
}

WSGI_APPLICATION = "config.wsgi.application"

# Caminho absoluto (4 barras) dentro do volume nomeado montado em /app/data
# — arquivo único, sem serviço de banco separado. `core.db` registra as
# UDFs de unaccent/collation em toda conexão SQLite nova (core/apps.py).
DATABASES = {
    "default": env.db("DATABASE_URL", default="sqlite:////app/data/db.sqlite3")
}
# As chaves de OPTIONS abaixo (transaction_mode/timeout/init_command) só
# existem no backend sqlite3 — psycopg rejeita "transaction_mode" como
# opção de conexão. Ambientes legados que ainda apontam DATABASE_URL para
# Postgres continuam subindo sem essa chave — não suportado nem testado
# desde a Fase 31.
if DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":
    DATABASES["default"]["OPTIONS"] = {
        # Adquire o lock de escrita cedo (evita SQLITE_BUSY em duas escritas
        # concorrentes) e espera até 20s por um lock ocupado antes de falhar.
        "transaction_mode": "IMMEDIATE",
        "timeout": 20,
        "init_command": (
            "PRAGMA journal_mode=WAL;"
            "PRAGMA synchronous=NORMAL;"
            "PRAGMA foreign_keys=ON;"
            "PRAGMA busy_timeout=20000;"
        ),
    }
    # Revisão da Fase 31 (MD-01): sem isto, TransactionTestCase/threads usam
    # o padrão `file:memorydb_default?mode=memory&cache=shared` — sem WAL
    # (que só existe em arquivo) e com um modelo de lock (tabela inteira,
    # `SQLITE_LOCKED` imediato) diferente do arquivo real em produção. Um
    # arquivo em `tempfile.gettempdir()` (não `BASE_DIR`, que é a árvore de
    # trabalho montada `:ro` no container de dev) restaura o comportamento
    # de lock genuíno (WAL + `busy_timeout`) para os testes de concorrência.
    DATABASES["default"]["TEST"] = {
        "NAME": str(Path(tempfile.gettempdir()) / "pca-test.sqlite3"),
    }

# Conexão por request é barata em arquivo local — WAL permite N leitores e
# 1 escritor ao mesmo tempo, então manter conexão persistente por thread
# não traz ganho. Sem health check: não há socket de rede caindo sob TTL.
DATABASES["default"]["CONN_MAX_AGE"] = env.int("CONN_MAX_AGE", default=0)

# Fase 39 — Assistente do PCA (spec §2). DEPOIS de DATABASES: o
# default dos 3 caminhos auxiliares deriva do diretório do banco PCA
# (`/app/data/ia/*.sqlite3` — mesmo volume `pca_data`, fora de backup/
# export/restore do PCA). `IA_API_KEY` vazio desabilita o assistente
# inteiro (menu oculto, rotas 404) sem quebrar check/testes/collectstatic/
# robô (A20) — `checks.py` valida os demais limites sem exigir chave.
IA_PROVEDOR = env("IA_PROVEDOR", default="openai")
IA_API_KEY = env("IA_API_KEY", default="")
IA_MODELO_ASSISTENTE = env("IA_MODELO_ASSISTENTE", default="gpt-4.1-mini")
# Raciocínio do modelo do assistente ("" = não enviar). Modelos gpt-6 com ferramentas: "none" (exigência
# da API de chat); modelos sem raciocínio (gpt-4.1) recusam o parâmetro, então fica vazio.
IA_ESFORCO_RACIOCINIO = env("IA_ESFORCO_RACIOCINIO", default="")
# Reservados — segundo leitor IA do robô SEI é fase futura; não ativam
# nada nesta entrega (spec irmã 2026-09-19-robo-sei-leitura-por-ia-design.md).
IA_MODELO_ROBO = env("IA_MODELO_ROBO", default="gpt-6-luna")
# Raciocínio do robô leitor do SEI: sem ferramentas, o gpt-6-luna aceita qualquer nível; "xhigh" (o máximo) custa
# ~US$ 0,0005 por documento e leva 3–7 s (medido em 2026-09-23 com contrato, aditivo e apostilamento reais).
IA_ESFORCO_RACIOCINIO_ROBO = env("IA_ESFORCO_RACIOCINIO_ROBO", default="xhigh")
IA_ROBO_ATIVO = env.bool("IA_ROBO_ATIVO", default=False)
IA_MODELO_EMBED = env("IA_MODELO_EMBED", default="text-embedding-3-small")
# IA_PROVEDOR agora escolhe só o adaptador de CHAT
# ("openai"/"anthropic"); embeddings são sempre OpenAI (IA_PROVEDOR_EMBED
# só aceita "openai" — a Anthropic não tem API de embeddings).
# IA_API_KEY_EMBED vazia reaproveita IA_API_KEY e só faz sentido quando
# IA_PROVEDOR == IA_PROVEDOR_EMBED.
IA_PROVEDOR_EMBED = env("IA_PROVEDOR_EMBED", default="openai")
IA_API_KEY_EMBED = env("IA_API_KEY_EMBED", default="")
_IA_DIR_PADRAO = Path(str(DATABASES["default"]["NAME"])).parent / "ia"
IA_INDICE_PATH = env("IA_INDICE_PATH", default=str(_IA_DIR_PADRAO / "indice.sqlite3"))
IA_ESTADO_PATH = env("IA_ESTADO_PATH", default=str(_IA_DIR_PADRAO / "estado.sqlite3"))
IA_CONVERSAS_PATH = env(
    "IA_CONVERSAS_PATH", default=str(_IA_DIR_PADRAO / "conversas.sqlite3")
)
IA_MAX_PERGUNTAS_DIA = env.int("IA_MAX_PERGUNTAS_DIA", default=50)
# Nunca maior que a sessão autenticada — uma conversa não sobrevive além
# do tempo em que o usuário continua logado.
IA_CONVERSA_TTL_S = min(
    env.int("IA_CONVERSA_TTL_S", default=28800), SESSION_COOKIE_AGE
)
IA_MAX_TOKENS_RESPOSTA = env.int("IA_MAX_TOKENS_RESPOSTA", default=1500)
IA_TIMEOUT_S = env.int("IA_TIMEOUT_S", default=30)
IA_PRAZO_PERGUNTA_S = env.int("IA_PRAZO_PERGUNTA_S", default=60)

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

# Fase 26 — a pitfall que este comentário documentava (Fase 22 Pitfall 5: o loader Stencil de `@govbr-ds/webcomponents`
# resolvia chunks `p-*.js` em runtime via `import.meta.url` relativo, fora
# de `{% static %}`, exigindo os nomes de arquivo ORIGINAIS ao lado dos
# hasheados) não existe mais — `core/static/vendor/govbr-ds/webcomponents/`
# saiu junto com o pacote inteiro (inventário zero). `core/static/
# dsgov/**` (vendor congelado atual) é só CSS/JS/fonte servidos direto por
# `{% static %}`, sem loader nenhum resolvendo caminho em runtime —
# `WHITENOISE_KEEP_ONLY_HASHED_FILES = True` voltou a ser uma opção segura,
# mas ativá-la é uma otimização não pedida por esta fase (fora de escopo:
# nenhum teste/must-have exige isso); registrado como ideia para uma quick
# futura, não decisão tomada aqui.

# A confirmação da importação administrativa transporta a planilha em Base64.
# Com ``multipart/form-data``, 10 MiB de arquivo ocupam pouco mais de 13,3 MiB
# no campo oculto; 16 MiB deixam margem para o envelope multipart e os demais
# campos, sem aceitar arquivos maiores que o limite validado pelo formulário.
DATA_UPLOAD_MAX_MEMORY_SIZE = 16 * 1024 * 1024

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SESSION_COOKIE_SECURE = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = False  # htmx lê o cookie; True quebra as escritas.
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_USE_SESSIONS = False
# Token velho (bfcache/"Voltar" após rotate_token() no
# login/logout, ou aba de login esquecida aberta) nunca mais cai na página
# crua "Verificação CSRF falhou" do Django; ver core.views.csrf_failure_view.
CSRF_FAILURE_VIEW = "core.views.csrf_failure_view"

# Sem isto, o filtro `require_debug_true` do LOGGING
# padrão do Django descarta django.security.csrf/django.request com
# DEBUG=False (produção), e `docker compose logs web` nunca mostra o motivo
# real de um 403/500. Sem corpo de requisição nem credenciais no log — só
# path e motivo (`core.views.csrf_failure_view` já filtra isso). `prod.py`
# não sobrescreve esta chave.
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
        # Fase 39 — logs estruturados do assistente (usuário, quantidade,
        # tokens, ferramenta, código de erro), NUNCA texto de
        # pergunta/resposta/argumentos nem `exc_info` (A18).
        "apps.assistente": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
