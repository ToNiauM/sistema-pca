"""Serialização compartilhada dos downloads CSV/XLSX (02-04).

Fase 28 — a ESPECIFICAÇÃO ÚNICA de
colunas deixa de ser duplicada aqui: `COLUNAS` é derivada de
`apps.pca.colunas.COLUNAS` (já a fonte única da TELA), com o
vocabulário de `tipo` mapeado ao interno deste módulo
(`TIPO_TEXTO`/`TIPO_INTEIRO`/`TIPO_DECIMAL`/`TIPO_DATA`, usado pelos loops
de formatação de `exportar_csv`/`exportar_xlsx` — ver `_MAPA_TIPO_TELA`
abaixo). original: cadastro completo (identidade e planejamento) +
as derivadas de histórico e de prazo (Fase 11: prazo
planejado, promessa vigente, prazo efetivo, dias em atraso, prorrogações);
o bloco de execução contratual fica fora enquanto estiver vazio (Fase 4 o
acrescenta).

Convenções fechadas (Armadilha 22):

- ** (inversão deliberada):** ausência é CÉLULA VAZIA no
  arquivo — nunca o rótulo cinza da tela ("Não classificado", "Sem mês
  previsto", "Não informado"). Texto no lugar de número quebra `SUM()`,
  filtro "(Vazias)" e ordenação no Excel pt-BR. Exceção específica desde a
  `mes_previsto` deixou de ser a exceção numérica que a
  Fase 28 abria (ver `_EXCECOES_TIPO` abaixo, removida) — pedido
  explícito do usuário para o mês sair por extenso ("Janeiro".."Dezembro")
  também no arquivo, igual às telas; célula vazia continua vazia (nunca
  "Sem mês previsto"), só o valor presente deixa de ser o inteiro 1-12.
  Nenhuma outra coluna numérica muda.
- ** ** múltiplos nºs SEI são concatenados numa única célula,
  separados por UM espaço — a invariante de uma linha por processo (149
  linhas para 149 processos) é o que mantém o `SUM()` da coluna de valor
  confiável.
- **CSV:** separador `;`, BOM UTF-8 (`utf-8-sig`), datas `DD/MM/AAAA` e
  decimal com vírgula (representação exclusiva do CSV; o XLSX carrega
  tipos nativos), para o Excel pt-BR abrir com colunas separadas, acentos
  corretos e números somáveis sem nenhum "Assistente de importação".
- **XLSX:** `Decimal`/`int`/`date` nativos com `number_format` — nunca
  texto formatado no servidor —, autofiltro, cabeçalho congelado e linha
  de total com `SUM()` real sobre as colunas monetárias selecionadas
  (generalizado para valor previsto e contratado).
- ** ** todo campo textual passa pela neutralização de formula
  injection (prefixo `'` quando inicia por `=`, `+`, `-` ou `@`, mesmo
  após espaços) — o banco vira conteúdo interpretável por planilha.
- ** -SC:** somente a openpyxl já travada em requirements.txt; nenhum
  pacote novo é instalado para o export.
"""

import csv
from datetime import date
from decimal import Decimal
from io import BytesIO, StringIO

from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment
from openpyxl.utils import get_column_letter

from apps.pca.colunas import COLUNAS as _COLUNAS_TELA
from apps.pca.colunas import canonizar
from apps.pca.filtros import NOMES_MES
from apps.pca.models import Estado, Situacao

# Fallback usado só quando `exercicio=None` é passado (chamador legado,
# nenhum consumidor vivo hoje) — nome/aba dinâmicos pelo exercício efetivo
# são o caminho normal desde (ver `_nome_arquivo`/`_titulo_aba`).
NOME_CSV = "pca-2026-processos.csv"
NOME_XLSX = "pca-2026-processos.xlsx"

# Sem prefixo "R$" (Decisão 2), caminho independente do
# filtro `moeda` (`number_format` nativo do openpyxl sobre células Decimal).
FORMATO_MOEDA = "#,##0.00"
FORMATO_DATA = "dd/mm/yyyy"

# Prefixos que o Excel interpreta como início de fórmula.
PREFIXOS_FORMULA = ("=", "+", "-", "@")

TIPO_TEXTO = "texto"
TIPO_INTEIRO = "inteiro"
TIPO_DECIMAL = "decimal"
TIPO_DATA = "data"

# /achado 5 — vocabulário de `tipo` da TELA
# (`apps.pca.colunas`) mapeado ao vocabulário INTERNO deste módulo.
# `status`/`booleano` viram TIPO_TEXTO porque `_extrair` já devolve a
# STRING final formatada ("Cancelado"/"Sim"/"Não") para essas chaves —
# tratá-las como texto no XLSX é correto, sem duplicar lógica.
_MAPA_TIPO_TELA = {
    "numero": TIPO_INTEIRO,
    "moeda": TIPO_DECIMAL,
    "data": TIPO_DATA,
    "texto": TIPO_TEXTO,
    "status": TIPO_TEXTO,
    "booleano": TIPO_TEXTO,
}

# (reversão da exceção original da Fase 28) —
# `mes_previsto` segue o vocabulário LITERAL da tela ("texto",
# `apps.pca.colunas`): o arquivo mostra o nome do mês por extenso
# (`NOMES_MES`, ver `_extrair`), igual à tela e ao restante do sistema.
# convenções do projeto (Localização) continua exigindo o inteiro 1-12 só no BANCO —
# nunca disse que o ARQUIVO exportado precisa repetir o dado cru; célula
# vazia continua vazia para o item sem mês (não muda). Nenhuma outra
# coluna numérica é afetada — este dicionário fica vazio de propósito,
# mantido só para o próximo achado não reinventar o mecanismo.
_EXCECOES_TIPO = {}


def _cabecalho_export(coluna):
    """Rótulo do arquivo = rótulo da tela, com a unidade monetária
    explícita nas 2 colunas de valor ("rótulos claros com
    unidade monetária"): a tela já comunica a unidade por fora do texto
    do cabeçalho (moeda formatada na própria célula), o arquivo não."""
    if coluna.tipo == "moeda":
        return f"{coluna.rotulo} (R$)"
    return coluna.rotulo


# Fonte ÚNICA de colunas: `apps.pca.colunas.COLUNAS` (Plano
# 28-02), mapeada ao vocabulário de tipo interno (`_MAPA_TIPO_TELA`,
# exceção `_EXCECOES_TIPO`). A tupla preserva a forma (chave, cabeçalho,
# tipo) que `_extrair`/`exportar_csv`/`exportar_xlsx` já consomem.
#
# Fase 29 — `data_inclusao_pca` entrou no registro
# único da TELA (`apps.pca.colunas`), então a exceção que a
# acrescentava só aqui (Fase) saiu por completo: o
# export volta a ser puramente `COLUNAS` derivada, sem tupla extra.
COLUNAS = tuple(
    (
        coluna.chave,
        _cabecalho_export(coluna),
        _EXCECOES_TIPO.get(coluna.chave, _MAPA_TIPO_TELA[coluna.tipo]),
    )
    for coluna in _COLUNAS_TELA
)

# Fase allowlist do EXPORT por chave, derivada de
# `COLUNAS`. É contra ESTE registro — não o da tela diretamente — que
# `apps.pca.views._colunas_selecionadas_do_request` valida `?colunas=`
# antes de decidir se cai no padrão/sessão.
COLUNAS_POR_CHAVE = {chave: (chave, cabecalho, tipo) for chave, cabecalho, tipo in COLUNAS}

# Larguras (unidades Excel) por chave, lidas do MESMO registro
# que já as define para a tela (`Coluna.largura_xlsx`).
_LARGURAS_XLSX = {coluna.chave: coluna.largura_xlsx for coluna in _COLUNAS_TELA}


def _largura_xlsx(chave):
    return _LARGURAS_XLSX.get(chave, 18)


def _colunas_resolvidas(colunas_selecionadas):
    """Resolve o subconjunto de `COLUNAS` a exportar (R3) — sem `colunas_selecionadas` (None/vazio), devolve `COLUNAS`
    inteiro (contrato histórico, válido para qualquer chamador direto que
    não passe nada). Com `colunas_selecionadas`, filtra as chaves válidas
    do allowlist fechado `COLUNAS` (T-mql-01) — cobre typos e chaves
    inexistentes —, dedup preservando a primeira ocorrência (Fase) e então monta a tupla na ORDEM CANÔNICA de
    `apps.pca.colunas.canonizar` (fechamento do gap "EDGE
    ordering") — núcleo padrão primeiro,
    opcionais na ordem do registro, a MESMA ordem que `colunas_selecionadas`
    (a função irmã de `apps.pca.colunas`) resolveria para a tela, garantindo
    paridade tabela/XLSX/CSV independentemente da ordem recebida no
    `?colunas=`. `valor_contratado`/`atrasado`/
    `publicacao_pendente` passaram a ter definição em `COLUNAS` e não
    caem mais neste descarte.

    Fase se TODAS as chaves recebidas forem
    inválidas/vazias/duplicadas-descartadas, o resultado filtrado nunca
    fica vazio — cai de volta em `COLUNAS` inteiro como ÚLTIMA rede de
    segurança desta função ("seleção inválida nunca produz
    tabela ou arquivo sem colunas"). Sem essa guarda, `exportar_xlsx`
    quebrava com `ValueError` em `get_column_letter(len(colunas))` para
    `?colunas=` vazio/desconhecido (reproduzido com `django.test.Client`
    contra `GET /exportar/xlsx?colunas=xyz-invalido`), e `exportar_csv`
    produzia um arquivo silenciosamente vazio (cabeçalho e linhas em
    branco) para o mesmo input. Na prática, o caminho pela VIEW
    (`apps.pca.views._colunas_selecionadas_do_request`) já garante uma
    lista não vazia antes de chegar aqui (cai no padrão/sessão da tela);
    esta guarda protege qualquer outro chamador direto da função."""
    if not colunas_selecionadas:
        return COLUNAS
    vistas = set()
    validas = []
    for chave in colunas_selecionadas:
        if chave in COLUNAS_POR_CHAVE and chave not in vistas:
            vistas.add(chave)
            validas.append(chave)
    if not validas:
        return COLUNAS
    return tuple(COLUNAS_POR_CHAVE[chave] for chave in canonizar(validas))


def _texto_seguro(valor):
    """Neutraliza formula injection: prefixa com apóstrofo todo
    texto cujo primeiro caractere não-espacial seja `=`, `+`, `-` ou `@`
    (recomendação OWASP para CSV/XLSX export). O conteúdo permanece
    legível na célula; só a interpretação como fórmula é bloqueada.

    QA 30/09/2026 (dados M9) — defesa em profundidade: um caractere de
    controle (`\\x0b`, `\\x0c` etc.) que chegue ao banco por qualquer outra
    via (dado legado, robô SEI) é removido aqui antes de gravar a célula —
    o openpyxl levanta `IllegalCharacterError` sem esta limpeza."""
    if isinstance(valor, str):
        valor = ILLEGAL_CHARACTERS_RE.sub("", valor)
        if valor.lstrip()[:1] in PREFIXOS_FORMULA:
            return "'" + valor
        return valor
    return valor


def _extrair(processo, chave):
    """Devolve o valor PYTHON nativo da coluna para o processo — Decimal,
    int, date ou str — com `None` para toda ausência. As derivadas
    (n_reunioes, n_compromissos, prazo_inicial, prazo_efetivo, dias_atraso,
    n_prorrogacoes, qualificador_prazo, situacao_atual) já chegam anotadas
    por para_listagem(); o acesso aqui é por atributo, sem nenhuma consulta
    adicional por linha."""
    if chave == "tipo":
        valor = processo.tipo.nome
    elif chave == "categoria":
        valor = processo.categoria.nome
    elif chave == "unidade_organizacional":
        valor = processo.unidade_organizacional.nome
    elif chave == "grau_prioridade":
        valor = processo.grau_prioridade.nome if processo.grau_prioridade else None
    elif chave == "classificacao":
        valor = processo.classificacao.nome if processo.classificacao else None
    elif chave == "modalidade":
        valor = processo.modalidade.nome if processo.modalidade else None
    elif chave == "instrumento_contratual":
        valor = (
            processo.instrumento_contratual.nome
            if processo.instrumento_contratual
            else None
        )
    elif chave == "estado":
        valor = processo.get_estado_display()
    elif chave == "situacao":
        # Fase 17 emendada (29/08/2026, gap 1) — exporta `situacao_efetiva` (a mesma
        # correção-na-leitura que a tela usa via `para_listagem()`), não
        # mais a coluna crua `get_situacao_display()`: o arquivo baixado
        # precisa mostrar a mesma Situação que a tabela já exibe, nunca
        # "No prazo" para uma linha que a tela já mostra como "Atrasado".
        # `Situacao(...)` só aceita os 4 valores fechados do enum —
        # `ValueError` explícito se a annotation devolver algo fora do
        # vocabulário, nunca string arbitrária no arquivo.
        #
        # Fase 28 — um processo CANCELADO com
        # `situacao_efetiva` residual ("concluido", por exemplo) saía do
        # arquivo como "Concluído" enquanto a tela (`_tabela_situacao.
        # html`) já mostra "Cancelado" corretamente: `estado` precisa ser
        # checado ANTES de `situacao_efetiva`, mesma regra da tela.
        if processo.estado == Estado.CANCELADO.value:
            valor = "Cancelado"
        else:
            valor = Situacao(processo.situacao_efetiva).label
    elif chave == "mes_previsto":
        # Nome do mês por extenso no arquivo, mesma
        # fonte única `NOMES_MES` das telas; `.get(None)` já devolve
        # `None` sem checagem extra, preservando a célula vazia.
        valor = NOMES_MES.get(processo.mes_previsto)
    elif chave == "numeros_sei":
        # Achatado numa célula, separado por UM espaço, na ordem de
        # origem (prefetch já avaliado na view; zero queries aqui).
        valor = " ".join(sei.numero_sei for sei in processo.numeros_sei.all()) or "Sem processo SEI"
    elif chave in ("atrasado", "publicacao_pendente"):
        # Anotações booleanas de para_listagem() com
        # `default=Value(False)` no Case, nunca None: a saída é sempre
        # "Sim" ou "Não" em pt-BR, nunca célula vazia (continua
        # valendo para ausência real, como valor_contratado nulo).
        valor = "Sim" if getattr(processo, chave) else "Não"
    else:
        valor = getattr(processo, chave)
    # TextFields em branco (justificativa="") também são ausência:
    # string vazia no XLSX é uma célula de TEXTO, não um vazio real.
    if valor == "":
        return None
    return valor


# Fase 28 — resultado vazio ainda ganha uma
# indicação explícita na primeira célula de dados, nunca só o cabeçalho
# sozinho (o usuário precisa distinguir "sem resultados" de "arquivo
# corrompido"); sem fórmula nenhuma associada a essa linha.
MENSAGEM_SEM_RESULTADOS = "Nenhum processo encontrado para os filtros aplicados."


def _nome_arquivo(extensao, exercicio):
    """Nome do arquivo pelo EXERCÍCIO EFETIVO, nunca "2026"
    fixo; sem `exercicio` (chamada legada, nenhum consumidor vivo hoje),
    cai nos literais históricos `NOME_CSV`/`NOME_XLSX`."""
    if exercicio is not None:
        return f"pca-{exercicio.ano}-processos.{extensao}"
    return NOME_CSV if extensao == "csv" else NOME_XLSX


def _titulo_aba(exercicio):
    """Título da aba pelo exercício efetivo, truncado a 31
    caracteres (limite do Excel para nomes de aba); fallback histórico
    sem `exercicio`."""
    if exercicio is not None:
        return f"Processos PCA {exercicio.ano}"[:31]
    return "Processos PCA 2026"


def exportar_csv(queryset, colunas_selecionadas=None, exercicio=None):
    """CSV `;` com BOM UTF-8, datas DD/MM/AAAA e decimal com vírgula —
    representação textual pensada para o Excel pt-BR abrir direto. Uma
    linha por processo, sem linha de total (o total é exclusivo do XLSX,
    onde é uma fórmula calculável). `colunas_selecionadas` (quick) restringe/reordena o subconjunto de `COLUNAS` exportado —
    veja `_colunas_resolvidas`. `exercicio` dá nome dinâmico ao
    arquivo pelo exercício efetivo."""
    colunas = _colunas_resolvidas(colunas_selecionadas)
    buffer = StringIO()
    # utf-8-sig: o BOM é o que faz o Excel pt-BR escolher UTF-8 em vez de
    # Windows-1252 ao abrir o arquivo (Pitfall 22).
    buffer.write("\ufeff")
    escritor = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    escritor.writerow([cabecalho for _, cabecalho, _ in colunas])
    for processo in queryset:
        linha = []
        for chave, _, tipo in colunas:
            valor = _extrair(processo, chave)
            if valor is None:
                linha.append("")
            elif tipo == TIPO_DATA:
                linha.append(valor.strftime("%d/%m/%Y"))
            elif tipo == TIPO_DECIMAL:
                # Vírgula decimal SEM separador de milhar: "162642475,66" —
                # o Excel pt-BR interpreta como número ao separar por `;`.
                linha.append(f"{valor:.2f}".replace(".", ","))
            elif tipo == TIPO_INTEIRO:
                linha.append(str(valor))
            else:
                linha.append(_texto_seguro(str(valor)))
        escritor.writerow(linha)
    resposta = HttpResponse(buffer.getvalue(), content_type="text/csv; charset=utf-8")
    nome_arquivo = _nome_arquivo("csv", exercicio)
    resposta["Content-Disposition"] = f'attachment; filename="{nome_arquivo}"'
    return resposta


def exportar_xlsx(queryset, colunas_selecionadas=None, exercicio=None):
    """XLSX com tipos nativos (Decimal/int/date — nunca texto formatado no
    servidor), `number_format` monetário e de data, larguras de coluna,
quebra de linha em texto longo, autofiltro sobre a região
    da tabela, cabeçalho congelado e linha de total com `SUM()` real por
    coluna monetária selecionada (generalizado a valor previsto
    E contratado). `colunas_selecionadas` restringe/
    reordena o subconjunto de `COLUNAS` exportado — veja
    `_colunas_resolvidas`. `exercicio` dá nome/aba dinâmicos
    pelo exercício efetivo."""
    colunas = _colunas_resolvidas(colunas_selecionadas)
    planilha = Workbook()
    ws = planilha.active
    ws.title = _titulo_aba(exercicio)
    ws.append([cabecalho for _, cabecalho, _ in colunas])

    # Largura por coluna, ANTES do loop de linhas (independe da
    # quantidade de dados); lida do registro único `apps.pca.colunas`.
    for indice, (chave, _, _) in enumerate(colunas, start=1):
        ws.column_dimensions[get_column_letter(indice)].width = _largura_xlsx(chave)

    processos = list(queryset)
    for processo in processos:
        ws.append(
            [
                _texto_seguro(_extrair(processo, chave))
                for chave, _, _ in colunas
            ]
        )

    if not processos:
        # Resultado vazio: cabeçalho + indicação de ausência,
        # nunca só o cabeçalho sozinho e nunca linha de total.
        ws.append([MENSAGEM_SEM_RESULTADOS])

    ultima_linha_dados = 1 + len(processos)
    ultima_linha = ws.max_row  # 1 (cabeçalho) + N processos (ou +1 aviso)

    # Formatos nativos por coluna — aplicados célula a célula porque o
    # openpyxl só atribui formato de data padrão (yyyy-mm-dd) às células
    # date; o monetário nunca é atribuído automaticamente. Só sobre linhas
    # de dado real (nunca a linha de aviso de ausência).
    for indice, (_, _, tipo) in enumerate(colunas):
        letra = get_column_letter(indice + 1)
        if tipo in (TIPO_DECIMAL, TIPO_DATA):
            formato = FORMATO_MOEDA if tipo == TIPO_DECIMAL else FORMATO_DATA
            for linha in range(2, ultima_linha_dados + 1):
                ws[f"{letra}{linha}"].number_format = formato
        elif tipo == TIPO_TEXTO:
            # Quebra de linha em texto longo (Objeto/
            # Justificativa etc.), reaproveitando o padrão de import de
            # `exportacao_resumo_uo.py`.
            for linha in range(2, ultima_linha_dados + 1):
                ws[f"{letra}{linha}"].alignment = Alignment(
                    wrap_text=True, vertical="top"
                )

    # Autofiltro e congelamento cobrem a REGIÃO DA TABELA (cabeçalho +
    # dados/aviso) — a linha de total fica de fora para não ser
    # filtrada/ordenada.
    ultima_coluna = get_column_letter(len(colunas))
    ws.auto_filter.ref = f"A1:{ultima_coluna}{ultima_linha}"
    ws.freeze_panes = "A2"

    # Linha de total: uma fórmula SUM real POR coluna monetária
    # selecionada (generalizado de "só valor_estimado" para
    # qualquer coluna TIPO_DECIMAL, hoje valor_estimado E
    # valor_contratado), todas na MESMA linha, rótulo "Total" só na
    # primeira célula. O range cobre exatamente as linhas de dados e
    # acompanha o filtro. Export sem nenhuma linha de dado (`processos`
    # vazio) não ganha total nenhum — SUM sobre range invertido seria um
    # falso número plausível (Pitfall 9).
    colunas_decimais = [
        (indice, chave)
        for indice, (chave, _, tipo) in enumerate(colunas, start=1)
        if tipo == TIPO_DECIMAL
    ]
    if processos and colunas_decimais:
        linha_total = ultima_linha_dados + 1
        ws.cell(row=linha_total, column=1, value="Total")
        for indice, _chave in colunas_decimais:
            letra = get_column_letter(indice)
            celula_total = ws.cell(
                row=linha_total,
                column=indice,
                value=f"=SUM({letra}2:{letra}{ultima_linha_dados})",
            )
            celula_total.number_format = FORMATO_MOEDA

    buffer = BytesIO()
    planilha.save(buffer)
    resposta = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    nome_arquivo = _nome_arquivo("xlsx", exercicio)
    resposta["Content-Disposition"] = f'attachment; filename="{nome_arquivo}"'
    return resposta
