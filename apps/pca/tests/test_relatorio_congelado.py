"""Testes do relatório da reunião congelado.

Fechar uma reunião ABERTA guarda uma versão imutável do documento; a tela serve a cópia
guardada, mostra prévia na reunião aberta, reconstitui o passado quando preciso. O motor de
checkout (cópia do banco no corte + subprocesso) tem testes próprios em `test_checkout.py`; aqui ele é
substituído por um patch de `apps.pca.checkout.renderizar_no_corte`.
"""

import hashlib
import json
import re
from datetime import date, datetime, timedelta
from unittest import mock

from django.contrib.admin.sites import site as admin_site
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.pca import checkout, congelamento
from apps.pca.models import (
    OrigemRelatorio,
    hash_dos_dados,
    Processo,
    RelatorioCongelado,
    RelatorioImutavel,
    Reuniao,
    SituacaoReuniao,
)
from apps.pca.relatorio_movimentacao import montar_relatorio
from apps.pca.relatorio_reuniao import apurar_relatorio, apresentar_relatorio, montar_relatorio_reuniao
from apps.pca.tests.test_relatorio_reuniao import cenario_reuniao

HOJE = date(2026, 10, 15)


def _fatos(c, reuniao, marcador=None, de=date(2026, 1, 1), ate=None):
    """Fatos reais do relatório; `marcador` entra no nome do condutor para a tela mostrar de qual versão veio."""
    fatos = apurar_relatorio(
        exercicio=c["exercicio"], reuniao=reuniao, de=de, ate=ate or reuniao.data, usuario=None, hoje=HOJE
    )
    if marcador:
        fatos["reuniao"]["condutor"] = f"CONDUTOR {marcador}"
    return fatos


def _semear(c, reuniao, marcador="UM", **extra):
    """Grava uma versão sem passar pelo gancho (para testar a tela)."""
    dados = {
        "reuniao": reuniao,
        "dados": _fatos(c, reuniao, marcador),
        "de": date(2026, 1, 1),
        "ate": reuniao.data,
        "corte": timezone.make_aware(datetime(2026, 9, 1, 23, 59, 59)),
        "origem": OrigemRelatorio.FECHAMENTO,
    }
    dados.update(extra)
    return congelamento.congelar(**dados)


class _Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.c = cenario_reuniao()
        cls.usuario = get_user_model().objects.create_user(
            email="congelado@pca.local", password="senha-forte-123", first_name="Maria", last_name="Souza"
        )
        cls.usuario.user_permissions.add(
            Permission.objects.get(codename="view_acompanhamento", content_type__app_label="pca")
        )
        cls.url = reverse("pca:relatorio_movimentacao")


class ModeloTests(_Base):
    def test_congelar_cria_versoes_com_hash_dos_fatos(self):
        v1 = _semear(self.c, self.c["anterior"], "UM")
        self.assertEqual(v1.versao, 1)
        self.assertEqual(v1.hash, hash_dos_dados(v1.dados))
        canonico = json.dumps(v1.dados, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        self.assertEqual(v1.hash, hashlib.sha256(canonico.encode("utf-8")).hexdigest())
        self.assertEqual(len(v1.hash_curto), 7)
        self.assertEqual(v1.hash_curto, v1.hash[:7])
        self.assertTrue(RelatorioCongelado.objects.get(pk=v1.pk).integro)
        v2 = _semear(self.c, self.c["anterior"], "DOIS")
        self.assertEqual(v2.versao, 2)
        self.assertNotEqual(v1.hash, v2.hash)
        # outra reunião começa de novo
        self.assertEqual(_semear(self.c, self.c["aberta"], "X").versao, 1)

    def test_fatos_sao_json_puro(self):
        fatos = _fatos(self.c, self.c["anterior"])
        # sem `default=`: nenhum Decimal, data ou instância de modelo nos fatos
        self.assertEqual(json.loads(json.dumps(fatos)), fatos)
        self.assertNotIn("<", json.dumps(fatos["reuniao"]))

    def test_imutavel_pelo_orm(self):
        v = _semear(self.c, self.c["anterior"], "UM")
        v.dados = {"mexido": True}
        with self.assertRaises(RelatorioImutavel):
            v.save()
        with self.assertRaises(RelatorioImutavel):
            v.delete()
        with self.assertRaises(RelatorioImutavel):
            RelatorioCongelado.objects.all().delete()
        with self.assertRaises(RelatorioImutavel):
            RelatorioCongelado.objects.all().update(dados={})
        with self.assertRaises(RelatorioImutavel):
            RelatorioCongelado.objects.filter(pk=v.pk).delete()
        self.assertNotIn("mexido", RelatorioCongelado.objects.get(pk=v.pk).dados)

    def test_admin_nao_adiciona_altera_nem_apaga_nem_para_superusuario(self):
        admin = admin_site._registry[RelatorioCongelado]
        superusuario = get_user_model().objects.create_superuser(email="root@pca.local", password="x-senha-123")
        pedido = RequestFactory().get("/")
        pedido.user = superusuario
        self.assertFalse(admin.has_add_permission(pedido))
        self.assertFalse(admin.has_change_permission(pedido))
        self.assertFalse(admin.has_delete_permission(pedido))

    def test_usuario_none_nos_dois_montadores(self):
        c = self.c
        relatorio = montar_relatorio_reuniao(
            exercicio=c["exercicio"], reuniao=c["anterior"], de=date(2026, 1, 1), ate=date(2026, 9, 1), usuario=None
        )
        self.assertEqual(relatorio["gerado_por"], "Sistema PCA CFC")
        movimentacao = montar_relatorio(
            exercicio=c["exercicio"], de=date(2026, 1, 1), ate=date(2026, 9, 1), usuario=None
        )
        self.assertEqual(movimentacao.gerado_por, "Sistema PCA CFC")

    def test_apresentar_dos_fatos_guardados_igual_ao_ao_vivo(self):
        """A ida e volta pelo banco não muda nada do que o template recebe."""
        v = _semear(self.c, self.c["anterior"], None)
        ao_vivo = montar_relatorio_reuniao(
            exercicio=self.c["exercicio"], reuniao=self.c["anterior"], de=date(2026, 1, 1),
            ate=date(2026, 9, 1), usuario=None, hoje=HOJE,
        )
        guardado = apresentar_relatorio(RelatorioCongelado.objects.get(pk=v.pk).dados)
        for chave in ("titulo", "introducao", "sintese", "tabela1", "concluidas", "incluidos", "anexo_resumo",
                      "anexo_processos", "tabelas", "graficos", "situacao_texto", "cartoes_situacao",
                      "quadros", "grafico_valores", "grafico_unidades"):
            self.assertEqual(guardado[chave], ao_vivo[chave], chave)


class GanchoTests(_Base):
    def _fechar(self, reuniao, usuario=None):
        reuniao.situacao = SituacaoReuniao.FECHADA
        if usuario is not None:
            reuniao._history_user = usuario
        with self.captureOnCommitCallbacks(execute=True):
            reuniao.save()

    def test_fechar_reuniao_aberta_grava_versao_1(self):
        aberta = Reuniao.objects.get(pk=self.c["aberta"].pk)
        antes = timezone.now()
        self._fechar(aberta, self.usuario)
        versoes = list(RelatorioCongelado.objects.filter(reuniao=aberta))
        self.assertEqual(len(versoes), 1)
        v = versoes[0]
        self.assertEqual(v.versao, 1)
        self.assertEqual(v.origem, OrigemRelatorio.FECHAMENTO)
        self.assertEqual(v.de, date(2026, 9, 2))
        self.assertEqual(v.ate, max(date(2026, 10, 1), timezone.localdate()))
        self.assertGreaterEqual(v.corte, antes)
        self.assertLess(v.corte - antes, timedelta(minutes=2))
        self.assertEqual(v.criado_por, self.usuario)
        self.assertEqual(v.dados["reuniao"]["ordinal"], 2)
        self.assertFalse(v.dados["reuniao"]["em_andamento"])
        self.assertEqual(v.dados["exercicio"]["ano"], 2026)
        self.assertTrue(v.integro)
        html = congelamento.renderizar_fatos(v.dados)
        self.assertIn("2ª reunião de acompanhamento", html)
        self.assertNotIn("reunião em andamento", html)

    def test_criar_ja_fechada_nao_congela(self):
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            Reuniao.objects.create(
                data=date(2026, 11, 3), situacao=SituacaoReuniao.FECHADA, exercicio=self.c["exercicio"]
            )
        self.assertEqual(callbacks, [])
        self.assertEqual(RelatorioCongelado.objects.count(), 0)

    def test_fechada_para_fechada_nao_congela(self):
        anterior = Reuniao.objects.get(pk=self.c["anterior"].pk)
        anterior.condutor = self.usuario
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            anterior.save()
        self.assertEqual(callbacks, [])
        self.assertEqual(RelatorioCongelado.objects.count(), 0)

    def test_reabrir_e_fechar_de_novo_cria_a_versao_2(self):
        aberta = Reuniao.objects.get(pk=self.c["aberta"].pk)
        self._fechar(aberta)
        aberta.situacao = SituacaoReuniao.ABERTA
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            aberta.save()
        self.assertEqual(callbacks, [])
        self.assertEqual(RelatorioCongelado.objects.filter(reuniao=aberta).count(), 1)
        self._fechar(aberta)
        self.assertEqual(
            list(RelatorioCongelado.objects.filter(reuniao=aberta).order_by("versao").values_list("versao", flat=True)),
            [1, 2],
        )

    def test_falha_na_apuracao_nao_quebra_o_fechamento(self):
        aberta = Reuniao.objects.get(pk=self.c["aberta"].pk)
        with mock.patch("apps.pca.congelamento.apurar_relatorio", side_effect=RuntimeError("boom")):
            with self.assertLogs("apps.pca.congelamento", level="ERROR"):
                self._fechar(aberta)
        aberta.refresh_from_db()
        self.assertEqual(aberta.situacao, SituacaoReuniao.FECHADA)
        self.assertEqual(RelatorioCongelado.objects.count(), 0)

    def test_save_com_update_fields_sem_situacao_nao_congela(self):
        aberta = Reuniao.objects.get(pk=self.c["aberta"].pk)
        aberta.situacao = SituacaoReuniao.FECHADA
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            aberta.save(update_fields=["condutor"])
        self.assertEqual(callbacks, [])


class TelaTests(_Base):
    def setUp(self):
        self.client.force_login(self.usuario)

    def _get(self, **params):
        return self.client.get(self.url, params, HTTP_X_FORWARDED_PROTO="https")

    def test_fechada_serve_os_fatos_guardados_sem_apurar_de_novo(self):
        anterior = self.c["anterior"]
        v = _semear(self.c, anterior, "UM", usuario=self.usuario)
        with mock.patch("apps.pca.congelamento.apurar_relatorio", side_effect=AssertionError("apurou")):
            resposta = self._get(reuniao=anterior.pk)
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta["Cache-Control"], "private, no-store")
        corpo = resposta.content.decode()
        self.assertIn("CONDUTOR UM", corpo)
        self.assertIn("1ª reunião de acompanhamento do PCA 2026", corpo)
        self.assertIn(f"Versão {v.hash_curto}", corpo)
        self.assertIn("congelada em", corpo)
        self.assertIn("Maria Souza", corpo)
        self.assertIn("versão 1 de 1", corpo)
        self.assertNotIn("Prévia", corpo)

    def test_editar_o_processo_depois_nao_muda_a_tela(self):
        anterior = self.c["anterior"]
        _semear(self.c, anterior, "UM")
        processo = Processo.objects.get(item_pca=1)
        processo.descricao_objeto = "OBJETO NOVO DEPOIS DO FECHAMENTO"
        processo.save()
        corpo = self._get(reuniao=anterior.pk).content.decode()
        self.assertIn("Aquisição de cadeiras", corpo)
        self.assertNotIn("OBJETO NOVO DEPOIS DO FECHAMENTO", corpo)

    def test_versoes_mais_recente_e_versao_escolhida(self):
        anterior = self.c["anterior"]
        _semear(self.c, anterior, "UM")
        _semear(self.c, anterior, "DOIS")
        corpo = self._get(reuniao=anterior.pk).content.decode()
        self.assertIn("CONDUTOR DOIS", corpo)
        self.assertNotIn("CONDUTOR UM", corpo)
        self.assertIn("versão 2 de 2", corpo)
        self.assertIn("Versões deste relatório", corpo)
        self.assertIn("versao=1", corpo)  # a exibida não leva link
        corpo = self._get(reuniao=anterior.pk, versao=1).content.decode()
        self.assertIn("CONDUTOR UM", corpo)
        self.assertNotIn("CONDUTOR DOIS", corpo)
        self.assertIn("versão 1 de 2", corpo)
        self.assertIn("versao=2", corpo)

    def test_versao_invalida_avisa_e_mostra_a_mais_recente(self):
        anterior = self.c["anterior"]
        _semear(self.c, anterior, "UM")
        for valor in ("99", "abc"):
            with self.subTest(versao=valor):
                corpo = self._get(reuniao=anterior.pk, versao=valor).content.decode()
                self.assertIn("CONDUTOR UM", corpo)
                self.assertIn("Versão pedida não encontrada", corpo)

    def test_versao_de_reconstrucao_mostra_origem_e_observacao(self):
        anterior = self.c["anterior"]
        _semear(
            self.c,
            anterior,
            "UM",
            origem=OrigemRelatorio.RECONSTRUCAO,
            observacao="Reconstituído a partir da planilha importada em 01/08/2026: o sistema não tinha dados.",
        )
        corpo = self._get(reuniao=anterior.pk).content.decode()
        self.assertIn("reconstituída do histórico em", corpo)
        self.assertIn("dados até 01/09/2026", corpo)
        self.assertIn("Reconstituído a partir da planilha importada em 01/08/2026", corpo)

    def test_fatos_adulterados_mostram_aviso_de_integridade_e_nao_renderizam(self):
        anterior = self.c["anterior"]
        v = _semear(self.c, anterior, "UM")
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE pca_relatoriocongelado SET dados = %s WHERE id = %s", ['{"adulterado":true}', v.pk]
            )
        resposta = self._get(reuniao=anterior.pk)
        self.assertEqual(resposta.status_code, 200)
        corpo = resposta.content.decode()
        self.assertIn("integridade", corpo)
        self.assertIn("br-message danger", corpo)
        self.assertNotIn("CONDUTOR UM", corpo)
        self.assertEqual(corpo.count("<h1"), 1)

    def test_fechada_sem_versao_reconstitui_uma_vez(self):
        anterior = self.c["anterior"]
        fatos = _fatos(self.c, anterior, "RECONSTRUIDO")
        with mock.patch("apps.pca.checkout.apurar_no_corte", return_value=fatos) as apurar:
            corpo = self._get(reuniao=anterior.pk).content.decode()
            self.assertIn("CONDUTOR RECONSTRUIDO", corpo)
            self._get(reuniao=anterior.pk)
        self.assertEqual(apurar.call_count, 1)
        self.assertEqual(apurar.call_args.kwargs["corte"], congelamento.fim_do_dia(anterior.data))
        v = RelatorioCongelado.objects.get(reuniao=anterior)
        self.assertEqual((v.versao, v.origem), (1, OrigemRelatorio.RECONSTRUCAO))
        self.assertEqual(v.criado_por, self.usuario)

    def test_reuniao_aberta_mostra_previa_ao_vivo(self):
        corpo = self._get().content.decode()
        self.assertIn("Prévia — a reunião está aberta; este relatório muda até ser fechada", corpo)
        self.assertIn("br-message warning", corpo)
        self.assertIn("2ª reunião de acompanhamento do PCA 2026", corpo)
        self.assertEqual(corpo.count("<h1"), 1)
        self.assertEqual(RelatorioCongelado.objects.count(), 0)

    def test_periodo_livre_no_passado_usa_o_checkout_sem_reuniao(self):
        fatos = apurar_relatorio(
            exercicio=self.c["exercicio"], reuniao=None, de=date(2026, 3, 1), ate=date(2026, 3, 31),
            usuario=None, hoje=date(2026, 3, 31),
        )
        with mock.patch("apps.pca.checkout.apurar_no_corte", return_value=fatos) as apurar:
            corpo = self._get(de="2026-03-01", ate="2026-03-31").content.decode()
        self.assertIn("Dados até 31/03/2026", corpo)
        self.assertIn("1 a 31/03/2026", corpo)
        apurar.assert_called_once()
        self.assertEqual(apurar.call_args.kwargs["corte"], congelamento.fim_do_dia(date(2026, 3, 31)))
        self.assertIsNone(apurar.call_args.kwargs["reuniao"])
        self.assertEqual(RelatorioCongelado.objects.count(), 0)

    def test_periodo_livre_ate_hoje_e_ao_vivo(self):
        hoje = timezone.localdate()
        with mock.patch("apps.pca.checkout.apurar_no_corte", side_effect=AssertionError("checkout")):
            corpo = self._get(de="2026-01-01", ate=hoje.isoformat()).content.decode()
        self.assertIn(f"Dados até {hoje:%d/%m/%Y}", corpo)

    def test_relatorio_de_periodo_nao_e_de_reuniao(self):
        hoje = timezone.localdate()
        corpo = self._get(de="2026-09-02", ate=hoje.isoformat()).content.decode()
        titulo = re.search(r'<h1 class="abnt-titulo"[^>]*>(.*?)</h1>', corpo, re.S).group(1)
        self.assertEqual(titulo, "Relatório de acompanhamento do PCA 2026")
        self.assertNotIn("reunião de acompanhamento", titulo)
        self.assertNotIn("Indicadores da reunião", corpo)
        self.assertIn("Quadro 1</b> – Itens ativos por situação", corpo)
        self.assertNotIn("Registros da reunião", corpo)
        self.assertNotIn("Não há reunião cadastrada", corpo)
        self.assertNotIn("Condução:", corpo)
        self.assertIn("Movimentação do período", corpo)
        # sem a seção de registros, a numeração sobe: 4 Movimentação, 5 Solicitações
        self.assertIn(">4 Movimentação do período<", corpo)
        self.assertIn(">5 Solicitações das unidades<", corpo)
        # já a reunião mantém a numeração de sempre
        corpo = self._get().content.decode()
        self.assertIn(">4 Registros da reunião<", corpo)
        self.assertIn(">5 Movimentação do período<", corpo)

    def test_erro_do_checkout_vira_aviso_na_tela(self):
        with mock.patch("apps.pca.checkout.apurar_no_corte", side_effect=checkout.CheckoutErro("falhou feio")):
            resposta = self._get(de="2026-03-01", ate="2026-03-31")
        self.assertEqual(resposta.status_code, 200)
        corpo = resposta.content.decode()
        self.assertIn("br-message danger", corpo)
        self.assertEqual(corpo.count("<h1"), 1)
        self.assertNotIn('id="relatorio-documento"', corpo)


class CorteDeReconstrucaoTests(_Base):
    def _forcar_primeiro_registro(self, dia):
        momento = timezone.make_aware(datetime(dia.year, dia.month, dia.day, 10, 0))
        for _modelo, historico in checkout.modelos_com_historico():
            historico.objects.all().update(history_date=momento)

    def test_reuniao_depois_do_primeiro_registro(self):
        self._forcar_primeiro_registro(date(2026, 8, 1))
        corte, observacao = congelamento.corte_de_reconstrucao(self.c["anterior"])
        self.assertEqual(corte, congelamento.fim_do_dia(date(2026, 9, 1)))
        self.assertEqual(observacao, "")

    def test_reuniao_antes_do_primeiro_registro(self):
        self._forcar_primeiro_registro(date(2026, 8, 1))
        antiga = Reuniao.objects.create(
            data=date(2026, 7, 15), situacao=SituacaoReuniao.FECHADA, exercicio=self.c["exercicio"]
        )
        corte, observacao = congelamento.corte_de_reconstrucao(antiga)
        self.assertEqual(corte, congelamento.fim_do_dia(date(2026, 8, 1)))
        self.assertEqual(
            observacao,
            "Reconstituído a partir da planilha importada em 01/08/2026: "
            "o sistema não tinha dados na data desta reunião.",
        )

    def test_fim_do_dia_e_casca(self):
        fim = congelamento.fim_do_dia(date(2026, 3, 31))
        self.assertTrue(timezone.is_aware(fim))
        local = timezone.localtime(fim)
        self.assertEqual((local.date(), local.hour, local.minute, local.second), (date(2026, 3, 31), 23, 59, 59))
        self.assertFalse(congelamento.casca_tabler_ativa())
        from core.tests.test_casca_tabler import CASCA_TABLER

        with CASCA_TABLER:
            self.assertTrue(congelamento.casca_tabler_ativa())
