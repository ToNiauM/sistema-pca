"""Fase 17.1, reestruturado pelas Quicks
e pelo plano (..47) — export
XLSX do resumo por UO (`apps/pca/resumo_uo.py::calcular_resumo_uo`). 27
colunas (13 indicadores + UO, cada par absoluto+percentual) da tela, com
cabeçalho de bloco mesclado sobre os nomes curtos, na mesma ordem;
`linhas`/`total` chegam prontos — este módulo só formata e escreve, nunca
recalcula nada (T-172-04).

A tabela ganha um 3º bloco, "Situação dos ativos"
(partição IRRESTRITA por tipo de A: Concluídos/Em tramitação/No prazo/
Atrasados, percentuais /ativos), reaproveitando as MESMAS 4 cores dos 4
valores de `Situacao` já usadas no bloco "Meta do PCA" (que representam os
mesmos 4 estados, só sobre um universo maior); "Por tipo" ganha "Outros
tipos" ("A não é assumido como M+V"), reaproveitando a cor do
bloco. "Meta do PCA" encolhe de 5 para 2 pares (Meta + Concluído (meta)) —
a decomposição detalhada da meta (em_tramitacao/no_prazo/fora_prazo,
restrita a NC|RN) sai do XLSX (orçamento de colunas do plano) e passa a
viver só na tela, no partial "Detalhar composição"
(`_resumo_uo_detalhamento.html`) — os valores continuam disponíveis no
dict de `calcular_resumo_uo`, só não são mais exportados aqui. 4 blocos
além de UO: "Previsto" (Total previsto/Cancelados/Ativos, INTOCADO),
"Por tipo" (NC/RN/VG/Outros tipos), "Situação dos ativos" (NOVO) e "Meta do
PCA" (Meta/Concluído (meta)). Colunas-SÍNTESE (Ativos e Meta) com dados em
negrito e o mesmo preenchimento `_COR_ATIVOS`; borda fina à esquerda da
primeira coluna de cada bloco em todas as linhas escritas.

Convenções aplicadas AQUI, e só aqui — a TELA
(`_resumo_uo_resultado.html`) usa tokens do design system, zero hex literal
(convenções do projeto); XLSX é arquivo, separa os dois formatos explicitamente:

- ausência (percentual com denominador zero, `None`) -> STRING `"-"`
  literal, nunca célula vazia, nunca "0%" fabricado.
- percentual calculável, mesmo que zero -> NÚMERO fração de Excel (0–1)
  com `number_format` `FORMATO_PERCENTUAL` ("0.0%") na célula — a exibição
  continua "X,X%" (1 casa, vírgula via locale pt-BR do Excel), idêntica
  para o leitor, mas a célula agora soma/filtra/entra em fórmula (Quick;
  antes era string explícita "X,X%").
- paleta por bloco de COLUNA no cabeçalho: identificação/total `#14314C`
  (fonte branca), Cancelados `#898781` (fonte branca, este é o único
  módulo do repositório onde hex literal vale), sínteses Ativos/Meta
  `#BDD7EE` (fonte preta), decomposição por tipo `#D9E1F2`, concluído
  `#548235` (fonte branca), em tramitação `#FFC000`, no prazo `#9BC2E6`,
  fora do prazo `#C00000` (fonte branca). A linha TOTAL inteira reaproveita
  o preenchimento identificação/total (`#14314C`/fonte branca).
- células mescladas de bloco que misturam cores de coluna por baixo
  ("Previsto" e "Meta do PCA") usam `_COR_NEUTRA` — mesmo precedente do
  antigo bloco "Andamento".
- SEM o destaque de linha CIT/COAD/COLOG da planilha original: essas
  siglas são da estrutura ANTIGA de UOs (pré-reforma administrativa) e não
  correspondem a nenhuma UO ativa hoje (14 UOs, estrutura GEX-*) — o
  de-para exato é do usuário e ainda não está confirmado
  (`<domain>`). A paleta de BLOCO (coluna) está
  implementada integralmente; o destaque de LINHA específica fica FORA DO
  ESCOPO de propósito.
- Todo valor é literal calculado em Python — nenhuma fórmula Excel
  replica os defeitos conhecidos da planilha original (K11 hardcoded, SUMs
  truncados, fórmulas não uniformes em I).
- T-172-02: nome de UO passa por `_texto_seguro` (de `exportacao.py`) antes
  de virar célula — defesa em profundidade, mesmo sendo dado de catálogo
  controlado, não input livre.
"""

from io import BytesIO

from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from apps.pca.exportacao import _texto_seguro

NOME_XLSX = "pca-resumo-por-uo.xlsx"

PREFIXO_PERCENTUAL = "percentual_"

# Formato de exibição das células de percentual (1 casa;
# a vírgula vem do locale pt-BR do Excel). Exportado como constante para os
# testes de contrato importarem em vez de repetir a string mágica.
FORMATO_PERCENTUAL = "0.0%"

_BRANCO = "FFFFFF"
_PRETO = "000000"
_COR_IDENTIFICACAO_TOTAL = "14314C"
# Renomeada de `_COR_NEUTRA_ANDAMENTO`: agora serve a
# qualquer célula mesclada de bloco que mistura cores de coluna por baixo
# ("Previsto" e "Meta do PCA"), não só ao extinto bloco "Andamento".
_COR_NEUTRA = "E7E6E6"

# `_COR_CANCELADOS` reaproveita o hex de
# `--cor-st-cancelado` do input.css (permite hex literal só aqui).
# `_COR_ATIVOS` vira a cor das DUAS colunas-síntese
# (Ativos e Meta), destacando-as das demais.
_COR_CANCELADOS = "898781"
_COR_ATIVOS = "BDD7EE"

# (chave em `linhas`/`total`, cabeçalho curto pt-BR, cor
# de fundo do bloco, cor de fonte do bloco). A ordem aqui é a ordem das
# colunas no arquivo E na tela (`resumo_uo.html` replica os mesmos
# cabeçalhos curtos — siglas NC/RN/VG inclusive).
COLUNAS = (
    ("uo", "UO", _COR_IDENTIFICACAO_TOTAL, _BRANCO),
    ("total_previsto", "Total previsto", _COR_IDENTIFICACAO_TOTAL, _BRANCO),
    ("percentual_no_pca", "% no PCA", _COR_IDENTIFICACAO_TOTAL, _BRANCO),
    ("cancelados", "Cancelados", _COR_CANCELADOS, _BRANCO),
    ("percentual_cancelados", "% Cancelados", _COR_CANCELADOS, _BRANCO),
    ("ativos", "Ativos", _COR_ATIVOS, _PRETO),
    ("percentual_ativos", "% Ativos", _COR_ATIVOS, _PRETO),
    ("nova", "NC", "D9E1F2", _PRETO),
    ("percentual_nova", "% NC", "D9E1F2", _PRETO),
    ("renovacao", "RN", "D9E1F2", _PRETO),
    ("percentual_renovacao", "% RN", "D9E1F2", _PRETO),
    ("vigente", "VG", "D9E1F2", _PRETO),
    ("percentual_vigente", "% VG", "D9E1F2", _PRETO),
    # "Outros tipos" (mesma cor do bloco "Por tipo").
    ("outros_tipos", "Outros tipos", "D9E1F2", _PRETO),
    ("percentual_outros_tipos", "% Outros tipos", "D9E1F2", _PRETO),
    # GRUPO NOVO "Situação dos ativos" (partição irrestrita
    # por tipo de A, percentuais /ativos); reaproveita as MESMAS 4 cores dos
    # 4 valores de `Situacao` já usadas no bloco "Meta do PCA" abaixo.
    ("concluido", "Concluídos", "548235", _BRANCO),
    ("percentual_concluido", "% Concluídos", "548235", _BRANCO),
    ("em_tramitacao_ativos", "Em tramitação", "FFC000", _PRETO),
    ("percentual_em_tramitacao_ativos", "% Em tramitação", "FFC000", _PRETO),
    ("no_prazo_ativos", "No prazo", "9BC2E6", _PRETO),
    ("percentual_no_prazo_ativos", "% No prazo", "9BC2E6", _PRETO),
    ("atrasado_ativos", "Atrasados", "C00000", _BRANCO),
    ("percentual_atrasado_ativos", "% Atrasados", "C00000", _BRANCO),
    # Meta do PCA — encolhe de 5 para 2 pares: a decomposição
    # detalhada (em_tramitacao/no_prazo/fora_prazo, restrita a NC|RN) sai
    # do XLSX e passa a viver só na tela ("Detalhar composição").
    ("meta", "Meta", _COR_ATIVOS, _PRETO),
    ("percentual_meta", "% Meta", _COR_ATIVOS, _PRETO),
    ("concluido_meta", "Concluído (meta)", "548235", _BRANCO),
    ("percentual_concluido_meta", "% Concluído (meta)", "548235", _BRANCO),
)

# Os 4 blocos da linha 1 do cabeçalho, mesclados
# sobre as colunas que cobrem: (rótulo do bloco, qtd de colunas de
# `COLUNAS` que ele cobre a partir daqui, cor de fundo, cor de fonte). `UO`
# mescla VERTICAL (linha 1 + linha 2), sem sub-colunas — tratado à parte,
# fora desta tupla. A soma das quantidades (sem contar UO) tem que bater
# com `len(COLUNAS) - 1` (26 colunas de indicador). "Previsto" e "Situação
# dos ativos"/"Meta do PCA" misturam cores de coluna por baixo ->
# `_COR_NEUTRA` na célula mesclada (mesmo precedente do antigo "Andamento").
BLOCOS = (
    ("Previsto", 6, _COR_NEUTRA, _PRETO),
    ("Por tipo", 8, "D9E1F2", _PRETO),
    ("Situação dos ativos", 8, _COR_NEUTRA, _PRETO),
    ("Meta do PCA", 4, _COR_NEUTRA, _PRETO),
)

# Primeira coluna de cada bloco (borda fina à
# esquerda em TODAS as linhas escritas) e pares de colunas-síntese (dados
# em negrito, cabeçalho já é bold). "concluido" agora abre o bloco
# "Situação dos ativos" (reposicionado; era o único membro do extinto
# bloco "Análise").
_CHAVES_BORDA_BLOCO = ("total_previsto", "nova", "concluido", "meta")
_CHAVES_SINTESE = ("ativos", "percentual_ativos", "meta", "percentual_meta")

_LEGENDA_SIGLAS = "NC = Nova Contratação · RN = Renovação · VG = Vigente"

_BORDA_BLOCO = Border(left=Side(style="thin"))


def _formatar_percentual(valor):
    """`None` (denominador zero, `_percentual` de kpis.py) vira o
    LITERAL `"-"`; qualquer percentual calculável, mesmo `0`, vira NÚMERO
    fração de Excel (`Decimal("12.5")` -> `0.125`) — nunca célula vazia,
    nunca zero implícito. A exibição (1 casa, vírgula pt-BR) vem de
    `FORMATO_PERCENTUAL` aplicado na célula + locale do Excel, não mais
    de string. Float em vez de Decimal por decisão
    do planner: evita surpresa de serialização no openpyxl; a precisão
    completa fica no número (útil para fórmulas) e o arredondamento é só
    de exibição, via `number_format`."""
    if valor is None:
        return "-"
    return float(valor) / 100


def _valor_celula(linha, chave):
    if chave.startswith(PREFIXO_PERCENTUAL):
        return _formatar_percentual(linha[chave])
    if chave == "uo":
        return _texto_seguro(linha[chave])
    return linha[chave]


def exportar_resumo_uo_xlsx(linhas, total):
    """Monta o XLSX do resumo por UO — 1 aba, cabeçalho de 2 linhas (bloco
    mesclado + coluna curta) colorido por bloco, N linhas de UO, 1 linha
    TOTAL destacada com o preenchimento identificação/total e 1 linha de
    nota com a legenda das siglas NC/RN/VG. `linhas`/`total` são o retorno
    exato de `apps.pca.resumo_uo.calcular_resumo_uo`, nenhum recálculo aqui
    (T-172-04)."""
    workbook = Workbook()
    ws = workbook.active
    ws.title = "Resumo por UO"

    chaves_colunas = [chave for chave, _, _, _ in COLUNAS]
    colunas_borda = [
        chaves_colunas.index(chave) + 1 for chave in _CHAVES_BORDA_BLOCO
    ]
    colunas_sintese = [
        chaves_colunas.index(chave) + 1 for chave in _CHAVES_SINTESE
    ]
    # Colunas de percentual (fração numérica + formato
    # de exibição), derivadas pelo prefixo, mesmo padrão de
    # `colunas_borda`/`colunas_sintese`.
    colunas_percentual = [
        indice
        for indice, chave in enumerate(chaves_colunas, start=1)
        if chave.startswith(PREFIXO_PERCENTUAL)
    ]

    # Linha 1 — cabeçalho de BLOCO. `UO` mescla verticalmente (linha 1+2),
    # sem sub-colunas.
    celula_uo = ws.cell(row=1, column=1, value="UO")
    ws.merge_cells(start_row=1, start_column=1, end_row=2, end_column=1)
    celula_uo.fill = PatternFill("solid", fgColor=_COR_IDENTIFICACAO_TOTAL)
    celula_uo.font = Font(color=_BRANCO, bold=True)
    celula_uo.alignment = Alignment(vertical="center")

    coluna_atual = 2  # coluna 1 já é "UO"
    for rotulo_bloco, quantidade, cor_fundo, cor_fonte in BLOCOS:
        celula_bloco = ws.cell(row=1, column=coluna_atual, value=rotulo_bloco)
        ws.merge_cells(
            start_row=1,
            start_column=coluna_atual,
            end_row=1,
            end_column=coluna_atual + quantidade - 1,
        )
        celula_bloco.fill = PatternFill("solid", fgColor=cor_fundo)
        celula_bloco.font = Font(color=cor_fonte, bold=True)
        celula_bloco.alignment = Alignment(horizontal="center")
        coluna_atual += quantidade

    # Linha 2 — cabeçalho de COLUNA (nomes curtos, um por entrada de
    # `COLUNAS`), cada um com a cor individual já documentada. `uo` (coluna
    # 1) fica de fora: já foi escrita acima, mesclada verticalmente com a
    # linha 1 — reescrevê-la aqui quebraria (`MergedCell` é read-only).
    for indice, (chave, cabecalho, cor_fundo, cor_fonte) in enumerate(COLUNAS, start=1):
        if chave == "uo":
            continue
        celula = ws.cell(row=2, column=indice, value=cabecalho)
        celula.fill = PatternFill("solid", fgColor=cor_fundo)
        celula.font = Font(color=cor_fonte, bold=True)

    for linha in linhas:
        ws.append([_valor_celula(linha, chave) for chave, _, _, _ in COLUNAS])
        # Colunas-síntese (Ativos/Meta + %) — dados em negrito.
        for indice in colunas_sintese:
            ws.cell(row=ws.max_row, column=indice).font = Font(bold=True)
        # Formato de percentual SÓ nas células
        # numéricas (fração); o "-" literal (denominador zero) é
        # str e fica sem formato.
        for indice in colunas_percentual:
            celula = ws.cell(row=ws.max_row, column=indice)
            if isinstance(celula.value, float):
                celula.number_format = FORMATO_PERCENTUAL

    ultima_linha_dados = ws.max_row  # 2 (cabeçalho) + N linhas de UO

    linha_total_indice = ultima_linha_dados + 1
    for indice, (chave, _, _, _) in enumerate(COLUNAS, start=1):
        celula = ws.cell(
            row=linha_total_indice, column=indice, value=_valor_celula(total, chave)
        )
        # Linha TOTAL inteira reaproveita o preenchimento
        # identificação/total, destacando-a de toda linha de UO.
        celula.fill = PatternFill("solid", fgColor=_COR_IDENTIFICACAO_TOTAL)
        celula.font = Font(color=_BRANCO, bold=True)
        # Mesmo tratamento numérico das linhas de UO:
        # fração + formato de percentual, só quando o valor é numérico
        # (o "-" literal fica sem formato).
        if chave.startswith(PREFIXO_PERCENTUAL) and isinstance(
            celula.value, float
        ):
            celula.number_format = FORMATO_PERCENTUAL

    # Borda fina à esquerda da PRIMEIRA coluna de cada
    # bloco, em TODAS as linhas escritas (2 de cabeçalho + UOs + TOTAL),
    # espelhando o separador vertical `border-l-2 border-baseline` da tela.
    for linha_indice in range(1, linha_total_indice + 1):
        for coluna_indice in colunas_borda:
            ws.cell(row=linha_indice, column=coluna_indice).border = _BORDA_BLOCO

    # (ajuste de escopo 01/09) — legenda das siglas do
    # bloco "Por tipo", como linha de nota abaixo do TOTAL.
    celula_legenda = ws.cell(
        row=linha_total_indice + 1, column=1, value=_LEGENDA_SIGLAS
    )
    celula_legenda.font = Font(italic=True, size=9)

    # Autofiltro/congelamento cobrem só a região UO (cabeçalho de coluna,
    # linha 2, + linhas de UO) — a linha TOTAL e a legenda ficam de fora,
    # mesmo princípio de `exportacao.py::exportar_xlsx` (não filtrar/ordenar
    # o total).
    ultima_coluna = get_column_letter(len(COLUNAS))
    ws.auto_filter.ref = f"A2:{ultima_coluna}{ultima_linha_dados}"
    ws.freeze_panes = "A3"

    for coluna_indice, (_chave, cabecalho, _cor_fundo, _cor_fonte) in enumerate(
        COLUNAS, start=1
    ):
        ws.column_dimensions[get_column_letter(coluna_indice)].width = min(
            max(len(cabecalho) + 2, 12), 28
        )

    buffer = BytesIO()
    workbook.save(buffer)
    resposta = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resposta["Content-Disposition"] = f'attachment; filename="{NOME_XLSX}"'
    return resposta
