from calendar import Calendar
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import urlencode
import logging

from django.conf import settings
from django.core.paginator import Paginator
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Case, Count, F, IntegerField, Prefetch, Q, Sum, Value, When
from django.db.models.functions import ExtractQuarter
from django.db import IntegrityError, transaction
from django.http import (
    Http404,
    HttpResponse,
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
from core import graficos
from core.templatetags.dsgov import moeda, numero, percentual

logger = logging.getLogger(__name__)

# o mapa fechado de colunas de ?ordenar= vive em filtros.py, ao lado de
# ordenacao_valida() que o valida

TAMANHO_PAGINA = 20
TAMANHO_VIRADA_PAGINA = 25

# chave de sessão do estado canônico de /tabela; só grava se diferir
CHAVE_SESSAO_ESTADO_TABELA = "pca_estado_tabela"

# allowlist única da fronteira de confiança de edição do processo,
# consumida por ProcessoForm/views_processo.py. estado/situacao continuam
# fora — sempre por pca:transicao_processo; data_envio_gelic continua fora,
# campo congelado
CAMPOS_EDITAVEIS_PROCESSO = (
    "grau_prioridade",
    "mes_previsto",
    "data_recebimento_gelic",
    "data_prevista_conclusao",
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
    "situacao_sei",
    # justificativa_alteracao_prazo e justificativa_alteracao_email saem
    # da allowlist de edição: a primeira passa a pertencer a cada promessa
    # (Acompanhamento.evento)
    # bloco de execução contratual
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
)

# a cor semântica da rosca de situação vive em
# apps.pca.graficos_pca.MAPA_SITUACAO_STATUS/core.graficos.CORES_STATUS.
#
# "Distribuição por status" (ORDEM_ROSCA, usada por
# resumo_uo_view/calendario_view) lê estado/situacao_efetiva, nunca mais a
# coluna crua status: 5 fatias — Cancelados + as 4 situações dos ativos
ORDEM_ROSCA = (
    ("estado", Estado.CANCELADO, "Cancelado"),
    ("situacao", Situacao.CONCLUIDO, "Concluído"),
    ("situacao", Situacao.NO_PRAZO, "No prazo"),
    ("situacao", Situacao.EM_TRAMITACAO, "Em tramitação"),
    ("situacao", Situacao.ATRASADO, "Atrasado"),
)

# cores dos pontos de situação do calendário, na mesma ordem/chave
# (eixo, valor) de ORDEM_ROSCA, montado por zip, nunca hardcoded linha a
# linha; nenhuma condição compartilha cor com outra
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

# ordem de severidade intrínseca do "Perfil da carteira" no dashboard,
# usada só para o grupo "prioridade". Os demais grupos continuam ordenados
# por contagem (-total, nome): não têm nível intrínseco, só frequência.
# "Alto" precisa ser sempre o degrau mais escuro da rampa monocrômica
ORDEM_PRIORIDADE = {"Alto": 0, "Médio": 1, "Baixo": 2}


def _cabecalhos_ordenaveis(campo_atual, direcao_atual, colunas_resolvidas):
    """Resolve, no servidor, tudo que o cabeçalho da tabela precisa saber
    para ordenar: se a coluna é ordenável, se é a ativa, qual direção o
    próximo clique deve pedir, e o par seta/aria-sort.

    Fica aqui e não no template porque "inverter o sentido só na coluna já
    ativa" é regra, não apresentação. Itera colunas_resolvidas (lista de
    chaves resolvida por colunas_selecionadas); a ordem da lista recebida
    é a ordem de exibição das colunas, rótulo/tipo resolvidos via
    COLUNAS_POR_CHAVE."""
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
                # campo propagado para o filtro genérico exibir/atributo
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
    """Um href de drill-down por família de recorte da tabela /resumo-uo.
    uo_id=None (linha TOTAL) limpa o filtro de UO — uo é chave multivalor,
    então um override None vira lista vazia.

    Bloco META: hrefs meta/concluido_meta/no_prazo/fora_prazo recortam
    ATIVO & tipo in (Nova, Renovação), prazos consolidados. concluido
    (c/ Vigentes) fica intacto."""
    ativo = Estado.ATIVO.value
    id_nova = ids_tipo.get("nova contratacao")
    id_renovacao = ids_tipo.get("renovacao")
    id_vigente = ids_tipo.get("vigente")

    href_uo = querystring_filtros(get, uo=uo_id)

    return {
        "uo": href_uo,
        # "Total previsto" inclui ATIVO + CANCELADO: sem estado
        "total_previsto": href_uo,
        # "Cancelados"/"Ativos" ganham drill-down próprio
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
        # bloco META: Meta = ATIVO & (Nova|Renovação); as 4 colunas que a
        # decompõem acrescentam só a situacao
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
        # bloco ANÁLISE — "Concluído c/ Vigentes": sem recorte de tipo
        "concluido": querystring_filtros(
            get, uo=uo_id, estado=[ativo], situacao=[Situacao.CONCLUIDO]
        ),
    }


def resumo_uo_view(request):
    """Tela "Resumo por UO", semântica de foto atual. Consome o mesmo
    queryset_filtrado de /tabela: os números daqui nunca divergem dos de
    qualquer outra tela para o mesmo filtro — toda a regra de negócio vive
    em apps.pca.resumo_uo, nunca reimplementada aqui.

    Sem @permission_required, protegido só pelo LoginRequiredMiddleware
    global."""
    get = request.GET
    qs = queryset_filtrado(request)
    linhas, total = calcular_resumo_uo(qs)
    ids_tipo = ids_tipo_recorte()
    for linha in linhas:
        linha["hrefs"] = _hrefs_resumo_uo(get, ids_tipo, linha["uo_id"])
    total["hrefs"] = _hrefs_resumo_uo(get, ids_tipo, None)
    exercicio = filtros_ativos(get)["exercicio"]
    # _tags_filtros.html lê total_geral incondicionalmente; sem esta chave
    # o contador "de N processos" renderizaria em branco
    total_geral = Processo.objects.filter(exercicio=exercicio).count()
    contexto = {
        "linhas": linhas,
        "total": total,
        "exercicio": exercicio,
        "querystring_filtros": querystring_filtros(get),
        "total_filtrado": total["total_previsto"],
        "total_geral": total_geral,
        # relatório puro: sem painel de filtros global, sem HTMX/OOB.
        # trilha em tuplas (rótulo, url)
        "trilha": [("Resumo por unidade", None)],
        "nome_tela": "Resumo por unidade",
    }
    resposta = render(request, "pca/resumo_uo.html", contexto)
    # nunca cacheável na borda; o filtro é por sessão autenticada, não público
    resposta["Cache-Control"] = "private, no-store"
    return resposta


# as 3 medidas da tabela "mês x dimensão", a mesma chave usada por
# calcular_grafico_mensal, que devolve as 3 prontas por ponto
MEDIDAS_ANALISE = (
    ("quantidade", "Quantidade"),
    ("valor_previsto", "Valor previsto"),
    ("valor_contratado", "Valor contratado"),
)

# allowlist fechada de ?perfil_dimensao= (separado de ?dimensao=).
# Qualquer valor fora cai no padrão "categoria", nunca alcança um
# .values()/.annotate() com nome de campo não confiável
ROTULOS_PERFIL = {
    "categoria": "Categoria",
    "prioridade": "Prioridade",
    "classificacao": "Estratégica",
    "modalidade": "Modalidade",
    "tipo": "Orçamento por tipo",
}

# allowlist fechada de ?vencimentos=; qualquer outro valor cai em 10
# (padrão), nunca alcança [:limite] com um inteiro não confiável
VENCIMENTOS_OPCOES = (10, 20)
VENCIMENTOS_PADRAO = 10


def analise_view(request):
    """Análises: relatório com dl.dsgov-detalhe (números de
    calcular_blocos_kpi que não viraram KPI no dashboard + valores
    planejado/contratado) e br-tables sem busca/paginação (situação,
    unidade, mês x previsto/entregue, mês x dimensão escolhida,
    vencimentos, Perfil). apps.pca.analise/apps.pca.kpis seguem sendo a
    fonte única dos números; apps.pca.graficos_pca é a mesma ponte de
    agregação que core.views.inicio usa — os números das duas telas nunca
    divergem para o mesmo filtro.

    Sem @permission_required, protegido só pelo LoginRequiredMiddleware
    global."""
    get = request.GET
    qs = queryset_filtrado(request)
    exercicio = filtros_ativos(get)["exercicio"]
    total_geral = Processo.objects.filter(exercicio=exercicio).count()
    soma_filtrada = qs.aggregate(total=Sum("valor_estimado"))["total"] or 0
    soma_contratada = qs.aggregate(total=Sum("valor_contratado"))["total"] or 0

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

    # cada bloco principal ganha um gráfico companheiro; todos reaproveitam
    # a mesma estrutura já computada para a tabela
    status_distribuicao = graficos_pca.calcular_status_distribuicao(qs, get)
    # tabela do par analítico de Situação no formato genérico
    # tabela_dados. Zero consulta nova: status_distribuicao já é a
    # agregação única usada pelo gráfico e pela tabela
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
    # "Adiamentos por item" saiu de Análises (HTML/contexto/consulta)
    pontos_previsto_entregue = graficos_pca.calcular_previsto_entregue(qs, get)

    # Perfil é um componente com dimensão selecionável; allowlist fechada
    # (ROTULOS_PERFIL) — qualquer valor fora cai no padrão "categoria",
    # nunca alcança .values()/.annotate() com nome de campo não confiável
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

    # "Próximos vencimentos — prazos dos processos": mesma leitura de
    # proximidade do KPI, sem janela de dias
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
        # parâmetro canônico de PARAMETROS_FILTRO; QueryDict mutável sobre
        # a base já validada preserva os demais filtros ativos
        parametros = QueryDict(querystring_filtros(get), mutable=True)
        parametros["vencimentos"] = str(valor)
        return parametros.urlencode()

    # o verificador conta literalmente a substring "primary" no arquivo
    # .html; a classe do botão selecionado é resolvida aqui em Python — o
    # literal "primary"/"secondary" nunca aparece no .html, só no valor
    # injetado por {{ }}
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
        # links do bloco de totais para "Valor planejado"/"Valor
        # contratado" (bloco_a/bloco_b já carregam "href" via kpis.card())
        "url_filtro_atual": f"{reverse('pca:tabela')}?{querystring_filtros(get)}",
        # situação/unidade/previsto x entregue: mesma fonte de
        # core.views.inicio, como tabela + gráfico companheiro. Todos os
        # pares seguem o mesmo contrato (par = {titulo, grafico, tabela})
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
        # Perfil vira 1 componente com dimensão selecionável, não mais 5 pares
        "rotulos_perfil": ROTULOS_PERFIL,
        "perfil_dimensao_selecionada": perfil_dimensao,
        "perfil_par": perfil_par,
        # espaço reservado entre Perfil e Previsto x Entregue
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
        # mês x dimensão escolhida — form GET (dimensao/medida), recarga
        # inteira, sem HTMX. series_mensais (matriz completa de 12 meses)
        # continua no contexto para o "Detalhamento mensal completo"
        # full-width logo abaixo do par
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
    # nunca cacheável na borda; o filtro é por sessão autenticada, não público
    resposta["Cache-Control"] = "private, no-store"
    return resposta


def exportar_resumo_uo_xlsx_view(request):
    """Download síncrono do XLSX do resumo por UO. Mesmo queryset/filtro de
    resumo_uo_view."""
    qs = queryset_filtrado(request)
    linhas, total = calcular_resumo_uo(qs)
    resposta = exportar_resumo_uo_xlsx(linhas, total)
    resposta["Cache-Control"] = "private, no-store"
    return resposta


# CAMPOS_ORDENACAO_FK traduz as colunas de FK do seletor de colunas para
# o nome de exibição, nunca o id cru, que não tem ordem útil na tela
CAMPOS_ORDENACAO_FK = {
    "grau_prioridade": "grau_prioridade__nome",
    "classificacao": "classificacao__nome",
    "unidade_organizacional": "unidade_organizacional__nome",
    "categoria": "categoria__nome",
    "modalidade": "modalidade__nome",
    "instrumento_contratual": "instrumento_contratual__nome",
    # "situacao" ordena pela mesma correção-na-leitura que a exibição
    # usa, nunca pela coluna crua
    "situacao": "situacao_efetiva",
}

# as duas FKs de Execução contratual só entram em select_related quando a
# coluna está de fato marcada; campos locais não precisam de preload
FKS_SELECT_RELATED_CONDICIONAL = ("modalidade", "instrumento_contratual")

# generaliza o nulls_last para toda coluna nova nullable — FK opcional,
# data solta ou subquery de acompanhamento ("sem valor" sempre por último,
# nos dois sentidos). atrasado/publicacao_pendente ficam de fora de
# propósito: são anotações booleanas com default=Value(False), nunca NULL
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
    """Aplica ao queryset a mesma ordem que a tabela exibe. O
    Anterior/Próximo precisa percorrer os processos na ordem que o usuário
    está vendo; recalcular a ordem por conta própria criaria uma segunda
    noção de ordem, que divergiria em silêncio justamente nos casos
    difíceis — o default de urgência e o nulls_last."""
    campo_ordenacao = ordenacao_valida(request.GET.get("ordenar"))
    descendente = direcao_valida(request.GET.get("dir")) == "desc"

    # ordenação default de urgência: quando uma das quatro flags de risco
    # está ativa e não há ?ordenar= explícito, a tabela abre por
    # prazo_efetivo ascendente (nulos por último), críticos primeiro,
    # depois por nome do grau e desempate estável exercicio/item_pca. Um
    # ?ordenar= explícito sempre vence este default
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

    # prazo_entrega/prazo_efetivo também são colunas de data anuláveis;
    # sem nulls_last nos dois sentidos, "Prazo efetivo" descendente poria
    # todo processo sem prazo à frente dos mais atrasados. campo_real é o
    # campo de fato usado no order_by(): campo_ordenacao para toda coluna
    # direta/anotada, e a tradução __nome só para grau_prioridade/classificacao
    campo_real = CAMPOS_ORDENACAO_FK.get(campo_ordenacao, campo_ordenacao)

    if campo_ordenacao in CAMPOS_ORDENACAO_NULOS_POR_ULTIMO:
        # item sem mês (NULL) sempre por último, nos dois sentidos:
        # nulls_last precisa ser repetido no desc, senão o PostgreSQL põe
        # NULL na frente
        expressao = F(campo_real)
        ordem = (
            expressao.desc(nulls_last=True)
            if descendente
            else expressao.asc(nulls_last=True)
        )
    else:
        ordem = f"-{campo_real}" if descendente else campo_real

    # item_pca como desempate: sem ele, colunas com valores repetidos
    # deixam a ordem das linhas empatadas indefinida, e o mesmo processo
    # pode aparecer em duas páginas — ou em nenhuma — ao paginar
    return qs.order_by(ordem, "exercicio", "item_pca")


def tabela_view(request):
    """/tabela isolada do dashboard, alimentada pelo contrato único
    queryset_filtrado: dashboard, kanban/detalhe e export consomem a
    mesma função, nunca um filtro próprio.

    Com HX-Request devolve só _listagem.html (chips de filtro ativo +
    tabela + paginação + Exportar), sem nenhum hx-swap-oob.

    Precisa de sessão válida, garantida pelo LoginRequiredMiddleware
    global."""
    # persistência do estado canônico em sessão, antes de qualquer outra
    # linha do corpo da view. colunas já tem sua própria persistência
    # independente — por isso uma requisição que só muda colunas não toca
    # nem lê CHAVE_SESSAO_ESTADO_TABELA: nem grava nem redireciona (a requisição
    # não está vazia — `test_colunas_tabela.py`, achado real desta guarda).
    # Chaves REAIS de filtro/ordenação/página presentes: grava o estado
    # (guarda "só grava se diferir", WR-03) — inclusive `?limpar=1`, que
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

    # import local: mantido por disciplina, sem necessidade funcional de
    # mudar agora
    from apps.pca.forms_listagem import FiltrosProcessoForm

    campo_ordenacao = ordenacao_valida(request.GET.get("ordenar"))
    direcao_ordenacao = direcao_valida(request.GET.get("dir"))
    descendente = direcao_ordenacao == "desc"

    # resolvida antes do queryset: prefetch_related("numeros_sei") só
    # entra quando a coluna está de fato marcada, senão toda requisição
    # pagaria 1 consulta a mais à toa
    colunas_resolvidas = colunas_selecionadas(request)

    # o queryset filtrado é avaliado uma vez por request e reaproveitado
    # para contagem, soma e página; nunca reconstruído a partir do GET em
    # cada bloco
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

    # A ordem vive em `_ordenar_para_tabela` para que o Anterior/Próximo do
    # modal de edição percorra os processos exatamente como a tabela os mostra.
    qs = _ordenar_para_tabela(request, qs)

    # br-pagination 10/20/50; TAMANHO_PAGINA (20) vira só o padrão quando
    # por_pagina está ausente/fora do allowlist
    opcoes_por_pagina = settings.DSGOV.get("OPCOES_POR_PAGINA", (10, 20, 50))
    try:
        por_pagina = int(request.GET.get("por_pagina", TAMANHO_PAGINA))
    except (TypeError, ValueError):
        por_pagina = TAMANHO_PAGINA
    if por_pagina not in opcoes_por_pagina:
        por_pagina = TAMANHO_PAGINA
    paginador = Paginator(qs, por_pagina)
    pagina = paginador.get_page(request.GET.get("pagina"))

    # soma do mesmo queryset filtrado (não paginado), nunca uma segunda consulta
    soma_filtrada = qs.aggregate(total=Sum("valor_estimado"))["total"] or 0
    filtros = filtros_ativos(request.GET)
    exercicio = filtros["exercicio"]
    total_geral = Processo.objects.filter(exercicio=exercicio).count()

    # "Mais filtros" abre sozinho quando algum dos campos secundários
    # está ativo
    mais_filtros_ativo = any(
        filtros[chave]
        for chave in (
            "categoria",
            "tipo",
            "prioridade",
            "classificacao",
            "modalidade",
            "estado",
            "desde_reuniao",
            "legados",
            "recebido_de",
            "recebido_ate",
            "vigencia_fim_de",
            "vigencia_fim_ate",
        )
    )

    # a seleção de colunas já foi resolvida acima, antes do queryset;
    # colunas_selecionadas grava na sessão como efeito colateral, então
    # não é chamada de novo aqui
    cabecalhos_dinamicos = _cabecalhos_ordenaveis(
        campo_ordenacao, direcao_ordenacao, colunas_resolvidas
    )

    # exercicio é o único parâmetro propagado pelo menu/links entre
    # telas; "Limpar filtros" remove todo o resto de PARAMETROS_FILTRO de
    # uma vez, preservando só ele
    querystring_limpar = querystring_filtros(
        request.GET,
        excluir=[chave for chave in PARAMETROS_FILTRO if chave != "exercicio"],
    )

    # link "Restaurar padrão" do seletor "Colunas": querystring dos
    # filtros atuais + as chaves do padrão novo, uma por par colunas=
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
        # seletor "Colunas"
        "colunas_selecionadas": colunas_resolvidas,
        "cabecalhos_dinamicos": cabecalhos_dinamicos,
        # seletor "Colunas" agrupado em quatro fieldsets (Planejamento/
        # Processo/Execução contratual/Publicação)
        "colunas_por_secao": colunas_por_secao(),
        "colunas_obrigatorias": COLUNAS_OBRIGATORIAS,
        "querystring_colunas_padrao": querystring_colunas_padrao,
        # "Mais filtros" abre sozinho
        "mais_filtros_ativo": mais_filtros_ativo,
    }

    if request.htmx:
        # uma única resposta por troca de filtro: _listagem.html inteiro,
        # sem nenhum OOB. Os br-select da barra de filtro não são
        # reescritos (o form inteiro continua fora do alvo) — por isso
        # FiltrosProcessoForm só é construído no ramo else abaixo, nunca aqui
        resposta = render(request, "pca/_listagem.html", contexto)
    else:
        # FiltrosProcessoForm é construído sem data= (nunca .is_valid()):
        # um valor inválido misturado a valores válidos não pode reaparecer
        # na página. Formulário desvinculado + initial a partir de filtros
        # já validado nunca dispara essa validação
        contexto["filtros_form"] = FiltrosProcessoForm(
            initial={
                "q": filtros["q"],
                "uo": filtros["uo"],
                "categoria": filtros["categoria"],
                "tipo": filtros["tipo"],
                "prioridade": filtros["prioridade"],
                "classificacao": filtros["classificacao"],
                "modalidade": filtros["modalidade"],
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

    # nunca cacheável na borda; o filtro é por sessão autenticada, não público
    resposta["Cache-Control"] = "private, no-store"
    return resposta


def _tipo_widget(campo):
    """Escolhe o widget a partir do tipo do campo do model, não por listas
    de nomes de campo."""
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
        # a allowlist contém exatamente um IntegerField limitado: mês
        return "select_mes"
    if isinstance(field, DateField):
        return "date"
    if isinstance(field, TextField):
        return "textarea"
    if isinstance(field, DecimalField):
        # widget próprio para os dois campos monetários: o template aplica
        # a máscara pcaMascaraMoeda só neles
        return "money"
    if isinstance(field, CharField):
        if field.choices:
            return "select_choice"
        return "text"
    raise Http404("Campo sem widget permitido")


def _normalizar_valor_monetario(bruto):
    """Aceita tanto a forma crua (35000, 35000.00) quanto a mascarada
    pt-BR (35.000,00). A presença de vírgula é o sinal de forma mascarada:
    remove os pontos de milhar e troca a vírgula decimal por ponto."""
    if "," in bruto:
        return bruto.replace(".", "").replace(",", ".")
    return bruto


# seções do formulário de edição completa. A ordem e o agrupamento são de
# apresentação; a fronteira de confiança continua sendo
# CAMPOS_EDITAVEIS_PROCESSO. status está ausente de propósito: ele só muda
# pelo modal de transição, que grava acompanhamento.
#
# Planejamento reúne só o que a equipe prevê (cadastro + a única data de
# prazo, prazo_entrega); as duas justificativas obsoletas saem das duas
# abas — justificativa_alteracao_prazo passa a pertencer a cada promessa
# (Acompanhamento.evento) e justificativa_alteracao_email sai de tudo;
# os campos físicos ficam até o plano 11-05 migrar os dados.
#
# a aba "Processo" enxuga para só situacao_sei + data_recebimento_gelic +
# Números SEI. data_prevista_conclusao sai da aba mas continua editável
# inline na tabela; data_envio_gelic fica sem superfície de edição em
# lugar nenhum, dado congelado
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
        (
            "situacao_sei",
            "data_recebimento_gelic",
        ),
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


def _carregar_processo_modal(ano, item_pca):
    """Carregamento único usado pelo GET, pelo sucesso e pelos erros do
    processo: acrescenta timeline_completa (todo Acompanhamento do
    processo, ordem cronológica crescente) como único to_attr do prefetch.
    historico_prazos é derivado em memória do mesmo timeline_completa,
    sem segunda query.

    Os marcadores prazo_anterior/prazo_mudou/prazo_mantido de cada item
    também são calculados aqui, em memória; usados para os badges
    Remarcado/Prazo mantido."""
    processo = get_object_or_404(
        Processo.objects.para_listagem().prefetch_related(
            Prefetch(
                "acompanhamentos",
                # select_related dentro do próprio queryset do prefetch:
                # join, não N+1. processo_detalhe.html usa reuniao.condutor
                # como proxy de autoria de cada linha da timeline
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
        # a mesma frase institucional do relatório de movimentação na
        # timeline do detalhe do processo. item.processo = processo evita
        # uma segunda query ao FK.
        #
        # processo já vem de para_listagem(), logo já está anotado com
        # prazo_inicial; _resolver_prazo_inicial encontra essa anotação
        # sem nenhuma consulta extra por linha da timeline
        if item.prazo_prometido:
            item.processo = processo
            item.frase_compromisso = frase_compromisso(item)
        else:
            item.frase_compromisso = ""
    processo.historico_prazos = [
        item for item in processo.timeline_completa if item.prazo_prometido is not None
    ]
    return processo


def _processo_nao_encontrado(request, ano, item_pca):
    """404 com copy própria para item inexistente num exercício.
    _carregar_processo_modal levanta Http404 via get_object_or_404; este
    helper devolve a resposta com o template próprio."""
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


def _condicao_calendario(processo):
    """A mesma convenção (eixo, valor) que apps/pca/kpis.py/a rosca do
    dashboard já usam: um processo tem exatamente uma condição — Cancelado
    se estado=CANCELADO, independente da situacao gravada; senão, a
    situação efetiva."""
    if processo.estado == Estado.CANCELADO:
        return ("estado", Estado.CANCELADO.value)
    return ("situacao", processo.situacao_efetiva)


def _condicoes_presentes(eventos):
    """Condições distintas presentes numa lista de eventos de um dia, na
    ordem de ORDEM_ROSCA, nunca na ordem de inserção. Devolve uma lista de
    dicts (eixo/valor/rotulo/classe), nunca tuplas: o template nunca faz
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
    """Um evento do calendário, com a classe/rótulo de condição já
    resolvidos — o template nunca faz lookup sozinho."""
    chave = _condicao_calendario(processo)
    return {
        "processo": processo,
        "data_fora_exercicio": data_fora_exercicio,
        "classe_condicao": CLASSE_CONDICAO_CALENDARIO[chave],
        "rotulo_condicao": ROTULO_CONDICAO_CALENDARIO[chave],
    }


def _celula_dia(dia, numero_mes, eventos_por_dia, get, limite):
    """Uma célula da grade (dia/semana), com contador e condições
    compactas — eventos_por_dia já cobre o ano inteiro, então do_mes
    decide se o dia pertence a este mês ou é preenchimento da semana.

    Acrescenta hoje (dia corrente) e url (drill-down exato por dia).

    limite (1 na grade anual, 3 na mensal) centraliza o corte de itens
    visíveis em Python, nunca em |slice espalhado nos templates."""
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


# o parsing/validação de token migrou para apps.pca.filtros. ORDEM_CONDICOES
# continua exportado daqui — mesmo conteúdo de ORDEM_ROSCA reduzido a
# (eixo, valor), agora um simples alias de filtros.ORDEM_CONDICOES_LEGENDA
ORDEM_CONDICOES = ORDEM_CONDICOES_LEGENDA


def _resolver_condicao_legenda(get):
    """Lê ?condicao_legenda= (multivalorado) e devolve (conjunto_ativo,
    tokens_na_ordem_de_ORDEM_CONDICOES). Delega por completo a
    apps.pca.filtros.resolver_condicao_legenda."""
    return resolver_condicao_legenda(get.getlist("condicao_legenda"))


def _grade_mensal(ano, numero_mes, eventos_por_dia, get, *, limite):
    """Semanas (domingo a sábado) de um mês, cada uma com 7 células,
    reaproveitada tanto pela visão mensal quanto pelos 12 mini-calendários
    da visão anual, sem duplicar o for-loop e sem consulta nova.

    Calendar.monthdatescalendar devolve 4, 5 ou 6 semanas conforme o
    mês/ano, nunca sempre 6: completa com semanas adicionais reais até o
    total ser exatamente 6 (42 células). limite: 1 para a grade anual, 3
    para a mensal."""
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
        # filtros["mes"] é lista (multi-seleção). Só assume o mês do filtro
        # quando exatamente um mês real está selecionado; do contrário cai
        # no mesmo padrão de sempre
        meses_reais_selecionados = [
            valor for valor in filtros["mes"] if valor != SENTINEL_SEM_MES
        ]
        if len(meses_reais_selecionados) == 1:
            mes_solicitado = meses_reais_selecionados[0]
        elif exercicio and exercicio.ano == localdate().year:
            mes_solicitado = localdate().month
        else:
            mes_solicitado = 1

    # ordem estável (item_pca/id) antes do loop que popula eventos_por_dia:
    # garante que os itens visíveis de cada célula sejam sempre os mesmos
    processos = list(
        queryset_filtrado(request)
        .select_related("origem", "origem__exercicio")
        .order_by("item_pca", "id")
    )
    if condicao_legenda_ativos != set(ORDEM_CONDICOES):
        # narrowing em Python sobre a lista já autorizada pelo queryset
        # filtrado; nenhuma consulta nova, filtro local só do calendário
        processos = [
            p for p in processos if _condicao_calendario(p) in condicao_legenda_ativos
        ]
    processos_por_mes = {numero: [] for numero in MESES}
    eventos_por_dia = {}
    sem_dia_por_mes = {numero: [] for numero in MESES}
    sem_mes_eventos = []

    for processo in processos:
        # o calendário posiciona pela mesma identidade única de avaliação
        # de prazo que rege atraso/dias/remarcações: prazo_efetivo.
        # data_prevista_conclusao nunca mais escolhe o dia
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

    # grade anual literal: 12 mini-calendários derivados do mesmo
    # eventos_por_dia já materializado, nenhuma consulta nova por mês
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

    # uma entrada por condição de ORDEM_ROSCA, serve tanto à legenda
    # informativa quanto ao br-select multiple de situação do formulário
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

    # preserva no formulário único qualquer outro filtro ativo que o
    # formulário não gerencia diretamente; exceto exercicio, que já tem
    # controle próprio no formulário
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
        # a navegação de um clique entre meses permanece na visão mensal,
        # ao lado do título
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
        # trilha_padrao já devolve trilha de 1 item (sem link) quando
        # exercicio é None, nunca falha
        "trilha": navegacao.trilha_padrao(exercicio, "Calendário"),
        "nome_tela": "Calendário",
    }


def calendario_view(request):
    """Calendário de leitura sobre o queryset filtrado único, como grade
    de 7 colunas nas visões anual (12 cards) e mensal (1 card).
    _contexto_calendario permanece a única fonte de contexto; esta view
    só ajusta a trilha para o formato da casca da skill."""
    contexto = _contexto_calendario(request)
    # _contexto_calendario monta trilha/nome_tela no formato de dict; a
    # casca exige tuplas (rótulo, url), sobrescritas aqui
    contexto["trilha"] = [("Calendário", None)]
    resposta = render(request, "pca/calendario.html", contexto)
    # nunca cacheável na borda
    resposta["Cache-Control"] = "private, no-store"
    return resposta


def redirecionar_kanban_view(request):
    """O kanban deixou de existir como ferramenta; /kanban responde 301
    permanente para /tabela, preservando os filtros validados, nunca a
    querystring crua. Bookmarks, links compartilhados e o PWA devem
    resolver /tabela diretamente na próxima visita, daí 301 e não 302."""
    destino = reverse("pca:tabela")
    filtros = querystring_filtros(request.GET)
    if filtros:
        destino = f"{destino}?{filtros}"
    return HttpResponsePermanentRedirect(destino)


def _rascunho_para_destino(ano_destino, usuario):
    """Resolve a origem e cria o rascunho durável único, se necessário."""
    try:
        destino = int(ano_destino)
    except (TypeError, ValueError):
        raise Http404("Exercício de destino inválido.")
    if Exercicio.objects.filter(ano=destino).exists():
        raise Http404("O exercício de destino já existe.")
    origem = Exercicio.objects.filter(ano__lt=destino).order_by("-ano").first()
    if origem is None:
        raise Http404("Nenhum exercício de origem está disponível.")
    rascunho = RascunhoVirada.objects.filter(
        exercicio_origem=origem, ano_destino=destino, confirmado_em__isnull=True
    ).first()
    if rascunho:
        return rascunho
    try:
        with transaction.atomic():
            rascunho = RascunhoVirada.objects.create(
                exercicio_origem=origem, ano_destino=destino, criado_por=usuario
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
            exercicio_origem=origem, ano_destino=destino, confirmado_em__isnull=True
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
    """Etapa 1 do wizard de virada — Selecionar. Sem HTMX por linha: um
    POST processa a página inteira de uma vez, comparando item_pagina
    (hidden, todos os ids renderizados) com selecionados (só os marcados)
    para marcar/desmarcar em lote. acao=avancar move para a etapa 2;
    acao=aplicar mantém nesta mesma etapa."""
    rascunho = _rascunho_para_destino(ano_destino, request.user)
    pagina_num = request.POST.get("pagina") or request.GET.get("pagina", 1)
    if request.method == "POST":
        ids_pagina = request.POST.getlist("item_pagina")
        ids_marcados = set(request.POST.getlist("selecionados"))
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
    """Etapa 2 do wizard — Ajustar: só os itens selecionado=True,
    "Editar" abre o formulário por item. "Avançar" é um POST real, nunca
    troca de painel em JS."""
    rascunho = _rascunho_para_destino(ano_destino, request.user)
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
    """Formulário da etapa "Ajustar": ViradaItemForm restringe os campos
    aceitos a mes_previsto_editado/valor_estimado_editado, nunca
    selecionado/processo_origem."""
    rascunho = _rascunho_para_destino(ano_destino, request.user)
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
    """Etapa 3 do wizard — Revisar e concluir: totais + tabela final
    read-only; "Concluir virada" é um form que faz POST direto a
    pca:virada_confirmar."""
    rascunho = _rascunho_para_destino(ano_destino, request.user)
    linhas = _linhas_selecionadas_virada(rascunho).order_by("ordem")
    paginador = Paginator(linhas, TAMANHO_VIRADA_PAGINA)
    pagina_obj = paginador.get_page(request.GET.get("pagina", 1))
    soma = linhas.aggregate(soma=Sum("valor_estimado_editado"))["soma"] or Decimal("0")
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
    """Rota histórica — a etapa 3 do wizard vive em pca:virada_revisar;
    mantida só para reverse()/links antigos não quebrarem."""
    return redirect("pca:virada_revisar", ano_destino)


@permission_required("pca.gerir_exercicio", raise_exception=True)
def virada_confirmar_descarte_view(request, ano_destino):
    """Página de confirmação de descarte; o POST real continua em
    pca:virada_descartar."""
    rascunho = _rascunho_para_destino(ano_destino, request.user)
    return render(
        request, "pca/virada_confirmar_descarte.html", {"rascunho": rascunho}
    )


@permission_required("pca.gerir_exercicio", raise_exception=True)
@require_POST
def virada_descartar_view(request, ano_destino):
    rascunho = _rascunho_para_destino(ano_destino, request.user)
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
    rascunho = _rascunho_para_destino(ano_destino, request.user)
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


@permission_required("pca.gerir_exercicio", raise_exception=True)
def gerenciar_exercicios_view(request):
    # "Iniciar virada" só faz sentido a partir do exercício aberto mais
    # recente, e só quando o destino (ano + 1) ainda não existe
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
        "trilha": [("Gerenciar exercícios", None)],
    })


@permission_required("pca.gerir_exercicio", raise_exception=True)
def encerrar_confirmar_view(request, ano):
    """Página de confirmação de encerramento do exercício."""
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


def _queryset_export(request, colunas_resolvidas=()):
    """O único queryset dos downloads: queryset_filtrado(request), nunca
    um filtro reimplementado, mais prefetch_related("numeros_sei") e
    select_related("tipo"). Sem paginação: o download leva o conjunto
    filtrado inteiro.

    A mesma ordenação da tabela é aplicada aqui: sem isso, o arquivo podia
    divergir da ordem visível na tela.

    colunas_resolvidas ativa select_related("modalidade",
    "instrumento_contratual") só quando a coluna foi de fato selecionada."""
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
    """Resolve o subconjunto de colunas do export a partir de ?colunas=
    repetido (um colunas= por checkbox). Sem nenhum ?colunas= no GET,
    delega ao resolvedor compartilhado (colunas_selecionadas), o mesmo
    que a tela usa.

    Com ?colunas=, as chaves são validadas contra
    exportacao.COLUNAS_POR_CHAVE (o allowlist do export) e deduplicadas
    preservando a primeira ocorrência. Se todas as chaves do GET forem
    inválidas/vazias, o resultado filtrado fica vazio e cai no mesmo
    resolvedor compartilhado — seleção inválida nunca produz tabela ou
    arquivo sem colunas."""
    vistas = set()
    chaves = []
    for chave in request.GET.getlist("colunas"):
        if chave in _COLUNAS_EXPORT_POR_CHAVE and chave not in vistas:
            vistas.add(chave)
            chaves.append(chave)
    if chaves:
        return chaves
    return colunas_selecionadas(request)


def exportar_csv_view(request):
    """Download síncrono do CSV ;/BOM UTF-8. Poucas linhas não justificam
    fila de tarefas. Sessão válida garantida pelo LoginRequiredMiddleware
    global. colunas espelha o que a tela mostra no momento do clique.
    exercicio dá nome dinâmico ao arquivo pelo exercício efetivo dos
    filtros correntes."""
    exercicio = filtros_ativos(request.GET)["exercicio"]
    colunas_resolvidas = _colunas_selecionadas_do_request(request)
    resposta = exportar_csv(
        _queryset_export(request, colunas_resolvidas),
        colunas_resolvidas,
        exercicio=exercicio,
    )
    # download nunca cacheável na borda
    resposta["Cache-Control"] = "private, no-store"
    return resposta


def exportar_xlsx_view(request):
    """Download síncrono do XLSX com tipos nativos e SUM(). Mesmas
    premissas do CSV acima."""
    exercicio = filtros_ativos(request.GET)["exercicio"]
    colunas_resolvidas = _colunas_selecionadas_do_request(request)
    resposta = exportar_xlsx(
        _queryset_export(request, colunas_resolvidas),
        colunas_resolvidas,
        exercicio=exercicio,
    )
    # download nunca cacheável na borda
    resposta["Cache-Control"] = "private, no-store"
    return resposta


def reuniao_listagem_view(request):
    """Lugar canônico de "Reuniões": a rota existia, mas não havia
    listagem — o item do menu apontava direto para o formulário de
    criação. Sem @permission_required, protegido só pelo
    LoginRequiredMiddleware global."""
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
    """GET renderiza reuniao_formulario.html; POST válido chama
    services.criar_reuniao e redireciona para pca:reuniao_listagem."""
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

    exercicio = Exercicio.objects.filter(ano=request.GET.get("exercicio")).first()
    try:
        services.criar_reuniao(
            data=form.cleaned_data["data"],
            usuario=request.user,
            exercicio=exercicio,
            situacao=form.cleaned_data["situacao"],
        )
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
