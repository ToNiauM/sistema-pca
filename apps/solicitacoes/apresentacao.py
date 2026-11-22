"""Textos e modelos de tela das Solicitações (Fase 43).

Tudo o que as duas cascas (DSGov e Tabler) mostram igual mora aqui, em Python: valores em linguagem
de gente, tags de estado, a trilha de cada solicitação e as linhas da fila "Para avaliar". Os
templates só desenham. Nada aqui grava no banco nem consulta por linha: as listas chegam com
`select_related`/`prefetch_related` das views.
"""

from __future__ import annotations

from django.urls import reverse
from django.utils.timezone import localdate, localtime

from apps.pca.filtros import NOMES_MES
from apps.pca.models import Estado, Situacao
from core.templatetags.formatos import moeda

from . import regras
from .regras import Alcada, Campo, EstadoParte, EstadoSolicitacao, TipoSolicitacao

# Chave semântica do `tag_status` (a mesma nas duas cascas).
CHAVE_DO_ESTADO_DA_PARTE = {
    EstadoParte.PENDENTE: "alerta",
    EstadoParte.APROVADA: "sucesso",
    EstadoParte.APROVADA_AJUSTE: "info",
    EstadoParte.RECUSADA: "erro",
    EstadoParte.PREJUDICADA: "neutro",
    EstadoParte.DESISTIDA: "neutro",
}
CHAVE_DO_ESTADO_DA_SOLICITACAO = {
    EstadoSolicitacao.PENDENTE: "alerta",
    EstadoSolicitacao.CONCLUIDA: "sucesso",
    EstadoSolicitacao.DESISTIDA: "neutro",
}
_CHAVE_DA_SITUACAO = {
    Situacao.NO_PRAZO: "alerta",
    Situacao.ATRASADO: "erro",
    Situacao.EM_TRAMITACAO: "info",
    Situacao.CONCLUIDO: "sucesso",
}


def nome_do_usuario(usuario) -> str:
    if usuario is None:
        return "Sistema"
    return usuario.get_full_name() or usuario.email


def texto_do_valor(campo, texto) -> str:
    """Valor guardado (texto estável de `regras.para_texto`) em linguagem de gente."""
    if texto in (None, ""):
        return "—"
    campo = Campo(campo)
    if campo == Campo.PRAZO_ENTREGA:
        return regras.de_texto(campo, texto).strftime("%d/%m/%Y")
    if campo == Campo.MES_PREVISTO:
        return NOMES_MES.get(int(texto), str(texto))
    if campo == Campo.VALOR_ESTIMADO:
        return f"R$ {moeda(regras.de_texto(campo, texto))}"
    return str(texto)


def data_hora(valor) -> str:
    return localtime(valor).strftime("%d/%m/%Y %H:%M") if valor else "—"


def rotulo_do_item(solicitacao) -> str:
    if solicitacao.processo_id:
        return f"Item {solicitacao.processo.item_pca}/{solicitacao.exercicio.ano}"
    return "Item novo"


def url_do_item(solicitacao) -> str | None:
    if solicitacao.processo_id:
        return reverse(
            "pca:detalhe_processo", args=[solicitacao.exercicio.ano, solicitacao.processo.item_pca]
        )
    return None


def url_da_solicitacao(solicitacao) -> str:
    return reverse("solicitacoes:detalhe", args=[solicitacao.ano, solicitacao.numero])


def resumo_do_item(item) -> dict:
    """O item como a tela "Nova solicitação" o mostra (o queryset vem de `para_listagem()`)."""
    if item.estado == Estado.CANCELADO:
        situacao, chave = "Cancelado", "cancelado"
    else:
        situacao = Situacao(item.situacao_efetiva).label
        chave = _CHAVE_DA_SITUACAO.get(item.situacao_efetiva, "info")
    return {
        "rotulo": f"Item {item.item_pca}/{item.exercicio.ano}",
        "objeto": item.descricao_objeto,
        "unidade": item.unidade_organizacional.nome,
        "situacao": situacao,
        "chave": chave,
        "prazo": texto_do_valor(Campo.PRAZO_ENTREGA, regras.para_texto(Campo.PRAZO_ENTREGA, item.prazo_efetivo)),
        "mes": texto_do_valor(Campo.MES_PREVISTO, item.mes_previsto),
        "valor": texto_do_valor(Campo.VALOR_ESTIMADO, regras.para_texto(Campo.VALOR_ESTIMADO, item.valor_estimado)),
        "url": reverse("pca:detalhe_processo", args=[item.exercicio.ano, item.item_pca]),
    }


def valor_atual_do_item(item, campo):
    return {
        Campo.PRAZO_ENTREGA: item.prazo_efetivo,
        Campo.MES_PREVISTO: item.mes_previsto,
        Campo.VALOR_ESTIMADO: item.valor_estimado,
        Campo.DESCRICAO_OBJETO: item.descricao_objeto,
    }.get(campo)


def linhas_do_pedido(item, campos_aceitos, form) -> list[dict]:
    """Uma linha por campo que o item aceita pedir: valor de hoje, o campo do pedido e quem decide."""
    linhas = []
    for campo in campos_aceitos:
        if campo == Campo.CANCELAMENTO or campo.value not in form.fields:
            continue
        linhas.append(
            {
                "rotulo": campo.label,
                "hoje": texto_do_valor(campo, regras.para_texto(campo, valor_atual_do_item(item, campo))),
                "campo": form[campo.value],
                "decide": Alcada(regras.alcada_do_campo(campo)).label,
            }
        )
    return linhas


def avisos_de_alcada(campos_aceitos) -> list[str]:
    """"Para quem vai cada parte" — só as alçadas dos campos que a tela oferece."""
    campos = [c for c in campos_aceitos]
    equipe = [c.label.lower() for c in campos if regras.alcada_do_campo(c) == Alcada.EQUIPE]
    diretoria = [c.label.lower() for c in campos if regras.alcada_do_campo(c) == Alcada.DIRETORIA]
    avisos = []
    if equipe:
        avisos.append(f"{', '.join(equipe).capitalize()}: decide a equipe do PCA.")
    if diretoria:
        avisos.append(f"{', '.join(diretoria).capitalize()}: decide a diretoria.")
    return avisos


def linhas_da_inclusao(solicitacao) -> list[tuple[str, str]]:
    dados = solicitacao.dados_inclusao or {}
    linhas = [
        ("Objeto", dados.get("descricao_objeto", "—")),
        ("Tipo", dados.get("tipo", "—")),
        ("Categoria", dados.get("categoria", "—")),
        ("Valor estimado", texto_do_valor(Campo.VALOR_ESTIMADO, dados.get("valor_estimado"))),
        ("Mês previsto", texto_do_valor(Campo.MES_PREVISTO, dados.get("mes_previsto"))),
        ("Prazo de entrega", texto_do_valor(Campo.PRAZO_ENTREGA, dados.get("prazo_entrega"))),
    ]
    return linhas


def parte_para_tela(parte, alcadas) -> dict:
    """Uma parte em dicionário de tela. `alcadas` = as alçadas em que quem olha decide."""
    campo = Campo(parte.campo)
    estado = EstadoParte(parte.estado)
    pendente = estado == EstadoParte.PENDENTE
    pode_decidir = pendente and regras.pode_decidir(
        parte.alcada, equipe=Alcada.EQUIPE in alcadas, diretoria=Alcada.DIRETORIA in alcadas
    )
    inclusao = campo == Campo.INCLUSAO
    cancelamento = campo == Campo.CANCELAMENTO
    return {
        "id": parte.pk,
        "obj": parte,
        "campo": campo.value,
        "rotulo": campo.label,
        "alcada": Alcada(parte.alcada).label,
        "estado": estado.value,
        "estado_rotulo": estado.label,
        "chave": CHAVE_DO_ESTADO_DA_PARTE[estado],
        "pendente": pendente,
        "pode_decidir": pode_decidir,
        "aguardando": f"Aguardando {Alcada(parte.alcada).label.lower()}" if pendente and not pode_decidir else "",
        "hoje": "—" if inclusao else ("Item ativo" if cancelamento else texto_do_valor(campo, parte.valor_atual)),
        "pedido": (
            "Cancelar o item" if cancelamento else texto_do_valor(campo, parte.valor_pedido)
        ),
        "concedido": texto_do_valor(campo, parte.valor_concedido) if parte.valor_concedido else "",
        "ajustada": estado == EstadoParte.APROVADA_AJUSTE,
        "motivo": parte.motivo,
        "decidido_por": nome_do_usuario(parte.decidido_por) if parte.decidido_por_id else "",
        "decidido_em": data_hora(parte.decidido_em) if parte.decidido_em else "",
        "fora_do_exercicio": parte.fora_do_exercicio,
        "inclusao": inclusao,
    }


def solicitacao_para_tela(solicitacao, alcadas) -> dict:
    """Resumo de uma solicitação para as listagens (as partes vêm do `prefetch_related`)."""
    estado = EstadoSolicitacao(solicitacao.estado)
    return {
        "obj": solicitacao,
        "codigo": solicitacao.codigo,
        "url": url_da_solicitacao(solicitacao),
        "item": rotulo_do_item(solicitacao),
        "item_url": url_do_item(solicitacao),
        "unidade": solicitacao.unidade.nome,
        "solicitante": nome_do_usuario(solicitacao.solicitante),
        "tipo": TipoSolicitacao(solicitacao.tipo).label,
        "estado": estado.value,
        "estado_rotulo": estado.label,
        "chave": CHAVE_DO_ESTADO_DA_SOLICITACAO[estado],
        "criada_em": data_hora(solicitacao.criada_em),
        "partes": [parte_para_tela(parte, alcadas) for parte in solicitacao.partes.all()],
        "pendente": estado == EstadoSolicitacao.PENDENTE,
    }


def trilha_da_solicitacao(solicitacao, partes) -> list[dict]:
    """Criação, decisões, desistência e "prejudicada", em ordem de acontecimento. As partes são
    as do `prefetch_related`; a trilha nasce dos próprios campos (autor e data de cada decisão)."""
    eventos = [
        {
            "quando": solicitacao.criada_em,
            "quem": nome_do_usuario(solicitacao.solicitante),
            "texto": "Solicitação criada",
            "detalhe": "",
        }
    ]
    for parte in partes:
        if not parte.decidido_em:
            continue
        estado = EstadoParte(parte.estado)
        campo = Campo(parte.campo).label
        if estado == EstadoParte.DESISTIDA:
            texto, detalhe = f"Desistência — {campo}", ""
        elif estado == EstadoParte.PREJUDICADA:
            texto, detalhe = f"Prejudicada — {campo}", parte.motivo or "O item foi encerrado."
        else:
            texto = f"{estado.label} — {campo}"
            detalhe = parte.motivo
            if estado == EstadoParte.APROVADA_AJUSTE and parte.valor_concedido:
                ajuste = f"Concedido: {texto_do_valor(parte.campo, parte.valor_concedido)}."
                detalhe = f"{ajuste} {detalhe}".strip()
        eventos.append(
            {
                "quando": parte.decidido_em,
                "quem": nome_do_usuario(parte.decidido_por),
                "texto": texto,
                "detalhe": detalhe,
            }
        )
    eventos.sort(key=lambda e: e["quando"])
    for evento in eventos:
        evento["quando_texto"] = data_hora(evento["quando"])
    return eventos


def linhas_da_fila(partes, hoje=None) -> dict:
    """Fila "Para avaliar": as partes da alçada de quem olha, as paradas há mais de 10 dias
    úteis primeiro e destacadas, depois da mais antiga para a mais nova. Devolve as linhas e os
    três números dos cartões-resumo. `partes` já vem de `services.partes_para_avaliar`."""
    hoje = hoje or localdate()
    linhas = []
    for parte in partes:
        solicitacao = parte.solicitacao
        criada = localtime(solicitacao.criada_em).date()
        dias = regras.dias_uteis_entre(criada, hoje)
        campo = Campo(parte.campo)
        linhas.append(
            {
                "parte_id": parte.pk,
                "codigo": solicitacao.codigo,
                "url": url_da_solicitacao(solicitacao),
                "item": rotulo_do_item(solicitacao),
                "item_url": url_do_item(solicitacao),
                "unidade": solicitacao.unidade.nome,
                "solicitante": nome_do_usuario(solicitacao.solicitante),
                "campo": campo.value,
                "rotulo": campo.label,
                "hoje": "—" if campo == Campo.INCLUSAO else (
                    "Item ativo" if campo == Campo.CANCELAMENTO else texto_do_valor(campo, parte.valor_atual)
                ),
                "pedido": "Cancelar o item" if campo == Campo.CANCELAMENTO else texto_do_valor(campo, parte.valor_pedido),
                "criada_em": criada.strftime("%d/%m/%Y"),
                "dias_uteis": dias,
                "parada": dias > regras.LIMITE_PARADA_DIAS_UTEIS,
                "fora_do_exercicio": parte.fora_do_exercicio,
                "_ordem": (not dias > regras.LIMITE_PARADA_DIAS_UTEIS, solicitacao.criada_em, parte.pk),
            }
        )
    linhas.sort(key=lambda linha: linha["_ordem"])
    return {
        "linhas": linhas,
        "pendentes": len(linhas),
        "paradas": sum(1 for linha in linhas if linha["parada"]),
        "fora_do_exercicio": sum(1 for linha in linhas if linha["fora_do_exercicio"]),
    }
