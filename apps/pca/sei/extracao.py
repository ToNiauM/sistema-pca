"""Parsing puro do robô SEI (Fase 32, parte
testável).

Módulo puro: importa `apps.pca.sei.extenso` mas NUNCA `playwright`,
`django.db` nem faz I/O de rede/disco — só recebe strings já buscadas pelo
coletor (`apps/pca/sei/coletor.py`) e devolve dados extraídos. É a fronteira
deliberada entre código testável sem Playwright instalado (roda no container
`web`) e código que fala com o navegador (só no container `robo`).

Cinco exports da Fase 32:

- `tipo_documento(rotulo)`: casa o rótulo do documento na árvore contra
  `RE_CONTRATUAL` (reaproveitada literalmente do spike) e devolve o tipo
  canônico do instrumento, ou `None` quando não é instrumento de contratação
  (inclusive "termo de rescisão", que não entra na disputa de valor).
- `extrair_assinaturas(texto_html)`: assinaturas classificadas por papel
  (`cfc`/`externo`), mesma lógica de `ler_documento` do spike (linhas
  506-519), reaproveitando `RE_ASSINATURA`.
- `extrair_numero_no_corpo(texto_html)`: nº do instrumento citado no corpo
  do documento, via `RE_NUMERO_CORPO`.
- `extrair_valor_documento(texto_html)`: cláusula de preço (§4.3 da spec) —
  frase-âncora "valor total"/"valor global"/"montante" seguida de `R$
  <cifra>` e o extenso entre parênteses; usa `apps.pca.sei.extenso.
  valores_conferem` para `confere`.
- `deve_bloquear_recurso(resource_type)`: bloqueio de imagens/fontes/ícones
  do SEI no navegador (§8.1 ponto 3, medida obrigatória de memória).

Mais quatro exports da Fase 33 (execução contratual
completa, spec `2026-09-18-robo-sei-execucao-contratual-design.md` §3.1):

- `extrair_contratado(texto)`: razão social + CNPJ do contratado (nunca do
  CFC) lidos do preâmbulo do instrumento.
- `extrair_procedencia(texto)`: modalidade + nº da contratação citados no
  preâmbulo, ou no campo estruturado da Ordem de Fornecimento (Fase 34),
  com a modalidade mapeada para o catálogo do PCA só quando reconhecida.
- `extrair_vigencia(texto, data_assinatura)`: início/fim da vigência, pelas
  5 formas da cláusula de prazo (por N meses/anos desde a assinatura, por
  datas explícitas, por N meses/anos sem a âncora "contados... da
  assinatura", por datas explícitas com o conector "a", ou por "a partir da
  assinatura até" uma data explícita — as duas últimas, Fase 34).
- `extrair_prorrogacao(texto)`: início/fim da nova vigência citada num termo
  aditivo de prorrogação.

Mais afinações da Fase 34 (sondagem incremental,
spec `2026-09-18-robo-sei-varredura-incremental-design.md` §3.4, achados
transcritos na spec da Fase 33 §2 "Padrões novos"): terminadores/sanidade
de razão social ampliados (`RE_RAZAO_PREAMBULO`, `_razao_valida`, caso
CIEE), campo estruturado de modalidade das Ordens de Fornecimento
(`RE_PROCEDENCIA_CAMPO`) e as duas formas novas de `extrair_vigencia`
acima — nenhuma mudança de comportamento nas formas já testadas na Fase 33.

E uma constante:

- `PROCESSOS_POR_LOTE = 25`: reciclagem do contexto do navegador a cada N
  processos (§8.1 ponto 2, medida obrigatória de memória).
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta

from apps.pca.sei.extenso import inteiro_por_extenso, valores_conferem

# Reaproveitadas literalmente de notas internas do projeto
# (linhas 40-53) — já provadas pelo spike, não reinventar.
RE_CONTRATUAL = re.compile(
    r"^(contrato(?!\s+social)|termo aditivo|termo de apostilamento|apostilamento|ordem de fornecimento|"
    r"ata de registro de pre[cç]os|termo de contrato|termo de rescis[aã]o)\b", re.I)
RE_ASSINATURA = re.compile(
    r"Documento assinado eletronicamente por\s+(?P<nome>.+?),\s+(?P<cargo>[^,]+?),\s+em\s+"
    r"(?P<data>\d{2}/\d{2}/\d{4}),\s+às\s+(?P<hora>\d{2}:\d{2})", re.S)
RE_NUMERO_CORPO = re.compile(
    r"\b(?:CONTRATO|TERMO ADITIVO|ORDEM DE FORNECIMENTO|ATA DE REGISTRO DE PRE[CÇ]OS)\s*N[ºo°.]*\s*(\d{1,4}/\d{4})", re.I)

# Frase-âncora da cláusula de preço (§4.3 ponto 3 da spec): "valor total",
# "valor global" ou "montante", seguida de "R$ <cifra>" e um trecho entre
# parênteses (o extenso) logo após — tolera pontuação interna, captura até o
# próximo "." ou ")" que feche o parêntese. "valor mensal"/"valor anual"
# (Fase 35) acrescentados como âncoras adicionais — periodicidade
# derivada do texto casado por `_periodicidade_de` (mesma função do módulo
# de apostilamento), nunca de um grupo nomeado fixo.
RE_VALOR_DOCUMENTO = re.compile(
    r"(?:valor\s+total|valor\s+global|valor\s+mensal|valor\s+anual|montante)\b.{0,80}?"
    r"R\$\s*(?P<cifra>\d{1,3}(?:\.\d{3})*,\d{2})\s*"
    r"\((?P<extenso>[^)]+)\)",
    re.I | re.S,
)

# Parcelas — "em N parcelas", buscada independentemente da âncora
# principal, em qualquer lugar do texto do documento.
RE_PARCELAS_DOCUMENTO = re.compile(r"\bem\s+(?P<n>\d+)\s*parcelas\b", re.I)

# Valores por item (decisão do usuário, 20/10/2026 — item 18, Contrato nº
# 39/2026: "5.1. Para o ITEM 01, o valor anual ... perfazendo o valor total
# ... 5.2. Para o ITEM 02, o valor total ... 5.3. Para o ITEM 03, ..."): o
# rótulo ITEM/LOTE/GRUPO NN que antecede a frase-âncora de valor DENTRO DA
# MESMA FRASE (recortada no último "." ou ";" seguido de espaço, até
# `_JANELA_ROTULO_ITEM` caracteres para trás). O lookahead negativo recusa
# número de seção ("item 5.1 do Termo de Referência") — só item da
# contratação vira rótulo.
RE_ROTULO_ITEM_VALOR = re.compile(
    r"\b(?P<tipo>item|lote|grupo)\s+(?:n[ºo°.]*\s*)?(?P<n>\d{1,3})(?![.,]?\d)", re.I
)
RE_FIM_DE_FRASE = re.compile(r"[.;]\s+")
_JANELA_ROTULO_ITEM = 300

PROCESSOS_POR_LOTE = 25

# ------------------------------------------------------ corpo/hash (Fase 39) ---
# /A10 (spec 2026-09-19-assistente-ia-design.md §4) — o texto do
# corpo do documento, sem o bloco de assinaturas eletrônicas nem o
# cabeçalho institucional, é o que entra no índice semântico do
# Assistente (`apps.assistente.fontes.extrair_sei`). `VERSAO_EXTRACAO_
# DOCUMENTO` marca a versão do algoritmo de recorte — o cache antigo (sem
# `texto_corpo`) não tem essa chave, e `sei_coletar --reprocessar-
# documentos` relê quando `versao_extracao != VERSAO_EXTRACAO_DOCUMENTO`.
#
# 2 -> 3 — documentos externos "Contrato..." antes
# marcados `conteudo="externo_nao_baixado"` passam a ser baixados e lidos
# como PDF (`apps.pca.sei.pdf.processar`); um cache gravado antes desta
# quick (inclusive os "externo_nao_baixado") só ganha o caminho novo após
# um `--reprocessar-documentos`.
#
# Debug robo-valor-contratado-item64 (20/10/2026): 3 -> 4 — o valor do
# documento passa a preferir total/global ao mensal/anual (e marca
# `por_itens` quando o contrato só traz valores por item, sem global único —
# item 18) e o apostilamento ganha a forma "novo valor global ... passa a
# ser de"; os `valor`/`apostilamento` já gravados no cache (versão 3) só são
# relidos por `sei_coletar --reprocessar-documentos`.
VERSAO_EXTRACAO_DOCUMENTO = 4

# Marcador de rodapé do SEI ("A autenticidade deste documento pode ser
# conferida no site https://sei.cfc.org.br/..."), testado por `in`
# (casefold) — não é regex porque o texto que segue varia (URL, código
# verificador) e só o início da frase é estável.
MARCADORES_RODAPE_SEI = (
    "a autenticidade deste documento pode ser conferida",
)

# --------------------------------------------------- contratado (Fase 33) ---
# CNPJ de qualquer parte citada no texto; tolera o erro de modelo do CNPJ do
# CFC ("3.618.570/0001-07", um dígito faltando no prefixo) — nunca pode virar
# o CNPJ do contratado.
RE_CNPJ = re.compile(r"\d{1,2}\.\d{3}\.\d{3}/\d{4}-\d{2}")
_CNPJ_CFC = {"33.618.570/0001-07", "3.618.570/0001-07"}

# Cláusula primeira marca o fim do preâmbulo — CNPJ/razão social do
# contratado só são procurados antes dela (spec §3.1).
RE_CLAUSULA_PRIMEIRA = re.compile(r"cl[aá]usula\s+primeira", re.I)

# Razão social no preâmbulo: "e (de outro lado) a|o|o(a)|a empresa|a(o)
# <NOME>, inscrit[ao]/sociedade/estabelecid[ao]/com sede/.../CNPJ...".
# Alternativas ordenadas da mais específica para a mais curta ("a empresa"
# antes de "a" solto) para que o casamento não pare em "a" e devolva
# "empresa <NOME>" por engano. `[^\n]+?` é não-guloso e NUNCA atravessa
# quebra de linha nenhuma (achado do item 3, contrato 08/2026, 18/09/2026:
# o parágrafo de qualificação é uma linha só no texto extraído do SEI —
# permitir a captura atravessar `\n\s*\n` deixava o "E A " do TÍTULO se
# estender até o ", inscrit" do PRÓPRIO CFC quando título e parágrafo vinham
# em linhas consecutivas sem linha em branco entre elas).
#
# Lista de terminadores ampliada (achado do item 5, contrato 98/2024,
# 18/09/2026: o preâmbulo da CAESB segue direto de "– CAESB" para ", com
# sede no Centro de Gestão..." — sem "inscrit"/"sociedade"/"estabelecid"
# antes do endereço — e a captura vazava nome + endereço + inscrição
# estadual inteiros). `\s*,\s*` (em vez do "," fixo com um espaço) tolera
# tanto "CAESB , com sede" (espaço ANTES da vírgula, erro de digitação do
# preâmbulo original) quanto "CAESB, com sede" (sem espaço extra).
# Lista de terminadores ampliada (achado do item
# 100, CIEE, sondagem da Fase 34, protocolo 1517335, spec da Fase 33 §2):
# entidades sem fins lucrativos/associativas terminam a qualificação em
# "associação"/"fundação"/etc. em vez de "inscrit"/"sociedade"/"estabelecid".
# Agrupadas junto dos demais qualificadores de tipo de entidade, antes do
# terminador genérico "entidade".
RE_RAZAO_PREAMBULO = re.compile(
    r"e (?:de outro lado )?(?:a empresa|a\(o\)|o\(a\)|a|o) "
    r"(?P<razao>[^\n]+?)\s*,\s*(?:inscrit|sociedade|estabelecid|com sede|"
    r"sediad|com endere[cç]o|localizad|situad|pessoa jur[íi]dica|"
    r"empresa p[úu]blica|associação|fundação|instituto|organização|"
    r"cooperativa|sindicato|federação|confederação|empresa individual|"
    r"microempresa|eireli|entidade|neste ato|doravante|representad|CNPJ)",
    re.I,
)

# Fallback: título do instrumento, "...ENTRE SI O CONSELHO FEDERAL DE
# CONTABILIDADE E (A EMPRESA)? <NOME>".
RE_RAZAO_TITULO = re.compile(
    r"ENTRE SI O CONSELHO FEDERAL DE CONTABILIDADE E (?:A EMPRESA )?(?P<razao>[^.\n]+)",
    re.I,
)


def _preambulo(texto: str) -> str:
    """Recorte do início do texto até (sem incluir) a "Cláusula Primeira" —
    onde vivem o título e o parágrafo de qualificação das partes. Sem essa
    cláusula no texto, devolve o texto inteiro (fallback seguro)."""
    texto = texto or ""
    m = RE_CLAUSULA_PRIMEIRA.search(texto)
    return texto[: m.start()] if m else texto


def _colapsar_espacos(texto: str) -> str:
    """Colapsa espaços internos e remove espaço solto antes de vírgula/ponto
    final (achado do item 5, contrato 98/2024: o preâmbulo original tem
    "CAESB , com sede" — espaço antes da vírgula — e a normalização evita
    que esse ruído de digitação sobreviva em `razao_social`)."""
    texto = re.sub(r"\s+", " ", texto).strip()
    return re.sub(r"\s+([,.])", r"\1", texto)


def _inicio_apos_contratante(preambulo: str) -> int:
    """Índice do preâmbulo a partir de onde `RE_RAZAO_PREAMBULO` pode
    procurar a razão social do CONTRATADO — nunca antes, para que o "e a
    "/"e o " do parágrafo de qualificação do próprio CFC (CONTRATANTE)
    jamais entre na disputa (achado do item 3, contrato 08/2026). Corte:
    logo depois do primeiro CNPJ do CFC (`_CNPJ_CFC`, inclusive a variante
    com o erro de modelo "3.618.570/0001-07"); sem CNPJ do CFC no texto,
    logo depois da palavra "CONTRATANTE" (case-insensitive); sem nenhum dos
    dois marcadores, devolve 0 — o preâmbulo inteiro, mesmo comportamento de
    antes desta correção."""
    for m in RE_CNPJ.finditer(preambulo):
        if m.group(0) in _CNPJ_CFC:
            return m.end()
    m = re.search(r"contratante", preambulo, re.I)
    if m:
        return m.end()
    return 0


# Sinais de endereço dentro de uma razão social candidata (achado do item 5,
# contrato 98/2024): a captura não deveria mais chegar até esses trechos
# agora que `RE_RAZAO_PREAMBULO` para em "com sede"/"sediad"/etc, mas isto é
# a rede de segurança para qualquer preâmbulo com redação diferente da já
# vista — a mesma função vale para a captura do preâmbulo E a do título.
RE_SINAL_ENDERECO = re.compile(
    r"\bcom sede\b|\bcep\b|\binscri[cç][aã]o estadual\b|\bav\.|\brua\b|"
    r"\bquadra\b|\blote\b",
    re.I,
)

# Referência de volta ao nome já citado no título ("a contratada acima
# qualificada", "a empresa acima referida"...), nunca o nome em si — sem
# este filtro, os terminadores "doravante"/"neste ato"/"representad" (achado
# do item 5) capturariam essa referência genérica como se fosse a razão
# social (regressão pega por `test_razao_social_titulo_quando_preambulo_
# nao_repete_o_nome`, que já cobria esse texto boilerplate antes desta
# correção).
RE_REFERENCIA_GENERICA = re.compile(
    r"acima\s+(?:qualificad|referid|identificad|mencionad|citad)", re.I
)


def _razao_valida(s: str | None) -> bool:
    """Sanidade contra captura absurda (achado do item 3, contrato 08/2026;
    achado do item 5, contrato 98/2024): rejeita uma razão social candidata
    — do preâmbulo OU do título — quando ela atravessou o parágrafo de
    qualificação do CFC, vazou pedaço de endereço (achado do item 5:
    "com sede"/"CEP"/"Inscrição Estadual"/"Av."/"Rua"/"Quadra"/"Lote"), é
    uma referência genérica de volta ao título ("acima qualificada/referida/
    ...") ou virou lixo de regex. Nunca lança exceção; devolve `False` para
    o chamador cair no próximo fallback (preâmbulo -> título -> `None`)."""
    if not s:
        return False
    if "\n" in s:
        return False
    if len(s) > 255:
        return False
    if len(s.strip()) < 3:
        return False
    baixa = s.casefold()
    if "conselho federal de contabilidade" in baixa:
        return False
    if "cnpj" in baixa:
        return False
    # (achado do item 100, CIEE): mesmo quando um terminador válido
    # casa DEPOIS desses termos, a captura não pode carregar o ruído da
    # qualificação de entidade sem fins lucrativos.
    if "filantrópica" in baixa:
        return False
    if "sem fins lucrativos" in baixa:
        return False
    if "de direito privado" in baixa:
        return False
    if RE_SINAL_ENDERECO.search(s):
        return False
    if RE_REFERENCIA_GENERICA.search(s):
        return False
    return True


def extrair_contratado(texto: str) -> dict:
    """Razão social + CNPJ do contratado (nunca do CFC), lidos do preâmbulo
    do instrumento (início do texto, antes da "Cláusula Primeira"). CNPJ =
    primeiro CNPJ do preâmbulo que não está em `_CNPJ_CFC`; `None` quando
    nenhum é encontrado (contratado pessoa física). Razão social: regex do
    preâmbulo, aplicada só ao trecho DEPOIS do CNPJ/da palavra "CONTRATANTE"
    do próprio CFC (`_inicio_apos_contratante`, `fonte="preambulo"`); se não
    casar ou a captura não passar em `_razao_valida`, cai para o título do
    instrumento (`fonte="titulo"`, também sujeito a `_razao_valida`); se
    nenhuma casar/validar, tudo `None` (`fonte=None`). NÃO valida o CNPJ
    (checksum é responsabilidade de `regras.py`) — só
    extrai o que está no texto."""
    preambulo = _preambulo(texto)

    cnpj = None
    for m in RE_CNPJ.finditer(preambulo):
        if m.group(0) not in _CNPJ_CFC:
            cnpj = m.group(0)
            break

    razao_social = None
    fonte = None
    trecho_razao = preambulo[_inicio_apos_contratante(preambulo):]
    m = RE_RAZAO_PREAMBULO.search(trecho_razao)
    if m and _razao_valida(m.group("razao")):
        razao_social = _colapsar_espacos(m.group("razao"))
        fonte = "preambulo"
    else:
        m = RE_RAZAO_TITULO.search(preambulo)
        if m:
            candidata_bruta = m.group("razao")
            if _razao_valida(candidata_bruta):
                razao_social = _colapsar_espacos(candidata_bruta).rstrip(".").strip()
                fonte = "titulo"

    return {"razao_social": razao_social, "cnpj": cnpj, "fonte": fonte}


# -------------------------------------------------- procedência (Fase 33) ---
# Alternância de modalidades, reaproveitada por `RE_PROCEDENCIA` (prosa do
# contrato) e `RE_PROCEDENCIA_CAMPO` (campo estruturado da Ordem de
# Fornecimento, Fase 34) — mesma lista, dois pontos de entrada no texto.
_MODALIDADES_RE = (
    r"Dispensa de Licitação|Dispensa Eletrônica|"
    r"Pregão Eletrônico|Pregão|Inexigibilidade de Licitação|Inexigibilidade|"
    r"Concorrência|Adesão à? Ata de Registro de Preços|Credenciamento"
)

# Tolerância a uma repetição de "de Licitação" logo após a modalidade casada
# (achado real do item 105, sondagem da Fase 34, protocolo 0120055: o
# instrumento original do CFC tem "Inexigibilidade de Licitação de
# Licitação n. ..." — erro de redação do próprio instrumento). Fora do
# grupo `mod`, para que `modalidade_texto` continue só "Inexigibilidade de
# Licitação", sem a duplicação.
_REPETICAO_DE_LICITACAO_RE = r"(?:\s+de\s+Licita[cç][aã]o)?"

# Achado dados M6 (QA 30/09/2026): o grupo capturado precisa começar com
# DÍGITO — "n. -90015/2025" (hífen solto antes do número) ou "n. …90015/2025"
# (reticências) nunca podem virar `numero` (itens reais 14/18/54 de 2026
# gravaram "-90015/2025"/"-26/2026"/"-90004/2026", sobrescrevendo um valor
# correto já digitado). Internamente o número ainda pode ter espaço/hífen
# solto (normalizado por `extrair_procedencia`).
RE_PROCEDENCIA = re.compile(
    r"decorrente d[aeo]s?\s+(?P<mod>" + _MODALIDADES_RE + r")" +
    _REPETICAO_DE_LICITACAO_RE +
    r"\s+n[º°.]*\s*(?P<num>\d[\d\s./-]*?)\s*[,;]",
    re.I,
)

# Campo estruturado das Ordens de Fornecimento (achado real dos itens 19 e
# 40, sondagem da Fase 34, protocolos 1282080/1504465, spec da Fase 33 §2):
# rótulo:valor numa linha própria, "Modalidade: <mod> nº <número>", fora de
# qualquer prosa "decorrente d[ao]...". Tentado só quando `RE_PROCEDENCIA`
# não casa (spec: forma de contrato tem prioridade sobre a de OF).
# Achado dados M6 (QA 30/09/2026): mesma âncora de dígito obrigatório no
# início do número capturado.
RE_PROCEDENCIA_CAMPO = re.compile(
    r"Modalidade:\s*(?P<mod>" + _MODALIDADES_RE + r")" +
    _REPETICAO_DE_LICITACAO_RE +
    r"\s+n[º°.]*\s*(?P<num>\d[\d./-]*)",
    re.I,
)

# Modalidades que mapeiam direto para o catálogo (chave sem acento,
# minúscula) — Dispensa/Dispensa Eletrônica são desambiguadas por `numero`.
_MAPA_MODALIDADE = {
    "pregao": "pregao eletronico",
    "pregao eletronico": "pregao eletronico",
    "inexigibilidade": "inexigibilidade",
    "inexigibilidade de licitacao": "inexigibilidade",
    "concorrencia": "concorrencia",
    "adesao a ata de registro de precos": "adesao a arp",
    "credenciamento": "credenciamento",
}

RE_DISPENSA_COM_DISPUTA = re.compile(r"^9\d{4}/\d{4}$")


def _modalidade_catalogo(modalidade_texto: str, numero: str) -> str | None:
    chave = _sem_acento(_colapsar_espacos(modalidade_texto))
    if chave.startswith("dispensa"):
        if RE_DISPENSA_COM_DISPUTA.match(numero or ""):
            return "dispensa com disputa"
        if (numero or "").startswith("383500-"):
            return "dispensa sem disputa"
        return None
    return _MAPA_MODALIDADE.get(chave)


def extrair_procedencia(texto: str) -> dict:
    """Modalidade + nº da contratação citados no preâmbulo ("decorrente
    d[ao]s <Modalidade> nº <número>") ou, quando essa prosa não aparece
    (Ordem de Fornecimento, Fase 34), no campo estruturado "Modalidade:
    <Modalidade> nº <número>" (`RE_PROCEDENCIA_CAMPO`, tentado só depois da
    prosa do contrato — a forma de contrato tem prioridade). `numero`
    normalizado (sem espaços ao redor do hífen nem espaços internos).
    `modalidade_catalogo` só quando a modalidade mapeia para o catálogo do
    PCA — Dispensa/Dispensa Eletrônica desambiguadas pelo formato do número
    (compras.gov `9####/AAAA` -> "com disputa"; `383500-...` -> "sem
    disputa"; qualquer outro formato -> `None`, pendência). Sem nenhuma das
    duas âncoras -> tudo `None`."""
    texto = texto or ""
    m = RE_PROCEDENCIA.search(texto) or RE_PROCEDENCIA_CAMPO.search(texto)
    if not m:
        return {"modalidade_texto": None, "numero": None, "modalidade_catalogo": None}
    modalidade_texto = m.group("mod")
    numero = re.sub(r"\s+", "", m.group("num"))
    return {
        "modalidade_texto": modalidade_texto,
        "numero": numero,
        "modalidade_catalogo": _modalidade_catalogo(modalidade_texto, numero),
    }


# ---------------------------------------------------- vigência (Fase 33) ---
# Forma (a): "prazo de vigência ... é de N (extenso) meses|anos contados da
# (data de) (sua) assinatura". Vírgula opcional antes de "contados" (achado real do item 105, sondagem da Fase 34, protocolo 0120055: "...
# meses, contados da data de assinatura...") — variante tolerada da mesma
# forma, sem forma nova.
RE_VIGENCIA_PRAZO_DESDE_ASSINATURA = re.compile(
    r"prazo\s+de\s+vig[eê]ncia.{0,80}?[eé]\s+de\s+(?P<n>\d+)\s*"
    r"\((?P<extenso>[^)]+)\)?\s*(?P<unidade>meses|anos),?\s+contados\s+da\s+"
    r"(?:data\s+de\s+)?(?:sua\s+)?assinatura",
    re.I | re.S,
)

# Forma (b): "com início na data de DD/MM/AAAA e encerramento em DD/MM/AAAA".
RE_VIGENCIA_DATAS_EXPLICITAS = re.compile(
    r"com\s+in[ií]cio\s+na\s+data\s+de\s+(?P<inicio>\d{2}/\d{2}/\d{4})\s+e\s+"
    r"encerramento\s+em\s+(?P<fim>\d{2}/\d{2}/\d{4})",
    re.I,
)

# Forma (c): mesma estrutura de (a), sem a âncora "contados... assinatura"
# ("de N (extenso) meses" sozinho) — também ancorada em `data_assinatura`.
RE_VIGENCIA_PRAZO_SEM_ANCORA = re.compile(
    r"de\s+(?P<n>\d+)\s*\((?P<extenso>[^)]+)\)?\s*(?P<unidade>meses|anos)\b",
    re.I,
)

# Forma (d), Fase 34 (achado real do item 44, sondagem, protocolo
# 1250786): mesma ideia da forma (b) — datas explícitas —, mas com o
# conector "a" em vez de "com início na data de ... e encerramento em ...".
RE_VIGENCIA_DATAS_INTERVALO = re.compile(
    r"vig[eê]ncia\s+da\s+contrata[cç][aã]o\s+[eé]\s+de\s+"
    r"(?P<inicio>\d{2}/\d{2}/\d{4})\s+a\s+(?P<fim>\d{2}/\d{2}/\d{4})",
    re.I,
)

# Forma (e), Fase 34 (achado real do item 138, sondagem, protocolo
# 1294043): início = data de assinatura, fim explícito no corpo ("...
# vigência a partir de sua assinatura até DD/MM/AAAA"). Também ancorada em
# `data_assinatura` (sem ela não há "início" para compor o resultado).
RE_VIGENCIA_ASSINATURA_ATE_DATA = re.compile(
    r"vig[eê]ncia\s+a\s+partir\s+de\s+sua\s+assinatura\s+at[eé]\s+"
    r"(?P<fim>\d{2}/\d{2}/\d{4})",
    re.I,
)

# Termo aditivo, cláusula de prorrogação — forma (1): datas explícitas.
RE_PRORROGACAO_DATAS = re.compile(
    r"a partir de\s+(?P<inicio>\d{2}/\d{2}/\d{4})\s+até\s+(?P<fim>\d{2}/\d{2}/\d{4})",
    re.I,
)

# Forma (2): "por mais N (extenso)? meses, a partir de DD/MM/AAAA".
RE_PRORROGACAO_PRAZO = re.compile(
    r"por mais\s+(?P<n>\d+)\s*(?:\([^)]+\))?\s*meses,?\s+a partir\s+de\s+"
    r"(?P<inicio>\d{2}/\d{2}/\d{4})",
    re.I,
)


def _somar_meses(data: date, n: int) -> date:
    """Soma `n` meses a `data`, sem `calendar`/`dateutil`: ajusta ano/mês por
    divisão inteira e usa `min(dia_original, último_dia_do_mês_resultante)`
    para o dia — nunca gera uma data inexistente como 30/02."""
    mes_total = data.month - 1 + n
    ano = data.year + mes_total // 12
    mes = mes_total % 12 + 1
    proximo_mes = date(ano + 1, 1, 1) if mes == 12 else date(ano, mes + 1, 1)
    ultimo_dia_do_mes = (proximo_mes - timedelta(days=1)).day
    dia = min(data.day, ultimo_dia_do_mes)
    return date(ano, mes, dia)


def _data_de_assinatura(data_assinatura: str | None) -> date | None:
    """Converte "DD/MM/AAAA HH:MM" (mesmo formato de `ultima_assinatura`) na
    parte `date`, descartando a hora. `None` quando `data_assinatura` é
    vazio ou não bate com o formato esperado."""
    if not data_assinatura:
        return None
    try:
        return datetime.strptime(data_assinatura, "%d/%m/%Y %H:%M").date()
    except ValueError:
        return None


# Achado dados M5 (QA 30/09/2026) — a forma (c) de `extrair_vigencia`
# ("de N (extenso) meses|anos" SEM a âncora "contados... assinatura") casa
# dentro de QUALQUER frase com esse molde, inclusive "interregno de 12
# (doze) meses" e "garantia de 60 (sessenta) meses" — nenhuma das duas é a
# vigência do instrumento. `_tem_ancora_de_vigencia` exige a palavra
# "vigência" (ou "prazo de execução/contratual/do contrato/da contratação")
# nos 100 caracteres antes do match, e recusa quando a janela tem
# "garantia"/"interregno"/"reajust" (a cláusula errada).
_RE_ANCORA_VIGENCIA = re.compile(
    r"vig[eê]ncia|prazo\s+(?:de\s+)?(?:execu[cç][aã]o|contratual|do\s+contrato|"
    r"da\s+contrata[cç][aã]o)",
    re.I,
)
_RE_ANCORA_PROIBIDA = re.compile(r"garantia|interregno|reajust", re.I)


def _tem_ancora_de_vigencia(texto: str, inicio_match: int) -> bool:
    janela = texto[max(0, inicio_match - 100):inicio_match]
    if _RE_ANCORA_PROIBIDA.search(janela):
        return False
    return bool(_RE_ANCORA_VIGENCIA.search(janela))


# Achado dados B3 (QA 30/09/2026) — uma assinatura datada de um ano muito no
# futuro (ex.: 2099, erro de OCR/digitação do SEI) nunca pode servir de
# âncora de vigência; `_FOLGA_ANOS_ASSINATURA_FUTURA` tolera só alguns anos
# à frente de hoje (relógio do servidor), suficiente para qualquer
# assinatura real.
_FOLGA_ANOS_ASSINATURA_FUTURA = 5


def _ano_assinatura_plausivel(ano: int) -> bool:
    return ano <= datetime.now().year + _FOLGA_ANOS_ASSINATURA_FUTURA


def _vigencia_sanidade(resultado: dict, vazio: dict) -> dict:
    """Achado dados B3 — uma vigência com `fim` antes de `inicio` nunca é
    aceita silenciosamente; cai no mesmo caminho de pendência
    `vigencia_nao_lida` que a leitura vazia já usa."""
    inicio = resultado.get("inicio")
    fim = resultado.get("fim")
    if inicio is not None and fim is not None and fim < inicio:
        return vazio
    return resultado


def _vigencia_por_prazo(m: re.Match, data_base: date, forma: str) -> dict | None:
    """A partir de um match de `RE_VIGENCIA_PRAZO_DESDE_ASSINATURA` ou
    `RE_VIGENCIA_PRAZO_SEM_ANCORA`, devolve `{"inicio", "fim", "forma"}` —
    `None` quando o algarismo `n` diverge do extenso entre parênteses
    (proteção contra erro de leitura, nunca lança exceção)."""
    n = int(m.group("n"))
    extenso = m.group("extenso")
    if extenso and inteiro_por_extenso(extenso) != n:
        return None
    unidade = m.group("unidade").lower()
    meses = n * 12 if unidade == "anos" else n
    fim = _somar_meses(data_base, meses) - timedelta(days=1)
    return {"inicio": data_base, "fim": fim, "forma": forma}


def extrair_vigencia(texto: str, data_assinatura: str | None) -> dict:
    """Início/fim da vigência do instrumento, pelas 5 formas da cláusula de
    prazo (spec §2/§3.1, mais §2 "Padrões novos" da Fase 34), nesta ordem
    de tentativa: (a) `prazo_desde_assinatura`; (b) `datas_explicitas`; (c)
    `prazo_sem_ancora`; (d) `datas_intervalo`; (e) `assinatura_ate_data`.
    `data_assinatura` no formato "DD/MM/AAAA HH:MM" (mesmo de
    `ultima_assinatura`) ou `None`. As formas (a)/(c)/(e) exigem
    `data_assinatura` (não há âncora para calcular sem ela); (a)/(c)
    conferem o algarismo `n` contra o extenso entre parênteses quando
    presente — divergência devolve tudo `None`, nunca lança exceção.
    Devolve sempre `{"inicio": date|None, "fim": date|None, "forma":
    str|None}`."""
    vazio = {"inicio": None, "fim": None, "forma": None}
    texto = texto or ""
    data_base = _data_de_assinatura(data_assinatura)
    # Achado dados B3 — uma assinatura implausível (ex.: 2099) nunca serve
    # de âncora para as formas (a)/(c)/(e): elas degradam para as formas
    # seguintes (ou para `vazio`), mesmo caminho de pendência de "vigência
    # não lida" que `regras.py` já trata.
    if data_base is not None and not _ano_assinatura_plausivel(data_base.year):
        data_base = None

    if data_base is not None:
        m = RE_VIGENCIA_PRAZO_DESDE_ASSINATURA.search(texto)
        if m:
            resultado = _vigencia_por_prazo(m, data_base, "prazo_desde_assinatura") or vazio
            return _vigencia_sanidade(resultado, vazio)

    m = RE_VIGENCIA_DATAS_EXPLICITAS.search(texto)
    if m:
        try:
            inicio = datetime.strptime(m.group("inicio"), "%d/%m/%Y").date()
            fim = datetime.strptime(m.group("fim"), "%d/%m/%Y").date()
        except ValueError:
            return vazio
        return _vigencia_sanidade(
            {"inicio": inicio, "fim": fim, "forma": "datas_explicitas"}, vazio
        )

    if data_base is not None:
        # Achado dados M5 — a primeira ocorrência COM âncora de vigência
        # válida vence; sem nenhuma âncora válida em NENHUMA ocorrência, a
        # forma (c) não produz resultado (segue para (d)/(e)/vazio, igual a
        # hoje quando nada casa).
        for m in RE_VIGENCIA_PRAZO_SEM_ANCORA.finditer(texto):
            if _tem_ancora_de_vigencia(texto, m.start()):
                resultado = _vigencia_por_prazo(m, data_base, "prazo_sem_ancora") or vazio
                return _vigencia_sanidade(resultado, vazio)

    m = RE_VIGENCIA_DATAS_INTERVALO.search(texto)
    if m:
        try:
            inicio = datetime.strptime(m.group("inicio"), "%d/%m/%Y").date()
            fim = datetime.strptime(m.group("fim"), "%d/%m/%Y").date()
        except ValueError:
            return vazio
        return _vigencia_sanidade(
            {"inicio": inicio, "fim": fim, "forma": "datas_intervalo"}, vazio
        )

    if data_base is not None:
        m = RE_VIGENCIA_ASSINATURA_ATE_DATA.search(texto)
        if m:
            try:
                fim = datetime.strptime(m.group("fim"), "%d/%m/%Y").date()
            except ValueError:
                return vazio
            return _vigencia_sanidade(
                {"inicio": data_base, "fim": fim, "forma": "assinatura_ate_data"}, vazio
            )

    return vazio


def extrair_prorrogacao(texto: str) -> dict:
    """Início/fim da nova vigência citada num termo aditivo de prorrogação
    (cláusula 1.1, spec §3.1), duas formas: (1) datas explícitas ("a partir
    de X até Y"); (2) prazo ("por mais N meses, a partir de X" — `fim = X +
    N meses - 1 dia`, mesmo `_somar_meses` de `extrair_vigencia`, sem
    checagem de extenso). Nenhuma forma casada -> `{"inicio": None, "fim":
    None}`, nunca lança exceção."""
    vazio = {"inicio": None, "fim": None}
    texto = texto or ""

    m = RE_PRORROGACAO_DATAS.search(texto)
    if m:
        try:
            inicio = datetime.strptime(m.group("inicio"), "%d/%m/%Y").date()
            fim = datetime.strptime(m.group("fim"), "%d/%m/%Y").date()
        except ValueError:
            return vazio
        return {"inicio": inicio, "fim": fim}

    m = RE_PRORROGACAO_PRAZO.search(texto)
    if m:
        try:
            inicio = datetime.strptime(m.group("inicio"), "%d/%m/%Y").date()
        except ValueError:
            return vazio
        n = int(m.group("n"))
        fim = _somar_meses(inicio, n) - timedelta(days=1)
        return {"inicio": inicio, "fim": fim}

    return vazio


# ----------------------------------------------- apostilamento (Fase 35) ---
# Sondagem read-only de 17 instrumentos reais (spec da Fase 33 §2,
# subseção "Padrões — apostilamento (Fase 35)"): 14/17 seguem o MESMO molde
# de reajuste cifra-a-cifra ("Valor [rótulo]: R$ X (extenso) ... Novo valor
# [rótulo]: R$ Y (extenso) ... reajustado com base no [índice]"); 2/17
# (item 108) usam a âncora "valor total (anual)? da contratação" já
# reconhecida por `extrair_valor_documento`; 2/17 (item 94) somam a
# dualidade mensal x anual com data-base "retroativo a...". A hipótese
# original (a) "dotação/empenho puro" (itens 43/50/57) foi REFUTADA pelo
# texto real — nenhum dos 17 é dotação pura; `natureza="dotacao"` fica
# reservado no contrato de saída sem âncora dedicada nesta fase
# (achado real substitui hipótese, nenhum casamento forçado).

RE_APOSTILAMENTO_REAJUSTE = re.compile(r"reajustad\w*|reajuste\b", re.I)
RE_APOSTILAMENTO_REPACTUACAO = re.compile(r"repactuad\w*|repactua[cç][aã]o", re.I)
RE_APOSTILAMENTO_DOTACAO = re.compile(r"dota[cç][aã]o\s+or[cç]ament[aá]ria|\bempenho\b", re.I)

# Âncora "valor total (anual)? da contratação" (item 108) — mesmo padrão
# "valor total" já usado por `RE_VALOR_DOCUMENTO`, agora confirmado também
# em apostilamento. Quando casa, é o valor NOVO (o total restabelecido por
# este apostilamento); não há "anterior" explícito nesta forma de texto.
RE_APOSTILAMENTO_VALOR_TOTAL = re.compile(
    r"\bvalor\s+total\b.{0,80}?"
    r"R\$\s*(?P<cifra>\d{1,3}(?:\.\d{3})*,\d{2})\s*\((?P<extenso>[^)]+)\)",
    re.I | re.S,
)

# Forma "o novo valor global do contrato passa a ser de R$ Y (extenso)" —
# achado real do 2º Termo de Apostilamento do item 64 (protocolo 1603102,
# cláusula 2.3; debug robo-valor-contratado-item64, 20/10/2026). O mesmo
# termo cita outras cifras globais ("o valor global do contrato foi
# atualizado de R$ X para R$ Y", cláusula 2.1, correção intermediária) e
# valores por período ("valor correspondente ao primeiro período
# contratual: R$ ...") que nunca são o global: só a frase "... passa a ser
# de R$" casa, e vale a ÚLTIMA ocorrência (a consolidação final). Tentada
# antes de `RE_APOSTILAMENTO_VALOR_TOTAL` — nenhum dos apostilamentos lidos
# até 20/10/2026 tem "valor global ... passa a ser de" além deste, então a
# ordem não muda a leitura de nenhum outro.
RE_APOSTILAMENTO_NOVO_VALOR_GLOBAL = re.compile(
    r"\b(?:novo\s+)?valor\s+global\b[^;]{0,80}?\bpassa\s+a\s+ser\s+de\s+"
    r"R\$\s*(?P<cifra>\d{1,3}(?:\.\d{3})*,\d{2})\s*\((?P<extenso>[^)]+)\)",
    re.I | re.S,
)

# Par "Valor [rótulo]: R$ X (extenso)" / "Novo valor [rótulo]: R$ Y
# (extenso)" — molde dominante (14/17). Lookbehind negativo em
# `RE_APOSTILAMENTO_VALOR_ANTERIOR` evita casar a própria cláusula "Novo
# valor...". `RE_APOSTILAMENTO_VALOR_NOVO` exige "R$" — achado real do item
# 106/protocolo 1008024 ("Novo valor do contrato: 28.868,92 ..." sem "R$",
# erro de digitação do instrumento original) fica pendência esperada, sem
# casamento forçado.
RE_APOSTILAMENTO_VALOR_ANTERIOR = re.compile(
    r"(?<!Novo )Valor\s*(?P<rotulo>[^:\n]{0,60}?)\s*:\s*"
    r"R\$\s*(?P<cifra>\d{1,3}(?:\.\d{3})*,\d{2})\s*\((?P<extenso>[^)]+)\)",
    re.I,
)
RE_APOSTILAMENTO_VALOR_NOVO = re.compile(
    r"Novo\s+valor\s*(?P<rotulo>[^:\n]{0,40}?)\s*:\s*"
    r"R\$\s*(?P<cifra>\d{1,3}(?:\.\d{3})*,\d{2})\s*\((?P<extenso>[^)]+)\)",
    re.I,
)

# Índice + percentual do reajuste — achado real: "reajustado com base
# [n[ao]|na aplicação d[ao]] ... IPCA|INPC|ICTI|IGP-M ... [na ordem de
# N,NN%]?". ICTI/INPC aparecem como sigla ao final do nome por extenso do
# índice; percentual só presente nos casos com IPCA (achado real, nenhum
# dos casos ICTI/INPC lidos trazia percentual explícito no corpo).
RE_APOSTILAMENTO_INDICE = re.compile(
    r"reajustad\w*\s+com\s+base\s+(?:n[ao]|na\s+aplica[cç][aã]o\s+d[ao])\s+"
    r".{0,80}?\b(?P<indice>IPCA|INPC|IGP-M|ICTI)\b"
    r"(?:.{0,40}?na\s+ordem\s+de\s+(?P<percentual>\d+,\d+)\s*%)?",
    re.I | re.S,
)

# Data-base explícita — achado real (item 94, protocolos 0060245/0063897):
# "retroativo a 1º de setembro de 2022" (dia + mês por extenso + ano),
# NUNCA o formato DD/MM/AAAA hipotetizado (achado real substitui
# a hipótese). Nos demais 15/17 instrumentos essa cláusula não aparece —
# `data_base=None` é o caso comum.
_MESES_APOSTILAMENTO = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9,
    "outubro": 10, "novembro": 11, "dezembro": 12,
}
RE_APOSTILAMENTO_DATA_BASE = re.compile(
    r"retroativ\w*\s+a\s+(?P<dia>\d{1,2})[ºª°]?\s+de\s+"
    r"(?P<mes>[A-Za-zçÇãÃéÉóÓôÔ]+)\s+de\s+(?P<ano>\d{4})",
    re.I,
)


_PERIODICIDADES_NAO_GLOBAIS = ("mensal", "anual")


def _periodicidade_de(*textos: str | None) -> str | None:
    """"mensal"/"anual"/"global" — o que aparecer primeiro, nesta ordem de
    prioridade, em qualquer um dos textos passados (achado real: a palavra
    pode vir antes OU depois da cifra, conforme o rótulo — "Valor mensal
    atual", "Valor anual atual do contrato", "... R$ X (...) anual.").
    `None` quando nenhuma das três aparece."""
    baixa = " ".join(t for t in textos if t).casefold()
    if "mensal" in baixa:
        return "mensal"
    if "anual" in baixa:
        return "anual"
    if "global" in baixa:
        return "global"
    return None


def _data_base_apostilamento(texto: str) -> str | None:
    m = RE_APOSTILAMENTO_DATA_BASE.search(texto or "")
    if not m:
        return None
    mes = _MESES_APOSTILAMENTO.get(m.group("mes").casefold())
    if mes is None:
        return None
    try:
        return date(int(m.group("ano")), mes, int(m.group("dia"))).isoformat()
    except ValueError:
        return None


def extrair_apostilamento(texto: str) -> dict | None:
    """Natureza (reajuste/repactuação/dotação/outro), par de valores
    (anterior/novo), índice/percentual, periodicidade e data-base de um
    termo de apostilamento (spec da Fase 33 §2, subseção "Padrões —
    apostilamento (Fase 35)"; contrato de saída). Puro, nunca
    lança exceção; devolve `None` quando nenhuma âncora de apostilamento é
    reconhecida no texto.

    Só os padrões confirmados pela sondagem real entram em produção:
o molde dominante "Valor [rótulo]: R$ X ... Novo valor
    [rótulo]: R$ Y ..." (14/17 instrumentos); a âncora "valor total (anual)?
    da contratação" (item 108, 2/17) — tratada como valor NOVO, sem
    "anterior" explícito nesta forma; "repactuação" é reconhecida como
    sinônimo legal do MESMO molde de reajuste (nenhum dos 17 usa a palavra
    real, mas a Lei 14.133/2021 trata as duas cláusulas como equivalentes).
    `natureza="dotacao"` fica reservado no contrato de saída, sem âncora
    dedicada — nenhum dos 17 instrumentos lidos confirmou esse padrão.

    Debug robo-valor-contratado-item64 (20/10/2026): a forma "o novo valor
    global do contrato passa a ser de R$ Y (extenso)" (2º termo do item 64)
    tem prioridade sobre as demais — vale a última ocorrência, sem
    "anterior" explícito, periodicidade lida da própria frase.
    """
    texto = texto or ""

    # Forma "novo valor global ... passa a ser de R$ Y" (debug
    # robo-valor-contratado-item64): a última ocorrência; periodicidade lida
    # só da frase casada (nunca do trecho alargado pelo índice, que pode
    # alcançar os valores anuais por período citados no mesmo termo).
    m_global = None
    for m_global in RE_APOSTILAMENTO_NOVO_VALOR_GLOBAL.finditer(texto):
        pass
    periodicidade_da_forma = _periodicidade_de(m_global.group(0)) if m_global else None

    m_total = m_global or RE_APOSTILAMENTO_VALOR_TOTAL.search(texto)
    if m_total:
        cifra = m_total.group("cifra")
        extenso = m_total.group("extenso").strip()
        valor_anterior = None
        valor_novo = {"cifra": cifra, "extenso": extenso, "confere": valores_conferem(cifra, extenso)}
        inicio, fim = m_total.start(), m_total.end()
        m_ant = m_novo = None
    else:
        m_ant = RE_APOSTILAMENTO_VALOR_ANTERIOR.search(texto)
        m_novo = RE_APOSTILAMENTO_VALOR_NOVO.search(texto)
        valor_anterior = None
        if m_ant:
            cifra = m_ant.group("cifra")
            extenso = m_ant.group("extenso").strip()
            valor_anterior = {"cifra": cifra, "extenso": extenso, "confere": valores_conferem(cifra, extenso)}
        valor_novo = None
        if m_novo:
            cifra = m_novo.group("cifra")
            extenso = m_novo.group("extenso").strip()
            valor_novo = {"cifra": cifra, "extenso": extenso, "confere": valores_conferem(cifra, extenso)}
        candidatos = [m for m in (m_ant, m_novo) if m is not None]
        inicio = min(m.start() for m in candidatos) if candidatos else None
        fim = max(m.end() for m in candidatos) if candidatos else None

    m_indice = RE_APOSTILAMENTO_INDICE.search(texto)
    if m_indice:
        inicio = m_indice.start() if inicio is None else min(inicio, m_indice.start())
        fim = m_indice.end() if fim is None else max(fim, m_indice.end())

    achou_reajuste = RE_APOSTILAMENTO_REAJUSTE.search(texto) is not None
    achou_repactuacao = RE_APOSTILAMENTO_REPACTUACAO.search(texto) is not None
    achou_dotacao = RE_APOSTILAMENTO_DOTACAO.search(texto) is not None
    valor_encontrado = valor_anterior is not None or valor_novo is not None

    if not (m_total or m_ant or m_novo or m_indice or achou_reajuste or achou_repactuacao or achou_dotacao):
        return None

    if achou_repactuacao:
        natureza = "repactuacao"
    elif achou_reajuste:
        natureza = "reajuste"
    elif achou_dotacao and not valor_encontrado:
        natureza = "dotacao"
    else:
        natureza = "outro"

    trecho = " ".join(texto[inicio:fim].split())[:500] if inicio is not None else ""
    percentual = m_indice.group("percentual") if m_indice else None
    indice = m_indice.group("indice").upper() if m_indice else None
    periodicidade = periodicidade_da_forma or _periodicidade_de(trecho)
    data_base = _data_base_apostilamento(texto)

    return {
        "natureza": natureza,
        "valor_anterior": valor_anterior,
        "valor_novo": valor_novo,
        "percentual": percentual,
        "indice": indice,
        "periodicidade": periodicidade,
        "data_base": data_base,
        "trecho": trecho,
    }


_MAPA_TIPOS = {
    "contrato": "contrato",
    "termo de contrato": "contrato",
    "termo aditivo": "termo_aditivo",
    "termo de apostilamento": "apostilamento",
    "apostilamento": "apostilamento",
    "ordem de fornecimento": "ordem_fornecimento",
    "ata de registro de precos": "ata_rp",
    "termo de rescisao": None,
}


def _sem_acento(texto: str) -> str:
    import unicodedata

    return (
        unicodedata.normalize("NFKD", texto)
        .encode("ascii", "ignore")
        .decode()
        .lower()
    )


def tipo_documento(rotulo: str) -> str | None:
    """Casa `rotulo` contra `RE_CONTRATUAL` e devolve o tipo canônico do
    instrumento (`contrato|termo_aditivo|apostilamento|ordem_fornecimento|
    ata_rp`), ou `None` quando `rotulo` não casa com `RE_CONTRATUAL` ou
    quando o grupo casado é "termo de rescisão" (não é instrumento de
    contratação, não entra na disputa de valor)."""
    if not rotulo:
        return None
    m = RE_CONTRATUAL.match(rotulo)
    if not m:
        return None
    chave = _sem_acento(m.group(1))
    return _MAPA_TIPOS.get(chave)


def extrair_assinaturas(texto_html: str) -> dict:
    """Extrai as assinaturas eletrônicas do texto já extraído do HTML do
    documento (o chamador já rodou algo equivalente a `texto_de_html` do
    spike — este módulo não sabe o que é HTML, só recebe texto puro).
    Mesma lógica das linhas 506-519 do spike: papel "externo" quando
    "usuário externo" aparece no cargo (casefold), senão "cfc".

    (Fase 39) — cada assinatura ganha também `nome`, normalizado
    do mesmo jeito que `cargo` (colapso de espaços, sem hífen solto nas
    pontas); o grupo `nome` já era capturado por `RE_ASSINATURA`, só não
    saía no retorno. Nome NUNCA é inferido de `cargo`/andamento — só do
    que a regex capturou aqui. As 4 chaves agregadas e as demais chaves
    de cada assinatura continuam idênticas (regressão zero).

    Achado dados B2 (QA 30/09/2026) — uma data impossível (ex.: 31/02, erro
    de redação do SEI) é descartada ASSINATURA POR ASSINATURA: nunca
    propaga exceção para fora da função, nunca marca o documento inteiro
    como erro. As demais assinaturas (válidas) do mesmo documento
    continuam normalmente."""
    assinaturas = []
    datas = []
    for m in RE_ASSINATURA.finditer(texto_html or ""):
        cargo = " ".join(m.group("cargo").split()).strip(" -")
        nome = " ".join(m.group("nome").split()).strip(" -")
        data = m.group("data")
        hora = m.group("hora")
        try:
            data_hora = datetime.strptime(f"{data} {hora}", "%d/%m/%Y %H:%M")
        except ValueError:
            # Data impossível (ex.: 31/02) — descarta só esta assinatura.
            continue
        papel = "externo" if "usuário externo" in cargo.casefold() else "cfc"
        assinaturas.append({
            "papel": papel,
            "cargo": cargo,
            "nome": nome,
            "data": data,
            "hora": hora,
        })
        datas.append(data_hora)
    assinado_cfc = any(a["papel"] == "cfc" for a in assinaturas)
    assinado_externo = any(a["papel"] == "externo" for a in assinaturas)

    ultima_assinatura = max(datas).strftime("%d/%m/%Y %H:%M") if datas else None
    ultima_assinatura_cfc = max(
        (d for d, a in zip(datas, assinaturas) if a["papel"] == "cfc"),
        default=None,
    )
    if ultima_assinatura_cfc is not None:
        ultima_assinatura_cfc = ultima_assinatura_cfc.strftime("%d/%m/%Y %H:%M")

    return {
        "assinaturas": assinaturas,
        "assinado_cfc": assinado_cfc,
        "assinado_externo": assinado_externo,
        "ultima_assinatura": ultima_assinatura,
        "ultima_assinatura_cfc": ultima_assinatura_cfc,
    }


def extrair_numero_no_corpo(texto_html: str) -> str | None:
    """Nº do instrumento citado no corpo do documento (ex.: "08/2026"), ou
    `None` quando a frase-âncora não aparece."""
    if not texto_html:
        return None
    m = RE_NUMERO_CORPO.search(texto_html)
    return m.group(1) if m else None


def _rotulo_item_do_valor(texto: str, casamento) -> str | None:
    """"ITEM 01"/"LOTE 2"/"GRUPO 3" que qualifica a frase-âncora de valor
    `casamento` — o último rótulo da MESMA frase (desde o último "."/";"
    seguido de espaço, até `_JANELA_ROTULO_ITEM` caracteres antes) ou do
    trecho entre a âncora e o "R$" ("o valor total do ITEM 02: R$ ...").
    `None` sem rótulo."""
    janela = texto[max(0, casamento.start() - _JANELA_ROTULO_ITEM):casamento.start()]
    fins = list(RE_FIM_DE_FRASE.finditer(janela))
    frase = janela[fins[-1].end():] if fins else janela
    frase += texto[casamento.start():casamento.start("cifra")]
    rotulo = None
    for rotulo in RE_ROTULO_ITEM_VALOR.finditer(frase):
        pass
    if rotulo is None:
        return None
    return f"{rotulo.group('tipo').upper()} {rotulo.group('n')}"


def extrair_valor_documento(texto_html: str) -> dict | None:
    """Procura a cláusula de preço (§4.3): "valor total"/"valor global"/
    "valor mensal"/"valor anual"/"montante" seguida de "R$ <cifra>" e o
    extenso entre parênteses. Devolve `{"cifra", "extenso", "confere"}` ou
    `None` quando a frase-âncora não é encontrada — nunca lança exceção.

    (Fase 35): `periodicidade` ("mensal"/"anual"/"global") e
    `parcelas` (inteiro) são chaves OPCIONAIS, acrescentadas só quando o
    texto traz a pista — o dict continua tendo exatamente as 3 chaves
    originais quando nenhuma das duas pistas aparece (regressão da Fase
    32/33/34 preservada).

    Com mais de uma frase-âncora no texto, vale a primeira conferida e não
    mensal/anual; depois a primeira conferida periódica; sem nenhuma
    conferida, a primeira do texto (debug robo-valor-contratado-item64,
    20/10/2026).

    Valores por item (decisão do usuário, 20/10/2026 — item 18): quando as
    frases-âncora são de 2 ou mais itens/lotes/grupos distintos ("Para o
    ITEM 01, o valor total ... Para o ITEM 02, ...") e nenhuma frase SEM
    rótulo traz um valor conferido e não periódico (o global único), o dict
    ganha a chave OPCIONAL `por_itens` — lista `{"rotulo", "cifra",
    "confere"}`, um por item, na ordem do texto. `regras.py` nunca grava
    esse documento como `valor_contratado` (pendência `valor_por_itens`).
    Havendo o global sem rótulo, ele é o preferido e `por_itens` não
    aparece."""
    if not texto_html:
        return None
    casamentos = list(RE_VALOR_DOCUMENTO.finditer(texto_html))
    if not casamentos:
        return None

    def _conferido(casamento):
        return valores_conferem(casamento.group("cifra"), casamento.group("extenso").strip())

    def _periodico(casamento):
        return _periodicidade_de(casamento.group(0)) in _PERIODICIDADES_NAO_GLOBAIS

    rotulos = [_rotulo_item_do_valor(texto_html, casamento) for casamento in casamentos]
    multiplos_itens = len({rotulo for rotulo in rotulos if rotulo}) >= 2

    # Debug robo-valor-contratado-item64 (20/10/2026): "O valor mensal da
    # contratação é de R$ 2.213,93 (...), perfazendo o valor total de R$
    # 79.701,70 (...)" — o primeiro casamento é o mensal. Ordem de
    # preferência (o primeiro do texto desempata): conferido e não
    # periódico (total/global/montante) > conferido periódico > não
    # conferido. Um total com extenso errado no próprio instrumento (item
    # 105, contrato 0120055: "R$ 3.905.040,00 (três milhões, novecentos e
    # cinco reais e quarenta centavos)") nunca tira do documento o mensal
    # conferido — `regras.py` decide o que fazer com o periódico. Com
    # valores de 2+ itens, a frase sem rótulo (o global) vem antes das
    # rotuladas no mesmo grau.
    def _preferencia(par):
        casamento, rotulo = par
        return (
            _conferido(casamento) is not True,
            _periodico(casamento),
            multiplos_itens and rotulo is not None,
        )

    m, _rotulo = min(zip(casamentos, rotulos), key=_preferencia)
    cifra = m.group("cifra")
    extenso = m.group("extenso").strip()
    resultado = {
        "cifra": cifra,
        "extenso": extenso,
        "confere": valores_conferem(cifra, extenso),
    }
    periodicidade = _periodicidade_de(m.group(0))
    if periodicidade is not None:
        resultado["periodicidade"] = periodicidade
    global_sem_rotulo = any(
        rotulo is None and _conferido(casamento) is True and not _periodico(casamento)
        for casamento, rotulo in zip(casamentos, rotulos)
    )
    if multiplos_itens and not global_sem_rotulo:
        por_item: dict[str, list] = {}
        for casamento, rotulo in zip(casamentos, rotulos):
            if rotulo is not None:
                por_item.setdefault(rotulo, []).append(casamento)
        itens = []
        for rotulo, casamentos_do_item in por_item.items():
            preferido = min(
                casamentos_do_item,
                key=lambda casamento: (_conferido(casamento) is not True, _periodico(casamento)),
            )
            itens.append({
                "rotulo": rotulo,
                "cifra": preferido.group("cifra"),
                "confere": _conferido(preferido),
            })
        resultado["por_itens"] = itens
    m_parcelas = RE_PARCELAS_DOCUMENTO.search(texto_html)
    if m_parcelas:
        resultado["parcelas"] = int(m_parcelas.group("n"))
    return resultado


def deve_bloquear_recurso(resource_type: str) -> bool:
    """`True` para imagens e fontes (ícones do SEI são `<img>`, já cobertos
    por "image") — bloqueio de estáticos do navegador, §8.1 ponto 3."""
    return resource_type in {"image", "font"}


# --------------------------------------------- corpo do documento (Fase 39) ---

def texto_corpo_de(texto: str) -> str:
    """Recorta o "corpo" de um documento (contrato/aditivo/apostilamento) a
    partir do texto já sem tags (saída de `texto_de_html`) — o texto que
    entra no índice semântico do Assistente do PCA.
    Puro, nunca lança exceção.

    Duas remoções, nesta ordem:

    (a) o bloco de assinaturas eletrônicas em diante — tudo a partir da
    PRIMEIRA linha que casa com `RE_ASSINATURA` ou que contém um dos
    `MARCADORES_RODAPE_SEI` (achado/rodapé de autenticidade do SEI);

    (b) o cabeçalho institucional — linhas iniciais até (e preservando) a
    primeira linha que casa com `RE_CLAUSULA_PRIMEIRA` OU com o início de
    um título contratual (`RE_CONTRATUAL`, testado na linha inteira
    stripada); sem nenhum dos dois marcadores no texto restante, mantém
    tudo — NUNCA devolve vazio quando havia corpo (regra explícita do
    plano: o cabeçalho institucional é comum a todo instrumento, mas sua
    ausência de marcador não pode apagar o documento inteiro).

    Texto vazio/`None` devolve `""`. Espaços colapsados por linha."""
    texto = texto or ""
    if not texto.strip():
        return ""

    linhas = texto.splitlines()

    fim = len(linhas)
    for i, linha in enumerate(linhas):
        if RE_ASSINATURA.search(linha):
            fim = i
            break
        baixa = linha.casefold()
        if any(marcador in baixa for marcador in MARCADORES_RODAPE_SEI):
            fim = i
            break
    linhas = linhas[:fim]

    inicio = 0
    for i, linha in enumerate(linhas):
        candidata = linha.strip()
        if RE_CLAUSULA_PRIMEIRA.search(candidata) or RE_CONTRATUAL.match(candidata):
            inicio = i
            break
    linhas = linhas[inicio:]

    return "\n".join(" ".join(l.split()) for l in linhas if l.strip())


def hash_texto(texto: str) -> str:
    """SHA-256 hex do texto normalizado (espaços colapsados, `casefold`) —
    usado tanto pelo cache SEI (`coletor.ler_documento`) quanto pelo índice
    semântico (`apps.assistente.indice`) para saber se um trecho mudou sem
    comparar o texto inteiro byte a byte. Insensível a espaço/caixa."""
    normalizado = " ".join((texto or "").split()).casefold()
    return hashlib.sha256(normalizado.encode("utf-8")).hexdigest()
