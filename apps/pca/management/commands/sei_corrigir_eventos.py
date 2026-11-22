"""Correção pontual dos `EventoFinanceiro` gravados pelo robô SEI com as
regras antigas do valor contratado (debug robo-valor-contratado-item64,
20/10/2026; decisão do usuário: comando com simulação padrão e gravação só
com `--aplicar`).

Reaplica as regras ATUAIS (`apps.pca.sei.regras.propor`) sobre um JSON de
coleta (padrão: o mais recente de `data/sei/coletas/`) e compara a série de
valores resultante com os eventos já gravados de cada item:

- evento de origem `robo` cujo documento está na coleta mas não entra mais
  na série (minuta sem assinatura, aditivo/contrato assinado só pelo CFC,
  valores por item sem global único...) → APAGAR;
- evento `robo` na série com `valor`/`valor_mensal`/`periodicidade`
  diferentes (ex.: o mensal do contrato do item 64 gravado como se fosse o
  valor) → ALTERAR;
- eventos `manual`, eventos sem o documento na coleta e campos fora de
  `valor`/`valor_mensal`/`periodicidade` nunca são tocados.

Documentos da coleta lidos por uma extração anterior à atual são relidos do
`texto_corpo` gravado (`montagem.reler_valores_do_corpo`) — o relatório
mostra a correção completa sem esperar `sei_coletar --reprocessar-
documentos`.

SEM `--aplicar` o comando é SOMENTE LEITURA: não grava evento, histórico,
usuário técnico, lock nem arquivo — só imprime o relatório. Com
`--aplicar`, toma o lock do robô (`data/sei/em_execucao`), grava tudo numa
transação, instância a instância (`simple_history` com autor = usuário
técnico do robô e motivo "sei_corrigir_eventos: ...").

Nunca abre o SEI: `apps.pca.sei.coletor`/Playwright não são importados.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.pca.management.commands.sei_aplicar import campos_atuais_de
from apps.pca.models import Processo
from apps.pca.sei import execucoes
from apps.pca.sei.montagem import reler_valores_do_corpo
from apps.pca.sei.regras import propor
from apps.pca.servicos import eventos_financeiros


def _fmt_valor(valor) -> str:
    if valor is None:
        return "vazio"
    bruto = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {bruto}"


def _fmt_campo(campo: str, valor) -> str:
    if campo in ("valor", "valor_mensal"):
        return _fmt_valor(valor)
    return valor if valor not in (None, "") else "vazio"


def _fmt_data(data) -> str:
    return data.strftime("%d/%m/%Y") if data else "sem data"


def _ultima_coleta() -> Path | None:
    pasta = execucoes.diretorio_base() / "coletas"
    if not pasta.exists():
        return None
    arquivos = sorted(pasta.glob("*.json"))
    return arquivos[-1] if arquivos else None


class Command(BaseCommand):
    help = (
        "Correção pontual dos eventos financeiros gravados pelo robô SEI com as "
        "regras antigas do valor contratado. Sem --aplicar só imprime o relatório "
        "(nada é gravado)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--coleta",
            help="JSON de coleta a usar (padrão: o mais recente de data/sei/coletas/).",
        )
        parser.add_argument(
            "--aplicar",
            action="store_true",
            help="Grava as correções (apaga/altera os eventos listados). Sem esta "
            "opção, nada é gravado.",
        )

    def handle(self, *args, **options):
        caminho = Path(options["coleta"]) if options.get("coleta") else _ultima_coleta()
        if caminho is None or not caminho.exists():
            raise CommandError(f"Arquivo de coleta não encontrado: {caminho or 'data/sei/coletas/'}")
        try:
            dados = json.loads(caminho.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"Arquivo de coleta inválido: {exc}") from exc
        if not isinstance(dados, dict) or not isinstance(dados.get("processos"), list):
            raise CommandError(
                "Arquivo de coleta fora do formato esperado (precisa de um objeto JSON "
                f"com a chave 'processos' como lista): {caminho}"
            )

        aplicar = options["aplicar"]
        self.stdout.write(
            "Correção dos eventos financeiros do robô SEI — "
            + ("APLICAÇÃO (grava)" if aplicar else "SIMULAÇÃO (nada é gravado)")
        )
        self.stdout.write(f"Coleta: {caminho} (executada em {dados.get('executado_em') or '?'})")

        agrupado: dict[tuple, list[dict]] = {}
        for processo_coletado in dados["processos"]:
            if not isinstance(processo_coletado, dict):
                raise CommandError(f"Entrada inválida em 'processos' do arquivo de coleta: {caminho}")
            chave = (processo_coletado.get("item_pca"), processo_coletado.get("exercicio"))
            agrupado.setdefault(chave, []).append(processo_coletado)

        relidos = 0
        diagnosticos = []
        for (item_pca, exercicio), processos_coletados in sorted(
            agrupado.items(), key=lambda par: (par[0][1] or 0, par[0][0] or 0)
        ):
            processo = (
                Processo.objects.select_related("instrumento_contratual", "modalidade")
                .filter(exercicio__ano=exercicio, item_pca=item_pca)
                .first()
            )
            if processo is None:
                continue
            documentos = {}
            coletados_relidos = []
            for processo_coletado in processos_coletados:
                copia = dict(processo_coletado)
                if processo_coletado.get("resultado") == "ok":
                    lista = []
                    for documento in processo_coletado.get("documentos_contratuais") or []:
                        documento, relido = reler_valores_do_corpo(documento)
                        relidos += relido
                        lista.append(documento)
                        if documento.get("protocolo"):
                            documentos[documento["protocolo"]] = documento
                    copia["documentos_contratuais"] = lista
                coletados_relidos.append(copia)
            proposta = propor(
                item_pca=item_pca,
                exercicio=exercicio,
                campos_atuais=campos_atuais_de(processo),
                processos_coletados=coletados_relidos,
            )
            diagnostico = eventos_financeiros.diagnosticar(
                processo, proposta.serie_valores, documentos
            )
            diagnosticos.append((item_pca, exercicio, processo, diagnostico))

        self.stdout.write(f"Documentos relidos do texto da coleta pela extração atual: {relidos}")
        self.stdout.write("")

        correcoes = []
        apagar = alterar = faltantes = manuais = fora = 0
        for item_pca, exercicio, _processo, diagnostico in diagnosticos:
            manuais += diagnostico.manuais
            fora += diagnostico.fora_da_coleta
            if not diagnostico.correcoes and not diagnostico.faltantes:
                continue
            self.stdout.write(f"Item {item_pca}/{exercicio}")
            for correcao in diagnostico.correcoes:
                evento = correcao.evento
                cabecalho = (
                    f"evento #{evento.pk} ({evento.tipo} {evento.protocolo_sei}, "
                    f"{_fmt_data(evento.data)}, {_fmt_valor(evento.valor)}"
                    f"{', ' + evento.periodicidade if evento.periodicidade else ''})"
                )
                if correcao.acao == "apagar":
                    apagar += 1
                    self.stdout.write(f"  APAGAR  {cabecalho}")
                else:
                    alterar += 1
                    self.stdout.write(f"  ALTERAR {cabecalho}")
                    for campo, (antes, depois) in correcao.campos.items():
                        self.stdout.write(
                            f"          {campo}: {_fmt_campo(campo, antes)} → {_fmt_campo(campo, depois)}"
                        )
                self.stdout.write(f"          motivo: {correcao.motivo}")
                correcoes.append(correcao)
            for entrada in diagnostico.faltantes:
                faltantes += 1
                self.stdout.write(
                    f"  (sem evento — a próxima sincronização cria) {entrada.get('tipo')} "
                    f"{entrada.get('protocolo')}, {_fmt_data(entrada.get('data'))}, "
                    f"{_fmt_valor(entrada.get('valor'))}"
                    f"{', ' + entrada['periodicidade'] if entrada.get('periodicidade') else ''}"
                )

        itens_com_correcao = sum(1 for *_x, d in diagnosticos if d.correcoes)
        self.stdout.write("")
        self.stdout.write(
            f"Resumo: {apagar} evento(s) a apagar e {alterar} a alterar em "
            f"{itens_com_correcao} item(ns), de {len(diagnosticos)} avaliado(s); "
            f"{faltantes} evento(s) que a sincronização ainda cria; {manuais} evento(s) "
            f"manual(is) e {fora} do robô sem o documento na coleta, nunca tocados."
        )

        if not aplicar:
            self.stdout.write(
                "Modo simulação — nada foi gravado. Para gravar: "
                "python manage.py sei_corrigir_eventos --aplicar"
            )
            return

        if not correcoes:
            self.stdout.write(self.style.SUCCESS("Nada a corrigir."))
            return

        # Import tardio: `_usuario_tecnico()` faz `get_or_create` do usuário
        # do robô — só no caminho que grava, nunca na simulação.
        from apps.pca.sei.aplicador import _usuario_tecnico

        if not execucoes.adquirir_lock():
            raise CommandError(
                "Há uma varredura do robô SEI em andamento (data/sei/em_execucao) — "
                "nada foi gravado; tente de novo quando ela terminar."
            )
        try:
            resultado = eventos_financeiros.aplicar_correcoes(correcoes, usuario=_usuario_tecnico())
        finally:
            execucoes.liberar_lock()
        self.stdout.write(self.style.SUCCESS(
            f"{resultado['apagados']} evento(s) apagado(s), {resultado['alterados']} "
            "alterado(s) — histórico registrado (sei_corrigir_eventos)."
        ))
