"""Migração física 0019->0020.

Prova, contra o schema histórico reconstruído (não os models atuais,
embora 0020 não altere schema algum — só dado): a correção retroativa de
R1/R2 sobre processos hoje inconsistentes, o "nunca toca cancelado", a
trilha de auditoria completa assinada por `importador@pca.local` e a
idempotência ao reaplicar a migração sobre um estado já corrigido.

Padrão consolidado por `test_prazo_migrations.py`/`test_multiexercicio_
migrations.py`: `TransactionTestCase(serialized_rollback=True)`, restauração
ao(s) nó(s)-folha via `addCleanup` chamando `MigrationExecutor(connection)
.migrate(...)` diretamente — nunca `tearDownClass` nem `call_command
('migrate')` nem `reset_sequences=True`."""

from datetime import date

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

ALVO_0019 = ("pca", "0019_status_enxuto_e_rename_gelic")
ALVO_0020 = ("pca", "0020_correcao_retroativa_status_automatico")

USUARIO_PADRAO_EMAIL = "importador@pca.local"


class MigracaoCorrecaoRetroativaTestCase(TransactionTestCase):
    """Migra fisicamente `pca` para trás até 0019 (a correção retroativa
    ainda não rodou), expõe os models do estado antigo via `apps.get_model` e
    sempre restaura ao(s) nó(s)-folha do grafo completo ao final — mesmo se o
    teste levantar exceção."""

    serialized_rollback = True

    def setUp(self):
        super().setUp()
        # Registrado PRIMEIRO: por ser LIFO, roda por ÚLTIMO — só depois de
        # qualquer fixup que um teste específico registre depois deste.
        self.addCleanup(
            lambda: MigrationExecutor(connection).migrate(
                MigrationExecutor(connection).loader.graph.leaf_nodes()
            )
        )
        MigrationExecutor(connection).migrate([ALVO_0019])
        old_state = MigrationExecutor(connection).loader.project_state([ALVO_0019])
        self.old_apps = old_state.apps
        self.OldProcesso = self.old_apps.get_model("pca", "Processo")
        self.OldAcompanhamento = self.old_apps.get_model("pca", "Acompanhamento")
        self.OldHistoricalProcesso = self.old_apps.get_model(
            "pca", "HistoricalProcesso"
        )
        self.OldHistoricalAcompanhamento = self.old_apps.get_model(
            "pca", "HistoricalAcompanhamento"
        )
        OldTipo = self.old_apps.get_model("catalogo", "Tipo")
        OldCategoria = self.old_apps.get_model("catalogo", "Categoria")
        OldUnidade = self.old_apps.get_model("catalogo", "Unidade")
        OldSituacaoNormalizada = self.old_apps.get_model(
            "catalogo", "SituacaoNormalizada"
        )
        OldExercicio = self.old_apps.get_model("catalogo", "Exercicio")
        OldUsuario = self.old_apps.get_model("core", "Usuario")

        self.tipo_nova = OldTipo.objects.create(
            nome="Nova Contratação", nome_normalizado="nova contratacao"
        )
        self.tipo_renovacao = OldTipo.objects.create(
            nome="Renovação", nome_normalizado="renovacao"
        )
        self.categoria = OldCategoria.objects.create(
            nome="Serviços", nome_normalizado="servicos"
        )
        self.unidade = OldUnidade.objects.create(
            nome="Presidência", nome_normalizado="presidencia"
        )
        for nome in ("Em tramitação", "Contrato vigente", "Concluído"):
            OldSituacaoNormalizada.objects.get_or_create(
                nome=nome,
                defaults={
                    "nome_normalizado": nome.lower()
                    .replace("ç", "c")
                    .replace("ã", "a")
                },
            )
        # `0008_backfill_exercicio_2026` já cria o exercício 2026 como parte
        # da migração normal até 0019 — `get_or_create` evita colidir com a
        # unicidade de `ano`.
        self.exercicio, _ = OldExercicio.objects.get_or_create(
            ano=2026, defaults={"rotulo": "PCA 2026"}
        )
        self.usuario_padrao, _ = OldUsuario.objects.get_or_create(
            email=USUARIO_PADRAO_EMAIL,
            defaults={"is_staff": False, "is_superuser": False},
        )

    def _processo(self, item_pca, *, tipo=None, status, **extra):
        return self.OldProcesso.objects.create(
            item_pca=item_pca,
            exercicio_id=self.exercicio.pk,
            descricao_objeto=f"Objeto {item_pca}",
            tipo_id=(tipo or self.tipo_nova).pk,
            categoria_id=self.categoria.pk,
            unidade_organizacional_id=self.unidade.pk,
            status=status,
            **extra,
        )

    def _aplicar_0020(self):
        MigrationExecutor(connection).migrate([ALVO_0020])


class TestR1CorrigeNaoIniciadoComGelicPreenchido(MigracaoCorrecaoRetroativaTestCase):
    def test_r1_sobe_nao_iniciado_para_em_tramitacao_com_trilha_completa(self):
        processo = self._processo(
            1, status="nao_iniciado", data_recebimento_gelic=date(2026, 3, 15)
        )

        self._aplicar_0020()

        processo_corrigido = self.OldProcesso.objects.get(pk=processo.pk)
        self.assertEqual(processo_corrigido.status, "em_tramitacao")

        acompanhamento = self.OldAcompanhamento.objects.get(processo_id=processo.pk)
        self.assertEqual(acompanhamento.tipo_evento, "automatico")
        self.assertIsNone(acompanhamento.reuniao_id)
        self.assertIn("Em tramitação", acompanhamento.situacao_informada)
        self.assertIn("15/03/2026", acompanhamento.situacao_informada)

        historico = self.OldHistoricalProcesso.objects.filter(
            id=processo.pk, history_type="~"
        ).order_by("-history_date")
        self.assertEqual(historico.count(), 1)
        self.assertEqual(historico.first().history_user_id, self.usuario_padrao.pk)
        self.assertEqual(historico.first().status, "em_tramitacao")


class TestR2RenovacaoComAssinaturaViraVigente(MigracaoCorrecaoRetroativaTestCase):
    def test_r2_renovacao_concluido_com_assinatura_vira_vigente(self):
        processo = self._processo(
            2,
            tipo=self.tipo_renovacao,
            status="concluido",
            data_assinatura_contrato=date(2026, 4, 1),
        )

        self._aplicar_0020()

        processo_corrigido = self.OldProcesso.objects.get(pk=processo.pk)
        self.assertEqual(processo_corrigido.status, "vigente")

        acompanhamento = self.OldAcompanhamento.objects.get(processo_id=processo.pk)
        self.assertEqual(acompanhamento.tipo_evento, "automatico")
        self.assertIsNone(acompanhamento.reuniao_id)


class TestR2NovaContratacaoComAssinaturaViraConcluido(MigracaoCorrecaoRetroativaTestCase):
    def test_r2_nova_contratacao_vigente_com_assinatura_vira_concluido(self):
        processo = self._processo(
            3,
            tipo=self.tipo_nova,
            status="vigente",
            data_assinatura_contrato=date(2026, 5, 10),
        )

        self._aplicar_0020()

        processo_corrigido = self.OldProcesso.objects.get(pk=processo.pk)
        self.assertEqual(processo_corrigido.status, "concluido")


class TestCanceladoNuncaETocado(MigracaoCorrecaoRetroativaTestCase):
    def test_cancelado_com_assinatura_permanece_cancelado_sem_novo_acompanhamento(
        self,
    ):
        processo = self._processo(
            4,
            tipo=self.tipo_renovacao,
            status="cancelado",
            data_assinatura_contrato=date(2026, 6, 1),
        )

        self._aplicar_0020()

        processo_apos = self.OldProcesso.objects.get(pk=processo.pk)
        self.assertEqual(processo_apos.status, "cancelado")
        self.assertEqual(
            self.OldAcompanhamento.objects.filter(processo_id=processo.pk).count(), 0
        )
        self.assertEqual(
            self.OldHistoricalProcesso.objects.filter(
                id=processo.pk, history_type="~"
            ).count(),
            0,
        )


class TestJaCorretoNaoGeraMudanca(MigracaoCorrecaoRetroativaTestCase):
    def test_em_tramitacao_ja_correto_nao_gera_acompanhamento_novo(self):
        processo = self._processo(
            5,
            status="em_tramitacao",
            data_recebimento_gelic=date(2026, 2, 1),
        )

        self._aplicar_0020()

        processo_apos = self.OldProcesso.objects.get(pk=processo.pk)
        self.assertEqual(processo_apos.status, "em_tramitacao")
        self.assertEqual(
            self.OldAcompanhamento.objects.filter(processo_id=processo.pk).count(), 0
        )
        self.assertEqual(
            self.OldHistoricalProcesso.objects.filter(
                id=processo.pk, history_type="~"
            ).count(),
            0,
        )


class TestIdempotenciaReaplicandoAMigracao(MigracaoCorrecaoRetroativaTestCase):
    def test_reaplicar_0020_sobre_estado_ja_corrigido_nao_duplica_nada(self):
        processo = self._processo(
            6, status="nao_iniciado", data_recebimento_gelic=date(2026, 3, 15)
        )

        self._aplicar_0020()

        acompanhamentos_antes = self.OldAcompanhamento.objects.filter(
            processo_id=processo.pk
        ).count()
        historicos_antes = self.OldHistoricalProcesso.objects.filter(
            id=processo.pk, history_type="~"
        ).count()
        self.assertEqual(acompanhamentos_antes, 1)
        self.assertEqual(historicos_antes, 1)

        # Desfaz a marca de "migração 0020 aplicada" (o reverse é `noop`,
        # dado intacto) e reaplica — a segunda execução do RunPython encontra
        # o processo já em `em_tramitacao` e não gera nada de novo.
        MigrationExecutor(connection).migrate([ALVO_0019])
        MigrationExecutor(connection).migrate([ALVO_0020])

        acompanhamentos_depois = self.OldAcompanhamento.objects.filter(
            processo_id=processo.pk
        ).count()
        historicos_depois = self.OldHistoricalProcesso.objects.filter(
            id=processo.pk, history_type="~"
        ).count()
        self.assertEqual(acompanhamentos_depois, 1)
        self.assertEqual(historicos_depois, 1)

        processo_apos = self.OldProcesso.objects.get(pk=processo.pk)
        self.assertEqual(processo_apos.status, "em_tramitacao")
