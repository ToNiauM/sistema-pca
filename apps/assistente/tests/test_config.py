"""Checks E001-E006, `criar_cliente()` sem chave, limite de
`IA_CONVERSA_TTL_S` (A20). Nunca abre arquivo, nunca acessa
rede. E005/E006 e os provedores de `criar_cliente()` são da quick
(assistente agnóstico de provedor)."""

import sys
import tempfile
import types
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from apps.assistente import checks
from apps.assistente import cliente as cliente_mod
from apps.assistente.cliente import criar_cliente


class TestChecksAssistente(SimpleTestCase):
    def test_sem_chave_nao_gera_erro(self):
        with override_settings(IA_API_KEY=""):
            self.assertEqual(checks.verificar_configuracao(None), [])

    def test_e001_limite_nao_positivo(self):
        with override_settings(IA_TIMEOUT_S=0):
            erros = checks.verificar_configuracao(None)
        self.assertTrue(any(e.id == "assistente.E001" for e in erros))

    def test_e002_caminhos_iguais_entre_si(self):
        with override_settings(IA_ESTADO_PATH=settings.IA_INDICE_PATH):
            erros = checks.verificar_configuracao(None)
        self.assertTrue(any(e.id == "assistente.E002" for e in erros))

    def test_e002_caminho_igual_ao_banco(self):
        banco = settings.DATABASES["default"]["NAME"]
        with override_settings(IA_ESTADO_PATH=banco):
            erros = checks.verificar_configuracao(None)
        self.assertTrue(any(e.id == "assistente.E002" for e in erros))

    def test_e003_provedor_invalido(self):
        with override_settings(IA_PROVEDOR="azure"):
            erros = checks.verificar_configuracao(None)
        self.assertTrue(any(e.id == "assistente.E003" for e in erros))

    def test_e003_anthropic_e_valido(self):
        with override_settings(IA_PROVEDOR="anthropic"):
            erros = checks.verificar_configuracao(None)
        self.assertFalse(any(e.id == "assistente.E003" for e in erros))

    def test_e004_chave_sem_modelo_embed(self):
        with override_settings(IA_API_KEY="chave", IA_MODELO_EMBED=""):
            erros = checks.verificar_configuracao(None)
        self.assertTrue(any(e.id == "assistente.E004" for e in erros))

    def test_e005_provedor_embed_invalido(self):
        with override_settings(IA_PROVEDOR_EMBED="anthropic"):
            erros = checks.verificar_configuracao(None)
        self.assertTrue(any(e.id == "assistente.E005" for e in erros))

    def test_e005_openai_e_valido(self):
        with override_settings(IA_PROVEDOR_EMBED="openai"):
            erros = checks.verificar_configuracao(None)
        self.assertFalse(any(e.id == "assistente.E005" for e in erros))

    def test_e006_chave_embed_vazia_com_provedores_diferentes(self):
        with override_settings(
            IA_API_KEY="chave",
            IA_PROVEDOR="anthropic",
            IA_PROVEDOR_EMBED="openai",
            IA_API_KEY_EMBED="",
        ):
            erros = checks.verificar_configuracao(None)
        self.assertTrue(any(e.id == "assistente.E006" for e in erros))

    def test_e006_ok_quando_chave_embed_preenchida(self):
        with override_settings(
            IA_API_KEY="chave",
            IA_PROVEDOR="anthropic",
            IA_PROVEDOR_EMBED="openai",
            IA_API_KEY_EMBED="outra-chave",
        ):
            erros = checks.verificar_configuracao(None)
        self.assertFalse(any(e.id == "assistente.E006" for e in erros))

    def test_e006_ok_quando_mesmo_provedor(self):
        with override_settings(
            IA_API_KEY="chave",
            IA_PROVEDOR="openai",
            IA_PROVEDOR_EMBED="openai",
            IA_API_KEY_EMBED="",
        ):
            erros = checks.verificar_configuracao(None)
        self.assertFalse(any(e.id == "assistente.E006" for e in erros))

    def test_conversa_ttl_nunca_maior_que_sessao(self):
        # A settings já aplica min(IA_CONVERSA_TTL_S, SESSION_COOKIE_AGE)
        # na leitura do .env — aqui provamos a invariante diretamente.
        self.assertLessEqual(settings.IA_CONVERSA_TTL_S, settings.SESSION_COOKIE_AGE)

    def test_criar_cliente_sem_chave_devolve_none(self):
        with override_settings(IA_API_KEY=""):
            self.assertIsNone(criar_cliente())

    def test_check_management_command_passa_sem_chave(self):
        from io import StringIO

        from django.core.management import call_command

        with override_settings(IA_API_KEY=""):
            saida = StringIO()
            call_command("check", stdout=saida, stderr=saida)


class _ClienteOpenAIFake:
    """Dublê de `ClienteOpenAI` só para capturar os kwargs do construtor —
    usado onde o teste precisa inspecionar `api_key` sem exigir rede nem o
    SDK `openai` de verdade."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs


def _modulo_anthropic_minimo():
    modulo = types.ModuleType("anthropic")

    class _Anthropic:
        def __init__(self, **kwargs):
            pass

    modulo.Anthropic = _Anthropic
    return modulo


class TestCriarClientePorProvedor(SimpleTestCase):
    """`criar_cliente()` escolhe o adaptador
    por `IA_PROVEDOR`, sem exigir o pacote `anthropic` instalado (SDK
    mockado via `sys.modules`)."""

    def test_sem_chave_devolve_none(self):
        with override_settings(IA_API_KEY=""):
            self.assertIsNone(criar_cliente())

    def test_openai_por_padrao_devolve_clienteopenai(self):
        with override_settings(IA_API_KEY="chave", IA_PROVEDOR="openai"):
            cliente_obj = criar_cliente()
        self.assertIsInstance(cliente_obj, cliente_mod.ClienteOpenAI)

    def test_anthropic_usa_chave_embed_propria_quando_preenchida(self):
        with (
            mock.patch.dict(sys.modules, {"anthropic": _modulo_anthropic_minimo()}),
            mock.patch("apps.assistente.cliente.ClienteOpenAI", _ClienteOpenAIFake),
            override_settings(
                IA_API_KEY="chave", IA_PROVEDOR="anthropic", IA_API_KEY_EMBED="chave-embed",
            ),
        ):
            cliente_obj = criar_cliente()
        self.assertIsInstance(cliente_obj, cliente_mod.ClienteAnthropic)
        self.assertEqual(cliente_obj._cliente_embed.kwargs["api_key"], "chave-embed")

    def test_anthropic_reaproveita_ia_api_key_quando_embed_vazia(self):
        with (
            mock.patch.dict(sys.modules, {"anthropic": _modulo_anthropic_minimo()}),
            mock.patch("apps.assistente.cliente.ClienteOpenAI", _ClienteOpenAIFake),
            override_settings(
                IA_API_KEY="chave", IA_PROVEDOR="anthropic", IA_API_KEY_EMBED="",
            ),
        ):
            cliente_obj = criar_cliente()
        self.assertIsInstance(cliente_obj, cliente_mod.ClienteAnthropic)
        self.assertEqual(cliente_obj._cliente_embed.kwargs["api_key"], "chave")
