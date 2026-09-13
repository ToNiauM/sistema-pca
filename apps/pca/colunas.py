"""Registro único de colunas da tabela de Processos, compartilhado entre a
tela e a exportação XLSX."""

from dataclasses import dataclass

from apps.pca.rotulos import ROTULOS


@dataclass(frozen=True)
class Coluna:
    """Uma entrada do registro de colunas. `campo` é o caminho de atributo
    consumido pelos filtros `atributo`/`exibir`; `__getitem__`/`get()`
    permitem acesso estilo dict. `secao` agrupa o seletor "Colunas"."""

    chave: str
    rotulo: str
    campo: str
    tipo: str
    largura_xlsx: int
    secao: str
    obrigatoria: bool = False

    def __getitem__(self, chave):
        return getattr(self, chave)

    def get(self, chave, default=None):
        return getattr(self, chave, default)


# mesma ordem de views.SECOES_FORMULARIO_PROCESSO, redeclarada para evitar
# dependência circular
SECOES_COLUNAS = (
    "Planejamento",
    "Processo",
    "Execução contratual",
    "Publicação",
)

# larguras Excel: item_pca=10, descricao_objeto=60,
# unidade_organizacional/valores=22, toda data=16, situacao=24, demais=18
COLUNAS = (
    # --- Planejamento ------------------------------------------------
    Coluna(
        "item_pca", "Item", "item_pca", "numero", 10, secao="Planejamento",
        obrigatoria=True,
    ),
    Coluna(
        "descricao_objeto", "Objeto", "descricao_objeto", "texto", 60,
        secao="Planejamento", obrigatoria=True,
    ),
    Coluna(
        "justificativa", "Justificativa", "justificativa", "texto", 18,
        secao="Planejamento",
    ),
    Coluna(
        "unidade_organizacional", "Unidade", "unidade_organizacional.nome",
        "texto", 22, secao="Planejamento",
    ),
    Coluna(
        "classificacao", "Classificação", "classificacao.nome", "texto", 18,
        secao="Planejamento",
    ),
    Coluna("tipo", "Tipo", "tipo.nome", "texto", 18, secao="Planejamento"),
    Coluna(
        "categoria", "Categoria", "categoria.nome", "texto", 18,
        secao="Planejamento",
    ),
    Coluna(
        "grau_prioridade", "Prioridade", "grau_prioridade.nome", "texto", 18,
        secao="Planejamento",
    ),
    Coluna(
        "valor_estimado", "Valor previsto", "valor_estimado", "moeda", 22,
        secao="Planejamento",
    ),
    # tratada à parte no template (filtro nome_mes, não atributo/exibir)
    Coluna(
        "mes_previsto", "Mês previsto", "mes_previsto", "texto", 18,
        secao="Planejamento",
    ),
    Coluna(
        "data_inclusao_pca", "Data de inclusão no PCA", "data_inclusao_pca",
        "data", 16, secao="Planejamento",
    ),
    # substitui prazo_entrega no registro: a anotação COALESCE de
    # ProcessoQuerySet.para_listagem(), nunca o campo cru
    Coluna(
        "prazo_inicial", ROTULOS.get("prazo_inicial", "Prazo inicial"),
        "prazo_inicial", "data", 16, secao="Planejamento",
    ),
    Coluna(
        "prazo_efetivo", ROTULOS.get("prazo_efetivo", "Prazo atual"),
        "prazo_efetivo", "data", 16, secao="Planejamento",
    ),
    # --- Processo (campos próprios e derivados do histórico) ---------
    # composta — campo aqui é só referência, o template resolve via _tabela_situacao.html
    Coluna(
        "situacao", "Situação", "situacao_efetiva", "status", 24,
        secao="Processo",
    ),
    # composta — concatenação dos números SEI; campo aqui também é só referência
    Coluna(
        "numeros_sei", "Nº do processo SEI", "numeros_sei", "texto", 18,
        secao="Processo",
    ),
    Coluna(
        "situacao_sei", "Situação do SEI", "get_situacao_sei_display",
        "texto", 18, secao="Processo",
    ),
    Coluna("estado", "Estado", "get_estado_display", "texto", 18, secao="Processo"),
    Coluna(
        "n_reunioes", "Nº reuniões", "n_reunioes", "numero", 18,
        secao="Processo",
    ),
    Coluna(
        "n_compromissos", "Nº compromissos", "n_compromissos", "numero", 18,
        secao="Processo",
    ),
    Coluna(
        "dias_atraso", "Dias em atraso", "dias_atraso", "numero", 18,
        secao="Processo",
    ),
    Coluna(
        "n_prorrogacoes", "Prazos remarcados", "n_prorrogacoes", "numero", 18,
        secao="Processo",
    ),
    Coluna(
        "situacao_atual", "Situação última reunião", "situacao_atual",
        "texto", 18, secao="Processo",
    ),
    Coluna("atrasado", "Atraso", "atrasado", "booleano", 18, secao="Processo"),
    Coluna(
        "publicacao_pendente", "Publicação", "publicacao_pendente",
        "booleano", 18, secao="Processo",
    ),
    Coluna(
        "data_envio_gelic", "Envio ao Gelic", "data_envio_gelic", "data", 16,
        secao="Processo",
    ),
    Coluna(
        "data_recebimento_gelic", "Recebimento no Gelic",
        "data_recebimento_gelic", "data", 16, secao="Processo",
    ),
    # --- Execução contratual ------------------------------------------
    Coluna(
        "modalidade", "Modalidade", "modalidade.nome", "texto", 18,
        secao="Execução contratual",
    ),
    Coluna(
        "numero_contratacao", "Nº da contratação", "numero_contratacao",
        "texto", 18, secao="Execução contratual",
    ),
    Coluna(
        "numero_arp", "Nº da ARP", "numero_arp", "texto", 18,
        secao="Execução contratual",
    ),
    Coluna(
        "instrumento_contratual", "Instrumento contratual",
        "instrumento_contratual.nome", "texto", 18,
        secao="Execução contratual",
    ),
    Coluna(
        "numero_instrumento_contratual", "Nº do instrumento contratual",
        "numero_instrumento_contratual", "texto", 18,
        secao="Execução contratual",
    ),
    Coluna(
        "fornecedor_cnpj", "CNPJ", "fornecedor_cnpj", "texto", 18,
        secao="Execução contratual",
    ),
    Coluna(
        "fornecedor_razao_social", "Razão social", "fornecedor_razao_social",
        "texto", 18, secao="Execução contratual",
    ),
    Coluna(
        "valor_contratado", "Valor contratado", "valor_contratado", "moeda",
        22, secao="Execução contratual",
    ),
    Coluna(
        "data_assinatura_contrato", "Data assinatura do contrato",
        "data_assinatura_contrato", "data", 16, secao="Execução contratual",
    ),
    Coluna(
        "vigencia_inicio", "Vigência início", "vigencia_inicio", "data", 16,
        secao="Execução contratual",
    ),
    Coluna(
        "vigencia_fim", "Vigência fim", "vigencia_fim", "data", 16,
        secao="Execução contratual",
    ),
    # --- Publicação -----------------------------------------------------
    Coluna(
        "data_lancamento_spw", "Data lançamento SPW", "data_lancamento_spw",
        "data", 16, secao="Publicação",
    ),
    Coluna(
        "data_lancamento_wordpress", "Data lançamento WordPress",
        "data_lancamento_wordpress", "data", 16, secao="Publicação",
    ),
    Coluna(
        "data_lancamento_dados_abertos", "Data lançamento Dados Abertos",
        "data_lancamento_dados_abertos", "data", 16, secao="Publicação",
    ),
)

COLUNAS_POR_CHAVE = {coluna.chave: coluna for coluna in COLUNAS}

# padrão de colunas exibidas quando o usuário não escolheu nenhuma
COLUNAS_PADRAO = (
    "item_pca",
    "descricao_objeto",
    "valor_estimado",
    "prazo_efetivo",
    "situacao",
)

# Item e Objeto nunca são desmarcáveis no seletor "Colunas"
COLUNAS_OBRIGATORIAS = ("item_pca", "descricao_objeto")

# chave de sessão da preferência de colunas da tela, por usuário autenticado
CHAVE_SESSAO_COLUNAS = "pca_colunas_tabela"


def colunas_por_secao():
    """Agrupa COLUNAS pela secao de cada entrada, na ordem de SECOES_COLUNAS.
    Devolve uma tupla de (nome_secao, tupla_de_colunas)."""
    grupos = {secao: [] for secao in SECOES_COLUNAS}
    for coluna in COLUNAS:
        grupos[coluna.secao].append(coluna)
    return tuple((secao, tuple(colunas)) for secao, colunas in grupos.items())


def canonizar(chaves):
    """Recebe chaves já válidas e devolve a lista na ordem canônica: núcleo
    padrão primeiro, depois as demais na ordem do registro COLUNAS."""
    selecionadas = set(chaves)
    nucleo = [chave for chave in COLUNAS_PADRAO if chave in selecionadas]
    opcionais = [
        coluna.chave
        for coluna in COLUNAS
        if coluna.chave in selecionadas and coluna.chave not in COLUNAS_PADRAO
    ]
    return nucleo + opcionais


def _normalizar(chaves):
    """Remove duplicatas e descarta chaves fora do registro COLUNAS. Devolve
    lista vazia se nenhuma sobreviver; reinjeta COLUNAS_OBRIGATORIAS ausentes
    e devolve na ordem canônica de canonizar()."""
    chaves_validas = COLUNAS_POR_CHAVE.keys()
    resultado = []
    for chave in chaves:
        chave = str(chave).strip()
        if chave in chaves_validas and chave not in resultado:
            resultado.append(chave)
    if not resultado:
        return []
    for obrigatoria in COLUNAS_OBRIGATORIAS:
        if obrigatoria not in resultado:
            resultado.append(obrigatoria)
    return canonizar(resultado)


def colunas_selecionadas(request):
    """Resolve as colunas a exibir: `?colunas=` da URL, depois sessão,
    depois padrão. Só regrava a sessão quando o resultado difere do que já
    estava salvo, para não escrever em toda requisição GET."""
    if "colunas" in request.GET:
        resultado = _normalizar(request.GET.getlist("colunas")) or list(
            COLUNAS_PADRAO
        )
        if request.session.get(CHAVE_SESSAO_COLUNAS) != resultado:
            request.session[CHAVE_SESSAO_COLUNAS] = resultado
        return resultado
    resultado = _normalizar(request.session.get(CHAVE_SESSAO_COLUNAS) or [])
    return resultado or list(COLUNAS_PADRAO)
