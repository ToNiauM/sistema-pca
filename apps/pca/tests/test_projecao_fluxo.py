"""Testes do módulo puro `apps.pca.projecao.fluxo` (Fase 36,
documento interno de desenho
§3). `unittest.TestCase` simples — mesmo padrão de `test_regras_situacao.py`:
o módulo é puro, sem banco, sem ORM, sem Django.
"""

import time
import unittest
from datetime import date, timedelta
from decimal import Decimal

from apps.pca.projecao import Parametros
from apps.pca.projecao.fluxo import projetar


def _item(**kwargs):
    """Fase 37 (spec §2.1) — o `base` só declara os campos do
    NOVO contrato de entrada (`contratos=[]` no lugar de `eventos`/
    `valor_contratado`/`vigencia_inicio` soltos; campos de planejado
    continuam no nível do item, spec §2.1). Testes PRÉ-EXISTENTES abaixo
    continuam passando kwargs do formato antigo (`valor_contratado=`,
    `vigencia_inicio=`, `eventos=`...) direto para `base.update(kwargs)` —
    o `fluxo.py` de hoje só lê essas chaves via `.get()` (nunca
    `item["chave"]` fora de `item_pca`/`uo`), então ausência vs. presença
    com `None` é indistinguível para ele; nenhum teste antigo muda de
    comportamento (RED só nasce nos testes NOVOS de
    `TestAceiteMotorFase37`, que usam `contratos=[...]` e nada mais — o
    motor de hoje ainda não lê esse campo, faz isso)."""
    base = {
        "item_pca": 1,
        "uo": "Unidade A",
        "objeto": "",
        "estado": "ativo",
        "situacao": "no_prazo",
        "modalidade": None,
        "valor_estimado": None,
        "regime_execucao": None,
        "mes_previsto": None,
        "prazo_efetivo": None,
        "renovacao_prevista": False,
        "contratos": [],
    }
    base.update(kwargs)
    return base


def _contrato(**kwargs):
    """Uma entrada de `item["contratos"]` (spec §2.1, interfaces do Plano
    37-01) — cadeia independente dentro de um item."""
    base = {
        "instrumento": "principal",
        "vigencia_inicio": None,
        "vigencia_fim": None,
        "data_assinatura": None,
        "valor": None,
        "periodicidade": None,
        "data_base": None,
        "protocolo_sei": None,
        "numero_sei": None,
        "eventos": [],
    }
    base.update(kwargs)
    return base


def _evento(**kwargs):
    """Uma entrada de `contrato["eventos"]` (spec §2.1) — só elegíveis
    (fronteira decidida fora do motor, deste plano)."""
    base = {
        "id": 1,
        "tipo": None,
        "natureza": None,
        "data": None,
        "valor": None,
        "valor_mensal": None,
        "periodicidade": None,
        "data_base": None,
        "protocolo_sei": None,
    }
    base.update(kwargs)
    return base


def _parametros(**kwargs):
    base = dict(
        horizonte_inicio=date(2026, 1, 1),
        horizonte_fim=date(2031, 12, 31),
        exercicio=2026,
        indices={},
        cenario="base",
        lead_time_mediano_dias=90,
    )
    base.update(kwargs)
    return Parametros(**base)


class TestParametrosPadrao(unittest.TestCase):
    def test_lead_time_mediano_dias_default_e_noventa(self):
        parametros = Parametros(
            horizonte_inicio=date(2026, 1, 1),
            horizonte_fim=date(2026, 12, 31),
            exercicio=2026,
            indices={},
            cenario="base",
        )
        self.assertEqual(parametros.lead_time_mediano_dias, 90)


class TestCamadaContratadoContinuado(unittest.TestCase):
    def test_doze_meses_exatos_dez_mil_cada(self):
        item = _item(
            valor_contratado=Decimal("120000.00"),
            vigencia_inicio=date(2026, 1, 1),
            vigencia_fim=date(2026, 12, 31),
            regime_execucao="continuado",
        )
        projecao = projetar([item], _parametros())
        parcelas = [p for p in projecao.parcelas if p.camada == "contratado"]
        self.assertEqual(len(parcelas), 12)
        for p in parcelas:
            self.assertEqual(p.valor, Decimal("10000.00"))
        self.assertEqual(sum(p.valor for p in parcelas), Decimal("120000.00"))

    def test_regime_null_usa_a_heuristica_de_regras_situacao(self):
        # vigência de exatamente 12 meses (mesmo dia, ano seguinte) —
        # regras_situacao.regime_presumido_projecao (limiar 12 meses) presume "continuado"; import relativo interfaces§.
        item = _item(
            valor_contratado=Decimal("120000.00"),
            vigencia_inicio=date(2026, 1, 1),
            vigencia_fim=date(2027, 1, 1),
            regime_execucao=None,
        )
        projecao = projetar([item], _parametros(horizonte_fim=date(2027, 12, 31)))
        parcelas = [p for p in projecao.parcelas if p.camada == "contratado"]
        self.assertGreater(len(parcelas), 1)

    def test_mes_parcial_no_inicio_e_proporcional_e_soma_bate(self):
        # vigência 15/03 a 31/08/2026 (6 meses de calendário: mar..ago),
        # valor_mensal explícito (R$ 10.000,00) — evita a ambiguidade de
        # "global ÷ meses_vigencia" combinada a mês parcial, fora do escopo
        # deste plano (a fallback de divisão é coberta pelo caso acima, sem
        # mês parcial).
        item = _item(
            valor_contratado=Decimal("60000.00"),
            valor_mensal=Decimal("10000.00"),
            regime_execucao="continuado",
            vigencia_inicio=date(2026, 3, 15),
            vigencia_fim=date(2026, 8, 31),
        )
        projecao = projetar([item], _parametros())
        parcelas = sorted(
            (p for p in projecao.parcelas if p.camada == "contratado"),
            key=lambda p: p.competencia,
        )
        self.assertEqual(
            [p.competencia for p in parcelas],
            ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"],
        )
        # março: 17 dos 31 dias (15 a 31 inclusive) -> 10000 * 17/31 = 5483,87
        self.assertEqual(parcelas[0].valor, Decimal("5483.87"))
        self.assertLess(parcelas[0].valor, Decimal("10000.00"))
        for p in parcelas[1:]:
            self.assertEqual(p.valor, Decimal("10000.00"))
        # arredondamento absorvido na ÚLTIMA parcela, nunca na primeira —
        # aqui não sobra resíduo de centavos, mas a soma continua batendo
        # com o valor global usado no período (5483,87 + 4x10000 + 10000).
        self.assertEqual(sum(p.valor for p in parcelas), Decimal("55483.87"))


class TestCamadaContratadoUnico(unittest.TestCase):
    def test_unico_lanca_cem_por_cento_no_fim_da_vigencia(self):
        item = _item(
            valor_contratado=Decimal("50000.00"),
            regime_execucao="unico",
            vigencia_fim=date(2026, 11, 30),
        )
        projecao = projetar([item], _parametros())
        parcelas = [p for p in projecao.parcelas if p.camada == "contratado"]
        self.assertEqual(len(parcelas), 1)
        self.assertEqual(parcelas[0].competencia, "2026-11")
        self.assertEqual(parcelas[0].valor, Decimal("50000.00"))

    def test_unico_sem_vigencia_fim_usa_assinatura_mais_30_dias(self):
        assinatura = date(2026, 5, 1)
        item = _item(
            valor_contratado=Decimal("20000.00"),
            regime_execucao="unico",
            data_assinatura_contrato=assinatura,
        )
        projecao = projetar([item], _parametros())
        parcelas = [p for p in projecao.parcelas if p.camada == "contratado"]
        competencia_esperada = assinatura + timedelta(days=30)
        self.assertEqual(len(parcelas), 1)
        self.assertEqual(
            parcelas[0].competencia,
            f"{competencia_esperada.year:04d}-{competencia_esperada.month:02d}",
        )
        self.assertEqual(parcelas[0].valor, Decimal("20000.00"))


class TestCamadaRenovacao(unittest.TestCase):
    def test_renovacao_prevista_projeta_ate_horizonte_fim_em_camada_propria(self):
        item = _item(
            valor_contratado=Decimal("120000.00"),
            valor_mensal=Decimal("10000.00"),
            regime_execucao="continuado",
            renovacao_prevista=True,
            vigencia_inicio=date(2026, 1, 1),
            vigencia_fim=date(2026, 12, 31),
        )
        parametros = _parametros(horizonte_fim=date(2027, 3, 31))
        projecao = projetar([item], parametros)
        renovacao = sorted(
            (p for p in projecao.parcelas if p.camada == "renovacao"),
            key=lambda p: p.competencia,
        )
        self.assertEqual(
            [p.competencia for p in renovacao], ["2027-01", "2027-02", "2027-03"]
        )
        for p in renovacao:
            self.assertEqual(p.valor, Decimal("10000.00"))
        contratado = [p for p in projecao.parcelas if p.camada == "contratado"]
        self.assertEqual(len(contratado), 12)


class TestCamadaReajuste(unittest.TestCase):
    def test_reajuste_composto_dois_anos_so_a_diferenca_na_camada(self):
        item = _item(
            valor_contratado=Decimal("120000.00"),
            valor_mensal=Decimal("10000.00"),
            regime_execucao="continuado",
            vigencia_inicio=date(2025, 1, 1),
            vigencia_fim=date(2029, 12, 31),
        )
        parametros = _parametros(
            horizonte_inicio=date(2026, 1, 1),
            horizonte_fim=date(2027, 12, 31),
            indices={2026: Decimal("5.00"), 2027: Decimal("5.00")},
        )
        projecao = projetar([item], parametros)

        contratado = {p.competencia: p.valor for p in projecao.parcelas if p.camada == "contratado"}
        reajuste = {p.competencia: p.valor for p in projecao.parcelas if p.camada == "reajuste"}

        # camada 1 nunca muda — sempre o valor base, mesmo depois do reajuste
        self.assertEqual(contratado["2026-01"], Decimal("10000.00"))
        self.assertEqual(contratado["2027-01"], Decimal("10000.00"))

        # 1º aniversário (jan/2026): 10000 * 1,05 = 10500 -> diferença 500
        self.assertEqual(reajuste["2026-01"], Decimal("500.00"))
        # 2º aniversário (jan/2027), composto: 10000 * 1,05 * 1,05 = 11025 -> diferença 1025
        self.assertEqual(reajuste["2027-01"], Decimal("1025.00"))


class TestEventoAlteraGlobalVigente(unittest.TestCase):
    def test_supressao_muda_o_global_a_partir_da_competencia_do_evento(self):
        item = _item(
            valor_contratado=Decimal("120000.00"),
            valor_mensal=Decimal("10000.00"),
            regime_execucao="continuado",
            vigencia_inicio=date(2026, 1, 1),
            vigencia_fim=date(2026, 12, 31),
            eventos=[
                {
                    "data": date(2026, 7, 1),
                    "natureza": "supressao",
                    "valor": Decimal("102000.00"),
                    "valor_mensal": Decimal("8500.00"),
                    "periodicidade": "mensal",
                },
            ],
        )
        projecao = projetar([item], _parametros())
        contratado = {p.competencia: p.valor for p in projecao.parcelas if p.camada == "contratado"}
        self.assertEqual(contratado["2026-06"], Decimal("10000.00"))
        self.assertEqual(contratado["2026-07"], Decimal("8500.00"))
        self.assertEqual(contratado["2026-12"], Decimal("8500.00"))


class TestCenarios(unittest.TestCase):
    def _itens(self):
        contratado = _item(
            item_pca=1,
            valor_contratado=Decimal("120000.00"),
            valor_mensal=Decimal("10000.00"),
            regime_execucao="continuado",
            renovacao_prevista=True,
            vigencia_inicio=date(2025, 1, 1),
            vigencia_fim=date(2026, 12, 31),
        )
        planejado = _item(
            item_pca=2,
            valor_estimado=Decimal("36000.00"),
            estado="ativo",
            mes_previsto=6,
            regime_execucao="continuado",
        )
        return [contratado, planejado]

    def _camadas(self, cenario):
        parametros = _parametros(
            horizonte_inicio=date(2026, 1, 1),
            horizonte_fim=date(2027, 12, 31),
            cenario=cenario,
            indices={2026: Decimal("5.00")},
            lead_time_mediano_dias=30,
        )
        projecao = projetar(self._itens(), parametros)
        return {p.camada for p in projecao.parcelas}

    def test_base_inclui_as_quatro_camadas(self):
        self.assertEqual(
            self._camadas("base"), {"contratado", "renovacao", "reajuste", "planejado"}
        )

    def test_contratado_so_tem_a_camada_contratado(self):
        self.assertEqual(self._camadas("contratado"), {"contratado"})

    def test_sem_reajuste_zera_a_camada_reajuste(self):
        camadas = self._camadas("sem_reajuste")
        self.assertNotIn("reajuste", camadas)
        self.assertEqual(camadas, {"contratado", "renovacao", "planejado"})

    def test_sem_renovacao_zera_a_camada_renovacao(self):
        camadas = self._camadas("sem_renovacao")
        self.assertNotIn("renovacao", camadas)
        self.assertEqual(camadas, {"contratado", "reajuste", "planejado"})


class TestSemDado(unittest.TestCase):
    def test_sem_vigencia_e_sem_assinatura_entra_em_sem_dado(self):
        item = _item(item_pca=7, valor_contratado=Decimal("1000.00"))
        projecao = projetar([item], _parametros())
        self.assertEqual(projecao.sem_dado, [{"item_pca": 7, "motivo": "sem_vigencia"}])
        self.assertEqual([p for p in projecao.parcelas if p.item_pca == 7], [])

    def test_sem_valor_contratado_e_sem_valor_estimado_entra_em_sem_dado(self):
        item = _item(item_pca=8, estado="ativo")
        projecao = projetar([item], _parametros())
        self.assertEqual(projecao.sem_dado, [{"item_pca": 8, "motivo": "sem_valor"}])

    def test_item_cancelado_nao_entra_em_sem_dado(self):
        item = _item(item_pca=9, estado="cancelado")
        projecao = projetar([item], _parametros())
        self.assertEqual(projecao.sem_dado, [])
        self.assertEqual([p for p in projecao.parcelas if p.item_pca == 9], [])


class TestIndiceAusente(unittest.TestCase):
    def test_ano_sem_indice_usa_ultimo_ano_conhecido_e_registra_premissa(self):
        item = _item(
            item_pca=3,
            valor_contratado=Decimal("120000.00"),
            valor_mensal=Decimal("10000.00"),
            regime_execucao="continuado",
            vigencia_inicio=date(2025, 1, 1),
            vigencia_fim=date(2028, 12, 31),
        )
        parametros = _parametros(
            horizonte_inicio=date(2026, 1, 1),
            horizonte_fim=date(2027, 12, 31),
            indices={2026: Decimal("5.00")},  # 2027 ausente de propósito
        )
        projecao = projetar([item], parametros)
        reajuste = {p.competencia: p.valor for p in projecao.parcelas if p.camada == "reajuste"}
        self.assertEqual(reajuste["2027-01"], Decimal("1025.00"))
        # Fase 36 (fix de apresentação): o
        # ano de 2027 sem índice gera parcela de reajuste em TODOS os 12
        # meses do ano, mas "Premissas" consolida numa ÚNICA linha por
        # (ano, item), nunca uma por mês.
        self.assertEqual(len(projecao.premissas), 1)
        self.assertIn("2027", projecao.premissas[0])
        self.assertIn("1 item", projecao.premissas[0])

    def test_dois_itens_dois_anos_sem_indice_gera_uma_premissa_por_ano_com_dois_itens(self):
        """Reprodução do defeito relatado pelo usuário em 19/09/2026: com
        vários itens × vários meses sem índice, o bloco Premissas chegou a
        1.250 linhas (106 distintas) — cada mês sem índice virava uma linha
        NOVA por item. Este teste prova a consolidação: 2 itens, 2 anos sem
        índice (2027/2028, ambos caindo no fallback de 2026) -> exatamente
        UMA premissa por ano, cada uma citando "2 itens" (nunca uma por
        parcela/mês nem duplicada por item)."""

        item_a = _item(
            item_pca=10,
            valor_contratado=Decimal("240000.00"),
            valor_mensal=Decimal("10000.00"),
            regime_execucao="continuado",
            vigencia_inicio=date(2025, 1, 1),
            vigencia_fim=date(2030, 12, 31),
        )
        item_b = _item(
            item_pca=11,
            valor_contratado=Decimal("240000.00"),
            valor_mensal=Decimal("10000.00"),
            regime_execucao="continuado",
            vigencia_inicio=date(2025, 6, 1),
            vigencia_fim=date(2030, 12, 31),
        )
        parametros = _parametros(
            horizonte_inicio=date(2026, 1, 1),
            horizonte_fim=date(2028, 12, 31),
            indices={2026: Decimal("5.00")},  # 2027 e 2028 ausentes de propósito
        )

        projecao = projetar([item_a, item_b], parametros)

        premissas_indice = [p for p in projecao.premissas if "Índice" in p]
        self.assertEqual(len(premissas_indice), 2)  # uma por ano, não uma por item x mês

        premissa_2027 = next(p for p in premissas_indice if "2027" in p)
        self.assertIn("2 itens", premissa_2027)

        premissa_2028 = next(p for p in premissas_indice if "2028" in p)
        self.assertIn("2 itens", premissa_2028)


class TestCamadaPlanejado(unittest.TestCase):
    def test_planejado_usa_lead_time_e_valor_estimado_inteiro(self):
        item = _item(
            item_pca=4,
            estado="ativo",
            valor_estimado=Decimal("36000.00"),
            mes_previsto=6,
            regime_execucao="continuado",
        )
        parametros = _parametros(
            horizonte_inicio=date(2026, 1, 1),
            horizonte_fim=date(2028, 12, 31),
            exercicio=2026,
            lead_time_mediano_dias=30,  # 01/06 + 30 dias = 01/07 (dia 1, sem mês parcial)
        )
        projecao = projetar([item], parametros)
        planejado = [p for p in projecao.parcelas if p.camada == "planejado"]
        self.assertTrue(planejado)
        self.assertEqual(sum(p.valor for p in planejado), Decimal("36000"))
        self.assertEqual(min(p.competencia for p in planejado), "2026-07")


class TestKpiCincoAnosPeriodoLiteral(unittest.TestCase):
    """M11 — `totais["cinco_anos"]` soma
    EXATAMENTE os 5 exercícios seguintes (exercicio+1..exercicio+5), nunca
    o exercício corrente (esse já é `ate_fim_exercicio`)."""

    def test_cinco_anos_exclui_exercicio_corrente_e_inclui_ano_mais_cinco(self):
        item_exercicio_corrente = _item(
            item_pca=1,
            valor_contratado=Decimal("1000.00"),
            regime_execucao="unico",
            vigencia_fim=date(2026, 6, 30),
        )
        item_ano_mais_cinco = _item(
            item_pca=2,
            valor_contratado=Decimal("2000.00"),
            regime_execucao="unico",
            vigencia_fim=date(2031, 6, 30),
        )
        projecao = projetar(
            [item_exercicio_corrente, item_ano_mais_cinco], _parametros()
        )

        self.assertEqual(projecao.totais["cinco_anos"], Decimal("2000.00"))
        self.assertEqual(projecao.totais["ate_fim_exercicio"], Decimal("1000.00"))


class TestDesempenho(unittest.TestCase):
    def test_quinhentos_itens_setenta_e_dois_meses_abaixo_de_trezentos_ms(self):
        itens = []
        for i in range(500):
            tipo = i % 4
            if tipo == 0:
                itens.append(
                    _item(
                        item_pca=i,
                        valor_contratado=Decimal("120000.00"),
                        valor_mensal=Decimal("10000.00"),
                        regime_execucao="continuado",
                        renovacao_prevista=True,
                        vigencia_inicio=date(2024, 1, 1),
                        vigencia_fim=date(2026, 12, 31),
                    )
                )
            elif tipo == 1:
                itens.append(
                    _item(
                        item_pca=i,
                        valor_contratado=Decimal("50000.00"),
                        regime_execucao="unico",
                        vigencia_fim=date(2026, 6, 30),
                    )
                )
            elif tipo == 2:
                itens.append(
                    _item(
                        item_pca=i,
                        estado="ativo",
                        valor_estimado=Decimal("24000.00"),
                        mes_previsto=(i % 12) + 1,
                        regime_execucao="continuado",
                    )
                )
            else:
                itens.append(_item(item_pca=i, estado="cancelado"))

        parametros = _parametros(
            horizonte_inicio=date(2026, 1, 1),
            horizonte_fim=date(2031, 12, 31),  # 72 meses
            indices={2026: Decimal("5.00"), 2027: Decimal("5.00")},
        )

        inicio = time.perf_counter()
        projecao = projetar(itens, parametros)
        duracao_ms = (time.perf_counter() - inicio) * 1000

        self.assertGreater(len(projecao.parcelas), 0)
        self.assertLess(duracao_ms, 300)


class TestAceiteMotorFase37(unittest.TestCase):
    """Fase 37 (spec §2.4, `melhorias.md` M01/M02/M03/M05/M10)
    — os 10 casos de aceite do motor CORRIGIDO, escritos ANTES da reescrita
    (RED, `Reescrita dirigida por testes de aceite escritos ANTES` — spec
    §2). Todo `item` usa exclusivamente o contrato de entrada NOVO
    (`contratos=[...]`, nunca `eventos`/`valor_contratado`/`vigencia_inicio`
    soltos no nível do item).

    Contra o `fluxo.py` de hoje (Fase 36, intocado nesta task) os 10 casos
    FALHAM pela mesma razão imediata: `_projetar_item` só lê
    `item.get("valor_contratado")`/`item.get("valor_estimado")` — nunca
    `item.get("contratos")` — então todo item descrito só pelo array novo
    cai em `"sem_valor"`/nenhuma parcela. Essa lacuna É exatamente o que o
    fecha (reescrita de `_projetar_item`/`_resolver_global`
    para ler `contratos[]`), e cada caso abaixo, uma vez que a leitura
    exista, prova também a correção do respectivo defeito M0X citado no
    docstring de cada teste — para o resultado real
    desta execução (RED) e o mapeamento teste → causa."""

    def test_contrato_global_cem_reais_janeiro_a_dezembro_soma_cem_reais_exatos(self):
        """M01 — rateio de um global preserva o valor exato: R$ 100,00 de
        jan a dez somam R$ 100,00 (o `fluxo.py` de hoje, quando lia o
        contrato antigo equivalente, produzia R$ 99,96 —
        `_mensal_base_em` arredondava antes da distribuição e
        `_distribuir_mensal` fechava contra a soma já reduzida)."""
        item = _item(
            item_pca=101,
            contratos=[
                _contrato(
                    vigencia_inicio=date(2026, 1, 1),
                    vigencia_fim=date(2026, 12, 31),
                    valor=Decimal("100.00"),
                    periodicidade="global",
                )
            ],
        )
        projecao = projetar([item], _parametros())
        parcelas = [p for p in projecao.parcelas if p.item_pca == 101]
        self.assertEqual(sum((p.valor for p in parcelas), Decimal("0")), Decimal("100.00"))

    def test_global_120_mil_15_01_a_14_01_soma_120_mil_no_horizonte_integral(self):
        """M01 — global de R$ 120.000,00 vigente de 15/01/2026 a 14/01/2027
        soma R$ 120.000,00 no horizonte que cobre a vigência inteira (hoje,
        com o formato antigo equivalente, o motor somava R$ 110.769,24 —
        divisor de meses de calendário aplicado antes da proporcionalidade
        diária)."""
        item = _item(
            item_pca=102,
            contratos=[
                _contrato(
                    vigencia_inicio=date(2026, 1, 15),
                    vigencia_fim=date(2027, 1, 14),
                    valor=Decimal("120000.00"),
                    periodicidade="global",
                )
            ],
        )
        parametros = _parametros(horizonte_fim=date(2027, 12, 31))
        projecao = projetar([item], parametros)
        parcelas = [p for p in projecao.parcelas if p.item_pca == 102]
        self.assertEqual(sum((p.valor for p in parcelas), Decimal("0")), Decimal("120000.00"))

    def test_planejado_execucao_unica_preserva_centavos(self):
        """M01 — valor estimado de execução única preserva os centavos;
        `_camada_planejado` usa `to_integral_value()` e R$ 1.000,49 vira
        R$ 1.000,00. Os campos de planejado continuam soltos no nível do
        item (spec §2.1), então este caso já roda contra o motor atual sem
        depender da leitura de `contratos[]` — a falha aqui É a aritmética
        real do M01, não um efeito colateral do contrato novo."""
        item = _item(
            item_pca=103,
            estado="ativo",
            valor_estimado=Decimal("1000.49"),
            regime_execucao="unico",
            mes_previsto=6,
        )
        projecao = projetar([item], _parametros())
        parcelas = [p for p in projecao.parcelas if p.item_pca == 103]
        self.assertEqual(len(parcelas), 1)
        self.assertEqual(parcelas[0].valor, Decimal("1000.49"))

    def test_evento_mensal_explicito_gera_doze_parcelas_de_mil_nunca_83_33(self):
        """M03 — contrato com periodicidade explicitamente `mensal` gera 12
        parcelas de R$ 1.000,00 cada, nunca R$ 83,33 (hoje `_resolver_global`
        ignora `periodicidade` e trata todo `valor` como global, dividindo
        pelos meses de vigência)."""
        item = _item(
            item_pca=104,
            contratos=[
                _contrato(
                    vigencia_inicio=date(2026, 1, 1),
                    vigencia_fim=date(2026, 12, 31),
                    valor=Decimal("1000.00"),
                    periodicidade="mensal",
                )
            ],
        )
        projecao = projetar([item], _parametros())
        parcelas = [p for p in projecao.parcelas if p.item_pca == 104]
        self.assertEqual(len(parcelas), 12)
        for p in parcelas:
            self.assertEqual(p.valor, Decimal("1000.00"))

    def test_renovacao_recebe_reajuste_nos_aniversarios_corretos(self):
        """M02 — renovação prevista recebe o mesmo reajuste projetado dos
        aniversários (hoje Base e Sem reajuste empatam, porque
        `_camada_renovacao` replica a mensalidade sem reajuste)."""
        item = _item(
            item_pca=105,
            renovacao_prevista=True,
            contratos=[
                _contrato(
                    vigencia_inicio=date(2026, 1, 1),
                    vigencia_fim=date(2026, 12, 31),
                    valor=Decimal("10000.00"),
                    periodicidade="mensal",
                )
            ],
        )
        parametros_base = _parametros(
            horizonte_inicio=date(2026, 1, 1),
            horizonte_fim=date(2028, 12, 31),
            indices={2027: Decimal("10.00"), 2028: Decimal("10.00")},
            indice_nome="IPCA",
        )
        projecao_base = projetar([item], parametros_base)
        por_ano = projecao_base.por_ano
        total_2027 = sum(por_ano.get(2027, {}).values(), Decimal("0"))
        total_2028 = sum(por_ano.get(2028, {}).values(), Decimal("0"))
        self.assertEqual(total_2027, Decimal("132000.00"))
        self.assertEqual(total_2028, Decimal("145200.00"))
        self.assertNotEqual(por_ano.get(2027, {}).get("reajuste", Decimal("0")), Decimal("0"))

        parametros_sem_reajuste = _parametros(
            horizonte_inicio=date(2026, 1, 1),
            horizonte_fim=date(2028, 12, 31),
            indices={2027: Decimal("10.00"), 2028: Decimal("10.00")},
            indice_nome="IPCA",
            cenario="sem_reajuste",
        )
        projecao_sem_reajuste = projetar([item], parametros_sem_reajuste)
        total_sem_reajuste_2027 = sum(
            projecao_sem_reajuste.por_ano.get(2027, {}).values(), Decimal("0")
        )
        self.assertEqual(total_sem_reajuste_2027, Decimal("120000.00"))

    def test_evento_de_reajuste_real_em_janeiro_nao_soma_reajuste_projetado_no_mesmo_mes(self):
        """M02 — com um evento REAL de reajuste em janeiro, o motor não
        soma reajuste PROJETADO no mesmo mês; o próximo aniversário
        projetado só entra no ano seguinte. A asserção positiva (reajuste
        != 0 em 2027-01) é o que torna este caso RED hoje — sem ela, "nada
        em 2026-01" seria trivialmente verdade também quando o motor
        simplesmente não lê `contratos[]` (nenhuma parcela em ano
        nenhum)."""
        item = _item(
            item_pca=106,
            contratos=[
                _contrato(
                    vigencia_inicio=date(2025, 1, 1),
                    vigencia_fim=date(2027, 12, 31),
                    valor=Decimal("10000.00"),
                    periodicidade="mensal",
                    eventos=[
                        _evento(
                            id=1,
                            tipo="aditivo",
                            natureza="reajuste",
                            data=date(2026, 1, 15),
                            valor_mensal=Decimal("10500.00"),
                            periodicidade="mensal",
                        ),
                    ],
                )
            ],
        )
        parametros = _parametros(
            horizonte_inicio=date(2026, 1, 1),
            horizonte_fim=date(2027, 12, 31),
            indices={2026: Decimal("5.00"), 2027: Decimal("5.00")},
        )
        projecao = projetar([item], parametros)
        reajuste = {
            p.competencia: p.valor
            for p in projecao.parcelas
            if p.item_pca == 106 and p.camada == "reajuste"
        }
        self.assertNotIn("2026-01", reajuste)
        self.assertNotEqual(reajuste.get("2027-01", Decimal("0")), Decimal("0"))

    def test_dois_contratos_no_mesmo_item_somam_por_mes(self):
        """M05 — item com dois contratos independentes soma por mês; um
        aditivo em só um dos contratos não deve afetar o outro (a fase 33
        soma contratos distintos; a fase 36 achatava tudo numa série só por
        item)."""
        item = _item(
            item_pca=107,
            contratos=[
                _contrato(
                    instrumento="CT 01/2026",
                    vigencia_inicio=date(2026, 1, 1),
                    vigencia_fim=date(2026, 12, 31),
                    valor=Decimal("100.00"),
                    periodicidade="mensal",
                ),
                _contrato(
                    instrumento="CT 02/2026",
                    vigencia_inicio=date(2026, 1, 1),
                    vigencia_fim=date(2026, 12, 31),
                    valor=Decimal("200.00"),
                    periodicidade="mensal",
                ),
            ],
        )
        projecao = projetar([item], _parametros())
        por_competencia = {}
        for p in projecao.parcelas:
            if p.item_pca == 107:
                por_competencia[p.competencia] = (
                    por_competencia.get(p.competencia, Decimal("0")) + p.valor
                )
        self.assertEqual(por_competencia.get("2026-06"), Decimal("300.00"))

    def test_dois_eventos_na_mesma_data_valem_o_de_maior_id(self):
        """M05 — dois eventos na mesma data ordenam por `(data, id)`; o
        vigente é o de maior `id` (hoje `max(..., key=data)` empata no
        primeiro)."""
        item = _item(
            item_pca=108,
            contratos=[
                _contrato(
                    vigencia_inicio=date(2026, 1, 1),
                    vigencia_fim=date(2026, 12, 31),
                    valor=Decimal("50.00"),
                    periodicidade="mensal",
                    eventos=[
                        _evento(
                            id=1, tipo="aditivo", data=date(2026, 6, 1),
                            valor_mensal=Decimal("100.00"), periodicidade="mensal",
                        ),
                        _evento(
                            id=2, tipo="aditivo", data=date(2026, 6, 1),
                            valor_mensal=Decimal("200.00"), periodicidade="mensal",
                        ),
                    ],
                )
            ],
        )
        projecao = projetar([item], _parametros())
        parcela_junho = next(
            (
                p for p in projecao.parcelas
                if p.item_pca == 108 and p.competencia == "2026-06"
            ),
            None,
        )
        self.assertIsNotNone(parcela_junho)
        self.assertEqual(parcela_junho.valor, Decimal("200.00"))

    def test_indice_sem_percentual_cadastrado_nunca_zera_silenciosamente(self):
        """M10 — índice sem percentual cadastrado nunca vira reajuste zero
        silencioso; a premissa aparece na lista mesmo sem percentual (hoje
        `indices={}` retorna `premissas=[]`)."""
        item = _item(
            item_pca=109,
            renovacao_prevista=True,
            contratos=[
                _contrato(
                    vigencia_inicio=date(2026, 1, 1),
                    vigencia_fim=date(2026, 12, 31),
                    valor=Decimal("10000.00"),
                    periodicidade="mensal",
                )
            ],
        )
        parametros = _parametros(
            horizonte_inicio=date(2026, 1, 1),
            horizonte_fim=date(2029, 12, 31),
            indices={},
            indice_nome="IGP-M",
        )
        projecao = projetar([item], parametros)
        self.assertTrue(projecao.premissas)
        self.assertTrue(any("IGP-M" in p for p in projecao.premissas))

    def test_carga_quinhentos_itens_setenta_e_dois_meses_sob_seiscentos_ms(self):
        """Carga (spec §2.4): 500 itens × 72 meses, motor chamado duas
        vezes (oficial + simulado) somam menos de 600 ms — orçamento de
        desempenho (`### Constraints` do convenções do projeto) para a chamada dupla
        real da simulação. A asserção de que a camada
        `contratado` não fica vazia é o que torna este caso RED hoje: o
        motor atual ignora `contratos[]` (125 dos 500 itens são desse
        tipo), então "abaixo de 600 ms" seria trivialmente verdadeiro
        mesmo sem processar nada."""
        itens = []
        for i in range(500):
            tipo = i % 4
            if tipo == 0:
                itens.append(
                    _item(
                        item_pca=i,
                        renovacao_prevista=True,
                        contratos=[
                            _contrato(
                                vigencia_inicio=date(2024, 1, 1),
                                vigencia_fim=date(2026, 12, 31),
                                valor=Decimal("10000.00"),
                                periodicidade="mensal",
                            )
                        ],
                    )
                )
            elif tipo == 1:
                itens.append(
                    _item(
                        item_pca=i,
                        contratos=[
                            _contrato(
                                vigencia_fim=date(2026, 6, 30),
                                valor=Decimal("50000.00"),
                                periodicidade="global",
                            )
                        ],
                    )
                )
            elif tipo == 2:
                itens.append(
                    _item(
                        item_pca=i,
                        estado="ativo",
                        valor_estimado=Decimal("24000.00"),
                        mes_previsto=(i % 12) + 1,
                        regime_execucao="continuado",
                    )
                )
            else:
                itens.append(_item(item_pca=i, estado="cancelado"))

        parametros = _parametros(
            horizonte_inicio=date(2026, 1, 1),
            horizonte_fim=date(2031, 12, 31),  # 72 meses
            indices={2026: Decimal("5.00"), 2027: Decimal("5.00")},
        )

        inicio = time.perf_counter()
        projecao = projetar(itens, parametros)
        projetar(itens, parametros)
        duracao = time.perf_counter() - inicio

        total_contratado = sum(
            (p.valor for p in projecao.parcelas if p.camada == "contratado"),
            Decimal("0"),
        )
        self.assertGreater(total_contratado, Decimal("0"))
        self.assertLess(duracao, 0.6)


if __name__ == "__main__":
    unittest.main()
