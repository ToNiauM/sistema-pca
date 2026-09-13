"""`PcaAdminSite` num módulo próprio, sem nenhum ModelAdmin registrado aqui.

A resolução de `admin.site` (LazyObject) é preguiçosa e não reentrante: se
`PcaAdminSite` vivesse dentro de `core/admin.py` — que também registra
`UsuarioAdmin` no mesmo import — o próprio import reentraria em
`admin.site` antes da resolução terminar, e a instância mais externa a
terminar sobrescreveria `_wrapped` com um `_registry` vazio, apagando os
registros já feitos. Isolar `PcaAdminSite` num módulo que não registra
nada elimina esse reentrant-setup.
"""

from django.conf import settings
from django.contrib import admin

# Ordem fixa dos blocos sintéticos do índice do admin. Qualquer ModelAdmin
# que declarar `admin_grupo = "<um destes rótulos>"` é realocado para o
# bloco correspondente por `PcaAdminSite.get_app_list`; os demais
# permanecem no agrupamento padrão por app do Django.
ORDEM_GRUPOS_ADMIN = [
    "Usuários e bloqueios de login",
    "Catálogos do PCA",
    "Importação da planilha",
    "Auditoria e histórico",
]


class PcaAdminSite(admin.AdminSite):
    """`AdminSite` próprio: gate por superuser e agrupamento pt-BR do índice
    via `admin_grupo` declarativo.

    Substitui `admin.site` globalmente através de `default_site` em
    `PcaAdminConfig` (core/apps.py) — `config/urls.py` não muda.
    """

    site_header = f"{settings.DSGOV['SISTEMA']} — Administração"
    site_title = settings.DSGOV["SISTEMA"]
    index_title = "Painel do administrador"

    def each_context(self, request):
        # Sobrescreve só os 3 tokens de cor do tema padrão do Django Admin
        # pelo azul do govbr-ds (#1351b4). O Admin roda fora do pipeline de
        # custom properties do app, então não há var(--cor-brand) aqui.
        contexto = super().each_context(request)
        contexto["admin_tema_css"] = (
            ":root { --primary: #1351b4; --header-bg: #1351b4; --link-fg: #1351b4; }"
        )
        return contexto

    def has_permission(self, request):
        # Gate explícito, mais restritivo que o `is_staff` padrão do
        # `AdminSite`: um usuário `is_staff=True, is_superuser=False` perde
        # o acesso que teria com o `AdminSite` padrão do Django.
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
        return blocos_ordenados + apps_restantes


def _slug_ascii(rotulo):
    """Slug ascii estável para `app_label` do bloco sintético — usado só como
    identificador interno do índice (não vira rota nem tabela)."""

    substituicoes = str.maketrans("áàâãéêíóôõúçÁÀÂÃÉÊÍÓÔÕÚÇ", "aaaaeeioooucAAAAEEIOOOUC")
    ascii_puro = rotulo.translate(substituicoes)
    return "-".join(ascii_puro.lower().split())
