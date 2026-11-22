"""Testes da API JSON `/api/sei/` (Fase 42): CORS restrito, limitador de
requisições, autenticação Bearer, os dois endpoints GET (`saude`/
`processo`) e `POST /coleta`.

Nunca o SEI real — nenhum teste aqui toca `apps.pca.sei.coletor`/
Playwright."""

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.cache import cache
from django.http import JsonResponse
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from apps.catalogo.models import (
    Categoria,
    Exercicio,
    GrauPrioridade,
    Modalidade,
    SituacaoExercicio,
    SituacaoNormalizada,
    Tipo,
    Unidade,
)
from apps.pca.api import limitador
from apps.pca.api.autenticacao import corpo_dentro_do_limite, pode_instruir, requer_token
from apps.pca.models import FichaContratacao, Processo, ProcessoSEI, Situacao
from apps.pca.sei import execucoes
from core.models import TokenApi

FIXTURE_COLETA_ITEM_3 = (
    Path(__file__).resolve().parent / "fixtures" / "sei" / "coleta_item_3.json"
)


@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False)
class TestCorsExtensaoMiddleware(TestCase):
    """`core.middleware.CorsExtensaoMiddleware` — origem fixa de
    `API_ORIGENS_EXTENSAO` (padrão `https://sei.cfc.org.br`) ou
    `chrome-extension://[a-p]{32}`."""

    def test_options_com_origem_permitida_devolve_cors(self):
        resposta = self.client.options(
            "/api/sei/saude", HTTP_ORIGIN="https://sei.cfc.org.br"
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(
            resposta["Access-Control-Allow-Origin"], "https://sei.cfc.org.br"
        )
        self.assertEqual(
            resposta["Access-Control-Allow-Methods"], "GET, POST, PUT, OPTIONS"
        )
        self.assertEqual(
            resposta["Access-Control-Allow-Headers"], "Authorization, Content-Type"
        )

    def test_options_com_origem_fora_da_lista_nao_tem_cors(self):
        resposta = self.client.options(
            "/api/sei/saude", HTTP_ORIGIN="https://exemplo-qualquer.com"
        )
        self.assertNotIn("Access-Control-Allow-Origin", resposta)

    def test_chrome_extension_com_32_letras_a_p_e_permitida(self):
        origem = "chrome-extension://" + "a" * 32
        resposta = self.client.options("/api/sei/saude", HTTP_ORIGIN=origem)
        self.assertEqual(resposta["Access-Control-Allow-Origin"], origem)

    def test_chrome_extension_com_31_letras_nao_e_permitida(self):
        origem = "chrome-extension://" + "a" * 31
        resposta = self.client.options("/api/sei/saude", HTTP_ORIGIN=origem)
        self.assertNotIn("Access-Control-Allow-Origin", resposta)

    def test_chrome_extension_com_33_letras_nao_e_permitida(self):
        origem = "chrome-extension://" + "a" * 33
        resposta = self.client.options("/api/sei/saude", HTTP_ORIGIN=origem)
        self.assertNotIn("Access-Control-Allow-Origin", resposta)

    def test_rota_fora_de_api_nunca_ganha_cors(self):
        resposta = self.client.options("/healthz", HTTP_ORIGIN="https://sei.cfc.org.br")
        self.assertNotIn("Access-Control-Allow-Origin", resposta)


class TestLimitador(TestCase):
    def tearDown(self):
        cache.clear()

    def test_60_chamadas_permitidas_61a_bloqueada(self):
        token_hash = "hash-de-teste-limitador"
        resultados = [limitador.permitido(token_hash) for _ in range(61)]
        self.assertTrue(all(resultados[:60]))
        self.assertFalse(resultados[60])


class TestRequerToken(TestCase):
    """Autenticação Bearer isolada de qualquer view real (`RequestFactory`,
    não `django.test.Client`) — view-stub decorada aqui mesmo."""

    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user(
            email="extensao@cfc.org.br", password="senha-segura-123"
        )
        cls.permissao = Permission.objects.get(
            codename="editar_pca", content_type__app_label="pca"
        )

    def setUp(self):
        self.factory = RequestFactory()
        _, self.token_valor = TokenApi.gerar(self.usuario)

    def tearDown(self):
        cache.clear()

    def _view_sem_permissao(self):
        @requer_token()
        def view(request):
            return JsonResponse({"ok": True})

        return view

    def _view_com_permissao(self):
        @requer_token(permissao="pca.editar_pca")
        def view(request):
            return JsonResponse({"ok": True})

        return view

    def test_sem_header_devolve_401(self):
        request = self.factory.get("/api/sei/stub")
        resposta = self._view_sem_permissao()(request)
        self.assertEqual(resposta.status_code, 401)
        self.assertEqual(json.loads(resposta.content)["erro"], "nao_autenticado")

    def test_prefixo_errado_devolve_401(self):
        request = self.factory.get("/api/sei/stub", HTTP_AUTHORIZATION="Token xyz")
        resposta = self._view_sem_permissao()(request)
        self.assertEqual(resposta.status_code, 401)

    def test_token_formato_valido_mas_inexistente_devolve_401(self):
        request = self.factory.get(
            "/api/sei/stub", HTTP_AUTHORIZATION="Bearer token-que-nao-existe"
        )
        resposta = self._view_sem_permissao()(request)
        self.assertEqual(resposta.status_code, 401)

    def test_token_revogado_devolve_401(self):
        TokenApi.gerar(self.usuario)  # revoga self.token_valor
        request = self.factory.get(
            "/api/sei/stub", HTTP_AUTHORIZATION=f"Bearer {self.token_valor}"
        )
        resposta = self._view_sem_permissao()(request)
        self.assertEqual(resposta.status_code, 401)

    def test_token_valido_sem_a_permissao_exigida_devolve_403(self):
        request = self.factory.get(
            "/api/sei/stub", HTTP_AUTHORIZATION=f"Bearer {self.token_valor}"
        )
        resposta = self._view_com_permissao()(request)
        self.assertEqual(resposta.status_code, 403)
        self.assertEqual(json.loads(resposta.content)["erro"], "sem_permissao")

    def test_token_valido_com_a_permissao_devolve_o_corpo_da_view(self):
        self.usuario.user_permissions.add(self.permissao)
        request = self.factory.get(
            "/api/sei/stub", HTTP_AUTHORIZATION=f"Bearer {self.token_valor}"
        )
        resposta = self._view_com_permissao()(request)
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(json.loads(resposta.content), {"ok": True})
        self.assertEqual(request.user, self.usuario)

    def test_61_chamadas_no_mesmo_minuto_com_o_mesmo_token_devolve_429_na_61a(self):
        view = self._view_sem_permissao()
        for _ in range(60):
            request = self.factory.get(
                "/api/sei/stub", HTTP_AUTHORIZATION=f"Bearer {self.token_valor}"
            )
            resposta = view(request)
            self.assertEqual(resposta.status_code, 200)

        request = self.factory.get(
            "/api/sei/stub", HTTP_AUTHORIZATION=f"Bearer {self.token_valor}"
        )
        resposta = view(request)
        self.assertEqual(resposta.status_code, 429)
        self.assertEqual(json.loads(resposta.content)["erro"], "limite_requisicoes")


class TestCorpoDentroDoLimite(TestCase):
    def _request_com_content_length(self, valor):
        return RequestFactory().generic(
            "POST", "/api/sei/stub", data="", CONTENT_LENGTH=str(valor)
        )

    def test_abaixo_do_limite(self):
        request = self._request_com_content_length(1024)
        self.assertTrue(corpo_dentro_do_limite(request))

    def test_igual_ao_limite(self):
        from django.conf import settings

        limite = settings.API_MAX_CORPO_MB * 1024 * 1024
        request = self._request_com_content_length(limite)
        self.assertTrue(corpo_dentro_do_limite(request))

    def test_acima_do_limite(self):
        from django.conf import settings

        limite = settings.API_MAX_CORPO_MB * 1024 * 1024
        request = self._request_com_content_length(limite + 1)
        self.assertFalse(corpo_dentro_do_limite(request))


class ApiSeiBase(TestCase):
    """Base de integração real (`django.test.Client`, nunca `force_login`
    — o header `Authorization` é o único jeito de "logar" nesta API) para
    `saude_view`/`processo_view`. `SEI_DATA_DIR` sempre um diretório
    temporário (nunca `BASE_DIR/data` de verdade), mesmo padrão de
    `apps.pca.tests.test_sei_execucoes`."""

    @classmethod
    def setUpTestData(cls):
        cls.exercicio, _ = Exercicio.objects.get_or_create(
            ano=2025, defaults={"situacao": SituacaoExercicio.ABERTO}
        )
        cls.tipo = Tipo.objects.create(nome="Vigente")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.unidade = Unidade.objects.create(nome="GECONT")
        cls.grau = GrauPrioridade.objects.create(nome="Essencial")
        cls.modalidade = Modalidade.objects.create(nome="Pregão Eletrônico")
        cls.usuario = get_user_model().objects.create_user(
            email="gelic@cfc.org.br", password="senha-segura-123"
        )
        cls.permissao = Permission.objects.get(
            codename="editar_pca", content_type__app_label="pca"
        )

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._override = override_settings(SEI_DATA_DIR=self._tmp.name)
        self._override.enable()
        self.addCleanup(self._override.disable)
        self.base = Path(self._tmp.name)
        _, self.token_valor = TokenApi.gerar(self.usuario)
        self.addCleanup(cache.clear)
        cache.clear()

    def _criar_processo(self, item_pca, numero_sei=None, **kwargs):
        kwargs.setdefault("descricao_objeto", f"Objeto {item_pca}")
        kwargs.setdefault("tipo", self.tipo)
        processo = Processo.objects.create(
            item_pca=item_pca,
            exercicio=self.exercicio,
            categoria=self.categoria,
            unidade_organizacional=self.unidade,
            **kwargs,
        )
        if numero_sei:
            ProcessoSEI.objects.create(processo=processo, numero_sei=numero_sei)
        return processo

    def _auth(self, token=None):
        return {"HTTP_AUTHORIZATION": f"Bearer {token or self.token_valor}"}


class TestSaudeView(ApiSeiBase):
    """Adendo (2026-10-10) — autenticação opcional: sem `Authorization`,
    só `{"versao": 1}`; com Bearer válido, também `usuario`/`pode_enviar`;
    Bearer inválido/revogado -> 401."""

    def test_sem_header_devolve_versao(self):
        resposta = self.client.get("/api/sei/saude")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(json.loads(resposta.content), {"versao": 1})

    def test_com_token_valido_devolve_usuario_e_pode_enviar(self):
        resposta = self.client.get("/api/sei/saude", **self._auth())
        self.assertEqual(resposta.status_code, 200)
        corpo = json.loads(resposta.content)
        self.assertEqual(corpo["versao"], 1)
        self.assertEqual(corpo["usuario"], self.usuario.email)
        self.assertFalse(corpo["pode_enviar"])

    def test_com_token_valido_e_permissao_pode_enviar_true(self):
        self.usuario.user_permissions.add(self.permissao)
        resposta = self.client.get("/api/sei/saude", **self._auth())
        self.assertTrue(json.loads(resposta.content)["pode_enviar"])

    def test_com_token_invalido_devolve_401(self):
        resposta = self.client.get("/api/sei/saude", **self._auth("token-que-nao-existe"))
        self.assertEqual(resposta.status_code, 401)
        self.assertEqual(json.loads(resposta.content)["erro"], "nao_autenticado")

    def test_pode_instruir_true_para_grupo_demandante(self):
        self.usuario.groups.add(Group.objects.get(name="demandante"))
        resposta = self.client.get("/api/sei/saude", **self._auth())
        corpo = json.loads(resposta.content)
        self.assertTrue(corpo["pode_instruir"])
        self.assertFalse(corpo["pode_enviar"])
        self.assertEqual(corpo["versao"], 1)

    def test_pode_instruir_true_para_editor_sem_grupo(self):
        self.usuario.user_permissions.add(self.permissao)
        resposta = self.client.get("/api/sei/saude", **self._auth())
        corpo = json.loads(resposta.content)
        self.assertTrue(corpo["pode_instruir"])
        self.assertTrue(corpo["pode_enviar"])
        self.assertEqual(corpo["versao"], 1)

    def test_pode_instruir_false_sem_nenhuma(self):
        resposta = self.client.get("/api/sei/saude", **self._auth())
        corpo = json.loads(resposta.content)
        self.assertFalse(corpo["pode_instruir"])
        self.assertFalse(corpo["pode_enviar"])
        self.assertEqual(corpo["versao"], 1)


class TestProcessoViewSemToken(ApiSeiBase):
    def test_sem_header_devolve_401(self):
        resposta = self.client.get("/api/sei/processo", {"sei": "qualquer"})
        self.assertEqual(resposta.status_code, 401)


class TestProcessoViewPorSei(ApiSeiBase):
    NUMERO_FORMATADO = "90796110000007.000036/2025-81"
    NUMERO_SO_DIGITOS = "90796110000007000036202581"

    def test_casa_por_digitos_mesmo_com_formatacao_diferente(self):
        self._criar_processo(3, numero_sei=self.NUMERO_FORMATADO, grau_prioridade=self.grau)

        resposta = self.client.get(
            "/api/sei/processo", {"sei": self.NUMERO_SO_DIGITOS}, **self._auth()
        )

        self.assertEqual(resposta.status_code, 200)
        corpo = json.loads(resposta.content)
        self.assertEqual(len(corpo["itens"]), 1)
        item = corpo["itens"][0]
        self.assertEqual(item["item_pca"], 3)
        self.assertEqual(item["exercicio"], 2025)
        self.assertEqual(item["unidade"], "GECONT")
        self.assertEqual(item["grau_prioridade"], "Essencial")
        self.assertEqual(item["numeros_sei"], [self.NUMERO_FORMATADO])
        self.assertIn("situacao_rotulo", item)
        self.assertIsNone(corpo["ultima_coleta"])

    def test_sem_vinculo_devolve_itens_vazio_nunca_404(self):
        resposta = self.client.get(
            "/api/sei/processo", {"sei": "00000000000000000000"}, **self._auth()
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(json.loads(resposta.content), {"itens": []})

    def test_campos_novos_v1_1_com_modalidade(self):
        self._criar_processo(
            4, numero_sei=self.NUMERO_FORMATADO, modalidade=self.modalidade
        )
        resposta = self.client.get(
            "/api/sei/processo", {"sei": self.NUMERO_FORMATADO}, **self._auth()
        )
        item = json.loads(resposta.content)["itens"][0]
        self.assertEqual(item["modalidade"], "Pregão Eletrônico")
        self.assertEqual(item["objeto"], item["descricao_objeto"])
        self.assertEqual(item["unidade_sigla_sei"], item["unidade"])

    def test_campos_novos_v1_1_sem_modalidade_e_null(self):
        self._criar_processo(5, numero_sei=self.NUMERO_FORMATADO)
        resposta = self.client.get(
            "/api/sei/processo", {"sei": self.NUMERO_FORMATADO}, **self._auth()
        )
        item = json.loads(resposta.content)["itens"][0]
        self.assertIsNone(item["modalidade"])

    def test_valor_estimado_serializado_como_string_decimal(self):
        self._criar_processo(
            7, numero_sei=self.NUMERO_FORMATADO, valor_estimado="165000.00"
        )
        resposta = self.client.get(
            "/api/sei/processo", {"sei": self.NUMERO_FORMATADO}, **self._auth()
        )
        item = json.loads(resposta.content)["itens"][0]
        self.assertEqual(item["valor_estimado"], "165000.00")

    def test_ultima_coleta_e_a_mais_recente_entre_cache_e_extensao(self):
        processo = self._criar_processo(9, numero_sei=self.NUMERO_FORMATADO)

        cache_json = {
            "processos": {
                self.NUMERO_FORMATADO: {
                    "registros": 10,
                    "primeiro": {
                        "data_hora": "01/01/2026 08:00",
                        "unidade": "DELIC",
                        "descricao": "Processo recebido na unidade DELIC",
                    },
                    "coletado_em": "2026-10-08T09:15:00-03:00",
                }
            },
            "documentos": {},
        }
        extensao_json = {
            "processos": {
                self.NUMERO_FORMATADO: {
                    "coleta": {
                        "registros": 12,
                        "primeiro": {
                            "data_hora": "05/01/2026 08:00",
                            "unidade": "DELIC",
                            "descricao": "Processo recebido na unidade DELIC",
                        },
                    },
                    "recebido_em": "2026-10-09T09:15:00-03:00",
                    "usuario_id": processo.pk,
                }
            }
        }
        execucoes.gravar_cache(cache_json)
        execucoes.gravar_extensao(extensao_json)

        resposta = self.client.get(
            "/api/sei/processo", {"sei": self.NUMERO_FORMATADO}, **self._auth()
        )
        ultima_coleta = json.loads(resposta.content)["ultima_coleta"]
        self.assertEqual(ultima_coleta["origem"], "extensao")
        self.assertEqual(ultima_coleta["registros"], 12)
        self.assertEqual(ultima_coleta["recebido_em"], "2026-10-09T09:15:00-03:00")

    def test_ultima_coleta_do_robo_quando_mais_recente(self):
        self._criar_processo(11, numero_sei=self.NUMERO_FORMATADO)

        execucoes.gravar_cache({
            "processos": {
                self.NUMERO_FORMATADO: {
                    "registros": 20,
                    "primeiro": None,
                    "coletado_em": "2026-10-10T09:15:00-03:00",
                }
            },
            "documentos": {},
        })
        execucoes.gravar_extensao({
            "processos": {
                self.NUMERO_FORMATADO: {
                    "coleta": {"registros": 5, "primeiro": None},
                    "recebido_em": "2026-10-01T09:15:00-03:00",
                    "usuario_id": self.usuario.pk,
                }
            }
        })

        resposta = self.client.get(
            "/api/sei/processo", {"sei": self.NUMERO_FORMATADO}, **self._auth()
        )
        ultima_coleta = json.loads(resposta.content)["ultima_coleta"]
        self.assertEqual(ultima_coleta["origem"], "robo")
        self.assertEqual(ultima_coleta["registros"], 20)


class TestProcessoViewPorItemExercicio(ApiSeiBase):
    def test_sem_processo_devolve_itens_vazio_200(self):
        resposta = self.client.get(
            "/api/sei/processo", {"item": 999, "exercicio": 2025}, **self._auth()
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(json.loads(resposta.content), {"itens": []})

    def test_com_processo_devolve_o_item_sem_ultima_coleta(self):
        self._criar_processo(117, descricao_objeto="Aquisição de licenças de software")

        resposta = self.client.get(
            "/api/sei/processo", {"item": 117, "exercicio": 2025}, **self._auth()
        )
        corpo = json.loads(resposta.content)
        self.assertEqual(len(corpo["itens"]), 1)
        self.assertEqual(corpo["itens"][0]["numeros_sei"], [])
        self.assertNotIn("ultima_coleta", corpo)

    def test_campos_novos_v1_1_com_e_sem_modalidade(self):
        self._criar_processo(118, modalidade=self.modalidade)

        resposta = self.client.get(
            "/api/sei/processo", {"item": 118, "exercicio": 2025}, **self._auth()
        )
        item = json.loads(resposta.content)["itens"][0]
        self.assertEqual(item["modalidade"], "Pregão Eletrônico")
        self.assertEqual(item["objeto"], item["descricao_objeto"])
        self.assertEqual(item["unidade_sigla_sei"], item["unidade"])

        self._criar_processo(119)
        resposta = self.client.get(
            "/api/sei/processo", {"item": 119, "exercicio": 2025}, **self._auth()
        )
        item = json.loads(resposta.content)["itens"][0]
        self.assertIsNone(item["modalidade"])


class TestProcessoViewSemParametroReconhecido(ApiSeiBase):
    def test_sem_sei_e_sem_item_exercicio_devolve_400(self):
        resposta = self.client.get("/api/sei/processo", **self._auth())
        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(json.loads(resposta.content)["erro"], "corpo_invalido")


# --- POST /api/sei/coleta -------------------------------------


class TestColetaViewBase(ApiSeiBase):
    """Base de `POST /api/sei/coleta` — `self.usuario` sempre com
    `pca.editar_pca` (rota de escrita, do contrato); `self.tipo_servico`
    é um `Tipo` que NUNCA é "vigente" (o `ApiSeiBase.tipo` compartilhado é
    "Vigente" — concluiria por natureza, sem passar pelo passo 3b da
    assinatura por ambas as partes que vários testes daqui exercitam)."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.tipo_servico = Tipo.objects.create(nome="Serviço")
        # `registrar_acompanhamento` (chamado por `aplicador.aplicar`)
        # resolve `situacao` por `SituacaoNormalizada.objects.get(nome=...)`
        # (`MAPA_SITUACAO_NORMALIZADA_POR_SITUACAO`, apps/pca/services.py) —
        # mesmo seed de `apps.pca.tests.test_sei_aplicador.py`, nenhuma
        # migração cria estes 3 registros sozinha.
        for nome in ("Sem informação", "Concluído", "Em tramitação"):
            SituacaoNormalizada.objects.get_or_create(nome=nome)

    def setUp(self):
        super().setUp()
        self.usuario.user_permissions.add(self.permissao)

    def _post(self, corpo, token=None, **extra):
        return self.client.post(
            "/api/sei/coleta",
            data=corpo,
            content_type="application/json",
            **self._auth(token),
            **extra,
        )


class TestColetaViewValidacaoDoCorpo(TestColetaViewBase):
    NUMERO = "90796110000007.000036/2025-81"

    def test_sem_permissao_editar_pca_devolve_403(self):
        self.usuario.user_permissions.clear()
        resposta = self._post({"numero": self.NUMERO, "andamentos": [], "documentos": []})
        self.assertEqual(resposta.status_code, 403)

    def test_json_invalido_devolve_400_com_detalhes(self):
        resposta = self.client.post(
            "/api/sei/coleta", data="{isto nao e json",
            content_type="application/json", **self._auth(),
        )
        self.assertEqual(resposta.status_code, 400)
        corpo = json.loads(resposta.content)
        self.assertEqual(corpo["erro"], "corpo_invalido")
        self.assertTrue(corpo["detalhes"])

    def test_corpo_sem_numero_devolve_400_com_detalhes(self):
        resposta = self._post({"andamentos": [], "documentos": []})
        self.assertEqual(resposta.status_code, 400)
        corpo = json.loads(resposta.content)
        self.assertEqual(corpo["erro"], "corpo_invalido")
        self.assertTrue(any("numero" in detalhe for detalhe in corpo["detalhes"]))

    def test_corpo_sem_documentos_devolve_400(self):
        resposta = self._post({"numero": self.NUMERO, "andamentos": []})
        self.assertEqual(resposta.status_code, 400)
        corpo = json.loads(resposta.content)
        self.assertTrue(any("documentos" in detalhe for detalhe in corpo["detalhes"]))

    def test_documentos_nao_e_lista_devolve_400(self):
        resposta = self._post(
            {"numero": self.NUMERO, "andamentos": [], "documentos": "nao e lista"}
        )
        self.assertEqual(resposta.status_code, 400)
        corpo = json.loads(resposta.content)
        self.assertTrue(any("documentos" in detalhe for detalhe in corpo["detalhes"]))

    def test_documento_sem_id_documento_ou_rotulo_devolve_400(self):
        resposta = self._post({
            "numero": self.NUMERO,
            "andamentos": [],
            "documentos": [{"protocolo": "1", "assinantes_externos_na_arvore": 0}],
        })
        self.assertEqual(resposta.status_code, 400)
        corpo = json.loads(resposta.content)
        self.assertTrue(any("documentos[0]" in detalhe for detalhe in corpo["detalhes"]))

    def test_corpo_acima_do_limite_devolve_413_sem_ler_o_corpo_inteiro(self):
        from django.conf import settings

        limite = settings.API_MAX_CORPO_MB * 1024 * 1024
        resposta = self.client.generic(
            "POST", "/api/sei/coleta", data=b"", content_type="application/json",
            CONTENT_LENGTH=str(limite + 1), **self._auth(),
        )
        self.assertEqual(resposta.status_code, 413)
        self.assertEqual(json.loads(resposta.content)["erro"], "corpo_grande_demais")

    def test_numero_sem_nenhum_item_vinculado_devolve_404(self):
        resposta = self._post(
            {"numero": "00000000000000000000", "andamentos": [], "documentos": []}
        )
        self.assertEqual(resposta.status_code, 404)
        self.assertEqual(json.loads(resposta.content)["erro"], "processo_sem_item")


class TestColetaViewCasamentoPorDigitos(TestColetaViewBase):
    NUMERO_FORMATADO = "90796110000007.000036/2025-81"
    NUMERO_SO_DIGITOS = "90796110000007000036202581"

    def test_numero_formatado_diferente_acha_o_processo_mesmo_assim(self):
        self._criar_processo(3, numero_sei=self.NUMERO_FORMATADO, tipo=self.tipo_servico)

        resposta = self._post({
            "numero": self.NUMERO_SO_DIGITOS,
            "andamentos": [],
            "documentos": [],
        })

        self.assertEqual(resposta.status_code, 200)
        corpo = json.loads(resposta.content)
        self.assertEqual(len(corpo["itens"]), 1)
        self.assertEqual(corpo["itens"][0]["item_pca"], 3)
        self.assertEqual(corpo["itens"][0]["exercicio"], 2025)


class TestColetaViewCompletaComOutroNumero(TestColetaViewBase):
    """Prova central (Opção B): um item com dois números SEI recebe o
    POST do PRIMEIRO, e o resumo de alterações reflete o instrumento do
    SEGUNDO (vindo de `cache.json`, como se o robô já o tivesse coletado)."""

    NUMERO_1 = "90796110000007.000036/2025-82"
    NUMERO_2 = "90796110000007.000036/2025-81"

    def test_alteracoes_refletem_o_instrumento_do_segundo_numero(self):
        processo = self._criar_processo(3, tipo=self.tipo_servico)
        ProcessoSEI.objects.create(processo=processo, numero_sei=self.NUMERO_1)
        ProcessoSEI.objects.create(processo=processo, numero_sei=self.NUMERO_2)

        with open(FIXTURE_COLETA_ITEM_3, encoding="utf-8") as arquivo:
            fixture = json.load(arquivo)
        coleta_segundo_numero = dict(fixture["processos"][0])
        coleta_segundo_numero.pop("item", None)
        coleta_segundo_numero["numero"] = self.NUMERO_2
        coleta_segundo_numero["coletado_em"] = "2026-10-01T09:00:00-03:00"
        execucoes.gravar_cache({
            "processos": {self.NUMERO_2: coleta_segundo_numero},
            "documentos": {},
        })

        resposta = self._post({
            "numero": self.NUMERO_1,
            "andamentos": [
                {"data_hora": "01/01/2026 08:00", "unidade": "DELIC",
                 "descricao": "Processo recebido na unidade DELIC"},
            ],
            "documentos": [],
        })

        self.assertEqual(resposta.status_code, 200)
        corpo = json.loads(resposta.content)
        self.assertEqual(len(corpo["itens"]), 1)
        item = corpo["itens"][0]
        self.assertEqual(item["item_pca"], 3)
        # O instrumento assinado por ambos (protocolo 1210804) só existe na
        # coleta do SEGUNDO número — sem "completar com o outro número" esta
        # alteração nunca apareceria, já que o POST em si não trouxe
        # nenhum documento.
        self.assertIn("data_assinatura_contrato", item["alterados"])
        # Contrato v1 (spec §3): `alterados` é `{campo: [antes, depois]}`.
        self.assertIsInstance(item["alterados"], dict)
        antes, depois = item["alterados"]["data_assinatura_contrato"]
        self.assertIsNone(antes)
        self.assertRegex(depois, r"^\d{4}-\d{2}-\d{2}$")


class TestColetaViewDocumentoRestrito(TestColetaViewBase):
    NUMERO = "90796110000005.000001/2025-33"

    def test_documento_restrito_vira_pendencia_nunca_derruba_a_requisicao(self):
        self._criar_processo(5, numero_sei=self.NUMERO, tipo=self.tipo_servico)

        resposta = self._post({
            "numero": self.NUMERO,
            "andamentos": [],
            "documentos": [{
                "id_documento": "1",
                "protocolo": "1",
                "rotulo": "Contrato nº 1/2026",
                "assinantes_externos_na_arvore": 0,
                "contratual": True,
                "cancelado": False,
                "motivo_cancelamento": None,
                "conteudo": "nao_lido",
                "motivo": "restrito",
                "html": None,
                "pdf_base64": None,
            }],
        })

        self.assertEqual(resposta.status_code, 200)
        corpo = json.loads(resposta.content)
        item = corpo["itens"][0]
        self.assertTrue(
            any(p["chave"].startswith("sem_acesso_documento") for p in item["pendencias"])
        )


class TestColetaViewAplicaDeVerdade(TestColetaViewBase):
    """`aplicador.aplicar(simular=False, usuario=request.user,
    origem="extensao")` de verdade + gravação de `extensao.json` sob
    `fcntl.flock` bloqueante."""

    NUMERO = "90796110000009.000001/2025-10"

    def _corpo_com_instrumento_assinado(self, numero=None):
        return {
            "numero": numero or self.NUMERO,
            "andamentos": [
                {
                    "data_hora": "01/01/2026 08:00",
                    "unidade": "DELIC",
                    "descricao": "Processo recebido na unidade DELIC",
                },
            ],
            "documentos": [{
                "id_documento": "100",
                "protocolo": "100",
                "rotulo": "Contrato nº 1/2026",
                "assinantes_externos_na_arvore": 1,
                "contratual": True,
                "cancelado": False,
                "motivo_cancelamento": None,
                "conteudo": "html",
                "motivo": None,
                "html": (
                    "<html><body>CONSELHO FEDERAL DE CONTABILIDADE SEI nº 100 "
                    "Documento assinado eletronicamente por Fulano, "
                    "Vice-Presidente, em 03/02/2026, às 16:16. "
                    "Documento assinado eletronicamente por Ciclano, "
                    "Usuário Externo, em 19/02/2026, às 16:50.</body></html>"
                ),
                "pdf_base64": None,
            }],
        }

    def test_aplicado_grava_historico_com_usuario_do_token(self):
        self._criar_processo(13, numero_sei=self.NUMERO, tipo=self.tipo_servico)

        resposta = self._post(self._corpo_com_instrumento_assinado())

        self.assertEqual(resposta.status_code, 200)
        processo = Processo.objects.get(item_pca=13, exercicio=self.exercicio)
        self.assertEqual(processo.history.latest().history_user, self.usuario)

    def test_mesma_coleta_duas_vezes_segunda_nao_altera_nada(self):
        self._criar_processo(14, numero_sei=self.NUMERO, tipo=self.tipo_servico)
        corpo = self._corpo_com_instrumento_assinado()

        self._post(corpo)
        resposta2 = self._post(corpo)

        self.assertEqual(json.loads(resposta2.content)["itens"][0]["alterados"], {})

    def test_situacao_manual_preserva_e_gera_pendencia_transicao_manual(self):
        processo = self._criar_processo(
            15, numero_sei=self.NUMERO, tipo=self.tipo_servico, situacao_manual=True,
        )

        resposta = self._post(self._corpo_com_instrumento_assinado())

        corpo = json.loads(resposta.content)
        item = corpo["itens"][0]
        self.assertTrue(any(p["chave"] == "transicao_manual" for p in item["pendencias"]))
        processo.refresh_from_db()
        self.assertEqual(processo.situacao, Situacao.NO_PRAZO)

    def test_extensao_json_tem_entrada_com_recebido_em_e_usuario_do_token(self):
        self._criar_processo(16, numero_sei=self.NUMERO, tipo=self.tipo_servico)
        antes = timezone.now()

        self._post(self._corpo_com_instrumento_assinado())

        extensao = execucoes.ler_extensao()
        entrada = extensao["processos"][self.NUMERO]
        self.assertEqual(entrada["usuario_id"], self.usuario.pk)
        recebido_em = datetime.fromisoformat(entrada["recebido_em"])
        self.assertGreaterEqual(recebido_em, antes - timedelta(seconds=5))

    def test_dois_posts_de_numeros_diferentes_do_mesmo_processo_preservam_as_duas_entradas(self):
        processo = self._criar_processo(17, tipo=self.tipo_servico)
        numero_a = "90796110000017.000001/2025-11"
        numero_b = "90796110000017.000002/2025-22"
        ProcessoSEI.objects.create(processo=processo, numero_sei=numero_a)
        ProcessoSEI.objects.create(processo=processo, numero_sei=numero_b)

        self._post(self._corpo_com_instrumento_assinado(numero=numero_a))
        self._post(self._corpo_com_instrumento_assinado(numero=numero_b))

        extensao = execucoes.ler_extensao()
        self.assertIn(numero_a, extensao["processos"])
        self.assertIn(numero_b, extensao["processos"])

    def test_falha_de_aplicador_devolve_500_e_nao_grava_extensao(self):
        self._criar_processo(18, numero_sei=self.NUMERO, tipo=self.tipo_servico)

        with mock.patch(
            "apps.pca.api.views.aplicador.aplicar", side_effect=RuntimeError("boom")
        ):
            resposta = self._post(self._corpo_com_instrumento_assinado())

        self.assertEqual(resposta.status_code, 500)
        self.assertEqual(json.loads(resposta.content)["erro"], "falha_interna")
        extensao = execucoes.ler_extensao()
        self.assertNotIn(self.NUMERO, extensao.get("processos", {}))


class TestColetaViewUltimaColetaDaExtensao(TestColetaViewBase):
    """Achado da sessão sei-pro (10/10/2026): depois de um POST, o GET
    `processo?sei=` devolve `registros`/`primeiro` da coleta da extensão —
    sem isso o atalho de pulo da extensão nunca funciona."""

    NUMERO = "90796110000007.000036/2025-81"

    def test_post_e_depois_get_devolve_registros_e_primeiro(self):
        self._criar_processo(3, numero_sei=self.NUMERO, tipo=self.tipo_servico)
        self._post({"numero": self.NUMERO, "documentos": [], "andamentos": [
            {"data_hora": "01/09/2026 10:00", "unidade": "GELIC", "descricao": "Processo recebido na unidade GELIC"},
            {"data_hora": "02/09/2026 11:00", "unidade": "DELIC", "descricao": "Processo recebido na unidade DELIC"},
        ]})

        resposta = self.client.get("/api/sei/processo", {"sei": self.NUMERO}, **self._auth())

        ultima = json.loads(resposta.content)["ultima_coleta"]
        self.assertEqual(ultima["origem"], "extensao")
        self.assertEqual(ultima["registros"], 2)
        self.assertEqual(ultima["primeiro"], {
            "data_hora": "02/09/2026 11:00", "unidade": "DELIC", "descricao": "Processo recebido na unidade DELIC",
        })


# --- POST /api/sei/vinculo (V-1/V-2) ----------------------


class TestVinculoView(ApiSeiBase):
    NUMERO_FORMATADO = "90796110000019.000030/2025-74"
    NUMERO_SO_DIGITOS = "90796110000019000030202574"

    def _demandante(self):
        self.usuario.groups.add(Group.objects.get(name="demandante"))

    def _post(self, corpo, token=None):
        return self.client.post(
            "/api/sei/vinculo",
            data=json.dumps(corpo),
            content_type="application/json",
            **self._auth(token),
        )

    def test_sem_token_devolve_401(self):
        resposta = self.client.post(
            "/api/sei/vinculo",
            data=json.dumps({"item_pca": 1, "exercicio": 2025, "numero_sei": "x"}),
            content_type="application/json",
        )
        self.assertEqual(resposta.status_code, 401)

    def test_visualizador_sem_pode_instruir_devolve_403(self):
        self._criar_processo(1)
        resposta = self._post(
            {"item_pca": 1, "exercicio": 2025, "numero_sei": self.NUMERO_FORMATADO}
        )
        self.assertEqual(resposta.status_code, 403)
        self.assertEqual(json.loads(resposta.content)["erro"], "sem_permissao")

    def test_demandante_consegue_vincular(self):
        self._demandante()
        self._criar_processo(1)
        resposta = self._post(
            {"item_pca": 1, "exercicio": 2025, "numero_sei": self.NUMERO_FORMATADO}
        )
        self.assertEqual(resposta.status_code, 201)

    def test_editor_consegue_vincular_sem_estar_no_grupo_demandante(self):
        self.usuario.user_permissions.add(self.permissao)
        self._criar_processo(1)
        resposta = self._post(
            {"item_pca": 1, "exercicio": 2025, "numero_sei": self.NUMERO_FORMATADO}
        )
        self.assertEqual(resposta.status_code, 201)

    def test_item_inexistente_devolve_404(self):
        self._demandante()
        resposta = self._post(
            {"item_pca": 999, "exercicio": 2025, "numero_sei": self.NUMERO_FORMATADO}
        )
        self.assertEqual(resposta.status_code, 404)
        self.assertEqual(json.loads(resposta.content)["erro"], "item_inexistente")

    def test_corpo_invalido_devolve_400_com_detalhes(self):
        self._demandante()
        self._criar_processo(1)
        resposta = self._post({"item_pca": "um", "exercicio": 2025, "numero_sei": ""})
        self.assertEqual(resposta.status_code, 400)
        corpo = json.loads(resposta.content)
        self.assertEqual(corpo["erro"], "corpo_invalido")
        self.assertTrue(corpo["detalhes"])

    def test_primeira_vez_cria_201(self):
        self._demandante()
        processo = self._criar_processo(1)
        resposta = self._post(
            {"item_pca": 1, "exercicio": 2025, "numero_sei": self.NUMERO_FORMATADO}
        )
        self.assertEqual(resposta.status_code, 201)
        corpo = json.loads(resposta.content)
        self.assertTrue(corpo["criado"])
        self.assertEqual(processo.numeros_sei.count(), 1)
        self.assertEqual(
            processo.numeros_sei.first().numero_sei, self.NUMERO_FORMATADO
        )

    def test_mesmo_numero_formatacao_diferente_e_idempotente(self):
        self._demandante()
        processo = self._criar_processo(1, numero_sei=self.NUMERO_FORMATADO)
        resposta = self._post(
            {"item_pca": 1, "exercicio": 2025, "numero_sei": self.NUMERO_SO_DIGITOS}
        )
        self.assertEqual(resposta.status_code, 200)
        corpo = json.loads(resposta.content)
        self.assertFalse(corpo["criado"])
        self.assertEqual(processo.numeros_sei.count(), 1)

    def test_mesmo_numero_em_outro_item_nao_gera_erro(self):
        self._demandante()
        self._criar_processo(1, numero_sei=self.NUMERO_FORMATADO)
        self._criar_processo(2)
        resposta = self._post(
            {"item_pca": 2, "exercicio": 2025, "numero_sei": self.NUMERO_FORMATADO}
        )
        self.assertEqual(resposta.status_code, 201)
        self.assertTrue(json.loads(resposta.content)["criado"])


# --- GET/PUT /api/sei/ficha (V-5) -------------------------


class TestFichaView(ApiSeiBase):
    def _demandante(self):
        self.usuario.groups.add(Group.objects.get(name="demandante"))

    def _get(self, params, token=None):
        return self.client.get("/api/sei/ficha", params, **self._auth(token))

    def _put(self, corpo, token=None):
        return self.client.generic(
            "PUT",
            "/api/sei/ficha",
            data=json.dumps(corpo),
            content_type="application/json",
            **self._auth(token),
        )

    def test_get_sem_ficha_devolve_versao_0(self):
        self._criar_processo(1)
        resposta = self._get({"item": 1, "exercicio": 2025})
        self.assertEqual(resposta.status_code, 200)
        corpo = json.loads(resposta.content)
        self.assertEqual(corpo, {
            "item_pca": 1,
            "exercicio": 2025,
            "versao": 0,
            "dados": {},
            "atualizado_em": None,
            "atualizado_por": None,
        })

    def test_get_item_inexistente_404(self):
        resposta = self._get({"item": 999, "exercicio": 2025})
        self.assertEqual(resposta.status_code, 404)
        self.assertEqual(json.loads(resposta.content)["erro"], "item_inexistente")

    def test_get_sem_parametro_reconhecido_400(self):
        resposta = self._get({})
        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(json.loads(resposta.content)["erro"], "corpo_invalido")

    def test_get_por_sei_unico_item(self):
        self._criar_processo(1, numero_sei="90796110000019.000030/2025-74")
        resposta = self._get({"sei": "90796110000019000030202574"})
        self.assertEqual(resposta.status_code, 200)
        corpo = json.loads(resposta.content)
        self.assertEqual(corpo["item_pca"], 1)

    def test_get_por_sei_sem_vinculo_404(self):
        resposta = self._get({"sei": "00000000000000000000"})
        self.assertEqual(resposta.status_code, 404)
        self.assertEqual(json.loads(resposta.content)["erro"], "item_inexistente")

    def test_get_por_sei_em_dois_itens_409(self):
        numero = "90796110000019.000030/2025-74"
        self._criar_processo(1, numero_sei=numero)
        self._criar_processo(2, numero_sei=numero)
        resposta = self._get({"sei": numero})
        self.assertEqual(resposta.status_code, 409)
        corpo = json.loads(resposta.content)
        self.assertEqual(corpo["erro"], "sei_em_varios_itens")
        self.assertEqual(
            [i["item_pca"] for i in corpo["itens"]], [1, 2]
        )

    def test_get_funciona_para_visualizador(self):
        self._criar_processo(1)
        resposta = self._get({"item": 1, "exercicio": 2025})
        self.assertEqual(resposta.status_code, 200)

    def test_put_visualizador_devolve_403_sem_tocar_banco(self):
        self._criar_processo(1)
        resposta = self._put(
            {"item_pca": 1, "exercicio": 2025, "versao": 0, "dados": {"x": 1}}
        )
        self.assertEqual(resposta.status_code, 403)
        self.assertEqual(json.loads(resposta.content)["erro"], "sem_permissao")
        self.assertFalse(FichaContratacao.objects.exists())

    def test_put_cria_com_versao_0(self):
        self._demandante()
        self._criar_processo(1)
        resposta = self._put(
            {"item_pca": 1, "exercicio": 2025, "versao": 0, "dados": {"situacao": "autuado"}}
        )
        self.assertEqual(resposta.status_code, 200)
        corpo = json.loads(resposta.content)
        self.assertEqual(corpo["versao"], 1)
        self.assertEqual(corpo["dados"], {"situacao": "autuado"})

        resposta_get = self._get({"item": 1, "exercicio": 2025})
        corpo_get = json.loads(resposta_get.content)
        self.assertEqual(corpo_get["versao"], 1)
        self.assertEqual(corpo_get["dados"], {"situacao": "autuado"})

    def test_put_seguinte_com_versao_atual_grava_versao_2_e_history_user_e_do_token(self):
        self._demandante()
        self._criar_processo(1)
        self._put({"item_pca": 1, "exercicio": 2025, "versao": 0, "dados": {"a": 1}})

        resposta = self._put(
            {"item_pca": 1, "exercicio": 2025, "versao": 1, "dados": {"a": 2}}
        )
        self.assertEqual(resposta.status_code, 200)
        corpo = json.loads(resposta.content)
        self.assertEqual(corpo["versao"], 2)

        ficha = FichaContratacao.objects.get(processo__item_pca=1)
        self.assertEqual(ficha.history.first().history_user, self.usuario)

    def test_put_com_versao_divergente_devolve_409_sem_sobrescrever(self):
        self._demandante()
        self._criar_processo(1)
        self._put({"item_pca": 1, "exercicio": 2025, "versao": 0, "dados": {"a": 1}})
        self._put({"item_pca": 1, "exercicio": 2025, "versao": 1, "dados": {"a": 2}})

        resposta = self._put(
            {"item_pca": 1, "exercicio": 2025, "versao": 1, "dados": {"a": 3}}
        )
        self.assertEqual(resposta.status_code, 409)
        corpo = json.loads(resposta.content)
        self.assertEqual(corpo["erro"], "versao_desatualizada")
        self.assertEqual(corpo["ficha"]["versao"], 2)
        self.assertEqual(corpo["ficha"]["dados"], {"a": 2})

        ficha = FichaContratacao.objects.get(processo__item_pca=1)
        self.assertEqual(ficha.versao, 2)
        self.assertEqual(ficha.dados, {"a": 2})

    def test_put_dados_nao_e_objeto_json_devolve_400(self):
        self._demandante()
        self._criar_processo(1)
        resposta = self._put(
            {"item_pca": 1, "exercicio": 2025, "versao": 0, "dados": ["não", "é", "objeto"]}
        )
        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(json.loads(resposta.content)["erro"], "corpo_invalido")

    def test_put_item_inexistente_devolve_404(self):
        self._demandante()
        resposta = self._put(
            {"item_pca": 999, "exercicio": 2025, "versao": 0, "dados": {}}
        )
        self.assertEqual(resposta.status_code, 404)
        self.assertEqual(json.loads(resposta.content)["erro"], "item_inexistente")

    @override_settings(API_FICHA_MAX_KB=1)
    def test_put_dados_grande_demais_devolve_413_sem_gravar(self):
        self._demandante()
        self._criar_processo(1)
        dados_grandes = {"texto": "x" * 2000}
        resposta = self._put(
            {"item_pca": 1, "exercicio": 2025, "versao": 0, "dados": dados_grandes}
        )
        self.assertEqual(resposta.status_code, 413)
        self.assertEqual(json.loads(resposta.content)["erro"], "corpo_grande_demais")
        self.assertFalse(FichaContratacao.objects.exists())
