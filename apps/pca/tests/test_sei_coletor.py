"""Testes de `apps.pca.sei.coletor` — cache incremental e pulo (Fase 34). Nenhum teste deste arquivo
toca Playwright/o SEI real: todo `sei` injetado em `coletar_um`/`coletar` é
um objeto falso simples (`SEIFalso`), com métodos `Mock` que registram
chamadas — a mesma técnica de injeção já usada em `test_sei_comandos.py`,
sem `unittest.mock.patch` porque `coletor.py` recebe o objeto `sei` como
argumento, nunca importa Playwright fora de `coletar()`."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase
from django.utils import timezone as django_timezone

from apps.pca.sei.coletor import (
    SEI,
    _SELETOR_FECHAR_NOVIDADES,
    _SELETOR_OVERLAY_NOVIDADES,
    _aditivo_externo_pendente,
    _documento_anterior,
    _documento_definitivo,
    _documentos_desatualizados,
    _linha_progresso_final,
    _linha_progresso_item,
    _linha_progresso_resolver_final,
    _linha_progresso_resolver_item,
    _marcos_desatualizados,
    coletar,
    coletar_um,
    resolver_links,
)
from apps.pca.sei.execucoes import interpretar_linha_progresso
from apps.pca.sei.extracao import VERSAO_EXTRACAO_DOCUMENTO, hash_texto
from apps.pca.tests.test_sei_pdf import (
    ASSINATURAS_ADITIVO_ITEM_89,
    ASSINATURAS_ITEM_58,
    PROCESSO_ITEM_58,
    PROCESSO_ITEM_89,
    TEXTO_ADITIVO_ITEM_89,
    construir_pdf_sintetico,
)

_RESUMO_PADRAO = {
    "registros": 10,
    "primeiro": {
        "data_hora": "18/09/2026 10:00",
        "unidade": "GELIC",
        "descricao": "Processo recebido na unidade GELIC",
    },
}


class SEIFalso:
    """`sei` falso injetável — os 6 métodos que `coletar_um` chama, cada um
    um `Mock` para permitir `assert_not_called()`/`assert_called()`."""

    def __init__(
        self,
        *,
        id_procedimento="1043956",
        titulo_confere=True,
        resumo=None,
        docs=None,
        andamentos=None,
        documentos_lidos=None,
    ):
        self.abrir_processo = Mock(
            return_value={"titulo_confere": titulo_confere, "id_procedimento": id_procedimento}
        )
        self.url_historico = Mock(return_value="https://sei.cfc.org.br/sei/historico")
        self.historico_resumo = Mock(return_value=resumo if resumo is not None else dict(_RESUMO_PADRAO))
        self.abrir_todas_pastas = Mock(return_value={"botao": True})
        self.documentos = Mock(return_value=docs or [])
        self.historico = Mock(return_value=andamentos or {"marcos": {"primeiro": None, "ultimo": None}})
        documentos_lidos = documentos_lidos or {}
        # `coletar_um` passa `numero_processo=numero` nos
        # dois call sites — a assinatura aceita (e ignora) o kwarg, mesmo
        # padrão de tolerância a argumento novo já usado pelo resto do
        # arquivo.
        self.ler_documento = Mock(
            side_effect=lambda d, numero_processo=None: dict(documentos_lidos[d["id_documento"]])
        )


def _doc_arvore(id_documento, rotulo="Contrato 01/2026"):
    return {
        "id_documento": id_documento,
        "protocolo": "1204703",
        "rotulo": rotulo,
        "cancelado": False,
        "motivo_cancelamento": None,
        "assinado_na_arvore": True,
        "assinantes_externos_na_arvore": 1,
        "contratual": True,
    }


def _doc_definitivo(id_documento="9001"):
    return {
        "id_documento": id_documento,
        "protocolo": "1204703",
        "rotulo": "Contrato 01/2026",
        "assinantes_externos_na_arvore": 1,
        "tipo": "contrato",
        "conteudo": "html",
        "assinado_cfc": True,
        "assinado_externo": True,
        "valor": {"cifra": "18.001,20", "extenso": "dezoito mil...", "confere": True},
    }


class TestColetarUmPulado(SimpleTestCase):
    def test_registros_e_primeiro_iguais_pula_sem_abrir_pastas_nem_documentos(self):
        anterior = {
            "registros": _RESUMO_PADRAO["registros"],
            "primeiro": _RESUMO_PADRAO["primeiro"],
            "coletado_em": "2026-09-17T10:00:00-03:00",
            "id_procedimento": "1043956",
            "pastas": {"botao": True},
            "total_documentos": 1,
            "andamentos": {
                "marcos": {"ultimo": {"data_hora": "17/09/2026 09:00"}, "ultima_remessa": None,
                           "recebimentos_gelic_delic": []}
            },
            "documentos_contratuais": [_doc_definitivo()],
            "resultado": "ok",
        }
        cache = {"processos": {"123": anterior}, "documentos": {}}
        sei = SEIFalso()

        r = coletar_um(sei, "123", cache=cache, forcar=False)

        sei.abrir_todas_pastas.assert_not_called()
        sei.documentos.assert_not_called()
        sei.historico.assert_not_called()
        sei.ler_documento.assert_not_called()
        self.assertTrue(r["pulado"])
        self.assertEqual(r["resultado"], "ok")
        self.assertEqual(r["numero"], "123")
        self.assertEqual(r["documentos_contratuais"], anterior["documentos_contratuais"])
        self.assertEqual(r["andamentos"], anterior["andamentos"])
        self.assertEqual(r["total_documentos"], anterior["total_documentos"])
        self.assertEqual(r["pastas"], anterior["pastas"])
        # r["abertura"] é o desta chamada, não o do cache (cache nem guarda "abertura")
        self.assertEqual(r["abertura"]["id_procedimento"], "1043956")


class TestColetarUmMudouOuForcar(SimpleTestCase):
    def test_sem_cache_anterior_coleta_completa(self):
        doc = _doc_definitivo("9001")
        sei = SEIFalso(docs=[_doc_arvore("9001")], documentos_lidos={"9001": doc})
        cache = {"processos": {}, "documentos": {}}

        r = coletar_um(sei, "123", cache=cache, forcar=False)

        sei.abrir_todas_pastas.assert_called_once()
        sei.documentos.assert_called_once()
        sei.historico.assert_called_once()
        sei.ler_documento.assert_called_once()
        self.assertNotIn("pulado", r)
        self.assertEqual(r["resultado"], "ok")
        self.assertEqual(cache["processos"]["123"]["registros"], _RESUMO_PADRAO["registros"])
        self.assertEqual(cache["processos"]["123"]["primeiro"], _RESUMO_PADRAO["primeiro"])

    def test_registros_diferentes_coleta_completa_e_atualiza_cache(self):
        anterior = {
            "registros": 5,  # difere do resumo (10) devolvido por SEIFalso
            "primeiro": _RESUMO_PADRAO["primeiro"],
            "documentos_contratuais": [],
            "andamentos": {},
            "pastas": {},
            "total_documentos": 0,
            "resultado": "ok",
        }
        cache = {"processos": {"123": anterior}, "documentos": {}}
        sei = SEIFalso(docs=[], documentos_lidos={})

        r = coletar_um(sei, "123", cache=cache, forcar=False)

        sei.abrir_todas_pastas.assert_called_once()
        sei.historico.assert_called_once()
        self.assertNotIn("pulado", r)
        self.assertEqual(cache["processos"]["123"]["registros"], _RESUMO_PADRAO["registros"])

    def test_primeiro_diferente_coleta_completa(self):
        anterior = {
            "registros": _RESUMO_PADRAO["registros"],
            "primeiro": {"data_hora": "01/01/2026 08:00", "unidade": "X", "descricao": "y"},
            "documentos_contratuais": [],
            "andamentos": {},
            "pastas": {},
            "total_documentos": 0,
            "resultado": "ok",
        }
        cache = {"processos": {"123": anterior}, "documentos": {}}
        sei = SEIFalso(docs=[], documentos_lidos={})

        r = coletar_um(sei, "123", cache=cache, forcar=False)

        sei.abrir_todas_pastas.assert_called_once()
        self.assertNotIn("pulado", r)

    def test_forcar_true_ignora_atalho_mesmo_com_cache_identico(self):
        anterior = {
            "registros": _RESUMO_PADRAO["registros"],
            "primeiro": _RESUMO_PADRAO["primeiro"],
            "documentos_contratuais": [],
            "andamentos": {},
            "pastas": {},
            "total_documentos": 0,
            "resultado": "ok",
        }
        cache = {"processos": {"123": anterior}, "documentos": {}}
        sei = SEIFalso(docs=[], documentos_lidos={})

        r = coletar_um(sei, "123", cache=cache, forcar=True)

        sei.abrir_todas_pastas.assert_called_once()
        sei.documentos.assert_called_once()
        sei.historico.assert_called_once()
        self.assertNotIn("pulado", r)
        self.assertEqual(r["resultado"], "ok")


class _SEIProibido:
    """`sei` falso que lança `AssertionError` em QUALQUER chamada — usado
    para provar que o pulo por coleta recente da extensão acontece ANTES de qualquer interação com o SEI/navegador,
    diferente do atalho de pulo antigo (que já abriu o processo antes de
    decidir pular)."""

    def _proibido(self, *args, **kwargs):
        raise AssertionError("coletar_um chamou o SEI apesar do pulo por extensão recente")

    def __getattr__(self, nome):
        return self._proibido


def _entrada_extensao(numero, horas_atras, **coleta_extra):
    coleta = {
        "total_documentos": 1,
        "andamentos": {
            "marcos": {"ultimo": None, "ultima_remessa": None, "recebimentos_gelic_delic": []}
        },
        "documentos_contratuais": [_doc_definitivo()],
        "resultado": "ok",
    }
    coleta.update(coleta_extra)
    recebido_em = (django_timezone.now() - timedelta(hours=horas_atras)).isoformat()
    return {"processos": {numero: {"coleta": coleta, "recebido_em": recebido_em, "usuario_id": 7}}}


class TestColetarUmPulaPorExtensaoRecente(SimpleTestCase):
    """Pulo ANTERIOR ao atalho existente: nem abre o
    processo no navegador quando a extensão já informou aquele número
    recentemente."""

    def test_entrada_de_1_hora_pula_sem_chamar_nenhum_metodo_do_sei(self):
        extensao = _entrada_extensao("123", 1)
        sei = _SEIProibido()

        r = coletar_um(sei, "123", extensao=extensao, pular_se_extensao_h=24)

        self.assertTrue(r["pulado"])
        self.assertEqual(r["motivo_pulo"], "extensao_recente")
        self.assertEqual(r["numero"], "123")
        self.assertEqual(r["resultado"], "ok")
        self.assertEqual(r["duracao_s"], 0.0)
        coleta = extensao["processos"]["123"]["coleta"]
        self.assertEqual(r["total_documentos"], coleta["total_documentos"])
        self.assertEqual(r["andamentos"], coleta["andamentos"])
        self.assertEqual(r["documentos_contratuais"], coleta["documentos_contratuais"])

    def test_entrada_de_30_horas_nao_pula_chega_a_chamar_abrir_processo(self):
        extensao = _entrada_extensao("123", 30)
        sei = SEIFalso(docs=[], documentos_lidos={})

        r = coletar_um(sei, "123", extensao=extensao, pular_se_extensao_h=24)

        sei.abrir_processo.assert_called_once()
        self.assertNotIn("motivo_pulo", r)

    def test_forcar_true_nao_pula_mesmo_com_entrada_recentissima(self):
        extensao = _entrada_extensao("123", 1 / 60)
        sei = SEIFalso(docs=[], documentos_lidos={})

        r = coletar_um(sei, "123", extensao=extensao, pular_se_extensao_h=24, forcar=True)

        sei.abrir_processo.assert_called_once()
        self.assertNotIn("motivo_pulo", r)

    def test_pular_se_extensao_h_zero_nao_pula_mesmo_com_entrada_recentissima(self):
        extensao = _entrada_extensao("123", 1 / 60)
        sei = SEIFalso(docs=[], documentos_lidos={})

        r = coletar_um(sei, "123", extensao=extensao, pular_se_extensao_h=0)

        sei.abrir_processo.assert_called_once()
        self.assertNotIn("motivo_pulo", r)

    def test_sem_entrada_para_o_numero_nao_pula(self):
        extensao = _entrada_extensao("123", 1)  # entrada é de "123", não "999"
        sei = SEIFalso(docs=[], documentos_lidos={})

        r = coletar_um(sei, "999", extensao=extensao, pular_se_extensao_h=24)

        sei.abrir_processo.assert_called_once()
        self.assertNotIn("motivo_pulo", r)


class TestLinhaProgressoPuladoPorExtensao(SimpleTestCase):
    def test_pulado_por_extensao_produz_texto_novo(self):
        r = {"pulado": True, "motivo_pulo": "extensao_recente"}
        self.assertEqual(
            _linha_progresso_item(42, 1, 10, r),
            "item 42 (1/10): pulado (coleta recente da extensão)",
        )

    def test_pulado_pelo_atalho_antigo_continua_com_texto_antigo(self):
        r = {"pulado": True}
        self.assertEqual(
            _linha_progresso_item(42, 1, 10, r),
            "item 42 (1/10): pulado (sem mudança no histórico)",
        )


class TestInterpretarLinhaProgressoReconheceDuasVariantesDePulo(SimpleTestCase):
    def test_pulado_sem_mudanca_no_historico(self):
        resultado = interpretar_linha_progresso(
            "item 42 (1/10): pulado (sem mudança no histórico)"
        )
        self.assertEqual(resultado["resultado"], "pulado")

    def test_pulado_coleta_recente_da_extensao(self):
        resultado = interpretar_linha_progresso(
            "item 42 (1/10): pulado (coleta recente da extensão)"
        )
        self.assertEqual(resultado["resultado"], "pulado")

    def test_coletado_continua_coletado(self):
        resultado = interpretar_linha_progresso("item 42 (1/10): coletado em 1.5 s")
        self.assertEqual(resultado["resultado"], "coletado")

    def test_erro_continua_erro(self):
        resultado = interpretar_linha_progresso("item 42 (1/10): erro — Boom")
        self.assertEqual(resultado["resultado"], "erro")


class TestMarcosRecebimentosGelic(SimpleTestCase):
    """29/09/2026 — processo reaproveitado a cada renovação (item 112/2026): além do PRIMEIRO
    recebimento no Gelic/Delic, os marcos guardam TODOS, em ordem cronológica."""

    def test_guarda_primeiro_e_todos_os_recebimentos_no_gelic(self):
        linhas = [
            ["01/09/2026 11:30", "GELIC", "Processo recebido na unidade GELIC"],
            ["02/09/2022 10:00", "GELIC", "Processo recebido na unidade GELIC"],
            ["18/09/2025 09:00", "VIPAD", "Processo recebido na unidade VIPAD"],
            ["05/09/2026 08:00", "DELIC", "Processo recebido na unidade DELIC"],
        ]
        marcos = SEI._marcos(linhas)
        self.assertEqual(marcos["recebimento_gelic_delic"]["data_hora"], "02/09/2022 10:00")
        self.assertEqual(
            marcos["recebimentos_gelic_delic"], ["02/09/2022 10:00", "01/09/2026 11:30", "05/09/2026 08:00"]
        )

    def test_sem_passagem_pelo_gelic_fica_lista_vazia(self):
        marcos = SEI._marcos([["01/09/2026 10:00", "GECONT", "Processo recebido na unidade GECONT"]])
        self.assertEqual(marcos["recebimentos_gelic_delic"], [])

    def test_cache_sem_o_marco_novo_esta_desatualizado(self):
        self.assertTrue(_marcos_desatualizados({"andamentos": {"marcos": {"ultima_remessa": None}}}))
        self.assertFalse(
            _marcos_desatualizados(
                {"andamentos": {"marcos": {"ultima_remessa": None, "recebimentos_gelic_delic": []}}}
            )
        )


class TestMarcosUltimaRemessa(SimpleTestCase):
    """`SEI._marcos()` é função pura, sem Playwright/DB. Linhas no
    formato `[data_hora, unidade, descricao]`."""

    def test_caso_real_do_diagnostico_remessa_vence_recebimentos(self):
        linhas = [
            ["04/09/2026 10:00", "GECONT", "Processo recebido na unidade GECONT"],
            ["08/09/2026 09:00", "PROJUR", "Processo recebido na unidade PROJUR"],
            ["21/09/2026 14:51", "GECONT", "Processo remetido pela unidade GELIC"],
            # "recebido" datado DEPOIS da remessa real — precisa ser ignorado.
            ["22/09/2026 08:00", "PROJUR", "Processo recebido na unidade PROJUR"],
        ]
        marcos = SEI._marcos(linhas)
        self.assertEqual(
            marcos["ultima_remessa"],
            {"data_hora": "21/09/2026 14:51", "unidade": "GECONT", "origem": "GELIC"},
        )

    def test_volta_a_unidade_ja_visitada_vence_a_remessa_mais_recente(self):
        linhas = [
            ["01/09/2026 10:00", "GECONT", "Processo remetido pela unidade GELIC"],
            ["15/09/2026 10:00", "GECONT", "Processo remetido pela unidade PROJUR"],
        ]
        marcos = SEI._marcos(linhas)
        self.assertEqual(
            marcos["ultima_remessa"],
            {"data_hora": "15/09/2026 10:00", "unidade": "GECONT", "origem": "PROJUR"},
        )

    def test_remessa_simultanea_desempata_pela_unidade_alfabeticamente_maior(self):
        linhas = [
            ["10/09/2026 10:00", "AAAA", "Processo remetido pela unidade X"],
            ["10/09/2026 10:00", "ZZZZ", "Processo remetido pela unidade Y"],
        ]
        marcos = SEI._marcos(linhas)
        self.assertEqual(marcos["ultima_remessa"]["unidade"], "ZZZZ")

    def test_sem_nenhuma_remessa_e_none(self):
        linhas = [["10/09/2026 10:00", "GECONT", "Processo recebido na unidade GECONT"]]
        marcos = SEI._marcos(linhas)
        self.assertIsNone(marcos["ultima_remessa"])

    def test_linhas_posteriores_de_outros_tipos_nao_mudam_ultima_remessa(self):
        linhas = [
            ["05/09/2026 10:00", "GECONT", "Processo remetido pela unidade GELIC"],
            ["06/09/2026 10:00", "GECONT", "Cancelada disponibilização do bloco"],
            ["07/09/2026 10:00", "GECONT", "Conclusão do processo na unidade"],
            ["08/09/2026 10:00", "GECONT", "Documento 123456 (Ofício) gerado"],
        ]
        marcos = SEI._marcos(linhas)
        self.assertEqual(
            marcos["ultima_remessa"],
            {"data_hora": "05/09/2026 10:00", "unidade": "GECONT", "origem": "GELIC"},
        )


class TestDocumentoDoCache(SimpleTestCase):
    def test_documento_ja_no_cache_nao_e_relido(self):
        doc_cache = _doc_definitivo("9001")
        cache = {"processos": {}, "documentos": {"9001": doc_cache}}
        sei = SEIFalso(docs=[_doc_arvore("9001")], documentos_lidos={})  # ler_documento explodiria se chamado

        r = coletar_um(sei, "123", cache=cache, forcar=False)

        sei.ler_documento.assert_not_called()
        self.assertEqual(len(r["documentos_contratuais"]), 1)
        devolvido = r["documentos_contratuais"][0]
        self.assertTrue(devolvido["do_cache"])
        for chave, valor in doc_cache.items():
            self.assertEqual(devolvido[chave], valor)


class TestDocumentoDefinitivoNaoEntraNoCache(SimpleTestCase):
    def _coletar_com_documento(self, doc):
        cache = {"processos": {}, "documentos": {}}
        sei = SEIFalso(docs=[_doc_arvore(doc["id_documento"])], documentos_lidos={doc["id_documento"]: doc})
        coletar_um(sei, "123", cache=cache, forcar=False)
        return cache

    def test_unilateral_nao_entra(self):
        doc = _doc_definitivo("9001")
        doc["assinado_externo"] = False  # só o CFC assinou
        cache = self._coletar_com_documento(doc)
        self.assertNotIn("9001", cache["documentos"])

    def test_externo_nao_baixado_nao_entra(self):
        doc = {
            "id_documento": "9002",
            "protocolo": "1204703",
            "rotulo": "Contrato 01/2026",
            "tipo": "contrato",
            "conteudo": "externo_nao_baixado",
        }
        cache = self._coletar_com_documento(doc)
        self.assertNotIn("9002", cache["documentos"])

    def test_cancelado_nao_entra(self):
        doc = {
            "id_documento": "9003",
            "protocolo": "1204703",
            "rotulo": "Contrato 01/2026",
            "tipo": "contrato",
            "conteudo": "cancelado",
            "motivo_cancelamento": "erro de autuação",
        }
        cache = self._coletar_com_documento(doc)
        self.assertNotIn("9003", cache["documentos"])

    def test_valor_nao_confere_nao_entra(self):
        doc = _doc_definitivo("9004")
        doc["valor"] = {"cifra": "18.001,20", "extenso": "outra coisa", "confere": False}
        cache = self._coletar_com_documento(doc)
        self.assertNotIn("9004", cache["documentos"])

    def test_apostilamento_so_exige_assinado_cfc(self):
        doc = {
            "id_documento": "9005",
            "protocolo": "1204703",
            "rotulo": "Apostilamento 01/2026",
            "tipo": "apostilamento",
            "conteudo": "html",
            "assinado_cfc": True,
            "assinado_externo": False,
            "valor": None,
        }
        cache = self._coletar_com_documento(doc)
        self.assertIn("9005", cache["documentos"])
        self.assertEqual(cache["documentos"]["9005"]["tipo"], "apostilamento")

    def test_apostilamento_sobrevive_ao_cache_de_documento_definitivo(self):
        # Documento["apostilamento"] (dict anexado por
        # `SEI.ler_documento` quando tipo == "apostilamento") tem de
        # sobreviver ao pipeline de cache exatamente como os outros campos
        # anexados (valor/contratado/procedencia/vigencia/prorrogacao) —
        # `_documento_definitivo`/`coletar_um` já copiam o dict inteiro
        # (`entrada = {k: v for k, v in doc.items() if k != "do_cache"}`,
        # sem lista de chaves fixa), então a chave nova entra no cache sem
        # nenhuma mudança adicional no pipeline de cache; a mudança real é
        # o wiring em `SEI.ler_documento` (verificado por grep, ver
        # Não testável aqui sem Playwright).
        doc = {
            "id_documento": "9007",
            "protocolo": "1204703",
            "rotulo": "Apostilamento 02/2026",
            "tipo": "apostilamento",
            "conteudo": "html",
            "assinado_cfc": True,
            "assinado_externo": False,
            "valor": None,
            "apostilamento": {
                "natureza": "reajuste",
                "valor_anterior": None,
                "valor_novo": {
                    "cifra": "45.000,00",
                    "extenso": "quarenta e cinco mil reais",
                    "confere": True,
                },
                "percentual": None,
                "indice": None,
                "periodicidade": "global",
                "data_base": None,
                "trecho": "Valor total da contratação: R$ 45.000,00 (...)",
            },
        }
        cache = self._coletar_com_documento(doc)
        self.assertIn("9007", cache["documentos"])
        self.assertEqual(cache["documentos"]["9007"]["apostilamento"], doc["apostilamento"])

    def test_documento_nao_apostilamento_nao_carrega_chave_apostilamento(self):
        # Um documento com tipo != "apostilamento" (ex. contrato)
        # nunca carrega a chave "apostilamento" com um dict — continua
        # ausente/None, nunca herdando o resultado de extrair_apostilamento
        # por engano.
        doc = _doc_definitivo("9008")
        self.assertNotIn("apostilamento", doc)
        cache = self._coletar_com_documento(doc)
        self.assertIn("9008", cache["documentos"])
        self.assertIsNone(cache["documentos"]["9008"].get("apostilamento"))

    def test_tipo_nao_reconhecido_nao_entra(self):
        doc = {
            "id_documento": "9006",
            "protocolo": "1204703",
            "rotulo": "Ofício 01/2026",
            "tipo": "outro",
            "conteudo": "html",
            "assinado_cfc": True,
            "assinado_externo": True,
            "valor": None,
        }
        cache = self._coletar_com_documento(doc)
        self.assertNotIn("9006", cache["documentos"])


class TestDocumentoDefinitivoFuncaoPura(SimpleTestCase):
    def test_contrato_com_assinatura_dupla_e_valor_confere_e_definitivo(self):
        self.assertTrue(_documento_definitivo(_doc_definitivo("1")))

    def test_contrato_sem_valor_e_definitivo(self):
        doc = _doc_definitivo("1")
        doc["valor"] = None
        self.assertTrue(_documento_definitivo(doc))

    def test_conteudo_nao_html_nunca_e_definitivo(self):
        self.assertFalse(_documento_definitivo({"conteudo": "nao_html:application/pdf", "tipo": "contrato"}))


class TestLinhaProgresso(SimpleTestCase):
    def test_coletado(self):
        r = {"resultado": "ok", "duracao_s": 12.34}
        self.assertEqual(
            _linha_progresso_item(6, 2, 10, r),
            "item 6 (2/10): coletado em 12.34 s",
        )

    def test_pulado(self):
        r = {"resultado": "ok", "pulado": True}
        self.assertEqual(
            _linha_progresso_item(6, 2, 10, r),
            "item 6 (2/10): pulado (sem mudança no histórico)",
        )

    def test_erro(self):
        r = {"resultado": "erro", "erro": "TimeoutError: tempo esgotado"}
        self.assertEqual(
            _linha_progresso_item(6, 2, 10, r),
            "item 6 (2/10): erro — TimeoutError: tempo esgotado",
        )

    def test_final(self):
        self.assertEqual(
            _linha_progresso_final(8, 100, 2, 312.5),
            "coleta concluída: 8 coletados, 100 pulados, 2 erros em 312.5 s",
        )


class TestColetarProgresso(SimpleTestCase):
    """`coletar()` chama `progresso` uma linha por processo mais o resumo
    final — testado aqui direto sobre `coletar_um`/laço, sem Playwright:
    substitui `sync_playwright` monkeypatchando o próprio módulo não é
    necessário porque `coletar()` só entra em `sync_playwright` depois do
    import preguiçoso; testamos o comportamento de progresso indiretamente
    via `_linha_progresso_item`/`_linha_progresso_final` acima (funções
    puras) — cobertura de integração fica a cargo de `test_sei_comandos.py`,
que mocka `coletor.coletar` por completo."""

    def test_coletar_e_importavel_com_a_nova_assinatura(self):
        import inspect

        parametros = list(inspect.signature(coletar).parameters)
        self.assertEqual(
            parametros,
            [
                "alvos",
                "cache",
                "forcar",
                "progresso",
                "reprocessar_documentos",
                "extensao",
                "pular_se_extensao_h",
            ],
        )

    def test_resolver_links_e_importavel_com_a_nova_assinatura(self):
        import inspect

        parametros = list(inspect.signature(resolver_links).parameters)
        self.assertEqual(parametros, ["numeros", "progresso"])


class TestLinhaProgressoResolver(SimpleTestCase):
    """`_linha_progresso_resolver_item`/`_linha_progresso_resolver_final`,
espelhando `TestLinhaProgresso` acima."""

    def test_resolvido(self):
        r = {"resultado": "ok"}
        self.assertEqual(
            _linha_progresso_resolver_item("111", 2, 10, r),
            "SEI 111 (2/10): resolvido",
        )

    def test_nao_encontrado(self):
        r = {"resultado": "nao_encontrado"}
        self.assertEqual(
            _linha_progresso_resolver_item("111", 2, 10, r),
            "SEI 111 (2/10): não encontrado",
        )

    def test_erro(self):
        r = {"resultado": "erro", "erro": "TimeoutError: tempo esgotado"}
        self.assertEqual(
            _linha_progresso_resolver_item("111", 2, 10, r),
            "SEI 111 (2/10): erro — TimeoutError: tempo esgotado",
        )

    def test_final(self):
        self.assertEqual(
            _linha_progresso_resolver_final(8, 1, 2),
            "resolução concluída: 8 resolvidos, 1 não encontrados, 2 erros",
        )


# ---------------------------------------------------------------------------
# Fase 39 (A10) — `--reprocessar-documentos`: cache antigo
# (sem `texto_corpo`/`versao_extracao`) migrado nas duas representações, de
# forma idempotente e segura em falha. Nenhum teste toca Playwright/o SEI
# real — `sei` é sempre `SEIFalso` (mesma técnica do resto do arquivo).
# ---------------------------------------------------------------------------


class TestDocumentosDesatualizadosFuncaoPura(SimpleTestCase):
    def test_sem_anterior_nao_desatualizado(self):
        self.assertFalse(_documentos_desatualizados(None))
        self.assertFalse(_documentos_desatualizados({}))

    def test_documento_sem_versao_extracao_e_desatualizado(self):
        anterior = {"documentos_contratuais": [{"id_documento": "1"}]}
        self.assertTrue(_documentos_desatualizados(anterior))

    def test_todos_na_versao_atual_nao_e_desatualizado(self):
        anterior = {
            "documentos_contratuais": [
                {"id_documento": "1", "versao_extracao": VERSAO_EXTRACAO_DOCUMENTO}
            ]
        }
        self.assertFalse(_documentos_desatualizados(anterior))


class TestMarcosDesatualizadosFuncaoPura(SimpleTestCase):
    """Guarda de cache pré-quick (sem a chave `ultima_remessa`)."""

    def test_sem_anterior_nao_desatualizado(self):
        self.assertFalse(_marcos_desatualizados(None))
        self.assertFalse(_marcos_desatualizados({}))

    def test_sem_andamentos_ou_marcos_nao_desatualizado(self):
        self.assertFalse(_marcos_desatualizados({"andamentos": {}}))
        self.assertFalse(_marcos_desatualizados({}))

    def test_marcos_sem_ultima_remessa_e_desatualizado(self):
        anterior = {"andamentos": {"marcos": {"primeiro": None, "ultimo": None}}}
        self.assertTrue(_marcos_desatualizados(anterior))

    def test_marcos_com_ultima_remessa_nao_e_desatualizado(self):
        anterior = {"andamentos": {"marcos": {"ultima_remessa": None, "recebimentos_gelic_delic": []}}}
        self.assertFalse(_marcos_desatualizados(anterior))


class TestColetarUmMarcosDesatualizadosForcaRecoleta(SimpleTestCase):
    """Cache anterior a esta quick (marcos sem `ultima_remessa`) NUNCA
    é reaproveitado pelo atalho de pulo, mesmo com `registros`/`primeiro` idênticos."""

    def test_cache_sem_ultima_remessa_forca_recoleta_completa(self):
        anterior = {
            "registros": _RESUMO_PADRAO["registros"],
            "primeiro": _RESUMO_PADRAO["primeiro"],
            "coletado_em": "2026-09-17T10:00:00-03:00",
            "id_procedimento": "1043956",
            "pastas": {"botao": True},
            "total_documentos": 1,
            # cache anterior a esta quick: marcos sem a chave "ultima_remessa".
            "andamentos": {"marcos": {"ultimo": {"data_hora": "17/09/2026 09:00"}}},
            "documentos_contratuais": [_doc_definitivo()],
            "resultado": "ok",
        }
        cache = {"processos": {"123": anterior}, "documentos": {}}
        sei = SEIFalso()

        r = coletar_um(sei, "123", cache=cache, forcar=False)

        sei.historico.assert_called_once()
        sei.abrir_todas_pastas.assert_called_once()
        self.assertNotIn("pulado", r)
        self.assertEqual(cache["processos"]["123"]["andamentos"], sei.historico.return_value)


class TestAditivoExternoPendenteFuncaoPura(SimpleTestCase):
    """Guarda de cache pré-quick (Termo Aditivo externo
    ainda não baixado como PDF), 4 casos do `<behavior>`."""

    def test_sem_anterior_nao_pendente(self):
        self.assertFalse(_aditivo_externo_pendente(None))
        self.assertFalse(_aditivo_externo_pendente({}))

    def test_termo_aditivo_externo_nao_baixado_e_pendente(self):
        anterior = {
            "documentos_contratuais": [
                {"id_documento": "9002", "tipo": "termo_aditivo", "conteudo": "externo_nao_baixado"}
            ]
        }
        self.assertTrue(_aditivo_externo_pendente(anterior))

    def test_termo_aditivo_ja_lido_como_pdf_nao_e_pendente(self):
        for conteudo in ("pdf", "pdf_sem_texto", "pdf_outro_orgao", "pdf_sem_assinatura_digital"):
            anterior = {
                "documentos_contratuais": [
                    {"id_documento": "9002", "tipo": "termo_aditivo", "conteudo": conteudo}
                ]
            }
            self.assertFalse(_aditivo_externo_pendente(anterior), conteudo)

    def test_contrato_externo_nao_baixado_nao_e_pendente(self):
        # Não é Termo Aditivo — a pendência desta quick é só para o tipo
        # que NUNCA era baixado antes dela.
        anterior = {
            "documentos_contratuais": [
                {"id_documento": "9001", "tipo": "contrato", "conteudo": "externo_nao_baixado"}
            ]
        }
        self.assertFalse(_aditivo_externo_pendente(anterior))


class TestColetarUmAditivoExternoPendenteForcaRecoleta(SimpleTestCase):
    """Cache anterior com um Termo Aditivo externo ainda
    `externo_nao_baixado` NUNCA é reaproveitado pelo atalho de pulo, mesmo
    com `registros`/`primeiro` idênticos e sem `reprocessar_documentos=
    True`; mas o HTML já definitivo no mesmo processo nunca é relido."""

    def test_aditivo_pendente_forca_recoleta_sem_reler_html_definitivo(self):
        doc_html_definitivo = _doc_definitivo("9001")
        doc_aditivo_pendente = {
            "id_documento": "9002",
            "protocolo": "1469673",
            "rotulo": "Termo Aditivo 3/2026",
            "tipo": "termo_aditivo",
            "conteudo": "externo_nao_baixado",
            "texto_corpo": None,
        }
        anterior = {
            "registros": _RESUMO_PADRAO["registros"],
            "primeiro": _RESUMO_PADRAO["primeiro"],
            "coletado_em": "2026-09-17T10:00:00-03:00",
            "id_procedimento": "1043956",
            "pastas": {"botao": True},
            "total_documentos": 2,
            "andamentos": {
                "marcos": {"ultimo": {"data_hora": "17/09/2026 09:00"}, "ultima_remessa": None,
                           "recebimentos_gelic_delic": []}
            },
            "documentos_contratuais": [doc_html_definitivo, doc_aditivo_pendente],
            "resultado": "ok",
        }
        cache = {
            "processos": {"123": anterior},
            "documentos": {"9001": doc_html_definitivo},
        }
        doc_aditivo_lido = dict(doc_aditivo_pendente, conteudo="pdf", texto_corpo="corpo lido")
        docs_arvore = [
            _doc_arvore("9001", rotulo="Contrato 01/2026"),
            _doc_arvore("9002", rotulo="Termo Aditivo 3/2026"),
        ]
        sei = SEIFalso(docs=docs_arvore, documentos_lidos={"9002": doc_aditivo_lido})

        r = coletar_um(sei, "123", cache=cache, forcar=False)

        sei.historico.assert_called_once()
        sei.abrir_todas_pastas.assert_called_once()
        self.assertNotIn("pulado", r)
        chamadas = [c.args[0]["id_documento"] for c in sei.ler_documento.call_args_list]
        self.assertEqual(chamadas, ["9002"])
        documento_final_9001 = next(
            d for d in r["documentos_contratuais"] if d["id_documento"] == "9001"
        )
        self.assertEqual(documento_final_9001, {**doc_html_definitivo, "do_cache": True})


class TestDocumentoAnteriorFuncaoPura(SimpleTestCase):
    def test_prioriza_cache_de_documentos(self):
        cache = {"documentos": {"9001": {"origem": "documentos"}}}
        anterior_processo = {"documentos_contratuais": [{"id_documento": "9001", "origem": "processo"}]}
        self.assertEqual(
            _documento_anterior(cache, anterior_processo, "9001")["origem"], "documentos"
        )

    def test_cai_para_representacao_por_processo(self):
        cache = {"documentos": {}}
        anterior_processo = {"documentos_contratuais": [{"id_documento": "9001", "origem": "processo"}]}
        self.assertEqual(
            _documento_anterior(cache, anterior_processo, "9001")["origem"], "processo"
        )

    def test_nenhuma_das_duas_devolve_none(self):
        self.assertIsNone(_documento_anterior({"documentos": {}}, {}, "9001"))


class TestReprocessarDocumentos(SimpleTestCase):
    def test_atalho_de_pulo_e_atravessado_e_ambas_representacoes_migram(self):
        doc_antigo = {
            "id_documento": "9001",
            "protocolo": "1204703",
            "rotulo": "Contrato 01/2026",
            "tipo": "contrato",
            "conteudo": "html",
            "assinado_cfc": True,
            "assinado_externo": True,
            "valor": None,
            # cache antigo: sem versao_extracao/texto_corpo/hash_texto.
        }
        doc_relido = dict(doc_antigo)
        doc_relido.update({
            "texto_corpo": "corpo novo",
            "versao_extracao": VERSAO_EXTRACAO_DOCUMENTO,
            "hash_texto": hash_texto("corpo novo"),
            "assinaturas": [
                {"papel": "cfc", "cargo": "Presidente", "nome": "Fulano de Tal",
                 "data": "01/01/2026", "hora": "10:00"}
            ],
        })
        anterior_processo = {
            "registros": _RESUMO_PADRAO["registros"],
            "primeiro": _RESUMO_PADRAO["primeiro"],
            "documentos_contratuais": [doc_antigo],
            "andamentos": {},
            "pastas": {},
            "total_documentos": 1,
            "resultado": "ok",
        }
        cache = {
            "processos": {"123": anterior_processo},
            "documentos": {"9001": dict(doc_antigo)},
        }
        sei = SEIFalso(docs=[_doc_arvore("9001")], documentos_lidos={"9001": doc_relido})

        r = coletar_um(sei, "123", cache=cache, forcar=False, reprocessar_documentos=True)

        sei.ler_documento.assert_called_once()
        self.assertNotIn("pulado", r)
        self.assertEqual(r["resultado"], "ok")
        self.assertEqual(cache["documentos"]["9001"]["texto_corpo"], "corpo novo")
        self.assertEqual(cache["documentos"]["9001"]["versao_extracao"], VERSAO_EXTRACAO_DOCUMENTO)
        self.assertEqual(
            cache["processos"]["123"]["documentos_contratuais"][0]["texto_corpo"], "corpo novo"
        )
        self.assertEqual(
            cache["processos"]["123"]["documentos_contratuais"][0]["assinaturas"][0]["nome"],
            "Fulano de Tal",
        )

    def test_segunda_chamada_ja_migrada_pula_sem_reler(self):
        doc_migrado = {
            "id_documento": "9001",
            "protocolo": "1204703",
            "rotulo": "Contrato 01/2026",
            "tipo": "contrato",
            "conteudo": "html",
            "assinado_cfc": True,
            "assinado_externo": True,
            "valor": None,
            "texto_corpo": "corpo",
            "versao_extracao": VERSAO_EXTRACAO_DOCUMENTO,
            "hash_texto": hash_texto("corpo"),
        }
        anterior_processo = {
            "registros": _RESUMO_PADRAO["registros"],
            "primeiro": _RESUMO_PADRAO["primeiro"],
            "documentos_contratuais": [doc_migrado],
            "andamentos": {},
            "pastas": {},
            "total_documentos": 1,
            "resultado": "ok",
        }
        cache = {
            "processos": {"123": anterior_processo},
            "documentos": {"9001": doc_migrado},
        }
        sei = SEIFalso()  # ler_documento explodiria (KeyError) se chamado

        r = coletar_um(sei, "123", cache=cache, forcar=False, reprocessar_documentos=True)

        sei.ler_documento.assert_not_called()
        self.assertTrue(r["pulado"])

    def test_forcar_sozinho_nao_rele_documento_definitivo_do_cache_a10(self):
        doc_antigo = _doc_definitivo("9001")  # sem versao_extracao — cache antigo
        anterior_processo = {
            "registros": _RESUMO_PADRAO["registros"],
            "primeiro": _RESUMO_PADRAO["primeiro"],
            "documentos_contratuais": [doc_antigo],
            "andamentos": {},
            "pastas": {},
            "total_documentos": 1,
            "resultado": "ok",
        }
        cache = {
            "processos": {"123": anterior_processo},
            "documentos": {"9001": dict(doc_antigo)},
        }
        sei = SEIFalso(docs=[_doc_arvore("9001")])  # ler_documento explodiria se chamado

        r = coletar_um(sei, "123", cache=cache, forcar=True, reprocessar_documentos=False)

        sei.ler_documento.assert_not_called()
        devolvido = r["documentos_contratuais"][0]
        self.assertTrue(devolvido["do_cache"])

    def test_falha_na_releitura_preserva_entrada_anterior_sem_esvaziar(self):
        doc_antigo = _doc_definitivo("9001")
        anterior_processo = {
            "registros": _RESUMO_PADRAO["registros"],
            "primeiro": _RESUMO_PADRAO["primeiro"],
            "documentos_contratuais": [doc_antigo],
            "andamentos": {},
            "pastas": {},
            "total_documentos": 1,
            "resultado": "ok",
        }
        cache = {
            "processos": {"123": anterior_processo},
            "documentos": {"9001": dict(doc_antigo)},
        }
        sei = SEIFalso(docs=[_doc_arvore("9001")])
        sei.ler_documento = Mock(side_effect=TimeoutError("tempo esgotado"))

        r = coletar_um(sei, "123", cache=cache, forcar=False, reprocessar_documentos=True)

        self.assertEqual(r["resultado"], "ok")
        devolvido = r["documentos_contratuais"][0]
        self.assertEqual(devolvido["reprocessamento_erro"], "TimeoutError: tempo esgotado")
        self.assertTrue(devolvido["do_cache"])
        self.assertNotEqual(devolvido.get("texto_corpo"), "")
        # A representação por documentos preserva a entrada anterior intacta
        # (o documento com erro nunca é promovido — `do_cache=True` pula a
        # promoção no laço de gravação de `coletar_um`).
        self.assertEqual(cache["documentos"]["9001"], doc_antigo)


class _FrameArvoreFalso:
    """Frame `ifrArvore` falso — só `locator(...).first.click()`, chamado
    pelo laço de tentativa de clique em `SEI.ler_documento`."""

    def locator(self, seletor):
        return self

    @property
    def first(self):
        return self

    def click(self):
        return None


class _FrameConteudoFalso:
    """Frame `ifrConteudoVisualizacao` falso — `url` (checado por `marca not
    in f.url`) e `locator('#ifrVisualizacao').first.get_attribute('src')`."""

    def __init__(self, url, src):
        self.url = url
        self._src = src

    def locator(self, seletor):
        return self

    @property
    def first(self):
        return self

    def get_attribute(self, nome, timeout=None):
        return self._src


class _CtxRequestFalso:
    """`self.ctx.request.get(src)` falso — devolve um corpo/`content-type`/
    `status` fixos, sem nenhuma rede real."""

    def __init__(self, corpo: bytes, content_type: str, status: int = 200):
        self._corpo = corpo
        self._content_type = content_type
        self.status = status

    def get(self, url, max_redirects=3):
        return self

    def body(self):
        return self._corpo

    @property
    def headers(self):
        return {"content-type": self._content_type}


def _sei_ler_documento_falso(*, src, content_type, corpo: bytes):
    """Objeto `self` falso mínimo para chamar `SEI.ler_documento` sem
    Playwright — só os atributos/métodos que o método de fato usa
    (`frame_arvore`, `_frame`, `ctx.request`, `rede`, `t`)."""
    frame_conteudo = _FrameConteudoFalso(url=src, src=src)
    return SimpleNamespace(
        frame_arvore=lambda: _FrameArvoreFalso(),
        _frame=lambda nome: frame_conteudo,
        ctx=SimpleNamespace(request=_CtxRequestFalso(corpo=corpo, content_type=content_type)),
        rede=Mock(),
        t=5,
    )


class TestLerDocumentoCorpo(SimpleTestCase):
    """/A10 — `ler_documento`, no ramo `html`, grava `texto_corpo`/
    `versao_extracao`/`hash_texto` sem nunca gravar o HTML bruto; no ramo
    `nao_html:*`, `texto_corpo` fica `None` (indisponível explícito)."""

    def test_ramo_html_grava_corpo_versao_e_hash_sem_html_bruto(self):
        src = "/sei/controlador.php?acao=documento_visualizar&id_documento=9001"
        html = (
            "<html><body>"
            "<p>CLÁUSULA PRIMEIRA – DO OBJETO</p>"
            "<p>1.1 O objeto do presente contrato.</p>"
            "<p>Documento assinado eletronicamente por Fulano de Tal, "
            "Presidente do CFC, em 03/02/2026, às 14:30.</p>"
            "</body></html>"
        )
        fake_self = _sei_ler_documento_falso(
            src=src, content_type="text/html; charset=utf-8", corpo=html.encode("utf-8")
        )
        doc = {
            "id_documento": "9001",
            "protocolo": "1204703",
            "rotulo": "Contrato 01/2026",
            "cancelado": False,
            "motivo_cancelamento": None,
            "assinantes_externos_na_arvore": 1,
        }

        resultado = SEI.ler_documento(fake_self, doc)

        self.assertEqual(resultado["conteudo"], "html")
        self.assertEqual(resultado["versao_extracao"], VERSAO_EXTRACAO_DOCUMENTO)
        self.assertIn("CLÁUSULA PRIMEIRA", resultado["texto_corpo"])
        self.assertNotIn("Documento assinado eletronicamente", resultado["texto_corpo"])
        self.assertEqual(resultado["hash_texto"], hash_texto(resultado["texto_corpo"]))
        self.assertNotIn("corpo", resultado)
        self.assertNotIn("src", resultado)

    def test_ramo_nao_html_texto_corpo_none(self):
        src = "/sei/controlador.php?acao=documento_visualizar&id_documento=9002"
        fake_self = _sei_ler_documento_falso(
            src=src, content_type="application/pdf", corpo=b"%PDF-1.4 conteudo binario"
        )
        doc = {
            "id_documento": "9002",
            "protocolo": "1204703",
            "rotulo": "Contrato 02/2026",
            "cancelado": False,
            "motivo_cancelamento": None,
            "assinantes_externos_na_arvore": 0,
        }

        resultado = SEI.ler_documento(fake_self, doc)

        self.assertTrue(resultado["conteudo"].startswith("nao_html:"))
        self.assertIsNone(resultado["texto_corpo"])
        self.assertEqual(resultado["versao_extracao"], VERSAO_EXTRACAO_DOCUMENTO)

    def test_documento_cancelado_texto_corpo_none(self):
        doc = {
            "id_documento": "9003",
            "protocolo": "1204703",
            "rotulo": "Contrato 03/2026",
            "cancelado": True,
            "motivo_cancelamento": "erro de autuação",
            "assinantes_externos_na_arvore": 0,
        }
        resultado = SEI.ler_documento(SimpleNamespace(), doc)
        self.assertEqual(resultado["conteudo"], "cancelado")
        self.assertIsNone(resultado["texto_corpo"])
        self.assertEqual(resultado["versao_extracao"], VERSAO_EXTRACAO_DOCUMENTO)


class _LocatorFalso:
    """Locator falso minimo — `.first` devolve o proprio objeto; `.count()`/
    `.is_visible()` fixos por construcao; `.click()` incrementa um contador
    (lanca se `falha_ao_clicar=True`); `.wait_for()` marca uma flag."""

    def __init__(self, *, existe, falha_ao_clicar=False):
        self.existe = existe
        self.falha_ao_clicar = falha_ao_clicar
        self.cliques = 0
        self.wait_for_chamado = False

    @property
    def first(self):
        return self

    def count(self):
        return 1 if self.existe else 0

    def is_visible(self, timeout=None):
        return self.existe

    def click(self, timeout=None):
        if self.falha_ao_clicar:
            raise RuntimeError("clique interceptado pelo overlay")
        self.cliques += 1

    def wait_for(self, state=None, timeout=None):
        self.wait_for_chamado = True


class _TecladoFalso:
    def __init__(self):
        self.teclas = []

    def press(self, tecla):
        self.teclas.append(tecla)


class _PaginaFalsa:
    def __init__(self, *, overlay, fechar):
        self._overlay = overlay
        self._fechar = fechar
        self.keyboard = _TecladoFalso()

    def locator(self, seletor):
        if seletor == _SELETOR_OVERLAY_NOVIDADES:
            return self._overlay
        if seletor == _SELETOR_FECHAR_NOVIDADES:
            return self._fechar
        raise AssertionError(f"seletor inesperado: {seletor!r}")


class TestFecharModalNovidades(SimpleTestCase):
    def _sei(self, *, overlay, fechar):
        sei = SEI.__new__(SEI)
        sei.p1 = _PaginaFalsa(overlay=overlay, fechar=fechar)
        return sei

    def test_overlay_ausente_devolve_false_sem_clicar(self):
        overlay = _LocatorFalso(existe=False)
        fechar = _LocatorFalso(existe=True)
        sei = self._sei(overlay=overlay, fechar=fechar)

        resultado = sei.fechar_modal_novidades()

        self.assertFalse(resultado)
        self.assertEqual(fechar.cliques, 0)

    def test_overlay_presente_clique_bem_sucedido_devolve_true(self):
        overlay = _LocatorFalso(existe=True)
        fechar = _LocatorFalso(existe=True)
        sei = self._sei(overlay=overlay, fechar=fechar)

        resultado = sei.fechar_modal_novidades()

        self.assertTrue(resultado)
        self.assertEqual(fechar.cliques, 1)
        self.assertTrue(overlay.wait_for_chamado)

    def test_overlay_presente_clique_falha_cai_para_escape_devolve_true(self):
        overlay = _LocatorFalso(existe=True)
        fechar = _LocatorFalso(existe=True, falha_ao_clicar=True)
        sei = self._sei(overlay=overlay, fechar=fechar)

        resultado = sei.fechar_modal_novidades()

        self.assertTrue(resultado)
        self.assertEqual(sei.p1.keyboard.teclas, ["Escape"])


class _FrameArvoreProcessarFalso:
    """Frame falso de `p1.frames` cuja `.url` contém "arvore_processar_html"
`locator('#divArvoreHtml').first.inner_html(...)`
    devolve o HTML (já escapado como o SEI de fato produz, `&amp;`) com o
    link de download do anexo, ou lança (`timeout`) quando `estoura_timeout`."""

    def __init__(self, url, html_escapado=None, estoura_timeout=False, desmontado=False):
        self.url = url
        self._html = html_escapado
        self._estoura_timeout = estoura_timeout
        self._desmontado = desmontado

    def is_detached(self):
        return self._desmontado

    def locator(self, seletor):
        return self

    @property
    def first(self):
        return self

    def inner_html(self, timeout=None):
        if self._estoura_timeout:
            raise RuntimeError("timeout simulado")
        return self._html


def _html_divarvore_com_link(id_documento="1", id_anexo="2"):
    return (
        '<div id="divArvoreHtml">'
        '<a href="controlador.php?acao=documento_download_anexo&amp;id_documento='
        f'{id_documento}&amp;id_anexo={id_anexo}&amp;infra_sistema=100000100">baixar</a>'
        "</div>"
    )


def _sei_ler_documento_externo_falso(*, rotulo, corpo, content_type="application/pdf",
                                      frames=None, protocolo="1374943", id_documento="9101"):
    """Objeto `self` falso para `SEI.ler_documento` no ramo externo (quick) — estende `_sei_ler_documento_falso` com `p1.frames` (frame
    `arvore_processar_html`, achado ao vivo do CONTEXT do plano) e liga
    `_frame_por_url`/`_link_anexo_externo`/`baixar_anexo_externo` à
    implementação REAL de `SEI` (não mocadas) para exercitar a lógica de
    verdade com frames/`ctx.request` falsos. `baixar_anexo_externo` é um
    `Mock(side_effect=...)` para permitir `assert_called`/`assert_not_called`."""
    src = f"/sei/controlador.php?acao=arvore_processar_html&id_documento={id_documento}"
    frame_conteudo = _FrameConteudoFalso(url=src, src=src)
    if frames is None:
        frames = [_FrameArvoreProcessarFalso(url=src, html_escapado=_html_divarvore_com_link())]
    fake_self = SimpleNamespace(
        frame_arvore=lambda: _FrameArvoreFalso(),
        _frame=lambda nome: frame_conteudo,
        ctx=SimpleNamespace(request=_CtxRequestFalso(corpo=corpo, content_type=content_type)),
        rede=Mock(),
        t=1,
        p1=SimpleNamespace(frames=frames),
    )
    fake_self._frame_por_url = lambda contem: SEI._frame_por_url(fake_self, contem)
    fake_self._link_anexo_externo = lambda: SEI._link_anexo_externo(fake_self)
    fake_self.baixar_anexo_externo = Mock(side_effect=lambda: SEI.baixar_anexo_externo(fake_self))
    doc = {
        "id_documento": id_documento,
        "protocolo": protocolo,
        "rotulo": rotulo,
        "cancelado": False,
        "motivo_cancelamento": None,
        "assinantes_externos_na_arvore": 1,
    }
    return fake_self, doc


class TestLinkAnexoExternoFrameDesmontado(SimpleTestCase):
    """Achado ao vivo (item 58, 02/10/2026): o SEI troca o frame
    `arvore_processar_html` logo após o clique; o antigo, desmontado, segue em
    `p1.frames` e o link nunca era achado. Frame desmontado é ignorado e a
    espera bombeia eventos por `p1.wait_for_timeout`, nunca `time.sleep`."""

    def _sei(self, frames):
        src = "/sei/controlador.php?acao=arvore_processar_html&id_documento=1"
        pausas = []
        p1 = SimpleNamespace(frames=frames, wait_for_timeout=lambda ms: pausas.append(ms))
        sei = SimpleNamespace(p1=p1, t=1)
        sei._frame_por_url = lambda contem: SEI._frame_por_url(sei, contem)
        return sei, src, pausas

    def test_frame_desmontado_e_ignorado(self):
        src = "/sei/controlador.php?acao=arvore_processar_html&id_documento=1"
        velho = _FrameArvoreProcessarFalso(url=src, estoura_timeout=True, desmontado=True)
        novo = _FrameArvoreProcessarFalso(url=src, html_escapado=_html_divarvore_com_link(id_anexo="77"))
        sei, _, _ = self._sei([velho, novo])
        link = SEI._link_anexo_externo(sei)
        self.assertIn("id_anexo=77", link)

    def test_espera_bombeia_eventos_pelo_wait_for_timeout(self):
        src = "/sei/controlador.php?acao=arvore_processar_html&id_documento=1"
        frames = []
        sei, _, pausas = self._sei(frames)

        def aparece(ms):
            pausas.append(ms)
            frames.append(_FrameArvoreProcessarFalso(url=src, html_escapado=_html_divarvore_com_link()))

        sei.p1.wait_for_timeout = aparece
        link = SEI._link_anexo_externo(sei)
        self.assertIsNotNone(link)
        self.assertEqual(pausas, [300])


class TestFramePorUrl(SimpleTestCase):
    """`SEI._frame_por_url` — percorre `self.p1.frames`
    e devolve o primeiro cujo `.url` contém `contem`, nunca lança."""

    def test_acha_frame_pelo_pedaco_da_url(self):
        frame = _FrameArvoreProcessarFalso(url="https://sei.cfc.org.br/x?acao=arvore_processar_html&y=1")
        fake_self = SimpleNamespace(p1=SimpleNamespace(frames=[frame]))
        self.assertIs(SEI._frame_por_url(fake_self, "arvore_processar_html"), frame)

    def test_nenhum_frame_casa_devolve_none(self):
        fake_self = SimpleNamespace(p1=SimpleNamespace(frames=[]))
        self.assertIsNone(SEI._frame_por_url(fake_self, "arvore_processar_html"))

    def test_frame_com_url_none_nunca_lanca(self):
        class _FrameUrlNone:
            url = None

        fake_self = SimpleNamespace(p1=SimpleNamespace(frames=[_FrameUrlNone()]))
        self.assertIsNone(SEI._frame_por_url(fake_self, "arvore_processar_html"))


class TestLerDocumentoExternoContrato(SimpleTestCase):
    """`SEI.ler_documento` baixa e lê o PDF só quando `tipo_documento(rotulo)
    == "contrato"` — os 4 comportamentos do bloco
    `<behavior>` do plano."""

    def test_contrato_externo_baixa_e_processa_pdf(self):
        pdf_bytes = construir_pdf_sintetico(assinaturas=ASSINATURAS_ITEM_58)
        fake_self, doc = _sei_ler_documento_externo_falso(
            rotulo="Contrato 25/2026", corpo=pdf_bytes,
        )

        resultado = SEI.ler_documento(fake_self, doc, numero_processo=PROCESSO_ITEM_58)

        self.assertEqual(resultado["conteudo"], "pdf")
        self.assertTrue(resultado["assinado_cfc"])
        self.assertTrue(resultado["assinado_externo"])
        self.assertEqual(resultado["numero_no_corpo"], "25/2026")
        self.assertEqual(resultado["versao_extracao"], VERSAO_EXTRACAO_DOCUMENTO)
        self.assertEqual(resultado["tipo"], "contrato")
        fake_self.baixar_anexo_externo.assert_called_once()

    def test_termo_aditivo_externo_tambem_baixa_e_processa_pdf(self):
        # Comportamento NOVO — Termo Aditivo externo
        # também é baixado e lido como PDF, mesmo caminho do Contrato.
        pdf_bytes = construir_pdf_sintetico(
            linhas=TEXTO_ADITIVO_ITEM_89, assinaturas=ASSINATURAS_ADITIVO_ITEM_89,
        )
        fake_self, doc = _sei_ler_documento_externo_falso(
            rotulo="Termo Aditivo 3/2026", corpo=pdf_bytes,
        )

        resultado = SEI.ler_documento(fake_self, doc, numero_processo=PROCESSO_ITEM_89)

        self.assertEqual(resultado["conteudo"], "pdf")
        self.assertTrue(resultado["assinado_cfc"])
        self.assertTrue(resultado["assinado_externo"])
        self.assertEqual(resultado["numero_no_corpo"], "26/2023")
        self.assertEqual(resultado["tipo"], "termo_aditivo")
        fake_self.baixar_anexo_externo.assert_called_once()

    def test_apostilamento_externo_nunca_tenta_baixar(self):
        # Prova de que o gate não ficou genérico demais: só
        # "contrato"/"termo_aditivo" baixam; "apostilamento" (e qualquer
        # outro tipo) continua `externo_nao_baixado` byte a byte.
        pdf_bytes = construir_pdf_sintetico(assinaturas=ASSINATURAS_ITEM_58)
        fake_self, doc = _sei_ler_documento_externo_falso(
            rotulo="Apostilamento 01/2026", corpo=pdf_bytes,
        )

        resultado = SEI.ler_documento(fake_self, doc, numero_processo=PROCESSO_ITEM_58)

        self.assertEqual(resultado["conteudo"], "externo_nao_baixado")
        self.assertIsNone(resultado["texto_corpo"])
        fake_self.baixar_anexo_externo.assert_not_called()

    def test_contrato_sem_link_de_download_degrada_para_externo_nao_baixado(self):
        pdf_bytes = construir_pdf_sintetico(assinaturas=ASSINATURAS_ITEM_58)
        frames = [_FrameArvoreProcessarFalso(
            url="/sei/controlador.php?acao=arvore_processar_html",
            html_escapado='<div id="divArvoreHtml">sem link nenhum aqui</div>',
        )]
        fake_self, doc = _sei_ler_documento_externo_falso(
            rotulo="Contrato 25/2026", corpo=pdf_bytes, frames=frames,
        )
        fake_self.t = 0.4

        resultado = SEI.ler_documento(fake_self, doc, numero_processo=PROCESSO_ITEM_58)

        self.assertEqual(resultado["conteudo"], "externo_nao_baixado")
        fake_self.baixar_anexo_externo.assert_called_once()

    def test_contrato_sem_frame_arvore_processar_html_degrada(self):
        pdf_bytes = construir_pdf_sintetico(assinaturas=ASSINATURAS_ITEM_58)
        fake_self, doc = _sei_ler_documento_externo_falso(
            rotulo="Contrato 25/2026", corpo=pdf_bytes, frames=[],
        )
        fake_self.t = 0.4

        resultado = SEI.ler_documento(fake_self, doc, numero_processo=PROCESSO_ITEM_58)

        self.assertEqual(resultado["conteudo"], "externo_nao_baixado")

    def test_contrato_outro_orgao_descarta_silenciosamente(self):
        linhas_outro = []
        from apps.pca.tests.test_sei_pdf import TEXTO_ITEM_58 as _TEXTO
        for linha in _TEXTO:
            if PROCESSO_ITEM_58 in linha:
                linhas_outro.append("processo SEI 23069.000001/2024-11.")
            else:
                linhas_outro.append(linha)
        pdf_bytes = construir_pdf_sintetico(linhas=linhas_outro, assinaturas=ASSINATURAS_ITEM_58)
        fake_self, doc = _sei_ler_documento_externo_falso(
            rotulo="Contrato 25/2026", corpo=pdf_bytes,
        )

        resultado = SEI.ler_documento(fake_self, doc, numero_processo=PROCESSO_ITEM_58)

        self.assertEqual(resultado["conteudo"], "pdf_outro_orgao")


class TestDocumentoDefinitivoPdf(SimpleTestCase):
    """`_documento_definitivo` aceita `conteudo="pdf"` na mesma disciplina
    do HTML."""

    def test_pdf_assinado_por_ambos_entra_no_cache(self):
        info = {
            "conteudo": "pdf",
            "tipo": "contrato",
            "assinado_cfc": True,
            "assinado_externo": True,
            "valor": {"cifra": "39.141,20", "extenso": "...", "confere": True},
        }
        self.assertTrue(_documento_definitivo(info))

    def test_pdf_sem_texto_nunca_entra(self):
        info = {"conteudo": "pdf_sem_texto", "tipo": "contrato"}
        self.assertFalse(_documento_definitivo(info))

    def test_pdf_outro_orgao_nunca_entra(self):
        info = {"conteudo": "pdf_outro_orgao", "tipo": "contrato"}
        self.assertFalse(_documento_definitivo(info))

    def test_pdf_sem_assinatura_digital_nunca_entra(self):
        info = {"conteudo": "pdf_sem_assinatura_digital", "tipo": "contrato"}
        self.assertFalse(_documento_definitivo(info))

    def test_pdf_assinado_so_pelo_cfc_nunca_entra(self):
        info = {
            "conteudo": "pdf",
            "tipo": "contrato",
            "assinado_cfc": True,
            "assinado_externo": False,
        }
        self.assertFalse(_documento_definitivo(info))
