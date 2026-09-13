"""Interpretação de termo de busca transversal: recebe um queryset já
autorizado e devolve (queryset_filtrado, avisos). Cada família de campos
entra como uma condição OR combinada num único Q()."""

import re
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.db.models import CharField, Exists, F, OuterRef, Q
from django.db.models.functions import Cast

from apps.pca.models import Estado, ProcessoSEI, Situacao

# limite de entrada; corte antes de qualquer interpretação
LIMITE_TERMO = 200

# texto por trecho, sem caixa/acento, sempre incondicional
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

# inteiros comparados por trecho; cada campo precisa de Cast prévio para texto
_CAMPOS_INTEIRO = (
    "item_pca",
    "exercicio__ano",
    "n_reunioes",
    "n_compromissos",
    "n_prorrogacoes",
    "dias_atraso",
)

# datas comparadas por igualdade exata; prazo_vigente fica de fora pois
# prazo_efetivo já é COALESCE(prazo_vigente, prazo_entrega)
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

# booleanos só casam por rótulo textual explícito, nunca "true"/"1";
# sobrestado replica a mesma condição de ProcessoQuerySet.sobrestados()
_ROTULOS_BOOLEANOS = {
    "atrasado": Q(atrasado=True),
    "publicacao pendente": Q(publicacao_pendente=True),
    "sobrestado": Q(n_prorrogacoes__gt=1) & ~Q(estado=Estado.CANCELADO),
}

# dígitos, pontos e opcionalmente uma vírgula, depois de remover "R$" e espaços
_RE_DINHEIRO = re.compile(r"^[0-9]+(\.[0-9]+)*(,[0-9]+)?$")


def _sem_acento(texto):
    """Casefold + remoção de acentos em Python puro."""
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).casefold()


def _tentar_dinheiro(termo):
    """Interpreta o termo como dinheiro, aceitando "R$", pontos e vírgula decimal."""
    limpo = termo.replace("R$", "").replace(" ", "")
    if not limpo or not _RE_DINHEIRO.fullmatch(limpo):
        return None
    normalizado = limpo.replace(".", "").replace(",", ".")
    try:
        return Decimal(normalizado)
    except InvalidOperation:
        return None


def _tentar_data(termo):
    """Interpreta o termo como data dd/mm/aaaa; falha devolve um aviso."""
    try:
        return datetime.strptime(termo, "%d/%m/%Y").date(), None
    except ValueError:
        return None, f"Data inválida: {termo} não existe no calendário."


def aplicar_busca(qs, termo):
    """Aplica a busca sobre um queryset já autorizado. Devolve
    (qs_filtrado, avisos); termo vazio devolve (qs, []) sem filtrar."""
    termo = (termo or "")[:LIMITE_TERMO].strip()
    avisos = []
    if not termo:
        return qs, avisos

    condicoes = Q()

    # texto — sempre incondicional
    for campo in _CAMPOS_TEXTO:
        condicoes |= Q(**{f"{campo}__unaccent__icontains": termo})

    # números SEI (1:N) via Exists, sem JOIN nem distinct()
    condicoes |= Q(
        Exists(
            ProcessoSEI.objects.filter(
                processo=OuterRef("pk"), numero_sei__unaccent__icontains=termo
            )
        )
    )

    # inteiros por trecho — Cast prévio, um alias por campo
    anotacoes_inteiro = {
        "_busca_" + campo.replace("__", "_"): Cast(F(campo), output_field=CharField())
        for campo in _CAMPOS_INTEIRO
    }
    qs = qs.annotate(**anotacoes_inteiro)
    for campo, alias in zip(_CAMPOS_INTEIRO, anotacoes_inteiro):
        condicoes |= Q(**{f"{alias}__icontains": termo})

    # mês — número (1-12) e nome em português, em paralelo
    if termo.isdigit() and 1 <= int(termo) <= 12:
        condicoes |= Q(mes_previsto=int(termo))
    from apps.pca.filtros import NOMES_MES  # import local — evita ciclo com filtros.py

    termo_sem_acento = _sem_acento(termo)
    for numero, nome in NOMES_MES.items():
        if _sem_acento(nome) == termo_sem_acento:
            condicoes |= Q(mes_previsto=numero)
            break

    # dinheiro e data são mutuamente exclusivos: "/" indica data
    if "/" in termo:
        data, aviso = _tentar_data(termo)
        if data is not None:
            for campo in _CAMPOS_DATA:
                condicoes |= Q(**{campo: data})
        elif aviso:
            avisos.append(aviso)
    else:
        decimal_valor = _tentar_dinheiro(termo)
        if decimal_valor is not None:
            condicoes |= Q(valor_estimado=decimal_valor) | Q(
                valor_contratado=decimal_valor
            )

    # rótulos — Estado/Situação pela representação apresentada, nunca pelo valor cru
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

    # indicadores booleanos — mesmo princípio de rótulo explícito
    if termo_sem_acento in _ROTULOS_BOOLEANOS:
        condicoes |= _ROTULOS_BOOLEANOS[termo_sem_acento]

    return qs.filter(condicoes), avisos
