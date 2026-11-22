"""Comando único que o agendador periódico do host chama (Fase 32/Plano
32-04, spec §6/§7): coleta + aplica em sequência, com lock de 3h e
registro de execução em `data/sei/execucoes/<carimbo>.json`. NUNCA instala,
escreve ou sugere uma entrada de agendamento — essa linha é só documentada
em `docs/operacao.md`, nunca executada por este comando.

`from apps.pca.sei import coletor` é importado DENTRO de `handle()` (mesmo
motivo de `sei_coletar.py` — `playwright` só existe na imagem `robo`).
"""

from __future__ import annotations

import sys

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.catalogo.models import SituacaoExercicio
from apps.pca.models import Estado, Processo
from apps.pca.sei import aplicador, execucoes, links
from apps.pca.sei.regras import propor
from apps.pca.servicos import eventos_financeiros


def _campos_atuais(processo: Processo) -> dict:
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
        # Ver comentário em `sei_aplicar.py::campos_atuais_de`.
        "unidade_sei_atual": processo.unidade_sei_atual,
        "unidade_sei_atual_desde": processo.unidade_sei_atual_desde,
    }


class Command(BaseCommand):
    help = (
        "Coleta + aplica em sequência, com lock de 3h e registro de "
        "execução — o comando que o cron do host chama (spec §6)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--simular",
            action="store_true",
            help="Coleta e calcula tudo, mas não grava nada no banco.",
        )

    def handle(self, *args, **options):
        # --- passo 1: lock (spec §6 passo 1) ---------------------------
        if not execucoes.adquirir_lock():
            self.stderr.write("execução em andamento")
            raise SystemExit(2)

        carimbo = execucoes.novo_carimbo()
        iniciado_em = timezone.localtime().isoformat()

        try:
            # --- passo 2: alvos — itens ativos do exercício aberto ------
            qs = (
                Processo.objects.filter(
                    exercicio__situacao=SituacaoExercicio.ABERTO,
                    estado=Estado.ATIVO,
                )
                .select_related("exercicio", "instrumento_contratual", "modalidade")
                .prefetch_related("numeros_sei")
            )

            alvos = []
            processos_por_item: dict[tuple[int, int], Processo] = {}
            for processo in qs:
                chave = (processo.item_pca, processo.exercicio.ano)
                processos_por_item[chave] = processo
                for numero_sei in processo.numeros_sei.all():
                    alvos.append({
                        "item_pca": processo.item_pca,
                        "exercicio": processo.exercicio.ano,
                        "numero_sei": numero_sei.numero_sei,
                    })
            # Itens ativos sem nenhum numero_sei permanecem em
            # `processos_por_item` sem entrada em `alvos` — `propor()`
            # recebe `processos_coletados=[]` para eles e produz, sozinho, a
            # pendência `sem_numero_sei` (regras.py passo 1); nenhum
            # tratamento especial é necessário aqui.

            from apps.pca.sei import coletor  # import local — ver docstring do módulo

            # --- Fase 34: carrega o cache incremental
            # antes da coleta; sei_sincronizar sempre usa o cache
            # (forcar=False) e imprime uma linha de progresso por processo
            #via self.stdout, com flush.
            # `docker compose exec` (não `docker compose logs -f robo`) é
            # onde essas linhas de fato aparecem — por isso o mesmo
            # progresso também grava em execucoes/<carimbo>.log e atualiza
            # o lock em_execucao (item/k/total/contadores), canal ao vivo
            # para o card "Sincronização com o SEI" do Início.
            cache = execucoes.ler_cache()
            # Fase 42: carregado uma vez, antes da
            # coleta, SÓ LEITURA — `sei_sincronizar` nunca grava
            # `extensao.json` (quem grava é `POST /api/sei/coleta`). Repassado a `coletor.coletar` abaixo junto com
            # `cache`/`forcar`.
            mapa_extensao = execucoes.ler_extensao()
            log_execucao = execucoes.abrir_log_execucao(carimbo)
            contadores = {"coletados": 0, "pulados": 0, "erros": 0}

            def progresso(mensagem):
                self.stdout.write(mensagem)
                self.stdout.flush()
                log_execucao(mensagem)
                info = execucoes.interpretar_linha_progresso(mensagem)
                if info is not None:
                    if info["resultado"] == "coletado":
                        contadores["coletados"] += 1
                    elif info["resultado"] == "pulado":
                        contadores["pulados"] += 1
                    elif info["resultado"] == "erro":
                        contadores["erros"] += 1
                    execucoes.atualizar_progresso(
                        carimbo,
                        item=info["item"],
                        k=info["k"],
                        total=info["total"],
                        coletados=contadores["coletados"],
                        pulados=contadores["pulados"],
                        erros=contadores["erros"],
                        ultima_linha=mensagem,
                    )

            # --- passo 4: coleta, exceção fatal é a última defesa antes
            # do cron (login recusado, SEI fora do ar, captcha) ----------
            try:
                dados_coleta = coletor.coletar(
                    alvos,
                    cache=cache,
                    forcar=False,
                    progresso=progresso,
                    extensao=mapa_extensao,
                    pular_se_extensao_h=getattr(settings, "SEI_PULAR_SE_EXTENSAO_H", 24),
                )
            except Exception as exc:  # noqa: BLE001 — última defesa antes do cron
                dados_execucao = {
                    "iniciado_em": iniciado_em,
                    "terminado_em": timezone.localtime().isoformat(),
                    "status": "erro",
                    "totais": {},
                    "alterados": [],
                    "pendencias": [],
                    "erros": [],
                    "mensagem": str(exc)[:500],
                    "metricas": {},
                }
                execucoes.gravar_execucao(carimbo, dados_execucao)
                sys.exit(1)

            # --- passo 5: grava a coleta (mesmo carimbo da execução) -----
            execucoes.gravar_coleta(carimbo, dados_coleta)

            # Fase 34: grava o cache UMA vez, depois da coleta
            # (nunca no caminho de exceção fatal acima, que já sai cedo sem
            # ter coletado nada para gravar).
            execucoes.gravar_cache(cache)

            # Mantém data/sei/links.json em dia sozinho a
            # cada varredura — primeiro absorve o que esta coleta já trouxe,
            # depois resolve (barato, sem histórico) os números dos alvos
            # ainda ausentes do mapa. É isto que garante 100% de cobertura
            # mesmo para números fora do exercício aberto já resolvidos por
            # uma varredura anterior, e cobre os novos desta.
            mapa_links = execucoes.ler_links()
            links.atualizar_de_coleta(mapa_links, dados_coleta)
            numeros_pendentes = sorted({
                alvo["numero_sei"] for alvo in alvos
                if alvo["numero_sei"] not in mapa_links.get("processos", {})
            })
            if numeros_pendentes:
                dados_links_extra = coletor.resolver_links(numeros_pendentes)
                links.atualizar_de_coleta(mapa_links, dados_links_extra)
            execucoes.gravar_links(mapa_links)

            agrupado: dict[tuple[int, int], list[dict]] = {}
            for processo_coletado in dados_coleta.get("processos", []):
                chave = (processo_coletado.get("item_pca"), processo_coletado.get("exercicio"))
                agrupado.setdefault(chave, []).append(processo_coletado)

            # --- passo 6: regras.propor por item -------------------------
            propostas = [
                propor(
                    item_pca=chave[0],
                    exercicio=chave[1],
                    campos_atuais=_campos_atuais(processo),
                    processos_coletados=agrupado.get(chave, []),
                )
                for chave, processo in processos_por_item.items()
            ]

            # --- passo 7: aplicação (ou simulação) ------------------------
            resumo = aplicador.aplicar(propostas, simular=options["simular"])

            # Fase 36 — `processos_por_item` já é
            # `{(item_pca, exercicio): processo}`; fiar `eventos_financeiros.
            # sincronizar` por item com `serie_valores`, nunca em `--simular`.
            if not options["simular"]:
                for chave_serie, serie in resumo["series"].items():
                    item_pca, exercicio = execucoes.decompor_chave_item(chave_serie)
                    processo = processos_por_item.get((item_pca, exercicio))
                    if processo is not None:
                        eventos_financeiros.sincronizar(processo, serie)

            # --- passo 8: JSON de execução, formato exato do §6 ----------
            processos_coletados_lista = dados_coleta.get("processos", [])
            status = "simulado" if options["simular"] else "ok"
            dados_execucao = {
                "iniciado_em": iniciado_em,
                "terminado_em": timezone.localtime().isoformat(),
                "status": status,
                "totais": {
                    "itens": len(processos_por_item),
                    "processos": len(alvos),
                    "coletados": sum(
                        1 for p in processos_coletados_lista if p.get("resultado") == "ok"
                    ),
                    "nao_encontrados": sum(
                        1 for p in processos_coletados_lista if p.get("resultado") != "ok"
                    ),
                    "erros": len(resumo["erros"]),
                    "itens_alterados": resumo["itens_alterados"],
                    "pendencias_novas": resumo["pendencias_novas"],
                    "eventos_gravados": resumo["eventos_gravados"],
                },
                "alterados": resumo["alterados"],
                "pendencias": resumo["pendencias"],
                "series": resumo["series"],
                "erros": resumo["erros"],
                "mensagem": None,
                "metricas": dados_coleta.get("metricas", {}),
            }
            execucoes.gravar_execucao(carimbo, dados_execucao)

            # A varredura registra a última consulta de
            # CADA item visitado ("pulado" incluso — o histórico foi
            # conferido), nunca em --simular. Antes só `sei_atender` gravava,
            # e a ficha do assistente dizia "SEI: não disponível" para o resto.
            if not options["simular"]:
                execucoes.registrar_ultimas_consultas(
                    execucoes.resumir_consultas_da_coleta(
                        processos_coletados_lista, dados_execucao["terminado_em"]
                    )
                )

            # --- passo 9: retenção -----------------------------------------
            execucoes.aplicar_retencao("coletas", 60)
            execucoes.aplicar_retencao("execucoes", 60)

            mensagem_final = (
                f"Sincronização concluída ({status}): "
                f"{dados_execucao['totais']['itens_alterados']} item(ns) alterado(s), "
                f"{dados_execucao['totais']['pendencias_novas']} pendência(s) nova(s)."
            )
            log_execucao(mensagem_final)
            self.stdout.write(self.style.SUCCESS(mensagem_final))
            sys.exit(0)
        finally:
            # --- passo 6 do §6 (numeração da spec): sempre solta o lock ---
            execucoes.liberar_lock()
