"""Serviços de domínio das Solicitações das unidades (Fase 43).

Tudo transacional e sempre pelos serviços de `apps.pca.services` — esta camada nunca
reescreve regra de situação, prazo ou estado do item. A decisão de cada parte (`decidir_parte`)
aplica o efeito na hora; o item encerrado por outro caminho encerra as partes
pendentes pelo gancho único `prejudicar_pendentes_do_processo` (ligado em
`signals.py`). Erros de negócio são `ErroSolicitacao` (a mensagem é para o usuário).
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Max
from django.utils.timezone import localdate, now

from apps.catalogo.models import Categoria, Exercicio, SituacaoExercicio, Tipo, Unidade
from apps.pca import services as servicos_pca
from apps.pca.models import Estado, Processo

from . import regras
from .models import ParteSolicitacao, Solicitacao, VinculoUnidade
from .regras import Alcada, Campo, EstadoParte, EstadoSolicitacao, TipoSolicitacao

PERM_SOLICITAR = "solicitacoes.solicitar"
PERM_DECIDIR_EQUIPE = "solicitacoes.decidir_equipe"
PERM_DECIDIR_DIRETORIA = "solicitacoes.decidir_diretoria"


class ErroSolicitacao(Exception):
    """Base dos erros de negócio; `str(erro)` é a mensagem para o usuário."""


class SemPermissao(ErroSolicitacao):
    pass


class PedidoInvalido(ErroSolicitacao):
    pass


class ItemNaoAceitaPedido(ErroSolicitacao):
    pass


class PedidoConflitante(ErroSolicitacao):
    pass


class DecisaoInvalida(ErroSolicitacao):
    pass


class JaEncerrada(ErroSolicitacao):
    """A parte já foi decidida ou a solicitação já está encerrada."""


# --- Perfis e visibilidade --------------------------------------------


def alcadas_do_usuario(usuario) -> set:
    """Alçadas em que o usuário decide (superusuário decide as duas)."""
    alcadas = set()
    if usuario.has_perm(PERM_DECIDIR_EQUIPE):
        alcadas.add(Alcada.EQUIPE)
    if usuario.has_perm(PERM_DECIDIR_DIRETORIA):
        alcadas.add(Alcada.DIRETORIA)
    return alcadas


def unidades_do_usuario(usuario):
    return Unidade.objects.filter(vinculos_usuario__usuario=usuario)


def solicitacoes_visiveis(usuario):
    """Toda a unidade vê as solicitações da unidade; equipe e diretoria veem todas."""
    solicitacoes = Solicitacao.objects.all()
    if alcadas_do_usuario(usuario):
        return solicitacoes
    return solicitacoes.filter(unidade__in=unidades_do_usuario(usuario))


def _exigir_solicitante(usuario, unidade_id):
    if not usuario.has_perm(PERM_SOLICITAR):
        raise SemPermissao("Você não tem permissão para fazer solicitações.")
    if not VinculoUnidade.objects.filter(usuario=usuario, unidade_id=unidade_id).exists():
        raise SemPermissao("Você só pode solicitar para as unidades a que está vinculado.")


def _nome(usuario) -> str:
    return usuario.get_full_name() or usuario.email


# --- Pedido ------------------------------------------------------------------------------


def _exigir_justificativa(justificativa) -> str:
    justificativa = (justificativa or "").strip()
    if not justificativa:
        raise PedidoInvalido("Informe a justificativa do pedido.")
    return justificativa


def _proximo_numero(ano: int) -> int:
    # A gravação roda em transação IMMEDIATE (config/settings/base.py): uma por vez; a
    # restrição única (ano, numero) é a rede de segurança.
    return (Solicitacao.objects.filter(ano=ano).aggregate(m=Max("numero"))["m"] or 0) + 1


def _gravar(objeto, usuario, motivo=None):
    objeto._history_user = usuario
    if motivo:
        objeto._change_reason = motivo[:100]
    objeto.save()
    return objeto


def _item_com_leitura(processo_id):
    """O item travado, com as anotações de leitura (`situacao_efetiva`, `prazo_efetivo`)."""
    Processo.objects.select_for_update().get(pk=processo_id)
    return Processo.objects.para_listagem().select_related("tipo").get(pk=processo_id)


def _exercicio_aberto(exercicio) -> bool:
    return exercicio.situacao == SituacaoExercicio.ABERTO


def _valor_atual(item, campo):
    return {
        Campo.PRAZO_ENTREGA: item.prazo_efetivo,
        Campo.MES_PREVISTO: item.mes_previsto,
        Campo.VALOR_ESTIMADO: item.valor_estimado,
        Campo.DESCRICAO_OBJETO: item.descricao_objeto,
    }.get(campo)


def _campos_do_item(item) -> tuple:
    return regras.campos_aceitos(
        estado=item.estado,
        situacao_efetiva=item.situacao_efetiva,
        exercicio_aberto=_exercicio_aberto(item.exercicio),
    )


def campos_aceitos_do_item(item) -> tuple:
    """Campos que o item aceita pedir hoje — para as telas. `item` vem de
    `Processo.objects.para_listagem()` (precisa de `situacao_efetiva` e do exercício)."""
    return _campos_do_item(item)


def _exigir_campo_aceito(item, campo):
    if campo not in _campos_do_item(item):
        motivo = regras.motivo_do_item_fechado(
            estado=item.estado,
            situacao_efetiva=item.situacao_efetiva,
            exercicio_aberto=_exercicio_aberto(item.exercicio),
        )
        raise ItemNaoAceitaPedido(f"{regras.rotulo_do_campo(campo)}: {motivo}")


@transaction.atomic
def criar_solicitacao(*, usuario, processo_id, justificativa, pedidos, numero_sei=""):
    """Cria a solicitação de um item. `pedidos` é `{campo: valor}` — o valor
    pedido em forma bruta (data, texto, número) ou `None` no cancelamento. Cada campo vira
    uma parte, decidida pela sua alçada."""
    justificativa = _exigir_justificativa(justificativa)
    pedidos = {Campo(campo): valor for campo, valor in pedidos.items()}
    try:
        regras.validar_pedido(pedidos)
    except ValueError as erro:
        raise PedidoInvalido(str(erro)) from erro

    item = _item_com_leitura(processo_id)
    _exigir_solicitante(usuario, item.unidade_organizacional_id)

    valores = {}
    for campo, bruto in pedidos.items():
        _exigir_campo_aceito(item, campo)
        if campo == Campo.CANCELAMENTO:
            valores[campo] = ""
            continue
        try:
            novo = regras.normalizar_valor(campo, bruto)
        except ValueError as erro:
            raise PedidoInvalido(f"{regras.rotulo_do_campo(campo)}: {erro}") from erro
        if regras.para_texto(campo, novo) == regras.para_texto(campo, _valor_atual(item, campo)):
            raise PedidoInvalido(f"{regras.rotulo_do_campo(campo)}: o valor pedido é igual ao atual.")
        valores[campo] = novo

    pendentes = set(
        ParteSolicitacao.objects.filter(processo=item, estado=EstadoParte.PENDENTE).values_list(
            "campo", flat=True
        )
    )
    if Campo.CANCELAMENTO in pendentes:
        raise PedidoConflitante(
            "Há um pedido de cancelamento em análise neste item; aguarde a decisão."
        )
    repetidos = [regras.rotulo_do_campo(campo) for campo in valores if campo in pendentes]
    if repetidos:
        raise PedidoConflitante(f"Já há pedido em análise para: {', '.join(repetidos)}.")

    ano = localdate().year
    solicitacao = _gravar(
        Solicitacao(
            numero=_proximo_numero(ano),
            ano=ano,
            exercicio=item.exercicio,
            processo=item,
            unidade=item.unidade_organizacional,
            solicitante=usuario,
            tipo=regras.tipo_do_pedido(valores),
            justificativa=justificativa,
            numero_sei=(numero_sei or "").strip(),
        ),
        usuario,
    )
    for campo, novo in valores.items():
        _gravar(
            ParteSolicitacao(
                solicitacao=solicitacao,
                processo=item,
                campo=campo,
                alcada=regras.alcada_do_campo(campo),
                valor_atual=regras.para_texto(campo, _valor_atual(item, campo)),
                valor_pedido=regras.para_texto(campo, novo) if campo != Campo.CANCELAMENTO else "",
                fora_do_exercicio=(
                    campo == Campo.PRAZO_ENTREGA
                    and regras.fora_do_exercicio(novo, item.exercicio.ano)
                ),
            ),
            usuario,
        )
    return solicitacao


@transaction.atomic
def criar_inclusao(
    *,
    usuario,
    unidade_id,
    descricao_objeto,
    tipo_id,
    categoria_id,
    valor_estimado,
    mes_previsto,
    justificativa,
    prazo_entrega=None,
    numero_sei="",
    exercicio=None,
):
    """Pedido de inclusão de item novo: sem item até a aprovação, que cria o
    item com o próximo número do PCA. A unidade é uma das do solicitante."""
    justificativa = _exigir_justificativa(justificativa)
    _exigir_solicitante(usuario, unidade_id)
    exercicio = exercicio or (
        Exercicio.objects.filter(situacao=SituacaoExercicio.ABERTO).order_by("-ano").first()
    )
    if exercicio is None or not _exercicio_aberto(exercicio):
        raise ItemNaoAceitaPedido("Não há exercício aberto para incluir itens.")
    try:
        tipo = Tipo.objects.get(pk=tipo_id)
        categoria = Categoria.objects.get(pk=categoria_id)
    except (Tipo.DoesNotExist, Categoria.DoesNotExist):
        raise PedidoInvalido("Escolha o tipo e a categoria.") from None
    if tipo.nome_normalizado not in regras.TIPOS_DE_INCLUSAO:
        raise PedidoInvalido("O tipo da inclusão é Nova Contratação ou Renovação.")
    try:
        objeto = regras.normalizar_valor(Campo.DESCRICAO_OBJETO, descricao_objeto)
        valor = regras.normalizar_valor(Campo.VALOR_ESTIMADO, valor_estimado)
        mes = regras.normalizar_valor(Campo.MES_PREVISTO, mes_previsto)
        prazo = (
            regras.normalizar_valor(Campo.PRAZO_ENTREGA, prazo_entrega)
            if prazo_entrega not in (None, "")
            else None
        )
    except ValueError as erro:
        raise PedidoInvalido(str(erro)) from erro

    ano = localdate().year
    solicitacao = _gravar(
        Solicitacao(
            numero=_proximo_numero(ano),
            ano=ano,
            exercicio=exercicio,
            processo=None,
            unidade_id=unidade_id,
            solicitante=usuario,
            tipo=TipoSolicitacao.INCLUSAO,
            justificativa=justificativa,
            numero_sei=(numero_sei or "").strip(),
            dados_inclusao={
                "descricao_objeto": objeto,
                "tipo_id": tipo.pk,
                "tipo": tipo.nome,
                "categoria_id": categoria.pk,
                "categoria": categoria.nome,
                "valor_estimado": regras.para_texto(Campo.VALOR_ESTIMADO, valor),
                "mes_previsto": mes,
                "prazo_entrega": regras.para_texto(Campo.PRAZO_ENTREGA, prazo),
            },
        ),
        usuario,
    )
    _gravar(
        ParteSolicitacao(
            solicitacao=solicitacao,
            campo=Campo.INCLUSAO,
            alcada=regras.alcada_do_campo(Campo.INCLUSAO),
            valor_pedido=objeto,
        ),
        usuario,
    )
    return solicitacao


@transaction.atomic
def desistir(*, solicitacao_id, usuario):
    """Sem edição: a unidade desiste (fica registrado) e pede de novo. Encerra as
    partes ainda pendentes; as já decididas ficam como estão."""
    solicitacao = Solicitacao.objects.select_for_update().get(pk=solicitacao_id)
    if solicitacao.estado != EstadoSolicitacao.PENDENTE:
        raise JaEncerrada("Esta solicitação já foi encerrada.")
    if not usuario.is_superuser:
        _exigir_solicitante(usuario, solicitacao.unidade_id)
    momento = now()
    for parte in solicitacao.partes.filter(estado=EstadoParte.PENDENTE):
        parte.estado = EstadoParte.DESISTIDA
        parte.decidido_por = usuario
        parte.decidido_em = momento
        _gravar(parte, usuario)
    _fechar_se_completa(solicitacao, usuario)
    return solicitacao


# --- Decisão -----------------------------------------------------------------------------


@transaction.atomic
def decidir_parte(*, parte_id, usuario, decisao, valor_ajuste=None, motivo=""):
    """Decide UMA parte: confere a alçada, aplica o efeito na hora e
    fecha a solicitação quando nenhuma parte ficou pendente. A parte é gravada ANTES do
    efeito, para o gancho de "prejudicada" não a confundir com uma pendente."""
    parte = ParteSolicitacao.objects.select_for_update().get(pk=parte_id)
    solicitacao = Solicitacao.objects.select_for_update().select_related("unidade").get(
        pk=parte.solicitacao_id
    )
    if parte.estado != EstadoParte.PENDENTE:
        raise JaEncerrada("Esta parte já foi decidida.")
    alcadas = alcadas_do_usuario(usuario)
    if not regras.pode_decidir(
        parte.alcada, equipe=Alcada.EQUIPE in alcadas, diretoria=Alcada.DIRETORIA in alcadas
    ):
        raise SemPermissao(
            f"Este pedido é decidido pela alçada: {Alcada(parte.alcada).label}."
        )
    campo = Campo(parte.campo)
    try:
        estado, concedido, motivo = regras.validar_decisao(
            campo,
            decisao,
            motivo=motivo,
            valor_ajuste=valor_ajuste,
            valor_pedido=regras.de_texto(campo, parte.valor_pedido) if parte.valor_pedido else None,
        )
    except ValueError as erro:
        raise DecisaoInvalida(str(erro)) from erro

    aprovada = estado != EstadoParte.RECUSADA
    if aprovada:
        _exigir_que_ainda_cabe(parte, solicitacao)

    parte.estado = estado
    parte.motivo = motivo
    parte.decidido_por = usuario
    parte.decidido_em = now()
    parte.valor_concedido = (
        regras.para_texto(campo, concedido)
        if aprovada and campo not in (Campo.CANCELAMENTO, Campo.INCLUSAO)
        else ""
    )
    _gravar(parte, usuario, f"Solicitação {solicitacao.codigo}: {EstadoParte(estado).label}")

    if aprovada:
        _aplicar_efeito(parte, solicitacao, usuario, motivo)
    _fechar_se_completa(solicitacao, usuario)
    return parte


def _exigir_que_ainda_cabe(parte, solicitacao):
    """Aprovar só vale se o item ainda aceita o campo (recusar vale sempre)."""
    if parte.campo == Campo.INCLUSAO:
        if not _exercicio_aberto(solicitacao.exercicio):
            raise ItemNaoAceitaPedido("O exercício da inclusão está fechado.")
        return
    _exigir_campo_aceito(_item_com_leitura(parte.processo_id), Campo(parte.campo))


def _aplicar_efeito(parte, solicitacao, usuario, motivo_decisao):
    """O aprovado vale na hora, pelos serviços do `apps.pca`."""
    campo = Campo(parte.campo)
    origem = f"solicitação {solicitacao.codigo} da unidade {solicitacao.unidade}"
    por = f"aprovada por {_nome(usuario)}"
    ajuste = f" (com ajuste: {motivo_decisao})" if parte.estado == EstadoParte.APROVADA_AJUSTE else ""

    if campo == Campo.INCLUSAO:
        _incluir_item(parte, solicitacao, usuario, origem)
        return

    item = Processo.objects.select_for_update().select_related("exercicio").get(pk=parte.processo_id)
    if campo == Campo.PRAZO_ENTREGA:
        # Conta prorrogação/sobrestado e aparece como repactuado: é uma promessa de prazo
        # como qualquer outra, só que pedida pela unidade.
        servicos_pca.registrar_acompanhamento(
            processo_id=item.pk,
            usuario=usuario,
            versao_cliente=item.atualizado_em.isoformat(),
            prazo_prometido=regras.de_texto(campo, parte.valor_concedido),
            observacao=f"Prazo alterado por {origem}, {por}{ajuste}.",
            justificativa=solicitacao.justificativa,
        )
    elif campo == Campo.CANCELAMENTO:
        servicos_pca.alterar_estado(
            processo_id=item.pk,
            usuario=usuario,
            estado_novo=Estado.CANCELADO,
            observacao=f"Cancelado por {origem}, {por}. Motivo: {solicitacao.justificativa}",
        )
    else:
        campo_do_modelo = {
            Campo.MES_PREVISTO: "mes_previsto",
            Campo.VALOR_ESTIMADO: "valor_estimado",
            Campo.DESCRICAO_OBJETO: "descricao_objeto",
        }[campo]
        setattr(item, campo_do_modelo, regras.de_texto(campo, parte.valor_concedido))
        item._history_user = usuario
        item._change_reason = f"Solicitação {solicitacao.codigo}: {EstadoParte(parte.estado).label.lower()}"[:100]
        item.save(update_fields=[campo_do_modelo, "atualizado_em"])


def _incluir_item(parte, solicitacao, usuario, origem):
    dados = solicitacao.dados_inclusao or {}
    item = servicos_pca.criar_processo(
        usuario=usuario,
        descricao_objeto=dados["descricao_objeto"],
        tipo_id=dados["tipo_id"],
        categoria_id=dados["categoria_id"],
        unidade_organizacional_id=solicitacao.unidade_id,
        exercicio=solicitacao.exercicio,
    )
    item.valor_estimado = regras.de_texto(Campo.VALOR_ESTIMADO, dados["valor_estimado"])
    item.mes_previsto = dados["mes_previsto"]
    item.prazo_entrega = regras.de_texto(Campo.PRAZO_ENTREGA, dados.get("prazo_entrega") or "")
    item.justificativa = solicitacao.justificativa
    item._history_user = usuario
    item._change_reason = f"Inclusão pela solicitação {solicitacao.codigo}"[:100]
    item.save(
        update_fields=["valor_estimado", "mes_previsto", "prazo_entrega", "justificativa", "atualizado_em"]
    )
    # O nº SEI da solicitação é informação do pedido, não vínculo do item: quem o vincula
    # ao item é a equipe (a coleta do robô passa a tocar o item assim que há número).
    solicitacao.processo = item
    _gravar(solicitacao, usuario)
    parte.processo = item
    _gravar(parte, usuario)


def _fechar_se_completa(solicitacao, usuario):
    """A solicitação fecha quando nenhuma parte está pendente (idempotente)."""
    solicitacao.refresh_from_db()
    novo = regras.estado_da_solicitacao(solicitacao.partes.values_list("estado", flat=True))
    if novo == EstadoSolicitacao.PENDENTE or solicitacao.estado == novo:
        return
    solicitacao.estado = novo
    solicitacao.encerrada_em = now()
    _gravar(solicitacao, usuario)


@transaction.atomic
def prejudicar_pendentes_do_processo(processo_id, *, usuario=None, motivo="Item encerrado."):
    """GANCHO ÚNICO de o item foi cancelado ou concluído (por equipe, Admin ou
    robô SEI) — as partes pendentes encerram como "prejudicada", sem decisão. Chamado só
    por `signals.item_encerrado` (post_save de `Processo`), que cobre todos os caminhos
    de escrita; devolve quantas partes encerrou."""
    partes = list(
        ParteSolicitacao.objects.select_for_update()
        .filter(processo_id=processo_id, estado=EstadoParte.PENDENTE)
        .select_related("solicitacao")
    )
    momento = now()
    for parte in partes:
        parte.estado = EstadoParte.PREJUDICADA
        parte.motivo = motivo
        parte.decidido_em = momento
        _gravar(parte, usuario)
    for solicitacao in {parte.solicitacao_id: parte.solicitacao for parte in partes}.values():
        _fechar_se_completa(solicitacao, usuario)
    return len(partes)


# --- Fila de avaliação ---------------------------------------------------------


def partes_para_avaliar(usuario):
    """Partes pendentes da alçada de quem está logado, da mais antiga para a mais nova.
    Quem não decide em nenhuma alçada recebe um queryset vazio."""
    alcadas = alcadas_do_usuario(usuario)
    return (
        ParteSolicitacao.objects.filter(estado=EstadoParte.PENDENTE, alcada__in=alcadas)
        .select_related(
            "solicitacao__unidade", "solicitacao__solicitante", "solicitacao__processo", "processo"
        )
        .order_by("solicitacao__criada_em", "id")
    )


def contar_pendentes(usuario) -> int:
    return partes_para_avaliar(usuario).count()
