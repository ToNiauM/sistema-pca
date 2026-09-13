import csv
from datetime import date
from decimal import Decimal
from io import StringIO

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.test import RequestFactory, TestCase
from django.urls import reverse

from apps.catalogo.models import Categoria, Exercicio, Tipo, Unidade
from apps.pca.filtros import filtros_ativos, querystring_filtros, queryset_filtrado
from apps.pca.models import Processo, Situacao


class TestMultiexercicioFiltros(TestCase):
    """The four read surfaces must share one validated annual scope."""

    @classmethod
    def setUpTestData(cls):
        cls.exercicio_2026, _ = Exercicio.objects.get_or_create(
            ano=2026, defaults={"rotulo": "PCA 2026"}
        )
        cls.exercicio_2027, _ = Exercicio.objects.get_or_create(
            ano=2027, defaults={"rotulo": "PCA 2027"}
        )
        cls.exercicio_fechado = Exercicio.objects.create(
            ano=2025, rotulo="PCA 2025", situacao="fechado"
        )
        cls.unidade = Unidade.objects.create(nome="Presidência")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.tipo = Tipo.objects.create(nome="Aquisição")
        for exercicio, item, valor in (
            (cls.exercicio_2026, 1, "100.00"),
            (cls.exercicio_2026, 2, "200.00"),
            (cls.exercicio_2027, 1, "700.00"),
        ):
            Processo.objects.create(
                exercicio=exercicio,
                item_pca=item,
                descricao_objeto=f"Objeto {exercicio.ano}/{item}",
                tipo=cls.tipo,
                categoria=cls.categoria,
                unidade_organizacional=cls.unidade,
                valor_estimado=valor,
            )

        cls.origem_aberta = Processo.objects.create(
            exercicio=cls.exercicio_2026,
            item_pca=65,
            descricao_objeto="Origem aberta",
            tipo=cls.tipo,
            categoria=cls.categoria,
            unidade_organizacional=cls.unidade,
            situacao=Situacao.EM_TRAMITACAO,
        )
        cls.origem_concluida = Processo.objects.create(
            exercicio=cls.exercicio_2026,
            item_pca=66,
            descricao_objeto="Origem concluída",
            tipo=cls.tipo,
            categoria=cls.categoria,
            unidade_organizacional=cls.unidade,
            situacao=Situacao.CONCLUIDO,
        )
        cls.legado_aberto = Processo.objects.create(
            exercicio=cls.exercicio_2027,
            item_pca=65,
            descricao_objeto="Continuação aberta",
            tipo=cls.tipo,
            categoria=cls.categoria,
            unidade_organizacional=cls.unidade,
            origem=cls.origem_aberta,
            data_inclusao_pca=date(2027, 1, 15),
        )
        Processo.objects.create(
            exercicio=cls.exercicio_2027,
            item_pca=66,
            descricao_objeto="Continuação concluída",
            tipo=cls.tipo,
            categoria=cls.categoria,
            unidade_organizacional=cls.unidade,
            origem=cls.origem_concluida,
        )
        Processo.objects.create(
            exercicio=cls.exercicio_fechado,
            item_pca=1,
            descricao_objeto="Processo encerrado",
            tipo=cls.tipo,
            categoria=cls.categoria,
            unidade_organizacional=cls.unidade,
        )

        cls.usuario = get_user_model().objects.create_user(
            email="escopo@pca.local", password="senha-forte"
        )

    def setUp(self):
        self.client.force_login(self.usuario)

    def test_querystring_exercicio_e_validado_e_transportado(self):
        self.assertEqual(
            filtros_ativos({"exercicio": "2026"})["exercicio"],
            self.exercicio_2026,
        )
        self.assertEqual(
            querystring_filtros({"exercicio": "2026", "status": "invalido"}),
            "exercicio=2026",
        )

    def test_exercicio_explicito_isola_dashboard_tabela_calendario_e_export(self):
        params = {"exercicio": "2026"}

        # `core:inicio` não expõe `total_processos_filtrados`/`valor_
        # planejado_total`/`total_geral` brutos no contexto (só os 4
        # KPIs). A isolação por exercício do mesmo `queryset_filtrado` que
        # `core:inicio`/`pca:tabela`/`pca:calendario` consomem é
        # verificada direto na fonte única; o KPI "Ativos" (apoio "de N
        # previstos") prova que a página nova lê o mesmo recorte.
        request = RequestFactory().get("/", params)
        qs = queryset_filtrado(request)
        self.assertEqual(qs.count(), 4)
        self.assertEqual(
            qs.aggregate(total=Sum("valor_estimado"))["total"], Decimal("300.00")
        )

        inicio = self.client.get(reverse("core:inicio"), params)
        kpis = {kpi["rotulo"]: kpi for kpi in inicio.context["kpis"]}
        self.assertIn("de 4 previstos", kpis["Ativos"]["apoio"])

        tabela = self.client.get(reverse("pca:tabela"), params)
        self.assertEqual(tabela.context["pagina"].paginator.count, 4)
        self.assertEqual(tabela.context["soma_filtrada"], 300)
        self.assertEqual({p.exercicio_id for p in tabela.context["pagina"].object_list}, {self.exercicio_2026.pk})

        calendario = self.client.get(reverse("pca:calendario"), params)
        self.assertEqual(calendario.context["total_filtrado"], 4)
        self.assertEqual(calendario.context["total_geral"], 4)
        self.assertEqual(
            {
                p.exercicio_id
                for agrupamento in [*calendario.context["meses"], calendario.context["sem_mes"]]
                for p in agrupamento["processos"]
            },
            {self.exercicio_2026.pk},
        )

        export = self.client.get(reverse("pca:exportar_csv"), params)
        rows = list(csv.reader(StringIO(export.content.decode("utf-8-sig")), delimiter=";"))
        self.assertEqual({row[0] for row in rows[1:]}, {"1", "2", "65", "66"})

    def test_outro_exercicio_e_default_e_valores_invalidos_nao_vazam(self):
        default = self.client.get(reverse("pca:tabela"))
        self.assertEqual(default.context["pagina"].paginator.count, 3)
        self.assertEqual(default.context["exercicio"], self.exercicio_2027)

        for valor in ("", "nao-e-ano", "2099"):
            resposta = self.client.get(reverse("pca:calendario"), {"exercicio": valor})
            self.assertEqual(resposta.context["total_filtrado"], 3)
            self.assertEqual(resposta.context["exercicio"], self.exercicio_2027)

    # `pca:tabela` usa `base.html` (skill dsgov), sem `<br-select
    # id="id_exercicio_global">` nem script de troca de exercício no
    # cabeçalho. `exercicio` continua o único parâmetro propagado entre
    # telas; o mecanismo de troca (um `<br-select>` no cabeçalho global)
    # é responsabilidade de uma frente futura, fora do escopo de
    # `pca:tabela`.

    def test_exercicio_explicito_e_tag_removivel_mas_implicit_currente_nao(self):
        explicito = self.client.get(reverse("pca:tabela"), {"exercicio": "2027"})
        html_explicito = explicito.content.decode("utf-8")
        self.assertIn("Exercício: 2027", html_explicito)
        self.assertIn("exercicio=2027", html_explicito)

        implicito = self.client.get(reverse("pca:tabela"))
        html_implicito = implicito.content.decode("utf-8")
        self.assertNotIn("aria-label=\"Remover filtro Exercício", html_implicito)

    def test_troca_de_exercicio_sem_htmx_preserva_o_filtro_no_calendario(self):
        # `pca:calendario` usa `base.html`, sem chrome OOB legado.
        # `exercicio=2027` continua resolvido corretamente, com ou sem o
        # cabeçalho HTMX.
        resposta = self.client.get(
            reverse("pca:calendario"),
            {"exercicio": "2027"},
            HTTP_HX_REQUEST="true",
        )
        html = resposta.content.decode("utf-8")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.context["exercicio"], self.exercicio_2027)
        self.assertIn("exercicio=2027", html)

    def test_tabela_htmx_com_exercicio_explicito_preserva_o_filtro(self):
        """`pca:tabela` não emite chrome OOB, mas `exercicio=2027`
        continua resolvido corretamente no fragmento HTMX (a mesma
        leitura validada de `filtros_ativos`)."""
        resposta = self.client.get(
            reverse("pca:tabela"), {"exercicio": "2027"}, HTTP_HX_REQUEST="true"
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.context["exercicio"], self.exercicio_2027)

    def test_titulo_e_chrome_da_pagina_usam_o_exercicio_resolvido(self):
        resposta = self.client.get(reverse("pca:tabela"), {"exercicio": "2027"})
        html = resposta.content.decode("utf-8")
        # Rótulo único de tela: "/tabela" é "Processos" (fonte única
        # `apps.pca.navegacao`, mesma que o menu). `<title>` é
        # "{{ titulo }} — {{ DSGOV.SISTEMA }}" (contrato de `base.html`).
        self.assertIn(
            f"<title>Processos · PCA 2027 — {settings.DSGOV['SISTEMA']}</title>",
            html,
        )
        self.assertIn("PCA 2027", html)
        self.assertNotIn("PCA 2026", html)

    def test_legados_filtra_copias_por_ano_e_origem_nao_concluida(self):
        resposta = self.client.get(
            reverse("pca:tabela"), {"exercicio": "2027", "legados": "1"}
        )
        html = resposta.content.decode("utf-8")

        self.assertEqual(resposta.context["pagina"].paginator.count, 1)
        self.assertIn("Continuação aberta", html)
        self.assertNotIn("Continuação concluída", html)

    def test_controle_e_tag_de_legados_preservam_exercicio_canonico(self):
        resposta = self.client.get(
            reverse("pca:tabela"), {"exercicio": "2027", "legados": "1"}
        )
        html = resposta.content.decode("utf-8")

        self.assertIn('name="legados"', html)
        self.assertIn("Apenas itens legados", html)
        self.assertIn("Legados", html)
        self.assertIn("legados=1", html)
        self.assertIn("exercicio=2027", html)

    # O selo vive no cabeçalho de `pca:detalhe_processo` e aponta para o
    # detalhe do item de origem.

    def test_detalhe_de_processo_com_origem_mostra_selo_de_continuacao(self):
        resposta = self.client.get(reverse("pca:detalhe_processo", args=[2027, 65]))
        html = resposta.content.decode("utf-8")

        self.assertIn("Continuação do item 65/2026", html)
        self.assertIn(
            reverse("pca:detalhe_processo", args=[2026, 65]), html
        )

    def test_detalhe_de_processo_sem_origem_nao_mostra_selo_de_continuacao(self):
        resposta = self.client.get(reverse("pca:detalhe_processo", args=[2026, 65]))
        html = resposta.content.decode("utf-8")

        self.assertNotIn("Continuação do item", html)

    def test_calendario_de_exercicio_fechado_e_somente_leitura(self):
        resposta = self.client.get(
            reverse("pca:calendario"), {"exercicio": "2025"}
        )
        html = resposta.content.decode("utf-8")

        self.assertEqual(resposta.status_code, 200)
        # Sem `id="calendario-grade"` (wrapper HTMX legado); a
        # leitura-somente continua provada pela ausência de qualquer
        # ferramenta de arrastar-e-soltar.
        self.assertIn("br-table", html)
        self.assertNotIn("sortable.min.js", html)
        self.assertNotIn("new Sortable", html)
