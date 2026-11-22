"""Ferramentas do Assistente do PCA (A17) — envelope comum e
`consultar_processos`, a única ferramenta desta fatia (39-01). `usuario`
é sempre injetado pelo servidor, nunca argumento do modelo. Referências
internas SÓ por `reverse()` + `urlencode` sobre os filtros de fato
aplicados — nenhuma URL vem de argumento do modelo."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from urllib.parse import urlencode

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from apps.assistente import cliente as cliente_mod
from apps.assistente import esquema
from apps.assistente import sql as sql_mod
from apps.catalogo.utils import normalizar_nome


def _serializar(objeto):
    if isinstance(objeto, Decimal):
        return str(objeto)
    if isinstance(objeto, (date, datetime)):
        return objeto.isoformat()
    raise TypeError(f"não serializável: {objeto!r}")


@dataclass
class Envelope:
    dados: dict
    referencias: list = field(default_factory=list)
    atualidade: dict = field(default_factory=dict)
    sem_permissao: bool = False
    truncado: bool = False

    def para_json(self) -> str:
        return json.dumps(
            {
                "dados": self.dados,
                "referencias": self.referencias,
                "atualidade": self.atualidade,
                "sem_permissao": self.sem_permissao,
                "truncado": self.truncado,
            },
            ensure_ascii=False,
            default=_serializar,
        )


@dataclass
class ContextoExecucao:
    """Contexto injetado pelo agente para ferramentas que
    precisam do cliente de IA e de um orçamento próprio dentro da mesma
    resposta — hoje só `buscar_texto` (embeddings de consulta,
    `MAX_EMBEDDINGS` por pergunta). `embeddings_restantes` é MUTADO por
    referência a cada chamada bem-sucedida — o mesmo objeto é reaproveitado
    por todas as `tool_calls` de uma única chamada a `agente.responder`."""

    usuario: object
    exercicio_padrao: object
    cliente: object = None
    embeddings_restantes: int = 0
    agora: object = None


def _atualidade_pca() -> dict:
    return {"pca_consultado_em": timezone.now().isoformat(), "sei": None, "indice": None}


def resolver_exercicio_ferramenta(exercicio_arg, exercicio_padrao):
    """`exercicio_arg` é o valor bruto (int|None) vindo do modelo;
    `exercicio_padrao` é o `Exercicio` da página. Devolve
    `(Exercicio|None, aviso|None)` — `None` sem aviso quando `exercicio_arg`
    foi informado mas não existe (o chamador distingue os dois casos)."""
    from apps.catalogo.models import Exercicio

    if exercicio_arg is None:
        if exercicio_padrao is None:
            return None, None
        return exercicio_padrao, f"exercício assumido: {exercicio_padrao.ano}"
    return Exercicio.objects.filter(ano=exercicio_arg).first(), None


def resolver_unidade(texto):
    """`(Unidade|None, alternativas: list[str])`. 0 resultados: `(None,
    [])`. >1: `(None, [nomes])` — desambiguação, SEM consultar processos
    (A17). 1: `(unidade, [])`."""
    from apps.catalogo.models import Unidade

    chave = normalizar_nome(texto)
    if not chave:
        return None, []
    qs = Unidade.objects.filter(nome_normalizado__icontains=chave).order_by("nome")
    total = qs.count()
    if total == 0:
        return None, []
    if total > 1:
        return None, list(qs.values_list("nome", flat=True))
    return qs.first(), []


_MAPA_SITUACOES: dict[str, str] = {}


def _mapa_situacoes():
    if not _MAPA_SITUACOES:
        from apps.pca.models import Situacao

        for valor, rotulo in Situacao.choices:
            _MAPA_SITUACOES[normalizar_nome(valor).replace(" ", "_")] = valor
            _MAPA_SITUACOES[normalizar_nome(rotulo).replace(" ", "_")] = valor
    return _MAPA_SITUACOES


def _resolver_situacao(valor_bruto):
    chave = normalizar_nome(valor_bruto).replace(" ", "_")
    return _mapa_situacoes().get(chave)


def consultar_processos(
    usuario,
    *,
    exercicio,
    unidade=None,
    situacao=None,
    fornecedor=None,
    texto_objeto=None,
    tipo=None,
    categoria=None,
    sem_processo_sei=None,
    limite=20,
) -> Envelope:
    """Autenticado (qualquer usuário logado). `exercicio` já é o ANO
    resolvido pelo dispatcher (`executar()`) — nunca `None` aqui."""
    from apps.catalogo.models import Exercicio
    from apps.pca.models import Estado, Processo, Situacao

    exercicio_obj = Exercicio.objects.filter(ano=exercicio).first()
    if exercicio_obj is None:
        anos = list(Exercicio.objects.order_by("-ano").values_list("ano", flat=True))
        return Envelope(dados={"erro": "exercício inexistente", "exercicios": anos})

    qs = Processo.objects.para_listagem().filter(exercicio=exercicio_obj, estado=Estado.ATIVO)
    filtros_aplicados = {"exercicio": exercicio}
    querystring_partes = [("exercicio", exercicio)]

    if unidade:
        unidade_obj, alternativas = resolver_unidade(unidade)
        if unidade_obj is None and alternativas:
            return Envelope(dados={"ambiguo": True, "alternativas": alternativas})
        if unidade_obj is None:
            return Envelope(dados={"erro": "unidade não encontrada"})
        qs = qs.filter(unidade_organizacional=unidade_obj)
        filtros_aplicados["unidade"] = unidade_obj.nome
        querystring_partes.append(("uo", unidade_obj.pk))

    if situacao:
        valor_situacao = _resolver_situacao(situacao)
        if valor_situacao is None:
            return Envelope(
                dados={
                    "erro": "situação inválida",
                    "situacoes": [valor for valor, _ in Situacao.choices],
                }
            )
        qs = qs.filter(situacao_efetiva=valor_situacao)
        filtros_aplicados["situacao"] = valor_situacao
        querystring_partes.append(("situacao", valor_situacao))

    termo_busca = None
    if fornecedor:
        qs = qs.filter(fornecedor_razao_social__unaccent__icontains=fornecedor)
        filtros_aplicados["fornecedor"] = fornecedor
        termo_busca = fornecedor
    if texto_objeto:
        qs = qs.filter(descricao_objeto__unaccent__icontains=texto_objeto)
        filtros_aplicados["texto_objeto"] = texto_objeto
        termo_busca = texto_objeto
    if termo_busca:
        querystring_partes.append(("q", termo_busca))
    if tipo:
        qs = qs.filter(tipo__nome_normalizado__icontains=normalizar_nome(tipo))
        filtros_aplicados["tipo"] = tipo

    if sem_processo_sei:
        qs = qs.filter(numeros_sei__isnull=True)
        filtros_aplicados["sem_processo_sei"] = True
        querystring_partes.append(("sem_processo_sei", "1"))

    aviso = None
    if categoria:
        from apps.catalogo.models import Categoria

        categorias_qs = Categoria.objects.filter(
            nome_normalizado__icontains=normalizar_nome(categoria)
        )
        ids_categoria = list(categorias_qs.values_list("id", flat=True))
        nomes_categoria = list(categorias_qs.values_list("nome", flat=True))
        filtros_aplicados["categoria"] = categoria
        if not ids_categoria:
            existentes = ", ".join(Categoria.objects.values_list("nome", flat=True))
            aviso = f"categoria não encontrada; existentes: {existentes}"
        elif len(ids_categoria) > 1:
            aviso = f"categoria ambígua; usando: {', '.join(nomes_categoria)}"
        qs = qs.filter(categoria_id__in=ids_categoria)
        for id_categoria in ids_categoria:
            querystring_partes.append(("categoria", id_categoria))

    total = qs.count()
    try:
        limite_efetivo = int(limite) if limite else 20
    except (TypeError, ValueError):
        limite_efetivo = 20
    limite_efetivo = min(max(limite_efetivo, 1), 20)
    itens_qs = list(qs.order_by("item_pca")[:limite_efetivo])
    itens = [
        {
            "item_pca": p.item_pca,
            "objeto": p.descricao_objeto[:160],
            "unidade": p.unidade_organizacional.nome,
            "situacao": p.situacao_efetiva,
            "prazo_efetivo": p.prazo_efetivo.isoformat() if p.prazo_efetivo else None,
            "dias_atraso": p.dias_atraso if p.atrasado else None,
            "valor_estimado": str(p.valor_estimado) if p.valor_estimado is not None else None,
            "fornecedor": p.fornecedor_razao_social or None,
            "unidade_sei_atual": p.unidade_sei_atual or None,
            "unidade_sei_atual_desde": (
                p.unidade_sei_atual_desde.isoformat() if p.unidade_sei_atual_desde else None
            ),
        }
        for p in itens_qs
    ]
    url = reverse("pca:tabela") + "?" + urlencode(querystring_partes, doseq=True)
    dados = {
        "exercicio": exercicio,
        "total": total,
        "exibidos": len(itens),
        "filtros": filtros_aplicados,
        "itens": itens,
    }
    if aviso:
        dados["aviso"] = aviso
    return Envelope(
        dados=dados,
        referencias=[{"rotulo": "Processos filtrados", "url": url}],
        atualidade=_atualidade_pca(),
        truncado=total > len(itens),
    )


_TIPOS_INSTRUMENTO_SEI = frozenset(
    {"contrato", "termo_aditivo", "apostilamento", "ordem_fornecimento", "ata_rp"}
)


def ficha(usuario, *, exercicio, item) -> Envelope:
    """Autenticado. Campos públicos do item, instrumentos/signatários/links
    do SEI e, só com `pca.view_acompanhamento`, os últimos 5 acompanhamentos.
Ausência de dado != zero — `Processo` inexistente devolve um
    erro explícito, nunca um envelope "vazio"."""
    from apps.pca.filtros import NOMES_MES
    from apps.pca.models import Processo
    from apps.pca.sei import execucoes
    from apps.pca.templatetags.sei_links import URL_PROCEDIMENTO, url_processo_sei

    processo = (
        Processo.objects.para_listagem()
        .select_related(
            "exercicio", "unidade_organizacional", "tipo", "categoria",
            "modalidade", "instrumento_contratual",
        )
        .prefetch_related("numeros_sei", "eventos_financeiros")
        .filter(exercicio__ano=exercicio, item_pca=item)
        .first()
    )
    if processo is None:
        return Envelope(dados={"erro": f"item {item} não encontrado no exercício {exercicio}"})

    dados = {
        "item_pca": processo.item_pca,
        "objeto": processo.descricao_objeto,
        "justificativa": (processo.justificativa or "")[:600],
        "unidade": processo.unidade_organizacional.nome,
        "tipo": processo.tipo.nome,
        "categoria": processo.categoria.nome,
        "valor_estimado": str(processo.valor_estimado) if processo.valor_estimado is not None else None,
        "mes_previsto": NOMES_MES.get(processo.mes_previsto),
        "estado": processo.estado,
        "situacao": processo.situacao_efetiva,
        "prazo_efetivo": processo.prazo_efetivo.isoformat() if processo.prazo_efetivo else None,
        "modalidade": processo.modalidade.nome if processo.modalidade else None,
        "numero_contratacao": processo.numero_contratacao,
        "numero_arp": processo.numero_arp,
        "instrumento": processo.instrumento_contratual.nome if processo.instrumento_contratual else None,
        "numero_instrumento": processo.numero_instrumento_contratual,
        "valor_contratado": str(processo.valor_contratado) if processo.valor_contratado is not None else None,
        "valor_mensal": str(processo.valor_mensal) if processo.valor_mensal is not None else None,
        "vigencia_inicio": processo.vigencia_inicio.isoformat() if processo.vigencia_inicio else None,
        "vigencia_fim": processo.vigencia_fim.isoformat() if processo.vigencia_fim else None,
        "fornecedor_razao_social": processo.fornecedor_razao_social,
        "fornecedor_cnpj": processo.fornecedor_cnpj,
        "regime_execucao": processo.regime_execucao,
        "renovacao_prevista": processo.renovacao_prevista,
        "sem_processo_sei": not processo.numeros_sei.all(),
        "unidade_sei_atual": processo.unidade_sei_atual or None,
        "unidade_sei_atual_desde": (
            processo.unidade_sei_atual_desde.isoformat() if processo.unidade_sei_atual_desde else None
        ),
    }

    links = execucoes.ler_links()
    numeros_sei_qs = list(processo.numeros_sei.all())
    numeros_sei = []
    for numero_sei in numeros_sei_qs:
        id_procedimento = (
            links.get("processos", {}).get(numero_sei.numero_sei, {}).get("id_procedimento")
        )
        numeros_sei.append({
            "numero": numero_sei.numero_sei,
            "url": URL_PROCEDIMENTO.format(id_procedimento) if id_procedimento else None,
        })
    dados["numeros_sei"] = numeros_sei

    referencias = [
        {
            "rotulo": f"Ficha do item {item} (PCA {exercicio})",
            "url": reverse("pca:detalhe_processo", args=[exercicio, item]),
        }
    ]

    cache = execucoes.ler_cache()
    instrumentos = []
    documentos_lidos_em = []
    for numero_sei in numeros_sei_qs:
        entrada = cache.get("processos", {}).get(numero_sei.numero_sei)
        if not entrada:
            continue
        for documento in entrada.get("documentos_contratuais") or []:
            tipo_doc = documento.get("tipo")
            if tipo_doc not in _TIPOS_INSTRUMENTO_SEI:
                continue
            # Documento do SEI não tem link próprio que funcione fora da sessão: aponta para o processo.
            url_documento = url_processo_sei(numero_sei.numero_sei, links)
            rotulo = documento.get("rotulo") or "Documento"
            valor_info = documento.get("valor") or {}
            signatarios = [
                {
                    "nome": assinatura.get("nome"),
                    "cargo": assinatura.get("cargo"),
                    "papel": assinatura.get("papel"),
                    "data": assinatura.get("data"),
                    "hora": assinatura.get("hora"),
                }
                for assinatura in (documento.get("assinaturas") or [])
            ]
            instrumentos.append({
                "rotulo": rotulo,
                "tipo": tipo_doc,
                "protocolo": documento.get("protocolo"),
                "data_assinatura": documento.get("ultima_assinatura"),
                "signatarios": signatarios,
                "valor": valor_info.get("cifra"),
                "vigencia": documento.get("vigencia"),
                "url": url_documento,
                "lido_em": documento.get("lido_em"),
            })
            if documento.get("lido_em"):
                documentos_lidos_em.append(documento["lido_em"])
            if url_documento and not any(r["url"] == url_documento for r in referencias):
                referencias.append({"rotulo": f"Processo SEI {numero_sei.numero_sei}", "url": url_documento})
    dados["instrumentos"] = instrumentos

    dados["eventos_financeiros"] = [
        {
            "tipo": evento.tipo,
            "natureza": evento.natureza,
            "data": evento.data.isoformat() if evento.data else None,
            "valor": str(evento.valor) if evento.valor is not None else None,
            "instrumento": evento.instrumento,
        }
        for evento in processo.eventos_financeiros.all()
    ]

    sem_permissao = False
    if usuario.has_perm("pca.view_acompanhamento"):
        dados["acompanhamentos"] = [
            {
                "data": acompanhamento.referencia_data.isoformat(),
                "evento": acompanhamento.evento,
                "situacao_informada": acompanhamento.situacao_informada,
                "prazo_prometido": (
                    acompanhamento.prazo_prometido.isoformat()
                    if acompanhamento.prazo_prometido else None
                ),
            }
            for acompanhamento in processo.acompanhamentos.order_by("-referencia_data", "-id")[:5]
        ]
    else:
        # Recusa PARCIAL: a ficha pública inteira já está montada
        # acima — só a fatia restrita fica de fora. `sem_permissao=True`
        # ainda soma na recusa genérica de `agente.py` (nome da ferramenta);
        # `aviso_permissao` aqui é o texto específico que a spec pede.
        dados["acompanhamentos"] = None
        dados["aviso_permissao"] = "Sem permissão para consultar: acompanhamentos do item"
        sem_permissao = True

    ultima_info = execucoes.carregar_ultima_consulta().get(execucoes.chave_item(item, exercicio))
    sei_atualidade = None
    if numeros_sei:
        sei_atualidade = {
            "ultima_consulta": ultima_info.get("data_hora") if ultima_info else None,
            "resultado": ultima_info.get("resultado") if ultima_info else None,
            "documentos_lidos_em": documentos_lidos_em,
        }

    return Envelope(
        dados=dados,
        referencias=referencias,
        atualidade={
            "pca_consultado_em": timezone.now().isoformat(),
            "sei": sei_atualidade,
            "indice": None,
        },
        sem_permissao=sem_permissao,
    )


def buscar_texto(
    usuario, *, pergunta, fonte=None, exercicio=None, item=None, contexto: ContextoExecucao = None
) -> Envelope:
    """Busca semântica autorizada: fontes autorizadas e recorte
    ANTES da recuperação (`indice.buscar` já calcula `permissoes_
    autorizadas` antes do top-k); `contexto.cliente`/`contexto.
    embeddings_restantes` controlam o orçamento de embeddings de consulta
    por resposta (`MAX_EMBEDDINGS`, `agente.py`)."""
    from apps.assistente import fontes as fontes_mod
    from apps.assistente import indice
    from apps.catalogo.models import Exercicio

    if not pergunta or not (1 <= len(pergunta) <= 500):
        return Envelope(dados={"erro": "pergunta inválida (1 a 500 caracteres)"})
    if fonte is not None and fonte not in fontes_mod.FONTES:
        return Envelope(dados={"erro": "fonte inválida", "fontes": list(fontes_mod.FONTES)})
    if exercicio is not None and not Exercicio.objects.filter(ano=exercicio).exists():
        return Envelope(dados={"erro": "exercício inexistente"})

    if contexto is None or contexto.cliente is None:
        return Envelope(dados={"erro": "busca indisponível — provedor de IA não configurado"})
    if contexto.embeddings_restantes <= 0:
        return Envelope(dados={"erro": "orçamento de busca esgotado"})

    try:
        resposta_embeddings = contexto.cliente.embeddings([pergunta], settings.IA_TIMEOUT_S)
    except cliente_mod.ErroCliente:
        return Envelope(dados={"erro": "busca indisponível — falha no provedor de IA"})
    contexto.embeddings_restantes -= 1
    vetor_consulta = resposta_embeddings.vetores[0]

    try:
        resultados = indice.buscar(
            usuario=usuario,
            vetor_consulta=vetor_consulta,
            exercicio=exercicio,
            item_pca=item,
            fonte=fonte,
            k=6,
            limiar=0.25,
        )
    except indice.IndiceIndisponivel:
        return Envelope(dados={"erro": "busca indisponível — índice ainda não gerado"})

    trechos = [
        {
            "fonte": resultado.fonte,
            "titulo": resultado.titulo,
            "texto": resultado.texto,
            "escore": round(resultado.escore, 3),
            "exercicio": resultado.exercicio,
            "item_pca": resultado.item_pca,
            "atualizado_em": resultado.atualizado_em,
        }
        for resultado in resultados
    ]

    referencias = []
    urls_vistas = set()
    for resultado in resultados:
        if resultado.url and resultado.url not in urls_vistas:
            referencias.append({"rotulo": resultado.titulo, "url": resultado.url})
            urls_vistas.add(resultado.url)

    documentos_lidos_em = [
        resultado.atualizado_em
        for resultado in resultados
        if resultado.fonte == "sei" and resultado.atualizado_em
    ]

    return Envelope(
        dados={"trechos": trechos, "total": len(trechos), "abstencao": len(trechos) == 0},
        referencias=referencias,
        atualidade={
            "pca_consultado_em": timezone.now().isoformat(),
            "sei": {"documentos_lidos_em": documentos_lidos_em} if documentos_lidos_em else None,
            "indice": indice.publicado_em(),
        },
    )


def consultar_sql(usuario, *, sql) -> Envelope:
    """SQL `SELECT` somente leitura sobre o banco
    inteiro, exceto senha/sessão (`apps.assistente.sql`). Qualquer usuário
    autenticado ("o PCA é público", sem checagem de permissão por
    perfil). `sem_permissao` fica SEMPRE `False` aqui — uma recusa de SQL
    (tabela bloqueada, escrita, timeout) não é a mesma coisa que recusa de
    perfil. Nunca levanta: erro do SQLite vira `dados["erro"]` legível,
    para o modelo poder corrigir e tentar de novo (conta uma ferramenta,
    mesmo espírito de `buscar_texto`)."""
    from django.conf import settings

    if not sql or not (1 <= len(sql) <= 4000):
        return Envelope(dados={"erro": "sql inválido (1 a 4000 caracteres)"})

    caminho_db = settings.DATABASES["default"]["NAME"]
    try:
        resultado = sql_mod.executar_select(sql, caminho_db=caminho_db)
    except sql_mod.ErroSQL as exc:
        return Envelope(dados={"erro": exc.mensagem})

    return Envelope(dados=resultado, atualidade=_atualidade_pca())


def _atualidade_sei_agregada(itens_pca, exercicio, execucoes_mod) -> dict:
    """Atualidade SEI de um CONJUNTO de itens (A13) — intervalo de
    coletas + quantos itens sem coleta + quantos com falha, NUNCA o maior
    timestamp como frescor de todos (mesmo espírito de `agente.py::
    _texto_sei`, aqui para o formato agregado que só `contratos_a_vencer`
    produz). Chave composta ano-item (Lote 6 do QA 30/09/2026, achado dados
    A3) — `exercicio` é sempre o mesmo para todo `itens_pca` (lista do
    MESMO exercício consultado)."""
    mapa = execucoes_mod.carregar_ultima_consulta()
    datas = []
    sem_coleta = 0
    com_falha = 0
    for item_pca in itens_pca:
        info = mapa.get(execucoes_mod.chave_item(item_pca, exercicio))
        if not info:
            sem_coleta += 1
            continue
        if info.get("resultado") != "ok":
            com_falha += 1
        data_hora = info.get("data_hora")
        if data_hora:
            datas.append(data_hora)
    return {
        "itens_com_coleta": len(itens_pca) - sem_coleta,
        "itens_sem_coleta": sem_coleta,
        "mais_antiga": min(datas) if datas else None,
        "mais_recente": max(datas) if datas else None,
        "com_falha": com_falha,
    }


def fluxo_de_caixa(
    usuario, *, exercicio, ano=None, mes=None, unidade=None
) -> Envelope:
    """`pca.ver_analises` (A16) — projeção SEMPRE oficial:
    `cenario="base"` fixo e índice padrão do sistema
    (`settings.PCA_INDICE_REAJUSTE_PADRAO`), nunca argumento do modelo,
    nunca rascunho/cenário de sessão (o serviço `consultas_fluxo` sequer
    aceita esses parâmetros). `ano`/`mes` acrescentam um recorte agregado
    sobre `Projecao.parcelas` já geradas — a mesma regra de "Contratações
    neste recorte" da tela de Fluxo de caixa."""
    if not usuario.has_perm("pca.ver_analises"):
        return Envelope(
            dados={
                "recusa": "requer a permissão de análises estratégicas (pca.ver_analises)"
            },
            sem_permissao=True,
        )

    from apps.catalogo.models import Exercicio, Unidade
    from apps.pca.projecao import CAMADAS
    from apps.pca.servicos import consultas_fluxo

    exercicio_obj = Exercicio.objects.filter(ano=exercicio).first()
    if exercicio_obj is None:
        anos = list(Exercicio.objects.order_by("-ano").values_list("ano", flat=True))
        return Envelope(dados={"erro": "exercício inexistente", "exercicios": anos})

    uo_obj = None
    if unidade:
        uo_obj, alternativas = resolver_unidade(unidade)
        if uo_obj is None and alternativas:
            return Envelope(dados={"ambiguo": True, "alternativas": alternativas})
        if uo_obj is None:
            return Envelope(dados={"erro": "unidade não encontrada"})

    if mes is not None and ano is None:
        return Envelope(dados={"erro": "mês exige ano"})

    if ano is not None and not (exercicio_obj.ano <= ano <= exercicio_obj.ano + 5):
        return Envelope(dados={"erro": "ano fora do horizonte"})

    hoje = timezone.localdate()
    projecao, itens = consultas_fluxo.projecao_oficial(
        exercicio_obj,
        uo_id=uo_obj.id if uo_obj else None,
        cenario="base",
        indice=settings.PCA_INDICE_REAJUSTE_PADRAO,
        hoje=hoje,
    )

    def _linha_camadas(mapa_camadas):
        linha = {camada: str(mapa_camadas.get(camada, Decimal("0"))) for camada in CAMADAS}
        linha["total"] = str(
            sum((mapa_camadas.get(camada, Decimal("0")) for camada in CAMADAS), Decimal("0"))
        )
        return linha

    por_ano = {str(a): _linha_camadas(mapa) for a, mapa in projecao.por_ano.items()}
    totais_acumulados = {camada: Decimal("0") for camada in CAMADAS}
    for mapa in projecao.por_ano.values():
        for camada in CAMADAS:
            totais_acumulados[camada] += mapa.get(camada, Decimal("0"))
    totais = {camada: str(valor) for camada, valor in totais_acumulados.items()}
    totais["total"] = str(sum(totais_acumulados.values(), Decimal("0")))

    dados = {
        "exercicio": exercicio,
        "cenario": "base",
        "indice": settings.PCA_INDICE_REAJUSTE_PADRAO,
        "horizonte": {
            "inicio": hoje.replace(day=1).isoformat(),
            "fim": f"{exercicio_obj.ano + 5}-12-31",
        },
        "por_ano": por_ano,
        "totais": totais,
        "premissas": list(projecao.premissas)[:10],
        "sem_dado": len(projecao.sem_dado),
    }
    if unidade:
        dados["unidade"] = uo_obj.nome

    referencias = [
        {
            "rotulo": "Fluxo de caixa (oficial)",
            "url": (
                reverse("pca:analise_fluxo")
                + "?"
                + urlencode(
                    {
                        "exercicio": exercicio,
                        "cenario": "base",
                        **({"ano": ano} if ano is not None else {}),
                        **({"mes": mes} if mes is not None else {}),
                        **({"uo": uo_obj.id} if uo_obj else {}),
                    }
                )
            ),
        }
    ]

    if ano is not None:
        mapa_itens = {item["item_pca"]: item for item in itens}
        uo_nomes = dict(Unidade.objects.values_list("id", "nome"))
        agregados: dict[int, dict] = {}
        for parcela in projecao.parcelas:
            ano_p, mes_p = (int(v) for v in parcela.competencia.split("-"))
            if ano_p != ano:
                continue
            if mes is not None and mes_p != mes:
                continue
            agr = agregados.setdefault(
                parcela.item_pca,
                {camada: Decimal("0") for camada in CAMADAS},
            )
            agr[parcela.camada] += parcela.valor

        linhas_recorte = []
        for item_pca, mapa_camadas in agregados.items():
            item_info = mapa_itens.get(item_pca)
            processo = item_info["_processo"] if item_info else None
            linhas_recorte.append(
                {
                    "item_pca": item_pca,
                    "objeto": processo.descricao_objeto[:160] if processo else "",
                    "unidade": (
                        uo_nomes.get(item_info["uo"], "Sem unidade")
                        if item_info
                        else "Sem unidade"
                    ),
                    "total": str(sum(mapa_camadas.values(), Decimal("0"))),
                }
            )
        linhas_recorte.sort(key=lambda linha: Decimal(linha["total"]), reverse=True)

        total_recorte = sum(
            (Decimal(linha["total"]) for linha in linhas_recorte), Decimal("0")
        )
        por_camada_recorte = {camada: Decimal("0") for camada in CAMADAS}
        for mapa_camadas in agregados.values():
            for camada in CAMADAS:
                por_camada_recorte[camada] += mapa_camadas.get(camada, Decimal("0"))

        dados["recorte"] = {
            "ano": ano,
            "mes": mes,
            "por_camada": {camada: str(valor) for camada, valor in por_camada_recorte.items()},
            "total": str(total_recorte),
            "itens": linhas_recorte[:20],
            "total_itens": len(linhas_recorte),
            "truncado": len(linhas_recorte) > 20,
        }
        if linhas_recorte:
            referencias.append(
                {
                    "rotulo": "Contratações neste recorte",
                    "url": referencias[0]["url"],
                }
            )

    return Envelope(
        dados=dados,
        referencias=referencias,
        atualidade={"pca_consultado_em": hoje.isoformat(), "sei": None, "indice": None},
    )


def memoria_de_calculo(usuario, *, exercicio, item) -> Envelope:
    """`pca.ver_analises` — memória de cálculo OFICIAL de um
    item, truncada explicitamente em 60 linhas (spec §6). Item inexistente
    é erro; item existente sem projeção suficiente é `sem_dado` — nunca a
    mesma coisa que zero."""
    if not usuario.has_perm("pca.ver_analises"):
        return Envelope(
            dados={
                "recusa": "requer a permissão de análises estratégicas (pca.ver_analises)"
            },
            sem_permissao=True,
        )

    from apps.catalogo.models import Exercicio
    from apps.pca.models import Processo
    from apps.pca.projecao import CAMADAS
    from apps.pca.servicos import consultas_fluxo

    exercicio_obj = Exercicio.objects.filter(ano=exercicio).first()
    if exercicio_obj is None:
        anos = list(Exercicio.objects.order_by("-ano").values_list("ano", flat=True))
        return Envelope(dados={"erro": "exercício inexistente", "exercicios": anos})

    existe = Processo.objects.filter(exercicio=exercicio_obj, item_pca=item).exists()
    if not existe:
        return Envelope(dados={"erro": f"item {item} não encontrado no exercício {exercicio}"})

    memoria = consultas_fluxo.memoria_oficial(exercicio_obj, item)

    referencias = [
        {
            "rotulo": f"Memória de cálculo do item {item}",
            "url": (
                reverse("pca:analise_fluxo_memoria", args=[item])
                + f"?exercicio={exercicio}&cenario=base"
            ),
        },
        {
            "rotulo": f"Ficha do item {item}",
            "url": reverse("pca:detalhe_processo", args=[exercicio, item]),
        },
    ]

    if memoria is None:
        return Envelope(
            dados={
                "item_pca": item,
                "sem_dado": True,
                "motivo": "item sem projeção no horizonte",
            },
            referencias=referencias,
            atualidade=_atualidade_pca(),
        )

    linhas_ordenadas = sorted(memoria.linhas, key=lambda l: l.competencia)
    total_linhas = len(linhas_ordenadas)
    linhas = [
        {
            "competencia": l.competencia,
            "camada": l.camada,
            "valor": str(l.valor),
            "formula": l.formula,
        }
        for l in linhas_ordenadas[:60]
    ]
    totais_por_camada = {
        camada: str(sum((l.valor for l in memoria.linhas if l.camada == camada), Decimal("0")))
        for camada in CAMADAS
    }

    dados = {
        "item_pca": item,
        "fontes": list(memoria.fontes),
        "premissas": list(memoria.premissas),
        "descartados": list(memoria.descartados),
        "totais_por_camada": totais_por_camada,
        "linhas": linhas,
        "total_linhas": total_linhas,
        "truncado": total_linhas > 60,
    }
    return Envelope(dados=dados, referencias=referencias, atualidade=_atualidade_pca())


def contratos_a_vencer(usuario, *, exercicio, horizonte="todos") -> Envelope:
    """`contratos_a_vencer` (C04) exige as DUAS permissões da tela Prazos, `pca.ver_analises` e `pca.view_acompanhamento`
    — nomeando a(s) ausente(s) sem consultar nada quando falta qualquer uma. Serviço
    canônico da Fase 38 (`apps.pca.servicos.contratos`) — nenhum `Case/
    When` de destino duplicado aqui."""
    faltantes = [
        chave
        for chave in ("pca.ver_analises", "pca.view_acompanhamento")
        if not usuario.has_perm(chave)
    ]
    if faltantes:
        return Envelope(
            dados={"recusa": f"requer a(s) permissão(ões): {', '.join(faltantes)}"},
            sem_permissao=True,
        )

    from apps.catalogo.models import Exercicio
    from apps.pca.projecao.virada import Destino
    from apps.pca.sei import execucoes
    from apps.pca.servicos import contratos as contratos_svc

    exercicio_obj = Exercicio.objects.filter(ano=exercicio).first()
    if exercicio_obj is None:
        anos = list(Exercicio.objects.order_by("-ano").values_list("ano", flat=True))
        return Envelope(dados={"erro": "exercício inexistente", "exercicios": anos})

    horizonte_normalizado = (
        horizonte if horizonte in contratos_svc.VENCE_OPCOES else "todos"
    )

    resultado = contratos_svc.contratos_a_vencer(exercicio_obj, horizonte_normalizado)
    kpis_resultado = resultado.kpis
    total_grupos = (
        kpis_resultado["encerramento_n"]
        + kpis_resultado["renovacao_n"]
        + kpis_resultado["renovacao_n1"]
        + kpis_resultado["vigente_n1"]
    )

    itens_qs = list(resultado.queryset.select_related("unidade_organizacional")[:20])
    itens = [
        {
            "item_pca": p.item_pca,
            "objeto": p.descricao_objeto[:160],
            "unidade": p.unidade_organizacional.nome,
            "fornecedor": p.fornecedor_razao_social or None,
            "vigencia_fim": p.vigencia_fim.isoformat() if p.vigencia_fim else None,
            "renovacao_prevista": p.renovacao_prevista,
            "destino": p.destino,
            "destino_rotulo": (
                Destino.por_chave(p.destino).rotulo
                if Destino.por_chave(p.destino) is not None
                else p.destino
            ),
        }
        for p in itens_qs
    ]
    total_itens = resultado.queryset.count()

    dados = {
        "exercicio": exercicio,
        "horizonte": horizonte_normalizado,
        "hoje": resultado.hoje.isoformat(),
        "kpis": {
            "total": kpis_resultado["total"],
            "encerramento_n": kpis_resultado["encerramento_n"],
            "renovacao_n": kpis_resultado["renovacao_n"],
            "renovacao_n1": kpis_resultado["renovacao_n1"],
            "vigente_n1": kpis_resultado["vigente_n1"],
            "por_destino": kpis_resultado["por_destino"],
        },
        "invariante": kpis_resultado["total"] == total_grupos,
        "itens": itens,
        "total_itens": total_itens,
        "truncado": total_itens > len(itens),
        "observacao": (
            "população = itens ativos com vigência informada e regime "
            "diferente de único; itens sem vigência não entram"
        ),
    }
    if kpis_resultado["total"] == 0:
        dados["mensagem"] = "nenhum item com contrato acompanhado neste exercício"

    url = (
        reverse("pca:analise_prazos")
        + "?"
        + urlencode({"exercicio": exercicio, "vence": horizonte_normalizado})
    )

    sei_agregado = _atualidade_sei_agregada([p.item_pca for p in itens_qs], exercicio, execucoes)

    return Envelope(
        dados=dados,
        referencias=[{"rotulo": "Prazos — Contratos a vencer", "url": url}],
        atualidade={
            "pca_consultado_em": timezone.now().isoformat(),
            "sei": sei_agregado,
            "indice": None,
        },
    )


_CAMPOS_IGNORADOS_HISTORICO = frozenset({"atualizado_em"})
_MAX_ITENS_ATUALIZACOES = 30
_MAX_DIAS_ATUALIZACOES = 90


def _origem_historico(email, email_robo) -> str:
    if not email:
        return "sistema"
    if email == email_robo:
        return "sincronização com o SEI"
    if email == "importador@pca.local":
        return "importação da planilha"
    return "equipe"


def _valor_legivel(valor):
    if valor is None or valor == "":
        return None
    if isinstance(valor, datetime) and timezone.is_aware(valor):
        return timezone.localtime(valor).isoformat(timespec="minutes")
    if isinstance(valor, (date, datetime, Decimal)):
        return _serializar(valor)
    texto = str(valor)
    return texto if len(texto) <= 80 else texto[:77] + "…"


_ORIGENS_ATUALIZACAO = ("equipe", "sincronização com o SEI", "importação da planilha", "sistema", "acompanhamento")
_TETO_ATUALIZACOES_BYTES = 10 * 1024


def atualizacoes_recentes(usuario, *, exercicio, dias=7, data=None, unidade=None, origem=None) -> Envelope:
    """Quais itens do exercício mudaram nos últimos `dias`
    — lido da trilha `simple_history` de `Processo` (edição da equipe, robô
    SEI, regras automáticas) e, só com `pca.view_acompanhamento`, dos
    acompanhamentos criados no período. Consultas em número constante: o
    diff campo a campo é feito sobre as linhas de histórico já carregadas
    (uma consulta), nunca `prev_record` por linha. Por item, só a mudança
    LÍQUIDA de cada campo (primeiro "antes" → último "depois") — o robô SEI
    toca quase todos os itens a cada varredura e o envelope precisa caber
    no teto de bytes do agente."""
    from apps.catalogo.models import Exercicio
    from apps.pca.models import Acompanhamento, Processo

    exercicio_obj = Exercicio.objects.filter(ano=exercicio).first()
    if exercicio_obj is None:
        anos = list(Exercicio.objects.order_by("-ano").values_list("ano", flat=True))
        return Envelope(dados={"erro": "exercício inexistente", "exercicios": anos})

    try:
        dias_efetivos = int(dias) if dias else 7
    except (TypeError, ValueError):
        dias_efetivos = 7
    dias_efetivos = min(max(dias_efetivos, 1), _MAX_DIAS_ATUALIZACOES)
    # Dias de CALENDÁRIO no fuso local: `dias=1` é "hoje desde 00:00", não
    # as últimas 24 h; `data` recorta um único dia (ex.: "ontem").
    hoje = timezone.localdate()
    if data:
        try:
            dia_inicial = date.fromisoformat(str(data))
        except ValueError:
            return Envelope(dados={"erro": "data inválida (use AAAA-MM-DD)"})
        dia_final = dia_inicial
    else:
        dia_inicial = hoje - timedelta(days=dias_efetivos - 1)
        dia_final = hoje
    fuso = timezone.get_current_timezone()
    desde = datetime.combine(dia_inicial, datetime.min.time(), tzinfo=fuso)
    ate = datetime.combine(dia_final + timedelta(days=1), datetime.min.time(), tzinfo=fuso)

    if origem and origem not in _ORIGENS_ATUALIZACAO:
        return Envelope(dados={"erro": "origem inválida", "origens": list(_ORIGENS_ATUALIZACAO)})

    processos_qs = Processo.objects.filter(exercicio=exercicio_obj)
    filtros = {"exercicio": exercicio, "de": dia_inicial.isoformat(), "ate": dia_final.isoformat()}
    if origem:
        filtros["origem"] = origem
    if unidade:
        unidade_obj, alternativas = resolver_unidade(unidade)
        if unidade_obj is None and alternativas:
            return Envelope(dados={"ambiguo": True, "alternativas": alternativas})
        if unidade_obj is None:
            return Envelope(dados={"erro": "unidade não encontrada"})
        processos_qs = processos_qs.filter(unidade_organizacional=unidade_obj)
        filtros["unidade"] = unidade_obj.nome

    Historico = Processo.history.model
    ids_alterados = set(
        Historico.objects.filter(
            id__in=processos_qs.values("pk"), history_date__gte=desde, history_date__lt=ate
        ).values_list("id", flat=True)
    )
    ve_acompanhamentos = usuario.has_perm("pca.view_acompanhamento")
    acompanhamentos_por_processo: dict[int, list] = {}
    if ve_acompanhamentos and origem in (None, "acompanhamento"):
        HistAcomp = Acompanhamento.history.model
        for linha in (
            HistAcomp.objects.filter(
                processo_id__in=processos_qs.values("pk"),
                history_type="+",
                history_date__gte=desde,
                history_date__lt=ate,
            )
            .order_by("history_date")
            .values("processo_id", "history_date", "referencia_data", "evento")
        ):
            acompanhamentos_por_processo.setdefault(linha["processo_id"], []).append(linha)

    campos = [
        f for f in Processo._meta.concrete_fields
        if f.attname not in _CAMPOS_IGNORADOS_HISTORICO and not f.primary_key
    ]
    email_robo = getattr(settings, "SEI_USUARIO_TECNICO_EMAIL", None) or "robo-sei@pca.local"

    linhas_por_processo: dict[int, list] = {}
    if origem != "acompanhamento":
        for linha in (
            Historico.objects.filter(id__in=ids_alterados)
            .filter(history_date__lt=ate)
            .order_by("id", "history_date", "history_id")
            .values("id", "history_date", "history_type", "history_user__email",
                    *[f.attname for f in campos])
        ):
            linhas_por_processo.setdefault(linha["id"], []).append(linha)

    por_item: dict[int, dict] = {}
    for processo_id, linhas in linhas_por_processo.items():
        anterior = None
        for linha in linhas:
            linha_origem = _origem_historico(linha["history_user__email"], email_robo)
            if linha["history_date"] >= desde and (origem is None or origem == linha_origem):
                if linha["history_type"] in ("+", "-") or anterior is None:
                    evento = "item excluído" if linha["history_type"] == "-" else "item criado"
                    mudancas = {evento: (None, None)}
                else:
                    mudancas = {}
                    for f in campos:
                        if linha[f.attname] == anterior[f.attname]:
                            continue
                        if f.is_relation:
                            mudancas[str(f.verbose_name)] = (None, None)
                        else:
                            rotulos = dict(f.flatchoices) if f.choices else {}
                            mudancas[str(f.verbose_name)] = (
                                rotulos.get(anterior[f.attname], anterior[f.attname]),
                                rotulos.get(linha[f.attname], linha[f.attname]),
                            )
                if mudancas:
                    registro = por_item.setdefault(
                        processo_id, {"campos": {}, "origens": set(), "n_alteracoes": 0}
                    )
                    registro["origens"].add(linha_origem)
                    registro["n_alteracoes"] += 1
                    registro["ultima"] = linha["history_date"]
                    registro["linha"] = linha
                    for rotulo, (antes, depois) in mudancas.items():
                        if rotulo in registro["campos"]:
                            registro["campos"][rotulo][1] = depois
                        else:
                            registro["campos"][rotulo] = [antes, depois]
            anterior = linha

    for processo_id, acomps in acompanhamentos_por_processo.items():
        registro = por_item.setdefault(
            processo_id, {"campos": {}, "origens": set(), "n_alteracoes": 0}
        )
        registro["origens"].add("acompanhamento")
        registro["acompanhamentos_novos"] = [
            {"data": a["referencia_data"].isoformat(), "evento": (a["evento"] or "")[:120]}
            for a in acomps[-2:]
        ]
        registro["n_acompanhamentos"] = len(acomps)
        ultima = acomps[-1]["history_date"]
        if registro.get("ultima") is None or ultima > registro["ultima"]:
            registro["ultima"] = ultima

    info = {
        p["pk"]: p
        for p in Processo.objects.filter(pk__in=por_item.keys()).values(
            "pk", "item_pca", "descricao_objeto", "unidade_organizacional__nome"
        )
    }
    por_origem: dict[str, int] = {}
    por_campo: dict[str, int] = {}
    for registro in por_item.values():
        for nome_origem in registro["origens"]:
            por_origem[nome_origem] = por_origem.get(nome_origem, 0) + 1
        for rotulo in registro["campos"]:
            por_campo[rotulo] = por_campo.get(rotulo, 0) + 1

    ordenados = sorted(por_item.items(), key=lambda par: par[1]["ultima"], reverse=True)
    itens = []
    for processo_id, registro in ordenados[:_MAX_ITENS_ATUALIZACOES]:
        p = info.get(processo_id)
        if p is None:  # item excluído no período — identifica pelo histórico
            linha = registro["linha"]
            p = {"item_pca": linha["item_pca"], "descricao_objeto": linha["descricao_objeto"],
                 "unidade_organizacional__nome": None}
        item = {
            "item_pca": p["item_pca"],
            "objeto": p["descricao_objeto"][:80],
            "unidade": p["unidade_organizacional__nome"],
            "ultima_atualizacao": timezone.localtime(registro["ultima"]).isoformat(timespec="minutes"),
            "origens": sorted(registro["origens"]),
            "campos_alterados": [
                {"campo": rotulo, "antes": _valor_legivel(antes), "depois": _valor_legivel(depois)}
                if (antes, depois) != (None, None) else {"campo": rotulo}
                for rotulo, (antes, depois) in list(registro["campos"].items())[:6]
            ],
        }
        if "acompanhamentos_novos" in registro:
            item["acompanhamentos_novos"] = registro["acompanhamentos_novos"]
            item["n_acompanhamentos"] = registro["n_acompanhamentos"]
        itens.append(item)

    dados = {
        "exercicio": exercicio,
        "filtros": filtros,
        "periodo": (
            f"{dia_inicial:%d/%m/%Y}" if dia_inicial == dia_final
            else f"{dia_inicial:%d/%m/%Y} a {dia_final:%d/%m/%Y}"
        ),
        "total_itens_atualizados": len(por_item),
        "itens_por_origem": por_origem,
        "itens_por_campo": dict(sorted(por_campo.items(), key=lambda par: -par[1])[:10]),
        "itens": itens,
        "como_ver_no_sistema": (
            "a ficha de cada item (link nas referências) mostra a linha do "
            "tempo de acompanhamentos; as alterações de campo (da equipe e da "
            "sincronização com o SEI) não têm tela própria — basta perguntar aqui ao "
            "Assistente, informando o período, a unidade ou a origem"
        ),
    }
    sem_permissao = False
    if not ve_acompanhamentos:
        dados["aviso_permissao"] = (
            "Sem permissão para consultar: acompanhamentos registrados no período"
        )
        sem_permissao = True
    if not por_item:
        dados["mensagem"] = f"nenhum item alterado em {dados['periodo']}"

    # Cabe no teto do agente: corta itens do fim (os menos recentes) até
    # o envelope caber — o total integral continua em `total_itens_atualizados`.
    while itens and len(json.dumps(dados, ensure_ascii=False, default=_serializar).encode()) > _TETO_ATUALIZACOES_BYTES:
        itens.pop()
    dados["exibidos"] = len(itens)

    referencias = [
        {
            "rotulo": f"Item {item['item_pca']}",
            "url": reverse("pca:detalhe_processo", args=[exercicio, item["item_pca"]]),
        }
        for item in itens[:10]
        if item["unidade"] is not None
    ]
    return Envelope(
        dados=dados,
        referencias=referencias,
        atualidade=_atualidade_pca(),
        sem_permissao=sem_permissao,
        truncado=len(por_item) > len(itens),
    )


ESQUEMAS: dict[str, dict] = {
    "consultar_processos": cliente_mod.esquema_estrito(
        "consultar_processos",
        (
            "Consulta processos do PCA por exercício, unidade organizacional, "
            "situação, fornecedor, trecho do objeto, tipo de contratação ou "
            "categoria (Material/Serviços/Solução de TIC — use `categoria` "
            "para 'o que é compra e o que é serviço', não busca de palavra no "
            "objeto). Devolve total integral e até 20 itens, com link para a "
            "lista completa filtrada. Não traz signatários, datas de "
            "assinatura nem texto de contrato — para isso, chame "
            "`ficha(exercicio, item)` com o item encontrado."
        ),
        {
            "exercicio": {
                "type": ["integer", "null"],
                "description": "Ano do PCA; null usa o exercício da página atual.",
            },
            "unidade": {
                "type": ["string", "null"],
                "description": "Nome (ou trecho) da unidade organizacional.",
            },
            "situacao": {
                "type": ["string", "null"],
                "description": "no_prazo, atrasado, em_tramitacao ou concluido.",
            },
            "fornecedor": {
                "type": ["string", "null"],
                "description": "Trecho da razão social do fornecedor.",
            },
            "texto_objeto": {
                "type": ["string", "null"],
                "description": "Trecho da descrição do objeto contratado.",
            },
            "tipo": {
                "type": ["string", "null"],
                "description": "Nome do tipo de contratação.",
            },
            "categoria": {
                "type": ["string", "null"],
                "description": (
                    "Categoria do objeto: Material (bens/compras), Serviços ou "
                    "Solução de TIC. Use para perguntas 'o que é compra e o que "
                    "é serviço' — não confundir com `tipo` ou `texto_objeto`."
                ),
            },
            "sem_processo_sei": {
                "type": ["boolean", "null"],
                "description": (
                    "true = só itens sem nenhum nº de processo SEI (nunca "
                    "atualizados automaticamente); null não filtra."
                ),
            },
            "limite": {
                "type": "integer",
                "description": "Máximo de itens detalhados na resposta (1 a 20).",
            },
        },
        [],
    ),
    "ficha": cliente_mod.esquema_estrito(
        "ficha",
        (
            "Traz a ficha completa de um item do PCA: campos públicos, "
            "instrumentos contratuais (contrato/aditivo/apostilamento), "
            "signatários e links do SEI armazenados. Os últimos acompanhamentos "
            "de reunião só aparecem para quem tem permissão de vê-los. Use "
            "sempre que a pergunta for sobre assinatura, signatário, vigência, "
            "valor contratado ou onde o processo está no SEI."
        ),
        {
            "exercicio": {
                "type": ["integer", "null"],
                "description": "Ano do PCA; null usa o exercício da página atual.",
            },
            "item": {
                "type": "integer",
                "description": "Número do item do PCA (item_pca).",
            },
        },
        [],
    ),
    "fluxo_de_caixa": cliente_mod.esquema_estrito(
        "fluxo_de_caixa",
        (
            "Projeção oficial do fluxo de caixa por ano (e, opcionalmente, por "
            "mês/unidade), cenário base, índice padrão do sistema — nunca "
            "rascunho de simulação. Mesmos números da tela 'Fluxo de caixa'."
        ),
        {
            "exercicio": {
                "type": ["integer", "null"],
                "description": "Ano do PCA; null usa o exercício da página atual.",
            },
            "ano": {
                "type": ["integer", "null"],
                "description": (
                    "Ano do recorte, dentro do horizonte do exercício "
                    "(exercicio..exercicio+5); null não recorta."
                ),
            },
            "mes": {
                "type": ["integer", "null"],
                "description": "Mês (1-12) do recorte; exige 'ano' informado.",
            },
            "unidade": {
                "type": ["string", "null"],
                "description": "Nome (ou trecho) da unidade organizacional.",
            },
        },
        [],
    ),
    "memoria_de_calculo": cliente_mod.esquema_estrito(
        "memoria_de_calculo",
        (
            "Memória de cálculo oficial de um item do PCA: de onde vem cada "
            "parcela do fluxo de caixa projetado (competência, camada, valor, "
            "fórmula). Até 60 linhas; truncamento explícito quando há mais."
        ),
        {
            "exercicio": {
                "type": ["integer", "null"],
                "description": "Ano do PCA; null usa o exercício da página atual.",
            },
            "item": {
                "type": "integer",
                "description": "Número do item do PCA (item_pca).",
            },
        },
        [],
    ),
    "contratos_a_vencer": cliente_mod.esquema_estrito(
        "contratos_a_vencer",
        (
            "KPIs e amostra de itens com contrato a vencer/renovar na virada "
            "de exercício (seção 'Prazos' da tela de Análises) — exige "
            "permissão de análises estratégicas E de acompanhamento."
        ),
        {
            "exercicio": {
                "type": ["integer", "null"],
                "description": "Ano do PCA; null usa o exercício da página atual.",
            },
            "horizonte": {
                "type": "string",
                "enum": ["todos", "vencidos", "90", "180", "365", "N", "N+1"],
                "description": "Recorte de vencimento; 'todos' não filtra.",
            },
        },
        [],
    ),
    "atualizacoes_recentes": cliente_mod.esquema_estrito(
        "atualizacoes_recentes",
        (
            "Lista os itens do PCA que tiveram alguma atualização num período "
            "de dias de calendário (hoje = dias=1, desde 00:00) ou num dia "
            "específico (`data`): campos alterados (antes → depois), quem originou (equipe, "
            "sincronização com o SEI, importação) e acompanhamentos registrados no período. "
            "Use para 'o que mudou', 'quais processos foram atualizados', "
            "'novidades da semana', 'o que a sincronização com o SEI alterou'."
        ),
        {
            "exercicio": {
                "type": ["integer", "null"],
                "description": "Ano do PCA; null usa o exercício da página atual.",
            },
            "dias": {
                "type": "integer",
                "description": (
                    "Dias de calendário até hoje, inclusive: 1 = só hoje, "
                    "2 = ontem e hoje, 7 = últimos 7 dias (1 a 90). Ignorado "
                    "quando `data` é informada."
                ),
            },
            "data": {
                "type": ["string", "null"],
                "description": "Um dia específico, AAAA-MM-DD (ex.: ontem); null usa `dias`.",
            },
            "unidade": {
                "type": ["string", "null"],
                "description": "Nome (ou trecho) da unidade organizacional.",
            },
            "origem": {
                "type": ["string", "null"],
                "enum": ["equipe", "sincronização com o SEI", "importação da planilha", "sistema", "acompanhamento", None],
                "description": "Restringe à origem da alteração; null traz todas.",
            },
        },
        [],
    ),
    "buscar_texto": cliente_mod.esquema_estrito(
        "buscar_texto",
        (
            "Busca semântica em texto livre: acompanhamentos de reunião, o "
            "corpo de instrumentos do SEI já coletados (contrato, aditivo, "
            "apostilamento) e a documentação oficial do sistema. A fonte "
            "'docs' é a documentação oficial das telas e indicadores do "
            "sistema (Fluxo de caixa, Estatísticas, Prazos: lead time, "
            "Kaplan-Meier, risco de atraso; como registrar acompanhamento; "
            "sobre o sistema e o autor). Devolve até "
            "6 trechos com referência e escore, respeitando a permissão de "
            "quem pergunta — nunca busca em SQL/dados estruturados."
        ),
        {
            "pergunta": {
                "type": "string",
                "description": "O que buscar, em português (1 a 500 caracteres).",
            },
            "fonte": {
                "type": ["string", "null"],
                "enum": ["acompanhamento", "sei", "docs", None],
                "description": "Restringe a uma fonte; null busca nas três.",
            },
            "exercicio": {
                "type": ["integer", "null"],
                "description": "Filtra por ano do PCA; null busca em todos os anos.",
            },
            "item": {
                "type": ["integer", "null"],
                "description": "Filtra pelo número do item do PCA; null não filtra.",
            },
        },
        [],
    ),
    "consultar_sql": cliente_mod.esquema_estrito(
        "consultar_sql",
        (
            "Executa UMA consulta SQL `SELECT` somente leitura sobre o banco "
            "inteiro do PCA (exceto a tabela de sessão e a coluna de senha dos "
            "usuários). Use para agregação, ranking, soma, contagem, cruzamento "
            "entre tabelas ou qualquer lista que as outras ferramentas não "
            "cobrem — elas continuam preferíveis para ficha de item, fluxo de "
            "caixa, memória de cálculo, contratos a vencer, alterações "
            "recentes e busca em texto (elas anexam links; esta não). Recusa "
            "escrita, PRAGMA, ATTACH, múltiplas instruções e tabela/coluna "
            "bloqueada com um erro legível — corrija e tente de novo.\n\n"
        )
        + esquema.catalogo(),
        {
            "sql": {
                "type": "string",
                "description": "Uma única instrução SELECT (ou WITH ... SELECT), em SQL SQLite.",
            },
        },
        [],
    ),
}

FUNCOES = {
    "consultar_processos": consultar_processos,
    "ficha": ficha,
    "fluxo_de_caixa": fluxo_de_caixa,
    "memoria_de_calculo": memoria_de_calculo,
    "contratos_a_vencer": contratos_a_vencer,
    "atualizacoes_recentes": atualizacoes_recentes,
    "buscar_texto": buscar_texto,
    "consultar_sql": consultar_sql,
}


def executar(nome, argumentos_json, *, usuario, exercicio_padrao, contexto: ContextoExecucao = None) -> Envelope:
    """Dispatch por nome na allowlist `FUNCOES`. Ferramenta fora da
    allowlist, JSON inválido ou chave fora do esquema contam como
    invocação (quem soma no orçamento é `agente.py`), mas NUNCA executam
    consulta nenhuma. `contexto` (opcional — retrocompatível com
    chamadas que não o passam) carrega `cliente`/`embeddings_restantes`
    para `buscar_texto`; ferramentas sem exercício "da página" (`buscar_
    texto`, cujo `exercicio` é só um filtro opcional) não passam pelo
    resolvedor de exercício genérico abaixo."""
    if nome not in FUNCOES:
        return Envelope(dados={"erro": "ferramenta desconhecida"})

    try:
        argumentos = json.loads(argumentos_json) if argumentos_json else {}
        if not isinstance(argumentos, dict):
            raise ValueError("argumentos não são um objeto JSON")
    except (json.JSONDecodeError, ValueError, TypeError):
        return Envelope(dados={"erro": "argumentos inválidos"})

    propriedades = set(ESQUEMAS[nome]["function"]["parameters"]["properties"].keys())
    if not set(argumentos.keys()) <= propriedades:
        return Envelope(dados={"erro": "argumentos inválidos"})

    if nome == "buscar_texto":
        # QA 30/09/2026 (periferia nº9) — uma ferramenta que lança exceção
        # (ex.: índice corrompido) não pode derrubar a resposta inteira nem
        # deixar a chamada já cobrada no orçamento sem envelope de volta.
        try:
            return buscar_texto(usuario, contexto=contexto, **argumentos)
        except Exception as exc:
            return Envelope(dados={"erro": f"falha interna na ferramenta: {exc}"})

    if nome == "consultar_sql":
        # Mesmo tratamento de `buscar_texto` (QA 30/09/2026): sem argumento
        # `exercicio` (o SQL filtra o que quiser) e nunca deixa exceção
        # inesperada derrubar a resposta.
        try:
            return consultar_sql(usuario, **argumentos)
        except Exception as exc:
            return Envelope(dados={"erro": f"falha interna na ferramenta: {exc}"})

    exercicio_arg = argumentos.get("exercicio")
    exercicio_obj, aviso = resolver_exercicio_ferramenta(exercicio_arg, exercicio_padrao)
    if exercicio_obj is None:
        if exercicio_arg is not None:
            from apps.catalogo.models import Exercicio

            anos = list(Exercicio.objects.order_by("-ano").values_list("ano", flat=True))
            return Envelope(dados={"erro": "exercício inexistente", "exercicios": anos})
        return Envelope(dados={"erro": "nenhum exercício disponível"})

    kwargs = {chave: valor for chave, valor in argumentos.items() if chave != "exercicio"}
    if nome == "consultar_processos":
        kwargs.setdefault("limite", 20)
    try:
        envelope = FUNCOES[nome](usuario, exercicio=exercicio_obj.ano, **kwargs)
    except Exception as exc:
        return Envelope(dados={"erro": f"falha interna na ferramenta: {exc}"})
    if aviso:
        envelope.dados.setdefault("aviso", aviso)
    return envelope
