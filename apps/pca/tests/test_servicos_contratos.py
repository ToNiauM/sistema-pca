"""Testes do serviço `apps.pca.servicos.contratos` (Fase 38). `django.test.TestCase`, fixture 100% `bulk_create`/`create` direto
no ORM (sem `importar_pca`), mesmo padrão de `test_desempenho_fase28.py`.

Reproduz M07 (`melhorias.md`) na população do serviço, prova cada filtro da
seção §4, a paridade `Case/When` × `virada.destino()` (C07) e o orçamento
de consultas constante entre 50 e 500 itens (C09).
"""

from collections import Counter
from datetime import date, timedelta

from django.core.paginator import Paginator
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection

from apps.catalogo.models import Categoria, Exercicio, Tipo, Unidade
from apps.pca.models import Estado, Processo, RegimeExecucao, Situacao
from apps.pca.projecao import virada
from apps.pca.projecao.virada import CHAVES_DESTINO, Destino, GRUPOS_DESTINO
from apps.pca.servicos.contratos import (
    RENOVACAO_OPCOES,
    VENCE_OPCOES,
    anotar_destino,
    aplicar_destino,
    aplicar_renovacao,
    aplicar_vence,
    contratos_a_vencer,
    kpis,
    populacao,
)

HOJE = date(2026, 9, 19)


class _BaseCatalogo(TestCase):
    """Catálogo mínimo compartilhado — uma UO, um `Tipo`/`Categoria` por
    classe filha via `setUpTestData` própria (cada subclasse chama
    `_popular_catalogo` para não colidir com `nome_normalizado`, único por
    tabela de vocabulário)."""

    _contador_item_pca = 0

    @classmethod
    def _popular_catalogo(cls, sufixo):
        cls.exercicio = Exercicio.objects.get(ano=2026)
        cls.uo = Unidade.objects.create(nome=f"Unidade {sufixo}")
        cls.uo2 = Unidade.objects.create(nome=f"Unidade {sufixo} B")
        cls.tipo = Tipo.objects.create(nome=f"Tipo {sufixo}")
        cls.tipo_vigente = Tipo.objects.create(nome=f"Vigente {sufixo}")
        cls.categoria = Categoria.objects.create(nome=f"Categoria {sufixo}")

    def _criar_item(self, **overrides):
        type(self)._contador_item_pca += 1
        campos = dict(
            item_pca=type(self)._contador_item_pca,
            exercicio=self.exercicio,
            descricao_objeto="Item de teste",
            tipo=self.tipo,
            categoria=self.categoria,
            unidade_organizacional=self.uo,
            estado=Estado.ATIVO,
            situacao=Situacao.NO_PRAZO,
            regime_execucao=RegimeExecucao.CONTINUADO,
            renovacao_prevista=True,
        )
        campos.update(overrides)
        return Processo.objects.create(**campos)


class TestPopulacaoItensComContrato(_BaseCatalogo):
    """M07 — a população reproduz e corrige M07."""

    @classmethod
    def setUpTestData(cls):
        cls._popular_catalogo("Populacao")

    def test_m07_item_vigente_concluido_continuado_aparece(self):
        item_a = self._criar_item(
            tipo=self.tipo_vigente,
            situacao=Situacao.CONCLUIDO,
            regime_execucao=RegimeExecucao.CONTINUADO,
            vigencia_fim=date(2026, 12, 31),
            renovacao_prevista=True,
        )
        item_b = self._criar_item(
            regime_execucao=RegimeExecucao.UNICO,
            vigencia_fim=date(2026, 12, 31),
        )
        item_c = self._criar_item(
            estado=Estado.CANCELADO,
            vigencia_fim=date(2026, 12, 31),
        )
        item_d = self._criar_item(vigencia_fim=None)
        item_e = self._criar_item(
            regime_execucao=None,
            situacao=Situacao.NO_PRAZO,
            vigencia_fim=date(2027, 6, 30),
            renovacao_prevista=False,
        )
        item_f = self._criar_item(
            vigencia_fim=HOJE - timedelta(days=10),
            renovacao_prevista=True,
            situacao=Situacao.ATRASADO,
        )

        ids = set(populacao(self.exercicio, []).values_list("pk", flat=True))

        self.assertIn(item_a.pk, ids)
        self.assertIn(item_e.pk, ids)
        self.assertIn(item_f.pk, ids)
        self.assertNotIn(item_b.pk, ids)
        self.assertNotIn(item_c.pk, ids)
        self.assertNotIn(item_d.pk, ids)

    def test_populacao_filtrada_por_uo(self):
        item_a = self._criar_item(
            unidade_organizacional=self.uo, vigencia_fim=date(2026, 12, 31)
        )
        self._criar_item(
            unidade_organizacional=self.uo2, vigencia_fim=date(2026, 12, 31)
        )

        ids = set(
            populacao(self.exercicio, [self.uo.pk]).values_list("pk", flat=True)
        )
        self.assertEqual(ids, {item_a.pk})

    def test_populacao_nao_herda_filtros_legados(self):
        """C05 — item `concluido` não some porque o serviço não recebe
        `request` nem passa por `queryset_filtrado`."""
        item_a = self._criar_item(
            situacao=Situacao.CONCLUIDO, vigencia_fim=date(2026, 12, 31)
        )
        resultado = contratos_a_vencer(self.exercicio, hoje=HOJE)
        ids = set(resultado.queryset.values_list("pk", flat=True))
        self.assertIn(item_a.pk, ids)

    def test_populacao_sem_exercicio_e_estado_vazio_seguro(self):
        resultado = contratos_a_vencer(None, hoje=HOJE)
        self.assertEqual(list(resultado.queryset), [])
        self.assertEqual(resultado.kpis["total"], 0)
        self.assertIsNone(resultado.exercicio_ano)


class TestOrdenacao(_BaseCatalogo):
    @classmethod
    def setUpTestData(cls):
        cls._popular_catalogo("Ordenacao")

    def test_vencidos_primeiro_mais_antigo_depois_vigencia_fim_crescente(self):
        recente_vencido = self._criar_item(
            vigencia_fim=HOJE - timedelta(days=1)
        )
        antigo_vencido = self._criar_item(
            vigencia_fim=HOJE - timedelta(days=30)
        )
        futuro_proximo = self._criar_item(
            vigencia_fim=HOJE + timedelta(days=10)
        )
        futuro_distante = self._criar_item(
            vigencia_fim=HOJE + timedelta(days=100)
        )

        ordem = list(
            populacao(self.exercicio, []).values_list("pk", flat=True)
        )
        self.assertEqual(
            ordem,
            [
                antigo_vencido.pk,
                recente_vencido.pk,
                futuro_proximo.pk,
                futuro_distante.pk,
            ],
        )

    def test_desempate_por_item_pca_na_mesma_vigencia_fim(self):
        mesma_vigencia = date(2026, 12, 31)
        item_maior = self._criar_item(vigencia_fim=mesma_vigencia)
        item_menor = self._criar_item(vigencia_fim=mesma_vigencia)
        # Garante item_pca crescente na ordem de criação (contador global).
        self.assertLess(item_maior.item_pca, item_menor.item_pca)

        ordem = list(
            populacao(self.exercicio, [])
            .filter(vigencia_fim=mesma_vigencia)
            .values_list("pk", flat=True)
        )
        self.assertEqual(ordem, [item_maior.pk, item_menor.pk])


class TestFiltroVence(_BaseCatalogo):
    @classmethod
    def setUpTestData(cls):
        cls._popular_catalogo("Vence")

    def test_allowlist_vence(self):
        self.assertEqual(
            VENCE_OPCOES,
            ("todos", "vencidos", "90", "180", "365", "N", "N+1"),
        )

    def test_vencidos_so_vigencia_fim_menor_que_hoje(self):
        vencido = self._criar_item(vigencia_fim=HOJE - timedelta(days=1))
        no_dia = self._criar_item(vigencia_fim=HOJE)
        qs = aplicar_vence(populacao(self.exercicio, []), "vencidos", 2026, HOJE)
        ids = set(qs.values_list("pk", flat=True))
        self.assertIn(vencido.pk, ids)
        self.assertNotIn(no_dia.pk, ids)

    def test_horizonte_90_inclusivo_nas_duas_pontas(self):
        no_dia = self._criar_item(vigencia_fim=HOJE)
        no_limite = self._criar_item(vigencia_fim=HOJE + timedelta(days=90))
        fora = self._criar_item(vigencia_fim=HOJE + timedelta(days=91))
        vencido = self._criar_item(vigencia_fim=HOJE - timedelta(days=1))

        qs = aplicar_vence(populacao(self.exercicio, []), "90", 2026, HOJE)
        ids = set(qs.values_list("pk", flat=True))
        self.assertIn(no_dia.pk, ids)
        self.assertIn(no_limite.pk, ids)
        self.assertNotIn(fora.pk, ids)
        self.assertNotIn(vencido.pk, ids)

    def test_horizonte_180_e_365_inclusivos(self):
        limite_180 = self._criar_item(vigencia_fim=HOJE + timedelta(days=180))
        fora_180 = self._criar_item(vigencia_fim=HOJE + timedelta(days=181))
        limite_365 = self._criar_item(vigencia_fim=HOJE + timedelta(days=365))
        fora_365 = self._criar_item(vigencia_fim=HOJE + timedelta(days=366))

        ids_180 = set(
            aplicar_vence(populacao(self.exercicio, []), "180", 2026, HOJE)
            .values_list("pk", flat=True)
        )
        self.assertIn(limite_180.pk, ids_180)
        self.assertNotIn(fora_180.pk, ids_180)

        ids_365 = set(
            aplicar_vence(populacao(self.exercicio, []), "365", 2026, HOJE)
            .values_list("pk", flat=True)
        )
        self.assertIn(limite_365.pk, ids_365)
        self.assertNotIn(fora_365.pk, ids_365)

    def test_horizonte_n_ate_31_12_n_sem_limite_inferior(self):
        vencido = self._criar_item(vigencia_fim=HOJE - timedelta(days=400))
        no_limite_n = self._criar_item(vigencia_fim=date(2026, 12, 31))
        fora_n = self._criar_item(vigencia_fim=date(2027, 1, 1))

        ids = set(
            aplicar_vence(populacao(self.exercicio, []), "N", 2026, HOJE)
            .values_list("pk", flat=True)
        )
        self.assertIn(vencido.pk, ids, "vencidos ENTRAM em N — sem limite inferior")
        self.assertIn(no_limite_n.pk, ids)
        self.assertNotIn(fora_n.pk, ids)

    def test_horizonte_n1_ate_31_12_n1(self):
        no_limite_n1 = self._criar_item(vigencia_fim=date(2027, 12, 31))
        fora_n1 = self._criar_item(vigencia_fim=date(2028, 1, 1))

        ids = set(
            aplicar_vence(populacao(self.exercicio, []), "N+1", 2026, HOJE)
            .values_list("pk", flat=True)
        )
        self.assertIn(no_limite_n1.pk, ids)
        self.assertNotIn(fora_n1.pk, ids)

    def test_todos_e_valor_invalido_nao_filtram(self):
        item = self._criar_item(vigencia_fim=HOJE + timedelta(days=1000))
        ids_todos = set(
            aplicar_vence(populacao(self.exercicio, []), "todos", 2026, HOJE)
            .values_list("pk", flat=True)
        )
        ids_invalido = set(
            aplicar_vence(populacao(self.exercicio, []), "inexistente", 2026, HOJE)
            .values_list("pk", flat=True)
        )
        self.assertIn(item.pk, ids_todos)
        self.assertIn(item.pk, ids_invalido)


class TestFiltroRenovacaoEDestino(_BaseCatalogo):
    @classmethod
    def setUpTestData(cls):
        cls._popular_catalogo("RenovacaoDestino")

    def test_allowlist_renovacao(self):
        self.assertEqual(RENOVACAO_OPCOES, ("todas", "sim", "nao"))

    def test_renovacao_sim_e_nao(self):
        sim = self._criar_item(
            renovacao_prevista=True, vigencia_fim=date(2026, 12, 31)
        )
        nao = self._criar_item(
            renovacao_prevista=False, vigencia_fim=date(2026, 12, 31)
        )

        ids_sim = set(
            aplicar_renovacao(populacao(self.exercicio, []), "sim")
            .values_list("pk", flat=True)
        )
        ids_nao = set(
            aplicar_renovacao(populacao(self.exercicio, []), "nao")
            .values_list("pk", flat=True)
        )
        ids_todas = set(
            aplicar_renovacao(populacao(self.exercicio, []), "todas")
            .values_list("pk", flat=True)
        )
        self.assertEqual(ids_sim, {sim.pk})
        self.assertEqual(ids_nao, {nao.pk})
        self.assertEqual(ids_todas, {sim.pk, nao.pk})

    def test_destino_filtra_so_a_chave_pedida(self):
        vencido = self._criar_item(vigencia_fim=HOJE - timedelta(days=1))
        vigente = self._criar_item(vigencia_fim=date(2029, 1, 1))

        base = anotar_destino(populacao(self.exercicio, []), 2026, HOJE)
        qs = aplicar_destino(base, "vencido", None)
        ids = set(qs.values_list("pk", flat=True))
        self.assertEqual(ids, {vencido.pk})

    def test_grupo_destino_vigente_n1_e_uniao(self):
        encerra_n1 = self._criar_item(
            vigencia_fim=date(2027, 6, 30), renovacao_prevista=False
        )
        vigente_n1 = self._criar_item(
            vigencia_fim=date(2028, 6, 30), renovacao_prevista=True
        )

        base = anotar_destino(populacao(self.exercicio, []), 2026, HOJE)
        qs = aplicar_destino(base, None, "vigente_n1")
        ids = set(qs.values_list("pk", flat=True))
        self.assertEqual(ids, {encerra_n1.pk, vigente_n1.pk})

    def test_destino_prevalece_sobre_grupo_destino(self):
        vencido = self._criar_item(vigencia_fim=HOJE - timedelta(days=1))
        vigente_n1 = self._criar_item(vigencia_fim=date(2028, 6, 30))

        base = anotar_destino(populacao(self.exercicio, []), 2026, HOJE)
        qs = aplicar_destino(base, "vencido", "vigente_n1")
        ids = set(qs.values_list("pk", flat=True))
        self.assertEqual(ids, {vencido.pk})

    def test_chave_invalida_nao_filtra(self):
        item = self._criar_item(vigencia_fim=date(2026, 12, 31))
        base = anotar_destino(populacao(self.exercicio, []), 2026, HOJE)
        qs = aplicar_destino(base, "chave-invalida", "grupo-invalido")
        ids = set(qs.values_list("pk", flat=True))
        self.assertIn(item.pk, ids)


class TestKpisInvariante(_BaseCatalogo):
    @classmethod
    def setUpTestData(cls):
        cls._popular_catalogo("Kpis")

    def test_total_e_soma_das_quatro_categorias(self):
        self._criar_item(vigencia_fim=HOJE - timedelta(days=1))  # vencido
        self._criar_item(
            vigencia_fim=date(2026, 12, 31), renovacao_prevista=False
        )  # encerra_n
        self._criar_item(
            vigencia_fim=date(2026, 12, 31), renovacao_prevista=True
        )  # renova_n
        self._criar_item(
            vigencia_fim=date(2027, 6, 30), renovacao_prevista=True
        )  # renovacao_n1
        self._criar_item(
            vigencia_fim=date(2027, 6, 30), renovacao_prevista=False
        )  # encerra_n1
        self._criar_item(vigencia_fim=date(2029, 1, 1))  # vigente_n1

        resultado = contratos_a_vencer(self.exercicio, hoje=HOJE)
        k = resultado.kpis
        self.assertEqual(
            k["total"],
            k["encerramento_n"] + k["renovacao_n"] + k["renovacao_n1"] + k["vigente_n1"],
        )

    def test_soma_valor_mensal_e_sem_valor_mensal(self):
        self._criar_item(vigencia_fim=date(2026, 12, 31), valor_mensal=100)
        self._criar_item(vigencia_fim=date(2026, 12, 31), valor_mensal=250)
        self._criar_item(vigencia_fim=date(2026, 12, 31), valor_mensal=None)

        resultado = contratos_a_vencer(self.exercicio, hoje=HOJE)
        self.assertEqual(resultado.kpis["soma_valor_mensal"], 350)
        self.assertEqual(resultado.kpis["sem_valor_mensal"], 1)

    def test_kpis_nao_mudam_so_com_destino_ou_grupo_destino(self):
        self._criar_item(vigencia_fim=HOJE - timedelta(days=1))
        self._criar_item(vigencia_fim=date(2026, 12, 31))

        sem_filtro = contratos_a_vencer(self.exercicio, hoje=HOJE)
        com_destino = contratos_a_vencer(
            self.exercicio, destino="vencido", hoje=HOJE
        )
        self.assertEqual(sem_filtro.kpis, com_destino.kpis)


class TestParidadeCaseWhenVsRegraPura(_BaseCatalogo):
    """C07, `Case/When` e `virada.destino()` concordam em todas
    as fronteiras, para N=2026 (exercício da população), N=2027 (futuro) e
    N=2025 (passado) — `anotar_destino` é chamado diretamente com cada
    `exercicio_ano`, mantendo a mesma população (exercicio FK=2026,
    a classificação usa `exercicio_ano` explícito, dissociado do FK de
    filtro)."""

    @classmethod
    def setUpTestData(cls):
        cls._popular_catalogo("Paridade")

    def _fixture_paridade(self):
        datas = [
            date(2025, 3, 1),  # < hoje, vencido
            HOJE - timedelta(days=1),
            HOJE,
            HOJE + timedelta(days=1),
            date(2026, 12, 31),
            date(2027, 1, 1),
            date(2027, 12, 31),
            date(2028, 1, 1),
            date(2029, 6, 15),
        ]
        for data in datas:
            for renovacao_prevista in (True, False):
                self._criar_item(
                    vigencia_fim=data, renovacao_prevista=renovacao_prevista
                )

    def _checar_paridade(self, exercicio_ano):
        qs = anotar_destino(populacao(self.exercicio, []), exercicio_ano, HOJE)
        linhas = list(qs)

        contagem_pura = Counter(
            virada.destino(
                p.vigencia_fim, p.renovacao_prevista, exercicio_ano, HOJE
            )
            for p in linhas
        )
        agregados = kpis(qs)
        for d in Destino:
            self.assertEqual(
                contagem_pura.get(d, 0),
                agregados["por_destino"][d.chave],
                f"paridade quebrada em {d.chave} (N={exercicio_ano})",
            )

        for p in linhas:
            esperado = virada.destino(
                p.vigencia_fim, p.renovacao_prevista, exercicio_ano, HOJE
            )
            self.assertEqual(
                esperado.chave,
                p.destino,
                f"paridade por linha quebrada em item_pca={p.item_pca}",
            )

    def test_paridade_exercicio_atual(self):
        self._fixture_paridade()
        self._checar_paridade(2026)

    def test_paridade_exercicio_futuro(self):
        self._fixture_paridade()
        self._checar_paridade(2027)

    def test_paridade_exercicio_passado(self):
        self._fixture_paridade()
        self._checar_paridade(2025)


class TestOrcamentoConsultasConstante(_BaseCatalogo):
    """C09 — o serviço isolado faz o MESMO número de consultas com
    50 e com 500 itens."""

    QUERIES_ESPERADAS = 4

    @classmethod
    def setUpTestData(cls):
        cls._popular_catalogo("Orcamento")

    def _criar_volume(self, quantidade):
        itens = []
        for i in range(quantidade):
            deslocamento = -400 + (i * (1300 // max(quantidade, 1)))
            itens.append(
                Processo(
                    item_pca=1000 + i,
                    exercicio=self.exercicio,
                    descricao_objeto=f"Item de volume {i}",
                    tipo=self.tipo,
                    categoria=self.categoria,
                    unidade_organizacional=self.uo,
                    estado=Estado.ATIVO,
                    situacao=Situacao.NO_PRAZO,
                    regime_execucao=RegimeExecucao.CONTINUADO,
                    renovacao_prevista=bool(i % 2),
                    vigencia_fim=HOJE + timedelta(days=deslocamento),
                    valor_mensal=None if i % 5 == 0 else 100 + i,
                )
            )
        Processo.objects.bulk_create(itens)

    def _medir(self, quantidade):
        Processo.objects.filter(item_pca__gte=1000).delete()
        self._criar_volume(quantidade)
        with CaptureQueriesContext(connection) as captura:
            resultado = contratos_a_vencer(self.exercicio, hoje=HOJE)
            lista = list(Paginator(resultado.queryset, 20).page(1).object_list)
            resultado.queryset.count()
            resultado.kpis
        return len(captura.captured_queries)

    def test_orcamento_de_consultas_constante_entre_50_e_500(self):
        consultas_50 = self._medir(50)
        consultas_500 = self._medir(500)
        self.assertEqual(consultas_50, consultas_500)
        self.assertEqual(consultas_50, self.QUERIES_ESPERADAS)
