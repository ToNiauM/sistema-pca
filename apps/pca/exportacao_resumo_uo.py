"""Export XLSX do resumo por UO: 27 colunas (13 indicadores + UO) com
cabeçalho de bloco mesclado; `linhas`/`total` chegam prontos, este módulo só
formata e escreve, nunca recalcula.

Convenções:
- ausência (percentual com denominador zero) vira string "-" literal.
- percentual calculável vira número fração de Excel (0-1) com
  number_format "0.0%" na célula, para poder somar/filtrar.
- paleta por bloco de coluna no cabeçalho, hex literal só neste módulo
  (arquivo, não tela).
- todo valor é literal calculado em Python, nenhuma fórmula Excel replica
  os defeitos da planilha original.
- nome de UO passa por `_texto_seguro` antes de virar célula.
"""

from io import BytesIO

from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from apps.pca.exportacao import _texto_seguro

NOME_XLSX = "pca-resumo-por-uo.xlsx"

PREFIXO_PERCENTUAL = "percentual_"

# formato de exibição das células de percentual; exportado para os testes de contrato
FORMATO_PERCENTUAL = "0.0%"

_BRANCO = "FFFFFF"
_PRETO = "000000"
_COR_IDENTIFICACAO_TOTAL = "14314C"
# célula mesclada de bloco que mistura cores de coluna por baixo
_COR_NEUTRA = "E7E6E6"

# _COR_ATIVOS destaca as duas colunas-síntese (Ativos e Meta)
_COR_CANCELADOS = "898781"
_COR_ATIVOS = "BDD7EE"

# (chave em linhas/total, cabeçalho curto pt-BR, cor de fundo, cor de fonte);
# ordem aqui é a ordem das colunas no arquivo e na tela
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
    # "Outros tipos", mesma cor do bloco "Por tipo"
    ("outros_tipos", "Outros tipos", "D9E1F2", _PRETO),
    ("percentual_outros_tipos", "% Outros tipos", "D9E1F2", _PRETO),
    # "Situação dos ativos" (partição irrestrita por tipo de A);
    # reaproveita as mesmas 4 cores de Situacao usadas em "Meta do PCA"
    ("concluido", "Concluídos", "548235", _BRANCO),
    ("percentual_concluido", "% Concluídos", "548235", _BRANCO),
    ("em_tramitacao_ativos", "Em tramitação", "FFC000", _PRETO),
    ("percentual_em_tramitacao_ativos", "% Em tramitação", "FFC000", _PRETO),
    ("no_prazo_ativos", "No prazo", "9BC2E6", _PRETO),
    ("percentual_no_prazo_ativos", "% No prazo", "9BC2E6", _PRETO),
    ("atrasado_ativos", "Atrasados", "C00000", _BRANCO),
    ("percentual_atrasado_ativos", "% Atrasados", "C00000", _BRANCO),
    # Meta do PCA — decomposição detalhada vive só na tela ("Detalhar composição")
    ("meta", "Meta", _COR_ATIVOS, _PRETO),
    ("percentual_meta", "% Meta", _COR_ATIVOS, _PRETO),
    ("concluido_meta", "Concluído (meta)", "548235", _BRANCO),
    ("percentual_concluido_meta", "% Concluído (meta)", "548235", _BRANCO),
)

# os 4 blocos da linha 1 do cabeçalho: (rótulo, qtd de colunas que cobre,
# cor de fundo, cor de fonte). UO mescla vertical, tratado à parte
BLOCOS = (
    ("Previsto", 6, _COR_NEUTRA, _PRETO),
    ("Por tipo", 8, "D9E1F2", _PRETO),
    ("Situação dos ativos", 8, _COR_NEUTRA, _PRETO),
    ("Meta do PCA", 4, _COR_NEUTRA, _PRETO),
)

# primeira coluna de cada bloco (borda fina à esquerda) e colunas-síntese (dados em negrito)
_CHAVES_BORDA_BLOCO = ("total_previsto", "nova", "concluido", "meta")
_CHAVES_SINTESE = ("ativos", "percentual_ativos", "meta", "percentual_meta")

_LEGENDA_SIGLAS = "NC = Nova Contratação · RN = Renovação · VG = Vigente"

_BORDA_BLOCO = Border(left=Side(style="thin"))


def _formatar_percentual(valor):
    """None (denominador zero) vira o literal "-"; qualquer percentual
    calculável vira número fração de Excel, formatado via number_format."""
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
    """Monta o XLSX do resumo por UO: 1 aba, cabeçalho de 2 linhas colorido
    por bloco, N linhas de UO, 1 linha TOTAL destacada e 1 linha de nota
    com a legenda das siglas. Nenhum recálculo aqui."""
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
    # colunas de percentual (fração numérica + formato), derivadas pelo prefixo
    colunas_percentual = [
        indice
        for indice, chave in enumerate(chaves_colunas, start=1)
        if chave.startswith(PREFIXO_PERCENTUAL)
    ]

    # linha 1 — cabeçalho de bloco; UO mescla verticalmente, sem sub-colunas
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

    # linha 2 — cabeçalho de coluna (nomes curtos); uo fica de fora, já escrita acima
    for indice, (chave, cabecalho, cor_fundo, cor_fonte) in enumerate(COLUNAS, start=1):
        if chave == "uo":
            continue
        celula = ws.cell(row=2, column=indice, value=cabecalho)
        celula.fill = PatternFill("solid", fgColor=cor_fundo)
        celula.font = Font(color=cor_fonte, bold=True)

    for linha in linhas:
        ws.append([_valor_celula(linha, chave) for chave, _, _, _ in COLUNAS])
        # colunas-síntese (Ativos/Meta + %) — dados em negrito
        for indice in colunas_sintese:
            ws.cell(row=ws.max_row, column=indice).font = Font(bold=True)
        # formato de percentual só nas células numéricas; "-" literal fica sem formato
        for indice in colunas_percentual:
            celula = ws.cell(row=ws.max_row, column=indice)
            if isinstance(celula.value, float):
                celula.number_format = FORMATO_PERCENTUAL

    ultima_linha_dados = ws.max_row

    linha_total_indice = ultima_linha_dados + 1
    for indice, (chave, _, _, _) in enumerate(COLUNAS, start=1):
        celula = ws.cell(
            row=linha_total_indice, column=indice, value=_valor_celula(total, chave)
        )
        # linha TOTAL inteira reaproveita o preenchimento identificação/total
        celula.fill = PatternFill("solid", fgColor=_COR_IDENTIFICACAO_TOTAL)
        celula.font = Font(color=_BRANCO, bold=True)
        # mesmo tratamento numérico das linhas de UO; "-" literal fica sem formato
        if chave.startswith(PREFIXO_PERCENTUAL) and isinstance(
            celula.value, float
        ):
            celula.number_format = FORMATO_PERCENTUAL

    # borda fina à esquerda da primeira coluna de cada bloco, em todas as linhas escritas
    for linha_indice in range(1, linha_total_indice + 1):
        for coluna_indice in colunas_borda:
            ws.cell(row=linha_indice, column=coluna_indice).border = _BORDA_BLOCO

    # legenda das siglas do bloco "Por tipo", como linha de nota abaixo do TOTAL
    celula_legenda = ws.cell(
        row=linha_total_indice + 1, column=1, value=_LEGENDA_SIGLAS
    )
    celula_legenda.font = Font(italic=True, size=9)

    # autofiltro/congelamento cobrem só a região UO; TOTAL e legenda ficam de fora
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
