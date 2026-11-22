"""Regra de renovação × vigência (decisão do usuário).

Contrato vigente além do ano do PCA é sempre Concluído; contrato que renova
no ano (vigência termina no ano, ou Renovação sem vigência) só é Concluído
com contrato ou termo aditivo assinado NO ano — apostilamento nunca conta.
Vence a transição manual. Caso real: Pluxee, contrato 93/2024 assinado em
09/12/2024, vigência até 18/12/2026 — não pode estar concluído em 2026.
"""

from datetime import date
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from apps.catalogo.models import (
    Categoria,
    Exercicio,
    SituacaoExercicio,
    SituacaoNormalizada,
    Tipo,
    Unidade,
)
from apps.pca.models import (
    Acompanhamento,
    EventoFinanceiro,
    Processo,
    Situacao,
    TipoEvento,
)
from apps.pca.regras_situacao import (
    CONCLUIDO_OBRIGATORIO,
    CONCLUSAO_BLOQUEADA,
    exigencia_do_contrato,
    situacao_por_eventos,
)
from apps.pca import services
from apps.pca.services import (
    alternar_renovacao_prevista,
    aplicar_regras_automaticas,
    liberar_situacao_automatica,
    registrar_acompanhamento,
)


def _exigencia(**kwargs):
    base = {
        "ano_exercicio": 2026,
        "tipo_nome_normalizado": "renovacao",
        "vigencia_fim": None,
        "renovacao_prevista": True,
        "datas_assinatura": [],
    }
    base.update(kwargs)
    return exigencia_do_contrato(**base)


class TestRegraPura(SimpleTestCase):
    def test_vigente_alem_do_ano_e_sempre_concluido(self):
        exigencia, motivo = _exigencia(
            tipo_nome_normalizado="nova contratacao", vigencia_fim=date(2027, 3, 1)
        )
        self.assertEqual(exigencia, CONCLUIDO_OBRIGATORIO)
        self.assertIn("01/03/2027", motivo)

    def test_pluxee_renova_no_ano_com_contrato_antigo_nao_conclui(self):
        exigencia, motivo = _exigencia(
            vigencia_fim=date(2026, 12, 18), datas_assinatura=[date(2024, 12, 9)]
        )
        self.assertEqual(exigencia, CONCLUSAO_BLOQUEADA)
        self.assertIn("18/12/2026", motivo)
        # Nem a assinatura antiga nem o recebimento no Gelic do ciclo passado
        # contam: fica sem alvo (No prazo / Atrasado pela leitura).
        self.assertIsNone(
            situacao_por_eventos(
                tipo_nome_normalizado="renovacao",
                data_assinatura_contrato=date(2024, 12, 9),
                data_recebimento_gelic=date(2024, 11, 21),
                exigencia=exigencia,
            )
        )

    def test_aditivo_do_ano_anterior_nao_conclui_e_o_do_ano_conclui(self):
        self.assertEqual(
            _exigencia(vigencia_fim=date(2026, 12, 20), datas_assinatura=[date(2025, 12, 2)])[0],
            CONCLUSAO_BLOQUEADA,
        )
        self.assertEqual(
            _exigencia(vigencia_fim=date(2026, 12, 20), datas_assinatura=[date(2026, 12, 1)])[0],
            CONCLUIDO_OBRIGATORIO,
        )

    def test_vigente_que_renova_no_ano_tambem_exige_aditivo(self):
        exigencia, _ = _exigencia(tipo_nome_normalizado="vigente", vigencia_fim=date(2026, 9, 30))
        self.assertEqual(exigencia, CONCLUSAO_BLOQUEADA)
        self.assertIsNone(
            situacao_por_eventos(
                tipo_nome_normalizado="vigente",
                data_assinatura_contrato=None,
                data_recebimento_gelic=None,
                exigencia=exigencia,
            )
        )

    def test_recebimento_no_gelic_depois_da_ultima_assinatura_e_tramitacao(self):
        self.assertEqual(
            situacao_por_eventos(
                tipo_nome_normalizado="renovacao",
                data_assinatura_contrato=date(2025, 12, 2),
                data_recebimento_gelic=date(2026, 8, 1),
                exigencia=CONCLUSAO_BLOQUEADA,
            ),
            "em_tramitacao",
        )

    def test_renovacao_sem_vigencia_exige_aditivo_e_nova_contratacao_nao(self):
        self.assertEqual(_exigencia(datas_assinatura=[date(2025, 9, 18)])[0], CONCLUSAO_BLOQUEADA)
        self.assertEqual(
            _exigencia(tipo_nome_normalizado="nova contratacao", datas_assinatura=[date(2025, 9, 18)]),
            (None, None),
        )

    def test_regra_nao_se_aplica(self):
        # Renovação não prevista (contrato vai encerrar).
        self.assertEqual(
            _exigencia(vigencia_fim=date(2026, 6, 1), renovacao_prevista=False), (None, None)
        )
        # Vigência encerrada antes do ano do PCA.
        self.assertEqual(_exigencia(vigencia_fim=date(2025, 6, 1)), (None, None))
        # Sem exigência, a regra antiga segue igual (assinatura conclui).
        self.assertEqual(
            situacao_por_eventos(
                tipo_nome_normalizado="nova contratacao",
                data_assinatura_contrato=date(2025, 1, 1),
                data_recebimento_gelic=None,
            ),
            "concluido",
        )


class TestRegraNosServicos(TestCase):
    @classmethod
    def setUpTestData(cls):
        for nome in ("Concluído", "Em tramitação", "Sem informação"):
            SituacaoNormalizada.objects.get_or_create(nome=nome)
        cls.exercicio, _ = Exercicio.objects.get_or_create(
            ano=2026, defaults={"situacao": SituacaoExercicio.ABERTO}
        )
        cls.renovacao = Tipo.objects.create(nome="Renovação")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.unidade = Unidade.objects.create(nome="Gerência de Teste")
        cls.usuario = get_user_model().objects.create_superuser(
            email="equipe@example.com", password="x"
        )

    def _processo(self, *, item, vigencia_fim, assinatura, situacao=Situacao.CONCLUIDO, gelic=None):
        processo = Processo(
            item_pca=item,
            exercicio=self.exercicio,
            descricao_objeto=f"Contrato {item}",
            tipo=self.renovacao,
            categoria=self.categoria,
            unidade_organizacional=self.unidade,
            estado="ativo",
            situacao=situacao,
            vigencia_fim=vigencia_fim,
            data_assinatura_contrato=assinatura,
            data_recebimento_gelic=gelic,
            renovacao_prevista=True,
        )
        processo._history_user = self.usuario
        processo.save()
        return processo

    def _manual(self, processo, destino):
        return registrar_acompanhamento(
            processo_id=processo.pk,
            usuario=self.usuario,
            versao_cliente=processo.atualizado_em.isoformat(),
            situacao_novo=destino,
            justificativa="teste",
        )

    def test_pluxee_sai_de_concluido_mesmo_com_transicao_manual(self):
        processo = self._processo(item=135, vigencia_fim=date(2026, 12, 18), assinatura=date(2024, 12, 9))
        Acompanhamento.objects.create(
            processo=processo, referencia_data=date(2026, 1, 10), origem_hash="manual-antigo",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO,
            situacao=SituacaoNormalizada.objects.get(nome="Concluído"), transicao_manual=True,
        )
        atualizado = aplicar_regras_automaticas(processo=processo, usuario=self.usuario)
        self.assertEqual(atualizado.situacao, Situacao.NO_PRAZO)
        ultimo = processo.acompanhamentos.order_by("-id").first()
        self.assertEqual(ultimo.tipo_evento, TipoEvento.AUTOMATICO)
        self.assertIn("18/12/2026", ultimo.situacao_informada)
        self.assertIn("não há contrato ou termo aditivo assinado em 2026", ultimo.situacao_informada)
        # Idempotente: rodar de novo não gera outro acompanhamento.
        processo.refresh_from_db()
        self.assertIsNone(aplicar_regras_automaticas(processo=processo, usuario=self.usuario))

    def test_apostilamento_do_ano_nao_conclui_aditivo_do_ano_conclui(self):
        processo = self._processo(
            item=130, vigencia_fim=date(2026, 12, 20), assinatura=date(2025, 12, 2),
            situacao=Situacao.NO_PRAZO,
        )
        EventoFinanceiro.objects.create(
            processo=processo, data=date(2026, 3, 1), tipo="apostilamento",
            valor=Decimal("10.00"), origem="robo",
        )
        self.assertIsNone(aplicar_regras_automaticas(processo=processo, usuario=self.usuario))
        EventoFinanceiro.objects.create(
            processo=processo, data=date(2026, 12, 1), tipo="aditivo",
            valor=Decimal("10.00"), origem="robo",
        )
        atualizado = aplicar_regras_automaticas(processo=processo, usuario=self.usuario)
        self.assertEqual(atualizado.situacao, Situacao.CONCLUIDO)

    def test_transicao_manual_para_concluido_prevalece_e_liga_a_trava(self):
        # 29/09/2026 (decisão do usuário) — a escolha manual vale até ser desmarcada no Admin, mesmo
        # contra a regra de renovação × vigência; `situacao_regra` guarda o que a regra aplicaria.
        processo = self._processo(
            item=115, vigencia_fim=date(2026, 10, 29), assinatura=date(2025, 10, 30),
            situacao=Situacao.NO_PRAZO,
        )
        atualizado = self._manual(processo, Situacao.CONCLUIDO)
        self.assertEqual(atualizado.situacao, Situacao.CONCLUIDO)
        self.assertTrue(atualizado.situacao_manual)
        self.assertEqual(atualizado.situacao_regra, Situacao.NO_PRAZO)
        processo.refresh_from_db()
        self.assertIsNone(aplicar_regras_automaticas(processo=processo, usuario=self.usuario))
        processo.refresh_from_db()
        self.assertEqual(processo.situacao, Situacao.CONCLUIDO)

    def test_manual_prevalece_ate_liberar_no_admin(self):
        processo = self._processo(
            item=20, vigencia_fim=date(2027, 5, 1), assinatura=None, situacao=Situacao.NO_PRAZO
        )
        atualizado = self._manual(processo, Situacao.ATRASADO)
        self.assertEqual(atualizado.situacao, Situacao.ATRASADO)
        self.assertEqual(atualizado.situacao_regra, Situacao.CONCLUIDO)
        liberado = liberar_situacao_automatica(processo_id=processo.pk, usuario=self.usuario)
        self.assertFalse(liberado.situacao_manual)
        self.assertEqual(liberado.situacao, Situacao.CONCLUIDO)
        self.assertEqual(liberado.situacao_regra, "")
        textos = " ".join(processo.acompanhamentos.values_list("situacao_informada", flat=True))
        self.assertIn("liberada para as regras automáticas", textos)

    def test_tela_de_transicao_aceita_a_escolha_manual(self):
        processo = self._processo(
            item=129, vigencia_fim=None, assinatura=date(2025, 11, 28), situacao=Situacao.NO_PRAZO
        )
        cliente = Client(HTTP_X_FORWARDED_PROTO="https")
        cliente.force_login(self.usuario)
        resposta = cliente.post(
            reverse("pca:transicao_processo", args=[2026, 129]),
            {"destino": Situacao.CONCLUIDO, "justificativa": "assinado", "versao": processo.atualizado_em.isoformat()},
        )
        self.assertEqual(resposta.status_code, 302)
        processo.refresh_from_db()
        self.assertEqual(processo.situacao, Situacao.CONCLUIDO)
        self.assertTrue(processo.situacao_manual)

    def test_vigencia_vencida_sem_aditivo_aparece_atrasado(self):
        self._processo(
            item=13, vigencia_fim=date(2026, 1, 2), assinatura=date(2025, 12, 18),
            situacao=Situacao.NO_PRAZO,
        )
        lido = Processo.objects.para_listagem().get(item_pca=13)
        self.assertEqual(lido.situacao_efetiva, Situacao.ATRASADO)

    def test_prazo_vencido_de_renovacao_pendente_so_e_atrasado_sem_a_trava(self):
        processo = self._processo(
            item=114, vigencia_fim=None, assinatura=date(2025, 10, 14), situacao=Situacao.NO_PRAZO
        )
        processo.prazo_entrega = date(2026, 1, 2)
        processo.save()
        self.assertEqual(Processo.objects.para_listagem().get(item_pca=114).situacao_efetiva, Situacao.ATRASADO)
        processo.situacao_manual = True
        processo.save(update_fields=["situacao_manual"])
        lido = Processo.objects.para_listagem().get(item_pca=114)
        self.assertTrue(lido.sobreposicao_manual_ativa)
        self.assertEqual(lido.situacao_efetiva, Situacao.NO_PRAZO)

    def test_admin_desmarcar_situacao_manual_libera_e_recalcula(self):
        from types import SimpleNamespace

        from django.contrib.admin.sites import site
        from django.test import RequestFactory

        processo = self._processo(
            item=21, vigencia_fim=date(2027, 5, 1), assinatura=None, situacao=Situacao.NO_PRAZO
        )
        processo = self._manual(processo, Situacao.ATRASADO)
        modelo_admin = site._registry[Processo]
        requisicao = RequestFactory().post("/")
        requisicao.user = self.usuario
        processo.situacao_manual = False
        modelo_admin.save_model(requisicao, processo, SimpleNamespace(changed_data=["situacao_manual"]), True)
        processo.refresh_from_db()
        self.assertFalse(processo.situacao_manual)
        self.assertEqual(processo.situacao, Situacao.CONCLUIDO)

    def test_inicio_avisa_situacao_manual_divergente(self):
        processo = self._processo(
            item=22, vigencia_fim=date(2027, 5, 1), assinatura=None, situacao=Situacao.NO_PRAZO
        )
        self._manual(processo, Situacao.ATRASADO)
        cliente = Client(HTTP_X_FORWARDED_PROTO="https")
        cliente.force_login(self.usuario)
        resposta = cliente.get(reverse("core:inicio"))
        self.assertContains(resposta, "Situação manual diferente das regras automáticas")
        self.assertContains(resposta, "pelas regras: Concluído")

    def test_desmarcar_renovacao_encerra_e_conclui(self):
        processo = self._processo(
            item=35, vigencia_fim=date(2026, 9, 10), assinatura=date(2025, 9, 10),
            situacao=Situacao.NO_PRAZO,
        )
        alternar_renovacao_prevista(processo_id=processo.pk, usuario=self.usuario, renovacao_prevista=False)
        processo.refresh_from_db()
        self.assertEqual(processo.situacao, Situacao.CONCLUIDO)

    def test_renovar_em_exercicio_fechado_recusa_e_nao_grava(self):
        # QA 30/09 (achados fluxos nº4/dominio nº4) — "renovar?" não pode gravar em exercício
        # encerrado; ExercicioFechado é levantada ANTES de qualquer save().
        fechado, _ = Exercicio.objects.get_or_create(
            ano=2020, defaults={"situacao": SituacaoExercicio.FECHADO}
        )
        processo = Processo(
            item_pca=1,
            exercicio=fechado,
            descricao_objeto="Contrato fechado",
            tipo=self.renovacao,
            categoria=self.categoria,
            unidade_organizacional=self.unidade,
            estado="ativo",
            situacao=Situacao.NO_PRAZO,
            renovacao_prevista=False,
        )
        processo._history_user = self.usuario
        processo.save()
        with self.assertRaises(services.ExercicioFechado):
            alternar_renovacao_prevista(
                processo_id=processo.pk, usuario=self.usuario, renovacao_prevista=True
            )
        processo.refresh_from_db()
        self.assertFalse(processo.renovacao_prevista)

    def test_comando_simula_por_padrao_e_aplica_com_flag(self):
        processo = self._processo(item=135, vigencia_fim=date(2026, 12, 18), assinatura=date(2024, 12, 9))
        saida = StringIO()
        call_command("recalcular_situacao_vigencia", "--exercicio=2026", f"--usuario={self.usuario.email}", stdout=saida)
        self.assertIn("item 135", saida.getvalue())
        self.assertIn("simulação", saida.getvalue())
        processo.refresh_from_db()
        self.assertEqual(processo.situacao, Situacao.CONCLUIDO)
        call_command(
            "recalcular_situacao_vigencia", "--exercicio=2026", f"--usuario={self.usuario.email}",
            "--aplicar", stdout=StringIO(),
        )
        processo.refresh_from_db()
        self.assertEqual(processo.situacao, Situacao.NO_PRAZO)
