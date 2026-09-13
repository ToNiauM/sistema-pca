from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from django.http import QueryDict
from django.test import TestCase
from django.urls import reverse

from apps.catalogo.models import Categoria, Exercicio, Tipo, Unidade
from apps.pca.models import Processo, Situacao


class TestNavegacaoProcessoAdmin(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_superuser(
            email="admin-navegacao@example.com", password="senha-segura"
        )
        cls.exercicio, _ = Exercicio.objects.get_or_create(
            ano=2026,
            defaults={"rotulo": "PCA 2026"},
        )
        cls.unidade = Unidade.objects.create(nome="Unidade de navegação")
        cls.categoria = Categoria.objects.create(nome="Categoria de navegação")
        cls.tipo = Tipo.objects.create(nome="Tipo de navegação")

        # A criação é propositalmente diferente da sequência por item_pca.
        cls.processo_menor = cls._criar_processo(10, "Alvo menor")
        cls.processo_maior = cls._criar_processo(30, "Alvo maior")
        cls.processo_meio = cls._criar_processo(20, "Alvo meio")
        cls.processo_fora = cls._criar_processo(
            40,
            "Fora do resultado",
            situacao=Situacao.CONCLUIDO.value,
        )

    @classmethod
    def _criar_processo(cls, item_pca, descricao_objeto, **extra):
        valores = {
            "item_pca": item_pca,
            "descricao_objeto": descricao_objeto,
            "tipo": cls.tipo,
            "categoria": cls.categoria,
            "unidade_organizacional": cls.unidade,
            "exercicio": cls.exercicio,
            "situacao": Situacao.NO_PRAZO.value,
        }
        valores.update(extra)
        return Processo.objects.create(**valores)

    def setUp(self):
        self.client.force_login(self.usuario)
        self.filtros = QueryDict(mutable=True)
        self.filtros.update(
            {
                "exercicio__id__exact": self.exercicio.pk,
                "situacao__exact": Situacao.NO_PRAZO.value,
                "unidade_organizacional__id__exact": self.unidade.pk,
                "q": "Alvo",
                # Com delete_selected reabilitado, o ChangeList prefixa a coluna
                # de checkbox como índice 0 de list_display — todo índice de
                # coluna real desloca +1. "item_pca" (list_display[0]) é a coluna 1.
                "o": "-1",
                "p": "0",
            }
        )

    def _resposta_change(self, processo, filtros=None):
        parametros = {}
        if filtros is not None:
            parametros["_changelist_filters"] = filtros.urlencode()
        return self.client.get(
            reverse("admin:pca_processo_change", args=[processo.pk]), parametros
        )

    def _assert_url_com_filtros(self, url, viewname, args=(), aninhado=False):
        partes = urlsplit(url)
        self.assertEqual(partes.path, reverse(viewname, args=args))
        query = QueryDict(partes.query)
        filtros_normalizados = QueryDict(self.filtros.urlencode())
        if aninhado:
            self.assertEqual(
                QueryDict(query["_changelist_filters"]), filtros_normalizados
            )
        else:
            self.assertEqual(query, filtros_normalizados)

    def test_processo_do_meio_usa_queryset_ordenado_do_changelist(self):
        response = self._resposta_change(self.processo_meio, self.filtros)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "admin/pca/processo/change_form.html")
        navegacao = response.context["processo_navegacao"]
        self._assert_url_com_filtros(
            navegacao["voltar_url"], "admin:pca_processo_changelist"
        )
        self._assert_url_com_filtros(
            navegacao["anterior_url"],
            "admin:pca_processo_change",
            args=[self.processo_maior.pk],
            aninhado=True,
        )
        self._assert_url_com_filtros(
            navegacao["proximo_url"],
            "admin:pca_processo_change",
            args=[self.processo_menor.pk],
            aninhado=True,
        )
        self.assertContains(
            response,
            f'<a id="processo-voltar-tabela" href="{navegacao["voltar_url"]}">Voltar para tabela</a>',
            html=True,
        )
        self.assertContains(
            response,
            f'<a id="processo-anterior" href="{navegacao["anterior_url"]}">Anterior</a>',
            html=True,
        )
        self.assertContains(
            response,
            f'<a id="processo-proximo" href="{navegacao["proximo_url"]}">Próximo</a>',
            html=True,
        )

    def test_fronteiras_e_resultado_isolado_desabilitam_controles_sem_href(self):
        for processo, controle in (
            (self.processo_maior, "anterior"),
            (self.processo_menor, "proximo"),
        ):
            with self.subTest(processo=processo.pk, controle=controle):
                response = self._resposta_change(processo, self.filtros)
                navegacao = response.context["processo_navegacao"]
                self.assertIsNone(navegacao[f"{controle}_url"])
                self.assertContains(
                    response,
                    '<a id="processo-{controle}" aria-disabled="true" '
                    'tabindex="-1" style="pointer-events: none; opacity: 0.5;">{rotulo}</a>'.format(
                        controle=controle,
                        rotulo="Anterior" if controle == "anterior" else "Próximo",
                    ),
                    html=True,
                )
                self.assertNotContains(response, f'id="processo-{controle}" href=')

        filtros_isolados = self.filtros.copy()
        filtros_isolados["q"] = "meio"
        response = self._resposta_change(self.processo_meio, filtros_isolados)
        for controle in ("anterior", "proximo"):
            with self.subTest(controle=controle):
                self.assertIsNone(response.context["processo_navegacao"][f"{controle}_url"])
                self.assertContains(
                    response,
                    '<a id="processo-{controle}" aria-disabled="true" '
                    'tabindex="-1" style="pointer-events: none; opacity: 0.5;">{rotulo}</a>'.format(
                        controle=controle,
                        rotulo="Anterior" if controle == "anterior" else "Próximo",
                    ),
                    html=True,
                )

    def test_sem_filtros_usa_ordenacao_padrao_e_retorno_sem_query_string(self):
        response = self._resposta_change(self.processo_meio)

        navegacao = response.context["processo_navegacao"]
        self.assertEqual(
            navegacao["voltar_url"], reverse("admin:pca_processo_changelist")
        )
        self.assertEqual(
            urlsplit(navegacao["anterior_url"]).path,
            reverse("admin:pca_processo_change", args=[self.processo_menor.pk]),
        )
        self.assertEqual(
            urlsplit(navegacao["proximo_url"]).path,
            reverse("admin:pca_processo_change", args=[self.processo_maior.pk]),
        )

    def test_formulario_de_adicao_mantem_ferramentas_nativas_sem_navegacao(self):
        response = self.client.get(reverse("admin:pca_processo_add"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="processo-voltar-tabela"')

    def test_objeto_fora_do_resultado_preserva_retorno_e_desabilita_vizinhos(self):
        response = self._resposta_change(self.processo_fora, self.filtros)

        navegacao = response.context["processo_navegacao"]
        self._assert_url_com_filtros(
            navegacao["voltar_url"], "admin:pca_processo_changelist"
        )
        self.assertIsNone(navegacao["anterior_url"])
        self.assertIsNone(navegacao["proximo_url"])
        for controle in ("anterior", "proximo"):
            with self.subTest(controle=controle):
                self.assertContains(
                    response,
                    '<a id="processo-{controle}" aria-disabled="true" '
                    'tabindex="-1" style="pointer-events: none; opacity: 0.5;">{rotulo}</a>'.format(
                        controle=controle,
                        rotulo="Anterior" if controle == "anterior" else "Próximo",
                    ),
                    html=True,
                )


class TestTemaAdmin(TestCase):
    """/admin usa o azul do govbr-ds (#1351b4) nos 3 tokens de cor
    sobrescritos por `PcaAdminSite.each_context`."""

    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_superuser(
            email="admin-tema@example.com", password="senha-segura"
        )

    def test_indice_do_admin_usa_azul_govbr(self):
        self.client.force_login(self.usuario)
        response = self.client.get(reverse("admin:index"))

        self.assertIn("#1351b4", response.content.decode())
