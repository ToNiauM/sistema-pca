"""Fonte central de rótulos de apresentação.

Nunca importa de `models.py` nem de nenhum outro módulo do app: os rótulos
daqui são de TELA (formulário, ficha, colunas, XLSX, importador, UI
operacional) — `verbose_name` do model continua intocado, zero migração.
`ROTULOS` é sempre consumido com fallback explícito (`ROTULOS.get(nome,
fallback)`), nunca sozinho: um campo sem entrada aqui usa seu rótulo
atual/`verbose_name` normalmente.

Vocabulário fechado: "vigente" sai de todo rótulo de PRAZO —
`prazo_efetivo`/`prazo_vigente` viram "Prazo atual" em toda a UI operacional
(formulário, ficha, modal, colunas, XLSX, análises, KPI). Vigência
CONTRATUAL (`vigencia_inicio`/`vigencia_fim`) não é rótulo de prazo e não é
afetada por esta tabela.
"""

ROTULOS = {
    # Uma só coluna/rótulo para a origem do prazo inicial
    # (COALESCE(prazo_entrega, primeira promessa)): `prazo_entrega` é o
    # nome do campo editável em Planejamento; `prazo_inicial` é a anotação
    # derivada de `ProcessoQuerySet.para_listagem()`. Os dois têm o MESMO
    # rótulo de tela — são a mesma ideia em dois estágios (campo cru vs.
    # anotação com fallback ao histórico).
    "prazo_entrega": "Prazo inicial",
    "prazo_inicial": "Prazo inicial",
    # "Prazo vigente"/"Compromisso vigente" viram "Prazo atual"
    # em toda a UI operacional (varredura completa: formulário, ficha,
    # modal, colunas/XLSX, Próximos vencimentos, KPI).
    "prazo_vigente": "Prazo atual",
    "prazo_efetivo": "Prazo atual",
    # A promessa nova registrada no modal de acompanhamento.
    "prazo_prometido": "Novo prazo",
    # Rótulo da coluna do histórico da ficha/timeline.
    "prazo_registrado": "Prazo registrado",
}
