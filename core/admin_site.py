"""`PcaAdminSite` num módulo próprio, sem nenhum ModelAdmin registrado aqui
(bug encontrado na execução).

`PcaAdminConfig.default_site` (core/apps.py) aponta para
`"core.admin_site.PcaAdminSite"`. A resolução de `admin.site` (LazyObject) é
preguiçosa: `DefaultAdminSite._setup()` importa este módulo só na primeira
vez que algo acessa `admin.site`. Se `PcaAdminSite` vivesse dentro de
`core/admin.py` — que também registra `UsuarioAdmin` via `admin.site.register`
no mesmo import — o próprio import do módulo, disparado de dentro de
`_setup()`, tentaria acessar `admin.site` de novo antes de `_setup()`
terminar de rodar. `LazyObject._setup()` não é reentrante: cada acesso
reentrante à `admin.site` enquanto `_wrapped` ainda está vazio dispara uma
NOVA chamada a `_setup()`, cada uma instanciando um `PcaAdminSite()` novo; a
última chamada a terminar (a mais externa) vence e sobrescreve `_wrapped`
com uma instância cujo `_registry` está vazio — apagando silenciosamente
`Group`, `User` e `Usuario`, registrados contra a instância descartada.
Isolar `PcaAdminSite` num módulo que não registra nada elimina o
reentrant-setup: a resolução de `admin.site` completa de uma vez, e só
depois o autodiscovery normal do Django registra os `ModelAdmin` de cada
app contra o site já pronto.
"""

from django.contrib import admin
from django.urls import reverse

# Ordem fixa dos blocos sintéticos do índice do admin (interface
# consumida pelos plano de wave 2). Qualquer ModelAdmin que
# declarar `admin_grupo = "<um destes rótulos>"` é realocado para o bloco
# correspondente por `PcaAdminSite.get_app_list`; os demais permanecem no
# agrupamento padrão por app do Django.
ORDEM_GRUPOS_ADMIN = [
    "Usuários e bloqueios de login",
    "Catálogos do PCA",
    "Importação da planilha",
    "Auditoria e histórico",
]


class PcaAdminSite(admin.AdminSite):
    """`AdminSite` próprio: gate por superuser e agrupamento
    pt-BR do índice (em diante, via `admin_grupo` declarativo).

    Substitui `admin.site` globalmente através de `default_site` em
    `PcaAdminConfig` (core/apps.py) — `config/urls.py` não muda.
    """

    site_header = "PCA CFC — Administração"
    site_title = "PCA CFC"
    index_title = "Painel do administrador"

    def each_context(self, request):
        # Sobrescreve só os 3 tokens de cor do tema
        # padrão do Django Admin pelo azul do govbr-ds (--blue-warm-vivid-70,
        # #1351b4) — antes o azul institucional do CFC, revertido
        # ("Tudo deve estar IGUAL ao gov"). O Admin roda fora do pipeline de
        # custom properties do app, então não há var(--cor-brand) para
        # reaproveitar aqui; nenhum outro aspecto do tema (densidade, tabela,
        # raio) é tocado.
        contexto = super().each_context(request)
        contexto["admin_tema_css"] = (
            ":root { --primary: #1351b4; --header-bg: #1351b4; --link-fg: #1351b4; }"
        )
        return contexto

    def get_urls(self):
        # Import local (não no topo do módulo): `core.views_banco` importa
        # `core.banco_xlsx`, que importa modelos de `apps.pca`/`apps.
        # catalogo` — carregar isso no topo, antes do app registry estar
        # pronto, arrisca o mesmo problema de import cedo demais que a
        # docstring do módulo descreve para `core.admin_site` em si.
        from django.urls import path

        from core import views_banco

        urls_banco = [
            path(
                "banco/exportar/",
                self.admin_view(views_banco.exportar_view),
                name="banco_exportar",
            ),
            path(
                "banco/importar/",
                self.admin_view(views_banco.importar_view),
                name="banco_importar",
            ),
            path(
                "banco/importar/confirmar/",
                self.admin_view(views_banco.confirmar_view),
                name="banco_confirmar",
            ),
        ]
        return urls_banco + super().get_urls()

    def has_permission(self, request):
        # Gate explícito, mais restritivo que o `is_staff` padrão do
        # `AdminSite`. Consequência deliberada e testada (test_admin.py): um
        # usuário `is_staff=True, is_superuser=False` perde o acesso que teria
        # com o `AdminSite` padrão do Django.
        return request.user.is_active and request.user.is_superuser

    def get_app_list(self, request, app_label=None):
        app_list = super().get_app_list(request, app_label)

        grupos = {}
        apps_restantes = []
        for app in app_list:
            modelos_restantes = []
            for modelo in app["models"]:
                model_admin = self._registry.get(modelo["model"])
                rotulo = getattr(model_admin, "admin_grupo", None)
                if rotulo:
                    bloco = grupos.setdefault(
                        rotulo,
                        {
                            "name": rotulo,
                            "app_label": _slug_ascii(rotulo),
                            "app_url": None,
                            "has_module_perms": True,
                            "models": [],
                        },
                    )
                    bloco["models"].append(modelo)
                else:
                    modelos_restantes.append(modelo)
            if modelos_restantes:
                app["models"] = modelos_restantes
                apps_restantes.append(app)

        blocos_ordenados = [
            grupos[nome] for nome in ORDEM_GRUPOS_ADMIN if nome in grupos
        ]

        # Bloco sintético fora de `_registry` (sem
        # ModelAdmin nenhum por trás): dois links diretos para as views de
        # exportar/importar o banco inteiro em XLSX. Aparece para todo
        # usuário que chega ao índice porque `has_permission` já
        # restringe o índice inteiro a superuser.
        bloco_banco = {
            "name": "Banco de dados",
            "app_label": "banco-de-dados",
            "app_url": None,
            "has_module_perms": True,
            "models": [
                {
                    "name": "Exportar banco (XLSX)",
                    "object_name": "BancoExportar",
                    "admin_url": reverse("admin:banco_exportar"),
                    "add_url": None,
                    "view_only": True,
                },
                {
                    "name": "Importar banco (XLSX)",
                    "object_name": "BancoImportar",
                    "admin_url": reverse("admin:banco_importar"),
                    "add_url": None,
                    "view_only": True,
                },
            ],
        }

        return blocos_ordenados + [bloco_banco] + apps_restantes


def _slug_ascii(rotulo):
    """Slug ascii estável para `app_label` do bloco sintético — usado só como
    identificador interno do índice (não vira rota nem tabela)."""

    substituicoes = str.maketrans("áàâãéêíóôõúçÁÀÂÃÉÊÍÓÔÕÚÇ", "aaaaeeioooucAAAAEEIOOOUC")
    ascii_puro = rotulo.translate(substituicoes)
    return "-".join(ascii_puro.lower().split())
