"""Backfill dos relatórios congelados.

Toda reunião FECHADA sem nenhuma versão ganha a versão 1 (origem "reconstrução"), reconstituída do histórico
no fim do dia da reunião — ou, se a reunião é anterior ao primeiro registro de histórico, no fim do dia desse
registro, com a observação da planilha importada. Idempotente: quem já tem versão fica de fora. `--dry-run`
só lista (período, corte e observação), sem cópia de banco nem subprocesso.
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.pca import congelamento
from apps.pca.checkout import CheckoutErro
from apps.pca.models import Reuniao, SituacaoReuniao
from core.templatetags.dsgov import data_br


class Command(BaseCommand):
    help = "Congela o relatório das reuniões fechadas que ainda não têm versão (reconstituído do histórico)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Só lista; não grava nada.")

    def handle(self, *args, **opcoes):
        pendentes = list(
            Reuniao.objects.filter(situacao=SituacaoReuniao.FECHADA, relatorios_congelados__isnull=True)
            .select_related("exercicio")
            .order_by("data")
        )
        if not pendentes:
            self.stdout.write("Nenhuma reunião fechada sem relatório congelado.")
            return
        criadas = falhas = 0
        for reuniao in pendentes:
            de, ate, _aviso = congelamento.resolver_periodo({}, reuniao.exercicio, reuniao)
            corte, observacao = congelamento.corte_de_reconstrucao(reuniao)
            if opcoes["dry_run"]:
                self.stdout.write(
                    f"{data_br(reuniao.data)} · período {data_br(de)} a {data_br(ate)} · "
                    f"corte {timezone.localtime(corte):%d/%m/%Y %H:%M}"
                )
                if observacao:
                    self.stdout.write(f"    {observacao}")
                continue
            try:
                versao = congelamento.reconstituir(reuniao)
            except CheckoutErro as exc:
                falhas += 1
                self.stderr.write(f"{data_br(reuniao.data)} · FALHOU: {exc}")
                continue
            criadas += 1
            self.stdout.write(
                f"{data_br(reuniao.data)} · versão {versao.versao} ({versao.hash_curto})"
                + (f" · {observacao}" if observacao else "")
            )
        if opcoes["dry_run"]:
            self.stdout.write(f"{len(pendentes)} reunião(ões) a congelar (dry-run: nada gravado).")
            return
        self.stdout.write(f"Congeladas: {criadas}. Falhas: {falhas}.")
        if falhas:
            raise CommandError(f"{falhas} reunião(ões) não puderam ser congeladas.")
