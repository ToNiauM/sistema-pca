from calendar import Calendar
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import urlencode
import logging
import re

from django.conf import settings
from django.core.paginator import Paginator
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Case, Count, F, IntegerField, Prefetch, Q, Sum, Value, When
from django.db.models.functions import ExtractQuarter
from django.db import IntegrityError, transaction
from django.http import (
    Http404,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponsePermanentRedirect,
    HttpResponseRedirect,
    QueryDict,
)
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.contrib.auth.decorators import permission_required
from django_htmx.http import HttpResponseClientRedirect
from django.views.decorators.http import require_POST
from django.utils.timezone import localdate, localtime

from apps.catalogo.models import (
    Exercicio,
    SituacaoExercicio,
    Tipo,
)
from apps.pca.analise import (
    ROTULOS_DIMENSAO,
    calcular_grafico_mensal,
    calcular_grafico_vencimento_contratos,
    calcular_proximos_vencimentos,
)
from apps.pca.colunas import (
    COLUNAS_OBRIGATORIAS,
    COLUNAS_PADRAO,
    COLUNAS_POR_CHAVE,
    _filtrar_restritas,
    colunas_por_secao,
    colunas_selecionadas,
)
from apps.pca.exportacao import COLUNAS_POR_CHAVE as _COLUNAS_EXPORT_POR_CHAVE
from apps.pca.exportacao import exportar_csv, exportar_xlsx
from apps.pca.exportacao_resumo_uo import exportar_resumo_uo_xlsx
from apps.pca.filtros import (
    COLUNA_ORDENACAO_PADRAO,
    COLUNAS_ORDENACAO,
    MESES,
    NOMES_MES,
    ORDEM_CONDICOES_LEGENDA,
    PARAMETROS_FILTRO,
    SENTINEL_NAO_CLASSIFICADO,
    SENTINEL_SEM_MES,
    direcao_valida,
    filtros_ativos,
    opcoes_filtros,
    ordenacao_valida,
    querystring_filtros,
    querystring_tabela,
    queryset_filtrado,
    resolver_condicao_legenda,
    resolver_exercicio,
    tags_ativas,
    VISTA_LISTA,
    vista_valida,
)
from apps.pca import graficos_pca, navegacao
from apps.pca.forms_exercicio import ReuniaoForm, ViradaItemForm
from apps.pca.kpis import _percentual, calcular_blocos_kpi
from apps.pca.models import (
    Acompanhamento,
    Estado,
    Processo,
    ProcessoSEI,
    RascunhoItemVirada,
    RascunhoVirada,
    Reuniao,
    Situacao,
)
from apps.pca.relatorio_movimentacao import frase_compromisso
from apps.pca.resumo_uo import calcular_resumo_uo, ids_tipo_recorte
from apps.pca import services
from apps.pca.servicos import geracao_n1
from core import graficos
from core.db import quantizar_soma
from core.templatetags.dsgov import moeda, numero, percentual

logger = logging.getLogger(__name__)

# O mapa fechado de colunas de `?ordenar=` vive em filtros.py,
# ao lado de `ordenacao_valida()` que o valida. Havia uma segunda cópia aqui
# (removida): o template recebia esta lista enquanto o
# validador usava a de filtros.py, então qualquer divergência entre as duas
# renderizaria como link clicável uma coluna que o validador descarta em
# silêncio.

TAMANHO_PAGINA = 20
TAMANHO_VIRADA_PAGINA = 25

# Chave de sessão do estado canônico de `/tabela`
# (`querystring_tabela(request.GET)`), mesmo padrão de
# `apps.pca.colunas.CHAVE_SESSAO_COLUNAS` ("só grava se diferir").
CHAVE_SESSAO_ESTADO_TABELA = "pca_estado_tabela"

# Allowlist única da fronteira de confiança de edição do processo,
# consumida por `ProcessoForm`/`views_processo.py` (o formulário é a única
# edição desde; a superfície de clique por célula da tabela,
# `CAMPOS_EDITAVEIS_TABELA`/`editar_campo_view`, saiu na Fase 26/Plano
# 26-06 — as duas tuplas se fundiram numa só porque não há mais dois
# consumidores distintos). `estado`/`situacao` continuam fora — sempre por
# `pca:transicao_processo`; `data_envio_gelic` continua fora —
# campo congelado.
CAMPOS_EDITAVEIS_PROCESSO = (
    "grau_prioridade",
    "mes_previsto",
    "data_recebimento_gelic",
    # 10/11/2026 — `data_prevista_conclusao` saiu daqui: não é desenhada em nenhuma seção
    # de `SECOES_FORMULARIO_PROCESSO`, o navegador não a envia e o
    # `ModelForm` gravava vazio sobre a data vinda da importação. Fora da
    # edição, o valor gravado é preservado (teste-guarda nas duas cascas em
    # `test_edicao_formulario.py::TestCampoNaoDesenhadoNaoApaga*`).
    "valor_contratado",
    "descricao_objeto",
    "unidade_organizacional",
    "classificacao",
    "valor_estimado",
    "tipo",
    "data_inclusao_pca",
    "prazo_entrega",
    "justificativa",
    "categoria",
    # Fase 11 — `justificativa_alteracao_prazo` e
    # `justificativa_alteracao_email` saem da allowlist de edição: a
    # primeira passa a pertencer a cada promessa (`Acompanhamento.evento`), a segunda "sai de tudo" por decisão do usuário. Os campos
    # físicos permanecem no modelo até o plano rodar a migração de
    # dados segura — não há limpeza de banco nesta task.
    # Phase 4 — bloco de execução contratual
    "modalidade",
    "vigencia_inicio",
    "vigencia_fim",
    "numero_contratacao",
    "numero_arp",
    "instrumento_contratual",
    "numero_instrumento_contratual",
    "fornecedor_cnpj",
    "fornecedor_razao_social",
    "data_assinatura_contrato",
    "data_lancamento_spw",
    "data_lancamento_wordpress",
    "data_lancamento_dados_abertos",
    # Fase 36 — base do fluxo de caixa projetado.
    "regime_execucao",
    "renovacao_prevista",
    "valor_mensal",
)

# Fase 26 — `apps/pca/paleta.py` saiu (só
# `dashboard_view`, removida nesta mesma frente, o importava); a cor
# semântica da rosca de situação hoje vive em
# `apps.pca.graficos_pca.MAPA_SITUACAO_STATUS`/`core.graficos.CORES_STATUS`.
#
# Fase 17 — "Distribuição por status" (aqui,
# `ORDEM_ROSCA`, ainda usada por `resumo_uo_view`/`calendario_view`) lê
# estado/situacao_efetiva (nunca mais a coluna crua `status`): 5 fatias —
# Cancelados (eixo Estado) + as 4 situações dos ativos (eixo Situação,
# sobre a annotation CORRIGIDA). Cada tupla é (eixo, valor,
# rótulo); `valor` é o membro do TextChoices.
ORDEM_ROSCA = (
    ("estado", Estado.CANCELADO, "Cancelado"),
    ("situacao", Situacao.CONCLUIDO, "Concluído"),
    ("situacao", Situacao.NO_PRAZO, "No prazo"),
    ("situacao", Situacao.EM_TRAMITACAO, "Em tramitação"),
    ("situacao", Situacao.ATRASADO, "Atrasado"),
)

# Cores dos pontos de situação do calendário
# (`telas/calendario.md`, regra literal: "bg-success concluído/no prazo,
# bg-info em tramitação, bg-danger atrasado, bg-gray-40 cancelado"), na
# MESMA ordem/chave `(eixo, valor)` de `ORDEM_ROSCA` — montado por `zip`,
# nunca hardcoded linha a linha.,
# achado de revisão nas capturas) — "No prazo" saiu de `bg-success` (MESMA cor de
# Concluído) para `bg-warning text-gray-80`: mesmo destino de "pendente"
# em `core.templatetags.dsgov.classe_status`/`apps.pca.templatetags.
# pca_listagem.CLASSE_SITUACAO_EFETIVA` — mapa projeto-inteiro, nenhuma
# condição compartilha cor com outra (nem mais "No prazo"/"Concluído").
_CLASSES_CALENDARIO_POR_ORDEM = (
    "bg-gray-40",  # Cancelado
    "bg-success",  # Concluído
    "bg-warning text-gray-80",  # No prazo
    "bg-info",  # Em tramitação
    "bg-danger",  # Atrasado
)
CLASSE_CONDICAO_CALENDARIO = {
    (eixo, valor.value if hasattr(valor, "value") else valor): classe
    for (eixo, valor, _rotulo), classe in zip(ORDEM_ROSCA, _CLASSES_CALENDARIO_POR_ORDEM)
}
ROTULO_CONDICAO_CALENDARIO = {
    (eixo, valor.value if hasattr(valor, "value") else valor): rotulo
    for eixo, valor, rotulo in ORDEM_ROSCA
}

# Fase 17 — `ORDEM_FUNIL` (a ordem de 6 valores de
# `Status`, usada pela extinta barra de progresso segmentada da Fase 16)
# removida: zero consumidor no módulo (confirmado por grep isolado antes de
# remover, mesmo padrão de diligência já usado pelo plano abaixo para
# as constantes STATUS_*_FUNIL). já tinha substituído a barra pelos
# Blocos A/B/C; esta constante só não tinha sido varrida ainda.

# Fase 17 — STATUS_ATIVOS_FUNIL/STATUS_CONTRATOS_
# VIGENTES_FUNIL/STATUS_CONTRATACOES_EXERCICIO_FUNIL/STATUS_A_CONCLUIR_FUNIL
# (da Fase 16) removidas: existiam só para os overrides de lista
# do dict `funil`, que substitui integralmente pelos Blocos A/B/C
# (apps/pca/kpis.py). Zero outro consumidor no módulo (confirmado por grep
# isolado antes de remover).

# (13-06) — ordem de SEVERIDADE intrínseca do "Perfil da carteira" no
# dashboard, usada só para o grupo "prioridade". Os demais grupos
# (categoria/classificação/modalidade/tipo) continuam ordenados por
# contagem (-total, nome): não têm nível intrínseco, só frequência.
# Prioridade tem — "Alto" precisa ser sempre o degrau mais escuro da rampa
# monocrômica (token_sequencial), nunca uma função de quantos processos
# caíram nela. Valores reais confirmados no banco via
# `GrauPrioridade.objects.values_list("nome", flat=True)`: "Alto"/"Médio"/
# "Baixo" (não "Alta"/"Média"/"Baixa", como o texto do plano especulava).
ORDEM_PRIORIDADE = {"Alto": 0, "Médio": 1, "Baixo": 2}

# Fase 17 — a antiga constante de bloqueio de
# "vigente" e sua mensagem de erro associada (Fase 15) foram
# removidas por inteiro: a razão de existir delas desapareceu com o modelo
# de 3 eixos. `vigente` era bloqueado como status alcançável só por
# automação com saídas restritas; agora "Vigente" é o eixo Tipo (intocado,
# sempre existiu como FK) e a situação correspondente é CONCLUÍDO por
# natureza — um valor comum do eixo Situação como qualquer outro,
# sem tratamento especial no modal.
#
# Fase 26 — `MENSAGEM_TRANSICAO_INVALIDA`/
# `MENSAGEM_TRANSICAO_NAO_REGISTRADA`/`MENSAGEM_DATA_INVALIDA` saíram junto
# com `confirmar_transicao_view` (o modal universal): `TransicaoForm`
# (`views_processo.py`) valida o destino com `ChoiceField`/`form.add_error`,
# mensagens do próprio Django forms, não destas constantes.

# Fase 28 — o antigo mapa `(chave, rótulo)` e
# o antigo conjunto de chaves-padrão (Fase 25) foram
# removidos por inteiro: o registro único agora vive em `apps.pca.colunas`
# (`COLUNAS`/`COLUNAS_PADRAO`), compartilhado com a exportação a partir do.
# Nenhum consumidor deste módulo referencia mais os nomes
# antigos.


def _cabecalhos_ordenaveis(campo_atual, direcao_atual, colunas_resolvidas):
    """Resolve, no servidor, tudo que o cabeçalho da tabela precisa saber
    para ordenar (§Screen Contracts 3, quick): se a coluna é ordenável, se é a ativa, qual direção o
    próximo clique deve pedir, e o par seta/aria-sort.

    Fica aqui e não no template porque "inverter o sentido só na coluna já
    ativa" é regra, não apresentação — e regra em template não tem teste
    unitário barato.

    Fase 28 — itera `colunas_resolvidas` (lista de chaves
    resolvida por `apps.pca.colunas.colunas_selecionadas`), não mais o
    registro antigo inteiro: a ORDEM da lista recebida é a
    ordem de exibição das colunas, rótulo/tipo resolvidos via
    `apps.pca.colunas.COLUNAS_POR_CHAVE`. A regra de ordenável/ativa/
    próxima-direção/aria-sort/seta é IDÊNTICA à versão anterior — só a
    fonte da lista de colunas mudou.
    """
    cabecalhos = []
    for chave in colunas_resolvidas:
        coluna = COLUNAS_POR_CHAVE.get(chave)
        if coluna is None:
            continue
        ordenavel = chave in COLUNAS_ORDENACAO
        ativa = ordenavel and chave == campo_atual
        cabecalhos.append(
            {
                "chave": chave,
                "rotulo": coluna.rotulo,
                "tipo": coluna.tipo,
                # `campo` propagado para o filtro genérico `exibir`/
                # `atributo` de `core/templatetags/dsgov.py` — usado por
                # `_tabela_linha.html` via `{{ p|exibir:col }}`.
                "campo": coluna.campo,
                "ordenavel": ordenavel,
                "ativa": ativa,
                # Coluna já ativa inverte; coluna nova sempre começa
                # ascendente (o que o usuário espera do primeiro clique).
                "proxima_direcao": (
                    "desc" if ativa and direcao_atual == "asc" else "asc"
                ),
                "aria_sort": (
                    ("ascending" if direcao_atual == "asc" else "descending")
                    if ativa
                    else None
                ),
                "seta": (
                    ("▲" if direcao_atual == "asc" else "▼") if ativa else None
                ),
            }
        )
    return tuple(cabecalhos)



def _hrefs_resumo_uo(get, ids_tipo, uo_id):
    """Um href de drill-down por família de recorte da
    tabela `/resumo-uo` (mapeamento fino no docstring de `calcular_resumo_uo`,
    `apps/pca/resumo_uo.py`), mesmo padrão de `querystring_filtros(get,
    **overrides)` que `apps.pca.kpis.calcular_blocos_kpi::card()` já usa para
    os 12 cards de KPI. `uo_id=None` (linha TOTAL) limpa o filtro de UO —
    `uo` é chave multivalor (`CHAVES_MULTIVALOR`), então um override `None`
    vira lista vazia (sem tratamento especial).

    Bloco META: hrefs `meta`/`concluido_meta`/`no_prazo`/
    `fora_prazo` recortam ATIVO & tipo in (Nova, Renovação) — os prazos são
    CONSOLIDADOS (NC+RN juntos); os 4 hrefs por tipo de prazo saíram junto
    com as colunas. `concluido` (c/ Vigentes, bloco ANÁLISE) fica intacto."""
    ativo = Estado.ATIVO.value
    id_nova = ids_tipo.get("nova contratacao")
    id_renovacao = ids_tipo.get("renovacao")
    id_vigente = ids_tipo.get("vigente")

    href_uo = querystring_filtros(get, uo=uo_id)

    return {
        "uo": href_uo,
        # "Total previsto" inclui ATIVO + CANCELADO: SEM `estado`.
        "total_previsto": href_uo,
        # "Cancelados"/"Ativos" ganham drill-down próprio.
        "cancelados": querystring_filtros(
            get, uo=uo_id, estado=[Estado.CANCELADO.value]
        ),
        "ativos": querystring_filtros(get, uo=uo_id, estado=[ativo]),
        "nova": querystring_filtros(get, uo=uo_id, estado=[ativo], tipo=[id_nova]),
        "renovacao": querystring_filtros(
            get, uo=uo_id, estado=[ativo], tipo=[id_renovacao]
        ),
        "vigente": querystring_filtros(
            get, uo=uo_id, estado=[ativo], tipo=[id_vigente]
        ),
        # Bloco META: Meta = ATIVO & (Nova|Renovação);
        # as 4 colunas que a decompõem acrescentam só a `situacao`.
        "meta": querystring_filtros(
            get, uo=uo_id, estado=[ativo], tipo=[id_nova, id_renovacao]
        ),
        "concluido_meta": querystring_filtros(
            get,
            uo=uo_id,
            estado=[ativo],
            tipo=[id_nova, id_renovacao],
            situacao=[Situacao.CONCLUIDO],
        ),
        "em_tramitacao": querystring_filtros(
            get,
            uo=uo_id,
            estado=[ativo],
            tipo=[id_nova, id_renovacao],
            situacao=[Situacao.EM_TRAMITACAO],
        ),
        "no_prazo": querystring_filtros(
            get,
            uo=uo_id,
            estado=[ativo],
            tipo=[id_nova, id_renovacao],
            situacao=[Situacao.NO_PRAZO],
        ),
        "fora_prazo": querystring_filtros(
            get,
            uo=uo_id,
            estado=[ativo],
            tipo=[id_nova, id_renovacao],
            situacao=[Situacao.ATRASADO],
        ),
        # Bloco ANÁLISE — "Concluído c/ Vigentes": sem recorte de tipo.
        "concluido": querystring_filtros(
            get, uo=uo_id, estado=[ativo], situacao=[Situacao.CONCLUIDO]
        ),
    }


def resumo_uo_view(request):
    """Fase 17.1 — tela "Resumo por UO", semântica de
    FOTO ATUAL: reproduz, no que a foto atual permite, a planilha
    `Percentual_execucao_UO_27_07_26_.xlsx` que a equipe já usa na reunião
    mensal. Consome o MESMO `queryset_filtrado` de `/`/`/tabela`: os
    números daqui nunca divergem dos de qualquer outra tela para o mesmo
    filtro — toda a regra de negócio vive em `apps.pca.resumo_uo`, nunca
    reimplementada aqui.

    Sem `@permission_required` — mesmo padrão de leitura de
    `dashboard_view`/`exportar_xlsx_view`, protegido só pelo
    `LoginRequiredMiddleware` global.
    """
    get = request.GET
    qs = queryset_filtrado(request)
    linhas, total = calcular_resumo_uo(qs)
    ids_tipo = ids_tipo_recorte()
    for linha in linhas:
        linha["hrefs"] = _hrefs_resumo_uo(get, ids_tipo, linha["uo_id"])
    total["hrefs"] = _hrefs_resumo_uo(get, ids_tipo, None)
    exercicio = filtros_ativos(get)["exercicio"]
    # `_tags_filtros.html` (agora incluído aqui, herdado de
    # /tabela) lê `total_geral` incondicionalmente; sem esta chave o
    # contador "de N processos" renderizaria em branco. Mesma consulta de
    # `tabela_view`/`dashboard_view`, zero query nova além do orçamento já
    # pago por elas (cada view paga a sua).
    total_geral = Processo.objects.filter(exercicio=exercicio).count()
    contexto = {
        "linhas": linhas,
        "total": total,
        # 29/09/2026 — roscas do topo, mesmo padrão do dashboard.
        "graficos": graficos_pca.graficos_resumo_uo(total) if linhas else [],
        "exercicio": exercicio,
        "querystring_filtros": querystring_filtros(get),
        "total_filtrado": total["total_previsto"],
        "total_geral": total_geral,
        # Fase 26 — relatório puro (`telas/relatorio.md`):
        # sem painel de filtros global, sem HTMX/OOB. `trilha` em tuplas
        # (rótulo, url) — contrato de `base.html`/`dsgov/_breadcrumb.html`;
        # `navegacao.trilha_padrao` já devolve o mesmo
        # formato, mas esta tela tem 1 item só (sem ancestral "PCA <ano>"),
        # por isso segue montada à mão em vez de chamar a função.
        "trilha": [("Resumo por unidade", None)],
        "nome_tela": "Resumo por unidade",
    }
    resposta = render(request, "pca/resumo_uo.html", contexto)
    # Pitfall 16 — nunca cacheável na borda; o filtro é por sessão
    # autenticada, não público.
    resposta["Cache-Control"] = "private, no-store"
    return resposta


# Fase 26 — as 3 medidas da tabela "mês × dimensão"
# (a MESMA chave usada por `apps.pca.analise.calcular_grafico_mensal`, que
# devolve as 3 prontas por ponto: nunca uma 4ª calculada aqui).
MEDIDAS_ANALISE = (
    ("quantidade", "Quantidade"),
    ("valor_previsto", "Valor previsto"),
    ("valor_contratado", "Valor contratado"),
)

# Fase 28 (01) — allowlist FECHADA de
# `?perfil_dimensao=` (separado de `?dimensao=`, que continua sendo só da
# distribuição mensal). Qualquer valor fora desta allowlist cai no padrão
# "categoria" em `analise_view`, nunca alcança um `.values()`/`.annotate()`
# com nome de campo não confiável.
ROTULOS_PERFIL = {
    "categoria": "Categoria",
    "prioridade": "Prioridade",
    "classificacao": "Estratégica",
    "modalidade": "Modalidade",
    "tipo": "Orçamento por tipo",
}

# Fase 28 — allowlist FECHADA de `?vencimentos=`;
# qualquer outro valor cai em 10 (padrão), nunca alcança `[:limite]` com um
# inteiro não confiável.
VENCIMENTOS_OPCOES = (10, 20)
VENCIMENTOS_PADRAO = 10


def analise_view(request):
    """Fase 24; reescrita na Fase 26 — Análises deixa de ter gráficos com seletor em JS e vira
    relatório (`telas/relatorio.md`): `dl.dsgov-detalhe` com os 9 números
    de `calcular_blocos_kpi` que não viraram KPI no dashboard +
    valores planejado/contratado, e `br-table`s sem busca/paginação
    (situação, unidade, mês×previsto/entregue, mês×dimensão escolhida,
    adiamentos, vencimentos, Perfil). `apps.pca.analise`/`apps.pca.kpis`
    (intocados) seguem sendo a fonte única dos números; `apps.pca.
    graficos_pca` é a mesma ponte de agregação que `core.views.
    inicio` usa para situação/unidade/previsto-entregue — os números das
    duas telas nunca divergem para o mesmo filtro (Pitfall 16).

    Sem `@permission_required` — mesmo padrão de leitura de
    `dashboard_view`/`resumo_uo_view`, protegido só pelo
    `LoginRequiredMiddleware` global.
    """
    get = request.GET
    qs = queryset_filtrado(request)
    exercicio = filtros_ativos(get)["exercicio"]
    total_geral = Processo.objects.filter(exercicio=exercicio).count()
    # quantizar_soma corrige o ruido de ponto flutuante do SUM() do SQLite (core/db.py).
    soma_filtrada = quantizar_soma(qs.aggregate(total=Sum("valor_estimado"))["total"]) or 0
    soma_contratada = quantizar_soma(qs.aggregate(total=Sum("valor_contratado"))["total"]) or 0

    bloco_a, bloco_b, _gauge_nao_usado = calcular_blocos_kpi(
        qs, get, dias_proximo_vencimento=settings.PCA_DIAS_PROXIMOS_VENCIMENTO
    )

    dimensao_selecionada = get.get("dimensao") or "uo"
    if dimensao_selecionada not in ROTULOS_DIMENSAO:
        dimensao_selecionada = "uo"
    medidas_validas = dict(MEDIDAS_ANALISE)
    medida_selecionada = get.get("medida") or "quantidade"
    if medida_selecionada not in medidas_validas:
        medida_selecionada = "quantidade"

    grafico_mensal = calcular_grafico_mensal(qs, get)
    series_mensais = graficos_pca.serializar_series_mensais(
        grafico_mensal.get(dimensao_selecionada, []), medida_selecionada
    )

    # (Análises, Escopo 2) — cada bloco principal ganha um
    # gráfico companheiro; TODOS reaproveitam a MESMA estrutura já
    # computada para a tabela (nenhuma consulta nova por gráfico).
    status_distribuicao = graficos_pca.calcular_status_distribuicao(qs, get)
    # Fase 28 — tabela do par analítico de
    # Situação no formato genérico `tabela_dados` (colunas/linhas), para
    # ficar reutilizável por todo par futuro (`dsgov/_par_analitico.html`).
    # ZERO consulta nova: `status_distribuicao` já é a agregação única
    #usada pelo gráfico e pela tabela; o total das 5 linhas (não a
    # soma de `qs`, que teria a MESMA contagem, mas por clareza soma-se as
    # linhas já computadas) é o denominador zero-safe de `%`.
    total_situacao = sum(linha["total"] for linha in status_distribuicao)
    tabela_situacao_linhas = [
        [
            {
                "valor": linha["rotulo"],
                "url": (
                    f"{reverse('pca:tabela')}?{linha['querystring']}"
                    if linha.get("querystring")
                    else None
                ),
            },
            numero(linha["total"]),
            moeda(linha["soma"]),
            percentual(_percentual(linha["total"], total_situacao)),
        ]
        for linha in status_distribuicao
    ]
    tabela_situacao_par = graficos.tabela_dados(
        ["Situação", "Quantidade", "Valor estimado", "%"], tabela_situacao_linhas
    )
    tabela_unidade = graficos_pca.tabela_por_unidade(qs, get)
    grafico_vencimento = calcular_grafico_vencimento_contratos(qs, get)
    dimensao_rotulo_selecionada = ROTULOS_DIMENSAO[dimensao_selecionada]
    medida_rotulo_selecionada = medidas_validas[medida_selecionada]
    # Fase 28 — "Adiamentos por item" saiu
    # de Análises (HTML/contexto/consulta); `calcular_grafico_adiamentos`
    # (`apps/pca/analise.py`) e `opcoes_adiamentos`/`resumo_adiamentos`
    # (`graficos_pca.py`) foram removidas (confirmado por grep — nenhum
    # outro consumidor).
    pontos_previsto_entregue = graficos_pca.calcular_previsto_entregue(qs, get)

    # Fase 28 — Perfil vira UM componente com
    # dimensão selecionável (`perfil_dimensao`, separado de `dimensao` da
    # distribuição mensal abaixo); allowlist fechada (`ROTULOS_PERFIL`,
    # 01) — qualquer valor fora cai no padrão "categoria", nunca
    # alcança `.values()`/`.annotate()` com nome de campo não confiável.
    # UMA query (não mais 5) por troca de dimensão.
    perfil_dimensao = get.get("perfil_dimensao") or "categoria"
    if perfil_dimensao not in ROTULOS_PERFIL:
        perfil_dimensao = "categoria"
    perfil_medida = "soma" if perfil_dimensao == "tipo" else "total"
    grupo_perfil = graficos_pca.calcular_perfil_grupo(qs, get, perfil_dimensao)
    perfil_par = {
        "chave": grupo_perfil["chave"],
        "titulo": grupo_perfil["titulo"],
        "linhas": grupo_perfil["linhas"],
        "grafico": {
            "id": f"analise-grafico-perfil-{grupo_perfil['chave']}",
            "titulo": grupo_perfil["titulo"],
            "opcoes": graficos_pca.opcoes_perfil_grupo(grupo_perfil, medida=perfil_medida),
            "resumo": (
                f"Perfil por {grupo_perfil['titulo'].lower()}: "
                f"{len(grupo_perfil['linhas'])} grupo(s)."
            ),
        },
        "tabela": graficos_pca.tabela_perfil_grupo(grupo_perfil),
    }

    # Fase 28 — "Próximos vencimentos — prazos
    # dos processos": mesma leitura de proximidade do KPI (`apps.pca.kpis.
    # condicao_proximo_do_prazo`), sem janela de dias, na posição
    # reservada (entre Perfil e Previsto×Entregue).
    #
    # "Próximos vencimentos" é prazo/acompanhamento:
    # some para quem não tem `pca.view_acompanhamento` (grupo
    # visualizador). Sem a permissão, nem `calcular_proximos_vencimentos`
    # é chamado — evita consulta gasta à toa para quem não vai ver o card
    # (convenções do projeto/Desempenho).
    if request.user.has_perm("pca.view_acompanhamento"):
        try:
            vencimentos_limite = int(get.get("vencimentos", VENCIMENTOS_PADRAO))
        except (TypeError, ValueError):
            vencimentos_limite = VENCIMENTOS_PADRAO
        if vencimentos_limite not in VENCIMENTOS_OPCOES:
            vencimentos_limite = VENCIMENTOS_PADRAO
        (
            processos_vencimentos,
            total_vencimentos_recorte,
            total_vencidos,
            url_vencidos,
        ) = calcular_proximos_vencimentos(qs, get, limite=vencimentos_limite)
        hoje_vencimentos = localdate()
        linhas_vencimentos = []
        for processo_vencimento in processos_vencimentos:
            dias_restantes = (processo_vencimento.prazo_efetivo - hoje_vencimentos).days
            rotulo_dias = (
                "Vence hoje" if dias_restantes == 0 else f"Em {dias_restantes} dias"
            )
            linhas_vencimentos.append(
                {"processo": processo_vencimento, "rotulo_dias": rotulo_dias}
            )
        def _querystring_vencimentos(valor):
            # "vencimentos" é um controle de paginação de Análises, não um
            # parâmetro canônico de `PARAMETROS_FILTRO` (não pertence a
            # `/tabela`) — `QueryDict` mutável sobre a base já validada
            # preserva os demais filtros ativos, mesmo padrão de
            # `_contexto_calendario::querystring_calendario`.
            parametros = QueryDict(querystring_filtros(get), mutable=True)
            parametros["vencimentos"] = str(valor)
            return parametros.urlencode()

        # ops/dsgov/verificar.py (regra PRIMARIO) conta literalmente a
        # substring "primary" no ARQUIVO .html — nunca simula `{% if %}`. Duas
        # ocorrências estáticas do literal "primary" no template (uma por
        # link, mesmo dentro de um `{% if %}/{% else %}`) contam como "2
        # botões primary", falso positivo. A classe do botão selecionado
        # (nunca mais que 1 "primary" ao mesmo tempo, de verdade) é resolvida
        # aqui em Python — o literal "primary"/"secondary" nunca aparece no
        # `.html`, só no valor injetado por `{{ }}`.
        classe_secundario = "secondary"
        classe_selecionado = "primary"
        proximos_vencimentos_ctx = {
            "linhas": linhas_vencimentos,
            "limite": vencimentos_limite,
            "opcoes_limite": VENCIMENTOS_OPCOES,
            "total_no_recorte": total_vencimentos_recorte,
            "total_vencidos": total_vencidos,
            "url_vencidos": url_vencidos,
            "querystring_10": _querystring_vencimentos(10),
            "querystring_20": _querystring_vencimentos(20),
            "classe_botao_10": (
                classe_selecionado if vencimentos_limite == 10 else classe_secundario
            ),
            "classe_botao_20": (
                classe_selecionado if vencimentos_limite == 20 else classe_secundario
            ),
        }
    else:
        proximos_vencimentos_ctx = None

    contexto = {
        "filtros": filtros_ativos(get),
        "tags": tags_ativas(get),
        "total_filtrado": qs.count(),
        "total_geral": total_geral,
        "soma_filtrada": soma_filtrada,
        "soma_contratada": soma_contratada,
        "exercicio": exercicio,
        "bloco_a": bloco_a,
        "bloco_b": bloco_b,
        # Links do bloco de totais para "Valor
        # planejado"/"Valor contratado" (os 9 números de bloco_a/bloco_b já
        # carregam "href" via apps.pca.kpis.card()).
        "url_filtro_atual": f"{reverse('pca:tabela')}?{querystring_filtros(get)}",
        # Situação/unidade/previsto×entregue: MESMA fonte de
        # `core.views.inicio` (graficos_pca), como tabela + gráfico
        # companheiro (Escopo 2). Fase 28 — Situação é a PRIMEIRA fatia migrada ao partial
        # canônico `dsgov/_par_analitico.html` (par = {titulo, grafico,
        # tabela}); Fase 28 — TODOS os pares abaixo
        # seguem o mesmo contrato, na ordem: Situação, Unidade, Perfil
        # (acima), [espaço para "Próximos vencimentos"],
        # Previsto×Entregue, Distribuição mensal, Vencimento.
        "grafico_situacao": {
            "titulo": "Processos por situação",
            "grafico": {
                "id": "analise-grafico-situacao",
                "opcoes": graficos_pca.opcoes_situacao(status_distribuicao),
                "resumo": graficos_pca.resumo_situacao(status_distribuicao),
            },
            "tabela": tabela_situacao_par,
        },
        "unidade_par": {
            "titulo": "Processos por unidade",
            "grafico": {
                "id": "analise-grafico-unidade",
                "titulo": "Processos por unidade",
                "opcoes": graficos_pca.opcoes_por_unidade_de(tabela_unidade),
                "resumo": graficos_pca.resumo_por_unidade_de(tabela_unidade),
                "alto": True,
            },
            "tabela": graficos_pca.tabela_unidade_dados(tabela_unidade),
        },
        # Fase 28 — Perfil vira 1 componente
        # com dimensão selecionável (`perfil_dimensao`), não mais 5 pares.
        "rotulos_perfil": ROTULOS_PERFIL,
        "perfil_dimensao_selecionada": perfil_dimensao,
        "perfil_par": perfil_par,
        # Fase 28 — espaço reservado entre Perfil
        # e Previsto×Entregue.
        "proximos_vencimentos": proximos_vencimentos_ctx,
        "previsto_entregue_par": {
            "titulo": "Previsto × Entregue por mês",
            "grafico": {
                "id": "analise-grafico-previsto-entregue",
                "titulo": "Previsto × Entregue por mês",
                "opcoes": graficos_pca.opcoes_previsto_entregue(pontos_previsto_entregue),
                "resumo": graficos_pca.resumo_previsto_entregue(pontos_previsto_entregue),
            },
            "tabela": graficos_pca.tabela_previsto_entregue(pontos_previsto_entregue),
        },
        # Mês × dimensão escolhida — form GET (dimensao/medida), recarga
        # inteira, sem HTMX (relatorio.md/telas não preveem HTMX aqui).
        # Fase 28 — o par (gráfico + tabela-resumo,
        # totais anuais) fica 6/6; `series_mensais` (matriz completa de 12
        # meses) continua no contexto para o "Detalhamento mensal
        # completo" full-width logo abaixo do par.
        "rotulos_dimensao": ROTULOS_DIMENSAO,
        "dimensao_selecionada": dimensao_selecionada,
        "dimensao_rotulo_selecionada": dimensao_rotulo_selecionada,
        "medidas_disponiveis": MEDIDAS_ANALISE,
        "medida_selecionada": medida_selecionada,
        "medida_rotulo_selecionada": medida_rotulo_selecionada,
        "series_mensais": series_mensais,
        "mesdim_par": {
            "titulo": f"{dimensao_rotulo_selecionada} por mês — {medida_rotulo_selecionada}",
            "grafico": {
                "id": "analise-grafico-mesdim",
                "titulo": f"{dimensao_rotulo_selecionada} por mês — {medida_rotulo_selecionada}",
                "opcoes": graficos_pca.opcoes_mes_dimensao(
                    grafico_mensal.get(dimensao_selecionada, []), medida_selecionada
                ),
                "resumo": graficos_pca.resumo_mes_dimensao(
                    grafico_mensal.get(dimensao_selecionada, []),
                    dimensao_rotulo_selecionada,
                    medida_rotulo_selecionada,
                ),
            },
            "tabela": graficos_pca.tabela_resumo_mes_dimensao(
                grafico_mensal.get(dimensao_selecionada, []),
                medida_selecionada,
                dimensao_rotulo_selecionada,
            ),
        },
        "vencimento_par": {
            "titulo": "Vencimentos por mês",
            "subtitulo": (
                f"{numero(grafico_vencimento['sem_vigencia_fim'])} vigente(s) sem "
                "data de fim de vigência cadastrada — fora da contagem abaixo."
                if grafico_vencimento["sem_vigencia_fim"]
                else None
            ),
            "grafico": {
                "id": "analise-grafico-vencimento",
                "titulo": "Vencimentos por mês",
                "opcoes": graficos_pca.opcoes_vencimento(grafico_vencimento),
                "resumo": graficos_pca.resumo_vencimento(grafico_vencimento),
            },
            "tabela": graficos_pca.tabela_vencimento(grafico_vencimento),
        },
        "trilha": (
            [
                (
                    f"PCA {exercicio.ano}",
                    f"{reverse('raiz')}?exercicio={exercicio.ano}",
                ),
                ("Análises", None),
            ]
            if exercicio
            else [("Análises", None)]
        ),
        "nome_tela": "Análises",
    }

    resposta = render(request, "pca/analise.html", contexto)
    # Pitfall 16 — nunca cacheável na borda; o filtro é por sessão
    # autenticada, não público.
    resposta["Cache-Control"] = "private, no-store"
    return resposta


def exportar_resumo_uo_xlsx_view(request):
    """Fase 17.1 — download síncrono do XLSX do
    resumo por UO. Mesmo queryset/filtro de `resumo_uo_view`, mesmas
    premissas de `exportar_xlsx_view` (sessão via LoginRequiredMiddleware,
    nunca cacheável na borda)."""
    qs = queryset_filtrado(request)
    linhas, total = calcular_resumo_uo(qs)
    resposta = exportar_resumo_uo_xlsx(linhas, total)
    resposta["Cache-Control"] = "private, no-store"
    return resposta


# Generaliza (nulls_last nos dois sentidos) e o
# padrão de tradução chave-de-tela → caminho-de-order_by que o bloco de
# default de urgência, logo abaixo, já usava inline só para
# `grau_prioridade__nome`.
#
# CAMPOS_ORDENACAO_FK traduz as colunas de FK do seletor de colunas para o
# nome de exibição — nunca o id cru, que não tem ordem útil nenhuma na
# tela. `unidade_organizacional` entrou, revertendo a
# exceção que havia aberto.
#
# Fase 29 — `categoria`/`modalidade`/
# `instrumento_contratual` (as duas últimas, novas) entram no
# mesmo grupo: ordenam pelo nome, nunca pelo id.
CAMPOS_ORDENACAO_FK = {
    "grau_prioridade": "grau_prioridade__nome",
    "classificacao": "classificacao__nome",
    "unidade_organizacional": "unidade_organizacional__nome",
    "categoria": "categoria__nome",
    "modalidade": "modalidade__nome",
    "instrumento_contratual": "instrumento_contratual__nome",
    # Fase 17 — a chave de cabeçalho "situacao" ordena
    # pela mesma correção-na-leitura que a exibição usa, nunca pela
    # coluna crua.
    "situacao": "situacao_efetiva",
}

# Fase 29 — as duas FKs de Execução contratual só
# entram em `select_related` quando a coluna está de fato marcada (mesmo
# princípio de `numeros_sei`/`prefetch_related` logo acima em
# `tabela_view`, e do único `select_related("tipo")` extra do export):
# campos locais (CharField/DateField de Execução contratual/Publicação)
# não precisam de preload nenhum, só as duas FKs.
FKS_SELECT_RELATED_CONDICIONAL = ("modalidade", "instrumento_contratual")

# CAMPOS_ORDENACAO_NULOS_POR_ULTIMO generaliza o `nulls_last` que antes só
# cobria o tuple hardcoded ("mes_previsto", "prazo_entrega", "prazo_efetivo")
# para toda coluna nova nullable — FK opcional, data solta ou subquery de
# acompanhamento (mesma regra "sem valor" sempre por último, nos dois
# sentidos). `atrasado`/`publicacao_pendente` ficam de fora de propósito:
# são anotações booleanas com `default=Value(False)` no `Case` de
# `para_listagem()`, nunca NULL, então não precisam (nem devem) desse
# tratamento.
#
# Fase 29 — `prazo_inicial` substitui `prazo_entrega`;
#as 12 chaves novas de Execução contratual/Publicação
# nullable entram no mesmo tratamento — FK opcional
# (`modalidade`/`instrumento_contratual`) ou data/texto solto, mesma
# regra de qualquer coluna nova nullable já generalizada pela quick.
CAMPOS_ORDENACAO_NULOS_POR_ULTIMO = frozenset(
    {
        "mes_previsto",
        "prazo_inicial",
        "prazo_efetivo",
        "grau_prioridade",
        "classificacao",
        "data_inclusao_pca",
        "situacao_atual",
        "data_envio_gelic",
        "data_recebimento_gelic",
        "data_prevista_conclusao",
        "modalidade",
        "instrumento_contratual",
        "numero_contratacao",
        "numero_arp",
        "numero_instrumento_contratual",
        "fornecedor_cnpj",
        "fornecedor_razao_social",
        "data_assinatura_contrato",
        "vigencia_inicio",
        "vigencia_fim",
        "data_lancamento_spw",
        "data_lancamento_wordpress",
        "data_lancamento_dados_abertos",
    }
)


def _ordenar_para_tabela(request, qs):
    """Aplica ao queryset a MESMA ordem que a tabela exibe.

    Extraído de `tabela_view` pela o Anterior/Próximo do modal
    de edição precisa percorrer os processos na ordem que o usuário está vendo.
    Recalcular a ordem por conta própria criaria uma segunda noção de ordem, que
    divergiria em silêncio justamente nos casos difíceis — o default de urgência
e o `nulls_last`.
    """
    campo_ordenacao = ordenacao_valida(request.GET.get("ordenar"), request)
    descendente = direcao_valida(request.GET.get("dir")) == "desc"

    # (06-01) — ordenação default de urgência: quando uma das quatro
    # flags de risco (atrasado/criticos/proximo_prazo/sem_atualizacao) está
    # ativa e NÃO há ?ordenar= explícito, a tabela abre por prazo_efetivo
    # (Fase 11 — a mesma identidade única que governa atraso, inclusive
    # o fallback para o prazo de Planejamento) ascendente (nulos por
    # último), críticos (grau 'Alta') primeiro, depois por nome do grau e
    # desempate estável exercicio/item_pca. Um ?ordenar= explícito sempre
    # vence este default.
    filtros = filtros_ativos(request.GET)
    risco_ativo = any(
        filtros[f] for f in ("atrasado", "criticos", "proximo_prazo", "sem_atualizacao")
    )
    if risco_ativo and not request.GET.get("ordenar"):
        return qs.order_by(
            F("prazo_efetivo").asc(nulls_last=True),
            Case(
                When(grau_prioridade__nome_normalizado="alta", then=Value(0)),
                When(grau_prioridade__isnull=True, then=Value(2)),
                default=Value(1),
                output_field=IntegerField(),
            ),
            "grau_prioridade__nome",
            "exercicio",
            "item_pca",
        )

    # Mesma razão do `mes_previsto` abaixo:
    # `prazo_entrega`/`prazo_efetivo` também são colunas de data anuláveis
    # (`prazo_efetivo = Coalesce(prazo_vigente, prazo_entrega)` é NULL sem
    # nenhuma das duas). Sem `nulls_last` nos DOIS sentidos, "Prazo efetivo"
    # descendente poria todo processo SEM prazo à frente dos mais atrasados
    # — o oposto do que "quem está mais atrasado" precisa mostrar primeiro.
    # `campo_real` é o campo de fato usado no
    # `order_by()`: `campo_ordenacao` para toda coluna direta/anotada, e a
    # tradução `__nome` só para `grau_prioridade`/`classificacao`
    # (`CAMPOS_ORDENACAO_FK`).
    campo_real = CAMPOS_ORDENACAO_FK.get(campo_ordenacao, campo_ordenacao)

    if campo_ordenacao in CAMPOS_ORDENACAO_NULOS_POR_ULTIMO:
        # Item 137 (mes_previsto=NULL) sempre por último, nos DOIS
        # sentidos: `nulls_last` precisa ser repetido no desc, senão o
        # PostgreSQL põe NULL na frente e o item sem mês vira o primeiro da
        # lista descendente. Generalizado para toda
        # coluna nullable nova (`CAMPOS_ORDENACAO_NULOS_POR_ULTIMO`).
        expressao = F(campo_real)
        ordem = (
            expressao.desc(nulls_last=True)
            if descendente
            else expressao.asc(nulls_last=True)
        )
    else:
        ordem = f"-{campo_real}" if descendente else campo_real

    # `item_pca` como desempate: sem ele, colunas com
    # valores repetidos (status, mês, nº de reuniões) deixam a ordem das
    # linhas empatadas indefinida no PostgreSQL, e o mesmo processo pode
    # aparecer em duas páginas — ou em nenhuma — ao paginar.
    return qs.order_by(ordem, "exercicio", "item_pca")


# Campos de cada resultado na visualização Lista (sempre
# os mesmos, como a busca de editais do PNCP: a escolha de colunas vale só
# para a Tabela). "Prazo atual" é acompanhamento: some sem a permissão.
CAMPOS_VISTA_LISTA = (
    "unidade_organizacional",
    "categoria",
    "mes_previsto",
    "modalidade",
    "valor_estimado",
    "valor_contratado",
    "prazo_efetivo",
)


def _colunas_vista_lista(request):
    """Duas linhas de pares "Rótulo: valor" por resultado: quem/quando/como
    (unidade, categoria, mês, modalidade) e quanto/até quando (valores e
    prazo atual)."""
    colunas = []
    for chave in CAMPOS_VISTA_LISTA:
        if chave == "prazo_efetivo" and not request.user.has_perm("pca.view_acompanhamento"):
            continue
        colunas.append(COLUNAS_POR_CHAVE[chave])
    return [colunas[:4], colunas[4:]]


def tabela_view(request):
    """`/tabela` isolada do dashboard, alimentada pelo contrato
    único `queryset_filtrado` (Pitfall 16): dashboard (02-02), kanban
    e detalhe (02-03) e export (02-04) consomem a mesma função, nunca um
    filtro próprio.

    Fase 26 — tela migrada ao padrão
    `telas/listagem.md`: com `HX-Request` devolve SÓ `_listagem.html`
    (chips de filtro ativo + tabela + paginação + Exportar), sem nenhum
    `hx-swap-oob` (a casca legada de 5 fragmentos concatenados —
    `_tags_filtros.html`/`_acoes_export.html`/`core/_nav_visoes.html`/
    `core/_titulo_exercicio.html`/`core/_rodape_visoes.html` — não se
    aplica mais a esta tela).

    Sem `@login_not_required`: precisa de sessão válida, garantida pelo
    `LoginRequiredMiddleware` global.
    """
    # Persistência do estado canônico em
    # sessão, ANTES de qualquer outra linha do corpo da view. `colunas` já
    # tem sua PRÓPRIA persistência independente (`colunas_selecionadas`,
    # `CHAVE_SESSAO_COLUNAS`) — por isso uma requisição que só muda
    # `colunas` (nenhuma outra chave no GET) não toca nem lê
    # `CHAVE_SESSAO_ESTADO_TABELA`: nem grava (evitaria persistir um
    # "estado" que é só a seleção de colunas, redirecionando à toa a
    # próxima navegação sem filtro nenhum) nem redireciona (a requisição
    # não está vazia — `test_colunas_tabela.py`, achado real desta guarda).
    # Chaves REAIS de filtro/ordenação/página presentes: grava o estado
    # (guarda "só grava se diferir") — inclusive `?limpar=1`, que
    # não pertence a nenhuma chave canônica e por isso produz o estado
    # "limpo" de verdade. Querystring vazia (`request.GET` sem chave
    # alguma) e requisição NÃO-htmx: se há estado guardado, redireciona
    # para ele sem montar queryset/contexto algum (retorno antecipado) — é
    # isso que restaura "voltar pelo menu/trilha" à mesma tabela filtrada.
    querystring_bruta = request.META.get("QUERY_STRING", "")
    chaves_relevantes = set(request.GET.keys()) - {"colunas"}
    if chaves_relevantes:
        canonico = querystring_tabela(request.GET)
        if request.session.get(CHAVE_SESSAO_ESTADO_TABELA) != canonico:
            request.session[CHAVE_SESSAO_ESTADO_TABELA] = canonico
    elif not querystring_bruta and not request.htmx:
        guardado = request.session.get(CHAVE_SESSAO_ESTADO_TABELA)
        if guardado:
            resposta = redirect(f"{reverse('pca:tabela')}?{guardado}")
            resposta["Cache-Control"] = "private, no-store"
            return resposta

    # Import local (não no topo do módulo) — Fase 28 removeu a
    # dependência circular original (`forms_listagem.py` importava o antigo
    # conjunto de chaves-padrão DESTE módulo); mantido local por
    # disciplina (mesmo padrão de `apps/pca/forms.py`), sem
    # necessidade funcional de mudar agora.
    from apps.pca.forms_listagem import FiltrosProcessoForm

    campo_ordenacao = ordenacao_valida(request.GET.get("ordenar"), request)
    direcao_ordenacao = direcao_valida(request.GET.get("dir"))
    descendente = direcao_ordenacao == "desc"

    # Resolvida ANTES do queryset: o
    # `prefetch_related("numeros_sei")` só entra quando a coluna está de
    # fato marcada, senão toda requisição da tabela pagaria 1 consulta a
    # mais à toa (convenções do projeto, Desempenho — nunca consulta desperdiçada).
    colunas_resolvidas = colunas_selecionadas(request)

    # O queryset filtrado é avaliado (parseado/filtrado) UMA vez por
    # request e reaproveitado para contagem, soma e página; nunca reconstruído
    # a partir do GET em cada bloco (o que abriria espaço para divergência
    # entre a soma exibida e a lista exibida).
    qs = queryset_filtrado(request).select_related(
        "origem", "origem__exercicio", "tipo"
    )
    if "numeros_sei" in colunas_resolvidas:
        qs = qs.prefetch_related("numeros_sei")
    fks_selecionadas = [
        chave for chave in FKS_SELECT_RELATED_CONDICIONAL if chave in colunas_resolvidas
    ]
    if fks_selecionadas:
        qs = qs.select_related(*fks_selecionadas)

    # Visualização Lista | Tabela (padrão Tabela). A lista
    # mostra sempre os mesmos campos (`CAMPOS_VISTA_LISTA`), inclusive a
    # modalidade (FK) — select_related para não virar consulta por linha.
    vista = vista_valida(request.GET.get("vista"))
    if vista == VISTA_LISTA and "modalidade" not in fks_selecionadas:
        qs = qs.select_related("modalidade")

    # A ordem vive em `_ordenar_para_tabela` para que o Anterior/Próximo do
    # modal de edição percorra os processos exatamente como a tabela os mostra.
    qs = _ordenar_para_tabela(request, qs)

    # `br-pagination` 10/20/50 (`por_pagina` novo, `pagina`
    # mantido); `TAMANHO_PAGINA` (20) vira só o padrão quando `por_pagina`
    # está ausente/fora do allowlist de `settings.DSGOV`.
    opcoes_por_pagina = settings.DSGOV.get("OPCOES_POR_PAGINA", (10, 20, 50))
    try:
        por_pagina = int(request.GET.get("por_pagina", TAMANHO_PAGINA))
    except (TypeError, ValueError):
        por_pagina = TAMANHO_PAGINA
    if por_pagina not in opcoes_por_pagina:
        por_pagina = TAMANHO_PAGINA
    paginador = Paginator(qs, por_pagina)
    pagina = paginador.get_page(request.GET.get("pagina"))

    # Soma do MESMO queryset filtrado (não paginado), nunca uma
    # segunda consulta com filtro reconstruído à parte (Armadilha 9/16).
    # quantizar_soma corrige o ruído de ponto flutuante do SUM() do SQLite
    # (core/db.py) — sem efeito sobre o valor exato já devolvido pelo
    # PostgreSQL.
    soma_filtrada = quantizar_soma(qs.aggregate(total=Sum("valor_estimado"))["total"]) or 0
    filtros = filtros_ativos(request.GET)
    exercicio = filtros["exercicio"]
    total_geral = Processo.objects.filter(exercicio=exercicio).count()

    # Fase 28 (REVOGADO) — os 12
    # campos secundários de "Mais filtros" (`estado` incluído: a enumeração
    #EJAMENTO.md tinha 11 campos, omitindo esse campo
    # real do form, ver forms_listagem.py). O acordeão NÃO abre
    # mais sozinho; a contagem abaixo é o que sinaliza filtro ativo.
    # A contagem alimenta o rótulo "Mais filtros (N)"
    # agora que o acordeão nunca nasce aberto: sem isso, um filtro
    # secundário ativo ficaria invisível atrás do painel fechado.
    _CHAVES_MAIS_FILTROS = (
        "categoria",
        "tipo",
        "prioridade",
        "classificacao",
        "modalidade",
        "unidade_sei",
        "estado",
        "desde_reuniao",
        "legados",
        "recebido_de",
        "recebido_ate",
        "vigencia_fim_de",
        "vigencia_fim_ate",
    )
    mais_filtros_contagem = sum(1 for chave in _CHAVES_MAIS_FILTROS if filtros[chave])
    mais_filtros_ativo = bool(mais_filtros_contagem)

    # Fase 28 — a seleção de colunas já foi
    # resolvida acima (`colunas_resolvidas`), antes do queryset (quick); `colunas_selecionadas` grava na sessão como efeito
    # colateral, então não é chamada de novo aqui (chamar duas vezes seria
    # inofensivo — a guarda "só grava se mudou" é idempotente — mas
    # redundante).
    cabecalhos_dinamicos = _cabecalhos_ordenaveis(
        campo_ordenacao, direcao_ordenacao, colunas_resolvidas
    )

    # `exercicio` é o ÚNICO parâmetro propagado pelo menu/links
    # entre telas; "Limpar filtros" (fecha A05) remove todo o
    # resto de `PARAMETROS_FILTRO` de uma vez, preservando só ele.
    querystring_limpar = querystring_filtros(
        request.GET,
        excluir=[chave for chave in PARAMETROS_FILTRO if chave != "exercicio"],
    )

    # Link "Restaurar padrão" do seletor "Colunas": querystring
    # dos filtros atuais (sem `colunas`, que não pertence a
    # `PARAMETROS_FILTRO`, mas `excluir="colunas"` documenta a intenção
    # mesmo assim) + as 5 chaves do padrão novo, uma por par `colunas=`.
    querystring_colunas_padrao = urlencode(
        {"colunas": list(COLUNAS_PADRAO)}, doseq=True
    )
    _base_restaurar = querystring_filtros(request.GET, excluir="colunas")
    if _base_restaurar:
        querystring_colunas_padrao = f"{_base_restaurar}&{querystring_colunas_padrao}"

    contexto = {
        "pagina": pagina,
        "filtros": filtros,
        "campo_ordenacao": campo_ordenacao,
        "direcao_ordenacao": direcao_ordenacao,
        "colunas_ordenacao": COLUNAS_ORDENACAO,
        "opcoes_por_pagina": opcoes_por_pagina,
        "soma_filtrada": soma_filtrada,
        "total_geral": total_geral,
        "exercicio": exercicio,
        "total_filtrado": pagina.paginator.count,
        "tags": tags_ativas(request.GET),
        "querystring_filtros": querystring_filtros(request.GET),
        "querystring_tabela": querystring_tabela(request.GET),
        "querystring_limpar": querystring_limpar,
        "trilha": [("Processos", None)],
        "nome_tela": "Processos",
        # Fase 28 — seletor "Colunas".
        "colunas_selecionadas": colunas_resolvidas,
        "cabecalhos_dinamicos": cabecalhos_dinamicos,
        # Fase 29 — seletor "Colunas" agrupado em
        # quatro fieldsets (Planejamento/Processo/Execução contratual/
        # Publicação); o registro achatado (`COLUNAS`) não tem mais
        # consumidor no template depois desta migração.
        "colunas_por_secao": colunas_por_secao(request),
        "colunas_obrigatorias": COLUNAS_OBRIGATORIAS,
        "querystring_colunas_padrao": querystring_colunas_padrao,
        # Fase 28 — "Mais filtros" abre sozinho.
        "mais_filtros_ativo": mais_filtros_ativo,
        "mais_filtros_contagem": mais_filtros_contagem,
        # Lista | Tabela e os campos fixos da lista.
        "vista": vista,
        "colunas_lista": _colunas_vista_lista(request),
    }

    if request.htmx and not request.htmx.history_restore_request:
        # Uma única resposta por troca de filtro: `_listagem.html`
        # inteiro (chips de filtro ativo + tabela/paginação/exportar), sem
        # nenhum OOB — o MESMO parcial que `tabela.html` usa dentro de
        # `#listagem` na carga inicial (chips/exportar desatualizados fora
        # do alvo do swap, achado real deste plano). Os `br-select` da
        # barra de filtro NÃO são reescritos (o form inteiro continua fora
        # do alvo) — por isso `FiltrosProcessoForm` (e as queries de
        # `opcoes_filtros()` que ela dispara ao popular prioridade/
        # classificação) só é construído no ramo `else` abaixo, nunca aqui
        # (mesmo orçamento de query mais barato que o contrato antigo já
        # garantia).
        #
        # QA de segurança 30/09/2026 (navegador M2/fuzz B7) — com
        # `HX-History-Restore-Request: true` (o "Voltar" do navegador
        # depois de uma troca de filtro por HTMX), cai no ramo `else`
        # abaixo: a PÁGINA inteira, com o form de filtros sincronizado ao
        # estado real da URL — nunca o snapshot local que o htmx
        # restauraria sozinho.
        resposta = render(request, "pca/_listagem.html", contexto)
    else:
        # `FiltrosProcessoForm` é construído SEM `data=`
        # (nunca `.is_valid()`/`.errors`): um `?situacao=<script>...`
        # inválido misturado a valores válidos (defesa em profundidade)
        # não pode reaparecer na página, nem escapado (Django escapa
        # `<`/`>`, mas a mensagem "X não é uma das escolhas disponíveis"
        # do ChoiceField ainda ecoaria o valor cru como TEXTO).
        # Formulário desvinculado + `initial` a partir de `filtros` (já
        # validado por `_ids_validos`/`_estados_validos`/etc.) nunca
        # dispara essa validação — só os valores REAIS do filtro aparecem
        # marcados, lixo é descartado em silêncio.
        contexto["filtros_form"] = FiltrosProcessoForm(
            exercicio=exercicio,
            initial={
                "q": filtros["q"],
                "uo": filtros["uo"],
                "categoria": filtros["categoria"],
                "tipo": filtros["tipo"],
                "prioridade": filtros["prioridade"],
                "classificacao": filtros["classificacao"],
                "modalidade": filtros["modalidade"],
                "unidade_sei": filtros["unidade_sei"],
                "estado": filtros["estado"],
                "situacao": filtros["situacao"],
                "mes": filtros["mes"],
                "desde_reuniao": filtros["desde_reuniao"],
                "legados": filtros["legados"] == "1",
                "recebido_de": filtros["recebido_de"],
                "recebido_ate": filtros["recebido_ate"],
                "vigencia_fim_de": filtros["vigencia_fim_de"],
                "vigencia_fim_ate": filtros["vigencia_fim_ate"],
            }
        )
        resposta = render(request, "pca/tabela.html", contexto)

    # Pitfall 16 — nunca cacheável na borda; o filtro é por sessão
    # autenticada, não público.
    resposta["Cache-Control"] = "private, no-store"
    return resposta


def _tipo_widget(campo):
    """Dispatch the widget from the model field type, not field-name lists."""
    field = Processo._meta.get_field(campo)
    from django.db.models import (
        CharField,
        DateField,
        DecimalField,
        ForeignKey,
        IntegerField,
        BooleanField,
        TextField,
    )

    if isinstance(field, ForeignKey):
        return "select_fk"
    if isinstance(field, BooleanField):
        return "boolean"
    if isinstance(field, IntegerField):
        # The allowlist contains exactly one bounded IntegerField: month.
        return "select_mes"
    if isinstance(field, DateField):
        return "date"
    if isinstance(field, TextField):
        return "textarea"
    if isinstance(field, DecimalField):
        # Widget próprio para os dois campos monetários
        # (valor_estimado, valor_contratado): o template aplica a máscara
        # `pcaMascaraMoeda` só neles, não em numero_contratacao/
        # fornecedor_razao_social etc., que continuam em "text".
        return "money"
    if isinstance(field, CharField):
        if field.choices:
            return "select_choice"
        return "text"
    raise Http404("Campo sem widget permitido")


def _normalizar_valor_monetario(bruto):
    """Aceita tanto a forma crua (`35000`, `35000.00`) quanto a mascarada
    pt-BR (`35.000,00`) — o servidor tem de entender as duas (Decisão 3).

    A presença de vírgula é o sinal de forma mascarada: remove os pontos de
    milhar e troca a vírgula decimal por ponto. Sem vírgula, o valor já está
    cru e passa intacto para `field.clean()`.
    """
    if "," in bruto:
        return bruto.replace(".", "").replace(",", ".")
    return bruto


# QA 30/09/2026 (fuzz M4/domínio nº8) — formato estrito do valor já
# normalizado: só dígitos ASCII (nunca `٣`, que não é `[0-9]`), sem sinal
# (negativo é decisão de negócio, nunca aceito), até 2 casas decimais;
# recusa notação científica (`1e10`) e separador `_` (`1_000`), que
# `Decimal()` aceitaria sem reclamar.
_FORMATO_VALOR_MONETARIO = re.compile(r"^[0-9]+(\.[0-9]{1,2})?$")


def _valor_monetario_formato_valido(normalizado):
    return bool(_FORMATO_VALOR_MONETARIO.fullmatch(normalizado))


# Seções do formulário de edição completa. A ordem e o
# agrupamento são de apresentação; a fronteira de confiança continua sendo
# CAMPOS_EDITAVEIS_PROCESSO, e nenhum campo daqui escapa dela (há teste).
# `status` está ausente de propósito: ele só muda pelo modal de transição, que
# grava acompanhamento.
#
# Fase 11 — revisão da
# Planejamento reúne só o que a equipe PREVÊ (cadastro + a única data de
# prazo, `prazo_entrega`, que já nasce com o verbose_name correto "Data
# prevista para entrega" — nenhum rótulo emprestado por aba). As duas
# justificativas obsoletas saem das duas abas —
# `justificativa_alteracao_prazo` passa a pertencer a cada promessa
# (`Acompanhamento.evento`) e `justificativa_alteracao_email` sai de tudo;
# os campos físicos ficam até o plano migrar os dados.
#
# Fase 15 — a aba "Processo" enxuga para só (sem
# `situacao_sei`, removido) `data_recebimento_gelic` (fusão Delic->Gelic) + Números SEI
# (bloco fora do loop de `secoes`, condicionado a `secao.titulo ==
# "Processo"`). `data_prevista_conclusao` sai da aba (a edição inline da
# tabela saiu na Fase 26; desde 10/11/2026 o campo não é mais editável
# em lugar nenhum, só importado); `data_envio_gelic` fica sem superfície de edição
# em lugar nenhum (dado congelado).
SECOES_FORMULARIO_PROCESSO = (
    (
        "Planejamento",
        (
            "descricao_objeto",
            "justificativa",
            "unidade_organizacional",
            "classificacao",
            "tipo",
            "categoria",
            "grau_prioridade",
            "valor_estimado",
            "mes_previsto",
            "data_inclusao_pca",
            "prazo_entrega",
        ),
    ),
    (
        "Processo",
        ("data_recebimento_gelic",),
    ),
    (
        "Execução contratual",
        (
            "modalidade",
            "numero_contratacao",
            "numero_arp",
            "instrumento_contratual",
            "numero_instrumento_contratual",
            "fornecedor_cnpj",
            "fornecedor_razao_social",
            "valor_contratado",
            "data_assinatura_contrato",
            "vigencia_inicio",
            "vigencia_fim",
            # Fase 36 — base do fluxo de caixa.
            "regime_execucao",
            "renovacao_prevista",
            "valor_mensal",
        ),
    ),
    (
        "Publicação",
        (
            "data_lancamento_spw",
            "data_lancamento_wordpress",
            "data_lancamento_dados_abertos",
        ),
    ),
)


# Fase 26 — `_valor_para_exibicao`/
# `_secoes_formulario_processo`/`_aplicar_campo`/`_vizinhos_na_ordem_da_tabela`/
# `_sem_permissao_de_edicao`/`_motivo_leitura`/`_somente_leitura` migraram para
# `apps/pca/views_processo.py` (a última sob o mesmo nome) ou saíram por
# obsolescência (o conceito `?modo=ver` de leitura dentro do modal não existe
# mais — ver `pca:detalhe_processo`).


# Fase 26 — `_aba_ativa` saiu: o novo
# `processo_formulario.html` não tem abas.


# Fase 26 — `_querystring_com_modo`/`_contexto_form_editar`
# saíram: eram exclusivos do modal multi-aba `_form_editar_processo.html`,
# apagado nesta Task junto com `editar_processo_view`/`criar_processo_view`
# antigas (agora em `apps/pca/views_processo.py`).


def _carregar_processo_modal(ano, item_pca):
    """Carregamento único usado pelo GET, pelo sucesso e pelos erros do
    modal do processo (Fase 11; consolidado):
    acrescenta ``timeline_completa`` — TODO ``Acompanhamento`` do processo,
    em ordem cronológica crescente — como único ``to_attr`` do prefetch.
    ``historico_prazos`` (só os acompanhamentos com ``prazo_prometido``
    preenchido, consumido pela aba Planejamento) é derivado em memória do
    mesmo ``timeline_completa`` por list comprehension, sem segunda query —
    preserva /convenções do projeto: derivadas de histórico nunca em consulta por
    linha.

    Os marcadores ``prazo_anterior``/``prazo_mudou``/``prazo_mantido`` de
    cada item também são calculados aqui, em memória, replicando a lógica
    da antiga `detalhe_view` (removida na Fase 14) — a aba "Acompanhamento"
    do modal os usa para os badges Remarcado/Prazo mantido.
    """
    processo = get_object_or_404(
        Processo.objects.para_listagem().prefetch_related(
            Prefetch(
                "acompanhamentos",
                # Fase 26 — `select_related` dentro do
                # PRÓPRIO queryset do prefetch: join, não N+1 (convenções do projeto,
                # "derivadas de histórico nunca em consulta por linha").
                # `processo_detalhe.html` usa `reuniao.condutor` como proxy de
                # autoria de cada linha da timeline (Acompanhamento não tem
                # FK de autor própria; a atribuição real vive só no histórico
                # do simple_history, que SERIA uma consulta por linha).
                queryset=Acompanhamento.objects.select_related(
                    "reuniao", "reuniao__condutor"
                ).order_by("referencia_data", "id"),
                to_attr="timeline_completa",
            ),
        ),
        exercicio__ano=ano,
        item_pca=item_pca,
    )
    anterior = None
    for item in processo.timeline_completa:
        item.prazo_anterior = anterior
        item.prazo_mudou = bool(
            item.prazo_prometido and anterior and item.prazo_prometido != anterior
        )
        item.prazo_mantido = bool(
            item.prazo_prometido and anterior and item.prazo_prometido == anterior
        )
        if item.prazo_prometido:
            anterior = item.prazo_prometido
        # A MESMA frase institucional do relatório de
        # movimentação (`frase_compromisso`) na timeline do
        # detalhe do processo. `item.processo = processo` evita uma segunda
        # query ao FK — mesmo truque de `compromisso_vigente()`.
        #
        # `processo` já vem de `para_listagem()`
        # (linha ~1244 acima), logo já está anotado com `prazo_inicial`;
        # `_resolver_prazo_inicial` (relatorio_movimentacao.py) encontra
        # essa anotação em `item.processo.prazo_inicial` sem nenhuma
        # consulta extra por linha da timeline — nenhum `Subquery`/`annotate`
        # adicional é necessário aqui (diferente de `_bloco_adiados`, que
        # atravessa N processos DISTINTOS e por isso precisa da própria
        # anotação em lote).
        if item.prazo_prometido:
            item.processo = processo
            item.frase_compromisso = frase_compromisso(item)
        else:
            item.frase_compromisso = ""
    processo.historico_prazos = [
        item for item in processo.timeline_completa if item.prazo_prometido is not None
    ]
    return processo


# A tabela "Acompanhamentos e prazos" da ficha mostra por
# padrão só os TIMELINE_RESUMIDA mais recentes (mais novo primeiro); com
# `?acompanhamentos=todos` mostra tudo. Constante de módulo para o teste
# poder criar exatamente TIMELINE_RESUMIDA + 2 acompanhamentos sem número
# mágico duplicado.
TIMELINE_RESUMIDA = 5


def contexto_timeline(request, processo, querystring_tabela_atual):
    """Fatia/inverte `timeline_completa` (já em memória,
    Prefetch de `_carregar_processo_modal`, ordem cronológica CRESCENTE
    necessária ao laço de `prazo_anterior` acima) SEM nenhuma consulta nova
    (convenções do projeto, Desempenho: derivadas de histórico nunca em consulta
    por linha). `url_ver_mais`/`url_ver_menos` reaproveitam a MESMA
    querystring canônica que `detalhe_processo_view` já calcula
    (`querystring_tabela_atual`, fonte única de "estado idêntico à tabela") — nunca concatenação de string crua, sempre
    `QueryDict`/`urlencode` (Ver mais soma `acompanhamentos=todos`; Ver
    menos é a MESMA querystring canônica, que já nunca inclui
    `acompanhamentos` porque `querystring_tabela` só reserializa a
    allowlist conhecida)."""
    timeline_total = len(processo.timeline_completa)
    mostrar_todos = request.GET.get("acompanhamentos") == "todos"
    timeline_exibida = list(reversed(processo.timeline_completa))
    if not mostrar_todos:
        timeline_exibida = timeline_exibida[:TIMELINE_RESUMIDA]
    timeline_ocultos = timeline_total - len(timeline_exibida)

    base = reverse(
        "pca:detalhe_processo", args=[processo.exercicio.ano, processo.item_pca]
    )
    ancora = "#acompanhamentos"
    qd_ver_mais = (
        QueryDict(querystring_tabela_atual, mutable=True)
        if querystring_tabela_atual
        else QueryDict(mutable=True)
    )
    qd_ver_mais["acompanhamentos"] = "todos"
    url_ver_mais = f"{base}?{qd_ver_mais.urlencode()}{ancora}"
    url_ver_menos = (
        f"{base}?{querystring_tabela_atual}{ancora}"
        if querystring_tabela_atual
        else f"{base}{ancora}"
    )
    return {
        "timeline_exibida": timeline_exibida,
        "timeline_total": timeline_total,
        "timeline_ocultos": timeline_ocultos,
        "url_ver_mais": url_ver_mais,
        "url_ver_menos": url_ver_menos,
    }


def _processo_nao_encontrado(request, ano, item_pca):
    """404 com copy própria para item inexistente
    num exercício. `_carregar_processo_modal` levanta `Http404` via
    `get_object_or_404`; este helper devolve a mesma resposta que
    `detalhe_view` (removida na Fase 14) devolvia antes de a rota de
    detalhe deixar de existir — recuperada quase verbatim de
    `git show 0e5a228^:apps/pca/templates/pca/processo_nao_encontrado.html`.
    Fase 26 — chamado a partir de `pca:detalhe_processo` e
    `pca:editar_processo` (`apps/pca/views_processo.py`), reaproveitado sem
    mudança de corpo.
    """
    resposta = render(
        request,
        "pca/processo_nao_encontrado.html",
        {
            "item_pca": item_pca,
            "ano": ano,
            "querystring_volta": querystring_filtros(request.GET),
        },
        status=404,
    )
    resposta["Cache-Control"] = "private, no-store"
    return resposta


# Fase 26 — `editar_processo_view`/
# `criar_processo_view`/`registrar_promessa_view` migraram para
# `apps/pca/views_processo.py` como `editar_processo_view`/
# `criar_processo_view`/`acompanhamento_modal_view`. Templates
# antigos apagados: `_form_editar_processo.html`, `processo_modal_criar.html`,
# `_form_criar_processo.html`.


# Fase 26 — `buscar_processo_por_item_view` (F5/F7, busca global
# empilhada sobre o `#modal` de `shell.html`) apagada: a casca do padrão DSGov não
# tem essa superfície (`dsgov/_header.html` não expõe campo de busca,
# ficou sem implementação porque o partial é congelado e não deveria ganhar
# um). Zero consumidor de template desde que `shell.html` saiu (26-06,
# `grep` confirmado). `pca:buscar_processo_por_item`/
# `_busca_processo_resultado.html` saíram junto. Fase 28 —
# `q_busca_ampla` (o filtro `q` que sobrou desta remoção) foi por sua vez
# substituído por `apps.pca.busca.aplicar_busca`, que hoje
# alimenta tanto `/tabela` quanto a nova `/busca` (`views_busca.py`).


def _condicao_calendario(processo):
    """Fase 17 — a MESMA convenção `(eixo, valor)`
    que `apps/pca/kpis.py`/a rosca do dashboard já usam: um
    processo tem exatamente UMA condição — Cancelado (eixo Estado) se
    `estado=CANCELADO`, independente da `situacao` gravada; senão, a
    situação EFETIVA (`situacao_efetiva`, correção-na-leitura nunca a
    coluna `situacao` crua). `processo` vem sempre de `queryset_filtrado()`
    (via `para_listagem()`), que já anota `situacao_efetiva`."""
    if processo.estado == Estado.CANCELADO:
        return ("estado", Estado.CANCELADO.value)
    return ("situacao", processo.situacao_efetiva)


def _condicoes_presentes(eventos):
    """Condições distintas presentes numa lista de eventos de um dia, na
    ordem de `ORDEM_ROSCA` — nunca na ordem de inserção. Mesma ordem
    canônica que alimenta a rosca do dashboard, para o
    marcador compacto do calendário literal não inventar uma terceira
    ordem. Substitui `_status_presentes` (Fase 17, migração do
    calendário para o espaço de 5 condições).

    (`telas/calendario.md`) — devolve uma lista de DICTS
    (`eixo`/`valor`/`rotulo`/`classe`), nunca tuplas: o template nunca faz
    lookup de classe/rótulo sozinho."""
    presentes = {_condicao_calendario(evento["processo"]) for evento in eventos}
    resultado = []
    for eixo, valor, rotulo in ORDEM_ROSCA:
        chave = (eixo, valor.value if hasattr(valor, "value") else valor)
        if chave in presentes:
            resultado.append(
                {
                    "eixo": chave[0],
                    "valor": chave[1],
                    "rotulo": rotulo,
                    "classe": CLASSE_CONDICAO_CALENDARIO[chave],
                }
            )
    return resultado


def _evento(processo, data_fora_exercicio=False):
    """Um evento do calendário, com a classe/rótulo de
    condição JÁ resolvidos (o `br-tag status` de `_calendario_grade.html`
    nunca faz lookup sozinho). Substitui os literais `{"processo":
    processo, "data_fora_exercicio": ...}` espalhados por
    `_contexto_calendario`."""
    chave = _condicao_calendario(processo)
    return {
        "processo": processo,
        "data_fora_exercicio": data_fora_exercicio,
        "classe_condicao": CLASSE_CONDICAO_CALENDARIO[chave],
        "rotulo_condicao": ROTULO_CONDICAO_CALENDARIO[chave],
    }


def _celula_dia(dia, numero_mes, eventos_por_dia, get, limite):
    """Uma célula da grade (dia/semana), com contador e condições compactas
    — `eventos_por_dia` já cobre o ano inteiro, então o
    filtro `do_mes` é o que decide se o dia pertence a este mês ou é
    preenchimento da semana.

    Acrescenta `hoje` (dia corrente) e `url` (drill-down
    exato por dia via `filtros.dia_calendario`, reaproveitado pelo número
    do dia da visão anual e pelo "+n" da visão mensal).

    Fase 28 — `limite` (1 na grade anual, 3 na
    mensal, os dois chamadores de `_grade_mensal` já sabem qual visão
    estão montando) centraliza o corte de itens visíveis EM PYTHON, nunca
    em `|slice` espalhado nos templates: `eventos_visiveis`/
    `eventos_ocultos` substituem o `|slice:":3"`/`total|add:"-3"` que só a
    visão mensal tinha antes."""
    do_mes = dia.month == numero_mes
    eventos = eventos_por_dia.get(dia, []) if do_mes else []
    return {
        "data": dia,
        "do_mes": do_mes,
        "hoje": dia == localdate(),
        "eventos": eventos,
        "eventos_visiveis": eventos[:limite],
        "eventos_ocultos": max(0, len(eventos) - limite),
        "total": len(eventos),
        "condicoes_presentes": _condicoes_presentes(eventos),
        "url": f"{reverse('pca:tabela')}?{querystring_filtros(get, dia_calendario=dia.isoformat())}",
    }


# Fase 28 — o parsing/validação de token migrou para
# `apps.pca.filtros` (fonte única, reaproveitada por `queryset_filtrado`/
# `q_condicao_legenda` para o "+n" do calendário abrir a MESMA população em
# `/tabela`). `ORDEM_CONDICOES` continua exportado daqui (nome histórico,
# `apps/pca/tests/test_calendario.py` importa de `apps.pca.views`) — mesmo
# conteúdo de `ORDEM_ROSCA` reduzido a `(eixo, valor)`, agora um simples
# alias de `filtros.ORDEM_CONDICOES_LEGENDA`.
ORDEM_CONDICOES = ORDEM_CONDICOES_LEGENDA


def _resolver_condicao_legenda(get):
    """Lê `?condicao_legenda=` (multivalorado; chave RENOMEADA de
    `status_legenda` — parâmetro do calendário, hoje TAMBÉM um parâmetro
    canônico de `filtros.PARAMETROS_FILTRO`) e devolve
    `(conjunto_ativo, tokens_na_ordem_de_ORDEM_CONDICOES)`. Delega por
    completo a `apps.pca.filtros.resolver_condicao_legenda` — mantém aqui
    só a leitura do `get`, para `views.py` continuar dono só da MONTAGEM da
    legenda visual (apresentação), nunca de uma segunda implementação do
    parsing de token."""
    return resolver_condicao_legenda(get.getlist("condicao_legenda"))


def _grade_mensal(ano, numero_mes, eventos_por_dia, get, *, limite):
    """Semanas (domingo a sábado) de um mês, cada uma com 7 células —
    mesma forma que `semanas_calendario` sempre teve, reaproveitada tanto
    pela visão mensal quanto pelos 12 mini-calendários da visão anual, sem
    duplicar o for-loop e sem consulta nova (opera só sobre
    `eventos_por_dia`, já materializado). `get` repassado a `_celula_dia`
para montar `celula.url`.

    Fase 28 — `Calendar.monthdatescalendar` devolve
    4, 5 OU 6 semanas conforme o mês/ano, NUNCA sempre 6: completa com
    semanas adicionais REAIS (continuação cronológica — a próxima semana
    começa no dia seguinte ao último dia já listado, nunca uma data
    inventada fora de sequência) até o total ser exatamente 6 (42
    células), inclusive fevereiro. `_celula_dia` já zera `eventos` quando
    `not do_mes` — as células de preenchimento nunca repetem eventos de
    meses vizinhos, mesma garantia de sempre. `limite`: 1 para a
    grade anual, 3 para a mensal."""
    semanas_datas = Calendar(firstweekday=6).monthdatescalendar(ano, numero_mes)
    while len(semanas_datas) < 6:
        ultimo_dia = semanas_datas[-1][-1]
        semanas_datas.append([ultimo_dia + timedelta(days=deslocamento) for deslocamento in range(1, 8)])
    return [
        [_celula_dia(dia, numero_mes, eventos_por_dia, get, limite) for dia in semana]
        for semana in semanas_datas
    ]


def _contexto_calendario(request):
    """Materializa o conjunto filtrado uma vez nas leituras anual e mensal."""
    get = request.GET
    filtros = filtros_ativos(get)
    exercicio = filtros["exercicio"]
    visao = get.get("visao") if get.get("visao") in {"mensal", "anual"} else "anual"
    condicao_legenda_ativos, condicao_legenda_tokens = _resolver_condicao_legenda(get)
    try:
        mes_solicitado = int(get.get("mes_calendario", ""))
    except (TypeError, ValueError):
        mes_solicitado = None
    if mes_solicitado not in MESES:
        mes_solicitado = None
    if mes_solicitado is None:
        # Gj7 — `filtros["mes"]` virou lista (multi-seleção).
        # Só assume o mês do filtro quando exatamente um mês real (sem a
        # sentinela "sem_mes") está selecionado; do contrário cai no mesmo
        # padrão de sempre (mês corrente do exercício vigente, ou janeiro).
        meses_reais_selecionados = [
            valor for valor in filtros["mes"] if valor != SENTINEL_SEM_MES
        ]
        if len(meses_reais_selecionados) == 1:
            mes_solicitado = meses_reais_selecionados[0]
        elif exercicio and exercicio.ano == localdate().year:
            mes_solicitado = localdate().month
        else:
            mes_solicitado = 1

    # Fase 28 — ordem estável (`item_pca`/`id`) ANTES
    # do loop que popula `eventos_por_dia`: garante que os itens visíveis
    # de cada célula (limite 1 na anual, 3 na mensal) sejam sempre os
    # mesmos, na mesma ordem, entre requisições.
    processos = list(
        queryset_filtrado(request)
        .select_related("origem", "origem__exercicio")
        .order_by("item_pca", "id")
    )
    if condicao_legenda_ativos != set(ORDEM_CONDICOES):
        # Narrowing em Python sobre a lista já autorizada pelo
        # queryset filtrado (mesmo padrão de bucketing desta função);
        # nenhuma consulta nova, filtro local só do calendário.
        processos = [
            p for p in processos if _condicao_calendario(p) in condicao_legenda_ativos
        ]
    processos_por_mes = {numero: [] for numero in MESES}
    eventos_por_dia = {}
    sem_dia_por_mes = {numero: [] for numero in MESES}
    sem_mes_eventos = []

    for processo in processos:
        # Fase 11 — o calendário posiciona pela mesma
        # identidade única de avaliação de prazo que rege atraso/dias/
        # remarcações: `prazo_efetivo` (promessa vigente, com
        # fallback ao prazo de Planejamento). `data_prevista_conclusao`
        # nunca mais escolhe o dia — tirou dela qualquer papel de
        # regra, ela só descreve a previsão de conclusão da contratação.
        data_exata = processo.prazo_efetivo
        if data_exata and data_exata.year == exercicio.ano:
            evento = _evento(processo, False)
            eventos_por_dia.setdefault(data_exata, []).append(evento)
            processos_por_mes[data_exata.month].append(processo)
        elif processo.mes_previsto in processos_por_mes:
            evento = _evento(processo, bool(data_exata))
            sem_dia_por_mes[processo.mes_previsto].append(evento)
            processos_por_mes[processo.mes_previsto].append(processo)
        else:
            sem_mes_eventos.append(_evento(processo, bool(data_exata)))

    def agrupamento(numero, rotulo, itens, *, eventos=None):
        soma = sum((p.valor_estimado or Decimal("0")) for p in itens)
        return {
            "numero": numero,
            "rotulo": rotulo,
            "processos": itens,
            "eventos": eventos if eventos is not None else [
                _evento(processo, False) for processo in itens
            ],
            "total": len(itens),
            "soma": soma,
        }

    meses = [
        agrupamento(numero, NOMES_MES[numero], processos_por_mes[numero])
        for numero in MESES
    ]
    sem_mes = agrupamento(
        None,
        "Sem mês previsto",
        [evento["processo"] for evento in sem_mes_eventos],
        eventos=sem_mes_eventos,
    )
    semanas_calendario = _grade_mensal(
        exercicio.ano, mes_solicitado, eventos_por_dia, get, limite=3
    )

    def querystring_calendario(*, visao_destino, mes_destino=None):
        parametros = QueryDict(querystring_filtros(get), mutable=True)
        parametros["visao"] = visao_destino
        if mes_destino in MESES:
            parametros["mes_calendario"] = str(mes_destino)
        else:
            parametros.pop("mes_calendario", None)
        if condicao_legenda_tokens:
            parametros.setlist("condicao_legenda", condicao_legenda_tokens)
        return parametros.urlencode()

    # Grade anual literal: 12 mini-calendários derivados
    # do MESMO `eventos_por_dia` já materializado (cobre o ano inteiro),
    # nenhuma consulta nova por mês. `querystring_abrir` nasce só de
    # `querystring_calendario()`, nunca de `request.GET` cru (T-L1O-01).
    meses_grade = [
        {
            "numero": numero,
            "rotulo": NOMES_MES[numero],
            "semanas": _grade_mensal(exercicio.ano, numero, eventos_por_dia, get, limite=1),
            "querystring_abrir": querystring_calendario(
                visao_destino="mensal", mes_destino=numero
            ),
        }
        for numero in MESES
    ]

    # Uma entrada por condição de `ORDEM_ROSCA`, serve
    # TANTO à legenda informativa (não clicável) quanto ao `br-select
    # multiple` de situação do formulário único (`token` no MESMO formato
    # `f"{eixo}:{valor}"` que `_resolver_condicao_legenda` já entende).
    # Substitui `legenda_status`/`querystring_condicao_legenda` (a legenda
    # deixou de ser clicável — isolar/acumular agora só via o form GET).
    condicoes_calendario = [
        {
            "eixo": eixo,
            "valor": valor.value if hasattr(valor, "value") else valor,
            "token": f"{eixo}:{valor.value if hasattr(valor, 'value') else valor}",
            "rotulo": rotulo,
            "classe": CLASSE_CONDICAO_CALENDARIO[
                (eixo, valor.value if hasattr(valor, "value") else valor)
            ],
            "marcado": (
                eixo,
                valor.value if hasattr(valor, "value") else valor,
            ) in condicao_legenda_ativos,
        }
        for eixo, valor, rotulo in ORDEM_ROSCA
    ]

    # Preserva no formulário único QUALQUER outro filtro
    # ativo (uo/tipo/categoria/situação/mês/atrasado/etc.) que o formulário
    # não gerencia diretamente; EXCETO "exercicio", que já tem controle
    # próprio no formulário (incluí-lo aqui duplicaria o campo). Mesmo
    # padrão de `apps/pca/views.py::exportar_view`'s `filtros_hidden`.
    querystring_atual = QueryDict(querystring_filtros(get))
    filtros_ocultos_calendario = [
        (chave, valor)
        for chave in PARAMETROS_FILTRO
        if chave != "exercicio"
        for valor in querystring_atual.getlist(chave)
    ]

    return {
        "meses": meses,
        "meses_grade": meses_grade,
        "sem_mes": sem_mes,
        "sem_dia_do_mes": agrupamento(
            mes_solicitado,
            "Sem dia definido",
            [evento["processo"] for evento in sem_dia_por_mes[mes_solicitado]],
            eventos=sem_dia_por_mes[mes_solicitado],
        ),
        "semanas_calendario": semanas_calendario,
        "visao_calendario": visao,
        "mes_calendario": mes_solicitado,
        "mes_calendario_rotulo": NOMES_MES[mes_solicitado],
        # Ajuste de escopo do usuário (09/09/2026): a
        # navegação de um clique entre meses (Mês anterior/Próximo mês)
        # PERMANECE na visão mensal, ao lado do título — a proposta do
        # plano de eliminá-la em favor do `br-select` de mês do formulário
        # único NÃO foi aceita.
        "mes_anterior": mes_solicitado - 1 if mes_solicitado > 1 else None,
        "mes_seguinte": mes_solicitado + 1 if mes_solicitado < 12 else None,
        "querystring_mes_anterior": querystring_calendario(
            visao_destino="mensal", mes_destino=mes_solicitado - 1
        ) if mes_solicitado > 1 else "",
        "querystring_mes_seguinte": querystring_calendario(
            visao_destino="mensal", mes_destino=mes_solicitado + 1
        ) if mes_solicitado < 12 else "",
        "condicoes_calendario": condicoes_calendario,
        "condicao_legenda_ativos": condicao_legenda_ativos,
        "condicao_legenda_tokens": condicao_legenda_tokens,
        "filtros_ocultos_calendario": filtros_ocultos_calendario,
        "querystring_mensal": querystring_calendario(
            visao_destino="mensal", mes_destino=mes_solicitado
        ),
        "querystring_anual": querystring_calendario(visao_destino="anual"),
        "filtros": filtros,
        "tags": tags_ativas(get),
        "total_filtrado": len(processos),
        "soma_filtrada": sum(mes["soma"] for mes in meses) + sem_mes["soma"],
        "total_geral": Processo.objects.filter(exercicio=exercicio).count()
        if exercicio
        else 0,
        "exercicio": exercicio,
        "querystring_filtros": querystring_filtros(get),
        "htmx_alvo": "calendario-grade",
        # (A04/A18) — ver comentário equivalente em
        # resumo_uo_view; `trilha_padrao` já devolve trilha de 1 item (sem
        # link) quando `exercicio` é `None`, nunca falha.
        "trilha": navegacao.trilha_padrao(exercicio, "Calendário"),
        "nome_tela": "Calendário",
    }


# Fase 26 — `_request_com_filtros_transportados`/
# `_destinos_transicao_manual`/`_contexto_modal_transicao`/
# `_renderizar_erro_transicao` (o modal universal de transição, Fase 17, `_modal_transicao.html`) apagados: seu único consumidor de template
# era `_tabela_linha_legado.html` (edição inline, saiu junto com
# `editar_campo_view` nesta mesma frente). Alterar situação é hoje só
# `pca:transicao_processo` (`processo_transicao.html`, página
# própria com aviso da consequência).


@permission_required("pca.view_acompanhamento", raise_exception=True)
def calendario_view(request):
    """Calendário de leitura sobre o queryset filtrado único, como grade de
    7 colunas (`telas/calendario.md`) nas visões anual
    (12 cards) e mensal (1 card). `_contexto_calendario` (bucketização,
    condição da legenda, querystrings, `condicoes_calendario` já com
    classe/rótulo pré-computados) permanece a única fonte de contexto —
    esta view só ajusta a `trilha` para o formato da casca do padrão DSGov.
    """
    # QA 30/09 (dominio nº11) — sem exercício aberto, `_contexto_calendario`
    # desreferencia `exercicio.ano` sem checar `None`; nunca monta o
    # contexto pesado nesse cenário.
    if filtros_ativos(request.GET)["exercicio"] is None:
        return render(
            request,
            "pca/sem_exercicio_aberto.html",
            {
                "nome_tela": "Calendário",
                "trilha": navegacao.trilha_padrao(None, "Calendário"),
            },
        )
    contexto = _contexto_calendario(request)
    # `navegacao.trilha_padrao` (usada por
    # `_contexto_calendario`) já devolve tuplas `(rótulo, url|None)`, o
    # contrato de `dsgov/_breadcrumb.html`; nenhum ajuste extra necessário
    # aqui (a sobrescrita anterior descartava o ancestral "PCA <ano>").
    resposta = render(request, "pca/calendario.html", contexto)
    # Pitfall 16 — nunca cacheável na borda.
    resposta["Cache-Control"] = "private, no-store"
    return resposta


def redirecionar_kanban_view(request):
    """(Fase 14.1) — o kanban deixou de existir como ferramenta; `/kanban`
    responde 301 permanente para `/tabela`, preservando os filtros VALIDADOS
    (nunca a querystring crua.1-01/ evita open redirect e reflected
    querystring). Bookmarks, links compartilhados e o PWA devem resolver
    `/tabela` diretamente na próxima visita, daí 301 e não 302."""
    destino = reverse("pca:tabela")
    filtros = querystring_filtros(request.GET)
    if filtros:
        destino = f"{destino}?{filtros}"
    return HttpResponsePermanentRedirect(destino)


# Fase 26 — `preparar_transicao_view`/`confirmar_transicao_view`
# (rotas `transicao/preparar`/`transicao/confirmar`, o modal universal de
# transição da Fase 17) apagadas junto com `_modal_transicao.html`:
# zero consumidor de template restante (só `_tabela_linha_legado.html` as
# usava). `pca:transicao_processo` é a única forma de alterar situação.


def _origem_virada():
    """O exercício ABERTO mais recente — a ÚNICA origem válida de uma
    virada (QA 30/09, fuzz A1/B6/fluxos nº10)."""
    return (
        Exercicio.objects.filter(situacao=SituacaoExercicio.ABERTO)
        .order_by("-ano")
        .first()
    )


def _validar_virada(ano_destino):
    """Valida origem/destino SEM nenhuma escrita — chamada em todo GET e
    POST, antes de qualquer leitura/escrita de rascunho. `ano_destino`
    só é aceito quando é exatamente `origem.ano + 1` (origem = exercício
    ABERTO mais recente); qualquer outro valor, ou a ausência de um
    exercício ABERTO, é 404."""
    try:
        destino = int(ano_destino)
    except (TypeError, ValueError):
        raise Http404("Exercício de destino inválido.")
    origem = _origem_virada()
    if origem is None:
        raise Http404("Nenhum exercício aberto está disponível para iniciar a virada.")
    if destino != origem.ano + 1:
        raise Http404(f"O exercício de destino da virada precisa ser {origem.ano + 1}.")
    if Exercicio.objects.filter(ano=destino).exists():
        raise Http404("O exercício de destino já existe.")
    return origem


def _rascunho_existente(origem, ano_destino):
    return RascunhoVirada.objects.filter(
        exercicio_origem=origem, ano_destino=ano_destino, confirmado_em__isnull=True
    ).first()


def _criar_rascunho(origem, ano_destino, usuario):
    """Cria o rascunho + as linhas — único ponto de escrita do wizard antes
    da confirmação final (`services.confirmar_virada`). Chamada SÓ a
    partir de um POST `acao=iniciar` explícito na etapa 1 (QA 30/09, fuzz
    B6/fluxos nº10: um GET isolado nunca grava nada)."""
    try:
        with transaction.atomic():
            rascunho = RascunhoVirada.objects.create(
                exercicio_origem=origem, ano_destino=ano_destino, criado_por=usuario
            )
            fontes = Processo.objects.filter(exercicio=origem).order_by("item_pca")
            RascunhoItemVirada.objects.bulk_create(
                [
                    RascunhoItemVirada(
                        rascunho=rascunho,
                        processo_origem=processo,
                        ordem=processo.item_pca,
                        selecionado=False,
                        valor_estimado_editado=processo.valor_estimado,
                        mes_previsto_editado=processo.mes_previsto,
                    )
                    for processo in fontes
                ]
            )
    except IntegrityError:
        rascunho = RascunhoVirada.objects.get(
            exercicio_origem=origem, ano_destino=ano_destino, confirmado_em__isnull=True
        )
    return rascunho


def _contexto_virada(request, rascunho, pagina=1):
    linhas = rascunho.itens.select_related("processo_origem", "processo_origem__unidade_organizacional")
    paginador = Paginator(linhas, TAMANHO_VIRADA_PAGINA)
    pagina_obj = paginador.get_page(pagina)
    return {
        "rascunho": rascunho,
        "exercicio_origem": rascunho.exercicio_origem,
        "pagina": pagina_obj,
        "paginador": paginador,
        "total_selecionados": rascunho.itens.filter(selecionado=True).count(),
        "meses": tuple((n, NOMES_MES[n]) for n in MESES),
    }


def _linhas_selecionadas_virada(rascunho):
    return rascunho.itens.filter(selecionado=True).select_related(
        "processo_origem", "processo_origem__unidade_organizacional"
    )


@permission_required("pca.gerir_exercicio", raise_exception=True)
def virada_view(request, ano_destino):
    """Etapa 1 do wizard de virada — Selecionar.

    Sem HTMX por linha (nem `virada_linha_view`/`virada_selecionar_pagina_view`,
    apagadas — substituídas por este único endpoint): um POST processa a
    PÁGINA inteira de uma vez, comparando `item_pagina` (hidden, TODOS os
    ids renderizados nesta página) com `selecionados` (só os marcados no
    envio) para marcar/desmarcar em lote. `acao=avancar` move para a etapa
    2 (`pca:virada_ajustar`); `acao=aplicar` mantém nesta mesma etapa (para
    o usuário revisar antes de trocar de página).

    QA 30/09 (fuzz B6/fluxos nº10) — `_validar_virada` roda ANTES de
    qualquer leitura/escrita de rascunho, para GET e POST igualmente; um
    rascunho só nasce a partir de um POST `acao=iniciar` explícito. Em
    qualquer outro caso sem rascunho (inclusive todo GET), a etapa 1
    renderiza a confirmação `virada_iniciar.html` e PARA — nunca chega a
    tocar `RascunhoVirada`/`RascunhoItemVirada`.
    """
    origem = _validar_virada(ano_destino)
    rascunho = _rascunho_existente(origem, ano_destino)
    if rascunho is None:
        if request.method == "POST" and request.POST.get("acao") == "iniciar":
            rascunho = _criar_rascunho(origem, ano_destino, request.user)
        else:
            return render(
                request,
                "pca/virada_iniciar.html",
                {
                    "exercicio_origem": origem,
                    "ano_destino": ano_destino,
                    "contagem_itens": Processo.objects.filter(exercicio=origem).count(),
                    "trilha": [
                        ("Gerenciar exercícios", reverse("pca:gerenciar_exercicios")),
                        (f"Iniciar virada {origem.ano} → {ano_destino}", None),
                    ],
                },
            )
    pagina_num = request.POST.get("pagina") or request.GET.get("pagina", 1)
    if request.method == "POST":
        ids_pagina = [
            item
            for item in request.POST.getlist("item_pagina")
            if item.isdecimal() and len(item) <= 6
        ]
        ids_marcados = set(request.POST.getlist("selecionados"))
        with transaction.atomic():
            rascunho.itens.filter(processo_origem__item_pca__in=ids_pagina).update(
                selecionado=False
            )
            ids_para_marcar = [item for item in ids_pagina if item in ids_marcados]
            if ids_para_marcar:
                rascunho.itens.filter(
                    processo_origem__item_pca__in=ids_para_marcar
                ).update(selecionado=True)
        if request.POST.get("acao") == "avancar":
            return redirect("pca:virada_ajustar", ano_destino)
        messages.success(request, "Seleção desta página aplicada.")
    contexto = _contexto_virada(request, rascunho, pagina_num)
    return render(request, "pca/virada_selecionar.html", contexto)


@permission_required("pca.gerir_exercicio", raise_exception=True)
def virada_ajustar_view(request, ano_destino):
    """Etapa 2 do wizard — Ajustar: só os itens `selecionado=True`,
    "Editar" abre `virada_item_formulario.html` por item (ModelForm,
    `ViradaItemForm`). "Avançar" é um POST — nada a persistir aqui além do
    que a etapa de edição por item já salvou, mas o clique continua sendo
    um POST real (nunca troca de painel em JS)."""
    origem = _validar_virada(ano_destino)
    rascunho = _rascunho_existente(origem, ano_destino)
    if rascunho is None:
        raise Http404("Inicie a virada pela etapa 1 antes de continuar.")
    if request.method == "POST":
        return redirect("pca:virada_revisar", ano_destino)
    linhas = _linhas_selecionadas_virada(rascunho).order_by("ordem")
    paginador = Paginator(linhas, TAMANHO_VIRADA_PAGINA)
    pagina_obj = paginador.get_page(request.GET.get("pagina", 1))
    contexto = {
        "rascunho": rascunho,
        "exercicio_origem": rascunho.exercicio_origem,
        "pagina": pagina_obj,
        "paginador": paginador,
        "total_selecionados": linhas.count(),
    }
    return render(request, "pca/virada_ajustar.html", contexto)


@permission_required("pca.gerir_exercicio", raise_exception=True)
def virada_item_editar_view(request, ano_destino, item_pca):
    """Formulário da etapa "Ajustar": `ViradaItemForm` restringe
    os campos aceitos a `mes_previsto_editado`/`valor_estimado_editado` —
    nunca `selecionado`/`processo_origem`. Substitui a antiga
    `virada_campo_view` (edição POR CAMPO cru, sem `ModelForm`)."""
    origem = _validar_virada(ano_destino)
    rascunho = _rascunho_existente(origem, ano_destino)
    if rascunho is None:
        raise Http404("Inicie a virada pela etapa 1 antes de continuar.")
    linha = get_object_or_404(
        _linhas_selecionadas_virada(rascunho), processo_origem__item_pca=item_pca
    )
    if request.method == "POST":
        form = ViradaItemForm(request.POST, instance=linha)
        if form.is_valid():
            form.save()
            messages.success(request, "Item atualizado.")
            return redirect("pca:virada_ajustar", ano_destino)
    else:
        form = ViradaItemForm(instance=linha)
    return render(
        request,
        "pca/virada_item_formulario.html",
        {"form": form, "linha": linha, "rascunho": rascunho},
    )


@permission_required("pca.gerir_exercicio", raise_exception=True)
def virada_revisar_view(request, ano_destino):
    """Etapa 3 do wizard — Revisar e concluir: totais + tabela
    final read-only; "Concluir virada" é um `<form>` que faz POST direto a
    `pca:virada_confirmar` (`services.confirmar_virada`, inalterado)."""
    origem = _validar_virada(ano_destino)
    rascunho = _rascunho_existente(origem, ano_destino)
    if rascunho is None:
        raise Http404("Inicie a virada pela etapa 1 antes de continuar.")
    linhas = _linhas_selecionadas_virada(rascunho).order_by("ordem")
    paginador = Paginator(linhas, TAMANHO_VIRADA_PAGINA)
    pagina_obj = paginador.get_page(request.GET.get("pagina", 1))
    # quantizar_soma corrige o ruido de ponto flutuante do SUM() do SQLite (core/db.py).
    soma = quantizar_soma(
        linhas.aggregate(soma=Sum("valor_estimado_editado"))["soma"]
    ) or Decimal("0")
    contexto = {
        "rascunho": rascunho,
        "exercicio_origem": rascunho.exercicio_origem,
        "pagina": pagina_obj,
        "paginador": paginador,
        "total_selecionados": linhas.count(),
        "soma_selecionados": soma,
    }
    return render(request, "pca/virada_revisar.html", contexto)


@permission_required("pca.gerir_exercicio", raise_exception=True)
def virada_confirmacao_view(request, ano_destino):
    """Rota histórica — a etapa 3 do wizard vive em
    `pca:virada_revisar`; mantida só para `reverse()`/links antigos não
    quebrarem (o antigo fragmento de modal `_virada_modal_confirmacao.html`
    foi apagado)."""
    return redirect("pca:virada_revisar", ano_destino)


@permission_required("pca.gerir_exercicio", raise_exception=True)
def virada_confirmar_descarte_view(request, ano_destino):
    """Página de confirmação de descarte — substitui o antigo
    fragmento de modal; o POST real continua em `pca:virada_descartar`
    (inalterado)."""
    origem = _validar_virada(ano_destino)
    rascunho = _rascunho_existente(origem, ano_destino)
    if rascunho is None:
        raise Http404("Inicie a virada pela etapa 1 antes de continuar.")
    return render(
        request, "pca/virada_confirmar_descarte.html", {"rascunho": rascunho}
    )


@permission_required("pca.gerir_exercicio", raise_exception=True)
@require_POST
def virada_descartar_view(request, ano_destino):
    origem = _validar_virada(ano_destino)
    rascunho = _rascunho_existente(origem, ano_destino)
    if rascunho is None:
        raise Http404("Inicie a virada pela etapa 1 antes de continuar.")
    rascunho.itens.update(selecionado=False)
    for linha in rascunho.itens.select_related("processo_origem"):
        linha.valor_estimado_editado = linha.processo_origem.valor_estimado
        linha.mes_previsto_editado = linha.processo_origem.mes_previsto
        linha.save(update_fields=["valor_estimado_editado", "mes_previsto_editado"])
    messages.success(request, "Rascunho de virada descartado.")
    return redirect("pca:virada", ano_destino)


@permission_required("pca.gerir_exercicio", raise_exception=True)
@require_POST
def virada_confirmar_view(request, ano_destino):
    origem = _validar_virada(ano_destino)
    rascunho = _rascunho_existente(origem, ano_destino)
    if rascunho is None:
        raise Http404("Inicie a virada pela etapa 1 antes de continuar.")
    try:
        destino = services.confirmar_virada(rascunho_id=rascunho.pk, usuario=request.user)
    except (services.DestinoJaExiste, services.NenhumItemSelecionado, services.ViradaJaConfirmada):
        messages.error(
            request,
            "Não foi possível concluir a virada. Nenhum item foi copiado.",
        )
        return redirect("pca:virada_revisar", ano_destino)
    messages.success(request, f"Virada concluída — PCA {destino.ano} criado.")
    url = f"/?exercicio={destino.ano}"
    return HttpResponseClientRedirect(url) if request.htmx else HttpResponseRedirect(url)


def _pode_gerar_n1(user) -> bool:
    """Fase 40 (spec §0 "Acesso") — guarda MAIS ESTRITA que a virada
    (`pca.gerir_exercicio` sozinha, `@permission_required` acima): só
    superusuário COM a permissão vê/aciona "Gerar itens de N+1". Consumida
    por `gerar_n1_previa_view`/`gerar_n1_confirmar_view` e pelas duas
    entradas de tela (Prazos e Gerenciar exercícios)."""
    return bool(user.is_superuser and user.has_perm("pca.gerir_exercicio"))


def gerar_n1_previa_view(request, ano):
    """GET — prévia (spec §1/§3): classifica a população, nunca escreve.
    `previa()` é recalculada a cada requisição (barato — spec §2, uma
    projeção por chamada)."""
    if not _pode_gerar_n1(request.user):
        raise PermissionDenied
    exercicio = get_object_or_404(Exercicio, ano=ano)
    resultado = geracao_n1.previa(exercicio, hoje=localdate())
    ano_n1 = resultado.ano_destino
    cards = [
        {"rotulo": "Novos", "valor": numero(resultado.novos)},
        {"rotulo": "Já gerados", "valor": numero(resultado.ja_gerados)},
        {"rotulo": "Não entram", "valor": numero(resultado.nao_entram)},
        {"rotulo": "Valor dos novos", "valor": moeda(resultado.valor_novos)},
    ]
    return render(request, "pca/gerar_n1_previa.html", {
        "previa": resultado,
        "exercicio": exercicio,
        "ano_n1": ano_n1,
        "cards": cards,
        "trilha": [
            ("Gerenciar exercícios", reverse("pca:gerenciar_exercicios")),
            (f"Gerar itens de {ano_n1}", None),
        ],
    })


@require_POST
def gerar_n1_confirmar_view(request, ano):
    """POST — único ponto de escrita (spec §1). PRG: sucesso → tabela de
    N+1; nada a gerar → `messages.info` + volta para a própria prévia;
    catálogo incompleto (`Tipo` "Renovação"/"Vigente" ausente) → 400, sem
    escrever nada (a prévia já mostra o erro e desabilita o botão)."""
    if not _pode_gerar_n1(request.user):
        raise PermissionDenied
    exercicio = get_object_or_404(Exercicio, ano=ano)
    ano_n1 = exercicio.ano + 1
    try:
        resultado = geracao_n1.gerar(exercicio, request.user)
    except geracao_n1.CatalogoIncompleto as erro:
        return HttpResponseBadRequest("; ".join(erro.erros))
    except geracao_n1.ExercicioDestinoFechado as erro:
        messages.error(
            request,
            f"O exercício {erro.exercicio.ano} está fechado — reabra-o pelo fluxo "
            "existente antes de gerar os itens de N+1.",
        )
        return redirect("pca:gerar_n1", ano)
    if not resultado.criados:
        messages.info(
            request,
            f"Nada a gerar — todos os contratos já têm item em {ano_n1}.",
        )
        return redirect("pca:gerar_n1", ano)
    primeiro = min(processo.item_pca for processo in resultado.criados)
    ultimo = max(processo.item_pca for processo in resultado.criados)
    messages.success(
        request,
        f"{len(resultado.criados)} itens gerados no PCA {ano_n1} "
        f"(itens {primeiro}–{ultimo}).",
    )
    return redirect(f"{reverse('pca:tabela')}?exercicio={ano_n1}")


@permission_required("pca.gerir_exercicio", raise_exception=True)
def gerenciar_exercicios_view(request):
    # "Iniciar virada" só faz sentido a partir do exercício ABERTO mais
    # recente (`_validar_virada` exige `ano_destino == origem.ano + 1`,
    # origem = exercício ABERTO mais recente), e só quando o destino
    # (ano + 1) ainda não existe — a view de virada levanta 404 "exercício
    # de destino já existe" caso contrário.
    exercicios = list(Exercicio.objects.order_by("-ano"))
    ano_aberto_mais_recente = next(
        (e.ano for e in exercicios if e.situacao == SituacaoExercicio.ABERTO), None
    )
    ano_destino_virada = (
        ano_aberto_mais_recente + 1 if ano_aberto_mais_recente else None
    )
    if ano_destino_virada and Exercicio.objects.filter(ano=ano_destino_virada).exists():
        ano_destino_virada = None
    return render(request, "pca/gerenciar_exercicios.html", {
        "exercicios": exercicios,
        "ano_aberto_mais_recente": ano_aberto_mais_recente,
        "ano_destino_virada": ano_destino_virada,
        "pode_gerar_n1": _pode_gerar_n1(request.user),
        "trilha": [("Gerenciar exercícios", None)],
    })


@permission_required("pca.gerir_exercicio", raise_exception=True)
def encerrar_confirmar_view(request, ano):
    """Página de confirmação — substitui o antigo fragmento de
    modal do webcomponent (apagado)."""
    exercicio = get_object_or_404(Exercicio, ano=ano)
    return render(
        request,
        "pca/exercicio_confirmar_encerrar.html",
        {
            "exercicio": exercicio,
            "trilha": [
                ("Gerenciar exercícios", reverse("pca:gerenciar_exercicios")),
                (f"Encerrar {exercicio.ano}", None),
            ],
        },
    )


@permission_required("pca.gerir_exercicio", raise_exception=True)
@require_POST
def encerrar_view(request, ano):
    try:
        services.fechar_exercicio(ano=ano, usuario=request.user)
    except Exercicio.DoesNotExist:
        messages.error(request, f"Exercício {ano} não encontrado.")
        return redirect("pca:gerenciar_exercicios")
    except (services.ExercicioJaEncerrado, services.UltimoExercicioAberto):
        exercicio = get_object_or_404(Exercicio, ano=ano)
        return render(
            request,
            "pca/exercicio_confirmar_encerrar.html",
            {
                "exercicio": exercicio,
                "erro": "O exercício está desatualizado ou não pode ser encerrado.",
                "trilha": [
                    ("Gerenciar exercícios", reverse("pca:gerenciar_exercicios")),
                    (f"Encerrar {exercicio.ano}", None),
                ],
            },
        )
    messages.success(request, f"Exercício {ano} encerrado.")
    return redirect("pca:gerenciar_exercicios")


# Fase 26 — `_renderizar_sei`/`adicionar_sei_view`/
# `remover_sei_view` migraram para `apps/pca/views_processo.py`. Fase 29 — as duas views e suas rotas saíram por
# completo: números SEI só mudam pelo `ProcessoSEIFormSet` do fieldset
# Processo de `pca:editar_processo`; o detalhe é estritamente de leitura.


def _queryset_export(request, colunas_resolvidas=()):
    """O ÚNICO queryset dos downloads (Pitfall 16):
    `queryset_filtrado(request)` — nunca um filtro reimplementado, para o
    arquivo ser literalmente o mesmo conjunto visível nas três visões —
    mais `.prefetch_related("numeros_sei")` e
    `.select_related("tipo")` (a única FK de cadastro fora do
    select_related de `para_listagem()`; sem ela o export teria N+1).
    Sem paginação: o download leva o conjunto filtrado inteiro.

    Fase 28 (achado 1) — a MESMA ordenação da tabela
    (`_ordenar_para_tabela`) é aplicada aqui: sem isso, o arquivo podia
    divergir da ordem visível na tela sempre que o usuário tivesse
    ordenado por uma coluna (`?ordenar=`/`?dir=`).

    Fase 29 — `colunas_resolvidas` (já resolvidas
    pelo chamador, mesmo contrato de `tabela_view`) ativa
    `select_related("modalidade", "instrumento_contratual")` só quando a
    respectiva coluna foi de fato selecionada para o arquivo."""
    qs = queryset_filtrado(request).select_related("tipo").prefetch_related(
        "numeros_sei"
    )
    fks_selecionadas = [
        chave for chave in FKS_SELECT_RELATED_CONDICIONAL if chave in colunas_resolvidas
    ]
    if fks_selecionadas:
        qs = qs.select_related(*fks_selecionadas)
    return _ordenar_para_tabela(request, qs)


def _colunas_selecionadas_do_request(request):
    """Resolve o subconjunto de colunas do export a partir de `?colunas=`
    REPETIDO (Fase 28, achado 2 — mesmo contrato do Plano
    28-02: um `colunas=` por checkbox, nunca mais o comma-join do quick). Sem nenhum `?colunas=` no GET, delega ao resolvedor
    COMPARTILHADO (`apps.pca.colunas.colunas_selecionadas` — sessão >
    padrão da fase), o MESMO que a tela usa: o export legado
    deixa de ter um fallback hardcoded próprio (`PADRAO_EXPORT_LEGADO`,
    removido nesta migração).

    Fase com `?colunas=`, as chaves são
    validadas AQUI contra `exportacao.COLUNAS_POR_CHAVE` (o allowlist do
    EXPORT, não o da tela — inclui `data_inclusao_pca`, que a tela não
    oferece) e deduplicadas preservando a primeira ocorrência (mesmo contrato de `apps.pca.colunas._normalizar`). Se TODAS as chaves
    do GET forem inválidas/vazias (`?colunas=`, `?colunas=xyz-invalido`),
    o resultado filtrado fica vazio e cai no MESMO resolvedor
    compartilhado do caminho "sem `?colunas=`" — sessão > padrão da fase
    ("seleção inválida nunca produz tabela ou arquivo sem
    colunas"), nunca uma lista vazia repassada a `exportacao.
    _colunas_resolvidas`/`exportar_xlsx` (que antes disso derrubava com
    `ValueError: Invalid column index 0` em `get_column_letter(0)`, e no
    CSV produzia um arquivo silenciosamente vazio)."""
    vistas = set()
    chaves = []
    for chave in request.GET.getlist("colunas"):
        if chave in _COLUNAS_EXPORT_POR_CHAVE and chave not in vistas:
            vistas.add(chave)
            chaves.append(chave)
    # QA de segurança 30/09/2026 (achado M2) — `?colunas=` explícito também
    # precisa passar pelo mesmo gate de `pca.view_acompanhamento` que a tela
    # já aplica; sem isto, pedir a chave restrita diretamente no export
    # contornava o filtro.
    chaves = _filtrar_restritas(chaves, request)
    if chaves:
        return chaves
    return colunas_selecionadas(request)


def exportar_csv_view(request):
    """Download síncrono do CSV `;`/BOM UTF-8 (Pitfall 22). 149
    linhas não justificam fila de tarefas (discrição do
    planejador). Sessão válida garantida pelo LoginRequiredMiddleware
    global. `colunas` (R3) espelha o
    que a tela mostra no momento do clique. `exercicio` dá nome
    dinâmico ao arquivo pelo exercício efetivo dos filtros correntes."""
    exercicio = filtros_ativos(request.GET)["exercicio"]
    colunas_resolvidas = _colunas_selecionadas_do_request(request)
    resposta = exportar_csv(
        _queryset_export(request, colunas_resolvidas),
        colunas_resolvidas,
        exercicio=exercicio,
    )
    # Download nunca cacheável na borda.
    resposta["Cache-Control"] = "private, no-store"
    return resposta


def exportar_xlsx_view(request):
    """Download síncrono do XLSX com tipos nativos e SUM()
    (Pitfall 22). Mesmas premissas do CSV acima."""
    exercicio = filtros_ativos(request.GET)["exercicio"]
    colunas_resolvidas = _colunas_selecionadas_do_request(request)
    resposta = exportar_xlsx(
        _queryset_export(request, colunas_resolvidas),
        colunas_resolvidas,
        exercicio=exercicio,
    )
    # Download nunca cacheável na borda.
    resposta["Cache-Control"] = "private, no-store"
    return resposta


# Fase 26 — `criar_processo_view` migrou para
# `apps/pca/views_processo.py` (mesma allocação via `services.criar_processo`,
# agora validada por `ProcessoForm(criando=True)`); `processo_modal_criar.html`/
# `_form_criar_processo.html` apagados.


@permission_required("pca.view_acompanhamento", raise_exception=True)
def reuniao_listagem_view(request):
    """Fase 26 — lugar canônico de "Reuniões": a rota
    existia (`pca:criar_reuniao`), mas não havia listagem — o item do menu
    apontava direto para o formulário de criação.

    Reuniões são acompanhamento: `@permission_required
    pca.view_acompanhamento` (grupo `editor`; `criar_reuniao_view` já exige
    `pca.editar_pca`, que só o grupo `editor` tem — sem regressão)."""
    return render(
        request,
        "pca/reuniao_listagem.html",
        {
            "reunioes": Reuniao.objects.select_related("condutor").order_by("-data"),
            "trilha": [("Reuniões", None)],
        },
    )


@permission_required("pca.editar_pca", raise_exception=True)
def criar_reuniao_view(request):
    """Fase 26 — GET renderiza `reuniao_formulario.html`
    (`ReuniaoForm`); POST válido chama `services.criar_reuniao` (inalterado)
    e redireciona para `pca:reuniao_listagem` (nunca mais `pca:tabela`)."""
    trilha = [
        ("Reuniões", reverse("pca:reuniao_listagem")),
        ("Nova reunião", None),
    ]
    if request.method != "POST":
        form = ReuniaoForm()
        return render(
            request, "pca/reuniao_formulario.html", {"form": form, "trilha": trilha}
        )

    form = ReuniaoForm(request.POST)
    if not form.is_valid():
        return render(
            request, "pca/reuniao_formulario.html", {"form": form, "trilha": trilha}
        )

    exercicio_bruto = request.GET.get("exercicio")
    exercicio = (
        Exercicio.objects.filter(ano=exercicio_bruto).first()
        if exercicio_bruto and exercicio_bruto.isdecimal() and len(exercicio_bruto) <= 6
        else None
    )
    try:
        services.criar_reuniao(
            data=form.cleaned_data["data"],
            usuario=request.user,
            exercicio=exercicio,
            situacao=form.cleaned_data["situacao"],
        )
    except services.ExercicioFechado as erro:
        messages.error(request, str(erro))
        return redirect("pca:reuniao_listagem")
    except (ValueError, ValidationError) as erro:
        mensagem = (
            "; ".join(erro.messages)
            if isinstance(erro, ValidationError)
            else str(erro)
        )
        form.add_error(None, mensagem)
        return render(
            request, "pca/reuniao_formulario.html", {"form": form, "trilha": trilha}
        )
    messages.success(request, "Reunião criada.")
    return redirect("pca:reuniao_listagem")
