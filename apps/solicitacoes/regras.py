"""Regras puras das Solicitações das unidades (Fase 43) — sem banco, sem modelo.

Mesmo padrão de `apps/pca/regras_situacao.py`: o que é decisão (quem decide o quê, o que
cada situação do item aceita, o que a decisão exige) mora aqui e é testável sem banco;
`services.py` só orquestra e grava. As enumerações ficam neste módulo para que os modelos
as importem (fonte única de valores).

Decisões de referência..09 em notas internas do projeto.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.db.models import TextChoices


class Campo(TextChoices):
    """O que a unidade pode pedir. Cada campo é uma "parte" da solicitação."""

    PRAZO_ENTREGA = "prazo_entrega", "Prazo de entrega"
    MES_PREVISTO = "mes_previsto", "Mês previsto"
    VALOR_ESTIMADO = "valor_estimado", "Valor estimado"
    DESCRICAO_OBJETO = "descricao_objeto", "Objeto"
    CANCELAMENTO = "cancelamento", "Cancelamento do item"
    INCLUSAO = "inclusao", "Inclusão de item novo"


class Alcada(TextChoices):
    """Quem decide."""

    EQUIPE = "equipe", "Equipe do PCA"
    DIRETORIA = "diretoria", "Diretoria"


class TipoSolicitacao(TextChoices):
    ALTERACAO = "alteracao", "Alteração"
    CANCELAMENTO = "cancelamento", "Cancelamento"
    INCLUSAO = "inclusao", "Inclusão"


class EstadoSolicitacao(TextChoices):
    PENDENTE = "pendente", "Em análise"
    CONCLUIDA = "concluida", "Concluída"
    DESISTIDA = "desistida", "Desistida"


class EstadoParte(TextChoices):
    PENDENTE = "pendente", "Em análise"
    APROVADA = "aprovada", "Aprovada"
    APROVADA_AJUSTE = "aprovada_ajuste", "Aprovada com ajuste"
    RECUSADA = "recusada", "Recusada"
    PREJUDICADA = "prejudicada", "Prejudicada"
    DESISTIDA = "desistida", "Desistida"


class Decisao(TextChoices):
    """O que quem avalia pode fazer com uma parte."""

    APROVAR = "aprovar", "Aprovar"
    AJUSTE = "ajuste", "Aprovar com ajuste"
    RECUSAR = "recusar", "Recusar"


ESTADO_DA_PARTE_POR_DECISAO = {
    Decisao.APROVAR: EstadoParte.APROVADA,
    Decisao.AJUSTE: EstadoParte.APROVADA_AJUSTE,
    Decisao.RECUSAR: EstadoParte.RECUSADA,
}

# Prazo e mês são da equipe do PCA; o resto, da diretoria.
ALCADA_POR_CAMPO = {
    Campo.PRAZO_ENTREGA: Alcada.EQUIPE,
    Campo.MES_PREVISTO: Alcada.EQUIPE,
    Campo.VALOR_ESTIMADO: Alcada.DIRETORIA,
    Campo.DESCRICAO_OBJETO: Alcada.DIRETORIA,
    Campo.CANCELAMENTO: Alcada.DIRETORIA,
    Campo.INCLUSAO: Alcada.DIRETORIA,
}

# Campos que uma solicitação de alteração pode combinar.
CAMPOS_ALTERAVEIS = (
    Campo.PRAZO_ENTREGA,
    Campo.MES_PREVISTO,
    Campo.VALOR_ESTIMADO,
    Campo.DESCRICAO_OBJETO,
)

# Espelham `apps.pca.models.Estado`/`Situacao` — `regras.py` não importa modelos; um teste
# garante que os literais não derivam.
ESTADO_ATIVO = "ativo"
SITUACAO_NO_PRAZO = "no_prazo"
SITUACAO_ATRASADO = "atrasado"
SITUACAO_EM_TRAMITACAO = "em_tramitacao"
SITUACAO_CONCLUIDO = "concluido"

# Tipos aceitos na inclusão (`nome_normalizado` do catálogo `Tipo`).
TIPOS_DE_INCLUSAO = ("nova contratacao", "renovacao")

# Fila "Para avaliar": parada = mais de 10 dias úteis.
LIMITE_PARADA_DIAS_UTEIS = 10

LIMITE_TEXTO = 4000


def alcada_do_campo(campo) -> str:
    return ALCADA_POR_CAMPO[Campo(campo)]


def rotulo_do_campo(campo) -> str:
    return Campo(campo).label


# --- O que o item aceita -----------------------------------------------------


def campos_aceitos(*, estado, situacao_efetiva, exercicio_aberto) -> tuple:
    """Campos que um item aceita pedir. Exercício aberto e item ativo são pré-condição;
    prazo e mês só em item a entregar (no prazo ou atrasado); valor, objeto e cancelamento
    em qualquer item ativo não concluído."""
    if not exercicio_aberto or estado != ESTADO_ATIVO:
        return ()
    if situacao_efetiva in (SITUACAO_NO_PRAZO, SITUACAO_ATRASADO):
        return (*CAMPOS_ALTERAVEIS, Campo.CANCELAMENTO)
    if situacao_efetiva == SITUACAO_EM_TRAMITACAO:
        return (Campo.VALOR_ESTIMADO, Campo.DESCRICAO_OBJETO, Campo.CANCELAMENTO)
    return ()


def motivo_do_item_fechado(*, estado, situacao_efetiva, exercicio_aberto) -> str:
    """Frase para quando o item não aceita pedido nenhum (ou o campo pedido)."""
    if not exercicio_aberto:
        return "O exercício do item está fechado."
    if estado != ESTADO_ATIVO:
        return "O item está cancelado."
    if situacao_efetiva == SITUACAO_CONCLUIDO:
        return "O item está concluído."
    return "O item não aceita este pedido na situação atual."


def validar_pedido(campos) -> None:
    """Uma solicitação de item é de alteração (um ou mais campos) OU de
    cancelamento (sozinho, exclusivo); inclusão é outro caminho (`criar_inclusao`)."""
    campos = [Campo(campo) for campo in campos]
    if not campos:
        raise ValueError("Informe ao menos uma alteração.")
    if Campo.INCLUSAO in campos:
        raise ValueError("A inclusão de item novo é um pedido à parte.")
    if Campo.CANCELAMENTO in campos and len(campos) > 1:
        raise ValueError("O cancelamento do item é pedido sozinho, sem outras alterações.")


def tipo_do_pedido(campos) -> str:
    campos = [Campo(campo) for campo in campos]
    if Campo.CANCELAMENTO in campos:
        return TipoSolicitacao.CANCELAMENTO
    if Campo.INCLUSAO in campos:
        return TipoSolicitacao.INCLUSAO
    return TipoSolicitacao.ALTERACAO


def fora_do_exercicio(prazo: date, ano_exercicio: int) -> bool:
    """Adiamento para depois de 31/12 do exercício é aceito, mas marcado."""
    return prazo > date(ano_exercicio, 12, 31)


# --- Valores: normalização e texto estável ---------------------------------------------


def normalizar_valor(campo, bruto):
    """Valor canônico de Python para o campo (date, int, Decimal ou str); `ValueError` com
    mensagem em português quando não serve."""
    campo = Campo(campo)
    if campo == Campo.PRAZO_ENTREGA:
        if isinstance(bruto, date):
            return bruto
        try:
            return date.fromisoformat(str(bruto).strip())
        except ValueError:
            raise ValueError("Informe uma data válida para o prazo de entrega.") from None
    if campo == Campo.MES_PREVISTO:
        try:
            mes = int(str(bruto).strip())
        except ValueError:
            raise ValueError("Informe o mês previsto de 1 a 12.") from None
        if not 1 <= mes <= 12:
            raise ValueError("Informe o mês previsto de 1 a 12.")
        return mes
    if campo == Campo.VALOR_ESTIMADO:
        try:
            valor = Decimal(str(bruto).strip())
        except InvalidOperation:
            raise ValueError("Informe um valor estimado válido.") from None
        if not valor.is_finite() or valor <= 0 or valor >= Decimal(10) ** 12:
            raise ValueError("Informe um valor estimado maior que zero.")
        return valor.quantize(Decimal("0.01"))
    if campo == Campo.DESCRICAO_OBJETO:
        texto = " ".join(str(bruto or "").split())
        if not texto:
            raise ValueError("Informe o objeto.")
        if len(texto) > LIMITE_TEXTO:
            raise ValueError("O objeto é longo demais.")
        return texto
    raise ValueError("Este campo não tem valor a informar.")


def para_texto(campo, valor) -> str:
    """Serialização estável (a mesma entrada dá sempre o mesmo texto) para
    `valor_atual`/`valor_pedido`/`valor_concedido`."""
    if valor is None:
        return ""
    campo = Campo(campo)
    if campo == Campo.PRAZO_ENTREGA:
        return valor.isoformat() if isinstance(valor, date) else str(valor)
    if campo == Campo.VALOR_ESTIMADO:
        return format(Decimal(valor).quantize(Decimal("0.01")), "f")
    return str(valor)


def de_texto(campo, texto):
    """Inverso de `para_texto` (vazio → None)."""
    if texto in (None, ""):
        return None
    campo = Campo(campo)
    if campo == Campo.PRAZO_ENTREGA:
        return date.fromisoformat(texto)
    if campo == Campo.MES_PREVISTO:
        return int(texto)
    if campo == Campo.VALOR_ESTIMADO:
        return Decimal(texto)
    return texto


# --- Decisão -----------------------------------------------------------------


def decisoes_admitidas(campo) -> tuple:
    """Cancelamento e inclusão não têm o que ajustar: só aprovar ou recusar."""
    if Campo(campo) in (Campo.CANCELAMENTO, Campo.INCLUSAO):
        return (Decisao.APROVAR, Decisao.RECUSAR)
    return (Decisao.APROVAR, Decisao.AJUSTE, Decisao.RECUSAR)


def motivo_obrigatorio(decisao) -> bool:
    """Ajuste e recusa exigem motivo; aprovação pura não."""
    return Decisao(decisao) in (Decisao.AJUSTE, Decisao.RECUSAR)


def validar_decisao(campo, decisao, *, motivo="", valor_ajuste=None, valor_pedido=None):
    """Confere a decisão e devolve `(estado_da_parte, valor_concedido, motivo)`.
    `valor_concedido` é o valor canônico (aprovar → o pedido; ajuste → o ajuste; recusar →
    None). `ValueError` com mensagem em português quando a decisão não vale."""
    campo = Campo(campo)
    try:
        decisao = Decisao(decisao)
    except ValueError:
        raise ValueError("Decisão desconhecida.") from None
    if decisao not in decisoes_admitidas(campo):
        raise ValueError("Este pedido só pode ser aprovado ou recusado.")
    motivo = (motivo or "").strip()
    if motivo_obrigatorio(decisao) and not motivo:
        raise ValueError("Informe o motivo.")
    if decisao == Decisao.RECUSAR:
        return ESTADO_DA_PARTE_POR_DECISAO[decisao], None, motivo
    if decisao == Decisao.AJUSTE:
        concedido = normalizar_valor(campo, valor_ajuste)
        if valor_pedido is not None and para_texto(campo, concedido) == para_texto(campo, valor_pedido):
            raise ValueError("O ajuste é igual ao pedido: aprove sem ajuste.")
        return ESTADO_DA_PARTE_POR_DECISAO[decisao], concedido, motivo
    return ESTADO_DA_PARTE_POR_DECISAO[decisao], valor_pedido, motivo


def pode_decidir(alcada, *, equipe: bool, diretoria: bool) -> bool:
    """Cada um só na sua alçada; quem está nos dois decide tudo."""
    alcada = Alcada(alcada)
    return (alcada == Alcada.EQUIPE and equipe) or (alcada == Alcada.DIRETORIA and diretoria)


def estado_da_solicitacao(estados_das_partes) -> str:
    """Fecha quando nenhuma parte está pendente. Se todas desistiram, a
    solicitação é "desistida"; qualquer outro desfecho (decisão ou prejudicada) é
    "concluída"."""
    estados = [EstadoParte(estado) for estado in estados_das_partes]
    if any(estado == EstadoParte.PENDENTE for estado in estados):
        return EstadoSolicitacao.PENDENTE
    if estados and all(estado == EstadoParte.DESISTIDA for estado in estados):
        return EstadoSolicitacao.DESISTIDA
    return EstadoSolicitacao.CONCLUIDA


# --- Fila --------------------------------------------------------------------


def dias_uteis_entre(inicio: date, fim: date) -> int:
    """Dias úteis (segunda a sexta) decorridos depois de `inicio`, até `fim` inclusive —
    a mesma conta de `core.views._dias_uteis_desde`, sem depender do relógio."""
    dias = 0
    cursor = inicio
    while cursor < fim:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            dias += 1
    return dias


def esta_parada(criada_em: date, hoje: date) -> bool:
    return dias_uteis_entre(criada_em, hoje) > LIMITE_PARADA_DIAS_UTEIS
