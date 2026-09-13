"""Normalização de célula de planilha para o comando importar_pca. Funções
puras, sem tocar o ORM: recebem o valor bruto de uma célula e devolvem o
tipo Python que o modelo espera, ou None quando não reconhecido — nunca
caso especial hardcoded para um item específico."""

import re
from datetime import date, datetime

from apps.catalogo.utils import normalizar_nome  # noqa: F401 — reexportado
# para apps/pca/management/commands/importar_pca.py

# mapa mês (3 letras, como a planilha grava) -> inteiro 1-12; mantido aqui,
# não em apps.pca.models, porque este módulo não importa django.db.models
MESES = {
    "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12,
}

# rótulo (sufixo de prazo já removido) -> slug legado; nunca gravado no
# banco, só decide estado/situacao no import
STATUS_POR_ROTULO = {
    "Concluído": "concluido",
    "Não iniciado": "nao_iniciado",
    "Em tramitação": "em_tramitacao",
    "Vigente": "vigente",
    "Cancelado": "cancelado",
}

_SUFIXO_PRAZO_RE = re.compile(r"\s*\((?:dentro|fora) do prazo\)\s*$")

# padrão de nº de processo SEI; usado com re.findall sobre a célula
# inteira, nunca por posição de caractere
_SEI_RE = re.compile(r"\d+\.\d+/\d{4}-\d+")


def parse_mes_previsto(valor) -> int | None:
    """"jan" -> 1 .. "dez" -> 12. Qualquer valor que não bata exatamente
    com um dos 12 rótulos retorna None."""
    if not valor:
        return None
    chave = str(valor).strip().lower()
    return MESES.get(chave)


def parse_status(valor) -> str:
    """Remove o sufixo " (dentro/fora do prazo)" antes de mapear para o
    slug legado. Rótulo não reconhecido é devolvido como está."""
    rotulo = _SUFIXO_PRAZO_RE.sub("", str(valor or "").strip())
    return STATUS_POR_ROTULO.get(rotulo, rotulo)


def parse_booleano_sim(valor) -> bool:
    """"SIM" -> True; None/vazio -> False."""
    return str(valor or "").strip().upper() == "SIM"


def parse_numeros_sei(valor) -> list[str]:
    """Extrai todos os números de processo SEI de uma célula, validando
    cada token contra o padrão real. ""/None -> lista vazia."""
    if not valor:
        return []
    return _SEI_RE.findall(str(valor))


def parse_data_excel(valor) -> date | None:
    """openpyxl já entrega datetime/date nativos para célula de data; esta
    função só normaliza None e string residual para None."""
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    # None ou texto residual: nunca se tenta adivinhar uma data
    return None
