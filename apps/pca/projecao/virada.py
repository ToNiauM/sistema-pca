"""Regra pura de destino em N+1 (Fase 38, spec §3).

Mesmo padrão de `apps/pca/regras_situacao.py`/`apps/pca/sei/regras.py`:
nenhum import do framework web nem de `apps.pca.models` — recebe e devolve
valores Python simples (`date`/`bool`/`int`/`Enum`), testável isoladamente,
sem tocar o ORM (mesmo espírito do pacote, ver `apps/pca/projecao/
__init__.py`).

`hoje` é sempre parâmetro, nunca lido do relógio do sistema dentro deste
módulo — os testes usam data fixa (`test_projecao_virada.py`).

A função `destino()` NÃO lê `situacao`, `tipo` nem `regime_execucao` — quem
decide QUEM entra é a população do serviço (`apps/pca/servicos/
contratos.py`); esta função só CLASSIFICA o que já entrou.

Vocabulário travado (memória `vocabulario-lei-14133-nao-jargao`):
contratado/planejado/renovação prevista — nunca o termo de mercado que a
mesma memória descarta.

`apps/pca/servicos/contratos.py::anotar_destino` reproduz, num único
`Case/When`, exatamente a mesma precedência de `destino()` abaixo — o
teste de paridade (`test_servicos_contratos.py`) é a prova de que os dois
lugares concordam.
"""

import re
from collections import Counter
from datetime import date
from enum import Enum
from typing import Iterable


class Destino(Enum):
    """Destino de um item com contrato ao virar do exercício N para N+1
    (spec §3). Cada membro carrega `(chave, rotulo, explicacao)` — `chave`
    é a allowlist usada em filtros/anotação ORM, `rotulo` é o texto do
    `br-tag` na tela, `explicacao` é o `title`/apoio."""

    VENCIDO = (
        "vencido",
        "Vencido",
        "Vigência encerrada antes de hoje — pendência: registrar a "
        "prorrogação ou encerrar. Não é declaração de situação jurídica "
        "atual.",
    )
    ENCERRA_N = (
        "encerra_n",
        "Encerra em N",
        "Renovação não prevista — sem possibilidade legal ou sem "
        "interesse. Não entra no PCA N+1.",
    )
    RENOVA_N = (
        "renova_n",
        "Renovação em N",
        "Aditivo/renovação ainda a registrar; o destino em N+1 depende da "
        "nova vigência.",
    )
    RENOVACAO_N1 = (
        "renovacao_n1",
        "Renovação em N+1",
        "Entra no PCA N+1 como Renovação, no prazo, mês previsto = mês do "
        "vencimento.",
    )
    ENCERRA_N1 = (
        "encerra_n1",
        "Encerra em N+1",
        "Entra no PCA N+1 como Vigente (concluído) e consome orçamento até "
        "vencer; renovação não prevista.",
    )
    VIGENTE_N1 = (
        "vigente_n1",
        "Vigente em N+1",
        "Entra no PCA N+1 como Vigente (concluído); vence depois de N+1.",
    )

    @property
    def chave(self) -> str:
        return self.value[0]

    @property
    def rotulo(self) -> str:
        return self.value[1]

    @property
    def explicacao(self) -> str:
        return self.value[2]

    @classmethod
    def por_chave(cls, chave: str) -> "Destino | None":
        for membro in cls:
            if membro.chave == chave:
                return membro
        return None


CHAVES_DESTINO: tuple[str, ...] = tuple(membro.chave for membro in Destino)


def com_anos(texto: str, ano: int | None) -> str:
    """Troca os marcadores da regra ("N" = exercício do PCA, "N+1" = o seguinte) pelos anos de verdade
    (pedido de 29/09/2026: na tela, "Encerra em N" vira "Encerra em 2026", "Vigente em N+1" vira
    "Vigente em 2027"). Sem ano (nenhum exercício aberto), devolve o texto como está."""
    if ano is None:
        return texto
    texto = re.sub(r"\bN\s*\+\s*1\b", str(ano + 1), texto)
    return re.sub(r"\bN\b", str(ano), texto)


GRUPOS_DESTINO: dict[str, tuple[Destino, ...]] = {
    "encerramento_n": (Destino.VENCIDO, Destino.ENCERRA_N),
    "renovacao_n": (Destino.RENOVA_N,),
    "renovacao_n1": (Destino.RENOVACAO_N1,),
    "vigente_n1": (Destino.VIGENTE_N1, Destino.ENCERRA_N1),
}


def destino(
    vigencia_fim: date,
    renovacao_prevista: bool,
    exercicio: int,
    hoje: date,
) -> Destino:
    """Classifica um item com contrato (spec §3). Precedência EXATA — a
    mesma que `apps/pca/servicos/contratos.py::anotar_destino` reproduz,
    `When` a `When`:

    1. `vigencia_fim < hoje` → VENCIDO
    2. `vigencia_fim.year <= exercicio` → RENOVA_N (Sim) / ENCERRA_N (Não)
       — o `<=`, e não `==`, implementa "vigencia_fim.year < N com
       vigencia_fim >= hoje classifica como == N" (consulta de
       exercício futuro).
    3. `vigencia_fim.year == exercicio + 1` → RENOVACAO_N1 (Sim) /
       ENCERRA_N1 (Não)
    4. senão → VIGENTE_N1

    `renovacao_prevista` é avaliado com `bool()` — o ORM devolve `bool`,
    mas a geração da Fase 40 pode passar `int` (0/1)."""

    renovacao_prevista = bool(renovacao_prevista)

    if vigencia_fim < hoje:
        return Destino.VENCIDO

    if vigencia_fim.year <= exercicio:
        return Destino.RENOVA_N if renovacao_prevista else Destino.ENCERRA_N

    if vigencia_fim.year == exercicio + 1:
        return (
            Destino.RENOVACAO_N1 if renovacao_prevista else Destino.ENCERRA_N1
        )

    return Destino.VIGENTE_N1


def contagem(destinos: Iterable[Destino]) -> dict[Destino, int]:
    """Devolve um dict com as 6 chaves de `Destino` sempre presentes (zero
    quando ausente) — usado por quem já tem a lista de destinos gerada em
    Python (a view/serviço usa `aggregate` no ORM, ver §2/§8 da spec; esta
    função existe para a futura geração de N+1 e para os testes)."""

    contador = Counter(destinos)
    return {d: contador.get(d, 0) for d in Destino}


def parametros_n1(
    destino: "Destino",
    vigencia_fim: date,
    mes_previsto_origem: int | None,
) -> tuple[str, str, int] | None:
    """Fase 40 (spec §0 — tabela "O que nasce em N+1") — regra pura que
    codifica que parâmetros o item nascido em N+1 carrega, a partir do
    `Destino` já classificado por `destino()` acima. Continua puro (sem
    import do framework web nem de `apps.pca.models`, mesmo espírito do
    módulo): as strings de `situação` devolvidas são as MESMAS chaves de
    `Situacao.NO_PRAZO`/`CONCLUIDO` ("no_prazo"/"concluido"), escritas
    cruas para não acoplar este módulo ao ORM.

    | Destino | chave do tipo | situação | mês |
    |---|---|---|---|
    | `RENOVACAO_N1` | `"renovacao"` | `"no_prazo"` | `vigencia_fim.month` |
    | `ENCERRA_N1` | `"vigente"` | `"concluido"` | `vigencia_fim.month` |
    | `VIGENTE_N1` | `"vigente"` | `"concluido"` | `mes_previsto_origem or 1` |
    | demais (`VENCIDO`/`ENCERRA_N`/`RENOVA_N`) | — | — | `None` (não gera) |
    """

    if destino is Destino.RENOVACAO_N1:
        return ("renovacao", "no_prazo", vigencia_fim.month)
    if destino is Destino.ENCERRA_N1:
        return ("vigente", "concluido", vigencia_fim.month)
    if destino is Destino.VIGENTE_N1:
        return ("vigente", "concluido", mes_previsto_origem or 1)
    return None
