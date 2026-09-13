"""Contrato de dados dos 12 KPIs (Bloco A/Bloco B) + gauge de
`apps.pca.kpis.calcular_blocos_kpi`, testado direto contra a função de
domínio (`RequestFactory`, nunca `self.client`/uma rota HTTP).

Esta classe não depende de nenhuma rota — só de `calcular_blocos_kpi`,
que `kpis.py` continua expondo, consumida por `core:inicio`."""

from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.conf import settings
from django.core.management import call_command
from django.test import RequestFactory, TransactionTestCase
from django.utils.timezone import localdate

from apps.catalogo.models import Categoria, Exercicio, Tipo, Unidade
from apps.pca.filtros import querystring_filtros, queryset_filtrado
from apps.pca.kpis import calcular_blocos_kpi
from apps.pca.models import Estado, Processo, Situacao

ARQUIVO_REAL = "apps/pca/fixtures/modelo-controle-exemplo.xlsx"


class TestBlocoAnaliticoDados(TransactionTestCase):
    """Contrato de dados dos 12 KPIs + gauge do header analítico,
    testado direto contra `apps.pca.kpis.calcular_blocos_kpi` (um único
    módulo de domínio, a UI só itera).

    Mesmo padrão TransactionTestCase + import real das demais classes
    deste arquivo — nunca lê banco de desenvolvimento. `RequestFactory`
    (não `self.client`) porque o alvo é a função de domínio, não uma
    rota HTTP."""

    serialized_rollback = True

    def setUp(self):
        call_command(
            "importar_pca",
            ARQUIVO_REAL,
            "--usuario=importador@pca.local",
            "--exercicio=2026",
            stdout=StringIO(),
        )
        self.factory = RequestFactory()

    def _blocos(self, **params):
        request = self.factory.get("/", params)
        qs = queryset_filtrado(request)
        return calcular_blocos_kpi(
            qs,
            request.GET,
            dias_proximo_vencimento=settings.PCA_DIAS_PROXIMOS_VENCIMENTO,
        )

    def _qs(self, **params):
        return queryset_filtrado(self.factory.get("/", params))

    def test_titulo_proximos_do_vencimento_usa_prazo_atual(self):
        # O texto de proximidade do KPI "PRÓXIMOS DO VENCIMENTO" usa
        # "prazo atual" (vocabulário fechado); vigência contratual
        # (`vigencia_*`) não é rótulo de prazo e não é tocada por esta
        # varredura.
        _bloco_a, bloco_b, _gauge = self._blocos()
        self.assertIn("prazo atual", bloco_b["proximos_vencimento"]["titulo"])
        self.assertNotIn("prazo vigente", bloco_b["proximos_vencimento"]["titulo"])

    # --- aritmética -------------------------------------------------------

    def test_ativos_e_soma_por_natureza_fecham_a_aritmetica(self):
        bloco_a, bloco_b, gauge = self._blocos()
        self.assertEqual(
            bloco_a["ativos"]["contagem"],
            bloco_a["total"]["contagem"] - bloco_a["cancelados"]["contagem"],
        )
        self.assertEqual(
            bloco_a["nova"]["contagem"]
            + bloco_a["renovacao"]["contagem"]
            + bloco_a["vigentes"]["contagem"],
            bloco_a["ativos"]["contagem"],
        )

    # --- Meta Exercício = Ativos - Vigentes ---------------------------------

    def test_meta_exercicio_e_ativos_menos_vigentes_com_drilldown_de_elegiveis(self):
        bloco_a, bloco_b, gauge = self._blocos()
        self.assertEqual(
            bloco_a["meta_exercicio"]["contagem"],
            bloco_a["ativos"]["contagem"] - bloco_a["vigentes"]["contagem"],
        )
        self.assertEqual(
            bloco_a["meta_exercicio"]["contagem"],
            bloco_a["nova"]["contagem"] + bloco_a["renovacao"]["contagem"],
        )

        request = self.factory.get("/")
        id_nova = Tipo.objects.get(nome_normalizado="nova contratacao").id
        id_renovacao = Tipo.objects.get(nome_normalizado="renovacao").id
        href_esperado = querystring_filtros(
            request.GET,
            estado=[Estado.ATIVO.value],
            tipo=[id_nova, id_renovacao],
        )
        self.assertEqual(bloco_a["meta_exercicio"]["href"], href_esperado)

    # --- denominadores -----------------------------------------------------

    def test_cada_grupo_de_cards_usa_o_denominador_correto(self):
        bloco_a, bloco_b, gauge = self._blocos()
        total = bloco_a["total"]["contagem"]
        ativos = bloco_a["ativos"]["contagem"]
        elegivel = bloco_a["nova"]["contagem"] + bloco_a["renovacao"]["contagem"]

        for chave in ("cancelados", "ativos"):
            with self.subTest(chave=chave):
                self.assertAlmostEqual(
                    float(bloco_a[chave]["percentual"]),
                    bloco_a[chave]["contagem"] / total * 100,
                    places=6,
                )
        for chave in ("nova", "renovacao", "vigentes"):
            with self.subTest(chave=chave):
                self.assertAlmostEqual(
                    float(bloco_a[chave]["percentual"]),
                    bloco_a[chave]["contagem"] / ativos * 100,
                    places=6,
                )
        for chave in ("no_prazo", "atrasados", "em_tramitacao"):
            with self.subTest(chave=chave):
                self.assertAlmostEqual(
                    float(bloco_b[chave]["percentual"]),
                    bloco_b[chave]["contagem"] / elegivel * 100,
                    places=6,
                )
        for chave in ("proximos_vencimento", "sobrestados"):
            with self.subTest(chave=chave):
                self.assertAlmostEqual(
                    float(bloco_b[chave]["percentual"]),
                    bloco_b[chave]["contagem"] / ativos * 100,
                    places=6,
                )

        # Quick 260831-vyr — CONCLUÍDO é o único card cujo percentual usa
        # uma base DIFERENTE da contagem bruta exibida: exclui Vigentes do
        # numerador E do denominador.
        id_vigente = Tipo.objects.get(nome_normalizado="vigente").id
        qs = self._qs()
        concluido_vigente = qs.filter(
            estado=Estado.ATIVO,
            situacao_efetiva=Situacao.CONCLUIDO,
            tipo_id=id_vigente,
        ).count()
        ativos_sem_vigente = ativos - bloco_a["vigentes"]["contagem"]
        concluido_sem_vigente = bloco_b["concluido"]["contagem"] - concluido_vigente
        self.assertAlmostEqual(
            float(bloco_b["concluido"]["percentual"]),
            concluido_sem_vigente / ativos_sem_vigente * 100,
            places=6,
        )

    # --- Teste 3 (zero-safe) --------------------------------------------

    def test_percentual_e_none_quando_o_denominador_de_elegiveis_zera(self):
        # `?tipo=<Vigente>` isola só processos Vigentes: nova+renovacao (o
        # denominador de NO PRAZO/ATRASADOS/EM TRAMITAÇÃO) zera no recorte,
        # nunca 0% nem ZeroDivisionError.
        id_vigente = Tipo.objects.get(nome_normalizado="vigente").id
        bloco_a, bloco_b, gauge = self._blocos(tipo=id_vigente)
        self.assertEqual(
            bloco_a["nova"]["contagem"] + bloco_a["renovacao"]["contagem"], 0
        )
        for chave in ("no_prazo", "atrasados", "em_tramitacao"):
            with self.subTest(chave=chave):
                self.assertIsNone(bloco_b[chave]["percentual"])
                self.assertEqual(bloco_b[chave]["contagem"], 0)

        # Quick 260831-vyr — recorte só de Vigentes zera `ativos_sem_vigente`
        # (base do percentual de CONCLUÍDO/gauge), nunca ZeroDivisionError.
        self.assertIsNone(bloco_b["concluido"]["percentual"])
        self.assertEqual(gauge["concluidos"], 0)
        self.assertEqual(gauge["ativos"], 0)

    # --- selo de inconsistência ---------------------------------------------

    def test_tipo_sintetico_fora_da_particao_gera_selo_de_inconsistencia(self):
        tipo_extra = Tipo.objects.create(nome="Tipo sintético fora da partição")
        exercicio = Exercicio.objects.get(ano=2026)
        Processo.objects.create(
            item_pca=9001,
            exercicio=exercicio,
            descricao_objeto="Ativo com tipo fora da partição nova/renovação/vigente",
            tipo=tipo_extra,
            categoria=Categoria.objects.first(),
            unidade_organizacional=Unidade.objects.first(),
            estado=Estado.ATIVO.value,
            situacao=Situacao.NO_PRAZO.value,
            valor_estimado=Decimal("1000.00"),
        )
        bloco_a, bloco_b, gauge = self._blocos()
        self.assertTrue(bloco_a["ativos"]["inconsistente"])
        self.assertIn("diverge em 1 processo", bloco_a["ativos"]["titulo"])

    # --- gauge --------------------------------------------------------------
    # O gauge exclui Vigentes do numerador e do denominador (o invariante
    # antigo, gauge == contagem bruta, não vale mais).

    def test_gauge_exclui_vigentes_do_numerador_e_denominador(self):
        id_vigente = Tipo.objects.get(nome_normalizado="vigente").id
        qs = self._qs()
        bloco_a, bloco_b, gauge = self._blocos()
        concluido_vigente = qs.filter(
            estado=Estado.ATIVO,
            situacao_efetiva=Situacao.CONCLUIDO,
            tipo_id=id_vigente,
        ).count()
        self.assertEqual(
            gauge["concluidos"], bloco_b["concluido"]["contagem"] - concluido_vigente
        )
        self.assertEqual(
            gauge["ativos"],
            bloco_a["ativos"]["contagem"] - bloco_a["vigentes"]["contagem"],
        )

    # --- hrefs distintos por faixa: o `href` único antigo fazia qualquer
    # clique navegar sempre para o mesmo recorte de CONCLUÍDO.

    def test_gauge_href_concluidos_e_href_restantes_sao_distintos_e_excluem_vigentes(
        self,
    ):
        bloco_a, bloco_b, gauge = self._blocos()
        id_nova = Tipo.objects.get(nome_normalizado="nova contratacao").id
        id_renovacao = Tipo.objects.get(nome_normalizado="renovacao").id
        href_concluidos_esperado = querystring_filtros(
            self.factory.get("/").GET,
            estado=[Estado.ATIVO.value],
            situacao=[Situacao.CONCLUIDO.value],
            tipo=[id_nova, id_renovacao],
        )
        href_restantes_esperado = querystring_filtros(
            self.factory.get("/").GET,
            estado=[Estado.ATIVO.value],
            situacao=[
                Situacao.NO_PRAZO.value,
                Situacao.ATRASADO.value,
                Situacao.EM_TRAMITACAO.value,
            ],
            tipo=[id_nova, id_renovacao],
        )
        self.assertEqual(gauge["href_concluidos"], href_concluidos_esperado)
        self.assertEqual(gauge["href_restantes"], href_restantes_esperado)
        self.assertNotEqual(gauge["href_concluidos"], gauge["href_restantes"])

    # --- orçamento de queries ------------------------------------------------

    def test_calcular_blocos_kpi_paga_no_maximo_duas_queries(self):
        request = self.factory.get("/")
        qs = queryset_filtrado(request)
        with self.assertNumQueries(2):
            calcular_blocos_kpi(
                qs,
                request.GET,
                dias_proximo_vencimento=settings.PCA_DIAS_PROXIMOS_VENCIMENTO,
            )

    # --- correção de leitura no Bloco B --------------------------------------

    def test_no_prazo_gravado_com_prazo_vencido_conta_como_atrasado(self):
        unidade = Unidade.objects.create(nome="UO correção de leitura")
        exercicio = Exercicio.objects.get(ano=2026)
        tipo_nova = Tipo.objects.get(nome_normalizado="nova contratacao")
        Processo.objects.create(
            item_pca=9002,
            exercicio=exercicio,
            descricao_objeto="No prazo gravado, prazo de entrega já vencido",
            tipo=tipo_nova,
            categoria=Categoria.objects.first(),
            unidade_organizacional=unidade,
            estado=Estado.ATIVO.value,
            situacao=Situacao.NO_PRAZO.value,
            prazo_entrega=localdate() - timedelta(days=1),
            valor_estimado=Decimal("1000.00"),
        )
        bloco_a, bloco_b, gauge = self._blocos(uo=unidade.pk)
        self.assertEqual(bloco_b["atrasados"]["contagem"], 1)
        self.assertEqual(bloco_b["no_prazo"]["contagem"], 0)

    # --- Bloco B mede universo restrito, não o antigo Atenção ----------------

    def test_atrasados_do_bloco_b_exclui_vigentes_do_universo_de_atenção_antigo(self):
        # O antigo bloco "Atenção" media qualquer processo não-terminal
        # com prazo vencido, inclusive Vigentes. O Bloco B mede só o
        # universo elegível (Nova+Renovação ativos) — um Vigente com
        # prazo vencido prova a diferença de escopo (evita dois números
        # "Atrasados" divergentes na mesma tela).
        unidade = Unidade.objects.create(nome="UO escopo restrito")
        exercicio = Exercicio.objects.get(ano=2026)
        tipo_vigente = Tipo.objects.get(nome_normalizado="vigente")
        Processo.objects.create(
            item_pca=9003,
            exercicio=exercicio,
            descricao_objeto="Vigente com prazo vencido — fora do universo do Bloco B",
            tipo=tipo_vigente,
            categoria=Categoria.objects.first(),
            unidade_organizacional=unidade,
            estado=Estado.ATIVO.value,
            situacao=Situacao.NO_PRAZO.value,
            prazo_entrega=localdate() - timedelta(days=1),
            valor_estimado=Decimal("1000.00"),
        )
        bloco_a, bloco_b, gauge = self._blocos(uo=unidade.pk)
        self.assertEqual(bloco_b["atrasados"]["contagem"], 0)

    # --- Meta/Concluído da meta exatos no apoio do KPI Concluídos
    # (Início), sem superestimar via
    # concluido_sem_vigente/ativos_sem_vigente. -------------------------

    def test_meta_pca_bate_com_nova_mais_renovacao_do_bloco_a(self):
        bloco_a, bloco_b, gauge = self._blocos()
        elegivel = bloco_a["nova"]["contagem"] + bloco_a["renovacao"]["contagem"]
        self.assertEqual(bloco_b["concluido"]["meta_pca"], elegivel)
        if elegivel:
            self.assertAlmostEqual(
                float(bloco_b["concluido"]["percentual_meta_pca"]),
                bloco_b["concluido"]["concluido_meta_pca"] / elegivel * 100,
                places=6,
            )

    def test_meta_pca_exclui_tipo_fora_da_particao_nova_renovacao_vigente(self):
        # Mesmo fixture de
        # test_tipo_sintetico_fora_da_particao_gera_selo_de_inconsistencia:
        # `meta_pca` não inclui o processo de tipo sintético — só NC/RN,
        # nunca `ativos_sem_vigente` (que incluiria esse tipo extra e
        # superestimaria a meta).
        tipo_extra = Tipo.objects.create(nome="Tipo sintético fora da partição")
        exercicio = Exercicio.objects.get(ano=2026)
        Processo.objects.create(
            item_pca=9004,
            exercicio=exercicio,
            descricao_objeto="Ativo com tipo fora da partição nova/renovação/vigente",
            tipo=tipo_extra,
            categoria=Categoria.objects.first(),
            unidade_organizacional=Unidade.objects.first(),
            estado=Estado.ATIVO.value,
            situacao=Situacao.CONCLUIDO.value,
            valor_estimado=Decimal("1000.00"),
        )
        bloco_a, bloco_b, gauge = self._blocos()
        elegivel_esperado = (
            bloco_a["nova"]["contagem"] + bloco_a["renovacao"]["contagem"]
        )
        self.assertEqual(bloco_b["concluido"]["meta_pca"], elegivel_esperado)
