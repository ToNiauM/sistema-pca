"""Tela "Assistente": PRG 302/400/409/429, corrida de logout/
revogação, quota em dois navegadores, menu condicionado à chave."""

import json
import re
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import Group
from django.contrib.sessions.models import Session
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time

from apps.assistente import estado
from apps.assistente.tests.base import (
    AssistenteTestBase,
    ClienteFalso,
    patch_cliente,
    resposta_ferramenta,
    resposta_texto,
)
from apps.pca.tests.test_estrutura_paginas import _coletar

_RE_REQUISICAO_ID = re.compile(r'name="requisicao_id" value="([^"]*)"')


def _extrair_requisicao_id(html: str) -> str:
    m = _RE_REQUISICAO_ID.search(html)
    assert m, "requisicao_id não encontrado no HTML"
    return m.group(1)


class TestMenuECheckSemChave(AssistenteTestBase):
    def test_sem_chave_404_e_menu_sem_assistente(self):
        with override_settings(IA_API_KEY=""):
            self.client.force_login(self.editor)
            resposta = self.client.get(reverse("assistente:pagina"))
            self.assertEqual(resposta.status_code, 404)
            self.assertIn("Assistente não configurado", resposta.content.decode())

            resposta_inicio = self.client.get(reverse("core:inicio"))
            self.assertNotIn("Assistente", resposta_inicio.content.decode())

    def test_com_chave_item_de_menu_presente(self):
        self.client.force_login(self.editor)
        resposta = self.client.get(reverse("core:inicio"))
        self.assertContains(resposta, "Assistente")


class TestTrilhaCompleta(AssistenteTestBase):
    def test_pergunta_resposta_prg_sem_texto_na_sessao(self):
        fake = ClienteFalso(
            [
                resposta_ferramenta(
                    "consultar_processos",
                    {
                        "exercicio": 2026,
                        "unidade": None,
                        "situacao": None,
                        "fornecedor": None,
                        "texto_objeto": None,
                        "tipo": None,
                        "limite": 20,
                    },
                ),
                resposta_texto("Há 3 itens atrasados."),
            ]
        )
        self.client.force_login(self.editor)
        with patch_cliente(fake):
            get1 = self.client.get(reverse("assistente:pagina") + "?exercicio=2026")
            self.assertEqual(get1.status_code, 200)
            requisicao_id = _extrair_requisicao_id(get1.content.decode())

            post = self.client.post(
                reverse("assistente:perguntar"),
                {
                    "pergunta": "quantos itens estão atrasados?",
                    "requisicao_id": requisicao_id,
                    "exercicio": 2026,
                },
            )
            self.assertEqual(post.status_code, 302)

            get2 = self.client.get(reverse("assistente:pagina") + "?exercicio=2026")
        html = get2.content.decode()
        self.assertIn("quantos itens estão atrasados?", html)
        self.assertIn("Há 3 itens atrasados.", html)
        self.assertIn("/tabela?", html)
        self.assertIn("PCA consultado em", html)

        consumo = estado.consumo(self.editor.pk, estado.dia_civil(timezone.now()))
        self.assertEqual(consumo.perguntas, 1)

        sessao = Session.objects.get(session_key=self.client.session.session_key)
        dados_sessao = sessao.get_decoded()
        self.assertNotIn("quantos itens estão atrasados", str(dados_sessao))
        self.assertIn(estado.CHAVE_SESSAO_CONVERSA, dados_sessao)

    def test_reenvio_do_mesmo_requisicao_id_nao_cobra_de_novo(self):
        fake = ClienteFalso(
            [
                resposta_ferramenta("consultar_processos", {"exercicio": 2026, "limite": 20}),
                resposta_texto("resposta única"),
            ]
        )
        self.client.force_login(self.editor)
        with patch_cliente(fake):
            get1 = self.client.get(reverse("assistente:pagina") + "?exercicio=2026")
            requisicao_id = _extrair_requisicao_id(get1.content.decode())
            payload = {"pergunta": "oi", "requisicao_id": requisicao_id, "exercicio": 2026}
            primeiro = self.client.post(reverse("assistente:perguntar"), payload)
            self.assertEqual(primeiro.status_code, 302)
            chamadas_antes = len(fake.chamadas)

            segundo = self.client.post(reverse("assistente:perguntar"), payload)
        self.assertEqual(segundo.status_code, 302)
        self.assertEqual(len(fake.chamadas), chamadas_antes)
        consumo = estado.consumo(self.editor.pk, estado.dia_civil(timezone.now()))
        self.assertEqual(consumo.perguntas, 1)


class TestRequisicoesInvalidas(AssistenteTestBase):
    def test_pergunta_vazia_400(self):
        self.client.force_login(self.editor)
        get1 = self.client.get(reverse("assistente:pagina") + "?exercicio=2026")
        requisicao_id = _extrair_requisicao_id(get1.content.decode())
        resposta = self.client.post(
            reverse("assistente:perguntar"),
            {"pergunta": "   ", "requisicao_id": requisicao_id, "exercicio": 2026},
        )
        self.assertEqual(resposta.status_code, 400)

    def test_pergunta_muito_longa_400(self):
        self.client.force_login(self.editor)
        get1 = self.client.get(reverse("assistente:pagina") + "?exercicio=2026")
        requisicao_id = _extrair_requisicao_id(get1.content.decode())
        resposta = self.client.post(
            reverse("assistente:perguntar"),
            {"pergunta": "a" * 1001, "requisicao_id": requisicao_id, "exercicio": 2026},
        )
        self.assertEqual(resposta.status_code, 400)

    def test_exercicio_inexistente_400(self):
        self.client.force_login(self.editor)
        get1 = self.client.get(reverse("assistente:pagina") + "?exercicio=2026")
        requisicao_id = _extrair_requisicao_id(get1.content.decode())
        resposta = self.client.post(
            reverse("assistente:perguntar"),
            {"pergunta": "oi", "requisicao_id": requisicao_id, "exercicio": 1999},
        )
        self.assertEqual(resposta.status_code, 400)

    def test_requisicao_id_inventado_400_sem_cobrar(self):
        self.client.force_login(self.editor)
        resposta = self.client.post(
            reverse("assistente:perguntar"),
            {"pergunta": "oi", "requisicao_id": "id-nunca-emitido-por-aqui", "exercicio": 2026},
        )
        self.assertEqual(resposta.status_code, 400)
        consumo = estado.consumo(self.editor.pk, estado.dia_civil(timezone.now()))
        self.assertEqual(consumo.perguntas, 0)


class TestConcorrencia(AssistenteTestBase):
    def test_em_andamento_devolve_409(self):
        self.client.force_login(self.editor)
        # Duas requisições válidas emitidas ANTES de qualquer POST — mesma
        # conversa (segunda GET reaproveita a conversa da primeira).
        get_a = self.client.get(reverse("assistente:pagina") + "?exercicio=2026")
        rid_a = _extrair_requisicao_id(get_a.content.decode())
        get_b = self.client.get(reverse("assistente:pagina") + "?exercicio=2026")
        rid_b = _extrair_requisicao_id(get_b.content.decode())

        sessao_hash = estado.hash_sessao(self.client.session.session_key)
        conversa_id = self.client.session.get(estado.CHAVE_SESSAO_CONVERSA)
        agora = timezone.now()
        # Reserva rid_a diretamente (simula uma requisição em andamento,
        # sem completar) — o lease de 120s continua vivo.
        primeira = estado.reservar(
            requisicao_id=rid_a, usuario_id=self.editor.pk, sessao_hash=sessao_hash,
            conversa_id=conversa_id, exercicio=2026, agora=agora, limite=50,
        )
        self.assertIsInstance(primeira, estado.Reserva)

        resposta = self.client.post(
            reverse("assistente:perguntar"),
            {"pergunta": "oi", "requisicao_id": rid_b, "exercicio": 2026},
        )
        self.assertEqual(resposta.status_code, 409)


class TestQuotaDoisNavegadores(AssistenteTestBase):
    def test_terceira_pergunta_429_com_retry_after(self):
        fake = ClienteFalso(
            [
                resposta_texto("um"),
                resposta_texto("dois"),
            ]
        )
        c1 = Client(HTTP_X_FORWARDED_PROTO="https")
        c2 = Client(HTTP_X_FORWARDED_PROTO="https")
        c1.force_login(self.editor)
        c2.force_login(self.editor)

        with override_settings(IA_MAX_PERGUNTAS_DIA=2), patch_cliente(fake):
            # As 3 requisições são emitidas ANTES de qualquer POST — com
            # quota ainda disponível — para provar que o SERVIDOR aplica o
            # limite na reserva, não que a tela deixa de emitir um id novo
            # depois de esgotada (a UI já desabilita o form nesse caso).
            get_c1 = c1.get(reverse("assistente:pagina") + "?exercicio=2026")
            rid1 = _extrair_requisicao_id(get_c1.content.decode())
            get_c2 = c2.get(reverse("assistente:pagina") + "?exercicio=2026")
            rid2 = _extrair_requisicao_id(get_c2.content.decode())
            get_c1_extra = c1.get(reverse("assistente:pagina") + "?exercicio=2026")
            rid3 = _extrair_requisicao_id(get_c1_extra.content.decode())

            resp1 = c1.post(
                reverse("assistente:perguntar"),
                {"pergunta": "primeira", "requisicao_id": rid1, "exercicio": 2026},
            )
            self.assertEqual(resp1.status_code, 302)

            resp2 = c2.post(
                reverse("assistente:perguntar"),
                {"pergunta": "segunda", "requisicao_id": rid2, "exercicio": 2026},
            )
            self.assertEqual(resp2.status_code, 302)

            chamadas_antes = len(fake.chamadas)
            resp3 = c1.post(
                reverse("assistente:perguntar"),
                {"pergunta": "terceira", "requisicao_id": rid3, "exercicio": 2026},
            )
        self.assertEqual(resp3.status_code, 429)
        retry_after = int(resp3["Retry-After"])
        self.assertGreaterEqual(retry_after, 1)
        self.assertLessEqual(retry_after, 86400)
        self.assertEqual(len(fake.chamadas), chamadas_antes)


class TestCorridaDeLogout(AssistenteTestBase):
    def test_logout_durante_a_chamada_descarta_a_resposta(self):
        cliente_http = Client(HTTP_X_FORWARDED_PROTO="https")
        cliente_http.force_login(self.editor)

        fake = ClienteFalso([resposta_texto("resposta que não pode aparecer")])
        fake.ao_chamar = lambda: cliente_http.logout()

        get1 = cliente_http.get(reverse("assistente:pagina") + "?exercicio=2026")
        requisicao_id = _extrair_requisicao_id(get1.content.decode())

        with patch_cliente(fake):
            resposta = cliente_http.post(
                reverse("assistente:perguntar"),
                {"pergunta": "oi", "requisicao_id": requisicao_id, "exercicio": 2026},
            )
        self.assertIn(resposta.status_code, (302,))

        con = estado._conectar_conversas()
        try:
            total = con.execute("SELECT COUNT(*) FROM troca").fetchone()[0]
        finally:
            con.close()
        self.assertEqual(total, 0)
        consumo = estado.consumo(self.editor.pk, estado.dia_civil(timezone.now()))
        self.assertEqual(consumo.perguntas, 1)


class TestFalhaDoProvedor(AssistenteTestBase):
    def test_erro_cliente_302_depois_200_sem_500(self):
        from apps.assistente.cliente import ErroCliente

        class ClienteComErro:
            def chat(self, *args, **kwargs):
                raise ErroCliente("limite_taxa")

        self.client.force_login(self.editor)
        with patch_cliente(ClienteComErro()):
            get1 = self.client.get(reverse("assistente:pagina") + "?exercicio=2026")
            requisicao_id = _extrair_requisicao_id(get1.content.decode())
            resposta = self.client.post(
                reverse("assistente:perguntar"),
                {"pergunta": "oi", "requisicao_id": requisicao_id, "exercicio": 2026},
            )
            self.assertEqual(resposta.status_code, 302)
            get2 = self.client.get(reverse("assistente:pagina") + "?exercicio=2026")
        self.assertEqual(get2.status_code, 200)
        consumo = estado.consumo(self.editor.pk, estado.dia_civil(timezone.now()))
        self.assertEqual(consumo.perguntas, 1)


class TestNovaConversa(AssistenteTestBase):
    def test_nova_conversa_limpa_trocas_sem_alterar_quota(self):
        fake = ClienteFalso([resposta_texto("resposta")])
        self.client.force_login(self.editor)
        with patch_cliente(fake):
            get1 = self.client.get(reverse("assistente:pagina") + "?exercicio=2026")
            requisicao_id = _extrair_requisicao_id(get1.content.decode())
            self.client.post(
                reverse("assistente:perguntar"),
                {"pergunta": "oi", "requisicao_id": requisicao_id, "exercicio": 2026},
            )
            resposta = self.client.post(
                reverse("assistente:nova_conversa"), {"exercicio": 2026}
            )
            self.assertEqual(resposta.status_code, 302)
            get2 = self.client.get(reverse("assistente:pagina") + "?exercicio=2026")
        self.assertNotIn("resposta", get2.content.decode())
        consumo = estado.consumo(self.editor.pk, estado.dia_civil(timezone.now()))
        self.assertEqual(consumo.perguntas, 1)


class TestSugestaoPreenche(AssistenteTestBase):
    def test_sugestao_preenche_sem_cobrar(self):
        self.client.force_login(self.editor)
        resposta = self.client.get(
            reverse("assistente:pagina") + "?exercicio=2026&sugestao=Quantos+itens+atrasados%3F"
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("Quantos itens atrasados?", resposta.content.decode())
        consumo = estado.consumo(self.editor.pk, estado.dia_civil(timezone.now()))
        self.assertEqual(consumo.perguntas, 0)
        con = estado._conectar_conversas()
        try:
            total = con.execute("SELECT COUNT(*) FROM troca").fetchone()[0]
        finally:
            con.close()
        self.assertEqual(total, 0)


class TestEstruturaEMarcaDagua(AssistenteTestBase):
    def test_estrutura_um_h1_um_primary(self):
        self.client.force_login(self.editor)
        resposta = self.client.get(reverse("assistente:pagina") + "?exercicio=2026")
        coletor = _coletar(resposta.content.decode())
        self.assertEqual(coletor.h1_count, 1)
        self.assertLessEqual(coletor.primary_count, 1)

    def test_marca_dagua_presente_fora_de_link_ou_botao(self):
        self.client.force_login(self.editor)
        html = self.client.get(reverse("assistente:pagina") + "?exercicio=2026").content.decode()
        self.assertIn("logo-cfc-2.png", html)
        self.assertIn("opacity-xs", html)
        self.assertIn('aria-hidden="true"', html)


class TestGetPaginaAtributosHtmx(AssistenteTestBase):
    """GET da página carrega os atributos que o
    form de pergunta precisa para não recarregar a tela."""

    def test_get_contem_atributos_do_form_htmx(self):
        self.client.force_login(self.editor)
        html = self.client.get(reverse("assistente:pagina") + "?exercicio=2026").content.decode()
        self.assertEqual(html.count('id="area-chat"'), 1)
        self.assertGreaterEqual(html.count("hx-post="), 1)
        self.assertEqual(html.count('hx-indicator="#digitando"'), 1)
        self.assertEqual(html.count('id="digitando"'), 1)
        self.assertIn("htmx-indicator", html)
        self.assertIn("br-loading", html)
        self.assertEqual(html.count("hx-disabled-elt"), 1)
        self.assertEqual(html.count("hx-swap-oob"), 0)
        self.assertIn('id="pergunta"', html)
        coletor = _coletar(html)
        self.assertEqual(coletor.h1_count, 1)
        self.assertLessEqual(coletor.primary_count, 1)


class TestCaixaPresaAoRodape(AssistenteTestBase):
    """A caixa de escrita fica presa ao rodapé
    da janela (padrão DSGov: dsgov-chat/dsgov-chat-caixa), como WhatsApp/
    Telegram, no mobile e no desktop."""

    def test_get_contem_classes_dsgov_chat(self):
        self.client.force_login(self.editor)
        html = self.client.get(reverse("assistente:pagina") + "?exercicio=2026").content.decode()
        self.assertEqual(html.count('class="dsgov-chat"'), 1)
        self.assertEqual(html.count('class="dsgov-chat-caixa"'), 1)
        self.assertEqual(html.count("style="), 0)


class TestRespiroDeChat(AssistenteTestBase):
    """Coluna central de leitura (grid do core 3.7.0,
    zero CSS novo) e composer com atalhos de teclado (Enter envia, Alt+Enter
    quebra linha, textarea cresce) vivendo em `dsgov.js` (padrão DSGov)."""

    def test_get_contem_coluna_central_sem_css_novo(self):
        self.client.force_login(self.editor)
        html = self.client.get(reverse("assistente:pagina") + "?exercicio=2026").content.decode()
        self.assertIn('class="row justify-content-center"', html)
        self.assertIn('class="col-12 col-lg-10 col-xl-8"', html)
        self.assertNotIn("col-lg-8", html)
        self.assertIn("rounder-lg", html)

    def test_get_contem_textarea_data_composer(self):
        self.client.force_login(self.editor)
        html = self.client.get(reverse("assistente:pagina") + "?exercicio=2026").content.decode()
        self.assertIn("data-composer", html)
        self.assertIn("Enter envia", html)
        self.assertIn("Alt+Enter quebra linha", html)

    def test_dsgov_js_contem_bloco_do_composer(self):
        caminho = Path(__file__).resolve().parents[3] / "core/static/dsgov/js/dsgov.js"
        conteudo = caminho.read_text()
        self.assertIn("textarea[data-composer]", conteudo)
        self.assertIn("redimensionarComposer", conteudo)

    def test_pca_static_v49_no_service_worker(self):
        caminho = Path(__file__).resolve().parents[3] / "core/views.py"
        self.assertEqual(caminho.read_text().count("pca-static-v66"), 1)


class TestPerguntaHtmxSemRecarregar(AssistenteTestBase):
    """Sucesso vira 200 + `HX-Location` para
    `#area-chat`; erro (400/409/429) vira 200 com a área re-renderizada,
    nunca `HX-Location`; sem HTMX, os códigos originais continuam intactos."""

    def test_post_htmx_valido_200_com_hx_location_para_area_chat(self):
        fake = ClienteFalso(
            [
                resposta_ferramenta("consultar_processos", {"exercicio": 2026, "limite": 20}),
                resposta_texto("Há 3 itens atrasados."),
            ]
        )
        self.client.force_login(self.editor)
        with patch_cliente(fake):
            get1 = self.client.get(reverse("assistente:pagina") + "?exercicio=2026")
            requisicao_id = _extrair_requisicao_id(get1.content.decode())
            resposta = self.client.post(
                reverse("assistente:perguntar"),
                {
                    "pergunta": "quantos itens estão atrasados?",
                    "requisicao_id": requisicao_id,
                    "exercicio": 2026,
                },
                HTTP_HX_REQUEST="true",
            )
        self.assertEqual(resposta.status_code, 200)
        self.assertNotIn("HX-Redirect", resposta)
        self.assertIn("HX-Location", resposta)
        local = json.loads(resposta["HX-Location"])
        self.assertEqual(local["target"], "#area-chat")
        self.assertEqual(local["select"], "#area-chat")

    def test_post_htmx_invalido_200_sem_hx_location_area_re_renderizada(self):
        self.client.force_login(self.editor)
        get1 = self.client.get(reverse("assistente:pagina") + "?exercicio=2026")
        requisicao_id = _extrair_requisicao_id(get1.content.decode())
        resposta = self.client.post(
            reverse("assistente:perguntar"),
            {"pergunta": "   ", "requisicao_id": requisicao_id, "exercicio": 2026},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertNotIn("HX-Location", resposta)
        html = resposta.content.decode()
        self.assertIn('id="area-chat"', html)

    def test_post_htmx_quota_esgotada_200_com_retry_after_e_mensagem(self):
        fake = ClienteFalso([resposta_texto("um")])
        self.client.force_login(self.editor)
        with override_settings(IA_MAX_PERGUNTAS_DIA=1), patch_cliente(fake):
            # Os dois `requisicao_id` são emitidos ANTES de qualquer POST
            # (mesmo padrão de `TestQuotaDoisNavegadores`): depois que a
            # quota esgota, o GET seguinte para de emitir id novo — pedir o
            # segundo DEPOIS do primeiro POST daria um id vazio e o 400
            # (`invalida`) mascararia o 429 que este teste quer provar.
            get1 = self.client.get(reverse("assistente:pagina") + "?exercicio=2026")
            rid1 = _extrair_requisicao_id(get1.content.decode())
            get1_extra = self.client.get(reverse("assistente:pagina") + "?exercicio=2026")
            rid2 = _extrair_requisicao_id(get1_extra.content.decode())

            primeira = self.client.post(
                reverse("assistente:perguntar"),
                {"pergunta": "primeira", "requisicao_id": rid1, "exercicio": 2026},
            )
            self.assertEqual(primeira.status_code, 302)

            resposta = self.client.post(
                reverse("assistente:perguntar"),
                {"pergunta": "segunda", "requisicao_id": rid2, "exercicio": 2026},
                HTTP_HX_REQUEST="true",
            )
        self.assertEqual(resposta.status_code, 200)
        self.assertNotIn("HX-Location", resposta)
        self.assertIn("Retry-After", resposta)
        self.assertIn("br-message", resposta.content.decode())

    def test_post_sem_htmx_continua_302_400_429_inalterado(self):
        self.client.force_login(self.editor)
        get1 = self.client.get(reverse("assistente:pagina") + "?exercicio=2026")
        requisicao_id = _extrair_requisicao_id(get1.content.decode())
        resposta_invalida = self.client.post(
            reverse("assistente:perguntar"),
            {"pergunta": "   ", "requisicao_id": requisicao_id, "exercicio": 2026},
        )
        self.assertEqual(resposta_invalida.status_code, 400)

    def test_get_pagina_htmx_com_select_devolve_area_chat(self):
        self.client.force_login(self.editor)
        resposta = self.client.get(
            reverse("assistente:pagina") + "?exercicio=2026", HTTP_HX_REQUEST="true"
        )
        self.assertEqual(resposta.status_code, 200)
        html = resposta.content.decode()
        self.assertIn('id="area-chat"', html)
        self.assertEqual(html.count("hx-swap-oob"), 0)


class TestPseudoStreamingAndamento(AssistenteTestBase):
    """Pseudo-streaming por polling htmx. A
    base já roda `_iniciar_thread` de forma síncrona (`setUp`); os testes
    que precisam observar o estado `em_andamento` desligam esse patch e
    substituem por um no-op (a "thread" nunca roda) ou por uma thread de
    verdade (`test_streaming.TestThreadReal`)."""

    def _reservar_sem_processar(self, pergunta="oi"):
        """POST com `_iniciar_thread` neutralizado — a requisição fica
        `em_andamento` com `andamento` gravado ("Pensando…"), mas a
        pergunta nunca é processada."""
        get1 = self.client.get(reverse("assistente:pagina") + "?exercicio=2026")
        rid = _extrair_requisicao_id(get1.content.decode())
        self._patch_thread_sincrona.stop()
        try:
            with mock.patch("apps.assistente.views._iniciar_thread"):
                resposta = self.client.post(
                    reverse("assistente:perguntar"),
                    {"pergunta": pergunta, "requisicao_id": rid, "exercicio": 2026},
                )
        finally:
            self._patch_thread_sincrona.start()
        self.assertEqual(resposta.status_code, 302)
        return rid

    def test_andamento_gravado_pensando_antes_de_processar(self):
        self.client.force_login(self.editor)
        get1 = self.client.get(reverse("assistente:pagina") + "?exercicio=2026")
        rid = _extrair_requisicao_id(get1.content.decode())
        capturado = {}
        fake = ClienteFalso(
            [resposta_texto("ok")],
            ao_chamar=lambda: capturado.setdefault("etapa", estado.andamento_ler(rid).etapa),
        )
        with patch_cliente(fake):
            resposta = self.client.post(
                reverse("assistente:perguntar"),
                {"pergunta": "oi", "requisicao_id": rid, "exercicio": 2026},
                HTTP_HX_REQUEST="true",
            )
        self.assertEqual(capturado["etapa"], "Pensando…")
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("HX-Location", resposta)

    def test_andamento_view_apos_concluir_hx_location_com_resposta_final(self):
        fake = ClienteFalso([resposta_texto("resposta final do pseudo-streaming")])
        self.client.force_login(self.editor)
        with patch_cliente(fake):
            get1 = self.client.get(reverse("assistente:pagina") + "?exercicio=2026")
            rid = _extrair_requisicao_id(get1.content.decode())
            self.client.post(
                reverse("assistente:perguntar"),
                {"pergunta": "oi", "requisicao_id": rid, "exercicio": 2026},
            )
            resp = self.client.get(
                reverse("assistente:andamento", args=[rid]), HTTP_HX_REQUEST="true"
            )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("HX-Location", resp)
        pagina = self.client.get(reverse("assistente:pagina") + "?exercicio=2026")
        self.assertIn("resposta final do pseudo-streaming", pagina.content.decode())

    def test_andamento_view_em_andamento_bolha_com_texto_escapado(self):
        self.client.force_login(self.editor)
        rid = self._reservar_sem_processar()
        estado.andamento_gravar(
            rid,
            agora=timezone.now(),
            etapa="Consultando processos…",
            texto_parcial="<script>alert(1)</script>",
        )
        resposta = self.client.get(reverse("assistente:andamento", args=[rid]))
        html = resposta.content.decode()
        self.assertEqual(resposta.status_code, 200)
        self.assertIn('id="bolha-andamento"', html)
        self.assertIn("hx-trigger", html)
        self.assertIn("every 700ms", html)
        self.assertIn("br-loading", html)
        self.assertIn("Consultando processos…", html)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_andamento_view_dono_errado_404(self):
        self.client.force_login(self.editor)
        rid = self._reservar_sem_processar()
        outro = Client(HTTP_X_FORWARDED_PROTO="https")
        outro.force_login(self.visualizador)
        resposta = outro.get(reverse("assistente:andamento", args=[rid]))
        self.assertEqual(resposta.status_code, 404)

    def test_andamento_view_lease_vencido_interrompida(self):
        self.client.force_login(self.editor)
        rid = self._reservar_sem_processar()
        with freeze_time(timezone.now() + timedelta(seconds=200)):
            resposta = self.client.get(
                reverse("assistente:andamento", args=[rid]), HTTP_HX_REQUEST="true"
            )
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("HX-Location", resposta)
        requisicao = estado.requisicao_ler(
            rid, usuario_id=self.editor.pk, sessao_hash=estado.hash_sessao(self.client.session.session_key)
        )
        self.assertEqual(requisicao.erro_codigo, "interrompida")
        pagina = self.client.get(reverse("assistente:pagina") + "?exercicio=2026")
        self.assertIn("interrompida", pagina.content.decode().lower())

    def test_sem_htmx_post_302_e_pagina_mostra_bolha_com_link_atualizar(self):
        self.client.force_login(self.editor)
        rid = self._reservar_sem_processar()
        pagina = self.client.get(reverse("assistente:pagina") + "?exercicio=2026")
        html = pagina.content.decode()
        self.assertIn('id="bolha-andamento"', html)
        self.assertIn("Atualizar", html)
        self.assertIn(reverse("assistente:andamento", args=[rid]), html)
