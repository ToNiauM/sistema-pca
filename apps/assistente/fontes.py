"""Fontes de texto do Assistente do PCA — extratores puros (sem `request`)
que devolvem `Trecho`s prontos para o índice semântico (A05/A09/A11/A12).

Três fontes, cada uma com sua própria permissão: `acompanhamento`
(observações de reunião — só `pca.view_acompanhamento`), `sei` (corpo dos
instrumentos contratuais já coletados pelo robô — autenticado, só
documentos vinculados a um item via `ProcessoSEI`) e `docs` (manifesto
FECHADO de 4 documentos — nunca `glob`). `fragmentar` respeita o teto de
2.400 bytes UTF-8 por trecho (nunca "800 tokens") com até 300
bytes de sobreposição, sempre em fronteira de palavra."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from django.urls import reverse

from apps.catalogo.utils import normalizar_nome
from apps.pca.sei.extracao import hash_texto as hash_texto_normalizado

FONTES = ("acompanhamento", "sei", "docs")
PERMISSAO_AUTENTICADO = ""
TETO_TRECHO_BYTES = 2400
SOBREPOSICAO_BYTES = 300
FRAGMENTADOR_VERSAO = 1

# Manifesto FECHADO — nunca uma varredura do diretório de docs por padrão
# de nome (A11/A12). Só estes 4 documentos entram no índice/na
# rota `assistente:documentacao`; qualquer outro arquivo de `docs/`
# (arquitetura, deployment, operação, documento de requisitos, planilhas) fica de fora por
# construção — a tupla abaixo é a ÚNICA fonte de quais arquivos existem.
# (Fase 43: `solicitacoes` entrou como 4º documento, explícito — o manifesto continua fechado.)
MANIFESTO_DOCS = (
    {
        "slug": "sobre-o-sistema",
        "arquivo": "docs/sobre-o-sistema.md",
        "titulo": "Sobre o sistema",
        "permissao": PERMISSAO_AUTENTICADO,
        "secoes_excluidas": ("Contato",),
    },
    {
        "slug": "assistente",
        "arquivo": "docs/assistente.md",
        "titulo": "Assistente do PCA",
        "permissao": PERMISSAO_AUTENTICADO,
        "secoes_excluidas": (),
    },
    {
        "slug": "analises-fluxo-de-caixa",
        "arquivo": "docs/analises-fluxo-de-caixa.md",
        "titulo": "Análises e fluxo de caixa",
        "permissao": "pca.ver_analises",
        "secoes_excluidas": (),
    },
    {
        "slug": "solicitacoes",
        "arquivo": "docs/solicitacoes.md",
        "titulo": "Solicitações das unidades",
        "permissao": PERMISSAO_AUTENTICADO,
        "secoes_excluidas": (),
    },
)

_ROTULOS_TIPO_SEI = {
    "contrato": "Contrato",
    "termo_aditivo": "Termo aditivo",
    "apostilamento": "Apostilamento",
}
_TIPOS_SEI_INDEXAVEIS = frozenset(_ROTULOS_TIPO_SEI)


class FonteIndisponivel(Exception):
    """Falha de leitura de uma fonte (ex.: arquivo do manifesto ausente) —
    aborta a geração inteira do índice ANTES de tocar nele."""


@dataclass(frozen=True)
class Trecho:
    fonte: str
    ref: str
    ordem: int
    titulo: str
    texto: str
    url: str | None
    exercicio: int | None
    item_pca: int | None
    permissao: str
    atualizado_em: str | None


def documento_do_manifesto(slug: str) -> dict | None:
    """Lookup por igualdade exata na tupla fechada — slug com `/`, `..` ou
    fora do manifesto devolve `None` (04: nenhum `open()`
    com valor de URL, só comparação de string)."""
    if not slug or "/" in slug or ".." in slug:
        return None
    for doc in MANIFESTO_DOCS:
        if doc["slug"] == slug:
            return doc
    return None


def secoes_markdown(texto: str, excluir: tuple[str, ...] = ()) -> list[tuple[str, str]]:
    """Divide `texto` por linhas que começam com `## ` (a linha `# ` inicial
    vira a seção 0), devolvendo `[(titulo, corpo), ...]` — `corpo` sem o
    título, com espaço em branco de borda removido. Seções cujo título
    (comparado sem acento/caixa via `normalizar_nome`) está em `excluir`
    não entram no resultado — usado para tirar `## Contato` de
    `docs/sobre-o-sistema.md` do índice/da página."""
    excluir_normalizado = {normalizar_nome(item) for item in excluir}
    secoes: list[tuple[str, list[str]]] = []
    for linha in (texto or "").splitlines():
        if linha.startswith("## "):
            secoes.append((linha[3:].strip(), []))
        elif linha.startswith("# "):
            secoes.append((linha[2:].strip(), []))
        elif secoes:
            secoes[-1][1].append(linha)
    return [
        (titulo, "\n".join(corpo).strip())
        for titulo, corpo in secoes
        if normalizar_nome(titulo) not in excluir_normalizado
    ]


def permissoes_autorizadas(usuario) -> frozenset:
    """Conjunto de valores de `permissao` que `usuario` pode ver — calculado
    ANTES de qualquer SELECT de candidatos. Usuário ausente/
    inativo/anônimo -> conjunto vazio (nenhuma fonte, nem a autenticada)."""
    if not usuario or not getattr(usuario, "is_authenticated", False) or not usuario.is_active:
        return frozenset()
    permitidas = {PERMISSAO_AUTENTICADO}
    if usuario.has_perm("pca.view_acompanhamento"):
        permitidas.add("pca.view_acompanhamento")
    if usuario.has_perm("pca.ver_analises"):
        permitidas.add("pca.ver_analises")
    return frozenset(permitidas)


def _janelas_por_palavra(paragrafo: str, teto: int, sobreposicao: int) -> list[str]:
    """Parte um parágrafo maior que `teto` em janelas por palavra (nunca
    corta um caractere multibyte), com sobreposição de até `sobreposicao`
    bytes também em fronteira de palavra."""
    palavras = paragrafo.split(" ")
    janelas: list[str] = []
    atual: list[str] = []
    atual_bytes = 0
    for palavra in palavras:
        tam = len((palavra + " ").encode("utf-8"))
        if atual and atual_bytes + tam > teto:
            janelas.append(" ".join(atual))
            mantidas: list[str] = []
            bytes_mantidos = 0
            for anterior in reversed(atual):
                tam_anterior = len((anterior + " ").encode("utf-8"))
                if bytes_mantidos + tam_anterior > sobreposicao:
                    break
                mantidas.insert(0, anterior)
                bytes_mantidos += tam_anterior
            atual = mantidas
            atual_bytes = bytes_mantidos
        atual.append(palavra)
        atual_bytes += tam
    if atual:
        janelas.append(" ".join(atual))
    return janelas


def fragmentar(
    texto: str, teto: int = TETO_TRECHO_BYTES, sobreposicao: int = SOBREPOSICAO_BYTES
) -> list[str]:
    """Divide `texto` em trechos de até `teto` bytes UTF-8, por parágrafo
    (linhas em branco); parágrafo maior que o teto é partido em janelas por
    palavra com sobreposição (`_janelas_por_palavra`). Texto vazio -> `[]`."""
    texto = (texto or "").strip()
    if not texto:
        return []
    paragrafos = [p.strip() for p in texto.split("\n\n") if p.strip()]
    if not paragrafos:
        return []

    trechos: list[str] = []
    acumulado = ""
    for paragrafo in paragrafos:
        candidato = f"{acumulado}\n\n{paragrafo}" if acumulado else paragrafo
        if len(candidato.encode("utf-8")) <= teto:
            acumulado = candidato
            continue
        if acumulado:
            trechos.append(acumulado)
            acumulado = ""
        if len(paragrafo.encode("utf-8")) <= teto:
            acumulado = paragrafo
        else:
            trechos.extend(_janelas_por_palavra(paragrafo, teto, sobreposicao))
    if acumulado:
        trechos.append(acumulado)
    return trechos


def extrair_acompanhamentos() -> list[Trecho]:
    """`Acompanhamento`/`EventoFinanceiro` com texto livre não vazio, de
    processos ativos — só `pca.view_acompanhamento`."""
    from apps.pca.models import Acompanhamento, Estado, EventoFinanceiro

    trechos: list[Trecho] = []

    qs = (
        Acompanhamento.objects.select_related("processo__exercicio")
        .filter(processo__estado=Estado.ATIVO)
        .order_by("processo_id", "referencia_data", "id")
    )
    for acompanhamento in qs:
        if not (acompanhamento.evento or acompanhamento.situacao_informada):
            continue
        ano = acompanhamento.processo.exercicio.ano
        item = acompanhamento.processo.item_pca
        prazo = (
            acompanhamento.prazo_prometido.strftime("%d/%m/%Y")
            if acompanhamento.prazo_prometido
            else "não informado"
        )
        texto = (
            f"Reunião de {acompanhamento.referencia_data.strftime('%d/%m/%Y')} — "
            f"item {item} (PCA {ano}): {acompanhamento.evento}. "
            f"Situação informada: {acompanhamento.situacao_informada}. "
            f"Prazo prometido: {prazo}"
        )
        url = reverse("pca:detalhe_processo", args=[ano, item])
        trechos.append(
            Trecho(
                fonte="acompanhamento",
                ref=f"ac:{ano}/{item}/{acompanhamento.pk}",
                ordem=0,
                titulo=f"Acompanhamento — item {item} (PCA {ano})",
                texto=texto,
                url=url,
                exercicio=ano,
                item_pca=item,
                permissao="pca.view_acompanhamento",
                atualizado_em=acompanhamento.referencia_data.isoformat(),
            )
        )

    qs_eventos = EventoFinanceiro.objects.select_related("processo__exercicio").filter(
        processo__estado=Estado.ATIVO
    )
    for evento in qs_eventos:
        if not evento.observacao:
            continue
        ano = evento.processo.exercicio.ano
        item = evento.processo.item_pca
        data_texto = evento.data.strftime("%d/%m/%Y") if evento.data else "data não informada"
        texto = (
            f"Observação do evento financeiro {evento.get_tipo_display()} de "
            f"{data_texto} — item {item} (PCA {ano}): {evento.observacao}"
        )
        url = reverse("pca:detalhe_processo", args=[ano, item])
        trechos.append(
            Trecho(
                fonte="acompanhamento",
                ref=f"ef:{ano}/{item}/{evento.pk}",
                ordem=0,
                titulo=f"Evento financeiro — item {item} (PCA {ano})",
                texto=texto,
                url=url,
                exercicio=ano,
                item_pca=item,
                permissao="pca.view_acompanhamento",
                atualizado_em=evento.data.isoformat() if evento.data else None,
            )
        )
    return trechos


def extrair_sei() -> list[Trecho]:
    """Corpo dos instrumentos contratuais (contrato/termo aditivo/
    apostilamento) já coletados pelo robô SEI, só de números vinculados a
    algum item via `ProcessoSEI` de um processo ativo — autenticado
    (`permissao=""`), texto é dado não confiável (01)."""
    from apps.pca.models import Estado, ProcessoSEI
    from apps.pca.sei import execucoes
    from apps.pca.templatetags.sei_links import url_processo_sei

    cache = execucoes.ler_cache()
    processos_cache = cache.get("processos", {})
    trechos: list[Trecho] = []

    qs = ProcessoSEI.objects.select_related("processo__exercicio").filter(
        processo__estado=Estado.ATIVO
    )
    for numero_sei in qs:
        entrada = processos_cache.get(numero_sei.numero_sei)
        if not entrada:
            continue
        ano = numero_sei.processo.exercicio.ano
        item = numero_sei.processo.item_pca
        for documento in entrada.get("documentos_contratuais") or []:
            if documento.get("tipo") not in _TIPOS_SEI_INDEXAVEIS:
                continue
            texto_corpo = documento.get("texto_corpo")
            if not texto_corpo:
                continue
            assinaturas = documento.get("assinaturas") or []
            assinaturas_texto = "; ".join(
                f"{assinatura.get('nome') or 'signatário não identificado'} "
                f"({assinatura.get('cargo', '')}) em {assinatura.get('data', '')} "
                f"{assinatura.get('hora', '')}"
                for assinatura in assinaturas
            )
            texto_completo = texto_corpo
            if assinaturas_texto:
                texto_completo = f"{texto_corpo}\nAssinado por: {assinaturas_texto}"

            rotulo = _ROTULOS_TIPO_SEI.get(documento.get("tipo"), "Documento")
            titulo = f"{rotulo} — item {item} (PCA {ano})"
            id_documento = documento.get("id_documento")
            # Documento do SEI não tem link próprio que funcione fora da sessão: aponta para o processo.
            url = url_processo_sei(numero_sei.numero_sei)
            for ordem, fragmento in enumerate(fragmentar(texto_completo)):
                trechos.append(
                    Trecho(
                        fonte="sei",
                        ref=f"{ano}/{item}/{id_documento}",
                        ordem=ordem,
                        titulo=titulo,
                        texto=fragmento,
                        url=url,
                        exercicio=ano,
                        item_pca=item,
                        permissao=PERMISSAO_AUTENTICADO,
                        atualizado_em=documento.get("lido_em"),
                    )
                )
    return trechos


def extrair_docs(base_dir=None) -> list[Trecho]:
    """Trechos dos 4 documentos do manifesto (A11/A12) — falha de
    leitura de qualquer um deles levanta `FonteIndisponivel` (aborta a
    geração inteira, nunca publica índice parcial)."""
    from django.conf import settings

    base = Path(base_dir) if base_dir is not None else Path(settings.BASE_DIR)
    trechos: list[Trecho] = []
    for doc in MANIFESTO_DOCS:
        caminho = base / doc["arquivo"]
        try:
            texto = caminho.read_text(encoding="utf-8")
        except OSError as exc:
            raise FonteIndisponivel(f"não foi possível ler {doc['arquivo']}") from exc
        secoes = secoes_markdown(texto, excluir=doc["secoes_excluidas"])
        url = reverse("assistente:documentacao", args=[doc["slug"]])
        for indice_secao, (titulo_secao, corpo) in enumerate(secoes):
            for ordem, fragmento in enumerate(fragmentar(corpo)):
                trechos.append(
                    Trecho(
                        fonte="docs",
                        ref=f"{doc['slug']}/{indice_secao}",
                        ordem=ordem,
                        titulo=f"{doc['titulo']} — {titulo_secao}",
                        texto=fragmento,
                        url=url,
                        exercicio=None,
                        item_pca=None,
                        permissao=doc["permissao"],
                        atualizado_em=None,
                    )
                )
    return trechos


def extrair_tudo() -> list[Trecho]:
    """Concatena as três fontes — qualquer exceção sobe (falha de
    UMA fonte aborta a publicação da geração inteira)."""
    return [*extrair_acompanhamentos(), *extrair_sei(), *extrair_docs()]
