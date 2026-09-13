from datetime import date
from urllib.parse import urlencode

from django.conf import settings
from django.db.models import Q

from apps.catalogo.models import (
    Categoria,
    Classificacao,
    Exercicio,
    GrauPrioridade,
    Modalidade,
    SituacaoExercicio,
    Tipo,
    Unidade,
)
from apps.pca.models import Estado, Processo, Reuniao, Situacao

# o filtro `legados` abaixo identifica o status do processo de origem
# numa continuação de exercício, lendo origem__situacao (coluna crua)

# este módulo é o único ponto de construção do queryset filtrado; nenhuma
# view monta o seu próprio filtro, ou os números divergem entre visões

# "não classificado" é filtro de primeira classe, não ausência silenciosa;
# mes usa sentinela própria porque o rótulo na tela é "Sem mês previsto"
SENTINEL_NAO_CLASSIFICADO = "nao_classificado"
SENTINEL_SEM_MES = "sem_mes"

# parâmetros canônicos do querystring — a única lista que define o que
# entra no filtro; qualquer outra chave do GET é ignorada silenciosamente
#
# atrasado/reprometidos são as duas flags de drill-down do dashboard sem
# controle próprio na barra de filtro global; precisam estar aqui para que
# querystring_filtros as preserve ao reconstruir links
PARAMETROS_FILTRO = (
    "q",
    "uo",
    "categoria",
    "tipo",
    "prioridade",
    "classificacao",
    "modalidade",
    "estado",
    "situacao",
    "mes",
    "atrasado",
    "reprometidos",
    "contratado",
    "publicacao_pendente",
    "criticos",
    "proximo_prazo",
    "sem_atualizacao",
    # duas flags de drill-down transversal: sem elas, o href de próximos
    # do vencimento/sobrestados perderia o recorte na volta pela URL
    "vencimento_proximo",
    "sobrestado",
    "desde_reuniao",
    "legados",
    "exercicio",
    # filtro de intervalo de datas para data_recebimento_gelic.
    # escalares — não entram em CHAVES_MULTIVALOR
    "recebido_de",
    "recebido_ate",
    # filtro de intervalo de datas absolutas para vigencia_fim (drill-down
    # do gráfico "Vencimento de contratos" da tela Análise); diferente de
    # recebido_de/recebido_ate, que comparam só o mês. Escalares
    "vigencia_fim_de",
    "vigencia_fim_ate",
    # drill-down exato por dia do calendário; data ISO exata comparando
    # igualdade (não intervalo) contra prazo_efetivo. Escalar
    "dia_calendario",
    # a mesma seleção de condições da legenda do calendário, agora um
    # parâmetro canônico de /tabela. Multivalor
    "condicao_legenda",
)

# mapa fechado de colunas permitidas para ?ordenar=; qualquer valor fora
# daqui cai no default (item_pca). prazo_entrega, prazo_efetivo,
# n_prorrogacoes e dias_atraso entram como anotações de para_listagem()
COLUNAS_ORDENACAO = (
    "item_pca",
    "descricao_objeto",
    "valor_estimado",
    "valor_contratado",
    # situacao_efetiva (não situacao crua) para a ordenação refletir a
    # mesma correção de leitura que a exibição usa; tipo ordena pela FK crua
    "estado",
    "tipo",
    "situacao",
    "situacao_efetiva",
    "mes_previsto",
    "n_reunioes",
    "n_compromissos",
    # prazo_inicial substitui prazo_entrega no mapa (a anotação COALESCE
    # de para_listagem(), nunca o campo cru)
    "prazo_inicial",
    "prazo_efetivo",
    "n_prorrogacoes",
    "dias_atraso",
    # todas as colunas de CABECALHOS_TABELA são ordenáveis
    "grau_prioridade",
    "classificacao",
    "data_inclusao_pca",
    "situacao_atual",
    "atrasado",
    "publicacao_pendente",
    "data_envio_gelic",
    "data_recebimento_gelic",
    "data_prevista_conclusao",
    "unidade_organizacional",
    # categoria/justificativa/situacao_sei (campos escalares simples) mais
    # as chaves de Execução contratual/Publicação, ordenáveis pelo nome
    # quando FK ou pelo campo cru quando data/texto solto
    "categoria",
    "justificativa",
    "situacao_sei",
    "modalidade",
    "numero_contratacao",
    "numero_arp",
    "instrumento_contratual",
    "numero_instrumento_contratual",
    "fornecedor_cnpj",
    "fornecedor_razao_social",
    "data_assinatura_contrato",
    "vigencia_inicio",
    "vigencia_fim",
    "data_lancamento_spw",
    "data_lancamento_wordpress",
    "data_lancamento_dados_abertos",
)
COLUNA_ORDENACAO_PADRAO = "item_pca"

# mesma disciplina de lista fechada para o sentido da ordenação: qualquer
# valor fora destes dois cai no padrão ascendente
DIRECOES_ORDENACAO = ("asc", "desc")
DIRECAO_ORDENACAO_PADRAO = "asc"

MESES = range(1, 13)
NOMES_MES = {
    1: "Janeiro",
    2: "Fevereiro",
    3: "Março",
    4: "Abril",
    5: "Maio",
    6: "Junho",
    7: "Julho",
    8: "Agosto",
    9: "Setembro",
    10: "Outubro",
    11: "Novembro",
    12: "Dezembro",
}


def _id_valido(valor):
    """Converte para inteiro positivo; qualquer outra coisa vira None."""
    if not valor:
        return None
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        return None
    return numero if numero > 0 else None


def _prioridade_ou_classificacao_valida(valor):
    if not valor:
        return None
    if valor == SENTINEL_NAO_CLASSIFICADO:
        return SENTINEL_NAO_CLASSIFICADO
    return _id_valido(valor)


def _mes_valido(valor):
    if not valor:
        return None
    if valor == SENTINEL_SEM_MES:
        return SENTINEL_SEM_MES
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        return None
    return numero if numero in MESES else None


def _data_valida(valor):
    """Converte para date; qualquer formato inválido ou ausência vira None."""
    if not valor:
        return None
    try:
        return date.fromisoformat(str(valor))
    except (TypeError, ValueError):
        return None


def _estado_valido(valor):
    return valor if valor in Estado.values else None


def _situacao_valida(valor):
    return valor if valor in Situacao.values else None


# versões "em lista" dos validadores acima, para os campos de domínio que
# viraram multi-seleção; item inválido é descartado, ordem preservada
def _validos_em_lista(valores, validador):
    vistos = []
    for valor in valores:
        item = validador(valor)
        if item is not None and item not in vistos:
            vistos.append(item)
    return vistos


def _ids_validos(valores):
    return _validos_em_lista(valores, _id_valido)


def _prioridade_ou_classificacao_validas(valores):
    return _validos_em_lista(valores, _prioridade_ou_classificacao_valida)


def _mes_validos(valores):
    return _validos_em_lista(valores, _mes_valido)


def _estados_validos(valores):
    return _validos_em_lista(valores, _estado_valido)


def _situacoes_validas(valores):
    return _validos_em_lista(valores, _situacao_valida)


def _getlist(get, chave):
    """Lê uma chave como lista, aceitando QueryDict ou dict simples; um
    valor escalar vira lista de 1 item."""
    getlist = getattr(get, "getlist", None)
    if getlist is not None:
        return getlist(chave)
    valor = get.get(chave)
    if valor is None:
        return []
    if isinstance(valor, (list, tuple)):
        return list(valor)
    return [valor]


# chaves multi-valor — usado por querystring_filtros/tags_ativas para
# saber quando tratar o valor como lista em vez de escalar
CHAVES_MULTIVALOR = (
    "uo",
    "categoria",
    "tipo",
    "prioridade",
    "classificacao",
    "estado",
    "situacao",
    "mes",
    # ver comentário em PARAMETROS_FILTRO
    "condicao_legenda",
)


# os 5 tokens (eixo, valor) possíveis para condicao_legenda, mesma ordem
# que a legenda do calendário sempre usou: um processo tem exatamente uma
# condição — Cancelado ou uma das 4 situações efetivas dos ativos
ORDEM_CONDICOES_LEGENDA = (
    ("estado", Estado.CANCELADO.value),
    ("situacao", Situacao.CONCLUIDO.value),
    ("situacao", Situacao.NO_PRAZO.value),
    ("situacao", Situacao.EM_TRAMITACAO.value),
    ("situacao", Situacao.ATRASADO.value),
)

# condicao_legenda=nenhum esvazia o conjunto ativo por completo,
# distinto de "ausente" (todas as 5 ativas, "sem filtro")
SENTINEL_CONDICAO_LEGENDA_NENHUM = "nenhum"


def resolver_condicao_legenda(valores):
    """Parsing/validação de condicao_legenda: recebe a lista crua de tokens
    e devolve (conjunto_ativo, tokens_na_ordem_canonica). Lista vazia
    devolve todas as 5 condições ativas, sem tokens."""
    if not valores:
        return set(ORDEM_CONDICOES_LEGENDA), []
    if valores == [SENTINEL_CONDICAO_LEGENDA_NENHUM]:
        return set(), [SENTINEL_CONDICAO_LEGENDA_NENHUM]
    condicoes_por_token = {
        f"{eixo}:{valor}": (eixo, valor) for eixo, valor in ORDEM_CONDICOES_LEGENDA
    }
    validos = {condicoes_por_token[v] for v in valores if v in condicoes_por_token}
    if not validos:
        return set(ORDEM_CONDICOES_LEGENDA), []
    tokens = [
        f"{eixo}:{valor}"
        for eixo, valor in ORDEM_CONDICOES_LEGENDA
        if (eixo, valor) in validos
    ]
    return validos, tokens


def q_condicao_legenda(valores):
    """Q() de união (nunca interseção) para os tokens de condicao_legenda.
    Devolve None quando o conjunto é "todas as 5" (sem filtro); Q(pk__in=[])
    quando é vazio (sentinela "nenhum")."""
    validos, _tokens = resolver_condicao_legenda(valores)
    if validos == set(ORDEM_CONDICOES_LEGENDA):
        return None
    if not validos:
        return Q(pk__in=[])
    condicao = Q()
    for eixo, valor in validos:
        if eixo == "estado":
            condicao |= Q(estado=valor)
        else:
            condicao |= Q(estado=Estado.ATIVO, situacao_efetiva=valor)
    return condicao


def _flag_valida(valor):
    """Normaliza uma flag booleana do querystring para "1" ou None."""
    return "1" if valor == "1" else None


def resolver_exercicio(get):
    """Resolve the one annual scope selected by a query string.

    An explicit value is accepted only when it is an existing exercise. An
    empty, malformed, or nonexistent value falls back to the greatest open
    exercise, never to an arbitrary process from another year.
    """
    valor = get.get("exercicio")
    try:
        ano = int(valor) if valor else None
    except (TypeError, ValueError):
        ano = None
    if ano is not None and ano > 0:
        exercicio = Exercicio.objects.filter(ano=ano).first()
        if exercicio is not None:
            return exercicio
    return Exercicio.objects.filter(
        situacao=SituacaoExercicio.ABERTO
    ).order_by("-ano").first()


def exercicio_explicito(get):
    """Return whether the query string names an existing exercise.

    The resolved current exercise is intentionally not considered an active
    filter when it was inferred from an absent, malformed, or unknown value.
    """
    cached = getattr(get, "_pca_exercicio_explicito", None)
    if cached is not None:
        return cached
    valor = get.get("exercicio")
    try:
        ano = int(valor) if valor else None
    except (TypeError, ValueError):
        ano = None
    explicito = (
        False
        if ano is None or ano <= 0
        else Exercicio.objects.filter(ano=ano).exists()
    )
    try:
        get._pca_exercicio_explicito = explicito
    except AttributeError:
        pass
    return explicito


def ordenacao_valida(valor):
    return valor if valor in COLUNAS_ORDENACAO else COLUNA_ORDENACAO_PADRAO


def direcao_valida(valor):
    """Normaliza ?dir= para "asc" ou "desc"."""
    return valor if valor in DIRECOES_ORDENACAO else DIRECAO_ORDENACAO_PADRAO


def filtros_ativos(get):
    """Lê o QueryDict cru e devolve um dict só com os parâmetros canônicos,
    já validados e tipados."""
    exercicio = getattr(get, "_pca_exercicio", None)
    if exercicio is None:
        exercicio = resolver_exercicio(get)
        try:
            get._pca_exercicio = exercicio
        except AttributeError:
            pass
    return {
        "q": (get.get("q") or "").strip(),
        "uo": _ids_validos(_getlist(get, "uo")),
        "categoria": _ids_validos(_getlist(get, "categoria")),
        "tipo": _ids_validos(_getlist(get, "tipo")),
        "prioridade": _prioridade_ou_classificacao_validas(_getlist(get, "prioridade")),
        "classificacao": _prioridade_ou_classificacao_validas(_getlist(get, "classificacao")),
        "modalidade": _id_valido(get.get("modalidade")),
        "estado": _estados_validos(_getlist(get, "estado")),
        "situacao": _situacoes_validas(_getlist(get, "situacao")),
        "mes": _mes_validos(_getlist(get, "mes")),
        "atrasado": _flag_valida(get.get("atrasado")),
        "reprometidos": _flag_valida(get.get("reprometidos")),
        "contratado": _flag_valida(get.get("contratado")),
        "publicacao_pendente": _flag_valida(get.get("publicacao_pendente")),
        "criticos": _flag_valida(get.get("criticos")),
        "proximo_prazo": _flag_valida(get.get("proximo_prazo")),
        "sem_atualizacao": _flag_valida(get.get("sem_atualizacao")),
        # recortes transversais do Bloco B
        "vencimento_proximo": _flag_valida(get.get("vencimento_proximo")),
        "sobrestado": _flag_valida(get.get("sobrestado")),
        "desde_reuniao": _id_valido(get.get("desde_reuniao")),
        "legados": _flag_valida(get.get("legados")),
        # intervalo de datas para data_recebimento_gelic, ver PARAMETROS_FILTRO
        "recebido_de": _data_valida(get.get("recebido_de")),
        "recebido_ate": _data_valida(get.get("recebido_ate")),
        # ver comentário em PARAMETROS_FILTRO
        "vigencia_fim_de": _data_valida(get.get("vigencia_fim_de")),
        "vigencia_fim_ate": _data_valida(get.get("vigencia_fim_ate")),
        # ver comentário em PARAMETROS_FILTRO
        "dia_calendario": _data_valida(get.get("dia_calendario")),
        # já resolvido/validado: tokens na ordem canônica, [] quando ausente
        "condicao_legenda": resolver_condicao_legenda(_getlist(get, "condicao_legenda"))[1],
        "exercicio": exercicio,
    }


# apps.pca.busca.aplicar_busca é a fonte única de interpretação do termo
# q, compartilhada com a busca global


def queryset_filtrado(request):
    """Ponto único de construção do queryset filtrado, sempre a partir de
    Processo.objects.para_listagem()."""
    filtros = filtros_ativos(request.GET)
    exercicio = filtros["exercicio"]
    qs = Processo.objects.para_listagem().filter(exercicio=exercicio)

    # a seleção de legados é aplicada só depois do recorte anual resolvido
    # pelo servidor; o status de origem é lido do processo anterior
    if filtros["legados"]:
        qs = qs.filter(origem__isnull=False).exclude(
            origem__situacao=Situacao.CONCLUIDO
        )

    if filtros["q"]:
        # import local evita ciclo com apps.pca.busca; .distinct() não é
        # necessário porque aplicar_busca usa Exists (não JOIN) para SEI.
        # avisos são descartados aqui; a busca global os exibe
        from apps.pca.busca import aplicar_busca

        qs, _avisos_busca_tabela = aplicar_busca(qs, filtros["q"])

    # uo/categoria/tipo/status viram __in (OR entre os valores); nunca
    # filtra quando a lista está vazia
    if filtros["uo"]:
        qs = qs.filter(unidade_organizacional_id__in=filtros["uo"])
    if filtros["categoria"]:
        qs = qs.filter(categoria_id__in=filtros["categoria"])
    if filtros["tipo"]:
        qs = qs.filter(tipo_id__in=filtros["tipo"])
    if filtros["modalidade"]:
        qs = qs.filter(modalidade_id=filtros["modalidade"])

    # prioridade/classificacao/mes misturam a sentinela com ids/números
    # reais na mesma lista; cada ramo só entra se tiver conteúdo
    if filtros["prioridade"]:
        ids_reais = [v for v in filtros["prioridade"] if v != SENTINEL_NAO_CLASSIFICADO]
        condicao = Q()
        if SENTINEL_NAO_CLASSIFICADO in filtros["prioridade"]:
            condicao |= Q(grau_prioridade__isnull=True)
        if ids_reais:
            condicao |= Q(grau_prioridade_id__in=ids_reais)
        qs = qs.filter(condicao)

    if filtros["classificacao"]:
        ids_reais = [v for v in filtros["classificacao"] if v != SENTINEL_NAO_CLASSIFICADO]
        condicao = Q()
        if SENTINEL_NAO_CLASSIFICADO in filtros["classificacao"]:
            condicao |= Q(classificacao__isnull=True)
        if ids_reais:
            condicao |= Q(classificacao_id__in=ids_reais)
        qs = qs.filter(condicao)

    # situacao filtra pela anotação corrigida situacao_efetiva, nunca a
    # coluna crua situacao
    if filtros["estado"]:
        qs = qs.filter(estado__in=filtros["estado"])
    if filtros["situacao"]:
        qs = qs.filter(situacao_efetiva__in=filtros["situacao"])

    if filtros["mes"]:
        numeros_reais = [v for v in filtros["mes"] if v != SENTINEL_SEM_MES]
        condicao = Q()
        if SENTINEL_SEM_MES in filtros["mes"]:
            condicao |= Q(mes_previsto__isnull=True)
        if numeros_reais:
            condicao |= Q(mes_previsto__in=numeros_reais)
        qs = qs.filter(condicao)

    # intervalo de mês (não de data absoluta) para data_recebimento_gelic:
    # a curva trimestral bucketiza por ExtractQuarter, só o mês, sem
    # restrição de ano; um filtro por data absoluta quebraria a coerência
    # entre o número do gráfico e a contagem de /tabela
    if filtros["recebido_de"]:
        qs = qs.filter(data_recebimento_gelic__month__gte=filtros["recebido_de"].month)
    if filtros["recebido_ate"]:
        qs = qs.filter(data_recebimento_gelic__month__lte=filtros["recebido_ate"].month)

    # intervalo de data absoluta (com ano) para vigencia_fim: vencimento
    # de contrato é uma data de calendário real, não um recorte recorrente
    if filtros["vigencia_fim_de"]:
        qs = qs.filter(vigencia_fim__gte=filtros["vigencia_fim_de"])
    if filtros["vigencia_fim_ate"]:
        qs = qs.filter(vigencia_fim__lte=filtros["vigencia_fim_ate"])

    # drill-down exato por dia do calendário
    if filtros["dia_calendario"]:
        qs = qs.filter(prazo_efetivo=filtros["dia_calendario"])

    # mesma seleção de condições que a legenda do calendário aplica em
    # Python; q_condicao_legenda devolve None quando é "todas as 5"
    if filtros["condicao_legenda"]:
        condicao_legenda = q_condicao_legenda(filtros["condicao_legenda"])
        if condicao_legenda is not None:
            qs = qs.filter(condicao_legenda)

    # atrasado/reprometido já chegam anotados por para_listagem(); aqui
    # só filtramos, nunca recalculamos
    if filtros["atrasado"]:
        qs = qs.filter(atrasado=True)
    if filtros["reprometidos"]:
        qs = qs.filter(reprometido=True)
    if filtros["contratado"]:
        qs = qs.filter(valor_contratado__isnull=False)
    if filtros["publicacao_pendente"]:
        qs = qs.filter(publicacao_pendente=True)
    if filtros["criticos"]:
        qs = qs.criticos()
    if filtros["proximo_prazo"]:
        qs = qs.proximos_do_prazo()
    if filtros["sem_atualizacao"]:
        qs = qs.sem_atualizacao_recente()
    # recortes transversais do Bloco B, mesmo padrão dos flags acima
    if filtros["vencimento_proximo"]:
        qs = qs.proximo_vencimento_gelic(settings.PCA_DIAS_PROXIMOS_VENCIMENTO)
    if filtros["sobrestado"]:
        qs = qs.sobrestados()

    # desde_reuniao pergunta "o que mudou na reunião escolhida" — igualdade
    # de data, não FK reuniao_id, para incluir lançamentos automáticos
    if filtros["desde_reuniao"]:
        data_reuniao = Reuniao.objects.filter(
            pk=filtros["desde_reuniao"]
        ).values_list("data", flat=True).first()
        if data_reuniao:
            qs = qs.filter(
                acompanhamentos__referencia_data=data_reuniao
            ).distinct()

    return qs


def querystring_filtros(get, excluir=None, excluir_valor=None, **overrides):
    """Reserializa só os parâmetros canônicos validados. `excluir` remove
    uma ou mais chaves inteiras (escalar ou lista); `excluir_valor` (chave,
    valor) remove só um valor de uma chave multi-valor; `overrides`
    substitui o valor de uma chave (escalar vira lista de 1 item nas
    chaves multi-valor)."""
    valores = dict(filtros_ativos(get))
    for chave, valor in overrides.items():
        if chave in CHAVES_MULTIVALOR:
            # override em lista/tupla preserva a ordem recebida; o
            # comportamento escalar (um valor -> lista de 1 item) continua idêntico
            if isinstance(valor, (list, tuple)):
                valores[chave] = list(valor)
            else:
                valores[chave] = [valor] if valor not in (None, "") else []
        else:
            valores[chave] = valor
    if excluir:
        chaves_excluir = (
            list(excluir) if isinstance(excluir, (list, tuple)) else [excluir]
        )
        for chave_excluir in chaves_excluir:
            valores[chave_excluir] = (
                [] if chave_excluir in CHAVES_MULTIVALOR else None
            )
    if excluir_valor:
        chave_ex, valor_ex = excluir_valor
        if chave_ex in CHAVES_MULTIVALOR:
            valores[chave_ex] = [
                v for v in valores.get(chave_ex, []) if str(v) != str(valor_ex)
            ]
    partes = []
    for chave in PARAMETROS_FILTRO:
        valor = valores.get(chave)
        if chave in CHAVES_MULTIVALOR:
            # um par (chave, valor) por item selecionado
            for item in valor or ():
                if item:
                    partes.append((chave, item))
            continue
        if not valor:
            continue
        # o maior exercício aberto é implícito: fica fora da URL até o
        # usuário selecionar um exercício explicitamente
        if (
            chave == "exercicio"
            and chave not in overrides
            and not exercicio_explicito(get)
        ):
            continue
        if chave == "exercicio":
            valor = valor.ano if isinstance(valor, Exercicio) else _id_valido(valor)
        if valor:
            partes.append((chave, valor))
    return urlencode(partes)


def querystring_tabela(get, excluir=None, excluir_valor=None, **overrides):
    """Fonte única de "estado idêntico à tabela": querystring_filtros mais
    ordenar/dir/pagina/por_pagina/colunas, cada um só incluído quando a
    chave está presente em get."""
    base = querystring_filtros(get, excluir=excluir, excluir_valor=excluir_valor, **overrides)
    extras = []
    if "ordenar" in get:
        extras.append(("ordenar", ordenacao_valida(get.get("ordenar"))))
        extras.append(("dir", direcao_valida(get.get("dir"))))
    if "pagina" in get:
        try:
            pagina = int(get.get("pagina"))
        except (TypeError, ValueError):
            pagina = None
        if pagina is not None and pagina > 1:
            extras.append(("pagina", pagina))
    if "por_pagina" in get:
        opcoes = settings.DSGOV.get("OPCOES_POR_PAGINA", (10, 20, 50))
        try:
            por_pagina = int(get.get("por_pagina"))
        except (TypeError, ValueError):
            por_pagina = None
        if por_pagina is not None and por_pagina in opcoes:
            extras.append(("por_pagina", por_pagina))
    if "colunas" in get:
        from apps.pca.colunas import COLUNAS_POR_CHAVE

        for chave in _getlist(get, "colunas"):
            if chave in COLUNAS_POR_CHAVE:
                extras.append(("colunas", chave))
    pedaco_extra = urlencode(extras, doseq=True) if extras else ""
    partes_finais = [p for p in (base, pedaco_extra) if p]
    return "&".join(partes_finais)


def opcoes_filtros():
    """Opções para os <select> da barra de filtro global."""
    return {
        "exercicio": Exercicio.objects.order_by("-ano"),
        "uo": Unidade.objects.order_by("nome"),
        "categoria": Categoria.objects.order_by("nome"),
        "tipo": Tipo.objects.order_by("nome"),
        "prioridade": GrauPrioridade.objects.order_by("nome"),
        "classificacao": Classificacao.objects.order_by("nome"),
        "estado": Estado.choices,
        "situacao": Situacao.choices,
        "mes": [(numero, NOMES_MES[numero]) for numero in MESES],
        "reuniao": Reuniao.objects.order_by("-data"),
    }


def tags_ativas(get):
    """Monta as tags removíveis a partir dos filtros já validados; cada
    tag carrega o rótulo humano, o valor legível e a querystring
    resultante de removê-la."""
    filtros = filtros_ativos(get)
    brutas = []

    if exercicio_explicito(get):
        brutas.append(("exercicio", "Exercício", str(filtros["exercicio"].ano), None))

    if filtros["q"]:
        brutas.append(("q", "Busca", filtros["q"], None))

    # as chaves multi-valor emitem uma tag por valor selecionado; cada tag
    # carrega sua própria querystring, removendo só aquele valor
    for id_uo in filtros["uo"]:
        nome = Unidade.objects.filter(pk=id_uo).values_list(
            "nome", flat=True
        ).first()
        if nome:
            brutas.append(("uo", "Unidade", nome, id_uo))
    for id_categoria in filtros["categoria"]:
        nome = Categoria.objects.filter(pk=id_categoria).values_list(
            "nome", flat=True
        ).first()
        if nome:
            brutas.append(("categoria", "Categoria", nome, id_categoria))
    for id_tipo in filtros["tipo"]:
        nome = Tipo.objects.filter(pk=id_tipo).values_list(
            "nome", flat=True
        ).first()
        if nome:
            brutas.append(("tipo", "Tipo", nome, id_tipo))
    for valor_prioridade in filtros["prioridade"]:
        if valor_prioridade == SENTINEL_NAO_CLASSIFICADO:
            valor = "Não classificado"
        else:
            valor = GrauPrioridade.objects.filter(
                pk=valor_prioridade
            ).values_list("nome", flat=True).first()
        if valor:
            brutas.append(("prioridade", "Prioridade", valor, valor_prioridade))
    for valor_classificacao in filtros["classificacao"]:
        if valor_classificacao == SENTINEL_NAO_CLASSIFICADO:
            valor = "Não classificado"
        else:
            valor = Classificacao.objects.filter(
                pk=valor_classificacao
            ).values_list("nome", flat=True).first()
        if valor:
            brutas.append(("classificacao", "Classificação", valor, valor_classificacao))
    if filtros["modalidade"]:
        nome = Modalidade.objects.filter(pk=filtros["modalidade"]).values_list(
            "nome", flat=True
        ).first()
        if nome:
            brutas.append(("modalidade", "Modalidade", nome, None))
    for valor_estado in filtros["estado"]:
        brutas.append(
            ("estado", "Estado", dict(Estado.choices).get(valor_estado), valor_estado)
        )
    for valor_situacao in filtros["situacao"]:
        brutas.append(
            (
                "situacao",
                "Situação",
                dict(Situacao.choices).get(valor_situacao),
                valor_situacao,
            )
        )
    for valor_mes in filtros["mes"]:
        if valor_mes == SENTINEL_SEM_MES:
            valor = "Sem mês previsto"
        else:
            valor = NOMES_MES.get(valor_mes, str(valor_mes))
        brutas.append(("mes", "Mês previsto", valor, valor_mes))
    if filtros["atrasado"]:
        brutas.append(("atrasado", "Atrasados", "Sim", None))
    if filtros["reprometidos"]:
        brutas.append(("reprometidos", "Prazos remarcados", "Sim", None))
    if filtros["criticos"]:
        brutas.append(("criticos", "Críticos", "Sim", None))
    if filtros["proximo_prazo"]:
        brutas.append(("proximo_prazo", "Próximos do prazo", "Sim", None))
    if filtros["sem_atualizacao"]:
        brutas.append(("sem_atualizacao", "Sem atualização recente", "Sim", None))
    if filtros["vencimento_proximo"]:
        brutas.append(("vencimento_proximo", "Próximos do vencimento", "Sim", None))
    if filtros["sobrestado"]:
        brutas.append(("sobrestado", "Sobrestados", "Sim", None))
    if filtros["contratado"]:
        brutas.append(("contratado", "Valor contratado", "Sim", None))
    if filtros["publicacao_pendente"]:
        brutas.append(("publicacao_pendente", "Publicação pendente", "Sim", None))
    if filtros["legados"]:
        brutas.append(("legados", "Legados", "Apenas itens legados", None))
    if filtros["desde_reuniao"]:
        data_reuniao = Reuniao.objects.filter(
            pk=filtros["desde_reuniao"]
        ).values_list("data", flat=True).first()
        if data_reuniao:
            brutas.append(
                (
                    "desde_reuniao",
                    "Alterações na reunião",
                    f"Reunião de {data_reuniao:%d/%m/%Y}",
                    None,
                )
            )
    # uma tag combinada para as duas chaves escalares do intervalo de
    # data_recebimento_gelic; a remoção trata as duas chaves de uma vez
    if filtros["recebido_de"] or filtros["recebido_ate"]:
        de = filtros["recebido_de"]
        ate = filtros["recebido_ate"]
        if de and ate:
            valor_intervalo = f"{de:%d/%m/%Y} a {ate:%d/%m/%Y}"
        elif de:
            valor_intervalo = f"a partir de {de:%d/%m/%Y}"
        else:
            valor_intervalo = f"até {ate:%d/%m/%Y}"
        brutas.append(("recebido_de", "Recebido no Gelic", valor_intervalo, None))

    # mesma anatomia de tag combinada acima, para vigencia_fim
    if filtros["vigencia_fim_de"] or filtros["vigencia_fim_ate"]:
        de = filtros["vigencia_fim_de"]
        ate = filtros["vigencia_fim_ate"]
        if de and ate:
            valor_intervalo = f"{de:%d/%m/%Y} a {ate:%d/%m/%Y}"
        elif de:
            valor_intervalo = f"a partir de {de:%d/%m/%Y}"
        else:
            valor_intervalo = f"até {ate:%d/%m/%Y}"
        brutas.append(
            ("vigencia_fim_de", "Vencimento do contrato", valor_intervalo, None)
        )

    # tag do drill-down por dia; cai no else genérico do loop de remoção
    if filtros["dia_calendario"]:
        brutas.append(
            (
                "dia_calendario",
                "Dia (calendário)",
                f"{filtros['dia_calendario']:%d/%m/%Y}",
                None,
            )
        )

    tags = []
    for chave, rotulo, valor, valor_bruto in brutas:
        if chave in CHAVES_MULTIVALOR and valor_bruto is not None:
            querystring = querystring_filtros(
                get, excluir_valor=(chave, valor_bruto)
            )
        elif chave == "recebido_de":
            # a mesma tag representa duas chaves escalares — remover as duas juntas
            querystring = querystring_filtros(
                get, excluir=["recebido_de", "recebido_ate"]
            )
        elif chave == "vigencia_fim_de":
            querystring = querystring_filtros(
                get, excluir=["vigencia_fim_de", "vigencia_fim_ate"]
            )
        else:
            querystring = querystring_filtros(get, excluir=chave)
        tags.append(
            {
                "chave": chave,
                "rotulo": rotulo,
                "valor": valor,
                "querystring": querystring,
            }
        )
    return tags
