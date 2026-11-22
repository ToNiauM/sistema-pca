"""Pontos de contato das Solicitações com a ficha do item (Fase 43).

`apps.pca.views_processo.detalhe_processo_view` chama `contexto_da_ficha` (import local, o domínio das
Solicitações depende do `apps.pca` e não o contrário) e as duas fichas — DSGov e Tabler — desenham o
botão "Solicitar alteração" e a aba "Solicitações" a partir destas chaves.
"""

from __future__ import annotations

from django.db.models import Prefetch
from django.urls import reverse

from . import apresentacao, services
from .models import ParteSolicitacao, Solicitacao, VinculoUnidade


def contexto_da_ficha(usuario, processo) -> dict:
    """`processo` vem de `Processo.objects.para_listagem()` (a ficha já o carrega assim).

    - `pode_solicitar`: pede quem tem `solicitar`, é vinculado à unidade do item e o item ainda
      aceita algum pedido (exercício aberto, item ativo e não concluído).
    - `pode_ver_solicitacoes`: a unidade do item (vinculada), a equipe do PCA e a diretoria.
    """
    alcadas = services.alcadas_do_usuario(usuario)
    da_unidade = usuario.has_perm(services.PERM_SOLICITAR) and VinculoUnidade.objects.filter(
        usuario=usuario, unidade_id=processo.unidade_organizacional_id
    ).exists()
    pode_ver = da_unidade or bool(alcadas)
    contexto = {
        "pode_solicitar": bool(da_unidade and services.campos_aceitos_do_item(processo)),
        "url_solicitar": (
            f"{reverse('solicitacoes:nova')}?processo={processo.exercicio.ano}/{processo.item_pca}"
        ),
        "pode_ver_solicitacoes": pode_ver,
        "solicitacoes_ficha": [],
    }
    if pode_ver:
        consulta = (
            Solicitacao.objects.filter(processo=processo)
            .select_related("unidade", "solicitante", "exercicio", "processo")
            .prefetch_related(
                Prefetch(
                    "partes",
                    queryset=ParteSolicitacao.objects.select_related("decidido_por").order_by("id"),
                )
            )
        )
        contexto["solicitacoes_ficha"] = [
            apresentacao.solicitacao_para_tela(s, alcadas) for s in consulta
        ]
    return contexto
