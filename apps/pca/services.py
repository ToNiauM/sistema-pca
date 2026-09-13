"""Serviços de domínio para alterações feitas durante a reunião mensal.

Toda alteração de status ou de compromisso de prazo passa por
``registrar_acompanhamento`` para manter o processo, a timeline e a auditoria
na mesma transação.
"""

import hashlib
import uuid

from django.db import transaction
from django.db import IntegrityError
from django.utils.timezone import localdate, now
from simple_history.utils import bulk_create_with_history

from .models import (
    Acompanhamento,
    Estado,
    ProcessoAlocador,
    Processo,
    Reuniao,
    RascunhoItemVirada,
    RascunhoVirada,
    Situacao,
    SituacaoReuniao,
    TipoEvento,
)
from .regras_situacao import situacao_por_eventos
from apps.catalogo.models import Exercicio, SituacaoExercicio, SituacaoNormalizada


class ConflitoDeEdicao(Exception):
    """A linha mudou desde que o chamador a carregou."""

    def __init__(self, processo):
        self.processo = processo
        super().__init__("O processo foi alterado por outro usuário.")


class ObservacaoObrigatoria(Exception):
    """Cancelamento sem justificativa legível."""


class ExercicioFechado(Exception):
    """A operação tenta escrever em um PCA encerrado."""

    def __init__(self, processo):
        self.processo = processo
        super().__init__(
            f"O exercício {processo.exercicio.ano} está fechado. "
            "Não é possível editar itens de um exercício encerrado."
        )


class NenhumItemSelecionado(Exception):
    """A turnover cannot create an empty destination exercise."""


class DestinoJaExiste(Exception):
    """The annual destination is already present or was confirmed elsewhere."""


class ViradaJaConfirmada(Exception):
    """A draft was already committed."""


class ExercicioJaEncerrado(Exception):
    """The requested annual closure is stale or already complete."""


class UltimoExercicioAberto(Exception):
    """At least one annual exercise must remain open."""


CAMPOS_PLANEJAMENTO_COPIAVEIS = (
    "descricao_objeto",
    "justificativa",
    "tipo_id",
    "categoria_id",
    "unidade_organizacional_id",
    "valor_estimado",
    "mes_previsto",
    "grau_prioridade_id",
    "classificacao_id",
    # prazo_entrega é dado de Planejamento, copiado como qualquer outro
    # campo. Distinto de data_recebimento_gelic, que continua explicitamente
    # zerado abaixo por ser fato consumado do exercício de origem
    "prazo_entrega",
)

CAMPOS_EXECUCAO_COPIAVEIS = (
    "modalidade_id",
    "vigencia_inicio",
    "vigencia_fim",
    "numero_contratacao",
    "numero_arp",
    "instrumento_contratual_id",
    "numero_instrumento_contratual",
    "valor_contratado",
    "fornecedor_cnpj",
    "fornecedor_razao_social",
    "data_assinatura_contrato",
    "data_lancamento_spw",
    "data_lancamento_wordpress",
    "data_lancamento_dados_abertos",
)


def _montar_copia(linha, destino, numero):
    origem = linha.processo_origem
    valores = {
        "item_pca": numero,
        "exercicio": destino,
        "origem": origem,
        # um processo concluído na origem chega concluído no destino: copiar
        # um contrato vigente/concluído não "reabre" o item. Qualquer outra
        # situação reseta para NO_PRAZO — o novo exercício começa do zero
        "estado": Estado.ATIVO,
        "situacao": (
            origem.situacao if origem.situacao == Situacao.CONCLUIDO else Situacao.NO_PRAZO
        ),
        "data_inclusao_pca": None,
        "data_envio_gelic": None,
        "data_recebimento_gelic": None,
        "data_prevista_conclusao": None,
        "situacao_sei": "",
    }
    for campo in CAMPOS_PLANEJAMENTO_COPIAVEIS:
        valores[campo] = getattr(linha, campo + "_editado", None) if campo in (
            "valor_estimado", "mes_previsto"
        ) else getattr(origem, campo)
    valores["valor_estimado"] = linha.valor_estimado_editado
    valores["mes_previsto"] = linha.mes_previsto_editado
    if origem.situacao == Situacao.CONCLUIDO:
        for campo in CAMPOS_EXECUCAO_COPIAVEIS:
            valores[campo] = getattr(origem, campo)
    return Processo(**valores)


def _confirmar_virada(*, rascunho_id, usuario):
    with transaction.atomic():
        rascunho = (
            RascunhoVirada.objects.select_for_update()
            .select_related("exercicio_origem")
            .get(pk=rascunho_id)
        )
        if Exercicio.objects.filter(ano=rascunho.ano_destino).exists():
            raise DestinoJaExiste()
        if rascunho.confirmado_em is not None:
            raise ViradaJaConfirmada()
        linhas = list(
            rascunho.itens.select_for_update()
            .filter(selecionado=True)
            .select_related("processo_origem")
            .order_by("ordem", "processo_origem__item_pca")
        )
        if not linhas:
            raise NenhumItemSelecionado()
        origem_ids = [linha.processo_origem_id for linha in linhas]
        fontes = {
            processo.pk: processo
            for processo in Processo.objects.select_for_update().filter(pk__in=origem_ids)
        }
        if len(fontes) != len(origem_ids):
            raise ValueError("A origem de uma linha da virada não existe mais.")
        for linha in linhas:
            linha.processo_origem = fontes[linha.processo_origem_id]
        destino = Exercicio.objects.create(
            ano=rascunho.ano_destino,
            rotulo=f"PCA {rascunho.ano_destino}",
            situacao=SituacaoExercicio.ABERTO,
        )
        copias = [
            _montar_copia(linha, destino, numero)
            for numero, linha in enumerate(linhas, start=1)
        ]
        bulk_create_with_history(
            copias,
            Processo,
            batch_size=200,
            default_user=usuario,
            default_change_reason=f"Virada {rascunho.exercicio_origem.ano}/{destino.ano}",
        )
        rascunho.confirmado_em = now()
        rascunho.confirmado_por = usuario
        rascunho.save(update_fields=["confirmado_em", "confirmado_por", "atualizado_em"])
        return destino


def confirmar_virada(*, rascunho_id, usuario):
    """Confirm a turnover once; translate annual uniqueness races to domain errors."""
    try:
        return _confirmar_virada(rascunho_id=rascunho_id, usuario=usuario)
    except IntegrityError as exc:
        if "ano" in str(exc).lower() or "virada" in str(exc).lower():
            raise DestinoJaExiste() from exc
        raise


@transaction.atomic
def fechar_exercicio(*, ano, usuario=None):
    """Close one exercise without storing a separate current-year marker.

    The row lock makes the open-year check and state transition one operation;
    callers receive the greatest remaining open exercise for their redirect.
    """
    exercicio = Exercicio.objects.select_for_update().get(ano=ano)
    if exercicio.situacao == SituacaoExercicio.FECHADO:
        raise ExercicioJaEncerrado()
    restantes = list(
        Exercicio.objects.select_for_update()
        .filter(situacao=SituacaoExercicio.ABERTO)
        .exclude(pk=exercicio.pk)
        .order_by("-ano")
    )
    if not restantes:
        raise UltimoExercicioAberto()
    exercicio.situacao = SituacaoExercicio.FECHADO
    exercicio.save(update_fields=["situacao"])
    return restantes[0]
def bloquear_para_edicao(processo_id, versao_cliente):
    """Carrega, trava e valida a edição de uma linha do PCA."""
    processo = (
        Processo.objects.select_related("exercicio")
        .select_for_update()
        .get(pk=processo_id)
    )
    if processo.exercicio.situacao == SituacaoExercicio.FECHADO:
        raise ExercicioFechado(processo)
    if processo.atualizado_em.isoformat() != versao_cliente:
        raise ConflitoDeEdicao(processo)
    return processo


# cada situação precisa de uma situação normalizada já existente na
# planilha; NO_PRAZO e ATRASADO caem no mesmo fallback "Sem informação"
MAPA_SITUACAO_NORMALIZADA_POR_SITUACAO = {
    Situacao.CONCLUIDO: "Concluído",
    Situacao.EM_TRAMITACAO: "Em tramitação",
    Situacao.NO_PRAZO: "Sem informação",
    Situacao.ATRASADO: "Sem informação",
}


def reuniao_corrente() -> Reuniao | None:
    return (
        Reuniao.objects.filter(situacao=SituacaoReuniao.ABERTA)
        .order_by("-data")
        .first()
    )


@transaction.atomic
def registrar_acompanhamento(
    *,
    processo_id,
    usuario,
    versao_cliente,
    situacao_novo=None,
    prazo_prometido=None,
    observacao="",
    justificativa="",
    reuniao=None,
    tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO,
    usar_reuniao_corrente=True,
    reafirmar_situacao=False,
):
    # reafirmar_situacao=True satisfaz esta pré-condição sem situacao_novo
    # nem prazo_prometido: grava um Acompanhamento de observação/justificativa
    # sem tocar Processo.situacao e sem transicao_manual=True
    if (
        situacao_novo is None
        and prazo_prometido is None
        and not reafirmar_situacao
    ):
        raise ValueError("informe situacao_novo ou prazo_prometido")
    if situacao_novo is not None and situacao_novo not in MAPA_SITUACAO_NORMALIZADA_POR_SITUACAO:
        raise ValueError(f"situação inválida: {situacao_novo}")

    processo = bloquear_para_edicao(processo_id, versao_cliente)

    processo._history_user = usuario
    if situacao_novo is not None:
        processo.situacao = situacao_novo
    elif prazo_prometido is not None:
        # prazo isolado reavalia a situação com a mesma precedência de
        # aplicar_regras_automaticas: existe sobreposição manual ativa quando
        # qualquer Acompanhamento já gravado tem transicao_manual=True. Com
        # sobreposição manual, processo.situacao é preservada tal como está.
        # Sem sobreposição manual, fatos gravados têm prioridade via
        # situacao_por_eventos; só na ausência de qualquer fato um prazo em
        # NO_PRAZO/ATRASADO é normalizado de volta a NO_PRAZO
        manual_ativa = processo.acompanhamentos.filter(transicao_manual=True).exists()
        if not manual_ativa:
            alvo = situacao_por_eventos(
                tipo_nome_normalizado=processo.tipo.nome_normalizado,
                data_assinatura_contrato=processo.data_assinatura_contrato,
                data_recebimento_gelic=processo.data_recebimento_gelic,
            )
            if alvo is not None:
                processo.situacao = alvo
            elif processo.situacao in (Situacao.NO_PRAZO, Situacao.ATRASADO):
                processo.situacao = Situacao.NO_PRAZO
    # mesmo uma mudança apenas de prazo avança o token: a edição é de
    # linha, não de campo, e precisa concorrer com as demais edições
    processo.save(update_fields=["situacao", "atualizado_em"])

    # usar_reuniao_corrente=False desliga o fallback: a automação nunca
    # prende um Acompanhamento a uma reunião ABERTA por acidente
    if usar_reuniao_corrente and reuniao is None:
        reuniao = reuniao_corrente()
    referencia_data = reuniao.data if reuniao else localdate()
    origem_hash = hashlib.sha256(
        f"ui:{processo_id}:{now().isoformat()}:{uuid.uuid4().hex}".encode()
    ).hexdigest()
    acompanhamento = Acompanhamento(
        processo=processo,
        referencia_data=referencia_data,
        origem_hash=origem_hash,
        # a justificativa da nova promessa vive em evento, separado de
        # situacao_informada, que reserva o texto literal da transição de
        # situação
        evento=justificativa.strip(),
        tipo_evento=tipo_evento,
        situacao_informada=observacao,
        situacao=SituacaoNormalizada.objects.get(
            nome=MAPA_SITUACAO_NORMALIZADA_POR_SITUACAO[situacao_novo or processo.situacao]
        ),
        prazo_prometido=prazo_prometido,
        reuniao=reuniao,
        # só é uma transição manual de situação quando situacao_novo é
        # explícito por uma via não-automática (o modal de transição)
        transicao_manual=(
            situacao_novo is not None and tipo_evento != TipoEvento.AUTOMATICO
        ),
    )
    acompanhamento._history_user = usuario
    acompanhamento.save()
    return processo


def alterar_estado(*, processo_id, usuario, estado_novo, observacao=""):
    """Única via de mudança de Processo.estado. Chamada exclusivamente por
    ProcessoAdmin.save_model; a exclusão mútua vem do select_for_update()
    dentro da própria transação. Idempotente: reaplicar o mesmo estado_novo
    não grava um segundo Acompanhamento."""
    with transaction.atomic():
        processo = Processo.objects.select_for_update().get(pk=processo_id)
        if processo.estado == estado_novo:
            return processo

        processo._history_user = usuario
        processo.estado = estado_novo
        processo.save(update_fields=["estado", "atualizado_em"])

        origem_hash = hashlib.sha256(
            f"admin:{processo_id}:{now().isoformat()}:{uuid.uuid4().hex}".encode()
        ).hexdigest()
        acompanhamento = Acompanhamento(
            processo=processo,
            referencia_data=localdate(),
            origem_hash=origem_hash,
            evento="",
            tipo_evento=TipoEvento.AUTOMATICO,
            situacao_informada=(
                observacao or f"Estado alterado para {Estado(estado_novo).label} via admin."
            ),
            situacao=SituacaoNormalizada.objects.get(
                nome="Cancelado" if estado_novo == Estado.CANCELADO else "Sem informação"
            ),
            prazo_prometido=None,
            reuniao=None,
        )
        acompanhamento._history_user = usuario
        acompanhamento.save()
        return processo


def aplicar_regras_automaticas(*, processo, usuario):
    """Deriva situacao de processo dos dados já preenchidos. Só grava
    situacao — estado é alterável apenas via alterar_estado. Delega
    inteiramente a situacao_por_eventos, a fonte única de derivação por
    eventos gravados. concluido nunca é rebaixado automaticamente; uma
    sobreposição manual não-terminal registrada por último também nunca é
    desfeita — "manual vence, automático não reverte". Nunca escreve
    atrasado — a correção NO_PRAZO -> ATRASADO é de leitura, não de escrita.
    Mudar tipo reavalia a situação na mesma chamada.

    Nunca toca um processo cancelado. Toda mudança passa por
    registrar_acompanhamento, com tipo_evento=TipoEvento.AUTOMATICO e
    reuniao=None: nunca grava processo.situacao direto, nunca infla
    n_reunioes.

    Retorna o Processo atualizado quando muda algo, None caso contrário."""
    if processo.estado == Estado.CANCELADO:
        return None
    if processo.situacao == Situacao.CONCLUIDO:
        # piso, nunca desce: terminal para qualquer novo evento
        return None

    # uma transição manual real de situação vence, e a automação nunca
    # desfaz uma sobreposição humana. Acompanhamento.transicao_manual
    # materializa essa distinção na escrita: só é True quando situacao_novo
    # foi passado explicitamente por uma via não-automática. A guarda olha
    # a existência de qualquer transicao_manual=True no histórico inteiro,
    # não só o último Acompanhamento
    if processo.acompanhamentos.filter(transicao_manual=True).exists():
        return None

    alvo = situacao_por_eventos(
        tipo_nome_normalizado=processo.tipo.nome_normalizado,
        data_assinatura_contrato=processo.data_assinatura_contrato,
        data_recebimento_gelic=processo.data_recebimento_gelic,
    )
    if alvo is None or alvo == processo.situacao:
        return None

    if (
        processo.tipo.nome_normalizado == "vigente"
        and processo.data_assinatura_contrato is None
    ):
        motivo = "Vigente é concluído por natureza"
    elif alvo == Situacao.CONCLUIDO:
        data_fmt = processo.data_assinatura_contrato.strftime("%d/%m/%Y")
        motivo = f"Data de assinatura do contrato preenchida ({data_fmt})"
    else:
        # alvo == Situacao.EM_TRAMITACAO — única alternativa que
        # situacao_por_eventos pode devolver além de concluido/None
        data_fmt = processo.data_recebimento_gelic.strftime("%d/%m/%Y")
        motivo = f"Data de Recebimento no Gelic preenchida ({data_fmt})"

    causa = f"Situação atualizada automaticamente para {Situacao(alvo).label} — {motivo}."

    return registrar_acompanhamento(
        processo_id=processo.pk,
        usuario=usuario,
        versao_cliente=processo.atualizado_em.isoformat(),
        situacao_novo=alvo,
        observacao=causa,
        tipo_evento=TipoEvento.AUTOMATICO,
        reuniao=None,
        usar_reuniao_corrente=False,
    )


@transaction.atomic
def criar_reuniao(*, data, usuario=None, exercicio=None, situacao=SituacaoReuniao.ABERTA):
    """Cria uma reunião no exercício em foco, nunca no ano do formulário."""
    exercicio = exercicio or Exercicio.objects.filter(
        situacao=SituacaoExercicio.ABERTO
    ).order_by("-ano").first()
    if exercicio is None:
        raise ValueError("Nenhum exercício aberto está disponível.")
    reuniao = Reuniao(data=data, exercicio=exercicio, situacao=situacao)
    reuniao.full_clean()
    reuniao.save()
    return reuniao


@transaction.atomic
def criar_processo(
    *,
    usuario,
    descricao_objeto,
    tipo_id,
    categoria_id,
    unidade_organizacional_id,
    exercicio=None,
):
    """Cria um item novo com o próximo número do PCA.

    A linha singleton do alocador é bloqueada antes de consultar o maior
    item, inclusive quando a tabela de processos está vazia. O usuário é
    definido antes do primeiro save para que a linha de auditoria de
    criação tenha autoria.

    A situação inicial é derivada por situacao_por_eventos no mesmo
    instante da criação, não um literal fixo — um item novo com
    Tipo=Vigente já nasce Situacao.CONCLUIDO, não NO_PRAZO. Para qualquer
    outro Tipo, o fallback Situacao.NO_PRAZO se aplica.
    """
    exercicio = exercicio or Exercicio.objects.filter(
        situacao=SituacaoExercicio.ABERTO
    ).order_by("-ano").first()
    if exercicio is None:
        raise ValueError("Nenhum exercício aberto está disponível.")
    if exercicio.situacao == SituacaoExercicio.FECHADO:
        processo = Processo(exercicio=exercicio)
        processo.exercicio = exercicio
        raise ExercicioFechado(processo)
    ProcessoAlocador.objects.get_or_create(chave=1)
    ProcessoAlocador.objects.select_for_update().get(chave=1)
    ultimo = Processo.objects.filter(exercicio=exercicio).order_by("-item_pca").values_list(
        "item_pca", flat=True
    ).first()
    processo = Processo(
        item_pca=(ultimo or 0) + 1,
        exercicio=exercicio,
        descricao_objeto=descricao_objeto,
        tipo_id=tipo_id,
        categoria_id=categoria_id,
        unidade_organizacional_id=unidade_organizacional_id,
        estado=Estado.ATIVO,
        data_inclusao_pca=localdate(),
    )
    processo.situacao = situacao_por_eventos(
        tipo_nome_normalizado=processo.tipo.nome_normalizado,
        data_assinatura_contrato=None,
        data_recebimento_gelic=None,
    ) or Situacao.NO_PRAZO
    processo._history_user = usuario
    processo.save()
    return processo
