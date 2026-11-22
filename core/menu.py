"""Menu lateral do sistema (Fase 26).

Cada item: {"rotulo", "icone" (classe Font Awesome 5, ex. "fas fa-home"), "url" (caminho já resolvido),
"filhos" (lista de itens, opcional), "permissao" (opcional — um codename string, ex.
"diarias.view_diaria", OU uma tupla/lista de codenames quando o item exige TODAS as permissões
ao mesmo tempo, Fase 37, spec §7 — `_permitido()` abaixo documenta o contrato).
Um item com filhos vira um menu-folder; sem filhos, um menu-item direto.

Fonte dos itens: `apps.pca.navegacao` (import LOCAL, dentro de `itens()`, para não criar dependência
circular de import em nível de módulo entre `core` e `apps.pca`).
"""

from django.urls import reverse


_ICONES_DESTINOS_OPERACIONAIS = {
    "processos": "fas fa-list",
    "calendario": "fas fa-calendar-alt",
    "resumo_uo": "fas fa-building",
    "analise": "fas fa-chart-bar",
    # Fase 27 — última entrada, ordem do dict
    # determina a ordem no menu (itens() itera .items()).
    "relatorio_movimentacao": "fas fa-file-alt",
}

# Acompanhamento/prazo: calendário e relatório de
# movimentação somem do menu para quem não tem `pca.view_acompanhamento`
# (`_permitido()` já filtra pelo `has_perm`, sem mudança ali).
_DESTINOS_RESTRITOS_ACOMPANHAMENTO = {"calendario", "relatorio_movimentacao"}


def itens(request):
    usuario = request.user
    # Import local — evita ciclo de import em nível de módulo entre core e apps.pca.
    from apps.pca import navegacao

    mapa_destinos = {d["chave"]: d for d in navegacao.DESTINOS_OPERACIONAIS}

    todos = [{"rotulo": "Início", "icone": "fas fa-home", "url": reverse("core:inicio")}]
    for chave, icone in _ICONES_DESTINOS_OPERACIONAIS.items():
        destino = mapa_destinos[chave]
        # Fase 36 — "Análises" vira menu-folder de 4
        # telas (`navegacao.SUBDESTINOS_ANALISE`), SEM "url" próprio (vira
        # pasta, não link); `_permitido()` filtra `filhos` recursivamente
        # e remove a pasta inteira se ficar vazia — nenhuma lógica de
        # permissão nova aqui, só declarar "permissao" no filho "prazos".
        if chave == "analise":
            filhos = [
                {
                    "rotulo": sub["rotulo"],
                    "url": reverse(sub["url_name"]),
                    **({"permissao": sub["permissao"]} if sub.get("permissao") else {}),
                }
                for sub in navegacao.SUBDESTINOS_ANALISE
            ]
            todos.append({"rotulo": destino["rotulo"], "icone": icone, "filhos": filhos})
            continue
        item = {"rotulo": destino["rotulo"], "icone": icone, "url": reverse(destino["url_name"])}
        if chave in _DESTINOS_RESTRITOS_ACOMPANHAMENTO:
            item["permissao"] = "pca.view_acompanhamento"
        todos.append(item)
    # Fase 39 — "Assistente" entra logo após o laço
    # acima e antes de "Reuniões"; só com IA_API_KEY configurada (usuário
    # já está autenticado nesta função, `LoginRequiredMiddleware` garante).
    destino_assistente = navegacao.destino_assistente()
    if destino_assistente is not None:
        todos.append({
            "rotulo": destino_assistente["rotulo"],
            # Robô (DSGov) / brilhos (Tabler, via mapa de ícones): o símbolo de IA, sem confusão com "mensagens".
            "icone": "fas fa-robot",
            "url": reverse(destino_assistente["url_name"]),
        })
    # Fase 43 — grupo "Solicitações": cada pessoa vê só o que o perfil dela usa.
    pasta_solicitacoes = _pasta_solicitacoes(usuario)
    if pasta_solicitacoes is not None:
        todos.append(pasta_solicitacoes)
    # Fase 26 — listagem própria, não mais o
    # formulário de criação direto.
    todos.append({
        "rotulo": "Reuniões",
        "icone": "fas fa-users",
        "url": reverse("pca:reuniao_listagem"),
        "permissao": "pca.view_acompanhamento",
    })
    todos.append({
        "rotulo": "Gerenciar exercícios",
        "icone": "fas fa-calendar-check",
        "url": reverse("pca:gerenciar_exercicios"),
        "permissao": "pca.gerir_exercicio",
        "divisor": True,
    })
    # Mesma área alcançável pelo dropdown do avatar; no menu
    # lateral fica ao alcance do polegar no celular.
    todos.append({"rotulo": "Meu perfil", "icone": "fas fa-user", "url": reverse("core:perfil")})
    todos.append({"rotulo": "Sobre o sistema", "icone": "fas fa-info-circle", "url": reverse("core:sobre")})
    if usuario.is_staff:
        todos.append({"rotulo": "Administração", "icone": "fas fa-cog", "url": "/admin/", "divisor": True})
    return [i for i in todos if _permitido(usuario, i)]


def _pasta_solicitacoes(usuario):
    """Fase 43 — menu-folder "Solicitações". Quem pede (grupo `solicitante`) vê "Nova
    solicitação" e "Minhas solicitações"; equipe do PCA e diretoria veem "Todas as solicitações" e a
    fila "Para avaliar", esta com o contador de partes pendentes da alçada de cada um (no próprio
    rótulo: o menu do padrão DSGov só desenha texto). `None` para quem não tem nada disso (ex.:
    visualizador). Import local pelo mesmo motivo de `itens()`."""
    from apps.solicitacoes import services

    alcadas = services.alcadas_do_usuario(usuario)
    pede = usuario.has_perm(services.PERM_SOLICITAR)
    filhos = []
    if pede:
        filhos.append({"rotulo": "Nova solicitação", "url": reverse("solicitacoes:nova")})
    if alcadas:
        filhos.append({"rotulo": "Todas as solicitações", "url": reverse("solicitacoes:minhas")})
        pendentes = services.contar_pendentes(usuario)
        rotulo = f"Para avaliar ({pendentes})" if pendentes else "Para avaliar"
        filhos.append({"rotulo": rotulo, "url": reverse("solicitacoes:avaliar")})
    elif pede:
        filhos.append({"rotulo": "Minhas solicitações", "url": reverse("solicitacoes:minhas")})
    if not filhos:
        return None
    return {"rotulo": "Solicitações", "icone": "fas fa-inbox", "filhos": filhos}


def _permitido(usuario, item):
    """Fase 37 (spec §7) — `item["permissao"]` aceita string
    (comportamento de sempre, `has_perm(perm)`) OU tupla/lista de
    codenames (`all(usuario.has_perm(p) for p in perm)`, TODAS exigidas —
    ex. "prazos" em `navegacao.SUBDESTINOS_ANALISE`, que exige
    `ver_analises` E `view_acompanhamento`); ausência de `permissao`
    continua liberando o item, sem mudança."""
    perm = item.get("permissao")
    if perm:
        if isinstance(perm, (tuple, list)):
            if not all(usuario.has_perm(p) for p in perm):
                return False
        elif not usuario.has_perm(perm):
            return False
    if item.get("filhos"):
        item["filhos"] = [f for f in item["filhos"] if _permitido(usuario, f)]
        return bool(item["filhos"])
    return True
