"""Aparência por usuário (casca Tabler): o painel grava claro/escuro, cor, base e cantos na conta."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import PreferenciaAparencia
from core.tests.test_casca_tabler import CASCA_TABLER


class AparenciaTest(TestCase):
    def setUp(self):
        self.usuario = get_user_model().objects.create_user(email="cor@pca.local", password="senha-segura-123")
        self.client.force_login(self.usuario)
        self.url = reverse("core:aparencia")

    def test_padrao_sem_escolha(self):
        self.assertEqual(PreferenciaAparencia.valores_de(self.usuario), PreferenciaAparencia.PADRAO)

    def test_grava_e_devolve_json(self):
        resposta = self.client.post(
            self.url, {"tema": "escuro", "cor": "green", "base": "stone", "cantos": "2"}, HTTP_ACCEPT="application/json"
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json(), {"tema": "escuro", "cor": "green", "base": "stone", "cantos": "2"})
        self.assertEqual(PreferenciaAparencia.valores_de(self.usuario)["cor"], "green")

    def test_valor_fora_da_lista_e_ignorado(self):
        self.client.post(self.url, {"cor": "green"}, HTTP_ACCEPT="application/json")
        resposta = self.client.post(self.url, {"cor": "#ff0000", "base": "x"}, HTTP_ACCEPT="application/json")
        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(PreferenciaAparencia.valores_de(self.usuario)["cor"], "green")

    def test_envio_sem_js_volta_para_a_pagina(self):
        resposta = self.client.post(self.url, {"cor": "red"}, HTTP_REFERER="http://testserver/tabela")
        self.assertRedirects(resposta, "http://testserver/tabela", fetch_redirect_response=False)
        resposta = self.client.post(self.url, {"cor": "red"}, HTTP_REFERER="https://outro-site.com/")
        self.assertRedirects(resposta, reverse("core:inicio"), fetch_redirect_response=False)

    def test_get_nao_permitido(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_anonimo_nao_grava(self):
        self.client.logout()
        resposta = self.client.post(self.url, {"cor": "red"})
        self.assertNotEqual(resposta.status_code, 200)
        self.assertFalse(PreferenciaAparencia.objects.exists())

    @CASCA_TABLER
    def test_pagina_abre_com_a_aparencia_da_conta(self):
        PreferenciaAparencia.objects.create(usuario=self.usuario, tema="escuro", cor="purple", base="zinc", cantos="0")
        html = self.client.get(reverse("core:sobre")).content.decode()
        self.assertIn('"cor": "purple"', html)
        self.assertIn('"tema": "escuro"', html)
        self.assertIn("tabler-themes.min.css", html)
        self.assertIn('id="painel-aparencia"', html)
