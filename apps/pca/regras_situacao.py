"""Módulo puro de derivação de Processo.situacao. Sem nenhum import de
django.db.models nem de apps.pca.models: seguro para importar de dentro de
uma migração congelada, testável isoladamente, sem tocar o ORM. As duas
funções recebem e devolvem os valores string dos enums Estado/Situacao,
não os objetos Choices.

situacao_por_eventos é a regra viva: reage só a fatos gravados (assinatura,
recebimento no Gelic), nunca a "hoje" — nunca devolve "atrasado", porque a
transição NO_PRAZO -> ATRASADO é correção de leitura, nunca escrita
automaticamente.

situacao_inicial é a regra de backfill/criação: delega primeiro para
situacao_por_eventos e só cai no fallback de prazo_efetivo vs. hoje quando
não há evento algum, medindo contra prazo_efetivo = COALESCE(prazo_vigente,
prazo_entrega)."""


def situacao_por_eventos(
    *, tipo_nome_normalizado, data_assinatura_contrato, data_recebimento_gelic
):
    """Deriva a situação a partir de fatos gravados.

    - Tipo VIGENTE => "concluido" por natureza, independente de qualquer data.
    - data_assinatura_contrato preenchida => "concluido".
    - data_recebimento_gelic preenchida => "em_tramitacao"; a função nunca
      olha timing, nunca compara datas com "hoje".
    - Nenhum fato gravado => None. Nunca devolve "atrasado" sob nenhuma
      combinação de argumentos.
    """
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

    Chama situacao_por_eventos primeiro — evento gravado tem precedência
    sobre a checagem de calendário. Só cai no fallback de prazo_efetivo vs.
    hoje quando não há nenhum fato gravado: prazo_efetivo anterior a hoje
    => "atrasado"; caso contrário (incluindo prazo_efetivo is None) =>
    "no_prazo" por padrão.

    prazo_vigente é opcional (default None) para que a chamada congelada em
    migração antiga, sem esse kwarg, continue funcionando sem alteração.
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
