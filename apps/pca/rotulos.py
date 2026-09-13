"""Fonte central de rótulos de apresentação. Nunca importa de models.py
nem de nenhum outro módulo do app: os rótulos daqui são de tela; o
verbose_name do model continua intocado. ROTULOS é sempre consumido com
fallback explícito, nunca sozinho.

"vigente" sai de todo rótulo de prazo — prazo_efetivo/prazo_vigente viram
"Prazo atual" em toda a UI operacional. Vigência contratual
(vigencia_inicio/vigencia_fim) não é rótulo de prazo e não é afetada."""

ROTULOS = {
    # uma só coluna/rótulo para a origem do prazo inicial; prazo_entrega é
    # o campo editável, prazo_inicial é a anotação derivada — mesma ideia
    # em dois estágios
    "prazo_entrega": "Prazo inicial",
    "prazo_inicial": "Prazo inicial",
    # "Prazo vigente"/"Compromisso vigente" viram "Prazo atual" em toda a
    # UI operacional
    "prazo_vigente": "Prazo atual",
    "prazo_efetivo": "Prazo atual",
    # a promessa nova registrada no modal de acompanhamento
    "prazo_prometido": "Novo prazo",
    # rótulo da coluna do histórico da ficha/timeline
    "prazo_registrado": "Prazo registrado",
}
