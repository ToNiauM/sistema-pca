"""Congelamento do "Relatório da reunião" — os fatos guardados como um commit.

Ao fechar uma reunião os FATOS do relatório (`apurar_relatorio`) são gravados como
`RelatorioCongelado` (imutável, versionado, com sha256 do JSON canônico). A tela renderiza esses fatos com a
apresentação e o template ATUAIS (`renderizar_fatos`), então melhorias visuais valem também para reuniões
antigas, e os fatos não dependem da casca (DSGov ou Tabler) do serviço que fechou. Reuniões que nunca foram
fechadas pelo sistema (importadas já FECHADAS) ganham a versão 1 "reconstituída" sob demanda — pela tela ou
por `congelar_relatorios` — a partir do histórico (`apps.pca.checkout`).
"""

import logging
from datetime import datetime, time

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.template.loader import get_template, render_to_string
from django.utils import timezone

from apps.pca import checkout
from apps.pca.models import OrigemRelatorio, RelatorioCongelado, Reuniao
from apps.pca.relatorio_reuniao import apresentar_relatorio, apurar_relatorio, resolver_periodo
from core.templatetags.dsgov import data_br

logger = logging.getLogger(__name__)


def fim_do_dia(dia):
    """Último instante do dia, no fuso do projeto (America/Sao_Paulo): 23:59:59.999999."""
    return timezone.make_aware(datetime.combine(dia, time.max))


def casca_tabler_ativa():
    """True quando a casca Tabler é a que resolve o template da página (PCA_DESIGN ou override de teste)."""
    origem = get_template("pca/relatorio_reuniao.html").origin.name or ""
    return "/tabler/templates/" in origem.replace("\\", "/")


def renderizar_fatos(fatos, *, casca_tabler=False):
    """O documento (html) dos FATOS, com a apresentação e o template atuais. Não toca no banco."""
    return render_to_string(
        "pca/_relatorio_reuniao_documento.html",
        {"relatorio": apresentar_relatorio(fatos), "casca_tabler": casca_tabler},
    )


def renderizar_documento(*, exercicio, reuniao, de, ate, usuario, hoje=None, casca_tabler=False):
    """O documento ao vivo (prévia, período de hoje): `renderizar_fatos(apurar_relatorio(...))`."""
    fatos = apurar_relatorio(exercicio=exercicio, reuniao=reuniao, de=de, ate=ate, usuario=usuario, hoje=hoje)
    return renderizar_fatos(fatos, casca_tabler=casca_tabler)


def periodo_de_fechamento(reuniao, *, hoje):
    """Período do documento no fechamento: o mesmo da prévia (dia seguinte à reunião anterior até
    max(data da reunião, hoje))."""
    de, ate, _aviso = resolver_periodo({}, reuniao.exercicio, reuniao, hoje=hoje)
    return de, max(ate, hoje)


def congelar(*, reuniao, dados, de, ate, corte, origem, usuario=None, observacao=""):
    """Grava a versão n+1 do relatório da reunião (a unicidade (reuniao, versao) pega a corrida)."""
    with transaction.atomic():
        ultima = RelatorioCongelado.objects.filter(reuniao=reuniao).aggregate(m=Max("versao"))["m"] or 0
        return RelatorioCongelado.objects.create(
            reuniao=reuniao,
            versao=ultima + 1,
            de=de,
            ate=ate,
            corte=corte,
            dados=dados,
            origem=origem,
            observacao=observacao,
            criado_por=usuario,
        )


def congelar_no_fechamento(reuniao_id, usuario_id=None):
    """Chamado no `on_commit` do fechamento ABERTA→FECHADA. Apura os fatos ao vivo no próprio processo e
    congela. Qualquer falha é registrada e engolida: o fechamento já foi commitado e a tela
    reconstrói a versão depois, se faltar."""
    try:
        reuniao = Reuniao.objects.select_related("exercicio").get(pk=reuniao_id)
        usuario = get_user_model().objects.filter(pk=usuario_id).first() if usuario_id else None
        hoje = timezone.localdate()
        corte = timezone.now()
        de, ate = periodo_de_fechamento(reuniao, hoje=hoje)
        dados = apurar_relatorio(
            exercicio=reuniao.exercicio, reuniao=reuniao, de=de, ate=ate, usuario=usuario, hoje=hoje
        )
        return congelar(
            reuniao=reuniao, dados=dados, de=de, ate=ate, corte=corte,
            origem=OrigemRelatorio.FECHAMENTO, usuario=usuario,
        )
    except Exception:
        logger.exception("Falha ao congelar o relatório da reunião %s no fechamento", reuniao_id)
        return None


def corte_de_reconstrucao(reuniao):
    """`(corte, observacao)` da reconstituição. Reunião depois do primeiro registro de histórico:
    fim do dia dela, sem observação. Antes dele o sistema ainda não tinha dados: o corte é o fim do dia do
    primeiro registro e a observação conta que o relatório vem da planilha importada."""
    primeiro = checkout.primeiro_registro_historico()
    if primeiro is None or primeiro <= fim_do_dia(reuniao.data):
        return fim_do_dia(reuniao.data), ""
    dia = timezone.localtime(primeiro).date()
    return fim_do_dia(dia), (
        f"Reconstituído a partir da planilha importada em {data_br(dia)}: "
        "o sistema não tinha dados na data desta reunião."
    )


def reconstituir(reuniao, *, usuario=None):
    """Versão congelada de uma reunião FECHADA. Se já existe alguma, devolve a mais recente (idempotente);
    senão reconstrói do histórico (`checkout.apurar_no_corte`) e grava a versão 1 "reconstrução"."""
    existente = reuniao.relatorios_congelados.order_by("-versao").first()
    if existente is not None:
        return existente
    de, ate, _aviso = resolver_periodo({}, reuniao.exercicio, reuniao)
    corte, observacao = corte_de_reconstrucao(reuniao)
    dados = checkout.apurar_no_corte(
        corte=corte, exercicio=reuniao.exercicio, reuniao=reuniao, de=de, ate=ate, usuario=usuario
    )
    try:
        return congelar(
            reuniao=reuniao, dados=dados, de=de, ate=ate, corte=corte,
            origem=OrigemRelatorio.RECONSTRUCAO, usuario=usuario, observacao=observacao,
        )
    except IntegrityError:
        return reuniao.relatorios_congelados.order_by("-versao").first()
