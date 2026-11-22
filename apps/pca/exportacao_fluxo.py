"""Relatório XLSX do fluxo de caixa projetado — Oficial × Simulado (Fase 37, documento interno de desenho §0 decisão 6/§6). Módulo PURO de montagem de planilha:
recebe só argumentos já calculados pela view (`views_analise.py::
_contexto_fluxo`) — NUNCA importa `apps.pca.views_analise` nem chama
`apps.pca.projecao.fluxo` (a função nunca roda o motor, só lê `Projecao` já
pronta), mesma disciplina de `apps/pca/exportacao.py`. -SC: nenhum
pacote novo — só a openpyxl já travada em `requirements.txt`.

5 abas, nesta ordem (spec §6): Resumo, Anual, Contratações, Parcelas,
Memória. `_texto_seguro` (reaproveitado de `apps.pca.exportacao`) neutraliza toda célula derivada de texto livre do usuário (nome/
descrição de cenário, filtros em texto, objeto do processo, fórmula da
memória de cálculo) — mesma disciplina anti-fórmula do resto do sistema,
sem duplicar a lista de prefixos."""

import re
import unicodedata
from decimal import Decimal
from io import BytesIO

from django.http import HttpResponse
from django.utils.timezone import localtime, now
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from apps.pca.exportacao import FORMATO_MOEDA, _texto_seguro
from apps.pca.projecao import CAMADAS, ROTULOS_CAMADA

# Formato numérico nativo (não o "%" embutido do Excel, que multiplica por
# 100 — `percentual_contratado` já chega em pontos percentuais 0-100) com o sinal só como sufixo de exibição.
FORMATO_PERCENTUAL = '0.0"%"'

MENSAGEM_SEM_RECORTE = (
    "Nenhum recorte selecionado — filtre por ano na tela para detalhar contratações."
)


def _slug(texto):
    """`cenario_slug` do nome do arquivo — minúsculas, sem acento, só
    `[a-z0-9-]`; nunca deriva do texto livre do usuário sem sanitizar (o
    nome do cenário pode conter qualquer caractere, inclusive `/`)."""
    sem_acento = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", sem_acento.lower()).strip("-")
    return slug or "cenario"


def exportar_fluxo_xlsx(
    *,
    exercicio,
    cenario_nome,
    cenario_rotulo,
    autor,
    filtros_ativos_texto,
    variaveis_simuladas,
    projecao_oficial,
    projecao_simulada,
    lista_recorte,
    anos_horizonte,
):
    """5 abas do relatório de fluxo de caixa — `HttpResponse` pronta pra
    download. `projecao_simulada`/`lista_recorte` podem ser `None`/`[]`
    (sem comparação ativa/sem recorte selecionado, respectivamente) — cada
    aba trata a ausência sem lançar."""
    planilha = Workbook()
    _aba_resumo(
        planilha.active,
        exercicio=exercicio,
        cenario_rotulo=cenario_rotulo,
        autor=autor,
        filtros_ativos_texto=filtros_ativos_texto,
        variaveis_simuladas=variaveis_simuladas,
        projecao_oficial=projecao_oficial,
        projecao_simulada=projecao_simulada,
    )
    _aba_anual(
        planilha.create_sheet("Anual"),
        projecao_oficial=projecao_oficial,
        projecao_simulada=projecao_simulada,
        anos_horizonte=anos_horizonte,
    )
    _aba_contratacoes(planilha.create_sheet("Contratações"), lista_recorte=lista_recorte)
    _aba_parcelas(
        planilha.create_sheet("Parcelas"),
        projecao_oficial=projecao_oficial,
        projecao_simulada=projecao_simulada,
    )
    _aba_memoria(
        planilha.create_sheet("Memória"),
        projecao_oficial=projecao_oficial,
        lista_recorte=lista_recorte,
    )

    buffer = BytesIO()
    planilha.save(buffer)
    resposta = HttpResponse(
        buffer.getvalue(),
        content_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
    )
    nome_arquivo = f"pca-fluxo-de-caixa-{exercicio.ano}-{_slug(cenario_nome)}.xlsx"
    resposta["Content-Disposition"] = f'attachment; filename="{nome_arquivo}"'
    resposta["Cache-Control"] = "private, no-store"
    return resposta


def _cabecalho(ws, colunas):
    ws.append(colunas)
    for indice in range(1, len(colunas) + 1):
        ws.cell(row=1, column=indice).font = Font(bold=True)


# --------------------------------------------------------------------------
# Aba 1 — Resumo: identificação do relatório, filtros/cenário em texto,
# variáveis simuladas e os 4 KPIs da tela (Oficial | Simulado | Δ, exceto
# "% contratado", só oficial — mesma decisão de `analise_fluxo_view`, spec
# §3.4/ dividir por um denominador que muda com a
# simulação tornaria a leitura ambígua).


def _aba_resumo(
    ws,
    *,
    exercicio,
    cenario_rotulo,
    autor,
    filtros_ativos_texto,
    variaveis_simuladas,
    projecao_oficial,
    projecao_simulada,
):
    ws.title = "Resumo"
    ws.column_dimensions["A"].width = 44
    for letra in ("B", "C", "D"):
        ws.column_dimensions[letra].width = 20

    # QA 30/09 (periferia nº2) — `ws.max_row` (openpyxl faz `max()` sobre
    # todas as células já escritas) é custo QUADRÁTICO quando lido dentro
    # de um laço proporcional a N; contador local `linha_atual`, só
    # incrementado a cada `ws.append` de 1 linha de dado.
    linha_atual = 0

    ws.append(["PCA CFC — Acompanhamento do Plano de Contratações Anual"])
    linha_atual += 1
    ws.cell(row=linha_atual, column=1).font = Font(bold=True)
    ws.append(["Fluxo de caixa projetado"])
    linha_atual += 1
    ws.append([f"Exercício: {exercicio.ano}"])
    linha_atual += 1
    # openpyxl recusa `datetime` com `tzinfo` (Excel não representa fuso em
    # data/hora) — `localtime(now())` converte para America/Sao_Paulo
    # (convenções do projeto/Localização) e `.replace(tzinfo=None)` descarta só a
    # ETIQUETA do fuso, mantendo os campos já convertidos (mesmo valor de
    # parede que `data_br`/`|date` mostrariam).
    ws.append(["Gerado em:", localtime(now()).replace(tzinfo=None)])
    linha_atual += 1
    ws.cell(row=linha_atual, column=2).number_format = "dd/mm/yyyy hh:mm"
    ws.append([f"Autor: {_texto_seguro(autor)}"])
    linha_atual += 1
    ws.append([f"Filtros ativos: {_texto_seguro(filtros_ativos_texto)}"])
    linha_atual += 1
    ws.append([f"Cenário: {_texto_seguro(cenario_rotulo)}"])
    linha_atual += 1
    ws.append([])
    linha_atual += 1

    if variaveis_simuladas:
        ws.append(["Variáveis simuladas"])
        linha_atual += 1
        ws.cell(row=linha_atual, column=1).font = Font(bold=True)
        for variavel in variaveis_simuladas:
            ws.append([_texto_seguro(variavel)])
            linha_atual += 1
        ws.append([])
        linha_atual += 1

    _cabecalho(ws, ["Indicador", "Oficial (R$)", "Simulado (R$)", "Δ (R$)"])
    linha_atual += 1  # _cabecalho já fez 1 ws.append (a linha do cabeçalho)

    linhas_kpi = [
        (
            "A pagar até 31/12",
            projecao_oficial.totais["ate_fim_exercicio"],
            projecao_simulada.totais["ate_fim_exercicio"] if projecao_simulada else None,
        ),
        (
            f"Projeção {exercicio.ano + 1}",
            projecao_oficial.totais["proximo_ano"],
            projecao_simulada.totais["proximo_ano"] if projecao_simulada else None,
        ),
        (
            f"Projeção {exercicio.ano + 1}–{exercicio.ano + 5}",
            projecao_oficial.totais["cinco_anos"],
            projecao_simulada.totais["cinco_anos"] if projecao_simulada else None,
        ),
    ]
    for rotulo, oficial, simulado in linhas_kpi:
        delta = (simulado - oficial) if simulado is not None else None
        ws.append([rotulo, oficial, simulado, delta])
        linha_atual += 1
        for coluna in (2, 3, 4):
            ws.cell(row=linha_atual, column=coluna).number_format = FORMATO_MOEDA

    ws.append(["% contratado", projecao_oficial.totais["percentual_contratado"], None, None])
    linha_atual += 1
    ws.cell(row=linha_atual, column=2).number_format = FORMATO_PERCENTUAL


# --------------------------------------------------------------------------
# Aba 2 — Anual: uma linha por (ano, camada) do MESMO horizonte único da
# tela (`_anos_horizonte`, exercício..exercício+5, M11) — os totais somados
# por ano batem com `Projecao.por_ano` porque são lidos direto dele, sem
# recalcular nada.


def _aba_anual(ws, *, projecao_oficial, projecao_simulada, anos_horizonte):
    _cabecalho(ws, ["Ano", "Camada", "Oficial (R$)", "Simulado (R$)", "Δ (R$)"])
    linha_atual = 1  # a linha 1 já é o cabeçalho
    ws.column_dimensions["A"].width = 10
    ws.column_dimensions["B"].width = 22
    for letra in ("C", "D", "E"):
        ws.column_dimensions[letra].width = 18

    for ano in anos_horizonte:
        valores_oficial_ano = projecao_oficial.por_ano.get(ano, {})
        valores_simulado_ano = (
            projecao_simulada.por_ano.get(ano, {}) if projecao_simulada is not None else {}
        )
        for camada in CAMADAS:
            oficial = valores_oficial_ano.get(camada, Decimal("0"))
            simulado = (
                valores_simulado_ano.get(camada, Decimal("0"))
                if projecao_simulada is not None
                else None
            )
            delta = (simulado - oficial) if simulado is not None else None
            ws.append([ano, ROTULOS_CAMADA[camada], oficial, simulado, delta])
            linha_atual += 1
            for coluna in (3, 4, 5):
                ws.cell(row=linha_atual, column=coluna).number_format = FORMATO_MOEDA

    ws.auto_filter.ref = f"A1:E{linha_atual}"
    ws.freeze_panes = "A2"


# --------------------------------------------------------------------------
# Aba 3 — Contratações: a MESMA lista "Contratações neste recorte" da tela,
#já agregada por item — sem recorte ativo, só o
# cabeçalho + aviso (nunca uma aba vazia sem explicação).


def _aba_contratacoes(ws, *, lista_recorte):
    colunas = ["Item", "Objeto", "Unidade", "Instrumento(s)", *ROTULOS_CAMADA.values(), "Total (R$)"]
    _cabecalho(ws, colunas)
    linha_atual = 1  # a linha 1 já é o cabeçalho
    ws.column_dimensions["A"].width = 10
    ws.column_dimensions["B"].width = 50
    ws.column_dimensions["C"].width = 24
    ws.column_dimensions["D"].width = 24

    if not lista_recorte:
        ws.append([MENSAGEM_SEM_RECORTE])
        return

    primeira_coluna_decimal = 5
    for linha_dado in lista_recorte:
        ws.append(
            [
                linha_dado["item_pca"],
                _texto_seguro(linha_dado["objeto"] or ""),
                _texto_seguro(linha_dado["uo"]),
                _texto_seguro(linha_dado["instrumentos"]),
                *[linha_dado["valores_por_camada"][camada] for camada in ROTULOS_CAMADA],
                linha_dado["total"],
            ]
        )
        linha_atual += 1
        for coluna in range(primeira_coluna_decimal, primeira_coluna_decimal + len(ROTULOS_CAMADA) + 1):
            ws.cell(row=linha_atual, column=coluna).number_format = FORMATO_MOEDA

    ws.auto_filter.ref = f"A1:{get_column_letter(len(colunas))}{linha_atual}"
    ws.freeze_panes = "A2"


# --------------------------------------------------------------------------
# Aba 4 — Parcelas: uma linha por `Parcela` de `projecao_oficial.parcelas`
# (nunca do simulado — spec), casada com o valor equivalente
# SIMULADO por `(item_pca, instrumento, competencia, camada)` quando há
# comparação ativa; ausência (ex. item excluído da simulação) fica em
# branco, nunca `0` (célula vazia é ausência real, `0` seria um
# falso valor plausível).


def _aba_parcelas(ws, *, projecao_oficial, projecao_simulada):
    tem_simulado = projecao_simulada is not None
    colunas = ["Item", "Instrumento", "Competência", "Camada", "Valor Oficial (R$)", "Origem"]
    if tem_simulado:
        colunas.append("Valor Simulado (R$)")
    _cabecalho(ws, colunas)
    linha_atual = 1  # a linha 1 já é o cabeçalho
    ws.column_dimensions["A"].width = 10
    ws.column_dimensions["B"].width = 20
    ws.column_dimensions["C"].width = 14
    ws.column_dimensions["D"].width = 20
    ws.column_dimensions["E"].width = 18
    ws.column_dimensions["F"].width = 14
    if tem_simulado:
        ws.column_dimensions["G"].width = 18

    mapa_simulado = {}
    if tem_simulado:
        for p in projecao_simulada.parcelas:
            mapa_simulado[(p.item_pca, p.instrumento, p.competencia, p.camada)] = p.valor

    for p in projecao_oficial.parcelas:
        linha = [
            p.item_pca,
            _texto_seguro(p.instrumento),
            p.competencia,
            ROTULOS_CAMADA.get(p.camada, p.camada),
            p.valor,
            p.origem,
        ]
        if tem_simulado:
            linha.append(mapa_simulado.get((p.item_pca, p.instrumento, p.competencia, p.camada)))
        ws.append(linha)
        linha_atual += 1
        ws.cell(row=linha_atual, column=5).number_format = FORMATO_MOEDA
        if tem_simulado:
            celula_simulado = ws.cell(row=linha_atual, column=7)
            if celula_simulado.value is not None:
                celula_simulado.number_format = FORMATO_MOEDA

    if linha_atual > 1:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(colunas))}{linha_atual}"
        ws.freeze_panes = "A2"


# --------------------------------------------------------------------------
# Aba 5 — Memória: uma linha por `LinhaMemoria` de cada item do MESMO
# recorte da aba Contratações (`Projecao.memorias`) — nunca
# recalculada, só lida.


def _aba_memoria(ws, *, projecao_oficial, lista_recorte):
    _cabecalho(ws, ["Item", "Competência", "Camada", "Valor (R$)", "Fórmula"])
    linha_atual = 1  # a linha 1 já é o cabeçalho
    ws.column_dimensions["A"].width = 10
    ws.column_dimensions["B"].width = 14
    ws.column_dimensions["C"].width = 20
    ws.column_dimensions["D"].width = 16
    ws.column_dimensions["E"].width = 60

    if not lista_recorte:
        ws.append([MENSAGEM_SEM_RECORTE])
        return

    for linha_dado in lista_recorte:
        memoria = projecao_oficial.memorias.get(linha_dado["item_pca"])
        if memoria is None:
            continue
        for linha_memoria in sorted(memoria.linhas, key=lambda l: l.competencia):
            ws.append(
                [
                    linha_dado["item_pca"],
                    linha_memoria.competencia,
                    ROTULOS_CAMADA.get(linha_memoria.camada, linha_memoria.camada),
                    linha_memoria.valor,
                    _texto_seguro(linha_memoria.formula),
                ]
            )
            linha_atual += 1
            ws.cell(row=linha_atual, column=4).number_format = FORMATO_MOEDA

    if linha_atual > 1:
        ws.auto_filter.ref = f"A1:E{linha_atual}"
        ws.freeze_panes = "A2"
