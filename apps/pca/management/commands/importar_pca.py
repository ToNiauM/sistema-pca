"""Comando de CLI que resolve os argumentos (caminho, --usuario, --dry-run,
--exercicio) e delega o import inteiro a executar_import. A lógica de
import vive só no executor; este Command não a duplica, para que a tela de
importação do admin chame exatamente o mesmo código."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.catalogo.models import Exercicio
from apps.pca.importacao.executor import USUARIO_PADRAO, executar_import

CAMINHO_PADRAO = "apps/pca/fixtures/modelo-controle-exemplo.xlsx"


class Command(BaseCommand):
    help = (
        "Importa apps/pca/fixtures/modelo-controle-exemplo.xlsx (fixture de "
        "exemplo, 30 processos fictícios) ou o caminho informado. "
        "Idempotente, auditado sob o usuário de serviço. "
        "--dry-run roda tudo sem persistir."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "caminho",
            nargs="?",
            default=CAMINHO_PADRAO,
            help=f"Caminho do .xlsx (default: '{CAMINHO_PADRAO}' na raiz do repo).",
        )
        parser.add_argument(
            "--usuario",
            default=USUARIO_PADRAO,
            help=f"E-mail do usuário que assina o histórico (default: {USUARIO_PADRAO}).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Roda o import e emite o relatório de conferência sem gravar nada.",
        )
        parser.add_argument(
            "--exercicio",
            type=int,
            required=True,
            help="Ano do exercício existente que receberá a recuperação.",
        )

    def handle(self, *args, **options):
        caminho = options["caminho"]
        dry_run = options["dry_run"]
        ano_exercicio = options["exercicio"]

        try:
            exercicio = Exercicio.objects.get(ano=ano_exercicio)
        except Exercicio.DoesNotExist as exc:
            raise CommandError(
                f"Exercício {ano_exercicio} não existe. "
                "A recuperação exige um exercício previamente criado; "
                "não é possível criar um exercício pelo importar_pca."
            ) from exc

        usuario_model = get_user_model()
        try:
            usuario = usuario_model.objects.get(email=options["usuario"])
        except usuario_model.DoesNotExist as exc:
            raise CommandError(
                f"Usuário '{options['usuario']}' não existe. "
                "'importador@pca.local' nasce pela migração de dados "
                "core.0003_usuario_importacao — rode as migrations primeiro, "
                "ou informe --usuario com um e-mail existente."
            ) from exc

        executar_import(
            caminho, usuario, exercicio, dry_run, escrever_stdout=self.stdout.write
        )

        self.stdout.write(self.style.SUCCESS(
            "Import concluído (dry-run, nada gravado)." if dry_run else "Import concluído."
        ))
