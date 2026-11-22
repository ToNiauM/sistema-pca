"""Normalização de célula de planilha para o comando `importar_pca` (01-04).

Funções puras, testáveis isoladamente, sem tocar o ORM — cada função
recebe o valor bruto de uma célula (já lido por `openpyxl` com
`data_only=True`) e devolve o tipo Python que o modelo espera, ou `None`
quando o valor não pode ser reconhecido. "Não reconheço, não invento" é o
comportamento genérico por trás (item 137): nenhuma função aqui tem
caso especial hardcoded para um item específico.
"""

import re
from datetime import date, datetime

from apps.catalogo.utils import normalizar_nome  # noqa: F401 — reexportado
# para apps/pca/management/commands/importar_pca.py: mesma lógica de
# DominioBase.save() (01-03), extraída para apps/catalogo/utils.py para não
# duplicar entre os dois apps (ver).

# Mapa mês (3 letras, como a planilha original grava) -> inteiro 1-12.
#Mantido aqui, não em apps.pca.models, porque este módulo não
# importa django.db.models (acceptance criteria) — por isso os
# nomes por extenso abaixo são literais, nunca importados de
# `apps.pca.filtros.NOMES_MES` (que arrasta o ORM).
# nomes por extenso ("Janeiro".."Dezembro", case-insensitive) acrescentados
# porque o XLSX exportado agora grava o mês por extenso (`exportacao.py`);
# sem isso, reimportar um arquivo baixado do próprio sistema perderia o
# mês (célula não reconhecida -> None, "não reconheço, não invento").
MESES = {
    "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12,
    "janeiro": 1, "fevereiro": 2, "março": 3, "abril": 4, "maio": 5,
    "junho": 6, "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10,
    "novembro": 11, "dezembro": 12,
}

# Rótulo (como aparece em `Planilha1`/`Listas`, sufixo de prazo já removido)
# -> slug legado (os 5 valores do extinto enum `Status`, removido do
# domínio vivo pelo plano). Mantido como conjunto literal — nunca
# gravado no banco, só decide `estado`/`situacao` no import —
# para que este módulo continue sem importar `django.db.models`.
STATUS_POR_ROTULO = {
    "Concluído": "concluido",
    "Não iniciado": "nao_iniciado",
    "Em tramitação": "em_tramitacao",
    "Vigente": "vigente",
    "Cancelado": "cancelado",
}

_SUFIXO_PRAZO_RE = re.compile(r"\s*\((?:dentro|fora) do prazo\)\s*$")

# Padrão de nº de processo SEI real: dígitos.dígitos/ano-dígitos (ex.:
# "90796110000032.000082/2026-53"). Usado com `re.findall` sobre a célula
# inteira — nunca por posição de caractere, porque as duas células com
# múltiplos números (itens 37 e 72) só têm espaço simples como separador.
_SEI_RE = re.compile(r"\d+\.\d+/\d{4}-\d+")


def parse_mes_previsto(valor) -> int | None:
    """`"jan"` -> `1` .. `"dez"` -> `12`; `"Janeiro"` -> `1` .. `"Dezembro"`
    -> `12` (case-insensitive — cobre o XLSX exportado
    pelo próprio sistema, que agora grava o mês por extenso). Qualquer
    valor que não bata exatamente com um dos 24 rótulos retorna `None` —
    cobre o item 137 (`"jan a dez"`) sem caso especial: é o
    comportamento genérico."""
    if not valor:
        return None
    chave = str(valor).strip().lower()
    return MESES.get(chave)


def parse_status(valor) -> str:
    """Remove o sufixo `" (dentro do prazo)"`/`" (fora do prazo)"` antes de
    mapear para o slug legado. Se o rótulo restante não for
    reconhecido, devolve-o como está — sinal de dado inesperado que deve
    estourar mais adiante, não ser mascarado aqui."""
    rotulo = _SUFIXO_PRAZO_RE.sub("", str(valor or "").strip())
    return STATUS_POR_ROTULO.get(rotulo, rotulo)


def parse_booleano_sim(valor) -> bool:
    """`"SIM"` -> `True`; `None`/vazio -> `False`. Nos dados reais nunca
    aparece `"NÃO"` literal (confirmado)."""
    return str(valor or "").strip().upper() == "SIM"


def parse_numeros_sei(valor) -> list[str]:
    """Extrai todos os números de processo SEI de uma célula, validando cada
    token contra o padrão real — nunca dividindo por posição de
    caractere. `""`/`None` -> lista vazia."""
    if not valor:
        return []
    return _SEI_RE.findall(str(valor))


def parse_data_excel(valor) -> date | None:
    """`openpyxl` com `data_only=True` já entrega `datetime`/`date` nativos
    para célula de data — esta função só normaliza `None` e string residual
    (`"?"`, `"N/A"` etc.) para `None`. Nunca inventa data a partir de texto
    livre não reconhecido."""
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    # None, ou qualquer texto residual ("?"/"N/A"/"-" ou não reconhecido):
    # nunca se tenta adivinhar uma data a partir de texto livre.
    return None
