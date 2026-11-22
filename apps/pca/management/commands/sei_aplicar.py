"""Aplica um JSON de coleta (produzido por `sei_coletar`/`sei_sincronizar`)
pelas regras puras de `apps.pca.sei.regras` e pelo aplicador auditado de
`apps.pca.sei.aplicador` (Fase 32, spec §3.5).

`--simular` imprime a tabela de alterações/pendências e não grava
absolutamente nada — nem `Processo`, nem `Acompanhamento`, nem
`data/sei/estado.json` (delegado inteiramente a
`aplicador.aplicar(simular=True)`).

`apps.pca.sei.regras`/`apps.pca.sei.aplicador` nunca importam `playwright`
— seguros no topo do arquivo, diferente de `sei_coletar.py`/
`sei_sincronizar.py`/`sei_atender.py`, que tocam `apps.pca.sei.coletor`.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.pca.models import Processo
from apps.pca.sei import aplicador, execucoes
from apps.pca.sei.regras import propor
from apps.pca.servicos import eventos_financeiros


def campos_atuais_de(processo: Processo) -> dict:
    """Retrato dos 6 campos de tramitação (Fase 32) + 6 campos novos de
    execução contratual (Fase 33) que `propor()` compara — mesmo
    formato usado pelos testes de `apps.pca.sei.aplicador` (32-03/33-02)."""
    return {
        "data_assinatura_contrato": processo.data_assinatura_contrato,
        "numero_instrumento_contratual": processo.numero_instrumento_contratual,
        "instrumento_contratual_nome_normalizado": (
            processo.instrumento_contratual.nome_normalizado
            if processo.instrumento_contratual_id
            else None
        ),
        "valor_contratado": processo.valor_contratado,
        "data_recebimento_gelic": processo.data_recebimento_gelic,
        "fornecedor_razao_social": processo.fornecedor_razao_social,
        "fornecedor_cnpj": processo.fornecedor_cnpj,
        "modalidade_nome_normalizado": (
            processo.modalidade.nome_normalizado if processo.modalidade_id else None
        ),
        "numero_contratacao": processo.numero_contratacao,
        "vigencia_inicio": processo.vigencia_inicio,
        "vigencia_fim": processo.vigencia_fim,
        # Sem os dois campos aqui, `propor()` (passo 7b)
        # sempre compararia contra `.get(..., "")`/`.get(...)` (ausência) e
        # reproporia a mesma unidade a cada varredura, mesmo sem mudança.
        "unidade_sei_atual": processo.unidade_sei_atual,
        "unidade_sei_atual_desde": processo.unidade_sei_atual_desde,
    }


class Command(BaseCommand):
    help = (
        "Aplica um JSON de coleta do SEI (sei_coletar) pelas regras puras e "
        "pelo aplicador auditado. --simular só imprime a tabela de "
        "alterações/pendências, sem gravar nada."
    )

    def add_arguments(self, parser):
        parser.add_argument("arquivo", help="Caminho do JSON de coleta.")
        parser.add_argument(
            "--simular",
            action="store_true",
            help="Calcula tudo e imprime a tabela, sem gravar nada.",
        )

    def handle(self, *args, **options):
        caminho = Path(options["arquivo"])
        if not caminho.exists():
            raise CommandError(f"Arquivo de coleta não encontrado: {caminho}")

        try:
            dados = json.loads(caminho.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"Arquivo de coleta inválido: {exc}") from exc

        # Achado dados B8 (QA 30/09/2026) — um JSON válido mas fora da
        # ESTRUTURA esperada (não é um objeto, ou "processos" não é lista)
        # derrubava o comando com AttributeError/TypeError crus; agora
        # sempre termina em CommandError amigável.
        if not isinstance(dados, dict) or not isinstance(dados.get("processos"), list):
            raise CommandError(
                "Arquivo de coleta fora do formato esperado (precisa de um "
                f"objeto JSON com a chave 'processos' como lista): {caminho}"
            )

        agrupado: dict[tuple[int, int], list[dict]] = {}
        for processo_coletado in dados.get("processos", []):
            if not isinstance(processo_coletado, dict):
                raise CommandError(
                    f"Entrada inválida em 'processos' do arquivo de coleta: {caminho}"
                )
            chave = (processo_coletado.get("item_pca"), processo_coletado.get("exercicio"))
            agrupado.setdefault(chave, []).append(processo_coletado)

        propostas = []
        # Fase 36 — retém o `Processo` de cada item
        # para, depois de `aplicador.aplicar()`, fiar `eventos_financeiros.
        # sincronizar` por item com `serie_valores` (nunca em `--simular`).
        processos_por_chave: dict[tuple[int, int], Processo] = {}
        for (item_pca, exercicio), processos_coletados in agrupado.items():
            processo = (
                Processo.objects.select_related("instrumento_contratual")
                .filter(exercicio__ano=exercicio, item_pca=item_pca)
                .first()
            )
            if processo is None:
                self.stderr.write(
                    f"Item {item_pca}/{exercicio}: processo não encontrado no PCA — ignorado."
                )
                continue
            processos_por_chave[(item_pca, exercicio)] = processo
            propostas.append(
                propor(
                    item_pca=item_pca,
                    exercicio=exercicio,
                    campos_atuais=campos_atuais_de(processo),
                    processos_coletados=processos_coletados,
                )
            )

        resumo = aplicador.aplicar(propostas, simular=options["simular"])

        if not options["simular"]:
            # Mesma regra do `sei_sincronizar` — a data é
            # a da COLETA aplicada (`executado_em`), não "agora".
            execucoes.registrar_ultimas_consultas(
                execucoes.resumir_consultas_da_coleta(
                    dados.get("processos", []), dados.get("executado_em")
                )
            )
            for chave_serie, serie in resumo["series"].items():
                item_pca, exercicio = execucoes.decompor_chave_item(chave_serie)
                processo = processos_por_chave.get((item_pca, exercicio))
                if processo is not None:
                    eventos_financeiros.sincronizar(processo, serie)

        if options["simular"]:
            self.stdout.write("Modo simulado — nada foi gravado.")
            for alterado in resumo["alterados"]:
                self.stdout.write(
                    f"  item {alterado['item']}: {', '.join(alterado['campos'])}"
                )
            for pendencia in resumo["pendencias"]:
                self.stdout.write(
                    f"  pendência item {pendencia['item']} [{pendencia['chave']}]: "
                    f"{pendencia['texto']}"
                )
            if not resumo["alterados"] and not resumo["pendencias"]:
                self.stdout.write("  nenhuma alteração nem pendência.")
        else:
            self.stdout.write(self.style.SUCCESS(
                f"{resumo['itens_alterados']} item(ns) alterado(s), "
                f"{resumo['pendencias_novas']} pendência(s) nova(s), "
                f"{resumo['eventos_gravados']} evento(s) gravado(s)."
            ))
