"""Registro único de colunas da tabela de Processos (Fase 28) — fonte compartilhada entre a TELA (`/tabela`, este plano) e
a EXPORTAÇÃO XLSX (`apps/pca/exportacao.py`,
sequencial).

Antes deste módulo existiam DOIS registros que já divergiam entre si: o
antigo mapa `(chave, rótulo)` de 22 pares que vivia em `apps/pca/views.py`
(tela) e `apps/pca/exportacao.py::COLUNAS` (26 triplas, export) — e
`apps/pca/forms_listagem.py` importava o antigo conjunto de chaves-padrão
de `views.py`, uma dependência circular só evitada por import local dentro
de `tabela_view`. Este módulo reúne as chaves que já existiam em QUALQUER
um dos dois registros antigos, sem duplicar nome nem perder nenhuma, e
`views.py`/`forms_listagem.py` passam a lê-lo, nunca mais duplicá-lo
(`exportacao.py` só na Fase 28-04, fora do escopo deste plano).

`COLUNAS_PADRAO` É O NOVO PADRÃO — diferente do conjunto
anterior (`item_pca, descricao_objeto, unidade_organizacional,
valor_estimado, situacao`): `unidade_organizacional` sai do núcleo (vira
opcional) e `prazo_efetivo` entra (nunca fez parte do padrão antes).

Fase 29 — cada coluna ganha `secao`
(mesmas quatro seções de `views.SECOES_FORMULARIO_PROCESSO`, redeclaradas
localmente em `SECOES_COLUNAS` para não abrir uma dependência circular com
`views.py`), o seletor "Colunas" agrupa por seção
(`colunas_por_secao()`), e as 14 chaves de Execução contratual/Publicação
mais `data_inclusao_pca` entram no registro. `prazo_vigente`,
`prazo_entrega` e `data_prevista_conclusao` SAEM do registro;
`prazo_inicial` (anotação `COALESCE(prazo_entrega, primeira promessa)` de
`ProcessoQuerySet.para_listagem()`) entra no lugar de
`prazo_entrega`. Rótulos de prazo vêm de `apps.pca.rotulos.ROTULOS`
("vigente" sai do vocabulário de prazo).
"""

from dataclasses import dataclass
from urllib.parse import urlparse

from apps.pca.rotulos import ROTULOS


@dataclass(frozen=True)
class Coluna:
    """Uma entrada do registro. `campo` é o caminho de atributo consumido
    pelos filtros `atributo`/`exibir` de `core/templatetags/dsgov.py`
    (mesmo contrato de `pendencias.colunas` em `core/templates/core/
    inicio.html`) — por isso esta classe implementa `__getitem__`/`get()`:
    `exibir()` acessa a coluna via `coluna["campo"]`/`coluna.get("tipo")`,
    estilo dict, não só por atributo.

    `situacao` (composta: Cancelado OU `situacao_efetiva`, mesma regra de
    `_tabela_situacao.html`) e `numeros_sei` (concatenação dos números SEI,
    mesma regra de `exportacao._extrair`) não cabem neste contrato
    genérico — `campo` documenta a fonte mais próxima só para referência;
    o template trata as duas à parte (`{% if col.chave == "situacao" %}` /
    `{% elif col.chave == "mes_previsto" %}`), nunca via `exibir()`.

    `secao` é uma das quatro chaves de `SECOES_COLUNAS` — usada só para
    agrupar o seletor "Colunas" em fieldsets (Fase 29); não
    afeta `exibir()`/export nem a ordem de exibição na tabela (essa
    continua vindo de `_normalizar`/`colunas_selecionadas`).
    """

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


# Fase 29 — mesma ordem de `views.SECOES_FORMULARIO_PROCESSO`,
# redeclarada aqui (não importada) para não recriar a dependência circular
# que motivou a extração original deste módulo (ver docstring acima).
SECOES_COLUNAS = (
    "Planejamento",
    "Processo",
    "Execução contratual",
    "Publicação",
)

# (ordem inicial) + as demais chaves que já existiam no antigo
# mapa da tela ou em exportacao.COLUNAS, reunidas num único vocabulário,
# mais as 14 novas (Execução contratual/Publicação/
# data_inclusao_pca) e `prazo_inicial` (substitui
# `prazo_entrega`). Larguras Excel: item_pca=10,
# descricao_objeto=60, unidade_organizacional/valores=22, toda data=16,
# situacao=24, demais=18.
#
# Ordem de exibição dentro de cada seção: Item/Objeto
# primeiro (obrigatórias), demais campos de Planejamento na ordem de
# `views.SECOES_FORMULARIO_PROCESSO` (prazo_inicial/prazo_efetivo/
# data_inclusao_pca após Mês previsto); Execução contratual e Publicação também na ordem daquela
# tupla; Processo recebe os campos próprios e derivados que não pertencem
# a nenhuma das outras três seções, na ordem histórica do registro.
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
    # Tratada à parte no template (filtro `nome_mes`, não `atributo`/`exibir`).
    Coluna(
        "mes_previsto", "Mês previsto", "mes_previsto", "texto", 18,
        secao="Planejamento",
    ),
    Coluna(
        "data_inclusao_pca", "Data de inclusão no PCA", "data_inclusao_pca",
        "data", 16, secao="Planejamento",
    ),
    # Substitui `prazo_entrega` no registro: a anotação
    # COALESCE de `ProcessoQuerySet.para_listagem()`, nunca o campo cru.
    Coluna(
        "prazo_inicial", ROTULOS.get("prazo_inicial", "Prazo inicial"),
        "prazo_inicial", "data", 16, secao="Planejamento",
    ),
    Coluna(
        "prazo_efetivo", ROTULOS.get("prazo_efetivo", "Prazo atual"),
        "prazo_efetivo", "data", 16, secao="Planejamento",
    ),
    # --- Processo (campos próprios e derivados do histórico) ---------
    # Composta — ver docstring de Coluna acima; `campo` aqui é só
    # referência (o template resolve via `_tabela_situacao.html`).
    Coluna(
        "situacao", "Situação", "situacao_efetiva", "status", 24,
        secao="Processo",
    ),
    # Composta — concatenação dos números SEI (consome via
    # `exportacao._extrair`); `campo` aqui também é só referência.
    Coluna(
        "numeros_sei", "Nº do processo SEI", "numeros_sei", "texto", 18,
        secao="Processo",
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
    # Visível a todo autenticado, mesma classe de
    # `numeros_sei` (não entra em `COLUNAS_PADRAO` nem em
    # `CHAVES_RESTRITAS_ACOMPANHAMENTO`).
    Coluna(
        "unidade_sei_atual", "Unidade SEI", "unidade_sei_atual", "texto", 18,
        secao="Processo",
    ),
    # --- Execução contratual --------------------------------
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
    # --- Publicação -----------------------------------------
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

# Padrão NOVO (substitui o antigo conjunto de chaves-padrão da
# Fase 26): `unidade_organizacional` sai, `prazo_efetivo` entra.
COLUNAS_PADRAO = (
    "item_pca",
    "descricao_objeto",
    "valor_estimado",
    "prazo_efetivo",
    "situacao",
)

# Item e Objeto nunca são desmarcáveis no seletor "Colunas".
COLUNAS_OBRIGATORIAS = ("item_pca", "descricao_objeto")

# Chave de sessão da preferência de colunas da tela (por usuário
# autenticado, nunca por processo/exercício).
CHAVE_SESSAO_COLUNAS = "pca_colunas_tabela"

# Acompanhamentos e prazos passam a ser visíveis só para
# quem tem `pca.view_acompanhamento` (grupo `editor`); `situacao`/
# `atrasado`/`estado`/`numeros_sei` continuam sempre
# visíveis (decisão explícita: "situação do processo" não é acompanhamento).
CHAVES_RESTRITAS_ACOMPANHAMENTO = frozenset({
    "prazo_inicial",
    "prazo_efetivo",
    "n_reunioes",
    "n_compromissos",
    "dias_atraso",
    "n_prorrogacoes",
    "situacao_atual",
})


def _sem_permissao_acompanhamento(request) -> bool:
    """`request=None` (chamador antigo de `colunas_por_secao()`, sem
    argumento) ou sem `.user` (duplo de teste mínimo de
    `test_colunas_tabela.py`, que só acessa `GET`/`session`) nunca restringe
    — só um `request` com `.user` autenticado de fato decide o gate."""
    if request is None:
        return False
    user = getattr(request, "user", None)
    if user is None:
        return False
    return not user.has_perm("pca.view_acompanhamento")


def _filtrar_restritas(chaves, request):
    if not _sem_permissao_acompanhamento(request):
        return chaves
    return [chave for chave in chaves if chave not in CHAVES_RESTRITAS_ACOMPANHAMENTO]


def _mesma_origem(request) -> bool:
    """QA de segurança 30/09/2026 (achado B4) — decide se a REQUISIÇÃO
    atual declara vir do próprio site, para `colunas_selecionadas()`
    condicionar a GRAVAÇÃO do `?colunas=` explícito (nunca a leitura/
    resposta atual, que continua imediata).

    Ordem de sinais: `Sec-Fetch-Site` (enviado pelo navegador em toda
    navegação de nível superior moderna) decide sozinho quando presente —
    só `"same-origin"`/`"none"` contam como mesma origem. Sem o cabeçalho
    (navegador antigo), cai para `Referer` comparado ao host da própria
    requisição. Na ausência de QUALQUER sinal (sem `.headers`, sem `.META`,
    sem Referer — o caso dos `_Request` sintéticos deste módulo/dos testes
    de `test_preferencia_colunas.py`, que chamam `colunas_selecionadas`
    sem passar por HTTP de verdade), devolve `True`: preserva o
    comportamento histórico para quem chama diretamente — só uma
    requisição HTTP que DECLARA ativamente vir de outra origem é
    recusada."""
    headers = getattr(request, "headers", None)
    if headers:
        sec_fetch_site = headers.get("Sec-Fetch-Site")
        if sec_fetch_site:
            return sec_fetch_site in ("same-origin", "none")
    meta = getattr(request, "META", None)
    if meta:
        referer = meta.get("HTTP_REFERER")
        if referer:
            get_host = getattr(request, "get_host", None)
            host_atual = get_host() if callable(get_host) else None
            return urlparse(referer).netloc == host_atual
    return True


def colunas_por_secao(request=None):
    """Agrupa `COLUNAS` pela `secao` de cada entrada, na ordem canônica de
    `SECOES_COLUNAS` — cada grupo preserva internamente a MESMA ordem de
    `COLUNAS` (a ordem de exibição/resolução nunca muda por causa
    do agrupamento). Devolve uma tupla de `(nome_secao, tupla_de_colunas)`,
    pronta para `{% for secao, colunas in colunas_por_secao %}` no
    template do seletor (`_tabela_resultado.html`).

    `request` (default `None` preserva o comportamento
    para quem ainda chama sem argumento): sem `pca.view_acompanhamento`,
    as colunas de `CHAVES_RESTRITAS_ACOMPANHAMENTO` somem do seletor."""
    grupos = {secao: [] for secao in SECOES_COLUNAS}
    for coluna in COLUNAS:
        if coluna.chave in CHAVES_RESTRITAS_ACOMPANHAMENTO and _sem_permissao_acompanhamento(request):
            continue
        grupos[coluna.secao].append(coluna)
    return tuple((secao, tuple(colunas)) for secao, colunas in grupos.items())


def canonizar(chaves):
    """(fechamento do gap "EDGE ordering") — recebe um iterável de chaves JÁ válidas
    (presentes em `COLUNAS_POR_CHAVE`, tipicamente a saída de
    `_normalizar`) e devolve a lista na ORDEM CANÔNICA, independentemente
    da ordem de chegada: primeiro o núcleo padrão presente, na ordem de
    `COLUNAS_PADRAO`, depois as demais chaves selecionadas na
    ordem do registro `COLUNAS` (já organizado pelas quatro seções
    canônicas) — basta iterar `COLUNAS` porque ele já está na
    ordem certa. Dedup automático (usa um `set` só para teste de
    pertencimento; a ORDEM de saída nunca vem do input). Chave fora do
    registro é ignorada silenciosamente — quem chama `canonizar` já
    filtrou inválidas (`_normalizar`/`exportacao._colunas_resolvidas`)."""
    selecionadas = set(chaves)
    nucleo = [chave for chave in COLUNAS_PADRAO if chave in selecionadas]
    opcionais = [
        coluna.chave
        for coluna in COLUNAS
        if coluna.chave in selecionadas and coluna.chave not in COLUNAS_PADRAO
    ]
    return nucleo + opcionais


def _normalizar(chaves):
    """Remove duplicatas (preservando a primeira ocorrência) e descarta
    toda chave fora do registro fechado `COLUNAS` (01) — inclusive
    toda chave extinta (`prazo_vigente`, `prazo_entrega`,
    `data_prevista_conclusao`): uma preferência de sessão antiga com
    qualquer uma delas é saneada automaticamente, porque `chaves_validas`
    é lido do registro ATUAL. Devolve lista VAZIA se nenhuma chave
    sobreviver — a decisão de cair no padrão fica em `colunas_selecionadas`,
    não aqui, porque só ali sabemos se o vazio veio do GET (cai no padrão)
    ou de uma sessão já normalizada (também cai no padrão, mesma regra).
    Reinjeta `COLUNAS_OBRIGATORIAS` ausentes ao final da lista, exceto
    quando o resultado já está vazio — pede a garantia de
    presença, não uma posição específica. Por fim, `canonizar()` reordena
    o resultado (núcleo `COLUNAS_PADRAO` primeiro, depois opcionais na
    ordem do registro) ANTES de devolver — os hidden inputs do formulário
    (do plano) já enviam a ordem canônica na prática, mas
    deixaram de ser a ÚNICA garantia (fechamento do gap de
    Sessão poluída, link antigo ou URL montada à
    mão também produzem a ordem canônica)."""
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


def _usuario_autenticado(request):
    usuario = getattr(request, "user", None)
    return usuario if getattr(usuario, "is_authenticated", False) else None


def _ler_da_conta(request):
    """Colunas gravadas na conta ou `None` sem preferência
    — a conta vence a sessão: é o que acompanha o usuário entre logins e
    navegadores."""
    usuario = _usuario_autenticado(request)
    if usuario is None:
        return None
    from apps.pca.models import PreferenciaColunas

    return (
        PreferenciaColunas.objects.filter(usuario=usuario)
        .values_list("colunas", flat=True)
        .first()
    )


def _gravar_na_conta(request, resultado):
    """Seleção nova grava na conta; a seleção igual ao padrão ("Restaurar
    padrões") APAGA a preferência, para o usuário voltar a seguir o padrão
    — inclusive quando ele mudar no futuro."""
    usuario = _usuario_autenticado(request)
    if usuario is None:
        return
    from apps.pca.models import PreferenciaColunas

    if resultado == canonizar(list(COLUNAS_PADRAO)):
        PreferenciaColunas.objects.filter(usuario=usuario).delete()
    else:
        PreferenciaColunas.objects.update_or_create(
            usuario=usuario, defaults={"colunas": resultado}
        )


def colunas_selecionadas(request):
    """Resolve a lista de chaves de coluna a exibir na tela, na ordem de
    exibição: (1) `?colunas=` explícito na URL (mesmo que
    inválido) tem precedência PARA A RESPOSTA atual e grava na sessão e na
    conta; (2) na ausência, preferência da CONTA do usuário
    (sobrevive a logout/outro navegador), e só sem ela a da sessão; (3) na ausência de ambos — ou se os dois
    resultarem vazios após a normalização —, o padrão da fase
    (`COLUNAS_PADRAO`). NUNCA devolve lista vazia.

    A gravação em sessão do `?colunas=` explícito só
    acontece quando o resultado REALMENTE difere da preferência já
    salva. Sem essa guarda, toda navegação HTMX da tela Processos (filtro,
    ordenação, paginação) reenvia `colunas=` no querystring via
    `hx-include="#form-colunas"` (bidirecional com o form de filtros — ver
    `_tabela_resultado.html`/`tabela.html`) e regravava a sessão a cada
    GET, inclusive quando a seleção não mudou — efeito colateral num
    método HTTP que deveria ser seguro/idempotente (qualquer prefetch de
    link, crawler autenticado ou extensão de navegador que apenas SIGA um
    link com `?colunas=...` já disparava a escrita). "Só em requisição
    não-HTMX" NÃO serve aqui: o próprio form `#form-colunas` (clique do
    usuário no seletor "Colunas") submete via HTMX (`hx-get`), então essa
    alternativa suprimiria a gravação do caso de uso real que a
    funcionalidade existe para servir."""
    if "colunas" in request.GET:
        resultado = _normalizar(request.GET.getlist("colunas")) or list(
            COLUNAS_PADRAO
        )
        # QA de segurança 30/09/2026 (achado B4) — a GRAVAÇÃO (sessão +
        # conta) só acontece em requisição same-origin; o `return` abaixo
        # continua devolvendo `resultado` para a resposta ATUAL de
        # qualquer jeito (a "última escolha vale para esta resposta" não
        # muda, só o efeito colateral de escrita fica condicionado).
        if request.session.get(CHAVE_SESSAO_COLUNAS) != resultado and _mesma_origem(
            request
        ):
            request.session[CHAVE_SESSAO_COLUNAS] = resultado
            _gravar_na_conta(request, resultado)
        return _filtrar_restritas(resultado, request) or _filtrar_restritas(
            list(COLUNAS_PADRAO), request
        )
    da_conta = _ler_da_conta(request)
    if da_conta is not None and request.session.get(CHAVE_SESSAO_COLUNAS) != da_conta:
        request.session[CHAVE_SESSAO_COLUNAS] = da_conta
    elif da_conta is None and request.session.get(CHAVE_SESSAO_COLUNAS):
        # Escolha feita antes da preferência na conta existir: sobe uma vez
        # para a conta (a partir daí `da_conta` deixa de ser `None`).
        da_sessao = _normalizar(request.session[CHAVE_SESSAO_COLUNAS])
        if da_sessao:
            _gravar_na_conta(request, da_sessao)
    resultado = _normalizar(
        (da_conta if da_conta is not None else request.session.get(CHAVE_SESSAO_COLUNAS)) or []
    )
    resultado = resultado or list(COLUNAS_PADRAO)
    return _filtrar_restritas(resultado, request) or _filtrar_restritas(
        list(COLUNAS_PADRAO), request
    )
