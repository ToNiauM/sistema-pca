"""Resolvedor barato de hiperlinks SEI: garante 100% de
cobertura de `data/sei/links.json` — não só os itens ativos do exercício
aberto que a varredura diária (`sei_sincronizar`) visita, mas todo
`ProcessoSEI.numero_sei` distinto do banco.

`from apps.pca.sei import coletor` importado DENTRO de `handle()` — mesma
regra dos outros 4 comandos que tocam `apps.pca.sei.coletor` (Playwright só
existe na imagem `robo`).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.pca.models import ProcessoSEI
from apps.pca.sei import execucoes, links


class Command(BaseCommand):
    help = (
        "Resolve hiperlinks SEI (id_procedimento/id_documento) para 100% "
        "dos números SEI do banco, gravando data/sei/links.json."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--todos",
            action="store_true",
            help="Relê TODO numero_sei do banco, mesmo já resolvido "
            "(default: só os ainda ausentes de links.json).",
        )

    def handle(self, *args, **options):
        mapa_links = execucoes.ler_links()

        numeros_banco = list(
            ProcessoSEI.objects.order_by("numero_sei")
            .values_list("numero_sei", flat=True)
            .distinct()
        )

        if options["todos"]:
            pendentes = numeros_banco
        else:
            pendentes = [
                numero for numero in numeros_banco if numero not in mapa_links.get("processos", {})
            ]

        if not pendentes:
            self.stdout.write(self.style.SUCCESS(
                "Nenhum número SEI pendente — links.json já cobre 100% do banco."
            ))
            return

        from apps.pca.sei import coletor  # import local — ver docstring do módulo

        # Mesmo padrão de progresso de sei_sincronizar
        # (stdout + log próprio), mas este comando NUNCA participa do lock
        # em_execucao — não é a varredura noturna, só ganha stdout + .log.
        carimbo = execucoes.novo_carimbo()
        log_execucao = execucoes.abrir_log_execucao(carimbo)

        def progresso(mensagem):
            self.stdout.write(mensagem)
            self.stdout.flush()
            log_execucao(mensagem)

        dados = coletor.resolver_links(pendentes, progresso=progresso)
        links.atualizar_de_coleta(mapa_links, dados)
        execucoes.gravar_links(mapa_links)

        resolvidos = sum(1 for p in dados.get("processos", []) if p.get("resultado") == "ok")
        nao_encontrados = sum(
            1 for p in dados.get("processos", []) if p.get("resultado") == "nao_encontrado"
        )
        erros = sum(1 for p in dados.get("processos", []) if p.get("resultado") == "erro")
        self.stdout.write(self.style.SUCCESS(
            f"links.json atualizado: {len(pendentes)} número(s) consultado(s), "
            f"{resolvidos} resolvido(s), {nao_encontrados} não encontrado(s), {erros} erro(s)."
        ))
