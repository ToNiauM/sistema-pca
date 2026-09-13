"""Migration contract for the annual PCA identity (Phase 05-01)."""

from datetime import date

from django.apps import apps as django_apps
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone

from apps.catalogo.models import Categoria, Exercicio, SituacaoExercicio, Tipo, Unidade
from apps.pca.models import HistoricalProcesso, Processo, Reuniao


class TestMultiexercicioMigration(TransactionTestCase):
    """Prove the nullable -> backfill -> required migration contract."""

    serialized_rollback = True

    def test_existing_rows_and_history_are_backfilled_without_new_audit_rows(self):
        executor = MigrationExecutor(connection)
        # Restore the schema to the most recent migration of ALL apps before the
        # framework's flush/serialized_rollback teardown, so later TransactionTestCase
        # classes don't run against a schema stuck at 0009. Must be addCleanup inside
        # the method (not tearDownClass): tearDownClass runs AFTER the flush, where
        # re-migrating re-emits post_migrate over an already-restored state.
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(MigrationExecutor(connection).loader.graph.leaf_nodes()))
        executor.migrate([("catalogo", "0001_initial"), ("pca", "0006_fornecedor_cnpj_validators")])
        old_apps = executor.loader.project_state(
            [("catalogo", "0001_initial"), ("pca", "0006_fornecedor_cnpj_validators")]
        ).apps

        OldTipo = old_apps.get_model("catalogo", "Tipo")
        OldCategoria = old_apps.get_model("catalogo", "Categoria")
        OldUnidade = old_apps.get_model("catalogo", "Unidade")
        OldProcesso = old_apps.get_model("pca", "Processo")
        OldHistorico = old_apps.get_model("pca", "HistoricalProcesso")
        OldReuniao = old_apps.get_model("pca", "Reuniao")

        tipo = OldTipo.objects.create(nome="Aquisição", nome_normalizado="aquisicao")
        categoria = OldCategoria.objects.create(nome="Serviços", nome_normalizado="servicos")
        unidade = OldUnidade.objects.create(nome="Presidência", nome_normalizado="presidencia")
        processo = OldProcesso.objects.create(
            item_pca=65,
            descricao_objeto="Contrato anual",
            tipo_id=tipo.pk,
            categoria_id=categoria.pk,
            unidade_organizacional_id=unidade.pk,
            status="em_tramitacao",
        )
        OldHistorico.objects.create(
            id=processo.pk,
            item_pca=processo.item_pca,
            descricao_objeto=processo.descricao_objeto,
            status=processo.status,
            atualizado_em=timezone.now(),
            history_date=timezone.now(),
            history_type="+",
        )
        OldReuniao.objects.create(data=date(2026, 8, 1), situacao="fechada")
        historico_antes = OldHistorico.objects.count()

        MigrationExecutor(connection).migrate([("pca", "0009_exercicio_obrigatorio")])
        # quick-260810-pw0 — as asserções abaixo usam os modelos ATUAIS
        # (importados no topo do arquivo), que incluem todo campo acrescentado
        # por migração desde então (0010+). Sem avançar o schema físico até a
        # folha do grafo de `pca`, o SELECT do ORM atual quebra contra um
        # schema parado em 0009 sempre que uma migração nova acrescenta uma
        # coluna — o contrato de backfill (nullable -> obrigatório) sendo
        # provado por este teste já está completo neste ponto; avançar mais
        # não o invalida, só evita que o teste fique preso a um alvo velho.
        folha_pca = next(
            no
            for no in MigrationExecutor(connection).loader.graph.leaf_nodes()
            if no[0] == "pca"
        )
        MigrationExecutor(connection).migrate([folha_pca])

        self.assertEqual(Exercicio.objects.get(ano=2026).rotulo, "PCA 2026")
        self.assertEqual(Processo.objects.get(item_pca=65).exercicio.ano, 2026)
        self.assertEqual(
            HistoricalProcesso.objects.filter(exercicio__isnull=True).count(), 0
        )
        self.assertEqual(Reuniao.objects.get(data=date(2026, 8, 1)).exercicio.ano, 2026)
        self.assertEqual(HistoricalProcesso.objects.count(), historico_antes)

    def test_annual_identity_allows_same_item_in_two_years_but_not_within_one(self):
        exercicio_2026 = Exercicio.objects.get(ano=2026)
        tipo = Tipo.objects.create(nome="Aquisição")
        categoria = Categoria.objects.create(nome="Serviços")
        unidade = Unidade.objects.create(nome="Presidência")
        processo_2026 = Processo.objects.create(
            item_pca=65,
            descricao_objeto="Contrato anual",
            tipo=tipo,
            categoria=categoria,
            unidade_organizacional=unidade,
            exercicio=exercicio_2026,
        )
        exercicio_2027 = Exercicio.objects.create(
            id=Exercicio.objects.order_by("-id").first().pk + 1,
            ano=2027, rotulo="PCA 2027", situacao=SituacaoExercicio.ABERTO
        )

        Processo.objects.create(
            item_pca=65,
            descricao_objeto="Continuação anual",
            tipo=processo_2026.tipo,
            categoria=processo_2026.categoria,
            unidade_organizacional=processo_2026.unidade_organizacional,
            exercicio=exercicio_2027,
        )

        with self.assertRaises(Exception):
            Processo.objects.create(
                item_pca=65,
                descricao_objeto="Duplicata inválida",
                tipo=processo_2026.tipo,
                categoria=processo_2026.categoria,
                unidade_organizacional=processo_2026.unidade_organizacional,
                exercicio=exercicio_2026,
            )

    def test_process_and_meeting_exercise_fields_are_required(self):
        processo_field = Processo._meta.get_field("exercicio")
        reuniao_field = Reuniao._meta.get_field("exercicio")
        historico_field = HistoricalProcesso._meta.get_field("exercicio")

        self.assertFalse(processo_field.null)
        self.assertFalse(reuniao_field.null)
        self.assertEqual(processo_field.remote_field.on_delete.__name__, "PROTECT")
        self.assertEqual(reuniao_field.remote_field.on_delete.__name__, "PROTECT")
        self.assertTrue(
            any(
                constraint.name == "pca_processo_exercicio_item_unico"
                for constraint in Processo._meta.constraints
            )
        )
