"""Serviço "Gerar itens de N+1" (Fase 40, spec
documento interno de desenho).

Ação PRÓPRIA, distinta do wizard de virada (`apps/pca/services.py`,
`confirmar_virada`) — este serviço funciona com N+1 já cadastrado (vazio ou
não), gera SÓ o que a regra de destino manda (`apps.pca.projecao.virada`) e
é reexecutável sem duplicar (chave natural: `Processo.origem` × N+1). Os
dois caminhos coexistem; nenhum altera o outro.

Sem import de view/request — recebe `Exercicio`/`usuario`/`hoje` já
resolvidos, devolve dataclasses simples (mesmo padrão de
`apps/pca/servicos/contratos.py`/`consultas_fluxo.py`)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Max
from django.utils.timezone import localdate
from simple_history.utils import bulk_create_with_history

from apps.catalogo.models import Exercicio, SituacaoExercicio, Tipo
from apps.catalogo.utils import normalizar_nome
from apps.pca.models import Estado, Processo
from apps.pca.projecao.virada import Destino, contagem, destino, parametros_n1
from apps.pca.services import CAMPOS_EXECUCAO_COPIAVEIS, CAMPOS_PLANEJAMENTO_COPIAVEIS
from apps.pca.servicos import consultas_fluxo, contratos

CHANGE_REASON = "Geração N+1 a partir de contratos (Fase 40)"

# `tipo_id` sai do loop de cópia de `CAMPOS_PLANEJAMENTO_COPIAVEIS`
# (ver): o item nascido em N+1 troca de
# tipo (Renovação/Vigente conforme o destino, nunca o tipo da origem) — se
# `tipo_id` ficasse no loop, `Processo(**valores)` receberia `tipo` (a
# chave de acesso do FK, atribuída explicitamente abaixo) E `tipo_id` (o
# attname copiado da origem) ao mesmo tempo, e o Django levantaria
# `TypeError` por argumento duplicado.
_CAMPOS_PLANEJAMENTO_EXCLUIDOS_N1 = frozenset(
    {"valor_estimado", "mes_previsto", "tipo_id"}
)

# QA 30/09/2026 (achado "dominio nº7") — `prazo_entrega` É copiado de propósito via
# `CAMPOS_PLANEJAMENTO_COPIAVEIS` (Fase 11, services.py) para o item novo de N+1,
# reaplicada pela spec da Fase 40 §0 ("Campos copiados"). O achado foi avaliado e MANTIDO
# como está — não é bug, é decisão deliberada de ambas as specs; nenhuma mudança de código
# nos dois serviços (`services.py`/`geracao_n1.py`).


class CatalogoIncompleto(Exception):
    """`Tipo` "Renovação" e/ou "Vigente" ausentes do catálogo — nada foi
    escrito."""

    def __init__(self, erros: list[str]):
        self.erros = list(erros)
        super().__init__("; ".join(self.erros))


class ExercicioDestinoFechado(Exception):
    """QA 30/09/2026 — o exercício de destino já existe FECHADO: a spec
    original da Fase 40 §0 mandava gerar "como está" nesse exercício; a
    decisão do QA de 30/09 sobrepõe essa spec e recusa a geração inteira
    (nada é escrito) em vez de gravar num PCA já encerrado."""

    def __init__(self, exercicio: Exercicio):
        self.exercicio = exercicio
        super().__init__(
            f"O exercício {exercicio.ano} está fechado. "
            "Não é possível gerar itens de N+1 nele."
        )


@dataclass(frozen=True)
class LinhaPrevia:
    """Uma linha da prévia — um item da população de contratos, já
    classificado por `destino()`/`parametros_n1()`."""

    processo: Processo
    destino: Destino
    tipo_chave: str | None
    situacao: str | None
    mes: int | None
    valor: Decimal
    fonte_valor: str | None  # "projecao" | "origem" | None (não entra)
    estado: str  # "novo" | "ja_gerado" | "nao_entra"
    item_gerado: int | None


@dataclass(frozen=True)
class Previa:
    """Resultado de `previa()` — classificação completa da população do
    exercício de origem, pronta para tela/`gerar()`."""

    exercicio_origem: Exercicio
    ano_destino: int
    exercicio_destino_existe: bool
    linhas: list = field(default_factory=list)
    novos: int = 0
    ja_gerados: int = 0
    nao_entram: int = 0
    valor_novos: Decimal = Decimal("0")
    contagem: dict = field(default_factory=dict)
    erros: list = field(default_factory=list)


@dataclass(frozen=True)
class Resultado:
    """Resultado de `gerar()` — os `Processo` criados (lista vazia quando
    não havia nada a gerar), o `Exercicio` de destino (`None` só quando
    nada foi criado e N+1 nunca existiu) e a prévia usada para gerar."""

    criados: list
    exercicio_destino: Exercicio | None
    previa: Previa


def _valores_n1_por_item(projecao, ano: int) -> dict[int, Decimal]:
    """Soma `parcela.valor` por `item_pca` das parcelas com competência em
    `ano` e camada != "planejado" (contratado+renovação+reajuste, nunca o
    planejamento) — spec §2. Quantizado a 2 casas."""

    prefixo = f"{ano}-"
    somas: dict[int, Decimal] = {}
    for parcela in projecao.parcelas:
        if parcela.camada == "planejado":
            continue
        if not parcela.competencia.startswith(prefixo):
            continue
        somas[parcela.item_pca] = somas.get(parcela.item_pca, Decimal("0")) + parcela.valor
    return {item: valor.quantize(Decimal("0.01")) for item, valor in somas.items()}


def _tipos() -> tuple[Tipo | None, Tipo | None]:
    """`Tipo` "Renovação"/"Vigente" do catálogo, casados por
    `nome_normalizado` (nunca hardcodando a forma normalizada — usa
    `normalizar_nome` do próprio catálogo)."""

    chave_renovacao = normalizar_nome("Renovação")
    chave_vigente = normalizar_nome("Vigente")
    tipo_renovacao = Tipo.objects.filter(nome_normalizado=chave_renovacao).first()
    tipo_vigente = Tipo.objects.filter(nome_normalizado=chave_vigente).first()
    return tipo_renovacao, tipo_vigente


def previa(exercicio_origem: Exercicio, hoje: date | None = None) -> Previa:
    """Classifica a população de contratos do exercício de origem (spec
    §0/§2): novos / já gerados (origem com derivado em N+1) / não entram —
    UMA chamada a `projecao_oficial` para todos os itens, nunca uma por
    item (spec §2)."""

    hoje = hoje or localdate()
    ano_destino = exercicio_origem.ano + 1

    qs = list(contratos.populacao(exercicio_origem))
    ids_origem = [p.pk for p in qs]
    derivados = dict(
        Processo.objects.filter(
            exercicio__ano=ano_destino, origem_id__in=ids_origem
        ).values_list("origem_id", "item_pca")
    )

    projecao, _itens = consultas_fluxo.projecao_oficial(exercicio_origem, hoje=hoje)
    valores_projetados = _valores_n1_por_item(projecao, ano_destino)

    tipo_renovacao, tipo_vigente = _tipos()
    erros = []
    if tipo_renovacao is None:
        erros.append("Catálogo sem o tipo 'Renovação'")
    if tipo_vigente is None:
        erros.append("Catálogo sem o tipo 'Vigente'")

    destinos_todos = []
    linhas_entram = []
    linhas_fora = []
    for processo in qs:
        d = destino(
            processo.vigencia_fim,
            processo.renovacao_prevista,
            exercicio_origem.ano,
            hoje,
        )
        destinos_todos.append(d)
        parametros = parametros_n1(d, processo.vigencia_fim, processo.mes_previsto)

        if parametros is None:
            linhas_fora.append(
                LinhaPrevia(
                    processo=processo,
                    destino=d,
                    tipo_chave=None,
                    situacao=None,
                    mes=None,
                    valor=Decimal("0"),
                    fonte_valor=None,
                    estado="nao_entra",
                    item_gerado=None,
                )
            )
            continue

        tipo_chave, situacao_chave, mes = parametros
        item_gerado = derivados.get(processo.pk)
        if item_gerado is not None:
            linhas_entram.append(
                LinhaPrevia(
                    processo=processo,
                    destino=d,
                    tipo_chave=tipo_chave,
                    situacao=situacao_chave,
                    mes=mes,
                    valor=Decimal("0"),
                    fonte_valor=None,
                    estado="ja_gerado",
                    item_gerado=item_gerado,
                )
            )
            continue

        valor_projecao = valores_projetados.get(processo.item_pca)
        if valor_projecao is not None and valor_projecao > 0:
            valor, fonte_valor = valor_projecao, "projecao"
        else:
            valor, fonte_valor = (processo.valor_estimado or Decimal("0")), "origem"

        linhas_entram.append(
            LinhaPrevia(
                processo=processo,
                destino=d,
                tipo_chave=tipo_chave,
                situacao=situacao_chave,
                mes=mes,
                valor=valor,
                fonte_valor=fonte_valor,
                estado="novo",
                item_gerado=None,
            )
        )

    linhas = linhas_entram + linhas_fora
    novos = sum(1 for linha in linhas if linha.estado == "novo")
    ja_gerados = sum(1 for linha in linhas if linha.estado == "ja_gerado")
    nao_entram = sum(1 for linha in linhas if linha.estado == "nao_entra")
    valor_novos = sum(
        (linha.valor for linha in linhas if linha.estado == "novo"), Decimal("0")
    )

    return Previa(
        exercicio_origem=exercicio_origem,
        ano_destino=ano_destino,
        exercicio_destino_existe=Exercicio.objects.filter(ano=ano_destino).exists(),
        linhas=linhas,
        novos=novos,
        ja_gerados=ja_gerados,
        nao_entram=nao_entram,
        valor_novos=valor_novos,
        contagem=contagem(destinos_todos),
        erros=erros,
    )


def gerar(exercicio_origem: Exercicio, usuario, hoje: date | None = None) -> Resultado:
    """Gera os itens novos de N+1 numa ÚNICA transação — idempotente
    (segunda chamada cria 0). Recalcula a prévia dentro da transação (não
    confia em prévia antiga computada por outra requisição)."""

    hoje = hoje or localdate()
    with transaction.atomic():
        resultado_previa = previa(exercicio_origem, hoje=hoje)
        if resultado_previa.erros:
            raise CatalogoIncompleto(resultado_previa.erros)

        exercicio_existente = Exercicio.objects.filter(
            ano=resultado_previa.ano_destino
        ).first()
        if exercicio_existente is not None and exercicio_existente.situacao == SituacaoExercicio.FECHADO:
            raise ExercicioDestinoFechado(exercicio_existente)

        linhas_novas = [
            linha for linha in resultado_previa.linhas if linha.estado == "novo"
        ]
        if not linhas_novas:
            exercicio_destino = Exercicio.objects.filter(
                ano=resultado_previa.ano_destino
            ).first()
            return Resultado(
                criados=[], exercicio_destino=exercicio_destino, previa=resultado_previa
            )

        exercicio_destino, _criado = Exercicio.objects.get_or_create(
            ano=resultado_previa.ano_destino,
            defaults={
                "rotulo": f"PCA {resultado_previa.ano_destino}",
                "situacao": SituacaoExercicio.ABERTO,
            },
        )

        origem_ids = [linha.processo.pk for linha in linhas_novas]
        origens_travadas = {
            processo.pk: processo
            for processo in Processo.objects.select_for_update().filter(
                pk__in=origem_ids
            )
        }

        tipo_renovacao, tipo_vigente = _tipos()
        tipos_por_chave = {"renovacao": tipo_renovacao, "vigente": tipo_vigente}

        proximo = (
            Processo.objects.filter(exercicio=exercicio_destino).aggregate(
                maximo=Max("item_pca")
            )["maximo"]
            or 0
        ) + 1

        copias = []
        for indice, linha in enumerate(linhas_novas):
            origem = origens_travadas[linha.processo.pk]
            valores = {
                "item_pca": proximo + indice,
                "exercicio": exercicio_destino,
                "origem": origem,
                "estado": Estado.ATIVO,
                "situacao": linha.situacao,
                "tipo": tipos_por_chave[linha.tipo_chave],
                "mes_previsto": linha.mes,
                "valor_estimado": linha.valor,
                "data_inclusao_pca": None,
                "data_envio_gelic": None,
                "data_recebimento_gelic": None,
                "data_prevista_conclusao": None,
                "renovacao_prevista": origem.renovacao_prevista,
                "regime_execucao": origem.regime_execucao,
                "valor_mensal": origem.valor_mensal,
            }
            for campo in CAMPOS_PLANEJAMENTO_COPIAVEIS:
                if campo in _CAMPOS_PLANEJAMENTO_EXCLUIDOS_N1:
                    continue
                valores[campo] = getattr(origem, campo)
            for campo in CAMPOS_EXECUCAO_COPIAVEIS:
                valores[campo] = getattr(origem, campo)
            copias.append(Processo(**valores))

        bulk_create_with_history(
            copias,
            Processo,
            batch_size=200,
            default_user=usuario,
            default_change_reason=CHANGE_REASON,
        )

        return Resultado(
            criados=copias, exercicio_destino=exercicio_destino, previa=resultado_previa
        )
