"""Leitura de PDF externo "Contrato..."/"Termo Aditivo..." (quicks) — módulo puro: zero import de `playwright`/
`django.db`/ORM, mesmo padrão de `apps/pca/sei/extracao.py`. Único import
de terceiros: `pypdf` (texto + assinatura digital embutida via
`/AcroForm`), sem OCR, sem validação criptográfica da assinatura (ver
`threat_model` T-q1h-02 do plano).

Cinco exports:

- `extrair_texto(corpo)`: texto de todas as páginas concatenadas, ou `None`
  (PDF corrompido/criptografado/sem texto extraível) — nunca lança.
- `pertence_ao_processo(texto, numero_processo)`: filtro de segurança
  (T-q1h-01) — exige menção ao CFC E aos dígitos do número DESTE processo.
- `extrair_assinaturas_digitais(corpo)`: campos `/FT /Sig` do `/AcroForm`
  com `/V` preenchido — `[{"nome", "data", "hora"}]`, nunca lança.
- `classificar_papel(nome, texto)`: "cfc"/"externo"/`None`, pelo marcador
  mais próximo (antes do nome) entre CONTRATANTE/CFC e CONTRATADA/CONTRATADO
  — desde, a comparação ignora espaço em branco (inclusive
  quebra de linha) em marcador/nome/texto, porque a extração do `pypdf`
  ocasionalmente quebra palavras no meio (achado real: PDF 1469673, item 89,
  "CONTRATADO" extraído como "CONTRA TADO").
- `processar(corpo, numero_processo)`: combina as quatro acima com os
  extratores de texto puro já existentes em `extracao.py` (reuso direto,
  mesma semântica do ramo HTML de `coletor.ler_documento`) — desde a quick
  também acrescenta `"prorrogacao"` ao envelope de sucesso
  (mesmo extrator `extrair_prorrogacao`, usado pelo ramo HTML de Termo
  Aditivo), incondicional e independente do `tipo` do documento (`pdf.py`
  não recebe `tipo` — só `regras.py` decide o que fazer com a chave).
  `"apostilamento"` NUNCA é acrescentada aqui: documentos `tipo==
  "apostilamento"` nunca são baixados como PDF (o gate de
  `coletor.ler_documento` só baixa `contrato`/`termo_aditivo`), e
  `regras.py` já lê essa chave via `.get()` (devolve `None` na ausência).
"""

from __future__ import annotations

import io
import re
from datetime import datetime

import pypdf

from apps.pca.sei.extracao import (
    extrair_contratado,
    extrair_numero_no_corpo,
    extrair_procedencia,
    extrair_prorrogacao,
    extrair_valor_documento,
    extrair_vigencia,
)

_RE_NOME_SEM_CPF = re.compile(r"^(?P<nome>.+?):\d+$")
_RE_DATA_HORA_ACROFORM = re.compile(r"^D:(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})")

_MARCADORES_CFC = ("CONTRATANTE", "CONSELHO FEDERAL DE CONTABILIDADE")
_MARCADORES_CONTRATADO = ("CONTRATADA", "CONTRATADO")


def _sem_espaco(valor: str) -> str:
    """Remove todo espaço em branco (inclusive quebra de linha) de `valor`
    — usada por `classificar_papel` para tolerar
    marcador/nome quebrados pela extração de texto do `pypdf`. Pura, nunca
    lança."""
    return re.sub(r"\s+", "", valor)


_MARCADORES_CFC_SEM_ESPACO = tuple(_sem_espaco(m) for m in _MARCADORES_CFC)
_MARCADORES_CONTRATADO_SEM_ESPACO = tuple(_sem_espaco(m) for m in _MARCADORES_CONTRATADO)

_ENVELOPE_VAZIO = {
    "conteudo": "pdf_sem_texto",
    "texto_corpo": None,
    "assinaturas": [],
    "assinado_cfc": False,
    "assinado_externo": False,
    "ultima_assinatura": None,
    "ultima_assinatura_cfc": None,
    "menciona_cfc": False,
    "numero_no_corpo": None,
}


def _resolver(valor):
    """Resolve um `IndirectObject` do pypdf para o objeto de fato, quando
    aplicável — valores já inline (não indiretos) são devolvidos como
    vieram. Nunca lança (ausência de `.get_object` -> devolve o próprio
    valor)."""
    get_object = getattr(valor, "get_object", None)
    return get_object() if callable(get_object) else valor


def extrair_texto(corpo: bytes) -> str | None:
    """Texto de todas as páginas concatenadas (`"\\n"` entre páginas).
    `None` para PDF corrompido, criptografado ou cujo texto extraído é
    vazio/só espaços — nunca lança exceção."""
    try:
        reader = pypdf.PdfReader(io.BytesIO(corpo))
        texto = "\n".join((pagina.extract_text() or "") for pagina in reader.pages)
    except Exception:
        return None
    if not texto or not texto.strip():
        return None
    return texto


def pertence_ao_processo(texto: str, numero_processo: str | None) -> bool:
    """Filtro de segurança (T-q1h-01): `texto` precisa mencionar
    "CONSELHO FEDERAL DE CONTABILIDADE" (case-insensitive) E os dígitos de
    `numero_processo` precisam aparecer entre os dígitos de `texto`
    (tolerando espaço/ponto/barra/hífen inseridos pela extração).
    `numero_processo=None`/`texto` vazio -> `False`. Nunca lança."""
    if not texto or not numero_processo:
        return False
    if "CONSELHO FEDERAL DE CONTABILIDADE" not in texto.upper():
        return False
    digitos_processo = re.sub(r"\D", "", numero_processo)
    if not digitos_processo:
        return False
    digitos_texto = re.sub(r"\D", "", texto)
    return digitos_processo in digitos_texto


def extrair_assinaturas_digitais(corpo: bytes) -> list[dict]:
    """Campos `/FT /Sig` do `/AcroForm`/`/Fields` com `/V` preenchido ->
    `[{"nome" (sem ":<cpf>"), "data" ("DD/MM/AAAA"), "hora" ("HH:MM")}]`.
    PDF sem `/AcroForm`/sem nenhum campo `/Sig` -> `[]`. Qualquer campo que
    falhe ao ser lido é pulado — nunca propaga exceção."""
    try:
        reader = pypdf.PdfReader(io.BytesIO(corpo))
        root = reader.trailer["/Root"]
        acroform = _resolver(root.get("/AcroForm")) if root else None
        if not acroform:
            return []
        campos = _resolver(acroform.get("/Fields"))
        if not campos:
            return []
    except Exception:
        return []

    resultado: list[dict] = []
    for campo_ref in campos:
        try:
            campo = _resolver(campo_ref)
            if campo is None or campo.get("/FT") != "/Sig":
                continue
            assinatura = _resolver(campo.get("/V"))
            if assinatura is None:
                continue
            nome_bruto = assinatura.get("/Name")
            if nome_bruto is None:
                continue
            nome_bruto = str(nome_bruto)
            m_nome = _RE_NOME_SEM_CPF.match(nome_bruto)
            nome = m_nome.group("nome") if m_nome else nome_bruto

            data_bruta = assinatura.get("/M")
            m_data = _RE_DATA_HORA_ACROFORM.match(str(data_bruta) if data_bruta else "")
            if not m_data:
                continue
            ano, mes, dia, hora, minuto, _segundo = m_data.groups()
            resultado.append({
                "nome": nome,
                "data": f"{dia}/{mes}/{ano}",
                "hora": f"{hora}:{minuto}",
            })
        except Exception:
            continue
    return resultado


def classificar_papel(nome: str, texto: str) -> str | None:
    """"cfc"/"externo"/`None` — o marcador (CONTRATANTE/CONSELHO FEDERAL
    DE CONTABILIDADE x CONTRATADA/CONTRATADO) mais próximo ANTES da
    primeira ocorrência de `nome` em `texto` (case-insensitive). `nome`
    ausente do texto, ou nenhum dos dois marcadores aparece antes dele ->
    `None`. Desde, a comparação ignora espaço em branco
    (inclusive quebra de linha) em marcador/nome/texto — a extração do
    `pypdf` ocasionalmente quebra palavras no meio (achado real: PDF
    1469673, item 89, "CONTRATADO" extraído como "CONTRA TADO"); remover
    espaços nunca inverte a ordem relativa dos caracteres restantes, então
    o critério "marcador mais próximo antes do nome" não muda. Nunca
    lança."""
    if not nome or not texto:
        return None
    baixa = _sem_espaco(texto.upper())
    posicao = baixa.find(_sem_espaco(nome.upper()))
    if posicao == -1:
        return None
    prefixo = baixa[:posicao]
    idx_cfc = max((prefixo.rfind(m) for m in _MARCADORES_CFC_SEM_ESPACO), default=-1)
    idx_contratado = max(
        (prefixo.rfind(m) for m in _MARCADORES_CONTRATADO_SEM_ESPACO), default=-1
    )
    if idx_cfc == -1 and idx_contratado == -1:
        return None
    return "cfc" if idx_cfc > idx_contratado else "externo"


def _parse_data_hora(data: str, hora: str) -> datetime | None:
    try:
        return datetime.strptime(f"{data} {hora}", "%d/%m/%Y %H:%M")
    except ValueError:
        return None


def processar(corpo: bytes, numero_processo: str | None) -> dict:
    """Envelope completo do documento PDF externo — `conteudo` em
    `"pdf"|"pdf_sem_texto"|"pdf_outro_orgao"|"pdf_sem_assinatura_digital"`,
    nunca lança exceção (toda extração interna já é blindada)."""
    texto = extrair_texto(corpo)
    if not texto:
        return dict(_ENVELOPE_VAZIO)

    menciona_cfc = "CONSELHO FEDERAL DE CONTABILIDADE" in texto.upper()
    if not pertence_ao_processo(texto, numero_processo):
        resultado = dict(_ENVELOPE_VAZIO)
        resultado["conteudo"] = "pdf_outro_orgao"
        resultado["menciona_cfc"] = menciona_cfc
        return resultado

    assinaturas_brutas = extrair_assinaturas_digitais(corpo)
    assinaturas = []
    datas: list[tuple[datetime, dict]] = []
    for assinatura in assinaturas_brutas:
        papel = classificar_papel(assinatura["nome"], texto)
        entrada = dict(assinatura, papel=papel)
        assinaturas.append(entrada)
        data_hora = _parse_data_hora(assinatura["data"], assinatura["hora"])
        if data_hora is not None:
            datas.append((data_hora, entrada))

    assinado_cfc = any(a["papel"] == "cfc" for a in assinaturas)
    assinado_externo = any(a["papel"] == "externo" for a in assinaturas)

    ultima_assinatura = max(datas, key=lambda par: par[0])[0].strftime("%d/%m/%Y %H:%M") if datas else None
    datas_cfc = [dt for dt, a in datas if a["papel"] == "cfc"]
    ultima_assinatura_cfc = max(datas_cfc).strftime("%d/%m/%Y %H:%M") if datas_cfc else None

    conteudo = "pdf" if assinaturas else "pdf_sem_assinatura_digital"

    return {
        "conteudo": conteudo,
        "texto_corpo": texto,
        "assinaturas": assinaturas,
        "assinado_cfc": assinado_cfc,
        "assinado_externo": assinado_externo,
        "ultima_assinatura": ultima_assinatura,
        "ultima_assinatura_cfc": ultima_assinatura_cfc,
        "menciona_cfc": menciona_cfc,
        "numero_no_corpo": extrair_numero_no_corpo(texto),
        "valor": extrair_valor_documento(texto),
        "contratado": extrair_contratado(texto),
        "procedencia": extrair_procedencia(texto),
        "vigencia": extrair_vigencia(texto, ultima_assinatura),
        "prorrogacao": extrair_prorrogacao(texto),
    }
