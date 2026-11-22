"""Motor Python do "git log" do PCA — Fase 27.

Nenhuma view reimplementa esta lógica: (desempenho) e convenções do projeto
("propriedades derivadas de histórico não podem virar consulta por linha")
exigem uma fonte única, agregada no ORM, testável isoladamente.

entregou os contratos de dados (dataclasses), o motor de diff de
histórico, o dicionário de frases por campo e os 4 blocos que não dependem
de `Acompanhamento.prazo_prometido` (Inclusões, Exclusões, Iniciados,
Concluídos) — todos devolvendo "candidato bruto" (`dict[int, dict]`). Plano
27-03 (este trecho) fecha o módulo: a apuração da situação do compromisso de
reunião (sem nenhuma marcação persistida), o bloco Adiados, o
bloco Alterações, e `montar_relatorio()` — a orquestração final que aplica a
deduplicação "um item, um bloco" e devolve o `RelatorioMovimentacao`
completo, pronto para a view do plano.

Nenhuma tabela nova: tudo é derivado de `Processo`,
`Acompanhamento`, `Reuniao`, `RascunhoVirada`/`RascunhoItemVirada` e do
`simple_history` já existentes.
"""

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
from core.db import quantizar_soma
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
# Ordens e vocabulário fixo dos blocos
# ---------------------------------------------------------------------------

# Ordem de LEITURA do relatório.
ORDEM_EXIBICAO_BLOCOS = (
    "inclusoes",
    "exclusoes",
    "iniciados",
    "concluidos",
    "adiados",
    "alteracoes",
)

# Ordem de DESEMPATE quando um processo se qualifica para mais de
# um bloco — nunca a mesma tupla usada para exibição: Concluídos pesa mais
# que Iniciados na precedência, mesmo aparecendo depois na exibição.
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

# Trilha compacta ("ago → set em 05/08..."). O valor líquido de
# mês previsto (campo `mes_previsto`) usa `NOMES_MES` por extenso — não isto.
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

# Campos curados do bloco Alterações. Fora: descrição,
# justificativa, categoria, tipo, grau, classificação, situação SEI, datas
# do funil que não são envio à Gelic.
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

# condição (c) — "a situação melhorou" compara o PESO da situação,
# não o valor cru: NO_PRAZO/ATRASADO empatam (nenhum dos dois é progresso
# sobre o outro), EM_TRAMITACAO é o próximo estágio, CONCLUIDO o final.
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

# Dicionário de frases por campo (rótulo institucional +
# particípio com concordância de gênero), reutilizado por todos os blocos
# que descrevem "de → para". Vive em Python, não no template.
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
    """Reduz um datetime tz-aware (`history_date`) à data em
    America/Sao_Paulo — as frases mostram só `dd/mm/aaaa`, nunca hora."""
    if isinstance(valor, datetime):
        return timezone.localtime(valor).date()
    return valor


def formatar_valor_campo(campo, valor, *, mapas_fk):
    """Rótulo humano pt-BR de um valor de campo, para uso fora de template
    (mesmo padrão de `views_processo._valor_exibicao_campo`)."""
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
    """Frase completa "Item N – descrição (UO): rótulo particípio de X para Y
    em dd/mm/aaaa." — o modelo aprovado pelo usuário."""
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
# Motor de diff de histórico
# ---------------------------------------------------------------------------


def _limites_do_dia(de: date, ate: date):
    """Limites inclusivos [de 00:00, até 23:59:59] em America/Sao_Paulo,
    tz-aware — `USE_TZ=True`/`TIME_ZONE=America/Sao_Paulo` já
    resolvem o fuso, sem aritmética manual de UTC."""
    inicio = timezone.make_aware(datetime.combine(de, time.min))
    fim = timezone.make_aware(datetime.combine(ate, time.max))
    return inicio, fim


def _historico_ate_por_processo(exercicio, fim):
    """Devolve `dict[int, list]` — para cada `id` de processo do
    `exercicio`, a lista de seus registros de history com
    `history_date <= fim`, ordenada por `(history_date, history_id)` (mesma
    ordem que `mudancas_no_periodo` já exigia ao consultar processo a
    processo). UMA query SQL para o exercício inteiro, não uma por
    processo — fecha o GAP 1: a versão
    anterior fazia `type(processo).history.filter(id=processo.pk)` dentro de
    um `for processo in qs`, medido em produção como 154 processos → 155
    queries.

    Só o limite SUPERIOR (`fim`) é seguro para filtrar no SQL. `diff_against`
    precisa do registro imediatamente ANTERIOR ao início do período para
    produzir o primeiro "de → para" dentro da janela, e essa linha-base pode
    estar arbitrariamente longe no passado — não há `history_date__gte`
    seguro sem perder essa base, a mesma limitação que já existia na versão
    por-processo (que também trazia o history inteiro), só que agora
    resolvida com UMA consulta em vez de N.
    """
    registros = (
        Processo.history.filter(exercicio=exercicio, history_date__lte=fim)
        .order_by("id", "history_date", "history_id")
    )
    mapa = {}
    for registro in registros:
        mapa.setdefault(registro.id, []).append(registro)
    return mapa


def mudancas_no_periodo(processo, *, de: date, ate: date, campos: tuple, registros=None):
    """Devolve `dict[str, list[MudancaCampo]]` — para cada `campo` em
    `campos`, as mudanças desse campo cujo `history_date` cai dentro de
    [de, ate] (inclusive, America/Sao_Paulo).

    Monta pares consecutivos (anterior, atual) a partir do history do
    processo e usa `diff_against` do django-simple-history. Ignora o
    primeiro registro histórico (sem anterior para comparar).

    `registros`, quando informado (lista pré-carregada, tipicamente de
    `_historico_ate_por_processo`), é usado diretamente — SEM nenhuma query
    própria (GAP 1). Quando omitido (`None`), mantém o
    comportamento original: consulta o history deste processo isoladamente
    — o caminho que `TestMudancasNoPeriodo` continua exercendo sem
    alteração.
    """
    inicio, fim = _limites_do_dia(de, ate)
    resultado = {campo: [] for campo in campos}
    if registros is None:
        # `pk=` no manager histórico filtra pelo `history_id`
        # (chave própria de cada snapshot), não pelo `id` do objeto
        # original: duas chaves primárias homônimas por coincidência
        # (`processo.pk` também é um inteiro pequeno em banco de teste)
        # faziam a consulta devolver quase sempre 0 ou 1 linha. `id=` é o
        # campo que espelha a chave do objeto rastreado (confirmado pelo
        # padrão já em produção em `test_admin_auditoria.py`:
        # `Processo.history.model.objects.filter(id=processo.pk)`).
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
    """Devolve `(valor_de_liquido, valor_para_liquido, trilha_ou_none)`.

    `valor_de_liquido` é o `.de` do primeiro item em ordem cronológica;
    `valor_para_liquido` é o `.para` do último. Quando há mais de uma
    mudança, `trilha_ou_none` é uma lista crua (não formatada) de tuplas
    `(de, para, data)` em ordem cronológica — formatar a trilha exige saber
    o `campo` (para chamar `formatar_valor_campo`), e só o chamador (Plano
    27-03, que orquestra por campo) tem essa informação em mãos. Esta
    função fica agnóstica de campo de propósito.
    """
    ordenadas = sorted(mudancas, key=lambda m: m.data)
    valor_de_liquido = ordenadas[0].de
    valor_para_liquido = ordenadas[-1].para
    trilha_ou_none = None
    if len(ordenadas) > 1:
        trilha_ou_none = [(m.de, m.para, m.data) for m in ordenadas]
    return valor_de_liquido, valor_para_liquido, trilha_ou_none


# ---------------------------------------------------------------------------
# Resolução de período
# ---------------------------------------------------------------------------


# QA 30/09/2026 (fuzz M5/B4, dominio/fluxos #8, navegador A1) — faixa
# fechada de datas aceitas e teto de dígitos para `reuniao`, ver
# `_reuniao_id_valido`/`_periodo_padrao` abaixo.
_ANO_MINIMO_PERIODO = 1900
_ANO_MAXIMO_PERIODO = 2100


def _reuniao_id_valido(valor):
    """`int(get.get("reuniao"))` seguro — `None` para vazio/ausente, para
    dígito Unicode (`"²".isdigit()` é `True`, mas `int("²")` lança
    `ValueError`; `isdecimal()` é a checagem correta) e para strings
    gigantes (teto de 18 dígitos, bem acima de qualquer PK real, evita o
    `ValueError`/`OverflowError` de conversão do Python para inteiros
    absurdamente grandes)."""
    if not valor:
        return None
    texto = str(valor)
    if not texto.isdecimal() or len(texto) > 18:
        return None
    return int(texto)


def _periodo_padrao(exercicio):
    """Período padrão (sem datas livres nem reunião válida no GET):
    `ate = hoje`; sem nenhuma reunião cadastrada, últimos 30 dias
    (comportamento original). Com reunião: QA 30/09 fluxos #8/navegador A1
    — no dia da própria reunião (ou reunião agendada no futuro), a mais
    recente não pode ser usada como baliza de `de` (inverteria `de > ate`,
    escondendo a movimentação do próprio dia) — usa-se a reunião ANTERIOR
    a ela, igual ao cálculo já existente para reunião selecionada
    manualmente."""
    ate = timezone.localdate()
    mais_recente = Reuniao.objects.filter(exercicio=exercicio).order_by("-data").first()
    if mais_recente is None:
        return ate - timedelta(days=30), ate
    if mais_recente.data >= ate:
        anterior = (
            Reuniao.objects.filter(exercicio=exercicio, data__lt=mais_recente.data)
            .order_by("-data")
            .first()
        )
        de = anterior.data + timedelta(days=1) if anterior else date(exercicio.ano, 1, 1)
        return de, ate
    return mais_recente.data + timedelta(days=1), ate


def resolver_periodo_relatorio(get, exercicio):
    """Devolve `(date, date, str | None)` a partir do `GET` da tela — nunca
    lança exceção para entrada malformada, cai sempre no default. O 3º
    valor é um aviso para `messages.warning` (QA 30/09 fluxos #8/navegador
    A1/M1, fuzz M5/B4), `None` quando não precisou corrigir nada.

    Precedência: datas livres (`de`/`ate`) > reunião selecionada > default
    (`_periodo_padrao`).
    """
    de_str = get.get("de")
    ate_str = get.get("ate")
    if de_str and ate_str:
        try:
            de_livre = date.fromisoformat(de_str)
            ate_livre = date.fromisoformat(ate_str)
        except (TypeError, ValueError):
            de_livre = ate_livre = None
        if de_livre is not None and ate_livre is not None:
            anos_fora_da_faixa = (
                de_livre.year < _ANO_MINIMO_PERIODO
                or de_livre.year > _ANO_MAXIMO_PERIODO
                or ate_livre.year < _ANO_MINIMO_PERIODO
                or ate_livre.year > _ANO_MAXIMO_PERIODO
            )
            if anos_fora_da_faixa:
                de, ate = _periodo_padrao(exercicio)
                return (
                    de,
                    ate,
                    "Datas fora do intervalo permitido (1900–2100) — período "
                    "padrão aplicado.",
                )
            if de_livre > ate_livre:
                de, ate = _periodo_padrao(exercicio)
                return (
                    de,
                    ate,
                    'Data "De" posterior a "Até" — período padrão aplicado.',
                )
            return de_livre, ate_livre, None

    reuniao_id = _reuniao_id_valido(get.get("reuniao"))
    if reuniao_id is not None:
        reuniao = Reuniao.objects.filter(pk=reuniao_id, exercicio=exercicio).first()
        if reuniao is not None:
            ate = reuniao.data
            anterior = (
                Reuniao.objects.filter(exercicio=exercicio, data__lt=reuniao.data)
                .order_by("-data")
                .first()
            )
            de = anterior.data + timedelta(days=1) if anterior else date(exercicio.ano, 1, 1)
            return de, ate, None

    de, ate = _periodo_padrao(exercicio)
    return de, ate, None


# ---------------------------------------------------------------------------
# Blocos independentes de `prazo_prometido`
#
# Cada função devolve `dict[int, dict]` — chave `processo.pk`, valor
# `{"processo": Processo, "frases": list[str], "automatico": bool}`. Este é
# o formato de "candidato bruto" que o plano consome em
# `montar_relatorio()` para a deduplicação; `BlocoRelatorio` só
# existe depois dessa deduplicação, fora do escopo deste plano.
# ---------------------------------------------------------------------------


def _candidato(processo, frase, *, automatico=False):
    return {"processo": processo, "frases": [frase], "automatico": automatico}


def _bloco_inclusoes(exercicio, de: date, ate: date):
    """bloco 1 — `data_inclusao_pca` dentro do período."""
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
    """bloco 2 — cancelado no período (history) OU descartado numa
    virada de exercício confirmada no período. Um processo nos dois casos
    entra só uma vez, pelo caso (a) — cancelamento."""
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
    """bloco 3 — `data_envio_gelic` passou de vazio a preenchido no
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


def _situacao_antes_da_transicao(processo_pk, desde, *, registros=None):
    """Valor de `situacao` no registro histórico imediatamente anterior ao
    que marca a transição para Concluído em `desde`.

    `registros`, quando informado (lista pré-carregada de
    `_historico_ate_por_processo`, já ordenada por `(history_date,
    history_id)`), é usado diretamente — SEM nenhuma query própria (dominio
    ACHADOS #1, QA 30/09). Quando omitido (`None`), mantém o comportamento
    original: consulta o history deste processo isoladamente — o caminho
    que os chamadores sem contexto em lote continuam exercendo."""
    if registros is None:
        registros = list(
            Processo.history.filter(id=processo_pk).order_by("history_date", "history_id")
        )
    for indice, registro in enumerate(registros):
        if registro.history_date == desde and registro.situacao == Situacao.CONCLUIDO:
            return registros[indice - 1].situacao if indice > 0 else None
    return None


def _bloco_concluidos(exercicio, de: date, ate: date, *, historico_por_processo=None):
    """bloco 4 — `situacao` passou a Concluído no período (primeira
    transição histórica dentro do intervalo). Justificativa/automático vêm
    do `Acompanhamento` correlacionado pela mesma data, quando existe.

    `historico_por_processo`, quando informado (dict de
    `_historico_ate_por_processo`), evita uma consulta de history por
    processo em `_situacao_antes_da_transicao` (dominio ACHADOS #1, QA
    30/09) — mantém o comportamento por-processo quando omitido (`None`),
    caminho ainda exercido por quem chama esta função direto (testes de
    `_bloco_concluidos`)."""
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
        registros = (
            historico_por_processo.get(processo.pk, [])
            if historico_por_processo is not None
            else None
        )
        situacao_anterior = _situacao_antes_da_transicao(
            processo.pk, desde, registros=registros
        )
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
# Apuração do compromisso de reunião e bloco
# Adiados
# ---------------------------------------------------------------------------


def _situacao_em(processo_id, quando):
    """Valor de `situacao` vigente num instante (via history) — usado só
    pela condição (c) de `apurar_situacao_compromisso` ("a situação
    melhorou em relação ao valor vigente na referência")."""
    registro = (
        Processo.history.filter(id=processo_id, history_date__date__lte=quando)
        .order_by("-history_date", "-history_id")
        .first()
    )
    return registro.situacao if registro is not None else None


def _situacao_em_lote(registros, quando):
    """Mesma leitura de `_situacao_em`, mas sobre uma lista de history JÁ
    carregada e ordenada por `(history_date, history_id)` (dominio ACHADOS
    #1, QA 30/09) — percorre em ordem, guarda o último `registro.situacao`
    cujo `registro.history_date.date() <= quando`; devolve `None` se
    nenhum registro satisfizer a condição."""
    situacao = None
    for registro in registros:
        if registro.history_date.date() <= quando:
            situacao = registro.situacao
    return situacao


def _contexto_compromissos_em_lote(exercicio, *, historico_por_processo):
    """Pré-carrega, em UMA consulta, tudo que `apurar_situacao_compromisso`
    precisaria consultar POR compromisso (dominio ACHADOS #1, QA 30/09): as
    promessas posteriores de cada processo (`processo_id -> [(data_reuniao,
    prazo), ...]`), reaproveitando o history já carregado pelo chamador
    (`historico_por_processo`, de `_historico_ate_por_processo`) sem
    nenhuma consulta própria para a parte de history."""
    linhas = (
        Acompanhamento.objects.filter(
            processo__exercicio=exercicio,
            prazo_prometido__isnull=False,
            reuniao__isnull=False,
        )
        .order_by("processo_id", "reuniao__data")
        .values_list("processo_id", "reuniao__data", "prazo_prometido")
    )
    posteriores = {}
    for processo_id, data_reuniao, prazo in linhas:
        posteriores.setdefault(processo_id, []).append((data_reuniao, prazo))
    return {"posteriores": posteriores, "historico": historico_por_processo}


def apurar_situacao_compromisso(acompanhamento, *, hoje=None, contexto=None):
    """Situação do compromisso (`prazo_prometido` + `evento`),
    derivada por regra a partir do history, sem nenhuma marcação
    persistida. Ordem de checagem fixa (a ordem importa):
    1. sem `reuniao` associada → "sem registro de cumprimento" (promessas
       antigas, sem backfill).
    2. existe promessa POSTERIOR do mesmo processo com prazo DIFERENTE →
       "reprogramado" (o novo registro é a reprogramação).
    3. prazo ainda não chegou → "em aberto".
    4. prazo já passou: "cumprido" se o processo concluiu, foi enviado à
       Gelic, ou melhorou de situação até o prazo (inclusive); senão
       "vencido".

    `contexto`, quando informado (`_contexto_compromissos_em_lote`),
    resolve as condições 2 e 4 em Python sobre dados já carregados — ZERO
    consultas por compromisso (dominio ACHADOS #1, QA 30/09). Quando
    omitido (`None`), mantém EXATAMENTE as 4 consultas originais — o
    caminho que os chamadores sem contexto em lote continuam exercendo.
    """
    hoje = hoje or timezone.localdate()

    if acompanhamento.reuniao_id is None:
        return "sem_registro_cumprimento", "sem registro de cumprimento"

    if contexto is None:
        posteriores = Acompanhamento.objects.filter(
            processo_id=acompanhamento.processo_id,
            prazo_prometido__isnull=False,
            reuniao__data__gt=acompanhamento.reuniao.data,
        ).order_by("reuniao__data")
        existe_reprogramacao = posteriores.exclude(
            prazo_prometido=acompanhamento.prazo_prometido
        ).exists()
    else:
        existe_reprogramacao = any(
            data_reuniao > acompanhamento.reuniao.data
            and prazo != acompanhamento.prazo_prometido
            for data_reuniao, prazo in contexto["posteriores"].get(
                acompanhamento.processo_id, []
            )
        )
    if existe_reprogramacao:
        return "reprogramado", "reprogramado"

    if acompanhamento.prazo_prometido >= hoje:
        return "em_aberto", "em aberto"

    prazo = acompanhamento.prazo_prometido
    if contexto is None:
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
    else:
        registros = contexto["historico"].get(acompanhamento.processo_id, [])
        concluido_ate_prazo = any(
            registro.situacao == Situacao.CONCLUIDO
            and registro.history_date.date() <= prazo
            for registro in registros
        )
        enviado_gelic_ate_prazo = any(
            registro.data_envio_gelic is not None
            and registro.history_date.date() <= prazo
            for registro in registros
        )
        situacao_na_referencia = _situacao_em_lote(
            registros, acompanhamento.referencia_data
        )
        situacao_no_prazo = _situacao_em_lote(registros, prazo)
    melhorou = PESO_SITUACAO.get(situacao_no_prazo, 0) > PESO_SITUACAO.get(
        situacao_na_referencia, 0
    )

    if concluido_ate_prazo or enviado_gelic_ate_prazo or melhorou:
        return "cumprido", "cumprido"
    return "vencido", "vencido"


# Sentinela distinto de `None`: um valor de data genuinamente ausente É
# `None` (o campo `prazo_inicial` aceita nulo); o sentinela marca "esta
# anotação não foi calculada para este objeto", não "foi calculada e é
# nula" — só assim `_resolver_prazo_inicial` sabe quando cair no próximo
# nível em vez de aceitar um `None` legítimo como resposta final.
_SEM_ANOTACAO = object()


def _resolver_prazo_inicial(acompanhamento):
    """Resolve o mesmo "Prazo inicial" derivado por
    `ProcessoQuerySet.para_listagem()` (COALESCE(prazo_entrega, primeira
    promessa do histórico)) sem uma consulta por linha quando o chamador já
    anotou em lote.

    Ordem de preferência: (1) `acompanhamento.prazo_inicial_processo`, a
    anotação em lote que `_bloco_adiados` aplica via `Subquery`
    correlacionada; (2) `processo.prazo_inicial`, quando o `Processo` já
    veio de `para_listagem()` (caso do detalhe do processo, `views.
    _carregar_processo_modal`); (3), só para uma chamada UNITÁRIA com
    `Processo` cru (nenhuma das anteriores), uma única consulta controlada
    à mesma anotação — nunca por linha."""
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


def frase_compromisso(acompanhamento, *, hoje=None, contexto=None):
    """Frase institucional do compromisso — MESMA função usada
    pelo bloco Adiados do relatório e, no plano, pela timeline do
    detalhe do processo e pelo bloco "Compromisso vigente" ("mesma
    função Python gera as duas").

    O "prazo inicial" da frase é o MESMO derivado por
    `ProcessoQuerySet.para_listagem()::prazo_inicial` (COALESCE
    entre `prazo_entrega` e a primeira promessa do histórico), resolvido
    por `_resolver_prazo_inicial` sem consulta por linha em lote.

    `contexto`, quando informado, é repassado para
    `apurar_situacao_compromisso` (dominio ACHADOS #1, QA 30/09)."""
    codigo, rotulo = apurar_situacao_compromisso(acompanhamento, hoje=hoje, contexto=contexto)
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
    """Compromisso MAIS RECENTE (por `referencia_data`, desempate `-id`)
    com `prazo_prometido` não nulo — `None` quando o processo nunca recebeu
    uma promessa. Consumido pelo plano (bloco "Compromisso vigente" do
    detalhe do processo e aviso do modal)."""
    acompanhamento = (
        Acompanhamento.objects.filter(processo=processo, prazo_prometido__isnull=False)
        .select_related("reuniao")
        .order_by("-referencia_data", "-id")
        .first()
    )
    if acompanhamento is None:
        return None
    # Evita uma segunda consulta ao `processo` já em mãos do chamador — o
    # descritor de FK aceita a atribuição direta e passa a servir do cache.
    acompanhamento.processo = processo
    hoje = hoje or timezone.localdate()
    codigo, rotulo = apurar_situacao_compromisso(acompanhamento, hoje=hoje)
    frase = frase_compromisso(acompanhamento, hoje=hoje)
    # "vence em N dias"/"vencido há N dias" do bloco
    # "Compromisso vigente" no detalhe do processo, calculado uma única vez
    # aqui (nunca duplicado entre view/template): positivo = dias até o
    # prazo, negativo = dias desde que venceu, zero = vence hoje.
    dias = (acompanhamento.prazo_prometido - hoje).days
    return {
        "acompanhamento": acompanhamento,
        "codigo": codigo,
        "rotulo": rotulo,
        "frase": frase,
        "dias": dias,
    }


def prazo_atual_ficha(processo, *, hoje=None):
    """Quadro "PRAZO ATUAL" da ficha
    PNCP: SEMPRE presente (nunca condicionado a existir compromisso),
    com fallback em `prazo_efetivo` — a MESMA leitura que
    `situacao_efetiva`/`atrasado` usam (`ProcessoQuerySet.para_listagem()`).

    A contagem "vence em N dias"/"vence hoje"/"vencido há N dias" só
    aparece em No prazo/Atrasado; Concluído, Em tramitação e o Estado
    Cancelado mostram a data + a situação entre parênteses; sem prazo
    nenhum, "Não informado" (a data histórica nunca é escondida).
    Reaproveita `compromisso_vigente` quando existe compromisso registrado
    (o mesmo `dias` já calculado ali, nunca recalculado) e só cai numa
    conta direta sobre `prazo_efetivo` quando não há compromisso algum
    (prazo vindo só de Planejamento) — "calcular sobre
    `prazo_efetivo`, não só quando `compromisso_vigente` existe". Cor do
    quadro e ausência do nome da UO são decisão só do template."""
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


def _bloco_adiados(exercicio, de: date, ate: date, *, contexto_compromissos=None):
    """bloco 5 — `Acompanhamento` com `prazo_prometido` cuja
    `reuniao.data` (não `referencia_data`) cai no período: só promessas
    ASSUMIDAS EM REUNIÃO entram aqui — promessas sem reunião associada não
    são "compromisso assumido em reunião" ("sem backfill"). Um
    processo com mais de uma promessa no período entra uma vez, com todas
    as frases, mais recente primeiro.

    `prazo_inicial_processo` é anotado em LOTE (`Subquery`
    correlacionada à mesma identidade de `para_listagem()::prazo_inicial`)
    para que `frase_compromisso`/`_resolver_prazo_inicial` nunca precisem
    de uma consulta adicional por linha, mesmo com N processos distintos
    no período (convenções do projeto — "propriedades derivadas de histórico não podem
    virar consulta por linha"). `contexto_compromissos`, quando informado
    (`_contexto_compromissos_em_lote`), repassa o mesmo tratamento para
    `apurar_situacao_compromisso` (dominio ACHADOS #1, QA 30/09)."""
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
        frase = frase_compromisso(acompanhamento, contexto=contexto_compromissos)
        if processo.pk in resultado:
            resultado[processo.pk]["frases"].append(frase)
        else:
            # Compromissos são sempre um ato humano de reunião — nunca
            # automático.
            resultado[processo.pk] = _candidato(processo, frase, automatico=False)
    return resultado


# ---------------------------------------------------------------------------
# Bloco Alterações e orquestração final
# ---------------------------------------------------------------------------


def _formatar_valor_trilha(campo, valor, mapas_fk):
    """Valor compacto de uma etapa da trilha: mês previsto usa
    `ABREV_MES` ("ago"); os demais campos reaproveitam
    `formatar_valor_campo` (a mesma função da frase líquida)."""
    if campo == "mes_previsto":
        return ABREV_MES.get(valor, "—")
    return formatar_valor_campo(campo, valor, mapas_fk=mapas_fk)


def _formatar_data_trilha(data):
    """Data compacta `dd/mm` (sem ano) de uma etapa da trilha — distinta da
    data líquida da frase principal, que é `dd/mm/aaaa` (`data_br`)."""
    return _como_data_local(data).strftime("%d/%m")


def _bloco_alteracoes(exercicio, de: date, ate: date, *, mapas_fk):
    """bloco 6 — demais campos curados. Uma frase por
    campo alterado (líquido + trilha entre parênteses); um
    processo com mais de um campo alterado contribui várias frases na MESMA
    entrada de candidato (`processo_id`).

    "conclusão tem bloco próprio": transições de `situacao` cujo
    valor líquido é Concluído não entram aqui (`_bloco_concluidos` já é o
    dono desse evento); contá-las de novo criaria uma frase redundante
    quando o dedup (`montar_relatorio`) junta os candidatos do
    mesmo processo."""
    qs = Processo.objects.filter(exercicio=exercicio).select_related(
        "unidade_organizacional", "exercicio"
    )
    # GAP 1 — UMA consulta de history
    # para o exercício inteiro, fora do loop, em vez de uma por processo.
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
    `ORDEM_PRECEDENCIA_BLOCOS`; as demais frases desse processo — do
    próprio candidato dono e de qualquer outro bloco — viram `frases_extra`
    da mesma entrada. Sempre devolve os 6 `BlocoRelatorio`, mesmo vazios.


    `historico_completo`/`contexto_compromissos` (dominio ACHADOS #1, QA
    30/09) pré-carregam em UMA consulta cada o que `_bloco_concluidos`/
    `_bloco_adiados` precisariam consultar por processo/compromisso — o
    history nunca tem registro no futuro, então `_historico_ate_por_
    processo(exercicio, timezone.now())` é o history COMPLETO do
    exercício. `_bloco_alteracoes` continua com sua própria consulta de
    history limitada a `fim=ate` (GAP 1 já fechado, lógica própria e já
    testada) — não é tocada aqui."""
    mapas_fk = {
        "unidade_organizacional": dict(Unidade.objects.values_list("id", "nome")),
        "modalidade": dict(Modalidade.objects.values_list("id", "nome")),
        "instrumento_contratual": dict(
            InstrumentoContratual.objects.values_list("id", "nome")
        ),
    }
    historico_completo = _historico_ate_por_processo(exercicio, timezone.now())
    contexto_compromissos = _contexto_compromissos_em_lote(
        exercicio, historico_por_processo=historico_completo
    )
    candidatos = {
        "inclusoes": _bloco_inclusoes(exercicio, de, ate),
        "exclusoes": _bloco_exclusoes(exercicio, de, ate),
        "iniciados": _bloco_iniciados(exercicio, de, ate),
        "concluidos": _bloco_concluidos(
            exercicio, de, ate, historico_por_processo=historico_completo
        ),
        "adiados": _bloco_adiados(
            exercicio, de, ate, contexto_compromissos=contexto_compromissos
        ),
        "alteracoes": _bloco_alteracoes(exercicio, de, ate, mapas_fk=mapas_fk),
    }

    # "Dono" de cada processo: a primeira chave, na ordem de PRECEDÊNCIA,
    # cujo dict de candidatos contém o `processo_id`.
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
            # quantizar_soma corrige o ruido de ponto flutuante do SUM() do SQLite.
            soma_valor = quantizar_soma(agregado["soma"]) or Decimal("0")
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
        gerado_por=(usuario.get_full_name() or usuario.email) if usuario else "Sistema PCA CFC",
    )
