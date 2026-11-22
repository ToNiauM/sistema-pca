"""Testes do checkout do banco no corte e do backfill `congelar_relatorios`.

`TransactionTestCase`: a cópia e o subprocesso abrem o arquivo do banco por conexões próprias e só enxergam
dados já commitados (uma transação de `TestCase` ficaria invisível). `serialized_rollback` devolve os dados de
migração (ex.: o exercício 2026) depois do flush de cada teste. O passado é simulado forçando `history_date`.
"""

import os
import sqlite3
import subprocess
from datetime import date, datetime
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.catalogo.models import Categoria, Tipo
from apps.pca import checkout, congelamento
from apps.pca.models import OrigemRelatorio, Processo, RelatorioCongelado, Reuniao, SituacaoReuniao
from apps.pca.tests.test_relatorio_reuniao import cenario_reuniao


def _momento(dia, hora=10):
    return timezone.make_aware(datetime(dia.year, dia.month, dia.day, hora, 0))


class _BaseCheckout(TransactionTestCase):
    serialized_rollback = True

    def setUp(self):
        self.c = cenario_reuniao()
        # Tudo o que já existe "nasceu" em 01/08/2026; os casos abaixo ajustam o que importa.
        for _modelo, historico in checkout.modelos_com_historico():
            historico.objects.update(history_date=_momento(date(2026, 8, 1)))
        tipo, categoria = Tipo.objects.first(), Categoria.objects.first()
        uo = self.c["uo_a"]

        def criar(item, descricao):
            return Processo.objects.create(
                item_pca=item, exercicio=self.c["exercicio"], descricao_objeto=descricao, tipo=tipo,
                categoria=categoria, unidade_organizacional=uo, valor_estimado=Decimal("500.00"), mes_previsto=11,
            )

        def historico_de(processo):
            return Processo.history.filter(id=processo.pk).order_by("history_date", "history_id")

        # Texto alterado depois do corte.
        self.alterado = criar(11, "Objeto antigo")
        historico_de(self.alterado).update(history_date=_momento(date(2026, 8, 10)))
        self.alterado.descricao_objeto = "Objeto novo"
        self.alterado.save()
        ultimo = historico_de(self.alterado).last()
        Processo.history.filter(history_id=ultimo.history_id).update(history_date=_momento(date(2026, 10, 10)))
        # Criado depois do corte.
        self.criado_depois = criar(12, "Criado depois")
        historico_de(self.criado_depois).update(history_date=_momento(date(2026, 10, 20)))
        # Apagado antes do corte.
        self.apagado_antes = criar(13, "Apagado antes")
        pk_antes = self.apagado_antes.pk
        self.apagado_antes.delete()
        Processo.history.filter(id=pk_antes, history_type="+").update(history_date=_momento(date(2026, 8, 10)))
        Processo.history.filter(id=pk_antes, history_type="-").update(history_date=_momento(date(2026, 9, 1)))
        self.pk_apagado_antes = pk_antes
        # Apagado depois do corte: no corte ainda existia.
        self.apagado_depois = criar(14, "Apagado depois")
        pk_depois = self.apagado_depois.pk
        self.apagado_depois.delete()
        Processo.history.filter(id=pk_depois, history_type="+").update(history_date=_momento(date(2026, 8, 10)))
        Processo.history.filter(id=pk_depois, history_type="-").update(history_date=_momento(date(2026, 10, 15)))
        self.pk_apagado_depois = pk_depois
        self.corte = congelamento.fim_do_dia(date(2026, 9, 30))


class CopiaNoCorteTests(_BaseCheckout):
    def test_copia_reflete_o_banco_no_corte_e_some_depois(self):
        with checkout.copia_no_corte(self.corte) as (caminho, avisos):
            con = sqlite3.connect(caminho)
            try:
                textos = dict(con.execute("SELECT id, descricao_objeto FROM pca_processo"))
                datas = [linha[0] for linha in con.execute("SELECT data FROM pca_reuniao ORDER BY data")]
            finally:
                con.close()
            self.assertTrue(os.path.exists(caminho))
        self.assertEqual(textos[self.alterado.pk], "Objeto antigo")
        self.assertNotIn(self.criado_depois.pk, textos)
        self.assertNotIn(self.pk_apagado_antes, textos)
        self.assertEqual(textos[self.pk_apagado_depois], "Apagado depois")
        self.assertEqual(datas, ["2026-09-01"])
        self.assertEqual(avisos["puladas"], 0)
        for sufixo in ("", "-wal", "-shm", "-journal"):
            self.assertFalse(os.path.exists(caminho + sufixo), sufixo)

    def test_banco_principal_continua_intacto(self):
        with checkout.copia_no_corte(self.corte):
            pass
        self.assertEqual(Processo.objects.get(pk=self.alterado.pk).descricao_objeto, "Objeto novo")
        self.assertTrue(Processo.objects.filter(pk=self.criado_depois.pk).exists())
        self.assertEqual(Reuniao.objects.count(), 2)
        self.assertEqual(Processo.history.filter(id=self.alterado.pk).count(), 2)

    def test_arquivo_some_mesmo_com_erro_dentro_do_contexto(self):
        with self.assertRaises(RuntimeError):
            with checkout.copia_no_corte(self.corte) as (caminho, _avisos):
                raise RuntimeError("boom")
        self.assertFalse(os.path.exists(caminho))


class ApurarNoCorteTests(_BaseCheckout):
    def test_fatos_no_corte_trazem_o_texto_antigo(self):
        fatos = checkout.apurar_no_corte(
            corte=self.corte, exercicio=self.c["exercicio"], reuniao=self.c["anterior"],
            de=date(2026, 1, 1), ate=date(2026, 9, 1), usuario=None,
        )
        objetos = [p["objeto"] for p in fatos["processos"]]
        self.assertIn("Objeto antigo", objetos)
        self.assertNotIn("Objeto novo", objetos)
        self.assertNotIn("Criado depois", objetos)
        self.assertEqual(fatos["reuniao"]["ordinal"], 1)
        self.assertEqual(fatos["hoje"], "2026-09-30")
        html = congelamento.renderizar_fatos(fatos)
        self.assertIn("Objeto antigo", html)
        self.assertNotIn("Objeto novo", html)

    def test_reuniao_posterior_ao_corte_vira_relatorio_sem_reuniao(self):
        fatos = checkout.apurar_no_corte(
            corte=self.corte, exercicio=self.c["exercicio"], reuniao=self.c["aberta"],
            de=date(2026, 9, 2), ate=date(2026, 9, 30), usuario=None,
        )
        self.assertIsNone(fatos["reuniao"])

    def test_erro_do_subprocesso_vira_checkout_erro(self):
        falha = subprocess.CompletedProcess(args=[], returncode=3, stdout=b"", stderr=b"explodiu aqui")
        with mock.patch("apps.pca.checkout.subprocess.run", return_value=falha):
            with self.assertRaisesMessage(checkout.CheckoutErro, "explodiu aqui"):
                checkout.apurar_no_corte(
                    corte=self.corte, exercicio=self.c["exercicio"], reuniao=None,
                    de=date(2026, 9, 1), ate=date(2026, 9, 30), usuario=None,
                )

    def test_ambiente_do_subprocesso_tem_so_texto_mesmo_com_override_settings(self):
        """`settings.SETTINGS_MODULE` é None dentro de `override_settings` (casca Tabler dos testes)."""
        capturado = {}

        def falso(comando, **kwargs):
            capturado.update(kwargs["env"])
            return subprocess.CompletedProcess(args=comando, returncode=0, stdout=b"{}", stderr=b"")

        with override_settings(DEBUG=False), mock.patch("apps.pca.checkout.subprocess.run", side_effect=falso):
            checkout.apurar_no_corte(
                corte=self.corte, exercicio=self.c["exercicio"], reuniao=None,
                de=date(2026, 9, 1), ate=date(2026, 9, 30), usuario=None,
            )
        self.assertTrue(all(isinstance(valor, str) for valor in capturado.values()))
        self.assertTrue(capturado["DATABASE_URL"].startswith("sqlite:////"))
        self.assertTrue(capturado["DJANGO_SETTINGS_MODULE"])

    def test_timeout_vira_checkout_erro(self):
        with mock.patch(
            "apps.pca.checkout.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="x", timeout=45)
        ):
            with self.assertRaises(checkout.CheckoutErro):
                checkout.apurar_no_corte(
                    corte=self.corte, exercicio=self.c["exercicio"], reuniao=None,
                    de=date(2026, 9, 1), ate=date(2026, 9, 30), usuario=None,
                )

    def test_comando_recusa_banco_diferente_do_ativo(self):
        with self.assertRaisesMessage(CommandError, "Recusado"):
            call_command(
                "relatorio_checkout", banco="/tmp/outro-banco.sqlite3", corte=self.corte.isoformat(),
                exercicio=self.c["exercicio"].pk, de="2026-09-01", ate="2026-09-30",
            )


class CongelarRelatoriosTests(_BaseCheckout):
    def _rodar(self, *args):
        saida = StringIO()
        call_command("congelar_relatorios", *args, stdout=saida, stderr=StringIO())
        return saida.getvalue()

    def test_dry_run_lista_e_nao_grava(self):
        Reuniao.objects.create(data=date(2026, 7, 15), situacao=SituacaoReuniao.FECHADA, exercicio=self.c["exercicio"])
        saida = self._rodar("--dry-run")
        self.assertIn("01/09/2026", saida)
        self.assertIn("15/07/2026", saida)
        self.assertIn("Reconstituído a partir da planilha importada em 01/08/2026", saida)
        self.assertEqual(RelatorioCongelado.objects.count(), 0)

    def test_cria_versao_1_de_reconstrucao_e_e_idempotente(self):
        antiga = Reuniao.objects.create(
            data=date(2026, 7, 15), situacao=SituacaoReuniao.FECHADA, exercicio=self.c["exercicio"]
        )
        self._rodar()
        v = RelatorioCongelado.objects.get(reuniao=self.c["anterior"])
        self.assertEqual((v.versao, v.origem), (1, OrigemRelatorio.RECONSTRUCAO))
        self.assertEqual(v.corte, congelamento.fim_do_dia(date(2026, 9, 1)))
        self.assertEqual(v.observacao, "")
        self.assertTrue(v.integro)
        va = RelatorioCongelado.objects.get(reuniao=antiga)
        self.assertEqual(va.corte, congelamento.fim_do_dia(date(2026, 8, 1)))
        self.assertIn("planilha importada em 01/08/2026", va.observacao)
        # a reunião aberta nunca é congelada pelo backfill
        self.assertFalse(RelatorioCongelado.objects.filter(reuniao=self.c["aberta"]).exists())
        total = RelatorioCongelado.objects.count()
        saida = self._rodar()
        self.assertEqual(RelatorioCongelado.objects.count(), total)
        self.assertIn("Nenhuma reunião fechada sem relatório congelado.", saida)
