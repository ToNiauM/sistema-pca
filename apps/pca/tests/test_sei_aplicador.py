"""Testes de `apps.pca.sei.aplicador` (Fase 32) contra o banco de teste real. `aplicador.py` é CLIENTE de
`apps/pca/services.py` (nunca escreve `situacao` direto) — os
testes provam idempotência, as guardas de `cancelado`/`concluído`/
`transicao_manual`, `--simular` e o usuário técnico como autor.

`data/sei/estado.json` é lido/gravado por `apps.pca.sei.execucoes` durante
`aplicar()` — todo teste roda contra um diretório temporário
(`tempfile.TemporaryDirectory()` + `@override_settings(SEI_DATA_DIR=...)`),
nunca `BASE_DIR/data` de verdade."""

import json
import tempfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone as django_timezone

from apps.catalogo.models import (
    Categoria,
    Exercicio,
    InstrumentoContratual,
    Modalidade,
    SituacaoExercicio,
    SituacaoNormalizada,
    Tipo,
    Unidade,
)
from apps.pca.models import Acompanhamento, Estado, Processo, Situacao, TipoEvento
from apps.pca.sei import aplicador, execucoes
from apps.pca.sei.regras import Proposta, propor

_FIXTURES = Path(__file__).parent / "fixtures" / "sei"


def _carregar(nome):
    with open(_FIXTURES / nome, encoding="utf-8") as arquivo:
        return json.load(arquivo)["processos"]


def _campos_atuais_de(processo):
    """Espelha o que o plano (`sei_aplicar`/`sei_sincronizar`/
    `sei_atender`) monta a partir de um `Processo` real antes de chamar
    `propor()` — usado aqui só para provar idempotência (teste 'segunda
    aplicação'). Inclui os 6 campos de tramitação (Fase 32) + os 6 campos
    novos de execução contratual (Fase 33 /33-03)."""
    return {
        "data_assinatura_contrato": processo.data_assinatura_contrato,
        "numero_instrumento_contratual": processo.numero_instrumento_contratual,
        "instrumento_contratual_nome_normalizado": (
            processo.instrumento_contratual.nome_normalizado
            if processo.instrumento_contratual_id
            else None
        ),
        "valor_contratado": processo.valor_contratado,
        "data_recebimento_gelic": processo.data_recebimento_gelic,
        "fornecedor_razao_social": processo.fornecedor_razao_social,
        "fornecedor_cnpj": processo.fornecedor_cnpj,
        "modalidade_nome_normalizado": (
            processo.modalidade.nome_normalizado if processo.modalidade_id else None
        ),
        "numero_contratacao": processo.numero_contratacao,
        "vigencia_inicio": processo.vigencia_inicio,
        "vigencia_fim": processo.vigencia_fim,
        # Ver comentário em `sei_aplicar.py::campos_atuais_de`.
        "unidade_sei_atual": processo.unidade_sei_atual,
        "unidade_sei_atual_desde": processo.unidade_sei_atual_desde,
    }


class AplicadorBase(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._override = override_settings(SEI_DATA_DIR=self._tmp.name)
        self._override.enable()
        self.addCleanup(self._override.disable)

        # `pca.0008_backfill_exercicio_2026` já cria o exercício 2026 na
        # migração — `get_or_create` evita `UNIQUE constraint failed` contra
        # esse registro pré-existente no banco de teste.
        self.exercicio, _ = Exercicio.objects.get_or_create(
            ano=2026, defaults={"rotulo": "PCA 2026", "situacao": SituacaoExercicio.ABERTO}
        )
        self.tipo = Tipo.objects.create(nome="Serviço")
        self.categoria = Categoria.objects.create(nome="Serviços")
        self.unidade = Unidade.objects.create(nome="Presidência")
        for nome in ("Sem informação", "Concluído", "Em tramitação"):
            SituacaoNormalizada.objects.get_or_create(nome=nome)

    def processo(self, item, **overrides):
        valores = dict(
            item_pca=item,
            exercicio=self.exercicio,
            descricao_objeto="Objeto de teste",
            justificativa="Justificativa",
            tipo=self.tipo,
            categoria=self.categoria,
            unidade_organizacional=self.unidade,
            estado=Estado.ATIVO,
            situacao=Situacao.NO_PRAZO,
        )
        valores.update(overrides)
        return Processo.objects.create(**valores)

    def _campos_atuais_vazios(self):
        return {
            "data_assinatura_contrato": None,
            "numero_instrumento_contratual": None,
            "instrumento_contratual_nome_normalizado": None,
            "valor_contratado": None,
            "data_recebimento_gelic": None,
        }


class TestSobrescritaDeDataEValor(AplicadorBase):
    def test_grava_data_numero_instrumento_e_valor_do_item_3(self):
        processo = self.processo(3)
        proposta = propor(
            item_pca=3,
            exercicio=2026,
            campos_atuais=self._campos_atuais_vazios(),
            processos_coletados=_carregar("coleta_item_3.json"),
        )
        self.assertIn("data_assinatura_contrato", proposta.alteracoes)

        resumo = aplicador.aplicar([proposta])

        processo.refresh_from_db()
        self.assertEqual(processo.data_assinatura_contrato, date(2026, 2, 19))
        self.assertEqual(processo.numero_instrumento_contratual, "08/2026")
        self.assertEqual(processo.instrumento_contratual.nome, "Contrato")
        self.assertEqual(processo.valor_contratado, Decimal("18001.20"))
        self.assertEqual(resumo["itens_alterados"], 1)
        # Item 3 tem também um instrumento unilateral (protocolo 1094956,
        # assinado só pelo CFC) — gera pendência além da alteração. 3
        # eventos: situação -> concluído (aplicar_regras_automaticas),
        # evidência (este aplicador) e a pendência "unilateral:1094956".
        self.assertEqual(resumo["eventos_gravados"], 3)
        self.assertEqual(processo.acompanhamentos.count(), 3)
        self.assertEqual(processo.situacao, Situacao.CONCLUIDO)
        self.assertEqual(resumo["pendencias_novas"], 1)


class TestGuardaDeTransicaoManual(AplicadorBase):
    def test_situacao_preservada_e_pendencia_derivada(self):
        """(b) — só o recebimento no Gelic mudou, sem nenhum
        instrumento de contratação assinado por ambas as partes: a exceção
        de 18/09/2026 (`instrumento_assinado_por_ambos`) não se aplica, e a
        guarda de `transicao_manual` continua preservando a situação (o
        campo `data_assinatura_contrato`, quando muda, só chega junto de
        `instrumento_assinado_por_ambos=True` no fluxo real do robô — ver
        `TestExcecaoAssinaturaPorAmbosSobrepoeTransicaoManual` abaixo)."""
        processo = self.processo(5, situacao=Situacao.NO_PRAZO)
        Acompanhamento.objects.create(
            processo=processo,
            referencia_data=date(2026, 1, 5),
            origem_hash="hash-transicao-manual-teste",
            evento="Transição manual anterior",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO,
            situacao_informada="",
            situacao=SituacaoNormalizada.objects.get(nome="Sem informação"),
            transicao_manual=True,
        )
        processo.situacao_manual = True  # 29/09/2026 — a trava é o campo explícito
        processo.save(update_fields=["situacao_manual"])
        proposta = Proposta(
            item_pca=5,
            exercicio=2026,
            processo_principal="123",
            alteracoes={"data_recebimento_gelic": (None, date(2026, 2, 10))},
            evidencias=[],
            pendencias=[],
        )

        resumo = aplicador.aplicar([proposta])

        processo.refresh_from_db()
        self.assertEqual(processo.data_recebimento_gelic, date(2026, 2, 10))
        self.assertEqual(processo.situacao, Situacao.NO_PRAZO)
        chaves = {p["chave"] for p in resumo["pendencias"] if p["item"] == 5}
        self.assertIn("transicao_manual", chaves)
        self.assertEqual(resumo["pendencias_novas"], 1)


class TestExcecaoAssinaturaPorAmbosSobrepoeTransicaoManual(AplicadorBase):
    """Decisão do usuário em 18/09/2026, após o teste do item 105: "uma vez
    assinado, está concluído" — `instrumento_assinado_por_ambos=True`
    sobrepõe a guarda de `transicao_manual` (spec §5)."""

    def _com_transicao_manual(self, item):
        processo = self.processo(item, situacao=Situacao.NO_PRAZO)
        Acompanhamento.objects.create(
            processo=processo,
            referencia_data=date(2026, 1, 5),
            origem_hash=f"hash-transicao-manual-{item}",
            evento="Transição manual anterior",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO,
            situacao_informada="",
            situacao=SituacaoNormalizada.objects.get(nome="Sem informação"),
            transicao_manual=True,
        )
        return processo

    def test_a_concluido_com_evento_e_sem_pendencia_transicao_manual(self):
        processo = self._com_transicao_manual(105)
        proposta = Proposta(
            item_pca=105,
            exercicio=2026,
            processo_principal="123",
            alteracoes={"data_assinatura_contrato": (None, date(2026, 2, 19))},
            evidencias=["Data de assinatura: 19/02/2026 (antes: vazio)."],
            pendencias=[],
            instrumento_assinado_por_ambos=True,
        )

        # 29/09/2026 (decisão do usuário) — com a trava `situacao_manual` ligada, nem a assinatura
        # por ambos conclui: a situação manual fica e `situacao_regra` registra que as regras
        # concluiriam (aviso do Início). Sem a trava (histórico sem o campo), conclui pelas regras.
        processo.situacao_manual = True
        processo.save(update_fields=["situacao_manual"])
        aplicador.aplicar([proposta])

        processo.refresh_from_db()
        self.assertEqual(processo.situacao, Situacao.NO_PRAZO)
        self.assertEqual(processo.situacao_regra, Situacao.CONCLUIDO)
        textos = [ac.situacao_informada for ac in processo.acompanhamentos.all()]
        self.assertNotIn(aplicador.OBSERVACAO_ASSINATURA_POR_AMBOS, textos)

    def test_b_sem_trava_conclui_pelas_regras(self):
        processo = self._com_transicao_manual(108)
        proposta = Proposta(
            item_pca=108,
            exercicio=2026,
            processo_principal="123",
            alteracoes={"data_assinatura_contrato": (None, date(2026, 2, 19))},
            evidencias=["Data de assinatura: 19/02/2026 (antes: vazio)."],
            pendencias=[],
            instrumento_assinado_por_ambos=True,
        )

        aplicador.aplicar([proposta])

        processo.refresh_from_db()
        self.assertEqual(processo.situacao, Situacao.CONCLUIDO)
        self.assertEqual(processo.situacao_regra, "")

    def test_c_cancelado_intocado_mesmo_com_assinatura_por_ambos(self):
        processo = self.processo(106, estado=Estado.CANCELADO)
        antes = processo.atualizado_em
        proposta = Proposta(
            item_pca=106,
            exercicio=2026,
            processo_principal="123",
            alteracoes={"data_assinatura_contrato": (None, date(2026, 2, 19))},
            evidencias=["Data de assinatura: 19/02/2026 (antes: vazio)."],
            pendencias=[],
            instrumento_assinado_por_ambos=True,
        )

        aplicador.aplicar([proposta])

        processo.refresh_from_db()
        self.assertIsNone(processo.data_assinatura_contrato)
        self.assertEqual(processo.atualizado_em, antes)
        self.assertEqual(processo.acompanhamentos.count(), 0)

    def test_d_segunda_aplicacao_zero_eventos(self):
        processo = self._com_transicao_manual(107)
        primeira = Proposta(
            item_pca=107,
            exercicio=2026,
            processo_principal="123",
            alteracoes={"data_assinatura_contrato": (None, date(2026, 2, 19))},
            evidencias=["Data de assinatura: 19/02/2026 (antes: vazio)."],
            pendencias=[],
            instrumento_assinado_por_ambos=True,
        )

        aplicador.aplicar([primeira])

        processo.refresh_from_db()
        self.assertEqual(processo.situacao, Situacao.CONCLUIDO)
        eventos_apos_primeira = processo.acompanhamentos.count()
        self.assertGreater(eventos_apos_primeira, 0)

        # Segunda varredura: o SEI confirma a mesma assinatura já gravada —
        # `alteracoes` chega vazio (nada mudou desde a primeira aplicação),
        # exatamente como `propor()` recalcularia a partir dos campos atuais.
        segunda = Proposta(
            item_pca=107,
            exercicio=2026,
            processo_principal="123",
            alteracoes={},
            evidencias=[],
            pendencias=[],
            instrumento_assinado_por_ambos=True,
        )

        resumo = aplicador.aplicar([segunda])

        processo.refresh_from_db()
        self.assertEqual(processo.acompanhamentos.count(), eventos_apos_primeira)
        self.assertEqual(resumo["eventos_gravados"], 0)


class TestConcluidoNaoRebaixado(AplicadorBase):
    def test_campos_gravados_situacao_permanece_concluido(self):
        processo = self.processo(7, situacao=Situacao.CONCLUIDO)
        proposta = Proposta(
            item_pca=7,
            exercicio=2026,
            processo_principal="123",
            alteracoes={"valor_contratado": (None, Decimal("500.00"))},
            evidencias=["Valor contratado: R$ 500,00 (antes: vazio)."],
            pendencias=[],
        )

        aplicador.aplicar([proposta])

        processo.refresh_from_db()
        self.assertEqual(processo.valor_contratado, Decimal("500.00"))
        self.assertEqual(processo.situacao, Situacao.CONCLUIDO)


class TestCanceladoIntocado(AplicadorBase):
    def test_nenhum_campo_muda_zero_acompanhamento_novo(self):
        processo = self.processo(9, estado=Estado.CANCELADO)
        antes = processo.atualizado_em
        proposta = Proposta(
            item_pca=9,
            exercicio=2026,
            processo_principal="123",
            alteracoes={"valor_contratado": (None, Decimal("999.00"))},
            evidencias=["Valor contratado: R$ 999,00 (antes: vazio)."],
            pendencias=[("unilateral:1", "assinado só pelo CFC")],
        )

        aplicador.aplicar([proposta])

        processo.refresh_from_db()
        self.assertIsNone(processo.valor_contratado)
        self.assertEqual(processo.atualizado_em, antes)
        self.assertEqual(processo.acompanhamentos.count(), 0)


class TestSegundaAplicacaoZeroEventos(AplicadorBase):
    def test_reaplicar_a_partir_do_estado_atualizado_nao_grava_nada(self):
        processo = self.processo(3)
        primeira = propor(
            item_pca=3,
            exercicio=2026,
            campos_atuais=self._campos_atuais_vazios(),
            processos_coletados=_carregar("coleta_item_3.json"),
        )
        aplicador.aplicar([primeira])
        processo.refresh_from_db()
        eventos_apos_primeira = processo.acompanhamentos.count()
        self.assertGreater(eventos_apos_primeira, 0)

        segunda = propor(
            item_pca=3,
            exercicio=2026,
            campos_atuais=_campos_atuais_de(processo),
            processos_coletados=_carregar("coleta_item_3.json"),
        )
        self.assertEqual(segunda.alteracoes, {})

        resumo = aplicador.aplicar([segunda])

        processo.refresh_from_db()
        self.assertEqual(processo.acompanhamentos.count(), eventos_apos_primeira)
        self.assertEqual(resumo["eventos_gravados"], 0)
        self.assertEqual(resumo["itens_alterados"], 0)


class TestPendenciaAvisadaUmaVez(AplicadorBase):
    def test_segunda_aplicacao_da_mesma_pendencia_nao_repete(self):
        processo = self.processo(11)
        proposta = Proposta(
            item_pca=11,
            exercicio=2026,
            processo_principal="123",
            alteracoes={},
            evidencias=[],
            pendencias=[("unilateral:1204703", "Instrumento assinado só pelo CFC.")],
        )

        resumo_1 = aplicador.aplicar([proposta])
        self.assertEqual(resumo_1["pendencias_novas"], 1)
        self.assertEqual(resumo_1["eventos_gravados"], 1)
        eventos_apos_primeira = processo.acompanhamentos.count()
        self.assertEqual(eventos_apos_primeira, 1)
        self.assertEqual(
            execucoes.carregar_estado_pendencias(), {"2026-11": ["unilateral:1204703"]}
        )

        resumo_2 = aplicador.aplicar([proposta])

        self.assertEqual(resumo_2["pendencias_novas"], 0)
        self.assertEqual(resumo_2["eventos_gravados"], 0)
        self.assertEqual(processo.acompanhamentos.count(), eventos_apos_primeira)
        self.assertEqual(
            execucoes.carregar_estado_pendencias(), {"2026-11": ["unilateral:1204703"]}
        )


class TestSimularNaoGrava(AplicadorBase):
    def test_calcula_tudo_e_nao_grava_nada(self):
        processo = self.processo(13)
        antes = processo.atualizado_em
        proposta = Proposta(
            item_pca=13,
            exercicio=2026,
            processo_principal="123",
            alteracoes={"valor_contratado": (None, Decimal("321.00"))},
            evidencias=["Valor contratado: R$ 321,00 (antes: vazio)."],
            pendencias=[("unilateral:99", "Instrumento assinado só pelo CFC.")],
        )

        resumo = aplicador.aplicar([proposta], simular=True)

        processo.refresh_from_db()
        self.assertIsNone(processo.valor_contratado)
        self.assertEqual(processo.atualizado_em, antes)
        self.assertEqual(processo.acompanhamentos.count(), 0)
        self.assertEqual(execucoes.carregar_estado_pendencias(), {})
        self.assertEqual(resumo["itens_alterados"], 1)
        self.assertEqual(resumo["pendencias_novas"], 1)
        self.assertEqual(resumo["eventos_gravados"], 0)

    def test_simular_nao_cria_usuario_tecnico(self):
        # M13 — `_usuario_tecnico()` fazia `get_or_create`
        # no topo de `aplicar()`, ANTES de checar `simular`: mesmo uma
        # varredura só de leitura gravava um usuário no banco.
        Usuario = get_user_model()
        antes = Usuario.objects.count()
        processo = self.processo(14)
        proposta = Proposta(
            item_pca=14,
            exercicio=2026,
            processo_principal="123",
            alteracoes={"valor_contratado": (None, Decimal("321.00"))},
            evidencias=["Valor contratado: R$ 321,00 (antes: vazio)."],
            pendencias=[],
        )

        aplicador.aplicar([proposta], simular=True)

        self.assertEqual(Usuario.objects.count(), antes)


class TestUsuarioTecnicoComoAutor(AplicadorBase):
    def test_historico_gravado_pelo_usuario_tecnico_inativo(self):
        processo = self.processo(17)
        proposta = Proposta(
            item_pca=17,
            exercicio=2026,
            processo_principal="123",
            alteracoes={"valor_contratado": (None, Decimal("111.00"))},
            evidencias=["Valor contratado: R$ 111,00 (antes: vazio)."],
            pendencias=[],
        )

        aplicador.aplicar([proposta])

        processo.refresh_from_db()
        email_esperado = getattr(
            settings, "SEI_USUARIO_TECNICO_EMAIL", None
        ) or "robo-sei@pca.local"
        self.assertEqual(processo.history.latest().history_user.email, email_esperado)
        usuario_tecnico = get_user_model().objects.get(email=email_esperado)
        self.assertFalse(usuario_tecnico.is_active)
        self.assertFalse(usuario_tecnico.has_usable_password())


class TestCamposDeExecucaoContratual(AplicadorBase):
    """(Fase 33): os 6 campos novos de execução
    contratual são gravados no `Processo` real pelo mesmo mecanismo já
    existente — `modalidade` resolvida contra o catálogo JÁ EXISTENTE
    (`_CAMPOS_FK_POR_ROTULO["modalidade"]`, nunca cria registro
    novo). `regras.propor()` chamado de verdade contra `coleta_item_6.json`,
não `Proposta` construída à mão."""

    def setUp(self):
        super().setUp()
        for nome in (
            "Adesão a ARP",
            "Concorrência",
            "Credenciamento",
            "Dispensa Com Disputa",
            "Dispensa Sem Disputa",
            "Inexigibilidade",
            "Pregão Eletrônico",
        ):
            Modalidade.objects.get_or_create(nome=nome)

    def _campos_atuais_execucao_vazios(self):
        campos = self._campos_atuais_vazios()
        campos.update(
            {
                "fornecedor_razao_social": None,
                "fornecedor_cnpj": None,
                "modalidade_nome_normalizado": None,
                "numero_contratacao": None,
                "vigencia_inicio": None,
                "vigencia_fim": None,
            }
        )
        return campos

    def test_grava_os_6_campos_novos_do_item_6(self):
        processo = self.processo(6)
        proposta = propor(
            item_pca=6,
            exercicio=2026,
            campos_atuais=self._campos_atuais_execucao_vazios(),
            processos_coletados=_carregar("coleta_item_6.json"),
        )

        aplicador.aplicar([proposta])

        processo.refresh_from_db()
        self.assertEqual(
            processo.fornecedor_razao_social, "Engemax Engenharia e Comércio Ltda"
        )
        self.assertEqual(processo.fornecedor_cnpj, "12.345.678/0001-95")
        self.assertEqual(processo.modalidade.nome, "Dispensa Com Disputa")
        self.assertEqual(processo.numero_contratacao, "90027/2024")
        self.assertEqual(processo.vigencia_inicio, date(2026, 1, 11))
        self.assertEqual(processo.vigencia_fim, date(2027, 1, 10))

    def test_modalidade_resolve_contra_catalogo_existente_nunca_cria_novo(self):
        processo = self.processo(6)
        total_antes = Modalidade.objects.count()
        proposta = propor(
            item_pca=6,
            exercicio=2026,
            campos_atuais=self._campos_atuais_execucao_vazios(),
            processos_coletados=_carregar("coleta_item_6.json"),
        )

        aplicador.aplicar([proposta])

        self.assertEqual(Modalidade.objects.count(), total_antes)
        processo.refresh_from_db()
        self.assertIsInstance(processo.modalidade, Modalidade)

    def test_modalidade_editada_so_em_caixa_no_admin_nao_derruba_a_proposta_seguinte(self):
        # Achado dados M4 (QA 30/09/2026): editar só caixa/acento do rótulo
        # no Admin não pode derrubar a próxima proposta do robô com
        # IntegrityError (`get_or_create(nome=...)` × `nome_normalizado`
        # único).
        Modalidade.objects.filter(nome_normalizado="dispensa com disputa").update(
            nome="DISPENSA COM DISPUTA"
        )
        processo = self.processo(6)
        total_antes = Modalidade.objects.count()
        proposta = propor(
            item_pca=6,
            exercicio=2026,
            campos_atuais=self._campos_atuais_execucao_vazios(),
            processos_coletados=_carregar("coleta_item_6.json"),
        )

        aplicador.aplicar([proposta])

        self.assertEqual(Modalidade.objects.count(), total_antes)
        processo.refresh_from_db()
        self.assertEqual(processo.modalidade.nome, "DISPENSA COM DISPUTA")

    def test_segunda_aplicacao_a_partir_do_processo_atualizado_e_idempotente(self):
        processo = self.processo(6)
        primeira = propor(
            item_pca=6,
            exercicio=2026,
            campos_atuais=self._campos_atuais_execucao_vazios(),
            processos_coletados=_carregar("coleta_item_6.json"),
        )
        aplicador.aplicar([primeira])
        processo.refresh_from_db()

        segunda = propor(
            item_pca=6,
            exercicio=2026,
            campos_atuais=_campos_atuais_de(processo),
            processos_coletados=_carregar("coleta_item_6.json"),
        )

        self.assertEqual(segunda.alteracoes, {})

    def test_simular_nao_grava_nenhum_dos_6_campos_novos(self):
        processo = self.processo(6)
        proposta = propor(
            item_pca=6,
            exercicio=2026,
            campos_atuais=self._campos_atuais_execucao_vazios(),
            processos_coletados=_carregar("coleta_item_6.json"),
        )

        aplicador.aplicar([proposta], simular=True)

        processo.refresh_from_db()
        self.assertIsNone(processo.fornecedor_razao_social)
        self.assertIsNone(processo.fornecedor_cnpj)
        self.assertIsNone(processo.modalidade)
        self.assertIsNone(processo.numero_contratacao)
        self.assertIsNone(processo.vigencia_inicio)
        self.assertIsNone(processo.vigencia_fim)


class TestSeriesDeValores(AplicadorBase):
    """(Fase 35): `aplicador.aplicar` devolve
    `resumo["series"]` a partir de `Proposta.serie_valores` — presente nos
    dois modos (`simular=True/False`), nunca gravado no banco; itens sem
    série não aparecem na chave (ausente, não lista vazia)."""

    def test_resumo_series_reflete_serie_valores_da_proposta(self):
        self.processo(15)
        proposta = propor(
            item_pca=15,
            exercicio=2026,
            campos_atuais=self._campos_atuais_vazios(),
            processos_coletados=_carregar("coleta_item_15.json"),
        )
        self.assertTrue(proposta.serie_valores)

        resumo = aplicador.aplicar([proposta])

        self.assertEqual(resumo["series"]["2026-15"], proposta.serie_valores)

    def test_resumo_series_preenchido_tambem_em_simular(self):
        processo = self.processo(15)
        proposta = propor(
            item_pca=15,
            exercicio=2026,
            campos_atuais=self._campos_atuais_vazios(),
            processos_coletados=_carregar("coleta_item_15.json"),
        )

        resumo = aplicador.aplicar([proposta], simular=True)

        self.assertEqual(resumo["series"]["2026-15"], proposta.serie_valores)
        processo.refresh_from_db()
        self.assertIsNone(processo.valor_contratado)

    def test_item_sem_serie_valores_nao_aparece_em_series(self):
        self.processo(49)
        proposta = Proposta(
            item_pca=49,
            exercicio=2026,
            processo_principal="123",
            alteracoes={},
            evidencias=[],
            pendencias=[],
        )

        resumo = aplicador.aplicar([proposta])

        self.assertNotIn("2026-49", resumo["series"])

    def test_dois_exercicios_abertos_mesmo_item_cada_um_recebe_sua_propria_serie(self):
        """Achado dados A3 (ALTO, QA 30/09/2026) — com "Gerar itens de N+1"
        dois `Exercicio` podem estar ABERTOS ao mesmo tempo; o mesmo nº de
        item em 2026 e 2027 nunca pode misturar série de valores."""
        exercicio_2027, _ = Exercicio.objects.get_or_create(
            ano=2027, defaults={"rotulo": "PCA 2027", "situacao": SituacaoExercicio.ABERTO}
        )
        self.processo(15)
        self.processo(15, exercicio=exercicio_2027)

        serie_2026 = [
            {"protocolo": "1", "tipo": "contrato", "data": date(2026, 1, 1),
             "valor": Decimal("100.00"), "periodicidade": None, "natureza": None,
             "instrumento": "01/2026"},
        ]
        serie_2027 = [
            {"protocolo": "2", "tipo": "contrato", "data": date(2027, 1, 1),
             "valor": Decimal("200.00"), "periodicidade": None, "natureza": None,
             "instrumento": "01/2027"},
            {"protocolo": "3", "tipo": "termo_aditivo", "data": date(2027, 6, 1),
             "valor": Decimal("50.00"), "periodicidade": None, "natureza": None,
             "instrumento": "01/2027"},
        ]
        proposta_2026 = Proposta(
            item_pca=15, exercicio=2026, processo_principal="1",
            alteracoes={}, evidencias=[], pendencias=[], serie_valores=serie_2026,
        )
        proposta_2027 = Proposta(
            item_pca=15, exercicio=2027, processo_principal="2",
            alteracoes={}, evidencias=[], pendencias=[], serie_valores=serie_2027,
        )

        resumo = aplicador.aplicar([proposta_2026, proposta_2027])

        self.assertNotEqual(resumo["series"]["2026-15"], resumo["series"]["2027-15"])
        self.assertEqual(resumo["series"]["2026-15"], serie_2026)
        self.assertEqual(resumo["series"]["2027-15"], serie_2027)


class TestUnidadeSeiAtual(AplicadorBase):
    """`_aplicar_campo` já é genérico (`setattr`), os
    dois campos novos não precisam de entrada em `_CAMPOS_FK_POR_ROTULO`:
    teste de regressão, sem mudança de código em `aplicador.py`."""

    def test_unidade_sei_atual_e_desde_gravados_juntos(self):
        processo = self.processo(3)
        desde = django_timezone.make_aware(datetime(2026, 9, 19, 10, 30))
        proposta = Proposta(
            item_pca=3,
            exercicio=2026,
            processo_principal="123",
            alteracoes={
                "unidade_sei_atual": ("", "GELIC / PROJUR"),
                "unidade_sei_atual_desde": (None, desde),
            },
            evidencias=[],
            pendencias=[],
        )

        aplicador.aplicar([proposta])

        processo.refresh_from_db()
        self.assertEqual(processo.unidade_sei_atual, "GELIC / PROJUR")
        self.assertEqual(processo.unidade_sei_atual_desde, desde)


class TestAplicadorNaoRepeteFrase(AplicadorBase):
    """Diagnóstico: `regras.py:440` acrescenta a frase de
    assinatura a `evidencias` SEMPRE que existe instrumento vencedor (ela
    descreve ESTADO, não mudança); `aplicador.py` gravava
    `" ".join(proposta.evidencias)` toda vez que `proposta.alteracoes` não
    estava vazio, bastando outro campo mudar (ex. `unidade_sei_atual`) para
    a mesma frase voltar à timeline. Medição no banco real em 22/09/2026:
    443 acompanhamentos automáticos, 21 linhas redundantes. Correção: cada
    frase é filtrada contra as observações automáticas já registradas do
    mesmo processo antes de gravar; sobrando zero frases novas, nenhum
    `Acompanhamento` novo nasce (mas `itens_alterados` continua contando —
    o campo mudou de fato)."""

    def _registrar_automatico(self, processo, texto):
        Acompanhamento.objects.create(
            processo=processo,
            referencia_data=date(2026, 1, 1),
            origem_hash=f"hash-existente-{processo.pk}-{hash(texto)}",
            tipo_evento=TipoEvento.AUTOMATICO,
            situacao_informada=texto,
            situacao=SituacaoNormalizada.objects.get(nome="Sem informação"),
        )

    def test_evidencia_identica_a_ja_registrada_nao_grava_novo_acompanhamento(self):
        processo = self.processo(20)
        frase = (
            "Termo Aditivo 03/2024 (doc. 1227659) assinado pelo CFC em "
            "09/02/2026 e pelo contratado em 10/02/2026."
        )
        self._registrar_automatico(processo, frase)
        eventos_antes = processo.acompanhamentos.count()

        proposta = Proposta(
            item_pca=20,
            exercicio=2026,
            processo_principal="123",
            alteracoes={"valor_contratado": (None, Decimal("1.00"))},
            evidencias=[frase],
            pendencias=[],
        )

        resumo = aplicador.aplicar([proposta])

        processo.refresh_from_db()
        self.assertEqual(processo.acompanhamentos.count(), eventos_antes)
        self.assertEqual(resumo["eventos_gravados"], 0)
        self.assertEqual(resumo["itens_alterados"], 1)
        self.assertEqual(processo.valor_contratado, Decimal("1.00"))

    def test_uma_frase_nova_e_uma_repetida_grava_so_a_nova(self):
        processo = self.processo(21)
        frase_repetida = "Frase já registrada antes."
        self._registrar_automatico(processo, frase_repetida)
        eventos_antes = processo.acompanhamentos.count()
        frase_nova = "Frase inédita desta varredura."

        proposta = Proposta(
            item_pca=21,
            exercicio=2026,
            processo_principal="123",
            alteracoes={"valor_contratado": (None, Decimal("2.00"))},
            evidencias=[frase_repetida, frase_nova],
            pendencias=[],
        )

        resumo = aplicador.aplicar([proposta])

        processo.refresh_from_db()
        self.assertEqual(processo.acompanhamentos.count(), eventos_antes + 1)
        self.assertEqual(resumo["eventos_gravados"], 1)
        novo = processo.acompanhamentos.latest("id")
        self.assertEqual(novo.situacao_informada, frase_nova)

    def test_duas_execucoes_seguidas_da_mesma_proposta_e_idempotente(self):
        processo = self.processo(22)
        proposta = Proposta(
            item_pca=22,
            exercicio=2026,
            processo_principal="123",
            alteracoes={"valor_contratado": (None, Decimal("3.00"))},
            evidencias=["Valor contratado: R$ 3,00 (antes: vazio)."],
            pendencias=[],
        )

        aplicador.aplicar([proposta])
        processo.refresh_from_db()
        eventos_apos_primeira = processo.acompanhamentos.count()
        self.assertGreater(eventos_apos_primeira, 0)

        resumo_segunda = aplicador.aplicar([proposta])

        processo.refresh_from_db()
        self.assertEqual(processo.acompanhamentos.count(), eventos_apos_primeira)
        self.assertEqual(resumo_segunda["eventos_gravados"], 0)

    def test_pendencia_repetida_com_estado_json_vazio_nao_regrava(self):
        processo = self.processo(23)
        texto_pendencia = "Instrumento assinado só pelo CFC."
        self._registrar_automatico(processo, f"Pendência SEI: {texto_pendencia}")
        eventos_antes = processo.acompanhamentos.count()
        self.assertEqual(execucoes.carregar_estado_pendencias(), {})

        proposta = Proposta(
            item_pca=23,
            exercicio=2026,
            processo_principal="123",
            alteracoes={},
            evidencias=[],
            pendencias=[("unilateral:999", texto_pendencia)],
        )

        resumo = aplicador.aplicar([proposta])

        processo.refresh_from_db()
        self.assertEqual(processo.acompanhamentos.count(), eventos_antes)
        self.assertEqual(resumo["pendencias_novas"], 0)

    def test_evidencia_inedita_continua_gravando_normal(self):
        processo = self.processo(24)
        eventos_antes = processo.acompanhamentos.count()
        frase_inedita = (
            "Contrato 09/2026 (doc. 999999) assinado pelo CFC em "
            "01/01/2026 e pelo contratado em 02/01/2026."
        )

        proposta = Proposta(
            item_pca=24,
            exercicio=2026,
            processo_principal="123",
            alteracoes={"valor_contratado": (None, Decimal("4.00"))},
            evidencias=[frase_inedita],
            pendencias=[],
        )

        resumo = aplicador.aplicar([proposta])

        processo.refresh_from_db()
        self.assertEqual(processo.acompanhamentos.count(), eventos_antes + 1)
        self.assertEqual(resumo["eventos_gravados"], 1)
        novo = processo.acompanhamentos.latest("id")
        self.assertEqual(novo.situacao_informada, frase_inedita)


class TestOrigemEUsuarioDaExtensao(AplicadorBase):
    """Fase 42 — `aplicar()` ganha `usuario=`/
    `origem=` opcionais e 100% retrocompatíveis: nenhum chamador em
    produção (`sei_aplicar.py`/`sei_atender.py`/`sei_sincronizar.py`) passa
    os novos kwargs hoje, então nenhum deles muda de comportamento."""

    def test_a_sem_kwargs_novos_continua_usando_usuario_tecnico_e_texto_robo(self):
        # `aplicar_regras_automaticas` (passo 3) é mockado como no-op: dado
        # `data_assinatura_contrato`, a regra viva (`situacao_por_eventos`)
        # SEMPRE conclui sozinha quando `situacao_manual=False` (confirmado
        # em runtime — nenhum chamador de produção hoje alcança o passo 3b
        # por este caminho), então isolar o passo 3 é o único jeito de
        # exercitar a seleção de texto (robô/extensão) que ESTE plano muda,
        # sem depender de uma combinação de regras de outro módulo.
        processo = self.processo(201, situacao=Situacao.NO_PRAZO)
        proposta = Proposta(
            item_pca=201,
            exercicio=2026,
            processo_principal="123",
            alteracoes={"data_assinatura_contrato": (None, date(2026, 2, 19))},
            evidencias=["Data de assinatura: 19/02/2026 (antes: vazio)."],
            pendencias=[],
            instrumento_assinado_por_ambos=True,
        )

        with patch.object(aplicador, "aplicar_regras_automaticas", return_value=None):
            aplicador.aplicar([proposta])

        processo.refresh_from_db()
        self.assertEqual(processo.situacao, Situacao.CONCLUIDO)
        email_esperado = getattr(
            settings, "SEI_USUARIO_TECNICO_EMAIL", None
        ) or "robo-sei@pca.local"
        self.assertEqual(processo.history.first().history_user.email, email_esperado)
        textos = [ac.situacao_informada for ac in processo.acompanhamentos.all()]
        self.assertIn(aplicador.OBSERVACAO_ASSINATURA_POR_AMBOS, textos)

    def test_b_com_usuario_e_origem_extensao_grava_usuario_real_e_texto_extensao(self):
        Usuario = get_user_model()
        usuario_real = Usuario.objects.create_user(
            email="extensao.usuario@cfc.org.br", password="senha-segura-123"
        )
        processo = self.processo(202, situacao=Situacao.NO_PRAZO)
        proposta = Proposta(
            item_pca=202,
            exercicio=2026,
            processo_principal="123",
            alteracoes={"data_assinatura_contrato": (None, date(2026, 2, 19))},
            evidencias=["Data de assinatura: 19/02/2026 (antes: vazio)."],
            pendencias=[],
            instrumento_assinado_por_ambos=True,
        )

        with patch.object(aplicador, "aplicar_regras_automaticas", return_value=None):
            aplicador.aplicar([proposta], usuario=usuario_real, origem="extensao")

        processo.refresh_from_db()
        self.assertEqual(processo.situacao, Situacao.CONCLUIDO)
        self.assertEqual(processo.history.first().history_user, usuario_real)
        email_tecnico = getattr(
            settings, "SEI_USUARIO_TECNICO_EMAIL", None
        ) or "robo-sei@pca.local"
        self.assertNotEqual(processo.history.first().history_user.email, email_tecnico)
        textos = [ac.situacao_informada for ac in processo.acompanhamentos.all()]
        self.assertTrue(any("extensão SEI Pro" in texto for texto in textos))
        self.assertNotIn(aplicador.OBSERVACAO_ASSINATURA_POR_AMBOS, textos)

    def test_c_simular_com_usuario_passado_nao_cria_usuario_nem_grava(self):
        Usuario = get_user_model()
        antes = Usuario.objects.count()
        processo = self.processo(203, situacao=Situacao.NO_PRAZO)
        proposta = Proposta(
            item_pca=203,
            exercicio=2026,
            processo_principal="123",
            alteracoes={"data_assinatura_contrato": (None, date(2026, 2, 19))},
            evidencias=["Data de assinatura: 19/02/2026 (antes: vazio)."],
            pendencias=[],
            instrumento_assinado_por_ambos=True,
        )

        aplicador.aplicar([proposta], simular=True, usuario=None, origem="extensao")

        processo.refresh_from_db()
        self.assertIsNone(processo.data_assinatura_contrato)
        self.assertEqual(processo.acompanhamentos.count(), 0)
        self.assertEqual(Usuario.objects.count(), antes)
