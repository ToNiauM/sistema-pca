"""Comando `ia_limpar` — limpeza sob demanda de
conversas expiradas/metadados de quota do Assistente do PCA e retenção da
fila de reindexação. Nunca importa nem consulta o domínio do PCA — só os
três SQLite auxiliares de `apps.assistente`; funciona SEM `IA_API_KEY`
(não depende de rede/cliente — mesma garantia de `apps.assistente.estado.
limpar_se_necessario`, que o laço do robô já chama a cada passagem)."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.assistente import estado, fila


class Command(BaseCommand):
    help = (
        "Limpa conversas expiradas, metadados de quota com mais de 7 dias, "
        "andamento órfão (thread morta há mais de 1h) e aplica retenção da "
        "fila de reindexação do Assistente do PCA."
    )

    def handle(self, *args, **options):
        agora = timezone.now()
        try:
            conversas_apagadas = estado.limpar_expiradas(agora)
            metadados_apagados = estado.limpar_metadados(timezone.localdate(agora))
            andamento_apagado = estado.limpar_andamento_orfao(agora)
        except estado.EstadoIndisponivel as exc:
            raise CommandError(str(exc)) from None

        pedidos_removidos = fila.aplicar_retencao()

        self.stdout.write(
            f"conversas expiradas removidas: {conversas_apagadas} · "
            f"metadados de quota removidos: {metadados_apagados} · "
            f"andamento órfão removido: {andamento_apagado} · "
            f"pedidos antigos da fila removidos: {pedidos_removidos}"
        )
