from datetime import date, timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils.timezone import localdate

from django.db.models import Q
from django.http import QueryDict

from apps.catalogo.models import Categoria, Exercicio, Modalidade, Tipo, Unidade
from apps.pca.filtros import querystring_filtros, tags_ativas
from apps.pca.models import Estado, Processo, Reuniao, Situacao

ARQUIVO_REAL = "apps/pca/fixtures/modelo-controle-exemplo.xlsx"


class TestFiltrosTabela(TransactionTestCase):
    """Task 1 — o contrato observável de `/tabela` e de `queryset_filtrado`
    (apps/pca/filtros.py), fixado ANTES da implementação existir (RED).
    Mesmo padrão de `TestDashboardGoldenNumbers` em test_dashboard.py (02-02):
    import real em `setUp()` (não `setUpTestData()` — `TransactionTestCase`
    nunca chama esse hook e faz `flush()` a cada teste, documentado lá),
    `serialized_rollback=True` para preservar o usuário de serviço da
    migração de dados entre testes."""

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

    def _processo(self, item_pca, **kwargs):
        """Fábrica de fixture para os testes de `?estado=`/`?situacao=`:
        os processos importados nascem só com os defaults do schema
        (`estado=ativo`, `situacao=no_prazo`) porque o importador não
        grava os 3 eixos — os casos não-default usados abaixo são
        fabricados diretamente via ORM."""
        exercicio = Exercicio.objects.get(ano=2026)
        defaults = {
            "descricao_objeto": f"Fixture estado/situação {item_pca}",
            "tipo": Tipo.objects.first(),
            "categoria": Categoria.objects.first(),
            "unidade_organizacional": Unidade.objects.first(),
        }
        defaults.update(kwargs)
        return Processo.objects.create(
            item_pca=item_pca, exercicio=exercicio, **defaults
        )

    def _todas_paginas(self, **params):
        """Percorre todas as páginas via `response.context["pagina"]`, nunca
        fazendo parsing de HTML — mesmo padrão de
        `TestDashboardTabela._paginas_ordenadas`."""
        objetos = []
        pagina_num = 1
        while True:
            resposta = self.client.get(
                reverse("pca:tabela"), {**params, "pagina": pagina_num}
            )
            pagina = resposta.context["pagina"]
            objetos.extend(pagina.object_list)
            if not pagina.has_next():
                break
            pagina_num += 1
        return objetos

    # --- rota ------------------------------------------------------------

    def test_reverse_pca_tabela_resolve_rota_sem_barra(self):
        self.assertEqual(reverse("pca:tabela"), "/tabela")

    # --- golden numbers ----------------------------------------------

    def test_golden_numbers_sem_filtro(self):
        resposta = self.client.get(reverse("pca:tabela"))
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.context["pagina"].paginator.count, 30)
        self.assertEqual(
            resposta.context["soma_filtrada"], Decimal("2077500.00")
        )
        conteudo = resposta.content.decode("utf-8")
        # "N processos" no título da `br-table` (`table-title`), não
        # "Mostrando X–Y de Z processos" do rodapé antigo.
        self.assertIn("30 processos", conteudo)
        # Soma formatada em pt-BR pelo filtro `moeda`, nunca `{{ valor }}` cru.
        self.assertIn("2.077.500,00", conteudo)

    # --- busca (q) ---------------------------------------------------

    def test_busca_sem_acento_na_descricao(self):
        resposta = self.client.get(reverse("pca:tabela"), {"q": "aquisicao"})
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("aquisição", resposta.content.decode("utf-8").lower())

    def test_busca_encontra_por_justificativa(self):
        alvo = Processo.objects.exclude(justificativa="").first()
        self.assertIsNotNone(
            alvo, "dado real precisa ter ao menos uma justificativa preenchida"
        )
        termo = alvo.justificativa.strip()[:15]
        objetos = self._todas_paginas(q=termo)
        self.assertIn(alvo.item_pca, [p.item_pca for p in objetos])

    def test_busca_encontra_por_numero_sei(self):
        alvo = Processo.objects.filter(numeros_sei__isnull=False).distinct().first()
        self.assertIsNotNone(
            alvo, "dado real precisa ter ao menos um processo com nº SEI"
        )
        numero = alvo.numeros_sei.first().numero_sei
        objetos = self._todas_paginas(q=numero[:6])
        self.assertIn(alvo.item_pca, [p.item_pca for p in objetos])

    # --- filtros de domínio combinam por AND --------------------------

    def test_filtros_de_dominio_combinam_por_and(self):
        """`?situacao=` combina com UO alvo. A combinação AND é provada
        com fixtures próprias, uma delas fora da UO alvo (deve ficar de
        fora do resultado); `esperado` é medido pela mesma query que a
        view usa — contra a fixture de exemplo alguma UO pode já ter um
        item EM_TRAMITACAO de origem, então o teste nunca hardcoda "1",
        só prova que a view bate com o ORM e que a `outra_uo` fica de
        fora."""
        uo_alvo = Unidade.objects.first()
        outra_uo = Unidade.objects.exclude(pk=uo_alvo.pk).first()
        criado = self._processo(
            960,
            situacao=Situacao.EM_TRAMITACAO,
            unidade_organizacional=uo_alvo,
        )
        fora_da_uo = self._processo(
            961,
            situacao=Situacao.EM_TRAMITACAO,
            unidade_organizacional=outra_uo,
        )
        esperado = Processo.objects.filter(
            exercicio__ano=2026,
            situacao=Situacao.EM_TRAMITACAO.value,
            unidade_organizacional_id=uo_alvo.pk,
        ).count()
        self.assertGreaterEqual(esperado, 1)
        resposta = self.client.get(
            reverse("pca:tabela"),
            {
                "situacao": Situacao.EM_TRAMITACAO.value,
                "uo": uo_alvo.pk,
            },
        )
        self.assertEqual(resposta.context["pagina"].paginator.count, esperado)
        ids = {p.pk for p in resposta.context["pagina"].object_list}
        self.assertIn(criado.pk, ids)
        self.assertNotIn(fora_da_uo.pk, ids)

    def test_sentinel_nao_classificado_prioridade(self):
        esperado = Processo.objects.filter(grau_prioridade__isnull=True).count()
        self.assertGreater(esperado, 0)
        resposta = self.client.get(
            reverse("pca:tabela"), {"prioridade": "nao_classificado"}
        )
        self.assertEqual(resposta.context["pagina"].paginator.count, esperado)

    def test_sentinel_nao_classificado_classificacao(self):
        esperado = Processo.objects.filter(classificacao__isnull=True).count()
        self.assertGreater(esperado, 0)
        resposta = self.client.get(
            reverse("pca:tabela"), {"classificacao": "nao_classificado"}
        )
        self.assertEqual(resposta.context["pagina"].paginator.count, esperado)

    def test_sentinel_sem_mes_isola_o_item_sem_mes(self):
        # A fixture de exemplo tem exatamente 1 item sem mês
        # previsto (item 9, `gerar_fixture_exemplo`), não mais o item 137
        # real.
        resposta = self.client.get(reverse("pca:tabela"), {"mes": "sem_mes"})
        pagina = resposta.context["pagina"]
        self.assertEqual(pagina.paginator.count, 1)
        self.assertEqual(pagina.object_list[0].item_pca, 9)

    def test_mes_filtra_por_inteiro(self):
        mes_com_dados = (
            Processo.objects.exclude(mes_previsto__isnull=True)
            .values_list("mes_previsto", flat=True)
            .first()
        )
        esperado = Processo.objects.filter(mes_previsto=mes_com_dados).count()
        resposta = self.client.get(
            reverse("pca:tabela"), {"mes": mes_com_dados}
        )
        self.assertEqual(resposta.context["pagina"].paginator.count, esperado)

    def test_parametro_desconhecido_e_ignorado_silenciosamente(self):
        resposta = self.client.get(
            reverse("pca:tabela"), {"campo_inventado": "1; DROP TABLE"}
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.context["pagina"].paginator.count, 30)

    # --- ordenação -----------------------------------------------------

    def test_ordenacao_ignora_parametro_fora_da_allowlist(self):
        # `justificativa` entrou na
        # allowlist nesta fase; `campo_inventado` nunca existiu em
        # `COLUNAS_ORDENACAO`, exemplo estável de chave fora da allowlist.
        resposta = self.client.get(
            reverse("pca:tabela"), {"ordenar": "campo_inventado"}
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.context["campo_ordenacao"], "item_pca")
        primeiro = resposta.context["pagina"].object_list[0]
        self.assertEqual(primeiro.item_pca, 1)

    def test_mes_nulo_fica_por_ultimo_na_ordenacao(self):
        objetos = self._todas_paginas(ordenar="mes_previsto")
        self.assertEqual(len(objetos), 30)
        self.assertEqual(objetos[-1].item_pca, 9)
        self.assertIsNone(objetos[-1].mes_previsto)

    def test_ordenacao_de_prazo_e_dias_usa_allowlist_e_annotations(self):
        """`prazo_inicial`
        (substitui prazo_entrega na allowlist), prazo_efetivo,
        n_prorrogacoes e dias_atraso entram na allowlist de `?ordenar=` e
        ordenam pelas annotations de `para_listagem()`, nunca por um nome
        cru fora dela. Os dois processos sintéticos abaixo não têm
        histórico de `Acompanhamento`, então `prazo_inicial` (COALESCE)
        coincide com `prazo_entrega` — a mesma ordem esperada."""
        exercicio = Exercicio.objects.get(ano=2026)
        hoje = localdate()
        vencido = Processo.objects.create(
            item_pca=901,
            exercicio=exercicio,
            descricao_objeto="Ordenação por prazo",
            tipo=Tipo.objects.first(),
            categoria=Categoria.objects.first(),
            unidade_organizacional=Unidade.objects.first(),
            prazo_entrega=hoje - timedelta(days=3650),
        )
        Processo.objects.create(
            item_pca=902,
            exercicio=exercicio,
            descricao_objeto="Ordenação por prazo, sem atraso",
            tipo=Tipo.objects.first(),
            categoria=Categoria.objects.first(),
            unidade_organizacional=Unidade.objects.first(),
            prazo_entrega=hoje + timedelta(days=5),
        )

        resposta = self.client.get(
            reverse("pca:tabela"), {"ordenar": "prazo_inicial", "dir": "asc"}
        )
        self.assertEqual(resposta.context["campo_ordenacao"], "prazo_inicial")
        self.assertEqual(
            resposta.context["pagina"].object_list[0].item_pca, vencido.item_pca
        )

        objetos_dias = self._todas_paginas(ordenar="dias_atraso", dir="desc")
        self.assertEqual(objetos_dias[0].item_pca, vencido.item_pca)

        resposta_efetivo = self.client.get(
            reverse("pca:tabela"), {"ordenar": "prazo_efetivo", "dir": "asc"}
        )
        self.assertEqual(resposta_efetivo.context["campo_ordenacao"], "prazo_efetivo")
        self.assertEqual(
            resposta_efetivo.context["pagina"].object_list[0].item_pca,
            vencido.item_pca,
        )

        # A fixture de exemplo não tem nenhum item com
        # `n_prorrogacoes >= 1` pronto (nenhum `prazo_prometido` gravado
        # por padrão, ver `gerar_fixture_exemplo.py`); fabrica 2 promessas
        # distintas para um processo NOVO e isolado (não `vencido`, cujo
        # `prazo_efetivo` já foi verificado acima — COALESCE(prazo_vigente,
        # prazo_entrega) trocaria de fonte e quebraria aquela asserção) só
        # para provar que a allowlist ordena de fato pela annotation.
        from apps.catalogo.models import SituacaoNormalizada
        from apps.pca.models import Acompanhamento, TipoEvento

        com_promessas = Processo.objects.create(
            item_pca=903,
            exercicio=exercicio,
            descricao_objeto="Ordenação por n_prorrogacoes",
            tipo=Tipo.objects.first(),
            categoria=Categoria.objects.first(),
            unidade_organizacional=Unidade.objects.first(),
        )
        situacao_cat = SituacaoNormalizada.objects.first()
        for indice, prazo in enumerate([hoje - timedelta(days=10), hoje - timedelta(days=5)]):
            Acompanhamento.objects.create(
                processo=com_promessas,
                referencia_data=hoje - timedelta(days=20 - indice),
                origem_hash=f"hash-ordenacao-prorrogacao-{com_promessas.pk}-{indice}",
                tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO,
                situacao=situacao_cat,
                prazo_prometido=prazo,
            )

        objetos_n = self._todas_paginas(ordenar="n_prorrogacoes", dir="desc")
        processo_com_prorrogacao = next(
            p for p in objetos_n if p.item_pca == com_promessas.item_pca
        )
        self.assertGreaterEqual(processo_com_prorrogacao.n_prorrogacoes, 1)

    def test_ordenacao_descendente_de_prazo_poe_sem_prazo_por_ultimo(self):
        """`prazo_inicial`/`prazo_efetivo` são colunas de data anuláveis;
        sem `nulls_last` nos dois sentidos (a mesma disciplina do
        `mes_previsto`), o PostgreSQL põe NULL primeiro num ORDER BY DESC
        — "quem está mais atrasado" mostraria em primeiro lugar
        justamente quem não tem prazo nenhum."""
        exercicio = Exercicio.objects.get(ano=2026)
        hoje = localdate()
        futuro = Processo.objects.create(
            item_pca=903,
            exercicio=exercicio,
            descricao_objeto="Prazo futuro, deve vir primeiro no desc",
            tipo=Tipo.objects.first(),
            categoria=Categoria.objects.first(),
            unidade_organizacional=Unidade.objects.first(),
            prazo_entrega=hoje + timedelta(days=3650),
        )
        sem_prazo = Processo.objects.create(
            item_pca=904,
            exercicio=exercicio,
            descricao_objeto="Sem prazo algum, nunca pode vencer o futuro",
            tipo=Tipo.objects.first(),
            categoria=Categoria.objects.first(),
            unidade_organizacional=Unidade.objects.first(),
            prazo_entrega=None,
        )

        objetos = self._todas_paginas(ordenar="prazo_inicial", dir="desc")
        indices = {p.item_pca: indice for indice, p in enumerate(objetos)}
        self.assertLess(indices[futuro.item_pca], indices[sem_prazo.item_pca])

    # --- filtros de prazo -----------------------------------------------
    #
    # `test_tabela_expoe_prazo_planejado_
    # efetivo_dias_e_remarcacoes`/`test_status_usa_qualificador_calculado`/
    # `test_processo_65_exibe_uma_remarcacao` removidos: as 4 colunas que
    # eles verificavam (`prazo_entrega`, `prazo_efetivo`, `dias_atraso`,
    # `n_prorrogacoes`) e o qualificador textual "(fora/dentro do prazo)"
    # SAÍRAM das 6 colunas visíveis da tabela migrada (`telas/listagem.md`:
    # "até 6 colunas visíveis") — não é perda de cobertura de NEGÓCIO: as
    # mesmas annotations (`n_prorrogacoes`, `qualificador_prazo`,
    # `dias_atraso`) continuam testadas contra o ORM em
    # `test_querysets.py`/`test_dashboard.py` (citados nos docstrings
    # originais), só não aparecem mais como célula da tabela de processos.
    # `_trecho_da_linha` (marcador `id="linha-{pk}"`) também saiu com eles —
    # a linha nova não tem esse id (nenhum swap OOB por linha).

    # --- paginação -------------------------------------------------------

    def test_paginacao_preserva_filtro_ativo_no_link(self):
        """`?estado=` (TAMANHO_PAGINA=20, precisa de mais de uma página)."""
        for indice in range(25):
            self._processo(970 + indice, estado=Estado.CANCELADO)
        resposta = self.client.get(
            reverse("pca:tabela"), {"estado": Estado.CANCELADO.value}
        )
        pagina = resposta.context["pagina"]
        self.assertTrue(pagina.has_next())
        conteudo = resposta.content.decode("utf-8")
        self.assertIn("estado=cancelado", conteudo)

    def test_contagem_exibida_igual_paginator_count(self):
        """`?estado=`: `ARQUIVO_REAL` já importa 18 processos CANCELADO,
        então o total sob `?estado=cancelado` dobra ao criar mais 18 — não
        é duplicação de linhas por JOIN (`queryset_filtrado`/`estado__in`
        não faz join multiplicador). O teste mede a baseline antes de
        criar as 18 novas, em vez de presumir zero."""
        base_cancelados = Processo.objects.filter(
            estado=Estado.CANCELADO.value
        ).count()
        for indice in range(18):
            self._processo(1000 + indice, estado=Estado.CANCELADO)
        resposta = self.client.get(
            reverse("pca:tabela"), {"estado": Estado.CANCELADO.value}
        )
        conteudo = resposta.content.decode("utf-8")
        total = resposta.context["pagina"].paginator.count
        self.assertEqual(total, base_cancelados + 18)
        # Título da `br-table`: "N processo(s)" (`table-title`), não
        # "Mostrando X–Y de Z processos" do rodapé antigo.
        self.assertIn(f"{total} processos", conteudo)

    # --- estado vazio ------------------------------------------------

    def test_estado_vazio_quando_filtro_nao_bate_nada(self):
        """`aguardando_dfd` saiu do domínio (zero instâncias).
        Combina um status válido com um termo de busca que não bate em nada
        real da base de teste, produzindo zero resultados de forma
        determinística sem depender de um status removido."""
        resposta = self.client.get(
            reverse("pca:tabela"),
            {
                "estado": Estado.CANCELADO.value,
                "q": "termo-inexistente-nas-descricoes-fase15",
            },
        )
        conteudo = resposta.content.decode("utf-8")
        self.assertIn("Nenhum processo com esses filtros", conteudo)

    # --- tags removíveis ---------------------------------------------------

    def test_tag_removivel_preserva_os_demais_filtros(self):
        uo_id = Processo.objects.filter(
            tipo__nome_normalizado="vigente"
        ).first().unidade_organizacional_id
        resposta = self.client.get(
            reverse("pca:tabela"),
            {"situacao": Situacao.CONCLUIDO.value, "uo": uo_id},
        )
        conteudo = resposta.content.decode("utf-8")
        # A tag que remove "status" precisa manter uo=<id> no href; nunca os
        # dois juntos (senão "remover" também apaga o outro filtro).
        self.assertIn(f"uo={uo_id}", conteudo)

    #
    # `test_link_nao_classificado_aplica_filtro_de_primeira_classe` removido:
    # `prioridade`/`classificacao` deixaram de ser colunas visíveis da
    # tabela (máximo 6 colunas, `telas/listagem.md`), então a célula-badge
    # clicável "Não classificado" que gerava o href
    # `?prioridade=nao_classificado` não existe mais. "Não classificado"
    # continua sendo filtro de primeira classe — agora
    # como opção normal dos `br-checkbox` de `filtros_form.prioridade`/
    # `filtros_form.classificacao` no form de busca/filtros, não mais um
    # atalho de 1 clique a partir da célula.

    # --- HTMX / OOB -----------------------------------------------------

    def test_requisicao_htmx_retorna_fragmento_sem_oob(self):
        """Inverte a asserção antiga: a
        resposta HTMX de `pca:tabela` passa a ser SÓ `_listagem.html`
        (chips + tabela + paginação + Exportar), sem nenhum `hx-swap-oob` —
        a casca legada de 5 fragmentos concatenados (`_tags_filtros.html`/
        `_acoes_export.html`/`core/_nav_visoes.html`/
        `core/_titulo_exercicio.html`/`core/_rodape_visoes.html`) não se
        aplica mais a esta tela."""
        resposta = self.client.get(
            reverse("pca:tabela"),
            {"situacao": Situacao.CONCLUIDO.value},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta["Cache-Control"], "private, no-store")
        conteudo = resposta.content.decode("utf-8")
        self.assertNotIn("<!DOCTYPE", conteudo)
        self.assertNotIn("hx-swap-oob", conteudo)

    def test_requisicao_normal_tambem_leva_cache_control(self):
        resposta = self.client.get(reverse("pca:tabela"))
        self.assertEqual(resposta["Cache-Control"], "private, no-store")

    def test_filtro_persiste_entre_requisicoes_via_sessao(self):
        """Quick 260911-usq (Q-05) inverte a asserção antiga (o teste se
        chamava `test_filtro_nao_vaza_entre_requisicoes_via_sessao` e exigia
        exatamente o oposto): sair de `/tabela` filtrada e voltar por uma
        URL crua agora restaura o MESMO estado — o filtro passa a persistir
        em sessão (`views.CHAVE_SESSAO_ESTADO_TABELA`), redirecionando a
        requisição não-htmx sem querystring de volta ao estado gravado."""
        self.client.get(
            reverse("pca:tabela"),
            {"estado": Estado.CANCELADO.value},
            HTTP_HX_REQUEST="true",
        )
        resposta = self.client.get(reverse("pca:tabela"))
        self.assertEqual(resposta.status_code, 302)
        self.assertIn(f"estado={Estado.CANCELADO.value}", resposta["Location"])
        resposta_seguindo = self.client.get(resposta["Location"])
        self.assertLess(resposta_seguindo.context["pagina"].paginator.count, 30)

    # --- orçamento de queries (Pitfall 8/9/10) --------------------------

    def test_orcamento_de_queries_independe_do_numero_de_linhas(self):
        # Mesmo formato de filtro (um único `status`), só troca o valor —
        # 53 linhas (duas páginas) de um lado, 15 (uma página) do outro.
        # Zero linhas fica FORA desta comparação de propósito: um slice
        # `queryset[0:0]` é otimizado pelo Django via `EmptyResultSet` e
        # nunca chega a consultar o banco (confirmado nesta revisão) — um
        # true positive de "menos queries", não um caso apto para detectar
        # N+1. Se o número de queries divergir entre 53 e 15, há N+1 nas
        # propriedades derivadas ou no bloco de tags/opções.
        with CaptureQueriesContext(connection) as muitas_linhas:
            resposta_muitas = self.client.get(
                reverse("pca:tabela"), {"situacao": Situacao.CONCLUIDO.value}
            )
        with CaptureQueriesContext(connection) as poucas_linhas:
            resposta_poucas = self.client.get(
                reverse("pca:tabela"), {"situacao": Situacao.EM_TRAMITACAO.value}
            )
        self.assertEqual(resposta_muitas.status_code, 200)
        self.assertEqual(resposta_poucas.status_code, 200)
        self.assertEqual(
            len(muitas_linhas.captured_queries), len(poucas_linhas.captured_queries)
        )

    def test_assertnumqueries_pagina_completa(self):
        # Orçamento fixo da carga completa (não-HTMX) — mesma convenção de
        # TestDashboardTabela.test_assertnumqueries, documentado por grupo:
        #   1. SELECT django_session (AuthenticationMiddleware)
        #   2. SELECT core_usuario (AuthenticationMiddleware)
        #   3. SELECT COUNT(*) — Paginator.count sobre o queryset filtrado
        #   4. SELECT SUM(valor_estimado) — soma do resultado filtrado (TAB-03)
        #   5. SELECT COUNT(*) — total geral (contador "de N processos")
        #   6. SELECT ... (select_related + Subqueries) — as até 20 linhas
        #      da página atual, nunca uma query por linha
        #   7-11. SELECT unidade/categoria/tipo/grau_prioridade/classificacao
        #      — opções dos 5 <select> de domínio da barra de filtro
        #   12. SELECT reuniões — opções do seletor do modo reunião
        #   13-14. SELECTs de permissão para o CTA de criação exclusivo do editor
        #   15-17. BEGIN / UPDATE django_session / COMMIT — sessão salva a
        #      cada request (SESSION_SAVE_EVERY_REQUEST=True)
        with self.assertNumQueries(19):
            resposta = self.client.get(reverse("pca:tabela"))
        self.assertEqual(resposta.status_code, 200)

    def test_assertnumqueries_fragmento_htmx_mais_barato(self):
        # A resposta HTMX não reconstrói os <select> da barra de filtro
        # Só os 9 grupos "estruturais" acima e os 2 checks de
        # permissão, sem as 5 de vocabulário.
        with self.assertNumQueries(12):
            resposta = self.client.get(
                reverse("pca:tabela"), HTTP_HX_REQUEST="true"
            )
        self.assertEqual(resposta.status_code, 200)


class TestFiltrosMultiSelecao(TransactionTestCase):
    """Motor de multi-seleção de
    `apps/pca/filtros.py` (RED antes da implementação; ver <behavior> do
    PLAN.md). Mesmo `setUp` de `TestFiltrosTabela`: import real via
    `importar_pca`, `serialized_rollback=True`."""

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
            email="leitor-multi@pca.local", password="x-forte-123"
        )
        self.client.force_login(self.usuario)

    def _processo(self, item_pca, **kwargs):
        """Mesma fábrica de `TestFiltrosTabela._processo`
        (não há herança entre as duas classes; ver docstring lá)."""
        exercicio = Exercicio.objects.get(ano=2026)
        defaults = {
            "descricao_objeto": f"Fixture estado/situação {item_pca}",
            "tipo": Tipo.objects.first(),
            "categoria": Categoria.objects.first(),
            "unidade_organizacional": Unidade.objects.first(),
        }
        defaults.update(kwargs)
        return Processo.objects.create(
            item_pca=item_pca, exercicio=exercicio, **defaults
        )

    def test_uo_multiplo_combina_por_or(self):
        ids_uo = list(
            Processo.objects.filter(exercicio__ano=2026)
            .values_list("unidade_organizacional_id", flat=True)
            .distinct()
            .order_by("unidade_organizacional_id")[:2]
        )
        self.assertEqual(len(ids_uo), 2, "dado real precisa ter ao menos 2 UOs distintas")
        esperado = Processo.objects.filter(
            exercicio__ano=2026, unidade_organizacional_id__in=ids_uo
        ).count()
        resposta = self.client.get(
            reverse("pca:tabela"), {"uo": [str(ids_uo[0]), str(ids_uo[1])]}
        )
        self.assertEqual(resposta.context["pagina"].paginator.count, esperado)

    def test_valor_invalido_na_lista_e_descartado_sem_quebrar_os_demais(self):
        id_valida = (
            Processo.objects.filter(exercicio__ano=2026)
            .values_list("unidade_organizacional_id", flat=True)
            .first()
        )
        esperado = Processo.objects.filter(
            exercicio__ano=2026, unidade_organizacional_id=id_valida
        ).count()
        resposta = self.client.get(
            reverse("pca:tabela"),
            {"uo": [str(id_valida), "abc", "-1"]},
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.context["pagina"].paginator.count, esperado)

    def test_prioridade_multi_mistura_sentinela_com_id_real(self):
        id_real = (
            Processo.objects.filter(
                exercicio__ano=2026, grau_prioridade__isnull=False
            )
            .values_list("grau_prioridade_id", flat=True)
            .first()
        )
        self.assertIsNotNone(id_real, "dado real precisa ter grau_prioridade preenchido")
        esperado = Processo.objects.filter(exercicio__ano=2026).filter(
            Q(grau_prioridade__isnull=True) | Q(grau_prioridade_id=id_real)
        ).count()
        resposta = self.client.get(
            reverse("pca:tabela"),
            {"prioridade": ["nao_classificado", str(id_real)]},
        )
        self.assertEqual(resposta.context["pagina"].paginator.count, esperado)

    def test_mes_multi_mistura_sentinela_com_inteiro(self):
        numero_mes = (
            Processo.objects.filter(
                exercicio__ano=2026, mes_previsto__isnull=False
            )
            .values_list("mes_previsto", flat=True)
            .first()
        )
        self.assertIsNotNone(numero_mes, "dado real precisa ter mes_previsto preenchido")
        esperado = Processo.objects.filter(exercicio__ano=2026).filter(
            Q(mes_previsto__isnull=True) | Q(mes_previsto=numero_mes)
        ).count()
        resposta = self.client.get(
            reverse("pca:tabela"),
            {"mes": ["sem_mes", str(numero_mes)]},
        )
        self.assertEqual(resposta.context["pagina"].paginator.count, esperado)

    def test_querystring_filtros_um_par_por_valor(self):
        get_unico = QueryDict(mutable=True)
        get_unico.setlist("uo", ["3"])
        self.assertEqual(querystring_filtros(get_unico), "uo=3")

        get_dois = QueryDict(mutable=True)
        get_dois.setlist("uo", ["3", "7"])
        self.assertEqual(querystring_filtros(get_dois), "uo=3&uo=7")

    def test_querystring_filtros_aceita_lista_como_override(self):
        """`?situacao=`/`?estado=` combinam via override em lista/tupla."""
        get = QueryDict(mutable=True)
        self.assertEqual(
            querystring_filtros(
                get,
                situacao=(Situacao.ATRASADO.value, Situacao.EM_TRAMITACAO.value),
            ),
            "situacao=atrasado&situacao=em_tramitacao",
        )

        # Guarda de regressão: a chamada escalar pré-existente continua
        # devolvendo exatamente o mesmo par único de antes desta extensão.
        self.assertEqual(
            querystring_filtros(get, estado=Estado.CANCELADO.value),
            "estado=cancelado",
        )

    def test_situacao_invalida_misturada_a_lista_valida_e_descartada_pelo_orm(self):
        """Defesa em profundidade — um token fora de `Situacao.values`
        misturado a uma combinação válida não pode vazar para o ORM,
        quebrar a página nem ser refletido sem escape. A barreira é
        `_situacoes_validas`/`queryset_filtrado`."""
        self._processo(980, situacao=Situacao.ATRASADO)
        self._processo(981, situacao=Situacao.EM_TRAMITACAO)
        esperado = (
            Processo.objects.para_listagem()
            .filter(
                exercicio__ano=2026,
                situacao_efetiva__in=[
                    Situacao.ATRASADO.value,
                    Situacao.EM_TRAMITACAO.value,
                ],
            )
            .count()
        )
        self.assertGreaterEqual(esperado, 2)
        resposta = self.client.get(
            reverse("pca:tabela"),
            {
                "situacao": [
                    Situacao.ATRASADO.value,
                    Situacao.EM_TRAMITACAO.value,
                    "<script>alert(1)</script>",
                ]
            },
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.context["pagina"].paginator.count, esperado)
        # A página legitimamente contém `<script>` (ECharts via
        # json_script) — o que não pode aparecer é o payload malicioso
        # refletido sem escape (Django autoescapa `<`/`>` por padrão em
        # templates).
        conteudo = resposta.content.decode("utf-8")
        self.assertNotIn("<script>alert(1)</script>", conteudo)
        self.assertNotIn("alert(1)", conteudo)

    def test_tags_ativas_uma_tag_por_valor_removivel_independente(self):
        id1, id2 = list(
            Processo.objects.filter(exercicio__ano=2026)
            .values_list("unidade_organizacional_id", flat=True)
            .distinct()
            .order_by("unidade_organizacional_id")[:2]
        )
        get = QueryDict(mutable=True)
        get.setlist("uo", [str(id1), str(id2)])
        tags = [tag for tag in tags_ativas(get) if tag["chave"] == "uo"]
        self.assertEqual(len(tags), 2)
        querystrings = [tag["querystring"] for tag in tags]
        for qs in querystrings:
            contem_id1 = f"uo={id1}" in qs
            contem_id2 = f"uo={id2}" in qs
            # cada tag remove só o próprio valor: preserva exatamente o
            # OUTRO id na querystring, nunca os dois nem nenhum.
            self.assertNotEqual(contem_id1, contem_id2)
        self.assertTrue(any(f"uo={id1}" in qs for qs in querystrings))
        self.assertTrue(any(f"uo={id2}" in qs for qs in querystrings))


class TestFiltrosEstadoSituacao(TransactionTestCase):
    """`?estado=`/`?situacao=` na barra de filtro global. Mesmo `setUp`
    de `TestFiltrosTabela`/`TestFiltrosMultiSelecao` (import real,
    `serialized_rollback=True`), mas os processos importados nascem só
    com os defaults do schema (`estado=ativo`, `situacao=no_prazo`)
    porque o importador não grava os 3 eixos. Os casos não-default usados
    abaixo são fabricados diretamente via ORM."""

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
            email="leitor-estado-situacao@pca.local", password="x-forte-123"
        )
        self.client.force_login(self.usuario)
        self.exercicio = Exercicio.objects.get(ano=2026)
        self.tipo = Tipo.objects.first()
        self.categoria = Categoria.objects.first()
        self.unidade = Unidade.objects.first()

    def _processo(self, item_pca, **kwargs):
        defaults = {
            "descricao_objeto": f"Fixture estado/situação {item_pca}",
            "tipo": self.tipo,
            "categoria": self.categoria,
            "unidade_organizacional": self.unidade,
        }
        defaults.update(kwargs)
        return Processo.objects.create(
            item_pca=item_pca, exercicio=self.exercicio, **defaults
        )

    def test_estado_filtra_e_preserva_demais_filtros_ativos(self):
        """`?estado=cancelado` filtra `estado="cancelado"`, combinando
        por AND com `?uo=`, mesmo padrão de `?tipo=`. `esperado` é medido
        pela mesma query que a view usa — a fixture de exemplo pode já
        ter algum item CANCELADO na mesma UO, então o teste nunca
        hardcoda "1", só prova que a view bate com o ORM e que a
        `outra_uo`/o item ATIVO ficam de fora."""
        outra_uo = Unidade.objects.exclude(pk=self.unidade.pk).first()
        cancelado_na_uo_alvo = self._processo(
            920, estado=Estado.CANCELADO, unidade_organizacional=self.unidade
        )
        cancelado_fora = self._processo(
            921, estado=Estado.CANCELADO, unidade_organizacional=outra_uo
        )
        ativo_na_uo_alvo = self._processo(
            922, estado=Estado.ATIVO, unidade_organizacional=self.unidade
        )

        esperado = Processo.objects.filter(
            exercicio__ano=2026,
            estado=Estado.CANCELADO.value,
            unidade_organizacional_id=self.unidade.pk,
        ).count()
        self.assertGreaterEqual(esperado, 1)
        resposta = self.client.get(
            reverse("pca:tabela"),
            {"estado": Estado.CANCELADO.value, "uo": self.unidade.pk},
        )
        pagina = resposta.context["pagina"]
        self.assertEqual(pagina.paginator.count, esperado)
        ids = {p.pk for p in pagina.object_list}
        self.assertIn(cancelado_na_uo_alvo.pk, ids)
        self.assertNotIn(cancelado_fora.pk, ids)
        self.assertNotIn(ativo_na_uo_alvo.pk, ids)

    def test_situacao_filtra_por_situacao_efetiva_incluindo_no_prazo_vencido(self):
        """`?situacao=atrasado` filtra por `situacao_efetiva`: inclui
        tanto os gravados `atrasado` quanto os `no_prazo` corrigidos na
        leitura por `prazo_entrega` vencido."""
        hoje = localdate()
        gravado_atrasado = self._processo(930, situacao=Situacao.ATRASADO)
        no_prazo_vencido = self._processo(
            931,
            situacao=Situacao.NO_PRAZO,
            prazo_entrega=hoje - timedelta(days=1),
        )
        no_prazo_em_dia = self._processo(
            932,
            situacao=Situacao.NO_PRAZO,
            prazo_entrega=hoje + timedelta(days=1),
        )

        resposta = self.client.get(
            reverse("pca:tabela"), {"situacao": Situacao.ATRASADO.value}
        )
        ids = {p.pk for p in resposta.context["pagina"].object_list}
        while resposta.context["pagina"].has_next():
            resposta = self.client.get(
                reverse("pca:tabela"),
                {
                    "situacao": Situacao.ATRASADO.value,
                    "pagina": resposta.context["pagina"].next_page_number(),
                },
            )
            ids.update(p.pk for p in resposta.context["pagina"].object_list)

        self.assertIn(gravado_atrasado.pk, ids)
        self.assertIn(no_prazo_vencido.pk, ids)
        self.assertNotIn(no_prazo_em_dia.pk, ids)

    def test_querystring_e_tags_ativas_para_estado_e_situacao(self):
        """Teste 3 do <behavior> — `querystring_filtros` inclui as chaves
        novas corretamente; `tags_ativas` gera uma tag removível por valor
        selecionado, mesmo padrão multivalor de `uo`/`tipo`."""
        get = QueryDict(mutable=True)
        self.assertEqual(
            querystring_filtros(get, estado=Estado.CANCELADO.value),
            "estado=cancelado",
        )
        self.assertEqual(
            querystring_filtros(get, situacao=[Situacao.ATRASADO.value]),
            "situacao=atrasado",
        )

        get_ativo = QueryDict(mutable=True)
        get_ativo.setlist("estado", [Estado.CANCELADO.value])
        get_ativo.setlist("situacao", [Situacao.ATRASADO.value])
        tags = tags_ativas(get_ativo)
        tag_estado = next(tag for tag in tags if tag["chave"] == "estado")
        tag_situacao = next(tag for tag in tags if tag["chave"] == "situacao")
        self.assertEqual(tag_estado["rotulo"], "Estado")
        self.assertEqual(tag_estado["valor"], "Cancelado")
        self.assertNotIn("estado=cancelado", tag_estado["querystring"])
        self.assertEqual(tag_situacao["rotulo"], "Situação")
        self.assertEqual(tag_situacao["valor"], "Atrasado")
        self.assertNotIn("situacao=atrasado", tag_situacao["querystring"])

    def test_status_chave_antiga_e_ignorada_silenciosamente(self):
        """`?status=cancelado` (chave antiga) não produz filtro nenhum:
        `status` saiu de `PARAMETROS_FILTRO`, e qualquer chave fora da
        allowlist é ignorada silenciosamente, como qualquer parâmetro
        desconhecido."""
        self._processo(940, estado=Estado.CANCELADO)
        resposta = self.client.get(
            reverse("pca:tabela"), {"status": "cancelado"}
        )
        self.assertEqual(resposta.status_code, 200)
        # Nenhum filtro foi aplicado: a contagem é a mesma de uma requisição
        # sem filtro nenhum (30 importados + 1 fixture criada acima).
        self.assertEqual(resposta.context["pagina"].paginator.count, 31)


class TestFiltroRecebidoGelicIntervalo(TransactionTestCase):
    """Filtro de intervalo de datas para `data_recebimento_gelic`,
    extensão de `filtros.py`. Mesmo `setUp` de
    `TestFiltrosEstadoSituacao`: import real, `serialized_rollback=True`,
    fixtures fabricadas diretamente via ORM."""

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
            email="leitor-recebido-gelic@pca.local", password="x-forte-123"
        )
        self.client.force_login(self.usuario)
        self.exercicio = Exercicio.objects.get(ano=2026)
        self.tipo = Tipo.objects.first()
        self.categoria = Categoria.objects.first()
        self.unidade = Unidade.objects.first()

    def _processo(self, item_pca, **kwargs):
        defaults = {
            "descricao_objeto": f"Fixture recebido-gelic {item_pca}",
            "tipo": self.tipo,
            "categoria": self.categoria,
            "unidade_organizacional": self.unidade,
        }
        defaults.update(kwargs)
        return Processo.objects.create(
            item_pca=item_pca, exercicio=self.exercicio, **defaults
        )

    def test_data_valida_converte_ou_devolve_none_sem_lancar_excecao(self):
        """Teste 1 do <behavior> — `_data_valida` nunca lança exceção."""
        from apps.pca.filtros import _data_valida

        self.assertEqual(_data_valida("2026-04-01"), date(2026, 4, 1))
        self.assertIsNone(_data_valida("lixo"))
        self.assertIsNone(_data_valida(""))
        self.assertIsNone(_data_valida(None))

    def test_recebido_de_e_recebido_ate_filtram_intervalo_fechado(self):
        """Teste 2 do <behavior> — só `recebido_de`, e os dois lados juntos
        (intervalo fechado)."""
        antes = self._processo(950, data_recebimento_gelic=date(2026, 3, 15))
        dentro = self._processo(951, data_recebimento_gelic=date(2026, 4, 15))
        depois = self._processo(952, data_recebimento_gelic=date(2026, 7, 1))

        resposta = self.client.get(
            reverse("pca:tabela"), {"recebido_de": "2026-04-01"}
        )
        ids = {p.pk for p in resposta.context["pagina"].object_list}
        while resposta.context["pagina"].has_next():
            resposta = self.client.get(
                reverse("pca:tabela"),
                {
                    "recebido_de": "2026-04-01",
                    "pagina": resposta.context["pagina"].next_page_number(),
                },
            )
            ids.update(p.pk for p in resposta.context["pagina"].object_list)
        self.assertNotIn(antes.pk, ids)
        self.assertIn(dentro.pk, ids)
        self.assertIn(depois.pk, ids)

        resposta = self.client.get(
            reverse("pca:tabela"),
            {"recebido_de": "2026-04-01", "recebido_ate": "2026-06-30"},
        )
        ids = {p.pk for p in resposta.context["pagina"].object_list}
        while resposta.context["pagina"].has_next():
            resposta = self.client.get(
                reverse("pca:tabela"),
                {
                    "recebido_de": "2026-04-01",
                    "recebido_ate": "2026-06-30",
                    "pagina": resposta.context["pagina"].next_page_number(),
                },
            )
            ids.update(p.pk for p in resposta.context["pagina"].object_list)
        self.assertNotIn(antes.pk, ids)
        self.assertIn(dentro.pk, ids)
        self.assertNotIn(depois.pk, ids)

    def test_querystring_filtros_com_recebido_de_e_ate_preserva_demais_filtros(self):
        """Teste 3 do <behavior> — `querystring_filtros` produz as duas
        chaves, preservando um filtro já ativo (`uo`)."""
        get = QueryDict(mutable=True)
        get.setlist("uo", [str(self.unidade.pk)])
        qs = querystring_filtros(
            get, recebido_de="2026-04-01", recebido_ate="2026-06-30"
        )
        self.assertIn("recebido_de=2026-04-01", qs)
        self.assertIn("recebido_ate=2026-06-30", qs)
        self.assertIn(f"uo={self.unidade.pk}", qs)

    def test_tags_ativas_gera_uma_tag_combinada_removivel(self):
        """Teste 4 do <behavior> — uma única tag, cuja querystring de
        remoção não contém nenhuma das duas chaves."""
        get = QueryDict(mutable=True)
        get["recebido_de"] = "2026-04-01"
        tags = tags_ativas(get)
        tags_intervalo = [t for t in tags if t["chave"] == "recebido_de"]
        self.assertEqual(len(tags_intervalo), 1)
        tag = tags_intervalo[0]
        self.assertEqual(tag["rotulo"], "Recebido no Gelic")
        self.assertNotIn("recebido_de", tag["querystring"])
        self.assertNotIn("recebido_ate", tag["querystring"])

    def test_data_malformada_no_get_nao_derruba_a_pagina(self):
        """Teste 5 do <behavior> — `?recebido_de=abacate` não derruba /tabela
        (200, filtro simplesmente ignorado — mesmo comportamento de
        `_id_valido` inválido hoje)."""
        resposta = self.client.get(
            reverse("pca:tabela"), {"recebido_de": "abacate"}
        )
        self.assertEqual(resposta.status_code, 200)


class TestFiltroVigenciaFimIntervalo(TransactionTestCase):
    """Filtro de intervalo de datas absolutas para `vigencia_fim`,
    extensão de `filtros.py` (mesmo molde de
    `TestFiltroRecebidoGelicIntervalo`) — mas aqui a comparação é por
    data absoluta (com ano), porque vencimento de contrato é uma data de
    calendário real, não um recorte recorrente."""

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
            email="leitor-vigencia-fim@pca.local", password="x-forte-123"
        )
        self.client.force_login(self.usuario)
        self.exercicio = Exercicio.objects.get(ano=2026)
        self.tipo = Tipo.objects.first()
        self.categoria = Categoria.objects.first()
        self.unidade = Unidade.objects.first()

    def _processo(self, item_pca, **kwargs):
        defaults = {
            "descricao_objeto": f"Fixture vigencia-fim {item_pca}",
            "tipo": self.tipo,
            "categoria": self.categoria,
            "unidade_organizacional": self.unidade,
        }
        defaults.update(kwargs)
        return Processo.objects.create(
            item_pca=item_pca, exercicio=self.exercicio, **defaults
        )

    def test_vigencia_fim_de_e_ate_filtram_intervalo_fechado_por_data_absoluta(self):
        """Ao contrário de recebido_de/recebido_ate (24-04), o ANO importa:
        um processo com vigencia_fim no mesmo mês/dia mas ano diferente do
        intervalo pedido fica FORA."""
        antes = self._processo(960, vigencia_fim=date(2025, 4, 15))
        dentro = self._processo(961, vigencia_fim=date(2026, 4, 15))
        depois = self._processo(962, vigencia_fim=date(2026, 7, 1))

        resposta = self.client.get(
            reverse("pca:tabela"), {"vigencia_fim_de": "2026-01-01"}
        )
        ids = {p.pk for p in resposta.context["pagina"].object_list}
        while resposta.context["pagina"].has_next():
            resposta = self.client.get(
                reverse("pca:tabela"),
                {
                    "vigencia_fim_de": "2026-01-01",
                    "pagina": resposta.context["pagina"].next_page_number(),
                },
            )
            ids.update(p.pk for p in resposta.context["pagina"].object_list)
        self.assertNotIn(antes.pk, ids)
        self.assertIn(dentro.pk, ids)
        self.assertIn(depois.pk, ids)

        resposta = self.client.get(
            reverse("pca:tabela"),
            {"vigencia_fim_de": "2026-04-01", "vigencia_fim_ate": "2026-04-30"},
        )
        ids = {p.pk for p in resposta.context["pagina"].object_list}
        while resposta.context["pagina"].has_next():
            resposta = self.client.get(
                reverse("pca:tabela"),
                {
                    "vigencia_fim_de": "2026-04-01",
                    "vigencia_fim_ate": "2026-04-30",
                    "pagina": resposta.context["pagina"].next_page_number(),
                },
            )
            ids.update(p.pk for p in resposta.context["pagina"].object_list)
        self.assertNotIn(antes.pk, ids)
        self.assertIn(dentro.pk, ids)
        self.assertNotIn(depois.pk, ids)

    def test_querystring_filtros_com_vigencia_fim_de_e_ate_preserva_demais_filtros(self):
        get = QueryDict(mutable=True)
        get.setlist("uo", [str(self.unidade.pk)])
        qs = querystring_filtros(
            get, vigencia_fim_de="2026-04-01", vigencia_fim_ate="2026-04-30"
        )
        self.assertIn("vigencia_fim_de=2026-04-01", qs)
        self.assertIn("vigencia_fim_ate=2026-04-30", qs)
        self.assertIn(f"uo={self.unidade.pk}", qs)

    def test_tags_ativas_gera_uma_tag_combinada_removivel(self):
        get = QueryDict(mutable=True)
        get["vigencia_fim_de"] = "2026-04-01"
        tags = tags_ativas(get)
        tags_intervalo = [t for t in tags if t["chave"] == "vigencia_fim_de"]
        self.assertEqual(len(tags_intervalo), 1)
        tag = tags_intervalo[0]
        self.assertEqual(tag["rotulo"], "Vencimento do contrato")
        self.assertNotIn("vigencia_fim_de", tag["querystring"])
        self.assertNotIn("vigencia_fim_ate", tag["querystring"])

    def test_data_malformada_no_get_nao_derruba_a_pagina(self):
        resposta = self.client.get(
            reverse("pca:tabela"), {"vigencia_fim_de": "abacate"}
        )
        self.assertEqual(resposta.status_code, 200)


class TestPainelDeFiltrosSobDemanda(TransactionTestCase):
    """`pca:tabela` usa a casca da skill dsgov: o form de busca/filtros
    fica sempre visível, sem painel para abrir/fechar. `pca:analise`
    também é relatório puro, sem `_filtros.html`. Só
    `pca:calendario`/`pca:resumo_uo` continuam cobertas pelo teste
    abaixo."""

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
            email="leitor-filtros@pca.local", password="x-forte-123"
        )
        self.client.force_login(self.usuario)

    def test_tabela_migrada_nao_tem_mais_painel_de_filtros_sob_demanda(self):
        """`pca:tabela` não tem o botão "Filtros (N)"/painel — o form de
        busca/filtros compostos fica sempre visível."""
        corpo = self.client.get(reverse("pca:tabela")).content.decode()
        self.assertNotIn("filtrosAbertos", corpo)
        self.assertNotIn("Filtros (0)", corpo)
        self.assertIn('id="filtros-processos"', corpo)

    def test_calendario_e_resumo_uo_tambem_nao_tem_mais_painel_sob_demanda(self):
        # Nenhuma tela do sistema tem painel "Filtros (N)" — todas
        # recarregam a página inteira, sem filtro global algum.
        for rota in (
            reverse("pca:calendario"),
            reverse("pca:resumo_uo"),
        ):
            with self.subTest(rota=rota):
                corpo = self.client.get(rota).content.decode()
                self.assertNotIn("filtrosAbertos", corpo)
                self.assertNotIn("Filtros (0)", corpo)


class TestGradeDeFiltrosReorganizada(TestCase):
    """Grade de filtros em 3 blocos (faixa 1: Busca+Unidade; faixa 2:
    Situação+Mês previsto; "Mais filtros" recolhível com os 12 campos
    restantes), aberto sozinho quando algum desses 12 campos está ativo.
    `TestCase` (fixture leve por ORM direto): não depende do XLSX real,
    só do form renderizado."""

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.usuario = User.objects.create_user(
            email="grade-filtros@example.com", password="senha-segura"
        )
        cls.unidade = Unidade.objects.create(nome="Presidência")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.tipo = Tipo.objects.create(nome="Aquisição")
        # `modalidade`/`desde_reuniao` só ganham `name=` no HTML quando o
        # `br-select`/`<select>` tem ao menos uma opção (widget custom,
        # zero opções = zero inputs renderizados) — sem estas fixtures, os
        # campos desaparecem do form e o teste de "nenhum name= removido"
        # dá falso positivo.
        Modalidade.objects.create(nome="Pregão eletrônico")
        cls.exercicio = Exercicio.objects.get(ano=2026)
        Reuniao.objects.create(data=date(2026, 1, 15), exercicio=cls.exercicio)
        cls.processo = Processo.objects.create(
            item_pca=1,
            descricao_objeto="Processo de teste da grade de filtros",
            tipo=cls.tipo,
            categoria=cls.categoria,
            unidade_organizacional=cls.unidade,
            exercicio=cls.exercicio,
        )

    def test_mais_filtros_fechado_sem_filtro_secundario_ativo(self):
        self.client.force_login(self.usuario)
        conteudo = self.client.get(reverse("pca:tabela")).content.decode()
        self.assertIn("Mais filtros", conteudo)
        self.assertNotIn('id="acordeao-mais-filtros-conteudo"><div class="item" active', conteudo)
        inicio = conteudo.index('id="acordeao-mais-filtros"')
        fim = conteudo.index("</form>", inicio)
        trecho = conteudo[inicio:fim]
        self.assertNotIn("active", trecho)

    def test_mais_filtros_abre_sozinho_com_filtro_secundario_ativo(self):
        self.client.force_login(self.usuario)
        conteudo = self.client.get(
            reverse("pca:tabela"), {"categoria": str(self.categoria.pk)}
        ).content.decode()
        inicio = conteudo.index('id="acordeao-mais-filtros"')
        fim = conteudo.index("</form>", inicio)
        trecho = conteudo[inicio:fim]
        self.assertIn("active", trecho)
        self.assertIn('aria-expanded="true"', trecho)

    def test_mais_filtros_abre_sozinho_com_estado_ativo(self):
        # `estado` é um campo real do form; entra em "Mais filtros"
        # como os demais 11 campos secundários.
        self.client.force_login(self.usuario)
        conteudo = self.client.get(
            reverse("pca:tabela"), {"estado": "cancelado"}
        ).content.decode()
        inicio = conteudo.index('id="acordeao-mais-filtros"')
        fim = conteudo.index("</form>", inicio)
        trecho = conteudo[inicio:fim]
        self.assertIn("active", trecho)

    def test_nenhum_name_de_campo_do_form_foi_removido_ou_renomeado(self):
        self.client.force_login(self.usuario)
        conteudo = self.client.get(reverse("pca:tabela")).content.decode()
        for nome in (
            "q",
            "uo",
            "categoria",
            "tipo",
            "prioridade",
            "classificacao",
            "modalidade",
            "estado",
            "situacao",
            "mes",
            "desde_reuniao",
            "legados",
            "recebido_de",
            "recebido_ate",
            "vigencia_fim_de",
            "vigencia_fim_ate",
        ):
            with self.subTest(campo=nome):
                self.assertIn(f'name="{nome}"', conteudo)

    def test_faixa_1_tem_busca_e_unidade_faixa_2_tem_situacao_e_mes(self):
        self.client.force_login(self.usuario)
        conteudo = self.client.get(reverse("pca:tabela")).content.decode()
        inicio_mais_filtros = conteudo.index('id="acordeao-mais-filtros"')
        cabecalho = conteudo[: conteudo.index('id="filtros-processos"')]
        corpo_filtros = conteudo[
            conteudo.index('id="filtros-processos"') : inicio_mais_filtros
        ]
        self.assertIn('name="q"', corpo_filtros)
        self.assertIn('name="uo"', corpo_filtros)
        self.assertIn('name="situacao"', corpo_filtros)
        self.assertIn('name="mes"', corpo_filtros)
        self.assertNotIn('name="categoria"', corpo_filtros)

    def test_form_de_filtros_inclui_o_form_de_colunas(self):
        # Bidirecional com `hx-include="#filtros-processos"` do form de
        # colunas — mudar um filtro preserva a seleção de colunas atual.
        self.client.force_login(self.usuario)
        conteudo = self.client.get(reverse("pca:tabela")).content.decode()
        self.assertIn('hx-include="#form-colunas"', conteudo)


class TestCondicaoLegendaTabela(TransactionTestCase):
    """`condicao_legenda` é um parâmetro canônico de `/tabela`,
    compartilhando `apps.pca.filtros.q_condicao_legenda` com o "+n" do
    calendário: união (nunca interseção) entre Cancelados e as situações
    efetivas marcadas."""

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
            email="condicao-legenda@pca.local", password="x-forte-123"
        )
        self.client.force_login(self.usuario)
        self.exercicio = Exercicio.objects.get(ano=2026)
        base = Processo.objects.first()
        self.tipo = base.tipo
        self.categoria = base.categoria
        self.unidade = base.unidade_organizacional

    def _processo(self, item_pca, **kwargs):
        defaults = {
            "descricao_objeto": f"Fixture condicao_legenda {item_pca}",
            "tipo": self.tipo,
            "categoria": self.categoria,
            "unidade_organizacional": self.unidade,
        }
        defaults.update(kwargs)
        return Processo.objects.create(
            item_pca=item_pca, exercicio=self.exercicio, **defaults
        )

    def _todos_os_itens(self, **params):
        # `item_pca` alto (fixtures sintéticas acima de 900) cai fora da
        # primeira página (20 por padrão) — pagina até o fim para não
        # confundir "não filtrado" com "está na página seguinte".
        itens = set()
        pagina = 1
        while True:
            resposta = self.client.get(
                reverse("pca:tabela"), {**params, "pagina": pagina}
            )
            objetos = resposta.context["pagina"].object_list
            if not objetos:
                break
            itens.update(p.item_pca for p in objetos)
            if not resposta.context["pagina"].has_next():
                break
            pagina += 1
        return itens

    def test_ausente_nao_filtra_nada(self):
        total_sem_filtro = self.client.get(
            reverse("pca:tabela")
        ).context["pagina"].paginator.count
        self.assertEqual(total_sem_filtro, Processo.objects.count())

    def test_isolar_situacao_filtra_so_aquela_situacao_efetiva(self):
        self._processo(
            930, estado=Estado.ATIVO, situacao=Situacao.ATRASADO,
            prazo_entrega=localdate() - timedelta(days=1),
        )
        self._processo(931, estado=Estado.ATIVO, situacao=Situacao.NO_PRAZO)
        itens = self._todos_os_itens(condicao_legenda="situacao:atrasado")
        self.assertIn(930, itens)
        self.assertNotIn(931, itens)
        for processo in Processo.objects.para_listagem():
            if processo.item_pca in itens:
                self.assertEqual(processo.situacao_efetiva, Situacao.ATRASADO.value)

    def test_uniao_cancelado_ou_atrasado_nunca_intersecao(self):
        cancelado = self._processo(940, estado=Estado.CANCELADO)
        atrasado = self._processo(
            941, estado=Estado.ATIVO, situacao=Situacao.ATRASADO,
            prazo_entrega=localdate() - timedelta(days=1),
        )
        no_prazo = self._processo(942, estado=Estado.ATIVO, situacao=Situacao.NO_PRAZO)

        itens = set()
        pagina = 1
        while True:
            resposta = self.client.get(
                reverse("pca:tabela"),
                QueryDict(
                    "condicao_legenda=estado%3Acancelado"
                    "&condicao_legenda=situacao%3Aatrasado"
                    f"&pagina={pagina}"
                ),
            )
            objetos = resposta.context["pagina"].object_list
            if not objetos:
                break
            itens.update(p.item_pca for p in objetos)
            if not resposta.context["pagina"].has_next():
                break
            pagina += 1
        self.assertIn(cancelado.item_pca, itens)
        self.assertIn(atrasado.item_pca, itens)
        self.assertNotIn(no_prazo.item_pca, itens)
        # Nenhum processo cancelado E atrasado ao mesmo tempo é exigido —
        # cancelado sozinho já qualifica (união, não interseção).
        self.assertFalse(
            Processo.objects.para_listagem()
            .filter(pk__in=[cancelado.pk, atrasado.pk])
            .exclude(estado=Estado.CANCELADO)
            .exclude(situacao_efetiva=Situacao.ATRASADO.value)
            .exists()
        )

    def test_sentinela_nenhum_nao_devolve_nenhum_processo(self):
        resposta = self.client.get(
            reverse("pca:tabela"), {"condicao_legenda": "nenhum"}
        )
        self.assertEqual(resposta.context["pagina"].paginator.count, 0)

    def test_token_invalido_cai_no_padrao_sem_filtro(self):
        resposta = self.client.get(
            reverse("pca:tabela"), {"condicao_legenda": "eixo-inexistente:valor"}
        )
        self.assertEqual(
            resposta.context["pagina"].paginator.count, Processo.objects.count()
        )

    def test_condicao_legenda_sobrevive_a_querystring_filtros(self):
        resposta = self.client.get(
            reverse("pca:tabela"), {"condicao_legenda": "situacao:atrasado"}
        )
        self.assertIn(
            "condicao_legenda=situacao%3Aatrasado",
            querystring_filtros(resposta.wsgi_request.GET),
        )
