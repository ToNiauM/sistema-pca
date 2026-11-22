"""Recalcula a situação pela regra de renovação × vigência.

Contrato vigente além do ano do PCA é sempre Concluído; contrato que renova
no ano (vigência termina no ano, ou Renovação sem vigência) só é Concluído
com contrato ou termo aditivo assinado no ano — apostilamento nunca conta.
A regra já roda sozinha a cada edição e a cada sincronização com o SEI;
este comando aplica a regra de uma vez aos itens que existiam antes dela.

Por padrão SÓ SIMULA (lista o que mudaria). `--aplicar` grava, pelo mesmo
`aplicar_regras_automaticas` das telas — um acompanhamento automático por
item alterado, com o motivo, autoria do `--usuario` informado.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.pca.models import Estado, Processo, Situacao
from apps.pca.regras_situacao import CONCLUIDO_OBRIGATORIO, CONCLUSAO_BLOQUEADA
from apps.pca.services import aplicar_regras_automaticas, exigencia_de


class Command(BaseCommand):
    help = (
        "Aplica a regra de renovação × vigência à situação dos itens de um "
        "exercício (simula por padrão; --aplicar grava)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--exercicio", type=int, required=True)
        parser.add_argument("--usuario", required=True, help="e-mail do autor dos acompanhamentos")
        parser.add_argument("--aplicar", action="store_true", help="grava (sem isso, só simula)")

    def handle(self, *args, **opcoes):
        try:
            usuario = get_user_model().objects.get(email=opcoes["usuario"])
        except get_user_model().DoesNotExist as exc:
            raise CommandError(f"usuário {opcoes['usuario']} não encontrado") from exc

        processos = (
            Processo.objects.filter(exercicio__ano=opcoes["exercicio"], estado=Estado.ATIVO)
            .select_related("exercicio", "tipo")
            .order_by("item_pca")
        )
        alterados = 0
        for processo in processos:
            exigencia, motivo = exigencia_de(processo)
            muda = (
                exigencia == CONCLUIDO_OBRIGATORIO and processo.situacao != Situacao.CONCLUIDO
            ) or (
                exigencia == CONCLUSAO_BLOQUEADA and processo.situacao == Situacao.CONCLUIDO
            )
            if not muda:
                continue
            alterados += 1
            antes = Situacao(processo.situacao).label
            if opcoes["aplicar"]:
                atualizado = aplicar_regras_automaticas(processo=processo, usuario=usuario)
                depois = Situacao(atualizado.situacao).label if atualizado else antes
            else:
                depois = "Concluído" if exigencia == CONCLUIDO_OBRIGATORIO else "não concluído"
            self.stdout.write(f"item {processo.item_pca}: {antes} → {depois} — {motivo}")

        verbo = "alterado(s)" if opcoes["aplicar"] else "a alterar (simulação; use --aplicar)"
        self.stdout.write(self.style.SUCCESS(f"{alterados} item(ns) {verbo}."))
