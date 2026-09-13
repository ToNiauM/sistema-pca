"""Fonte única de navegação do PCA: DESTINOS_OPERACIONAIS é a única lista
com os destinos operacionais (rótulo + nome de rota), consumida pelo menu.
trilha_padrao monta a trilha de breadcrumb das visões operacionais que não
são a raiz (a raiz é trilha de um único item, sem link)."""
from django.urls import reverse

# ordem fixa: Visão geral/Processos/Calendário/Resumo por unidade/
# Análises — a mesma ordem em que o menu e o usuário esperam encontrar as telas
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
    # 6º destino, após "Análises"
    {
        "chave": "relatorio_movimentacao",
        "rotulo": "Relatório de movimentação",
        "url_name": "pca:relatorio_movimentacao",
    },
)


def querystring_exercicio(exercicio):
    """exercicio=<ano> para o exercicio resolvido, ou string vazia quando
    não há exercício."""
    return f"exercicio={exercicio.ano}" if exercicio is not None else ""


def trilha_padrao(exercicio, rotulo_pagina):
    """Trilha de 2 itens (PCA <ano> -> tela atual) das visões operacionais
    que não são a raiz. O item ancestral "PCA <ano>" sempre carrega o
    exercício da página atual na sua própria querystring. Sem exercicio,
    devolve só o item da página atual."""
    if exercicio is None:
        return [{"rotulo": rotulo_pagina, "url": None}]
    qs = querystring_exercicio(exercicio)
    url_ancestral = f"{reverse('raiz')}?{qs}" if qs else reverse("raiz")
    return [
        {"rotulo": f"PCA {exercicio.ano}", "url": url_ancestral},
        {"rotulo": rotulo_pagina, "url": None},
    ]
