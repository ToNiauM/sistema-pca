"""Views da API JSON `/api/sei/` (Fase 42) — `saude`/`processo` (GET,
leitura), `coleta` (POST, escrita) e, desde a,
`vinculo` (POST) e `ficha` (GET/PUT) — V-1..V-5 do
contrato v1.1 (`docs/api-extensao-sei.md`). Nunca usam sessão de
navegador: `login_not_required` (isenta de `LoginRequiredMiddleware`) +
`csrf_exempt` (só Bearer, sem cookie de sessão) em toda view daqui."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime

from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.pca.api import limitador
from apps.pca.api.autenticacao import corpo_dentro_do_limite, pode_instruir, requer_token
from apps.pca.management.commands.sei_sincronizar import _campos_atuais
from apps.pca.models import FichaContratacao, Processo, ProcessoSEI
from apps.pca.sei import aplicador, execucoes, montagem, regras
from core.models import TokenApi

logger = logging.getLogger(__name__)

PREFIXO_BEARER = "Bearer "


def _so_digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto or "")


@login_not_required
@csrf_exempt
def saude_view(request):
    """GET /api/sei/saude — autenticação OPCIONAL (Adendo 2026-10-10,
    revisão do contrato v1 — `docs/api-extensao-sei.md`): sem
    `Authorization`, só confirma disponibilidade/versão; com
    `Authorization: Bearer <token>` válido, também devolve `usuario`/
    `pode_enviar` (a extensão usa isso antes de decidir se oferece o envio
    da coleta); Bearer inválido/revogado -> 401."""
    cabecalho = request.META.get("HTTP_AUTHORIZATION", "")
    if not cabecalho:
        return JsonResponse({"versao": 1})

    if not cabecalho.startswith(PREFIXO_BEARER):
        return JsonResponse({"erro": "nao_autenticado"}, status=401)

    valor_em_claro = cabecalho[len(PREFIXO_BEARER):]
    usuario = TokenApi.autenticar(valor_em_claro)
    if usuario is None:
        return JsonResponse({"erro": "nao_autenticado"}, status=401)

    if not limitador.permitido(TokenApi._hash_de(valor_em_claro)):
        return JsonResponse({"erro": "limite_requisicoes"}, status=429)

    return JsonResponse({
        "versao": 1,
        "usuario": usuario.email,
        "pode_enviar": usuario.has_perm("pca.editar_pca"),
        "pode_instruir": pode_instruir(usuario),
    })


def _serializar_item(processo: Processo) -> dict:
    return {
        "item_pca": processo.item_pca,
        "exercicio": processo.exercicio.ano,
        "descricao_objeto": processo.descricao_objeto,
        "valor_estimado": (
            str(processo.valor_estimado) if processo.valor_estimado is not None else None
        ),
        "unidade": processo.unidade_organizacional.nome,
        "grau_prioridade": (
            processo.grau_prioridade.nome if processo.grau_prioridade_id else None
        ),
        "mes_previsto": processo.mes_previsto,
        "situacao": processo.situacao,
        "situacao_rotulo": processo.get_situacao_display(),
        "numeros_sei": list(processo.numeros_sei.values_list("numero_sei", flat=True)),
        "modalidade": processo.modalidade.nome if processo.modalidade_id else None,
        "objeto": processo.descricao_objeto,
        "unidade_sigla_sei": processo.unidade_organizacional.nome,
    }


def _ultima_coleta(numero_sei_original: str) -> dict | None:
    """`{"registros", "primeiro", "recebido_em", "origem": "robo"|"extensao"}`
    — o mais recente entre `cache.json` (robô) e `extensao.json`,
pelo próprio `numero_sei` tal como foi gravado (nunca o
    normalizado). `None` sem nenhuma entrada em nenhum dos dois."""
    cache = execucoes.ler_cache()
    extensao = execucoes.ler_extensao()

    candidatos = []
    entrada_cache = cache.get("processos", {}).get(numero_sei_original)
    if entrada_cache:
        candidatos.append({
            "registros": entrada_cache.get("registros"),
            "primeiro": entrada_cache.get("primeiro"),
            "recebido_em": entrada_cache.get("coletado_em"),
            "origem": "robo",
        })
    entrada_extensao = extensao.get("processos", {}).get(numero_sei_original)
    if entrada_extensao:
        coleta = entrada_extensao.get("coleta") or {}
        candidatos.append({
            "registros": coleta.get("registros"),
            "primeiro": coleta.get("primeiro"),
            "recebido_em": entrada_extensao.get("recebido_em"),
            "origem": "extensao",
        })

    if not candidatos:
        return None
    if len(candidatos) == 1:
        return candidatos[0]
    return max(candidatos, key=lambda c: datetime.fromisoformat(c["recebido_em"]))


def _processo_por_sei(numero_sei_query: str) -> JsonResponse:
    """Casamento por DÍGITOS completos (nunca prefixo nem igualdade de
    string formatada) — `ProcessoSEI.numero_sei` não é normalizado
    (formatos reais como `90796110000019.000030/2025-74`). Sem nenhum
    vínculo, devolve `{"itens": []}` com 200 (nunca 404 — contrato v1
    revisado, `docs/api-extensao-sei.md`, tabela de erros: "hoje a rota
    nunca devolve 404")."""
    digitos = _so_digitos(numero_sei_query)
    encontrados = []
    numero_original = None
    for numero_sei in ProcessoSEI.objects.select_related(
        "processo__exercicio",
        "processo__unidade_organizacional",
        "processo__grau_prioridade",
        "processo__modalidade",
    ):
        if _so_digitos(numero_sei.numero_sei) == digitos:
            encontrados.append(numero_sei.processo)
            if numero_original is None:
                numero_original = numero_sei.numero_sei

    if not encontrados:
        return JsonResponse({"itens": []})

    itens = [_serializar_item(processo) for processo in encontrados]
    return JsonResponse({
        "itens": itens,
        "ultima_coleta": _ultima_coleta(numero_original),
    })


def _processo_por_item(item_str: str, exercicio_str: str) -> JsonResponse:
    """O caminho que o DFD da extensão usa quando o processo ainda
    não tem nº SEI vinculado; `itens: []` (nunca 404) sem resultado."""
    try:
        item_pca = int(item_str)
        ano = int(exercicio_str)
    except (TypeError, ValueError):
        return JsonResponse(
            {"erro": "corpo_invalido", "detalhes": ["item e exercicio devem ser inteiros"]},
            status=400,
        )
    processos = Processo.objects.filter(
        item_pca=item_pca, exercicio__ano=ano
    ).select_related("exercicio", "unidade_organizacional", "grau_prioridade", "modalidade")
    itens = [_serializar_item(processo) for processo in processos]
    return JsonResponse({"itens": itens})


@login_not_required
@csrf_exempt
@requer_token()
def processo_view(request):
    """GET /api/sei/processo — dois modos mutuamente exclusivos: `?sei=` ou
    `?item=&exercicio=`. GET exige só usuário ativo (sem `pca.editar_pca`
    — rota de leitura, `requer_token()` sem `permissao`)."""
    sei = request.GET.get("sei")
    item = request.GET.get("item")
    exercicio = request.GET.get("exercicio")

    if sei:
        return _processo_por_sei(sei)
    if item and exercicio:
        return _processo_por_item(item, exercicio)
    return JsonResponse(
        {"erro": "corpo_invalido", "detalhes": ["informe sei ou item e exercicio"]},
        status=400,
    )


# --- POST /api/sei/coleta -------------------------------------


_CAMPOS_ANDAMENTO = ("data_hora", "unidade", "descricao")
_CAMPOS_DOCUMENTO = ("id_documento", "protocolo", "rotulo")


def _validar_corpo(dados) -> list[str]:
    """Mensagens de validação do corpo do POST (contrato v1,
    `docs/api-extensao-sei.md`) — lista vazia quando `dados` está OK.
    Nunca lança: todo acesso é por `.get()`/`isinstance`, a view NUNCA
    deixa uma exceção de parsing virar 500."""
    if not isinstance(dados, dict):
        return ["corpo deve ser um objeto JSON"]

    detalhes = []
    numero = dados.get("numero")
    if not numero or not isinstance(numero, str):
        detalhes.append("numero: campo obrigatório")

    andamentos = dados.get("andamentos")
    if andamentos is None:
        detalhes.append("andamentos: campo obrigatório")
    elif not isinstance(andamentos, list):
        detalhes.append("andamentos: deve ser uma lista")
    else:
        for indice, andamento in enumerate(andamentos):
            if not isinstance(andamento, dict) or not all(
                andamento.get(campo) for campo in _CAMPOS_ANDAMENTO
            ):
                detalhes.append(
                    f"andamentos[{indice}]: data_hora/unidade/descricao obrigatórios"
                )

    documentos = dados.get("documentos")
    if documentos is None:
        detalhes.append("documentos: campo obrigatório")
    elif not isinstance(documentos, list):
        detalhes.append("documentos: deve ser uma lista")
    else:
        for indice, documento in enumerate(documentos):
            if not isinstance(documento, dict):
                detalhes.append(f"documentos[{indice}]: deve ser um objeto")
                continue
            faltantes = [
                campo for campo in _CAMPOS_DOCUMENTO if not documento.get(campo)
            ]
            if "assinantes_externos_na_arvore" not in documento:
                faltantes.append("assinantes_externos_na_arvore")
            if faltantes:
                detalhes.append(
                    f"documentos[{indice}]: {', '.join(faltantes)} obrigatório(s)"
                )

    return detalhes


def _processos_sei_por_digitos(numero_sei_query: str) -> list[ProcessoSEI]:
    """Todo `ProcessoSEI` cujo número bate por DÍGITOS completos com
    `numero_sei_query` (mesmo casamento de `_processo_por_sei`, nunca por
    prefixo) — pode devolver mais de um (um número pode estar vinculado a
    mais de um item do PCA, ex. renovação em exercícios diferentes); o POST
    se aplica a TODOS."""
    digitos = _so_digitos(numero_sei_query)
    return [
        numero_sei
        for numero_sei in ProcessoSEI.objects.select_related(
            "processo__exercicio"
        ).prefetch_related("processo__numeros_sei")
        if _so_digitos(numero_sei.numero_sei) == digitos
    ]


def _coleta_mais_recente_do_numero(numero_sei: str) -> dict | None:
    """Coleta mais recente (dict COMPLETO, no formato de
    `montagem.montar_processo`/`coletor.coletar_um`) de `numero_sei`, entre
    `cache.json` (robô) e `extensao.json` (outro POST anterior) — mesmo
    critério de desempate de `_ultima_coleta` acima (`coletado_em` ×
    `recebido_em`), mas devolvendo o dado inteiro (não o resumo), para
    completar `regras.propor(processos_coletados=...)` com a coleta do
    OUTRO número SEI do mesmo item. `None` sem nenhuma entrada em nenhum
    dos dois arquivos."""
    cache = execucoes.ler_cache()
    extensao = execucoes.ler_extensao()
    candidatos = []
    entrada_cache = cache.get("processos", {}).get(numero_sei)
    if entrada_cache and entrada_cache.get("coletado_em"):
        candidatos.append((entrada_cache["coletado_em"], entrada_cache))
    entrada_extensao = extensao.get("processos", {}).get(numero_sei)
    if entrada_extensao and entrada_extensao.get("recebido_em"):
        candidatos.append(
            (entrada_extensao["recebido_em"], entrada_extensao.get("coleta") or {})
        )
    if not candidatos:
        return None
    return max(candidatos, key=lambda c: datetime.fromisoformat(c[0]))[1]


@login_not_required
@csrf_exempt
@requer_token(permissao="pca.editar_pca")
def coleta_view(request):
    """POST /api/sei/coleta (`docs/api-extensao-sei.md`) — recebe
    o material bruto de UM processo SEI, monta o mesmo dict que o robô
    produziria (`montagem.montar_processo`), completa com a coleta mais
    recente dos OUTROS números SEI do mesmo item, roda `regras.propor` +
    `aplicador.aplicar` com o usuário do token e `origem="extensao"`, e
    grava a coleta recebida em `extensao.json` (nunca em `cache.json`)."""
    if not corpo_dentro_do_limite(request):
        return JsonResponse({"erro": "corpo_grande_demais"}, status=413)

    try:
        dados = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse(
            {"erro": "corpo_invalido", "detalhes": ["JSON inválido"]}, status=400
        )

    detalhes = _validar_corpo(dados)
    if detalhes:
        return JsonResponse({"erro": "corpo_invalido", "detalhes": detalhes}, status=400)

    encontrados = _processos_sei_por_digitos(dados["numero"])
    if not encontrados:
        return JsonResponse({"erro": "processo_sem_item"}, status=404)

    itens_resposta = []
    for numero_sei_obj in encontrados:
        processo = numero_sei_obj.processo
        material = {**dados, "numero": numero_sei_obj.numero_sei}
        coleta_recebida = montagem.montar_processo(material)

        processos_coletados = [coleta_recebida]
        for outro in processo.numeros_sei.all():
            if outro.pk == numero_sei_obj.pk:
                continue
            coleta_outro = _coleta_mais_recente_do_numero(outro.numero_sei)
            if coleta_outro:
                processos_coletados.append(coleta_outro)

        proposta = regras.propor(
            item_pca=processo.item_pca,
            exercicio=processo.exercicio.ano,
            campos_atuais=_campos_atuais(processo),
            processos_coletados=processos_coletados,
        )

        try:
            resumo = aplicador.aplicar(
                [proposta], simular=False, usuario=request.user, origem="extensao"
            )
        except Exception:
            # /falha_interna — nunca propaga: se `aplicador.aplicar`
            # falhou no meio de uma transação, a própria `transaction.atomic`
            # de `aplicador.py` já reverteu o banco; esta view só garante não
            # escrever `extensao.json` quando o banco não foi tocado (abaixo,
            # a gravação só acontece DEPOIS de um `aplicar()` bem-sucedido).
            logger.exception(
                "coleta_view: falha ao aplicar proposta do item %s", processo.item_pca
            )
            return JsonResponse({"erro": "falha_interna"}, status=500)

        campos_aplicados = next(
            (
                entrada["campos"]
                for entrada in resumo["alterados"]
                if entrada["item"] == processo.item_pca
            ),
            [],
        )
        # Contrato v1 (spec §3): `{campo: [antes, depois]}` — o par vem da
        # própria proposta; datas/Decimal serializados pelo encoder do
        # `JsonResponse` (ISO / string).
        alterados = {
            campo: list(proposta.alteracoes[campo])
            for campo in campos_aplicados
            if campo in proposta.alteracoes
        }
        pendencias = [
            {"chave": pendencia["chave"], "texto": pendencia["texto"]}
            for pendencia in resumo["pendencias"]
            if pendencia["item"] == processo.item_pca
        ]
        itens_resposta.append({
            "item_pca": processo.item_pca,
            "exercicio": processo.exercicio.ano,
            "alterados": alterados,
            "pendencias": pendencias,
        })

        # Só grava extensao.json DEPOIS de aplicar() ter retornado sem
        # exceção (ver comentário acima) — read+update+write inteiros
        # dentro de uma única seção crítica de flock (execucoes.py).
        execucoes.atualizar_extensao(
            numero_sei_obj.numero_sei, coleta_recebida, request.user.pk
        )

    return JsonResponse({"itens": itens_resposta})


# --- POST /api/sei/vinculo (V-1/V-2) ----------------------


def _validar_corpo_vinculo(corpo) -> list[str]:
    """Mensagens de validação do corpo de `POST /vinculo` — lista vazia
    quando `corpo` está OK. Mesmo estilo de `_validar_corpo` (acima, para
    `/coleta`): nunca lança, todo acesso é por `.get()`/`isinstance`."""
    if not isinstance(corpo, dict):
        return ["corpo deve ser um objeto JSON"]

    detalhes = []
    item_pca = corpo.get("item_pca")
    if not isinstance(item_pca, int) or isinstance(item_pca, bool):
        detalhes.append("item_pca: campo obrigatório (inteiro)")

    exercicio = corpo.get("exercicio")
    if not isinstance(exercicio, int) or isinstance(exercicio, bool):
        detalhes.append("exercicio: campo obrigatório (inteiro)")

    numero_sei = corpo.get("numero_sei")
    if not numero_sei or not isinstance(numero_sei, str):
        detalhes.append("numero_sei: campo obrigatório")

    return detalhes


def _processo_do_corpo(corpo) -> Processo | None:
    """`Processo` casado por `item_pca`/`exercicio__ano`, com os mesmos
    `select_related` de `_serializar_item` — reaproveitado por
    `vinculo_view`/`_ficha_put`."""
    return (
        Processo.objects.filter(
            item_pca=corpo["item_pca"], exercicio__ano=corpo["exercicio"]
        )
        .select_related(
            "exercicio", "unidade_organizacional", "grau_prioridade", "modalidade"
        )
        .first()
    )


@login_not_required
@csrf_exempt
@requer_token(permissao=pode_instruir)
def vinculo_view(request):
    """POST /api/sei/vinculo (V-1/V-2, `docs/api-extensao-sei.md`) — liga
    um nº SEI a um item do PCA; idempotente por DÍGITOS completos (nunca
    recusa por "já tem outro processo" — um nº SEI pode estar em mais de um
    item)."""
    try:
        corpo = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse(
            {"erro": "corpo_invalido", "detalhes": ["JSON inválido"]}, status=400
        )

    detalhes = _validar_corpo_vinculo(corpo)
    if detalhes:
        return JsonResponse({"erro": "corpo_invalido", "detalhes": detalhes}, status=400)

    processo = _processo_do_corpo(corpo)
    if processo is None:
        return JsonResponse({"erro": "item_inexistente"}, status=404)

    digitos = _so_digitos(corpo["numero_sei"])
    for numero_sei_existente in processo.numeros_sei.all():
        if _so_digitos(numero_sei_existente.numero_sei) == digitos:
            return JsonResponse({"criado": False, "item": _serializar_item(processo)})

    processo.numeros_sei.create(numero_sei=corpo["numero_sei"])
    return JsonResponse(
        {"criado": True, "item": _serializar_item(processo)}, status=201
    )


# --- GET/PUT /api/sei/ficha (V-5) -------------------------


def _validar_corpo_ficha_put(corpo) -> list[str]:
    """Mesmo estilo de `_validar_corpo_vinculo` — `item_pca`/`exercicio`
    inteiros obrigatórios; `versao` inteiro `>= 0` obrigatório; `dados`
    precisa ser um objeto JSON."""
    if not isinstance(corpo, dict):
        return ["corpo deve ser um objeto JSON"]

    detalhes = []
    item_pca = corpo.get("item_pca")
    if not isinstance(item_pca, int) or isinstance(item_pca, bool):
        detalhes.append("item_pca: campo obrigatório (inteiro)")

    exercicio = corpo.get("exercicio")
    if not isinstance(exercicio, int) or isinstance(exercicio, bool):
        detalhes.append("exercicio: campo obrigatório (inteiro)")

    versao = corpo.get("versao")
    if (
        not isinstance(versao, int)
        or isinstance(versao, bool)
        or versao < 0
    ):
        detalhes.append("versao: campo obrigatório (inteiro >= 0)")

    dados = corpo.get("dados")
    if not isinstance(dados, dict):
        detalhes.append("dados: precisa ser um objeto JSON")

    return detalhes


def _serializar_ficha(processo: Processo, ficha: FichaContratacao | None) -> dict:
    """`{item_pca, exercicio, versao, dados, atualizado_em, atualizado_por}`
    — `versao: 0`/`dados: {}`/`atualizado_em: None`/`atualizado_por: None`
    quando `ficha` é `None` (nenhuma ficha gravada ainda, V-5)."""
    base = {
        "item_pca": processo.item_pca,
        "exercicio": processo.exercicio.ano,
    }
    if ficha is None:
        return {
            **base,
            "versao": 0,
            "dados": {},
            "atualizado_em": None,
            "atualizado_por": None,
        }
    return {
        **base,
        "versao": ficha.versao,
        "dados": ficha.dados,
        "atualizado_em": ficha.atualizado_em.isoformat(),
        "atualizado_por": (
            ficha.atualizado_por.email if ficha.atualizado_por_id else None
        ),
    }


def _ficha_get(request) -> JsonResponse:
    """GET /api/sei/ficha — `?sei=` ou `?item=&exercicio=`, mutuamente
    exclusivos (mesmo padrão de `processo_view`); qualquer usuário
    autenticado lê (sem exigir `pode_instruir`)."""
    sei = request.GET.get("sei")
    item = request.GET.get("item")
    exercicio = request.GET.get("exercicio")

    if sei:
        encontrados = _processos_sei_por_digitos(sei)
        processos_distintos = {
            numero_sei.processo.pk: numero_sei.processo for numero_sei in encontrados
        }
        if not processos_distintos:
            return JsonResponse({"erro": "item_inexistente"}, status=404)
        if len(processos_distintos) > 1:
            itens = sorted(
                (
                    {"item_pca": p.item_pca, "exercicio": p.exercicio.ano}
                    for p in processos_distintos.values()
                ),
                key=lambda i: (i["exercicio"], i["item_pca"]),
            )
            return JsonResponse(
                {"erro": "sei_em_varios_itens", "itens": itens}, status=409
            )
        processo = next(iter(processos_distintos.values()))
    elif item and exercicio:
        try:
            item_pca = int(item)
            ano = int(exercicio)
        except (TypeError, ValueError):
            return JsonResponse(
                {"erro": "corpo_invalido", "detalhes": ["item e exercicio devem ser inteiros"]},
                status=400,
            )
        processo = (
            Processo.objects.filter(item_pca=item_pca, exercicio__ano=ano)
            .select_related("exercicio")
            .first()
        )
        if processo is None:
            return JsonResponse({"erro": "item_inexistente"}, status=404)
    else:
        return JsonResponse(
            {"erro": "corpo_invalido", "detalhes": ["informe sei ou item e exercicio"]},
            status=400,
        )

    ficha = (
        FichaContratacao.objects.filter(processo=processo)
        .select_related("atualizado_por")
        .first()
    )
    return JsonResponse(_serializar_ficha(processo, ficha))


def _ficha_put(request) -> JsonResponse:
    """PUT /api/sei/ficha — controle otimista (V-5): `versao` igual à
    atual (`0` para criar) grava com `versao+1`; divergente -> 409 com a
    ficha atual, NUNCA sobrescreve."""
    try:
        corpo = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse(
            {"erro": "corpo_invalido", "detalhes": ["JSON inválido"]}, status=400
        )

    detalhes = _validar_corpo_ficha_put(corpo)
    if detalhes:
        return JsonResponse({"erro": "corpo_invalido", "detalhes": detalhes}, status=400)

    tamanho_bytes = len(json.dumps(corpo["dados"], ensure_ascii=False).encode("utf-8"))
    if tamanho_bytes > settings.API_FICHA_MAX_KB * 1024:
        return JsonResponse({"erro": "corpo_grande_demais"}, status=413)

    processo = _processo_do_corpo(corpo)
    if processo is None:
        return JsonResponse({"erro": "item_inexistente"}, status=404)

    with transaction.atomic():
        ficha = (
            FichaContratacao.objects.select_for_update()
            .filter(processo=processo)
            .first()
        )
        versao_atual = ficha.versao if ficha is not None else 0

        if corpo["versao"] != versao_atual:
            return JsonResponse(
                {
                    "erro": "versao_desatualizada",
                    "ficha": _serializar_ficha(processo, ficha),
                },
                status=409,
            )

        if ficha is None:
            ficha = FichaContratacao.objects.create(
                processo=processo,
                versao=1,
                dados=corpo["dados"],
                atualizado_por=request.user,
            )
        else:
            ficha.versao += 1
            ficha.dados = corpo["dados"]
            ficha.atualizado_por = request.user
            ficha.save(
                update_fields=["versao", "dados", "atualizado_por", "atualizado_em"]
            )

    return JsonResponse(_serializar_ficha(processo, ficha))


@login_not_required
@csrf_exempt
@require_http_methods(["GET", "PUT"])
@requer_token()
def ficha_view(request):
    """GET/PUT /api/sei/ficha (V-5) — GET é leitura (qualquer usuário
    autenticado, sem exigir `pode_instruir`); PUT exige `pode_instruir`,
    checado manualmente (não no `requer_token`, que aqui fica sem
    `permissao` para não bloquear o GET)."""
    if request.method == "GET":
        return _ficha_get(request)

    if not pode_instruir(request.user):
        return JsonResponse({"erro": "sem_permissao"}, status=403)
    return _ficha_put(request)
