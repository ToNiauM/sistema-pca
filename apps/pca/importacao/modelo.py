"""Modelo XLSX vazio e compatível com o importador do PCA."""

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.utils import get_column_letter, quote_sheetname

from apps.pca.exportacao import _texto_seguro
from apps.pca.importacao.executor import (
    COLUNAS_CATALOGO,
    SITUACAO_SEI_POR_ROTULO,
    TIPO_EVENTO_POR_ROTULO,
)
from apps.pca.importacao.parsers import MESES, STATUS_POR_ROTULO


NOME_ARQUIVO_MODELO = "modelo-importacao-pca.xlsx"

# a planilha modelo mantém o cabeçalho histórico "Data prevista para
# entrega" na posição 14; ImportadorPca lê Planilha1 só por posição,
# nunca compara texto de cabeçalho
CABECALHOS_PLANILHA1 = (
    "Item PCA (ID)", "Nº do Processo SEI", "Descrição do Objeto", "Justificativa",
    "Tipo de Contratação", "Categoria", "UO (Área Demandante)", "Valor Estimado (R$)",
    "Mês Previsto (PCA)", "Data de Inclusão no PCA", "Grau de Prioridade",
    "Classificação", "Data Envio ao Gelic", "Data prevista para entrega",
    "Data de Recebimento do Processo no Gelic", "Data Prevista/Conclusão da Contratação", "Status",
    "Data da Última Reunião", "Situação na Última Reunião", "Prazo Prometido Vigente",
    "Nº de Reuniões", "Nº de Compromissos Assumidos", "Situação do Prazo",
    "Dias em Atraso", "Data Recebimento do Processo",
    "Modalidade", "Vigência Início", "Vigência Fim", "Nº da Contratação", "Nº da ARP",
    "Instrumento Contratual", "Nº do Instrumento Contratual", "Valor Contratado (R$)",
    "CNPJ", "Razão Social", "Data Assinatura do Contrato", "Data Lançamento SPW",
    "Data Lançamento WordPress", "Data Lançamento Dados Abertos", "Situação do SEI",
)

CABECALHOS_ACOMPANHAMENTO = (
    "ID Registro", "ID Processo", "Nº do Processo SEI", "Data da Reunião", "Evento",
    "Tipo de Evento", "Situação Informada (original)", "Situação Normalizada",
    "Prazo Prometido", "Data do Evento Informada", "Área Informada",
)

CABECALHOS_AUXILIARES = (
    "Status", "Situação do SEI", "Tipo de Evento", "Mês Previsto (PCA)",
)

_PREENCHIMENTO_CABECALHO = PatternFill("solid", fgColor="1F4E78")
_FONTE_CABECALHO = Font(color="FFFFFF", bold=True)
_FORMATO_DATA = "dd/mm/yyyy"
_FORMATO_MOEDA = 'R$ #,##0.00'
_FORMATO_NUMERO = "0"


def _escrever_texto(aba, linha, coluna, valor):
    """Grava rótulos de catálogo sempre como texto, inclusive ``=valor``."""
    celula = aba.cell(row=linha, column=coluna, value=str(valor))
    celula.data_type = "s"
    return celula


def _preparar_aba(aba, cabecalhos):
    for coluna, cabecalho in enumerate(cabecalhos, start=1):
        celula = aba.cell(row=1, column=coluna, value=cabecalho)
        celula.fill = _PREENCHIMENTO_CABECALHO
        celula.font = _FONTE_CABECALHO
        celula.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        aba.column_dimensions[get_column_letter(coluna)].width = min(
            max(len(cabecalho) + 2, 14), 38
        )
    aba.freeze_panes = "A2"
    aba.auto_filter.ref = f"A1:{get_column_letter(len(cabecalhos))}1"


def _intervalo_lista(coluna, tamanho):
    return f"{quote_sheetname('Listas')}!${get_column_letter(coluna)}$2:${get_column_letter(coluna)}${max(tamanho + 1, 2)}"


def _adicionar_validacao(aba, destino, formula):
    validacao = DataValidation(type="list", formula1=formula, allow_blank=True)
    validacao.error = "Selecione um valor da lista fornecida no modelo."
    validacao.errorTitle = "Valor não reconhecido"
    validacao.prompt = "Escolha um dos valores cadastrados na aba Listas."
    validacao.promptTitle = "Valor aceito"
    aba.add_data_validation(validacao)
    validacao.add(destino)


def _formatar_colunas(aba, datas=(), moedas=(), numeros=()):
    for coluna in datas:
        aba.column_dimensions[get_column_letter(coluna)].number_format = _FORMATO_DATA
    for coluna in moedas:
        aba.column_dimensions[get_column_letter(coluna)].number_format = _FORMATO_MOEDA
    for coluna in numeros:
        aba.column_dimensions[get_column_letter(coluna)].number_format = _FORMATO_NUMERO


def _montar_workbook_base():
    """Estrutura comum às duas variantes do modelo: as 3 abas com
    cabeçalho/formatos/validações, e a aba Listas já preenchida a partir
    do banco. Devolve (workbook, planilha, acompanhamento)."""
    workbook = Workbook()
    planilha = workbook.active
    planilha.title = "Planilha1"
    acompanhamento = workbook.create_sheet("Acompanhamento")
    listas = workbook.create_sheet("Listas")

    _preparar_aba(planilha, CABECALHOS_PLANILHA1)
    _preparar_aba(acompanhamento, CABECALHOS_ACOMPANHAMENTO)
    _preparar_aba(listas, tuple(nome for nome, _ in COLUNAS_CATALOGO) + CABECALHOS_AUXILIARES)

    valores_por_coluna = []
    for _nome, modelo in COLUNAS_CATALOGO:
        valores_por_coluna.append(list(modelo.objects.order_by(*modelo._meta.ordering).values_list("nome", flat=True)))
    valores_por_coluna.extend(
        [
            list(STATUS_POR_ROTULO),
            list(SITUACAO_SEI_POR_ROTULO),
            list(TIPO_EVENTO_POR_ROTULO),
            list(MESES),
        ]
    )
    for coluna, valores in enumerate(valores_por_coluna, start=1):
        for linha, valor in enumerate(valores, start=2):
            _escrever_texto(listas, linha, coluna, valor)

    maior_linha_listas = max((len(valores) for valores in valores_por_coluna), default=1) + 1
    listas.auto_filter.ref = f"A1:{get_column_letter(len(valores_por_coluna))}{maior_linha_listas}"
    intervalos = [_intervalo_lista(coluna, len(valores)) for coluna, valores in enumerate(valores_por_coluna, start=1)]
    # Planilha1: catálogos, domínios TextChoices e listas auxiliares do
    # importador
    for destino, indice in {
        "E2:E1048576": 0, "F2:F1048576": 1, "G2:G1048576": 2,
        "K2:K1048576": 3, "L2:L1048576": 4, "Q2:Q1048576": 8,
        "Z2:Z1048576": 5, "AE2:AE1048576": 6,
        "AN2:AN1048576": 9, "I2:I1048576": 11,
    }.items():
        _adicionar_validacao(planilha, destino, intervalos[indice])
    # Acompanhamento: situação normalizada e tipo de evento entram no mesmo contrato
    _adicionar_validacao(acompanhamento, "F2:F1048576", intervalos[10])
    _adicionar_validacao(acompanhamento, "H2:H1048576", intervalos[7])

    _formatar_colunas(
        planilha,
        datas=(10, 13, 14, 15, 16, 18, 20, 25, 27, 28, 36, 37, 38, 39),
        moedas=(8, 33),
        numeros=(1, 21, 22, 24),
    )
    _formatar_colunas(acompanhamento, datas=(4, 9, 10), numeros=(1, 2))
    return workbook, planilha, acompanhamento


def gerar_modelo_importacao() -> BytesIO:
    """Monta em memória uma planilha vazia que o ``ImportadorPca`` consome."""
    workbook, _planilha, _acompanhamento = _montar_workbook_base()
    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()
    buffer.seek(0)
    return buffer


# mapa inverso de parsers.MESES: o modelo pré-preenchido grava a string
# de 3 letras, nunca o inteiro, porque é isso que parse_mes_previsto espera
_MESES_INVERSO = {numero: rotulo for rotulo, numero in MESES.items()}


def _status_legado_de(processo):
    """Só decide 'Cancelado' vs o resto, porque é só isso que
    _importar_processos consome da coluna Status legado."""
    from apps.pca.models import Estado, Situacao

    if processo.estado == Estado.CANCELADO:
        return "Cancelado"
    if processo.situacao_efetiva == Situacao.CONCLUIDO:
        return "Concluído"
    if processo.data_recebimento_gelic is not None:
        return "Em tramitação"
    return "Não iniciado"


def _texto_seguro_ou_none(valor):
    """_texto_seguro só neutraliza formula injection; aqui também
    colapsamos string vazia em None (célula em branco)."""
    if not valor:
        return None
    return _texto_seguro(valor)


def _linha_processo(processo):
    numeros_sei = " ".join(sei.numero_sei for sei in processo.numeros_sei.all())
    return [
        processo.item_pca,
        _texto_seguro_ou_none(numeros_sei),
        _texto_seguro(processo.descricao_objeto),
        _texto_seguro_ou_none(processo.justificativa),
        processo.tipo.nome,
        processo.categoria.nome,
        processo.unidade_organizacional.nome,
        processo.valor_estimado,
        _MESES_INVERSO.get(processo.mes_previsto),
        processo.data_inclusao_pca,
        processo.grau_prioridade.nome if processo.grau_prioridade else None,
        processo.classificacao.nome if processo.classificacao else None,
        processo.data_envio_gelic,
        processo.prazo_entrega,
        processo.data_recebimento_gelic,
        processo.data_prevista_conclusao,
        _status_legado_de(processo),
        None,  # Data da Última Reunião — decorativa, não lida pelo executor
        processo.situacao_atual,
        processo.prazo_vigente,
        processo.n_reunioes,
        processo.n_compromissos,
        processo.qualificador_prazo,
        processo.dias_atraso,
        None,  # Data Recebimento do Processo — não lida pelo executor
        processo.modalidade.nome if processo.modalidade else None,
        processo.vigencia_inicio,
        processo.vigencia_fim,
        _texto_seguro_ou_none(processo.numero_contratacao),
        _texto_seguro_ou_none(processo.numero_arp),
        processo.instrumento_contratual.nome if processo.instrumento_contratual else None,
        _texto_seguro_ou_none(processo.numero_instrumento_contratual),
        processo.valor_contratado,
        processo.fornecedor_cnpj,
        _texto_seguro_ou_none(processo.fornecedor_razao_social),
        processo.data_assinatura_contrato,
        processo.data_lancamento_spw,
        processo.data_lancamento_wordpress,
        processo.data_lancamento_dados_abertos,
        processo.get_situacao_sei_display() if processo.situacao_sei else None,
    ]


def _linha_acompanhamento(acompanhamento):
    return [
        acompanhamento.pk,
        acompanhamento.processo.item_pca,
        None,  # Nº do Processo SEI — decorativa, sem vínculo direto na aba
        acompanhamento.referencia_data,
        _texto_seguro_ou_none(acompanhamento.evento),
        acompanhamento.get_tipo_evento_display(),
        _texto_seguro_ou_none(acompanhamento.situacao_informada),
        acompanhamento.situacao.nome,
        acompanhamento.prazo_prometido,
        acompanhamento.data_evento_informada,
        _texto_seguro_ou_none(acompanhamento.area_informada),
    ]


def gerar_modelo_preenchido(exercicio) -> BytesIO:
    """Mesmo contrato de gerar_modelo_importacao(), mas Planilha1 e
    Acompanhamento nascem com uma linha por registro atual do exercicio."""
    from apps.pca.models import Acompanhamento, Processo

    workbook, planilha, acompanhamento = _montar_workbook_base()

    # query única, sem N+1: não busca FK por linha
    processos = list(
        Processo.objects.para_listagem()
        .filter(exercicio=exercicio)
        .select_related(
            "tipo", "categoria", "unidade_organizacional", "grau_prioridade",
            "classificacao", "modalidade", "instrumento_contratual",
        )
        .prefetch_related("numeros_sei")
        .order_by("item_pca")
    )
    acompanhamentos = list(
        Acompanhamento.objects.filter(processo__exercicio=exercicio)
        .select_related("processo", "situacao")
        .order_by("processo__item_pca", "referencia_data")
    )

    for linha, processo in enumerate(processos, start=2):
        for coluna, valor in enumerate(_linha_processo(processo), start=1):
            planilha.cell(row=linha, column=coluna, value=valor)
    for linha, item in enumerate(acompanhamentos, start=2):
        for coluna, valor in enumerate(_linha_acompanhamento(item), start=1):
            acompanhamento.cell(row=linha, column=coluna, value=valor)

    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()
    buffer.seek(0)
    return buffer
