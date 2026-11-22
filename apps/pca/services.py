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
from .regras_situacao import (
    CONCLUIDO_OBRIGATORIO,
    CONCLUSAO_BLOQUEADA,
    exigencia_do_contrato,
    situacao_por_eventos,
)
from apps.catalogo.models import Exercicio, SituacaoExercicio, SituacaoNormalizada


class ConflitoDeEdicao(Exception):
    """A linha mudou desde que o chamador a carregou."""

    def __init__(self, processo):
        self.processo = processo
        super().__init__("O processo foi alterado por outro usuário.")


class SituacaoImpostaPelaVigencia(Exception):
    """A regra de renovação × vigência não admite a situação
    escolhida à mão — vence qualquer transição manual."""

    def __init__(self, motivo):
        self.motivo = motivo
        super().__init__(motivo)


def exigencia_de(processo):
    """`exigencia_do_contrato` sobre um `Processo`: datas de assinatura =
    a do item (vem do contrato ou do último termo aditivo, nunca de
    apostilamento) + as dos eventos de contrato/termo aditivo coletados do
    SEI. Uma consulta (eventos)."""
    from .models import TipoEventoFinanceiro

    datas = [processo.data_assinatura_contrato]
    datas.extend(
        processo.eventos_financeiros.filter(
            tipo__in=[TipoEventoFinanceiro.CONTRATO, TipoEventoFinanceiro.ADITIVO]
        ).values_list("data", flat=True)
    )
    return exigencia_do_contrato(
        ano_exercicio=processo.exercicio.ano,
        tipo_nome_normalizado=processo.tipo.nome_normalizado,
        vigencia_fim=processo.vigencia_fim,
        renovacao_prevista=processo.renovacao_prevista,
        datas_assinatura=datas,
    )


def _alvo_da_exigencia(processo, exigencia):
    """Situação que a regra impõe: concluído, ou — conclusão bloqueada —
    a derivada dos demais fatos (em tramitação) com fallback NO_PRAZO (a
    leitura mostra Atrasado quando o prazo ou a vigência já passou)."""
    return situacao_por_eventos(
        tipo_nome_normalizado=processo.tipo.nome_normalizado,
        data_assinatura_contrato=processo.data_assinatura_contrato,
        data_recebimento_gelic=processo.data_recebimento_gelic,
        exigencia=exigencia,
        ano_exercicio=processo.exercicio.ano,
    ) or Situacao.NO_PRAZO


class ObservacaoObrigatoria(Exception):
    """Cancelamento sem justificativa legível."""


class ExercicioFechado(Exception):
    """A operação tenta escrever em um PCA encerrado."""

    def __init__(self, processo=None, *, exercicio=None):
        self.processo = processo
        self.exercicio = exercicio or processo.exercicio
        super().__init__(
            f"O exercício {self.exercicio.ano} está fechado. "
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
    # Fase 11 — prazo_entrega é dado de Planejamento (a promessa do PCA
    # em si), copiado como qualquer outro campo de planejamento. Distinto de
    # `data_recebimento_gelic` (Fase 15), que continua
    # explicitamente zerado abaixo por ser fato consumado do exercício de
    # origem.
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
        # Fase 17: um processo concluído (Vigente ou Renovação com
        # contrato assinado) na origem chega concluído no destino — preserva
        # o comportamento observável anterior (copiar um contrato
        # vigente/concluído não "reabre" o item no novo exercício). Qualquer
        # outra situação (no_prazo/atrasado/em_tramitacao) reseta para
        # NO_PRAZO — o novo exercício começa do zero para itens ainda não
        # concluídos (equivalente ao antigo NAO_INICIADO).
        "estado": Estado.ATIVO,
        "situacao": (
            origem.situacao if origem.situacao == Situacao.CONCLUIDO else Situacao.NO_PRAZO
        ),
        "data_inclusao_pca": None,
        "data_envio_gelic": None,
        "data_recebimento_gelic": None,
        "data_prevista_conclusao": None,
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

    `select_for_update()` é no-op no backend sqlite3 do Django (sem lock de
    linha); a exclusão mútua real vem do lock de banco inteiro de
    `transaction_mode="IMMEDIATE"` (config/settings/base.py), que já torna
    o check do ano aberto e a transição de estado uma única operação.
    Callers receive the greatest remaining open exercise for their
    redirect.
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
def bloquear_para_edicao(processo_id, versao_cliente, ignorar_exercicio_fechado: bool = False):
    """Carrega, trava e valida a edição de uma linha do PCA."""
    processo = (
        Processo.objects.select_related("exercicio")
        .select_for_update()
        .get(pk=processo_id)
    )
    if not ignorar_exercicio_fechado and processo.exercicio.situacao == SituacaoExercicio.FECHADO:
        raise ExercicioFechado(processo)
    if processo.atualizado_em.isoformat() != versao_cliente:
        raise ConflitoDeEdicao(processo)
    return processo


# Fase 17: cada situação (eixo Situação) precisa de uma situação
# normalizada já existente na planilha (catálogo de 12 valores; não criamos
# um 13º só para este mapa). NO_PRAZO e ATRASADO caem no mesmo fallback
# "Sem informação" já usado pelo antigo status nao_iniciado — nenhum dos dois
# tem entrada literal equivalente no catálogo.
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
    ignorar_exercicio_fechado: bool = False,
):
    # `reafirmar_situacao=True` (`acompanhamento_modal_view`
    # "só observação") satisfaz esta pré-condição sem `situacao_novo` nem
    # `prazo_prometido`: grava um Acompanhamento de observação/justificativa
    # sem tocar `Processo.situacao` e SEM `transicao_manual=True` (o modal
    # nunca altera situação por conta própria — reafirmar não é escolher).
    if (
        situacao_novo is None
        and prazo_prometido is None
        and not reafirmar_situacao
    ):
        raise ValueError("informe situacao_novo ou prazo_prometido")
    if situacao_novo is not None and situacao_novo not in MAPA_SITUACAO_NORMALIZADA_POR_SITUACAO:
        raise ValueError(f"situação inválida: {situacao_novo}")

    processo = bloquear_para_edicao(
        processo_id, versao_cliente, ignorar_exercicio_fechado=ignorar_exercicio_fechado
    )

    # 29/09/2026 (decisão do usuário) — escolha manual de situação prevalece sobre as regras (inclusive
    # a de renovação × vigência) e liga a trava `situacao_manual`, que só se desfaz no Admin. O que as
    # regras aplicariam fica em `situacao_regra` (aviso no Início), calculado depois de gravar.
    manual_explicita = situacao_novo is not None and tipo_evento != TipoEvento.AUTOMATICO

    processo._history_user = usuario
    if situacao_novo is not None:
        processo.situacao = situacao_novo
        if manual_explicita:
            processo.situacao_manual = True
    elif processo.situacao_manual:
        # Trava ligada: prazo ou observação não mexem na situação escolhida manualmente.
        pass
    elif prazo_prometido is not None:
        # Prazo isolado (sem `situacao_novo` explícito) reavalia a
        # situação com a MESMA precedência de `aplicar_regras_automaticas`:
        # existe sobreposição manual ativa quando QUALQUER Acompanhamento já
        # gravado do processo tem `transicao_manual=True` — não existe sinal
        # autorizado de reset, então a existência isolada já basta. Com
        # sobreposição manual, `processo.situacao` é preservada tal como
        # está. Sem sobreposição manual, fatos gravados (assinatura de
        # contrato, recebimento no Gelic) têm prioridade via
        # `situacao_por_eventos`; só na ausência de qualquer fato um prazo
        # em NO_PRAZO/ATRASADO é normalizado de volta a NO_PRAZO.
        # Esta promessa continua `transicao_manual=False` (calculado abaixo
        # a partir do parâmetro `situacao_novo`, que permanece `None`).
        manual_ativa = processo.situacao_manual
        exigencia, _motivo = exigencia_de(processo)
        if exigencia == CONCLUIDO_OBRIGATORIO:
            processo.situacao = Situacao.CONCLUIDO
        elif exigencia == CONCLUSAO_BLOQUEADA and processo.situacao == Situacao.CONCLUIDO:
            processo.situacao = _alvo_da_exigencia(processo, exigencia)
        elif not manual_ativa:
            alvo = situacao_por_eventos(
                tipo_nome_normalizado=processo.tipo.nome_normalizado,
                data_assinatura_contrato=processo.data_assinatura_contrato,
                data_recebimento_gelic=processo.data_recebimento_gelic,
                exigencia=exigencia,
                ano_exercicio=processo.exercicio.ano,
            )
            if alvo is not None:
                processo.situacao = alvo
            elif processo.situacao in (Situacao.NO_PRAZO, Situacao.ATRASADO, Situacao.EM_TRAMITACAO):
                # 29/09/2026 — sem recebimento no Gelic no ano do PCA, não está em tramitação.
                processo.situacao = Situacao.NO_PRAZO
    # Mesmo uma mudança apenas de prazo avança o token: a edição é de linha,
    # não de campo, e precisa concorrer com as demais edições.
    processo.save(update_fields=["situacao", "situacao_manual", "atualizado_em"])

    # Fase 15 — `usar_reuniao_corrente=False` desliga o fallback: a
    # automação nunca prende um Acompanhamento a uma reunião ABERTA por
    # acidente (reuniao permanece exatamente o que o chamador passou).
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
        # (Fase 11) — a justificativa da nova promessa vive em
        # `evento`, separado de `situacao_informada`, que reserva
        # ao texto literal da transição de situação (modal de kanban).
        evento=justificativa.strip(),
        tipo_evento=tipo_evento,
        situacao_informada=observacao,
        situacao=SituacaoNormalizada.objects.get(
            nome=MAPA_SITUACAO_NORMALIZADA_POR_SITUACAO[situacao_novo or processo.situacao]
        ),
        prazo_prometido=prazo_prometido,
        reuniao=reuniao,
        # Fase 17 (gap-closure GAP 1) — só é uma transição
        # MANUAL de situação quando `situacao_novo` é explícito por uma via
        # NÃO-automática (`confirmar_transicao_view`, o modal de transição).
        # `aplicar_regras_automaticas` sempre passa `tipo_evento=AUTOMATICO`,
        # e `registrar_promessa_view` sempre passa `situacao_novo=None` — em
        # ambos os casos o campo nasce `False`.
        transicao_manual=(
            situacao_novo is not None and tipo_evento != TipoEvento.AUTOMATICO
        ),
    )
    acompanhamento._history_user = usuario
    acompanhamento.save()
    if manual_explicita:
        atualizar_situacao_regra(processo, usuario)
    return processo


def situacao_pelas_regras(processo):
    """O que as regras automáticas aplicariam à situação de `processo`, ignorando a trava manual
    (mesma precedência de `aplicar_regras_automaticas`). Sem fato que decida, devolve a situação
    atual — a regra não tem opinião, então concorda."""
    exigencia, _motivo = exigencia_de(processo)
    if exigencia == CONCLUIDO_OBRIGATORIO:
        return Situacao.CONCLUIDO
    if exigencia == CONCLUSAO_BLOQUEADA and processo.situacao == Situacao.CONCLUIDO:
        return _alvo_da_exigencia(processo, exigencia)
    if processo.situacao == Situacao.CONCLUIDO:
        return Situacao.CONCLUIDO
    alvo = situacao_por_eventos(
        tipo_nome_normalizado=processo.tipo.nome_normalizado,
        data_assinatura_contrato=processo.data_assinatura_contrato,
        data_recebimento_gelic=processo.data_recebimento_gelic,
        exigencia=exigencia,
        ano_exercicio=processo.exercicio.ano,
    )
    if alvo is None:
        return Situacao.NO_PRAZO if processo.situacao == Situacao.EM_TRAMITACAO else processo.situacao
    return alvo


def atualizar_situacao_regra(processo, usuario, alvo=None):
    """Com a trava manual ligada, grava em `situacao_regra` o que as regras aplicariam quando diverge
    da escolha manual (vazio quando concordam). Só grava se mudou — não enche o histórico."""
    if not processo.situacao_manual:
        regra = ""
    else:
        alvo = alvo or situacao_pelas_regras(processo)
        regra = "" if alvo == processo.situacao else alvo
    if processo.situacao_regra != regra:
        processo.situacao_regra = regra
        processo._history_user = usuario
        processo.save(update_fields=["situacao_regra", "atualizado_em"])
    return processo


def liberar_situacao_automatica(*, processo_id, usuario, ignorar_exercicio_fechado: bool = False):
    """Desmarcar "situação manual" (Admin): registra no histórico quem liberou e recalcula a situação
    pelas regras na hora."""
    processo = Processo.objects.select_related("tipo", "exercicio").get(pk=processo_id)
    processo.situacao_manual = False
    processo.situacao_regra = ""
    processo._history_user = usuario
    processo.save(update_fields=["situacao_manual", "situacao_regra", "atualizado_em"])
    processo = registrar_acompanhamento(
        processo_id=processo.pk,
        usuario=usuario,
        versao_cliente=processo.atualizado_em.isoformat(),
        observacao=(
            "Situação liberada para as regras automáticas por "
            f"{usuario.get_full_name() or usuario.email} (situação manual desmarcada no Admin)."
        ),
        tipo_evento=TipoEvento.AUTOMATICO,
        reuniao=None,
        usar_reuniao_corrente=False,
        reafirmar_situacao=True,
        ignorar_exercicio_fechado=ignorar_exercicio_fechado,
    )
    processo = Processo.objects.select_related("tipo", "exercicio").get(pk=processo_id)
    return aplicar_regras_automaticas(processo=processo, usuario=usuario) or processo


def alterar_estado(*, processo_id, usuario, estado_novo, observacao=""):
    """Fase 17 — única via de mudança de `Processo.estado`.

    Chamada exclusivamente por `ProcessoAdmin.save_model`;
    nenhuma view fora do admin invoca esta função (02). Sem controle
    de versão otimista via `versao_cliente` — o admin não tem esse mecanismo
    de UI. `select_for_update()` é no-op no backend sqlite3 do Django (sem
    lock de linha); a exclusão mútua real vem do lock de banco inteiro de
    `transaction_mode="IMMEDIATE"` (config/settings/base.py). Idempotente:
    reaplicar o mesmo `estado_novo` não grava um segundo `Acompanhamento`
    (03, aceito — resubmissão silenciosa é o comportamento
    esperado).
    """
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


def alternar_renovacao_prevista(*, processo_id, usuario, renovacao_prevista: bool):
    """Fase 36 (spec §6.5) — grava o "renovar?"
    da tela Prazos. MESMO molde de `alterar_estado` acima
    (`select_for_update`/`_history_user`/`save(update_fields=[...])`),
    mais simples: ajuste de planejamento financeiro (a camada Renovação
    prevista do fluxo de caixa, `apps.pca.projecao.fluxo`), NÃO mudança de
    situação operacional por si — mas reaplica `aplicar_regras_automaticas`,
que pode registrar um `Acompanhamento` automático quando
    a regra de renovação × vigência muda a situação. Idempotente: reaplicar
    o mesmo valor não grava."""
    with transaction.atomic():
        processo = Processo.objects.select_related("exercicio").select_for_update().get(
            pk=processo_id
        )
        if processo.exercicio.situacao == SituacaoExercicio.FECHADO:
            raise ExercicioFechado(processo)
        if processo.renovacao_prevista == renovacao_prevista:
            return processo

        processo._history_user = usuario
        processo.renovacao_prevista = renovacao_prevista
        processo.save(update_fields=["renovacao_prevista", "atualizado_em"])
        # "renovar?" agora rege a situação (renovação no ano
        # sem aditivo não conclui; desmarcada, o contrato encerra e a regra
        # sai de cena): reavalia na mesma transação.
        return aplicar_regras_automaticas(processo=processo, usuario=usuario) or processo


def aplicar_regras_automaticas(*, processo, usuario):
    """Deriva `situacao` de `processo` dos dados já preenchidos (Fase 17).

    Só grava `situacao` — `estado` é alterável apenas via
    `alterar_estado` (admin). delega inteiramente a
    `situacao_por_eventos` (regras_situacao.py), a fonte única de derivação
    por eventos gravados — nunca decide por conta própria. (piso,
    terminal): `concluido` nunca é rebaixado automaticamente; e (17-14) uma sobreposição manual não-terminal (NO_PRAZO/ATRASADO/
    EM_TRAMITACAO) registrada por último também nunca é desfeita — "manual
    vence, automático não reverte". nunca escreve `atrasado` — a
    correção NO_PRAZO -> ATRASADO é de leitura, não de
    escrita; viradas puras de calendário não geram Acompanhamento.
    mudar `tipo` reavalia a situação na mesma chamada (qualquer edição de
    campo já dispara esta função). revoga a regra R3/`a_renovar` —
    zero instâncias em produção.

    Nunca toca um processo `cancelado` (eixo Estado). Toda mudança passa por
    `registrar_acompanhamento`, com `tipo_evento=TipoEvento.AUTOMATICO` e
    `reuniao=None`: nunca grava `processo.situacao` direto, nunca infla
    `n_reunioes`.

    Retorna o `Processo` atualizado quando muda algo, `None` caso contrário
    (cancelado, terminal, sem gatilho, ou já no alvo).
    """
    if processo.estado == Estado.CANCELADO:
        return None

    # 29/09/2026 — trava manual: nenhuma regra mexe na situação; só registra o que aplicaria.
    if processo.situacao_manual:
        atualizar_situacao_regra(processo, usuario)
        return None

    # Renovação × vigência vem ANTES do piso e da guarda
    # manual: é a única regra que tira um item de Concluído (renovação no
    # ano sem contrato/termo aditivo do ano) e que conclui por cima de uma
    # transição manual (vigente além do ano, ou aditivo do ano assinado).
    exigencia, motivo_exigencia = exigencia_de(processo)
    if exigencia is not None:
        alvo = _alvo_da_exigencia(processo, exigencia)
        impoe = (
            exigencia == CONCLUIDO_OBRIGATORIO and processo.situacao != Situacao.CONCLUIDO
        ) or (
            exigencia == CONCLUSAO_BLOQUEADA and processo.situacao == Situacao.CONCLUIDO
        )
        if impoe:
            return registrar_acompanhamento(
                processo_id=processo.pk,
                usuario=usuario,
                versao_cliente=processo.atualizado_em.isoformat(),
                situacao_novo=alvo,
                observacao=(
                    f"Situação atualizada automaticamente para {Situacao(alvo).label} — "
                    f"{motivo_exigencia[0].upper()}{motivo_exigencia[1:]}."
                ),
                tipo_evento=TipoEvento.AUTOMATICO,
                reuniao=None,
                usar_reuniao_corrente=False,
            )

    if processo.situacao == Situacao.CONCLUIDO:
        # Piso, nunca desce: terminal para qualquer novo evento.
        return None

    # /GAP 1 (17-16, gap-closure) — reforçado por
    # Uma TRANSIÇÃO MANUAL real de situação vence, e a automação
    # nunca desfaz uma sobreposição humana. O campo
    # `Acompanhamento.transicao_manual` materializa essa distinção NA
    # ESCRITA (ver `registrar_acompanhamento` acima): só é `True` quando
    # `situacao_novo` foi passado explicitamente por uma via não-automática
    # (`confirmar_transicao_view`). A guarda olha a EXISTÊNCIA de qualquer
    # `transicao_manual=True` no histórico inteiro, não só o último
    # Acompanhamento por id/data — não existe sinal autorizado de reset, e
    # uma promessa de prazo posterior (`transicao_manual=False`, isolada ou
    # gravada pelo importador) não pode mascarar uma sobreposição manual
    # anterior. Um processo recém-criado via ORM direto (sem nenhum
    # Acompanhamento — ex.: fixtures de teste que usam `_processo()`, como em
    # `test_d46_troca_de_tipo_reavalia_situacao_na_hora`) não tem histórico
    # algum, então `.exists()` devolve `False` e a guarda não interfere.
    if processo.situacao_manual:
        return None

    alvo = situacao_por_eventos(
        tipo_nome_normalizado=processo.tipo.nome_normalizado,
        data_assinatura_contrato=processo.data_assinatura_contrato,
        data_recebimento_gelic=processo.data_recebimento_gelic,
        exigencia=exigencia,
        ano_exercicio=processo.exercicio.ano,
    )
    if alvo is None and processo.situacao == Situacao.EM_TRAMITACAO:
        # 29/09/2026 (decisão do usuário) — em tramitação sem recebimento no Gelic no ano do PCA
        # (data apagada ou de ano anterior) volta para NO PRAZO; a leitura mostra Atrasado se o
        # prazo já passou. Transição manual já saiu acima (guarda).
        return registrar_acompanhamento(
            processo_id=processo.pk,
            usuario=usuario,
            versao_cliente=processo.atualizado_em.isoformat(),
            situacao_novo=Situacao.NO_PRAZO,
            observacao=(
                "Situação atualizada automaticamente para No prazo — sem recebimento no Gelic em "
                f"{processo.exercicio.ano}: o processo não tramitou no Gelic no ano do PCA."
            ),
            tipo_evento=TipoEvento.AUTOMATICO,
            reuniao=None,
            usar_reuniao_corrente=False,
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
        # `situacao_por_eventos` pode devolver além de `concluido`/`None`.
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
    if exercicio.situacao == SituacaoExercicio.FECHADO:
        raise ExercicioFechado(exercicio=exercicio)
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

    A linha singleton do alocador é bloqueada antes de consultar o maior item,
    inclusive quando a tabela de processos está vazia. O usuário é definido
    antes do primeiro save para que a linha de auditoria de criação tenha
    autoria, assim como as alterações posteriores.

    Fase 17 (17-14): a situação inicial é derivada por
    `situacao_por_eventos` no mesmo instante da criação, não um literal fixo
    — um item novo com `Tipo=Vigente` já nasce `Situacao.CONCLUIDO`,
    não `NO_PRAZO`. Um item novo nunca tem `data_assinatura_contrato`/
    `data_recebimento_gelic` preenchidas, então na prática só o eixo Tipo
    pode disparar algo além do fallback; para qualquer outro Tipo,
    `situacao_por_eventos` devolve `None` e o fallback `Situacao.NO_PRAZO`
    ("sem prazo ⇒ NO PRAZO por padrão") se aplica.
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


# Excluir acompanhamento pela ficha, com confirmação que
# anuncia o efeito real no estado derivado. `_CAMPOS_EFEITO_EXCLUSAO` é a
# lista EXATA anotada por `ProcessoQuerySet.para_listagem()` (conferida
# linha a linha em `querysets.py` antes de escrever esta lista — nunca
# reimplementar a regra de derivação aqui, só medir o antes/depois dela).
_CAMPOS_EFEITO_EXCLUSAO = [
    ("situacao_efetiva", "Situação efetiva"),
    ("situacao_atual", "Situação atual (último acompanhamento)"),
    ("prazo_vigente", "Prazo vigente"),
    ("prazo_efetivo", "Prazo efetivo"),
    ("atrasado", "Atrasado"),
    ("dias_atraso", "Dias em atraso"),
    ("n_prorrogacoes", "Prorrogações"),
    ("reprometido", "Reprometido"),
    ("qualificador_prazo", "Qualificador do prazo"),
    ("publicacao_pendente", "Publicação pendente"),
    ("n_reunioes", "Nº de reuniões"),
    ("n_compromissos", "Nº de compromissos"),
    ("n_prazos_distintos", "Nº de prazos distintos"),
    ("sobreposicao_manual_ativa", "Sobreposição manual ativa"),
]


def efeito_da_exclusao(acompanhamento) -> dict:
    """Mede o efeito REAL de apagar `acompanhamento` nos campos derivados
    do processo (`Processo.objects.para_listagem()`), sem deixar NENHUMA
    escrita persistida: lê o ANTES, apaga a linha, lê o DEPOIS, tudo
    dentro de `transaction.atomic()` — o bloco sempre termina com
    `transaction.set_rollback(True)` (inclusive quando a leitura do
    DEPOIS levanta exceção, via `finally`), nunca reimplementando a regra
    de derivação. Devolve `{"mudancas": [...], "nada_muda": bool}`."""
    processo_id = acompanhamento.processo_id
    pk = acompanhamento.pk
    campos = [campo for campo, _ in _CAMPOS_EFEITO_EXCLUSAO]

    with transaction.atomic():
        try:
            antes = Processo.objects.para_listagem().filter(pk=processo_id).values(
                *campos
            )[0]
            Acompanhamento.objects.filter(pk=pk).delete()
            depois = Processo.objects.para_listagem().filter(pk=processo_id).values(
                *campos
            )[0]
        finally:
            transaction.set_rollback(True)

    mudancas = [
        {"campo": campo, "rotulo": rotulo, "antes": antes[campo], "depois": depois[campo]}
        for campo, rotulo in _CAMPOS_EFEITO_EXCLUSAO
        if antes[campo] != depois[campo]
    ]
    return {"mudancas": mudancas, "nada_muda": not mudancas}


@transaction.atomic
def excluir_acompanhamento(*, acompanhamento_id, usuario) -> dict:
    """Exclusão real de UMA linha de `Acompanhamento` — nunca em lote.
    Marca `_history_user` ANTES do `delete()` para a exclusão entrar na
    trilha `simple_history` com autor (`history_type="-"`, mesmo contrato
    que o Admin já garante, `test_admin_auditoria.py`). Devolve um resumo
    textual (data + texto) para a mensagem de sucesso da view."""
    acompanhamento = Acompanhamento.objects.select_related("processo__exercicio").get(
        pk=acompanhamento_id
    )
    processo = acompanhamento.processo
    if processo.exercicio.situacao == SituacaoExercicio.FECHADO:
        raise ExercicioFechado(processo)
    texto = (acompanhamento.situacao_informada or acompanhamento.evento or "").strip()
    data_fmt = acompanhamento.referencia_data.strftime("%d/%m/%Y")
    resumo = f"{data_fmt} — {texto}" if texto else data_fmt

    acompanhamento._history_user = usuario
    acompanhamento.delete()

    return {"resumo": resumo, "processo": processo}
