"""Migração física 0014→0015.

Prova, contra o schema histórico reconstruído (não os models atuais): a
transferência de `Processo.justificativa_alteracao_prazo` para o `evento`
da promessa mais recente, a preservação/concatenação sem duplicar de um
evento já existente, o no-op de texto vazio, o abort fail-closed quando
falta promessa de destino (com rollback provado), e a ausência final dos
quatro campos obsoletos (`justificativa_alteracao_email`/
`justificativa_alteracao_prazo` em `Processo`/`HistoricalProcesso`).

Padrão consolidado por `test_multiexercicio_migrations.py`:
`TransactionTestCase(serialized_rollback=True)`, restauração ao(s)
nó(s)-folha via `addCleanup` chamando
`MigrationExecutor(connection).migrate(...)` diretamente — nunca
`tearDownClass` (roda depois do flush) nem `call_command('migrate')`
(reemite o sinal `post_migrate`) nem `reset_sequences=True` (colide com
serialized_rollback ao reconstituir uma linha com id fixo)."""

from datetime import date

from django.core.exceptions import FieldDoesNotExist
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase

from apps.pca.models import HistoricalProcesso, Processo

ALVO_0014 = ("pca", "0014_prazo_entrega")
ALVO_0015 = ("pca", "0015_migrar_justificativa_e_remover_campos_obsoletos")


class MigracaoPrazoTestCase(TransactionTestCase):
    """Migra fisicamente `pca` para trás até 0014 (os dois campos obsoletos
    ainda existem), expõe os models do estado antigo via `apps.get_model` e
    sempre restaura ao(s) nó(s)-folha do grafo completo ao final — mesmo se
    o teste levantar exceção (cenário fail-closed)."""

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
        MigrationExecutor(connection).migrate([ALVO_0014])
        old_state = MigrationExecutor(connection).loader.project_state([ALVO_0014])
        self.old_apps = old_state.apps
        self.OldProcesso = self.old_apps.get_model("pca", "Processo")
        self.OldAcompanhamento = self.old_apps.get_model("pca", "Acompanhamento")
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

        self.tipo = OldTipo.objects.create(nome="Serviço", nome_normalizado="servico")
        self.categoria = OldCategoria.objects.create(
            nome="Serviços", nome_normalizado="servicos"
        )
        self.unidade = OldUnidade.objects.create(
            nome="Presidência", nome_normalizado="presidencia"
        )
        self.situacao = OldSituacaoNormalizada.objects.create(
            nome="Em andamento", nome_normalizado="em_andamento"
        )
        # `0008_backfill_exercicio_2026` já cria o exercício 2026 como parte
        # da migração normal até 0014 — `get_or_create` evita colidir com a
        # unicidade de `ano`.
        self.exercicio, _ = OldExercicio.objects.get_or_create(
            ano=2026, defaults={"rotulo": "PCA 2026"}
        )

    def _processo(self, item_pca, *, texto=""):
        return self.OldProcesso.objects.create(
            item_pca=item_pca,
            exercicio_id=self.exercicio.pk,
            descricao_objeto=f"Objeto {item_pca}",
            tipo_id=self.tipo.pk,
            categoria_id=self.categoria.pk,
            unidade_organizacional_id=self.unidade.pk,
            status="em_tramitacao",
            justificativa_alteracao_prazo=texto,
        )

    def _promessa(self, processo, *, referencia_data, prazo_prometido, evento="", sufixo=""):
        return self.OldAcompanhamento.objects.create(
            processo_id=processo.pk,
            referencia_data=referencia_data,
            origem_hash=f"hash-{processo.pk}-{referencia_data}{sufixo}",
            evento=evento,
            tipo_evento="reuniao_acompanhamento",
            situacao_id=self.situacao.pk,
            prazo_prometido=prazo_prometido,
        )

    def _aplicar_0015(self):
        MigrationExecutor(connection).migrate([ALVO_0015])


class TestTransfereTextoParaUltimaPromessa(MigracaoPrazoTestCase):
    def test_transfere_texto_para_ultima_promessa_e_cria_snapshot(self):
        processo = self._processo(1, texto="Fornecedor pediu prorrogação.")
        antiga = self._promessa(
            processo,
            referencia_data=date(2026, 3, 1),
            prazo_prometido=date(2026, 4, 1),
            sufixo="-antiga",
        )
        recente = self._promessa(
            processo,
            referencia_data=date(2026, 6, 1),
            prazo_prometido=date(2026, 7, 1),
            sufixo="-recente",
        )

        self._aplicar_0015()

        recente.refresh_from_db()
        antiga.refresh_from_db()
        self.assertEqual(recente.evento, "Fornecedor pediu prorrogação.")
        self.assertEqual(antiga.evento, "")

        snapshot = self.OldHistoricalAcompanhamento.objects.filter(id=recente.pk)
        self.assertEqual(snapshot.count(), 1)
        historico = snapshot.first()
        self.assertEqual(historico.history_type, "~")
        self.assertEqual(
            historico.history_change_reason,
            "Migração da justificativa de prazo do Processo",
        )
        self.assertEqual(historico.evento, "Fornecedor pediu prorrogação.")
        self.assertIsNone(historico.history_user)
        self.assertEqual(
            self.OldHistoricalAcompanhamento.objects.filter(id=antiga.pk).count(), 0
        )

    def test_ordem_de_desempate_por_id_quando_referencia_data_empata(self):
        # Duas promessas na MESMA data: desempate por `-id` (a mais recente
        # criada), o mesmo critério de `para_listagem()`.
        processo = self._processo(2, texto="Reunião confirmou novo prazo.")
        primeira = self._promessa(
            processo,
            referencia_data=date(2026, 5, 10),
            prazo_prometido=date(2026, 6, 1),
            sufixo="-1",
        )
        segunda = self._promessa(
            processo,
            referencia_data=date(2026, 5, 10),
            prazo_prometido=date(2026, 6, 15),
            sufixo="-2",
        )
        self.assertGreater(segunda.pk, primeira.pk)

        self._aplicar_0015()

        segunda.refresh_from_db()
        primeira.refresh_from_db()
        self.assertEqual(segunda.evento, "Reunião confirmou novo prazo.")
        self.assertEqual(primeira.evento, "")


class TestPreservaEventoPreexistente(MigracaoPrazoTestCase):
    def test_preserva_evento_preexistente_sem_duplicar_texto(self):
        # Processo A: evento existente DIFERENTE do texto migrado — os dois
        # sobrevivem, separados por newline (nada é descartado).
        processo_a = self._processo(1, texto="Fornecedor pediu prorrogação.")
        promessa_a = self._promessa(
            processo_a,
            referencia_data=date(2026, 5, 1),
            prazo_prometido=date(2026, 6, 1),
            evento="Reunião anterior discutiu o cronograma.",
            sufixo="-a",
        )

        # Processo B: evento existente IDÊNTICO (ignorando espaços externos)
        # ao texto migrado — não duplica, e por não haver alteração real,
        # nenhum snapshot histórico é criado.
        processo_b = self._processo(2, texto="  Mesmo texto da reunião.  ")
        promessa_b = self._promessa(
            processo_b,
            referencia_data=date(2026, 5, 2),
            prazo_prometido=date(2026, 6, 2),
            evento="Mesmo texto da reunião.",
            sufixo="-b",
        )

        self._aplicar_0015()

        promessa_a.refresh_from_db()
        promessa_b.refresh_from_db()
        self.assertEqual(
            promessa_a.evento,
            "Reunião anterior discutiu o cronograma.\nFornecedor pediu prorrogação.",
        )
        self.assertEqual(promessa_b.evento, "Mesmo texto da reunião.")

        self.assertEqual(
            self.OldHistoricalAcompanhamento.objects.filter(id=promessa_a.pk).count(),
            1,
        )
        self.assertEqual(
            self.OldHistoricalAcompanhamento.objects.filter(id=promessa_b.pk).count(),
            0,
        )


class TestTextoVazioENoop(MigracaoPrazoTestCase):
    def test_texto_vazio_e_noop(self):
        # Default "" (nunca setado) e "   " (só espaço) são ambos vazios em
        # efeito — nenhum dos dois toca a promessa nem cria histórico.
        processo_default = self._processo(1)
        promessa_default = self._promessa(
            processo_default,
            referencia_data=date(2026, 4, 1),
            prazo_prometido=date(2026, 5, 1),
            sufixo="-default",
        )
        processo_espacos = self._processo(2, texto="   ")
        promessa_espacos = self._promessa(
            processo_espacos,
            referencia_data=date(2026, 4, 2),
            prazo_prometido=date(2026, 5, 2),
            sufixo="-espacos",
        )

        self._aplicar_0015()

        promessa_default.refresh_from_db()
        promessa_espacos.refresh_from_db()
        self.assertEqual(promessa_default.evento, "")
        self.assertEqual(promessa_espacos.evento, "")
        self.assertEqual(
            self.OldHistoricalAcompanhamento.objects.filter(
                id__in=[promessa_default.pk, promessa_espacos.pk]
            ).count(),
            0,
        )


class TestTextoSemPromessaAborta(MigracaoPrazoTestCase):
    def test_texto_sem_promessa_aborta_antes_da_remocao(self):
        # Nenhuma Acompanhamento para este processo: não há promessa de
        # destino. A migração inteira precisa abortar ANTES de qualquer
        # RemoveField — os dois campos e o texto continuam intactos.
        processo = self._processo(1, texto="Justificativa sem promessa associada.")

        # Fixup registrado DEPOIS de setUp: por ser LIFO, roda ANTES da
        # restauração ao nó-folha (senão a re-tentativa de 0015 dentro do
        # cleanup falharia de novo com o mesmo dado inconsistente).
        self.addCleanup(
            lambda: self.OldProcesso.objects.filter(pk=processo.pk).update(
                justificativa_alteracao_prazo=""
            )
        )

        with self.assertRaises(RuntimeError):
            self._aplicar_0015()

        processo_apos_falha = self.OldProcesso.objects.get(pk=processo.pk)
        self.assertEqual(
            processo_apos_falha.justificativa_alteracao_prazo,
            "Justificativa sem promessa associada.",
        )
        # Os campos obsoletos continuam existindo no estado antigo — a
        # transação da migração 0015 nunca chegou a confirmar.
        self.OldProcesso._meta.get_field("justificativa_alteracao_prazo")
        self.OldProcesso._meta.get_field("justificativa_alteracao_email")


class TestSchemaFinalRemoveOsQuatroCampos(TestCase):
    """Sem MigrationExecutor: a suíte já roda com o schema no nó-folha
    (0015 aplicada), então os models ATUAIS já refletem o estado final."""

    def test_processo_nao_tem_mais_os_campos_obsoletos(self):
        for nome in ("justificativa_alteracao_email", "justificativa_alteracao_prazo"):
            with self.subTest(nome=nome):
                with self.assertRaises(FieldDoesNotExist):
                    Processo._meta.get_field(nome)

    def test_historicalprocesso_nao_tem_mais_os_campos_obsoletos(self):
        for nome in ("justificativa_alteracao_email", "justificativa_alteracao_prazo"):
            with self.subTest(nome=nome):
                with self.assertRaises(FieldDoesNotExist):
                    HistoricalProcesso._meta.get_field(nome)
