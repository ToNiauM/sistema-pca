"""Motor Python do "git log" do PCA. Nenhuma view reimplementa esta
lógica: exige uma fonte única, agregada no ORM, testável isoladamente.

Os contratos de dados (dataclasses), o motor de diff de histórico, o
dicionário de frases por campo e os blocos que não dependem de
Acompanhamento.prazo_prometido (Inclusões, Exclusões, Iniciados,
Concluídos) devolvem "candidato bruto" (dict[int, dict]). A apuração da
situação do compromisso de reunião, o bloco Adiados, o bloco Alterações, e
montar_relatorio() fecham o módulo: a orquestração final que aplica a
deduplicação "um item, um bloco" e devolve o RelatorioMovimentacao
completo.

Nenhuma tabela nova: tudo é derivado de Processo, Acompanhamento, Reuniao,
RascunhoVirada/RascunhoItemVirada e do simple_history já existentes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Min, OuterRef, Subquery, Sum
from django.utils import timezone

from apps.catalogo.models import Exercicio, InstrumentoContratual, Modalidade, Unidade
from apps.pca.filtros import NOMES_MES
from apps.pca.models import (
    Acompanhamento,
    Estado,
    Processo,
    RascunhoItemVirada,
    Reuniao,
    Situacao,
    TipoEvento,
)
from core.templatetags.dsgov import data_br, moeda

# ---------------------------------------------------------------------------
# Contratos (dataclasses)
# ---------------------------------------------------------------------------


@dataclass
class MudancaCampo:
    """Uma transição pontual de valor de um campo, lida do history."""

    data: datetime
    de: object
    para: object


@dataclass
class ItemRelatorio:
    """Um processo dentro de um bloco do relatório, com sua(s) frase(s)."""

    processo: Processo
    frase_principal: str
    frases_extra: list = field(default_factory=list)
    automatico: bool = False


@dataclass
class BlocoRelatorio:
    """Um dos 6 blocos do relatório (Inclusões, Exclusões, ...)."""

    chave: str
    titulo: str
    contagem: int
    soma_valor: Decimal | None
    itens: list = field(default_factory=list)
    mensagem_vazio: str = "Nenhum item neste período."


@dataclass
class RelatorioMovimentacao:
    """O relatório completo de um exercício entre duas datas."""

    exercicio: Exercicio
    de: date
    ate: date
    blocos: list
    gerado_em: datetime
    gerado_por: str


# ---------------------------------------------------------------------------
# ordens e vocabulário fixo dos blocos
# ---------------------------------------------------------------------------

# ordem de leitura do relatório
ORDEM_EXIBICAO_BLOCOS = (
    "inclusoes",
    "exclusoes",
    "iniciados",
    "concluidos",
    "adiados",
    "alteracoes",
)

# ordem de desempate quando um processo se qualifica para mais de um
# bloco — nunca a mesma tupla usada para exibição: Concluídos pesa mais
# que Iniciados na precedência
ORDEM_PRECEDENCIA_BLOCOS = (
    "inclusoes",
    "exclusoes",
    "concluidos",
    "iniciados",
    "adiados",
    "alteracoes",
)

TITULOS_BASE_BLOCOS = {
    "inclusoes": "Inclusões",
    "exclusoes": "Exclusões",
    "iniciados": "Iniciados — encaminhados à Gelic",
    "concluidos": "Concluídos",
    "adiados": "Adiados — compromissos assumidos em reunião",
    "alteracoes": "Alterações",
}

# trilha compacta ("ago -> set em 05/08..."). O valor líquido de mês
# previsto usa NOMES_MES por extenso, não isto
ABREV_MES = {
    1: "jan",
    2: "fev",
    3: "mar",
    4: "abr",
    5: "mai",
    6: "jun",
    7: "jul",
    8: "ago",
    9: "set",
    10: "out",
    11: "nov",
    12: "dez",
}

# campos curados do bloco Alterações. Fora: descrição, justificativa,
# categoria, tipo, grau, classificação, situação SEI, datas do funil que
# não são envio à Gelic
CAMPOS_ALTERACOES = (
    "valor_estimado",
    "mes_previsto",
    "unidade_organizacional",
    "situacao",
    "modalidade",
    "numero_contratacao",
    "numero_arp",
    "instrumento_contratual",
    "numero_instrumento_contratual",
    "valor_contratado",
    "fornecedor_cnpj",
    "fornecedor_razao_social",
    "data_assinatura_contrato",
    "vigencia_inicio",
    "vigencia_fim",
    "data_lancamento_spw",
    "data_lancamento_wordpress",
    "data_lancamento_dados_abertos",
)

# Campos históricos de FK que exigem leitura por `<campo>_id` (o atributo
# sem `_id` no registro histórico dispara uma query ao valor ATUAL da FK).
CAMPOS_FK_HISTORICO = {"unidade_organizacional", "modalidade", "instrumento_contratual"}

# "a situação melhorou" compara o peso da situação, não o valor cru:
# NO_PRAZO/ATRASADO empatam, EM_TRAMITACAO é o próximo estágio, CONCLUIDO
# o final
PESO_SITUACAO = {
    Situacao.NO_PRAZO: 0,
    Situacao.ATRASADO: 0,
    Situacao.EM_TRAMITACAO: 1,
    Situacao.CONCLUIDO: 2,
}

_CAMPOS_DATA = {
    "data_assinatura_contrato",
    "vigencia_inicio",
    "vigencia_fim",
    "data_lancamento_spw",
    "data_lancamento_wordpress",
    "data_lancamento_dados_abertos",
}

# dicionário de frases por campo (rótulo institucional + particípio com
# concordância de gênero), reutilizado por todos os blocos que descrevem
# "de -> para". Vive em Python, não no template
FRASES_CAMPO = {
    "valor_estimado": ("valor estimado", "alterado"),
    "mes_previsto": ("mês previsto", "alterado"),
    "unidade_organizacional": ("unidade organizacional", "alterada"),
    "situacao": ("situação", "alterada"),
    "estado": ("estado", "alterado"),
    "modalidade": ("modalidade", "alterada"),
    "numero_contratacao": ("nº da contratação", "alterado"),
    "numero_arp": ("nº da ARP", "alterado"),
    "instrumento_contratual": ("instrumento contratual", "alterado"),
    "numero_instrumento_contratual": ("nº do instrumento contratual", "alterado"),
    "valor_contratado": ("valor contratado", "alterado"),
    "fornecedor_cnpj": ("CNPJ do fornecedor", "alterado"),
    "fornecedor_razao_social": ("razão social do fornecedor", "alterada"),
    "data_assinatura_contrato": ("data de assinatura do contrato", "alterada"),
    "vigencia_inicio": ("início de vigência", "alterado"),
    "vigencia_fim": ("fim de vigência", "alterado"),
    "data_lancamento_spw": ("lançamento no SPW", "alterado"),
    "data_lancamento_wordpress": ("lançamento no WordPress", "alterado"),
    "data_lancamento_dados_abertos": ("lançamento em Dados Abertos", "alterado"),
}


# ---------------------------------------------------------------------------
# Formatação de valores e frases
# ---------------------------------------------------------------------------


def _truncar_descricao(texto, limite=60):
    texto = texto or ""
    if len(texto) <= limite:
        return texto
    return texto[: limite - 1].rstrip() + "…"


def _como_data_local(valor):
    """Reduz um datetime tz-aware à data em America/Sao_Paulo; as frases
    mostram só dd/mm/aaaa, nunca hora."""
    if isinstance(valor, datetime):
        return timezone.localtime(valor).date()
    return valor


def formatar_valor_campo(campo, valor, *, mapas_fk):
    """Rótulo humano pt-BR de um valor de campo, para uso fora de template."""
    if campo in ("valor_estimado", "valor_contratado"):
        return moeda(valor)
    if campo == "mes_previsto":
        return NOMES_MES.get(valor, "sem mês previsto definido")
    if campo in CAMPOS_FK_HISTORICO:
        return mapas_fk.get(campo, {}).get(valor, "—")
    if campo == "situacao":
        return Situacao(valor).label if valor else "—"
    if campo == "estado":
        return Estado(valor).label if valor else "—"
    if campo in _CAMPOS_DATA:
        return data_br(valor)
    return str(valor) if valor else "—"


def frase_mudanca_campo(campo, de_valor, para_valor, data, *, processo, mapas_fk):
    """Frase completa "Item N - descrição (UO): rótulo particípio de X
    para Y em dd/mm/aaaa"."""
    rotulo, participio = FRASES_CAMPO[campo]
    descricao = _truncar_descricao(processo.descricao_objeto)
    de_fmt = formatar_valor_campo(campo, de_valor, mapas_fk=mapas_fk)
    para_fmt = formatar_valor_campo(campo, para_valor, mapas_fk=mapas_fk)
    data_fmt = data_br(_como_data_local(data))
    return (
        f"Item {processo.item_pca} – {descricao} "
        f"({processo.unidade_organizacional.nome}): {rotulo} {participio} de "
        f"{de_fmt} para {para_fmt} em {data_fmt}."
    )


# ---------------------------------------------------------------------------
# motor de diff de histórico
# ---------------------------------------------------------------------------


def _limites_do_dia(de: date, ate: date):
    """Limites inclusivos [de 00:00, até 23:59:59] em America/Sao_Paulo,
    tz-aware, sem aritmética manual de UTC."""
    inicio = timezone.make_aware(datetime.combine(de, time.min))
    fim = timezone.make_aware(datetime.combine(ate, time.max))
    return inicio, fim


def _historico_ate_por_processo(exercicio, fim):
    """Devolve dict[int, list]: para cada id de processo do exercicio, a
    lista de seus registros de history com history_date <= fim, ordenada
    por (history_date, history_id). Uma query SQL para o exercício
    inteiro, não uma por processo.

    Só o limite superior (fim) é seguro para filtrar no SQL. diff_against
    precisa do registro imediatamente anterior ao início do período para
    produzir o primeiro "de -> para" dentro da janela, e essa linha-base
    pode estar arbitrariamente longe no passado."""
    registros = (
        Processo.history.filter(exercicio=exercicio, history_date__lte=fim)
        .order_by("id", "history_date", "history_id")
    )
    mapa = {}
    for registro in registros:
        mapa.setdefault(registro.id, []).append(registro)
    return mapa


def mudancas_no_periodo(processo, *, de: date, ate: date, campos: tuple, registros=None):
    """Devolve dict[str, list[MudancaCampo]]: para cada campo em campos,
    as mudanças desse campo cujo history_date cai dentro de [de, ate].

    Monta pares consecutivos (anterior, atual) a partir do history do
    processo e usa diff_against. Ignora o primeiro registro histórico.

    registros, quando informado, é usado diretamente sem nenhuma query
    própria. Quando omitido (None), consulta o history deste processo
    isoladamente."""
    inicio, fim = _limites_do_dia(de, ate)
    resultado = {campo: [] for campo in campos}
    if registros is None:
        # pk= no manager histórico filtra pelo history_id (chave própria
        # de cada snapshot), não pelo id do objeto original; id= é o campo
        # que espelha a chave do objeto rastreado
        registros = list(
            type(processo).history.filter(id=processo.pk).order_by("history_date", "history_id")
        )
    anterior = None
    for atual in registros:
        if anterior is not None:
            if inicio <= atual.history_date <= fim:
                diff = atual.diff_against(anterior)
                for campo in diff.changed_fields:
                    if campo not in resultado:
                        continue
                    if campo in CAMPOS_FK_HISTORICO:
                        valor_de = getattr(anterior, f"{campo}_id")
                        valor_para = getattr(atual, f"{campo}_id")
                    else:
                        valor_de = getattr(anterior, campo)
                        valor_para = getattr(atual, campo)
                    resultado[campo].append(
                        MudancaCampo(data=atual.history_date, de=valor_de, para=valor_para)
                    )
        anterior = atual
    return resultado


def consolidar_mudancas(mudancas: list):
    """Devolve (valor_de_liquido, valor_para_liquido, trilha_ou_none).

    valor_de_liquido é o .de do primeiro item em ordem cronológica;
    valor_para_liquido é o .para do último. Quando há mais de uma mudança,
    trilha_ou_none é uma lista crua de tuplas (de, para, data) em ordem
    cronológica. Esta função fica agnóstica de campo de propósito."""
    ordenadas = sorted(mudancas, key=lambda m: m.data)
    valor_de_liquido = ordenadas[0].de
    valor_para_liquido = ordenadas[-1].para
    trilha_ou_none = None
    if len(ordenadas) > 1:
        trilha_ou_none = [(m.de, m.para, m.data) for m in ordenadas]
    return valor_de_liquido, valor_para_liquido, trilha_ou_none


# ---------------------------------------------------------------------------
# resolução de período
# ---------------------------------------------------------------------------


def resolver_periodo_relatorio(get, exercicio):
    """Devolve (date, date) a partir do GET da tela, nunca lança exceção
    para entrada malformada, cai sempre no default.

    Precedência: datas livres (de/ate) > reunião selecionada > default
    (última reunião do exercício até hoje, ou últimos 30 dias sem
    reunião)."""
    de_str = get.get("de")
    ate_str = get.get("ate")
    if de_str and ate_str:
        try:
            return date.fromisoformat(de_str), date.fromisoformat(ate_str)
        except (TypeError, ValueError):
            pass

    reuniao_id = get.get("reuniao")
    if reuniao_id:
        reuniao = (
            Reuniao.objects.filter(pk=reuniao_id, exercicio=exercicio).first()
            if str(reuniao_id).isdigit()
            else None
        )
        if reuniao is not None:
            ate = reuniao.data
            anterior = (
                Reuniao.objects.filter(exercicio=exercicio, data__lt=reuniao.data)
                .order_by("-data")
                .first()
            )
            de = anterior.data + timedelta(days=1) if anterior else date(exercicio.ano, 1, 1)
            return de, ate

    ate = timezone.localdate()
    mais_recente = Reuniao.objects.filter(exercicio=exercicio).order_by("-data").first()
    if mais_recente is not None:
        de = mais_recente.data + timedelta(days=1)
    else:
        de = ate - timedelta(days=30)
    return de, ate


# ---------------------------------------------------------------------------
# Blocos independentes de `prazo_prometido` (Task 2)
#
# cada função devolve dict[int, dict]: chave processo.pk, valor
# {"processo": Processo, "frases": list[str], "automatico": bool}. Este é
# o formato de "candidato bruto" que montar_relatorio() consome para a
# deduplicação; BlocoRelatorio só existe depois dessa deduplicação
# ---------------------------------------------------------------------------


def _candidato(processo, frase, *, automatico=False):
    return {"processo": processo, "frases": [frase], "automatico": automatico}


def _bloco_inclusoes(exercicio, de: date, ate: date):
    """Bloco Inclusões — data_inclusao_pca dentro do período."""
    qs = Processo.objects.filter(
        exercicio=exercicio, data_inclusao_pca__range=(de, ate)
    ).select_related("unidade_organizacional", "exercicio")
    resultado = {}
    for processo in qs:
        frase = (
            f"Item {processo.item_pca} – {_truncar_descricao(processo.descricao_objeto)} "
            f"({processo.unidade_organizacional.nome}): incluído no PCA em "
            f"{data_br(processo.data_inclusao_pca)}, valor estimado "
            f"{moeda(processo.valor_estimado)}."
        )
        resultado[processo.pk] = _candidato(processo, frase)
    return resultado


def _bloco_exclusoes(exercicio, de: date, ate: date):
    """Bloco Exclusões — cancelado no período (history) ou descartado
    numa virada de exercício confirmada no período. Um processo nos dois
    casos entra só uma vez, pelo caso (a): cancelamento."""
    inicio, fim = _limites_do_dia(de, ate)
    resultado = {}

    desde_cancelado = (
        Processo.history.filter(exercicio=exercicio, estado=Estado.CANCELADO)
        .values("id")
        .annotate(desde=Min("history_date"))
    )
    mapa_desde = {
        linha["id"]: linha["desde"]
        for linha in desde_cancelado
        if inicio <= linha["desde"] <= fim
    }
    if mapa_desde:
        qs = Processo.objects.filter(
            pk__in=mapa_desde, exercicio=exercicio, estado=Estado.CANCELADO
        ).select_related("unidade_organizacional", "exercicio")
        for processo in qs:
            desde = mapa_desde[processo.pk]
            frase = (
                f"Item {processo.item_pca} – {_truncar_descricao(processo.descricao_objeto)} "
                f"({processo.unidade_organizacional.nome}): cancelado em "
                f"{data_br(_como_data_local(desde))}."
            )
            resultado[processo.pk] = _candidato(processo, frase)

    itens_descartados = RascunhoItemVirada.objects.filter(
        selecionado=False,
        rascunho__exercicio_origem=exercicio,
        rascunho__confirmado_em__date__range=(de, ate),
    ).select_related(
        "rascunho",
        "processo_origem",
        "processo_origem__unidade_organizacional",
        "processo_origem__exercicio",
    )
    for item in itens_descartados:
        processo = item.processo_origem
        if processo.pk in resultado:
            continue
        frase = (
            f"Item {processo.item_pca} – {_truncar_descricao(processo.descricao_objeto)} "
            f"({processo.unidade_organizacional.nome}): não migrado na virada para o "
            f"exercício {item.rascunho.ano_destino} (virada confirmada em "
            f"{data_br(_como_data_local(item.rascunho.confirmado_em))})."
        )
        resultado[processo.pk] = _candidato(processo, frase)
    return resultado


def _bloco_iniciados(exercicio, de: date, ate: date):
    """Bloco Iniciados — data_envio_gelic passou de vazio a preenchido no
    período (primeira transição histórica dentro do intervalo)."""
    inicio, fim = _limites_do_dia(de, ate)
    desde_envio = (
        Processo.history.filter(exercicio=exercicio, data_envio_gelic__isnull=False)
        .values("id")
        .annotate(desde=Min("history_date"))
    )
    mapa_desde = {
        linha["id"]: linha["desde"]
        for linha in desde_envio
        if inicio <= linha["desde"] <= fim
    }
    resultado = {}
    if not mapa_desde:
        return resultado
    qs = Processo.objects.filter(
        pk__in=mapa_desde, exercicio=exercicio, data_envio_gelic__isnull=False
    ).select_related("unidade_organizacional", "exercicio")
    for processo in qs:
        desde = mapa_desde[processo.pk]
        frase = (
            f"Item {processo.item_pca} – {_truncar_descricao(processo.descricao_objeto)} "
            f"({processo.unidade_organizacional.nome}): encaminhado à Gelic em "
            f"{data_br(_como_data_local(desde))}."
        )
        resultado[processo.pk] = _candidato(processo, frase)
    return resultado


def _situacao_antes_da_transicao(processo_pk, desde):
    """Valor de situacao no registro histórico imediatamente anterior ao
    que marca a transição para Concluído em desde."""
    registros = list(
        Processo.history.filter(id=processo_pk).order_by("history_date", "history_id")
    )
    for indice, registro in enumerate(registros):
        if registro.history_date == desde and registro.situacao == Situacao.CONCLUIDO:
            return registros[indice - 1].situacao if indice > 0 else None
    return None


def _bloco_concluidos(exercicio, de: date, ate: date):
    """Bloco Concluídos — situacao passou a Concluído no período (primeira
    transição histórica dentro do intervalo). Justificativa/automático vêm
    do Acompanhamento correlacionado pela mesma data, quando existe."""
    inicio, fim = _limites_do_dia(de, ate)
    desde_concluido = (
        Processo.history.filter(exercicio=exercicio, situacao=Situacao.CONCLUIDO)
        .values("id")
        .annotate(desde=Min("history_date"))
    )
    mapa_desde = {
        linha["id"]: linha["desde"]
        for linha in desde_concluido
        if inicio <= linha["desde"] <= fim
    }
    resultado = {}
    if not mapa_desde:
        return resultado
    qs = Processo.objects.filter(
        pk__in=mapa_desde, exercicio=exercicio, situacao=Situacao.CONCLUIDO
    ).select_related("unidade_organizacional", "exercicio")
    for processo in qs:
        desde = mapa_desde[processo.pk]
        situacao_anterior = _situacao_antes_da_transicao(processo.pk, desde)
        frase = frase_mudanca_campo(
            "situacao",
            situacao_anterior,
            Situacao.CONCLUIDO,
            desde,
            processo=processo,
            mapas_fk={},
        )
        automatico = False
        acompanhamento = (
            Acompanhamento.objects.filter(
                processo=processo, referencia_data=_como_data_local(desde)
            )
            .exclude(evento="")
            .first()
        )
        if acompanhamento is not None:
            frase = f"{frase} Justificativa: {acompanhamento.evento}."
            automatico = acompanhamento.tipo_evento == TipoEvento.AUTOMATICO
        resultado[processo.pk] = _candidato(processo, frase, automatico=automatico)
    return resultado


# ---------------------------------------------------------------------------
# apuração do compromisso de reunião e bloco Adiados
# ---------------------------------------------------------------------------


def _situacao_em(processo_id, quando):
    """Valor de situacao vigente num instante (via history), usado só
    pela condição (c) de apurar_situacao_compromisso."""
    registro = (
        Processo.history.filter(id=processo_id, history_date__date__lte=quando)
        .order_by("-history_date", "-history_id")
        .first()
    )
    return registro.situacao if registro is not None else None


def apurar_situacao_compromisso(acompanhamento, *, hoje=None):
    """Situação do compromisso (prazo_prometido + evento), derivada por
    regra a partir do history, sem nenhuma marcação persistida. Ordem de
    checagem fixa:
    1. sem reuniao associada -> "sem registro de cumprimento".
    2. existe promessa posterior do mesmo processo com prazo diferente ->
       "reprogramado".
    3. prazo ainda não chegou -> "em aberto".
    4. prazo já passou: "cumprido" se o processo concluiu, foi enviado à
       Gelic, ou melhorou de situação até o prazo; senão "vencido".
    """
    hoje = hoje or timezone.localdate()

    if acompanhamento.reuniao_id is None:
        return "sem_registro_cumprimento", "sem registro de cumprimento"

    posteriores = Acompanhamento.objects.filter(
        processo_id=acompanhamento.processo_id,
        prazo_prometido__isnull=False,
        reuniao__data__gt=acompanhamento.reuniao.data,
    ).order_by("reuniao__data")
    if posteriores.exclude(prazo_prometido=acompanhamento.prazo_prometido).exists():
        return "reprogramado", "reprogramado"

    if acompanhamento.prazo_prometido >= hoje:
        return "em_aberto", "em aberto"

    prazo = acompanhamento.prazo_prometido
    concluido_ate_prazo = Processo.history.filter(
        id=acompanhamento.processo_id,
        situacao=Situacao.CONCLUIDO,
        history_date__date__lte=prazo,
    ).exists()
    enviado_gelic_ate_prazo = Processo.history.filter(
        id=acompanhamento.processo_id,
        data_envio_gelic__isnull=False,
        history_date__date__lte=prazo,
    ).exists()
    situacao_na_referencia = _situacao_em(
        acompanhamento.processo_id, acompanhamento.referencia_data
    )
    situacao_no_prazo = _situacao_em(acompanhamento.processo_id, prazo)
    melhorou = PESO_SITUACAO.get(situacao_no_prazo, 0) > PESO_SITUACAO.get(
        situacao_na_referencia, 0
    )

    if concluido_ate_prazo or enviado_gelic_ate_prazo or melhorou:
        return "cumprido", "cumprido"
    return "vencido", "vencido"


# sentinela distinto de None: um valor de data genuinamente ausente é
# None; o sentinela marca "esta anotação não foi calculada para este
# objeto", não "foi calculada e é nula"
_SEM_ANOTACAO = object()


def _resolver_prazo_inicial(acompanhamento):
    """Resolve o mesmo "Prazo inicial" derivado por
    ProcessoQuerySet.para_listagem() sem uma consulta por linha quando o
    chamador já anotou em lote.

    Ordem de preferência: (1) acompanhamento.prazo_inicial_processo, a
    anotação em lote que _bloco_adiados aplica via Subquery
    correlacionada; (2) processo.prazo_inicial, quando o Processo já veio
    de para_listagem(); (3), só para uma chamada unitária com Processo
    cru, uma única consulta controlada à mesma anotação, nunca por linha."""
    anotado = getattr(acompanhamento, "prazo_inicial_processo", _SEM_ANOTACAO)
    if anotado is not _SEM_ANOTACAO:
        return anotado
    processo = acompanhamento.processo
    anotado = getattr(processo, "prazo_inicial", _SEM_ANOTACAO)
    if anotado is not _SEM_ANOTACAO:
        return anotado
    return (
        Processo.objects.para_listagem()
        .filter(pk=processo.pk)
        .values_list("prazo_inicial", flat=True)
        .first()
    )


def frase_compromisso(acompanhamento, *, hoje=None):
    """Frase institucional do compromisso, mesma função usada pelo bloco
    Adiados do relatório e pela timeline do detalhe do processo e pelo
    bloco "Compromisso vigente".

    O "prazo inicial" da frase é o mesmo derivado por
    ProcessoQuerySet.para_listagem()::prazo_inicial, resolvido por
    _resolver_prazo_inicial sem consulta por linha em lote."""
    codigo, rotulo = apurar_situacao_compromisso(acompanhamento, hoje=hoje)
    processo = acompanhamento.processo
    uo = processo.unidade_organizacional.nome
    prazo_inicial_valor = _resolver_prazo_inicial(acompanhamento)
    prazo_inicial = (
        data_br(prazo_inicial_valor)
        if prazo_inicial_valor
        else "sem prazo inicial registrado"
    )
    if acompanhamento.reuniao_id is not None:
        prefixo_evento = f"na reunião de {data_br(acompanhamento.reuniao.data)}"
    else:
        prefixo_evento = f"em {data_br(acompanhamento.referencia_data)}"
    verbo = (
        "solicitou adiamento para"
        if codigo == "reprogramado"
        else "comprometeu-se a entregar até"
    )
    justificativa = acompanhamento.evento or "sem justificativa registrada"
    if codigo == "sem_registro_cumprimento":
        clausula_final = "Situação: sem registro de cumprimento."
    else:
        clausula_final = f"Situação apurada pelo sistema: {rotulo}."
    return (
        f"prazo inicial {prazo_inicial}; {prefixo_evento} a {uo} {verbo} "
        f"{data_br(acompanhamento.prazo_prometido)}. Justificativa: {justificativa}. "
        f"{clausula_final}"
    )


def compromisso_vigente(processo, *, hoje=None):
    """Compromisso mais recente (por referencia_data, desempate -id) com
    prazo_prometido não nulo; None quando o processo nunca recebeu uma
    promessa. Consumido pelo bloco "Compromisso vigente" do detalhe do
    processo e aviso do modal."""
    acompanhamento = (
        Acompanhamento.objects.filter(processo=processo, prazo_prometido__isnull=False)
        .select_related("reuniao")
        .order_by("-referencia_data", "-id")
        .first()
    )
    if acompanhamento is None:
        return None
    # evita uma segunda consulta ao processo já em mãos do chamador
    acompanhamento.processo = processo
    hoje = hoje or timezone.localdate()
    codigo, rotulo = apurar_situacao_compromisso(acompanhamento, hoje=hoje)
    frase = frase_compromisso(acompanhamento, hoje=hoje)
    # "vence em N dias"/"vencido há N dias" do bloco "Compromisso vigente",
    # calculado uma única vez aqui: positivo = dias até o prazo, negativo =
    # dias desde que venceu, zero = vence hoje
    dias = (acompanhamento.prazo_prometido - hoje).days
    return {
        "acompanhamento": acompanhamento,
        "codigo": codigo,
        "rotulo": rotulo,
        "frase": frase,
        "dias": dias,
    }


def prazo_atual_ficha(processo, *, hoje=None):
    """Quadro "PRAZO ATUAL" da ficha: sempre presente, com fallback em
    prazo_efetivo, a mesma leitura que situacao_efetiva/atrasado usam.

    A contagem "vence em N dias"/"vence hoje"/"vencido há N dias" só
    aparece em No prazo/Atrasado; Concluído, Em tramitação e Cancelado
    mostram a data + a situação entre parênteses; sem prazo nenhum, "Não
    informado". Reaproveita compromisso_vigente quando existe compromisso
    registrado e só cai numa conta direta sobre prazo_efetivo quando não
    há compromisso algum. Cor do quadro e ausência do nome da UO são
    decisão só do template."""
    prazo = processo.prazo_efetivo
    if prazo is None:
        return {"valor": "Não informado", "complemento": ""}
    hoje = hoje or timezone.localdate()
    valor = data_br(prazo)
    if processo.estado == Estado.CANCELADO:
        return {"valor": valor, "complemento": "(cancelado)"}
    if processo.situacao_efetiva == Situacao.CONCLUIDO:
        return {"valor": valor, "complemento": "(concluído)"}
    if processo.situacao_efetiva == Situacao.EM_TRAMITACAO:
        return {"valor": valor, "complemento": "(em tramitação)"}
    vigente = compromisso_vigente(processo, hoje=hoje)
    dias = vigente["dias"] if vigente is not None else (prazo - hoje).days
    if dias > 0:
        complemento = f"(vence em {dias} dia{'s' if dias != 1 else ''})"
    elif dias == 0:
        complemento = "(vence hoje)"
    else:
        dias_abs = -dias
        complemento = f"(vencido há {dias_abs} dia{'s' if dias_abs != 1 else ''})"
    return {"valor": valor, "complemento": complemento}


def _bloco_adiados(exercicio, de: date, ate: date):
    """Bloco Adiados — Acompanhamento com prazo_prometido cuja
    reuniao.data (não referencia_data) cai no período: só promessas
    assumidas em reunião entram aqui. Um processo com mais de uma
    promessa no período entra uma vez, com todas as frases, mais recente
    primeiro.

    prazo_inicial_processo é anotado em lote (Subquery correlacionada)
    para que frase_compromisso/_resolver_prazo_inicial nunca precisem de
    uma consulta adicional por linha."""
    qs = (
        Acompanhamento.objects.filter(
            processo__exercicio=exercicio,
            prazo_prometido__isnull=False,
            reuniao__data__range=(de, ate),
        )
        .select_related(
            "processo",
            "processo__unidade_organizacional",
            "processo__exercicio",
            "reuniao",
        )
        .annotate(
            prazo_inicial_processo=Subquery(
                Processo.objects.para_listagem()
                .filter(pk=OuterRef("processo_id"))
                .values("prazo_inicial")[:1]
            )
        )
        .order_by("processo_id", "-referencia_data", "-id")
    )
    resultado = {}
    for acompanhamento in qs:
        processo = acompanhamento.processo
        frase = frase_compromisso(acompanhamento)
        if processo.pk in resultado:
            resultado[processo.pk]["frases"].append(frase)
        else:
            # compromissos são sempre um ato humano de reunião, nunca automático
            resultado[processo.pk] = _candidato(processo, frase, automatico=False)
    return resultado


# ---------------------------------------------------------------------------
# bloco Alterações e orquestração final
# ---------------------------------------------------------------------------


def _formatar_valor_trilha(campo, valor, mapas_fk):
    """Valor compacto de uma etapa da trilha: mês previsto usa ABREV_MES;
    os demais campos reaproveitam formatar_valor_campo."""
    if campo == "mes_previsto":
        return ABREV_MES.get(valor, "—")
    return formatar_valor_campo(campo, valor, mapas_fk=mapas_fk)


def _formatar_data_trilha(data):
    """Data compacta dd/mm (sem ano) de uma etapa da trilha, distinta da
    data líquida da frase principal, que é dd/mm/aaaa."""
    return _como_data_local(data).strftime("%d/%m")


def _bloco_alteracoes(exercicio, de: date, ate: date, *, mapas_fk):
    """Bloco Alterações — demais campos curados. Uma frase por campo
    alterado (líquido + trilha entre parênteses); um processo com mais de
    um campo alterado contribui várias frases na mesma entrada de
    candidato.

    "Conclusão tem bloco próprio": transições de situacao cujo valor
    líquido é Concluído não entram aqui — _bloco_concluidos já é o dono
    desse evento."""
    qs = Processo.objects.filter(exercicio=exercicio).select_related(
        "unidade_organizacional", "exercicio"
    )
    # uma consulta de history para o exercício inteiro, fora do loop, em vez de uma por processo
    _, fim = _limites_do_dia(de, ate)
    historico_por_processo = _historico_ate_por_processo(exercicio, fim)
    resultado = {}
    for processo in qs:
        mudancas_por_campo = mudancas_no_periodo(
            processo,
            de=de,
            ate=ate,
            campos=CAMPOS_ALTERACOES,
            registros=historico_por_processo.get(processo.pk, []),
        )
        frases = []
        for campo in CAMPOS_ALTERACOES:
            mudancas = mudancas_por_campo.get(campo) or []
            if not mudancas:
                continue
            de_liq, para_liq, trilha = consolidar_mudancas(mudancas)
            if campo == "situacao" and para_liq == Situacao.CONCLUIDO:
                continue
            data_liquida = max(mudanca.data for mudanca in mudancas)
            frase = frase_mudanca_campo(
                campo, de_liq, para_liq, data_liquida, processo=processo, mapas_fk=mapas_fk
            )
            if trilha:
                etapas = "; ".join(
                    f"{_formatar_valor_trilha(campo, de_t, mapas_fk)} → "
                    f"{_formatar_valor_trilha(campo, para_t, mapas_fk)} em "
                    f"{_formatar_data_trilha(data_t)}"
                    for de_t, para_t, data_t in trilha
                )
                frase = f"{frase} ({etapas})"
            frases.append(frase)
        if frases:
            resultado[processo.pk] = {
                "processo": processo,
                "frases": frases,
                "automatico": False,
            }
    return resultado


def montar_relatorio(*, exercicio, de: date, ate: date, usuario):
    """Orquestra os 6 blocos e aplica a deduplicação "um item, um bloco":
    cada processo aparece uma única vez, no bloco mais forte por
    ORDEM_PRECEDENCIA_BLOCOS; as demais frases desse processo viram
    frases_extra da mesma entrada. Sempre devolve os 6 BlocoRelatorio,
    mesmo vazios."""
    mapas_fk = {
        "unidade_organizacional": dict(Unidade.objects.values_list("id", "nome")),
        "modalidade": dict(Modalidade.objects.values_list("id", "nome")),
        "instrumento_contratual": dict(
            InstrumentoContratual.objects.values_list("id", "nome")
        ),
    }
    candidatos = {
        "inclusoes": _bloco_inclusoes(exercicio, de, ate),
        "exclusoes": _bloco_exclusoes(exercicio, de, ate),
        "iniciados": _bloco_iniciados(exercicio, de, ate),
        "concluidos": _bloco_concluidos(exercicio, de, ate),
        "adiados": _bloco_adiados(exercicio, de, ate),
        "alteracoes": _bloco_alteracoes(exercicio, de, ate, mapas_fk=mapas_fk),
    }

    # "dono" de cada processo: a primeira chave, na ordem de precedência,
    # cujo dict de candidatos contém o processo_id
    donos = {}
    for chave in ORDEM_PRECEDENCIA_BLOCOS:
        for processo_id in candidatos[chave]:
            if processo_id not in donos:
                donos[processo_id] = chave

    itens_por_bloco = {chave: [] for chave in ORDEM_EXIBICAO_BLOCOS}
    for processo_id, chave_dona in donos.items():
        candidato_dono = candidatos[chave_dona][processo_id]
        frases_dono = list(candidato_dono["frases"])
        frase_principal = frases_dono[0]
        frases_extra = frases_dono[1:]
        for outra_chave in ORDEM_EXIBICAO_BLOCOS:
            if outra_chave == chave_dona:
                continue
            candidato_outro = candidatos[outra_chave].get(processo_id)
            if candidato_outro is not None:
                frases_extra.extend(candidato_outro["frases"])
        item = ItemRelatorio(
            processo=candidato_dono["processo"],
            frase_principal=frase_principal,
            frases_extra=frases_extra,
            automatico=candidato_dono["automatico"],
        )
        itens_por_bloco[chave_dona].append(item)

    blocos = []
    for chave in ORDEM_EXIBICAO_BLOCOS:
        itens = sorted(itens_por_bloco[chave], key=lambda item: item.processo.item_pca)
        contagem = len(itens)
        soma_valor = None
        if chave in ("inclusoes", "exclusoes", "concluidos"):
            ids_finais = [item.processo.pk for item in itens]
            agregado = Processo.objects.filter(pk__in=ids_finais).aggregate(
                soma=Sum("valor_estimado")
            )
            soma_valor = agregado["soma"] or Decimal("0")
        titulo = f"{TITULOS_BASE_BLOCOS[chave]} ({contagem})"
        blocos.append(
            BlocoRelatorio(
                chave=chave,
                titulo=titulo,
                contagem=contagem,
                soma_valor=soma_valor,
                itens=itens,
            )
        )

    return RelatorioMovimentacao(
        exercicio=exercicio,
        de=de,
        ate=ate,
        blocos=blocos,
        gerado_em=timezone.now(),
        gerado_por=usuario.get_full_name() or usuario.email,
    )
