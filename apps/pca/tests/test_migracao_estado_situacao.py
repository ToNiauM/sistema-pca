"""Migração física 0022->0023.

Prova, contra o schema histórico reconstruído: cobertura total (todo
processo sai com `estado`/`situacao` não nulos), o mapeamento exato
reproduzido fresco (não copiado dos números de produção) e a
idempotência do backfill ao reaplicar a função Python sobre o estado já
migrado.

Padrão consolidado por `test_correcao_retroativa_a_renovar_migrations.py`:
`TransactionTestCase(serialized_rollback=True)`, restauração ao(s) nó(s)-
folha via `addCleanup` chamando `MigrationExecutor(connection).migrate(...)`
diretamente — nunca `tearDownClass` nem `call_command('migrate')` nem
`reset_sequences=True`."""

from datetime import date, timedelta

from django.db import connection, models
from django.db.migrations.executor import MigrationExecutor
from django.db.models import Q
from django.test import TransactionTestCase
from django.utils import timezone

ALVO_0022 = ("pca", "0022_correcao_retroativa_a_renovar")
ALVO_0023 = ("pca", "0023_estado_situacao_tres_eixos")


class MigracaoEstadoSituacaoTestCase(TransactionTestCase):
    """Migra fisicamente `pca` para trás até 0022 (estado/situacao ainda não
    existem), expõe os models do estado antigo via `apps.get_model` e sempre
    restaura ao(s) nó(s)-folha do grafo completo ao final — mesmo se o teste
    levantar exceção."""

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
        MigrationExecutor(connection).migrate([ALVO_0022])
        old_state = MigrationExecutor(connection).loader.project_state([ALVO_0022])
        self.old_apps = old_state.apps
        self.OldProcesso = self.old_apps.get_model("pca", "Processo")
        OldTipo = self.old_apps.get_model("catalogo", "Tipo")
        OldCategoria = self.old_apps.get_model("catalogo", "Categoria")
        OldUnidade = self.old_apps.get_model("catalogo", "Unidade")
        OldExercicio = self.old_apps.get_model("catalogo", "Exercicio")

        self.tipo_nova = OldTipo.objects.create(
            nome="Nova Contratação", nome_normalizado="nova contratacao"
        )
        self.tipo_renovacao = OldTipo.objects.create(
            nome="Renovação", nome_normalizado="renovacao"
        )
        self.tipo_vigente = OldTipo.objects.create(
            nome="Vigente", nome_normalizado="vigente"
        )
        self.categoria = OldCategoria.objects.create(
            nome="Serviços", nome_normalizado="servicos"
        )
        self.unidade = OldUnidade.objects.create(
            nome="Presidência", nome_normalizado="presidencia"
        )
        # `0008_backfill_exercicio_2026` já cria o exercício 2026 como parte
        # da migração normal até 0022 — `get_or_create` evita colidir com a
        # unicidade de `ano`.
        self.exercicio, _ = OldExercicio.objects.get_or_create(
            ano=2026, defaults={"rotulo": "PCA 2026"}
        )

    def _processo(self, item_pca, *, status, tipo=None, **extra):
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

    def _aplicar_0023(self):
        MigrationExecutor(connection).migrate([ALVO_0023])


class TestCoberturaTotalSemNulos(MigracaoEstadoSituacaoTestCase):
    """Nenhum processo fica com estado/situacao nulos após a migração."""

    def test_todo_processo_tem_estado_e_situacao_preenchidos(self):
        self._processo(1, status="cancelado")
        self._processo(2, status="concluido", data_assinatura_contrato=date(2026, 6, 1))
        self._processo(3, status="vigente", tipo=self.tipo_vigente)
        self._processo(4, status="em_tramitacao", data_recebimento_gelic=date(2026, 5, 1))
        self._processo(5, status="nao_iniciado")

        self._aplicar_0023()

        Processo = MigrationExecutor(connection).loader.project_state(
            [ALVO_0023]
        ).apps.get_model("pca", "Processo")
        pendentes = models.QuerySet(model=Processo, using="default").filter(
            Q(estado__isnull=True) | Q(situacao__isnull=True)
        ).count()
        self.assertEqual(pendentes, 0)


class TestMapeamentoD48Exato(MigracaoEstadoSituacaoTestCase):
    """Reproduz fresco no teste a contagem por combinação
    (status_legado, estado, situacao), sem copiar números de outro
    lugar."""

    def test_mapeamento_exato_por_status_legado(self):
        hoje = timezone.localdate()
        ontem = hoje - timedelta(days=1)
        amanha = hoje + timedelta(days=1)

        cancelado = self._processo(1, status="cancelado")
        concluido = self._processo(
            2, status="concluido", data_assinatura_contrato=date(2026, 6, 1)
        )
        vigente_tipo_vigente = self._processo(
            3, status="vigente", tipo=self.tipo_vigente
        )
        vigente_renovacao_assinado = self._processo(
            4,
            status="vigente",
            tipo=self.tipo_renovacao,
            data_assinatura_contrato=date(2026, 7, 1),
        )
        em_tramitacao = self._processo(
            5, status="em_tramitacao", data_recebimento_gelic=date(2026, 5, 1)
        )
        nao_iniciado_atrasado = self._processo(
            6, status="nao_iniciado", prazo_entrega=ontem
        )
        nao_iniciado_no_prazo_futuro = self._processo(
            7, status="nao_iniciado", prazo_entrega=amanha
        )
        nao_iniciado_sem_prazo = self._processo(
            8, status="nao_iniciado", prazo_entrega=None
        )

        self._aplicar_0023()

        NewProcesso = MigrationExecutor(connection).loader.project_state(
            [ALVO_0023]
        ).apps.get_model("pca", "Processo")

        def _recarregar(pk):
            return NewProcesso.objects.using("default").get(pk=pk)

        self.assertEqual(_recarregar(cancelado.pk).estado, "cancelado")

        for pk in (concluido.pk, vigente_tipo_vigente.pk, vigente_renovacao_assinado.pk):
            processo = _recarregar(pk)
            self.assertEqual(processo.estado, "ativo")
            self.assertEqual(processo.situacao, "concluido")

        processo_tramitacao = _recarregar(em_tramitacao.pk)
        self.assertEqual(processo_tramitacao.estado, "ativo")
        self.assertEqual(processo_tramitacao.situacao, "em_tramitacao")

        self.assertEqual(_recarregar(nao_iniciado_atrasado.pk).estado, "ativo")
        self.assertEqual(_recarregar(nao_iniciado_atrasado.pk).situacao, "atrasado")

        for pk in (nao_iniciado_no_prazo_futuro.pk, nao_iniciado_sem_prazo.pk):
            processo = _recarregar(pk)
            self.assertEqual(processo.estado, "ativo")
            self.assertEqual(processo.situacao, "no_prazo")


class TestIdempotenciaDoBackfill(MigracaoEstadoSituacaoTestCase):
    """Rodar a função de backfill uma segunda vez sobre o estado já
    migrado não muda nenhuma linha (comparação de snapshot, não via
    `migrate` duas vezes — o Django já impede reaplicar uma migração
    registrada como aplicada)."""

    def test_reaplicar_a_funcao_de_backfill_nao_muda_nenhuma_linha(self):
        hoje = timezone.localdate()
        self._processo(1, status="cancelado")
        self._processo(2, status="concluido", data_assinatura_contrato=date(2026, 6, 1))
        self._processo(3, status="vigente", tipo=self.tipo_vigente)
        self._processo(
            4, status="em_tramitacao", data_recebimento_gelic=date(2026, 5, 1)
        )
        self._processo(5, status="nao_iniciado", prazo_entrega=hoje - timedelta(days=3))
        self._processo(6, status="nao_iniciado", prazo_entrega=None)

        self._aplicar_0023()

        # Nome de módulo começa com dígito — `importlib` em vez de `import`
        # léxico (mesmo motivo de qualquer módulo de migração precisar ser
        # carregado dinamicamente).
        import importlib

        modulo_migracao = importlib.import_module(
            "apps.pca.migrations.0023_estado_situacao_tres_eixos"
        )
        preencher_estado_situacao = modulo_migracao.preencher_estado_situacao

        novo_state = MigrationExecutor(connection).loader.project_state([ALVO_0023])
        NewProcesso = novo_state.apps.get_model("pca", "Processo")
        antes = {
            processo.pk: (processo.estado, processo.situacao)
            for processo in NewProcesso.objects.using("default").order_by("pk")
        }

        # A função de backfill lê `processo.status` (congelada dentro da
        # migração 0023 — nunca editada retroativamente). Chamá-la contra
        # o app registry atual não tem mais `.status`, e a chamada
        # estoura `AttributeError`. A correção é chamar contra o mesmo
        # `apps` congelado em 0023, reaproveitando o mesmo `novo_state`
        # já usado para `NewProcesso` acima.
        preencher_estado_situacao(novo_state.apps, None)

        depois = {
            processo.pk: (processo.estado, processo.situacao)
            for processo in NewProcesso.objects.using("default").order_by("pk")
        }
        self.assertEqual(antes, depois)
