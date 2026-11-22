"""Coleta os processos SEI dos itens ativos do exercício aberto e grava o
JSON em `data/sei/coletas/<carimbo>.json` (Fase 32,
spec §3.5). Nunca toca o banco — só lê `Processo`/`ProcessoSEI` para montar
`alvos` e devolve o envelope exatamente como `apps.pca.sei.coletor.coletar`
o produziu, sem aplicar nenhuma `Proposta` (isso é trabalho de
`sei_aplicar`/`sei_sincronizar`).

`from apps.pca.sei import coletor` é importado DENTRO de `handle()`, nunca no
topo do arquivo — `coletor.py` importa `playwright` de forma preguiçosa, mas
mesmo esse import preguiçoso só existe na imagem `robo`; importar o módulo
inteiro no topo quebraria o autodiscovery do Django rodando na imagem `web`
(mesma regra para os 4 comandos deste plano que tocam `apps.pca.sei.coletor`).
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.catalogo.models import SituacaoExercicio
from apps.pca.models import Estado, Processo
from apps.pca.sei import execucoes, links
from apps.pca.sei.extracao import VERSAO_EXTRACAO_DOCUMENTO


class Command(BaseCommand):
    help = (
        "Coleta os processos SEI dos itens ativos do exercício aberto e "
        "grava o JSON de coleta em data/sei/coletas/. Não aplica nada ao "
        "banco — use sei_aplicar sobre o arquivo gerado."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--itens",
            type=str,
            default=None,
            help="Lista de item_pca separados por vírgula (ex.: '1,2,3'). "
            "Default: todos os itens ativos do exercício aberto.",
        )
        parser.add_argument(
            "--saida",
            type=str,
            default=None,
            help="Caminho extra para gravar uma cópia do JSON de coleta "
            "(além do registro padrão em data/sei/coletas/).",
        )
        parser.add_argument(
            "--forcar",
            action="store_true",
            help="Ignora o cache e relê tudo do zero (default: usa o cache).",
        )
        parser.add_argument(
            "--reprocessar-documentos",
            action="store_true",
            help=(
                "Relê documentos do cache sem texto_corpo/nome (versão de "
                "extração antiga) nas duas representações; não aplica nada "
                "ao PCA."
            ),
        )

    def handle(self, *args, **options):
        from apps.pca.sei import coletor  # import local — ver docstring do módulo

        itens = None
        if options["itens"]:
            itens = [int(pedaco) for pedaco in options["itens"].split(",") if pedaco.strip()]

        qs = (
            Processo.objects.filter(
                exercicio__situacao=SituacaoExercicio.ABERTO,
                estado=Estado.ATIVO,
            )
            .select_related("exercicio")
            .prefetch_related("numeros_sei")
        )
        if itens:
            qs = qs.filter(item_pca__in=itens)

        alvos = [
            {
                "item_pca": processo.item_pca,
                "exercicio": processo.exercicio.ano,
                "numero_sei": numero_sei.numero_sei,
            }
            for processo in qs
            for numero_sei in processo.numeros_sei.all()
        ]

        # Fase 34: --forcar ignora o cache e relê tudo do zero;
        # default usa o cache (mesmo comportamento incremental de
        # sei_sincronizar, sem imprimir progresso — comando de depuração).
        cache = execucoes.ler_cache()
        dados = coletor.coletar(
            alvos,
            cache=cache,
            forcar=options["forcar"],
            reprocessar_documentos=options["reprocessar_documentos"],
        )
        execucoes.gravar_cache(cache)

        # Mantém data/sei/links.json em dia — sem o passo
        # extra de resolver pendentes (só sei_sincronizar faz isso).
        mapa_links = execucoes.ler_links()
        links.atualizar_de_coleta(mapa_links, dados)
        execucoes.gravar_links(mapa_links)

        carimbo = execucoes.novo_carimbo()
        caminho = execucoes.gravar_coleta(carimbo, dados)

        if options["saida"]:
            destino = Path(options["saida"])
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(
                json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self.stdout.write(f"Cópia extra gravada em {destino}.")

        processos_coletados = dados.get("processos", [])
        ok = sum(1 for p in processos_coletados if p.get("resultado") == "ok")
        erros = len(processos_coletados) - ok
        self.stdout.write(self.style.SUCCESS(
            f"Coleta gravada em {caminho} — {len(processos_coletados)} processo(s) "
            f"consultado(s), {ok} ok, {erros} erro(s)."
        ))

        if options["reprocessar_documentos"]:
            relidos = 0
            preservados = 0
            for processo in processos_coletados:
                for doc in processo.get("documentos_contratuais") or []:
                    if doc.get("reprocessamento_erro"):
                        preservados += 1
                    elif (
                        not doc.get("do_cache")
                        and doc.get("versao_extracao") == VERSAO_EXTRACAO_DOCUMENTO
                    ):
                        relidos += 1
            self.stdout.write(
                f"documentos relidos: {relidos} · falhas preservadas: {preservados}"
            )
