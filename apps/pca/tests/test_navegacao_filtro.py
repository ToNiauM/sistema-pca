from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.test import TransactionTestCase
from django.urls import reverse

from apps.pca.models import Processo

ARQUIVO_REAL = "Modelo_de_Controle_.xlsx"


class TestNavegacaoPreservaFiltro(TransactionTestCase):
    """Trocar de visão preserva o filtro ativo.

    Este módulo existe por causa de um falso verde: a suíte tinha 146 testes
    passando e não pegou o gap do Teste 10 da UAT da Fase 2, porque todo teste
    de filtro fazia um GET DIRETO com a querystring já na URL. Nesse cenário o
    shell re-renderiza e os links da sidebar saem corretos — o bug não existe.

    O bug só aparece na TROCA HTMX: o hx-get substitui apenas o alvo
    (#resultado-tabela / #dashboard-conteudo / #calendario-grade), a sidebar não é
    alcançada, e seus href ficam congelados no estado da carga inicial (sem
    filtro). Por isso todo teste aqui manda `HTTP_HX_REQUEST="true"` e
    inspeciona o HTML servido, não o contexto — é o HTML que o navegador troca.

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
        # `/calendario` passou a exigir
        # `pca.view_acompanhamento`; este módulo testa preservação de
        # filtro na troca HTMX (persona equivalente ao grupo `editor`), não
        # o gate.
        self.usuario.user_permissions.add(
            Permission.objects.get(
                codename="view_acompanhamento", content_type__app_label="pca"
            )
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
        """GET SEM HTTP_HX_REQUEST: é o que a navegação
        nova (brNavigate/hx-boost) produz no servidor, porque base.html
        remove o cabeçalho HX-Request antes de disparar a requisição que
        mira #conteudo-principal (ver htmx:configRequest). Devolve a
        página cheia, não o fragmento de `_troca_htmx`."""
        resposta = self.client.get(reverse(rota) if ":" in rota else rota, filtro)
        self.assertEqual(resposta.status_code, 200)
        return resposta.content.decode("utf-8")

    # --- o OOB existia nas respostas de filtro das telas ainda legadas ---

    # Fase 26 — `pca:tabela` migrou para `base.html`
    # (padrão DSGov): fecha a porta de "o filtro corrente trafega para as
    # OUTRAS visões via nav-visoes" — o ÚNICO parâmetro que atravessa
    # telas pelo menu é `exercicio`. Fase 26 —
    # `pca:calendario`/`pca:resumo_uo` migraram nesta fase: eram os 2
    # últimos exemplares de `<br-menu id="nav-visoes">`/OOB/links
    # cross-tela carregando filtro arbitrário. Nenhuma tela do sistema
    # ainda faz isso — `test_troca_htmx_reemite_a_navegacao_com_swap_oob_
    # nas_visoes_legadas`/`test_do_resumo_uo_filtrado_os_links_levam_o_
    # filtro_para_tabela_e_calendario`/`test_do_calendario_filtrado_os_
    # links_levam_o_filtro_para_tabela_e_dashboard` removidos — sem
    # exemplar vivo, mesmo raciocínio.

    def test_tabela_htmx_nao_tem_mais_nav_visoes_nem_oob(self):
        conteudo = self._troca_htmx("pca:tabela", situacao="concluido")
        self.assertNotIn('id="nav-visoes"', conteudo)
        self.assertNotIn("hx-swap-oob", conteudo)
        self.assertNotIn('id="conteudo-principal"', conteudo)

    # Fase 26 — deviation documentada: `{% ordenar_por_tabela %}`/
    # `{% url_com %}` (ambos) copiam `request.GET` inteiro para
    # montar os links de ordenação/paginação da PRÓPRIA tabela (convenção
    # do padrão DSGov) — ao contrário do contrato antigo (`querystring_filtros`,
    # só campos validados), um parâmetro fora do vocabulário PODE aparecer
    # nesses links internos. Não é a mesma classe de risco de a
    # fronteira que importa (ORM) continua validada por `filtros_ativos`/
    # `queryset_filtrado`, intocados — um clique num link "sujo" volta para
    # `pca:tabela`, que descarta o parâmetro em silêncio de novo
    # (`test_filtros_tabela.py::test_parametro_desconhecido_e_ignorado_
    # silenciosamente`). Nenhum teste novo aqui: cobertura já existe lá.

    # Fase 26 — `test_par_de_hooks_configrequest_e_beforeswap_
    # e_coerente` apagado: testava os hooks `htmx:configRequest`/
    # `htmx:beforeSwap` de `_casca_legado_base.html` (o roteador de fragmento
    # #modal/OOB da casca antiga) e o `hx-select="#conteudo-principal"` de
    # `shell.html` — os dois arquivos saíram por completo nesta fase (zero HTMX de navegação/OOB no sistema). Sem substituto: a mecânica que
    # o teste protegia não existe mais em lugar nenhum.

    def test_editar_processo_modo_ver_redireciona_ao_detalhe_sem_modal(self):
        """Fase 26 — o modal de
        webcomponents em `?modo=ver` não existe mais:
        `pca:editar_processo?modo=ver` redireciona à página de detalhe
        (`pca:detalhe_processo`), sem fragmento `<br-modal` nenhum — a
        leitura pura agora é sempre página inteira na casca do padrão DSGov,
        nunca um `#modal` da casca legada. Requisição htmx: `core.middleware.
        HtmxRedirectMiddleware` (intocado) converte o redirect em
        `HX-Redirect`/200, não 302 — mesmo contrato de qualquer outro
        redirect do sistema numa troca htmx."""
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
        # Fase 26 — sem painel de filtros/HTMX: o
        # estado validado (visão/mês/situação) chega só por bookmark/link
        # direto (recarga inteira), nunca por um formulário hidden que
        # sobrevive a um swap parcial. `filtros_ativos`/`queryset_
        # filtrado` (intocados) continuam a única fonte de verdade.
        resposta = self.client.get(
            reverse("pca:calendario"),
            {"situacao": "concluido", "visao": "anual", "mes_calendario": "4"},
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.context["visao_calendario"], "anual")
        conteudo = resposta.content.decode("utf-8")
        self.assertNotIn("parametro_inventado", conteudo)
