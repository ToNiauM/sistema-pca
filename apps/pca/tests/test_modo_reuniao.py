from io import StringIO
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TransactionTestCase
from django.urls import reverse

from apps.pca.filtros import (
    PARAMETROS_FILTRO,
    opcoes_filtros,
    querystring_filtros,
    queryset_filtrado,
)
from apps.pca.models import Acompanhamento, Processo, Reuniao


ARQUIVO_REAL = "apps/pca/fixtures/modelo-controle-exemplo.xlsx"


class TestFiltroDesdeReuniao(TransactionTestCase):
    serialized_rollback = True

    def setUp(self):
        call_command(
            "importar_pca",
            ARQUIVO_REAL,
            "--usuario=importador@pca.local",
            "--exercicio=2026",
            stdout=StringIO(),
        )
        usuario = get_user_model().objects.create_user(
            email="leitor@pca.local", password="x-forte-123"
        )
        self.client.force_login(usuario)
        self.reuniao = Reuniao.objects.order_by("data").first()

    def test_desde_reuniao_filtra_acompanhamentos_da_propria_reuniao(self):
        esperado = set(
            Acompanhamento.objects.filter(
                referencia_data=self.reuniao.data
            ).values_list("processo_id", flat=True)
        )
        resposta = self.client.get(
            reverse("pca:tabela"), {"desde_reuniao": self.reuniao.pk}
        )
        encontrados = set(
            queryset_filtrado(
            SimpleNamespace(GET=resposta.wsgi_request.GET)
            ).values_list("pk", flat=True)
        )
        self.assertEqual(encontrados, esperado)
        self.assertEqual(resposta.context["pagina"].paginator.count, len(esperado))

    def test_id_inexistente_tem_comportamento_sem_filtro(self):
        sem_filtro = self.client.get(reverse("pca:tabela"))
        invalido = self.client.get(
            reverse("pca:tabela"), {"desde_reuniao": 99999}
        )
        self.assertEqual(invalido.status_code, 200)
        self.assertEqual(
            invalido.context["pagina"].paginator.count,
            sem_filtro.context["pagina"].paginator.count,
        )

    def test_desde_reuniao_esta_entre_os_parametros_de_filtro_e_e_preservado(self):
        # O que prova o comportamento real é que desde_reuniao está entre
        # os parâmetros.
        self.assertIn("desde_reuniao", PARAMETROS_FILTRO)
        # `situacao=` é o parâmetro real hoje (Situacao.choices).
        querystring = querystring_filtros(
            {"situacao": "concluido", "desde_reuniao": str(self.reuniao.pk)}
        )
        self.assertIn(f"desde_reuniao={self.reuniao.pk}", querystring)
        self.assertIn("situacao=concluido", querystring)

    def test_opcoes_de_filtro_traz_reunioes_mais_recentes_primeiro(self):
        reunioes = list(opcoes_filtros()["reuniao"])
        self.assertEqual(reunioes, list(Reuniao.objects.order_by("-data")))


class TestBannerFiltroAtivo(TransactionTestCase):
    serialized_rollback = True

    def setUp(self):
        call_command(
            "importar_pca",
            ARQUIVO_REAL,
            "--usuario=importador@pca.local",
            "--exercicio=2026",
            stdout=StringIO(),
        )
        usuario = get_user_model().objects.create_user(
            email="leitor@pca.local", password="x-forte-123"
        )
        self.client.force_login(usuario)

    def test_htmx_com_filtro_exibe_banner_e_limpar(self):
        # Chips de `_filtros_ativos_tabela.html`: um
        # `<span class="br-tag interaction">` por filtro + o link "Limpar
        # filtros".
        resposta = self.client.get(
            reverse("pca:tabela"), {"situacao": "concluido"}, HTTP_HX_REQUEST="true"
        )
        conteudo = resposta.content.decode()
        self.assertIn("Situação: Concluído", conteudo)
        self.assertIn("Limpar filtros", conteudo)

    def test_htmx_sem_filtro_mantem_contador_sem_banner(self):
        resposta = self.client.get(reverse("pca:tabela"), HTTP_HX_REQUEST="true")
        conteudo = resposta.content.decode()
        self.assertIn("30 processos", conteudo)
        self.assertNotIn("br-tag interaction", conteudo)
        self.assertNotIn("Limpar filtros", conteudo)

    def test_seletor_de_reuniao_aparece_na_tabela_migrada(self):
        # `pca:tabela` renderiza `desde_reuniao` via
        # `FiltrosProcessoForm`/`DSGovFormRenderer` (`br-select` simples);
        # sem opção vazia explícita (o "sem seleção" vira o placeholder
        # "Selecione" do próprio componente).
        resposta = self.client.get(reverse("pca:tabela"))
        conteudo = resposta.content.decode()
        self.assertIn('name="desde_reuniao"', conteudo)
        self.assertIn("Reunião de", conteudo)

    def test_calendario_sem_seletor_de_reuniao_mas_filtro_continua_via_url(self):
        # `pca:calendario` não tem painel de filtros global (o seletor
        # de reunião vive só em `pca:tabela`). O parâmetro `desde_reuniao`
        # continua funcionando via querystring direta — só a UI de
        # escolha saiu desta tela.
        resposta = self.client.get(reverse("pca:calendario"))
        conteudo = resposta.content.decode()
        self.assertNotIn('name="desde_reuniao"', conteudo)

        reuniao = Reuniao.objects.order_by("data").first()
        com_filtro = self.client.get(
            reverse("pca:calendario"), {"desde_reuniao": reuniao.pk}
        )
        self.assertEqual(com_filtro.status_code, 200)
