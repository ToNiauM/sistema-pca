"""Comando de CLI que grava em sys.stdout.buffer o .xlsx pré-preenchido com
os processos/acompanhamentos atuais do banco, para o usuário confrontar
linha a linha com os controles dele fora do sistema. Delega o conteúdo a
gerar_modelo_preenchido; este Command só resolve o exercício e escreve os
bytes.

Só faz SELECT, nenhuma escrita no banco. O comando não escreve mais nada em
stdout além do .xlsx binário, para permitir redirecionamento puro no host;
qualquer mensagem de progresso vai para sys.stderr."""

import sys

from django.core.management.base import BaseCommand, CommandError

from apps.catalogo.models import Exercicio, SituacaoExercicio
from apps.pca.importacao.modelo import gerar_modelo_preenchido


class Command(BaseCommand):
    help = (
        "Gera em stdout (binário) o .xlsx pré-preenchido com os processos e "
        "acompanhamentos atuais do banco, nas mesmas colunas que "
        "`importar_pca` consome. Redirecione a saída para um arquivo: "
        "`manage.py gerar_modelo_dados_atuais > modelo.xlsx`."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--exercicio",
            type=int,
            default=None,
            help=(
                "Ano do exercício a exportar (default: o exercício ABERTO "
                "mais recente)."
            ),
        )

    def handle(self, *args, **options):
        ano_exercicio = options["exercicio"]

        if ano_exercicio is not None:
            try:
                exercicio = Exercicio.objects.get(ano=ano_exercicio)
            except Exercicio.DoesNotExist as exc:
                raise CommandError(
                    f"Exercício {ano_exercicio} não existe."
                ) from exc
        else:
            exercicio = (
                Exercicio.objects.filter(situacao=SituacaoExercicio.ABERTO)
                .order_by("-ano")
                .first()
            )
            if exercicio is None:
                raise CommandError(
                    "Nenhum exercício ABERTO encontrado. Informe --exercicio "
                    "explicitamente."
                )

        print(
            f"Gerando modelo pré-preenchido do exercício {exercicio.ano}...",
            file=sys.stderr,
        )
        buffer = gerar_modelo_preenchido(exercicio)
        sys.stdout.buffer.write(buffer.getvalue())
        print("Concluído.", file=sys.stderr)
