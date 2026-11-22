"""Serviços das Solicitações (..09) — sobre o banco, pelos serviços reais do `apps.pca`."""

from datetime import date, timedelta
from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils.timezone import now

from apps.catalogo.models import Exercicio, SituacaoExercicio
from apps.pca import services as servicos_pca
from apps.pca.models import Acompanhamento, Estado, Processo, Situacao
from apps.solicitacoes import services
from apps.solicitacoes.models import Solicitacao
from apps.solicitacoes.regras import Campo, Decisao, EstadoParte, EstadoSolicitacao

from .base import CenarioBase


def _item_atual(item):
    return Processo.objects.para_listagem().get(pk=item.pk)


class Base(CenarioBase):
    def pedir(self, item=None, usuario=None, justificativa="Precisamos mudar.", **pedidos):
        return services.criar_solicitacao(
            usuario=usuario or self.solicitante,
            processo_id=(item or self.item).pk,
            justificativa=justificativa,
            pedidos={Campo(campo): valor for campo, valor in pedidos.items()},
        )

    def parte(self, solicitacao, campo):
        return solicitacao.partes.get(campo=campo)

    def decidir(self, solicitacao, campo, decisao=Decisao.APROVAR, usuario=None, **kwargs):
        if decisao != Decisao.APROVAR:
            kwargs.setdefault("motivo", "porque sim")
        return services.decidir_parte(
            parte_id=self.parte(solicitacao, campo).pk,
            usuario=usuario or self.admin,
            decisao=decisao,
            **kwargs,
        )


class TestCriarSolicitacao(Base):
    def test_pedido_simples_cria_solicitacao_e_parte(self):
        solicitacao = self.pedir(mes_previsto=9)
        self.assertEqual(solicitacao.codigo, f"1/{now().year}")
        self.assertEqual(solicitacao.tipo, "alteracao")
        self.assertEqual(solicitacao.estado, EstadoSolicitacao.PENDENTE)
        self.assertEqual(solicitacao.unidade, self.unidade)
        self.assertEqual(solicitacao.processo, self.item)
        parte = self.parte(solicitacao, Campo.MES_PREVISTO)
        self.assertEqual((parte.valor_atual, parte.valor_pedido), ("6", "9"))
        self.assertEqual(parte.alcada, "equipe")
        self.assertEqual(parte.estado, EstadoParte.PENDENTE)
        self.assertFalse(parte.fora_do_exercicio)

    def test_d43_03_uma_solicitacao_com_varias_partes_cada_uma_na_sua_alcada(self):
        solicitacao = self.pedir(
            prazo_entrega=date(self.ano, 12, 20), valor_estimado="2500", descricao_objeto="Novo objeto"
        )
        self.assertEqual(solicitacao.partes.count(), 3)
        alcadas = {p.campo: p.alcada for p in solicitacao.partes.all()}
        self.assertEqual(
            alcadas,
            {"prazo_entrega": "equipe", "valor_estimado": "diretoria", "descricao_objeto": "diretoria"},
        )
        parte_valor = self.parte(solicitacao, Campo.VALOR_ESTIMADO)
        self.assertEqual((parte_valor.valor_atual, parte_valor.valor_pedido), ("1000.00", "2500.00"))

    def test_numeracao_por_ano_e_sequencial(self):
        primeira = self.pedir(mes_previsto=9)
        segunda = self.pedir(self.item_atrasado, mes_previsto=9)
        self.assertEqual((primeira.numero, segunda.numero), (1, 2))
        self.assertEqual(primeira.ano, segunda.ano)

    def test_d43_05_justificativa_obrigatoria(self):
        with self.assertRaisesMessage(services.PedidoInvalido, "justificativa"):
            self.pedir(justificativa="   ", mes_previsto=9)
        self.assertEqual(Solicitacao.objects.count(), 0)

    def test_d43_05_numero_sei_e_opcional(self):
        solicitacao = services.criar_solicitacao(
            usuario=self.solicitante, processo_id=self.item.pk, justificativa="x",
            pedidos={Campo.MES_PREVISTO: 9}, numero_sei=" 00123.000456/2026-11 ",
        )
        self.assertEqual(solicitacao.numero_sei, "00123.000456/2026-11")

    def test_d43_10_so_pede_nos_itens_das_suas_unidades(self):
        for usuario in (self.solicitante_b, self.sem_vinculo):
            with self.subTest(usuario=usuario.email), self.assertRaises(services.SemPermissao):
                self.pedir(usuario=usuario, mes_previsto=9)

    def test_d43_10_sem_a_permissao_solicitar_nao_pede_nem_com_vinculo(self):
        from apps.solicitacoes.models import VinculoUnidade

        VinculoUnidade.objects.create(usuario=self.visualizador, unidade=self.unidade)
        with self.assertRaises(services.SemPermissao):
            self.pedir(usuario=self.visualizador, mes_previsto=9)

    def test_d43_10_o_colega_da_unidade_tambem_pede(self):
        self.assertTrue(self.pedir(usuario=self.colega, mes_previsto=9).pk)

    def test_d43_06_item_concluido_cancelado_ou_de_exercicio_fechado_nao_aceita(self):
        concluido = self.novo_item(20, situacao=Situacao.CONCLUIDO)
        cancelado = self.novo_item(21, estado=Estado.CANCELADO)
        fechado_ex = Exercicio.objects.create(
            ano=self.ano - 1, rotulo="PCA passado", situacao=SituacaoExercicio.FECHADO
        )
        fechado = self.novo_item(22, exercicio=fechado_ex)
        for item, trecho in ((concluido, "concluído"), (cancelado, "cancelado"), (fechado, "fechado")):
            with self.subTest(item=item.item_pca), self.assertRaisesMessage(
                services.ItemNaoAceitaPedido, trecho
            ):
                self.pedir(item, valor_estimado="10")

    def test_d43_06_prazo_e_mes_so_em_item_a_entregar(self):
        with self.assertRaises(services.ItemNaoAceitaPedido):
            self.pedir(self.item_tramitacao, prazo_entrega=date(self.ano, 12, 30))
        with self.assertRaises(services.ItemNaoAceitaPedido):
            self.pedir(self.item_tramitacao, mes_previsto=10)
        # valor, objeto e cancelamento continuam aceitos em tramitação
        self.assertTrue(self.pedir(self.item_tramitacao, valor_estimado="77").pk)

    def test_d43_06_item_atrasado_aceita_prazo_e_o_valor_atual_e_o_prazo_efetivo(self):
        self.assertEqual(_item_atual(self.item_atrasado).situacao_efetiva, Situacao.ATRASADO)
        solicitacao = self.pedir(self.item_atrasado, prazo_entrega=date(self.ano, 12, 20))
        self.assertEqual(
            self.parte(solicitacao, Campo.PRAZO_ENTREGA).valor_atual, f"{self.ano - 1}-12-01"
        )

    def test_d43_06_adiar_para_depois_de_31_12_e_aceito_e_marcado_fora_do_exercicio(self):
        solicitacao = self.pedir(prazo_entrega=date(self.ano + 1, 2, 10))
        self.assertTrue(self.parte(solicitacao, Campo.PRAZO_ENTREGA).fora_do_exercicio)
        dentro = self.pedir(self.item_atrasado, prazo_entrega=date(self.ano, 12, 31))
        self.assertFalse(self.parte(dentro, Campo.PRAZO_ENTREGA).fora_do_exercicio)

    def test_d43_05_so_uma_parte_pendente_por_campo_por_item(self):
        self.pedir(mes_previsto=9)
        with self.assertRaisesMessage(services.PedidoConflitante, "Mês previsto"):
            self.pedir(usuario=self.colega, mes_previsto=10, valor_estimado="5000")
        # outro campo, ou o mesmo campo em outro item, segue livre
        self.assertTrue(self.pedir(valor_estimado="5000").pk)
        self.assertTrue(self.pedir(self.item_atrasado, mes_previsto=10).pk)

    def test_d43_05_decidida_a_parte_o_campo_volta_a_aceitar_pedido(self):
        primeira = self.pedir(mes_previsto=9)
        self.decidir(primeira, Campo.MES_PREVISTO, Decisao.RECUSAR)
        self.assertTrue(self.pedir(mes_previsto=10).pk)

    def test_d43_05_cancelamento_pendente_bloqueia_qualquer_outra_solicitacao_no_item(self):
        self.pedir(cancelamento=None)
        with self.assertRaisesMessage(services.PedidoConflitante, "cancelamento"):
            self.pedir(usuario=self.colega, mes_previsto=9)

    def test_d43_03_cancelamento_vai_sozinho(self):
        with self.assertRaisesMessage(services.PedidoInvalido, "sozinho"):
            self.pedir(cancelamento=None, mes_previsto=9)
        solicitacao = self.pedir(cancelamento=None)
        self.assertEqual(solicitacao.tipo, "cancelamento")
        parte = solicitacao.partes.get()
        self.assertEqual((parte.campo, parte.alcada, parte.valor_pedido), ("cancelamento", "diretoria", ""))

    def test_pedido_igual_ao_atual_ou_invalido_e_recusado(self):
        with self.assertRaisesMessage(services.PedidoInvalido, "igual ao atual"):
            self.pedir(mes_previsto=6)
        with self.assertRaisesMessage(services.PedidoInvalido, "igual ao atual"):
            self.pedir(valor_estimado="1000")
        with self.assertRaises(services.PedidoInvalido):
            self.pedir(mes_previsto=13)
        with self.assertRaises(services.PedidoInvalido):
            self.pedir()

    def test_d43_13_a_criacao_entra_na_trilha_com_autor(self):
        solicitacao = self.pedir(mes_previsto=9)
        self.assertEqual(solicitacao.history.first().history_user, self.solicitante)
        self.assertEqual(self.parte(solicitacao, Campo.MES_PREVISTO).history.first().history_user, self.solicitante)


class TestInclusao(Base):
    def incluir(self, **extra):
        dados = dict(
            usuario=self.solicitante, unidade_id=self.unidade.pk, descricao_objeto="Licença de software",
            tipo_id=self.tipo_nova.pk, categoria_id=self.categoria.pk, valor_estimado="9000",
            mes_previsto=5, justificativa="Demanda nova.",
        )
        dados.update(extra)
        return services.criar_inclusao(**dados)

    def test_d43_07_pedido_de_inclusao_nao_tem_item_ate_a_aprovacao(self):
        total = Processo.objects.count()
        solicitacao = self.incluir(prazo_entrega="2026-11-30")
        self.assertEqual(solicitacao.tipo, "inclusao")
        self.assertIsNone(solicitacao.processo)
        self.assertEqual(Processo.objects.count(), total)
        parte = solicitacao.partes.get()
        self.assertEqual((parte.campo, parte.alcada), ("inclusao", "diretoria"))
        self.assertEqual(solicitacao.dados_inclusao["valor_estimado"], "9000.00")
        self.assertEqual(solicitacao.dados_inclusao["prazo_entrega"], "2026-11-30")

    def test_d43_07_tipo_so_nova_contratacao_ou_renovacao(self):
        self.assertTrue(self.incluir(tipo_id=self.tipo_renovacao.pk).pk)
        with self.assertRaisesMessage(services.PedidoInvalido, "Nova Contratação ou Renovação"):
            self.incluir(tipo_id=self.tipo_vigente.pk)

    def test_d43_07_unidade_e_uma_das_do_solicitante(self):
        with self.assertRaises(services.SemPermissao):
            self.incluir(unidade_id=self.outra_unidade.pk)

    def test_d43_07_campos_obrigatorios(self):
        for extra in ({"descricao_objeto": " "}, {"valor_estimado": "0"}, {"mes_previsto": 0}, {"justificativa": ""}):
            with self.subTest(extra=extra), self.assertRaises(services.PedidoInvalido):
                self.incluir(**extra)

    def test_aprovar_cria_o_item_com_o_proximo_numero_e_os_campos(self):
        solicitacao = self.incluir(prazo_entrega="2026-11-30")
        self.decidir(solicitacao, Campo.INCLUSAO, usuario=self.diretoria)
        item = Processo.objects.get(exercicio=self.exercicio, item_pca=4)
        self.assertEqual(item.descricao_objeto, "Licença de software")
        self.assertEqual(item.unidade_organizacional, self.unidade)
        self.assertEqual(item.tipo, self.tipo_nova)
        self.assertEqual(item.valor_estimado, Decimal("9000.00"))
        self.assertEqual((item.mes_previsto, item.prazo_entrega), (5, date(2026, 11, 30)))
        self.assertEqual(item.justificativa, "Demanda nova.")
        self.assertTrue(item.history.filter(history_user=self.diretoria).exists())
        solicitacao.refresh_from_db()
        self.assertEqual(solicitacao.processo, item)
        self.assertEqual(solicitacao.estado, EstadoSolicitacao.CONCLUIDA)

    def test_recusar_nao_cria_item(self):
        total = Processo.objects.count()
        solicitacao = self.incluir()
        self.decidir(solicitacao, Campo.INCLUSAO, Decisao.RECUSAR, usuario=self.diretoria)
        self.assertEqual(Processo.objects.count(), total)
        self.assertEqual(self.parte(solicitacao, Campo.INCLUSAO).estado, EstadoParte.RECUSADA)

    def test_inclusao_so_aprova_ou_recusa(self):
        solicitacao = self.incluir()
        with self.assertRaises(services.DecisaoInvalida):
            self.decidir(solicitacao, Campo.INCLUSAO, Decisao.AJUSTE, usuario=self.diretoria, valor_ajuste="x")

    def test_aprovar_com_exercicio_fechado_e_recusado(self):
        solicitacao = self.incluir()
        Exercicio.objects.filter(pk=self.exercicio.pk).update(situacao=SituacaoExercicio.FECHADO)
        with self.assertRaises(services.ItemNaoAceitaPedido):
            self.decidir(solicitacao, Campo.INCLUSAO, usuario=self.diretoria)
        self.assertEqual(self.parte(solicitacao, Campo.INCLUSAO).estado, EstadoParte.PENDENTE)


class TestAlcadas(Base):
    def test_d43_02_equipe_decide_prazo_e_mes_mas_nao_o_resto(self):
        solicitacao = self.pedir(mes_previsto=9, valor_estimado="2000")
        self.decidir(solicitacao, Campo.MES_PREVISTO, usuario=self.equipe)
        with self.assertRaises(services.SemPermissao):
            self.decidir(solicitacao, Campo.VALOR_ESTIMADO, usuario=self.equipe)

    def test_d43_02_diretoria_decide_o_resto_mas_nao_prazo_nem_mes(self):
        solicitacao = self.pedir(mes_previsto=9, valor_estimado="2000")
        self.decidir(solicitacao, Campo.VALOR_ESTIMADO, usuario=self.diretoria)
        with self.assertRaises(services.SemPermissao):
            self.decidir(solicitacao, Campo.MES_PREVISTO, usuario=self.diretoria)

    def test_d43_02_quem_esta_nos_dois_grupos_e_o_superusuario_decidem_tudo(self):
        solicitacao = self.pedir(mes_previsto=9, valor_estimado="2000")
        self.decidir(solicitacao, Campo.MES_PREVISTO, usuario=self.ambos)
        self.decidir(solicitacao, Campo.VALOR_ESTIMADO, usuario=self.ambos)
        outra = self.pedir(self.item_atrasado, mes_previsto=9, valor_estimado="2000")
        self.decidir(outra, Campo.MES_PREVISTO, usuario=self.admin)
        self.decidir(outra, Campo.VALOR_ESTIMADO, usuario=self.admin)

    def test_solicitante_e_visualizador_nao_decidem(self):
        solicitacao = self.pedir(mes_previsto=9)
        for usuario in (self.solicitante, self.visualizador):
            with self.subTest(usuario=usuario.email), self.assertRaises(services.SemPermissao):
                self.decidir(solicitacao, Campo.MES_PREVISTO, usuario=usuario)
        self.assertEqual(self.parte(solicitacao, Campo.MES_PREVISTO).estado, EstadoParte.PENDENTE)


class TestDecisao(Base):
    def test_d43_08_prazo_aprovado_vira_promessa_e_conta_prorrogacao(self):
        solicitacao = self.pedir(prazo_entrega=date(self.ano, 12, 20))
        self.decidir(solicitacao, Campo.PRAZO_ENTREGA, usuario=self.equipe)
        promessa = Acompanhamento.objects.get(processo=self.item, prazo_prometido__isnull=False)
        self.assertEqual(promessa.prazo_prometido, date(self.ano, 12, 20))
        self.assertIn(solicitacao.codigo, promessa.situacao_informada)
        self.assertEqual(promessa.evento, "Precisamos mudar.")
        self.assertTrue(promessa.history.filter(history_user=self.equipe).exists())
        atual = _item_atual(self.item)
        self.assertEqual((atual.prazo_efetivo, atual.n_prorrogacoes), (date(self.ano, 12, 20), 0))

        segunda = self.pedir(prazo_entrega=date(self.ano, 12, 28))
        self.decidir(segunda, Campo.PRAZO_ENTREGA, usuario=self.equipe)
        atual = _item_atual(self.item)
        self.assertEqual((atual.prazo_efetivo, atual.n_prorrogacoes), (date(self.ano, 12, 28), 1))

    def test_d43_08_prazo_de_item_atrasado_volta_a_no_prazo(self):
        solicitacao = self.pedir(self.item_atrasado, prazo_entrega=date(self.ano, 12, 20))
        self.decidir(solicitacao, Campo.PRAZO_ENTREGA, usuario=self.equipe)
        self.assertEqual(_item_atual(self.item_atrasado).situacao_efetiva, Situacao.NO_PRAZO)

    def test_d43_04_aprovar_com_ajuste_concede_o_valor_do_ajuste(self):
        solicitacao = self.pedir(prazo_entrega=date(self.ano, 12, 20))
        parte = self.decidir(
            solicitacao, Campo.PRAZO_ENTREGA, Decisao.AJUSTE, usuario=self.equipe,
            valor_ajuste=date(self.ano, 12, 10), motivo="Só conseguimos até o dia 10",
        )
        self.assertEqual(parte.estado, EstadoParte.APROVADA_AJUSTE)
        self.assertEqual((parte.valor_pedido, parte.valor_concedido), (f"{self.ano}-12-20", f"{self.ano}-12-10"))
        self.assertEqual(parte.motivo, "Só conseguimos até o dia 10")
        self.assertEqual(parte.decidido_por, self.equipe)
        self.assertIsNotNone(parte.decidido_em)
        self.assertEqual(_item_atual(self.item).prazo_efetivo, date(self.ano, 12, 10))

    def test_d43_04_ajuste_e_recusa_exigem_motivo_e_nada_muda_sem_ele(self):
        solicitacao = self.pedir(mes_previsto=9)
        parte = self.parte(solicitacao, Campo.MES_PREVISTO)
        with self.assertRaisesMessage(services.DecisaoInvalida, "motivo"):
            services.decidir_parte(
                parte_id=parte.pk, usuario=self.equipe, decisao=Decisao.AJUSTE, valor_ajuste=8
            )
        with self.assertRaisesMessage(services.DecisaoInvalida, "motivo"):
            services.decidir_parte(parte_id=parte.pk, usuario=self.equipe, decisao=Decisao.RECUSAR)
        parte.refresh_from_db()
        self.assertEqual(parte.estado, EstadoParte.PENDENTE)
        self.item.refresh_from_db()
        self.assertEqual(self.item.mes_previsto, 6)

    def test_d43_04_recusa_registra_o_motivo_e_nao_toca_o_item(self):
        solicitacao = self.pedir(valor_estimado="9999")
        parte = self.decidir(
            solicitacao, Campo.VALOR_ESTIMADO, Decisao.RECUSAR, usuario=self.diretoria, motivo="Sem verba"
        )
        self.assertEqual((parte.estado, parte.motivo, parte.valor_concedido), (EstadoParte.RECUSADA, "Sem verba", ""))
        self.item.refresh_from_db()
        self.assertEqual(self.item.valor_estimado, Decimal("1000.00"))

    def test_d43_08_mes_valor_e_objeto_atualizam_o_campo_com_autor_e_motivo_na_trilha(self):
        solicitacao = self.pedir(mes_previsto=9, valor_estimado="2500", descricao_objeto="Objeto revisto")
        self.decidir(solicitacao, Campo.MES_PREVISTO, usuario=self.equipe)
        self.decidir(solicitacao, Campo.VALOR_ESTIMADO, usuario=self.diretoria)
        self.decidir(solicitacao, Campo.DESCRICAO_OBJETO, usuario=self.diretoria)
        self.item.refresh_from_db()
        self.assertEqual(
            (self.item.mes_previsto, self.item.valor_estimado, self.item.descricao_objeto),
            (9, Decimal("2500.00"), "Objeto revisto"),
        )
        historico = list(self.item.history.order_by("-history_id")[:3])
        self.assertEqual({h.history_user for h in historico}, {self.equipe, self.diretoria})
        for registro in historico:
            self.assertIn(solicitacao.codigo, registro.history_change_reason)

    def test_d43_08_valor_com_ajuste_grava_o_ajuste(self):
        solicitacao = self.pedir(valor_estimado="2500")
        self.decidir(
            solicitacao, Campo.VALOR_ESTIMADO, Decisao.AJUSTE, usuario=self.diretoria, valor_ajuste="1800"
        )
        self.item.refresh_from_db()
        self.assertEqual(self.item.valor_estimado, Decimal("1800.00"))

    def test_d43_08_cancelamento_aprovado_cancela_o_item_com_o_motivo(self):
        solicitacao = self.pedir(justificativa="Contratação desnecessária", cancelamento=None)
        self.decidir(solicitacao, Campo.CANCELAMENTO, usuario=self.diretoria)
        self.item.refresh_from_db()
        self.assertEqual(self.item.estado, Estado.CANCELADO)
        registro = Acompanhamento.objects.filter(processo=self.item, situacao__nome="Cancelado").get()
        self.assertIn("Contratação desnecessária", registro.situacao_informada)
        self.assertIn(solicitacao.codigo, registro.situacao_informada)
        # a própria parte aprovada não vira "prejudicada" pelo gancho
        self.assertEqual(self.parte(solicitacao, Campo.CANCELAMENTO).estado, EstadoParte.APROVADA)

    def test_d43_03_cada_parte_vale_na_hora_e_a_solicitacao_fecha_na_ultima(self):
        solicitacao = self.pedir(prazo_entrega=date(self.ano, 12, 20), valor_estimado="3000")
        self.decidir(solicitacao, Campo.PRAZO_ENTREGA, usuario=self.equipe)
        solicitacao.refresh_from_db()
        self.assertEqual(solicitacao.estado, EstadoSolicitacao.PENDENTE)
        self.assertIsNone(solicitacao.encerrada_em)
        self.assertEqual(_item_atual(self.item).prazo_efetivo, date(self.ano, 12, 20))  # já vale
        self.decidir(solicitacao, Campo.VALOR_ESTIMADO, Decisao.RECUSAR, usuario=self.diretoria)
        solicitacao.refresh_from_db()
        self.assertEqual(solicitacao.estado, EstadoSolicitacao.CONCLUIDA)
        self.assertIsNotNone(solicitacao.encerrada_em)

    def test_parte_ja_decidida_nao_decide_de_novo(self):
        solicitacao = self.pedir(mes_previsto=9)
        self.decidir(solicitacao, Campo.MES_PREVISTO, usuario=self.equipe)
        with self.assertRaises(services.JaEncerrada):
            self.decidir(solicitacao, Campo.MES_PREVISTO, Decisao.RECUSAR, usuario=self.equipe)

    def test_aprovar_exige_que_o_item_ainda_aceite_o_campo_mas_recusar_vale(self):
        solicitacao = self.pedir(prazo_entrega=date(self.ano, 12, 20))
        self.item.situacao = Situacao.EM_TRAMITACAO
        self.item.save(update_fields=["situacao", "atualizado_em"])
        with self.assertRaises(services.ItemNaoAceitaPedido):
            self.decidir(solicitacao, Campo.PRAZO_ENTREGA, usuario=self.equipe)
        self.assertEqual(self.parte(solicitacao, Campo.PRAZO_ENTREGA).estado, EstadoParte.PENDENTE)
        self.decidir(solicitacao, Campo.PRAZO_ENTREGA, Decisao.RECUSAR, usuario=self.equipe)
        self.assertEqual(self.parte(solicitacao, Campo.PRAZO_ENTREGA).estado, EstadoParte.RECUSADA)

    def test_d43_13_a_decisao_entra_na_trilha_com_autor(self):
        solicitacao = self.pedir(mes_previsto=9)
        self.decidir(solicitacao, Campo.MES_PREVISTO, usuario=self.equipe)
        ultimo = self.parte(solicitacao, Campo.MES_PREVISTO).history.first()
        self.assertEqual((ultimo.history_user, ultimo.estado), (self.equipe, EstadoParte.APROVADA))


class TestPrejudicada(Base):
    """O item cancelado ou concluído por outro caminho encerra as pendentes."""

    def pendentes(self):
        return self.pedir(mes_previsto=9, valor_estimado="2500")

    def conferir_prejudicada(self, solicitacao, motivo):
        for parte in solicitacao.partes.all():
            parte.refresh_from_db()
            self.assertEqual(parte.estado, EstadoParte.PREJUDICADA)
            self.assertEqual(parte.motivo, motivo)
            self.assertIsNone(parte.decidido_por)
        solicitacao.refresh_from_db()
        self.assertEqual(solicitacao.estado, EstadoSolicitacao.CONCLUIDA)
        self.assertIsNotNone(solicitacao.encerrada_em)

    def test_cancelado_pelo_servico_alterar_estado_do_admin(self):
        solicitacao = self.pendentes()
        servicos_pca.alterar_estado(processo_id=self.item.pk, usuario=self.admin, estado_novo=Estado.CANCELADO)
        self.conferir_prejudicada(solicitacao, "Item cancelado.")

    def test_cancelado_por_edicao_completa_do_processo_no_admin(self):
        solicitacao = self.pendentes()
        item = Processo.objects.get(pk=self.item.pk)
        item.estado = Estado.CANCELADO
        item.save()
        self.conferir_prejudicada(solicitacao, "Item cancelado.")

    def test_concluido_pela_equipe_na_transicao_manual(self):
        solicitacao = self.pendentes()
        servicos_pca.registrar_acompanhamento(
            processo_id=self.item.pk, usuario=self.equipe,
            versao_cliente=Processo.objects.get(pk=self.item.pk).atualizado_em.isoformat(),
            situacao_novo=Situacao.CONCLUIDO, justificativa="Entregue",
        )
        self.conferir_prejudicada(solicitacao, "Item concluído.")

    def test_concluido_pela_regra_automatica_do_robo(self):
        solicitacao = self.pendentes()
        item = Processo.objects.select_related("tipo", "exercicio").get(pk=self.item.pk)
        item.data_assinatura_contrato = date(self.ano, 3, 1)
        item.save(update_fields=["data_assinatura_contrato", "atualizado_em"])
        servicos_pca.aplicar_regras_automaticas(processo=item, usuario=self.admin)
        self.assertEqual(Processo.objects.get(pk=self.item.pk).situacao, Situacao.CONCLUIDO)
        self.conferir_prejudicada(solicitacao, "Item concluído.")

    def test_nao_toca_partes_decididas_nem_pendentes_de_outros_itens(self):
        solicitacao = self.pendentes()
        self.decidir(solicitacao, Campo.MES_PREVISTO, usuario=self.equipe)
        outro = self.pedir(self.item_atrasado, mes_previsto=9)
        servicos_pca.alterar_estado(processo_id=self.item.pk, usuario=self.admin, estado_novo=Estado.CANCELADO)
        self.assertEqual(self.parte(solicitacao, Campo.MES_PREVISTO).estado, EstadoParte.APROVADA)
        self.assertEqual(self.parte(solicitacao, Campo.VALOR_ESTIMADO).estado, EstadoParte.PREJUDICADA)
        self.assertEqual(self.parte(outro, Campo.MES_PREVISTO).estado, EstadoParte.PENDENTE)
        solicitacao.refresh_from_db()
        self.assertEqual(solicitacao.estado, EstadoSolicitacao.CONCLUIDA)

    def test_prazo_aprovado_que_conclui_o_item_prejudica_as_outras_pendentes(self):
        vigente = self.novo_item(30, tipo=self.tipo_vigente, situacao=Situacao.NO_PRAZO)
        solicitacao = self.pedir(vigente, prazo_entrega=date(self.ano, 12, 20), valor_estimado="2500")
        self.decidir(solicitacao, Campo.PRAZO_ENTREGA, usuario=self.equipe)
        self.assertEqual(Processo.objects.get(pk=vigente.pk).situacao, Situacao.CONCLUIDO)
        self.assertEqual(self.parte(solicitacao, Campo.PRAZO_ENTREGA).estado, EstadoParte.APROVADA)
        self.assertEqual(self.parte(solicitacao, Campo.VALOR_ESTIMADO).estado, EstadoParte.PREJUDICADA)

    def test_salvar_o_item_sem_encerrar_nao_mexe_em_nada(self):
        solicitacao = self.pendentes()
        item = Processo.objects.get(pk=self.item.pk)
        item.descricao_objeto = "Editado na reunião"
        item.save()
        for parte in solicitacao.partes.all():
            parte.refresh_from_db()
            self.assertEqual(parte.estado, EstadoParte.PENDENTE)

    def test_hook_so_consulta_quando_o_save_pode_ter_encerrado(self):
        # `save(update_fields=[...])` sem estado/situacao não deve consultar as partes.
        item = Processo.objects.get(pk=self.item.pk)
        item.estado = Estado.CANCELADO  # em memória, sem gravar estado
        with CaptureQueriesContext(connection) as consultas:
            item.save(update_fields=["descricao_objeto"])
        self.assertFalse([q["sql"] for q in consultas if "solicitacoes_" in q["sql"]])


class TestDesistencia(Base):
    def test_d43_05_a_unidade_desiste_e_a_solicitacao_fica_desistida(self):
        solicitacao = self.pedir(mes_previsto=9, valor_estimado="2500")
        services.desistir(solicitacao_id=solicitacao.pk, usuario=self.colega)
        solicitacao.refresh_from_db()
        self.assertEqual(solicitacao.estado, EstadoSolicitacao.DESISTIDA)
        self.assertIsNotNone(solicitacao.encerrada_em)
        for parte in solicitacao.partes.all():
            self.assertEqual((parte.estado, parte.decidido_por), (EstadoParte.DESISTIDA, self.colega))
        self.assertEqual(solicitacao.history.first().history_user, self.colega)

    def test_depois_de_desistir_pode_pedir_de_novo(self):
        solicitacao = self.pedir(mes_previsto=9)
        services.desistir(solicitacao_id=solicitacao.pk, usuario=self.solicitante)
        self.assertEqual(self.pedir(mes_previsto=10).numero, 2)

    def test_so_a_propria_unidade_desiste(self):
        solicitacao = self.pedir(mes_previsto=9)
        for usuario in (self.solicitante_b, self.equipe, self.visualizador):
            with self.subTest(usuario=usuario.email), self.assertRaises(services.SemPermissao):
                services.desistir(solicitacao_id=solicitacao.pk, usuario=usuario)

    def test_desistir_de_solicitacao_encerrada_e_erro(self):
        solicitacao = self.pedir(mes_previsto=9)
        services.desistir(solicitacao_id=solicitacao.pk, usuario=self.solicitante)
        with self.assertRaises(services.JaEncerrada):
            services.desistir(solicitacao_id=solicitacao.pk, usuario=self.solicitante)

    def test_desistir_com_parte_ja_decidida_preserva_a_decisao(self):
        solicitacao = self.pedir(mes_previsto=9, valor_estimado="2500")
        self.decidir(solicitacao, Campo.MES_PREVISTO, usuario=self.equipe)
        services.desistir(solicitacao_id=solicitacao.pk, usuario=self.solicitante)
        self.assertEqual(self.parte(solicitacao, Campo.MES_PREVISTO).estado, EstadoParte.APROVADA)
        self.assertEqual(self.parte(solicitacao, Campo.VALOR_ESTIMADO).estado, EstadoParte.DESISTIDA)
        solicitacao.refresh_from_db()
        self.assertEqual(solicitacao.estado, EstadoSolicitacao.CONCLUIDA)


class TestFilaEVisibilidade(Base):
    def setUp(self):
        antiga = self.pedir(self.item, mes_previsto=9, valor_estimado="2500")
        Solicitacao.objects.filter(pk=antiga.pk).update(criada_em=now() - timedelta(days=30))
        self.antiga = antiga
        self.recente = self.pedir(self.item_atrasado, prazo_entrega=date(self.ano, 12, 20))

    def test_d43_11_a_fila_traz_so_a_alcada_de_quem_esta_logado_da_mais_antiga_para_a_mais_nova(self):
        equipe = list(services.partes_para_avaliar(self.equipe))
        self.assertEqual(
            [(p.solicitacao_id, p.campo) for p in equipe],
            [(self.antiga.pk, "mes_previsto"), (self.recente.pk, "prazo_entrega")],
        )
        diretoria = list(services.partes_para_avaliar(self.diretoria))
        self.assertEqual([(p.solicitacao_id, p.campo) for p in diretoria], [(self.antiga.pk, "valor_estimado")])
        self.assertEqual(services.contar_pendentes(self.equipe), 2)
        self.assertEqual(services.contar_pendentes(self.diretoria), 1)

    def test_quem_esta_nos_dois_e_o_superusuario_veem_tudo(self):
        self.assertEqual(services.contar_pendentes(self.ambos), 3)
        self.assertEqual(services.contar_pendentes(self.admin), 3)

    def test_solicitante_e_visualizador_nao_tem_fila(self):
        for usuario in (self.solicitante, self.visualizador):
            self.assertEqual(services.contar_pendentes(usuario), 0)
            self.assertEqual(list(services.partes_para_avaliar(usuario)), [])

    def test_parte_decidida_sai_da_fila(self):
        self.decidir(self.antiga, Campo.MES_PREVISTO, usuario=self.equipe)
        self.assertEqual(services.contar_pendentes(self.equipe), 1)

    def test_d43_10_solicitacoes_da_unidade_sao_vistas_pela_unidade_equipe_e_diretoria(self):
        ids = {self.antiga.pk, self.recente.pk}
        for usuario in (self.solicitante, self.colega, self.equipe, self.diretoria, self.admin):
            with self.subTest(usuario=usuario.email):
                self.assertEqual({s.pk for s in services.solicitacoes_visiveis(usuario)}, ids)
        for usuario in (self.solicitante_b, self.sem_vinculo, self.visualizador):
            with self.subTest(usuario=usuario.email):
                self.assertEqual(list(services.solicitacoes_visiveis(usuario)), [])

    def test_a_parada_ha_mais_de_10_dias_uteis_se_destaca_pela_regra(self):
        from django.utils.timezone import localdate, localtime

        from apps.solicitacoes import regras

        hoje = localdate()
        antiga = Solicitacao.objects.get(pk=self.antiga.pk)
        recente = Solicitacao.objects.get(pk=self.recente.pk)
        self.assertTrue(regras.esta_parada(localtime(antiga.criada_em).date(), hoje))
        self.assertFalse(regras.esta_parada(localtime(recente.criada_em).date(), hoje))


class TestPrejudicadaPeloRoboSei(Base):
    """pelo caminho real do robô: `aplicador.aplicar` (assinado por ambos conclui)."""

    def test_instrumento_assinado_por_ambos_conclui_e_prejudica_as_pendentes(self):
        import tempfile

        from django.test import override_settings

        from apps.pca.sei import aplicador
        from apps.pca.sei.regras import Proposta

        solicitacao = self.pedir(mes_previsto=9, valor_estimado="2500")
        proposta = Proposta(
            item_pca=self.item.item_pca,
            exercicio=self.ano,
            processo_principal="123",
            alteracoes={"data_assinatura_contrato": (None, date(self.ano, 3, 1))},
            evidencias=["Data de assinatura registrada."],
            pendencias=[],
            instrumento_assinado_por_ambos=True,
        )
        with tempfile.TemporaryDirectory() as pasta, override_settings(SEI_DATA_DIR=pasta):
            aplicador.aplicar([proposta])
        self.assertEqual(Processo.objects.get(pk=self.item.pk).situacao, Situacao.CONCLUIDO)
        for parte in solicitacao.partes.all():
            parte.refresh_from_db()
            self.assertEqual((parte.estado, parte.motivo), (EstadoParte.PREJUDICADA, "Item concluído."))
        solicitacao.refresh_from_db()
        self.assertEqual(solicitacao.estado, EstadoSolicitacao.CONCLUIDA)
