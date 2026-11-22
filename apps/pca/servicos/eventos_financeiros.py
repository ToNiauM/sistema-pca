"""Fase 36 (spec §2.2) — sincroniza `EventoFinanceiro`
a partir de `Proposta.serie_valores` (Fase 35, `apps.pca.sei.regras`).

Pacote NOVO (`apps/pca/servicos/`), distinto do módulo já existente
`apps/pca/services.py` (nomeia explicitamente `apps/pca/servicos/
eventos_financeiros.py` — dois nomes parecidos, dois arquivos diferentes,
de propósito).

Chamado por `sei_aplicar`/`sei_sincronizar`/`sei_atender`, SEMPRE depois de
`aplicador.aplicar()` e SEMPRE fora do caminho `simular=True` (nada é
gravado em modo simulado).

`diagnosticar`/`aplicar_correcoes` (debug robo-valor-contratado-item64,
20/10/2026) são a ÚNICA exceção ao "nunca altera nem apaga" de
`sincronizar`: servem só ao comando de correção pontual
`sei_corrigir_eventos`, tocam só eventos de origem `robo` (nunca `manual`)
e gravam sempre instância a instância (`save()`/`delete()`), com autor e
motivo no `simple_history`."""

from __future__ import annotations

from dataclasses import dataclass, field

from django.db import transaction

from apps.pca.models import EventoFinanceiro, OrigemEventoFinanceiro
from apps.pca.sei.regras import motivo_fora_da_serie

# Campos que a correção pontual compara/corrige — só os que a leitura do
# valor decide (debug robo-valor-contratado-item64). `data`/`tipo`/
# `natureza`/`instrumento` ficam como gravados (eventos anteriores à Fase 37
# têm `instrumento` vazio de propósito, sem regressão).
CAMPOS_CORRIGIVEIS = ("valor", "valor_mensal", "periodicidade")

# Prefixo do `history_change_reason` (CharField(max_length=100)) — o motivo
# é truncado para caber.
PREFIXO_MOTIVO = "sei_corrigir_eventos: "
_TAMANHO_MOTIVO = 100


def _entrada_valida(entrada: dict) -> bool:
    """Mesma fronteira de `sincronizar`: sem `valor` ou sem `protocolo`
    estável (`None`/"?"), a entrada nunca vira evento."""
    return entrada.get("valor") is not None and entrada.get("protocolo") not in (None, "?")


def _valores_do_evento(entrada: dict) -> dict:
    """`valor`/`valor_mensal`/`periodicidade` que `sincronizar` grava para
    uma entrada da série — fonte única para criação e correção."""
    valor = entrada.get("valor")
    periodicidade = entrada.get("periodicidade")
    return {
        "valor": valor,
        "valor_mensal": valor if periodicidade == "mensal" else None,
        "periodicidade": periodicidade,
    }


def sincronizar(processo, serie: list[dict]) -> dict:
    """Cria os `EventoFinanceiro` que faltam a partir de `serie`
    (`Proposta.serie_valores`, contrato do plano, estendido pelo
    M03/M04): `{"protocolo", "tipo", "data", "valor",
    "periodicidade", "natureza", "instrumento"}` — `instrumento` é
    OPCIONAL na entrada (séries antigas sem essa chave continuam
    funcionando, gravando `""` = cadeia "principal").

    Idempotência inteira via `get_or_create(processo, protocolo_sei)` — o
    `UniqueConstraint(processo, protocolo_sei)` do model é a mesma chave;
    `defaults` NUNCA sobrescreve um registro já existente (nunca
    altera nem apaga `manual`, nunca apaga `robo`). Ignora, sem gravar nada:
    entradas sem `valor` (nada para disputar `valor_contratado` — a
    fronteira de `confere`/valor conferido já filtrou isso em
    `sei/regras.py::_valor_efetivo`, M03) e entradas sem `protocolo`
    estável (`None`/"?" — sem chave de idempotência, nunca duplica em
    execuções repetidas). Devolve `{"criados": n, "ignorados": m}` —
    `ignorados` soma as entradas puladas por falta de dado E as que já
    existiam (`get_or_create` com `created=False`).

    `valor_mensal` (Fase 37, M03): quando `periodicidade ==
    "mensal"`, o `entrada["valor"]` recebido já É o valor mensal (a
    fronteira de `sei/regras.py` não distingue global de mensal em campos
    separados) — grava-se em `valor_mensal` E em `valor` (mantém
    `EventoFinanceiro.valor` como "global vigente após o evento", coerente
    com a docstring do model: para periodicidade mensal, o "global" num
    dado mês é o próprio valor mensal). Para `"anual"`/`"global"`/`None`,
    `valor_mensal` fica `None` — o rateio é responsabilidade do motor
    (`apps.pca.projecao.fluxo`), não deste serviço."""
    criados = 0
    ignorados = 0

    for entrada in serie:
        if not _entrada_valida(entrada):
            ignorados += 1
            continue

        _, criado = EventoFinanceiro.objects.get_or_create(
            processo=processo,
            protocolo_sei=entrada.get("protocolo"),
            defaults={
                "data": entrada.get("data"),
                "tipo": entrada.get("tipo"),
                "natureza": entrada.get("natureza"),
                **_valores_do_evento(entrada),
                "instrumento": entrada.get("instrumento") or "",
                "origem": OrigemEventoFinanceiro.ROBO,
            },
        )
        if criado:
            criados += 1
        else:
            ignorados += 1

    return {"criados": criados, "ignorados": ignorados}


# --------------------------- correção pontual (sei_corrigir_eventos) -------


@dataclass
class Correcao:
    """Uma correção proposta para um `EventoFinanceiro` de origem `robo`:
    `acao` "apagar" (o documento coletado não entra mais na série) ou
    "alterar" (`campos`: `{campo: (antes, depois)}`, só
    `CAMPOS_CORRIGIVEIS`)."""

    evento: EventoFinanceiro
    acao: str
    motivo: str
    campos: dict = field(default_factory=dict)


@dataclass
class Diagnostico:
    """Resultado SOMENTE-LEITURA de `diagnosticar` para um `Processo`:
    `correcoes` (o que `aplicar_correcoes` faria), `faltantes` (entradas da
    série corrigida sem evento — a próxima sincronização cria, este módulo
    não), `manuais` (eventos `manual`, nunca tocados) e `fora_da_coleta`
    (eventos `robo` cujo documento não está na coleta — sem evidência,
    mantidos)."""

    correcoes: list = field(default_factory=list)
    faltantes: list = field(default_factory=list)
    manuais: int = 0
    fora_da_coleta: int = 0


_PERIODICAS = ("mensal", "anual")


def _motivo_alteracao(campos: dict) -> str:
    periodicidade = campos.get("periodicidade")
    if periodicidade is not None:
        antes, depois = periodicidade
        if antes in _PERIODICAS and depois not in _PERIODICAS:
            return f"o valor gravado era o {antes} do instrumento; vale o total/global"
        if antes is None and depois == "global" and "valor" not in campos:
            return "apostilamento que disputa o valor é global"
    return "valor relido pelas regras atuais"


def diagnosticar(processo, serie: list[dict], documentos: dict[str, dict]) -> Diagnostico:
    """Compara os `EventoFinanceiro` já gravados de `processo` com a série
    que as regras ATUAIS produzem (`serie`, `Proposta.serie_valores`) —
    SOMENTE LEITURA, nunca grava nada.

    `documentos` é `{protocolo: documento}` da coleta (só processos com
    `resultado == "ok"`): um evento `robo` só é julgado quando o documento
    dele está ali (sem evidência, nada se apaga). Evento `robo` cujo
    documento está na coleta mas fora da série vira "apagar" (motivo de
    `regras.motivo_fora_da_serie`); na série com `valor`/`valor_mensal`/
    `periodicidade` diferentes vira "alterar". Eventos `manual` nunca
    entram em `correcoes`."""
    esperado = {
        entrada["protocolo"]: entrada for entrada in serie if _entrada_valida(entrada)
    }
    diagnostico = Diagnostico()
    protocolos_gravados = set()
    for evento in EventoFinanceiro.objects.filter(processo=processo).order_by("data", "id"):
        if evento.protocolo_sei:
            protocolos_gravados.add(evento.protocolo_sei)
        if evento.origem != OrigemEventoFinanceiro.ROBO:
            diagnostico.manuais += 1
            continue
        documento = documentos.get(evento.protocolo_sei) if evento.protocolo_sei else None
        if documento is None:
            diagnostico.fora_da_coleta += 1
            continue
        entrada = esperado.get(evento.protocolo_sei)
        if entrada is None:
            diagnostico.correcoes.append(
                Correcao(evento=evento, acao="apagar", motivo=motivo_fora_da_serie(documento))
            )
            continue
        alvo = _valores_do_evento(entrada)
        campos = {
            campo: (getattr(evento, campo), alvo[campo])
            for campo in CAMPOS_CORRIGIVEIS
            if getattr(evento, campo) != alvo[campo]
        }
        if campos:
            diagnostico.correcoes.append(
                Correcao(evento=evento, acao="alterar", motivo=_motivo_alteracao(campos), campos=campos)
            )
    diagnostico.faltantes = [
        entrada for protocolo, entrada in esperado.items() if protocolo not in protocolos_gravados
    ]
    return diagnostico


def aplicar_correcoes(correcoes: list[Correcao], *, usuario) -> dict:
    """Grava `correcoes` (de `diagnosticar`) numa única transação, instância
    a instância — `delete()`/`save(update_fields=...)` com `_history_user`
    e `_change_reason` (o `ManagerAuditado` proíbe `.update()` em massa,,
    então cada correção deixa sua linha no
    `simple_history`. Só eventos `robo` (reconferido aqui). Devolve
    `{"apagados": n, "alterados": m}`."""
    apagados = 0
    alterados = 0
    with transaction.atomic():
        for correcao in correcoes:
            evento = correcao.evento
            if evento.origem != OrigemEventoFinanceiro.ROBO:
                continue
            evento._history_user = usuario
            evento._change_reason = (PREFIXO_MOTIVO + correcao.motivo)[:_TAMANHO_MOTIVO]
            if correcao.acao == "apagar":
                evento.delete()
                apagados += 1
            elif correcao.acao == "alterar" and correcao.campos:
                for campo, (_antes, depois) in correcao.campos.items():
                    setattr(evento, campo, depois)
                evento.save(update_fields=list(correcao.campos))
                alterados += 1
    return {"apagados": apagados, "alterados": alterados}
