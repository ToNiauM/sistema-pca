"""Apura os fatos do relatório contra uma cópia reconstruída do banco.

Só somente-leitura, e só roda contra a CÓPIA que `apps.pca.checkout` montou: recusa qualquer outro banco
(`--banco` tem de ser o arquivo da conexão ativa; o pai define `DATABASE_URL` no ambiente do subprocesso).
O relógio fica parado no corte, para `hoje`, `agora` e os `localdate()` das anotações verem a data do corte.
Escreve só o JSON dos fatos no stdout.
"""

from datetime import date, datetime
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone

from apps.catalogo.models import Exercicio
from apps.pca import congelamento
from apps.pca.models import Reuniao, json_canonico
from apps.pca.relatorio_reuniao import apurar_relatorio


class Command(BaseCommand):
    help = "Apura os fatos do relatório da reunião contra a cópia do banco no corte (uso interno)."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--banco", required=True)
        parser.add_argument("--corte", required=True)
        parser.add_argument("--exercicio", required=True, type=int)
        parser.add_argument("--reuniao", default="")
        parser.add_argument("--de", required=True)
        parser.add_argument("--ate", required=True)
        parser.add_argument("--usuario", default="")

    def handle(self, *args, **opcoes):
        ativo = Path(connection.settings_dict["NAME"]).resolve()
        if ativo != Path(opcoes["banco"]).resolve():
            raise CommandError("Recusado: o banco ativo não é a cópia informada em --banco.")
        corte = datetime.fromisoformat(opcoes["corte"])
        if timezone.is_naive(corte):
            raise CommandError("--corte precisa de fuso horário.")
        try:
            exercicio = Exercicio.objects.get(pk=opcoes["exercicio"])
        except Exercicio.DoesNotExist:
            raise CommandError("Exercício inexistente na cópia.") from None
        reuniao = None
        if opcoes["reuniao"]:
            # Reunião posterior ao corte não existe na cópia: o relatório sai sem reunião.
            reuniao = Reuniao.objects.select_related("condutor").filter(pk=int(opcoes["reuniao"])).first()
        usuario = None
        if opcoes["usuario"]:
            usuario = get_user_model().objects.filter(pk=int(opcoes["usuario"])).first()
        hoje = timezone.localtime(corte).date()
        with mock.patch("django.utils.timezone.now", return_value=corte):
            fatos = apurar_relatorio(
                exercicio=exercicio, reuniao=reuniao, de=date.fromisoformat(opcoes["de"]),
                ate=date.fromisoformat(opcoes["ate"]), usuario=usuario, hoje=hoje,
            )
        self.stdout.write(json_canonico(fatos), ending="")
