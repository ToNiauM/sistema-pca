"""Testes do motor de "git log" do PCA.

Dataclasses, motor de diff de histórico, dicionário de frases, resolução
de período, e os 4 blocos independentes de `prazo_prometido` (Inclusões,
Exclusões, Iniciados, Concluídos): apuração da situação do compromisso,
bloco Adiados, bloco Alterações e `montar_relatorio()` (orquestração +
dedup).
"""

import time as tempo_parede
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.catalogo.models import (
    Categoria,
    Exercicio,
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
from apps.pca.relatorio_movimentacao import (
    ABREV_MES,
    CAMPOS_ALTERACOES,
    FRASES_CAMPO,
    ORDEM_EXIBICAO_BLOCOS,
    ORDEM_PRECEDENCIA_BLOCOS,
    _bloco_adiados,
    _bloco_alteracoes,
    _bloco_concluidos,
    _bloco_exclusoes,
    _bloco_inclusoes,
    _bloco_iniciados,
    apurar_situacao_compromisso,
    compromisso_vigente,
    consolidar_mudancas,
    formatar_valor_campo,
    frase_compromisso,
    frase_mudanca_campo,
    montar_relatorio,
    mudancas_no_periodo,
    resolver_periodo_relatorio,
)


def _aware(data, hora=time(12, 0)):
    return timezone.make_aware(datetime.combine(data, hora))


class BaseRelatorioTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.exercicio = Exercicio.objects.get(ano=2026)
        cls.unidade = Unidade.objects.create(nome="GEX-ITEC")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.tipo = Tipo.objects.create(nome="Aquisição")
        cls.usuario = get_user_model().objects.create_user(
            email="relatorio@pca.local", password="senha-forte-123"
        )

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

    def _criar_processo_datado(self, item_pca, data_criacao, **kwargs):
        """Como `_criar_processo`, mas com `_history_date` do registro `+`
        no passado — necessário sempre que o teste for encadear updates
        também com `_history_date` no passado: sem isto, o snapshot de
        criação nasce com `history_date=now()` (o relógio real do
        container), que ordena DEPOIS de qualquer data de 2026 anterior a
        hoje e inverte a ordem cronológica anterior/atual."""
        defaults = {
            "descricao_objeto": f"Objeto {item_pca}",
            "tipo": self.tipo,
            "categoria": self.categoria,
            "unidade_organizacional": self.unidade,
        }
        defaults.update(kwargs)
        processo = Processo(item_pca=item_pca, exercicio=self.exercicio, **defaults)
        processo._history_date = _aware(data_criacao)
        processo._history_user = self.usuario
        processo.save()
        return processo


class TestOrdensEVocabulario(BaseRelatorioTests):
    def test_ordem_exibicao_difere_da_ordem_precedencia(self):
        self.assertNotEqual(ORDEM_EXIBICAO_BLOCOS, ORDEM_PRECEDENCIA_BLOCOS)
        self.assertEqual(set(ORDEM_EXIBICAO_BLOCOS), set(ORDEM_PRECEDENCIA_BLOCOS))

    def test_campos_alteracoes_nao_inclui_campos_fora_de_escopo(self):
        for fora in ("descricao_objeto", "justificativa", "categoria", "tipo"):
            self.assertNotIn(fora, CAMPOS_ALTERACOES)

    def test_frases_campo_cobre_todos_os_campos_de_alteracoes(self):
        for campo in CAMPOS_ALTERACOES:
            self.assertIn(campo, FRASES_CAMPO)

    def test_abrev_mes_tem_12_entradas(self):
        self.assertEqual(len(ABREV_MES), 12)
        self.assertEqual(ABREV_MES[1], "jan")
        self.assertEqual(ABREV_MES[12], "dez")


class TestFormatarValorCampo(BaseRelatorioTests):
    def test_valor_monetario(self):
        self.assertEqual(
            formatar_valor_campo("valor_estimado", Decimal("1500.50"), mapas_fk={}),
            "R$ 1.500,50",
        )

    def test_mes_previsto_por_extenso(self):
        self.assertEqual(formatar_valor_campo("mes_previsto", 8, mapas_fk={}), "Agosto")

    def test_mes_previsto_none(self):
        self.assertEqual(
            formatar_valor_campo("mes_previsto", None, mapas_fk={}),
            "sem mês previsto definido",
        )

    def test_fk_resolvida_pelo_mapa(self):
        mapas_fk = {"unidade_organizacional": {self.unidade.pk: self.unidade.nome}}
        self.assertEqual(
            formatar_valor_campo(
                "unidade_organizacional", self.unidade.pk, mapas_fk=mapas_fk
            ),
            self.unidade.nome,
        )

    def test_fk_sem_entrada_no_mapa_devolve_travessao(self):
        self.assertEqual(
            formatar_valor_campo("unidade_organizacional", 999, mapas_fk={}), "—"
        )

    def test_situacao_label(self):
        self.assertEqual(
            formatar_valor_campo("situacao", Situacao.CONCLUIDO, mapas_fk={}),
            "Concluído",
        )

    def test_situacao_none(self):
        self.assertEqual(formatar_valor_campo("situacao", None, mapas_fk={}), "—")

    def test_data_formatada(self):
        self.assertEqual(
            formatar_valor_campo(
                "data_assinatura_contrato", date(2026, 8, 28), mapas_fk={}
            ),
            "28/08/2026",
        )

    def test_texto_vazio_devolve_travessao(self):
        self.assertEqual(
            formatar_valor_campo("numero_contratacao", None, mapas_fk={}), "—"
        )
        self.assertEqual(
            formatar_valor_campo("numero_contratacao", "12/2026", mapas_fk={}),
            "12/2026",
        )


class TestFraseMudancaCampo(BaseRelatorioTests):
    def test_frase_situacao_no_modelo_aprovado(self):
        processo = self._criar_processo(37, descricao_objeto="Aquisição de notebooks")
        frase = frase_mudanca_campo(
            "situacao",
            Situacao.EM_TRAMITACAO,
            Situacao.CONCLUIDO,
            date(2026, 8, 28),
            processo=processo,
            mapas_fk={},
        )
        self.assertEqual(
            frase,
            "Item 37 – Aquisição de notebooks (GEX-ITEC): situação alterada de "
            "Em tramitação para Concluído em 28/08/2026.",
        )

    def test_frase_trunca_descricao_longa(self):
        descricao = "A" * 80
        processo = self._criar_processo(38, descricao_objeto=descricao)
        frase = frase_mudanca_campo(
            "valor_estimado",
            Decimal("100.00"),
            Decimal("200.00"),
            date(2026, 1, 1),
            processo=processo,
            mapas_fk={},
        )
        # 60 caracteres de descrição + reticências, nunca a string de 80.
        self.assertNotIn("A" * 61, frase)
        self.assertIn("…", frase)


class TestMudancasNoPeriodo(BaseRelatorioTests):
    def test_encontra_mudancas_dentro_do_periodo_em_ordem_cronologica(self):
        processo = self._criar_processo_datado(
            1, date(2025, 12, 1), valor_estimado=Decimal("100.00")
        )
        processo._history_date = _aware(date(2026, 1, 5))
        processo._history_user = self.usuario
        processo.valor_estimado = Decimal("200.00")
        processo.save()

        processo._history_date = _aware(date(2026, 1, 10))
        processo._history_user = self.usuario
        processo.valor_estimado = Decimal("300.00")
        processo.save()

        # Fora do período (mês seguinte).
        processo._history_date = _aware(date(2026, 2, 1))
        processo._history_user = self.usuario
        processo.valor_estimado = Decimal("400.00")
        processo.save()

        resultado = mudancas_no_periodo(
            processo,
            de=date(2026, 1, 1),
            ate=date(2026, 1, 31),
            campos=("valor_estimado",),
        )
        mudancas = resultado["valor_estimado"]
        self.assertEqual(len(mudancas), 2)
        self.assertEqual(mudancas[0].de, Decimal("100.00"))
        self.assertEqual(mudancas[0].para, Decimal("200.00"))
        self.assertEqual(mudancas[1].de, Decimal("200.00"))
        self.assertEqual(mudancas[1].para, Decimal("300.00"))

    def test_limite_inclusivo_23_59_59_incluido_dia_seguinte_nao(self):
        processo = self._criar_processo_datado(
            2, date(2026, 1, 1), valor_estimado=Decimal("10.00")
        )

        processo._history_date = _aware(date(2026, 1, 31), time(23, 59, 59))
        processo._history_user = self.usuario
        processo.valor_estimado = Decimal("20.00")
        processo.save()

        processo._history_date = _aware(date(2026, 2, 1), time(0, 0, 1))
        processo._history_user = self.usuario
        processo.valor_estimado = Decimal("30.00")
        processo.save()

        resultado = mudancas_no_periodo(
            processo,
            de=date(2026, 1, 1),
            ate=date(2026, 1, 31),
            campos=("valor_estimado",),
        )
        mudancas = resultado["valor_estimado"]
        self.assertEqual(len(mudancas), 1)
        self.assertEqual(mudancas[0].para, Decimal("20.00"))

    def test_ignora_o_primeiro_registro_historico(self):
        processo = self._criar_processo(3, valor_estimado=Decimal("10.00"))
        resultado = mudancas_no_periodo(
            processo,
            de=date(2020, 1, 1),
            ate=date(2030, 1, 1),
            campos=("valor_estimado",),
        )
        self.assertEqual(resultado["valor_estimado"], [])

    def test_le_fk_pelo_atributo_id(self):
        outra_unidade = Unidade.objects.create(nome="GEX-CSIS")
        processo = self._criar_processo_datado(4, date(2026, 1, 1))
        processo._history_date = _aware(date(2026, 3, 1))
        processo._history_user = self.usuario
        processo.unidade_organizacional = outra_unidade
        processo.save()

        resultado = mudancas_no_periodo(
            processo,
            de=date(2026, 1, 1),
            ate=date(2026, 12, 31),
            campos=("unidade_organizacional",),
        )
        mudancas = resultado["unidade_organizacional"]
        self.assertEqual(len(mudancas), 1)
        self.assertEqual(mudancas[0].de, self.unidade.pk)
        self.assertEqual(mudancas[0].para, outra_unidade.pk)


class TestConsolidarMudancas(BaseRelatorioTests):
    def test_uma_mudanca_sem_trilha(self):
        from apps.pca.relatorio_movimentacao import MudancaCampo

        mudancas = [MudancaCampo(data=_aware(date(2026, 1, 5)), de="a", para="b")]
        de_liq, para_liq, trilha = consolidar_mudancas(mudancas)
        self.assertEqual((de_liq, para_liq, trilha), ("a", "b", None))

    def test_varias_mudancas_liquido_e_trilha(self):
        from apps.pca.relatorio_movimentacao import MudancaCampo

        mudancas = [
            MudancaCampo(data=_aware(date(2026, 1, 10)), de="b", para="c"),
            MudancaCampo(data=_aware(date(2026, 1, 5)), de="a", para="b"),
        ]
        de_liq, para_liq, trilha = consolidar_mudancas(mudancas)
        self.assertEqual(de_liq, "a")
        self.assertEqual(para_liq, "c")
        self.assertEqual(len(trilha), 2)
        # Ordem cronológica: a→b antes de b→c.
        self.assertEqual(trilha[0][:2], ("a", "b"))
        self.assertEqual(trilha[1][:2], ("b", "c"))


class TestResolverPeriodoRelatorio(BaseRelatorioTests):
    def test_datas_livres_prevalecem(self):
        de, ate = resolver_periodo_relatorio(
            {"de": "2026-02-01", "ate": "2026-02-28"}, self.exercicio
        )
        self.assertEqual((de, ate), (date(2026, 2, 1), date(2026, 2, 28)))

    def test_reuniao_sem_anterior_comeca_em_1_de_janeiro(self):
        reuniao = Reuniao.objects.create(
            data=date(2026, 3, 31),
            situacao=SituacaoReuniao.FECHADA,
            exercicio=self.exercicio,
        )
        de, ate = resolver_periodo_relatorio(
            {"reuniao": str(reuniao.pk)}, self.exercicio
        )
        self.assertEqual(de, date(2026, 1, 1))
        self.assertEqual(ate, date(2026, 3, 31))

    def test_reuniao_com_anterior_comeca_no_dia_seguinte(self):
        Reuniao.objects.create(
            data=date(2026, 2, 28),
            situacao=SituacaoReuniao.FECHADA,
            exercicio=self.exercicio,
        )
        reuniao_atual = Reuniao.objects.create(
            data=date(2026, 3, 31),
            situacao=SituacaoReuniao.FECHADA,
            exercicio=self.exercicio,
        )
        de, ate = resolver_periodo_relatorio(
            {"reuniao": str(reuniao_atual.pk)}, self.exercicio
        )
        self.assertEqual(de, date(2026, 3, 1))
        self.assertEqual(ate, date(2026, 3, 31))

    def test_default_sem_reuniao_ultimos_30_dias(self):
        de, ate = resolver_periodo_relatorio({}, self.exercicio)
        hoje = timezone.localdate()
        self.assertEqual(ate, hoje)
        self.assertEqual(de, hoje - timedelta(days=30))

    def test_default_com_reuniao_dia_seguinte_ate_hoje(self):
        reuniao = Reuniao.objects.create(
            data=timezone.localdate() - timedelta(days=10),
            situacao=SituacaoReuniao.FECHADA,
            exercicio=self.exercicio,
        )
        de, ate = resolver_periodo_relatorio({}, self.exercicio)
        self.assertEqual(ate, timezone.localdate())
        self.assertEqual(de, reuniao.data + timedelta(days=1))

    def test_entrada_malformada_nunca_lanca_excecao(self):
        de, ate = resolver_periodo_relatorio(
            {"de": "não-é-data", "ate": "também-não", "reuniao": "abc"},
            self.exercicio,
        )
        self.assertIsInstance(de, date)
        self.assertIsInstance(ate, date)

    def test_reuniao_de_outro_exercicio_e_ignorada(self):
        outro_exercicio, _ = Exercicio.objects.get_or_create(
            ano=2025, defaults={"rotulo": "PCA 2025"}
        )
        reuniao_outro = Reuniao.objects.create(
            data=date(2025, 6, 30),
            situacao=SituacaoReuniao.FECHADA,
            exercicio=outro_exercicio,
        )
        de, ate = resolver_periodo_relatorio(
            {"reuniao": str(reuniao_outro.pk)}, self.exercicio
        )
        # Cai no default (últimos 30 dias), não usa a reunião de outro ano.
        hoje = timezone.localdate()
        self.assertEqual(ate, hoje)
        self.assertEqual(de, hoje - timedelta(days=30))


class BlocosBaseTests(BaseRelatorioTests):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.situacao_normalizada = SituacaoNormalizada.objects.create(
            nome="Concluído (reunião)"
        )


class TestBlocoInclusoes(BlocosBaseTests):
    def test_inclusao_dentro_do_periodo_aparece_com_frase(self):
        processo = self._criar_processo(
            10,
            data_inclusao_pca=date(2026, 1, 15),
            valor_estimado=Decimal("5000.00"),
        )
        resultado = _bloco_inclusoes(self.exercicio, date(2026, 1, 1), date(2026, 1, 31))
        self.assertIn(processo.pk, resultado)
        frase = resultado[processo.pk]["frases"][0]
        self.assertIn("incluído no PCA em 15/01/2026", frase)
        self.assertIn("R$ 5.000,00", frase)
        self.assertFalse(resultado[processo.pk]["automatico"])

    def test_inclusao_nos_limites_do_periodo_aparece(self):
        inicio = self._criar_processo(11, data_inclusao_pca=date(2026, 1, 1))
        fim = self._criar_processo(12, data_inclusao_pca=date(2026, 1, 31))
        resultado = _bloco_inclusoes(self.exercicio, date(2026, 1, 1), date(2026, 1, 31))
        self.assertIn(inicio.pk, resultado)
        self.assertIn(fim.pk, resultado)

    def test_inclusao_um_dia_antes_do_periodo_nao_aparece(self):
        self._criar_processo(13, data_inclusao_pca=date(2025, 12, 31))
        resultado = _bloco_inclusoes(self.exercicio, date(2026, 1, 1), date(2026, 1, 31))
        self.assertEqual(resultado, {})

    def test_sem_candidatos_devolve_dict_vazio(self):
        resultado = _bloco_inclusoes(self.exercicio, date(2026, 1, 1), date(2026, 1, 31))
        self.assertEqual(resultado, {})


class TestBlocoExclusoes(BlocosBaseTests):
    def test_cancelado_dentro_do_periodo_aparece_com_frase(self):
        processo = self._criar_processo_datado(20, date(2025, 12, 1))
        processo._history_date = _aware(date(2026, 1, 10))
        processo._history_user = self.usuario
        processo.estado = Estado.CANCELADO
        processo.save()

        resultado = _bloco_exclusoes(self.exercicio, date(2026, 1, 1), date(2026, 1, 31))
        self.assertIn(processo.pk, resultado)
        self.assertIn("cancelado em 10/01/2026", resultado[processo.pk]["frases"][0])

    def test_cancelado_fora_do_periodo_nao_aparece(self):
        processo = self._criar_processo_datado(21, date(2025, 12, 1))
        processo._history_date = _aware(date(2025, 12, 15))
        processo._history_user = self.usuario
        processo.estado = Estado.CANCELADO
        processo.save()

        resultado = _bloco_exclusoes(self.exercicio, date(2026, 1, 1), date(2026, 1, 31))
        self.assertNotIn(processo.pk, resultado)

    def test_descartado_na_virada_aparece_com_frase(self):
        processo = self._criar_processo(22)
        destino = Exercicio.objects.create(ano=2027, rotulo="PCA 2027")
        rascunho = RascunhoVirada.objects.create(
            exercicio_origem=self.exercicio,
            ano_destino=2027,
            criado_por=self.usuario,
            confirmado_em=_aware(date(2026, 1, 20)),
            confirmado_por=self.usuario,
        )
        RascunhoItemVirada.objects.create(
            rascunho=rascunho, processo_origem=processo, ordem=1, selecionado=False
        )

        resultado = _bloco_exclusoes(self.exercicio, date(2026, 1, 1), date(2026, 1, 31))
        self.assertIn(processo.pk, resultado)
        frase = resultado[processo.pk]["frases"][0]
        self.assertIn("não migrado na virada para o exercício 2027", frase)
        self.assertIn("20/01/2026", frase)
        destino.delete()

    def test_processo_cancelado_e_descartado_na_virada_conta_uma_vez_pelo_cancelamento(self):
        processo = self._criar_processo_datado(23, date(2025, 12, 1))
        processo._history_date = _aware(date(2026, 1, 10))
        processo._history_user = self.usuario
        processo.estado = Estado.CANCELADO
        processo.save()

        rascunho = RascunhoVirada.objects.create(
            exercicio_origem=self.exercicio,
            ano_destino=2028,
            criado_por=self.usuario,
            confirmado_em=_aware(date(2026, 1, 20)),
            confirmado_por=self.usuario,
        )
        RascunhoItemVirada.objects.create(
            rascunho=rascunho, processo_origem=processo, ordem=1, selecionado=False
        )

        resultado = _bloco_exclusoes(self.exercicio, date(2026, 1, 1), date(2026, 1, 31))
        self.assertEqual(len(resultado), 1)
        self.assertIn("cancelado em", resultado[processo.pk]["frases"][0])


class TestBlocoIniciados(BlocosBaseTests):
    def test_envio_gelic_preenchido_dentro_do_periodo_aparece(self):
        processo = self._criar_processo_datado(30, date(2025, 12, 1))
        processo._history_date = _aware(date(2026, 1, 15))
        processo._history_user = self.usuario
        processo.data_envio_gelic = date(2026, 1, 15)
        processo.save()

        resultado = _bloco_iniciados(self.exercicio, date(2026, 1, 1), date(2026, 1, 31))
        self.assertIn(processo.pk, resultado)
        self.assertIn(
            "encaminhado à Gelic em 15/01/2026", resultado[processo.pk]["frases"][0]
        )

    def test_transicao_historica_antes_do_periodo_nao_aparece_mesmo_com_data_do_campo_dentro(self):
        processo = self._criar_processo_datado(31, date(2025, 11, 1))
        # A transição real (quando o sistema registrou) é ANTES do período,
        # mesmo que o valor gravado no campo caia dentro da janela do
        # relatório — só o `history_date` decide.
        processo._history_date = _aware(date(2025, 12, 1))
        processo._history_user = self.usuario
        processo.data_envio_gelic = date(2026, 1, 10)
        processo.save()

        resultado = _bloco_iniciados(self.exercicio, date(2026, 1, 1), date(2026, 1, 31))
        self.assertNotIn(processo.pk, resultado)


class TestBlocoConcluidos(BlocosBaseTests):
    def test_concluido_com_acompanhamento_automatico(self):
        processo = self._criar_processo_datado(
            40, date(2025, 12, 1), situacao=Situacao.EM_TRAMITACAO
        )
        processo._history_date = _aware(date(2026, 1, 12))
        processo._history_user = self.usuario
        processo.situacao = Situacao.CONCLUIDO
        processo.save()

        Acompanhamento.objects.create(
            processo=processo,
            referencia_data=date(2026, 1, 12),
            origem_hash="hash-concluido-automatico-40",
            tipo_evento=TipoEvento.AUTOMATICO,
            situacao=self.situacao_normalizada,
            evento="Concluído automaticamente pela regra de vigência.",
        )

        resultado = _bloco_concluidos(self.exercicio, date(2026, 1, 1), date(2026, 1, 31))
        self.assertIn(processo.pk, resultado)
        item = resultado[processo.pk]
        self.assertTrue(item["automatico"])
        frase = item["frases"][0]
        self.assertIn(
            "situação alterada de Em tramitação para Concluído em 12/01/2026",
            frase,
        )
        self.assertIn(
            "Justificativa: Concluído automaticamente pela regra de vigência.",
            frase,
        )

    def test_concluido_por_edicao_manual_sem_acompanhamento_correlacionado(self):
        processo = self._criar_processo_datado(
            41, date(2025, 12, 1), situacao=Situacao.NO_PRAZO
        )
        processo._history_date = _aware(date(2026, 1, 13))
        processo._history_user = self.usuario
        processo.situacao = Situacao.CONCLUIDO
        processo.save()

        resultado = _bloco_concluidos(self.exercicio, date(2026, 1, 1), date(2026, 1, 31))
        self.assertIn(processo.pk, resultado)
        item = resultado[processo.pk]
        self.assertFalse(item["automatico"])
        self.assertNotIn("Justificativa:", item["frases"][0])

    def test_conclusao_fora_do_periodo_nao_aparece(self):
        processo = self._criar_processo_datado(
            42, date(2025, 12, 1), situacao=Situacao.NO_PRAZO
        )
        processo._history_date = _aware(date(2025, 12, 20))
        processo._history_user = self.usuario
        processo.situacao = Situacao.CONCLUIDO
        processo.save()

        resultado = _bloco_concluidos(self.exercicio, date(2026, 1, 1), date(2026, 1, 31))
        self.assertNotIn(processo.pk, resultado)


# ---------------------------------------------------------------------------
# Apuração do compromisso e bloco Adiados
# ---------------------------------------------------------------------------


def _criar_reuniao(exercicio, data_reuniao):
    return Reuniao.objects.create(
        data=data_reuniao, situacao=SituacaoReuniao.FECHADA, exercicio=exercicio
    )


class TestApurarSituacaoCompromisso(BlocosBaseTests):
    def _criar_acompanhamento(self, processo, *, referencia_data, prazo_prometido,
                               origem_hash, reuniao=None, evento=""):
        return Acompanhamento.objects.create(
            processo=processo,
            referencia_data=referencia_data,
            origem_hash=origem_hash,
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO,
            situacao=self.situacao_normalizada,
            prazo_prometido=prazo_prometido,
            reuniao=reuniao,
            evento=evento,
        )

    def test_sem_reuniao_e_sem_registro_de_cumprimento(self):
        processo = self._criar_processo(50)
        acompanhamento = self._criar_acompanhamento(
            processo,
            referencia_data=date(2026, 1, 10),
            prazo_prometido=date(2026, 1, 20),
            origem_hash="hash-50-1",
            reuniao=None,
        )
        codigo, rotulo = apurar_situacao_compromisso(acompanhamento)
        self.assertEqual(codigo, "sem_registro_cumprimento")
        self.assertEqual(rotulo, "sem registro de cumprimento")

    def test_em_aberto_quando_prazo_futuro(self):
        processo = self._criar_processo(51)
        reuniao = _criar_reuniao(self.exercicio, date(2026, 1, 10))
        acompanhamento = self._criar_acompanhamento(
            processo,
            referencia_data=date(2026, 1, 10),
            prazo_prometido=date(2026, 3, 1),
            origem_hash="hash-51-1",
            reuniao=reuniao,
        )
        codigo, rotulo = apurar_situacao_compromisso(acompanhamento, hoje=date(2026, 1, 15))
        self.assertEqual(codigo, "em_aberto")
        self.assertEqual(rotulo, "em aberto")

    def test_vencido_quando_prazo_passou_sem_desfecho(self):
        processo = self._criar_processo(52, situacao=Situacao.EM_TRAMITACAO)
        reuniao = _criar_reuniao(self.exercicio, date(2026, 1, 10))
        acompanhamento = self._criar_acompanhamento(
            processo,
            referencia_data=date(2026, 1, 10),
            prazo_prometido=date(2026, 1, 20),
            origem_hash="hash-52-1",
            reuniao=reuniao,
        )
        codigo, rotulo = apurar_situacao_compromisso(acompanhamento, hoje=date(2026, 2, 1))
        self.assertEqual(codigo, "vencido")
        self.assertEqual(rotulo, "vencido")

    def test_cumprido_quando_concluiu_ate_o_prazo(self):
        processo = self._criar_processo_datado(
            53, date(2025, 12, 1), situacao=Situacao.EM_TRAMITACAO
        )
        reuniao = _criar_reuniao(self.exercicio, date(2026, 1, 10))
        acompanhamento = self._criar_acompanhamento(
            processo,
            referencia_data=date(2026, 1, 10),
            prazo_prometido=date(2026, 1, 20),
            origem_hash="hash-53-1",
            reuniao=reuniao,
        )
        processo._history_date = _aware(date(2026, 1, 15))
        processo._history_user = self.usuario
        processo.situacao = Situacao.CONCLUIDO
        processo.save()

        codigo, rotulo = apurar_situacao_compromisso(acompanhamento, hoje=date(2026, 2, 1))
        self.assertEqual(codigo, "cumprido")
        self.assertEqual(rotulo, "cumprido")

    def test_reprogramado_quando_existe_promessa_posterior_com_outro_prazo(self):
        processo = self._criar_processo(54)
        reuniao1 = _criar_reuniao(self.exercicio, date(2026, 1, 10))
        reuniao2 = _criar_reuniao(self.exercicio, date(2026, 2, 10))
        acompanhamento1 = self._criar_acompanhamento(
            processo,
            referencia_data=date(2026, 1, 10),
            prazo_prometido=date(2026, 1, 20),
            origem_hash="hash-54-1",
            reuniao=reuniao1,
        )
        self._criar_acompanhamento(
            processo,
            referencia_data=date(2026, 2, 10),
            prazo_prometido=date(2026, 3, 1),
            origem_hash="hash-54-2",
            reuniao=reuniao2,
        )
        codigo, rotulo = apurar_situacao_compromisso(acompanhamento1, hoje=date(2026, 2, 15))
        self.assertEqual(codigo, "reprogramado")
        self.assertEqual(rotulo, "reprogramado")

    def test_promessa_posterior_com_mesmo_prazo_nao_e_reprogramacao(self):
        processo = self._criar_processo(55)
        reuniao1 = _criar_reuniao(self.exercicio, date(2026, 1, 10))
        reuniao2 = _criar_reuniao(self.exercicio, date(2026, 2, 10))
        acompanhamento1 = self._criar_acompanhamento(
            processo,
            referencia_data=date(2026, 1, 10),
            prazo_prometido=date(2026, 3, 1),
            origem_hash="hash-55-1",
            reuniao=reuniao1,
        )
        self._criar_acompanhamento(
            processo,
            referencia_data=date(2026, 2, 10),
            prazo_prometido=date(2026, 3, 1),
            origem_hash="hash-55-2",
            reuniao=reuniao2,
        )
        codigo, rotulo = apurar_situacao_compromisso(acompanhamento1, hoje=date(2026, 2, 15))
        self.assertEqual(codigo, "em_aberto")


class TestFraseCompromisso(BlocosBaseTests):
    def test_frase_reprogramado_usa_solicitou_adiamento(self):
        processo = self._criar_processo(56, prazo_entrega=date(2026, 1, 5))
        reuniao1 = _criar_reuniao(self.exercicio, date(2026, 1, 10))
        reuniao2 = _criar_reuniao(self.exercicio, date(2026, 2, 10))
        acompanhamento = Acompanhamento.objects.create(
            processo=processo,
            referencia_data=date(2026, 1, 10),
            origem_hash="hash-56-1",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO,
            situacao=self.situacao_normalizada,
            prazo_prometido=date(2026, 1, 20),
            reuniao=reuniao1,
            evento="Equipe reduzida no período.",
        )
        Acompanhamento.objects.create(
            processo=processo,
            referencia_data=date(2026, 2, 10),
            origem_hash="hash-56-2",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO,
            situacao=self.situacao_normalizada,
            prazo_prometido=date(2026, 3, 1),
            reuniao=reuniao2,
        )
        frase = frase_compromisso(acompanhamento, hoje=date(2026, 2, 15))
        self.assertIn("prazo inicial 05/01/2026", frase)
        self.assertIn("na reunião de 10/01/2026", frase)
        self.assertIn("solicitou adiamento para 20/01/2026", frase)
        self.assertIn("Justificativa: Equipe reduzida no período.", frase)
        self.assertIn("Situação apurada pelo sistema: reprogramado.", frase)

    def test_frase_usa_primeira_promessa_quando_sem_prazo_entrega(self):
        """Sem `prazo_entrega`, "prazo inicial" na frase passa a ser a
        mesma anotação `prazo_inicial` de `para_listagem()`
        (COALESCE(prazo_entrega, primeira promessa)): a própria promessa
        sendo narrada aqui é, por definição, uma entrada do histórico,
        então "sem prazo inicial registrado" deixa de aparecer."""
        processo = self._criar_processo(57)
        reuniao = _criar_reuniao(self.exercicio, date(2026, 1, 10))
        acompanhamento = Acompanhamento.objects.create(
            processo=processo,
            referencia_data=date(2026, 1, 10),
            origem_hash="hash-57-1",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO,
            situacao=self.situacao_normalizada,
            prazo_prometido=date(2026, 3, 1),
            reuniao=reuniao,
        )
        frase = frase_compromisso(acompanhamento, hoje=date(2026, 1, 15))
        self.assertIn("prazo inicial 01/03/2026", frase)
        self.assertIn("comprometeu-se a entregar até 01/03/2026", frase)
        self.assertIn("Justificativa: sem justificativa registrada.", frase)
        self.assertIn("Situação apurada pelo sistema: em aberto.", frase)

    def test_frase_prefere_primeira_promessa_nao_a_que_esta_sendo_narrada(self):
        """EDGE FIC29-03 ordering — com DUAS promessas e sem `prazo_entrega`,
        "prazo inicial" é sempre a PRIMEIRA por `(referencia_data, id)`
        ascendente, mesmo ao narrar a promessa mais recente."""
        processo = self._criar_processo(571)
        reuniao1 = _criar_reuniao(self.exercicio, date(2026, 1, 5))
        reuniao2 = _criar_reuniao(self.exercicio, date(2026, 2, 10))
        Acompanhamento.objects.create(
            processo=processo,
            referencia_data=date(2026, 1, 5),
            origem_hash="hash-571-1",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO,
            situacao=self.situacao_normalizada,
            prazo_prometido=date(2026, 1, 31),
            reuniao=reuniao1,
        )
        segunda = Acompanhamento.objects.create(
            processo=processo,
            referencia_data=date(2026, 2, 10),
            origem_hash="hash-571-2",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO,
            situacao=self.situacao_normalizada,
            prazo_prometido=date(2026, 3, 1),
            reuniao=reuniao2,
        )
        frase = frase_compromisso(segunda, hoje=date(2026, 2, 15))
        self.assertIn("prazo inicial 31/01/2026", frase)
        self.assertIn("comprometeu-se a entregar até 01/03/2026", frase)

    def test_frase_chamada_unitaria_com_processo_cru_resolve_pela_mesma_anotacao(self):
        """Chamada unitária com `Processo` cru (não anotado por
        `para_listagem()`): `_resolver_prazo_inicial` cai numa única
        consulta controlada, mesmo resultado de uma chamada em lote."""
        processo = self._criar_processo(572, prazo_entrega=date(2026, 2, 1))
        reuniao = _criar_reuniao(self.exercicio, date(2026, 1, 10))
        acompanhamento = Acompanhamento.objects.create(
            processo=processo,
            referencia_data=date(2026, 1, 10),
            origem_hash="hash-572-1",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO,
            situacao=self.situacao_normalizada,
            prazo_prometido=date(2026, 3, 1),
            reuniao=reuniao,
        )
        # `processo` cru (sem `.prazo_inicial` anotado) — o mesmo objeto
        # devolvido por `Processo.objects.create()`, como qualquer chamador
        # fora de `para_listagem()`.
        self.assertFalse(hasattr(processo, "prazo_inicial"))
        frase = frase_compromisso(acompanhamento, hoje=date(2026, 1, 15))
        self.assertIn("prazo inicial 01/02/2026", frase)

    def test_frase_sem_registro_cumprimento_nao_cita_reuniao(self):
        processo = self._criar_processo(58)
        acompanhamento = Acompanhamento.objects.create(
            processo=processo,
            referencia_data=date(2026, 1, 10),
            origem_hash="hash-58-1",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO,
            situacao=self.situacao_normalizada,
            prazo_prometido=date(2026, 1, 20),
            reuniao=None,
        )
        frase = frase_compromisso(acompanhamento)
        self.assertIn("em 10/01/2026", frase)
        self.assertIn("comprometeu-se a entregar até 20/01/2026", frase)
        self.assertIn("Situação: sem registro de cumprimento.", frase)
        self.assertNotIn("apurada pelo sistema", frase)
        self.assertNotIn("reunião", frase)


class TestCompromissoVigente(BlocosBaseTests):
    def test_none_quando_processo_sem_promessa(self):
        processo = self._criar_processo(59)
        self.assertIsNone(compromisso_vigente(processo))

    def test_devolve_o_mais_recente_por_referencia_data(self):
        processo = self._criar_processo(60)
        reuniao1 = _criar_reuniao(self.exercicio, date(2026, 1, 10))
        reuniao2 = _criar_reuniao(self.exercicio, date(2026, 2, 10))
        Acompanhamento.objects.create(
            processo=processo,
            referencia_data=date(2026, 1, 10),
            origem_hash="hash-60-1",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO,
            situacao=self.situacao_normalizada,
            prazo_prometido=date(2026, 1, 20),
            reuniao=reuniao1,
        )
        mais_recente = Acompanhamento.objects.create(
            processo=processo,
            referencia_data=date(2026, 2, 10),
            origem_hash="hash-60-2",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO,
            situacao=self.situacao_normalizada,
            prazo_prometido=date(2026, 3, 1),
            reuniao=reuniao2,
        )
        resultado = compromisso_vigente(processo, hoje=date(2026, 2, 15))
        self.assertEqual(resultado["acompanhamento"].pk, mais_recente.pk)
        self.assertEqual(resultado["codigo"], "em_aberto")
        self.assertIn("comprometeu-se a entregar até 01/03/2026", resultado["frase"])


class TestBlocoAdiados(BlocosBaseTests):
    def test_promessa_com_reuniao_no_periodo_aparece(self):
        processo = self._criar_processo(61)
        reuniao = _criar_reuniao(self.exercicio, date(2026, 1, 15))
        Acompanhamento.objects.create(
            processo=processo,
            referencia_data=date(2026, 1, 15),
            origem_hash="hash-61-1",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO,
            situacao=self.situacao_normalizada,
            prazo_prometido=date(2026, 3, 1),
            reuniao=reuniao,
        )
        resultado = _bloco_adiados(self.exercicio, date(2026, 1, 1), date(2026, 1, 31))
        self.assertIn(processo.pk, resultado)
        self.assertFalse(resultado[processo.pk]["automatico"])

    def test_usa_reuniao_data_nao_referencia_data(self):
        processo = self._criar_processo(62)
        reuniao = _criar_reuniao(self.exercicio, date(2026, 1, 15))
        Acompanhamento.objects.create(
            processo=processo,
            referencia_data=date(2026, 2, 20),  # divergente de propósito
            origem_hash="hash-62-1",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO,
            situacao=self.situacao_normalizada,
            prazo_prometido=date(2026, 3, 1),
            reuniao=reuniao,
        )
        resultado = _bloco_adiados(self.exercicio, date(2026, 1, 1), date(2026, 1, 31))
        self.assertIn(processo.pk, resultado)

    def test_promessa_com_reuniao_fora_do_periodo_nao_aparece(self):
        processo = self._criar_processo(63)
        reuniao = _criar_reuniao(self.exercicio, date(2026, 2, 15))
        Acompanhamento.objects.create(
            processo=processo,
            referencia_data=date(2026, 2, 15),
            origem_hash="hash-63-1",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO,
            situacao=self.situacao_normalizada,
            prazo_prometido=date(2026, 3, 1),
            reuniao=reuniao,
        )
        resultado = _bloco_adiados(self.exercicio, date(2026, 1, 1), date(2026, 1, 31))
        self.assertEqual(resultado, {})

    def test_promessa_sem_reuniao_nunca_entra(self):
        processo = self._criar_processo(64)
        Acompanhamento.objects.create(
            processo=processo,
            referencia_data=date(2026, 1, 15),
            origem_hash="hash-64-1",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO,
            situacao=self.situacao_normalizada,
            prazo_prometido=date(2026, 1, 20),
            reuniao=None,
        )
        resultado = _bloco_adiados(self.exercicio, date(2026, 1, 1), date(2026, 1, 31))
        self.assertEqual(resultado, {})

    def test_mais_de_uma_promessa_no_periodo_agrupa_no_mesmo_processo(self):
        processo = self._criar_processo(65)
        reuniao1 = _criar_reuniao(self.exercicio, date(2026, 1, 10))
        reuniao2 = _criar_reuniao(self.exercicio, date(2026, 1, 20))
        Acompanhamento.objects.create(
            processo=processo,
            referencia_data=date(2026, 1, 10),
            origem_hash="hash-65-1",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO,
            situacao=self.situacao_normalizada,
            prazo_prometido=date(2026, 2, 1),
            reuniao=reuniao1,
        )
        Acompanhamento.objects.create(
            processo=processo,
            referencia_data=date(2026, 1, 20),
            origem_hash="hash-65-2",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO,
            situacao=self.situacao_normalizada,
            prazo_prometido=date(2026, 2, 15),
            reuniao=reuniao2,
        )
        resultado = _bloco_adiados(self.exercicio, date(2026, 1, 1), date(2026, 1, 31))
        self.assertEqual(len(resultado[processo.pk]["frases"]), 2)
        # Mais recente primeiro.
        self.assertIn("15/02/2026", resultado[processo.pk]["frases"][0])

    def test_prazo_inicial_por_processo_usa_a_propria_primeira_promessa(self):
        """A anotação em lote `prazo_inicial_processo` respeita cada
        processo separadamente: dois processos sem `prazo_entrega`, cada
        um com sua própria promessa inicial distinta, não podem
        compartilhar/misturar prazo inicial."""
        reuniao = _criar_reuniao(self.exercicio, date(2026, 1, 15))
        processo_a = self._criar_processo(66)
        processo_b = self._criar_processo(67)
        Acompanhamento.objects.create(
            processo=processo_a,
            referencia_data=date(2026, 1, 15),
            origem_hash="hash-66-1",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO,
            situacao=self.situacao_normalizada,
            prazo_prometido=date(2026, 4, 1),
            reuniao=reuniao,
        )
        Acompanhamento.objects.create(
            processo=processo_b,
            referencia_data=date(2026, 1, 15),
            origem_hash="hash-67-1",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO,
            situacao=self.situacao_normalizada,
            prazo_prometido=date(2026, 5, 1),
            reuniao=reuniao,
        )
        resultado = _bloco_adiados(self.exercicio, date(2026, 1, 1), date(2026, 1, 31))
        self.assertIn("prazo inicial 01/04/2026", resultado[processo_a.pk]["frases"][0])
        self.assertIn("prazo inicial 01/05/2026", resultado[processo_b.pk]["frases"][0])


# ---------------------------------------------------------------------------
# Bloco Alterações e orquestração montar_relatorio
# ---------------------------------------------------------------------------


class TestBlocoAlteracoes(BlocosBaseTests):
    def test_processo_so_mudou_valor_estimado_aparece_em_alteracoes(self):
        processo = self._criar_processo_datado(
            70, date(2025, 12, 1), valor_estimado=Decimal("100.00")
        )
        processo._history_date = _aware(date(2026, 1, 5))
        processo._history_user = self.usuario
        processo.valor_estimado = Decimal("500.00")
        processo.save()

        resultado = _bloco_alteracoes(
            self.exercicio, date(2026, 1, 1), date(2026, 1, 31), mapas_fk={}
        )
        self.assertIn(processo.pk, resultado)
        self.assertIn("valor estimado", resultado[processo.pk]["frases"][0])

    def test_situacao_para_concluido_nao_entra_em_alteracoes(self):
        processo = self._criar_processo_datado(
            71, date(2025, 12, 1), situacao=Situacao.EM_TRAMITACAO
        )
        processo._history_date = _aware(date(2026, 1, 10))
        processo._history_user = self.usuario
        processo.situacao = Situacao.CONCLUIDO
        processo.save()

        resultado = _bloco_alteracoes(
            self.exercicio, date(2026, 1, 1), date(2026, 1, 31), mapas_fk={}
        )
        self.assertEqual(resultado, {})

    def test_trilha_com_mais_de_uma_mudanca_no_periodo(self):
        processo = self._criar_processo_datado(72, date(2025, 12, 1), mes_previsto=8)
        processo._history_date = _aware(date(2026, 1, 5))
        processo._history_user = self.usuario
        processo.mes_previsto = 9
        processo.save()
        processo._history_date = _aware(date(2026, 1, 20))
        processo._history_user = self.usuario
        processo.mes_previsto = 10
        processo.save()

        resultado = _bloco_alteracoes(
            self.exercicio, date(2026, 1, 1), date(2026, 1, 31), mapas_fk={}
        )
        frase = resultado[processo.pk]["frases"][0]
        self.assertIn("mês previsto alterado de Agosto para Outubro em 20/01/2026", frase)
        self.assertIn("(ago → set em 05/01; set → out em 20/01)", frase)


class TestMontarRelatorio(BlocosBaseTests):
    def test_periodo_sem_movimentacao_seis_blocos_vazios(self):
        self._criar_processo(80, data_inclusao_pca=date(2025, 1, 1))
        relatorio = montar_relatorio(
            exercicio=self.exercicio,
            de=date(2026, 6, 1),
            ate=date(2026, 6, 30),
            usuario=self.usuario,
        )
        self.assertEqual(len(relatorio.blocos), 6)
        self.assertEqual([b.chave for b in relatorio.blocos], list(ORDEM_EXIBICAO_BLOCOS))
        for bloco in relatorio.blocos:
            self.assertEqual(bloco.contagem, 0)
            self.assertEqual(bloco.itens, [])
            self.assertEqual(bloco.mensagem_vazio, "Nenhum item neste período.")
        self.assertEqual(relatorio.gerado_por, self.usuario.email)

    def test_um_item_um_bloco_concluido_e_alterado_aparece_so_em_concluidos(self):
        processo = self._criar_processo_datado(
            81,
            date(2025, 12, 1),
            situacao=Situacao.EM_TRAMITACAO,
            valor_estimado=Decimal("1000.00"),
        )
        processo._history_date = _aware(date(2026, 1, 10))
        processo._history_user = self.usuario
        processo.situacao = Situacao.CONCLUIDO
        processo.valor_estimado = Decimal("2000.00")
        processo.save()

        relatorio = montar_relatorio(
            exercicio=self.exercicio,
            de=date(2026, 1, 1),
            ate=date(2026, 1, 31),
            usuario=self.usuario,
        )
        blocos = {bloco.chave: bloco for bloco in relatorio.blocos}
        self.assertEqual(blocos["concluidos"].contagem, 1)
        self.assertEqual(blocos["alteracoes"].contagem, 0)
        item = blocos["concluidos"].itens[0]
        self.assertEqual(item.processo.pk, processo.pk)
        self.assertTrue(any("valor estimado" in frase for frase in item.frases_extra))

    def test_soma_valor_so_em_inclusoes_exclusoes_concluidos(self):
        self._criar_processo(
            82, data_inclusao_pca=date(2026, 1, 15), valor_estimado=Decimal("3000.00")
        )
        relatorio = montar_relatorio(
            exercicio=self.exercicio,
            de=date(2026, 1, 1),
            ate=date(2026, 1, 31),
            usuario=self.usuario,
        )
        blocos = {bloco.chave: bloco for bloco in relatorio.blocos}
        self.assertEqual(blocos["inclusoes"].soma_valor, Decimal("3000.00"))
        for chave in ("iniciados", "adiados", "alteracoes"):
            self.assertIsNone(blocos[chave].soma_valor)

    def test_bloco_alteracoes_orcamento_de_queries_independe_do_numero_de_processos(self):
        """Substitui um teste anterior, `test_desempenho_500_
        processos_abaixo_de_3s`.

        O teste anterior usava `Processo.objects.bulk_create`, que NÃO
        dispara os sinais `post_save` do `django-simple-history`: os 500
        processos nasciam sem NENHUMA linha de history, então o teste
        cronometrava 500 consultas VAZIAS e passava mesmo com
        `_bloco_alteracoes` fazendo uma query de history por processo (o
        N+1 real, medido em produção como 154 processos → 155 queries).
        Um teste que só mede segundos não prova nada — máquina rápida
        esconde N+1.

        Este teste cria history REAL (`.save()`, nunca `bulk_create`) em
        duas escalas — 10 processos, depois mais 40 (total 50) — e trava o
        número de queries de `montar_relatorio` entre as duas rodadas: se
        `_bloco_alteracoes` voltar a consultar processo a processo, o
        número sobe com a contagem de processos e o teste quebra. A
        duração continua medida como sinal auxiliar, não como única prova.
        """

        def _criar_processos_com_history(quantidade, item_pca_inicial):
            for indice in range(quantidade):
                item_pca = item_pca_inicial + indice
                processo = self._criar_processo_datado(
                    item_pca,
                    date(2025, 6, 1),
                    valor_estimado=Decimal("1000.00"),
                )
                # Segunda linha de history, dentro do período do relatório
                # (2026-01-01..2026-01-31) — o padrão que o N+1 original
                # media: 1 query de history por processo, sem filtro de
                # data no SQL.
                processo._history_date = _aware(date(2026, 1, 15))
                processo._history_user = self.usuario
                processo.valor_estimado = Decimal("2000.00")
                processo.save()

        _criar_processos_com_history(10, item_pca_inicial=9000)
        with CaptureQueriesContext(connection) as primeira:
            relatorio_primeira = montar_relatorio(
                exercicio=self.exercicio,
                de=date(2026, 1, 1),
                ate=date(2026, 1, 31),
                usuario=self.usuario,
            )

        _criar_processos_com_history(40, item_pca_inicial=9010)
        inicio = tempo_parede.perf_counter()
        with CaptureQueriesContext(connection) as segunda:
            relatorio_segunda = montar_relatorio(
                exercicio=self.exercicio,
                de=date(2026, 1, 1),
                ate=date(2026, 1, 31),
                usuario=self.usuario,
            )
        duracao = tempo_parede.perf_counter() - inicio

        self.assertEqual(
            len(primeira.captured_queries),
            len(segunda.captured_queries),
            "número de queries de montar_relatorio variou com a contagem de "
            "processos (10 -> 50) — sinal de N+1 em _bloco_alteracoes/"
            "mudancas_no_periodo.",
        )
        self.assertLess(duracao, 3.0)
        self.assertEqual(len(relatorio_primeira.blocos), 6)
        self.assertEqual(len(relatorio_segunda.blocos), 6)
        blocos_segunda = {b.chave: b for b in relatorio_segunda.blocos}
        self.assertEqual(blocos_segunda["alteracoes"].contagem, 50)
