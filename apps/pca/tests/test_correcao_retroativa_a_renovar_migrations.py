"""Migração física 0021->0022.

Prova, contra o schema histórico reconstruído: a correção retroativa de R3
sobre processos hoje `vigente` cuja `vigencia_fim` cai dentro do ano do
próprio exercício, o "nunca toca cancelado" (filtro `status="vigente"`
exclui por construção), a trilha de auditoria completa assinada por
`importador@pca.local` e a idempotência estrutural ao reaplicar a
migração sobre um estado já corrigido.

Padrão consolidado por `test_correcao_retroativa_migrations.py`:
`TransactionTestCase(serialized_rollback=True)`, restauração ao(s) nó(s)-
folha via `addCleanup` chamando `MigrationExecutor(connection).migrate(...)`
diretamente — nunca `tearDownClass` nem `call_command('migrate')` nem
`reset_sequences=True`."""

from datetime import date

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

ALVO_0021 = ("pca", "0021_status_a_renovar")
ALVO_0022 = ("pca", "0022_correcao_retroativa_a_renovar")

USUARIO_PADRAO_EMAIL = "importador@pca.local"


class MigracaoCorrecaoRetroativaARenovarTestCase(TransactionTestCase):
    """Migra fisicamente `pca` para trás até 0021 (a correção retroativa de
    a_renovar ainda não rodou), expõe os models do estado antigo via
    `apps.get_model` e sempre restaura ao(s) nó(s)-folha do grafo completo ao
    final — mesmo se o teste levantar exceção."""

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
        MigrationExecutor(connection).migrate([ALVO_0021])
        old_state = MigrationExecutor(connection).loader.project_state([ALVO_0021])
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

        self.tipo_renovacao = OldTipo.objects.create(
            nome="Renovação", nome_normalizado="renovacao"
        )
        self.categoria = OldCategoria.objects.create(
            nome="Serviços", nome_normalizado="servicos"
        )
        self.unidade = OldUnidade.objects.create(
            nome="Presidência", nome_normalizado="presidencia"
        )
        for nome in ("Contrato vigente", "Cancelado"):
            OldSituacaoNormalizada.objects.get_or_create(
                nome=nome,
                defaults={
                    "nome_normalizado": nome.lower()
                    .replace("ç", "c")
                    .replace("ã", "a")
                },
            )
        # `0008_backfill_exercicio_2026` já cria o exercício 2026 como parte
        # da migração normal até 0021 — `get_or_create` evita colidir com a
        # unicidade de `ano`.
        self.exercicio, _ = OldExercicio.objects.get_or_create(
            ano=2026, defaults={"rotulo": "PCA 2026"}
        )
        self.usuario_padrao, _ = OldUsuario.objects.get_or_create(
            email=USUARIO_PADRAO_EMAIL,
            defaults={"is_staff": False, "is_superuser": False},
        )

    def _processo(self, item_pca, *, status, **extra):
        return self.OldProcesso.objects.create(
            item_pca=item_pca,
            exercicio_id=self.exercicio.pk,
            descricao_objeto=f"Objeto {item_pca}",
            tipo_id=self.tipo_renovacao.pk,
            categoria_id=self.categoria.pk,
            unidade_organizacional_id=self.unidade.pk,
            status=status,
            **extra,
        )

    def _aplicar_0022(self):
        MigrationExecutor(connection).migrate([ALVO_0022])


class TestVigenteComVigenciaFimNoAnoViraARenovar(
    MigracaoCorrecaoRetroativaARenovarTestCase
):
    def test_vigente_com_vigencia_fim_no_ano_do_exercicio_vira_a_renovar_com_trilha_completa(
        self,
    ):
        processo = self._processo(
            1, status="vigente", vigencia_fim=date(2026, 12, 31)
        )

        self._aplicar_0022()

        processo_corrigido = self.OldProcesso.objects.get(pk=processo.pk)
        self.assertEqual(processo_corrigido.status, "a_renovar")

        acompanhamento = self.OldAcompanhamento.objects.get(processo_id=processo.pk)
        self.assertEqual(acompanhamento.tipo_evento, "automatico")
        self.assertIsNone(acompanhamento.reuniao_id)
        self.assertIn("A renovar", acompanhamento.situacao_informada)
        self.assertIn("31/12/2026", acompanhamento.situacao_informada)

        historico = self.OldHistoricalProcesso.objects.filter(
            id=processo.pk, history_type="~"
        ).order_by("-history_date")
        self.assertEqual(historico.count(), 1)
        self.assertEqual(historico.first().history_user_id, self.usuario_padrao.pk)
        self.assertEqual(historico.first().status, "a_renovar")

        historico_acompanhamento = self.OldHistoricalAcompanhamento.objects.filter(
            id=acompanhamento.pk, history_type="+"
        )
        self.assertEqual(historico_acompanhamento.count(), 1)
        self.assertEqual(
            historico_acompanhamento.first().history_user_id, self.usuario_padrao.pk
        )


class TestVigenteComVigenciaFimForaDoAnoNaoMuda(
    MigracaoCorrecaoRetroativaARenovarTestCase
):
    def test_vigente_com_vigencia_fim_fora_do_ano_do_exercicio_permanece_vigente(
        self,
    ):
        processo = self._processo(
            2, status="vigente", vigencia_fim=date(2027, 1, 17)
        )

        self._aplicar_0022()

        processo_apos = self.OldProcesso.objects.get(pk=processo.pk)
        self.assertEqual(processo_apos.status, "vigente")
        self.assertEqual(
            self.OldAcompanhamento.objects.filter(processo_id=processo.pk).count(), 0
        )


class TestVigenteSemVigenciaFimNaoMuda(MigracaoCorrecaoRetroativaARenovarTestCase):
    def test_vigente_sem_vigencia_fim_permanece_vigente(self):
        processo = self._processo(3, status="vigente", vigencia_fim=None)

        self._aplicar_0022()

        processo_apos = self.OldProcesso.objects.get(pk=processo.pk)
        self.assertEqual(processo_apos.status, "vigente")
        self.assertEqual(
            self.OldAcompanhamento.objects.filter(processo_id=processo.pk).count(), 0
        )


class TestCanceladoNuncaETocado(MigracaoCorrecaoRetroativaARenovarTestCase):
    def test_cancelado_com_vigencia_fim_no_ano_do_exercicio_permanece_cancelado(self):
        processo = self._processo(
            4, status="cancelado", vigencia_fim=date(2026, 6, 30)
        )

        self._aplicar_0022()

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


class TestIdempotenciaReaplicandoAMigracao(MigracaoCorrecaoRetroativaARenovarTestCase):
    def test_reaplicar_0022_sobre_estado_ja_corrigido_nao_duplica_nada(self):
        processo = self._processo(
            5, status="vigente", vigencia_fim=date(2026, 12, 31)
        )

        self._aplicar_0022()

        acompanhamentos_antes = self.OldAcompanhamento.objects.filter(
            processo_id=processo.pk
        ).count()
        historicos_antes = self.OldHistoricalProcesso.objects.filter(
            id=processo.pk, history_type="~"
        ).count()
        self.assertEqual(acompanhamentos_antes, 1)
        self.assertEqual(historicos_antes, 1)

        # Desfaz a marca de "migração 0022 aplicada" (o reverse é `noop`,
        # dado intacto) e reaplica — a segunda execução do RunPython encontra
        # o processo já em `a_renovar`, e o filtro base `status="vigente"`
        # deixa de selecioná-lo: idempotência estrutural, não apenas
        # comparação de alvo.
        MigrationExecutor(connection).migrate([ALVO_0021])
        MigrationExecutor(connection).migrate([ALVO_0022])

        acompanhamentos_depois = self.OldAcompanhamento.objects.filter(
            processo_id=processo.pk
        ).count()
        historicos_depois = self.OldHistoricalProcesso.objects.filter(
            id=processo.pk, history_type="~"
        ).count()
        self.assertEqual(acompanhamentos_depois, 1)
        self.assertEqual(historicos_depois, 1)

        processo_apos = self.OldProcesso.objects.get(pk=processo.pk)
        self.assertEqual(processo_apos.status, "a_renovar")
