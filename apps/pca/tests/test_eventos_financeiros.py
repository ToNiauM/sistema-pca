"""Testes de `apps/pca/servicos/eventos_financeiros.py::sincronizar` (Fase
36/, spec §2.2) e da fiação nos três comandos do robô
SEI (`sei_aplicar`/`sei_sincronizar`/`sei_atender`), TDD (RED/GREEN).

`TestSincronizarIsolado` cobre o `<behavior>` do serviço puro, sem passar
pelo robô — `Processo`/`Exercicio` mínimos criados direto via ORM (sem
`importar_pca`, mesmo padrão de `apps.catalogo.tests.AdminCatalogoTests`).
`TestFiacaoSeiAplicar`/`TestFiacaoSeiSincronizar` reaproveitam
`ComandosSeiBase` (`tempfile.TemporaryDirectory()` +
`override_settings(SEI_DATA_DIR=...)`) de `test_sei_comandos.py` — nenhum
teste deste arquivo importa `playwright` nem toca o SEI real
(`apps.pca.sei.coletor.coletar` é sempre mockado)."""

import json
from datetime import date
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from apps.catalogo.models import Categoria, Exercicio, Tipo, Unidade
from apps.pca.models import EventoFinanceiro, OrigemEventoFinanceiro, Processo, ProcessoSEI
from apps.pca.servicos import eventos_financeiros
from apps.pca.tests.test_sei_comandos import ComandosSeiBase

_FIXTURES = Path(__file__).parent / "fixtures" / "sei"


def _coleta_item_15(item_pca=15, exercicio=2026):
    """Mesmo padrão de `test_sei_comandos.py::_coleta_item_15` — fixture com
    apostilamento de reajuste global qualificado (Fase 35): `serie_valores`
    dessa coleta tem exatamente 1 entrada (protocolo `1290088`, R$
    45.000,00, `tipo="apostilamento"`, `natureza="reajuste"`) — o contrato
    (protocolo `1180020`) não entra na série porque a fixture não traz
    `valor` no documento de contrato."""
    with open(_FIXTURES / "coleta_item_15.json", encoding="utf-8") as arquivo:
        dados = json.load(arquivo)
    processos = []
    for processo in dados["processos"]:
        processo = dict(processo)
        processo["item_pca"] = item_pca
        processo["exercicio"] = exercicio
        processos.append(processo)
    return {"processos": processos}


class TestSincronizarIsolado(TestCase):
    """`sincronizar(processo, serie)` isolado do robô."""

    def setUp(self):
        self.exercicio, _ = Exercicio.objects.get_or_create(
            ano=2026, defaults={"rotulo": "PCA 2026"}
        )
        self.tipo = Tipo.objects.create(nome="Tipo eventos financeiros")
        self.categoria = Categoria.objects.create(nome="Categoria eventos financeiros")
        self.unidade = Unidade.objects.create(nome="Unidade eventos financeiros")
        self.processo = Processo.objects.create(
            exercicio=self.exercicio,
            item_pca=1,
            descricao_objeto="Objeto de teste — eventos financeiros",
            tipo=self.tipo,
            categoria=self.categoria,
            unidade_organizacional=self.unidade,
        )

    def _serie(self):
        return [
            {
                "protocolo": "111",
                "tipo": "contrato",
                "data": date(2025, 1, 1),
                "valor": Decimal("1000.00"),
                "periodicidade": "mensal",
                "natureza": None,
            },
            {
                "protocolo": "222",
                "tipo": "aditivo",
                "data": date(2025, 6, 1),
                "valor": Decimal("1200.00"),
                "periodicidade": "mensal",
                "natureza": None,
            },
        ]

    def test_cria_dois_eventos_novos_com_protocolos_distintos(self):
        resultado = eventos_financeiros.sincronizar(self.processo, self._serie())

        self.assertEqual(resultado, {"criados": 2, "ignorados": 0})
        self.assertEqual(
            EventoFinanceiro.objects.filter(processo=self.processo).count(), 2
        )

    def test_segunda_chamada_com_a_mesma_serie_e_idempotente(self):
        eventos_financeiros.sincronizar(self.processo, self._serie())

        resultado = eventos_financeiros.sincronizar(self.processo, self._serie())

        self.assertEqual(resultado, {"criados": 0, "ignorados": 2})
        self.assertEqual(
            EventoFinanceiro.objects.filter(processo=self.processo).count(), 2
        )

    def test_evento_manual_existente_nunca_e_sobrescrito(self):
        EventoFinanceiro.objects.create(
            processo=self.processo,
            protocolo_sei="111",
            tipo="contrato",
            valor=Decimal("999999.99"),
            origem=OrigemEventoFinanceiro.MANUAL,
            observacao="Lançado à mão pela equipe do PCA",
        )

        resultado = eventos_financeiros.sincronizar(self.processo, self._serie())

        evento = EventoFinanceiro.objects.get(processo=self.processo, protocolo_sei="111")
        self.assertEqual(evento.valor, Decimal("999999.99"))
        self.assertEqual(evento.origem, OrigemEventoFinanceiro.MANUAL)
        self.assertEqual(evento.observacao, "Lançado à mão pela equipe do PCA")
        # protocolo 111 já existia (ignorado); protocolo 222 é novo (criado).
        self.assertEqual(resultado, {"criados": 1, "ignorados": 1})

    def test_entrada_sem_valor_e_ignorada(self):
        serie = [
            {
                "protocolo": "333",
                "tipo": "contrato",
                "data": None,
                "valor": None,
                "periodicidade": None,
                "natureza": None,
            }
        ]

        resultado = eventos_financeiros.sincronizar(self.processo, serie)

        self.assertEqual(resultado, {"criados": 0, "ignorados": 1})
        self.assertFalse(EventoFinanceiro.objects.filter(processo=self.processo).exists())

    def test_entrada_sem_protocolo_estavel_e_ignorada_nunca_duplica(self):
        serie = [
            {
                "protocolo": None,
                "tipo": "contrato",
                "data": date(2025, 1, 1),
                "valor": Decimal("500.00"),
                "periodicidade": None,
                "natureza": None,
            },
            {
                "protocolo": "?",
                "tipo": "contrato",
                "data": date(2025, 1, 1),
                "valor": Decimal("500.00"),
                "periodicidade": None,
                "natureza": None,
            },
        ]

        resultado = eventos_financeiros.sincronizar(self.processo, serie)
        self.assertEqual(resultado, {"criados": 0, "ignorados": 2})
        self.assertFalse(EventoFinanceiro.objects.filter(processo=self.processo).exists())

        # execução repetida — continua sem criar nem duplicar.
        resultado_2 = eventos_financeiros.sincronizar(self.processo, serie)
        self.assertEqual(resultado_2, {"criados": 0, "ignorados": 2})
        self.assertFalse(EventoFinanceiro.objects.filter(processo=self.processo).exists())

    def test_duas_entradas_da_mesma_serie_com_mesmo_protocolo_nunca_duplicam(self):
        serie = [
            {
                "protocolo": "444",
                "tipo": "contrato",
                "data": date(2025, 1, 1),
                "valor": Decimal("700.00"),
                "periodicidade": None,
                "natureza": None,
            },
            {
                "protocolo": "444",
                "tipo": "aditivo",
                "data": date(2025, 2, 1),
                "valor": Decimal("750.00"),
                "periodicidade": None,
                "natureza": None,
            },
        ]

        resultado = eventos_financeiros.sincronizar(self.processo, serie)

        self.assertEqual(
            EventoFinanceiro.objects.filter(
                processo=self.processo, protocolo_sei="444"
            ).count(),
            1,
        )
        self.assertEqual(resultado, {"criados": 1, "ignorados": 1})

    # ------------- Fase 37 (M03/M04) --------------------------

    def test_evento_mensal_grava_periodicidade_mensal_e_valor_mensal(self):
        """M03 — `periodicidade == "mensal"` grava `valor_mensal` além de
        `valor` (hoje `sincronizar()` nunca preenchia `valor_mensal`)."""
        serie = [
            {
                "protocolo": "X",
                "tipo": "contrato",
                "data": date(2026, 1, 1),
                "valor": Decimal("1000.00"),
                "periodicidade": "mensal",
                "natureza": None,
                "instrumento": "05/2026",
            }
        ]

        eventos_financeiros.sincronizar(self.processo, serie)

        evento = EventoFinanceiro.objects.get(processo=self.processo, protocolo_sei="X")
        self.assertEqual(evento.periodicidade, "mensal")
        self.assertEqual(evento.valor_mensal, Decimal("1000.00"))
        self.assertEqual(evento.valor, Decimal("1000.00"))

    def test_sincronizar_grava_instrumento_no_evento(self):
        """spec §2.1/§8 — `instrumento` da entrada é gravado no evento."""
        serie = [
            {
                "protocolo": "X",
                "tipo": "contrato",
                "data": date(2026, 1, 1),
                "valor": Decimal("1000.00"),
                "periodicidade": "mensal",
                "natureza": None,
                "instrumento": "05/2026",
            }
        ]

        eventos_financeiros.sincronizar(self.processo, serie)

        evento = EventoFinanceiro.objects.get(processo=self.processo, protocolo_sei="X")
        self.assertEqual(evento.instrumento, "05/2026")

    def test_periodicidade_global_nunca_grava_valor_mensal(self):
        """M03 — `periodicidade == "global"` (ou `None`) nunca preenche
        `valor_mensal`; o rateio é do motor, não do serviço."""
        serie = [
            {
                "protocolo": "Y",
                "tipo": "contrato",
                "data": date(2026, 1, 1),
                "valor": Decimal("120000.00"),
                "periodicidade": "global",
                "natureza": None,
                "instrumento": "",
            }
        ]

        eventos_financeiros.sincronizar(self.processo, serie)

        evento = EventoFinanceiro.objects.get(processo=self.processo, protocolo_sei="Y")
        self.assertIsNone(evento.valor_mensal)
        self.assertEqual(evento.instrumento, "")

    def test_entrada_sem_instrumento_grava_cadeia_principal_vazia(self):
        """spec §8 — séries antigas sem a chave `instrumento` continuam
        funcionando, gravando `""` = cadeia "principal" (sem regressão)."""
        serie = [
            {
                "protocolo": "Z",
                "tipo": "contrato",
                "data": date(2026, 1, 1),
                "valor": Decimal("500.00"),
                "periodicidade": None,
                "natureza": None,
            }
        ]

        eventos_financeiros.sincronizar(self.processo, serie)

        evento = EventoFinanceiro.objects.get(processo=self.processo, protocolo_sei="Z")
        self.assertEqual(evento.instrumento, "")


class TestFiacaoSeiAplicar(ComandosSeiBase):
    """`sei_aplicar` chama `eventos_financeiros.sincronizar` depois de
    `aplicador.aplicar()`, só fora de `--simular`."""

    def _escrever_coleta(self, nome="coleta.json"):
        arquivo = self.base / nome
        arquivo.write_text(
            json.dumps(_coleta_item_15(), default=str), encoding="utf-8"
        )
        return arquivo

    def test_simular_nao_cria_nenhum_evento_financeiro(self):
        processo = self.processo(15)
        ProcessoSEI.objects.create(
            processo=processo, numero_sei="90796110000007.000015/2025-44"
        )
        arquivo = self._escrever_coleta()

        call_command("sei_aplicar", str(arquivo), "--simular", stdout=StringIO())

        self.assertFalse(EventoFinanceiro.objects.filter(processo=processo).exists())

    def test_sem_simular_cria_os_eventos_financeiros_do_item(self):
        processo = self.processo(15)
        ProcessoSEI.objects.create(
            processo=processo, numero_sei="90796110000007.000015/2025-44"
        )
        arquivo = self._escrever_coleta()

        call_command("sei_aplicar", str(arquivo), stdout=StringIO())

        eventos = EventoFinanceiro.objects.filter(processo=processo)
        self.assertEqual(eventos.count(), 1)
        self.assertEqual(eventos.first().protocolo_sei, "1290088")
        self.assertEqual(eventos.first().origem, OrigemEventoFinanceiro.ROBO)


class TestFiacaoSeiSincronizar(ComandosSeiBase):
    """`sei_sincronizar` chama `eventos_financeiros.sincronizar` depois de
    `aplicador.aplicar()`, só fora de `--simular` — mesma regra de
    `sei_aplicar`."""

    def test_sem_simular_cria_eventos_financeiros_de_todos_os_itens_com_serie(self):
        processo = self.processo(15)
        ProcessoSEI.objects.create(
            processo=processo, numero_sei="90796110000007.000015/2025-44"
        )

        with patch(
            "apps.pca.sei.coletor.coletar",
            return_value=_coleta_item_15(item_pca=15, exercicio=2026),
        ):
            with self.assertRaises(SystemExit) as contexto:
                call_command("sei_sincronizar", stdout=StringIO(), stderr=StringIO())

        self.assertEqual(contexto.exception.code, 0)
        eventos = EventoFinanceiro.objects.filter(processo=processo)
        self.assertEqual(eventos.count(), 1)
        self.assertEqual(eventos.first().protocolo_sei, "1290088")

    def test_simular_nao_cria_nenhum_evento_financeiro(self):
        processo = self.processo(15)
        ProcessoSEI.objects.create(
            processo=processo, numero_sei="90796110000007.000015/2025-44"
        )

        with patch(
            "apps.pca.sei.coletor.coletar",
            return_value=_coleta_item_15(item_pca=15, exercicio=2026),
        ):
            with self.assertRaises(SystemExit):
                call_command(
                    "sei_sincronizar", "--simular", stdout=StringIO(), stderr=StringIO()
                )

        self.assertFalse(EventoFinanceiro.objects.filter(processo=processo).exists())
