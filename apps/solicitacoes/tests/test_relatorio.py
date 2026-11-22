"""Seção "Solicitações das unidades" do Relatório da reunião."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from html.parser import HTMLParser

from django.db import connection
from django.template.loader import render_to_string
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from django.utils.timezone import localdate

from apps.pca.models import Reuniao, SituacaoReuniao
from apps.pca.relatorio_reuniao import montar_relatorio_reuniao
from apps.pca.relatorio_movimentacao import _limites_do_dia
from apps.solicitacoes import services
from apps.solicitacoes.models import ParteSolicitacao
from apps.solicitacoes.regras import Campo, Decisao, EstadoParte
from apps.solicitacoes.relatorio import montar_bloco

from .base import CenarioBase


class _Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class RelatorioSolicitacoesTests(CenarioBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.hoje = localdate()
        cls.de = date(cls.ano, 1, 1)
        Reuniao.objects.create(data=cls.hoje, situacao=SituacaoReuniao.ABERTA, exercicio=cls.exercicio)

    def _pedir(self, item, usuario=None, **pedidos):
        return services.criar_solicitacao(
            usuario=usuario or self.solicitante, processo_id=item.pk, justificativa="Precisamos mudar o item.",
            pedidos={Campo(campo): valor for campo, valor in pedidos.items()},
        )

    def _decidir(self, solicitacao, campo, usuario, decisao=Decisao.APROVAR, **kwargs):
        if decisao != Decisao.APROVAR:
            kwargs.setdefault("motivo", "Motivo da decisão.")
        return services.decidir_parte(
            parte_id=solicitacao.partes.get(campo=campo).pk, usuario=usuario, decisao=decisao, **kwargs
        )

    def _cenario_com_pedidos(self):
        """Item 1: prazo aprovado (equipe), valor com ajuste (diretoria), mês em análise. Item 2: objeto recusado.
        Inclusão em análise."""
        s1 = self._pedir(
            self.item, prazo_entrega=date(self.ano, 12, 20), valor_estimado="2000.00", mes_previsto=7
        )
        self._decidir(s1, Campo.PRAZO_ENTREGA, self.equipe)
        self._decidir(
            s1, Campo.VALOR_ESTIMADO, self.diretoria, Decisao.AJUSTE, valor_ajuste="1500.00", motivo="Verba menor."
        )
        s2 = self._pedir(self.item_atrasado, descricao_objeto="Objeto novo do item 2")
        self._decidir(s2, Campo.DESCRICAO_OBJETO, self.diretoria, Decisao.RECUSAR, motivo="Escopo mantido.")
        services.criar_inclusao(
            usuario=self.solicitante, unidade_id=self.unidade.pk, descricao_objeto="Curso de capacitação",
            tipo_id=self.tipo_nova.pk, categoria_id=self.categoria.pk, valor_estimado="5000.00", mes_previsto=9,
            justificativa="Demanda nova da unidade.",
        )
        return s1, s2

    def _montar(self):
        return montar_relatorio_reuniao(
            exercicio=self.exercicio, reuniao=Reuniao.objects.get(exercicio=self.exercicio), de=self.de,
            ate=self.hoje, usuario=self.admin, hoje=self.hoje,
        )

    def _render(self, relatorio, **extra):
        html = render_to_string("pca/_relatorio_reuniao_documento.html", {"relatorio": relatorio, **extra})
        coletor = _Tags()
        coletor.feed(html)
        return html, coletor.tags

    def _bloco(self):
        inicio, fim = _limites_do_dia(self.de, self.hoje)
        return montar_bloco(exercicio=self.exercicio, inicio=inicio, fim=fim)

    def test_sem_solicitacoes_a_secao_diz_que_nao_ha_nada(self):
        r = self._montar()
        self.assertEqual(r["solicitacoes"]["grupos"], [])
        self.assertNotIn("solicitacoes", r["tabelas"])
        self.assertEqual(r["solicitacoes_texto"], "Nenhum pedido das unidades foi decidido no período nem está em análise.")
        self.assertNotIn("solicitações das unidades", r["sintese"])
        html, _ = self._render(r)
        self.assertIn("6 Solicitações das unidades", html)
        self.assertIn(r["solicitacoes_texto"], html)
        self.assertEqual(r["tabelas"]["anexo_processos"], r["tabelas"]["anexo_resumo"] + 1)

    def test_decididas_e_em_analise_com_item_unidade_pedido_e_decisao(self):
        self._cenario_com_pedidos()
        bloco = self._bloco()
        self.assertEqual(
            (bloco["decididas"], bloco["aprovadas"], bloco["ajustadas"], bloco["recusadas"], bloco["pendentes"]),
            (3, 1, 1, 1, 2),
        )
        self.assertEqual([g["titulo"] for g in bloco["grupos"]], ["Decididas no período", "Em análise"])
        decididas, em_analise = (g["linhas"] for g in bloco["grupos"])
        self.assertEqual([l["item"] for l in decididas], [1, 1, 2])
        self.assertTrue(all(l["uo"] == "Gerência A" for l in decididas))
        prazo, valor, objeto = decididas
        self.assertEqual(prazo["pedido"]["campo"], "Prazo de entrega")
        self.assertEqual(prazo["pedido"]["texto"], f"15/12/{self.ano} → 20/12/{self.ano}")
        self.assertEqual(prazo["decisao"]["rotulo"], "Aprovada")
        self.assertIn("Eva", prazo["decisao"]["detalhe"])
        self.assertIn("Solicitação 1/", prazo["pedido"]["detalhe"])
        self.assertIn("Justificativa: Precisamos mudar o item.", prazo["pedido"]["detalhe"])
        self.assertEqual(valor["decisao"]["rotulo"], "Aprovada com ajuste")
        self.assertIn("R$ 1.500,00", valor["decisao"]["texto"])
        self.assertIn("Verba menor.", valor["decisao"]["texto"])
        self.assertEqual(objeto["decisao"]["rotulo"], "Recusada")
        self.assertEqual(objeto["decisao"]["texto"], "Escopo mantido.")
        # Em análise: o mês do item 1 e a inclusão (item "Novo"), da mais antiga para a mais nova.
        self.assertEqual([l["item"] for l in em_analise], [1, "Novo"])
        self.assertEqual(em_analise[0]["pedido"]["campo"], "Mês previsto")
        self.assertEqual(em_analise[0]["decisao"]["rotulo"], "Em análise")
        self.assertIn("aguardando equipe do pca", em_analise[0]["decisao"]["detalhe"].lower())
        self.assertIn("Curso de capacitação", em_analise[1]["pedido"]["texto"])
        self.assertIn("Aguardando diretoria", em_analise[1]["decisao"]["detalhe"])

    def test_texto_corrido_numeracao_e_sintese(self):
        self._cenario_com_pedidos()
        r = self._montar()
        self.assertEqual(r["tabelas"]["solicitacoes"], r["tabelas"]["anexo_resumo"] - 1)
        numero = r["tabelas"]["solicitacoes"]
        self.assertIn("Foram decididos 3 pedidos das unidades", r["solicitacoes_texto"])
        self.assertIn("1 aprovado, 1 aprovado com ajuste e 1 recusado", r["solicitacoes_texto"])
        self.assertIn("2 pedidos seguem em análise", r["solicitacoes_texto"])
        self.assertIn(f"(Tabela {numero})", r["solicitacoes_texto"])
        self.assertIn(
            f"Quanto às solicitações das unidades, 3 pedidos foram decididos e 2 seguem em análise (Tabela {numero}).",
            r["sintese"],
        )

    def test_so_pendentes_ou_so_decididas_concordam_em_numero(self):
        s = self._pedir(self.item, prazo_entrega=date(self.ano, 12, 20))
        r = self._montar()
        self.assertTrue(r["solicitacoes_texto"].startswith("Há 1 pedido das unidades em análise (Tabela"))
        self._decidir(s, Campo.PRAZO_ENTREGA, self.equipe)
        r = self._montar()
        self.assertTrue(r["solicitacoes_texto"].startswith("Foi decidido 1 pedido das unidades"))
        self.assertNotIn("em análise", r["solicitacoes_texto"])

    def test_decisao_fora_do_periodo_nao_entra(self):
        s = self._pedir(self.item, prazo_entrega=date(self.ano, 12, 20))
        self._decidir(s, Campo.PRAZO_ENTREGA, self.equipe)
        antiga = timezone.make_aware(datetime(self.ano - 1, 6, 1, 10, 0))
        ParteSolicitacao.objects.filter(solicitacao=s).update(decidido_em=antiga)
        bloco = self._bloco()
        self.assertEqual((bloco["decididas"], bloco["pendentes"], bloco["grupos"]), (0, 0, []))

    def test_prejudicadas_e_desistidas_nao_sao_decisao(self):
        s = self._pedir(self.item, prazo_entrega=date(self.ano, 12, 20))
        services.desistir(solicitacao_id=s.pk, usuario=self.solicitante)
        self.assertEqual(ParteSolicitacao.objects.get(solicitacao=s).estado, EstadoParte.DESISTIDA)
        bloco = self._bloco()
        self.assertEqual((bloco["decididas"], bloco["pendentes"]), (0, 0))

    def test_pendente_criada_depois_do_periodo_fica_de_fora(self):
        self._pedir(self.item, prazo_entrega=date(self.ano, 12, 20))
        inicio, fim = _limites_do_dia(self.de, self.hoje - timedelta(days=30))
        bloco = montar_bloco(exercicio=self.exercicio, inicio=inicio, fim=fim)
        self.assertEqual(bloco["pendentes"], 0)

    def test_numero_de_consultas_nao_cresce_com_as_linhas(self):
        self._pedir(self.item, prazo_entrega=date(self.ano, 12, 20))
        with CaptureQueriesContext(connection) as uma:
            self._bloco()
        self._pedir(self.item_atrasado, descricao_objeto="Outro objeto", valor_estimado="3000.00")
        self._pedir(self.item_tramitacao, valor_estimado="4000.00")
        with CaptureQueriesContext(connection) as varias:
            bloco = self._bloco()
        self.assertEqual(bloco["pendentes"], 4)
        self.assertEqual(len(uma), len(varias))

    def test_documento_nas_duas_cascas(self):
        self._cenario_com_pedidos()
        r = self._montar()
        for extra in ({}, {"casca_tabler": True}):
            with self.subTest(**extra):
                html, tags = self._render(r, **extra)
                self.assertEqual(sum(1 for t, _ in tags if t == "h1"), 1)
                self.assertFalse([t for t, a in tags if "style" in a])
                for trecho in (
                    "6 Solicitações das unidades", "Decididas no período", "Aprovada com ajuste", "Recusada",
                    "Escopo mantido.", "Em análise", "Curso de capacitação", "Gerência A",
                ):
                    self.assertIn(trecho, html)
                if extra:
                    self.assertNotIn("br-table", html)
                else:
                    self.assertEqual(html.count('class="br-table abnt-tabela"'), html.count("<table"))
        # A seção 6 vem antes dos anexos.
        html, _ = self._render(r)
        self.assertLess(html.index("6 Solicitações das unidades"), html.index("Anexo I – Resumo por unidade"))
        self.assertGreater(html.index("6 Solicitações das unidades"), html.index("5 Movimentação do período"))
