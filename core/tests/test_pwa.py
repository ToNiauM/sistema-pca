import struct
from pathlib import Path

from django.conf import settings
from django.templatetags.static import static
from django.test import Client, TestCase


class ManifestPWATests(TestCase):
    """manifest.json instalável, resolvido via static()."""

    def test_manifest_returns_200_with_manifest_content_type(self):
        cliente = Client()  # sem force_login — a rota é pública

        resposta = cliente.get("/manifest.json")

        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(
            resposta["Content-Type"].startswith("application/manifest+json")
        )

    def test_manifest_icons_src_matches_resolved_static_urls(self):
        cliente = Client()

        resposta = cliente.get("/manifest.json")
        corpo = resposta.json()

        # Sem ano no manifest: ele é cacheado no dispositivo e sobreviveria
        # à virada de exercício.
        self.assertEqual(corpo["name"], "PCA — Plano de Contratações Anual")
        self.assertEqual(corpo["short_name"], "PCA")
        self.assertEqual(corpo["start_url"], "/inicio")
        self.assertEqual(corpo["scope"], "/")
        self.assertEqual(corpo["display"], "standalone")

        srcs = [icone["src"] for icone in corpo["icons"]]
        self.assertIn(static("img/icon-192.png"), srcs)
        self.assertIn(static("img/icon-512.png"), srcs)
        self.assertIn(static("img/icon-512-maskable.png"), srcs)


class ServiceWorkerPWATests(TestCase):
    """sw.js servido fora de /static/, com Service-Worker-Allowed."""

    def test_service_worker_returns_200_with_correct_content_type_and_scope_header(
        self,
    ):
        cliente = Client()  # sem force_login — a rota é pública

        resposta = cliente.get("/sw.js")

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta["Content-Type"], "application/javascript")
        self.assertEqual(resposta["Service-Worker-Allowed"], "/")

    def test_service_worker_body_contains_install_skipwaiting_and_static_scope(self):
        cliente = Client()

        resposta = cliente.get("/sw.js")
        corpo = resposta.content.decode()

        self.assertIn("install", corpo)
        self.assertIn("skipWaiting", corpo)
        self.assertIn("/static/", corpo)
        self.assertIn(static("offline.html"), corpo)


class IconesPWATests(TestCase):
    """Os 3 ícones saem de `core/static/img/logo-neutro.png`, recortados
    em quadrado (`ops/gerar_icones_pwa.py`, roda no host). Sem depender de
    Pillow (que não está no container `web`): lê os 24 primeiros bytes do PNG
    e decodifica largura/altura do chunk `IHDR` na mão — o cabeçalho `IHDR` é
    sempre os bytes 16–24 de um PNG válido (assinatura de 8 bytes + comprimento
    de 4 + tipo de chunk de 4 + largura de 4 + altura de 4).
    """

    DIRETORIO_IMG = Path(settings.BASE_DIR) / "core" / "static" / "img"

    def _dimensoes(self, nome_arquivo):
        caminho = self.DIRETORIO_IMG / nome_arquivo
        with caminho.open("rb") as arquivo:
            dados = arquivo.read(24)
        return struct.unpack(">II", dados[16:24])

    def test_icon_192_e_quadrado_de_192(self):
        self.assertEqual(self._dimensoes("icon-192.png"), (192, 192))

    def test_icon_512_e_quadrado_de_512(self):
        self.assertEqual(self._dimensoes("icon-512.png"), (512, 512))

    def test_icon_512_maskable_e_quadrado_de_512(self):
        self.assertEqual(self._dimensoes("icon-512-maskable.png"), (512, 512))


class OfflineFallbackPWATests(TestCase):
    """Página de fallback offline, servida sob /static/."""

    def test_offline_html_returns_200_with_expected_copy(self):
        cliente = Client()  # sem force_login — a rota é pública

        resposta = cliente.get("/static/offline.html")

        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta["Content-Type"].startswith("text/html"))
        corpo = b"".join(resposta.streaming_content).decode()
        self.assertIn("Sem conexão", corpo)
        self.assertIn("Tentar novamente", corpo)
