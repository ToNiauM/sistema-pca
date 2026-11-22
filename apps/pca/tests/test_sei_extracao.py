"""Testes do módulo puro `apps.pca.sei.extracao` (Fase 32, parte testável; Fase 33).
`unittest.TestCase` simples, sem banco, sem Django, sem Playwright — o
módulo é importável no container `web`, que nunca ganha Playwright
instalado.
"""

import json
import unittest
from datetime import date
from pathlib import Path

from apps.pca.sei.extracao import (
    PROCESSOS_POR_LOTE,
    VERSAO_EXTRACAO_DOCUMENTO,
    deve_bloquear_recurso,
    extrair_apostilamento,
    extrair_assinaturas,
    extrair_contratado,
    extrair_numero_no_corpo,
    extrair_procedencia,
    extrair_prorrogacao,
    extrair_valor_documento,
    extrair_vigencia,
    hash_texto,
    texto_corpo_de,
    tipo_documento,
)


class TestSemImportPlaywright(unittest.TestCase):
    def test_extracao_nao_importa_playwright(self):
        with open("apps/pca/sei/extracao.py", encoding="utf-8") as f:
            conteudo = f.read()
        self.assertNotIn("import playwright", conteudo)
        self.assertNotIn("from playwright", conteudo)


class TestDeveBloquearRecurso(unittest.TestCase):
    def test_bloqueia_imagem(self):
        self.assertIs(deve_bloquear_recurso("image"), True)

    def test_bloqueia_fonte(self):
        self.assertIs(deve_bloquear_recurso("font"), True)

    def test_nao_bloqueia_documento(self):
        self.assertIs(deve_bloquear_recurso("document"), False)

    def test_nao_bloqueia_stylesheet(self):
        self.assertIs(deve_bloquear_recurso("stylesheet"), False)


class TestProcessosPorLote(unittest.TestCase):
    def test_constante_igual_a_25(self):
        self.assertEqual(PROCESSOS_POR_LOTE, 25)


class TestTipoDocumento(unittest.TestCase):
    def test_contrato(self):
        self.assertEqual(
            tipo_documento("Contrato nº 08/2026 - GOSHME x CFC"), "contrato"
        )

    def test_termo_de_apostilamento(self):
        self.assertEqual(
            tipo_documento("Termo de Apostilamento Primeiro - F5"),
            "apostilamento",
        )

    def test_apostilamento_curto(self):
        self.assertEqual(tipo_documento("Apostilamento - F3"), "apostilamento")

    def test_termo_aditivo(self):
        self.assertEqual(
            tipo_documento("Termo Aditivo Primeiro ao Contrato 01/2025"),
            "termo_aditivo",
        )

    def test_ordem_de_fornecimento(self):
        self.assertEqual(
            tipo_documento("Ordem de Fornecimento nº 12/2026"),
            "ordem_fornecimento",
        )

    def test_ata_de_registro_de_precos(self):
        self.assertEqual(
            tipo_documento("Ata de Registro de Preços nº 03/2026"), "ata_rp"
        )

    def test_termo_de_rescisao_nao_e_instrumento(self):
        self.assertIsNone(tipo_documento("Termo de Rescisão do Contrato 05/2024"))

    def test_contrato_social_excluido(self):
        self.assertIsNone(tipo_documento("Contrato Social da Empresa X"))

    def test_rotulo_nao_contratual(self):
        self.assertIsNone(tipo_documento("Ofício circular"))

    def test_rotulo_vazio(self):
        self.assertIsNone(tipo_documento(""))
        self.assertIsNone(tipo_documento(None))


class TestExtrairAssinaturas(unittest.TestCase):
    def test_assinatura_cfc_e_externa(self):
        texto = (
            "Documento assinado eletronicamente por Fulano de Tal, "
            "Presidente do CFC, em 03/02/2026, às 14:30.\n"
            "Documento assinado eletronicamente por Ciclano da Silva, "
            "Usuário Externo, em 19/02/2026, às 09:10."
        )
        resultado = extrair_assinaturas(texto)
        self.assertEqual(len(resultado["assinaturas"]), 2)
        self.assertTrue(resultado["assinado_cfc"])
        self.assertTrue(resultado["assinado_externo"])
        self.assertEqual(resultado["ultima_assinatura"], "19/02/2026 09:10")
        self.assertEqual(resultado["ultima_assinatura_cfc"], "03/02/2026 14:30")
        # (Fase 39) — `nome` normalizado, chaves antigas intactas.
        self.assertEqual(resultado["assinaturas"][0]["nome"], "Fulano de Tal")
        self.assertEqual(resultado["assinaturas"][0]["cargo"], "Presidente do CFC")
        self.assertEqual(resultado["assinaturas"][1]["nome"], "Ciclano da Silva")

    def test_sem_assinatura(self):
        resultado = extrair_assinaturas("texto qualquer sem assinatura")
        self.assertEqual(resultado["assinaturas"], [])
        self.assertFalse(resultado["assinado_cfc"])
        self.assertFalse(resultado["assinado_externo"])
        self.assertIsNone(resultado["ultima_assinatura"])
        self.assertIsNone(resultado["ultima_assinatura_cfc"])

    def test_texto_vazio(self):
        resultado = extrair_assinaturas("")
        self.assertEqual(resultado["assinaturas"], [])

    def test_nome_com_espacos_extras_normalizado(self):
        texto = (
            "Documento assinado eletronicamente por   Maria   da   Costa , "
            "Diretora, em 01/01/2026, às 10:00."
        )
        resultado = extrair_assinaturas(texto)
        self.assertEqual(resultado["assinaturas"][0]["nome"], "Maria da Costa")

    def test_assinatura_com_data_impossivel_e_descartada_sem_lancar(self):
        # Achado dados B2 (QA 30/09/2026) — 31/02 não existe; a assinatura é
        # descartada, as demais (válidas) continuam normalmente, nunca
        # lança exceção.
        texto = (
            "Documento assinado eletronicamente por Fulano de Tal, "
            "Presidente do CFC, em 31/02/2026, às 14:30.\n"
            "Documento assinado eletronicamente por Ciclano da Silva, "
            "Usuário Externo, em 18/09/2026, às 09:10."
        )
        resultado = extrair_assinaturas(texto)
        self.assertEqual(len(resultado["assinaturas"]), 1)
        self.assertEqual(resultado["ultima_assinatura"], "18/09/2026 09:10")


class TestTextoCorpoDe(unittest.TestCase):
    def test_remove_bloco_de_assinatura_e_cabecalho(self):
        texto = (
            "CONSELHO FEDERAL DE CONTABILIDADE\n"
            "TERMO DE CONTRATO Nº 08/2026\n\n"
            "CLÁUSULA PRIMEIRA – DO OBJETO\n"
            "1.1. O objeto do presente contrato é a prestação de serviços.\n"
            "CLÁUSULA SEGUNDA – DO VALOR\n"
            "2.1. O valor total é de R$ 18.001,20.\n"
            "Documento assinado eletronicamente por Fulano de Tal, "
            "Presidente do CFC, em 03/02/2026, às 14:30.\n"
            "A autenticidade deste documento pode ser conferida no site "
            "https://sei.cfc.org.br/verifica.\n"
        )
        resultado = texto_corpo_de(texto)
        self.assertIn("CLÁUSULA PRIMEIRA", resultado)
        self.assertIn("CLÁUSULA SEGUNDA", resultado)
        self.assertNotIn("Documento assinado eletronicamente", resultado)
        self.assertNotIn("autenticidade", resultado)
        self.assertNotIn("CONSELHO FEDERAL DE CONTABILIDADE", resultado)

    def test_preserva_corpo_quando_nao_ha_marcador_de_cabecalho(self):
        # Sem "CLÁUSULA PRIMEIRA" nem título contratual reconhecível: nunca
        # esvazia um corpo que já existia.
        texto = "Texto de um documento qualquer, sem cláusula reconhecível."
        resultado = texto_corpo_de(texto)
        self.assertIn("Texto de um documento qualquer", resultado)

    def test_texto_vazio_devolve_vazio(self):
        self.assertEqual(texto_corpo_de(""), "")
        self.assertEqual(texto_corpo_de(None), "")

    def test_colapsa_espacos_por_linha(self):
        texto = "CLÁUSULA PRIMEIRA – DO OBJETO\n1.1.   Texto   com   espaços   extras."
        resultado = texto_corpo_de(texto)
        self.assertIn("1.1. Texto com espaços extras.", resultado)


class TestHashTexto(unittest.TestCase):
    def test_estavel_a_espacos_e_caixa(self):
        self.assertEqual(hash_texto("Texto Igual"), hash_texto("texto   igual"))

    def test_textos_diferentes_geram_hashes_diferentes(self):
        self.assertNotEqual(hash_texto("abc"), hash_texto("abd"))

    def test_texto_vazio_nao_lanca_excecao(self):
        hash_texto("")
        hash_texto(None)


class TestVersaoExtracaoDocumento(unittest.TestCase):
    def test_constante_igual_a_4(self):
        # 2 -> 3 (PDF externo "Contrato..." passa a ser
        # lido); debug robo-valor-contratado-item64: 3 -> 4 (valor total
        # preferido ao mensal, forma "novo valor global ... passa a ser de")
        # — golden number atualizado junto com a mudança de design.
        self.assertEqual(VERSAO_EXTRACAO_DOCUMENTO, 4)


class TestExtrairNumeroNoCorpo(unittest.TestCase):
    def test_numero_de_contrato(self):
        self.assertEqual(
            extrair_numero_no_corpo("CONTRATO Nº 08/2026 celebrado entre..."),
            "08/2026",
        )

    def test_numero_de_termo_aditivo(self):
        self.assertEqual(
            extrair_numero_no_corpo("TERMO ADITIVO N° 01/2025 ao contrato..."),
            "01/2025",
        )

    def test_sem_numero(self):
        self.assertIsNone(extrair_numero_no_corpo("texto sem número de instrumento"))

    def test_texto_vazio(self):
        self.assertIsNone(extrair_numero_no_corpo(""))


class TestExtrairValorDocumento(unittest.TestCase):
    def test_valor_total_confere(self):
        texto = (
            "...o valor total de R$ 18.001,20 (dezoito mil e um reais e "
            "vinte centavos)..."
        )
        resultado = extrair_valor_documento(texto)
        self.assertIsNotNone(resultado)
        self.assertEqual(resultado["cifra"], "18.001,20")
        self.assertIs(resultado["confere"], True)

    def test_valor_global_nao_confere(self):
        texto = "...valor global de R$ 37.000,00 (trinta e oito mil reais)..."
        resultado = extrair_valor_documento(texto)
        self.assertIsNotNone(resultado)
        self.assertIs(resultado["confere"], False)

    def test_montante(self):
        texto = "...o montante de R$ 54.156,00 (cinquenta e quatro mil e cento e cinquenta e seis reais)..."
        resultado = extrair_valor_documento(texto)
        self.assertIsNotNone(resultado)
        self.assertIs(resultado["confere"], True)

    def test_sem_frase_ancora_devolve_none(self):
        texto = "Este documento não menciona nenhuma cláusula de preço reconhecível."
        self.assertIsNone(extrair_valor_documento(texto))

    def test_texto_vazio_devolve_none(self):
        self.assertIsNone(extrair_valor_documento(""))

    def test_periodicidade_mensal_opcional(self):
        # Chave nova opcional, sem alterar o contrato já testado.
        texto = "...o valor mensal de R$ 5.000,00 (cinco mil reais)..."
        resultado = extrair_valor_documento(texto)
        self.assertIsNotNone(resultado)
        self.assertEqual(resultado["cifra"], "5.000,00")
        self.assertEqual(resultado["periodicidade"], "mensal")

    def test_periodicidade_global_pela_ancora_valor_global(self):
        texto = "...valor global de R$ 37.000,00 (trinta e sete mil reais)..."
        resultado = extrair_valor_documento(texto)
        self.assertIsNotNone(resultado)
        self.assertEqual(resultado["periodicidade"], "global")

    def test_parcelas_opcional(self):
        texto = (
            "...o valor total de R$ 18.001,20 (dezoito mil e um reais e "
            "vinte centavos), pago em 12 parcelas mensais..."
        )
        resultado = extrair_valor_documento(texto)
        self.assertIsNotNone(resultado)
        self.assertEqual(resultado["parcelas"], 12)

    def test_sem_pistas_continua_com_exatamente_tres_chaves(self):
        # Regressão da Fase 32/33/34: sem periodicidade/parcelas no texto,
        # o dict continua {"cifra", "extenso", "confere"} — nada a mais.
        texto = "...o valor total de R$ 18.001,20 (dezoito mil e um reais e vinte centavos)..."
        resultado = extrair_valor_documento(texto)
        self.assertEqual(set(resultado.keys()), {"cifra", "extenso", "confere"})


class TestExtrairContratado(unittest.TestCase):
    def test_cnpj_do_contratado_ignora_cnpj_do_cfc_com_erro_de_modelo(self):
        # (a) CNPJ do CFC citado ANTES do CNPJ do contratado, com o erro de
        # modelo do próprio CFC ("3.618.570/0001-07") — nunca escolhido.
        texto = (
            "CONTRATO Nº 08/2026, QUE FAZEM ENTRE SI O CONSELHO FEDERAL DE "
            "CONTABILIDADE E A EMPRESA GOSHME TECNOLOGIA LTDA.\n\n"
            "Aos dezoito dias do mês de setembro de 2026, de um lado o CONSELHO "
            "FEDERAL DE CONTABILIDADE, CNPJ sob o nº 3.618.570/0001-07, e de "
            "outro lado a empresa GOSHME TECNOLOGIA LTDA, inscrita no CNPJ sob "
            "o nº 12.345.678/0001-99, neste ato denominada CONTRATADA.\n\n"
            "CLÁUSULA PRIMEIRA – DO OBJETO\n"
            "1.1. O objeto do presente contrato é a prestação de serviços."
        )
        resultado = extrair_contratado(texto)
        self.assertEqual(resultado["cnpj"], "12.345.678/0001-99")

    def test_razao_social_pela_regex_do_preambulo(self):
        # (b) razão social lida do parágrafo de qualificação das partes.
        texto = (
            "CONTRATO Nº 08/2026, QUE FAZEM ENTRE SI O CONSELHO FEDERAL DE "
            "CONTABILIDADE E A EMPRESA GOSHME TECNOLOGIA LTDA.\n\n"
            "Aos dezoito dias do mês de setembro de 2026, de um lado o CONSELHO "
            "FEDERAL DE CONTABILIDADE, CNPJ sob o nº 3.618.570/0001-07, e de "
            "outro lado a empresa GOSHME TECNOLOGIA LTDA, inscrita no CNPJ sob "
            "o nº 12.345.678/0001-99, neste ato denominada CONTRATADA.\n\n"
            "CLÁUSULA PRIMEIRA – DO OBJETO\n"
            "1.1. O objeto do presente contrato é a prestação de serviços."
        )
        resultado = extrair_contratado(texto)
        self.assertEqual(resultado["razao_social"], "GOSHME TECNOLOGIA LTDA")
        self.assertEqual(resultado["fonte"], "preambulo")

    def test_razao_social_pelo_fallback_do_titulo(self):
        # (c) o preâmbulo não traz "..., inscrit..." — cai para o título.
        texto = (
            "CONTRATO Nº 15/2026, QUE CELEBRAM ENTRE SI O CONSELHO FEDERAL DE "
            "CONTABILIDADE E A EMPRESA ACME SERVIÇOS LTDA.\n\n"
            "Pelo presente instrumento, o CFC ajusta com a contratada acima "
            "qualificada, mediante as cláusulas e condições seguintes.\n\n"
            "CLÁUSULA PRIMEIRA – DO OBJETO\n"
            "1.1. Texto do objeto."
        )
        resultado = extrair_contratado(texto)
        self.assertEqual(resultado["razao_social"], "ACME SERVIÇOS LTDA")
        self.assertEqual(resultado["fonte"], "titulo")
        self.assertIsNone(resultado["cnpj"])

    def test_pessoa_fisica_sem_cnpj_no_texto(self):
        # (d) contratado pessoa física — placeholder literal, nunca um nome
        # real; sem nenhum CNPJ (do contratado) no texto.
        texto = (
            "CONTRATO Nº 02/2026, QUE CELEBRAM ENTRE SI O CONSELHO FEDERAL DE "
            "CONTABILIDADE E [pessoa física omitida].\n\n"
            "De um lado o CONSELHO FEDERAL DE CONTABILIDADE, CNPJ sob o nº "
            "33.618.570/0001-07, e de outro lado [pessoa física omitida], "
            "inscrito no CPF sob o nº 000.000.000-00, residente e domiciliado "
            "nesta capital.\n\n"
            "CLÁUSULA PRIMEIRA – DO OBJETO\n"
            "1.1. Texto do objeto."
        )
        resultado = extrair_contratado(texto)
        self.assertIsNone(resultado["cnpj"])
        self.assertEqual(resultado["razao_social"], "[pessoa física omitida]")

    def test_texto_sem_nenhuma_frase_reconhecivel(self):
        resultado = extrair_contratado("Texto qualquer sem qualificação de partes.")
        self.assertEqual(
            resultado, {"razao_social": None, "cnpj": None, "fonte": None}
        )

    def test_texto_vazio(self):
        resultado = extrair_contratado("")
        self.assertEqual(
            resultado, {"razao_social": None, "cnpj": None, "fonte": None}
        )

    def test_razao_social_nao_vaza_o_paragrafo_do_cfc_item_3(self):
        # Achado real do item 3 (contrato 08/2026, 18/09/2026): título e
        # parágrafo de qualificação em linhas consecutivas, SEM linha em
        # branco entre eles — antes da correção, `razao_social` gravava o
        # preâmbulo inteiro do CONTRATANTE (202 caracteres).
        texto = (
            "CONTRATO Nº 08/2026, QUE FAZEM ENTRE SI O CONSELHO FEDERAL DE "
            "CONTABILIDADE E A GOSHME SOLUÇÕES PARA A INTERNET LTDA\n"
            "O Conselho Federal de Contabilidade , por intermédio do "
            "Departamento de Licitações e Contratos, com sede no SAUS "
            "Quadra 5, Bloco J, Ed. CFC, na cidade de Brasília/DF, "
            "inscrito(a) no CNPJ sob o nº 33.618.570/0001-07, neste ato "
            "representado pelo Vice Presidente Fulano de Tal, doravante "
            "denominado CONTRATANTE, e a GOSHME SOLUÇÕES PARA A INTERNET "
            "LTDA, inscrita no CNPJ nº 07.112.529/0001-46, com sede na Rua "
            "X, nº 1, doravante designada CONTRATADA, resolvem celebrar o "
            "presente contrato.\n\n"
            "CLÁUSULA PRIMEIRA – DO OBJETO\n"
            "1.1. Texto do objeto."
        )
        resultado = extrair_contratado(texto)
        self.assertEqual(
            resultado["razao_social"], "GOSHME SOLUÇÕES PARA A INTERNET LTDA"
        )
        self.assertEqual(resultado["cnpj"], "07.112.529/0001-46")
        self.assertEqual(resultado["fonte"], "preambulo")

    def test_razao_social_titulo_quando_preambulo_nao_repete_o_nome(self):
        # Título traz "...E A EMPRESA X"; o parágrafo de qualificação NÃO
        # repete "e a X, inscrit..." (fala só "a contratada acima
        # qualificada") — preâmbulo não casa, cai para o título.
        texto = (
            "CONTRATO Nº 30/2026, QUE FAZEM ENTRE SI O CONSELHO FEDERAL DE "
            "CONTABILIDADE E A EMPRESA BETA SISTEMAS LTDA.\n\n"
            "O Conselho Federal de Contabilidade, por intermédio do "
            "Departamento de Licitações e Contratos, inscrito no CNPJ sob "
            "o nº 33.618.570/0001-07, neste ato representado pelo "
            "Vice-Presidente, doravante denominado CONTRATANTE, e a "
            "contratada acima qualificada, doravante designada "
            "CONTRATADA, resolvem celebrar o presente contrato.\n\n"
            "CLÁUSULA PRIMEIRA – DO OBJETO\n"
            "1.1. Texto do objeto."
        )
        resultado = extrair_contratado(texto)
        self.assertEqual(resultado["razao_social"], "BETA SISTEMAS LTDA")
        self.assertEqual(resultado["fonte"], "titulo")

    def test_razao_social_absurda_maior_que_255_cai_para_none(self):
        # Nem preâmbulo nem título dão uma razão social plausível ->
        # `_razao_valida` rejeita e o resultado final é `None`.
        razao_longa = "X" * 300
        texto = (
            "CONTRATO Nº 40/2026 - objeto qualquer.\n\n"
            f"De um lado o CONTRATANTE, e a {razao_longa}, inscrita no "
            "CNPJ sob o nº 12.345.678/0001-99, doravante designada "
            "CONTRATADA.\n\n"
            "CLÁUSULA PRIMEIRA – DO OBJETO\n"
            "1.1. Texto do objeto."
        )
        resultado = extrair_contratado(texto)
        self.assertIsNone(resultado["razao_social"])
        self.assertIsNone(resultado["fonte"])

    def test_razao_social_absurda_contem_conselho_federal_cai_para_none(self):
        texto = (
            "CONTRATO Nº 41/2026 - objeto qualquer.\n\n"
            "De um lado o CONTRATANTE, e a Conselho Federal de "
            "Contabilidade Consultoria Ltda, inscrita no CNPJ sob o nº "
            "12.345.678/0001-99, doravante designada CONTRATADA.\n\n"
            "CLÁUSULA PRIMEIRA – DO OBJETO\n"
            "1.1. Texto do objeto."
        )
        resultado = extrair_contratado(texto)
        self.assertIsNone(resultado["razao_social"])
        self.assertIsNone(resultado["fonte"])

    def test_razao_social_nao_vaza_o_endereco_item_5(self):
        # Achado real do item 5 (contrato 98/2024, CAESB, 18/09/2026): o
        # preâmbulo passa direto de "– CAESB" para ", com sede no..." — sem
        # "inscrit"/"sociedade"/"estabelecid" antes do endereço — e a
        # captura vazava nome + endereço + Inscrição Estadual inteiros.
        # Nota o espaço ANTES da vírgula ("CAESB , com sede"), erro de
        # digitação real do preâmbulo original — `_colapsar_espacos` tem
        # de absorvê-lo.
        texto = (
            "TERMO DE CONTRATO Nº 98/2024, QUE FAZEM ENTRE SI O CONSELHO "
            "FEDERAL DE CONTABILIDADE E A COMPANHIA DE SANEAMENTO "
            "AMBIENTAL DO DISTRITO FEDERAL – CAESB.\n\n"
            "Aos vinte dias do mês de setembro de 2024, de um lado o "
            "CONSELHO FEDERAL DE CONTABILIDADE, CNPJ sob o nº "
            "33.618.570/0001-07, doravante denominado CONTRATANTE, e a "
            "COMPANHIA DE SANEAMENTO AMBIENTAL DO DISTRITO FEDERAL – "
            "CAESB , com sede no Centro de Gestão Águas Emendadas, Av. "
            "Sibipiruna, lotes 13/21, Águas Claras, Brasília/DF, CEP "
            "71.928-720, Inscrição Estadual nº 07.324.667-001-67, "
            "inscrita no CNPJ sob o nº 00.082.024/0001-37, neste ato "
            "representada...\n\n"
            "CLÁUSULA PRIMEIRA – DO OBJETO\n"
            "1.1. Texto do objeto."
        )
        resultado = extrair_contratado(texto)
        self.assertEqual(
            resultado["razao_social"],
            "COMPANHIA DE SANEAMENTO AMBIENTAL DO DISTRITO FEDERAL – CAESB",
        )
        self.assertEqual(resultado["cnpj"], "00.082.024/0001-37")
        self.assertEqual(resultado["fonte"], "preambulo")

    def test_razao_social_termina_em_sociedade_de_economia_mista(self):
        # Variante do achado do item 5: terminador "sociedade de economia
        # mista" seguido de "com sede" — já funcionava antes (a "sociedade"
        # já era um terminador reconhecido), mantém-se verde depois da
        # lista de terminadores ampliada.
        texto = (
            "CONTRATO Nº 50/2024, QUE FAZEM ENTRE SI O CONSELHO FEDERAL DE "
            "CONTABILIDADE E A COMPANHIA X S.A..\n\n"
            "De um lado o CONSELHO FEDERAL DE CONTABILIDADE, CNPJ sob o "
            "nº 33.618.570/0001-07, doravante denominado CONTRATANTE, e a "
            "COMPANHIA X S.A., sociedade de economia mista, com sede na "
            "Capital Federal, inscrita no CNPJ sob o nº "
            "05.111.222/0001-33, neste ato representada...\n\n"
            "CLÁUSULA PRIMEIRA – DO OBJETO\n"
            "1.1. Texto do objeto."
        )
        resultado = extrair_contratado(texto)
        self.assertEqual(resultado["razao_social"], "COMPANHIA X S.A.")
        self.assertEqual(resultado["fonte"], "preambulo")

    def test_razao_social_com_cep_na_captura_cai_para_titulo(self):
        # Rede de segurança de `_razao_valida` (RE_SINAL_ENDERECO): mesmo
        # quando a captura do preâmbulo consegue vazar um pedaço de
        # endereço (aqui, "CEP" sem vírgula/terminador antes dele), o
        # resultado cai para o fallback do título em vez de gravar lixo.
        texto = (
            "CONTRATO Nº 60/2024, QUE FAZEM ENTRE SI O CONSELHO FEDERAL DE "
            "CONTABILIDADE E A EMPRESA TESTE LTDA.\n\n"
            "De um lado o CONSELHO FEDERAL DE CONTABILIDADE, CNPJ sob o "
            "nº 33.618.570/0001-07, doravante denominado CONTRATANTE, e a "
            "EMPRESA TESTE CEP 12345 LTDA, inscrita no CNPJ sob o nº "
            "05.111.222/0001-33, neste ato representada...\n\n"
            "CLÁUSULA PRIMEIRA – DO OBJETO\n"
            "1.1. Texto do objeto."
        )
        resultado = extrair_contratado(texto)
        self.assertEqual(resultado["razao_social"], "TESTE LTDA")
        self.assertEqual(resultado["fonte"], "titulo")

    def test_razao_social_termina_em_cada_terminador_novo_d_34_07(self):
        # Lista de terminadores ampliada — um caso
        # por terminador, fixture sintética (molde já usado nos testes
        # acima), nunca texto real de contrato.
        terminadores = [
            "associação",
            "fundação",
            "instituto",
            "organização",
            "cooperativa",
            "sindicato",
            "federação",
            "confederação",
            "empresa individual",
            "microempresa",
            "eireli",
        ]
        for terminador in terminadores:
            with self.subTest(terminador=terminador):
                texto = (
                    "CONTRATO Nº 70/2024, QUE FAZEM ENTRE SI O CONSELHO FEDERAL DE "
                    "CONTABILIDADE E A ENTIDADE MODELO LTDA.\n\n"
                    "De um lado o CONSELHO FEDERAL DE CONTABILIDADE, CNPJ sob o "
                    "nº 33.618.570/0001-07, doravante denominado CONTRATANTE, e a "
                    f"ENTIDADE MODELO LTDA, {terminador}, inscrita no CNPJ sob o "
                    "nº 05.111.222/0001-33, neste ato representada...\n\n"
                    "CLÁUSULA PRIMEIRA – DO OBJETO\n"
                    "1.1. Texto do objeto."
                )
                resultado = extrair_contratado(texto)
                self.assertEqual(resultado["razao_social"], "ENTIDADE MODELO LTDA")
                self.assertEqual(resultado["fonte"], "preambulo")

    def test_razao_social_ciee_item_100(self):
        # Achado real do item 100 (termo aditivo, CIEE, sondagem da Fase 34,
        # protocolo 1517335, transcrito na spec da Fase 33 §2): terminador
        # "associação" + sanidade rejeitando "filantrópica"/"sem fins
        # lucrativos"/"de direito privado" — a captura pára exatamente no
        # terminador certo, sem vazar o ruído depois dele.
        texto = (
            "TERCEIRO TERMO ADITIVO AO CONTRATO Nº 45/2023, QUE ENTRE SI "
            "CELEBRAM O CONSELHO FEDERAL DE CONTABILIDADE E O CENTRO DE "
            "INTEGRAÇÃO EMPRESA ESCOLA – CIEE.\n\n"
            "O CONSELHO FEDERAL DE CONTABILIDADE, entidade de direito "
            "público interno, devidamente inscrito no CNPJ n.º "
            "33.618.570/0001-07, doravante denominada CONTRATANTE e o "
            "CENTRO DE INTEGRAÇÃO EMPRESA ESCOLA – CIEE, associação "
            "filantrópica de direito privado, sem fins lucrativos e de "
            "fins não econômicos, beneficente de assistência social, "
            "inscrita no CNPJ/ME sob nº. 61.600.839/0001-55, neste ato "
            "denominado CONTRATADA.\n\n"
            "CLÁUSULA PRIMEIRA – DO OBJETO\n"
            "1.1. Texto do objeto."
        )
        resultado = extrair_contratado(texto)
        self.assertEqual(
            resultado["razao_social"], "CENTRO DE INTEGRAÇÃO EMPRESA ESCOLA – CIEE"
        )
        self.assertEqual(resultado["cnpj"], "61.600.839/0001-55")
        self.assertEqual(resultado["fonte"], "preambulo")

    def test_razao_social_rejeita_ruido_filantropica_sem_terminador_valido(self):
        # `_razao_valida`, via `extrair_contratado`: só "filantrópica"/"sem
        # fins lucrativos"/"de direito privado" aparecem, sem NENHUM
        # terminador válido antes deles — a captura cai para o fallback do
        # título (ou None, se o título também não casar).
        texto = (
            "CONTRATO Nº 71/2024, QUE FAZEM ENTRE SI O CONSELHO FEDERAL DE "
            "CONTABILIDADE E A EMPRESA ENTIDADE SEM TERMINADOR LTDA.\n\n"
            "De um lado o CONSELHO FEDERAL DE CONTABILIDADE, CNPJ sob o "
            "nº 33.618.570/0001-07, doravante denominado CONTRATANTE, e a "
            "ENTIDADE SEM TERMINADOR filantrópica, sem fins lucrativos, de "
            "direito privado, neste ato representada...\n\n"
            "CLÁUSULA PRIMEIRA – DO OBJETO\n"
            "1.1. Texto do objeto."
        )
        resultado = extrair_contratado(texto)
        self.assertEqual(resultado["razao_social"], "ENTIDADE SEM TERMINADOR LTDA")
        self.assertEqual(resultado["fonte"], "titulo")


class TestExtrairProcedencia(unittest.TestCase):
    def test_dispensa_com_disputa_padrao_compras_gov(self):
        # (e)
        texto = "...decorrente da Dispensa de Licitação n. 90027/2024, nos termos do art. 75..."
        resultado = extrair_procedencia(texto)
        self.assertEqual(resultado["numero"], "90027/2024")
        self.assertEqual(resultado["modalidade_catalogo"], "dispensa com disputa")

    def test_dispensa_sem_disputa_padrao_383500(self):
        # (f)
        texto = "...decorrente da Dispensa de Licitação nº 383500-6/2026, conforme despacho..."
        resultado = extrair_procedencia(texto)
        self.assertEqual(resultado["numero"], "383500-6/2026")
        self.assertEqual(resultado["modalidade_catalogo"], "dispensa sem disputa")

    def test_pregao_eletronico(self):
        # (g)
        texto = "...decorrente do Pregão Eletrônico nº 90012/2025, celebrado entre as partes..."
        resultado = extrair_procedencia(texto)
        self.assertEqual(resultado["modalidade_texto"], "Pregão Eletrônico")
        self.assertEqual(resultado["numero"], "90012/2025")
        self.assertEqual(resultado["modalidade_catalogo"], "pregao eletronico")

    def test_numero_com_espacos_ao_redor_do_hifen_normalizado(self):
        # (h)
        texto = "...decorrente da Inexigibilidade de Licitação n. 383500 - 24/2025, tendo em vista..."
        resultado = extrair_procedencia(texto)
        self.assertEqual(resultado["numero"], "383500-24/2025")
        self.assertEqual(resultado["modalidade_catalogo"], "inexigibilidade")

    def test_dispensa_em_formato_desconhecido_devolve_none(self):
        # (i)
        texto = "...decorrente da Dispensa Eletrônica nº 12345/2025, nos termos do art. 75..."
        resultado = extrair_procedencia(texto)
        self.assertIsNone(resultado["modalidade_catalogo"])

    def test_sem_frase_ancora_devolve_tudo_none(self):
        # (j)
        resultado = extrair_procedencia(
            "Este documento não menciona nenhuma modalidade de contratação."
        )
        self.assertEqual(
            resultado,
            {"modalidade_texto": None, "numero": None, "modalidade_catalogo": None},
        )

    def test_texto_vazio(self):
        resultado = extrair_procedencia("")
        self.assertEqual(
            resultado,
            {"modalidade_texto": None, "numero": None, "modalidade_catalogo": None},
        )

    def test_campo_estruturado_modalidade_ordem_de_fornecimento_item_19(self):
        # Achado real do item 19 (Ordem de Fornecimento, sondagem da Fase
        # 34, protocolo 1282080, spec da Fase 33 §2): campo estruturado
        # "Modalidade: <mod> nº <número>", fora de qualquer prosa
        # "decorrente d[ao]...".
        texto = (
            "DADOS CONTRATUAIS\n"
            "Número do processo SEI: 90796110000012.000049/2024-08\n"
            "Prazo de entrega/execução: 30 (trinta) dias\n"
            "Modalidade: Pregão Eletrônico nº 90010/2025\n"
            "Área(s) Demandante(s): DECER\n"
        )
        resultado = extrair_procedencia(texto)
        self.assertEqual(resultado["modalidade_texto"], "Pregão Eletrônico")
        self.assertEqual(resultado["numero"], "90010/2025")
        self.assertEqual(resultado["modalidade_catalogo"], "pregao eletronico")

    def test_campo_estruturado_modalidade_ordem_de_fornecimento_item_40(self):
        # Achado real do item 40 (Ordem de Fornecimento, sondagem da Fase
        # 34, protocolo 1504465): mesmo campo estruturado, confirma o
        # padrão repetido (não é caso isolado).
        texto = (
            "DADOS CONTRATUAIS\n"
            "Número do processo SEI: 90796110000031.000012/2026-13\n"
            "Prazo de entrega/execução: 15 (quinze) dias corridos\n"
            "Modalidade: Pregão Eletrônico nº 90005/2026\n"
            "Área(s) Demandante(s): GEX-REIP\n"
        )
        resultado = extrair_procedencia(texto)
        self.assertEqual(resultado["numero"], "90005/2026")
        self.assertEqual(resultado["modalidade_catalogo"], "pregao eletronico")

    def test_decorrente_prosa_tem_prioridade_sobre_campo_estruturado(self):
        # A prosa "decorrente d[ao]..." (contrato) continua tentada primeiro
        # — o campo estruturado (Ordem de Fornecimento) é só um fallback
        # quando a prosa não casa, nunca o inverso (mesma ordem de tentativa
        # já usada nas outras afinações deste plano).
        texto = (
            "...decorrente da Dispensa de Licitação n. 90027/2024, nos termos do art. 75...\n"
            "Modalidade: Pregão Eletrônico nº 90010/2025\n"
        )
        resultado = extrair_procedencia(texto)
        self.assertEqual(resultado["modalidade_texto"], "Dispensa de Licitação")
        self.assertEqual(resultado["numero"], "90027/2024")

    def test_duplicacao_de_licitacao_tolerada_item_105(self):
        # Achado real do item 105 (sondagem da Fase 34, protocolo 0120055):
        # o instrumento original do CFC repete "de Licitação" por erro de
        # redação — "decorrente da Inexigibilidade de Licitação de
        # Licitação n. <número>". `modalidade_texto` continua só
        # "Inexigibilidade de Licitação", sem a duplicação.
        texto = "...decorrente da Inexigibilidade de Licitação de Licitação n. 13/2023, mediante..."
        resultado = extrair_procedencia(texto)
        self.assertEqual(resultado["modalidade_texto"], "Inexigibilidade de Licitação")
        self.assertEqual(resultado["numero"], "13/2023")
        self.assertEqual(resultado["modalidade_catalogo"], "inexigibilidade")

    def test_numero_com_hifen_solto_antes_do_digito_vira_none(self):
        # Achado dados M6 (QA 30/09/2026): item 14 de 2026 — hífen solto
        # antes do número captura lixo e sobrescreve "90015/2025" já
        # digitado. Com o dígito obrigatório no início, a regex inteira
        # deixa de casar.
        texto = "...decorrente da Dispensa de Licitação nº -90015/2025,"
        resultado = extrair_procedencia(texto)
        self.assertIsNone(resultado["numero"])
        self.assertIsNone(resultado["modalidade_catalogo"])

    def test_numero_do_campo_estruturado_com_hifen_solto_vira_none(self):
        # Mesmo achado, forma do campo estruturado (RE_PROCEDENCIA_CAMPO).
        texto = "Modalidade: Dispensa Eletrônica nº -26/2026"
        resultado = extrair_procedencia(texto)
        self.assertIsNone(resultado["numero"])

    def test_dispensa_com_numero_sequencial_sem_prefixo_fica_pendencia(self):
        # Achado real dos itens 89/101 (sondagem da Fase 34, protocolos
        # 0099383/0127547): número puramente sequencial ("NN/AAAA"), sem o
        # prefixo `9####` (compras.gov) nem `383500-` (interno) —
        # `modalidade_texto`/`numero` são lidos normalmente, mas
        # `modalidade_catalogo` fica `None` (pendência esperada,
        # nenhum casamento forçado).
        texto = "...decorrente da Dispensa de Licitação n. 18/2023, mediante as cláusulas..."
        resultado = extrair_procedencia(texto)
        self.assertEqual(resultado["modalidade_texto"], "Dispensa de Licitação")
        self.assertEqual(resultado["numero"], "18/2023")
        self.assertIsNone(resultado["modalidade_catalogo"])


class TestExtrairVigencia(unittest.TestCase):
    def test_prazo_desde_assinatura_item_2(self):
        # item 2 do checkpoint: 13/03/2026 a 12/03/2028, N=24 meses.
        texto = (
            "CLÁUSULA SEGUNDA – DA VIGÊNCIA\n"
            "2.1. O prazo de vigência deste contrato é de 24 (vinte e quatro) "
            "meses contados da data de assinatura."
        )
        resultado = extrair_vigencia(texto, "13/03/2026 09:00")
        self.assertEqual(resultado["forma"], "prazo_desde_assinatura")
        self.assertEqual(resultado["inicio"], date(2026, 3, 13))
        self.assertEqual(resultado["fim"], date(2028, 3, 12))

    def test_prazo_sem_ancora_item_11(self):
        # item 11 do checkpoint: 06/02/2026 a 05/02/2031, N=60 meses, sem a
        # âncora "contados... assinatura".
        texto = (
            "CLÁUSULA SEGUNDA – DA VIGÊNCIA\n"
            "2.1. O prazo deste Termo de Contrato é de 60 (sessenta) meses, "
            "prorrogável nos termos da lei."
        )
        resultado = extrair_vigencia(texto, "06/02/2026 10:00")
        self.assertEqual(resultado["forma"], "prazo_sem_ancora")
        self.assertEqual(resultado["inicio"], date(2026, 2, 6))
        self.assertEqual(resultado["fim"], date(2031, 2, 5))

    def test_interregno_nunca_e_lido_como_vigencia(self):
        # Achado dados M5 (QA 30/09/2026) — "interregno de N meses" não é a
        # vigência do instrumento.
        texto = (
            "O contrato terá interregno de 12 (doze) meses entre uma "
            "renovação e outra."
        )
        resultado = extrair_vigencia(texto, "06/02/2026 10:00")
        self.assertIsNone(resultado["forma"])
        self.assertIsNone(resultado["inicio"])

    def test_garantia_nunca_e_lida_como_vigencia(self):
        texto = "A garantia de 60 (sessenta) meses cobre defeitos de fabricação."
        resultado = extrair_vigencia(texto, "06/02/2026 10:00")
        self.assertIsNone(resultado["forma"])
        self.assertIsNone(resultado["inicio"])

    def test_vigencia_sem_ancora_continua_funcionando_com_a_palavra_vigencia_perto(self):
        texto = "O prazo de vigência deste instrumento contratual é de 12 (doze) meses."
        resultado = extrair_vigencia(texto, "06/02/2026 10:00")
        self.assertEqual(resultado["forma"], "prazo_sem_ancora")
        self.assertEqual(resultado["inicio"], date(2026, 2, 6))
        self.assertEqual(resultado["fim"], date(2027, 2, 5))

    def test_assinatura_implausivel_2099_nunca_vira_ancora_de_vigencia(self):
        # Achado dados B3 — assinatura datada de um ano muito no futuro
        # nunca serve de âncora.
        texto = (
            "CLÁUSULA SEGUNDA – DA VIGÊNCIA\n"
            "2.1. O prazo de vigência deste contrato é de 24 (vinte e quatro) "
            "meses contados da data de assinatura."
        )
        resultado = extrair_vigencia(texto, "31/12/2099 10:00")
        self.assertIsNone(resultado["forma"])

    def test_fim_antes_do_inicio_nunca_e_aceito(self):
        texto = (
            "CLÁUSULA SEGUNDA – DA VIGÊNCIA\n"
            "2.1. A vigência tem prazo com início na data de 31/12/2026 e "
            "encerramento em 01/01/2026."
        )
        resultado = extrair_vigencia(texto, None)
        self.assertIsNone(resultado["forma"])
        self.assertIsNone(resultado["inicio"])
        self.assertIsNone(resultado["fim"])

    def test_datas_explicitas(self):
        texto = (
            "CLÁUSULA SEGUNDA – DA VIGÊNCIA\n"
            "2.1. A vigência tem prazo com início na data de 11/12/2025 e "
            "encerramento em 10/12/2026."
        )
        resultado = extrair_vigencia(texto, None)
        self.assertEqual(resultado["forma"], "datas_explicitas")
        self.assertEqual(resultado["inicio"], date(2025, 12, 11))
        self.assertEqual(resultado["fim"], date(2026, 12, 10))

    def test_divergencia_algarismo_e_extenso_devolve_tudo_none(self):
        texto = (
            "CLÁUSULA SEGUNDA – DA VIGÊNCIA\n"
            "2.1. O prazo de vigência deste contrato é de 24 (doze) meses "
            "contados da data de assinatura."
        )
        resultado = extrair_vigencia(texto, "01/01/2026 08:00")
        self.assertEqual(
            resultado, {"inicio": None, "fim": None, "forma": None}
        )

    def test_sem_data_assinatura_devolve_tudo_none(self):
        texto = (
            "CLÁUSULA SEGUNDA – DA VIGÊNCIA\n"
            "2.1. O prazo de vigência deste contrato é de 24 (vinte e quatro) "
            "meses contados da data de assinatura."
        )
        resultado = extrair_vigencia(texto, None)
        self.assertEqual(
            resultado, {"inicio": None, "fim": None, "forma": None}
        )

    def test_texto_sem_nenhuma_clausula_devolve_tudo_none(self):
        resultado = extrair_vigencia(
            "Este documento não menciona nenhuma cláusula de vigência.",
            "01/01/2026 08:00",
        )
        self.assertEqual(
            resultado, {"inicio": None, "fim": None, "forma": None}
        )

    def test_prazo_desde_assinatura_com_virgula_antes_de_contados_item_105(self):
        # Achado real do item 105 (sondagem da Fase 34, protocolo 0120055):
        # o instrumento tem uma vírgula entre a unidade e "contados"
        # ("... meses, contados da data de assinatura..."), ausente do
        # molde já testado da Fase 33 — variante tolerada da forma (a), sem
        # forma nova.
        texto = (
            "CLÁUSULA SEGUNDA – VIGÊNCIA E PRORROGAÇÃO\n"
            "2.1. O prazo de vigência da contratação é de 36 (trinta e seis) "
            "meses, contados da data de assinatura, na forma do artigo 105 "
            "da Lei n° 14.133/2021."
        )
        resultado = extrair_vigencia(texto, "01/09/2023 08:00")
        self.assertEqual(resultado["forma"], "prazo_desde_assinatura")
        self.assertEqual(resultado["inicio"], date(2023, 9, 1))
        self.assertEqual(resultado["fim"], date(2026, 8, 31))

    def test_datas_intervalo_item_44(self):
        # Achado real do item 44 (sondagem da Fase 34, protocolo 1250786):
        # forma nova "datas_intervalo" — mesma ideia da forma (b), conector
        # "a" no lugar de "com início na data de ... e encerramento em ...".
        texto = (
            "CLÁUSULA SEGUNDA – VIGÊNCIA E PRORROGAÇÃO\n"
            "2.1. O prazo de vigência da contratação é de 18/03/2026 a "
            "18/03/2027, prorrogável sucessivamente por até 10 anos, na "
            "forma dos artigos 106 e 107 da Lei n.º 14.133, de 2021."
        )
        resultado = extrair_vigencia(texto, None)
        self.assertEqual(resultado["forma"], "datas_intervalo")
        self.assertEqual(resultado["inicio"], date(2026, 3, 18))
        self.assertEqual(resultado["fim"], date(2027, 3, 18))

    def test_assinatura_ate_data_item_138(self):
        # Achado real do item 138 (sondagem da Fase 34, protocolo 1294043):
        # forma nova "assinatura_ate_data" — início = data de assinatura,
        # fim = data explícita ("... terá vigência a partir de sua
        # assinatura até DD/MM/AAAA.").
        texto = (
            "CLÁUSULA SEGUNDA – VIGÊNCIA E PRORROGAÇÃO\n"
            "2.1. O CONTRATO terá vigência a partir de sua assinatura até "
            "30/06/2026.\n"
            "2.1.1. O prazo de vigência será automaticamente prorrogado..."
        )
        resultado = extrair_vigencia(texto, "15/01/2026 09:00")
        self.assertEqual(resultado["forma"], "assinatura_ate_data")
        self.assertEqual(resultado["inicio"], date(2026, 1, 15))
        self.assertEqual(resultado["fim"], date(2026, 6, 30))

    def test_assinatura_ate_data_sem_data_assinatura_devolve_tudo_none(self):
        # Forma nova (e) também exige `data_assinatura` — sem ela, não há
        # "início" para compor o resultado; nunca lança exceção.
        texto = (
            "CLÁUSULA SEGUNDA – VIGÊNCIA E PRORROGAÇÃO\n"
            "2.1. O CONTRATO terá vigência a partir de sua assinatura até "
            "30/06/2026."
        )
        resultado = extrair_vigencia(texto, None)
        self.assertEqual(resultado, {"inicio": None, "fim": None, "forma": None})


class TestExtrairProrrogacao(unittest.TestCase):
    def test_forma_datas_explicitas(self):
        texto = (
            "1.1. O prazo do contrato fica prorrogado a partir de 01/03/2026 "
            "até 28/02/2027."
        )
        resultado = extrair_prorrogacao(texto)
        self.assertEqual(resultado["inicio"], date(2026, 3, 1))
        self.assertEqual(resultado["fim"], date(2027, 2, 28))

    def test_forma_por_mais_n_meses_item_6(self):
        # item 6 do checkpoint: aditivo assinado 11/01/2026, "por mais 12
        # meses" -> fim 10/01/2027.
        texto = (
            "TERMO ADITIVO Nº 01/2026\n"
            "1.1. Fica prorrogado o prazo de vigência do contrato por mais "
            "12 (doze) meses, a partir de 11/01/2026."
        )
        resultado = extrair_prorrogacao(texto)
        self.assertEqual(resultado["inicio"], date(2026, 1, 11))
        self.assertEqual(resultado["fim"], date(2027, 1, 10))

    def test_texto_sem_nenhuma_clausula_devolve_tudo_none(self):
        resultado = extrair_prorrogacao(
            "Este documento não menciona nenhuma prorrogação."
        )
        self.assertEqual(resultado, {"inicio": None, "fim": None})

    def test_texto_vazio(self):
        resultado = extrair_prorrogacao("")
        self.assertEqual(resultado, {"inicio": None, "fim": None})


class TestExtrairApostilamento(unittest.TestCase):
    """Fixtures sintéticas derivadas dos moldes generalizados da spec da
    Fase 33 §2, subseção "Padrões — apostilamento (Fase 35)" —
    nunca texto literal de contrato, nunca nome de pessoa física. Cada
    `def test_...` cobre um padrão confirmado ou uma hipótese refutada pela
    sondagem real (achado real substitui hipótese, sem casamento
    forçado)."""

    def test_reajuste_cifra_a_cifra_molde_dominante(self):
        # Molde confirmado em 14/17 instrumentos da sondagem (itens 43, 50,
        # 57, 96, 61, 63, 56, 59, 97, 64, 70, 80, 100, 106) — a hipótese
        # original (a) "dotação/empenho puro" para os itens 43/50/57 foi
        # REFUTADA pelo texto real: são, na prática, este mesmo molde.
        texto = (
            "... tendo em vista o direito resguardado ao reajuste conforme "
            "Cláusula Sétima do Contrato, resolve apostilar o Contrato nº "
            "01/2026. CLÁUSULA PRIMEIRA - DO VALOR. Valor atual do "
            "contrato: R$ 10.000,00 (dez mil reais). Novo valor do "
            "contrato: R$ 10.400,00 (dez mil e quatrocentos reais), "
            "conforme Despacho SEI 999999. O valor contratual foi "
            "reajustado com base no índice IPCA acumulado, na ordem de "
            "4,00% (quatro por cento), conforme detalhamento constante no "
            "despacho SEI 999998."
        )
        resultado = extrair_apostilamento(texto)
        self.assertIsNotNone(resultado)
        self.assertEqual(resultado["natureza"], "reajuste")
        self.assertEqual(resultado["valor_anterior"]["cifra"], "10.000,00")
        self.assertIs(resultado["valor_anterior"]["confere"], True)
        self.assertEqual(resultado["valor_novo"]["cifra"], "10.400,00")
        self.assertIs(resultado["valor_novo"]["confere"], True)
        self.assertEqual(resultado["indice"], "IPCA")
        self.assertEqual(resultado["percentual"], "4,00")
        self.assertIsNone(resultado["periodicidade"])

    def test_indice_icti_sem_percentual_no_texto(self):
        # Achado real (itens 96, 61, 63, 97, 64, 80, 100, 106): o índice
        # ICTI aparece só pelo nome, sem percentual explícito no corpo lido.
        texto = (
            "... tendo em vista o direito resguardado ao reajuste conforme "
            "Cláusula Sétima do Contrato, resolve apostilar. Valor do "
            "contrato: R$ 20.000,00 (vinte mil reais). Novo valor do "
            "contrato: R$ 20.800,00 (vinte mil e oitocentos reais). O "
            "valor contratual foi reajustado com base no Índice de Custos "
            "de Tecnologia da Informação - ICTI, conforme detalhamento "
            "constante no despacho SEI 111222."
        )
        resultado = extrair_apostilamento(texto)
        self.assertIsNotNone(resultado)
        self.assertEqual(resultado["indice"], "ICTI")
        self.assertIsNone(resultado["percentual"])

    def test_repactuacao_mesma_estrutura_palavra_diferente(self):
        # Nenhum dos 17 instrumentos reais usa "repactuad*" — todos usam
        # "reajuste" (spec §2). Fixture sintética: mesmo molde, sinônimo
        # legal (reajuste/repactuação são a mesma cláusula de revisão de
        # valor na Lei 14.133/2021).
        texto = (
            "... tendo em vista o direito resguardado à repactuação "
            "conforme Cláusula Sétima do Contrato, resolve apostilar. "
            "Valor do contrato: R$ 30.000,00 (trinta mil reais). Novo "
            "valor do contrato: R$ 31.000,00 (trinta e um mil reais)."
        )
        resultado = extrair_apostilamento(texto)
        self.assertIsNotNone(resultado)
        self.assertEqual(resultado["natureza"], "repactuacao")

    def test_valor_novo_sem_prefixo_rs_fica_pendencia_item_106(self):
        # Achado real (item 106, protocolo 1008024): "Novo valor do
        # contrato: 28.868,92 ..." sem "R$" — erro de digitação do
        # instrumento original do CFC. Nenhum casamento forçado:
        # valor_anterior é lido normalmente, valor_novo fica None.
        texto = (
            "... tendo em vista o direito resguardado ao reajuste conforme "
            "Cláusula Sétima do instrumento contratual, resolve apostilar. "
            "Valor do contrato: R$ 28.000,00 (vinte e oito mil reais). "
            "Novo valor do contrato: 28.868,92 (vinte e oito mil "
            "oitocentos e sessenta e oito reais e noventa e dois "
            "centavos). O valor contratual foi reajustado com base no "
            "Índice de Custos de Tecnologia da Informação - ICTI."
        )
        resultado = extrair_apostilamento(texto)
        self.assertIsNotNone(resultado)
        self.assertEqual(resultado["natureza"], "reajuste")
        self.assertEqual(resultado["valor_anterior"]["cifra"], "28.000,00")
        self.assertIsNone(resultado["valor_novo"])

    def test_periodicidade_mensal_duplicidade_mensal_x_anual_item_94(self):
        # Achado real (item 94, protocolos 0060245/0063897): "Valor mensal
        # atual" seguido de "Novo valor contratual ... mensais, totalizando
        # ... anuais" — periodicidade="mensal" (a âncora "Valor mensal
        # atual" vem primeiro, prioridade sobre o "anuais" do total).
        texto = (
            "... tendo em vista o direito resguardado ao reajuste quando "
            "da prorrogação autorizada na Cláusula Sexta do Contrato, "
            "resolve apostilar. Valor mensal atual: R$ 1.000,00 (mil "
            "reais). Novo valor contratual: R$ 1.050,00 (mil e cinquenta "
            "reais) mensais, totalizando R$ 12.600,00 (doze mil e "
            "seiscentos reais) anuais, retroativo a 1º de setembro de "
            "2022."
        )
        resultado = extrair_apostilamento(texto)
        self.assertIsNotNone(resultado)
        self.assertEqual(resultado["periodicidade"], "mensal")
        self.assertEqual(resultado["valor_anterior"]["cifra"], "1.000,00")
        self.assertEqual(resultado["valor_novo"]["cifra"], "1.050,00")

    def test_data_base_retroativo_a_dia_mes_por_extenso_ano(self):
        # Achado real (item 94): "retroativo a Dº de <mês por extenso> de
        # AAAA" — formato diferente da hipótese original ("a partir
        # de DD/MM/AAAA"), que NÃO se confirmou em nenhum dos 17 textos.
        texto = (
            "Novo valor contratual: R$ 1.050,00 (mil e cinquenta reais) "
            "mensais, retroativo a 1º de setembro de 2022."
        )
        resultado = extrair_apostilamento(texto)
        self.assertIsNotNone(resultado)
        self.assertEqual(resultado["data_base"], "2022-09-01")

    def test_sem_data_base_no_texto_devolve_none(self):
        texto = (
            "... reajuste conforme Cláusula Sétima do Contrato, resolve "
            "apostilar. Valor do contrato: R$ 5.000,00 (cinco mil reais). "
            "Novo valor do contrato: R$ 5.200,00 (cinco mil e duzentos "
            "reais)."
        )
        resultado = extrair_apostilamento(texto)
        self.assertIsNotNone(resultado)
        self.assertIsNone(resultado["data_base"])

    def test_periodicidade_anual_pela_ancora_valor_total_item_108(self):
        # Achado real (item 108, protocolos 0802566/1373298): "Valor total
        # anual da contratação: R$ Y (extenso)." — mesma âncora "valor
        # total" já reconhecida por extrair_valor_documento, agora
        # confirmada também em apostilamento; periodicidade="anual", NUNCA
        # "global" (a palavra "global" não aparece em nenhum dos 17
        # instrumentos lidos).
        texto = (
            "... tendo em vista o direito resguardado ao reajuste, "
            "previsto na Cláusula Sétima do Contrato, resolve-se apostilar "
            "o Contrato nº 05/2024. Valor anual atual de 10 postos: R$ "
            "60.000,00 (sessenta mil reais) mensais, totalizando R$ "
            "720.000,00 (setecentos e vinte mil reais). Valor atual de 1 "
            "posto: R$ 6.000,00 (seis mil reais) mensais, totalizando R$ "
            "72.000,00 (setenta e dois mil reais). Valor total anual da "
            "contratação: R$ 792.000,00 (setecentos e noventa e dois mil "
            "reais)."
        )
        resultado = extrair_apostilamento(texto)
        self.assertIsNotNone(resultado)
        self.assertEqual(resultado["periodicidade"], "anual")
        self.assertEqual(resultado["valor_novo"]["cifra"], "792.000,00")
        self.assertIsNone(resultado["valor_anterior"])

    def test_dotacao_nao_confirmada_clausula_dentro_de_reajuste_nao_dispara(self):
        # Achado real (item 94): a cláusula "CLÁUSULA TERCEIRA - DA DOTAÇÃO
        # ORÇAMENTÁRIA" aparece como cabeçalho de seção DENTRO de um
        # apostilamento de reajuste — nunca pode disparar
        # natureza="dotacao" por engano (hipótese (a) refutada
        # pela sondagem: nenhum dos 17 instrumentos lidos é dotação pura).
        texto = (
            "... tendo em vista o direito resguardado ao reajuste conforme "
            "Cláusula Sexta do Contrato, resolve apostilar. Valor mensal "
            "atual: R$ 1.000,00 (mil reais). Novo valor contratual: R$ "
            "1.050,00 (mil e cinquenta reais) mensais. CLÁUSULA TERCEIRA - "
            "DA DOTAÇÃO ORÇAMENTÁRIA. 3.1. A despesa decorrente desta "
            "contratação correrá à conta dos recursos orçamentários."
        )
        resultado = extrair_apostilamento(texto)
        self.assertIsNotNone(resultado)
        self.assertEqual(resultado["natureza"], "reajuste")

    def test_texto_sem_nenhuma_ancora_reconhecivel_devolve_none(self):
        texto = "Este documento não menciona nenhuma cláusula reconhecível."
        self.assertIsNone(extrair_apostilamento(texto))

    def test_texto_vazio_devolve_none(self):
        self.assertIsNone(extrair_apostilamento(""))


# ------------------ debug robo-valor-contratado-item64 (20/10/2026) ---------
# Trechos literais das cláusulas de valor do item 64 (contrato 24/2024 e os
# dois termos de apostilamento) — fixture `textos_item_64.json`, só as
# cláusulas de preço/valor, sem preâmbulo, assinatura nem nome de pessoa.

_TEXTOS_ITEM_64 = json.loads(
    (Path(__file__).parent / "fixtures" / "sei" / "textos_item_64.json").read_text(
        encoding="utf-8"
    )
)


class TestValorDocumentoPrefereTotalAoPeriodico(unittest.TestCase):
    """Ponto 1: "O valor mensal da contratação é de R$ 2.213,93 (...),
    perfazendo o valor total de R$ 79.701,70 (...)" — o valor do documento é
    o total, nunca o primeiro casamento só porque veio antes."""

    def test_contrato_item_64_devolve_o_valor_total(self):
        resultado = extrair_valor_documento(_TEXTOS_ITEM_64["contrato_0347594"])
        self.assertEqual(resultado["cifra"], "79.701,70")
        self.assertIs(resultado["confere"], True)
        self.assertNotIn(resultado.get("periodicidade"), ("mensal", "anual"))

    def test_anual_antes_do_global_devolve_o_global(self):
        texto = (
            "O valor anual é de R$ 12.000,00 (doze mil reais), perfazendo o "
            "valor global de R$ 36.000,00 (trinta e seis mil reais)."
        )
        resultado = extrair_valor_documento(texto)
        self.assertEqual(resultado["cifra"], "36.000,00")
        self.assertEqual(resultado["periodicidade"], "global")

    def test_total_antes_do_mensal_continua_o_total(self):
        texto = (
            "O valor total de R$ 36.000,00 (trinta e seis mil reais), sendo o "
            "valor mensal de R$ 1.000,00 (mil reais)."
        )
        self.assertEqual(extrair_valor_documento(texto)["cifra"], "36.000,00")

    def test_so_mensal_continua_devolvendo_o_mensal(self):
        # Sem total/global no texto, o periódico é o único valor lido — a
        # decisão de não gravá-lo como valor contratado é de `regras.py`.
        texto = "O valor mensal da contratação é de R$ 2.213,93 (dois mil duzentos e treze reais e noventa e três centavos)."
        resultado = extrair_valor_documento(texto)
        self.assertEqual(resultado["cifra"], "2.213,93")
        self.assertEqual(resultado["periodicidade"], "mensal")

    def test_total_com_extenso_errado_nao_tira_o_mensal_conferido(self):
        # Achado real (item 105, contrato 0120055): o extenso do total está
        # errado no próprio instrumento — o mensal conferido continua sendo
        # a leitura do documento (nunca troca um conferido por um não
        # conferido).
        texto = (
            "O valor mensal da contratação será de R$ 106.000,00 (cento e seis "
            "mil reais), perfazendo o valor total de R$ 3.905.040,00 (três "
            "milhões, novecentos e cinco reais e quarenta centavos)."
        )
        resultado = extrair_valor_documento(texto)
        self.assertEqual(resultado["cifra"], "106.000,00")
        self.assertIs(resultado["confere"], True)

    def test_nada_conferido_devolve_o_primeiro(self):
        texto = (
            "O valor total de R$ 10.000,00 (onze mil reais). O valor mensal de "
            "R$ 1.000,00 (dois mil reais)."
        )
        resultado = extrair_valor_documento(texto)
        self.assertEqual(resultado["cifra"], "10.000,00")
        self.assertIs(resultado["confere"], False)

    def test_total_anual_conta_como_periodico(self):
        # "valor total anual" é anual (item 108) — não é preferido a um
        # mensal anterior como se fosse global; vale o primeiro casamento.
        texto = (
            "Valor mensal de R$ 1.000,00 (mil reais). Valor total anual de "
            "R$ 12.000,00 (doze mil reais)."
        )
        resultado = extrair_valor_documento(texto)
        self.assertEqual(resultado["cifra"], "1.000,00")
        self.assertEqual(resultado["periodicidade"], "mensal")


class TestApostilamentoItem64TextosReais(unittest.TestCase):
    """Pontos 2 e 3: o 1º termo usa o molde "Valor do contrato / Novo valor
    do contrato"; o 2º usa "o novo valor global do contrato passa a ser de
    R$ X" (cláusula 2.3) — e cita valores por período que nunca são o
    global."""

    def test_primeiro_termo_novo_valor_do_contrato(self):
        resultado = extrair_apostilamento(_TEXTOS_ITEM_64["apostilamento_0967338"])
        self.assertEqual(resultado["natureza"], "reajuste")
        self.assertEqual(resultado["valor_anterior"]["cifra"], "79.701,70")
        self.assertEqual(resultado["valor_novo"]["cifra"], "82.744,93")
        self.assertIs(resultado["valor_novo"]["confere"], True)
        self.assertEqual(resultado["indice"], "ICTI")

    def test_segundo_termo_novo_valor_global_passa_a_ser_de(self):
        resultado = extrair_apostilamento(_TEXTOS_ITEM_64["apostilamento_1603102"])
        self.assertEqual(resultado["natureza"], "reajuste")
        self.assertEqual(resultado["valor_novo"]["cifra"], "83.575,71")
        self.assertIs(resultado["valor_novo"]["confere"], True)
        self.assertEqual(resultado["periodicidade"], "global")

    def test_segundo_termo_nunca_le_valor_por_periodo(self):
        resultado = extrair_apostilamento(_TEXTOS_ITEM_64["apostilamento_1603102"])
        lidos = {
            (resultado.get("valor_anterior") or {}).get("cifra"),
            (resultado.get("valor_novo") or {}).get("cifra"),
        }
        self.assertFalse(lidos & {"26.567,23", "28.227,24", "28.781,24"})

    def test_vale_o_ultimo_novo_valor_global(self):
        texto = (
            "Em razão da correção, o novo valor global do contrato passa a ser "
            "de R$ 10.000,00 (dez mil reais). Em razão do reajuste, o novo "
            "valor global do contrato passa a ser de R$ 10.500,00 (dez mil e "
            "quinhentos reais)."
        )
        resultado = extrair_apostilamento(texto)
        self.assertEqual(resultado["valor_novo"]["cifra"], "10.500,00")
        self.assertEqual(resultado["periodicidade"], "global")

    def test_periodicidade_da_frase_global_nao_contaminada_pelo_indice(self):
        # O trecho é alargado até a frase do índice ("reajustado com base
        # no..."); os valores anuais por período no meio do caminho nunca
        # podem rebaixar a forma global para "anual".
        texto = (
            "O novo valor global do contrato passa a ser de R$ 10.000,00 (dez "
            "mil reais), sendo o valor anual de cada período de R$ 5.000,00 "
            "(cinco mil reais). O valor contratual foi reajustado com base no "
            "índice IPCA."
        )
        resultado = extrair_apostilamento(texto)
        self.assertEqual(resultado["valor_novo"]["cifra"], "10.000,00")
        self.assertEqual(resultado["indice"], "IPCA")
        self.assertEqual(resultado["periodicidade"], "global")

    def test_novo_valor_global_anual_nao_vira_global(self):
        # A periodicidade sai da frase casada: "novo valor global anual"
        # continua anual (nunca promovido a global pela âncora).
        texto = (
            "O novo valor global anual do contrato passa a ser de R$ 12.000,00 "
            "(doze mil reais), em razão do reajuste."
        )
        resultado = extrair_apostilamento(texto)
        self.assertEqual(resultado["valor_novo"]["cifra"], "12.000,00")
        self.assertEqual(resultado["periodicidade"], "anual")


_TEXTOS_ITEM_18 = json.loads(
    (Path(__file__).parent / "fixtures" / "sei" / "textos_item_18.json").read_text(
        encoding="utf-8"
    )
)


class TestValorDocumentoPorItens(unittest.TestCase):
    """Decisão do usuário (20/10/2026, item 18): contrato com valores por
    item e sem um valor global único — o documento marca `por_itens` (um
    valor por rótulo ITEM/LOTE/GRUPO) para `regras.py` não gravar nada e
    gerar a pendência de preenchimento manual."""

    def test_contrato_item_18_marca_os_tres_itens(self):
        resultado = extrair_valor_documento(_TEXTOS_ITEM_18["contrato_1513621"])
        self.assertEqual(
            resultado["por_itens"],
            [
                {"rotulo": "ITEM 01", "cifra": "110.499,60", "confere": True},
                {"rotulo": "ITEM 02", "cifra": "62.000,00", "confere": True},
                {"rotulo": "ITEM 03", "cifra": "18.800,00", "confere": True},
            ],
        )

    def test_contrato_item_18_cifra_continua_a_leitura_preferida(self):
        # A cifra do documento continua a leitura preferida (o total do
        # ITEM 01) — quem decide não gravar é `regras.py`, pela marca.
        resultado = extrair_valor_documento(_TEXTOS_ITEM_18["contrato_1513621"])
        self.assertEqual(resultado["cifra"], "110.499,60")
        self.assertIs(resultado["confere"], True)

    def test_global_sem_rotulo_conferido_vence_os_itens(self):
        texto = (
            "5.1. Para o ITEM 01, o valor total é de R$ 1.000,00 (mil reais). "
            "5.2. Para o ITEM 02, o valor total é de R$ 2.000,00 (dois mil reais). "
            "5.3. O valor global da contratação é de R$ 3.000,00 (três mil reais)."
        )
        resultado = extrair_valor_documento(texto)
        self.assertEqual(resultado["cifra"], "3.000,00")
        self.assertNotIn("por_itens", resultado)

    def test_global_sem_rotulo_que_nao_confere_nao_vence_os_itens(self):
        texto = (
            "5.1. Para o ITEM 01, o valor total é de R$ 1.000,00 (mil reais). "
            "5.2. Para o ITEM 02, o valor total é de R$ 2.000,00 (dois mil reais). "
            "5.3. O valor global da contratação é de R$ 3.000,00 (quatro mil reais)."
        )
        resultado = extrair_valor_documento(texto)
        self.assertEqual(len(resultado["por_itens"]), 2)

    def test_um_item_so_nao_marca(self):
        texto = (
            "5.1. Para o ITEM 01, o valor anual da contratação é de R$ 12.000,00 "
            "(doze mil reais), perfazendo o valor total de R$ 60.000,00 "
            "(sessenta mil reais)."
        )
        resultado = extrair_valor_documento(texto)
        self.assertEqual(resultado["cifra"], "60.000,00")
        self.assertNotIn("por_itens", resultado)

    def test_lotes_tambem_marcam(self):
        texto = (
            "Para o LOTE 1, o valor total é de R$ 1.000,00 (mil reais). "
            "Para o LOTE 2, o valor total é de R$ 2.000,00 (dois mil reais)."
        )
        resultado = extrair_valor_documento(texto)
        self.assertEqual(
            [entrada["rotulo"] for entrada in resultado["por_itens"]], ["LOTE 1", "LOTE 2"]
        )

    def test_referencia_a_secao_do_termo_nao_e_rotulo_de_item(self):
        # "item 5.1 do Termo de Referência" é seção de documento, não item
        # da contratação — nunca vira rótulo.
        texto = (
            "Conforme o item 5.1 do Termo de Referência, o valor total é de "
            "R$ 1.000,00 (mil reais). Conforme o item 7.2, o valor mensal é de "
            "R$ 100,00 (cem reais)."
        )
        resultado = extrair_valor_documento(texto)
        self.assertEqual(resultado["cifra"], "1.000,00")
        self.assertNotIn("por_itens", resultado)

    def test_rotulo_de_clausula_anterior_nao_contamina(self):
        # O rótulo só vale dentro da mesma frase: "ITEM 02" da cláusula
        # anterior não marca o valor global da cláusula seguinte.
        texto = (
            "5.1. Para o ITEM 01, o valor total é de R$ 1.000,00 (mil reais). "
            "5.2. Para o ITEM 02, o valor total é de R$ 2.000,00 (dois mil reais). "
            "5.3. Perfazendo o valor global de R$ 3.000,00 (três mil reais)."
        )
        resultado = extrair_valor_documento(texto)
        self.assertEqual(resultado["cifra"], "3.000,00")
        self.assertNotIn("por_itens", resultado)

    def test_documento_sem_rotulo_mantem_as_chaves_de_sempre(self):
        resultado = extrair_valor_documento(_TEXTOS_ITEM_64["contrato_0347594"])
        self.assertNotIn("por_itens", resultado)


if __name__ == "__main__":
    unittest.main()
