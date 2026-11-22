"""Testes do comando `sei_corrigir_eventos` (debug robo-valor-contratado-
item64, 20/10/2026 — decisão do usuário: correção pontual dos eventos
financeiros gravados pelas regras antigas, simulação por padrão e gravação
só com `--aplicar`).

Banco de teste e `SEI_DATA_DIR` em `tempfile` (`ComandosSeiBase`) — nunca o
SEI real nem o `data/sei` de verdade. A coleta é montada aqui com os casos
reais do relatório: item 64 (contrato 24/2024 gravado pelo valor MENSAL,
documentos ainda na extração 3), 81 (contrato assinado só pelo CFC), 87
(aditivo sem nenhuma assinatura), 115 (aditivo assinado só pelo CFC) e 18
(contrato com valores por item, sem global único)."""

import json
from datetime import date
from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.pca.models import EventoFinanceiro, OrigemEventoFinanceiro
from apps.pca.sei import execucoes
from apps.pca.sei.extracao import extrair_apostilamento, extrair_valor_documento
from apps.pca.tests.test_sei_comandos import ComandosSeiBase

_FIXTURES = Path(__file__).parent / "fixtures" / "sei"
_TEXTOS_64 = json.loads((_FIXTURES / "textos_item_64.json").read_text(encoding="utf-8"))
_TEXTOS_18 = json.loads((_FIXTURES / "textos_item_18.json").read_text(encoding="utf-8"))

_ESCRITA_SQL = ("INSERT", "UPDATE", "DELETE", "REPLACE")


def _doc(protocolo, tipo, *, cfc=True, externo=True, ultima=None, valor=None,
         apostilamento=None, texto=None, versao=3, numero=None):
    return {
        "protocolo": protocolo,
        "tipo": tipo,
        "conteudo": "html",
        "menciona_cfc": True,
        "numero_no_corpo": numero,
        "assinado_cfc": cfc,
        "assinado_externo": externo,
        "ultima_assinatura": ultima,
        "valor": valor,
        "apostilamento": apostilamento,
        "texto_corpo": texto,
        "versao_extracao": versao,
    }


def _valor(cifra, extenso, periodicidade=None):
    valor = {"cifra": cifra, "extenso": extenso, "confere": True}
    if periodicidade:
        valor["periodicidade"] = periodicidade
    return valor


def _processo_coletado(item, numero, *documentos):
    return {
        "numero": numero,
        "resultado": "ok",
        "item_pca": item,
        "exercicio": 2026,
        "documentos_contratuais": list(documentos),
    }


def _coleta():
    item_64 = _processo_coletado(
        64,
        "90796110000007.000010/2024-51",
        # Leitura antiga (extração 3) ainda no cache: o mensal.
        _doc(
            "0347594", "contrato", ultima="20/05/2024 15:25", numero="24/2024",
            valor=_valor(
                "2.213,93", "dois mil duzentos e treze reais e noventa e três centavos", "mensal"
            ),
            texto=_TEXTOS_64["contrato_0347594"],
        ),
        _doc(
            "0967338", "apostilamento", externo=False, ultima="13/08/2025 16:54",
            valor=extrair_valor_documento(_TEXTOS_64["apostilamento_0967338"]),
            apostilamento=extrair_apostilamento(_TEXTOS_64["apostilamento_0967338"]),
            texto=_TEXTOS_64["apostilamento_0967338"],
        ),
        # 2º termo: minuta, sem nenhuma assinatura.
        _doc(
            "1603102", "apostilamento", cfc=False, externo=False,
            apostilamento=extrair_apostilamento(_TEXTOS_64["apostilamento_1603102"]),
            texto=_TEXTOS_64["apostilamento_1603102"], versao=4,
        ),
    )
    item_81 = _processo_coletado(
        81,
        "90796110000033.000033/2026-19",
        _doc(
            "1386865", "contrato", externo=False, ultima="28/05/2026 17:00", numero="26/2026",
            valor=_valor("400.000,00", "quatrocentos mil reais"),
        ),
        # Também fora da série (só CFC), mas o evento dele é MANUAL — nunca
        # tocado.
        _doc(
            "1388398", "contrato", externo=False, ultima="29/05/2026 10:00", numero="27/2026",
            valor=_valor("50.000,00", "cinquenta mil reais"),
        ),
    )
    item_87 = _processo_coletado(
        87,
        "90796110000037.000008/2023-44",
        _doc(
            "0898600", "termo_aditivo", cfc=False, externo=False, numero="22/2023",
            valor=_valor(
                "1.328,71", "um mil trezentos e vinte e oito reais e setenta e um centavos", "mensal"
            ),
        ),
    )
    item_115 = _processo_coletado(
        115,
        "90796110000037.000115/2025-00",
        _doc(
            "1089996", "contrato", ultima="10/11/2025 10:00", numero="68/2025",
            valor=_valor("2.952,15", "dois mil novecentos e cinquenta e dois reais e quinze centavos"),
        ),
        _doc(
            "1601897", "termo_aditivo", externo=False, ultima="19/10/2026 11:05", numero="68/2025",
            valor=_valor(
                "3.064,70", "três mil sessenta e quatro reais e setenta centavos", "global"
            ),
        ),
    )
    item_18 = _processo_coletado(
        18,
        "90796110000037.000017/2025-05",
        _doc(
            "1513621", "contrato", ultima="24/08/2026 14:54", numero="39/2026",
            valor=_valor(
                "22.099,92", "vinte e dois mil noventa e nove reais e noventa e dois centavos",
                "anual",
            ),
            texto=_TEXTOS_18["contrato_1513621"],
        ),
    )
    return {
        "executado_em": "2026-10-20T04:00:00-03:00",
        "processos": [item_64, item_81, item_87, item_115, item_18],
    }


def _email_robo():
    return getattr(settings, "SEI_USUARIO_TECNICO_EMAIL", None) or "robo-sei@pca.local"


class CorrigirEventosBase(ComandosSeiBase):
    def setUp(self):
        super().setUp()
        self.p64 = self.processo(64, valor_contratado=Decimal("2213.93"))
        self.p81 = self.processo(81, valor_contratado=Decimal("400000.00"))
        self.p87 = self.processo(87, valor_contratado=Decimal("1328.71"))
        self.p115 = self.processo(115, valor_contratado=Decimal("3064.70"))
        self.p18 = self.processo(18, valor_contratado=Decimal("22099.92"))
        self.p99 = self.processo(99)

        self.ev64_mensal = self.evento(
            self.p64, "0347594", "contrato", "2213.93", "mensal", date(2024, 5, 20), mensal=True
        )
        self.ev64_fora = self.evento(self.p64, "9999999", "aditivo", "100.00", None, date(2023, 1, 1))
        self.ev81 = self.evento(self.p81, "1386865", "contrato", "400000.00", None, date(2026, 5, 28))
        self.ev81_manual = self.evento(
            self.p81, "1388398", "manual", "123.45", None, date(2026, 6, 1),
            origem=OrigemEventoFinanceiro.MANUAL,
        )
        self.ev87 = self.evento(
            self.p87, "0898600", "aditivo", "1328.71", "mensal", None, mensal=True
        )
        self.ev115_contrato = self.evento(
            self.p115, "1089996", "contrato", "2952.15", None, date(2025, 11, 10)
        )
        self.ev115_aditivo = self.evento(
            self.p115, "1601897", "aditivo", "3064.70", "global", date(2026, 10, 19)
        )
        self.ev18 = self.evento(self.p18, "1513621", "contrato", "22099.92", "anual", date(2026, 8, 24))
        self.ev99 = self.evento(self.p99, "5555555", "contrato", "1.00", None, date(2026, 1, 1))

        execucoes.gravar_coleta("2026-10-20-0400", _coleta())

    def evento(self, processo, protocolo, tipo, valor, periodicidade, data, *, mensal=False,
               origem=OrigemEventoFinanceiro.ROBO):
        return EventoFinanceiro.objects.create(
            processo=processo,
            protocolo_sei=protocolo,
            tipo=tipo,
            valor=Decimal(valor),
            valor_mensal=Decimal(valor) if mensal else None,
            periodicidade=periodicidade,
            data=data,
            origem=origem,
        )

    def rodar(self, *args):
        saida = StringIO()
        call_command("sei_corrigir_eventos", *args, stdout=saida)
        return saida.getvalue()

    def retrato(self):
        return sorted(
            EventoFinanceiro.objects.values_list(
                "pk", "processo_id", "protocolo_sei", "valor", "valor_mensal", "periodicidade",
                "tipo", "data", "origem",
            )
        )


class TestSimulacaoNaoGrava(CorrigirEventosBase):
    """Sem `--aplicar`: só o relatório — nenhum INSERT/UPDATE/DELETE, nenhum
    histórico, nenhum usuário técnico, nenhum lock."""

    def test_nenhuma_escrita_no_banco(self):
        retrato_antes = self.retrato()
        historicos_antes = EventoFinanceiro.history.count()
        usuarios_antes = get_user_model().objects.count()
        with CaptureQueriesContext(connection) as consultas:
            self.rodar()
        escritas = [
            q["sql"] for q in consultas.captured_queries
            if q["sql"].lstrip().upper().startswith(_ESCRITA_SQL)
        ]
        self.assertEqual(escritas, [])
        self.assertEqual(self.retrato(), retrato_antes)
        self.assertEqual(EventoFinanceiro.history.count(), historicos_antes)
        self.assertEqual(get_user_model().objects.count(), usuarios_antes)

    def test_nenhum_lock_nem_arquivo_novo(self):
        arquivos_antes = sorted(p.relative_to(self.base) for p in self.base.rglob("*"))
        self.rodar()
        self.assertFalse((execucoes.diretorio_base() / "em_execucao").exists())
        self.assertEqual(sorted(p.relative_to(self.base) for p in self.base.rglob("*")), arquivos_antes)

    def test_relatorio_lista_as_correcoes_com_motivo(self):
        saida = self.rodar()
        self.assertIn("SIMULAÇÃO (nada é gravado)", saida)
        self.assertIn(
            f"ALTERAR evento #{self.ev64_mensal.pk} (contrato 0347594, 20/05/2024, R$ 2.213,93, mensal)",
            saida,
        )
        self.assertIn("valor: R$ 2.213,93 → R$ 79.701,70", saida)
        self.assertIn("valor_mensal: R$ 2.213,93 → vazio", saida)
        self.assertIn("periodicidade: mensal → vazio", saida)
        self.assertIn("motivo: o valor gravado era o mensal do instrumento; vale o total/global", saida)
        self.assertIn(f"APAGAR  evento #{self.ev81.pk} (contrato 1386865", saida)
        self.assertIn("motivo: assinado só pelo CFC — falta a assinatura do contratado", saida)
        self.assertIn(f"APAGAR  evento #{self.ev87.pk} (aditivo 0898600", saida)
        self.assertIn("motivo: documento sem nenhuma assinatura (minuta)", saida)
        self.assertIn(f"APAGAR  evento #{self.ev115_aditivo.pk} (aditivo 1601897", saida)
        self.assertIn(f"APAGAR  evento #{self.ev18.pk} (contrato 1513621", saida)
        self.assertIn("motivo: valores por item, sem valor global único — preencher à mão", saida)
        self.assertIn(
            "(sem evento — a próxima sincronização cria) apostilamento 0967338, 13/08/2025, "
            "R$ 82.744,93, global",
            saida,
        )
        self.assertIn("Resumo: 4 evento(s) a apagar e 1 a alterar em 5 item(ns)", saida)
        self.assertIn("Modo simulação — nada foi gravado.", saida)

    def test_eventos_que_nao_mudam_nao_aparecem(self):
        saida = self.rodar()
        self.assertNotIn(f"#{self.ev115_contrato.pk} ", saida)
        self.assertNotIn(f"#{self.ev64_fora.pk} ", saida)
        self.assertNotIn(f"#{self.ev81_manual.pk} ", saida)
        self.assertNotIn(f"#{self.ev99.pk} ", saida)

    def test_minuta_do_segundo_termo_nao_vira_evento_faltante(self):
        self.assertNotIn("1603102", self.rodar())


class TestAplicarGrava(CorrigirEventosBase):
    def setUp(self):
        super().setUp()
        self.saida = self.rodar("--aplicar")

    def test_item_64_mensal_vira_o_total(self):
        self.ev64_mensal.refresh_from_db()
        self.assertEqual(self.ev64_mensal.valor, Decimal("79701.70"))
        self.assertIsNone(self.ev64_mensal.valor_mensal)
        self.assertIsNone(self.ev64_mensal.periodicidade)
        # Campos fora da correção ficam como estavam.
        self.assertEqual(self.ev64_mensal.data, date(2024, 5, 20))
        self.assertEqual(self.ev64_mensal.tipo, "contrato")

    def test_eventos_sem_assinatura_suficiente_e_por_itens_apagados(self):
        for evento in (self.ev81, self.ev87, self.ev115_aditivo, self.ev18):
            self.assertFalse(EventoFinanceiro.objects.filter(pk=evento.pk).exists(), evento)

    def test_o_que_nao_e_corrigivel_fica(self):
        for evento in (self.ev115_contrato, self.ev64_fora, self.ev81_manual, self.ev99):
            self.assertTrue(EventoFinanceiro.objects.filter(pk=evento.pk).exists(), evento)
        self.ev81_manual.refresh_from_db()
        self.assertEqual(self.ev81_manual.valor, Decimal("123.45"))

    def test_nao_cria_eventos_faltantes(self):
        self.assertFalse(
            EventoFinanceiro.objects.filter(processo=self.p64, protocolo_sei="0967338").exists()
        )

    def test_historico_da_alteracao_com_autor_e_motivo(self):
        registro = EventoFinanceiro.history.filter(id=self.ev64_mensal.pk).latest("history_id")
        self.assertEqual(registro.history_type, "~")
        self.assertEqual(registro.history_user.email, _email_robo())
        self.assertEqual(
            registro.history_change_reason,
            "sei_corrigir_eventos: o valor gravado era o mensal do instrumento; vale o total/global",
        )
        self.assertEqual(registro.valor, Decimal("79701.70"))

    def test_historico_das_exclusoes_com_autor_e_motivo(self):
        registro = EventoFinanceiro.history.filter(id=self.ev81.pk).latest("history_id")
        self.assertEqual(registro.history_type, "-")
        self.assertEqual(registro.history_user.email, _email_robo())
        self.assertEqual(
            registro.history_change_reason,
            "sei_corrigir_eventos: assinado só pelo CFC — falta a assinatura do contratado",
        )
        self.assertLessEqual(
            max(len(r.history_change_reason or "") for r in EventoFinanceiro.history.all()), 100
        )

    def test_valor_contratado_dos_processos_intocado(self):
        for processo, valor in (
            (self.p64, "2213.93"), (self.p81, "400000.00"), (self.p18, "22099.92"),
        ):
            processo.refresh_from_db()
            self.assertEqual(processo.valor_contratado, Decimal(valor))

    def test_lock_liberado_e_resumo(self):
        self.assertFalse((execucoes.diretorio_base() / "em_execucao").exists())
        self.assertIn("4 evento(s) apagado(s), 1 alterado(s)", self.saida)

    def test_segunda_execucao_nada_a_corrigir(self):
        saida = self.rodar("--aplicar")
        self.assertIn("Resumo: 0 evento(s) a apagar e 0 a alterar", saida)
        self.assertIn("Nada a corrigir.", saida)


class TestAplicarComRoboEmExecucao(CorrigirEventosBase):
    def test_recusa_sem_gravar(self):
        self.assertTrue(execucoes.adquirir_lock())
        retrato_antes = self.retrato()
        historicos_antes = EventoFinanceiro.history.count()
        with self.assertRaises(CommandError):
            self.rodar("--aplicar")
        self.assertEqual(self.retrato(), retrato_antes)
        self.assertEqual(EventoFinanceiro.history.count(), historicos_antes)
        # O lock é do robô — o comando nunca o apaga.
        self.assertTrue((execucoes.diretorio_base() / "em_execucao").exists())


class TestColetaAusente(ComandosSeiBase):
    def test_sem_coleta_erro_amigavel(self):
        with self.assertRaises(CommandError):
            call_command("sei_corrigir_eventos", stdout=StringIO())

    def test_coleta_explicita_inexistente(self):
        with self.assertRaises(CommandError):
            call_command(
                "sei_corrigir_eventos", "--coleta", str(self.base / "nao-existe.json"),
                stdout=StringIO(),
            )
