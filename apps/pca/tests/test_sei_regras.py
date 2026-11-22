"""Testes do módulo puro `apps.pca.sei.regras` (Fase 32). `unittest.TestCase` simples, sem banco, sem Django —
mesmo padrão de `test_regras_situacao.py`/`test_sei_extenso.py`.

Cada teste usa uma fixture derivada de `evidencia-amostra.json` (protocolos,
rótulos, `ultima_assinatura`, `numero_no_corpo`, `recebimento_gelic_delic`
reais do spike notas internas do projeto) e um `campos_atuais`
montado a partir da coluna "PCA" da tabela de `RETOMADA.md`. Os 8 casos
cobrem o §9 da spec (itens 1, 3, 6, 10, 16, 39, 49, inexistente).
"""

import json
import unittest
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from django.utils import timezone as django_timezone

from apps.pca.sei.extracao import extrair_apostilamento, extrair_valor_documento
from apps.pca.sei.regras import propor, unidade_atual

_FIXTURES = Path(__file__).parent / "fixtures" / "sei"


def _carregar(nome):
    with open(_FIXTURES / nome, encoding="utf-8") as arquivo:
        return json.load(arquivo)["processos"]


class TestItem1InstrumentoUnilateralXBilateral(unittest.TestCase):
    """Item 1: contrato 03/2026 (protocolo 1204703) assinado só pelo CFC —
    não conclui. Contrato 11/2026 (protocolo 1229914), assinado
    pelas duas partes, é quem vence e grava a data de assinatura."""

    def setUp(self):
        self.processos = _carregar("coleta_item_1.json")
        self.campos_atuais = {
            "data_assinatura_contrato": None,
            "numero_instrumento_contratual": None,
            "instrumento_contratual_nome_normalizado": None,
            "valor_contratado": None,
            "data_recebimento_gelic": date(2024, 7, 3),
        }
        self.proposta = propor(
            item_pca=1,
            exercicio=2024,
            campos_atuais=self.campos_atuais,
            processos_coletados=self.processos,
        )

    def test_data_assinatura_vem_do_contrato_bilateral_11_2026(self):
        self.assertEqual(
            self.proposta.alteracoes["data_assinatura_contrato"],
            (None, date(2026, 2, 11)),
        )

    def test_pendencia_unilateral_do_contrato_03_2026(self):
        chaves = [chave for chave, _texto in self.proposta.pendencias]
        self.assertIn("unilateral:1204703", chaves)

    def test_documentos_externos_nunca_entram_na_disputa(self):
        # Os dois "Contrato vigente" externos (CAU/ES, TJ/TO) não geram
        # pendência nem concorrem: prova que conteudo != "html" é excluído
        # já no filtro-base do passo 3.
        chaves = [chave for chave, _texto in self.proposta.pendencias]
        self.assertNotIn("unilateral:0393857", chaves)
        self.assertNotIn("unilateral:0822179", chaves)


class TestItem3Referencia(unittest.TestCase):
    """Item 3: caso de referência. A assinatura já registrada no PCA
    (19/02/2026) já bate com a última assinatura do SEI — propor() não deve
    reescrever um campo que já está correto (idempotência). O valor
    contratado, esse sim, ainda não estava confirmado no PCA."""

    def setUp(self):
        self.processos = _carregar("coleta_item_3.json")
        self.campos_atuais = {
            "data_assinatura_contrato": date(2026, 2, 19),
            "numero_instrumento_contratual": None,
            "instrumento_contratual_nome_normalizado": None,
            "valor_contratado": None,
            "data_recebimento_gelic": date(2025, 9, 5),
        }
        self.proposta = propor(
            item_pca=3,
            exercicio=2025,
            campos_atuais=self.campos_atuais,
            processos_coletados=self.processos,
        )

    def test_data_assinatura_ja_correta_nao_reaparece_em_alteracoes(self):
        self.assertNotIn("data_assinatura_contrato", self.proposta.alteracoes)

    def test_valor_contratado_alterado_para_18001_20(self):
        self.assertEqual(
            self.proposta.alteracoes["valor_contratado"],
            (None, Decimal("18001.20")),
        )

    def test_processo_principal_e_o_numero_036_2025_81(self):
        self.assertEqual(
            self.proposta.processo_principal, "90796110000007.000036/2025-81"
        )


class TestItem6AditivoMaisRecenteQueOContrato(unittest.TestCase):
    """Item 6: contrato 01/2025 (R$ 37.000,00, sem valor extraído nesta
    fixture) x 1º Termo Aditivo (R$ 38.731,90, assinatura mais recente).
    O aditivo vence a disputa de valor mesmo o contrato original não tendo
    cláusula de preço lida — prova o critério "assinatura mais recente"
    (§4.3 ponto 2)."""

    def setUp(self):
        self.processos = _carregar("coleta_item_6.json")
        self.campos_atuais = {
            "data_assinatura_contrato": date(2025, 12, 9),
            "numero_instrumento_contratual": None,
            "instrumento_contratual_nome_normalizado": None,
            "valor_contratado": Decimal("37000.00"),
            "data_recebimento_gelic": date(2025, 11, 28),
        }
        self.proposta = propor(
            item_pca=6,
            exercicio=2024,
            campos_atuais=self.campos_atuais,
            processos_coletados=self.processos,
        )

    def test_valor_contratado_reflete_o_aditivo_nao_o_contrato_original(self):
        self.assertEqual(
            self.proposta.alteracoes["valor_contratado"],
            (Decimal("37000.00"), Decimal("38731.90")),
        )


class TestItem10TresContratosOMaisRecenteVence(unittest.TestCase):
    """Item 10: três contratos (05, 06, 07/2026) assinados no mesmo dia,
    horários distintos. O critério de desempate é `ultima_assinatura` mais
    recente — nesta fixture real não há empate: 06/2026 (protocolo 1208777,
    17:02) vence por 25 minutos sobre os outros dois (16:37)."""

    def setUp(self):
        self.processos = _carregar("coleta_item_10.json")
        self.campos_atuais = {
            "data_assinatura_contrato": None,
            "numero_instrumento_contratual": None,
            "instrumento_contratual_nome_normalizado": None,
            "valor_contratado": None,
            "data_recebimento_gelic": date(2025, 8, 28),
        }
        self.proposta = propor(
            item_pca=10,
            exercicio=2025,
            campos_atuais=self.campos_atuais,
            processos_coletados=self.processos,
        )

    def test_instrumento_vencedor_e_o_contrato_06_2026(self):
        self.assertEqual(
            self.proposta.alteracoes["numero_instrumento_contratual"],
            (None, "06/2026"),
        )

    def test_processo_principal_e_o_unico_processo_do_item(self):
        self.assertEqual(
            self.proposta.processo_principal, "90796110000007.000027/2025-90"
        )


class TestItem16ProcessoPrincipalComInstrumento(unittest.TestCase):
    """Item 16: dois processos SEI. O `...018/2025-41` não tem nenhum
    documento contratual; o `...021/2020-51` tem o Contrato 08/2021 e seis
    termos aditivos. O processo principal precisa ser o que TEM instrumento
    — nunca o fallback por "primeiro andamento mais recente" quando um dos
    processos do item já resolve a disputa do passo 3."""

    def setUp(self):
        self.processos = _carregar("coleta_item_16.json")
        self.campos_atuais = {
            "data_assinatura_contrato": date(2026, 2, 25),
            "numero_instrumento_contratual": None,
            "instrumento_contratual_nome_normalizado": None,
            "valor_contratado": None,
            "data_recebimento_gelic": date(2025, 11, 3),
        }
        self.proposta = propor(
            item_pca=16,
            exercicio=2025,
            campos_atuais=self.campos_atuais,
            processos_coletados=self.processos,
        )

    def test_processo_principal_e_o_processo_com_instrumento(self):
        self.assertEqual(
            self.proposta.processo_principal, "90796110000037.000021/2020-51"
        )

    def test_ultimo_termo_aditivo_sem_numero_no_corpo_vira_pendencia(self):
        # O Termo Aditivo de 24/02/2026 (protocolo 1245824) é o vencedor por
        # assinatura mais recente, mas veio sem número no corpo do
        # documento — sem_numero:<protocolo>, sem alterar o campo.
        chaves = [chave for chave, _texto in self.proposta.pendencias]
        self.assertIn("sem_numero:1245824", chaves)
        self.assertNotIn("numero_instrumento_contratual", self.proposta.alteracoes)


class TestItem39ApostilamentoNuncaViraInstrumentoDeContratacao(unittest.TestCase):
    """Item 39: nove candidatos elegíveis a instrumento de contratação
    (contratos + termos aditivos) e quatro apostilamentos, todos assinados
    só pelo CFC. O 3º Termo Aditivo (13/03/2026) é o instrumento de
    contratação vencedor — data e número vêm dele. O valor contratado, esse
    sim, vem do apostilamento de 28/05/2026 (assinatura mais recente entre
    TODOS os documentos com valor extraído, apostilamento incluído)."""

    def setUp(self):
        self.processos = _carregar("coleta_item_39.json")
        self.campos_atuais = {
            "data_assinatura_contrato": None,
            "numero_instrumento_contratual": None,
            "instrumento_contratual_nome_normalizado": None,
            "valor_contratado": None,
            "data_recebimento_gelic": date(2026, 2, 2),
        }
        self.proposta = propor(
            item_pca=39,
            exercicio=2023,
            campos_atuais=self.campos_atuais,
            processos_coletados=self.processos,
        )

    def test_valor_contratado_vem_do_apostilamento(self):
        self.assertEqual(
            self.proposta.alteracoes["valor_contratado"][1], Decimal("54156.00")
        )

    def test_numero_e_data_de_assinatura_vem_do_terceiro_termo_aditivo(self):
        self.assertEqual(
            self.proposta.alteracoes["numero_instrumento_contratual"],
            (None, "09/2023"),
        )
        self.assertEqual(
            self.proposta.alteracoes["data_assinatura_contrato"],
            (None, date(2026, 3, 13)),
        )

    def test_apostilamentos_nunca_geram_pendencia_unilateral(self):
        # Apostilamento é ato unilateral por natureza (§4.1) — não entra na
        # disputa do passo 3 nem gera "unilateral:<protocolo>".
        chaves = [chave for chave, _texto in self.proposta.pendencias]
        self.assertNotIn("unilateral:1383390", chaves)
        self.assertNotIn("unilateral:0464615", chaves)
        self.assertNotIn("unilateral:0464616", chaves)
        self.assertNotIn("unilateral:0368909", chaves)
        self.assertNotIn("unilateral:0368630", chaves)


def _campos_atuais_execucao_vazios(**overrides):
    """Retrato vazio dos 6 campos de tramitação (Fase 32) + 6 campos novos
    de execução contratual (Fase 33) — mesmo formato que os 3
    comandos (`sei_aplicar`/`sei_sincronizar`/`sei_atender`) montam a partir de um `Processo` real."""
    base = {
        "data_assinatura_contrato": None,
        "numero_instrumento_contratual": None,
        "instrumento_contratual_nome_normalizado": None,
        "valor_contratado": None,
        "data_recebimento_gelic": None,
        "fornecedor_razao_social": None,
        "fornecedor_cnpj": None,
        "modalidade_nome_normalizado": None,
        "numero_contratacao": None,
        "vigencia_inicio": None,
        "vigencia_fim": None,
    }
    base.update(overrides)
    return base


class TestItem6PrecedenciaContratoEAditivo(unittest.TestCase):
    """Item 6 (Fase 33): razão social/CNPJ/nº da
    contratação/modalidade vêm do CONTRATO (protocolo 0661569); vigência
    vem do ADITIVO (protocolo 1141522, `ultima_assinatura` mais recente que
    o contrato) — prova a precedência "contrato preenche tudo; aditivo só
    atualiza valor e vigência"."""

    def setUp(self):
        self.processos = _carregar("coleta_item_6.json")
        self.campos_atuais = _campos_atuais_execucao_vazios(
            data_assinatura_contrato=date(2025, 12, 9),
            valor_contratado=Decimal("37000.00"),
            data_recebimento_gelic=date(2025, 11, 28),
        )
        self.proposta = propor(
            item_pca=6,
            exercicio=2024,
            campos_atuais=self.campos_atuais,
            processos_coletados=self.processos,
        )

    def test_razao_social_e_cnpj_vem_do_contrato(self):
        self.assertEqual(
            self.proposta.alteracoes["fornecedor_razao_social"],
            (None, "Engemax Engenharia e Comércio Ltda"),
        )
        self.assertEqual(
            self.proposta.alteracoes["fornecedor_cnpj"],
            (None, "12.345.678/0001-95"),
        )

    def test_numero_contratacao_e_modalidade_vem_do_contrato(self):
        self.assertEqual(
            self.proposta.alteracoes["numero_contratacao"], (None, "90027/2024")
        )
        self.assertEqual(
            self.proposta.alteracoes["modalidade"][1], "Dispensa Com Disputa"
        )

    def test_vigencia_vem_do_aditivo_mais_recente(self):
        self.assertEqual(
            self.proposta.alteracoes["vigencia_inicio"], (None, date(2026, 1, 11))
        )
        self.assertEqual(
            self.proposta.alteracoes["vigencia_fim"], (None, date(2027, 1, 10))
        )


class TestItem2PessoaFisicaSemCnpj(unittest.TestCase):
    """Item 2: contratado pessoa física, sem CNPJ — grava só a
    razão social; `fornecedor_cnpj` nunca aparece em `alteracoes` nem gera
    pendência `contratado_invalido` (CNPJ ausente não é erro)."""

    def setUp(self):
        self.processos = _carregar("coleta_item_2.json")
        self.campos_atuais = _campos_atuais_execucao_vazios()
        self.proposta = propor(
            item_pca=2,
            exercicio=2026,
            campos_atuais=self.campos_atuais,
            processos_coletados=self.processos,
        )

    def test_razao_social_gravada_sem_cnpj(self):
        self.assertEqual(
            self.proposta.alteracoes["fornecedor_razao_social"],
            (None, "[pessoa física omitida]"),
        )
        self.assertNotIn("fornecedor_cnpj", self.proposta.alteracoes)
        chaves = [chave for chave, _texto in self.proposta.pendencias]
        self.assertFalse(any(chave.startswith("contratado_invalido:") for chave in chaves))

    def test_numero_contratacao_e_modalidade(self):
        self.assertEqual(
            self.proposta.alteracoes["numero_contratacao"], (None, "383500-6/2026")
        )
        self.assertEqual(
            self.proposta.alteracoes["modalidade"][1], "Dispensa Sem Disputa"
        )

    def test_vigencia(self):
        self.assertEqual(
            self.proposta.alteracoes["vigencia_inicio"], (None, date(2026, 3, 13))
        )
        self.assertEqual(
            self.proposta.alteracoes["vigencia_fim"], (None, date(2028, 3, 12))
        )


class TestItem11CorrigeRazaoSocialDoPca(unittest.TestCase):
    """Item 11: o PCA já tem a razão social com o erro de digitação
    ("TELEBRAS -T ELECOMUNICAÇÕES BRASILEIRAS S.A") — o SEI sobrescreve
    (mesmo princípio da Fase 32) com o texto correto do contrato."""

    def setUp(self):
        self.processos = _carregar("coleta_item_11.json")
        self.campos_atuais = _campos_atuais_execucao_vazios(
            fornecedor_razao_social="TELEBRAS -T ELECOMUNICAÇÕES BRASILEIRAS S.A",
        )
        self.proposta = propor(
            item_pca=11,
            exercicio=2026,
            campos_atuais=self.campos_atuais,
            processos_coletados=self.processos,
        )

    def test_razao_social_corrigida(self):
        self.assertEqual(
            self.proposta.alteracoes["fornecedor_razao_social"],
            (
                "TELEBRAS -T ELECOMUNICAÇÕES BRASILEIRAS S.A",
                "TELEBRAS - TELECOMUNICAÇÕES BRASILEIRAS S.A",
            ),
        )

    def test_numero_contratacao_e_modalidade(self):
        self.assertEqual(
            self.proposta.alteracoes["numero_contratacao"], (None, "383500-02/2026")
        )
        self.assertEqual(
            self.proposta.alteracoes["modalidade"][1], "Dispensa Sem Disputa"
        )

    def test_vigencia(self):
        self.assertEqual(
            self.proposta.alteracoes["vigencia_inicio"], (None, date(2026, 2, 6))
        )
        self.assertEqual(
            self.proposta.alteracoes["vigencia_fim"], (None, date(2031, 2, 5))
        )


class TestItem15ApostilamentoNuncaAlteraVigencia(unittest.TestCase):
    """Item 15: apostilamento (protocolo 1290088) é mais recente que o
    contrato e vence a disputa de valor, mas nunca fornece vigência — só
    contrato/termo aditivo entram na disputa de vigência."""

    def setUp(self):
        self.processos = _carregar("coleta_item_15.json")
        self.campos_atuais = _campos_atuais_execucao_vazios()
        self.proposta = propor(
            item_pca=15,
            exercicio=2025,
            campos_atuais=self.campos_atuais,
            processos_coletados=self.processos,
        )

    def test_vigencia_vem_do_contrato(self):
        self.assertEqual(
            self.proposta.alteracoes["vigencia_inicio"], (None, date(2025, 6, 1))
        )
        self.assertEqual(
            self.proposta.alteracoes["vigencia_fim"], (None, date(2026, 5, 31))
        )

    def test_valor_contratado_vem_do_apostilamento(self):
        self.assertEqual(
            self.proposta.alteracoes["valor_contratado"][1], Decimal("45000.00")
        )


class TestModalidadeNaoMapeada(unittest.TestCase):
    """Modalidade fora do mapa fechado do catálogo — pendência
    `modalidade_nao_mapeada:<protocolo>`, `modalidade` nunca entra em
    `alteracoes` (nunca cria registro novo no catálogo)."""

    def setUp(self):
        self.processos = [
            {
                "numero": "90796110000007.000090/2026-01",
                "resultado": "ok",
                "documentos_contratuais": [
                    {
                        "protocolo": "9000001",
                        "conteudo": "html",
                        "cancelado": False,
                        "menciona_cfc": True,
                        "tipo": "contrato",
                        "numero_no_corpo": "90/2026",
                        "assinado_cfc": True,
                        "assinado_externo": True,
                        "ultima_assinatura": "01/03/2026 10:00",
                        "contratado": {
                            "razao_social": "Fornecedor Modalidade Desconhecida Ltda",
                            "cnpj": "07.526.557/0001-00",
                        },
                        "procedencia": {
                            "modalidade_texto": "Chamamento Público",
                            "numero": "90/2026",
                            "modalidade_catalogo": None,
                        },
                        "vigencia": None,
                        "prorrogacao": None,
                        "valor": None,
                    }
                ],
            }
        ]
        self.proposta = propor(
            item_pca=90,
            exercicio=2026,
            campos_atuais=_campos_atuais_execucao_vazios(),
            processos_coletados=self.processos,
        )

    def test_pendencia_modalidade_nao_mapeada(self):
        chaves = [chave for chave, _texto in self.proposta.pendencias]
        self.assertIn("modalidade_nao_mapeada:9000001", chaves)

    def test_modalidade_nunca_entra_em_alteracoes(self):
        self.assertNotIn("modalidade", self.proposta.alteracoes)

    def test_razao_social_e_cnpj_continuam_gravados(self):
        # A modalidade não mapeada não bloqueia o contratado — são blocos
        # independentes.
        self.assertIn("fornecedor_razao_social", self.proposta.alteracoes)
        self.assertIn("fornecedor_cnpj", self.proposta.alteracoes)


class TestTextoPendenciaModalidade(unittest.TestCase):
    """O texto da pendência nunca mostra "?": separa
    modalidade ausente no texto do instrumento (contrato em PDF do item 58,
    02/10/2026) de modalidade encontrada mas fora do catálogo."""

    def _texto(self, procedencia):
        caso = TestModalidadeNaoMapeada()
        caso.setUp()
        processos = caso.processos
        processos[0]["documentos_contratuais"][0]["procedencia"] = procedencia
        proposta = propor(
            item_pca=90,
            exercicio=2026,
            campos_atuais=_campos_atuais_execucao_vazios(),
            processos_coletados=processos,
        )
        return dict(proposta.pendencias)["modalidade_nao_mapeada:9000001"], proposta

    def test_modalidade_ausente_no_texto(self):
        texto, _ = self._texto({"modalidade_texto": None, "numero": None, "modalidade_catalogo": None})
        self.assertNotIn("?", texto)
        self.assertEqual(
            texto,
            "Modalidade da contratação não encontrada no texto do instrumento 9000001; "
            "preencher manualmente.",
        )

    def test_modalidade_fora_do_catalogo(self):
        texto, _ = self._texto(
            {"modalidade_texto": "Chamamento Público", "numero": "90/2026", "modalidade_catalogo": None}
        )
        self.assertNotIn("?", texto)
        self.assertEqual(
            texto,
            "Modalidade \u201cChamamento Público\u201d do instrumento 9000001 não corresponde "
            "a nenhuma modalidade do catálogo; preencher manualmente.",
        )

    def test_evidencia_de_procedencia_sem_interrogacao(self):
        _, proposta = self._texto(
            {"modalidade_texto": None, "numero": "90/2026", "modalidade_catalogo": None}
        )
        procedencia = [e for e in proposta.evidencias if e.startswith("Procedência")]
        self.assertEqual(procedencia, ["Procedência: nº da contratação 90/2026."])


class TestCnpjInvalidoBloqueiaRazaoECnpj(unittest.TestCase):
    """CNPJ que não passa no checksum de `validar_digitos_cnpj` bloqueia a
    gravação de razão social E CNPJ — pendência
    `contratado_invalido:<protocolo>`, mesmo com a razão social presente na
    fixture."""

    def setUp(self):
        self.processos = [
            {
                "numero": "90796110000007.000091/2026-02",
                "resultado": "ok",
                "documentos_contratuais": [
                    {
                        "protocolo": "9000002",
                        "conteudo": "html",
                        "cancelado": False,
                        "menciona_cfc": True,
                        "tipo": "contrato",
                        "numero_no_corpo": "91/2026",
                        "assinado_cfc": True,
                        "assinado_externo": True,
                        "ultima_assinatura": "02/03/2026 10:00",
                        "contratado": {
                            "razao_social": "Fornecedor CNPJ Inválido Ltda",
                            # Último dígito verificador trocado — checksum falha.
                            "cnpj": "07.526.557/0001-01",
                        },
                        "procedencia": None,
                        "vigencia": None,
                        "prorrogacao": None,
                        "valor": None,
                    }
                ],
            }
        ]
        self.proposta = propor(
            item_pca=91,
            exercicio=2026,
            campos_atuais=_campos_atuais_execucao_vazios(),
            processos_coletados=self.processos,
        )

    def test_pendencia_contratado_invalido(self):
        chaves = [chave for chave, _texto in self.proposta.pendencias]
        self.assertIn("contratado_invalido:9000002", chaves)

    def test_razao_social_nao_gravada(self):
        self.assertNotIn("fornecedor_razao_social", self.proposta.alteracoes)

    def test_cnpj_nao_gravado(self):
        self.assertNotIn("fornecedor_cnpj", self.proposta.alteracoes)


class TestEvidenciaContratadoSemRazaoSocial(unittest.TestCase):
    """Achado periferia nº 5 (QA 30/09/2026): quando só o CNPJ muda e a
    razão social não foi extraída, a evidência de contratado nunca pode
    interpolar a string "None" no lugar do nome (acompanhamentos reais
    887/906/915/1046 gravados com "Contratado: None (CNPJ …)")."""

    def test_evidencia_sem_razao_social_nunca_mostra_none(self):
        processos = [
            {
                "numero": "90796110000007.000092/2026-03",
                "resultado": "ok",
                "documentos_contratuais": [
                    {
                        "protocolo": "9000003",
                        "conteudo": "html",
                        "cancelado": False,
                        "menciona_cfc": True,
                        "tipo": "contrato",
                        "numero_no_corpo": "92/2026",
                        "assinado_cfc": True,
                        "assinado_externo": True,
                        "ultima_assinatura": "02/03/2026 10:00",
                        "contratado": {
                            "razao_social": None,
                            "cnpj": "12.345.678/0001-95",
                        },
                        "procedencia": None,
                        "vigencia": None,
                        "prorrogacao": None,
                        "valor": None,
                    }
                ],
            }
        ]
        campos_atuais = _campos_atuais_execucao_vazios(fornecedor_cnpj="98.765.432/0001-10")
        proposta = propor(
            item_pca=92,
            exercicio=2026,
            campos_atuais=campos_atuais,
            processos_coletados=processos,
        )
        self.assertIn("fornecedor_cnpj", proposta.alteracoes)
        self.assertTrue(proposta.evidencias)
        for evidencia in proposta.evidencias:
            self.assertNotIn("None", evidencia)


class TestItem10ContratosDistintosSomaValorEPendenciaContratado(unittest.TestCase):
    """(18/09/2026, "fortemente aprovado"): item 10 tem três
    contratos assinados por ambos com CNPJs diferentes (05, 06, 07/2026) —
    `valor_contratado` é a SOMA dos três; razão social/CNPJ NÃO são
    gravados (pendência `multiplos_contratados:<protocolos>`); modalidade/
    nº da contratação continuam vindo do mais recente (06/2026), sem
    mudança de comportamento em relação ao que já existia antes."""

    def setUp(self):
        self.processos = _carregar("coleta_item_10.json")
        self.campos_atuais = _campos_atuais_execucao_vazios(
            data_recebimento_gelic=date(2025, 8, 28),
        )
        self.proposta = propor(
            item_pca=10,
            exercicio=2025,
            campos_atuais=self.campos_atuais,
            processos_coletados=self.processos,
        )

    def test_valor_contratado_e_a_soma_dos_tres_contratos(self):
        self.assertEqual(
            self.proposta.alteracoes["valor_contratado"],
            (None, Decimal("60000.00")),
        )

    def test_razao_social_e_cnpj_nao_sao_gravados(self):
        self.assertNotIn("fornecedor_razao_social", self.proposta.alteracoes)
        self.assertNotIn("fornecedor_cnpj", self.proposta.alteracoes)

    def test_pendencia_multiplos_contratados(self):
        chaves = dict(self.proposta.pendencias)
        chave_esperada = "multiplos_contratados:1208622,1208777,1208781"
        self.assertIn(chave_esperada, chaves)
        self.assertIn("3 contratos distintos", chaves[chave_esperada])
        self.assertIn("05/2026, 06/2026 e 07/2026", chaves[chave_esperada])

    def test_modalidade_e_numero_contratacao_vem_do_mais_recente(self):
        self.assertEqual(
            self.proposta.alteracoes["numero_contratacao"], (None, "90050/2025")
        )
        self.assertEqual(
            self.proposta.alteracoes["modalidade"][1], "Pregão Eletrônico"
        )


class TestItem49SemContratoNadaAFazer(unittest.TestCase):
    """Item 49: processo encontrado, mas sem nenhum documento contratual.
    Nada preenchido no PCA para confirmar (nenhum campo de execução
    contratual já tinha valor) e a situação do SEI já estava "autuado" —
    uma varredura sobre este item não produz nenhuma alteração nos campos
    de execução contratual nem pendência nova.

    `unidade_sei_atual`/`unidade_sei_atual_desde`
    (passo 7b) SÃO propostos mesmo sem contrato — a unidade atual deriva de
    `unidade_atual()`, não da disputa de instrumento contratual do passo 6.
    Esta fixture é anterior (sem a chave `ultima_remessa`
    em `marcos`) e não tem nenhuma linha "Processo remetido pela unidade X"
    (só `Processo público gerado`/andamentos internos em GECER), então cai
    no fallback `marcos["primeiro"]` — GECER, 18/08/2026 08:46 (a unidade
    que gerou o processo; `primeiro` e `ultimo` têm a MESMA unidade nesta
    fixture — o processo nunca saiu de GECER —, então o resultado do teste
    não muda em relação à regra anterior, só a explicação de por quê)."""

    def setUp(self):
        self.processos = _carregar("coleta_item_49.json")
        self.campos_atuais = {
            "data_assinatura_contrato": None,
            "numero_instrumento_contratual": None,
            "instrumento_contratual_nome_normalizado": None,
            "valor_contratado": None,
            "data_recebimento_gelic": None,
        }
        self.proposta = propor(
            item_pca=49,
            exercicio=2026,
            campos_atuais=self.campos_atuais,
            processos_coletados=self.processos,
        )

    def test_alteracoes_so_tem_unidade_sei_atual(self):
        self.assertEqual(
            set(self.proposta.alteracoes),
            {"unidade_sei_atual", "unidade_sei_atual_desde"},
        )

    def test_unidade_sei_atual_cai_no_fallback_do_ultimo_andamento(self):
        self.assertEqual(
            self.proposta.alteracoes["unidade_sei_atual"], ("", "GECER")
        )

    def test_pendencias_vazio(self):
        self.assertEqual(self.proposta.pendencias, [])


class TestNumeroInexistente(unittest.TestCase):
    """Número de controle que a pesquisa rápida do SEI não abriu
    (`resultado: "nao_encontrado"`) — pendência, nunca exceção, e nenhuma
    alteração no PCA."""

    def setUp(self):
        self.processos = _carregar("coleta_inexistente.json")
        self.proposta = propor(
            item_pca=999,
            exercicio=2025,
            campos_atuais={
                "data_assinatura_contrato": None,
                "numero_instrumento_contratual": None,
                "instrumento_contratual_nome_normalizado": None,
                "valor_contratado": None,
                "data_recebimento_gelic": None,
            },
            processos_coletados=self.processos,
        )

    def test_pendencia_nao_encontrado(self):
        self.assertEqual(
            self.proposta.pendencias,
            [
                (
                    "nao_encontrado:90796110000007.000999/2025-00",
                    "Processo SEI 90796110000007.000999/2025-00 não encontrado ou sem acesso.",
                )
            ],
        )

    def test_alteracoes_vazio(self):
        self.assertEqual(self.proposta.alteracoes, {})


class TestListaVaziaEFalhaTotalDeColeta(unittest.TestCase):
    """Passos 1 e 9 do §4: item ativo sem nenhum número SEI cadastrado, e
    item cuja coleta falhou em TODOS os números (erro de rede/timeout, não
    "não encontrado")."""

    def test_lista_vazia_gera_pendencia_sem_numero_sei(self):
        proposta = propor(
            item_pca=1, exercicio=2026, campos_atuais={}, processos_coletados=[]
        )
        self.assertEqual(
            proposta.pendencias,
            [
                (
                    "sem_numero_sei",
                    "Item ativo sem nenhum número de processo SEI cadastrado.",
                )
            ],
        )
        self.assertEqual(proposta.alteracoes, {})

    def test_todos_os_processos_com_erro_devolve_erro_sem_pendencias(self):
        proposta = propor(
            item_pca=1,
            exercicio=2026,
            campos_atuais={},
            processos_coletados=[
                {"numero": "1", "resultado": "erro"},
                {"numero": "2", "resultado": "erro"},
            ],
        )
        self.assertEqual(proposta.erro, "falha ao coletar todos os números SEI do item")
        self.assertEqual(proposta.alteracoes, {})
        self.assertEqual(proposta.pendencias, [])


# ---------------------------- Fase 35: apostilamento -------------
# Fixtures sintéticas inline (mesmo padrão de `TestModalidadeNaoMapeada`/
# `TestCnpjInvalidoBloqueiaRazaoECnpj` acima) — coerentes com o contrato real
# de `extrair_apostilamento` (`apps/pca/sei/extracao.py`): `natureza`
# reajuste/repactuacao/dotacao/outro, `valor_novo` {"cifra","extenso",
# "confere"}|None, `periodicidade` mensal/anual/global/None, `trecho` texto
# casado.


def _doc_contrato(
    protocolo, numero_no_corpo, cifra, extenso, ultima_assinatura,
    *, tipo="contrato", confere=True,
):
    return {
        "protocolo": protocolo,
        "conteudo": "html",
        "cancelado": False,
        "menciona_cfc": True,
        "tipo": tipo,
        "numero_no_corpo": numero_no_corpo,
        "assinado_cfc": True,
        "assinado_externo": True,
        "ultima_assinatura": ultima_assinatura,
        "valor": {"cifra": cifra, "extenso": extenso, "confere": confere},
    }


def _doc_apostilamento(
    protocolo,
    numero_no_corpo,
    ultima_assinatura,
    *,
    natureza="reajuste",
    periodicidade="global",
    trecho="valor global",
    cifra="1.200,00",
    extenso="mil e duzentos reais",
    confere=True,
    valor_novo_presente=True,
    cancelado=False,
    apostilamento_presente=True,
):
    apost = None
    if apostilamento_presente:
        apost = {
            "natureza": natureza,
            "valor_anterior": None,
            "valor_novo": (
                {"cifra": cifra, "extenso": extenso, "confere": confere}
                if valor_novo_presente
                else None
            ),
            "percentual": None,
            "indice": None,
            "periodicidade": periodicidade,
            "data_base": None,
            "trecho": trecho,
        }
    return {
        "protocolo": protocolo,
        "conteudo": "cancelado" if cancelado else "html",
        "cancelado": cancelado,
        "menciona_cfc": True,
        "tipo": "apostilamento",
        "numero_no_corpo": numero_no_corpo,
        "assinado_cfc": True,
        "assinado_externo": False,
        "ultima_assinatura": ultima_assinatura,
        "valor": None,
        "apostilamento": apost,
    }


class TestApostilamentoGlobalReajustaValor(unittest.TestCase):
    """(caso 1): apostilamento de reajuste com periodicidade global
    e valor conferido entra na disputa e reajusta `valor_contratado`."""

    def setUp(self):
        doc = _doc_apostilamento(
            "9300001", "60/2026", "01/03/2026 10:00",
            periodicidade="global", cifra="1.200,00", extenso="mil e duzentos reais",
        )
        self.processos = [
            {
                "numero": "90796110000007.000200/2026-01",
                "resultado": "ok",
                "documentos_contratuais": [doc],
            }
        ]
        self.proposta = propor(
            item_pca=200,
            exercicio=2026,
            campos_atuais=_campos_atuais_execucao_vazios(),
            processos_coletados=self.processos,
        )

    def test_valor_contratado_reflete_o_apostilamento_global(self):
        self.assertEqual(
            self.proposta.alteracoes["valor_contratado"],
            (None, Decimal("1200.00")),
        )

    def test_nenhuma_pendencia_apostilamento_sem_global(self):
        chaves = [chave for chave, _texto in self.proposta.pendencias]
        self.assertFalse(any(c.startswith("apostilamento_sem_global:") for c in chaves))


class TestApostilamentoMensalViraPendencia(unittest.TestCase):
    """(caso 2): reajuste mensal, sem âncora "valor global"/"valor
    total" no trecho, nunca entra na disputa — pendência
    `apostilamento_sem_global:<protocolo>`, `valor_contratado` intocado."""

    def setUp(self):
        doc = _doc_apostilamento(
            "9300002", "61/2026", "01/03/2026 10:00",
            periodicidade="mensal", trecho="valor mensal atual",
            cifra="500,00", extenso="quinhentos reais",
        )
        self.processos = [
            {
                "numero": "90796110000007.000201/2026-01",
                "resultado": "ok",
                "documentos_contratuais": [doc],
            }
        ]
        self.proposta = propor(
            item_pca=201,
            exercicio=2026,
            campos_atuais=_campos_atuais_execucao_vazios(),
            processos_coletados=self.processos,
        )

    def test_pendencia_apostilamento_sem_global(self):
        chaves = [chave for chave, _texto in self.proposta.pendencias]
        self.assertIn("apostilamento_sem_global:9300002", chaves)

    def test_valor_contratado_intocado(self):
        self.assertNotIn("valor_contratado", self.proposta.alteracoes)


class TestApostilamentoDotacaoNaoAltera(unittest.TestCase):
    """(caso 3): apostilamento de dotação nunca altera
    `valor_contratado` e sempre gera a evidência "sem efeito no valor",
    nunca uma pendência."""

    def setUp(self):
        doc = _doc_apostilamento(
            "9300003", "62/2026", "01/03/2026 10:00",
            natureza="dotacao", valor_novo_presente=False,
        )
        self.processos = [
            {
                "numero": "90796110000007.000202/2026-01",
                "resultado": "ok",
                "documentos_contratuais": [doc],
            }
        ]
        self.proposta = propor(
            item_pca=202,
            exercicio=2026,
            campos_atuais=_campos_atuais_execucao_vazios(),
            processos_coletados=self.processos,
        )

    def test_evidencia_sem_efeito_no_valor(self):
        self.assertIn(
            "Apostilamento 9300003: alteração de dotação, sem efeito no valor.",
            self.proposta.evidencias,
        )

    def test_valor_contratado_nao_entra_em_alteracoes(self):
        self.assertNotIn("valor_contratado", self.proposta.alteracoes)

    def test_nenhuma_pendencia_gerada_para_o_apostilamento(self):
        chaves = [chave for chave, _texto in self.proposta.pendencias]
        self.assertFalse(any("9300003" in chave for chave in chaves))


class TestApostilamentoCanceladoIgnorado(unittest.TestCase):
    """(caso 4): apostilamento cancelado (sem corpo lido, `valor`/
    `apostilamento` ambos `None` — comportamento real de `ler_documento`)
    nunca entra na disputa nem em `serie_valores`, mesmo coexistindo com um
    apostilamento válido no mesmo item."""

    def setUp(self):
        doc_cancelado = _doc_apostilamento(
            "9300004", "63/2026", "01/01/2026 09:00",
            cancelado=True, apostilamento_presente=False,
        )
        doc_valido = _doc_apostilamento(
            "9300005", "63/2026", "01/03/2026 10:00",
            periodicidade="global", cifra="2.000,00", extenso="dois mil reais",
        )
        self.processos = [
            {
                "numero": "90796110000007.000203/2026-01",
                "resultado": "ok",
                "documentos_contratuais": [doc_cancelado, doc_valido],
            }
        ]
        self.proposta = propor(
            item_pca=203,
            exercicio=2026,
            campos_atuais=_campos_atuais_execucao_vazios(),
            processos_coletados=self.processos,
        )

    def test_valor_contratado_vem_so_do_apostilamento_valido(self):
        self.assertEqual(
            self.proposta.alteracoes["valor_contratado"],
            (None, Decimal("2000.00")),
        )

    def test_cancelado_nunca_aparece_na_serie_de_valores(self):
        protocolos = [entrada["protocolo"] for entrada in self.proposta.serie_valores]
        self.assertNotIn("9300004", protocolos)
        self.assertIn("9300005", protocolos)


class TestSerieValoresOrdemCronologica(unittest.TestCase):
    """(caso 5): `serie_valores` sai em ordem cronológica ascendente
    por `ultima_assinatura`, mesmo com os documentos chegando fora de ordem
    na coleta."""

    def setUp(self):
        contrato = _doc_contrato(
            "9300010", "70/2026", "500.000,00", "quinhentos mil reais",
            "10/01/2024 09:00",
        )
        apost1 = _doc_apostilamento(
            "9300011", "70/2026", "10/01/2025 09:00",
            periodicidade="global", cifra="550.000,00",
            extenso="quinhentos e cinquenta mil reais",
        )
        apost2 = _doc_apostilamento(
            "9300012", "70/2026", "10/06/2025 09:00",
            periodicidade="global", cifra="600.000,00", extenso="seiscentos mil reais",
        )
        # Fora de ordem cronológica de propósito — prova que `propor()`
        # ordena `serie_valores`, não apenas devolve a ordem de chegada.
        self.processos = [
            {
                "numero": "90796110000007.000204/2026-01",
                "resultado": "ok",
                "documentos_contratuais": [apost2, contrato, apost1],
            }
        ]
        self.proposta = propor(
            item_pca=204,
            exercicio=2026,
            campos_atuais=_campos_atuais_execucao_vazios(),
            processos_coletados=self.processos,
        )

    def test_ordem_cronologica_ascendente(self):
        protocolos = [entrada["protocolo"] for entrada in self.proposta.serie_valores]
        self.assertEqual(protocolos, ["9300010", "9300011", "9300012"])

    def test_datas_em_ordem_nao_decrescente(self):
        datas = [entrada["data"] for entrada in self.proposta.serie_valores]
        self.assertEqual(datas, sorted(datas))


class TestEvidenciaEncadeadaContratoAditivoDoisApostilamentos(unittest.TestCase):
    """(caso 6): item com contrato + termo aditivo + 2
    apostilamentos de reajuste global produz a evidência encadeada.
"""

    def setUp(self):
        contrato = _doc_contrato(
            "9300020", "80/2026", "100.000,00", "cem mil reais",
            "10/01/2024 09:00",
        )
        aditivo = _doc_contrato(
            "9300021", "80/2026", "110.000,00", "cento e dez mil reais",
            "10/06/2024 09:00", tipo="termo_aditivo",
        )
        apost1 = _doc_apostilamento(
            "9300022", "80/2026", "10/01/2025 09:00",
            periodicidade="global", cifra="120.000,00", extenso="cento e vinte mil reais",
        )
        apost2 = _doc_apostilamento(
            "9300023", "80/2026", "10/06/2025 09:00",
            periodicidade="global", cifra="130.000,00", extenso="cento e trinta mil reais",
        )
        self.processos = [
            {
                "numero": "90796110000007.000205/2026-01",
                "resultado": "ok",
                "documentos_contratuais": [contrato, aditivo, apost1, apost2],
            }
        ]
        self.proposta = propor(
            item_pca=205,
            exercicio=2026,
            campos_atuais=_campos_atuais_execucao_vazios(),
            processos_coletados=self.processos,
        )

    def test_evidencia_encadeada_exata(self):
        esperado = (
            "Valor contratado: R$ 130.000,00 (contrato 9300020 R$ 100.000,00 → "
            "aditivo 9300021 R$ 110.000,00 → apost. 1º R$ 120.000,00 → "
            "apost. 2º R$ 130.000,00)."
        )
        self.assertIn(esperado, self.proposta.evidencias)

    def test_valor_contratado_e_o_ultimo_apostilamento(self):
        self.assertEqual(
            self.proposta.alteracoes["valor_contratado"],
            (None, Decimal("130000.00")),
        )


# ------------------- Fase 37 (M03/M04) — fronteira de --------
# elegibilidade de `serie_valores`: valor não conferido nunca entra,
# "termo_aditivo" sempre vira "aditivo", `instrumento` é preenchido, e o
# apostilamento usa a data-base extraída (não a assinatura) quando existe.


class TestValorNaoConferidoNuncaEntraEmSerieValores(unittest.TestCase):
    """M03 — um documento com `valor.confere = False` nunca disputa
    `valor_contratado` nem entra em `serie_valores` (hoje entrava sempre
    para tipos != apostilamento)."""

    def test_documento_sem_confere_fica_fora_da_serie(self):
        doc = _doc_contrato(
            "9300030", "90/2026", "38.731,90", "trinta e oito mil setecentos "
            "e trinta e um reais e noventa centavos", "10/01/2026 09:00",
            confere=False,
        )
        processos = [
            {
                "numero": "90796110000007.000206/2026-01",
                "resultado": "ok",
                "documentos_contratuais": [doc],
            }
        ]
        proposta = propor(
            item_pca=206,
            exercicio=2026,
            campos_atuais=_campos_atuais_execucao_vazios(),
            processos_coletados=processos,
        )
        protocolos = [e["protocolo"] for e in proposta.serie_valores]
        self.assertNotIn("9300030", protocolos)
        self.assertNotIn("valor_contratado", proposta.alteracoes)


class TestTermoAditivoViraAditivoNaSerieValores(unittest.TestCase):
    """M04 — `tipo="termo_aditivo"` (vocabulário do coletor) sai como
    `"aditivo"` em `serie_valores` (nunca `"termo_aditivo"` cru, que o
    model rejeitaria em `full_clean()`)."""

    def test_tipo_mapeado_para_aditivo(self):
        doc = _doc_contrato(
            "9300031", "91/2026", "50.000,00", "cinquenta mil reais",
            "10/01/2026 09:00", tipo="termo_aditivo",
        )
        processos = [
            {
                "numero": "90796110000007.000207/2026-01",
                "resultado": "ok",
                "documentos_contratuais": [doc],
            }
        ]
        proposta = propor(
            item_pca=207,
            exercicio=2026,
            campos_atuais=_campos_atuais_execucao_vazios(),
            processos_coletados=processos,
        )
        entrada = next(
            e for e in proposta.serie_valores if e["protocolo"] == "9300031"
        )
        self.assertEqual(entrada["tipo"], "aditivo")


class TestSerieValoresInstrumento(unittest.TestCase):
    """spec §2.1/§8 — `instrumento` identifica a cadeia de contrato:
    `numero_no_corpo` quando o coletor o extrai, senão o `protocolo`."""

    def test_usa_numero_no_corpo_quando_presente(self):
        doc = _doc_contrato(
            "9300032", "05/2026", "10.000,00", "dez mil reais",
            "10/01/2026 09:00",
        )
        processos = [
            {
                "numero": "90796110000007.000208/2026-01",
                "resultado": "ok",
                "documentos_contratuais": [doc],
            }
        ]
        proposta = propor(
            item_pca=208,
            exercicio=2026,
            campos_atuais=_campos_atuais_execucao_vazios(),
            processos_coletados=processos,
        )
        entrada = next(
            e for e in proposta.serie_valores if e["protocolo"] == "9300032"
        )
        self.assertEqual(entrada["instrumento"], "05/2026")

    def test_usa_protocolo_quando_sem_numero_no_corpo(self):
        doc = _doc_contrato(
            "9300033", None, "10.000,00", "dez mil reais", "10/01/2026 09:00",
        )
        processos = [
            {
                "numero": "90796110000007.000209/2026-01",
                "resultado": "ok",
                "documentos_contratuais": [doc],
            }
        ]
        proposta = propor(
            item_pca=209,
            exercicio=2026,
            campos_atuais=_campos_atuais_execucao_vazios(),
            processos_coletados=processos,
        )
        entrada = next(
            e for e in proposta.serie_valores if e["protocolo"] == "9300033"
        )
        self.assertEqual(entrada["instrumento"], entrada["protocolo"])


class TestApostilamentoUsaDataBaseExtraidaNaoAAssinatura(unittest.TestCase):
    """M04 — com `data_base` extraída, `entrada["data"]` usa essa data-base
    (a âncora real de reajuste, spec §2.2), não a assinatura. Sem
    `data_base`, cai para a assinatura — comportamento preservado, já
    coberto pelas fixtures de apostilamento existentes acima."""

    def test_data_base_extraida_vira_a_data_da_entrada(self):
        doc = _doc_apostilamento(
            "9300034", "92/2026", "15/03/2026 10:00",
            periodicidade="global", cifra="1.000,00", extenso="mil reais",
        )
        doc["apostilamento"]["data_base"] = "2026-01-01"
        processos = [
            {
                "numero": "90796110000007.000210/2026-01",
                "resultado": "ok",
                "documentos_contratuais": [doc],
            }
        ]
        proposta = propor(
            item_pca=210,
            exercicio=2026,
            campos_atuais=_campos_atuais_execucao_vazios(),
            processos_coletados=processos,
        )
        entrada = next(
            e for e in proposta.serie_valores if e["protocolo"] == "9300034"
        )
        self.assertEqual(entrada["data"], date(2026, 1, 1))


class TestUnidadeAtual(unittest.TestCase):
    """`unidade_atual()` é módulo puro, sem banco. Regra: unidade de
    DESTINO da linha "Processo remetido pela unidade X" mais recente (`marcos
    ["ultima_remessa"]`), nunca `marcos["recebimentos"]`/`marcos["conclusoes_na_unidade"]`.
    Substitui a regra (recebimento mais recente), que se provou errada
    (ver diagnóstico)."""

    def _aware(self, texto):
        return django_timezone.make_aware(datetime.strptime(texto, "%d/%m/%Y %H:%M"))

    def test_remessa_unica_devolve_a_unidade_de_destino(self):
        marcos = {
            "ultima_remessa": {
                "data_hora": "21/09/2026 14:51",
                "unidade": "GECONT",
                "origem": "GELIC",
            },
            # recebimento mais recente ainda — DEVE ser ignorado.
            "recebimentos": {"PROJUR": "22/09/2026 08:00"},
        }
        self.assertEqual(
            unidade_atual(marcos, None),
            ("GECONT", self._aware("21/09/2026 14:51")),
        )

    def test_sem_remessa_cai_no_fallback_primeiro(self):
        marcos = {"ultima_remessa": None}
        primeiro = {
            "data_hora": "18/08/2026 08:46",
            "unidade": "GECER",
            "descricao": "Processo público gerado",
        }
        self.assertEqual(
            unidade_atual(marcos, primeiro),
            ("GECER", self._aware("18/08/2026 08:46")),
        )

    def test_sem_remessa_e_sem_primeiro(self):
        self.assertEqual(unidade_atual({}, None), ("", None))

    def test_sem_remessa_com_primeiro_sem_unidade(self):
        marcos = {"ultima_remessa": None}
        primeiro = {"data_hora": "18/08/2026 08:46", "unidade": ""}
        self.assertEqual(unidade_atual(marcos, primeiro), ("", None))


class TestUnidadeAtualIntegradaComPropor(unittest.TestCase):
    """Caso de integração (substitui):
    `coleta_item_3.json` tem `marcos["ultima_remessa"]` = DECONT, 27/10/2025
    10:44 (mesmo instante já registrado em `recebimentos.DECONT` — agora
    também a remessa que efetivamente moveu o processo para lá) — a fonte
    de `unidade_atual()` passou a ser `ultima_remessa`, não mais
    `recebimentos`, mas os dois valores esperados abaixo permanecem os
    mesmos porque o instante coincide nesta fixture. `campos_atuais` sem as
    duas chaves novas: `.get(..., "")`/`.get(...)` cobre a ausência."""

    def setUp(self):
        self.processos = _carregar("coleta_item_3.json")
        self.campos_atuais = {
            "data_assinatura_contrato": date(2026, 2, 19),
            "numero_instrumento_contratual": None,
            "instrumento_contratual_nome_normalizado": None,
            "valor_contratado": None,
            "data_recebimento_gelic": date(2025, 9, 5),
        }
        self.proposta = propor(
            item_pca=3,
            exercicio=2025,
            campos_atuais=self.campos_atuais,
            processos_coletados=self.processos,
        )

    def test_unidade_sei_atual_e_a_unidade_do_recebimento_mais_recente(self):
        self.assertEqual(
            self.proposta.alteracoes["unidade_sei_atual"],
            ("", "DECONT"),
        )

    def test_unidade_sei_atual_desde_e_o_recebimento_mais_recente(self):
        self.assertEqual(
            self.proposta.alteracoes["unidade_sei_atual_desde"],
            (
                None,
                django_timezone.make_aware(datetime(2025, 10, 27, 10, 44)),
            ),
        )


if __name__ == "__main__":
    unittest.main()


class TestRecebimentoGelicPrimeiroDoAnoDoPCA(unittest.TestCase):
    """29/09/2026 (decisão do usuário) — processo SEI reaproveitado a cada renovação: a data de
    recebimento no Gelic é a PRIMEIRA entrada no Gelic/Delic do ano do PCA, não a primeira de todas."""

    def _proposta(self, recebimentos, exercicio=2026):
        import copy

        processos = copy.deepcopy(_carregar("coleta_item_1.json"))
        for processo in processos:
            marcos = processo.setdefault("andamentos", {}).setdefault("marcos", {})
            marcos["recebimento_gelic_delic"] = {"unidade": "GELIC", "data_hora": "02/09/2022 10:00"}
            marcos["recebimentos_gelic_delic"] = recebimentos
        return propor(
            item_pca=1,
            exercicio=exercicio,
            campos_atuais={"data_recebimento_gelic": date(2022, 9, 2)},
            processos_coletados=processos,
        )

    def test_escolhe_a_primeira_entrada_do_ano(self):
        proposta = self._proposta(["02/09/2022 10:00", "18/09/2025 09:00", "17/09/2026 14:00", "20/09/2026 08:00"])
        self.assertEqual(proposta.alteracoes["data_recebimento_gelic"], (date(2022, 9, 2), date(2026, 9, 17)))

    def test_sem_entrada_no_ano_fica_a_primeira_de_todas(self):
        proposta = self._proposta(["02/09/2022 10:00", "18/09/2025 09:00"])
        self.assertNotIn("data_recebimento_gelic", proposta.alteracoes)


_CAMPOS_ATUAIS_VAZIOS = {
    "data_assinatura_contrato": None,
    "numero_instrumento_contratual": None,
    "instrumento_contratual_nome_normalizado": None,
    "valor_contratado": None,
    "data_recebimento_gelic": None,
    "fornecedor_cnpj": None,
    "fornecedor_razao_social": None,
    "numero_contratacao": None,
    "modalidade_nome_normalizado": None,
    "vigencia_inicio": None,
    "vigencia_fim": None,
    "unidade_sei_atual": "",
    "unidade_sei_atual_desde": None,
}


def _documento_pdf_item_58(
    *,
    protocolo="1374943",
    numero_no_corpo="25/2026",
    ultima_assinatura="20/05/2026 16:17",
    cifra="39.141,20",
    cnpj="31.238.552/0001-66",
    razao_social="BELIZE COMPANY AUTO POSTO LTDA",
    vigencia_inicio=date(2026, 5, 20),
    vigencia_fim=date(2027, 5, 19),
):
    """Documento `conteudo="pdf"` sintético — exatamente os campos que
    `apps.pca.sei.pdf.processar()` produziria para o caso feliz do item 58.
`regras.py` nunca importa `pdf.py` — o dict é
    montado à mão, não gerado de verdade."""
    return {
        "protocolo": protocolo,
        "tipo": "contrato",
        "conteudo": "pdf",
        "cancelado": False,
        "menciona_cfc": True,
        "assinado_cfc": True,
        "assinado_externo": True,
        "numero_no_corpo": numero_no_corpo,
        "ultima_assinatura": ultima_assinatura,
        "assinaturas": [
            {"nome": "WEBERTH FERNANDES", "data": "20/05/2026", "hora": "15:20", "papel": "cfc"},
            {"nome": "CLEVER MORATO AXHCAR", "data": "20/05/2026", "hora": "16:17", "papel": "externo"},
        ],
        "contratado": {"razao_social": razao_social, "cnpj": cnpj, "fonte": "preambulo"},
        "valor": {"cifra": cifra, "extenso": "trinta e nove mil...", "confere": True},
        "vigencia": {"inicio": vigencia_inicio, "fim": vigencia_fim, "forma": "prazo_desde_assinatura"},
        "procedencia": {"modalidade_texto": None, "numero": None, "modalidade_catalogo": None},
    }


def _documento_html_contrato(
    *,
    protocolo="1204703",
    numero_no_corpo="11/2026",
    ultima_assinatura="10/05/2026 09:00",
    cifra="18.001,20",
    cnpj="12.345.678/0001-95",
    razao_social="OUTRA EMPRESA LTDA",
):
    """Documento `conteudo="html"` sintético — contrato interno comum,
    assinado pelas duas partes, usado para provar a precedência sobre o
    PDF."""
    return {
        "protocolo": protocolo,
        "tipo": "contrato",
        "conteudo": "html",
        "cancelado": False,
        "menciona_cfc": True,
        "assinado_cfc": True,
        "assinado_externo": True,
        "numero_no_corpo": numero_no_corpo,
        "ultima_assinatura": ultima_assinatura,
        "assinaturas": [
            {"nome": "FULANO", "cargo": "Presidente do CFC", "nome_cargo": "cfc", "data": "09/05/2026", "hora": "08:00"},
            {"nome": "CICLANO", "cargo": "Usuário Externo", "data": "10/05/2026", "hora": "09:00"},
        ],
        "contratado": {"razao_social": razao_social, "cnpj": cnpj, "fonte": "preambulo"},
        "valor": {"cifra": cifra, "extenso": "dezoito mil...", "confere": True},
        "vigencia": {"inicio": date(2026, 5, 10), "fim": date(2027, 5, 9), "forma": "prazo_desde_assinatura"},
        "procedencia": {"modalidade_texto": None, "numero": None, "modalidade_catalogo": None},
    }


class TestPdfUnicoInstrumentoSemHtml(unittest.TestCase):
    """PDF externo "Contrato..." assinado pelas duas partes, único
    documento contratual do item — lido como se fosse HTML (plano §7
    novo)."""

    def setUp(self):
        self.processos = [
            {
                "numero": "90796110000024.000002/2026-69",
                "resultado": "ok",
                "documentos_contratuais": [_documento_pdf_item_58()],
            }
        ]
        self.proposta = propor(
            item_pca=58,
            exercicio=2026,
            campos_atuais=dict(_CAMPOS_ATUAIS_VAZIOS),
            processos_coletados=self.processos,
        )

    def test_data_assinatura(self):
        self.assertEqual(
            self.proposta.alteracoes["data_assinatura_contrato"], (None, date(2026, 5, 20))
        )

    def test_numero_instrumento(self):
        self.assertEqual(
            self.proposta.alteracoes["numero_instrumento_contratual"], (None, "25/2026")
        )

    def test_fornecedor(self):
        self.assertEqual(
            self.proposta.alteracoes["fornecedor_cnpj"], (None, "31.238.552/0001-66")
        )
        self.assertEqual(
            self.proposta.alteracoes["fornecedor_razao_social"],
            (None, "BELIZE COMPANY AUTO POSTO LTDA"),
        )

    def test_valor_contratado(self):
        self.assertEqual(
            self.proposta.alteracoes["valor_contratado"], (None, Decimal("39141.20"))
        )

    def test_vigencia(self):
        self.assertEqual(
            self.proposta.alteracoes["vigencia_inicio"], (None, date(2026, 5, 20))
        )
        self.assertEqual(
            self.proposta.alteracoes["vigencia_fim"], (None, date(2027, 5, 19))
        )

    def test_instrumento_assinado_por_ambos(self):
        self.assertTrue(self.proposta.instrumento_assinado_por_ambos)

    def test_nenhuma_pendencia_sem_acesso_documento(self):
        chaves = [chave for chave, _texto in self.proposta.pendencias]
        self.assertFalse(any(c.startswith("sem_acesso_documento:") for c in chaves))


class TestHtmlVenceSobrePdfMaisRecente(unittest.TestCase):
    """HTML assinado pelas duas partes, com `ultima_assinatura` ANTERIOR à
    do PDF do mesmo item — o HTML continua vencendo; a precedência nunca é
    decidida por data."""

    def setUp(self):
        self.processos = [
            {
                "numero": "90796110000024.000002/2026-69",
                "resultado": "ok",
                "documentos_contratuais": [
                    _documento_html_contrato(),  # ultima_assinatura 10/05, mais ANTIGA
                    _documento_pdf_item_58(),  # ultima_assinatura 20/05, mais RECENTE
                ],
            }
        ]
        self.proposta = propor(
            item_pca=58,
            exercicio=2026,
            campos_atuais=dict(_CAMPOS_ATUAIS_VAZIOS),
            processos_coletados=self.processos,
        )

    def test_data_assinatura_vem_do_html_mais_antigo(self):
        self.assertEqual(
            self.proposta.alteracoes["data_assinatura_contrato"], (None, date(2026, 5, 10))
        )

    def test_numero_instrumento_vem_do_html(self):
        self.assertEqual(
            self.proposta.alteracoes["numero_instrumento_contratual"], (None, "11/2026")
        )

    def test_fornecedor_vem_do_html(self):
        self.assertEqual(
            self.proposta.alteracoes["fornecedor_cnpj"], (None, "12.345.678/0001-95")
        )

    def test_valor_contratado_vem_do_html_nunca_do_pdf(self):
        self.assertEqual(
            self.proposta.alteracoes["valor_contratado"], (None, Decimal("18001.20"))
        )

    def test_vigencia_vem_do_html(self):
        self.assertEqual(
            self.proposta.alteracoes["vigencia_inicio"], (None, date(2026, 5, 10))
        )
        self.assertEqual(
            self.proposta.alteracoes["vigencia_fim"], (None, date(2027, 5, 9))
        )


class TestPdfOutroOrgaoDescartadoSilenciosamente(unittest.TestCase):
    """`conteudo="pdf_outro_orgao"` — filtro de segurança do coletor já
    descartou o documento; `regras.py` nunca gera pendência pra ele."""

    def test_sem_pendencia_sem_acesso_documento(self):
        processos = [
            {
                "numero": "23069.000001/2024-11",
                "resultado": "ok",
                "documentos_contratuais": [
                    {"protocolo": "999999", "tipo": "contrato", "conteudo": "pdf_outro_orgao",
                     "cancelado": False, "menciona_cfc": True},
                ],
            }
        ]
        proposta = propor(
            item_pca=58,
            exercicio=2026,
            campos_atuais=dict(_CAMPOS_ATUAIS_VAZIOS),
            processos_coletados=processos,
        )
        chaves = [chave for chave, _texto in proposta.pendencias]
        self.assertNotIn("sem_acesso_documento:999999", chaves)
        self.assertFalse(proposta.instrumento_assinado_por_ambos)


class TestPdfSemTextoOuSemAssinaturaGeraPendencia(unittest.TestCase):
    """`pdf_sem_texto`/`pdf_sem_assinatura_digital` — nunca confirmado como
    instrumento; vira a mesma pendência `sem_acesso_documento` já usada
    para `externo_nao_baixado`."""

    def test_pdf_sem_texto_gera_pendencia(self):
        processos = [
            {
                "numero": "90796110000024.000002/2026-69",
                "resultado": "ok",
                "documentos_contratuais": [
                    {"protocolo": "1374943", "tipo": "contrato", "conteudo": "pdf_sem_texto",
                     "cancelado": False},
                ],
            }
        ]
        proposta = propor(
            item_pca=58,
            exercicio=2026,
            campos_atuais=dict(_CAMPOS_ATUAIS_VAZIOS),
            processos_coletados=processos,
        )
        chaves = [chave for chave, _texto in proposta.pendencias]
        self.assertIn("sem_acesso_documento:1374943", chaves)

    def test_pdf_sem_assinatura_digital_gera_pendencia(self):
        processos = [
            {
                "numero": "90796110000024.000002/2026-69",
                "resultado": "ok",
                "documentos_contratuais": [
                    {"protocolo": "1374943", "tipo": "contrato", "conteudo": "pdf_sem_assinatura_digital",
                     "cancelado": False, "menciona_cfc": True, "assinado_cfc": False,
                     "assinado_externo": False},
                ],
            }
        ]
        proposta = propor(
            item_pca=58,
            exercicio=2026,
            campos_atuais=dict(_CAMPOS_ATUAIS_VAZIOS),
            processos_coletados=processos,
        )
        chaves = [chave for chave, _texto in proposta.pendencias]
        self.assertIn("sem_acesso_documento:1374943", chaves)


# Termo Aditivo em PDF disputa por data com HTML e dedupe de cópia na
# série de valores — item 89 do CONTEXT do plano (seguro de
# veículos), CNPJ/razão social/nº de processo sintéticos.

def _documento_termo_aditivo(
    *,
    protocolo,
    conteudo,
    numero_no_corpo="26/2023",
    ultima_assinatura,
    cifra,
    cnpj="12.345.678/0001-95",
    razao_social="SEGURADORA EXEMPLO VEICULOS LTDA",
    prorrogacao_inicio,
    prorrogacao_fim,
):
    """Shape exato que `pdf.processar()`/o ramo HTML produziriam para um
    Termo Aditivo — `conteudo` ("html" ou "pdf") é o único parâmetro que
    distingue a origem; o resto é idêntico nos dois casos (mesmo
    documento, duas origens possíveis)."""
    return {
        "protocolo": protocolo,
        "tipo": "termo_aditivo",
        "conteudo": conteudo,
        "cancelado": False,
        "menciona_cfc": True,
        "assinado_cfc": True,
        "assinado_externo": True,
        "numero_no_corpo": numero_no_corpo,
        "ultima_assinatura": ultima_assinatura,
        "assinaturas": [
            {"nome": "MARIA EXEMPLO SILVA", "data": ultima_assinatura.split(" ")[0], "hora": "10:00", "papel": "cfc"},
            {"nome": "JOAO EXEMPLO SOUZA", "data": ultima_assinatura.split(" ")[0], "hora": "11:00", "papel": "externo"},
        ],
        "contratado": {"razao_social": razao_social, "cnpj": cnpj, "fonte": "preambulo"},
        "valor": {"cifra": cifra, "extenso": "...", "confere": True},
        "prorrogacao": {"inicio": prorrogacao_inicio, "fim": prorrogacao_fim},
        "procedencia": {"modalidade_texto": None, "numero": None, "modalidade_catalogo": None},
    }


class TestTermoAditivoPdfVenceSobreHtmlMaisAntigo(unittest.TestCase):
    """Primeiro item do <behavior> da Termo Aditivo em PDF com
    assinatura MAIS RECENTE vence sobre o Termo Aditivo HTML mais antigo
    do mesmo item — disputa por data, não "HTML sempre vence"."""

    def setUp(self):
        self.doc_html = _documento_termo_aditivo(
            protocolo="0940252", conteudo="html", ultima_assinatura="24/07/2025 10:00",
            cifra="3.886,09", prorrogacao_inicio=date(2025, 7, 26), prorrogacao_fim=date(2026, 7, 25),
        )
        self.doc_pdf = _documento_termo_aditivo(
            protocolo="1469673", conteudo="pdf", ultima_assinatura="24/07/2026 11:00",
            cifra="4.104,00", prorrogacao_inicio=date(2026, 7, 26), prorrogacao_fim=date(2027, 7, 25),
        )
        self.processos = [
            {
                "numero": "90796110000024.000099/2026-10",
                "resultado": "ok",
                "documentos_contratuais": [self.doc_html, self.doc_pdf],
            }
        ]
        self.proposta = propor(
            item_pca=89,
            exercicio=2026,
            campos_atuais=dict(_CAMPOS_ATUAIS_VAZIOS),
            processos_coletados=self.processos,
        )

    def test_data_assinatura_vem_do_pdf_mais_recente(self):
        self.assertEqual(
            self.proposta.alteracoes["data_assinatura_contrato"], (None, date(2026, 7, 24))
        )

    def test_vigencia_vem_do_pdf(self):
        self.assertEqual(
            self.proposta.alteracoes["vigencia_inicio"], (None, date(2026, 7, 26))
        )
        self.assertEqual(
            self.proposta.alteracoes["vigencia_fim"], (None, date(2027, 7, 25))
        )

    def test_valor_contratado_vem_do_pdf(self):
        self.assertEqual(
            self.proposta.alteracoes["valor_contratado"], (None, Decimal("4104.00"))
        )

    def test_fornecedor_vem_do_pdf(self):
        self.assertEqual(
            self.proposta.alteracoes["fornecedor_cnpj"], (None, "12.345.678/0001-95")
        )

    def test_serie_valores_tem_as_duas_entradas(self):
        valores = {e["valor"] for e in self.proposta.serie_valores}
        self.assertEqual(valores, {Decimal("3886.09"), Decimal("4104.00")})


class TestTermoAditivoHtmlVenceSobrePdfMaisAntigo(unittest.TestCase):
    """Segundo item do <behavior>: mesmas datas invertidas — o HTML (mais
    recente) vence. Prova que a disputa é por data nos dois sentidos."""

    def setUp(self):
        self.doc_html = _documento_termo_aditivo(
            protocolo="0940252", conteudo="html", ultima_assinatura="24/07/2026 11:00",
            cifra="4.104,00", prorrogacao_inicio=date(2026, 7, 26), prorrogacao_fim=date(2027, 7, 25),
        )
        self.doc_pdf = _documento_termo_aditivo(
            protocolo="1469673", conteudo="pdf", ultima_assinatura="24/07/2025 10:00",
            cifra="3.886,09", prorrogacao_inicio=date(2025, 7, 26), prorrogacao_fim=date(2026, 7, 25),
        )
        self.processos = [
            {
                "numero": "90796110000024.000099/2026-10",
                "resultado": "ok",
                "documentos_contratuais": [self.doc_html, self.doc_pdf],
            }
        ]
        self.proposta = propor(
            item_pca=89,
            exercicio=2026,
            campos_atuais=dict(_CAMPOS_ATUAIS_VAZIOS),
            processos_coletados=self.processos,
        )

    def test_data_assinatura_vem_do_html_mais_recente(self):
        self.assertEqual(
            self.proposta.alteracoes["data_assinatura_contrato"], (None, date(2026, 7, 24))
        )

    def test_valor_contratado_vem_do_html(self):
        self.assertEqual(
            self.proposta.alteracoes["valor_contratado"], (None, Decimal("4104.00"))
        )


class TestTermoAditivoPdfCopiaDeHtmlDescartadaNaSerie(unittest.TestCase):
    """Terceiro item do <behavior>: Termo Aditivo HTML e PDF com MESMO
    `numero_no_corpo`/`valor["cifra"]` (cópia do mesmo evento) -> apenas
    UMA entrada na série, com o protocolo do HTML."""

    def test_serie_valores_tem_uma_entrada_so(self):
        doc_html = _documento_termo_aditivo(
            protocolo="0940252", conteudo="html", ultima_assinatura="24/07/2025 10:00",
            cifra="3.886,09", prorrogacao_inicio=date(2025, 7, 26), prorrogacao_fim=date(2026, 7, 25),
        )
        doc_pdf_copia = _documento_termo_aditivo(
            protocolo="9999999", conteudo="pdf", ultima_assinatura="24/07/2025 10:00",
            cifra="3.886,09", prorrogacao_inicio=date(2025, 7, 26), prorrogacao_fim=date(2026, 7, 25),
        )
        processos = [
            {
                "numero": "90796110000024.000099/2026-10",
                "resultado": "ok",
                "documentos_contratuais": [doc_html, doc_pdf_copia],
            }
        ]
        proposta = propor(
            item_pca=89,
            exercicio=2026,
            campos_atuais=dict(_CAMPOS_ATUAIS_VAZIOS),
            processos_coletados=processos,
        )
        self.assertEqual(len(proposta.serie_valores), 1)
        self.assertEqual(proposta.serie_valores[0]["protocolo"], "0940252")
        self.assertNotIn("_html", proposta.serie_valores[0])


class TestTermoAditivoPdfSemAssinaturaDigitalGeraPendencia(unittest.TestCase):
    """Quarto item do <behavior>: único documento é um Termo Aditivo
    `conteudo="pdf_sem_assinatura_digital"` -> nenhum instrumento vencedor,
    pendência `sem_acesso_documento`, `instrumento_assinado_por_ambos`
    `False` (mesmo padrão de TestPdfSemTextoOuSemAssinaturaGeraPendencia,
    trocando o tipo para "termo_aditivo")."""

    def test_pendencia_sem_acesso_documento(self):
        processos = [
            {
                "numero": "90796110000024.000099/2026-10",
                "resultado": "ok",
                "documentos_contratuais": [
                    {"protocolo": "1469673", "tipo": "termo_aditivo",
                     "conteudo": "pdf_sem_assinatura_digital", "cancelado": False,
                     "menciona_cfc": True, "assinado_cfc": False, "assinado_externo": False},
                ],
            }
        ]
        proposta = propor(
            item_pca=89,
            exercicio=2026,
            campos_atuais=dict(_CAMPOS_ATUAIS_VAZIOS),
            processos_coletados=processos,
        )
        chaves = [chave for chave, _texto in proposta.pendencias]
        self.assertIn("sem_acesso_documento:1469673", chaves)
        self.assertFalse(proposta.instrumento_assinado_por_ambos)


# ------------------ debug robo-valor-contratado-item64 (20/10/2026) ---------
# Item 64 (processo 90796110000007.000010/2024-51): contrato 24/2024 (valor
# mensal R$ 2.213,93, total R$ 79.701,70), 1º termo de apostilamento
# (assinado pelo CFC em 13/08/2025, novo valor 82.744,93) e 2º termo (minuta
# sem assinatura em 20/10/2026, novo valor global 83.575,71). Os documentos
# são montados com a extração REAL (`apps.pca.sei.extracao`) sobre os trechos
# literais das cláusulas de valor (`fixtures/sei/textos_item_64.json`).

_TEXTOS_ITEM_64 = json.loads(
    (_FIXTURES / "textos_item_64.json").read_text(encoding="utf-8")
)

_LEITURA_MENSAL_ANTIGA_0347594 = {
    # Dict exato que o cache/coleta guardam hoje para o contrato 24/2024
    # (extração anterior à correção): o 1º casamento, o valor mensal.
    "cifra": "2.213,93",
    "extenso": "dois mil duzentos e treze reais e noventa e três centavos",
    "confere": True,
    "periodicidade": "mensal",
}


def _processos_item_64(*, segundo_assinado, valor_contrato=None):
    def apostilamento(protocolo, chave_texto, assinado, ultima):
        texto = _TEXTOS_ITEM_64[chave_texto]
        return {
            "protocolo": protocolo,
            "conteudo": "html",
            "cancelado": False,
            "menciona_cfc": True,
            "tipo": "apostilamento",
            "numero_no_corpo": None,
            "assinado_cfc": assinado,
            "assinado_externo": False,
            "assinaturas": (
                [{"papel": "cfc", "data": ultima[:10], "hora": ultima[11:]}] if assinado else []
            ),
            "ultima_assinatura": ultima if assinado else None,
            "valor": extrair_valor_documento(texto),
            "apostilamento": extrair_apostilamento(texto),
        }

    contrato = {
        "protocolo": "0347594",
        "conteudo": "html",
        "cancelado": False,
        "menciona_cfc": True,
        "tipo": "contrato",
        "numero_no_corpo": "24/2024",
        "assinado_cfc": True,
        "assinado_externo": True,
        "assinaturas": [
            {"papel": "externo", "data": "17/05/2024", "hora": "10:00"},
            {"papel": "cfc", "data": "20/05/2024", "hora": "15:25"},
        ],
        "ultima_assinatura": "20/05/2024 15:25",
        "valor": (
            valor_contrato
            if valor_contrato is not None
            else extrair_valor_documento(_TEXTOS_ITEM_64["contrato_0347594"])
        ),
        "apostilamento": None,
    }
    return [
        {
            "numero": "90796110000007.000010/2024-51",
            "resultado": "ok",
            "documentos_contratuais": [
                contrato,
                apostilamento("0967338", "apostilamento_0967338", True, "13/08/2025 16:54"),
                apostilamento(
                    "1603102", "apostilamento_1603102", segundo_assinado, "21/10/2026 10:00"
                ),
            ],
        }
    ]


def _propor_item_64(**kwargs):
    return propor(
        item_pca=64,
        exercicio=2026,
        campos_atuais=_campos_atuais_execucao_vazios(valor_contratado=Decimal("2213.93")),
        processos_coletados=_processos_item_64(**kwargs),
    )


class TestItem64SegundoTermoSemAssinatura(unittest.TestCase):
    """Enquanto o 2º termo é minuta (sem assinatura do CFC), o vigente é o
    1º termo: R$ 82.744,93 — e a minuta não gera pendência nem entra na
    série."""

    def setUp(self):
        self.proposta = _propor_item_64(segundo_assinado=False)

    def test_valor_contratado_e_o_do_primeiro_termo(self):
        self.assertEqual(
            self.proposta.alteracoes["valor_contratado"],
            (Decimal("2213.93"), Decimal("82744.93")),
        )

    def test_primeiro_termo_entra_na_disputa_sem_pendencia(self):
        chaves = [chave for chave, _texto in self.proposta.pendencias]
        self.assertNotIn("apostilamento_sem_global:0967338", chaves)

    def test_minuta_nao_gera_pendencia(self):
        chaves = [chave for chave, _texto in self.proposta.pendencias]
        self.assertFalse(any("1603102" in chave for chave in chaves))

    def test_minuta_fora_da_serie_de_valores(self):
        protocolos = [e["protocolo"] for e in self.proposta.serie_valores]
        self.assertNotIn("1603102", protocolos)

    def test_primeiro_termo_entra_na_serie_como_global(self):
        entrada = next(e for e in self.proposta.serie_valores if e["protocolo"] == "0967338")
        self.assertEqual(entrada["valor"], Decimal("82744.93"))
        self.assertEqual(entrada["periodicidade"], "global")

    def test_contrato_entra_na_serie_pelo_valor_total(self):
        entrada = next(e for e in self.proposta.serie_valores if e["protocolo"] == "0347594")
        self.assertEqual(entrada["valor"], Decimal("79701.70"))


class TestItem64SegundoTermoAssinadoPeloCfc(unittest.TestCase):
    """Assinado o 2º termo pelo CFC, vale o novo valor global da cláusula
    2.3: R$ 83.575,71."""

    def setUp(self):
        self.proposta = _propor_item_64(segundo_assinado=True)

    def test_valor_contratado_e_o_novo_valor_global(self):
        self.assertEqual(
            self.proposta.alteracoes["valor_contratado"],
            (Decimal("2213.93"), Decimal("83575.71")),
        )

    def test_evidencia_encadeada(self):
        self.assertIn(
            "Valor contratado: R$ 83.575,71 (contrato 0347594 R$ 79.701,70 → "
            "apost. 1º R$ 82.744,93 → apost. 2º R$ 83.575,71).",
            self.proposta.evidencias,
        )

    def test_nenhuma_pendencia_de_valor(self):
        chaves = [chave for chave, _texto in self.proposta.pendencias]
        self.assertFalse(
            [c for c in chaves if c.startswith(("valor_", "apostilamento_sem_global"))]
        )


class TestItem64ContratoComLeituraMensalAindaNoCache(unittest.TestCase):
    """Antes de `sei_coletar --reprocessar-documentos`, o cache ainda guarda
    a leitura antiga do contrato (o mensal). O 1º termo, já assinado e mais
    recente, vence; o mensal superado não gera pendência nem entra na
    evidência encadeada."""

    def setUp(self):
        self.proposta = _propor_item_64(
            segundo_assinado=False, valor_contrato=dict(_LEITURA_MENSAL_ANTIGA_0347594)
        )

    def test_valor_contratado_e_o_do_primeiro_termo(self):
        self.assertEqual(
            self.proposta.alteracoes["valor_contratado"],
            (Decimal("2213.93"), Decimal("82744.93")),
        )

    def test_mensal_superado_nao_gera_pendencia(self):
        chaves = [chave for chave, _texto in self.proposta.pendencias]
        self.assertNotIn("valor_sem_global:0347594", chaves)

    def test_mensal_fora_da_evidencia(self):
        self.assertIn(
            "Valor contratado: R$ 82.744,93 (antes: R$ 2.213,93).", self.proposta.evidencias
        )

    def test_mensal_continua_na_serie_para_o_fluxo_de_caixa(self):
        entrada = next(e for e in self.proposta.serie_valores if e["protocolo"] == "0347594")
        self.assertEqual(entrada["valor"], Decimal("2213.93"))
        self.assertEqual(entrada["periodicidade"], "mensal")


class TestItem64MinutaComLeituraAntigaNaoGeraPendencia(unittest.TestCase):
    """A coleta de 20/10/2026 trouxe o 2º termo (minuta, sem assinatura)
    com a leitura antiga — `valor_novo` None, `valor_anterior` 26.567,23 —
    e ele gerava `valor_nao_confere:1603102` ("cifra '?' × extenso '?'").
    Minuta não é ato: nenhuma pendência."""

    def setUp(self):
        processos = _processos_item_64(segundo_assinado=False)
        minuta = processos[0]["documentos_contratuais"][2]
        minuta["apostilamento"] = {
            "natureza": "reajuste",
            "valor_anterior": {
                "cifra": "26.567,23",
                "extenso": "vinte e seis mil quinhentos e sessenta e sete reais e vinte e três centavos",
                "confere": True,
            },
            "valor_novo": None,
            "percentual": None,
            "indice": None,
            "periodicidade": None,
            "data_base": None,
            "trecho": "valor correspondente ao primeiro período contratual: R$ 26.567,23",
        }
        self.proposta = propor(
            item_pca=64,
            exercicio=2026,
            campos_atuais=_campos_atuais_execucao_vazios(valor_contratado=Decimal("2213.93")),
            processos_coletados=processos,
        )

    def test_nenhuma_pendencia_da_minuta(self):
        chaves = [chave for chave, _texto in self.proposta.pendencias]
        self.assertNotIn("valor_nao_confere:1603102", chaves)
        self.assertFalse(any("1603102" in chave for chave in chaves))

    def test_valor_contratado_continua_o_do_primeiro_termo(self):
        self.assertEqual(
            self.proposta.alteracoes["valor_contratado"],
            (Decimal("2213.93"), Decimal("82744.93")),
        )


class TestApostilamentoMensalSemAssinaturaNaoGeraPendencia(unittest.TestCase):
    """Minuta de reajuste mensal (sem assinatura do CFC) não gera
    `apostilamento_sem_global` — a pendência é só do ato assinado."""

    def test_sem_pendencia(self):
        doc = _doc_apostilamento(
            "9300400", "400/2026", None, periodicidade="mensal", trecho="valor mensal atual",
            cifra="500,00", extenso="quinhentos reais",
        )
        doc["assinado_cfc"] = False
        proposta = propor(
            item_pca=305,
            exercicio=2026,
            campos_atuais=_campos_atuais_execucao_vazios(),
            processos_coletados=_processo_unico(doc),
        )
        self.assertFalse(any("9300400" in c for c, _t in proposta.pendencias))


def _processo_unico(*documentos):
    return [
        {
            "numero": "90796110000007.000300/2026-01",
            "resultado": "ok",
            "documentos_contratuais": list(documentos),
        }
    ]


class TestValorPeriodicoNuncaViraValorContratado(unittest.TestCase):
    """Ponto 1 (lado das regras): contrato/aditivo com valor mensal ou anual
    nunca grava `valor_contratado` — pendência `valor_sem_global`; global e
    sem periodicidade (total/montante) continuam gravando."""

    def _proposta(self, periodicidade):
        doc = _doc_contrato("9300100", "100/2026", "1.000,00", "mil reais", "10/01/2026 09:00")
        if periodicidade is not None:
            doc["valor"]["periodicidade"] = periodicidade
        return propor(
            item_pca=300,
            exercicio=2026,
            campos_atuais=_campos_atuais_execucao_vazios(),
            processos_coletados=_processo_unico(doc),
        )

    def test_mensal_vira_pendencia(self):
        proposta = self._proposta("mensal")
        self.assertNotIn("valor_contratado", proposta.alteracoes)
        self.assertIn("valor_sem_global:9300100", [c for c, _t in proposta.pendencias])

    def test_anual_vira_pendencia(self):
        proposta = self._proposta("anual")
        self.assertNotIn("valor_contratado", proposta.alteracoes)
        self.assertIn("valor_sem_global:9300100", [c for c, _t in proposta.pendencias])

    def test_global_grava(self):
        proposta = self._proposta("global")
        self.assertEqual(proposta.alteracoes["valor_contratado"], (None, Decimal("1000.00")))
        self.assertFalse(any(c.startswith("valor_sem_global") for c, _t in proposta.pendencias))

    def test_sem_periodicidade_grava(self):
        proposta = self._proposta(None)
        self.assertEqual(proposta.alteracoes["valor_contratado"], (None, Decimal("1000.00")))


class TestPeriodicoMaisRecenteNuncaCaiParaDocumentoAnterior(unittest.TestCase):
    """Achado do relatório de impacto (itens 8/16/56/76/114/129): quando o
    documento MAIS RECENTE só tem valor mensal/anual, o valor de um
    documento anterior já foi superado — nada é gravado (fica o valor
    atual) e a pendência aponta o documento que governa."""

    def _proposta(self, *documentos, atual=None):
        return propor(
            item_pca=306,
            exercicio=2026,
            campos_atuais=_campos_atuais_execucao_vazios(valor_contratado=atual),
            processos_coletados=_processo_unico(*documentos),
        )

    def test_aditivo_anual_mais_recente_nao_cai_para_o_total_do_contrato(self):
        contrato = _doc_contrato("9300500", "500/2023", "19.800,00", "dezenove mil e oitocentos reais", "05/12/2023 11:26")
        aditivo = _doc_contrato(
            "9300501", "500/2023", "20.820,12", "vinte mil oitocentos e vinte reais e doze centavos",
            "28/11/2024 21:48", tipo="termo_aditivo",
        )
        aditivo["valor"]["periodicidade"] = "anual"
        proposta = self._proposta(contrato, aditivo, atual=Decimal("20820.12"))
        self.assertNotIn("valor_contratado", proposta.alteracoes)
        chaves = [c for c, _t in proposta.pendencias]
        self.assertIn("valor_sem_global:9300501", chaves)
        self.assertNotIn("pca_nao_confirmado:valor_contratado", chaves)

    def test_mensal_superado_por_global_posterior_grava_o_global(self):
        aditivo_mensal = _doc_contrato(
            "9300502", "502/2023", "1.000,00", "mil reais", "10/01/2024 09:00", tipo="termo_aditivo",
        )
        aditivo_mensal["valor"]["periodicidade"] = "mensal"
        aditivo_global = _doc_contrato(
            "9300503", "502/2023", "36.000,00", "trinta e seis mil reais", "10/01/2025 09:00",
            tipo="termo_aditivo",
        )
        proposta = self._proposta(aditivo_mensal, aditivo_global)
        self.assertEqual(proposta.alteracoes["valor_contratado"], (None, Decimal("36000.00")))
        self.assertFalse(any(c.startswith("valor_sem_global") for c, _t in proposta.pendencias))

    def test_contratos_distintos_com_periodico_nao_somam(self):
        contrato_a = _doc_contrato("9300504", "504/2026", "10.000,00", "dez mil reais", "10/01/2026 09:00")
        contrato_a["contratado"] = {"cnpj": "11.111.111/0001-11"}
        contrato_b = _doc_contrato("9300505", "505/2026", "1.000,00", "mil reais", "10/01/2026 10:00")
        contrato_b["contratado"] = {"cnpj": "22.222.222/0001-22"}
        contrato_b["valor"]["periodicidade"] = "mensal"
        proposta = self._proposta(contrato_a, contrato_b)
        self.assertNotIn("valor_contratado", proposta.alteracoes)
        self.assertIn("valor_sem_global:9300505", [c for c, _t in proposta.pendencias])


class TestApostilamentoValorDoContratoContaComoGlobal(unittest.TestCase):
    """Ponto 2: o molde "Valor do contrato: R$ X ... Novo valor do contrato:
    R$ Y" (sem mensal/anual) é o valor global; com marca de período ("ao
    mês", "mensais", "ao ano"...) continua fora da disputa."""

    def _proposta(self, trecho):
        doc = _doc_apostilamento(
            "9300200", "200/2026", "01/03/2026 10:00",
            periodicidade=None, trecho=trecho, cifra="1.200,00", extenso="mil e duzentos reais",
        )
        return propor(
            item_pca=301,
            exercicio=2026,
            campos_atuais=_campos_atuais_execucao_vazios(),
            processos_coletados=_processo_unico(doc),
        )

    def test_novo_valor_do_contrato_entra_na_disputa(self):
        proposta = self._proposta(
            "Valor atual do contrato: R$ 1.000,00 (mil reais). Novo valor do "
            "contrato: R$ 1.200,00 (mil e duzentos reais)."
        )
        self.assertEqual(proposta.alteracoes["valor_contratado"], (None, Decimal("1200.00")))
        self.assertFalse(any(c.startswith("apostilamento_sem_global") for c, _t in proposta.pendencias))

    def test_valor_do_contrato_ao_mes_continua_fora(self):
        proposta = self._proposta(
            "Valor do contrato: R$ 1.000,00 (mil reais) ao mês. Novo valor do "
            "contrato: R$ 1.200,00 (mil e duzentos reais) ao mês."
        )
        self.assertNotIn("valor_contratado", proposta.alteracoes)
        self.assertIn("apostilamento_sem_global:9300200", [c for c, _t in proposta.pendencias])

    def test_valor_do_contrato_mensais_continua_fora(self):
        proposta = self._proposta(
            "Novo valor do contrato: R$ 1.200,00 (mil e duzentos reais) mensais."
        )
        self.assertNotIn("valor_contratado", proposta.alteracoes)

    def test_sem_ancora_continua_fora(self):
        proposta = self._proposta("Valor correspondente ao período: R$ 1.200,00 (mil e duzentos reais).")
        self.assertNotIn("valor_contratado", proposta.alteracoes)


class TestAssinaturaExigidaNaDisputaDeValor(unittest.TestCase):
    """Ponto 4 (spec §4.1/§4.3): só disputa `valor_contratado` (e só entra
    na série) o documento assinado — apostilamento pelo CFC; contrato,
    aditivo, OF e ata pelo CFC e pelo contratado."""

    def test_apostilamento_sem_assinatura_nao_disputa_nem_gera_pendencia(self):
        doc = _doc_apostilamento("9300300", "300/2026", None, cifra="1.200,00", extenso="mil e duzentos reais")
        doc["assinado_cfc"] = False
        proposta = propor(
            item_pca=302,
            exercicio=2026,
            campos_atuais=_campos_atuais_execucao_vazios(),
            processos_coletados=_processo_unico(doc),
        )
        self.assertNotIn("valor_contratado", proposta.alteracoes)
        self.assertFalse(any("9300300" in c for c, _t in proposta.pendencias))
        self.assertEqual(proposta.serie_valores, [])

    def test_apostilamento_sem_assinatura_mais_recente_nao_vence_o_assinado(self):
        assinado = _doc_apostilamento(
            "9300301", "301/2026", "01/03/2026 10:00", cifra="1.100,00", extenso="mil e cem reais",
        )
        minuta = _doc_apostilamento(
            "9300302", "301/2026", "01/04/2026 10:00", cifra="1.300,00", extenso="mil e trezentos reais",
        )
        minuta["assinado_cfc"] = False
        proposta = propor(
            item_pca=303,
            exercicio=2026,
            campos_atuais=_campos_atuais_execucao_vazios(),
            processos_coletados=_processo_unico(assinado, minuta),
        )
        self.assertEqual(proposta.alteracoes["valor_contratado"], (None, Decimal("1100.00")))

    def test_contrato_assinado_so_pelo_cfc_nao_disputa(self):
        doc = _doc_contrato("9300303", "303/2026", "5.000,00", "cinco mil reais", "10/01/2026 09:00")
        doc["assinado_externo"] = False
        proposta = propor(
            item_pca=304,
            exercicio=2026,
            campos_atuais=_campos_atuais_execucao_vazios(),
            processos_coletados=_processo_unico(doc),
        )
        self.assertNotIn("valor_contratado", proposta.alteracoes)
        self.assertIn("unilateral:9300303", [c for c, _t in proposta.pendencias])


# ------ decisão do usuário (20/10/2026): contrato com valores por item -------
# Item 18 (processo 90796110000037.000017/2025-05): o Contrato nº 39/2026
# (protocolo 1513621) traz um valor por item (ITEM 01 R$ 110.499,60, ITEM 02
# R$ 62.000,00, ITEM 03 R$ 18.800,00) e nenhum valor global único — o robô
# não grava `valor_contratado` (o valor atual fica intocado), registra a
# pendência `valor_por_itens:<protocolo>` para preenchimento manual e o
# documento fica fora da série de valores (um único item nunca é o global do
# fluxo de caixa).

_TEXTOS_ITEM_18 = json.loads(
    (_FIXTURES / "textos_item_18.json").read_text(encoding="utf-8")
)


def _contrato_item_18(valor=None):
    doc = _doc_contrato("1513621", "39/2026", "0,00", "zero", "24/08/2026 14:54")
    doc["valor"] = (
        valor if valor is not None else extrair_valor_documento(_TEXTOS_ITEM_18["contrato_1513621"])
    )
    return doc


class TestValorPorItensViraPendencia(unittest.TestCase):
    def setUp(self):
        self.proposta = propor(
            item_pca=18,
            exercicio=2026,
            campos_atuais=_campos_atuais_execucao_vazios(valor_contratado=Decimal("22099.92")),
            processos_coletados=_processo_unico(_contrato_item_18()),
        )

    def test_valor_contratado_intocado(self):
        self.assertNotIn("valor_contratado", self.proposta.alteracoes)

    def test_pendencia_valor_por_itens(self):
        chaves = [c for c, _t in self.proposta.pendencias]
        self.assertIn("valor_por_itens:1513621", chaves)
        self.assertNotIn("valor_sem_global:1513621", chaves)
        self.assertNotIn("pca_nao_confirmado:valor_contratado", chaves)

    def test_pendencia_lista_o_valor_de_cada_item(self):
        texto = dict(self.proposta.pendencias)["valor_por_itens:1513621"]
        self.assertIn("ITEM 01 R$ 110.499,60", texto)
        self.assertIn("ITEM 02 R$ 62.000,00", texto)
        self.assertIn("ITEM 03 R$ 18.800,00", texto)
        self.assertIn("preencher manualmente", texto)

    def test_fora_da_serie_de_valores(self):
        self.assertNotIn("1513621", [e["protocolo"] for e in self.proposta.serie_valores])

    def test_sem_valor_atual_continua_sem_gravar(self):
        proposta = propor(
            item_pca=18,
            exercicio=2026,
            campos_atuais=_campos_atuais_execucao_vazios(),
            processos_coletados=_processo_unico(_contrato_item_18()),
        )
        self.assertNotIn("valor_contratado", proposta.alteracoes)
        self.assertIn("valor_por_itens:1513621", [c for c, _t in proposta.pendencias])


class TestValorPorItensSuperadoPorGlobalPosterior(unittest.TestCase):
    """Um aditivo posterior com valor global único governa — o contrato por
    itens, já superado, não gera pendência."""

    def test_aditivo_global_posterior_grava(self):
        aditivo = _doc_contrato(
            "1513999", "39/2026", "191.299,60",
            "cento e noventa e um mil duzentos e noventa e nove reais e sessenta centavos",
            "10/10/2026 10:00", tipo="termo_aditivo",
        )
        proposta = propor(
            item_pca=18,
            exercicio=2026,
            campos_atuais=_campos_atuais_execucao_vazios(valor_contratado=Decimal("22099.92")),
            processos_coletados=_processo_unico(_contrato_item_18(), aditivo),
        )
        self.assertEqual(
            proposta.alteracoes["valor_contratado"], (Decimal("22099.92"), Decimal("191299.60"))
        )
        self.assertFalse(any(c.startswith("valor_por_itens") for c, _t in proposta.pendencias))


class TestValorPorItensEmContratosDistintosNaoSoma(unittest.TestCase):
    def test_soma_incompleta(self):
        contrato_a = _doc_contrato("9300600", "600/2026", "10.000,00", "dez mil reais", "10/01/2026 09:00")
        contrato_a["contratado"] = {"cnpj": "11.111.111/0001-11"}
        contrato_b = _contrato_item_18()
        contrato_b["contratado"] = {"cnpj": "22.222.222/0001-22"}
        proposta = propor(
            item_pca=307,
            exercicio=2026,
            campos_atuais=_campos_atuais_execucao_vazios(),
            processos_coletados=_processo_unico(contrato_a, contrato_b),
        )
        self.assertNotIn("valor_contratado", proposta.alteracoes)
        self.assertIn("valor_por_itens:1513621", [c for c, _t in proposta.pendencias])


class TestValorPorItensLeituraAntigaNoCache(unittest.TestCase):
    """Antes de `sei_coletar --reprocessar-documentos`, o cache guarda a
    leitura antiga do contrato do item 18 (o valor anual do ITEM 01): fica
    `valor_sem_global` — também sem gravar nada."""

    def test_leitura_anual_antiga_vira_valor_sem_global(self):
        antiga = {
            "cifra": "22.099,92",
            "extenso": "vinte e dois mil noventa e nove reais e noventa e dois centavos",
            "confere": True,
            "periodicidade": "anual",
        }
        proposta = propor(
            item_pca=18,
            exercicio=2026,
            campos_atuais=_campos_atuais_execucao_vazios(valor_contratado=Decimal("22099.92")),
            processos_coletados=_processo_unico(_contrato_item_18(antiga)),
        )
        self.assertNotIn("valor_contratado", proposta.alteracoes)
        self.assertIn("valor_sem_global:1513621", [c for c, _t in proposta.pendencias])
