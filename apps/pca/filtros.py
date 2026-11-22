from datetime import date
from urllib.parse import urlencode

from django.conf import settings
from django.db.models import F, Q
from django.db.models.functions import Collate

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
from apps.pca.colunas import CHAVES_RESTRITAS_ACOMPANHAMENTO, _sem_permissao_acompanhamento
from apps.pca.models import Estado, Processo, Reuniao, Situacao

# Fase 17 — `Status` saiu por completo deste módulo: o
# filtro `legados` abaixo, que identificava o status do
# processo de ORIGEM numa continuação de exercício, passa a ler
# `origem__situacao` (eixo Situação, coluna crua — mesma leitura "sem
# correção" que a própria já fazia para `status`, decisão preservada:
# a lógica de herança entre exercícios não muda com a remoção do enum).

# /Pitfall 16 — este módulo é o ÚNICO ponto de construção do queryset
# filtrado. Tabela (02-01), dashboard (02-02), kanban/detalhe (02-03) e
# export (02-04) consomem `queryset_filtrado(request)`; nenhuma view monta o
# seu próprio filtro, ou os números divergem entre visões.

# Sentinelas (UI-SPEC §Color) — "não classificado" é filtro de
# primeira classe, não ausência silenciosa. `mes` usa sentinela própria
# porque o rótulo na tela é "Sem mês previsto", distinto de "Não
# classificado" (prioridade/classificação).
SENTINEL_NAO_CLASSIFICADO = "nao_classificado"
SENTINEL_SEM_MES = "sem_mes"

# Parâmetros canônicos do querystring — a única lista que define o que
# entra no filtro. Qualquer outra chave do GET é ignorada silenciosamente
# (nunca repassar o GET cru ao ORM).
#
# `atrasado`/`reprometidos` (02-02) são as duas flags de
# drill-down do dashboard sem controle próprio na barra de filtro global
# (UI-SPEC §Screen 1 — KPIs "Atrasados" e "Prazos remarcados").
# Precisam estar aqui, não só em `queryset_filtrado`, para que
# `querystring_filtros` as preserve ao reconstruir links de ordenação e
# paginação em `/tabela` depois do drill-down (Critério de Sucesso 2 —
# "a URL resultante... pode ser colada... e reaberta idêntica").
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
    # Filtro "Unidade no SEI" (`unidade_sei_atual`,
    # derivado pelo robô SEI). Escalar — NÃO entra em `CHAVES_MULTIVALOR`,
    # mesmo padrão de `modalidade`.
    "unidade_sei",
    # "Sem processo SEI" (nenhum nº SEI cadastrado). Só por
    # URL (drill-down do card do Início e do Assistente), sem controle
    # próprio na barra — mesmo padrão de `atrasado`/`sem_atualizacao`.
    "sem_processo_sei",
    "atrasado",
    "reprometidos",
    "contratado",
    "publicacao_pendente",
    "criticos",
    "proximo_prazo",
    "sem_atualizacao",
    # Fase 17 — as duas flags de drill-down
    # transversal do Bloco B: sem elas, o href de PRÓXIMOS DO VENCIMENTO/
    # SOBRESTADOS perderia o recorte na volta pela URL (o card mostraria N,
    # mas o clique abriria a tabela com TODOS os "no prazo"/ativos, não só o
    # subconjunto). Mesmo padrão de `criticos`/`proximo_prazo`/
    # `sem_atualizacao` acima.
    "vencimento_proximo",
    "sobrestado",
    "desde_reuniao",
    "legados",
    "exercicio",
    # Fase 24 — filtro de intervalo de datas para
    # `data_recebimento_gelic`, extensão autorizada do invariante de
    # preservação funcional (23) para dar clique à série "Entregue" da
    # curva trimestral. Escalares — NÃO entram em `CHAVES_MULTIVALOR`.
    "recebido_de",
    "recebido_ate",
    # Fase 24 — filtro de intervalo de datas ABSOLUTAS
    # para `vigencia_fim` (drill-down do gráfico "Vencimento de contratos
    # vigentes" da tela Análise). Diferente de recebido_de/recebido_ate
    # (24-04) — que comparam só o MÊS por causa de uma bucketização
    # year-agnostic pré-existente (ExtractQuarter) — vigência é uma data
    # de calendário real, então a comparação é por data ABSOLUTA
    # (`vigencia_fim__gte`/`__lte`), sem truncar o ano. Escalares — NÃO
    # entram em `CHAVES_MULTIVALOR`.
    "vigencia_fim_de",
    "vigencia_fim_ate",
    # Drill-down exato por dia do calendário
    # (`telas/calendario.md`): "+n" da visão mensal e o número do dia com
    # evento na visão anual levam aqui. Data ISO exata, parseada por
    # `_data_valida` (existente, intocada) — mesmo precedente literal de
    # `vigencia_fim_de`/`vigencia_fim_ate` acima, só que comparando
    # IGUALDADE (não intervalo) contra `prazo_efetivo` (annotation de
    # `para_listagem()`, já usada por `atrasado`/`situacao_efetiva` no
    # mesmo método — filtrável sem tocar `querysets.py`). Escalar — NÃO
    # entra em `CHAVES_MULTIVALOR`.
    "dia_calendario",
    # Fase 28 — a mesma seleção de condições da
    # legenda do calendário (`f"{eixo}:{valor}"`, allowlist fechada em
    # `ORDEM_CONDICOES_LEGENDA` abaixo), agora um parâmetro canônico de
    # `/tabela`: o "+n" do calendário (`views.py::_celula_dia`) propaga
    # `condicao_legenda` via `querystring_filtros` sem nenhum ponto de
    # montagem extra — o link já herda os tokens ativos automaticamente
    # por entrar nesta lista. Multivalor — entra em `CHAVES_MULTIVALOR`.
    "condicao_legenda",
)

# (herdado de 01-05) — mapa fechado de colunas permitidas para
# `?ordenar=`. Qualquer valor fora daqui cai no default (item_pca).
#
# Fase 11 — prazo_entrega, prazo_efetivo, n_prorrogacoes e
# dias_atraso entram como anotações de `para_listagem()`; nenhum nome cru
# fora desta lista chega a um `order_by()`.
COLUNAS_ORDENACAO = (
    "item_pca",
    "descricao_objeto",
    "valor_estimado",
    "valor_contratado",
    # Fase 17 — `status` cede lugar aos 3 eixos, cada um ordenável
    # isoladamente. `situacao_efetiva` (não `situacao` crua) para a
    # ordenação refletir a mesma correção de leitura que a exibição
    # usa; `tipo` ordena pela FK crua (mesmo padrão de
    # `unidade_organizacional` logo abaixo) — se precisar de tradução por
    # nome via `CAMPOS_ORDENACAO_FK` (views.py), é ajuste do plano.
    "estado",
    "tipo",
    "situacao",
    "situacao_efetiva",
    "mes_previsto",
    "n_reunioes",
    "n_compromissos",
    # Fase 29 — `prazo_inicial` substitui
    # `prazo_entrega` no mapa (a anotação COALESCE de `para_listagem()`,
    # nunca o campo cru — mesma identidade que a coluna/XLSX exibem).
    "prazo_inicial",
    "prazo_efetivo",
    "n_prorrogacoes",
    "dias_atraso",
    # Estas 10 chaves já existiam em `CABECALHOS_TABELA`
    # (views.py) e no seletor de colunas da tela, mas nunca entraram neste
    # mapa fechado: o cabeçalho renderizava `<span>` mudo e `?ordenar=`
    # caía em silêncio no padrão `item_pca`. reverteu a
    # exceção de `unidade_organizacional` aberta pela agora
    # são 10 chaves, sem exceção — todas as 22 colunas de
    # `CABECALHOS_TABELA` são ordenáveis.
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
    # Fase 29 — `categoria`/`justificativa` (campos
    # escalares simples, sem anotação nova necessária; `situacao_sei` saiu) deixam de ser exceção; as 12 chaves de Execução
    # contratual/Publicação entram todas, ordenáveis pelo nome
    # quando FK (`CAMPOS_ORDENACAO_FK`, views.py) ou pelo campo cru quando
    # data/texto solto.
    "categoria",
    "justificativa",
    # `unidade_sei_atual` é campo escalar simples, sem
    # anotação nova necessária: ordenação direta, mesmo padrão de
    # `numero_contratacao`.
    "unidade_sei_atual",
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

# Mesma disciplina de lista fechada para o SENTIDO da ordenação (§Screen Contracts 3). A direção também vai
# parar num `order_by()`, então nunca sai do GET cru: qualquer valor fora
# destes dois cai no padrão ascendente.
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
    """Converte para inteiro positivo; qualquer outra coisa vira None —
    nunca repassa a string do GET para o ORM."""
    if not valor:
        return None
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        return None
    # QA 30/09/2026 (fuzz B1) — um ID de 20+ dígitos no `__in=` levanta
    # `OverflowError` do SQLite (Python int grande demais para INTEGER);
    # mesmo teto que o Django já aplica ao lookup `exact`.
    if numero > 2**63 - 1:
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
    """Converte para `date`; qualquer formato inválido (ou ausência) vira
    None — nunca repassa a string crua do GET para o ORM (mesmo
    padrão de `_id_valido`)."""
    if not valor:
        return None
    try:
        return date.fromisoformat(str(valor))
    except (TypeError, ValueError):
        return None


def _texto_unidade_sei_valido(valor):
    """Sigla de unidade do SEI — `strip()`; vazio ou
    maior que o `max_length=80` de `unidade_sei_atual` vira None. Nunca
    repassa string crua ao ORM (mesmo padrão de `_id_valido`)."""
    if not valor:
        return None
    valor = valor.strip()
    if not valor or len(valor) > 80:
        return None
    return valor


def _estado_valido(valor):
    return valor if valor in Estado.values else None


def _situacao_valida(valor):
    return valor if valor in Situacao.values else None


# Gj7/ versões "em lista" dos validadores acima, para
# os 7 campos de domínio que viraram multi-seleção (uo, categoria, tipo,
# prioridade, classificacao, status, mes). Cada item passa pelo MESMO
# validador escalar que já existia (preservado item a item — nunca
# em bloco); item inválido é descartado silenciosamente, ordem de primeira
# ocorrência preservada, duplicatas removidas.
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
    """Lê uma chave como lista, aceitando tanto QueryDict (`.getlist`, o
    caso real de toda requisição HTTP) quanto um dict simples usado em
    alguns testes/chamadas internas (`{"exercicio": "2026"}`) — um valor
    escalar nesse caso vira lista de 1 item, nunca quebra por
    AttributeError."""
    getlist = getattr(get, "getlist", None)
    if getlist is not None:
        return getlist(chave)
    valor = get.get(chave)
    if valor is None:
        return []
    if isinstance(valor, (list, tuple)):
        return list(valor)
    return [valor]


# As 7 chaves que viraram multi-valor — usado por
# `querystring_filtros`/`tags_ativas` para saber quando tratar o valor como
# lista (um par por item) em vez de escalar.
CHAVES_MULTIVALOR = (
    "uo",
    "categoria",
    "tipo",
    "prioridade",
    "classificacao",
    "estado",
    "situacao",
    "mes",
    # Fase 28 — ver comentário em `PARAMETROS_FILTRO`.
    "condicao_legenda",
)


# Fase 28 — os 5 tokens `(eixo, valor)` possíveis para
# `condicao_legenda`, MESMA ordem/chave que a legenda do calendário sempre
# usou (`apps/pca/views.py::ORDEM_ROSCA`, Fase 17): um
# processo tem exatamente UMA condição — Cancelado (eixo Estado,
# independente da `situacao` gravada) ou uma das 4 situações EFETIVAS dos
# ativos (`situacao_efetiva`, correção-na-leitura). Vive aqui (não em
# `views.py`) para `queryset_filtrado`/`q_condicao_legenda` — a fonte ÚNICA
# de parsing de token, reaproveitada pelo calendário via
# `views.py::_resolver_condicao_legenda`, que agora só delega.
ORDEM_CONDICOES_LEGENDA = (
    ("estado", Estado.CANCELADO.value),
    ("situacao", Situacao.CONCLUIDO.value),
    ("situacao", Situacao.NO_PRAZO.value),
    ("situacao", Situacao.EM_TRAMITACAO.value),
    ("situacao", Situacao.ATRASADO.value),
)

# Sentinela hand-crafted — `condicao_legenda=nenhum` esvazia o
# conjunto ativo por completo (nenhuma das 5 condições), distinto de
# "ausente" (todas as 5 ativas, "sem filtro"). Preservado por
# retrocompatibilidade com `?status_legenda=nenhum` de eras anteriores.
SENTINEL_CONDICAO_LEGENDA_NENHUM = "nenhum"


def resolver_condicao_legenda(valores):
    """Fase 28 — fonte ÚNICA do parsing/validação de
    `condicao_legenda` (antes só em `views.py::_resolver_condicao_legenda`,
    Fase 17): recebe a lista crua de tokens (`get.getlist(
    "condicao_legenda")`) e devolve `(conjunto_ativo, tokens_na_ordem_de_
    ORDEM_CONDICOES_LEGENDA)`. Cada token textual é `f"{eixo}:{valor}"`
    (01 — evita colisão entre um `valor` de `situacao` e um de
    `estado` que por acaso tivessem o mesmo texto). Lista vazia (parâmetro
    ausente) devolve todas as 5 condições ativas, SEM tokens — "sem
    filtro" nunca vira uma lista completa no querystring.
    `[SENTINEL_CONDICAO_LEGENDA_NENHUM]` devolve conjunto vazio. Qualquer
    outra lista é filtrada contra `ORDEM_CONDICOES_LEGENDA` (allowlist
    fechada, -01); se nada válido sobrar, cai no caso "ausente"."""
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
    """Fase 28 — `Q()` de UNIÃO (nunca interseção)
    para os tokens de `condicao_legenda`, aplicável por `queryset_filtrado`
    — mesma condição que o calendário já aplica em Python sobre uma lista
    materializada (`views.py::_condicao_calendario`). Devolve `None`
    quando o conjunto resolvido é "todas as 5" (ausente/sem filtro — o
    chamador não aplica nada); um `Q(pk__in=[])` (nunca casa nada) quando o
    conjunto é vazio (sentinela "nenhum"); senão a união de um `Q(estado=
    CANCELADO)` (se o token `estado:cancelado` estiver presente) com um
    `Q(estado=ATIVO, situacao_efetiva=<valor>)` por cada token
    `situacao:<valor>` presente — NUNCA `Q(estado__in=...) &
    Q(situacao__in=...)`, que seria INTERSEÇÃO (01)."""
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
    """Normaliza uma flag booleana do querystring para o valor canônico
    "1" ou None — nunca repassa a string crua do GET."""
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


def ordenacao_valida(valor, request=None):
    """QA de segurança 30/09/2026 (achado B1) — sem `pca.view_acompanhamento`
    (`request` passado por quem decide a ordem REAL do `order_by()`), as
    chaves de `CHAVES_RESTRITAS_ACOMPANHAMENTO` saem do mapa de colunas
    ordenáveis: `?ordenar=n_reunioes` deixa de reordenar de verdade para
    esse perfil, caindo no padrão (`item_pca`)."""
    colunas_permitidas = COLUNAS_ORDENACAO
    if _sem_permissao_acompanhamento(request):
        colunas_permitidas = tuple(
            c for c in COLUNAS_ORDENACAO if c not in CHAVES_RESTRITAS_ACOMPANHAMENTO
        )
    return valor if valor in colunas_permitidas else COLUNA_ORDENACAO_PADRAO


def direcao_valida(valor):
    """Normaliza `?dir=` para "asc" ou "desc" — nunca repassa a string crua
    do GET, que aqui viraria parte de um `order_by()`."""
    return valor if valor in DIRECOES_ORDENACAO else DIRECAO_ORDENACAO_PADRAO


def filtros_ativos(get):
    """Lê o QueryDict cru e devolve um dict só com os parâmetros canônicos,
    já validados e tipados — a única representação que qualquer outra
    função deste módulo (ou qualquer view) deve usar. Nunca devolve a
    string crua do GET."""
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
        # Ver comentário em `PARAMETROS_FILTRO`.
        "unidade_sei": _texto_unidade_sei_valido(get.get("unidade_sei")),
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
        "sem_processo_sei": _flag_valida(get.get("sem_processo_sei")),
        # Fase 17 — recortes transversais do Bloco B.
        "vencimento_proximo": _flag_valida(get.get("vencimento_proximo")),
        "sobrestado": _flag_valida(get.get("sobrestado")),
        "desde_reuniao": _id_valido(get.get("desde_reuniao")),
        "legados": _flag_valida(get.get("legados")),
        # Fase 24 — intervalo de datas para
        # `data_recebimento_gelic`, ver comentário em `PARAMETROS_FILTRO`.
        "recebido_de": _data_valida(get.get("recebido_de")),
        "recebido_ate": _data_valida(get.get("recebido_ate")),
        # Fase 24 — ver comentário em `PARAMETROS_FILTRO`.
        "vigencia_fim_de": _data_valida(get.get("vigencia_fim_de")),
        "vigencia_fim_ate": _data_valida(get.get("vigencia_fim_ate")),
        # Ver comentário em `PARAMETROS_FILTRO`.
        "dia_calendario": _data_valida(get.get("dia_calendario")),
        # Fase 28 — já resolvido/validado contra a
        # allowlist fechada (`resolver_condicao_legenda`): tokens na ordem
        # canônica, `[]` quando ausente ("sem filtro" nunca vira lista
        # completa no querystring), `["nenhum"]` quando o sentinela está
        # ativo.
        "condicao_legenda": resolver_condicao_legenda(_getlist(get, "condicao_legenda"))[1],
        "exercicio": exercicio,
    }


# Fase 28 — `q_busca_ampla` (descrição/justificativa/SEI,
# 3 campos) saiu deste módulo: `apps.pca.busca.aplicar_busca` é agora a fonte
# ÚNICA de interpretação do termo `q`, com toda a allowlist de campos por
# família (Identificação/Descrição/Classificação/Situação/Financeiro/
# Planejamento/Contratação/Indicadores), compartilhada com a busca global
# (`apps.pca.views_busca.busca_view`). Ver `queryset_filtrado` abaixo.


def queryset_filtrado(request):
    """Ponto único de construção do queryset filtrado (Pitfall 16).
    Parte sempre de `Processo.objects.para_listagem()`; nunca repassa o GET
    cru ao ORM (mitigado por `filtros_ativos`)."""
    filtros = filtros_ativos(request.GET)
    exercicio = filtros["exercicio"]
    qs = Processo.objects.para_listagem().filter(exercicio=exercicio)
    # QA de segurança 30/09/2026 (achado B1) — sem `pca.view_acompanhamento`,
    # os filtros `reprometidos`/`proximo_prazo`/`sem_atualizacao` (que só
    # fazem sentido olhando para o histórico de acompanhamento) são
    # silenciosamente ignorados, nunca um erro.
    restringir = _sem_permissao_acompanhamento(request)

    # Legacy selection is deliberately applied only after the
    # server-resolved annual scope.  The origin status is read from the
    # previous process, not from the continuation itself.
    if filtros["legados"]:
        qs = qs.filter(origem__isnull=False).exclude(
            origem__situacao=Situacao.CONCLUIDO
        )

    if filtros["q"]:
        # Fase 28 — import local: evita ciclo com
        # `apps.pca.busca` (que precisa de `NOMES_MES`, definido neste
        # módulo, para a interpretação de mês por nome). `.distinct()`
        # removido deliberadamente: `aplicar_busca` usa `Exists` (não JOIN)
        # para números SEI — a única relação 1:N da união — e todo outro
        # campo da allowlist é FK to-one (nunca duplica linha). Avisos (ex.
        # data inválida) são descartados aqui: a tabela de Processos não
        # tem, hoje, um lugar para exibi-los (limitação conhecida); a busca global (`views_busca.py`) os exibe.
        from apps.pca.busca import aplicar_busca

        qs, _avisos_busca_tabela = aplicar_busca(qs, filtros["q"], request=request)

    # Gj7/ uo/categoria/tipo/status viram `__in` (OR
    # entre os valores de um mesmo filtro); nunca filtra quando a lista está
    # vazia (campo não usado = sem restrição, igual a antes da conversão).
    if filtros["uo"]:
        qs = qs.filter(unidade_organizacional_id__in=filtros["uo"])
    if filtros["categoria"]:
        qs = qs.filter(categoria_id__in=filtros["categoria"])
    if filtros["tipo"]:
        qs = qs.filter(tipo_id__in=filtros["tipo"])
    if filtros["modalidade"]:
        qs = qs.filter(modalidade_id=filtros["modalidade"])
    if filtros["unidade_sei"]:
        # `unidade_sei_atual` guarda UMA sigla
        # (a unidade de destino da última linha "Processo remetido pela
        # unidade X" do histórico, `apps.pca.sei.regras.unidade_atual`);
        # igualdade simples, sem malabarismo de separador.
        qs = qs.filter(unidade_sei_atual=filtros["unidade_sei"])
    if filtros["sem_processo_sei"]:
        qs = qs.filter(numeros_sei__isnull=True)

    # prioridade/classificacao/mes misturam a sentinela ("não classificado"/
    # "sem mês") com ids/números reais na MESMA lista — cada ramo só entra
    # no Q() combinado se tiver conteúdo, para nunca aplicar um Q() vazio
    # que zeraria o resultado à toa.
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

    # Fase 17 — `estado`/`situacao` substituem `status`. `situacao`
    # filtra pela anotação CORRIGIDA `situacao_efetiva`, nunca pela
    # coluna crua `situacao` — um filtro `?situacao=atrasado` inclui tanto os
    # gravados `atrasado` quanto os `no_prazo` com `prazo_entrega` vencido.
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

    # Fase 24 — intervalo de MÊS (não de data absoluta)
    # para `data_recebimento_gelic`, ambos os lados opcionais e
    # independentes. Descoberta (bug): a curva
    # trimestral (`entregues_por_trimestre`) já bucketiza por
    # `ExtractQuarter(data_recebimento_gelic)` — só o MÊS, sem restrição de
    # ano — porque processos de um exercício podem carregar
    # `data_recebimento_gelic` de anos anteriores (dado real da planilha,
    # sem vínculo de `origem`/legado). Um filtro por data ABSOLUTA
    # (`__gte`/`__lte` no valor completo, incluindo ano) quebra a coerência
    # exigida entre o número mostrado no ponto do gráfico e a
    # contagem de `/tabela` ao clicar (confirmado com `ARQUIVO_REAL`:
    # trimestre 2 mostra 20, um filtro por data absoluta devolvia 17 — 3
    # processos com `data_recebimento_gelic` de 2025 dentro do mês
    # abril-junho ficavam de fora). `recebido_de`/`recebido_ate` continuam
    # recebendo uma data ISO completa (para o rótulo da tag e a legibilidade
    # da URL), mas só o MÊS de cada um entra na comparação — mesma leitura
    # "sem ano" que `ExtractQuarter` já faz.
    if filtros["recebido_de"]:
        qs = qs.filter(data_recebimento_gelic__month__gte=filtros["recebido_de"].month)
    if filtros["recebido_ate"]:
        qs = qs.filter(data_recebimento_gelic__month__lte=filtros["recebido_ate"].month)

    # Fase 24 — intervalo de data ABSOLUTA (com ano) para
    # `vigencia_fim`, ao contrário do filtro de MÊS acima: vencimento de
    # contrato é uma data de calendário real, não um recorte recorrente
    # (ver comentário em `PARAMETROS_FILTRO`).
    if filtros["vigencia_fim_de"]:
        qs = qs.filter(vigencia_fim__gte=filtros["vigencia_fim_de"])
    if filtros["vigencia_fim_ate"]:
        qs = qs.filter(vigencia_fim__lte=filtros["vigencia_fim_ate"])

    # Drill-down exato por dia do calendário (ver
    # comentário em `PARAMETROS_FILTRO`).
    if filtros["dia_calendario"]:
        qs = qs.filter(prazo_efetivo=filtros["dia_calendario"])

    # Fase 28 — mesma seleção de condições que a
    # legenda do calendário aplica em Python; `q_condicao_legenda` devolve
    # `None` quando é "todas as 5" (sem filtro, nada a aplicar).
    if filtros["condicao_legenda"]:
        condicao_legenda = q_condicao_legenda(filtros["condicao_legenda"])
        if condicao_legenda is not None:
            qs = qs.filter(condicao_legenda)

    # /02 (drill-down do dashboard, 02-02) — `atrasado`/`reprometido`
    # já chegam anotados por `para_listagem()`; aqui só filtramos, nunca
    # recalculamos.
    if filtros["atrasado"]:
        qs = qs.filter(atrasado=True)
    if filtros["reprometidos"] and not restringir:
        qs = qs.filter(reprometido=True)
    if filtros["contratado"]:
        qs = qs.filter(valor_contratado__isnull=False)
    if filtros["publicacao_pendente"]:
        qs = qs.filter(publicacao_pendente=True)
    if filtros["criticos"]:
        qs = qs.criticos()
    if filtros["proximo_prazo"] and not restringir:
        qs = qs.proximos_do_prazo()
    if filtros["sem_atualizacao"] and not restringir:
        qs = qs.sem_atualizacao_recente()
    # Fase 17 — recortes transversais do Bloco B,
    # mesmo padrão dos três flags acima: mensagem já anotada por
    # `para_listagem()`, aqui só filtramos.
    if filtros["vencimento_proximo"]:
        qs = qs.proximo_vencimento_gelic(settings.PCA_DIAS_PROXIMOS_VENCIMENTO)
    if filtros["sobrestado"]:
        qs = qs.sobrestados()

    # A chave de querystring `desde_reuniao` é histórica (Fase 3: filtrava
    # acompanhamentos POSTERIORES à data). A partir de 2026-09-01 (quick,
    # decisão do usuário) a pergunta virou "o que mudou NA reunião
    # escolhida" — igualdade de data, não FK `reuniao_id`, para incluir também
    # os lançamentos automáticos/administrativos do mesmo dia (`reuniao=None`,
    # `referencia_data=localdate()`); a chave em si não muda, só a semântica.
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
    """Reserializa somente os parâmetros canônicos VALIDADOS — nunca a
    querystring crua do GET. `excluir` remove uma ou mais chaves inteiras
    (tags removíveis; aceita uma chave escalar OU uma lista/tupla de
    chaves — Fase 17: o segundo clique de um card de KPI
    com `overrides` multi-chave, ex. `{"estado": [...], "situacao": [...]}`,
    precisa remover as DUAS chaves de uma vez, `apps/pca/kpis.py::card()`);
    `excluir_valor` (tupla `(chave, valor)`, -gj7) remove
    só UM valor de uma chave multi-valor, mantendo os demais; `overrides`
    substitui o valor de uma chave (ex.: o link "Não classificado" na
    tabela, que soma `prioridade=nao_classificado` ao filtro atual sem
    descartar os demais) — para as 7 chaves multi-valor, um override
    escalar vira lista de 1 item (backward compatible com as chamadas
    existentes de drill-down)."""
    valores = dict(filtros_ativos(get))
    for chave, valor in overrides.items():
        if chave in CHAVES_MULTIVALOR:
            # Override em lista/tupla (os ramos
            # combinados do funil executivo, ex. status=(VIGENTE,
            # A_RENOVAR)) preserva a ordem recebida; o comportamento
            # escalar pré-existente (um valor -> lista de 1 item) continua
            # idêntico, retrocompatível com toda chamada já existente.
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
            # Um par (chave, valor) por item selecionado — com um único
            # valor isso produz exatamente a mesma string de antes da
            # conversão (ex. "uo=3"), preservando compatibilidade.
            for item in valor or ():
                if item:
                    partes.append((chave, item))
            continue
        if not valor:
            continue
        # The greatest open exercise is implicit. Keep it out of the
        # URL until the user explicitly selects an exercise, while retaining
        # it through every canonical link after an explicit selection.
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


VISTA_TABELA = "tabela"
VISTA_LISTA = "lista"


def vista_valida(valor):
    """Allowlist da visualização da tela Processos:
    "lista" (resultados um embaixo do outro, como a busca de editais do
    PNCP) ou "tabela" (padrão, a de sempre, com a escolha de colunas)."""
    return VISTA_LISTA if valor == VISTA_LISTA else VISTA_TABELA


def querystring_tabela(get, excluir=None, excluir_valor=None, **overrides):
    """Fonte ÚNICA de "estado idêntico à tabela" —
    `querystring_filtros` (só os filtros de domínio, validados) mais
    `ordenar`/`dir`/`pagina`/`por_pagina`/`colunas`, cada um só incluído
    quando a CHAVE está presente em `get` (nunca grava o padrão implícito).
    Toda superfície que devolve o usuário à mesma tabela/sequência — link
    da linha, Anterior/Próximo, Voltar, trilha, Editar/Alterar situação/
    Registrar acompanhamento e os redirects PRG de volta ao detalhe — usa
    esta função, nunca `querystring_filtros` sozinha nem o GET cru."""
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
    # Visualização da tela Processos (Lista | Tabela).
    # Só a lista entra no estado: a tabela é o padrão implícito, nunca gravado.
    if vista_valida(get.get("vista")) == VISTA_LISTA:
        extras.append(("vista", VISTA_LISTA))
    pedaco_extra = urlencode(extras, doseq=True) if extras else ""
    partes_finais = [p for p in (base, pedaco_extra) if p]
    return "&".join(partes_finais)


def opcoes_filtros():
    """Opções para os `<select>` da barra de filtro global — vocabulário
    fixo, não depende do usuário nem da requisição."""
    return {
        "exercicio": Exercicio.objects.order_by("-ano"),
        "uo": Unidade.objects.order_by(Collate(F("nome"), "ptbr")),
        "categoria": Categoria.objects.order_by(Collate(F("nome"), "ptbr")),
        "tipo": Tipo.objects.order_by(Collate(F("nome"), "ptbr")),
        "prioridade": GrauPrioridade.objects.order_by(Collate(F("nome"), "ptbr")),
        "classificacao": Classificacao.objects.order_by(Collate(F("nome"), "ptbr")),
        "estado": Estado.choices,
        "situacao": Situacao.choices,
        "mes": [(numero, NOMES_MES[numero]) for numero in MESES],
        "reuniao": Reuniao.objects.order_by("-data"),
    }


def opcoes_unidade_sei(exercicio):
    """Siglas distintas de `unidade_sei_atual` no exercício corrente, para
    o `<select>` do filtro "Unidade no SEI". Campo
    escalar simples — uma sigla por processo — direto do
    `values_list(...).distinct()`, sem split."""
    if exercicio is None:
        return []
    valores = (
        Processo.objects.filter(exercicio=exercicio)
        .exclude(unidade_sei_atual="")
        .values_list("unidade_sei_atual", flat=True)
        .distinct()
    )
    return sorted(set(valores))


def tags_ativas(get):
    """Monta as tags removíveis a partir dos filtros já validados —
    cada tag carrega o rótulo humano, o valor legível e a querystring
    resultante de removê-la (nunca a querystring crua do GET)."""
    filtros = filtros_ativos(get)
    brutas = []

    if exercicio_explicito(get):
        brutas.append(("exercicio", "Exercício", str(filtros["exercicio"].ano), None))

    if filtros["q"]:
        brutas.append(("q", "Busca", filtros["q"], None))

    # Gj7/ as 7 chaves multi-valor emitem UMA tag por
    # valor selecionado (rótulo humano igual ao que já existia, dentro de um
    # loop); cada tag carrega sua própria querystring, calculada removendo
    # só aquele valor (`excluir_valor`), preservando os demais.
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
    if filtros["unidade_sei"]:
        # Cai no ramo `else` genérico de remoção (`excluir=chave`) — mesmo
        # padrão de `modalidade` acima.
        brutas.append(("unidade_sei", "Unidade no SEI", filtros["unidade_sei"], None))
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
    if filtros["sem_processo_sei"]:
        brutas.append(("sem_processo_sei", "Sem processo SEI", "Sim", None))
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
    # Fase 24 — UMA tag combinada para as duas chaves
    # escalares do intervalo de `data_recebimento_gelic` (qualquer lado
    # presente já ativa a tag); o loop abaixo trata a remoção das duas
    # chaves de uma vez (não é o `excluir=chave` genérico).
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

    # Fase 24 — mesma anatomia de tag combinada acima,
    # para as duas chaves escalares de `vigencia_fim`.
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

    # Tag do drill-down por dia; cai no `else` genérico
    # do loop de remoção abaixo, não precisa de tratamento especial.
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
            # A mesma tag representa DUAS chaves escalares — remover as
            # duas juntas (ver comentário acima), não só `recebido_de`.
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
