"""A entidade `Reuniao`, o backfill das reuniões importadas e o serviço
único de domínio do efeito duplo.

O serviço é a única porta de escrita de status e de prazo prometido:
nenhuma view pode instanciar `Acompanhamento` por conta própria.
"""

import importlib
from datetime import date
from decimal import Decimal
from io import StringIO

from django.apps import apps as django_apps
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.utils.timezone import localdate

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
    Estado,
    Processo,
    RascunhoItemVirada,
    RascunhoVirada,
    Reuniao,
    Situacao,
    SituacaoReuniao,
    TipoEvento,
)
from apps.pca.services import (
    ConflitoDeEdicao,
    _montar_copia,
    alterar_estado,
    aplicar_regras_automaticas,
    criar_processo,
    criar_reuniao,
    registrar_acompanhamento,
)

ARQUIVO_REAL = "apps/pca/fixtures/modelo-controle-exemplo.xlsx"

MIGRACAO_BACKFILL = importlib.import_module(
    "apps.pca.migrations.0003_reuniao_versao_otimista"
)


class TestBackfillReuniao(TransactionTestCase):
    """Sem o backfill, `n_reunioes` zera para os processos.

    `TransactionTestCase` + `serialized_rollback` pelo mesmo motivo de
    `TestImportComando`: `importar_pca` gerencia a própria transação, e o
    flush entre testes apagaria o usuário de serviço criado pela migração
    de dados `core.0003_usuario_importacao`.
    """

    serialized_rollback = True

    @classmethod
    def _catalogo_minimo(cls):
        unidade = Unidade.objects.create(nome="Presidência")
        categoria = Categoria.objects.create(nome="Serviços")
        tipo = Tipo.objects.create(nome="Aquisição")
        situacao = SituacaoNormalizada.objects.create(nome="Em tramitação")
        exercicio = Exercicio.objects.get(ano=2026)
        return unidade, categoria, tipo, situacao, exercicio

    def test_import_real_deixa_as_5_reunioes_e_nenhum_acompanhamento_avulso(self):
        """Contra a fixture de exemplo: 5 datas de referência distintas
        nas 75 linhas importadas (pool `_DATAS_REUNIAO` de
        `gerar_fixture_exemplo`) -> 5 `Reuniao`, todas fechadas, e nenhum
        acompanhamento importado sem reunião."""
        call_command("importar_pca", ARQUIVO_REAL, "--exercicio=2026", stdout=StringIO())

        self.assertEqual(Reuniao.objects.count(), 5)
        self.assertEqual(
            Acompanhamento.objects.filter(reuniao__isnull=True).count(), 0
        )
        self.assertEqual(
            set(Reuniao.objects.values_list("situacao", flat=True)),
            {SituacaoReuniao.FECHADA.value},
        )

    def test_reimport_nao_duplica_reuniao(self):
        """O import é idempotente; a reunião segue a mesma regra."""
        call_command("importar_pca", ARQUIVO_REAL, "--exercicio=2026", stdout=StringIO())
        call_command("importar_pca", ARQUIVO_REAL, "--exercicio=2026", stdout=StringIO())

        self.assertEqual(Reuniao.objects.count(), 5)
        self.assertEqual(Acompanhamento.objects.count(), 75)

    def test_funcao_de_backfill_agrupa_por_data_e_e_idempotente(self):
        """A `RunPython` de `0003_reuniao_versao_otimista` chamada diretamente:
        uma `Reuniao` por `referencia_data` distinta (dois acompanhamentos no
        mesmo dia continuam sendo UMA reunião), e rodar de novo não cria uma
        reunião a mais.

        `exercicio` (NOT NULL em `Reuniao`) só chegou na migração 0009, seis
        migrações depois da 0003. Para exercitar a `RunPython` contra o schema
        da PRÓPRIA época, o banco é rebaixado fisicamente via
        `MigrationExecutor.migrate([...])` até o estado imediatamente anterior
        à 0003, a fixture é construída com os modelos históricos daquele estado
        (sem `exercicio`), e a 0003 é reaplicada de verdade — a `RunPython` roda
        uma vez como parte da própria migração. A prova de idempotência chama a
        função de novo com o registro de apps daquele estado. O schema é
        restaurado ao HEAD via `addCleanup` antes do flush do framework (mesma
        técnica do plano 08-01)."""
        executor = MigrationExecutor(connection)
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(MigrationExecutor(connection).loader.graph.leaf_nodes()))
        executor.migrate([("catalogo", "0001_initial"), ("pca", "0002_unaccent")])
        old_apps = executor.loader.project_state(
            [("catalogo", "0001_initial"), ("pca", "0002_unaccent")]
        ).apps

        OldTipo = old_apps.get_model("catalogo", "Tipo")
        OldCategoria = old_apps.get_model("catalogo", "Categoria")
        OldUnidade = old_apps.get_model("catalogo", "Unidade")
        OldSituacao = old_apps.get_model("catalogo", "SituacaoNormalizada")
        OldProcesso = old_apps.get_model("pca", "Processo")
        OldAcompanhamento = old_apps.get_model("pca", "Acompanhamento")

        tipo = OldTipo.objects.create(nome="Aquisição", nome_normalizado="aquisicao")
        categoria = OldCategoria.objects.create(nome="Serviços", nome_normalizado="servicos")
        unidade = OldUnidade.objects.create(nome="Presidência", nome_normalizado="presidencia")
        situacao = OldSituacao.objects.create(nome="Em tramitação")
        processo = OldProcesso.objects.create(
            item_pca=1,
            descricao_objeto="Objeto 1",
            tipo_id=tipo.pk,
            categoria_id=categoria.pk,
            unidade_organizacional_id=unidade.pk,
            status="em_tramitacao",
        )
        for i, dia in enumerate((10, 10, 20), start=1):
            OldAcompanhamento.objects.create(
                processo_id=processo.pk,
                referencia_data=date(2026, 1, dia),
                origem_hash=f"hash-backfill-{i}",
                tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
                situacao_id=situacao.pk,
            )
        # Estado de partida: linhas importadas antes da migração, sem reunião
        # (o campo `reuniao` ainda não existe no schema 0002 — chega na 0003).
        self.assertEqual(OldAcompanhamento.objects.count(), 3)

        # Aplicar a 0003 de verdade: a RunPython roda dentro da própria
        # migração, contra o schema da época (sem `exercicio`).
        MigrationExecutor(connection).migrate([("pca", "0003_reuniao_versao_otimista")])
        apps_pos_0003 = MigrationExecutor(connection).loader.project_state(
            [("pca", "0003_reuniao_versao_otimista")]
        ).apps
        ReuniaoHist = apps_pos_0003.get_model("pca", "Reuniao")
        AcompanhamentoHist = apps_pos_0003.get_model("pca", "Acompanhamento")

        self.assertEqual(ReuniaoHist.objects.count(), 2)
        self.assertEqual(
            AcompanhamentoHist.objects.filter(reuniao__isnull=True).count(), 0
        )
        self.assertEqual(
            AcompanhamentoHist.objects.filter(
                referencia_data=date(2026, 1, 10)
            ).values_list("reuniao_id", flat=True).distinct().count(),
            1,
        )

        # Idempotência: chamar a função de novo não cria uma reunião a mais.
        MIGRACAO_BACKFILL.backfill_reunioes(apps_pos_0003, None)
        self.assertEqual(ReuniaoHist.objects.count(), 2)


class TestVersaoOtimistaNoModelo(TestCase):
    """`atualizado_em` é o token de versão. `auto_now=True` só dispara em
    `save()`, nunca em `bulk_create`/`update()`, o que preserva a
    semântica de 'versão da última escrita via save()'."""

    @classmethod
    def setUpTestData(cls):
        cls.unidade = Unidade.objects.create(nome="Presidência")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.tipo = Tipo.objects.create(nome="Aquisição")
        cls.exercicio = Exercicio.objects.get(ano=2026)

    def test_atualizado_em_nasce_preenchido_e_avanca_no_save(self):
        processo = Processo.objects.create(
            item_pca=1,
            descricao_objeto="Objeto 1",
            tipo=self.tipo,
            categoria=self.categoria,
            unidade_organizacional=self.unidade,
            exercicio=self.exercicio,
        )
        self.assertIsNotNone(processo.atualizado_em)

        versao_anterior = processo.atualizado_em
        processo.situacao = Situacao.CONCLUIDO.value
        processo.save(update_fields=["situacao", "atualizado_em"])
        processo.refresh_from_db()
        self.assertGreater(processo.atualizado_em, versao_anterior)


class TestReuniaoNoAdmin(TestCase):
    def test_reuniao_registrada_no_admin(self):
        from django.contrib import admin

        self.assertIn(Reuniao, admin.site._registry)


class TestRegistrarAcompanhamento(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user(
            email="editor@example.com", password="senha-segura"
        )
        cls.unidade = Unidade.objects.create(nome="Presidência")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.tipo = Tipo.objects.create(nome="Aquisição")
        cls.exercicio = Exercicio.objects.get(ano=2026)
        cls.situacoes = {
            nome: SituacaoNormalizada.objects.create(nome=nome)
            for nome in (
                "Concluído", "Sem informação", "Em tramitação",
                "Contrato vigente", "Cancelado", "Compromisso de entrega",
            )
        }

    def _processo(self, item=1):
        return Processo.objects.create(
            item_pca=item,
            descricao_objeto=f"Objeto {item}",
            tipo=self.tipo,
            categoria=self.categoria,
            unidade_organizacional=self.unidade,
            exercicio=self.exercicio,
        )

    def test_efeito_duplo_grava_processo_timeline_e_historico_assinado(self):
        processo = self._processo()
        versao = processo.atualizado_em.isoformat()

        resultado = registrar_acompanhamento(
            processo_id=processo.pk,
            usuario=self.usuario,
            versao_cliente=versao,
            situacao_novo=Situacao.CONCLUIDO.value,
            observacao="Concluído na reunião",
        )

        self.assertEqual(resultado.situacao, Situacao.CONCLUIDO.value)
        acompanhamento = Acompanhamento.objects.get(processo=processo)
        self.assertEqual(acompanhamento.situacao.nome, "Concluído")
        self.assertEqual(acompanhamento.situacao_informada, "Concluído na reunião")
        self.assertIsNotNone(
            resultado.history.filter(history_user=self.usuario)
            .order_by("-history_date").first()
        )
        self.assertIsNotNone(
            acompanhamento.history.filter(history_user=self.usuario)
            .order_by("-history_date").first()
        )

    def test_versao_obsoleta_nao_grava_nada_e_expoe_processo_recarregado(self):
        processo = self._processo()
        versao = processo.atualizado_em.isoformat()
        registrar_acompanhamento(
            processo_id=processo.pk, usuario=self.usuario,
            versao_cliente=versao, situacao_novo=Situacao.CONCLUIDO.value,
        )
        quantidade = Acompanhamento.objects.count()

        with self.assertRaises(ConflitoDeEdicao) as contexto:
            registrar_acompanhamento(
                processo_id=processo.pk, usuario=self.usuario,
                versao_cliente=versao, situacao_novo=Situacao.EM_TRAMITACAO.value,
                observacao="tentativa com versão obsoleta",
            )

        self.assertEqual(contexto.exception.processo.pk, processo.pk)
        self.assertEqual(Acompanhamento.objects.count(), quantidade)
        self.assertEqual(Processo.objects.get(pk=processo.pk).situacao,
                         Situacao.CONCLUIDO.value)

    def test_prazo_sem_situacao_cria_timeline_sem_mudar_situacao(self):
        processo = self._processo()
        situacao_anterior = processo.situacao
        resultado = registrar_acompanhamento(
            processo_id=processo.pk, usuario=self.usuario,
            versao_cliente=processo.atualizado_em.isoformat(),
            prazo_prometido=date(2026, 9, 1),
        )
        acompanhamento = Acompanhamento.objects.get(processo=processo)
        self.assertEqual(resultado.situacao, situacao_anterior)
        self.assertEqual(acompanhamento.prazo_prometido, date(2026, 9, 1))

    def test_justificativa_e_observacao_ocupam_campos_distintos_sem_quebrar_transicao(self):
        """`justificativa` (nova promessa) grava só `evento`;
        `observacao` (transição existente) grava só `situacao_informada`.
        Cobre também a associação automática à reunião aberta, o
        fallback sem reunião e a invariância de `n_reunioes`
        (acompanhamento sem reunião não conta)."""
        processo = self._processo()

        resultado = registrar_acompanhamento(
            processo_id=processo.pk,
            usuario=self.usuario,
            versao_cliente=processo.atualizado_em.isoformat(),
            prazo_prometido=date(2026, 9, 1),
            justificativa="  Fornecedor pediu prazo maior  ",
        )
        promessa_avulsa = Acompanhamento.objects.get(processo=processo)
        self.assertEqual(promessa_avulsa.evento, "Fornecedor pediu prazo maior")
        self.assertEqual(promessa_avulsa.situacao_informada, "")
        self.assertIsNone(promessa_avulsa.reuniao_id)
        self.assertEqual(
            Processo.objects.para_listagem().get(pk=processo.pk).n_reunioes, 0
        )

        reuniao = Reuniao.objects.create(
            data=date(2026, 6, 30), situacao=SituacaoReuniao.ABERTA,
            exercicio=self.exercicio,
        )
        resultado = registrar_acompanhamento(
            processo_id=processo.pk,
            usuario=self.usuario,
            versao_cliente=resultado.atualizado_em.isoformat(),
            prazo_prometido=date(2026, 10, 1),
            justificativa="Segunda promessa",
        )
        promessa_com_reuniao = Acompanhamento.objects.exclude(
            pk=promessa_avulsa.pk
        ).get(processo=processo)
        self.assertEqual(promessa_com_reuniao.evento, "Segunda promessa")
        self.assertEqual(promessa_com_reuniao.reuniao_id, reuniao.pk)
        self.assertEqual(promessa_com_reuniao.referencia_data, reuniao.data)
        self.assertEqual(
            Processo.objects.para_listagem().get(pk=processo.pk).n_reunioes, 1
        )

        registrar_acompanhamento(
            processo_id=processo.pk,
            usuario=self.usuario,
            versao_cliente=resultado.atualizado_em.isoformat(),
            situacao_novo=Situacao.CONCLUIDO.value,
            observacao="Concluído na reunião",
        )
        transicao = Acompanhamento.objects.exclude(
            pk__in=[promessa_avulsa.pk, promessa_com_reuniao.pk]
        ).get(processo=processo)
        self.assertEqual(transicao.situacao_informada, "Concluído na reunião")
        self.assertEqual(transicao.evento, "")

    def test_regras_de_entrada_e_reuniao_corrente(self):
        # Cancelamento não passa por `registrar_acompanhamento` (é
        # `alterar_estado`, só via admin); a validação de entrada aqui é
        # só situacao_novo/prazo_prometido.
        processo = self._processo()
        with self.assertRaises(ValueError):
            registrar_acompanhamento(
                processo_id=processo.pk, usuario=self.usuario,
                versao_cliente=processo.atualizado_em.isoformat(),
            )
        with self.assertRaises(ValueError):
            registrar_acompanhamento(
                processo_id=processo.pk, usuario=self.usuario,
                versao_cliente=processo.atualizado_em.isoformat(),
                situacao_novo="valor-invalido",
            )
        reuniao = Reuniao.objects.create(
            data=date(2026, 6, 30), situacao=SituacaoReuniao.ABERTA,
            exercicio=self.exercicio,
        )
        registrar_acompanhamento(
            processo_id=processo.pk, usuario=self.usuario,
            versao_cliente=processo.atualizado_em.isoformat(),
            prazo_prometido=date(2026, 9, 1), reuniao=reuniao,
        )
        self.assertEqual(
            Acompanhamento.objects.get(processo=processo).referencia_data,
            date(2026, 6, 30),
        )


class TestPrazoIsoladoReavaliaSituacao(TestCase):
    """Registrar um prazo isolado (`registrar_acompanhamento(
    prazo_prometido=..., situacao_novo=None)`, o mesmo caminho de
    `acompanhamento_modal_view`) reavalia `Processo.situacao` com a mesma
    precedência da automação — sobreposição manual ativa preserva; sem
    ela, fatos gravados mandam; sem fato, NO_PRAZO/ATRASADO normaliza
    para NO_PRAZO."""

    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user(
            email="editor-prazo-isolado@example.com", password="senha-segura"
        )
        cls.unidade = Unidade.objects.create(nome="Presidência")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.tipo = Tipo.objects.create(nome="Aquisição")
        cls.exercicio = Exercicio.objects.get(ano=2026)
        for nome in (
            "Concluído", "Sem informação", "Em tramitação",
            "Contrato vigente", "Cancelado", "Compromisso de entrega",
        ):
            SituacaoNormalizada.objects.get_or_create(nome=nome)

    def _processo(self, item, *, situacao=Situacao.NO_PRAZO, **extra):
        return Processo.objects.create(
            item_pca=item,
            descricao_objeto=f"Objeto {item}",
            tipo=self.tipo,
            categoria=self.categoria,
            unidade_organizacional=self.unidade,
            situacao=situacao,
            exercicio=self.exercicio,
            **extra,
        )

    def test_sem_manual_atrasado_vira_no_prazo_ao_registrar_novo_prazo(self):
        processo = self._processo(30, situacao=Situacao.ATRASADO)

        resultado = registrar_acompanhamento(
            processo_id=processo.pk,
            usuario=self.usuario,
            versao_cliente=processo.atualizado_em.isoformat(),
            prazo_prometido=date(2026, 12, 1),
        )

        self.assertEqual(resultado.situacao, Situacao.NO_PRAZO.value)

    def test_sem_manual_sem_fato_no_prazo_permanece_no_prazo(self):
        processo = self._processo(31, situacao=Situacao.NO_PRAZO)

        resultado = registrar_acompanhamento(
            processo_id=processo.pk,
            usuario=self.usuario,
            versao_cliente=processo.atualizado_em.isoformat(),
            prazo_prometido=date(2026, 12, 1),
        )

        self.assertEqual(resultado.situacao, Situacao.NO_PRAZO.value)

    def test_sem_manual_assinatura_registrada_prevalece_sobre_normalizacao(self):
        # Sem sobreposição manual, a assinatura do contrato já gravada
        # tem prioridade sobre a normalização NO_PRAZO/ATRASADO ->
        # NO_PRAZO: o prazo isolado não pode rebaixar um processo que já
        # deveria estar CONCLUIDO.
        processo = self._processo(
            32, situacao=Situacao.ATRASADO,
            data_assinatura_contrato=date(2026, 6, 2),
        )

        resultado = registrar_acompanhamento(
            processo_id=processo.pk,
            usuario=self.usuario,
            versao_cliente=processo.atualizado_em.isoformat(),
            prazo_prometido=date(2026, 12, 1),
        )

        self.assertEqual(resultado.situacao, Situacao.CONCLUIDO.value)

    def test_sem_manual_recebimento_gelic_prevalece_sobre_normalizacao(self):
        processo = self._processo(
            33, situacao=Situacao.ATRASADO,
            data_recebimento_gelic=date(2026, 5, 20),
        )

        resultado = registrar_acompanhamento(
            processo_id=processo.pk,
            usuario=self.usuario,
            versao_cliente=processo.atualizado_em.isoformat(),
            prazo_prometido=date(2026, 12, 1),
        )

        self.assertEqual(resultado.situacao, Situacao.EM_TRAMITACAO.value)

    def test_manual_atrasado_sobrevive_a_promessa_futura(self):
        # Behavior do plano: "Manual Atrasado → promessa futura →
        # reavaliação automática → leitura permanece Atrasado."
        processo = self._processo(34, situacao=Situacao.NO_PRAZO)
        registrar_acompanhamento(
            processo_id=processo.pk,
            usuario=self.usuario,
            versao_cliente=processo.atualizado_em.isoformat(),
            situacao_novo=Situacao.ATRASADO.value,
            observacao="Sobreposição manual em reunião",
        )
        processo.refresh_from_db()
        manual = Acompanhamento.objects.get(processo=processo)
        self.assertTrue(manual.transicao_manual)

        resultado = registrar_acompanhamento(
            processo_id=processo.pk,
            usuario=self.usuario,
            versao_cliente=processo.atualizado_em.isoformat(),
            prazo_prometido=date(2026, 12, 1),
        )
        promessa = Acompanhamento.objects.exclude(pk=manual.pk).get(processo=processo)
        self.assertFalse(promessa.transicao_manual)
        self.assertEqual(resultado.situacao, Situacao.ATRASADO.value)

        reavaliado = aplicar_regras_automaticas(processo=resultado, usuario=self.usuario)
        self.assertIsNone(reavaliado)
        self.assertEqual(
            Processo.objects.get(pk=processo.pk).situacao, Situacao.ATRASADO.value
        )

    def test_manual_no_prazo_sobrevive_a_promessa_passada(self):
        # Behavior do plano: "Manual No prazo → promessa passada → leitura
        # permanece No prazo, mas dias_atraso continua refletindo a data
        # vencida" (a parte de dias_atraso é coberta em test_querysets.py).
        processo = self._processo(35, situacao=Situacao.ATRASADO)
        registrar_acompanhamento(
            processo_id=processo.pk,
            usuario=self.usuario,
            versao_cliente=processo.atualizado_em.isoformat(),
            situacao_novo=Situacao.NO_PRAZO.value,
            observacao="Sobreposição manual em reunião",
        )
        processo.refresh_from_db()

        resultado = registrar_acompanhamento(
            processo_id=processo.pk,
            usuario=self.usuario,
            versao_cliente=processo.atualizado_em.isoformat(),
            prazo_prometido=date(2020, 1, 1),
        )

        self.assertEqual(resultado.situacao, Situacao.NO_PRAZO.value)

    def test_guarda_automatica_detecta_manual_mesmo_quando_nao_e_o_ultimo(self):
        # A guarda não olha só o último Acompanhamento: uma promessa
        # isolada gravada depois de uma transição manual não pode
        # destravar `aplicar_regras_automaticas`.
        processo = self._processo(
            36, situacao=Situacao.EM_TRAMITACAO,
            data_recebimento_gelic=date(2026, 3, 15),
        )
        registrar_acompanhamento(
            processo_id=processo.pk,
            usuario=self.usuario,
            versao_cliente=processo.atualizado_em.isoformat(),
            situacao_novo=Situacao.NO_PRAZO.value,
            observacao="Sobreposição manual em reunião",
        )
        processo.refresh_from_db()
        registrar_acompanhamento(
            processo_id=processo.pk,
            usuario=self.usuario,
            versao_cliente=processo.atualizado_em.isoformat(),
            prazo_prometido=date(2026, 12, 1),
        )
        processo.refresh_from_db()
        self.assertEqual(processo.situacao, Situacao.NO_PRAZO.value)

        resultado = aplicar_regras_automaticas(processo=processo, usuario=self.usuario)

        self.assertIsNone(resultado)
        self.assertEqual(
            Processo.objects.get(pk=processo.pk).situacao, Situacao.NO_PRAZO.value
        )

    def test_legado_sem_transicao_manual_continua_seguindo_a_automacao(self):
        # "Legado sem transicao_manual=True segue a automação; valores já
        # sobrescritos não são reconstruídos." — um Acompanhamento importado
        # (transicao_manual=False pelo default, mesmo sendo
        # REUNIAO_ACOMPANHAMENTO) não trava a normalização do prazo isolado.
        processo = self._processo(37, situacao=Situacao.ATRASADO)
        Acompanhamento.objects.create(
            processo=processo,
            referencia_data=date(2026, 2, 10),
            origem_hash="hash-legado-item37",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
            situacao=SituacaoNormalizada.objects.get(nome="Sem informação"),
            situacao_informada="Importado do Excel",
        )

        resultado = registrar_acompanhamento(
            processo_id=processo.pk,
            usuario=self.usuario,
            versao_cliente=processo.atualizado_em.isoformat(),
            prazo_prometido=date(2026, 12, 1),
        )

        self.assertEqual(resultado.situacao, Situacao.NO_PRAZO.value)


class TestRegrasAutomaticasTresEixos(TestCase):
    """`aplicar_regras_automaticas` para o modelo de 3 eixos, delegando
    inteiramente a `situacao_por_eventos` (regras_situacao.py), nunca
    escrevendo `atrasado` e tratando `concluido` como piso/terminal."""

    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user(
            email="editor-automacao@example.com", password="senha-segura"
        )
        cls.unidade = Unidade.objects.create(nome="Presidência")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.tipo_nova = Tipo.objects.create(nome="Nova Contratação")
        cls.tipo_renovacao = Tipo.objects.create(nome="Renovação")
        cls.tipo_vigente = Tipo.objects.create(nome="Vigente")
        cls.exercicio = Exercicio.objects.get(ano=2026)
        for nome in ("Concluído", "Sem informação", "Em tramitação", "Cancelado"):
            SituacaoNormalizada.objects.get_or_create(nome=nome)

    def _processo(
        self, item, *, tipo=None, estado=Estado.ATIVO,
        situacao=Situacao.NO_PRAZO, **extra,
    ):
        return Processo.objects.create(
            item_pca=item,
            descricao_objeto=f"Objeto {item}",
            tipo=tipo or self.tipo_nova,
            categoria=self.categoria,
            unidade_organizacional=self.unidade,
            estado=estado,
            situacao=situacao,
            exercicio=self.exercicio,
            **extra,
        )

    def test_d41_d42_evento_recebimento_gelic_grava_em_tramitacao(self):
        # Via evento: `data_recebimento_gelic` preenchida, sem
        # `data_assinatura_contrato`, grava `em_tramitacao` com um
        # Acompanhamento automático.
        processo = self._processo(
            1, tipo=self.tipo_nova, situacao=Situacao.NO_PRAZO,
            data_recebimento_gelic=date(2026, 3, 15),
        )

        resultado = aplicar_regras_automaticas(processo=processo, usuario=self.usuario)

        self.assertIsNotNone(resultado)
        self.assertEqual(resultado.situacao, Situacao.EM_TRAMITACAO.value)
        acompanhamento = Acompanhamento.objects.get(processo=processo)
        self.assertEqual(acompanhamento.tipo_evento, TipoEvento.AUTOMATICO.value)
        self.assertIn("Em tramitação", acompanhamento.situacao_informada)
        self.assertIn("15/03/2026", acompanhamento.situacao_informada)

    def test_d44_concluido_e_piso_nunca_e_rebaixado(self):
        # Um processo já `concluido` (terminal) recebendo
        # `data_recebimento_gelic` de novo (edição posterior) não muda
        # `situacao` nem cria Acompanhamento — a automação nunca rebaixa
        # um terminal.
        processo = self._processo(
            2, tipo=self.tipo_nova, situacao=Situacao.CONCLUIDO,
        )
        processo.data_recebimento_gelic = date(2026, 4, 1)
        processo.save(update_fields=["data_recebimento_gelic"])

        resultado = aplicar_regras_automaticas(processo=processo, usuario=self.usuario)

        self.assertIsNone(resultado)
        self.assertEqual(Acompanhamento.objects.filter(processo=processo).count(), 0)
        self.assertEqual(
            Processo.objects.get(pk=processo.pk).situacao, Situacao.CONCLUIDO.value
        )

    def test_d44_sobreposicao_manual_nao_terminal_sobrevive_a_regra_automatica(self):
        # Uma situação não-terminal gravada manualmente sobrevive a uma
        # edição posterior de outro campo que dispararia a mesma regra
        # automática — a automação nunca desfaz a última escolha humana
        # registrada.
        processo = self._processo(
            10, tipo=self.tipo_nova, situacao=Situacao.EM_TRAMITACAO,
            data_recebimento_gelic=date(2026, 3, 15),
        )
        registrar_acompanhamento(
            processo_id=processo.pk,
            usuario=self.usuario,
            versao_cliente=processo.atualizado_em.isoformat(),
            situacao_novo=Situacao.NO_PRAZO.value,
            observacao="Sobreposição manual em reunião",
        )
        processo.refresh_from_db()

        resultado = aplicar_regras_automaticas(processo=processo, usuario=self.usuario)

        self.assertIsNone(resultado)
        self.assertEqual(
            Processo.objects.get(pk=processo.pk).situacao, Situacao.NO_PRAZO.value
        )
        self.assertEqual(Acompanhamento.objects.filter(processo=processo).count(), 1)

    def test_d41_promocao_automatica_sobrevive_a_historico_de_reuniao_importado(self):
        # GAP 1 (17-16, fecha 17-VERIFICATION.md) — cenário (a): um processo
        # com histórico de reunião REAL (Acompanhamento gravado direto pelo
        # importador, fora de `registrar_acompanhamento`, `transicao_manual`
        # nasce `False` pelo default do model) é promovido a CONCLUÍDO
        # quando `data_assinatura_contrato` é preenchida pela primeira vez.
        # Antes do 17-16, a guarda ampla do 17-14 bloqueava isto para TODO
        # processo real (149/149 — nenhum acompanhamento importado é
        # `tipo_evento=automatico`).
        processo = self._processo(
            20, tipo=self.tipo_nova, situacao=Situacao.NO_PRAZO,
        )
        Acompanhamento.objects.create(
            processo=processo,
            referencia_data=date(2026, 2, 10),
            origem_hash="hash-import-d41-item20",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
            situacao=SituacaoNormalizada.objects.get(nome="Sem informação"),
            situacao_informada="Aguardando assinatura",
        )
        processo.data_assinatura_contrato = date(2026, 6, 2)
        processo.save(update_fields=["data_assinatura_contrato"])

        resultado = aplicar_regras_automaticas(processo=processo, usuario=self.usuario)

        self.assertIsNotNone(resultado)
        self.assertEqual(resultado.situacao, Situacao.CONCLUIDO.value)
        automatico = Acompanhamento.objects.filter(
            processo=processo, tipo_evento=TipoEvento.AUTOMATICO.value
        ).first()
        self.assertIsNotNone(automatico)
        self.assertFalse(automatico.transicao_manual)

    def test_d42_promocao_automatica_sobrevive_a_promessa_de_prazo_registrada(self):
        # GAP 1 (17-16) — cenário (b): um processo com uma promessa de prazo
        # já registrada via `registrar_acompanhamento(prazo_prometido=...,
        # situacao_novo=None)` (mesmo padrão de `registrar_promessa_view`,
        # que nunca grava `transicao_manual=True` porque não passa
        # `situacao_novo`) é promovido a EM_TRAMITACAO quando
        # `data_recebimento_gelic` é preenchida.
        processo = self._processo(
            21, tipo=self.tipo_renovacao, situacao=Situacao.NO_PRAZO,
        )
        registrar_acompanhamento(
            processo_id=processo.pk,
            usuario=self.usuario,
            versao_cliente=processo.atualizado_em.isoformat(),
            prazo_prometido=date(2026, 7, 1),
            justificativa="Prazo reprometido em reunião",
        )
        processo.refresh_from_db()
        ultima_promessa = Acompanhamento.objects.get(processo=processo)
        self.assertFalse(ultima_promessa.transicao_manual)

        processo.data_recebimento_gelic = date(2026, 5, 20)
        processo.save(update_fields=["data_recebimento_gelic"])

        resultado = aplicar_regras_automaticas(processo=processo, usuario=self.usuario)

        self.assertIsNotNone(resultado)
        self.assertEqual(resultado.situacao, Situacao.EM_TRAMITACAO.value)
        self.assertEqual(Acompanhamento.objects.filter(processo=processo).count(), 2)

    def test_wr01_guarda_ordena_por_criacao_nao_por_referencia_data(self):
        # WR-01 (17-REVIEW.md) — um Acompanhamento AUTOMÁTICO "antigo" na
        # ordem de criação (id menor) mas com `referencia_data` mais recente
        # (hoje) não pode mascarar uma sobreposição MANUAL real criada
        # depois (id maior) associada a uma reunião ABERTA com data passada.
        # A guarda tem de olhar para quem foi gravado por último (`-id`),
        # não para qual reunião é "mais recente" no calendário.
        processo = self._processo(
            22, tipo=self.tipo_nova, situacao=Situacao.EM_TRAMITACAO,
            data_recebimento_gelic=date(2026, 3, 1),
        )
        Acompanhamento.objects.create(
            processo=processo,
            referencia_data=localdate(),
            origem_hash="hash-wr01-automatico-recente",
            tipo_evento=TipoEvento.AUTOMATICO.value,
            situacao=SituacaoNormalizada.objects.get(nome="Em tramitação"),
            situacao_informada="Situação atualizada automaticamente (fato antigo).",
        )
        reuniao_passada = criar_reuniao(
            data=date(2026, 2, 1), usuario=self.usuario, exercicio=self.exercicio,
        )

        registrar_acompanhamento(
            processo_id=processo.pk,
            usuario=self.usuario,
            versao_cliente=processo.atualizado_em.isoformat(),
            situacao_novo=Situacao.NO_PRAZO.value,
            observacao="Sobreposição manual registrada na reunião de fevereiro",
            reuniao=reuniao_passada,
            usar_reuniao_corrente=False,
        )
        processo.refresh_from_db()
        manual = Acompanhamento.objects.order_by("-id").first()
        self.assertTrue(manual.transicao_manual)
        self.assertEqual(manual.referencia_data, date(2026, 2, 1))
        self.assertEqual(processo.situacao, Situacao.NO_PRAZO.value)

        resultado = aplicar_regras_automaticas(processo=processo, usuario=self.usuario)

        self.assertIsNone(resultado)
        self.assertEqual(
            Processo.objects.get(pk=processo.pk).situacao, Situacao.NO_PRAZO.value
        )
        self.assertEqual(Acompanhamento.objects.filter(processo=processo).count(), 2)

    def test_d46_troca_de_tipo_reavalia_situacao_na_hora(self):
        # Reclassificar um processo em tramitação para Vigente recalcula
        # a situação imediatamente para CONCLUIDO, com Acompanhamento
        # automático.
        processo = self._processo(
            3, tipo=self.tipo_renovacao, situacao=Situacao.EM_TRAMITACAO,
        )
        processo.tipo = self.tipo_vigente
        processo.save(update_fields=["tipo"])

        resultado = aplicar_regras_automaticas(processo=processo, usuario=self.usuario)

        self.assertIsNotNone(resultado)
        self.assertEqual(resultado.situacao, Situacao.CONCLUIDO.value)
        acompanhamento = Acompanhamento.objects.get(processo=processo)
        self.assertEqual(acompanhamento.tipo_evento, TipoEvento.AUTOMATICO.value)
        self.assertIn("Vigente é concluído por natureza", acompanhamento.situacao_informada)

    def test_d45_nunca_escreve_atrasado_mesmo_com_prazo_vencido(self):
        # Prazo vencido sem nenhum campo de evento preenchido não
        # dispara escrita — `situacao` permanece `no_prazo` no banco; a
        # correção para "atrasado" é só de leitura.
        processo = self._processo(
            4, tipo=self.tipo_nova, situacao=Situacao.NO_PRAZO,
            prazo_entrega=date(2026, 1, 1),
        )

        resultado = aplicar_regras_automaticas(processo=processo, usuario=self.usuario)

        self.assertIsNone(resultado)
        self.assertEqual(
            Processo.objects.get(pk=processo.pk).situacao, Situacao.NO_PRAZO.value
        )
        self.assertEqual(Acompanhamento.objects.filter(processo=processo).count(), 0)

    def test_d39_registrar_acompanhamento_nunca_altera_estado(self):
        # `registrar_acompanhamento(situacao_novo=...)` não tem parâmetro
        # `estado_novo` — `estado` nunca é tocado por esta função.
        processo = self._processo(5, tipo=self.tipo_nova, estado=Estado.ATIVO)

        registrar_acompanhamento(
            processo_id=processo.pk,
            usuario=self.usuario,
            versao_cliente=processo.atualizado_em.isoformat(),
            situacao_novo=Situacao.CONCLUIDO.value,
        )

        self.assertEqual(
            Processo.objects.get(pk=processo.pk).estado, Estado.ATIVO.value
        )

    def test_regressao_nunca_toca_processo_cancelado(self):
        # Regressão: `aplicar_regras_automaticas` sobre um processo
        # `estado=cancelado` retorna None e não grava nada, mesmo com
        # `data_assinatura_contrato` preenchida.
        processo = self._processo(
            6, tipo=self.tipo_renovacao, estado=Estado.CANCELADO,
            situacao=Situacao.NO_PRAZO,
            data_assinatura_contrato=date(2026, 6, 2),
        )

        resultado = aplicar_regras_automaticas(processo=processo, usuario=self.usuario)

        self.assertIsNone(resultado)
        self.assertEqual(Acompanhamento.objects.filter(processo=processo).count(), 0)
        self.assertEqual(
            Processo.objects.get(pk=processo.pk).estado, Estado.CANCELADO.value
        )

    def test_autor_do_acompanhamento_automatico_e_o_usuario_que_editou(self):
        outro_usuario = get_user_model().objects.create_user(
            email="quem-editou@example.com", password="senha-segura"
        )
        processo = self._processo(7, data_recebimento_gelic=date(2026, 3, 15))

        aplicar_regras_automaticas(processo=processo, usuario=outro_usuario)

        acompanhamento = Acompanhamento.objects.get(processo=processo)
        self.assertIsNotNone(
            acompanhamento.history.filter(history_user=outro_usuario)
            .order_by("-history_date").first()
        )

    def test_usar_reuniao_corrente_false_nunca_associa_reuniao_aberta(self):
        Reuniao.objects.create(
            data=date(2026, 6, 30), situacao=SituacaoReuniao.ABERTA,
            exercicio=self.exercicio,
        )
        processo = self._processo(8, situacao=Situacao.NO_PRAZO)

        resultado = registrar_acompanhamento(
            processo_id=processo.pk,
            usuario=self.usuario,
            versao_cliente=processo.atualizado_em.isoformat(),
            situacao_novo=Situacao.EM_TRAMITACAO.value,
            tipo_evento=TipoEvento.AUTOMATICO,
            usar_reuniao_corrente=False,
        )

        acompanhamento = Acompanhamento.objects.get(processo=resultado)
        self.assertIsNone(acompanhamento.reuniao_id)
        self.assertEqual(acompanhamento.tipo_evento, TipoEvento.AUTOMATICO.value)

    def test_chamada_sem_novos_kwargs_associa_reuniao_corrente(self):
        reuniao = Reuniao.objects.create(
            data=date(2026, 6, 30), situacao=SituacaoReuniao.ABERTA,
            exercicio=self.exercicio,
        )
        processo = self._processo(9, situacao=Situacao.NO_PRAZO)

        resultado = registrar_acompanhamento(
            processo_id=processo.pk,
            usuario=self.usuario,
            versao_cliente=processo.atualizado_em.isoformat(),
            situacao_novo=Situacao.EM_TRAMITACAO.value,
        )

        acompanhamento = Acompanhamento.objects.get(processo=resultado)
        self.assertEqual(
            acompanhamento.tipo_evento, TipoEvento.REUNIAO_ACOMPANHAMENTO.value
        )
        self.assertEqual(acompanhamento.reuniao_id, reuniao.pk)


class TestAlterarEstadoECriacao(TestCase):
    """`alterar_estado` (única via de mudança de Estado) e
    `criar_processo`/`_montar_copia` migrados para os 3 eixos."""

    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user(
            email="editor-estado@example.com", password="senha-segura"
        )
        cls.unidade = Unidade.objects.create(nome="Presidência")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.tipo = Tipo.objects.create(nome="Aquisição")
        cls.tipo_vigente = Tipo.objects.create(nome="Vigente")
        cls.exercicio = Exercicio.objects.get(ano=2026)
        for nome in ("Concluído", "Sem informação", "Em tramitação", "Cancelado"):
            SituacaoNormalizada.objects.get_or_create(nome=nome)

    def _processo(self, item, *, tipo=None, **extra):
        return Processo.objects.create(
            item_pca=item,
            descricao_objeto=f"Objeto {item}",
            tipo=tipo or self.tipo,
            categoria=self.categoria,
            unidade_organizacional=self.unidade,
            exercicio=self.exercicio,
            **extra,
        )

    def test_alterar_estado_grava_acompanhamento_e_e_idempotente(self):
        processo = self._processo(1, estado=Estado.ATIVO)

        resultado = alterar_estado(
            processo_id=processo.pk, estado_novo=Estado.CANCELADO,
            usuario=self.usuario, observacao="Contrato rescindido",
        )

        self.assertEqual(resultado.estado, Estado.CANCELADO.value)
        acompanhamento = Acompanhamento.objects.get(processo=processo)
        self.assertEqual(acompanhamento.situacao_informada, "Contrato rescindido")
        self.assertEqual(acompanhamento.tipo_evento, TipoEvento.AUTOMATICO.value)

        # Idempotência: reaplicar o MESMO estado_novo não cria um segundo
        # Acompanhamento.
        alterar_estado(
            processo_id=processo.pk, estado_novo=Estado.CANCELADO,
            usuario=self.usuario, observacao="Segunda tentativa",
        )
        self.assertEqual(Acompanhamento.objects.filter(processo=processo).count(), 1)

    def test_alterar_estado_nunca_toca_situacao(self):
        processo = self._processo(
            2, estado=Estado.ATIVO, situacao=Situacao.EM_TRAMITACAO,
        )

        alterar_estado(
            processo_id=processo.pk, estado_novo=Estado.CANCELADO,
            usuario=self.usuario, observacao="Contrato rescindido",
        )

        self.assertEqual(
            Processo.objects.get(pk=processo.pk).situacao,
            Situacao.EM_TRAMITACAO.value,
        )

    def test_criar_processo_produz_ativo_no_prazo_por_padrao(self):
        processo = criar_processo(
            usuario=self.usuario,
            descricao_objeto="Novo item",
            tipo_id=self.tipo.pk,
            categoria_id=self.categoria.pk,
            unidade_organizacional_id=self.unidade.pk,
            exercicio=self.exercicio,
        )

        self.assertEqual(processo.estado, Estado.ATIVO.value)
        self.assertEqual(processo.situacao, Situacao.NO_PRAZO.value)

    def test_criar_processo_com_tipo_vigente_produz_concluido(self):
        # Tipo=Vigente é concluído por natureza mesmo na criação — não
        # herda o fallback NO_PRAZO dos demais tipos.
        processo = criar_processo(
            usuario=self.usuario,
            descricao_objeto="Contrato já vigente",
            tipo_id=self.tipo_vigente.pk,
            categoria_id=self.categoria.pk,
            unidade_organizacional_id=self.unidade.pk,
            exercicio=self.exercicio,
        )

        self.assertEqual(processo.estado, Estado.ATIVO.value)
        self.assertEqual(processo.situacao, Situacao.CONCLUIDO.value)

    def test_montar_copia_preserva_vigente_concluido_e_copia_execucao(self):
        # A virada não pode regredir: um processo concluído (Vigente) na
        # origem chega concluído no destino, com os campos de execução
        # contratual copiados.
        origem = self._processo(
            3, tipo=self.tipo_vigente, estado=Estado.ATIVO,
            situacao=Situacao.CONCLUIDO,
            valor_estimado=Decimal("100.00"),
            data_assinatura_contrato=date(2026, 5, 10),
            vigencia_fim=date(2027, 5, 9),
        )
        destino = Exercicio.objects.create(
            ano=2099, rotulo="PCA 2099", situacao=SituacaoExercicio.ABERTO,
        )
        rascunho = RascunhoVirada.objects.create(
            exercicio_origem=self.exercicio, ano_destino=2099,
            criado_por=self.usuario,
        )
        linha = RascunhoItemVirada.objects.create(
            rascunho=rascunho, processo_origem=origem, ordem=1,
            selecionado=True,
            valor_estimado_editado=origem.valor_estimado,
            mes_previsto_editado=origem.mes_previsto,
        )

        copia = _montar_copia(linha, destino, 1)

        self.assertEqual(copia.estado, Estado.ATIVO.value)
        self.assertEqual(copia.situacao, Situacao.CONCLUIDO.value)
        self.assertEqual(copia.data_assinatura_contrato, date(2026, 5, 10))
        self.assertEqual(copia.vigencia_fim, date(2027, 5, 9))

    def test_montar_copia_reseta_situacao_nao_concluida_para_no_prazo(self):
        origem = self._processo(
            4, tipo=self.tipo, estado=Estado.ATIVO,
            situacao=Situacao.EM_TRAMITACAO,
        )
        destino = Exercicio.objects.create(
            ano=2098, rotulo="PCA 2098", situacao=SituacaoExercicio.ABERTO,
        )
        rascunho = RascunhoVirada.objects.create(
            exercicio_origem=self.exercicio, ano_destino=2098,
            criado_por=self.usuario,
        )
        linha = RascunhoItemVirada.objects.create(
            rascunho=rascunho, processo_origem=origem, ordem=1,
            selecionado=True,
            valor_estimado_editado=origem.valor_estimado,
            mes_previsto_editado=origem.mes_previsto,
        )

        copia = _montar_copia(linha, destino, 1)

        self.assertEqual(copia.estado, Estado.ATIVO.value)
        self.assertEqual(copia.situacao, Situacao.NO_PRAZO.value)
        self.assertIsNone(copia.data_assinatura_contrato)
