"""Fonte única de navegação do PCA CFC (Fase 25).

Corrige A02/A03 (menu e rodapé com destinos/rótulos divergentes) e A04/A18
(trilha de breadcrumb que descarta o exercício ao voltar/trocar de visão):
antes deste módulo, cada view montava sua própria lista de trilha inline
com `reverse("raiz")` SEM querystring, e `_nav_visoes.html`/o rodapé de
`shell.html` hardcodavam os 5 destinos com rótulos independentes que já
haviam divergido entre si (`_nav_visoes.html` dizia "Dashboard"/"Tabela", o
rodapé só tinha 4 dos 5 destinos).

`DESTINOS_OPERACIONAIS` é a única lista com os 5 destinos operacionais
(rótulo + nome de rota) — consumida por `core/menu.py::itens()` (Fase 26). `trilha_padrao` é a função que monta a trilha de breadcrumb (lista
de tuplas `(rótulo, url|None)` — o contrato de `dsgov/_breadcrumb.html`,
congelado pelo padrão DSGov, que faz `{% for rotulo, url in trilha %}`) das visões
operacionais que NÃO são a raiz (a raiz é trilha de um único item,
sem link, e não passa por aqui).

Fase 26 — `destinos_com_href`/`cards_com_href`/`DESTINO_INICIO`/
`CARDS_INICIO` saíram: existiam só para `_nav_visoes.html`/`_rodape_visoes.
html` (menu/rodapé da casca legada) e os cards "Acesse o PCA" da antiga
Início (Fase 25) — nenhum dos três sobrevive à casca do padrão DSGov
(`core/menu.py`/`dsgov/_menu.html`; Início virou o dashboard). Zero consumidor de template/view confirmado por grep antes da
remoção.
"""
from django.urls import reverse

# Ordem fixa: Visão geral/Processos/Calendário/Resumo por unidade/
# Análises — a mesma ordem em que o menu, o rodapé e (indiretamente, via
# navegação sequencial) o usuário esperam encontrar as 5 telas.
DESTINOS_OPERACIONAIS = (
    {"chave": "visao_geral", "rotulo": "Visão geral", "url_name": "raiz"},
    {"chave": "processos", "rotulo": "Processos", "url_name": "pca:tabela"},
    {"chave": "calendario", "rotulo": "Calendário", "url_name": "pca:calendario"},
    {
        "chave": "resumo_uo",
        "rotulo": "Resumo por unidade",
        "url_name": "pca:resumo_uo",
    },
    {"chave": "analise", "rotulo": "Análises", "url_name": "pca:analise"},
    # Fase 27 — 6º destino, após "Análises"; rótulo "Relatório da reunião" desde
    #(a chave e a URL continuam as mesmas).
    {
        "chave": "relatorio_movimentacao",
        "rotulo": "Relatório da reunião",
        "url_name": "pca:relatorio_movimentacao",
    },
)


# Fase 36 — Análises vira menu-folder de 4 telas;
# mesmo formato de DESTINOS_OPERACIONAIS mais "permissao" (opcional) —
# `core/menu.py::_permitido()` já filtra recursivamente pelos filhos e
# some com a pasta inteira se ficar vazia. Fase 37 (spec §7,
# estendido): "fluxo"/"estatisticas" passam a exigir
# `pca.ver_analises` (as 3 telas estratégicas ficam atrás da mesma
# permissão); "prazos" exige as DUAS (`ver_analises` E
# `view_acompanhamento`) — `permissao` aceita string OU tupla/lista de
# codenames (`core/menu.py::_permitido`, contrato estendido). "painel"
# (`pca:analise`) continua SEM `permissao` — Painel quantitativo sempre
# visível, mesmo para quem não tem `ver_analises`.
SUBDESTINOS_ANALISE = (
    {"chave": "painel", "rotulo": "Painel", "url_name": "pca:analise"},
    {
        "chave": "fluxo",
        "rotulo": "Fluxo de caixa",
        "url_name": "pca:analise_fluxo",
        "permissao": "pca.ver_analises",
    },
    {
        "chave": "estatisticas",
        "rotulo": "Estatísticas",
        "url_name": "pca:analise_estatisticas",
        "permissao": "pca.ver_analises",
    },
    {
        "chave": "prazos",
        "rotulo": "Prazos",
        "url_name": "pca:analise_prazos",
        "permissao": ("pca.ver_analises", "pca.view_acompanhamento"),
    },
)


# Fase 39 — item "Assistente", fora de
# `DESTINOS_OPERACIONAIS` (que continua com os 6 destinos operacionais de
# sempre; consumidores que contam esses 6 não são afetados). Só aparece
# com `settings.IA_API_KEY` preenchida — `core/menu.py::itens()` decide,
# este módulo só declara o destino.
DESTINO_ASSISTENTE = {"chave": "assistente", "rotulo": "Assistente de IA", "url_name": "assistente:pagina"}


def destino_assistente():
    from django.conf import settings

    if settings.IA_API_KEY:
        return DESTINO_ASSISTENTE
    return None


def querystring_exercicio(exercicio):
    """`exercicio=<ano>` para o `exercicio` resolvido, ou string vazia
    quando não há exercício (nunca lança, nunca produz `exercicio=None`)."""
    return f"exercicio={exercicio.ano}" if exercicio is not None else ""


def trilha_padrao(exercicio, rotulo_pagina):
    """Trilha de 2 itens (PCA <ano> → tela atual) das 4 visões
    operacionais que NÃO são a raiz (a raiz é trilha de um único
    item, sem link, e não passa por aqui).

    Devolve lista de tuplas `(rótulo, url|None)` — o contrato de
    `dsgov/_breadcrumb.html` (`{% for rotulo, url in trilha %}`), o mesmo
    formato que `resumo_uo_view`/`views_analise.py` já montam à mão.

    O item ancestral "PCA <ano>" SEMPRE carrega o exercício da página em
    que o usuário está (`exercicio`, já resolvido pelo servidor) na sua
    própria querystring — fecha A04 (clicar no ancestral não mais cai no
    exercício padrão do sistema) e A18 (a identidade anual nunca diverge
    entre trilha e o restante do chrome). Sem `exercicio` (nenhum exercício
    cadastrado), devolve só o item da página atual — nunca falha."""
    if exercicio is None:
        return [(rotulo_pagina, None)]
    qs = querystring_exercicio(exercicio)
    url_ancestral = f"{reverse('raiz')}?{qs}" if qs else reverse("raiz")
    return [
        (f"PCA {exercicio.ano}", url_ancestral),
        (rotulo_pagina, None),
    ]
