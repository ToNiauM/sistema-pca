"""Módulo puro de regras de negócio do robô SEI (Fase 32).

Sem nenhum import de `django.db.models` nem de `apps.pca.models` — mesmo
padrão de `apps/pca/regras_situacao.py`/`apps/pca/importacao/parsers.py`:
recebe e devolve valores Python simples (`dict`/`list`/`Decimal`/`date`/
`str`), testável isoladamente, sem tocar o ORM. Não importa
`apps.pca.sei.extenso` — o `confere` de cada valor já vem calculado no JSON
de coleta (produzido pelo coletor); a única conversão de cifra
que este módulo faz é uma cópia privada mínima, só para comparar o valor já
confirmado contra `campos_atuais["valor_contratado"]` (o extenso
em si não entra nesta comparação, já foi conferido na coleta).

`propor()` é a única função pública, junto com a dataclass `Proposta`. Os 6
campos que `Proposta.alteracoes` pode conter são exatamente os do bloco de
execução contratual do `Processo` (`apps/pca/models.py` linhas
291-327): `data_assinatura_contrato`, `numero_instrumento_contratual`,
`instrumento_contratual`, `valor_contratado`, `data_recebimento_gelic`
(`situacao_sei` saiu). Nenhum outro campo é tocado — item, área, objeto,
justificativa, valores planejados, prazos e tipo são governados pelo PCA,
nunca pelo SEI (§4.4 da spec).

Nunca lança exceção para dado ausente/malformado — todo campo é lido com
`.get()`/checagem de tipo antes de comparar; degrada sempre para pendência
(do registro de ameaças da Fase 32).
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import date as _date
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re

from django.core.exceptions import ValidationError
from django.utils import timezone as django_timezone

from apps.pca.validators import validar_digitos_cnpj

# --- Instrumentos considerados no §4.1 (apostilamento fica de fora desta
# lista — entra só na disputa de valor do passo 6) ------------------------
_TIPOS_INSTRUMENTO_CONTRATACAO = (
    "contrato",
    "termo_aditivo",
    "ordem_fornecimento",
    "ata_rp",
)

# --- Subconjuntos usados pelo passo 5b (Fase 33) ------
# Razão social/CNPJ/modalidade/nº da contratação: só contrato, ordem de
# fornecimento e ata de registro de preços preenchem — termo aditivo nunca
# ("termos aditivos e apostilamentos nunca alteram modalidade, nº
# da contratação, razão social ou CNPJ já vindos do contrato").
_TIPOS_INSTRUMENTO_PRINCIPAL = ("contrato", "ordem_fornecimento", "ata_rp")

# Vigência: só contrato (`vigencia`) e termo aditivo (`prorrogacao`) —
# ordem de fornecimento/ata de registro de preços/apostilamento nunca.
_TIPOS_INSTRUMENTO_VIGENCIA = ("contrato", "termo_aditivo")

# --- Fase 37, M04 — mapeia o vocabulário do coletor
# (`extracao.py:752`, sempre "termo_aditivo") para o `TipoEventoFinanceiro.
# choices` do model ("aditivo") na fronteira de `serie_valores`, antes de
# `sincronizar()` gravar — nunca depender de `full_clean()` para rejeitar
# silenciosamente o que o coletor produz. Dict extensível (`.get(x, x)`),
# não `if/elif` solto.
_MAPA_TIPO_SERIE = {"termo_aditivo": "aditivo"}

_MODALIDADE_NORMALIZADO_PARA_ROTULO = {
    "adesao a arp": "Adesão a ARP",
    "concorrencia": "Concorrência",
    "credenciamento": "Credenciamento",
    "dispensa com disputa": "Dispensa Com Disputa",
    "dispensa sem disputa": "Dispensa Sem Disputa",
    "inexigibilidade": "Inexigibilidade",
    "pregao eletronico": "Pregão Eletrônico",
}

_TIPO_PARA_ROTULO_CATALOGO = {
    "contrato": "Contrato",
    "termo_aditivo": "Termo Aditivo",
    "ordem_fornecimento": "Ordem de Fornecimento",
    "ata_rp": "Ata de Registro de Preços",
}

_TIPO_PARA_ROTULO_EVIDENCIA = dict(
    _TIPO_PARA_ROTULO_CATALOGO, apostilamento="Termo de Apostilamento"
)

_RE_CIFRA = re.compile(r"(?:R\$\s*)?(\d{1,3}(?:\.\d{3})*,\d{2})")

# --- Debug robo-valor-contratado-item64 (20/10/2026) -----------------------
# Valor mensal/anual de contrato/aditivo nunca é o valor contratado (o global
# depende da vigência) — mesma regra que já aplicava ao apostilamento.
_PERIODICIDADES_NAO_GLOBAIS = ("mensal", "anual")

# Molde dominante do apostilamento ("Valor (atual) do contrato: R$ X ...
# Novo valor do contrato: R$ Y") — conta como global quando o trecho não
# traz nenhuma marca de período (o `_periodicidade_de` da extração só vê
# "mensal"/"anual" literais; "mensais", "ao mês", "ao ano" passariam).
_RE_VALOR_DO_CONTRATO = re.compile(r"\bvalor\s+do\s+contrato\b", re.I)
_RE_MARCA_DE_PERIODO = re.compile(
    r"mensa(?:l|is)\b|anua(?:l|is)\b|\b(?:ao|por)\s+(?:m[eê]s|ano)\b", re.I
)


@dataclass(frozen=True)
class Proposta:
    """Resultado de `propor()` para um item do PCA — só o que muda de fato.

    `alteracoes`: `{campo: (antes, depois)}`, só campos que realmente mudam.
    `evidencias`: frases prontas para a timeline (uma por fato novo
    confirmado). `pendencias`: pares `(chave_estável, texto)` — a chave
    nunca inclui o texto, só o identificador (§4.5). `erro`: preenchido só
    quando a coleta inteira do item falhou (passo 9).
    `instrumento_assinado_por_ambos`: `True` quando o passo 3 encontrou um
    instrumento de contratação (documento HTML, mencionando o CFC, tipo do
    §4.1) assinado tanto pelo CFC quanto pelo contratado — independente de
    `data_assinatura_contrato` estar ou não em `alteracoes` (o PCA pode já
    ter a mesma data de uma execução anterior). Decisão do usuário em
    18/09/2026 (exceção do §5 da spec): `aplicador.aplicar()` usa este sinal
    para sobrepor a guarda de `transicao_manual` só quando a assinatura de
    ambas as partes está confirmada.

    `serie_valores` (Fase 35): lista de `{"protocolo", "tipo",
    "data", "valor", "periodicidade", "natureza"}`, um item por documento
    com valor (contrato/aditivo/apostilamento qualificado ou não), em ordem
    cronológica — nunca gravado no banco, só no JSON de execução
    (`execucoes/<carimbo>.json`, campo `series`), para a futura fase de
    fluxo de caixa.
    """

    item_pca: int
    exercicio: int
    processo_principal: str | None
    alteracoes: dict = field(default_factory=dict)
    evidencias: list = field(default_factory=list)
    pendencias: list = field(default_factory=list)
    erro: str | None = None
    instrumento_assinado_por_ambos: bool = False
    serie_valores: list = field(default_factory=list)


def _normalizar_nome(nome: str | None) -> str:
    """Mesmo algoritmo de `apps.catalogo.utils.normalizar_nome`, reimplementado
    aqui porque `regras.py` é módulo puro e não pode importar `apps.catalogo`."""
    return (
        unicodedata.normalize("NFKD", nome or "")
        .encode("ascii", "ignore")
        .decode()
        .lower()
        .strip()
    )


def _parse_data_hora(texto: str | None) -> datetime | None:
    if not texto:
        return None
    try:
        return datetime.strptime(texto, "%d/%m/%Y %H:%M")
    except (ValueError, TypeError):
        return None


def unidade_atual(
    marcos: dict, primeiro: dict | None = None
) -> tuple[str, datetime | None]:
    """Última localização do processo no SEI (substitui a regra da quick): a unidade de DESTINO da linha "Processo remetido pela unidade X" mais
    recente do histórico — `marcos["ultima_remessa"]`, produzido por `coletor.SEI._marcos`.
    Nunca a lista de unidades por onde tramitou.

    A regra anterior (oy2) lia o marco de "Processo recebido na unidade" mais
    recente e tinha dois defeitos: (1) esse evento só aparece quando alguém ABRE o processo
    na unidade — nem toda unidade que recebe abre; (2) `_marcos` guardava só a PRIMEIRA
    ocorrência dele por unidade, então um processo que volta a uma unidade já visitada
    nunca era visto de volta por essa chave. "Remetido" é o evento que efetivamente move o
    processo, e `ultima_remessa` reflete sempre a remessa mais recente, em qualquer unidade
    — sem essa limitação.

    Sem nenhuma remessa utilizável (`marcos.get("ultima_remessa")` ausente/sem
    `unidade`), cai no fallback `primeiro` (a chamadora passa `marcos["primeiro"]` — a
    linha mais antiga do histórico, a unidade que GEROU o processo, nunca `marcos["ultimo"]`
    — não é mais "onde chegou por último no andamento genérico", é "quem abriu"). Sem
    `primeiro` ou sem `primeiro.get("unidade")`: `("", None)`.

    Só lê a chave `ultima_remessa` de `marcos` — as demais chaves (a lista de unidades
    visitadas, os fechamentos por unidade etc.) continuam existindo, usadas por outras
    regras (ex.: `recebimento_gelic_delic`), só não por esta função.

    Nunca lança exceção para dado ausente/malformado (mesma disciplina do resto do
    módulo)."""
    remessa = marcos.get("ultima_remessa")
    if remessa and remessa.get("unidade"):
        dt_remessa = _parse_data_hora(remessa.get("data_hora"))
        if dt_remessa is not None:
            dt_remessa = django_timezone.make_aware(dt_remessa)
        return (remessa["unidade"], dt_remessa)

    if not primeiro or not primeiro.get("unidade"):
        return ("", None)
    dt_fallback = _parse_data_hora(primeiro.get("data_hora"))
    if dt_fallback is not None:
        dt_fallback = django_timezone.make_aware(dt_fallback)
    return (primeiro["unidade"], dt_fallback)


def _parse_data_iso(valor) -> _date | None:
    """Aceita tanto `date` (produção — `extrair_vigencia`/`extrair_
    prorrogacao` devolvem `date` direto, sem round-trip por JSON antes de
    `propor()`) quanto string ISO `AAAA-MM-DD` (fixtures de teste, que
    passam por `json.load`, incapaz de preservar `date`)."""
    if valor is None:
        return None
    if isinstance(valor, _date):
        return valor
    try:
        return _date.fromisoformat(valor)
    except (TypeError, ValueError):
        return None


def _mais_recente_documento(pares: list[tuple[str | None, dict]]) -> dict | None:
    """`documento` de `ultima_assinatura` mais recente entre `pares` —
    mesmo critério `max(..., key=_parse_data_hora(...))` do passo 3.
    `None` quando `pares` está vazio."""
    if not pares:
        return None
    return max(
        pares,
        key=lambda par: _parse_data_hora(par[1].get("ultima_assinatura")) or datetime.min,
    )[1]


def _lista_portugues(itens: list[str]) -> str:
    """"05/2026", "05/2026 e 06/2026", "05/2026, 06/2026 e 07/2026" —
    lista em português com "e" antes do último item."""
    if not itens:
        return ""
    if len(itens) == 1:
        return itens[0]
    return ", ".join(itens[:-1]) + f" e {itens[-1]}"


def _cifra_para_decimal(texto: str | None) -> Decimal | None:
    """Cópia privada mínima do parser de cifra de `apps.pca.sei.extenso` —
    `regras.py` não importa aquele módulo (ver docstring do arquivo)."""
    if not texto:
        return None
    encontrado = _RE_CIFRA.search(texto)
    if not encontrado:
        return None
    bruto = encontrado.group(1).replace(".", "").replace(",", ".")
    try:
        return Decimal(bruto).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def _apostilamento_entra_na_disputa(apost: dict | None) -> bool:
    """`True` só quando o apostilamento é reajuste/repactuação, com o valor
    novo conferido (cifra × extenso) e periodicidade global — explícita
    (`periodicidade == "global"`) ou, na ausência dela, confirmada pela
    âncora "valor global"/"valor total" no `trecho` casado (Fase
    35) ou pela âncora "valor do contrato" sem nenhuma marca de período no
    trecho (debug robo-valor-contratado-item64: o 1º termo do item 64,
    "Novo valor do contrato: R$ 82.744,93", e o mesmo molde em outros 14
    itens). Mensal/anual sem essa âncora nunca entra — fica pendência
    `apostilamento_sem_global` (passo 6)."""
    if apost is None:
        return False
    if apost.get("natureza") not in ("reajuste", "repactuacao"):
        return False
    if (apost.get("valor_novo") or {}).get("confere") is not True:
        return False
    periodicidade = apost.get("periodicidade")
    if periodicidade == "global":
        return True
    if periodicidade is None:
        trecho = apost.get("trecho") or ""
        baixa = trecho.casefold()
        if "valor global" in baixa or "valor total" in baixa:
            return True
        return bool(_RE_VALOR_DO_CONTRATO.search(trecho)) and not _RE_MARCA_DE_PERIODO.search(
            trecho
        )
    return False


def _assinatura_suficiente(documento: dict) -> bool:
    """§4.1/§4.3 da spec: só documento assinado disputa `valor_contratado`,
    gera pendência de valor ou entra em `serie_valores` — apostilamento é
    ato unilateral (basta o CFC); contrato, aditivo, OF e ata exigem CFC e
    contratado. Minuta sem assinatura nunca conta (debug
    robo-valor-contratado-item64: o 2º termo do item 64, ainda sem
    assinatura, já gerava pendência e disputaria o valor quando lido)."""
    if documento.get("tipo") == "apostilamento":
        return bool(documento.get("assinado_cfc"))
    return bool(documento.get("assinado_cfc") and documento.get("assinado_externo"))


def _pendencia_valor_nao_gravavel(documento: dict) -> tuple[str, str] | None:
    """Pendência do passo 6 quando o `valor` conferido de um contrato/
    aditivo/OF/ata não pode virar `valor_contratado`, ou `None` quando pode:

    - valores por item, sem global único (`valor["por_itens"]`, decisão do
      usuário de 20/10/2026, item 18) → `valor_por_itens:<protocolo>`;
    - valor só mensal/anual (debug robo-valor-contratado-item64) →
      `valor_sem_global:<protocolo>`.

    O documento continua contando para ORDENAR ("vale o de assinatura mais
    recente", §4.3.2) — quando é ele o mais recente, nada é gravado e a
    pendência aparece; já superado por outro documento, não gera nada.
    Apostilamento devolve sempre `None` (já governado por
    `_apostilamento_entra_na_disputa`)."""
    if documento.get("tipo") == "apostilamento":
        return None
    valor = _valor_efetivo(documento)
    if valor is None:
        return None
    if valor.get("por_itens"):
        return _pendencia_valor_por_itens(documento, valor)
    if valor.get("periodicidade") in _PERIODICIDADES_NAO_GLOBAIS:
        return _pendencia_valor_sem_global(documento, valor)
    return None


def _pendencia_valor_sem_global(documento: dict, valor: dict) -> tuple[str, str]:
    """Pendência do passo 6 quando o documento MAIS RECENTE com valor só traz
    valor mensal/anual — `valor_contratado` não é atualizado (nem cai para
    um documento anterior); a pessoa confere."""
    protocolo = documento.get("protocolo") or "?"
    return (
        f"valor_sem_global:{protocolo}",
        f"Instrumento {protocolo} (o mais recente com valor) traz só o valor "
        f"{valor.get('periodicidade')} de R$ {valor.get('cifra') or '?'}, sem valor "
        "total/global — valor contratado não atualizado; conferir manualmente.",
    )


def _pendencia_valor_por_itens(documento: dict, valor: dict) -> tuple[str, str]:
    """Pendência do passo 6 quando o documento MAIS RECENTE com valor traz um
    valor por item e nenhum valor global único (decisão do usuário,
    20/10/2026 — item 18, Contrato nº 39/2026) — `valor_contratado` não é
    atualizado; a pessoa preenche à mão. O texto lista o valor lido de cada
    item, para conferência."""
    protocolo = documento.get("protocolo") or "?"
    itens = "; ".join(
        f"{item.get('rotulo') or '?'} R$ {item.get('cifra') or '?'}"
        + ("" if item.get("confere") is True else " (extenso não confere)")
        for item in valor.get("por_itens") or []
    )
    return (
        f"valor_por_itens:{protocolo}",
        f"Instrumento {protocolo} (o mais recente com valor) traz valores por item "
        f"({itens}), sem valor global único — valor contratado não atualizado; "
        "preencher manualmente.",
    )


def motivo_fora_da_serie(documento: dict) -> str:
    """Uma frase curta (cabe no `history_change_reason`, 100 caracteres,
    junto do prefixo do comando) dizendo por que um documento coletado NÃO
    entra em `Proposta.serie_valores` pelas regras atuais — usada por
    `sei_corrigir_eventos` para justificar a exclusão de um
    `EventoFinanceiro` gravado por regras antigas (debug
    robo-valor-contratado-item64). Puro; nunca lança exceção. Os motivos
    que dependem do item inteiro (contrato em PDF preterido pelo HTML,
    cópia em PDF de aditivo já lido em HTML) caem na frase genérica."""
    tipo = documento.get("tipo")
    if documento.get("conteudo") == "cancelado" or documento.get("cancelado"):
        return "documento cancelado no SEI"
    if not _assinatura_suficiente(documento):
        if tipo == "apostilamento":
            return "apostilamento sem assinatura do CFC (minuta)"
        cfc = bool(documento.get("assinado_cfc"))
        externo = bool(documento.get("assinado_externo"))
        if not cfc and not externo:
            return "documento sem nenhuma assinatura (minuta)"
        if cfc:
            return "assinado só pelo CFC — falta a assinatura do contratado"
        return "assinado só pelo contratado — falta a assinatura do CFC"
    if tipo == "apostilamento":
        if documento.get("apostilamento") is None:
            return "apostilamento sem cláusula de valor lida"
        if not _apostilamento_entra_na_disputa(documento.get("apostilamento")):
            return "apostilamento sem valor global confirmado"
    else:
        valor = documento.get("valor") or {}
        if valor.get("confere") is not True:
            return "valor do documento não lido ou não confere (cifra × extenso)"
        if valor.get("por_itens"):
            return "valores por item, sem valor global único — preencher à mão"
    return "fora da série de valores pelas regras atuais"


def _valor_efetivo(documento: dict) -> dict | None:
    """Valor que de fato disputa `valor_contratado` e alimenta
    `serie_valores` (Fase 37, M03): para `tipo ==
    "apostilamento"`, só o `valor_novo` do apostilamento quando
    `_apostilamento_entra_na_disputa` é `True`, senão `None`; para os demais
    tipos, `documento.get("valor")` — mas só quando `confere is True`
    (cifra × extenso conferidos na coleta, mesma disciplina que
    `_apostilamento_entra_na_disputa` já aplica ao apostilamento). Um valor
    com `confere=False`/ausente nunca disputa `valor_contratado` nem entra
    em `serie_valores` — fica pendência, nunca contamina o dado."""
    if documento.get("tipo") == "apostilamento":
        apost = documento.get("apostilamento")
        if _apostilamento_entra_na_disputa(apost):
            return apost.get("valor_novo")
        return None
    valor = documento.get("valor")
    if (valor or {}).get("confere") is not True:
        return None
    return valor


def _fmt_data(valor) -> str:
    if valor is None:
        return "vazio"
    if isinstance(valor, datetime):
        valor = valor.date()
    return valor.strftime("%d/%m/%Y")


def _fmt_valor(valor: Decimal | None) -> str:
    if valor is None:
        return "vazio"
    bruto = f"{valor:,.2f}"
    bruto = bruto.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {bruto}"


def propor(
    *, item_pca: int, exercicio: int, campos_atuais: dict, processos_coletados: list[dict]
) -> Proposta:
    """Deriva uma `Proposta` a partir da coleta SEI de um item (todos os
    seus números) e do retrato atual dos campos do `Processo` no PCA.

    Implementa, nesta ordem, os 9 passos do §4 da spec
    (documento interno de desenho):
    1. sem nenhum processo coletado → pendência `sem_numero_sei`;
    2. processo com `resultado != "ok"` → pendência `nao_encontrado:<numero>`;
    3. instrumento relevante + pendência `unilateral:<protocolo>`;
    4. processo principal;
    5. campos derivados do instrumento vencedor (data, número, tipo);
    6. valor contratado (cifra × extenso já conferidos na coleta);
    7. data de recebimento no Gelic, do processo principal;
    8. (removido na situação do SEI não existe mais);
    9. `erro` só quando TODOS os processos vieram com `resultado == "erro"`.
    """
    if not processos_coletados:
        return Proposta(
            item_pca=item_pca,
            exercicio=exercicio,
            processo_principal=None,
            pendencias=[
                (
                    "sem_numero_sei",
                    "Item ativo sem nenhum número de processo SEI cadastrado.",
                )
            ],
        )

    if all(p.get("resultado") == "erro" for p in processos_coletados):
        return Proposta(
            item_pca=item_pca,
            exercicio=exercicio,
            processo_principal=None,
            erro="falha ao coletar todos os números SEI do item",
        )

    pendencias: list[tuple[str, str]] = []
    evidencias: list[str] = []
    alteracoes: dict = {}

    # --- passo 2 ------------------------------------------------------
    processos_ok = [p for p in processos_coletados if p.get("resultado") == "ok"]
    for processo in processos_coletados:
        if processo.get("resultado") != "ok":
            numero = processo.get("numero") or "?"
            pendencias.append(
                (
                    f"nao_encontrado:{numero}",
                    f"Processo SEI {numero} não encontrado ou sem acesso.",
                )
            )

    # --- passo 3: candidatos ao instrumento + unilaterais ---------------
    # Um PDF externo "Contrato..." lido com sucesso
    # (`conteudo == "pdf"`) entra na MESMA disputa de um HTML — só que em
    # `candidatos_pdf`, nunca em `candidatos_reais` (a precedência do HTML
    # nativo nunca é decidida por data, ver passo abaixo). Quick
    # Essa exceção fica RESTRITA a `tipo == "contrato"` — um
    # Termo Aditivo em PDF (o único outro tipo que o coletor baixa como
    # PDF) entra em `candidatos_reais` como um HTML entraria, disputando o
    # instrumento vencedor/vigência/valor POR DATA com qualquer HTML do
    # item (pode vencer mesmo havendo HTML).
    candidatos_reais: list[tuple[str | None, dict]] = []
    candidatos_pdf: list[tuple[str | None, dict]] = []
    for processo in processos_ok:
        numero_processo = processo.get("numero")
        for documento in processo.get("documentos_contratuais") or []:
            tipo = documento.get("tipo")
            conteudo = documento.get("conteudo")
            if conteudo not in ("html", "pdf"):
                continue
            base_valida = (
                not documento.get("cancelado", False)
                and documento.get("menciona_cfc")
                and tipo in _TIPOS_INSTRUMENTO_CONTRATACAO
            )
            if not base_valida:
                continue
            if documento.get("assinado_cfc") and documento.get("assinado_externo"):
                if conteudo == "pdf" and tipo == "contrato":
                    candidatos_pdf.append((numero_processo, documento))
                else:
                    candidatos_reais.append((numero_processo, documento))
            elif documento.get("assinado_cfc") and not documento.get("assinado_externo"):
                protocolo = documento.get("protocolo") or "?"
                pendencias.append(
                    (
                        f"unilateral:{protocolo}",
                        f"Instrumento {protocolo} assinado só pelo CFC; "
                        "conferir assinatura do contratado.",
                    )
                )

    # `candidatos_reais` truthy deixa de ser sinônimo de
    # "um HTML venceu" (agora pode ser truthy só por um Termo Aditivo em
    # PDF, sem HTML nenhum no item) — `html_qualificou` isola o sinal
    # original, usado nos passos 6/serie_valores abaixo para restringir a
    # exclusão do Contrato em PDF (fallback-only) ao caso em que de fato
    # existe um HTML concorrente.
    html_qualificou = any(d.get("conteudo") == "html" for _, d in candidatos_reais)

    instrumento_vencedor: dict | None = None
    processo_do_instrumento: str | None = None
    if candidatos_reais:
        processo_do_instrumento, instrumento_vencedor = max(
            candidatos_reais,
            key=lambda par: _parse_data_hora(par[1].get("ultima_assinatura")) or datetime.min,
        )
    elif candidatos_pdf:
        # Fallback — só considerado quando NENHUM HTML qualificou no item;
        # a precedência do HTML nativo nunca é reaberta por data (ver
        # `<behavior>` do plano, 2º caso).
        processo_do_instrumento, instrumento_vencedor = max(
            candidatos_pdf,
            key=lambda par: _parse_data_hora(par[1].get("ultima_assinatura")) or datetime.min,
        )

    # Contratado/procedência/vigência (passo 5b) seguem o mesmo vencedor:
    # HTML quando há, PDF só como fallback — nunca uma mistura dos dois.
    candidatos_para_secundarios = candidatos_reais or candidatos_pdf

    # --- vários contratos distintos no mesmo item (18/09/2026) --
    # Mais de um documento tipo "contrato" assinado por ambos com CNPJs
    # diferentes (caso real: item 10, contratos 05/06/07-2026): data de
    # assinatura/situação/nº/tipo do instrumento continuam vindo do mais
    # recente (passo 5, inalterado); modalidade/nº da contratação também
    # (passo 5b, instrumento_principal); valor_contratado passa a ser a
    # SOMA de cada contrato distinto (cada um com seu próprio encadeamento
    # de aditivos/apostilamentos); razão social/CNPJ não são gravados —
    # pendência `multiplos_contratados:<protocolos>` no lugar.
    contratos_no_item = [d for _, d in candidatos_reais if d.get("tipo") == "contrato"]
    cnpjs_contratos_distintos = {
        (d.get("contratado") or {}).get("cnpj")
        for d in contratos_no_item
        if (d.get("contratado") or {}).get("cnpj")
    }
    multiplos_contratos_distintos = len(cnpjs_contratos_distintos) >= 2

    # --- passo 4: processo principal ------------------------------------
    if processo_do_instrumento is not None:
        processo_principal = processo_do_instrumento
    elif processos_ok:
        processo_principal = max(
            processos_ok,
            key=lambda p: _parse_data_hora(
                (
                    ((p.get("andamentos") or {}).get("marcos") or {}).get("primeiro")
                    or {}
                ).get("data_hora")
            )
            or datetime.min,
        ).get("numero")
    else:
        processo_principal = None

    # --- passo 5: campos derivados do instrumento vencedor --------------
    if instrumento_vencedor is not None:
        protocolo = instrumento_vencedor.get("protocolo") or "?"
        tipo = instrumento_vencedor.get("tipo")
        numero_no_corpo = instrumento_vencedor.get("numero_no_corpo")
        rotulo_evidencia = _TIPO_PARA_ROTULO_EVIDENCIA.get(tipo, tipo or "Instrumento")
        descricao = (
            f"{rotulo_evidencia} {numero_no_corpo}" if numero_no_corpo else rotulo_evidencia
        )
        assinaturas = instrumento_vencedor.get("assinaturas") or []
        data_cfc = next(
            (a.get("data") for a in assinaturas if a.get("papel") == "cfc"), None
        )
        data_externo = next(
            (a.get("data") for a in assinaturas if a.get("papel") == "externo"), None
        )
        evidencias.append(
            f"{descricao} (doc. {protocolo}) assinado pelo CFC em {data_cfc or '?'} "
            f"e pelo contratado em {data_externo or '?'}."
        )

        dt_assinatura = _parse_data_hora(instrumento_vencedor.get("ultima_assinatura"))
        if dt_assinatura is not None:
            depois_data = dt_assinatura.date()
            antes_data = campos_atuais.get("data_assinatura_contrato")
            if depois_data != antes_data:
                alteracoes["data_assinatura_contrato"] = (antes_data, depois_data)
                evidencias.append(
                    f"Data de assinatura: {_fmt_data(depois_data)} "
                    f"(antes: {_fmt_data(antes_data)})."
                )

        if numero_no_corpo is None:
            pendencias.append(
                (
                    f"sem_numero:{protocolo}",
                    f"Instrumento {protocolo} sem número identificado no corpo do documento.",
                )
            )
        else:
            antes_numero = campos_atuais.get("numero_instrumento_contratual")
            if numero_no_corpo != antes_numero:
                alteracoes["numero_instrumento_contratual"] = (antes_numero, numero_no_corpo)
                evidencias.append(
                    f"Nº do instrumento: {numero_no_corpo} "
                    f"(antes: {antes_numero or 'vazio'})."
                )

        if tipo not in _TIPO_PARA_ROTULO_CATALOGO:
            pendencias.append(
                (
                    f"tipo_fora_catalogo:{tipo}",
                    f"Instrumento {protocolo} tem tipo '{tipo}', fora do catálogo "
                    "de instrumentos.",
                )
            )
        else:
            rotulo_canonico = _TIPO_PARA_ROTULO_CATALOGO[tipo]
            antes_normalizado = campos_atuais.get("instrumento_contratual_nome_normalizado")
            if _normalizar_nome(rotulo_canonico) != (antes_normalizado or ""):
                alteracoes["instrumento_contratual"] = (antes_normalizado, rotulo_canonico)
    else:
        # Sem instrumento vencedor em nenhum processo do item: um documento
        # contratual não lido (externo, PDF) pode ser o instrumento perdido
        # — §7 "Documento externo (PDF): ... se for o único instrumento,
        # pendência sem_acesso_documento". Cancelados nunca entram aqui.
        # `pdf_outro_orgao` (PDF "Contrato..." de OUTRO
        # órgão, já descartado pelo filtro de segurança do coletor) também
        # nunca entra — descarte silencioso, sem pendência nenhuma.
        for processo in processos_ok:
            for documento in processo.get("documentos_contratuais") or []:
                conteudo = documento.get("conteudo")
                protocolo = documento.get("protocolo")
                if conteudo not in ("html", "cancelado", "pdf_outro_orgao") and protocolo:
                    pendencias.append(
                        (
                            f"sem_acesso_documento:{protocolo}",
                            f"Documento {protocolo} não pôde ser lido (conteúdo externo); "
                            "conferir manualmente se é o instrumento de contratação.",
                        )
                    )

    # --- passo 5b: contratado/procedência/vigência --
    # Precedência do usuário: contrato preenche tudo; termo aditivo só
    # atualiza razão/CNPJ quando o contrato não trouxe, e nunca atualiza
    # modalidade/nº da contratação; apostilamento não entra em nenhum dos
    # três blocos abaixo (já está fora de `candidatos_reais`/`candidatos_
    # pdf`). lê `candidatos_para_secundarios` (HTML
    # quando há; PDF só como fallback, mesmo vencedor do passo 3) em vez de
    # `candidatos_reais` puro — contratado/procedência/vigência também vêm
    # do PDF quando ele é quem venceu.
    instrumento_principal = _mais_recente_documento(
        [(n, d) for n, d in candidatos_para_secundarios if d.get("tipo") in _TIPOS_INSTRUMENTO_PRINCIPAL]
    )

    # --- contratado (razão social/CNPJ) ---------------------------------
    if multiplos_contratos_distintos:
        protocolos = ",".join(d.get("protocolo") or "?" for d in contratos_no_item)
        numeros_contratos = [d.get("numero_no_corpo") or "?" for d in contratos_no_item]
        pendencias.append(
            (
                f"multiplos_contratados:{protocolos}",
                f"{len(contratos_no_item)} contratos distintos "
                f"({_lista_portugues(numeros_contratos)}): razão social e CNPJ "
                "não preenchidos automaticamente.",
            )
        )
    else:
        fonte_contratado = None
        if instrumento_principal is not None:
            contratado_principal = instrumento_principal.get("contratado") or {}
            if contratado_principal.get("razao_social") or contratado_principal.get("cnpj"):
                fonte_contratado = instrumento_principal
        if fonte_contratado is None:
            aditivo_mais_recente = _mais_recente_documento(
                [(n, d) for n, d in candidatos_reais if d.get("tipo") == "termo_aditivo"]
            )
            if aditivo_mais_recente is not None and aditivo_mais_recente.get("contratado"):
                fonte_contratado = aditivo_mais_recente

        if fonte_contratado is not None:
            protocolo = fonte_contratado.get("protocolo") or "?"
            contratado = fonte_contratado.get("contratado") or {}
            cnpj = contratado.get("cnpj")
            razao = contratado.get("razao_social")
            mudou_contratado = False
            if cnpj:
                try:
                    validar_digitos_cnpj(cnpj)
                except ValidationError:
                    pendencias.append(
                        (
                            f"contratado_invalido:{protocolo}",
                            f"CNPJ do contratado ({cnpj}) não passa na validação de dígitos.",
                        )
                    )
                else:
                    antes_cnpj = campos_atuais.get("fornecedor_cnpj")
                    if cnpj != antes_cnpj:
                        alteracoes["fornecedor_cnpj"] = (antes_cnpj, cnpj)
                        mudou_contratado = True
                    if razao:
                        antes_razao = campos_atuais.get("fornecedor_razao_social")
                        if razao != antes_razao:
                            alteracoes["fornecedor_razao_social"] = (antes_razao, razao)
                            mudou_contratado = True
            elif razao:
                antes_razao = campos_atuais.get("fornecedor_razao_social")
                if razao != antes_razao:
                    alteracoes["fornecedor_razao_social"] = (antes_razao, razao)
                    mudou_contratado = True
            if mudou_contratado:
                # Achado periferia nº 5 (QA 30/09/2026): quando só o CNPJ
                # muda e a razão social não foi extraída, `razao` é `None`
                # — a evidência nunca pode interpolar a string "None" no
                # lugar do nome (acompanhamentos reais 887/906/915/1046).
                if razao:
                    evidencias.append(
                        f"Contratado: {razao} (CNPJ {cnpj or 'pessoa física'})."
                    )
                else:
                    evidencias.append(f"Contratado: CNPJ {cnpj or 'pessoa física'}.")

    # --- procedência (modalidade + nº da contratação) --------------------
    # `instrumento_principal.get("procedencia")` distingue a chave AUSENTE
    # (documento de antes da Fase 33 — coleta antiga, sem os
    # leitores novos, nenhuma pendência nova) da chave PRESENTE com
    # `modalidade_catalogo=None` (coleta atual, extração rodou e não achou
    # nada — pendência de verdade). Em produção, `coletor.py::ler_documento`
    # sempre anexa esta chave a todo documento HTML — só
    # fixtures anteriores a essa mudança ficam sem ela.
    if instrumento_principal is not None:
        procedencia = instrumento_principal.get("procedencia")
        if procedencia is not None:
            protocolo = instrumento_principal.get("protocolo") or "?"
            numero = procedencia.get("numero")
            modalidade_catalogo = procedencia.get("modalidade_catalogo")
            modalidade_texto = procedencia.get("modalidade_texto")
            mudou_procedencia = False

            if numero:
                antes_numero = campos_atuais.get("numero_contratacao")
                if numero != antes_numero:
                    alteracoes["numero_contratacao"] = (antes_numero, numero)
                    mudou_procedencia = True

            if modalidade_catalogo:
                rotulo_modalidade = _MODALIDADE_NORMALIZADO_PARA_ROTULO.get(
                    modalidade_catalogo, modalidade_catalogo
                )
                antes_normalizado = campos_atuais.get("modalidade_nome_normalizado")
                if _normalizar_nome(rotulo_modalidade) != (antes_normalizado or ""):
                    alteracoes["modalidade"] = (antes_normalizado, rotulo_modalidade)
                    mudou_procedencia = True
            else:
                # Nunca "?" no texto: modalidade ausente
                # no instrumento (ex.: contrato em PDF sem a procedência,
                # item 58) é um caso diferente de modalidade lida mas fora
                # do catálogo.
                if modalidade_texto:
                    texto_pendencia = (
                        f"Modalidade \u201c{modalidade_texto}\u201d do instrumento {protocolo} "
                        "não corresponde a nenhuma modalidade do catálogo; preencher manualmente."
                    )
                else:
                    texto_pendencia = (
                        "Modalidade da contratação não encontrada no texto do instrumento "
                        f"{protocolo}; preencher manualmente."
                    )
                pendencias.append((f"modalidade_nao_mapeada:{protocolo}", texto_pendencia))

            if mudou_procedencia:
                modalidade_evidencia = modalidade_texto or modalidade_catalogo
                if modalidade_evidencia and numero:
                    evidencias.append(f"Procedência: {modalidade_evidencia} nº {numero}.")
                elif modalidade_evidencia:
                    evidencias.append(f"Procedência: {modalidade_evidencia}.")
                else:
                    evidencias.append(f"Procedência: nº da contratação {numero}.")

    # --- vigência ----------------------------------------------------------
    # Mesma distinção acima (chave ausente x chave presente vazia), agora
    # para `vigencia`/`prorrogacao`.
    instrumento_vigencia = _mais_recente_documento(
        [(n, d) for n, d in candidatos_para_secundarios if d.get("tipo") in _TIPOS_INSTRUMENTO_VIGENCIA]
    )
    if instrumento_vigencia is not None:
        tipo_vigencia = instrumento_vigencia.get("tipo")
        fonte_vigencia = (
            instrumento_vigencia.get("vigencia")
            if tipo_vigencia == "contrato"
            else instrumento_vigencia.get("prorrogacao")
        )
        if fonte_vigencia is not None:
            protocolo = instrumento_vigencia.get("protocolo") or "?"
            inicio_vigencia = _parse_data_iso(fonte_vigencia.get("inicio"))
            fim_vigencia = _parse_data_iso(fonte_vigencia.get("fim"))
            if inicio_vigencia is not None and fim_vigencia is not None:
                mudou_vigencia = False
                antes_inicio = campos_atuais.get("vigencia_inicio")
                if inicio_vigencia != antes_inicio:
                    alteracoes["vigencia_inicio"] = (antes_inicio, inicio_vigencia)
                    mudou_vigencia = True
                antes_fim = campos_atuais.get("vigencia_fim")
                if fim_vigencia != antes_fim:
                    alteracoes["vigencia_fim"] = (antes_fim, fim_vigencia)
                    mudou_vigencia = True
                if mudou_vigencia:
                    evidencias.append(
                        f"Vigência: {inicio_vigencia.strftime('%d/%m/%Y')} a "
                        f"{fim_vigencia.strftime('%d/%m/%Y')}."
                    )
            else:
                pendencias.append(
                    (
                        f"vigencia_nao_lida:{protocolo}",
                        f"Vigência do instrumento {protocolo} não pôde ser lida.",
                    )
                )

    # --- passo 6: valor contratado ----------------------
    # Um Contrato em PDF (`conteudo == "pdf" and tipo ==
    # "contrato"`) só disputa o valor quando NENHUM HTML venceu no item
    # (fallback-only, nunca decidido por data). a
    # condição usa `html_qualificou` (não mais `candidatos_reais` puro) —
    # um Termo Aditivo em PDF sem HTML concorrente não é mais excluído por
    # engano (ele já está em `candidatos_reais`, não cai nesta exclusão de
    # qualquer forma; a troca é para precisão de intenção, não muda
    # comportamento para esse tipo).
    #
    # Debug robo-valor-contratado-item64 (20/10/2026): só documento assinado
    # disputa (`_assinatura_suficiente`, §4.1/§4.3), e valor mensal/anual de
    # contrato/aditivo nunca vira `valor_contratado` — pendência
    # `valor_sem_global:<protocolo>` no lugar. O periódico continua na lista
    # só para ORDENAR ("vale o de assinatura mais recente", §4.3.2): quando é
    # ele o mais recente, nada é gravado — nunca cai para um documento
    # anterior, cujo valor já foi superado (achado do relatório de impacto:
    # itens 76/114 cairiam em leituras antigas erradas, 8/16/56/129 em
    # totais de anos atrás). Decisão do usuário (20/10/2026, item 18): o
    # mesmo vale para contrato com valores por item e sem global único —
    # pendência `valor_por_itens:<protocolo>`, preenchimento manual.
    documentos_com_valor = []
    for processo in processos_ok:
        for documento in processo.get("documentos_contratuais") or []:
            if (
                documento.get("conteudo") == "pdf"
                and documento.get("tipo") == "contrato"
                and html_qualificou
            ):
                continue
            if not _assinatura_suficiente(documento):
                continue
            if _valor_efetivo(documento) is not None:
                documentos_com_valor.append(documento)

    # Pendências/evidências de apostilamento: percorre TODOS os
    # apostilamentos do item, independente de qualificarem para a disputa,
    # ANTES de decidir `valor_contratado` — reajuste/repactuação com valor
    # que não confere vira `valor_nao_confere` (mesma chave já usada para
    # contrato/aditivo); reajuste/repactuação sem periodicidade global
    # confirmada vira `apostilamento_sem_global`; dotação/outro nunca
    # bloqueia nem gera pendência, só a evidência "sem efeito no valor".
    # Minuta sem assinatura do CFC fica de fora (debug
    # robo-valor-contratado-item64): ainda não é ato, não gera pendência.
    for processo in processos_ok:
        for documento in processo.get("documentos_contratuais") or []:
            if documento.get("tipo") != "apostilamento":
                continue
            if not _assinatura_suficiente(documento):
                continue
            apost = documento.get("apostilamento")
            if apost is None:
                continue
            protocolo = documento.get("protocolo") or "?"
            natureza = apost.get("natureza")
            if natureza in ("reajuste", "repactuacao"):
                valor_novo = apost.get("valor_novo") or {}
                if valor_novo.get("confere") is not True:
                    cifra = valor_novo.get("cifra") or "?"
                    extenso = valor_novo.get("extenso") or "?"
                    pendencias.append(
                        (
                            f"valor_nao_confere:{protocolo}",
                            f"Valor do instrumento {protocolo} não confere: "
                            f"cifra '{cifra}' × extenso '{extenso}'.",
                        )
                    )
                elif not _apostilamento_entra_na_disputa(apost):
                    periodicidade = apost.get("periodicidade") or "?"
                    pendencias.append(
                        (
                            f"apostilamento_sem_global:{protocolo}",
                            f"Apostilamento {protocolo}: reajuste {periodicidade}, "
                            "sem confirmação de valor global (fica para a fase de "
                            "fluxo de caixa).",
                        )
                    )
            elif natureza in ("dotacao", "outro"):
                evidencias.append(
                    f"Apostilamento {protocolo}: alteração de dotação, sem efeito "
                    "no valor."
                )

    atual_valor = campos_atuais.get("valor_contratado")
    if multiplos_contratos_distintos:
        # Cada contrato distinto tem seu próprio encadeamento de
        # aditivos/apostilamentos — agrupa por `numero_no_corpo` (a chave
        # que liga um contrato aos seus próprios aditivos/apostilamentos,
        # mesmo padrão do item 6/item 39) e soma o valor mais recente de
        # cada grupo, na ordem dos contratos distintos.
        grupos_valor: dict[str, list[dict]] = {}
        for documento in documentos_com_valor:
            chave_grupo = documento.get("numero_no_corpo") or documento.get("protocolo") or "?"
            grupos_valor.setdefault(chave_grupo, []).append(documento)

        soma_valor = Decimal("0.00")
        partes_evidencia = []
        algum_valor_valido = False
        # Debug robo-valor-contratado-item64: um contrato cujo documento mais
        # recente só tem valor mensal/anual (ou, decisão de 20/10/2026, só
        # valores por item) torna a soma inconfirmável — nada é gravado,
        # pendência `valor_sem_global`/`valor_por_itens` no lugar.
        soma_incompleta = False
        for numero_no_corpo in (d.get("numero_no_corpo") or "?" for d in contratos_no_item):
            docs_grupo = grupos_valor.get(numero_no_corpo) or []
            if not docs_grupo:
                continue
            docs_grupo.sort(
                key=lambda d: _parse_data_hora(d.get("ultima_assinatura")) or datetime.min,
                reverse=True,
            )
            pendencia_nao_gravavel = _pendencia_valor_nao_gravavel(docs_grupo[0])
            if pendencia_nao_gravavel is not None:
                pendencias.append(pendencia_nao_gravavel)
                soma_incompleta = True
                continue
            valor_info = _valor_efetivo(docs_grupo[0]) or {}
            if valor_info.get("confere") is True:
                valor_decimal = _cifra_para_decimal(valor_info.get("cifra"))
                if valor_decimal is not None:
                    soma_valor += valor_decimal
                    algum_valor_valido = True
                    partes_evidencia.append(f"{numero_no_corpo} ({_fmt_valor(valor_decimal)})")

        if algum_valor_valido and not soma_incompleta:
            if soma_valor != atual_valor:
                alteracoes["valor_contratado"] = (atual_valor, soma_valor)
            evidencias.append("Contratos distintos: " + ", ".join(partes_evidencia) + ".")
    elif documentos_com_valor:
        documentos_com_valor.sort(
            key=lambda d: _parse_data_hora(d.get("ultima_assinatura")) or datetime.min,
            reverse=True,
        )
        mais_recente = documentos_com_valor[0]
        valor_info = _valor_efetivo(mais_recente) or {}
        protocolo = mais_recente.get("protocolo") or "?"
        pendencia_nao_gravavel = _pendencia_valor_nao_gravavel(mais_recente)
        if pendencia_nao_gravavel is not None:
            pendencias.append(pendencia_nao_gravavel)
        elif valor_info.get("confere") is True:
            depois_valor = _cifra_para_decimal(valor_info.get("cifra"))
            if depois_valor is not None and depois_valor != atual_valor:
                alteracoes["valor_contratado"] = (atual_valor, depois_valor)
                # Evidência encadeada: só quando mais de um
                # documento contribuiu para o valor — cronológica ascendente,
                # rótulo por tipo ("contrato <protocolo>"/"aditivo
                # <protocolo>"/"apost. Nº"). Com 1 só documento, mantém o
                # formato antigo (antes/depois) — regressão dos itens
                # 1/3/6/10/15/16/39 preservada. Valor mensal/anual ou por
                # item (já superado) não entra na cadeia — não é valor global.
                cadeia = sorted(
                    (
                        d
                        for d in documentos_com_valor
                        if _pendencia_valor_nao_gravavel(d) is None
                    ),
                    key=lambda d: _parse_data_hora(d.get("ultima_assinatura")) or datetime.min,
                )
                if len(cadeia) > 1:
                    partes = []
                    indice_apostilamento = 0
                    for doc in cadeia:
                        tipo_doc = doc.get("tipo")
                        protocolo_doc = doc.get("protocolo") or "?"
                        valor_doc = _cifra_para_decimal(
                            (_valor_efetivo(doc) or {}).get("cifra")
                        )
                        if tipo_doc == "contrato":
                            rotulo = f"contrato {protocolo_doc}"
                        elif tipo_doc == "termo_aditivo":
                            rotulo = f"aditivo {protocolo_doc}"
                        elif tipo_doc == "apostilamento":
                            indice_apostilamento += 1
                            rotulo = f"apost. {indice_apostilamento}º"
                        else:
                            rotulo = f"{tipo_doc or 'instrumento'} {protocolo_doc}"
                        partes.append(f"{rotulo} {_fmt_valor(valor_doc)}")
                    evidencias.append(
                        f"Valor contratado: {_fmt_valor(depois_valor)} "
                        f"({' → '.join(partes)})."
                    )
                else:
                    evidencias.append(
                        f"Valor contratado: {_fmt_valor(depois_valor)} "
                        f"(antes: {_fmt_valor(atual_valor)})."
                    )
        else:
            cifra = valor_info.get("cifra") or "?"
            extenso = valor_info.get("extenso") or "?"
            pendencias.append(
                (
                    f"valor_nao_confere:{protocolo}",
                    f"Valor do instrumento {protocolo} não confere: "
                    f"cifra '{cifra}' × extenso '{extenso}'.",
                )
            )
    elif atual_valor is not None:
        pendencias.append(
            (
                "pca_nao_confirmado:valor_contratado",
                "PCA tem valor contratado preenchido, mas nenhum instrumento "
                "no SEI sustenta esse valor.",
            )
        )

    # --- passo 7: recebimento no Gelic, do processo principal -----------
    processo_principal_dict = next(
        (p for p in processos_ok if p.get("numero") == processo_principal), None
    )
    atual_recebimento = campos_atuais.get("data_recebimento_gelic")
    marco_recebimento = None
    if processo_principal_dict is not None:
        marcos_recebimento = (processo_principal_dict.get("andamentos") or {}).get("marcos", {})
        marco_recebimento = marcos_recebimento.get("recebimento_gelic_delic")
        # 29/09/2026 (decisão do usuário) — vale a PRIMEIRA entrada no Gelic/Delic no ano do PCA:
        # o processo SEI é reaproveitado a cada renovação e a primeira entrada de todas pode ser de
        # um ciclo antigo. Sem entrada no ano, fica a primeira de todas (histórico), que a regra de
        # situação ignora (recebimento de ano anterior não põe em tramitação).
        do_ano = [
            data_hora
            for data_hora in marcos_recebimento.get("recebimentos_gelic_delic") or []
            if (_dt := _parse_data_hora(data_hora)) is not None and _dt.year == exercicio
        ]
        if do_ano:
            marco_recebimento = {"data_hora": do_ano[0]}
    if marco_recebimento and marco_recebimento.get("data_hora"):
        dt_recebimento = _parse_data_hora(marco_recebimento["data_hora"])
        if dt_recebimento is not None:
            depois_recebimento = dt_recebimento.date()
            if depois_recebimento != atual_recebimento:
                alteracoes["data_recebimento_gelic"] = (atual_recebimento, depois_recebimento)
    elif atual_recebimento is not None:
        pendencias.append(
            (
                "pca_nao_confirmado:data_recebimento_gelic",
                "PCA tem recebimento no Gelic preenchido, mas o processo "
                "principal não confirma.",
            )
        )

    # --- passo 7b: unidade atual no SEI, do processo principal (quicks) — deriva de marcos já coletados, nunca gera
    # evidência na timeline (mesmo padrão sem evidência do passo 7).
    marcos_principal = (
        (processo_principal_dict or {}).get("andamentos") or {}
    ).get("marcos") or {}
    unidade_nova, desde_nova = unidade_atual(
        marcos_principal, marcos_principal.get("primeiro")
    )
    atual_unidade_sei = campos_atuais.get("unidade_sei_atual", "")
    atual_unidade_sei_desde = campos_atuais.get("unidade_sei_atual_desde")
    if unidade_nova != atual_unidade_sei or desde_nova != atual_unidade_sei_desde:
        alteracoes["unidade_sei_atual"] = (atual_unidade_sei, unidade_nova)
        alteracoes["unidade_sei_atual_desde"] = (atual_unidade_sei_desde, desde_nova)

    # --- passo 8 (situação do SEI) saiu na o campo foi
    # removido — ter ou não processo SEI é derivado do próprio nº SEI.

    # --- serie_valores (Fase 37 M03/M04): contrato/
    # aditivo com valor CONFERIDO (`_valor_efetivo` já recusa `confere` !=
    # True) + TODO apostilamento com `documento["apostilamento"]` presente
    # (qualificado para a disputa ou não) — nunca gravado no banco, só no
    # JSON de execução, até `sincronizar()` (`apps/pca/servicos/
    # eventos_financeiros.py`) persistir em `EventoFinanceiro`.
    serie_valores = []
    for processo in processos_ok:
        for documento in processo.get("documentos_contratuais") or []:
            # Mesma precedência do passo 6 —
            # só um Contrato em PDF é excluído quando algum HTML já venceu
            # o item; Termo Aditivo em PDF nunca é excluído por esta regra.
            if (
                documento.get("conteudo") == "pdf"
                and documento.get("tipo") == "contrato"
                and html_qualificou
            ):
                continue
            # Debug robo-valor-contratado-item64: minuta nunca vira evento
            # financeiro — mesma exigência de assinatura do passo 6.
            if not _assinatura_suficiente(documento):
                continue
            tipo_doc = documento.get("tipo")
            # Decisão do usuário (20/10/2026, item 18): valor de UM item de
            # um contrato com vários itens não é o global do instrumento —
            # nunca vira evento financeiro (o fluxo de caixa cai para o
            # valor contratado preenchido à mão).
            if tipo_doc != "apostilamento" and (documento.get("valor") or {}).get("por_itens"):
                continue
            apost = documento.get("apostilamento")
            eh_apostilamento_lido = tipo_doc == "apostilamento" and apost is not None
            valor_efetivo = _valor_efetivo(documento)
            if valor_efetivo is None and not eh_apostilamento_lido:
                continue
            dt_documento = _parse_data_hora(documento.get("ultima_assinatura"))
            valor_decimal = (
                _cifra_para_decimal(valor_efetivo.get("cifra"))
                if valor_efetivo is not None
                else None
            )
            if eh_apostilamento_lido:
                # Debug robo-valor-contratado-item64: apostilamento que
                # disputa o valor é global por definição — sem isso, um
                # "Novo valor do contrato" (periodicidade None) herdaria no
                # motor de fluxo a periodicidade do evento anterior (ex.: o
                # mensal do contrato) e seria rateado como mensal.
                periodicidade = apost.get("periodicidade") or (
                    "global" if _apostilamento_entra_na_disputa(apost) else None
                )
                natureza = apost.get("natureza")
                # M04 — a data-base extraída (`extracao.py::
                # _data_base_apostilamento`) é a âncora real de reajuste
                # (spec §2.2); sem ela, cai para a assinatura, como antes.
                data_base_apost = _parse_data_iso(apost.get("data_base"))
                data_entrada = data_base_apost or (
                    dt_documento.date() if dt_documento is not None else None
                )
            else:
                periodicidade = (documento.get("valor") or {}).get("periodicidade")
                natureza = None
                data_entrada = dt_documento.date() if dt_documento is not None else None
            serie_valores.append(
                {
                    "protocolo": documento.get("protocolo") or "?",
                    # M04 — o coletor sempre produz "termo_aditivo"
                    # (`extracao.py:752`); o model só aceita "aditivo"
                    # (`TipoEventoFinanceiro.choices`) — mapear na
                    # fronteira, nunca depender de `full_clean()` para
                    # rejeitar silenciosamente.
                    "tipo": _MAPA_TIPO_SERIE.get(tipo_doc, tipo_doc),
                    "data": data_entrada,
                    "valor": valor_decimal,
                    "periodicidade": periodicidade,
                    "natureza": natureza,
                    # spec §2.1/§8 — identifica a cadeia de contrato;
                    # nº citado no corpo do documento quando o coletor o
                    # extrai, senão o protocolo SEI do documento-base.
                    "instrumento": documento.get("numero_no_corpo")
                    or documento.get("protocolo")
                    or "",
                    # Chave temporária — nunca
                    # sobrevive ao `return` abaixo; só serve para o dedupe
                    # de cópia PDF/HTML logo a seguir.
                    "_html": documento.get("conteudo") == "html",
                }
            )

    # Um Termo Aditivo em PDF que seja cópia
    # assinada/escaneada de um aditivo já presente como HTML na série
    # (mesmo tipo/valor/instrumento) é descartado — a entrada HTML
    # permanece, a série nunca conta o mesmo evento financeiro duas vezes.
    chaves_html = {
        (e["tipo"], e["valor"], e["instrumento"]) for e in serie_valores if e["_html"]
    }
    serie_valores = [
        e
        for e in serie_valores
        if e["_html"] or (e["tipo"], e["valor"], e["instrumento"]) not in chaves_html
    ]
    for e in serie_valores:
        del e["_html"]

    serie_valores.sort(key=lambda entrada: entrada["data"] or _date.min)

    return Proposta(
        item_pca=item_pca,
        exercicio=exercicio,
        processo_principal=processo_principal,
        alteracoes=alteracoes,
        evidencias=evidencias,
        pendencias=pendencias,
        # `instrumento_vencedor` (passo 3) só é preenchido com um documento
        # onde `assinado_cfc` E `assinado_externo` são ambos `True` — os
        # candidatos assinados só pelo CFC viram pendência `unilateral:` e
        # nunca chegam a `candidatos_reais` (ver acima).
        instrumento_assinado_por_ambos=instrumento_vencedor is not None,
        serie_valores=serie_valores,
    )
