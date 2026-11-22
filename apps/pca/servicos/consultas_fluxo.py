"""Fase 39 (spec `2026-09-19-assistente-ia-
design.md` §6) — leitura OFICIAL do fluxo de caixa compartilhada entre as
telas de `apps/pca/views_analise.py` (Fases 36/37) e o assistente do PCA
(app `apps/assistente/`). Nenhuma leitura de rascunho de sessão nem de
cenário salvo pelo usuário — os quatro helpers movidos aqui
(`itens_para_projecao`/`contratos_do_processo`/`indices_do_ano`/
`parametros_oficiais`) fazem EXATAMENTE o que faziam como `_itens_
para_projecao`/`_contratos_do_processo`/`_indices_do_ano`/`_parametros` em
`views_analise.py` — só o nome mudou (sem prefixo `_`, sem objeto de
requisição HTTP), para que `views_analise.py` continue chamando-os por
wrappers de uma linha, byte a byte na lógica.

`projecao_oficial`/`memoria_oficial` são as duas funções de conveniência
que o assistente consome (do plano): partem sempre do MESMO
recorte de `Processo.objects.para_listagem()` filtrado só por exercício
(e, opcionalmente, unidade organizacional) — nunca os filtros de busca/
situação/tipo da tela de Processos (o assistente não tem "filtros
ativos" de página) — e nunca leem nada persistido pelo usuário além do
banco principal do PCA."""

from __future__ import annotations

from datetime import date

from django.conf import settings
from django.db.models import Prefetch
from django.utils.timezone import localdate

from apps.catalogo.models import IndiceReajuste
from apps.pca.models import Processo
from apps.pca.projecao import CENARIOS, Parametros
from apps.pca.projecao import fluxo as fluxo_mod

# 01 (allowlist fechada) — movida de `views_analise.py` para este
# módulo ("sem duplicar"); `views_analise.py` reimporta o mesmo
# nome, sem repetir a tupla.
INDICES_VALIDOS = ("IPCA", "INPC", "IGP-M", "META_BC")


def itens_para_projecao(qs):
    """`itens: list[dict]` no contrato de `apps.pca.projecao` (spec §3.1) —
    UMA consulta (`select_related` + `prefetch_related` de
    `eventos_financeiros`). Chaves extras (`modalidade`, `razao_social`,
    marcos de prazo, `n_prorrogacoes`, `_processo`) alimentam
    `estatistica.py`/`prazos.py` e o enriquecimento de tela em
    `analise_prazos_view` (`_processo`: o objeto ORM, para UO/fornecedor/
    link sem 2ª consulta — nunca lido pelos módulos puros, que só fazem
    `.get(chave)`). Movida byte a byte de `views_analise.py::
    _itens_para_projecao` (Fases 36/37)."""
    processos = qs.select_related(
        "modalidade", "unidade_organizacional"
    ).prefetch_related(Prefetch("eventos_financeiros"))
    itens = []
    for p in processos:
        eventos = [
            {
                "data": e.data,
                "natureza": e.natureza,
                "valor": e.valor,
                "valor_mensal": e.valor_mensal,
                "periodicidade": e.periodicidade,
            }
            for e in p.eventos_financeiros.all()
        ]
        itens.append(
            {
                "item_pca": p.item_pca,
                "uo": p.unidade_organizacional_id,
                "estado": p.estado,
                "situacao": p.situacao,
                "valor_estimado": p.valor_estimado,
                "valor_contratado": p.valor_contratado,
                "valor_mensal": p.valor_mensal,
                "vigencia_inicio": p.vigencia_inicio,
                "vigencia_fim": p.vigencia_fim,
                "data_assinatura_contrato": p.data_assinatura_contrato,
                "regime_execucao": p.regime_execucao,
                "renovacao_prevista": p.renovacao_prevista,
                "mes_previsto": p.mes_previsto,
                "prazo_efetivo": p.prazo_efetivo,
                "eventos": eventos,
                "contratos": contratos_do_processo(p),
                "modalidade": p.modalidade.nome if p.modalidade_id else None,
                "razao_social": p.fornecedor_razao_social,
                "data_envio_gelic": p.data_envio_gelic,
                "data_recebimento_gelic": p.data_recebimento_gelic,
                "data_prevista_conclusao": p.data_prevista_conclusao,
                "n_prorrogacoes": p.n_prorrogacoes,
                "_processo": p,
            }
        )
    return itens


def contratos_do_processo(p):
    """`item["contratos"]` (spec §2.1) do fluxo de caixa: **um contrato por item, o do PCA** — vigência,
    assinatura e valor vêm do `Processo` (o número oficial consolidado, que o aplicador do robô mantém).

    Correção de 2026-09-23 (duplicação no fluxo): os `EventoFinanceiro` que o robô grava vêm agrupados pelo
    número do instrumento no SEI e, antes, cada grupo virava um contrato INDEPENDENTE ao lado deste. O
    grupo com o número do próprio contrato do PCA É este contrato: 78 itens eram contados duas vezes (a
    projeção 2026–2031 saía com R$ 495,8 mi em vez de R$ 216,6 mi). Os demais grupos também não são
    contratos à parte na prática (contrato anterior já substituído, lotes cujo total é o valor do PCA, o
    mesmo contrato registrado pelo protocolo) — decisão do usuário: o fluxo usa só o contrato do PCA.
    A série de eventos NÃO entra aqui: o motor tira dela o valor vigente mês a mês, e o valor do PCA pode
    ser a soma de vários instrumentos (item 39: R$ 110,5 mil = 09/2023 + 10/2023) — uma série parcial
    rebaixaria o valor. É o mesmo contrato "principal" que o fluxo sempre projetou, agora sozinho."""
    return [
        {
            "instrumento": "principal",
            "vigencia_inicio": p.vigencia_inicio,
            "vigencia_fim": p.vigencia_fim,
            "data_assinatura": p.data_assinatura_contrato,
            "numero_sei": p.numero_instrumento_contratual,
            "protocolo_sei": None,
            "data_base": None,
            "periodicidade": "mensal" if p.valor_mensal is not None else "global",
            "valor": p.valor_mensal if p.valor_mensal is not None else p.valor_contratado,
            "eventos": [],
        }
    ]


def indices_do_ano(indice):
    """`{ano: Decimal percentual}` do catálogo `IndiceReajuste` — o `dict`
    que `Parametros.indices` espera (spec §3.1); ano sem linha cai no
    último ano conhecido dentro do próprio `fluxo.py`. Movida
    byte a byte de `views_analise.py::_indices_do_ano`."""
    return dict(
        IndiceReajuste.objects.filter(indice=indice).values_list("ano", "percentual")
    )


def parametros_oficiais(exercicio, cenario, indice, hoje):
    """Movida byte a byte de `views_analise.py::_parametros`."""
    horizonte_inicio = hoje.replace(day=1)
    horizonte_fim = date(exercicio.ano + 5, 12, 31)
    return Parametros(
        horizonte_inicio=horizonte_inicio,
        horizonte_fim=horizonte_fim,
        exercicio=exercicio.ano,
        indices=indices_do_ano(indice),
        cenario=cenario,
        indice_nome=indice,
    )


def projecao_oficial(exercicio, *, uo_id=None, cenario="base", indice=None, hoje=None):
    """Ponto de entrada do assistente (do plano) — projeção
    SEMPRE oficial: nunca lê nada além do exercício/unidade recebidos como
    parâmetro. `qs` parte de `Processo.objects.para_listagem().filter
    (exercicio=exercicio)` — a MESMA base usada pela tela de Processos,
    sem os filtros de busca/situação/tipo da querystring (o assistente não
    tem "filtros ativos" de página). `cenario` fora de `CENARIOS` cai em
    `"base"`; `indice` vazio ou fora de `INDICES_VALIDOS` cai no padrão do
    sistema (`settings.PCA_INDICE_REAJUSTE_PADRAO`). Devolve
    `(Projecao, itens)` — `itens` para quem precisa dos nomes/objetos por
    item sem uma segunda consulta."""
    hoje = hoje or localdate()
    cenario = cenario if cenario in CENARIOS else "base"
    indice = indice or settings.PCA_INDICE_REAJUSTE_PADRAO
    indice = indice if indice in INDICES_VALIDOS else settings.PCA_INDICE_REAJUSTE_PADRAO

    qs = Processo.objects.para_listagem().filter(exercicio=exercicio)
    if uo_id:
        qs = qs.filter(unidade_organizacional_id=uo_id)

    itens = itens_para_projecao(qs)
    parametros = parametros_oficiais(exercicio, cenario, indice, hoje)
    projecao = fluxo_mod.projetar(itens, parametros)
    return projecao, itens


def memoria_oficial(exercicio, item_pca, *, cenario="base", indice=None, hoje=None):
    """Memória de cálculo OFICIAL de UM item — exatamente o que
    `views_analise.py::analise_fluxo_memoria_view` monta no ramo
    `sim == "oficial"`, até `projecao.memorias.get(item_pca)`. `None` só
    quando o item existe mas a projeção não gerou memória para ele (sem
    dado no horizonte); item inexistente também devolve `None` — quem
    distingue os dois casos é a camada acima (o assistente confere
    existência antes de chamar esta função)."""
    hoje = hoje or localdate()
    cenario = cenario if cenario in CENARIOS else "base"
    indice = indice or settings.PCA_INDICE_REAJUSTE_PADRAO
    indice = indice if indice in INDICES_VALIDOS else settings.PCA_INDICE_REAJUSTE_PADRAO

    processo = (
        Processo.objects.para_listagem()
        .filter(exercicio=exercicio, item_pca=item_pca)
        .first()
    )
    if processo is None:
        return None

    parametros = parametros_oficiais(exercicio, cenario, indice, hoje)
    itens = itens_para_projecao(
        Processo.objects.para_listagem().filter(pk=processo.pk)
    )
    projecao = fluxo_mod.projetar(itens, parametros)
    return projecao.memorias.get(item_pca)
