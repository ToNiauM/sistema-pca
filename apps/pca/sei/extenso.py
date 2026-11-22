"""Conversor de valor por extenso em português + parser de cifra.

Módulo puro: zero import de `django.*`, zero import de `apps.pca.models` — só
stdlib (`decimal`, `re`, `unicodedata`). Consumido pelo coletor (`apps/pca/sei/coletor.py`) durante a extração da cláusula de preço de cada
documento contratual; `apps/pca/sei/regras.py` NÃO
importa este módulo — recebe `confere` já calculado no JSON de coleta e
reimplementa, em privado, só o parser de cifra de que precisa.

Quatro funções públicas:

- `cifra_para_decimal(texto)`: extrai "R$ 18.001,20" (ou "18.001,20", sem o
  prefixo) e devolve `Decimal("18001.20")`.
- `valor_por_extenso_para_decimal(texto)`: converte "dezoito mil e um reais e
  vinte centavos" no mesmo `Decimal`. Cobre unidades a bilhões, "cem"/"cento",
  o conectivo "e", milhar sem "um" antes de "mil" ("mil reais", não "um mil
  reais"). Tolera espaço interno espúrio dentro de uma palavra (defeito real
  de extração de HTML do SEI): tokeniza por espaço e funde tokens vizinhos
  até o resultado bater com uma palavra numérica conhecida.
- `valores_conferem(cifra, extenso)`: compara os dois `Decimal` (2 casas,
  nunca ponto flutuante). Cifra ou extenso ilegível → `False`, nunca lança
  exceção — o robô nunca trava a varredura por um documento estranho.
- `inteiro_por_extenso(texto)`: conversor de número por extenso NÃO monetário
  (Fase 33) — mesmo vocabulário/tokenização acima, sem o sufixo
  "reais"/"centavos" que `valor_por_extenso_para_decimal` exige. Usado por
  `apps.pca.sei.extracao.extrair_vigencia` para conferir o N de meses/anos
  contra o algarismo.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation

_UNIDADES = {
    "zero": 0,
    "um": 1,
    "uma": 1,
    "dois": 2,
    "duas": 2,
    "tres": 3,
    "quatro": 4,
    "cinco": 5,
    "seis": 6,
    "sete": 7,
    "oito": 8,
    "nove": 9,
}

_DEZ_A_DEZENOVE = {
    "dez": 10,
    "onze": 11,
    "doze": 12,
    "treze": 13,
    "quatorze": 14,
    "catorze": 14,
    "quinze": 15,
    "dezesseis": 16,
    "dezessete": 17,
    "dezoito": 18,
    "dezenove": 19,
}

_DEZENAS = {
    "vinte": 20,
    "trinta": 30,
    "quarenta": 40,
    "cinquenta": 50,
    "sessenta": 60,
    "setenta": 70,
    "oitenta": 80,
    "noventa": 90,
}

_CENTENAS = {
    "cem": 100,
    "cento": 100,
    "duzentos": 200,
    "trezentos": 300,
    "quatrocentos": 400,
    "quinhentos": 500,
    "seiscentos": 600,
    "setecentos": 700,
    "oitocentos": 800,
    "novecentos": 900,
}

_ESCALAS = {
    "mil": 1_000,
    "milhao": 1_000_000,
    "milhoes": 1_000_000,
    "bilhao": 1_000_000_000,
    "bilhoes": 1_000_000_000,
}

_PALAVRAS_CONHECIDAS = (
    set(_UNIDADES)
    | set(_DEZ_A_DEZENOVE)
    | set(_DEZENAS)
    | set(_CENTENAS)
    | set(_ESCALAS)
    # Achado dados B1 (QA 30/09/2026) — "de" (conectivo entre escala e
    # "reais"/"centavos", "um milhão DE reais") precisa ser um token PRÓPRIO
    # conhecido, senão o tokenizer funde "de" com a palavra seguinte
    # ("dereais") e `valor_por_extenso_para_decimal` nunca encontra "reais".
    | {"e", "de", "reais", "real", "centavos", "centavo"}
)

_RE_CIFRA = re.compile(r"(?:R\$\s*)?(\d{1,3}(?:\.\d{3})*,\d{2})")


def _sem_acento(texto: str) -> str:
    return (
        unicodedata.normalize("NFKD", texto)
        .encode("ascii", "ignore")
        .decode()
        .lower()
    )


_RE_SEPARADOR_DE_GRUPO = re.compile(r"[,;]")


def _tokenizar(texto: str) -> list[str]:
    """Tokeniza por espaço, fundindo tokens vizinhos até bater com uma
    palavra numérica conhecida — tolera o defeito real de extração "c
    inquenta" (espaço espúrio dentro de uma palavra). Vírgulas e
    ponto-e-vírgula entre grupos (o SEI escreve "três milhões, oitocentos e
    trinta e dois mil, setecentos e quarenta reais") são substituídos por
    espaço antes da separação — nunca sobram colados a uma palavra
    numérica, o que impediria o casamento com `_PALAVRAS_CONHECIDAS`."""
    texto = _RE_SEPARADOR_DE_GRUPO.sub(" ", texto)
    brutos = [t for t in texto.split() if t]
    tokens: list[str] = []
    i = 0
    n = len(brutos)
    while i < n:
        candidato = _sem_acento(brutos[i])
        j = i
        while candidato not in _PALAVRAS_CONHECIDAS and j + 1 < n:
            j += 1
            candidato += _sem_acento(brutos[j])
        tokens.append(candidato)
        i = j + 1
    return tokens


def _grupo_para_inteiro(tokens: list[str]) -> int | None:
    """Converte uma sequência de tokens numéricos (sem "reais"/"centavos")
    no inteiro que representam. Devolve `None` se algum token não é
    reconhecido."""
    # Achado dados B1 — "de" nunca carrega valor numérico, só conecta a
    # escala (milhão/milhões/mil/bilhão) a "reais" quando não há casa
    # decimal ("um milhão de reais").
    tokens = [t for t in tokens if t not in ("e", "de")]
    total = 0
    grupo_atual = 0
    for token in tokens:
        if token in _UNIDADES:
            grupo_atual += _UNIDADES[token]
        elif token in _DEZ_A_DEZENOVE:
            grupo_atual += _DEZ_A_DEZENOVE[token]
        elif token in _DEZENAS:
            grupo_atual += _DEZENAS[token]
        elif token in _CENTENAS:
            grupo_atual += _CENTENAS[token]
        elif token in _ESCALAS:
            if grupo_atual == 0:
                grupo_atual = 1
            total += grupo_atual * _ESCALAS[token]
            grupo_atual = 0
        else:
            return None
    total += grupo_atual
    return total


def cifra_para_decimal(texto: str) -> Decimal | None:
    """Extrai uma cifra em R$ ("R$ 18.001,20" ou "18.001,20") e devolve o
    `Decimal` de 2 casas. `None` quando nada reconhecível é encontrado —
    nunca lança exceção sobre texto malformado."""
    if not texto:
        return None
    encontrado = _RE_CIFRA.search(texto)
    if not encontrado:
        return None
    bruto = encontrado.group(1).replace(".", "").replace(",", ".")
    try:
        return Decimal(bruto).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def valor_por_extenso_para_decimal(texto: str) -> Decimal | None:
    """Converte um valor por extenso em português ("dezoito mil e um reais e
    vinte centavos") no `Decimal` de 2 casas equivalente. `None` quando o
    texto não contém "reais"/"real" reconhecível ou quando algum token não
    bate com nenhuma palavra numérica conhecida — nunca lança exceção."""
    if not texto:
        return None
    tokens = _tokenizar(texto)
    if not tokens:
        return None

    try:
        indice_reais = next(i for i, t in enumerate(tokens) if t in ("reais", "real"))
    except StopIteration:
        return None

    parte_reais = tokens[:indice_reais]
    resto = tokens[indice_reais + 1 :]

    parte_centavos: list[str] = []
    if resto:
        resto_sem_conectivo = [t for t in resto if t not in ("e", "de")]
        try:
            indice_centavos = next(
                i for i, t in enumerate(resto_sem_conectivo) if t in ("centavos", "centavo")
            )
        except StopIteration:
            return None
        parte_centavos = resto_sem_conectivo[:indice_centavos]

    valor_reais = _grupo_para_inteiro(parte_reais)
    if valor_reais is None:
        return None

    if parte_centavos:
        valor_centavos = _grupo_para_inteiro(parte_centavos)
        if valor_centavos is None:
            return None
    else:
        valor_centavos = 0

    total = Decimal(valor_reais) + (Decimal(valor_centavos) / Decimal(100))
    return total.quantize(Decimal("0.01"))


def inteiro_por_extenso(texto: str) -> int | None:
    """Converte um número por extenso ("doze", "vinte e quatro") no inteiro
    correspondente — sem o sufixo "reais"/"centavos" que
    `valor_por_extenso_para_decimal` exige. Reaproveita a mesma tokenização/
    vocabulário (`_tokenizar`/`_grupo_para_inteiro`); cobre só unidades a
    centenas, suficiente para o N de meses/anos de uma cláusula de vigência
    (nunca "mil"). `None` quando `texto` é vazio ou algum token não é
    reconhecido — nunca lança exceção."""
    if not texto:
        return None
    tokens = _tokenizar(texto)
    if not tokens:
        return None
    return _grupo_para_inteiro(tokens)


def valores_conferem(cifra: str, extenso: str) -> bool:
    """`True` só quando cifra e extenso convertem para o MESMO `Decimal` de
    2 casas. Qualquer um dos dois ilegível → `False`, nunca exceção
    (o valor só é gravado quando os dois conferem)."""
    valor_cifra = cifra_para_decimal(cifra)
    valor_extenso = valor_por_extenso_para_decimal(extenso)
    if valor_cifra is None or valor_extenso is None:
        return False
    return valor_cifra == valor_extenso
