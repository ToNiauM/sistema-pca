"""Testes de `apps.pca.sei.montagem` (Fase 42) — prova de que
`montagem.marcos`/`montagem.montar_documento`/`montagem.montar_processo`
reproduzem byte a byte o que `SEI._marcos`/`SEI.ler_documento`/`coletar_um`
produziam antes da extração desta fase (não regressão exigida). Módulo puro: nenhum teste aqui toca Playwright/ORM."""

import base64

from django.test import SimpleTestCase

from apps.pca.sei import montagem
from apps.pca.sei.extracao import VERSAO_EXTRACAO_DOCUMENTO, hash_texto
from apps.pca.tests.test_sei_pdf import (
    ASSINATURAS_ITEM_58,
    PROCESSO_ITEM_58,
    construir_pdf_sintetico,
)


class TestMarcosRecebimentosGelic(SimpleTestCase):
    """Mesmos casos de `TestMarcosRecebimentosGelic` em
    `test_sei_coletor.py`, chamando `montagem.marcos` em vez de
    `SEI._marcos`."""

    def test_guarda_primeiro_e_todos_os_recebimentos_no_gelic(self):
        linhas = [
            ["01/09/2026 11:30", "GELIC", "Processo recebido na unidade GELIC"],
            ["02/09/2022 10:00", "GELIC", "Processo recebido na unidade GELIC"],
            ["18/09/2025 09:00", "VIPAD", "Processo recebido na unidade VIPAD"],
            ["05/09/2026 08:00", "DELIC", "Processo recebido na unidade DELIC"],
        ]
        marcos = montagem.marcos(linhas)
        self.assertEqual(marcos["recebimento_gelic_delic"]["data_hora"], "02/09/2022 10:00")
        self.assertEqual(
            marcos["recebimentos_gelic_delic"], ["02/09/2022 10:00", "01/09/2026 11:30", "05/09/2026 08:00"]
        )

    def test_sem_passagem_pelo_gelic_fica_lista_vazia(self):
        marcos = montagem.marcos([["01/09/2026 10:00", "GECONT", "Processo recebido na unidade GECONT"]])
        self.assertEqual(marcos["recebimentos_gelic_delic"], [])


class TestMarcosUltimaRemessa(SimpleTestCase):
    """Mesmos casos de `TestMarcosUltimaRemessa` em `test_sei_coletor.py`."""

    def test_caso_real_do_diagnostico_remessa_vence_recebimentos(self):
        linhas = [
            ["04/09/2026 10:00", "GECONT", "Processo recebido na unidade GECONT"],
            ["08/09/2026 09:00", "PROJUR", "Processo recebido na unidade PROJUR"],
            ["21/09/2026 14:51", "GECONT", "Processo remetido pela unidade GELIC"],
            # "recebido" datado DEPOIS da remessa real — precisa ser ignorado.
            ["22/09/2026 08:00", "PROJUR", "Processo recebido na unidade PROJUR"],
        ]
        marcos = montagem.marcos(linhas)
        self.assertEqual(
            marcos["ultima_remessa"],
            {"data_hora": "21/09/2026 14:51", "unidade": "GECONT", "origem": "GELIC"},
        )

    def test_volta_a_unidade_ja_visitada_vence_a_remessa_mais_recente(self):
        linhas = [
            ["01/09/2026 10:00", "GECONT", "Processo remetido pela unidade GELIC"],
            ["15/09/2026 10:00", "GECONT", "Processo remetido pela unidade PROJUR"],
        ]
        marcos = montagem.marcos(linhas)
        self.assertEqual(
            marcos["ultima_remessa"],
            {"data_hora": "15/09/2026 10:00", "unidade": "GECONT", "origem": "PROJUR"},
        )

    def test_sem_nenhuma_remessa_e_none(self):
        linhas = [["10/09/2026 10:00", "GECONT", "Processo recebido na unidade GECONT"]]
        marcos = montagem.marcos(linhas)
        self.assertIsNone(marcos["ultima_remessa"])

    def test_anonimiza_quem_assinou_ou_recebeu_liberacao(self):
        linhas = [
            ["01/09/2026 10:00", "GELIC", "Assinado Documento 123456 (Contrato) por fulano@cfc.org.br"],
        ]
        marcos = montagem.marcos(linhas)
        self.assertEqual(
            marcos["ultimo"]["descricao"], "Assinado Documento 123456 (Contrato) por [omitido]"
        )


class TestMontarDocumentoHtml(SimpleTestCase):
    """Mesmo HTML/asserções de `TestLerDocumentoCorpo.
    test_ramo_html_grava_corpo_versao_e_hash_sem_html_bruto` em
    `test_sei_coletor.py`, chamando `montagem.montar_documento` em vez de
    `SEI.ler_documento`."""

    def test_reproduz_o_dict_do_ramo_html_de_ler_documento(self):
        html = (
            "<html><body>"
            "<p>CLÁUSULA PRIMEIRA – DO OBJETO</p>"
            "<p>1.1 O objeto do presente contrato.</p>"
            "<p>Documento assinado eletronicamente por Fulano de Tal, "
            "Presidente do CFC, em 03/02/2026, às 14:30.</p>"
            "</body></html>"
        )

        resultado = montagem.montar_documento(
            id_documento="9001", protocolo="1204703", rotulo="Contrato 01/2026",
            assinantes_externos_na_arvore=1, html=html,
        )

        self.assertEqual(resultado["conteudo"], "html")
        self.assertEqual(resultado["tipo"], "contrato")
        self.assertEqual(resultado["versao_extracao"], VERSAO_EXTRACAO_DOCUMENTO)
        self.assertIn("CLÁUSULA PRIMEIRA", resultado["texto_corpo"])
        self.assertNotIn("Documento assinado eletronicamente", resultado["texto_corpo"])
        self.assertEqual(resultado["hash_texto"], hash_texto(resultado["texto_corpo"]))
        self.assertNotIn("corpo", resultado)
        self.assertNotIn("src", resultado)

    def test_assinatura_dupla_cfc_e_usuario_externo(self):
        html = (
            "<html><body>"
            "<p>CLÁUSULA PRIMEIRA – DO OBJETO</p>"
            "<p>Documento assinado eletronicamente por Fulano de Tal, "
            "Presidente do CFC, em 03/02/2026, às 14:30.</p>"
            "<p>Documento assinado eletronicamente por Beltrano da Silva, "
            "Usuário Externo, em 04/02/2026, às 09:00.</p>"
            "</body></html>"
        )

        resultado = montagem.montar_documento(
            id_documento="9002", protocolo="1204704", rotulo="Contrato 02/2026",
            assinantes_externos_na_arvore=1, html=html,
        )

        self.assertTrue(resultado["assinado_cfc"])
        self.assertTrue(resultado["assinado_externo"])


class TestMontarDocumentoPdfExterno(SimpleTestCase):
    """Mesma fixture de PDF sintético de `TestLerDocumentoExternoContrato.
    test_contrato_externo_baixa_e_processa_pdf` em `test_sei_coletor.py`."""

    def test_reproduz_o_dict_do_ramo_pdf_externo(self):
        pdf_bytes = construir_pdf_sintetico(assinaturas=ASSINATURAS_ITEM_58)

        resultado = montagem.montar_documento(
            id_documento="9101", protocolo="1374943", rotulo="Contrato 25/2026",
            assinantes_externos_na_arvore=1, pdf_bytes=pdf_bytes,
            numero_processo=PROCESSO_ITEM_58,
        )

        self.assertEqual(resultado["conteudo"], "pdf")
        self.assertTrue(resultado["assinado_cfc"])
        self.assertTrue(resultado["assinado_externo"])
        self.assertEqual(resultado["numero_no_corpo"], "25/2026")
        self.assertEqual(resultado["versao_extracao"], VERSAO_EXTRACAO_DOCUMENTO)
        self.assertEqual(resultado["tipo"], "contrato")


class TestMontarDocumentoSemConteudo(SimpleTestCase):
    """Sem `html` nem `pdf_bytes` — externo nunca baixado OU documento
    restrito nunca lido pela extensão (spec §3): mesmo efeito."""

    def test_sem_html_nem_pdf_vira_externo_nao_baixado(self):
        resultado = montagem.montar_documento(
            id_documento="9201", protocolo="1234567", rotulo="Apostilamento 01/2026",
            assinantes_externos_na_arvore=0,
        )

        self.assertEqual(resultado["conteudo"], "externo_nao_baixado")
        self.assertIsNone(resultado["texto_corpo"])
        self.assertEqual(resultado["versao_extracao"], VERSAO_EXTRACAO_DOCUMENTO)
        self.assertEqual(resultado["tipo"], "apostilamento")


class TestMontarProcesso(SimpleTestCase):
    """`montar_processo` reproduz o formato de `coletor.coletar_um` a partir
    de um material sintético (2-3 documentos, um cancelado, um HTML
    assinado por ambos) — comparado contra o formato de
    `apps/pca/tests/fixtures/sei/coleta_item_3.json`."""

    def test_monta_processo_com_documento_cancelado_e_assinado_por_ambos(self):
        html = (
            "<html><body>"
            "<p>CLÁUSULA PRIMEIRA – DO OBJETO</p>"
            "<p>Documento assinado eletronicamente por Fulano de Tal, "
            "Presidente do CFC, em 03/02/2026, às 14:30.</p>"
            "<p>Documento assinado eletronicamente por Beltrano da Silva, "
            "Usuário Externo, em 04/02/2026, às 09:00.</p>"
            "</body></html>"
        )
        material = {
            "numero": "90796110000007.000036/2025-81",
            "andamentos": [
                {"data_hora": "25/08/2025 09:40", "unidade": "CGTI", "descricao": "Processo público gerado"},
                {
                    "data_hora": "05/09/2025 16:19", "unidade": "DELIC",
                    "descricao": "Processo recebido na unidade DELIC",
                },
            ],
            "documentos": [
                {
                    "id_documento": "1156024", "protocolo": "1094956", "rotulo": "Contrato nº 69/2025",
                    "assinantes_externos_na_arvore": 1, "contratual": True, "cancelado": False,
                    "motivo_cancelamento": None, "conteudo": "html", "html": html,
                },
                {
                    "id_documento": "1156099", "protocolo": "1094999", "rotulo": "Termo Aditivo 1/2026",
                    "assinantes_externos_na_arvore": 0, "contratual": True, "cancelado": True,
                    "motivo_cancelamento": "erro de autuação", "conteudo": "nao_lido", "motivo": None,
                },
                {
                    "id_documento": "1156100", "protocolo": "1094111", "rotulo": "Ofício 1/2026",
                    "assinantes_externos_na_arvore": 0, "contratual": False, "cancelado": False,
                    "motivo_cancelamento": None, "conteudo": "html", "html": "<html></html>",
                },
            ],
        }

        resultado = montagem.montar_processo(material)

        self.assertEqual(resultado["numero"], material["numero"])
        self.assertEqual(resultado["resultado"], "ok")
        self.assertEqual(resultado["total_documentos"], 3)
        self.assertEqual(resultado["andamentos"]["marcos"]["recebimentos"], {"DELIC": "05/09/2025 16:19"})
        self.assertEqual(len(resultado["documentos_contratuais"]), 2)

        contrato = resultado["documentos_contratuais"][0]
        self.assertEqual(contrato["conteudo"], "html")
        self.assertTrue(contrato["assinado_cfc"])
        self.assertTrue(contrato["assinado_externo"])

        cancelado = resultado["documentos_contratuais"][1]
        self.assertEqual(cancelado["conteudo"], "cancelado")
        self.assertEqual(cancelado["motivo_cancelamento"], "erro de autuação")
        self.assertIsNone(cancelado["texto_corpo"])
        self.assertEqual(cancelado["versao_extracao"], VERSAO_EXTRACAO_DOCUMENTO)

    def test_documento_pdf_base64_e_decodificado_antes_de_montar(self):
        pdf_bytes = construir_pdf_sintetico(assinaturas=ASSINATURAS_ITEM_58)
        material = {
            "numero": PROCESSO_ITEM_58,
            "andamentos": [],
            "documentos": [
                {
                    "id_documento": "9101", "protocolo": "1374943", "rotulo": "Contrato 25/2026",
                    "assinantes_externos_na_arvore": 1, "contratual": True, "cancelado": False,
                    "motivo_cancelamento": None, "conteudo": "pdf",
                    "pdf_base64": base64.b64encode(pdf_bytes).decode("ascii"),
                },
            ],
        }

        resultado = montagem.montar_processo(material)

        self.assertEqual(len(resultado["documentos_contratuais"]), 1)
        doc = resultado["documentos_contratuais"][0]
        self.assertEqual(doc["conteudo"], "pdf")
        self.assertTrue(doc["assinado_cfc"])
        self.assertTrue(doc["assinado_externo"])

    def test_documento_restrito_nunca_lido_vira_externo_nao_baixado(self):
        material = {
            "numero": "90796110000007.000036/2025-81",
            "andamentos": [],
            "documentos": [
                {
                    "id_documento": "1156200", "protocolo": "1099999", "rotulo": "Contrato 70/2025",
                    "assinantes_externos_na_arvore": 0, "contratual": True, "cancelado": False,
                    "motivo_cancelamento": None, "conteudo": "nao_lido", "motivo": "restrito",
                },
            ],
        }

        resultado = montagem.montar_processo(material)

        doc = resultado["documentos_contratuais"][0]
        self.assertEqual(doc["conteudo"], "externo_nao_baixado")
        self.assertIsNone(doc["texto_corpo"])


class TestMontarProcessoContratualPeloRotulo(SimpleTestCase):
    """Revisão do contrato v1 pela sessão sei-pro (pontos 1, 2 e 4): o PCA
    decide `contratual` pelo `RE_CONTRATUAL` sobre o rótulo — mesma regra de
    `SEI.documentos` —, ignorando o campo enviado; documento não contratual
    nunca tem o conteúdo considerado; `externo_nao_baixado` é aceito."""

    def _doc(self, rotulo, contratual, conteudo, motivo=None):
        return {
            "id_documento": "1", "protocolo": "1000001", "rotulo": rotulo,
            "assinantes_externos_na_arvore": 0, "contratual": contratual, "cancelado": False,
            "motivo_cancelamento": None, "conteudo": conteudo, "motivo": motivo,
        }

    def test_campo_contratual_do_cliente_e_ignorado(self):
        material = {"numero": "1", "andamentos": [], "documentos": [
            self._doc("Despacho 12", True, "nao_lido", "nao_contratual"),
            self._doc("Contrato 70/2025", False, "nao_lido", "restrito"),
        ]}
        resultado = montagem.montar_processo(material)
        self.assertEqual([d["rotulo"] for d in resultado["documentos_contratuais"]], ["Contrato 70/2025"])
        self.assertEqual(resultado["total_documentos"], 2)

    def test_nao_contratual_com_conteudo_null_e_aceito(self):
        material = {"numero": "1", "andamentos": [], "documentos": [self._doc("Despacho 12", False, None)]}
        self.assertEqual(montagem.montar_processo(material)["documentos_contratuais"], [])

    def test_externo_nao_baixado_mantem_paridade_com_o_robo(self):
        material = {"numero": "1", "andamentos": [], "documentos": [
            self._doc("Apostilamento 3", True, "externo_nao_baixado"),
        ]}
        doc = montagem.montar_processo(material)["documentos_contratuais"][0]
        self.assertEqual(doc["conteudo"], "externo_nao_baixado")


class TestMontarProcessoResumoDoHistorico(SimpleTestCase):
    """Pedido da sessão sei-pro (10/10/2026): a coleta da extensão traz
    `registros`/`primeiro` como o `historico_resumo` do robô — senão o
    atalho de pulo (`ultima_coleta` do GET processo) nunca funciona para
    ela. `primeiro` = andamento MAIS RECENTE (o SEI lista assim), com a
    descrição anonimizada; empate de data fica com o primeiro da lista."""

    def test_registros_e_primeiro_mais_recente_anonimizado(self):
        material = {"numero": "1", "documentos": [], "andamentos": [
            {"data_hora": "01/09/2026 10:00", "unidade": "GELIC", "descricao": "Processo recebido na unidade GELIC"},
            {"data_hora": "05/09/2026 08:00", "unidade": "DELIC",
             "descricao": "Assinado Documento 1210804 (Contrato 08/2026) por fulano@empresa.com.br"},
            {"data_hora": "05/09/2026 08:00", "unidade": "GELIC", "descricao": "Processo remetido pela unidade DELIC"},
        ]}
        resultado = montagem.montar_processo(material)
        self.assertEqual(resultado["registros"], 3)
        self.assertEqual(resultado["primeiro"]["data_hora"], "05/09/2026 08:00")
        self.assertEqual(resultado["primeiro"]["unidade"], "DELIC")
        self.assertEqual(
            resultado["primeiro"]["descricao"],
            montagem._anon("Assinado Documento 1210804 (Contrato 08/2026) por fulano@empresa.com.br"),
        )
        self.assertNotIn("fulano@", resultado["primeiro"]["descricao"])

    def test_sem_andamentos(self):
        resultado = montagem.montar_processo({"numero": "1", "documentos": [], "andamentos": []})
        self.assertEqual(resultado["registros"], 0)
        self.assertIsNone(resultado["primeiro"])
