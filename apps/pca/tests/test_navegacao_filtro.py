from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TransactionTestCase
from django.urls import reverse

from apps.pca.models import Processo

ARQUIVO_REAL = "apps/pca/fixtures/modelo-controle-exemplo.xlsx"


class TestNavegacaoPreservaFiltro(TransactionTestCase):
    """Trocar de visão preserva o filtro ativo.

    O risco aparece na troca HTMX: o hx-get substitui apenas o alvo
    (#resultado-tabela / #dashboard-conteudo / #calendario-grade), a
    sidebar não é alcançada, e seus href ficariam congelados no estado da
    carga inicial (sem filtro) se dependessem de re-render. Por isso todo
    teste aqui manda `HTTP_HX_REQUEST="true"` e inspeciona o HTML
    servido, não o contexto — é o HTML que o navegador troca.

    Mesmo padrão de setUp() de TestFiltrosTabela: import real a cada teste
    (TransactionTestCase não chama setUpTestData e dá flush entre testes) e
    serialized_rollback para preservar o usuário de serviço da migração.
    """

    serialized_rollback = True

    def setUp(self):
        call_command(
            "importar_pca",
            ARQUIVO_REAL,
            "--usuario=importador@pca.local",
            "--exercicio=2026",
            stdout=StringIO(),
        )
        self.usuario = get_user_model().objects.create_user(
            email="leitor@pca.local", password="x-forte-123"
        )
        self.client.force_login(self.usuario)

    def _troca_htmx(self, rota, **filtro):
        """Simula a troca de filtro por HTMX e devolve o HTML servido."""
        resposta = self.client.get(
            reverse(rota) if ":" in rota else rota,
            filtro,
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(resposta.status_code, 200)
        return resposta.content.decode("utf-8")

    def _get_sem_filtro(self, rota, **filtro):
        """Quick 260903-tub — GET SEM HTTP_HX_REQUEST: é o que a navegação
        nova (brNavigate/hx-boost) produz no servidor, porque base.html
        remove o cabeçalho HX-Request antes de disparar a requisição que
        mira #conteudo-principal (ver htmx:configRequest). Devolve a
        página cheia, não o fragmento de `_troca_htmx`."""
        resposta = self.client.get(reverse(rota) if ":" in rota else rota, filtro)
        self.assertEqual(resposta.status_code, 200)
        return resposta.content.decode("utf-8")

    # `pca:tabela`/`pca:calendario`/`pca:resumo_uo` usam `base.html` (skill
    # dsgov): o único parâmetro que atravessa telas pelo menu é
    # `exercicio`. Nenhuma tela do sistema usa `<br-menu id="nav-visoes">`/
    # OOB/links cross-tela carregando filtro arbitrário.

    def test_tabela_htmx_nao_tem_mais_nav_visoes_nem_oob(self):
        conteudo = self._troca_htmx("pca:tabela", situacao="concluido")
        self.assertNotIn('id="nav-visoes"', conteudo)
        self.assertNotIn("hx-swap-oob", conteudo)
        self.assertNotIn('id="conteudo-principal"', conteudo)

    # `{% ordenar_por_tabela %}`/`{% url_com %}` copiam `request.GET`
    # inteiro para montar os links de ordenação/paginação da própria
    # tabela (convenção da skill) — um parâmetro fora do vocabulário pode
    # aparecer nesses links internos. A fronteira que importa (ORM)
    # continua validada por `filtros_ativos`/`queryset_filtrado`,
    # intocados — um clique num link "sujo" volta para `pca:tabela`, que
    # descarta o parâmetro em silêncio de novo
    # (`test_filtros_tabela.py::test_parametro_desconhecido_e_ignorado_
    # silenciosamente`).

    def test_editar_processo_modo_ver_redireciona_ao_detalhe_sem_modal(self):
        """`pca:editar_processo?modo=ver` redireciona à página de detalhe
        (`pca:detalhe_processo`), sem fragmento `<br-modal` nenhum — a
        leitura pura é sempre página inteira na casca da skill dsgov.
        Requisição htmx: `core.middleware.HtmxRedirectMiddleware` converte
        o redirect em `HX-Redirect`/200, não 302."""
        processo = Processo.objects.order_by("item_pca").first()
        self.assertIsNotNone(processo)
        url = reverse("pca:editar_processo", args=[processo.exercicio.ano, processo.item_pca])
        destino = reverse(
            "pca:detalhe_processo", args=[processo.exercicio.ano, processo.item_pca]
        )
        resposta = self.client.get(
            url, {"modo": "ver"}, HTTP_HX_REQUEST="true"
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta["HX-Redirect"], destino)

        detalhe = self.client.get(destino)
        self.assertNotIn("<br-modal", detalhe.content.decode())

    def test_calendario_bookmark_com_filtro_resolve_o_mesmo_estado(self):
        # Sem painel de filtros/HTMX: o estado validado (visão/mês/
        # situação) chega só por bookmark/link direto (recarga inteira).
        # `filtros_ativos`/`queryset_filtrado` continuam a única fonte de
        # verdade.
        resposta = self.client.get(
            reverse("pca:calendario"),
            {"situacao": "concluido", "visao": "anual", "mes_calendario": "4"},
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.context["visao_calendario"], "anual")
        conteudo = resposta.content.decode("utf-8")
        self.assertNotIn("parametro_inventado", conteudo)
