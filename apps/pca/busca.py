"""Serviço único de interpretação de busca transversal.

Consumido por `apps.pca.filtros.queryset_filtrado` (recorte do exercício
atual, filtro `q` da tabela de Processos) e por
`apps.pca.views_busca.busca_view` (busca global, todos os exercícios
acessíveis). Recebe um queryset já AUTORIZADO — este módulo nunca decide
sozinho o que o usuário pode ver, só interpreta o termo — e devolve
`(queryset_filtrado, avisos)`: uma tupla, nunca só o queryset, para que a
UI possa exibir avisos de data inválida quando existirem.

Cada família de campos entra como uma condição adicional de um
único `Q()` combinado por OR — a União: o primeiro achado nunca interrompe
a busca dos demais. Fora do escopo: histórico completo de
`Acompanhamento`, contas de `Usuario`, campos técnicos de auditoria do
`simple_history`.
"""

import re
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.db.models import CharField, Exists, F, OuterRef, Q
from django.db.models.functions import Cast

from apps.pca.colunas import CHAVES_RESTRITAS_ACOMPANHAMENTO, _sem_permissao_acompanhamento
from apps.pca.models import Estado, ProcessoSEI, Situacao

# Limite de entrada; corte ANTES de qualquer interpretação.
LIMITE_TERMO = 200

# Texto por trecho, sem caixa/acento, SEMPRE incondicional (a
# interpretação textual nunca é descartada por causa de outra bater ou
# não). `situacao_atual` é a anotação de `para_listagem()` (nome textual da
# última reunião) — texto direto, nunca a comparação por rótulo do item 6
# abaixo (que é sobre o eixo Situação/`situacao_efetiva`, outra coisa).
_CAMPOS_TEXTO = (
    "descricao_objeto",
    "justificativa",
    "unidade_organizacional__nome",
    "tipo__nome",
    "categoria__nome",
    "grau_prioridade__nome",
    "classificacao__nome",
    "modalidade__nome",
    "situacao_atual",
    "numero_contratacao",
    "numero_arp",
    "instrumento_contratual__nome",
    "numero_instrumento_contratual",
    "fornecedor_razao_social",
)

# Inteiros comparados por TRECHO (substring da representação
# decimal). `IntegerField`/`DecimalField` não aceita `__icontains` direto
# no Postgres: cada campo precisa de um `Cast` prévio para texto.
_CAMPOS_INTEIRO = (
    "item_pca",
    "exercicio__ano",
    "n_reunioes",
    "n_compromissos",
    "n_prorrogacoes",
    "dias_atraso",
)

# Datas comparadas por IGUALDADE exata (nunca substring); a
# lista literal do bloco <interfaces> do plano (Planejamento +
# Contratação). `prazo_vigente` fica de fora desta lista (só `prazo_efetivo`
# entra) — decisão do próprio texto do plano: `prazo_efetivo` já é
# `COALESCE(prazo_vigente, prazo_entrega)`, então uma data de
# `prazo_vigente` preenchida sempre bate `prazo_efetivo` também.
_CAMPOS_DATA = (
    "data_inclusao_pca",
    "prazo_entrega",
    "prazo_efetivo",
    "data_envio_gelic",
    "data_recebimento_gelic",
    "vigencia_inicio",
    "vigencia_fim",
    "data_assinatura_contrato",
)

# Booleanos só casam por RÓTULO textual explícito, nunca por
# "true"/"1". `sobrestado` não é campo nem anotação própria de
# `para_listagem()` — só existe como `ProcessoQuerySet.sobrestados()`
# (ativos com mais de uma data de entrega distinta); o Q() abaixo replica
# a MESMA condição desse método, para o rótulo "sobrestado" encontrar os
# mesmos processos que o filtro `?sobrestado=1` da tabela já encontra.
_ROTULOS_BOOLEANOS = {
    "atrasado": Q(atrasado=True),
    "publicacao pendente": Q(publicacao_pendente=True),
    "sobrestado": Q(n_prorrogacoes__gt=1) & ~Q(estado=Estado.CANCELADO),
}

# "dígitos, pontos e opcionalmente UMA vírgula seguida de
# dígitos", depois de remover "R$" e espaços.
_RE_DINHEIRO = re.compile(r"^[0-9]+(\.[0-9]+)*(,[0-9]+)?$")


def _sem_acento(texto):
    """Casefold + remoção de acentos em Python puro — `NOMES_MES`/`choices`
    são conjuntos fixos e pequenos em memória, não precisam do lookup
    `__unaccent` do banco."""
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).casefold()


def _tentar_dinheiro(termo):
    """Só interpreta como dinheiro se, depois de remover "R$"
    e espaços, o resto for só dígitos/pontos com no máximo UMA vírgula
    decimal. As quatro grafias `1400`, `1.400`, `1400,00` e
    `R$ 1.400,00` devolvem o MESMO `Decimal`."""
    limpo = termo.replace("R$", "").replace(" ", "")
    if not limpo or not _RE_DINHEIRO.fullmatch(limpo):
        return None
    normalizado = limpo.replace(".", "").replace(",", ".")
    try:
        return Decimal(normalizado)
    except InvalidOperation:
        return None


def _tentar_data(termo):
    """Só chamado quando `termo` contém "/". Falha (ex.
    31/02/2026, dia inexistente) NÃO é silenciosa: devolve um aviso
    pt-BR."""
    try:
        return datetime.strptime(termo, "%d/%m/%Y").date(), None
    except ValueError:
        return None, f"Data inválida: {termo} não existe no calendário."


def aplicar_busca(qs, termo, request=None):
    """Fonte única de interpretação de termo de busca. `qs` é um
    queryset já AUTORIZADO — recorte de exercício/permissão é
    responsabilidade do CHAMADOR, nunca deste serviço. Devolve
    `(qs_filtrado, avisos)`; termo vazio devolve `(qs, [])` sem filtrar.


    QA de segurança 30/09/2026 (achado B1) — `request`, quando passado,
    decide se os campos de `CHAVES_RESTRITAS_ACOMPANHAMENTO` (prazo/
    reuniões/situação última reunião) entram na busca: sem
    `pca.view_acompanhamento`, esses campos nunca participam da
    interpretação do termo — o visualizador não pode localizar processos
    por um dado que a tela já esconde dele."""
    termo = (termo or "")[:LIMITE_TERMO].strip()
    avisos = []
    if not termo:
        return qs, avisos

    restringir = _sem_permissao_acompanhamento(request)
    campos_texto = _CAMPOS_TEXTO
    campos_inteiro = _CAMPOS_INTEIRO
    campos_data = _CAMPOS_DATA
    if restringir:
        campos_texto = tuple(
            c for c in _CAMPOS_TEXTO if c not in CHAVES_RESTRITAS_ACOMPANHAMENTO
        )
        campos_inteiro = tuple(
            c for c in _CAMPOS_INTEIRO if c not in CHAVES_RESTRITAS_ACOMPANHAMENTO
        )
        campos_data = tuple(
            c for c in _CAMPOS_DATA if c not in CHAVES_RESTRITAS_ACOMPANHAMENTO
        )

    condicoes = Q()

    # (1) Texto — sempre incondicional.
    for campo in campos_texto:
        condicoes |= Q(**{f"{campo}__unaccent__icontains": termo})

    # Identificação — números SEI (1:N) via Exists: nenhum JOIN,
    # nenhum `.distinct()` necessário por causa desta condição.
    condicoes |= Q(
        Exists(
            ProcessoSEI.objects.filter(
                processo=OuterRef("pk"), numero_sei__unaccent__icontains=termo
            )
        )
    )

    # (2) Inteiros por trecho — Cast prévio, um alias por campo (nunca dois
    # Subquery/Cast somados no mesmo annotate(), mesma cautela de Pitfall 9
    # já documentada em querysets.py).
    anotacoes_inteiro = {
        "_busca_" + campo.replace("__", "_"): Cast(F(campo), output_field=CharField())
        for campo in campos_inteiro
    }
    qs = qs.annotate(**anotacoes_inteiro)
    for campo, alias in zip(campos_inteiro, anotacoes_inteiro):
        condicoes |= Q(**{f"{alias}__icontains": termo})

    # (3) Mês — número (1-12, igualdade) e nome em português, em paralelo
    # (as duas tentativas rodam sempre, uma não substitui a outra).
    # QA 30/09/2026 (fuzz M1) — "²".isdigit() é True, mas int("²") levanta
    # ValueError (não capturada); isdecimal() só aceita dígitos decimais
    # que int() de fato converte (nunca os superescritos/circulados de
    # isdigit()). Teto de 2 caracteres redundante com a faixa 1-12, só
    # documenta a intenção.
    if termo.isdecimal() and len(termo) <= 2 and 1 <= int(termo) <= 12:
        condicoes |= Q(mes_previsto=int(termo))
    from apps.pca.filtros import NOMES_MES  # import local — evita ciclo com filtros.py

    termo_sem_acento = _sem_acento(termo)
    for numero, nome in NOMES_MES.items():
        if _sem_acento(nome) == termo_sem_acento:
            condicoes |= Q(mes_previsto=numero)
            break

    # (4)/(5) Dinheiro e data são MUTUAMENTE EXCLUSIVOS: a presença de "/"
    # decide que o termo é candidato a data, nunca a dinheiro.
    if "/" in termo:
        data, aviso = _tentar_data(termo)
        if data is not None:
            for campo in campos_data:
                condicoes |= Q(**{campo: data})
        elif aviso:
            avisos.append(aviso)
    else:
        decimal_valor = _tentar_dinheiro(termo)
        if decimal_valor is not None:
            condicoes |= Q(valor_estimado=decimal_valor) | Q(
                valor_contratado=decimal_valor
            )

    # (6) Rótulos — Estado/Situação pela REPRESENTAÇÃO apresentada, nunca
    # pelo valor cru. Um processo `estado=cancelado` cuja coluna crua
    # `situacao` seja residualmente "concluido" NUNCA casa o termo
    # "Concluído" — a condição do eixo Estado é obrigatória aqui.
    rotulos_estado = {_sem_acento(rotulo): valor for valor, rotulo in Estado.choices}
    rotulos_situacao = {
        _sem_acento(rotulo): valor for valor, rotulo in Situacao.choices
    }
    if termo_sem_acento in rotulos_estado:
        condicoes |= Q(estado=rotulos_estado[termo_sem_acento])
    if termo_sem_acento in rotulos_situacao:
        condicoes |= Q(
            estado=Estado.ATIVO, situacao_efetiva=rotulos_situacao[termo_sem_acento]
        )

    # (6b) Indicadores booleanos — mesmo princípio de rótulo explícito.
    if termo_sem_acento in _ROTULOS_BOOLEANOS:
        condicoes |= _ROTULOS_BOOLEANOS[termo_sem_acento]

    return qs.filter(condicoes), avisos
