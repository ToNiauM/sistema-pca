from datetime import date, timedelta

from django.test import TestCase, override_settings
from freezegun import freeze_time

from apps.catalogo.models import (
    Categoria,
    Exercicio,
    GrauPrioridade,
    SituacaoNormalizada,
    Tipo,
    Unidade,
)
from apps.pca.models import (
    Acompanhamento,
    Estado,
    Processo,
    Reuniao,
    Situacao,
    SituacaoReuniao,
    TipoEvento,
)


class TestQuerysetBase(TestCase):
    """`TestQuerysetBase` cobre `ProcessoQuerySet.para_listagem()`
    isoladamente do ORM, reaproveitada por toda view que consome
    `para_listagem()` (tabela, dashboard, kanban/detalhe, export)."""

    @classmethod
    def setUpTestData(cls):
        cls.unidade = Unidade.objects.create(nome="Presidência")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.tipo = Tipo.objects.create(nome="Aquisição")
        cls.situacao_a = SituacaoNormalizada.objects.create(nome="Em tramitação")
        cls.situacao_b = SituacaoNormalizada.objects.create(nome="Concluído")
        cls.exercicio = Exercicio.objects.get(ano=2026)

    def _criar_processo(self, item_pca, **kwargs):
        defaults = {
            "descricao_objeto": f"Objeto {item_pca}",
            "tipo": self.tipo,
            "categoria": self.categoria,
            "unidade_organizacional": self.unidade,
        }
        defaults.update(kwargs)
        return Processo.objects.create(
            item_pca=item_pca, exercicio=self.exercicio, **defaults
        )

    def test_n_reunioes_conta_os_acompanhamentos_do_processo(self):
        processo = self._criar_processo(1)
        for i, dia in enumerate((1, 10, 20), start=1):
            reuniao = Reuniao.objects.create(
                data=date(2026, 1, dia),
                situacao=SituacaoReuniao.FECHADA,
                exercicio=self.exercicio,
            )
            Acompanhamento.objects.create(
                processo=processo,
                referencia_data=date(2026, 1, dia),
                origem_hash=f"hash-n-reunioes-{i}",
                tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
                situacao=self.situacao_a,
                reuniao=reuniao,
            )

        resultado = Processo.objects.para_listagem().get(pk=processo.pk)
        self.assertEqual(resultado.n_reunioes, 3)

    def test_n_reunioes_conta_reunioes_distintas_nao_linhas(self):
        processo = self._criar_processo(7)
        reuniao = Reuniao.objects.create(
            data=date(2026, 1, 1),
            situacao=SituacaoReuniao.FECHADA,
            exercicio=self.exercicio,
        )
        for i in range(3):
            Acompanhamento.objects.create(
                processo=processo,
                referencia_data=reuniao.data,
                origem_hash=f"hash-mesma-reuniao-{i}",
                tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
                situacao=self.situacao_a,
                reuniao=reuniao,
            )

        resultado = Processo.objects.para_listagem().get(pk=processo.pk)
        self.assertEqual(resultado.n_reunioes, 1)

    def test_empate_de_data_desempata_por_maior_id_sem_duplicar_linha(self):
        processo = self._criar_processo(2)
        Acompanhamento.objects.create(
            processo=processo,
            referencia_data=date(2026, 3, 15),
            origem_hash="hash-empate-1",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
            situacao=self.situacao_a,
        )
        mais_recente = Acompanhamento.objects.create(
            processo=processo,
            referencia_data=date(2026, 3, 15),
            origem_hash="hash-empate-2",
            tipo_evento=TipoEvento.GESTAO_RISCOS.value,
            situacao=self.situacao_b,
        )
        self.assertGreater(mais_recente.pk, Acompanhamento.objects.exclude(
            pk=mais_recente.pk
        ).get(processo=processo).pk)

        qs = Processo.objects.para_listagem().filter(pk=processo.pk)
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.get().situacao_atual, self.situacao_b.nome)

    def test_atraso_respeita_localdate_as_23h_de_brasilia(self):
        """Pitfall 11 — América/São_Paulo é UTC-3 (sem horário de verão desde
        2019). freeze_time recebe UTC ingênuo; os horários abaixo equivalem
        a 2026-07-27 23:30 e 2026-07-28 00:30 em America/Sao_Paulo.

        Atrasado mede contra `prazo_efetivo` (`prazo_entrega`, sem
        promessa), nunca `data_prevista_conclusao` (fica só como previsão
        de conclusão da contratação, sem reger flag nenhuma)."""
        processo = self._criar_processo(
            3,
            prazo_entrega=date(2026, 7, 27),
        )

        with freeze_time("2026-07-28 02:30:00"):  # 23:30 em Brasília, ainda 27/07
            resultado = Processo.objects.para_listagem().get(pk=processo.pk)
            self.assertFalse(resultado.atrasado)

        with freeze_time("2026-07-28 03:30:00"):  # 00:30 em Brasília, já 28/07
            resultado = Processo.objects.para_listagem().get(pk=processo.pk)
            self.assertTrue(resultado.atrasado)

    def test_data_prevista_conclusao_nao_participa_do_atraso(self):
        """`data_prevista_conclusao` fica na aba Processo sem reger
        atraso nenhum: um processo vencido só por essa data, sem promessa
        nem prazo_entrega, não fica atrasado."""
        processo = self._criar_processo(
            9,
            data_prevista_conclusao=date(2020, 1, 1),
        )

        resultado = Processo.objects.para_listagem().get(pk=processo.pk)
        self.assertIsNone(resultado.prazo_efetivo)
        self.assertFalse(resultado.atrasado)
        self.assertEqual(resultado.dias_atraso, 0)

    def test_reprometido_exige_mais_de_uma_data_distinta_prometida(self):
        """"Compromissos reprometidos" conta datas de entrega diferentes
        ao longo do histórico, não apenas "mais de um compromisso": 3
        reuniões com prazo prometido, mas só 2 datas distintas (15/05
        repetido não conta duas vezes)."""
        processo = self._criar_processo(4)
        Acompanhamento.objects.create(
            processo=processo,
            referencia_data=date(2026, 1, 10),
            origem_hash="hash-reprometido-1",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
            situacao=self.situacao_a,
            prazo_prometido=date(2026, 5, 15),
        )
        Acompanhamento.objects.create(
            processo=processo,
            referencia_data=date(2026, 2, 10),
            origem_hash="hash-reprometido-2",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
            situacao=self.situacao_a,
            prazo_prometido=date(2026, 8, 21),
        )
        Acompanhamento.objects.create(
            processo=processo,
            referencia_data=date(2026, 3, 10),
            origem_hash="hash-reprometido-3",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
            situacao=self.situacao_a,
            prazo_prometido=date(2026, 8, 21),
        )

        resultado = Processo.objects.para_listagem().get(pk=processo.pk)
        self.assertEqual(resultado.n_compromissos, 3)
        self.assertEqual(resultado.n_prazos_distintos, 2)
        self.assertTrue(resultado.reprometido)

    def test_um_unico_prazo_prometido_nao_e_reprometido(self):
        processo = self._criar_processo(5)
        Acompanhamento.objects.create(
            processo=processo,
            referencia_data=date(2026, 1, 10),
            origem_hash="hash-nao-reprometido",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
            situacao=self.situacao_a,
            prazo_prometido=date(2026, 5, 15),
        )

        resultado = Processo.objects.para_listagem().get(pk=processo.pk)
        self.assertEqual(resultado.n_prazos_distintos, 1)
        self.assertFalse(resultado.reprometido)

    def test_sem_prazo_prometido_nao_e_reprometido(self):
        processo = self._criar_processo(6)
        resultado = Processo.objects.para_listagem().get(pk=processo.pk)
        self.assertEqual(resultado.n_prazos_distintos, 0)
        self.assertFalse(resultado.reprometido)


class TestPrazoEfetivoEAtraso(TestCase):
    """Matriz de regressão de `prazo_efetivo`, `atrasado`, `dias_atraso`,
    `n_prorrogacoes` e `qualificador_prazo`. Todas as anotações nascem
    numa única avaliação de `para_listagem()`, sem consulta por linha.

    Classe irmã de `TestQuerysetBase`, não subclasse — evitar herdar seus
    métodos `test_*` e rodá-los em duplicata (mesmo padrão de
    `TestSinaisAtencao` logo abaixo)."""

    @classmethod
    def setUpTestData(cls):
        cls.unidade = Unidade.objects.create(nome="Presidência")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.tipo = Tipo.objects.create(nome="Aquisição")
        cls.situacao_a = SituacaoNormalizada.objects.create(nome="Em tramitação")
        cls.exercicio = Exercicio.objects.get(ano=2026)

    def _criar_processo(self, item_pca, **kwargs):
        defaults = {
            "descricao_objeto": f"Objeto {item_pca}",
            "tipo": self.tipo,
            "categoria": self.categoria,
            "unidade_organizacional": self.unidade,
        }
        defaults.update(kwargs)
        return Processo.objects.create(
            item_pca=item_pca, exercicio=self.exercicio, **defaults
        )

    def test_prazo_efetivo_prefere_promessa_e_cai_no_planejado(self):
        sem_promessa = self._criar_processo(60, prazo_entrega=date(2026, 6, 1))
        com_promessa = self._criar_processo(61, prazo_entrega=date(2026, 6, 1))
        Acompanhamento.objects.create(
            processo=com_promessa,
            referencia_data=date(2026, 1, 10),
            origem_hash="hash-prazo-efetivo-promessa",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
            situacao=self.situacao_a,
            prazo_prometido=date(2026, 8, 1),
        )
        sem_nada = self._criar_processo(62)

        qs = Processo.objects.para_listagem()
        self.assertEqual(qs.get(pk=sem_promessa.pk).prazo_efetivo, date(2026, 6, 1))
        self.assertEqual(qs.get(pk=com_promessa.pk).prazo_efetivo, date(2026, 8, 1))
        self.assertIsNone(qs.get(pk=sem_nada.pk).prazo_efetivo)

    def test_atraso_fecha_na_entrega_ou_status_terminal(self):
        with freeze_time("2026-08-15 12:00:00"):
            vencido_ativo = self._criar_processo(70, prazo_entrega=date(2026, 8, 1))
            vencido_entregue = self._criar_processo(
                71,
                prazo_entrega=date(2026, 8, 1),
                data_recebimento_gelic=date(2026, 8, 5),
            )
            vencido_concluido = self._criar_processo(
                72, prazo_entrega=date(2026, 8, 1), situacao=Situacao.CONCLUIDO.value
            )
            vencido_cancelado = self._criar_processo(
                73, prazo_entrega=date(2026, 8, 1), estado=Estado.CANCELADO.value
            )

            qs = Processo.objects.para_listagem()
            self.assertTrue(qs.get(pk=vencido_ativo.pk).atrasado)
            self.assertFalse(qs.get(pk=vencido_entregue.pk).atrasado)
            self.assertFalse(qs.get(pk=vencido_concluido.pk).atrasado)
            self.assertFalse(qs.get(pk=vencido_cancelado.pk).atrasado)

    def test_promessa_futura_remove_atraso_corrente(self):
        """Atraso é estado corrente: uma promessa nova e futura tira o
        processo do atraso na hora, e é o contador de prorrogações que
        denuncia o furo (não uma marca permanente)."""
        with freeze_time("2026-08-15 12:00:00"):
            processo = self._criar_processo(74, prazo_entrega=date(2026, 1, 1))
            Acompanhamento.objects.create(
                processo=processo,
                referencia_data=date(2026, 1, 10),
                origem_hash="hash-promessa-vencida",
                tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
                situacao=self.situacao_a,
                prazo_prometido=date(2026, 2, 1),
            )
            resultado_vencido = Processo.objects.para_listagem().get(pk=processo.pk)
            self.assertTrue(resultado_vencido.atrasado)

            Acompanhamento.objects.create(
                processo=processo,
                referencia_data=date(2026, 8, 10),
                origem_hash="hash-promessa-futura",
                tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
                situacao=self.situacao_a,
                prazo_prometido=date(2026, 9, 1),
            )
            resultado_novo = Processo.objects.para_listagem().get(pk=processo.pk)
            self.assertFalse(resultado_novo.atrasado)
            self.assertEqual(resultado_novo.n_prorrogacoes, 1)

    def test_dias_atraso_respeita_localdate(self):
        with freeze_time("2026-08-15 12:00:00"):
            processo = self._criar_processo(75, prazo_entrega=date(2026, 8, 5))
            resultado = Processo.objects.para_listagem().get(pk=processo.pk)
            self.assertTrue(resultado.atrasado)
            self.assertEqual(resultado.dias_atraso, 10)

            sem_atraso = self._criar_processo(76, prazo_entrega=date(2026, 9, 1))
            resultado_sem = Processo.objects.para_listagem().get(pk=sem_atraso.pk)
            self.assertFalse(resultado_sem.atrasado)
            self.assertEqual(resultado_sem.dias_atraso, 0)

            sem_prazo = self._criar_processo(77)
            resultado_vazio = Processo.objects.para_listagem().get(pk=sem_prazo.pk)
            self.assertEqual(resultado_vazio.dias_atraso, 0)

    def test_processo_65_tem_uma_prorrogacao(self):
        """15/05 → 21/08 → 21/08: 3 compromissos, 2 datas distintas, 1
        prorrogação (n_prazos_distintos - 1, piso zero)."""
        processo = self._criar_processo(65)
        for i, (referencia, prazo) in enumerate(
            [
                (date(2026, 4, 1), date(2026, 5, 15)),
                (date(2026, 6, 1), date(2026, 8, 21)),
                (date(2026, 7, 1), date(2026, 8, 21)),
            ],
            start=1,
        ):
            Acompanhamento.objects.create(
                processo=processo,
                referencia_data=referencia,
                origem_hash=f"hash-processo-65-{i}",
                tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
                situacao=self.situacao_a,
                prazo_prometido=prazo,
            )

        resultado = Processo.objects.para_listagem().get(pk=processo.pk)
        self.assertEqual(resultado.n_compromissos, 3)
        self.assertEqual(resultado.n_prazos_distintos, 2)
        self.assertEqual(resultado.n_prorrogacoes, 1)
        self.assertTrue(resultado.reprometido)

    def test_retorno_a_data_anterior_documenta_limite_do_count_distinct(self):
        """Limitação conhecida (Claude's Discretion, 11-CONTEXT.md):
        `Count(distinct)` conta VALORES distintos, não MUDANÇAS. 15/05 →
        21/08 → 15/05 são duas mudanças reais, mas só 2 datas distintas — o
        contador marca 1 prorrogação, não 2. É o preço documentado de manter
        o cálculo no banco (ORM, nunca Python por linha)."""
        processo = self._criar_processo(80)
        for i, (referencia, prazo) in enumerate(
            [
                (date(2026, 4, 1), date(2026, 5, 15)),
                (date(2026, 6, 1), date(2026, 8, 21)),
                (date(2026, 7, 1), date(2026, 5, 15)),
            ],
            start=1,
        ):
            Acompanhamento.objects.create(
                processo=processo,
                referencia_data=referencia,
                origem_hash=f"hash-retorno-{i}",
                tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
                situacao=self.situacao_a,
                prazo_prometido=prazo,
            )

        resultado = Processo.objects.para_listagem().get(pk=processo.pk)
        self.assertEqual(resultado.n_compromissos, 3)
        self.assertEqual(resultado.n_prazos_distintos, 2)
        self.assertEqual(resultado.n_prorrogacoes, 1)

    def test_qualificador_prazo_reflete_atraso_dentro_fora_e_vazio(self):
        with freeze_time("2026-08-15 12:00:00"):
            atrasado = self._criar_processo(90, prazo_entrega=date(2026, 8, 1))
            dentro = self._criar_processo(91, prazo_entrega=date(2026, 9, 1))
            sem_prazo = self._criar_processo(92)
            entregue = self._criar_processo(
                93,
                prazo_entrega=date(2026, 8, 1),
                data_recebimento_gelic=date(2026, 8, 10),
            )

            qs = Processo.objects.para_listagem()
            self.assertEqual(qs.get(pk=atrasado.pk).qualificador_prazo, "fora do prazo")
            self.assertEqual(qs.get(pk=dentro.pk).qualificador_prazo, "dentro do prazo")
            self.assertEqual(qs.get(pk=sem_prazo.pk).qualificador_prazo, "")
            self.assertEqual(qs.get(pk=entregue.pk).qualificador_prazo, "")


class TestSinaisAtencao(TestCase):
    """Os três sinais de risco da faixa de atenção: `criticos` (grau de
    prioridade Alta), `proximos_do_prazo` (prazo_vigente decorrendo
    dentro de 30 dias) e `sem_atualizacao_recente` (último acompanhamento
    há mais de 30 dias, ou nenhum). Bordas temporais controladas por
    freezegun — "hoje" via localdate() em Python, nunca NOW() no SQL.

    freeze_time recebe UTC ingênuo; o fuso é America/São_Paulo (UTC-3). O
    horário 09:00 UTC equivale a 06:00 em Brasília — já 28/07 local.
    """

    @classmethod
    def setUpTestData(cls):
        cls.unidade = Unidade.objects.create(nome="Presidência")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.tipo = Tipo.objects.create(nome="Aquisição")
        cls.situacao_a = SituacaoNormalizada.objects.create(nome="Em tramitação")
        cls.exercicio = Exercicio.objects.get(ano=2026)
        cls.grau_alta = GrauPrioridade.objects.create(nome="Alta")
        cls.grau_media = GrauPrioridade.objects.create(nome="Média")

    def _criar_processo(self, item_pca, **kwargs):
        defaults = {
            "descricao_objeto": f"Objeto {item_pca}",
            "tipo": self.tipo,
            "categoria": self.categoria,
            "unidade_organizacional": self.unidade,
        }
        defaults.update(kwargs)
        return Processo.objects.create(
            item_pca=item_pca, exercicio=self.exercicio, **defaults
        )

    def _criar_processo_com_prazo(self, item_pca, prazo, **kwargs):
        processo = self._criar_processo(item_pca, **kwargs)
        Acompanhamento.objects.create(
            processo=processo,
            referencia_data=date(2026, 1, 10),
            origem_hash=f"hash-proximo-{item_pca}",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
            situacao=self.situacao_a,
            prazo_prometido=prazo,
        )
        return processo

    def _criar_processo_com_acompanhamento(self, item_pca, referencia_data, **kwargs):
        processo = self._criar_processo(item_pca, **kwargs)
        Acompanhamento.objects.create(
            processo=processo,
            referencia_data=referencia_data,
            origem_hash=f"hash-sem-atualizacao-{item_pca}",
            tipo_evento=TipoEvento.GESTAO_RISCOS.value,
            situacao=self.situacao_a,
        )
        return processo

    # --- críticos ---------------------------------------------------------

    def test_criticos_inclui_alta_em_tramitacao_e_exclui_demais(self):
        em_tramitacao = self._criar_processo(10, grau_prioridade=self.grau_alta)
        concluido = self._criar_processo(
            11, grau_prioridade=self.grau_alta, situacao=Situacao.CONCLUIDO.value
        )
        cancelado = self._criar_processo(
            12, grau_prioridade=self.grau_alta, estado=Estado.CANCELADO.value
        )
        media = self._criar_processo(13, grau_prioridade=self.grau_media)
        sem_grau = self._criar_processo(14)

        criticos = Processo.objects.para_listagem().criticos()
        ids = set(criticos.values_list("id", flat=True))
        self.assertIn(em_tramitacao.pk, ids)
        self.assertNotIn(concluido.pk, ids)
        self.assertNotIn(cancelado.pk, ids)
        self.assertNotIn(media.pk, ids)
        self.assertNotIn(sem_grau.pk, ids)

    def test_criticos_resolve_variante_renomeada_ou_acentuada_por_nome_normalizado(self):
        # Renomear o rótulo ("Álta") NÃO muda nome_normalizado ("alta") —
        # a resolução é pela chave natural, sem query de lookup.
        self.grau_alta.nome = "Álta"
        self.grau_alta.save()
        self.assertEqual(self.grau_alta.nome_normalizado, "alta")
        processo = self._criar_processo(20, grau_prioridade=self.grau_alta)
        criticos = Processo.objects.para_listagem().criticos()
        self.assertEqual(list(criticos.values_list("id", flat=True)), [processo.pk])

    def test_criticos_sem_grau_alta_no_dominio_retorna_vazio(self):
        self._criar_processo(30, grau_prioridade=self.grau_media)
        GrauPrioridade.objects.filter(nome_normalizado="alta").delete()
        self.assertEqual(Processo.objects.para_listagem().criticos().count(), 0)

    # --- próximos do prazo -------------------------------------------------

    def test_proximos_do_prazo_respeita_bordas_de_30_dias(self):
        with freeze_time("2026-07-28 09:00:00"):  # 06:00 em Brasília, hoje = 28/07
            hoje = date(2026, 7, 28)
            casos = {
                "hoje": self._criar_processo_com_prazo(40, hoje),
                "amanha": self._criar_processo_com_prazo(41, hoje + timedelta(days=1)),
                "dia30": self._criar_processo_com_prazo(42, hoje + timedelta(days=30)),
                "dia31": self._criar_processo_com_prazo(43, hoje + timedelta(days=31)),
                "sem_prazo": self._criar_processo(44),
                "concluido": self._criar_processo_com_prazo(
                    45, hoje + timedelta(days=5), situacao=Situacao.CONCLUIDO.value
                ),
            }
            proximos = set(
                Processo.objects.para_listagem()
                .proximos_do_prazo()
                .values_list("id", flat=True)
            )
            self.assertIn(casos["amanha"].pk, proximos)
            self.assertIn(casos["dia30"].pk, proximos)
            self.assertNotIn(casos["hoje"].pk, proximos)
            self.assertNotIn(casos["dia31"].pk, proximos)
            self.assertNotIn(casos["sem_prazo"].pk, proximos)
            self.assertNotIn(casos["concluido"].pk, proximos)

    def test_proximos_do_prazo_cai_no_prazo_entrega_sem_promessa(self):
        """`proximos_do_prazo()` filtra por `prazo_efetivo`; um processo
        sem nenhuma promessa da UO, mas com `prazo_entrega` dentro da
        janela de 30 dias, entra na lista."""
        with freeze_time("2026-07-28 09:00:00"):
            hoje = date(2026, 7, 28)
            sem_promessa = self._criar_processo(
                46, prazo_entrega=hoje + timedelta(days=10)
            )
            proximos = set(
                Processo.objects.para_listagem()
                .proximos_do_prazo()
                .values_list("id", flat=True)
            )
            self.assertIn(sem_promessa.pk, proximos)

    # --- sem atualização recente --------------------------------------------

    def test_sem_atualizacao_recente_respeita_bordas_de_30_dias(self):
        with freeze_time("2026-07-28 09:00:00"):
            hoje = date(2026, 7, 28)
            casos = {
                "sem_acompanhamento": self._criar_processo(50),
                "exatos_30": self._criar_processo_com_acompanhamento(
                    51, hoje - timedelta(days=30)
                ),
                "ha_31": self._criar_processo_com_acompanhamento(
                    52, hoje - timedelta(days=31)
                ),
                "concluido_sem": self._criar_processo(
                    53, situacao=Situacao.CONCLUIDO.value
                ),
            }
            sem_atualizacao = set(
                Processo.objects.para_listagem()
                .sem_atualizacao_recente()
                .values_list("id", flat=True)
            )
            self.assertIn(casos["sem_acompanhamento"].pk, sem_atualizacao)
            self.assertIn(casos["ha_31"].pk, sem_atualizacao)
            self.assertNotIn(casos["exatos_30"].pk, sem_atualizacao)
            self.assertNotIn(casos["concluido_sem"].pk, sem_atualizacao)


class TestSituacaoEfetivaERecortesTransversais(TestCase):
    """`situacao_efetiva` e os dois recortes transversais do Bloco B,
    `proximo_vencimento_gelic` e `sobrestados`. Classe irmã das demais
    desta suíte (não subclasse), mesmo padrão de `TestSinaisAtencao` —
    evita herdar/rodar `test_*` em duplicata."""

    @classmethod
    def setUpTestData(cls):
        cls.unidade = Unidade.objects.create(nome="Presidência")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.tipo = Tipo.objects.create(nome="Aquisição")
        cls.exercicio = Exercicio.objects.get(ano=2026)

    def _criar_processo(self, item_pca, **kwargs):
        defaults = {
            "descricao_objeto": f"Objeto {item_pca}",
            "tipo": self.tipo,
            "categoria": self.categoria,
            "unidade_organizacional": self.unidade,
            "estado": Estado.ATIVO,
        }
        defaults.update(kwargs)
        return Processo.objects.create(
            item_pca=item_pca, exercicio=self.exercicio, **defaults
        )

    # --- situacao_efetiva ---------------------------------------------------

    def test_no_prazo_com_prazo_vencido_corrige_para_atrasado_na_leitura(self):
        with freeze_time("2026-08-15 12:00:00"):
            processo = self._criar_processo(
                200,
                situacao=Situacao.NO_PRAZO,
                prazo_entrega=date(2026, 8, 14),  # ontem
            )
            resultado = Processo.objects.para_listagem().get(pk=processo.pk)
            self.assertEqual(resultado.situacao_efetiva, Situacao.ATRASADO.value)

            # A coluna crua no banco continua NO_PRAZO — a correção é só
            # de leitura, sem escrita nenhuma.
            processo.refresh_from_db()
            self.assertEqual(processo.situacao, Situacao.NO_PRAZO.value)

    def test_no_prazo_com_prazo_futuro_nao_corrige(self):
        with freeze_time("2026-08-15 12:00:00"):
            processo = self._criar_processo(
                201,
                situacao=Situacao.NO_PRAZO,
                prazo_entrega=date(2026, 8, 16),  # amanhã
            )
            resultado = Processo.objects.para_listagem().get(pk=processo.pk)
            self.assertEqual(resultado.situacao_efetiva, Situacao.NO_PRAZO.value)

    def test_atrasado_gravado_manualmente_nunca_e_revertido_pela_leitura(self):
        """Sobreposição manual explícita vence a correção: mesmo com
        `prazo_entrega` no futuro (renegociação hipotética não refletida
        no prazo), um processo já gravado ATRASADO nunca volta a
        NO_PRAZO só pela leitura."""
        with freeze_time("2026-08-15 12:00:00"):
            processo = self._criar_processo(
                202,
                situacao=Situacao.ATRASADO,
                prazo_entrega=date(2026, 8, 16),  # amanhã
            )
            resultado = Processo.objects.para_listagem().get(pk=processo.pk)
            self.assertEqual(resultado.situacao_efetiva, Situacao.ATRASADO.value)

    def test_situacoes_nao_corrigidas_passam_direto_independente_do_prazo(self):
        with freeze_time("2026-08-15 12:00:00"):
            em_tramitacao = self._criar_processo(
                203,
                situacao=Situacao.EM_TRAMITACAO,
                prazo_entrega=date(2026, 8, 14),  # vencido
            )
            concluido = self._criar_processo(
                204,
                situacao=Situacao.CONCLUIDO,
                prazo_entrega=date(2026, 8, 14),  # vencido
            )
            qs = Processo.objects.para_listagem()
            self.assertEqual(
                qs.get(pk=em_tramitacao.pk).situacao_efetiva,
                Situacao.EM_TRAMITACAO.value,
            )
            self.assertEqual(
                qs.get(pk=concluido.pk).situacao_efetiva, Situacao.CONCLUIDO.value
            )

    def test_no_prazo_com_promessa_mais_recente_vencida_corrige_para_atrasado(
        self,
    ):
        """A correção na leitura mede contra `prazo_efetivo =
        COALESCE(prazo_vigente, prazo_entrega)`, não `prazo_entrega` cru.
        Processo NO_PRAZO com `prazo_entrega` nulo, mas cuja promessa mais
        recente (maior `referencia_data`) já venceu, precisa aparecer
        como ATRASADO."""
        with freeze_time("2026-08-29 12:00:00"):
            processo = self._criar_processo(
                205,
                situacao=Situacao.NO_PRAZO,
                prazo_entrega=None,
            )
            situacao_normalizada = SituacaoNormalizada.objects.create(
                nome="Compromisso de entrega"
            )
            # Promessa mais antiga, já vencida também, mas NÃO é a mais
            # recente — prova que o critério de desempate é o mesmo de
            # `prazo_vigente` (maior referencia_data, depois maior id).
            Acompanhamento.objects.create(
                processo=processo,
                referencia_data=date(2026, 6, 1),
                origem_hash="hash-promessa-antiga-205",
                tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
                situacao=situacao_normalizada,
                prazo_prometido=date(2026, 12, 1),  # futura, mas superada
            )
            # Promessa mais recente — já vencida.
            Acompanhamento.objects.create(
                processo=processo,
                referencia_data=date(2026, 8, 1),
                origem_hash="hash-promessa-recente-205",
                tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
                situacao=situacao_normalizada,
                prazo_prometido=date(2026, 8, 20),  # vencida
            )
            resultado = Processo.objects.para_listagem().get(pk=processo.pk)
            self.assertEqual(resultado.situacao_efetiva, Situacao.ATRASADO.value)

            processo.refresh_from_db()
            self.assertEqual(processo.situacao, Situacao.NO_PRAZO.value)

    # --- sobreposicao_manual_ativa -------------------------------------------

    def test_manual_no_prazo_com_prazo_vencido_nao_e_promovido_mas_dias_atraso_mede_o_atraso(
        self,
    ):
        """"Manual No prazo → promessa passada → leitura permanece No
        prazo, mas `dias_atraso` continua refletindo a data vencida."
        `situacao_efetiva` preserva a sobreposição manual;
        `atrasado`/`dias_atraso` (métricas factuais) não são mascarados."""
        with freeze_time("2026-08-15 12:00:00"):
            processo = self._criar_processo(
                206,
                situacao=Situacao.NO_PRAZO,
                prazo_entrega=date(2026, 8, 1),  # vencido há 14 dias
            )
            Acompanhamento.objects.create(
                processo=processo,
                referencia_data=date(2026, 7, 1),
                origem_hash="hash-manual-no-prazo-206",
                tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
                situacao=SituacaoNormalizada.objects.create(
                    nome="Situação manual 206"
                ),
                transicao_manual=True,
            )

            resultado = Processo.objects.para_listagem().get(pk=processo.pk)
            self.assertTrue(resultado.sobreposicao_manual_ativa)
            self.assertEqual(resultado.situacao_efetiva, Situacao.NO_PRAZO.value)
            self.assertTrue(resultado.atrasado)
            self.assertEqual(resultado.dias_atraso, 14)

    def test_sobreposicao_manual_ativa_e_false_sem_nenhuma_transicao_manual(self):
        processo = self._criar_processo(207, situacao=Situacao.NO_PRAZO)
        Acompanhamento.objects.create(
            processo=processo,
            referencia_data=date(2026, 7, 1),
            origem_hash="hash-automatico-207",
            tipo_evento=TipoEvento.AUTOMATICO.value,
            situacao=SituacaoNormalizada.objects.create(nome="Situação 207"),
        )

        resultado = Processo.objects.para_listagem().get(pk=processo.pk)
        self.assertFalse(resultado.sobreposicao_manual_ativa)

    # --- prazo_inicial -------------------------------------------------------

    def test_prazo_inicial_prefere_prazo_entrega_do_pca(self):
        processo = self._criar_processo(208, prazo_entrega=date(2026, 3, 1))
        Acompanhamento.objects.create(
            processo=processo,
            referencia_data=date(2026, 1, 1),
            origem_hash="hash-prazo-inicial-208",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
            situacao=SituacaoNormalizada.objects.create(nome="Situação 208"),
            prazo_prometido=date(2026, 6, 1),
        )

        resultado = Processo.objects.para_listagem().get(pk=processo.pk)
        self.assertEqual(resultado.prazo_inicial, date(2026, 3, 1))

    def test_prazo_inicial_cai_na_primeira_promessa_sem_prazo_entrega(self):
        processo = self._criar_processo(209, prazo_entrega=None)
        situacao_normalizada = SituacaoNormalizada.objects.create(
            nome="Situação 209"
        )
        Acompanhamento.objects.create(
            processo=processo,
            referencia_data=date(2026, 6, 1),
            origem_hash="hash-prazo-inicial-209-primeira",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
            situacao=situacao_normalizada,
            prazo_prometido=date(2026, 6, 30),
        )
        Acompanhamento.objects.create(
            processo=processo,
            referencia_data=date(2026, 8, 1),
            origem_hash="hash-prazo-inicial-209-ultima",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
            situacao=situacao_normalizada,
            prazo_prometido=date(2026, 9, 30),
        )

        resultado = Processo.objects.para_listagem().get(pk=processo.pk)
        self.assertEqual(resultado.prazo_inicial, date(2026, 6, 30))

    def test_prazo_inicial_desempate_por_id_crescente_na_mesma_referencia_data(self):
        """EDGE FIC29-03 adjacency: promessas com a mesma `referencia_data`
        usam id CRESCENTE para a inicial (a primeira gravada), oposto do
        desempate por `-id` de `prazo_vigente`/`ultimo`."""
        processo = self._criar_processo(210, prazo_entrega=None)
        situacao_normalizada = SituacaoNormalizada.objects.create(
            nome="Situação 210"
        )
        mesma_data = date(2026, 6, 1)
        Acompanhamento.objects.create(
            processo=processo,
            referencia_data=mesma_data,
            origem_hash="hash-prazo-inicial-210-a",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
            situacao=situacao_normalizada,
            prazo_prometido=date(2026, 7, 1),
        )
        Acompanhamento.objects.create(
            processo=processo,
            referencia_data=mesma_data,
            origem_hash="hash-prazo-inicial-210-b",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
            situacao=situacao_normalizada,
            prazo_prometido=date(2026, 8, 1),
        )

        resultado = Processo.objects.para_listagem().get(pk=processo.pk)
        self.assertEqual(resultado.prazo_inicial, date(2026, 7, 1))

    def test_prazo_inicial_nulo_sem_prazo_entrega_nem_promessa(self):
        """EDGE FIC29-03 empty: sem `prazo_entrega` nem promessa, a
        anotação fica nula."""
        processo = self._criar_processo(211, prazo_entrega=None)

        resultado = Processo.objects.para_listagem().get(pk=processo.pk)
        self.assertIsNone(resultado.prazo_inicial)

    def test_prazo_inicial_e_prazo_vigente_coincidem_com_uma_unica_promessa(self):
        """EDGE FIC29-03 empty: com uma única promessa, ela é
        simultaneamente inicial e vigente/atual."""
        processo = self._criar_processo(212, prazo_entrega=None)
        Acompanhamento.objects.create(
            processo=processo,
            referencia_data=date(2026, 6, 1),
            origem_hash="hash-prazo-inicial-212",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
            situacao=SituacaoNormalizada.objects.create(nome="Situação 212"),
            prazo_prometido=date(2026, 7, 15),
        )

        resultado = Processo.objects.para_listagem().get(pk=processo.pk)
        self.assertEqual(resultado.prazo_inicial, date(2026, 7, 15))
        self.assertEqual(resultado.prazo_vigente, date(2026, 7, 15))
        self.assertEqual(resultado.prazo_inicial, resultado.prazo_vigente)

    # --- proximo_vencimento_gelic -------------------------------------------

    @override_settings(PCA_DIAS_PROXIMOS_VENCIMENTO=15)
    def test_proximo_vencimento_gelic_respeita_janela_configuravel_e_exclui_cancelado(
        self,
    ):
        with freeze_time("2026-08-15 12:00:00"):
            hoje = date(2026, 8, 15)
            dentro_da_janela = self._criar_processo(
                210,
                situacao=Situacao.NO_PRAZO,
                prazo_entrega=hoje + timedelta(days=14),  # N-1
            )
            fora_da_janela = self._criar_processo(
                211,
                situacao=Situacao.NO_PRAZO,
                prazo_entrega=hoje + timedelta(days=16),  # N+1
            )
            cancelado_na_janela = self._criar_processo(
                212,
                situacao=Situacao.NO_PRAZO,
                estado=Estado.CANCELADO,
                prazo_entrega=hoje + timedelta(days=10),
            )

            proximos = set(
                Processo.objects.para_listagem()
                .proximo_vencimento_gelic(15)
                .values_list("id", flat=True)
            )
            self.assertIn(dentro_da_janela.pk, proximos)
            self.assertNotIn(fora_da_janela.pk, proximos)
            self.assertNotIn(cancelado_na_janela.pk, proximos)

    # --- sobrestados -----------------------------------------------------------

    def test_sobrestados_exige_mais_de_uma_prorrogacao_e_exclui_cancelado(self):
        duas_prorrogacoes = self._criar_processo(220)
        uma_prorrogacao = self._criar_processo(221)
        cancelado_com_duas_prorrogacoes = self._criar_processo(
            222, estado=Estado.CANCELADO
        )

        for i, prazo in enumerate(
            (date(2026, 5, 15), date(2026, 6, 15), date(2026, 7, 15)), start=1
        ):
            Acompanhamento.objects.create(
                processo=duas_prorrogacoes,
                referencia_data=date(2026, 1, i),
                origem_hash=f"hash-sobrestado-duas-{i}",
                tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
                situacao=SituacaoNormalizada.objects.create(
                    nome=f"Situação sobrestado duas {i}"
                ),
                prazo_prometido=prazo,
            )

        for i, prazo in enumerate((date(2026, 5, 15), date(2026, 6, 15)), start=1):
            Acompanhamento.objects.create(
                processo=uma_prorrogacao,
                referencia_data=date(2026, 1, i),
                origem_hash=f"hash-sobrestado-uma-{i}",
                tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
                situacao=SituacaoNormalizada.objects.create(
                    nome=f"Situação sobrestado uma {i}"
                ),
                prazo_prometido=prazo,
            )

        for i, prazo in enumerate(
            (date(2026, 5, 15), date(2026, 6, 15), date(2026, 7, 15)), start=1
        ):
            Acompanhamento.objects.create(
                processo=cancelado_com_duas_prorrogacoes,
                referencia_data=date(2026, 1, i),
                origem_hash=f"hash-sobrestado-cancelado-{i}",
                tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
                situacao=SituacaoNormalizada.objects.create(
                    nome=f"Situação sobrestado cancelado {i}"
                ),
                prazo_prometido=prazo,
            )

        sobrestados = set(
            Processo.objects.para_listagem()
            .sobrestados()
            .values_list("id", flat=True)
        )
        self.assertIn(duas_prorrogacoes.pk, sobrestados)
        self.assertNotIn(uma_prorrogacao.pk, sobrestados)
        self.assertNotIn(cancelado_com_duas_prorrogacoes.pk, sobrestados)
