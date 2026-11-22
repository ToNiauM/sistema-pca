"""Comando `ia_indexar` — publica uma geração do índice
semântico do Assistente do PCA. Incremental por padrão (reaproveita
embeddings de texto igual); `--completo` força reconstrução total. Nunca
chamado dentro de uma request; não mexe em `estado.sqlite3`/
`conversas.sqlite3` (quota/conversas), mesmo com `--completo`."""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.assistente import cliente as cliente_mod
from apps.assistente import indice


class Command(BaseCommand):
    help = "Publica uma geração do índice semântico do Assistente do PCA."

    def add_arguments(self, parser):
        parser.add_argument(
            "--completo",
            action="store_true",
            help="Reconstrói o índice inteiro (reembedda tudo), mesmo sem troca de modelo.",
        )

    def handle(self, *args, **options):
        if not settings.IA_API_KEY:
            raise CommandError("IA_API_KEY não configurada — indexação desabilitada")

        cliente = cliente_mod.criar_cliente()
        try:
            resumo = indice.indexar(
                cliente,
                completo=options["completo"],
                agora=timezone.now(),
                stdout=self.stdout,
            )
        except indice.IndiceOcupado:
            self.stderr.write("indexação já em andamento")
            raise SystemExit(1) from None
