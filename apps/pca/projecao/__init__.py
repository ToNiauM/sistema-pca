"""Pacote puro de cálculo do fluxo de caixa projetado (Fase 36,
documento interno de desenho
§3-§5). NENHUM módulo deste pacote importa `django`/`from django` — mesmo
padrão de `apps/pca/regras_situacao.py`/`apps/pca/sei/extracao.py`: entrada
e saída são só `list[dict]`/`dataclass`/`Decimal`/`date`/`str`, nunca um
QuerySet nem um model. Calculado por requisição, nada materializado
(abordagem A) — quem monta `itens: list[dict]` a partir do ORM é a
view do plano.

Vocabulário travado (decisão do usuário): as quatro camadas usam o
vocabulário da Lei 14.133/2021 — o jargão de mercado descartado pelo usuário
(ver) NUNCA aparece em identificador, chave ou string
deste pacote.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


CAMADAS = ("contratado", "renovacao", "reajuste", "planejado")

ROTULOS_CAMADA = {
    "contratado": "Contratado",
    "renovacao": "Renovação prevista",
    "reajuste": "Reajuste projetado",
    "planejado": "Planejado",
}

CENARIOS = ("base", "contratado", "sem_reajuste", "sem_renovacao")


@dataclass(frozen=True)
class Parametros:
    """Parâmetros de uma chamada a `fluxo.projetar` (spec §3.1)."""

    horizonte_inicio: date
    horizonte_fim: date
    exercicio: int
    indices: dict
    cenario: str
    lead_time_mediano_dias: int = 90
    # Fase 36 (fix de apresentação): nome do
    # índice selecionado (IPCA/INPC/IGP-M/META_BC), só para compor o texto
    # consolidado de "Premissas" (fluxo.py) quando falta percentual para um
    # ano — não influencia a regra de fallback em si (spec §3.5).
    indice_nome: str = None


@dataclass(frozen=True, slots=True)
class Parcela:
    """Uma linha do fluxo — um item, uma competência, uma camada.

    `instrumento` (Fase 37, spec §2.1/§2.3): identifica de qual
    contrato do item a parcela veio — `"principal"` (item sem `contratos[]`
    explícito, ou grupo de eventos sem `EventoFinanceiro.instrumento`) ou o
    valor de `contrato["instrumento"]` (ex. "CT 12/2026"). Permite somar por
    item (achatando) sem perder de onde cada parcela veio (M05).

    `slots=True` (Fase 37, otimização de desempenho — spec §9: motor ×2 por
    requisição dentro do orçamento de 500 itens × 72 meses; esta é a
    dataclass mais instanciada de `fluxo.py`, uma por parcela gerada)."""

    item_pca: int
    instrumento: str
    competencia: str
    valor: Decimal
    camada: str
    origem: str


@dataclass(frozen=True, slots=True)
class LinhaMemoria:
    """Uma linha da memória de cálculo de um item (Fase 37, spec
    §2.3) — mesma granularidade de `Parcela` (competência × camada × valor),
    mais o texto pronto para tela/XLSX que explica como o valor foi
    calculado (lê isso, não recalcula nada). `slots=True` pelo
    mesmo motivo de `Parcela` acima — uma `LinhaMemoria` por `Parcela`."""

    competencia: str
    camada: str
    valor: Decimal
    formula: str


@dataclass(frozen=True)
class Memoria:
    """Memória de cálculo de UM item (Fase 37, spec §2.3) —
    `sum(l.valor for l in linhas if l.camada == camada)` concilia exatamente
    com a soma das `Parcela`s dessa camada/item em `Projecao.parcelas`
    (depende dessa igualdade)."""

    item_pca: int
    fontes: list = field(default_factory=list)
    segmentos: list = field(default_factory=list)
    premissas: list = field(default_factory=list)
    descartados: list = field(default_factory=list)
    linhas: list = field(default_factory=list)


@dataclass(frozen=True)
class Projecao:
    """Resultado de `fluxo.projetar` — parcelas + agregados prontos para a
    view/template do plano consumir sem recalcular nada."""

    parcelas: list = field(default_factory=list)
    por_mes: dict = field(default_factory=dict)
    por_ano: dict = field(default_factory=dict)
    por_uo_ano: dict = field(default_factory=dict)
    totais: dict = field(default_factory=dict)
    sem_dado: list = field(default_factory=list)
    premissas: list = field(default_factory=list)
    memorias: dict = field(default_factory=dict)
