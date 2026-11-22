"""Cobertura automatizada (must_haves):
`querystring_tabela()` é a fonte única de "estado idêntico à tabela" e
precisa reaparecer em TODOS os pontos que devolvem o usuário à mesma
tabela/sequência filtrada: link da linha, Anterior/Próximo, Voltar (com
âncora), trilha "Processos" e os redirects PRG de Editar/Alterar situação/
Registrar acompanhamento.

`TestQuerystringTabela` cobre as regras de serialização isoladamente, sem
fixture pesada (`QueryDict` sintético, mesmo padrão de
`views.py::_querystring_vencimentos`). `TestNavegacaoDetalheComFiltro`
prova, via `django.test.Client` contra o XLSX real (mesmo padrão de
`test_filtros_tabela.py`), que a MESMA querystring passada ao link da
linha reaparece em cada um desses pontos."""

from datetime import date, datetime
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.http import QueryDict
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone as django_timezone
from django.utils.html import escape

from apps.catalogo.models import Categoria, Exercicio, Tipo, Unidade
from apps.pca.filtros import querystring_filtros, querystring_tabela
from apps.pca.forms import ProcessoForm
from apps.pca.models import Estado, Processo, Situacao

ARQUIVO_REAL = "Modelo_de_Controle_.xlsx"


class TestQuerystringTabela(TestCase):
    """`querystring_tabela()` isolada — sem banco/fixture além do necessário
    para `querystring_filtros` (que não toca o banco)."""

    def test_ordenar_e_dir_so_aparecem_juntos_quando_ordenar_esta_no_get(self):
        get_sem_ordenar = QueryDict(mutable=True)
        self.assertNotIn("ordenar=", querystring_tabela(get_sem_ordenar))
        self.assertNotIn("dir=", querystring_tabela(get_sem_ordenar))

        get_com_ordenar = QueryDict(mutable=True)
        get_com_ordenar["ordenar"] = "item_pca"
        saida = querystring_tabela(get_com_ordenar)
        self.assertIn("ordenar=item_pca", saida)
        self.assertIn("dir=asc", saida)

    def test_ordenar_invalido_cai_no_padrao_mas_ainda_aparece(self):
        get = QueryDict(mutable=True)
        get["ordenar"] = "chave-inexistente"
        saida = querystring_tabela(get)
        self.assertIn("ordenar=item_pca", saida)
        self.assertIn("dir=asc", saida)

    def test_pagina_1_nunca_aparece_pagina_3_aparece(self):
        get_pagina_1 = QueryDict(mutable=True)
        get_pagina_1["pagina"] = "1"
        self.assertNotIn("pagina=", querystring_tabela(get_pagina_1))

        get_pagina_3 = QueryDict(mutable=True)
        get_pagina_3["pagina"] = "3"
        self.assertIn("pagina=3", querystring_tabela(get_pagina_3))

    def test_por_pagina_fora_da_allowlist_e_descartado(self):
        get_invalido = QueryDict(mutable=True)
        get_invalido["por_pagina"] = "999"
        self.assertNotIn("por_pagina=", querystring_tabela(get_invalido))

        get_valido = QueryDict(mutable=True)
        get_valido["por_pagina"] = "50"
        self.assertIn("por_pagina=50", querystring_tabela(get_valido))

    def test_colunas_invalida_e_descartada_validas_aparecem_na_ordem(self):
        get = QueryDict(mutable=True)
        get.setlist("colunas", ["item_pca", "chave-inexistente", "situacao"])
        saida = querystring_tabela(get)
        self.assertIn("colunas=item_pca", saida)
        self.assertIn("colunas=situacao", saida)
        self.assertNotIn("chave-inexistente", saida)
        # ordem recebida preservada
        self.assertLess(saida.index("colunas=item_pca"), saida.index("colunas=situacao"))

    def test_sem_chave_extra_saida_identica_a_querystring_filtros(self):
        get = QueryDict("situacao=atrasado")
        self.assertEqual(querystring_tabela(get), querystring_filtros(get))


class TestNavegacaoDetalheComFiltro(TransactionTestCase):
    """Contrato observável de propagação linha→detalhe→navegação→ações→
    redirect, via `django.test.Client` contra o XLSX real (isolado por UO
    exclusiva para não interferir com nenhum item "atrasado" real do
    dataset)."""

    serialized_rollback = True

    def setUp(self):
        call_command(
            "importar_pca",
            ARQUIVO_REAL,
            "--usuario=importador@pca.local",
            "--exercicio=2026",
            stdout=StringIO(),
        )
        User = get_user_model()
        self.editor = User.objects.create_user(
            email="editor-nav@pca.local", password="senha-segura-260911"
        )
        self.editor.groups.add(Group.objects.get(name="editor"))
        self.client.force_login(self.editor)

        self.exercicio = Exercicio.objects.get(ano=2026)
        self.uo = Unidade.objects.create(nome="Unidade Teste Navegação xc153")
        tipo = Tipo.objects.first()
        categoria = Categoria.objects.first()

        self.p901 = self._processo(901, tipo, categoria)
        self.p902 = self._processo(902, tipo, categoria)
        self.p903 = self._processo(903, tipo, categoria)

        # Querystring canônica de teste — a ordem já é a saída REAL de
        # `querystring_tabela` (PARAMETROS_FILTRO tem `uo` antes de
        # `situacao`; `ordenar`/`dir` sempre por último), então serve tanto
        # para requisitar quanto para o assert de igualdade.
        self.querystring = f"uo={self.uo.pk}&situacao=atrasado&ordenar=item_pca&dir=asc"
        # Django escapa `&` -> `&amp;` em qualquer `{{ variavel }}` de
        # template (auto-escaping) — usado nos asserts contra HTML bruto
        # (`href=`/hidden field); `resposta["Location"]` (cabeçalho HTTP,
        # nunca HTML) e `response.context` continuam com o valor cru.
        self.querystring_html = escape(self.querystring)

    def _processo(self, item_pca, tipo, categoria):
        return Processo.objects.create(
            item_pca=item_pca,
            exercicio=self.exercicio,
            descricao_objeto=f"Fixture navegação xc153 {item_pca}",
            tipo=tipo,
            categoria=categoria,
            unidade_organizacional=self.uo,
            situacao=Situacao.ATRASADO,
            estado=Estado.ATIVO,
        )

    def test_link_da_linha_carrega_querystring_tabela(self):
        resposta = self.client.get(f"{reverse('pca:tabela')}?{self.querystring}")
        self.assertEqual(resposta.status_code, 200)
        html = resposta.content.decode()
        href_esperado = (
            f'href="{reverse("pca:detalhe_processo", args=[2026, 901])}?{self.querystring_html}"'
        )
        self.assertIn(href_esperado, html)
        self.assertIn(f'id="item-{self.p901.pk}"', html)

    def test_anterior_proximo_seguem_a_sequencia_filtrada(self):
        resposta_901 = self.client.get(
            f"{reverse('pca:detalhe_processo', args=[2026, 901])}?{self.querystring}"
        )
        self.assertIsNone(resposta_901.context["anterior"])
        self.assertEqual(resposta_901.context["proximo"], {"ano": 2026, "item_pca": 902})

        resposta_902 = self.client.get(
            f"{reverse('pca:detalhe_processo', args=[2026, 902])}?{self.querystring}"
        )
        self.assertEqual(resposta_902.context["anterior"], {"ano": 2026, "item_pca": 901})
        self.assertEqual(resposta_902.context["proximo"], {"ano": 2026, "item_pca": 903})

        resposta_903 = self.client.get(
            f"{reverse('pca:detalhe_processo', args=[2026, 903])}?{self.querystring}"
        )
        self.assertEqual(resposta_903.context["anterior"], {"ano": 2026, "item_pca": 902})
        self.assertIsNone(resposta_903.context["proximo"])

    def test_voltar_preserva_querystring_e_ancora_na_linha(self):
        resposta = self.client.get(
            f"{reverse('pca:detalhe_processo', args=[2026, 902])}?{self.querystring}"
        )
        html = resposta.content.decode()
        voltar_esperado = (
            f'{reverse("pca:tabela")}?{self.querystring_html}#item-{self.p902.pk}'
        )
        self.assertIn(voltar_esperado, html)

    def test_trilha_processos_carrega_querystring(self):
        resposta = self.client.get(
            f"{reverse('pca:detalhe_processo', args=[2026, 902])}?{self.querystring}"
        )
        trilha = dict(resposta.context["trilha"])
        self.assertIn("Processos", trilha)
        self.assertIn(self.querystring, trilha["Processos"])

    def test_editar_get_hidden_field_e_post_preserva_querystring_no_redirect(self):
        url_editar = (
            f"{reverse('pca:editar_processo', args=[2026, 902])}?{self.querystring}"
        )
        resposta_get = self.client.get(url_editar)
        self.assertEqual(resposta_get.status_code, 200)
        html = resposta_get.content.decode()
        self.assertIn(
            f'name="querystring_retorno" value="{self.querystring_html}"', html
        )

        self.p902.refresh_from_db()
        form = ProcessoForm(instance=self.p902)
        dados = {}
        for nome in form.fields:
            valor = form.initial.get(nome)
            if valor is None:
                dados[nome] = ""
            elif hasattr(valor, "isoformat"):
                dados[nome] = valor.isoformat()
            else:
                dados[nome] = str(valor)
        dados.update(
            {
                "numeros_sei-TOTAL_FORMS": "0",
                "numeros_sei-INITIAL_FORMS": "0",
                "numeros_sei-MIN_NUM_FORMS": "0",
                "numeros_sei-MAX_NUM_FORMS": "1000",
                "versao": self.p902.atualizado_em.isoformat(),
                "querystring_retorno": self.querystring,
            }
        )
        resposta_post = self.client.post(
            reverse("pca:editar_processo", args=[2026, 902]), dados
        )
        self.assertEqual(resposta_post.status_code, 302)
        self.assertEqual(
            resposta_post["Location"],
            f"{reverse('pca:detalhe_processo', args=[2026, 902])}?{self.querystring}",
        )

    def test_transicao_get_hidden_field_e_post_preserva_querystring_no_redirect(self):
        url_transicao = (
            f"{reverse('pca:transicao_processo', args=[2026, 902])}?{self.querystring}"
        )
        resposta_get = self.client.get(url_transicao)
        self.assertEqual(resposta_get.status_code, 200)
        html = resposta_get.content.decode()
        self.assertIn(
            f'name="querystring_retorno" value="{self.querystring_html}"', html
        )

        self.p902.refresh_from_db()
        resposta_post = self.client.post(
            reverse("pca:transicao_processo", args=[2026, 902]),
            {
                "destino": Situacao.EM_TRAMITACAO,
                "justificativa": "x06d6 — teste de preservação de querystring.",
                "versao": self.p902.atualizado_em.isoformat(),
                "querystring_retorno": self.querystring,
            },
        )
        self.assertEqual(resposta_post.status_code, 302)
        self.assertEqual(
            resposta_post["Location"],
            f"{reverse('pca:detalhe_processo', args=[2026, 902])}?{self.querystring}",
        )


class TestFichaExecucaoFinanceira(TestCase):
    """Fase 36 — os 3 campos novos na ficha do
    processo ("Não informado" quando vazios) e o aviso de
    coerência de 5% entre `valor_mensal` × meses de vigência e
    `valor_contratado` (SINALIZADO, `_aviso_coerencia_valor_mensal`)."""

    def setUp(self):
        self.exercicio, _ = Exercicio.objects.get_or_create(
            ano=2026, defaults={"rotulo": "PCA 2026"}
        )
        self.tipo = Tipo.objects.create(nome="Tipo execução financeira")
        self.categoria = Categoria.objects.create(nome="Categoria execução financeira")
        self.uo = Unidade.objects.create(nome="Unidade execução financeira")
        User = get_user_model()
        self.usuario = User.objects.create_user(
            email="leitor-execucao-financeira@pca.local", password="senha-segura"
        )
        self.client.force_login(self.usuario)

    def _processo(self, item_pca, **overrides):
        valores = dict(
            item_pca=item_pca,
            exercicio=self.exercicio,
            descricao_objeto="Objeto de teste da Fase 36",
            tipo=self.tipo,
            categoria=self.categoria,
            unidade_organizacional=self.uo,
        )
        valores.update(overrides)
        return Processo.objects.create(**valores)

    def test_campos_vazios_mostram_nao_informado(self):
        self._processo(910)
        resposta = self.client.get(reverse("pca:detalhe_processo", args=[2026, 910]))
        self.assertContains(
            resposta,
            "<strong>Regime de execução:</strong> Não informado",
            html=False,
        )
        self.assertContains(
            resposta,
            "<strong>Valor mensal (R$):</strong> Não informado",
            html=False,
        )

    def test_mes_previsto_aparece_por_extenso_na_ficha(self):
        self._processo(912, mes_previsto=7)
        resposta = self.client.get(reverse("pca:detalhe_processo", args=[2026, 912]))
        self.assertContains(
            resposta,
            "<strong>Mês previsto (PCA):</strong> Julho",
            html=False,
        )

    def test_aviso_coerencia_aparece_quando_diverge_mais_de_5_por_cento(self):
        self._processo(
            911,
            valor_mensal=Decimal("10000.00"),
            valor_contratado=Decimal("100000.00"),
            vigencia_inicio=date(2026, 1, 1),
            vigencia_fim=date(2026, 12, 31),
        )
        resposta = self.client.get(reverse("pca:detalhe_processo", args=[2026, 911]))
        self.assertContains(resposta, "diverge do valor contratado")

    def test_aviso_coerencia_some_quando_valores_batem(self):
        self._processo(
            912,
            valor_mensal=Decimal("10000.00"),
            valor_contratado=Decimal("120000.00"),
            vigencia_inicio=date(2026, 1, 1),
            vigencia_fim=date(2026, 12, 31),
        )
        resposta = self.client.get(reverse("pca:detalhe_processo", args=[2026, 912]))
        self.assertNotContains(resposta, "diverge do valor contratado")


class TestFichaUnidadeSeiAtual(TestCase):
    """"Unidade atual (SEI)" na ficha, somente leitura,
    mesmo molde de `TestFichaExecucaoFinanceira`. Vazio devolve "—" (não
    "Não informado", decisão explícita desta quick)."""

    def setUp(self):
        self.exercicio, _ = Exercicio.objects.get_or_create(
            ano=2026, defaults={"rotulo": "PCA 2026"}
        )
        self.tipo = Tipo.objects.create(nome="Tipo unidade SEI atual")
        self.categoria = Categoria.objects.create(nome="Categoria unidade SEI atual")
        self.uo = Unidade.objects.create(nome="Unidade unidade SEI atual")
        User = get_user_model()
        self.usuario = User.objects.create_user(
            email="leitor-unidade-sei-atual@pca.local", password="senha-segura"
        )
        self.client.force_login(self.usuario)

    def _processo(self, item_pca, **overrides):
        valores = dict(
            item_pca=item_pca,
            exercicio=self.exercicio,
            descricao_objeto="Objeto de teste da xd3d9",
            tipo=self.tipo,
            categoria=self.categoria,
            unidade_organizacional=self.uo,
        )
        valores.update(overrides)
        return Processo.objects.create(**valores)

    def test_campo_vazio_mostra_traco(self):
        self._processo(920)
        resposta = self.client.get(reverse("pca:detalhe_processo", args=[2026, 920]))
        self.assertContains(
            resposta, "<strong>Unidade atual (SEI):</strong> —", html=False
        )

    def test_campo_preenchido_mostra_unidade_e_data(self):
        desde = django_timezone.make_aware(datetime(2026, 9, 15, 14, 5))
        self._processo(
            921,
            unidade_sei_atual="GELIC / PROJUR",
            unidade_sei_atual_desde=desde,
        )
        resposta = self.client.get(reverse("pca:detalhe_processo", args=[2026, 921]))
        conteudo = resposta.content.decode()
        self.assertIn("<strong>Unidade atual (SEI):</strong>", conteudo)
        self.assertIn("GELIC / PROJUR · desde", conteudo)
        self.assertIn("15/09/2026 14:05", conteudo)
