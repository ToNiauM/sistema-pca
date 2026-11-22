"""Módulo puro de derivação de `Processo.situacao` (Fase 17).

Sem nenhum import de `django.db.models` nem de `apps.pca.models` — mesmo
motivo de `apps/pca/importacao/parsers.py`: seguro para importar de dentro de
uma migração congelada (0023), testável isoladamente, sem tocar o ORM. As duas
funções recebem e devolvem os VALORES STRING dos enums `Estado`/`Situacao`
(não os objetos `Choices`), para não acoplar este módulo ao Django.

`situacao_por_eventos` é a regra VIVA: reage só a fatos
gravados (assinatura, recebimento no Gelic), nunca a "hoje" — nunca devolve
`"atrasado"`, porque a transição NO_PRAZO -> ATRASADO é correção de leitura,
nunca escrita automaticamente ("viradas puras de
calendário não geram evento").

`situacao_inicial` é a regra de BACKFILL/CRIAÇÃO: delega primeiro para
`situacao_por_eventos` (evento gravado tem precedência sobre calendário) e só
cai no fallback de `prazo_efetivo` vs. `hoje` quando não há evento algum.

emendada em 29/08/2026 (gap 1): o fallback de
calendário mede contra `prazo_efetivo = COALESCE(prazo_vigente,
prazo_entrega)`, a mesma identidade que `ProcessoQuerySet.para_listagem()`
usa para `atrasado`/`dias_atraso`/`situacao_efetiva` desde a Fase 11/17 — não
mais `prazo_entrega` cru.
"""


CONCLUIDO_OBRIGATORIO = "concluido"
CONCLUSAO_BLOQUEADA = "bloqueada"


def exigencia_do_contrato(
    *,
    ano_exercicio,
    tipo_nome_normalizado,
    vigencia_fim,
    renovacao_prevista,
    datas_assinatura,
):
    """Regra de renovação × vigência (decisão do usuário).

    O que se olha é SEMPRE contrato e termo aditivo — `datas_assinatura`
    traz só as datas desses dois instrumentos; termo de apostilamento nunca
    entra (só reajusta valor, não altera o instrumento contratual).

    Devolve `(exigencia, motivo)`:
    - `CONCLUIDO_OBRIGATORIO` — vigência termina depois de 31/12 do ano do
      PCA: não há termo aditivo previsto no ano, o item é concluído; OU o
      item renova no ano e já tem contrato/termo aditivo assinado no ano.
    - `CONCLUSAO_BLOQUEADA` — o item renova no ano (vigência termina dentro
      do ano do PCA, ou Renovação sem vigência informada) com renovação
      prevista e NÃO tem contrato/termo aditivo assinado no ano: não pode
      estar concluído.
    - `(None, None)` — a regra não se aplica (sem contrato a renovar no
      ano, renovação não prevista, vigência encerrada antes do ano).
    Vence qualquer transição manual."""
    from datetime import date

    if ano_exercicio is None:
        return None, None
    if vigencia_fim is not None and vigencia_fim > date(ano_exercicio, 12, 31):
        return (
            CONCLUIDO_OBRIGATORIO,
            f"contrato vigente até {vigencia_fim:%d/%m/%Y}, sem termo aditivo "
            f"previsto em {ano_exercicio}",
        )
    renova_no_ano = renovacao_prevista and (
        (vigencia_fim is not None and vigencia_fim.year == ano_exercicio)
        or (vigencia_fim is None and tipo_nome_normalizado == "renovacao")
    )
    if not renova_no_ano:
        return None, None
    assinadas_no_ano = sorted(
        d for d in datas_assinatura if d is not None and d.year == ano_exercicio
    )
    if assinadas_no_ano:
        return (
            CONCLUIDO_OBRIGATORIO,
            f"contrato ou termo aditivo assinado em {assinadas_no_ano[-1]:%d/%m/%Y}",
        )
    fim = (
        f"a vigência termina em {vigencia_fim:%d/%m/%Y}"
        if vigencia_fim is not None
        else "a vigência não está informada"
    )
    return (
        CONCLUSAO_BLOQUEADA,
        f"renovação no ano: {fim} e não há contrato ou termo aditivo "
        f"assinado em {ano_exercicio}",
    )


def situacao_por_eventos(
    *,
    tipo_nome_normalizado,
    data_assinatura_contrato,
    data_recebimento_gelic,
    exigencia=None,
    ano_exercicio=None,
):
    """Deriva a situação a partir de fatos gravados.

    29/09/2026 (decisão do usuário) — com `ano_exercicio`, o recebimento no Gelic só conta se for do
    ano do PCA: NC/RN que não tramitou no Gelic no ano N não está em tramitação (está no prazo ou
    atrasado), mesmo que o processo SEI — reaproveitado a cada renovação — tenha passado pelo Gelic
    em anos anteriores. Sem `ano_exercicio` (chamadas congeladas), qualquer data conta, como antes.

    - Tipo VIGENTE ⇒ `"concluido"` por natureza: um vigente nada
      precisa fazer no ano, independente de qualquer data.
    - `data_assinatura_contrato` preenchida ⇒ `"concluido"`: a
      assinatura conclui tanto Nova Contratação quanto Renovação.
    - `data_recebimento_gelic` preenchida ⇒ `"em_tramitacao"`: a
      entrega ao Gelic, mesmo fora do prazo, é a condição atual — a função
      nunca olha timing, nunca compara datas com "hoje".
    - `exigencia` (de `exigencia_do_contrato`) vem antes de
      tudo: `CONCLUIDO_OBRIGATORIO` conclui; `CONCLUSAO_BLOQUEADA` impede
      concluir (Vigente e assinatura antiga deixam de valer).
    - Nenhum fato gravado ⇒ `None`: sem alvo automático. NUNCA devolve
      `"atrasado"` sob nenhuma combinação de argumentos.
    """
    if (
        ano_exercicio is not None
        and data_recebimento_gelic is not None
        and data_recebimento_gelic.year < ano_exercicio
    ):
        data_recebimento_gelic = None
    if exigencia == CONCLUIDO_OBRIGATORIO:
        return "concluido"
    if exigencia == CONCLUSAO_BLOQUEADA:
        # Renovação sem contrato/aditivo no ano: nem Vigente nem assinatura
        # antiga concluem; o recebimento no Gelic só conta se for POSTERIOR
        # à última assinatura (o anterior é do ciclo passado).
        if data_recebimento_gelic is not None and (
            data_assinatura_contrato is None
            or data_recebimento_gelic > data_assinatura_contrato
        ):
            return "em_tramitacao"
        return None
    if tipo_nome_normalizado == "vigente":
        return "concluido"
    if data_assinatura_contrato is not None:
        return "concluido"
    if data_recebimento_gelic is not None:
        return "em_tramitacao"
    return None


def situacao_inicial(
    *,
    tipo_nome_normalizado,
    data_assinatura_contrato,
    data_recebimento_gelic,
    prazo_entrega,
    hoje,
    prazo_vigente=None,
):
    """Deriva a situação inicial de um processo no backfill/criação.

    Chama `situacao_por_eventos` primeiro — evento gravado tem precedência
    sobre a checagem de calendário. Só cai no fallback de `prazo_efetivo` vs.
    `hoje` quando não há nenhum fato gravado, onde `prazo_efetivo =
    COALESCE(prazo_vigente, prazo_entrega)` (emendada, 29/08/2026):
    `prazo_efetivo` anterior a `hoje` ⇒ `"atrasado"`; caso contrário
    (incluindo `prazo_efetivo is None`) ⇒ `"no_prazo"` por padrão ("sem
    prazo ⇒ NO PRAZO por padrão").

    `prazo_vigente` é opcional (default `None`) para que a chamada congelada
    em `apps/pca/migrations/0023_estado_situacao_tres_eixos.py` — sem esse
    kwarg — continue funcionando sem alteração: nesse caso `prazo_efetivo`
    cai direto em `prazo_entrega`, comportamento idêntico ao anterior.
    """
    situacao_por_fatos = situacao_por_eventos(
        tipo_nome_normalizado=tipo_nome_normalizado,
        data_assinatura_contrato=data_assinatura_contrato,
        data_recebimento_gelic=data_recebimento_gelic,
    )
    if situacao_por_fatos is not None:
        return situacao_por_fatos
    prazo_efetivo = prazo_vigente if prazo_vigente is not None else prazo_entrega
    if prazo_efetivo is not None and prazo_efetivo < hoje:
        return "atrasado"
    return "no_prazo"


def _somar_meses(data, n):
    """Mesma técnica de `apps/pca/sei/extracao.py::_somar_meses` (Fase 34):
    ajusta ano/mês por divisão inteira e usa `min(dia_original,
    último_dia_do_mês_resultante)` para o dia — nunca gera uma data
    inexistente como 30/02. Copiada aqui (em vez de importada) para manter
    `regras_situacao.py` sem NENHUM import de fora da biblioteca padrão —
    o mesmo motivo do módulo inteiro (docstring acima): seguro para
    importar de dentro de uma migração congelada."""
    from datetime import date, timedelta

    mes_total = data.month - 1 + n
    ano = data.year + mes_total // 12
    mes = mes_total % 12 + 1
    proximo_mes = date(ano + 1, 1, 1) if mes == 12 else date(ano, mes + 1, 1)
    ultimo_dia_do_mes = (proximo_mes - timedelta(days=1)).day
    dia = min(data.day, ultimo_dia_do_mes)
    return date(ano, mes, dia)


def _meses_entre(inicio, fim):
    """Nº de meses entre `inicio` e `fim` (`inicio <= fim`), meses inteiros
    mais fração de dia — direção INVERSA de `_somar_meses` acima: em vez de
    "some N meses a uma data", "quantos meses cabem entre duas datas".
    Devolve `0.0` quando `fim <= inicio` (nunca negativo)."""
    if fim <= inicio:
        return 0.0
    meses = (fim.year - inicio.year) * 12 + (fim.month - inicio.month)
    data_base = _somar_meses(inicio, meses)
    if data_base > fim:
        meses -= 1
        data_base = _somar_meses(inicio, meses)
    dias_extra = (fim - data_base).days
    proximo = _somar_meses(data_base, 1)
    dias_no_mes_seguinte = (proximo - data_base).days
    fracao = dias_extra / dias_no_mes_seguinte if dias_no_mes_seguinte else 0.0
    return meses + fracao


def regime_presumido_migracao(vigencia_inicio, vigencia_fim):
    """Heurística de regime de execução USADA SÓ PELA MIGRAÇÃO 0027 (spec §2.1) — backfill de `Processo.regime_execucao` quando o campo
    nasce `null` num item já existente (import da planilha não o
    preenche). `None` quando falta `vigencia_inicio` ou `vigencia_fim`
    (sem dado suficiente, a migração não escreve nada); senão `"continuado"`
    quando a vigência tem 11 meses ou mais, `"unico"` caso contrário.

    Limiar EXATAMENTE 11 — deliberadamente diferente do limiar 12 de
    `regime_presumido_projecao` abaixo: os dois
    NUNCA se reconciliam, cada um serve um consumidor exclusivo."""
    if vigencia_inicio is None or vigencia_fim is None:
        return None
    return "continuado" if _meses_entre(vigencia_inicio, vigencia_fim) >= 11 else "unico"


def regime_presumido_projecao(vigencia_inicio, vigencia_fim):
    """Heurística de regime de execução USADA SÓ POR
    `apps/pca/projecao/fluxo.py` para presumir o
    regime de um item cujo `Processo.regime_execucao` está `null` NA HORA
    DE PROJETAR (nunca gravada no banco, nunca usada pela migração 0027).
    Mesma assinatura/mesmo cálculo de `regime_presumido_migracao`, limiar
    12 meses ("vigência ≥ 12 meses → continuado, senão único")."""
    if vigencia_inicio is None or vigencia_fim is None:
        return None
    return "continuado" if _meses_entre(vigencia_inicio, vigencia_fim) >= 12 else "unico"
