"""Montagem pura do material do SEI (Fase 42) — extraída de
`apps/pca/sei/coletor.py`: a parte de `SEI._marcos`/`SEI.ler_documento` que não
depende do navegador (Playwright). Permite ao futuro POST `/api/sei/coleta`
montar o MESMO dict que o robô (`coletor.coletar_um`) produz, a
partir só de material bruto já extraído — pela extensão SEI Pro OU pelo
próprio robô, regra num lugar só.

Módulo puro, mesmo padrão de `apps/pca/sei/regras.py`/`apps/pca/sei/aplicador.py`
quanto a módulo sem ORM/Playwright: zero import de `django.db.models`,
`apps.pca.models` ou `playwright`. Importa livremente de
`apps.pca.sei.extracao`/`apps.pca.sei.pdf` (ambos também puros).

Três exports:

- `marcos(linhas)`: idêntico ao que `SEI._marcos` produzia antes desta fase —
  dado uma lista de `[data_hora, unidade, descricao]` (mais recente ou mais
  antigo primeiro, indiferente), devolve o dict com os 7 marcos
  (`primeiro`/`ultimo`/`recebimentos`/`conclusoes_na_unidade`/
  `assinaturas_no_historico`/`ultima_remessa`/`recebimentos_gelic_delic`).
- `montar_documento(...)`: a parte de `SEI.ler_documento` posterior à leitura
  do conteúdo (precisa só do HTML/PDF já obtido, não do clique na árvore) —
  três ramos: `html` preenchido (ramo HTML interno), `pdf_bytes` preenchido
  e `html is None` (ramo PDF externo, delega a `apps.pca.sei.pdf.processar`),
  os dois `None` (externo nunca baixado OU documento restrito nunca lido
  pela extensão — mesmo efeito, spec §3).
- `montar_processo(material)`: monta o dict completo no formato de
  `coletor.coletar_um`, a partir do contrato JSON do POST `/api/sei/coleta`
  (`docs/api-extensao-sei.md`).
- `reler_valores_do_corpo(documento)` (debug robo-valor-contratado-item64,
  20/10/2026): recalcula `valor`/`apostilamento` de um documento já coletado
  pela extração atual, a partir do `texto_corpo` gravado — usado só por
  `sei_corrigir_eventos`.
"""

from __future__ import annotations

import base64
import html as html_mod
import re
from datetime import datetime

from apps.pca.sei.extracao import (
    RE_CONTRATUAL,
    VERSAO_EXTRACAO_DOCUMENTO,
    extrair_apostilamento,
    extrair_assinaturas,
    extrair_contratado,
    extrair_numero_no_corpo,
    extrair_procedencia,
    extrair_prorrogacao,
    extrair_valor_documento,
    extrair_vigencia,
    hash_texto,
    texto_corpo_de,
    tipo_documento,
)
from apps.pca.sei.pdf import processar as processar_pdf

# Movidas de `coletor.py` (Fase 42) — usadas só por `marcos`/`_anon` abaixo;
# nada mais no repositório as importava diretamente (ver CONTEXT do plano).
RE_HIST_ASSINADO = re.compile(
    r"^Assinado Documento (?P<protocolo>\d+) \((?P<tipo>[^)]*)\) por (?P<login>\S+)", re.I)
RE_ANON_POR = re.compile(r"\bpor \S+@?\S*$")
RE_ANON_USUARIO = re.compile(r"usuário .+? \([^)]*@[^)]*\)")
# Casa contra a descrição ORIGINAL da linha (não a
# casefolded, para preservar a sigla de origem tal como veio no histórico);
# IGNORECASE só cobre o prefixo fixo "processo remetido pela unidade".
RE_REMESSA = re.compile(r"^processo remetido pela unidade\s+(?P<origem>.+?)\.?\s*$", re.I)


def texto_de_html(corpo: str) -> str:
    """Texto puro a partir de HTML bruto — remove `<script>`/`<style>`,
    converte quebras de bloco em nova linha e tira o resto das tags. Movida
    de `coletor.py` (Fase 42): pura, sem Playwright."""
    corpo = re.sub(r"(?is)<(script|style).*?</\1>", " ", corpo)
    corpo = re.sub(r"(?is)<br\s*/?>|</p>|</div>|</tr>", "\n", corpo)
    corpo = re.sub(r"(?s)<[^>]+>", " ", corpo)
    return "\n".join(" ".join(l.split()) for l in html_mod.unescape(corpo).splitlines() if l.strip())


def _anon(descricao: str) -> str:
    """Tira logins/nomes de quem assinou ou recebeu liberação — mesma lógica
    de `SEI._anon` antes desta fase (movida aqui, Fase 42)."""
    descricao = RE_ANON_USUARIO.sub("usuário [omitido]", descricao)
    if descricao.casefold().startswith("assinado documento"):
        descricao = RE_ANON_POR.sub("por [omitido]", descricao)
    return re.sub(r"\(cancelada por \S+ em ", "(cancelada por [omitido] em ", descricao)


def marcos(linhas: list[list[str]]) -> dict:
    """Linhas `[data_hora, unidade, descricao]`, em qualquer ordem.

    `ultima_remessa`: o candidato de MAIOR `(data_hora,
    unidade)` entre as linhas cuja descrição casa com `RE_REMESSA` ("Processo
    remetido pela unidade X") — `ultima_remessa["unidade"]` é a coluna da
    linha, ou seja, a unidade de DESTINO da remessa, não a origem (essa só
    sobrevive em `ultima_remessa["origem"]`, texto informativo, nunca lido
    por `regras.unidade_atual`). `None` sem nenhuma remessa no histórico."""
    def data(l):
        return datetime.strptime(l[0], "%d/%m/%Y %H:%M")
    ordenadas = sorted(linhas, key=data)
    fmt = lambda l: {"data_hora": l[0], "unidade": l[1], "descricao": _anon(l[2])}
    resultado = {"primeiro": fmt(ordenadas[0]) if ordenadas else None,
                 "ultimo": fmt(ordenadas[-1]) if ordenadas else None,
                 "recebimentos": {}, "conclusoes_na_unidade": {}, "assinaturas_no_historico": [],
                 "ultima_remessa": None, "recebimentos_gelic_delic": []}
    candidato_remessa = None
    for l in ordenadas:
        d = l[2].casefold()
        if "processo recebido na unidade" in d and l[1] not in resultado["recebimentos"]:
            resultado["recebimentos"][l[1]] = l[0]
            if l[1] in ("GELIC", "DELIC") and "recebimento_gelic_delic" not in resultado:
                resultado["recebimento_gelic_delic"] = {"unidade": l[1], "data_hora": l[0]}
        # 29/09/2026 — processo SEI reaproveitado a cada renovação: o
        # PRIMEIRO recebimento no Gelic/Delic pode ser de um ciclo antigo.
        # Guarda TODOS, em ordem cronológica; `regras.propor` escolhe o
        # primeiro do ano do PCA.
        if "processo recebido na unidade" in d and l[1] in ("GELIC", "DELIC"):
            resultado["recebimentos_gelic_delic"].append(l[0])
        if "conclusão do processo na unidade" in d:
            resultado["conclusoes_na_unidade"][l[1]] = l[0]
        m_remessa = RE_REMESSA.match(l[2].strip())
        if m_remessa:
            chave = (data(l), l[1])
            if candidato_remessa is None or chave >= (
                data([candidato_remessa["data_hora"], candidato_remessa["unidade"], ""]),
                candidato_remessa["unidade"],
            ):
                candidato_remessa = {
                    "data_hora": l[0],
                    "unidade": l[1],
                    "origem": m_remessa.group("origem").strip(),
                }
        m = RE_HIST_ASSINADO.match(l[2])
        if m and RE_CONTRATUAL.match(m.group("tipo")):
            resultado["assinaturas_no_historico"].append({
                "data_hora": l[0], "unidade": l[1], "protocolo": m.group("protocolo"), "tipo": m.group("tipo"),
                "papel": "externo" if "@" in m.group("login") else "interno"})
    resultado["ultima_remessa"] = candidato_remessa
    return resultado


def montar_documento(
    *,
    id_documento,
    protocolo,
    rotulo,
    assinantes_externos_na_arvore,
    html: str | None = None,
    pdf_bytes: bytes | None = None,
    numero_processo: str | None = None,
) -> dict:
    """Monta o dict de um documento contratual a partir do material já
    obtido (sem clique na árvore, sem leitura de rede) — mesmo formato do
    que `SEI.ler_documento` produzia nos ramos HTML interno/PDF externo
    antes desta fase. `info["tipo"]` sempre vem de `tipo_documento(rotulo)`,
    calculado aqui dentro — nunca passado pronto pelo chamador.

    - `html` preenchido: ramo HTML interno — `conteudo="html"`.
    - `html is None` e `pdf_bytes` preenchido: ramo PDF externo, delega a
      `apps.pca.sei.pdf.processar` (`conteudo` vem de dentro dele).
    - os dois `None`: documento externo nunca baixado OU documento restrito
      nunca lido pela extensão (spec §3) — mesmo efeito, `"externo_nao_baixado"`.
    """
    info = {
        "id_documento": id_documento,
        "protocolo": protocolo,
        "rotulo": rotulo,
        "assinantes_externos_na_arvore": assinantes_externos_na_arvore,
    }
    info["tipo"] = tipo_documento(rotulo)
    if html is not None:
        texto = texto_de_html(html)
        info["conteudo"] = "html"
        info["protocolo_no_corpo"] = bool(protocolo) and f"SEI nº {protocolo}" in texto
        info["menciona_cfc"] = "CONSELHO FEDERAL DE CONTABILIDADE" in texto.upper()
        info["numero_no_corpo"] = extrair_numero_no_corpo(texto)
        assinaturas_info = extrair_assinaturas(texto)
        info["assinaturas"] = assinaturas_info["assinaturas"]
        info["assinado_cfc"] = assinaturas_info["assinado_cfc"]
        info["assinado_externo"] = assinaturas_info["assinado_externo"]
        info["ultima_assinatura"] = assinaturas_info["ultima_assinatura"]
        info["ultima_assinatura_cfc"] = assinaturas_info["ultima_assinatura_cfc"]
        # (Fase 39) — corpo do documento para o índice semântico do
        # Assistente, sem o bloco de assinaturas nem o cabeçalho
        # institucional; NUNCA grava o HTML bruto, só texto puro derivado.
        info["texto_corpo"] = texto_corpo_de(texto)
        info["versao_extracao"] = VERSAO_EXTRACAO_DOCUMENTO
        info["hash_texto"] = hash_texto(info["texto_corpo"])
        info["valor"] = extrair_valor_documento(texto)
        info["contratado"] = extrair_contratado(texto)
        info["procedencia"] = extrair_procedencia(texto)
        info["vigencia"] = extrair_vigencia(texto, assinaturas_info["ultima_assinatura"])
        info["prorrogacao"] = extrair_prorrogacao(texto)
        # Apostilamento (Fase 35): só quando o tipo já derivado do
        # rótulo é "apostilamento" — nunca herda o resultado por engano num
        # contrato/aditivo/OF.
        info["apostilamento"] = (
            extrair_apostilamento(texto) if info["tipo"] == "apostilamento" else None
        )
        return info
    # Defaults do externo nunca baixado — o ramo PDF (abaixo) os sobrescreve
    # quando `pdf_bytes` vem preenchido, mas `versao_extracao` sobrevive
    # sempre (mesmo padrão de `SEI.ler_documento` antes desta fase).
    info["conteudo"] = "externo_nao_baixado"
    info["texto_corpo"] = None
    info["versao_extracao"] = VERSAO_EXTRACAO_DOCUMENTO
    if pdf_bytes is not None:
        info.update(processar_pdf(pdf_bytes, numero_processo))
    return info


def montar_processo(material: dict) -> dict:
    """Dado o material bruto de UM processo (contrato do POST
    `/api/sei/coleta`, `docs/api-extensao-sei.md`): `{"numero", "andamentos":
    [{"data_hora","unidade","descricao"}, ...], "documentos": [{"id_documento",
    "protocolo","rotulo","assinantes_externos_na_arvore","contratual",
    "cancelado","motivo_cancelamento","conteudo","motivo","html","pdf_base64"},
    ...]}`, devolve o MESMO formato que `coletor.coletar_um` produz:
    `{"numero", "resultado": "ok", "total_documentos", "andamentos":
    {"marcos": ...}, "documentos_contratuais": [...]}`.

    Só documentos cujo rótulo casa com `RE_CONTRATUAL` entram em
    `documentos_contratuais` (mesmo filtro do robô; o campo `contratual` do
    material é ignorado). Um documento `cancelado: true` vira o mesmo
    formato do ramo cancelado de `SEI.ler_documento`, SEM passar por
    `montar_documento`. Os demais chamam `montar_documento` com `html`/
    `pdf_bytes` (decodificado de `pdf_base64`) conforme o que o material
    trouxer — documento restrito (`conteudo="nao_lido"`/`motivo="restrito"`)
    não traz nem `html` nem `pdf_base64`, caindo no ramo `externo_nao_baixado`
    de `montar_documento` (spec §3)."""
    andamentos = material.get("andamentos") or []
    linhas = [[a["data_hora"], a["unidade"], a["descricao"]] for a in andamentos]
    documentos = material.get("documentos") or []
    documentos_contratuais = []
    for doc in documentos:
        # Fonte da verdade é o rótulo, pela mesma regra de `SEI.documentos` —
        # o campo `contratual` enviado pela extensão é ignorado, e o conteúdo
        # de documento não contratual nunca é considerado (revisão do contrato
        # v1 pela sessão sei-pro, pontos 1 e 4).
        if not RE_CONTRATUAL.match(doc.get("rotulo") or ""):
            continue
        if doc.get("cancelado"):
            documentos_contratuais.append({
                "id_documento": doc["id_documento"],
                "protocolo": doc["protocolo"],
                "rotulo": doc["rotulo"],
                "assinantes_externos_na_arvore": doc["assinantes_externos_na_arvore"],
                "tipo": tipo_documento(doc["rotulo"]),
                "conteudo": "cancelado",
                "motivo_cancelamento": doc.get("motivo_cancelamento"),
                "texto_corpo": None,
                "versao_extracao": VERSAO_EXTRACAO_DOCUMENTO,
            })
            continue
        pdf_base64 = doc.get("pdf_base64")
        documentos_contratuais.append(montar_documento(
            id_documento=doc["id_documento"],
            protocolo=doc["protocolo"],
            rotulo=doc["rotulo"],
            assinantes_externos_na_arvore=doc["assinantes_externos_na_arvore"],
            html=doc.get("html"),
            pdf_bytes=base64.b64decode(pdf_base64) if pdf_base64 else None,
            numero_processo=material.get("numero"),
        ))
    return {
        "numero": material["numero"],
        "resultado": "ok",
        "total_documentos": len(documentos),
        "andamentos": {"marcos": marcos(linhas)},
        "documentos_contratuais": documentos_contratuais,
        **resumo_do_historico(linhas),
    }


def resumo_do_historico(linhas: list[list[str]]) -> dict:
    """`{"registros", "primeiro"}` no formato de `SEI.historico_resumo` — o
    sinal do atalho de pulo (`ultima_coleta` do GET `processo`). `primeiro`
    é o andamento MAIS RECENTE (o SEI lista assim), com a descrição
    anonimizada; `max` é estável, então no empate de data fica o primeiro da
    lista, que a extensão manda na ordem do SEI. Pedido da sessão sei-pro
    (10/10/2026): sem isso, toda coleta da extensão voltava `registros:
    null`."""
    if not linhas:
        return {"registros": 0, "primeiro": None}
    linha = max(linhas, key=lambda l: datetime.strptime(l[0], "%d/%m/%Y %H:%M"))
    return {
        "registros": len(linhas),
        "primeiro": {"data_hora": linha[0], "unidade": linha[1], "descricao": _anon(linha[2])},
    }


# Conteúdos cujo `texto_corpo` é o texto lido do documento (HTML interno ou
# PDF externo com texto) — os demais (`externo_nao_baixado`, `cancelado`,
# `pdf_sem_texto`, `pdf_outro_orgao`) não têm o que reler.
_CONTEUDOS_COM_TEXTO = ("html", "pdf", "pdf_sem_assinatura_digital")


def reler_valores_do_corpo(documento: dict) -> tuple[dict, bool]:
    """Debug robo-valor-contratado-item64 (20/10/2026): devolve uma CÓPIA de
    `documento` com `valor` (e, para apostilamento em HTML, `apostilamento`)
    recalculados pela extração ATUAL a partir do `texto_corpo` já gravado na
    coleta, quando `versao_extracao` é anterior a
    `VERSAO_EXTRACAO_DOCUMENTO` — sem abrir o SEI. O segundo elemento diz se
    houve releitura. Documento sem `texto_corpo`, de outro conteúdo ou já na
    versão atual volta como está (a mesma instância, nunca alterada).

    Usado só por `sei_corrigir_eventos` (prévia da correção dos eventos
    financeiros sem depender de `sei_coletar --reprocessar-documentos`).
    O coletor lê o valor do texto inteiro do documento; o `texto_corpo` só
    não tem o cabeçalho institucional nem o bloco de assinaturas — a
    releitura das 287 leituras da coleta de 20/10/2026 pela extração antiga
    reproduziu 287/287 valores gravados."""
    texto = documento.get("texto_corpo")
    if (
        not texto
        or documento.get("conteudo") not in _CONTEUDOS_COM_TEXTO
        or documento.get("versao_extracao") == VERSAO_EXTRACAO_DOCUMENTO
    ):
        return documento, False
    relido = dict(documento)
    relido["valor"] = extrair_valor_documento(texto)
    if relido.get("tipo") == "apostilamento" and relido.get("conteudo") == "html":
        relido["apostilamento"] = extrair_apostilamento(texto)
    relido["versao_extracao"] = VERSAO_EXTRACAO_DOCUMENTO
    return relido, True
