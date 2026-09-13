from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from apps.catalogo.models import Categoria, Exercicio, SituacaoExercicio, Tipo, Unidade
from apps.pca.models import Processo


class AnnualRouteFixtures(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.closed, _ = Exercicio.objects.update_or_create(
            ano=2026,
            defaults={"rotulo": "PCA 2026", "situacao": SituacaoExercicio.FECHADO},
        )
        cls.open, _ = Exercicio.objects.update_or_create(
            ano=2027,
            defaults={"rotulo": "PCA 2027", "situacao": SituacaoExercicio.ABERTO},
        )
        cls.tipo = Tipo.objects.create(nome="Aquisição")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.unidade = Unidade.objects.create(nome="Presidência")
        cls.closed_process = cls._process(cls.closed, "Item fechado")
        cls.open_process = cls._process(cls.open, "Item aberto")
        cls.editor = get_user_model().objects.create_user(
            email="editor-annual-routes@example.com", password="senha-segura"
        )
        cls.editor.user_permissions.add(Permission.objects.get(codename="editar_pca"))

    def setUp(self):
        self.client.force_login(self.editor)

    @classmethod
    def _process(cls, exercicio, descricao):
        return Processo.objects.create(
            exercicio=exercicio,
            item_pca=65,
            descricao_objeto=descricao,
            tipo=cls.tipo,
            categoria=cls.categoria,
            unidade_organizacional=cls.unidade,
        )

    def test_canonical_route_resolves_the_requested_annual_item(self):
        # `pca:detalhe_processo` é a rota anual de 2 argumentos que prova o
        # invariante de desambiguação multiexercício (item 65 existe nos
        # dois anos, cada rota resolve o processo do ano pedido).
        # `pca:editar_processo?modo=ver` redireciona (302) para esta rota
        # (ver `TestNavegacaoPreservaFiltro` em `test_navegacao_filtro.py`).
        fechado = self.client.get(reverse("pca:detalhe_processo", args=[2026, 65]))
        aberto = self.client.get(reverse("pca:detalhe_processo", args=[2027, 65]))

        self.assertEqual(fechado.status_code, 200)
        self.assertContains(fechado, "Item fechado")
        self.assertEqual(aberto.status_code, 200)
        self.assertContains(aberto, "Item aberto")
        self.assertNotContains(fechado, "Item aberto")

    def test_legacy_route_no_longer_resolves(self):
        # `pca:detalhe` (rota legada de 1 argumento) não existe mais: 404
        # puro de roteamento, igual em qualquer chave de item.
        resposta = self.client.get("/processo/65")
        self.assertEqual(resposta.status_code, 404)

    def test_editor_permission_is_available_for_the_forged_write_regressions(self):
        self.assertTrue(self.editor.has_perm("pca.editar_pca"))

    def test_navegacao_direta_e_htmx_devolvem_a_mesma_pagina_completa(self):
        """`pca:detalhe_processo` não distingue GET direto de GET htmx: é
        sempre navegação de página inteira, nunca um fragmento trocado
        dentro de `#modal`."""
        url = reverse("pca:detalhe_processo", args=[2026, 65])

        pagina_completa = self.client.get(url)
        via_htmx = self.client.get(url, HTTP_HX_REQUEST="true")

        self.assertEqual(pagina_completa.status_code, 200)
        self.assertIn("<html", pagina_completa.content.decode())
        self.assertIn("Item fechado", pagina_completa.content.decode())

        self.assertEqual(via_htmx.status_code, 200)
        self.assertIn("<html", via_htmx.content.decode())
        self.assertIn("Item fechado", via_htmx.content.decode())

    def test_item_inexistente_devolve_404_com_copy_propria(self):
        # Item que não existe no exercício 2026 do fixture devolve página
        # 404 própria (número do item, ano consultado, link "Voltar à
        # tabela"), nunca a página 404 padrão do Django.
        resposta = self.client.get(reverse("pca:editar_processo", args=[2026, 9999]))
        conteudo = resposta.content.decode()

        self.assertEqual(resposta.status_code, 404)
        self.assertIn("não encontrado", conteudo.lower())
        self.assertIn("9999", conteudo)
        self.assertIn("2026", conteudo)
        self.assertTrue(
            "‹ Voltar à tabela" in conteudo or reverse("pca:tabela") in conteudo
        )
        self.assertEqual(resposta["Cache-Control"], "private, no-store")
        self.assertIn("<html", conteudo)
