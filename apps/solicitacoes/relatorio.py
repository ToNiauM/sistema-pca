"""Seção "Solicitações das unidades" do Relatório da reunião.

Dados prontos para o documento ABNT (`apps.pca.relatorio_reuniao` só compõe o texto corrido e o
template só desenha): as partes DECIDIDAS no período (aprovadas, aprovadas com ajuste, recusadas) e as
que seguem EM ANÁLISE na data de emissão, uma linha por parte, com item, unidade, pedido e decisão.
Prejudicadas e desistidas não são decisão — ficam de fora. Uma consulta por lista, sem consulta por linha.
"""

from __future__ import annotations

from django.utils.timezone import localtime

from .apresentacao import nome_do_usuario, texto_do_valor
from .models import ParteSolicitacao
from .regras import Alcada, Campo, EstadoParte

ESTADOS_DECIDIDOS = (EstadoParte.APROVADA, EstadoParte.APROVADA_AJUSTE, EstadoParte.RECUSADA)
LIMITE_JUSTIFICATIVA = 200

_SELECT = (
    "solicitacao__unidade", "solicitacao__processo", "solicitacao__exercicio",
    "solicitacao__solicitante", "decidido_por",
)


def _data(valor) -> str:
    return localtime(valor).strftime("%d/%m/%Y")


def _resumida(texto: str, limite: int = LIMITE_JUSTIFICATIVA) -> str:
    texto = " ".join((texto or "").split())
    return texto if len(texto) <= limite else texto[: limite - 1].rstrip() + "…"


def _pedido(parte) -> dict:
    solicitacao = parte.solicitacao
    campo = Campo(parte.campo)
    if campo == Campo.CANCELAMENTO:
        texto = "cancelar o item"
    elif campo == Campo.INCLUSAO:
        dados = solicitacao.dados_inclusao or {}
        texto = _resumida(dados.get("descricao_objeto", "—"), 160)
        valor = dados.get("valor_estimado")
        if valor:
            texto += f" ({texto_do_valor(Campo.VALOR_ESTIMADO, valor)})"
    else:
        texto = f"{texto_do_valor(campo, parte.valor_atual)} → {texto_do_valor(campo, parte.valor_pedido)}"
    detalhe = f"Solicitação {solicitacao.codigo}, de {_data(solicitacao.criada_em)}"
    if solicitacao.justificativa:
        detalhe += f" – Justificativa: {_resumida(solicitacao.justificativa)}"
    return {"campo": campo.label, "texto": texto, "detalhe": detalhe}


def _decisao(parte) -> dict:
    estado = EstadoParte(parte.estado)
    if estado == EstadoParte.PENDENTE:
        detalhe = f"Aguardando {Alcada(parte.alcada).label.lower()} desde {_data(parte.solicitacao.criada_em)}"
        if parte.fora_do_exercicio:
            detalhe += "; prazo fora do exercício"
        return {"rotulo": estado.label, "texto": "", "detalhe": detalhe}
    texto = ""
    if estado == EstadoParte.APROVADA_AJUSTE and parte.valor_concedido:
        texto = f"concedido {texto_do_valor(parte.campo, parte.valor_concedido)}."
    if parte.motivo:
        texto = f"{texto} {_resumida(parte.motivo)}".strip()
    detalhe = f"{nome_do_usuario(parte.decidido_por)}, em {_data(parte.decidido_em)}"
    if parte.fora_do_exercicio:
        detalhe += "; prazo fora do exercício"
    return {"rotulo": estado.label, "texto": texto, "detalhe": detalhe}


def _linha(parte) -> dict:
    solicitacao = parte.solicitacao
    return {
        "item": solicitacao.processo.item_pca if solicitacao.processo_id else "Novo",
        "uo": solicitacao.unidade.nome,
        "pedido": _pedido(parte),
        "decisao": _decisao(parte),
    }


def montar_bloco(*, exercicio, inicio, fim) -> dict:
    """`inicio`/`fim` = limites do período (datetimes com fuso, como `_limites_do_dia`)."""
    decididas = list(
        ParteSolicitacao.objects.filter(
            solicitacao__exercicio=exercicio, estado__in=ESTADOS_DECIDIDOS,
            decidido_em__gte=inicio, decidido_em__lte=fim,
        )
        .select_related(*_SELECT)
        .order_by("decidido_em", "id")
    )
    pendentes = list(
        ParteSolicitacao.objects.filter(
            solicitacao__exercicio=exercicio, estado=EstadoParte.PENDENTE, solicitacao__criada_em__lte=fim,
        )
        .select_related(*_SELECT)
        .order_by("solicitacao__criada_em", "id")
    )
    contagem = {estado: 0 for estado in ESTADOS_DECIDIDOS}
    for parte in decididas:
        contagem[EstadoParte(parte.estado)] += 1
    grupos = []
    if decididas:
        grupos.append({"titulo": "Decididas no período", "linhas": [_linha(p) for p in decididas]})
    if pendentes:
        grupos.append({"titulo": "Em análise", "linhas": [_linha(p) for p in pendentes]})
    return {
        "grupos": grupos,
        "decididas": len(decididas),
        "aprovadas": contagem[EstadoParte.APROVADA],
        "ajustadas": contagem[EstadoParte.APROVADA_AJUSTE],
        "recusadas": contagem[EstadoParte.RECUSADA],
        "pendentes": len(pendentes),
    }

