from datetime import date, timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils.timezone import localdate

from django.db.models import Q
from django.http import QueryDict

from apps.catalogo.models import Categoria, Exercicio, Modalidade, Tipo, Unidade
from apps.pca.filtros import opcoes_unidade_sei, querystring_filtros, tags_ativas
from apps.pca.models import Estado, Processo, Reuniao, Situacao

ARQUIVO_REAL = "Modelo_de_Controle_.xlsx"


class TestFiltrosTabela(TransactionTestCase):
    """O contrato observável de `/tabela` e de `queryset_filtrado`
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
        # QA de segurança 30/09/2026 (achado B1) — este módulo testa o
        # contrato de ordenação/filtro em si (persona equivalente ao grupo
        # `editor`, mesmo padrão de `test_ordenacao_tabela.py`), não o gate
        # de `pca.view_acompanhamento`: sem a permissão, `ordenacao_valida`
        # passaria a recusar `prazo_inicial`/`dias_atraso` por GATE, o que
        # mascararia o contrato de ordenação em si.
        self.usuario.user_permissions.add(
            Permission.objects.get(
                codename="view_acompanhamento", content_type__app_label="pca"
            )
        )
        self.client.force_login(self.usuario)

    def _processo(self, item_pca, **kwargs):
        """Fase 17 — fábrica de fixture para os testes que
        migraram de `?status=` para `?estado=`/`?situacao=`: os 149
        processos importados nascem só com os defaults do schema
        (`estado=ativo`, `situacao=no_prazo`) porque o
        importador ainda não foi migrado para os 3 eixos — os
        casos não-default usados abaixo são fabricados diretamente via ORM."""
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
        self.assertEqual(resposta.context["pagina"].paginator.count, 149)
        self.assertEqual(
            resposta.context["soma_filtrada"], Decimal("162642475.66")
        )
        conteudo = resposta.content.decode("utf-8")
        # Fase 26 — "N processos" no título da
        # `br-table` (`table-title`), não mais "Mostrando X–Y de Z
        # processos" do rodapé antigo.
        self.assertIn("149 processos", conteudo)
        # Soma formatada em pt-BR pelo filtro `moeda`, nunca
        # `{{ valor }}` cru Armadilha 22).
        self.assertIn("162.642.475,66", conteudo)

    # Fase 17 — `test_distribuicao_dourada_por_status_
    # permanece_intacta_no_campo_cru` removido, não adaptado:
    # a própria premissa do teste ("o campo `status` segue intocado no
    # schema até o plano") deixa de existir neste plano — a coluna
    # crua não é mais consultável pelo ORM (`RemoveField`). A distribuição
    # golden 53/39/24/18/15 era sobre o enum `Status`, que também não
    # existe mais; não há substituto 1:1 no eixo `situacao` porque o
    # backfill datado espalha `nao_iniciado` entre NO_PRAZO/ATRASADO
    # conforme a data corrente, tornando a golden-number antiga não
    # reprodutível pelo novo modelo.

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
        """Fase 17 — migrado de `?status=` para
        `?situacao=` (o exemplo original combinava status+uo; o eixo
        Situação é o sucessor direto). Os 149 processos importados nascem
        todos com `situacao=no_prazo` (default, importador não migrado
        ainda); a combinação AND é provada com fixtures
        próprias, uma delas fora da UO alvo (deve ficar de fora do
        resultado)."""
        uo_alvo = Unidade.objects.first()
        outra_uo = Unidade.objects.exclude(pk=uo_alvo.pk).first()
        self._processo(
            960,
            situacao=Situacao.EM_TRAMITACAO,
            unidade_organizacional=uo_alvo,
        )
        self._processo(
            961,
            situacao=Situacao.EM_TRAMITACAO,
            unidade_organizacional=outra_uo,
        )
        esperado = Processo.objects.filter(
            exercicio__ano=2026,
            situacao=Situacao.EM_TRAMITACAO.value,
            unidade_organizacional_id=uo_alvo.pk,
        ).count()
        self.assertEqual(esperado, 1)
        resposta = self.client.get(
            reverse("pca:tabela"),
            {
                "situacao": Situacao.EM_TRAMITACAO.value,
                "uo": uo_alvo.pk,
            },
        )
        self.assertEqual(resposta.context["pagina"].paginator.count, esperado)

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

    def test_sentinel_sem_mes_isola_item_137(self):
        resposta = self.client.get(reverse("pca:tabela"), {"mes": "sem_mes"})
        pagina = resposta.context["pagina"]
        self.assertEqual(pagina.paginator.count, 1)
        self.assertEqual(pagina.object_list[0].item_pca, 137)

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
        self.assertEqual(resposta.context["pagina"].paginator.count, 149)

    # --- ordenação -----------------------------------------------------

    def test_ordenacao_ignora_parametro_fora_da_allowlist(self):
        # Fase 29 — `justificativa` entrou na
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
        self.assertEqual(len(objetos), 149)
        self.assertEqual(objetos[-1].item_pca, 137)
        self.assertIsNone(objetos[-1].mes_previsto)

    def test_ordenacao_de_prazo_e_dias_usa_allowlist_e_annotations(self):
        """Fase 11 (Fase 29) — prazo_inicial
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
            descricao_objeto="Ordenação por prazo (Fase 11)",
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

        objetos_n = self._todas_paginas(ordenar="n_prorrogacoes", dir="desc")
        processo_65 = next(p for p in objetos_n if p.item_pca == 65)
        self.assertGreaterEqual(processo_65.n_prorrogacoes, 1)

        resposta_efetivo = self.client.get(
            reverse("pca:tabela"), {"ordenar": "prazo_efetivo", "dir": "asc"}
        )
        self.assertEqual(resposta_efetivo.context["campo_ordenacao"], "prazo_efetivo")
        self.assertEqual(
            resposta_efetivo.context["pagina"].object_list[0].item_pca,
            vencido.item_pca,
        )

    def test_ordenacao_descendente_de_prazo_poe_sem_prazo_por_ultimo(self):
        """`prazo_inicial` (Fase 29,
        substitui `prazo_entrega` na allowlist)/`prazo_efetivo` são
        colunas de data ANULÁVEIS; sem `nulls_last` nos DOIS sentidos (a
        mesma disciplina do `mes_previsto`), o PostgreSQL põe NULL
        primeiro num ORDER BY DESC — "quem está mais atrasado" mostraria em
        primeiro lugar justamente quem não tem prazo nenhum."""
        exercicio = Exercicio.objects.get(ano=2026)
        hoje = localdate()
        futuro = Processo.objects.create(
            item_pca=903,
            exercicio=exercicio,
            descricao_objeto="xc684 — prazo futuro, deve vir primeiro no desc",
            tipo=Tipo.objects.first(),
            categoria=Categoria.objects.first(),
            unidade_organizacional=Unidade.objects.first(),
            prazo_entrega=hoje + timedelta(days=3650),
        )
        sem_prazo = Processo.objects.create(
            item_pca=904,
            exercicio=exercicio,
            descricao_objeto="xc684 — sem prazo algum, nunca pode vencer o futuro",
            tipo=Tipo.objects.first(),
            categoria=Categoria.objects.first(),
            unidade_organizacional=Unidade.objects.first(),
            prazo_entrega=None,
        )

        objetos = self._todas_paginas(ordenar="prazo_inicial", dir="desc")
        indices = {p.item_pca: indice for indice, p in enumerate(objetos)}
        self.assertLess(indices[futuro.item_pca], indices[sem_prazo.item_pca])

    # --- Fase 11 ------------------------
    #
    # Fase 26 — `test_tabela_expoe_prazo_planejado_
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
    # a linha nova não tem mais esse id (nenhum swap OOB por linha).

    # --- paginação -------------------------------------------------------

    def test_paginacao_preserva_filtro_ativo_no_link(self):
        """Fase 17 — migrado de `?status=` para
        `?estado=` (TAMANHO_PAGINA=20, precisa de mais de uma página)."""
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
        """Fase 17 — migrado de `?status=` para
        `?estado=`.

        24.1-01 (Grupo B) — a asserção fixa (18) presumia zero CANCELADOs
        na fixture real antes deste teste criar os seus. Confirmado por
        reprodução isolada: `ARQUIVO_REAL` já importa 18 processos
        CANCELADO (mesmo golden number de
        `test_dashboard.TestDashboardGoldenNumbers.
        test_distribuicao_dourada_por_status_na_rosca`), então o total sob
        `?estado=cancelado` dobra para 36 — não é duplicação de linhas por
        JOIN (confirmado: `queryset_filtrado`/`estado__in` não faz join
        multiplicador). O teste passa a medir a baseline ANTES de criar as
        18 novas, em vez de presumir zero."""
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
        # Fase 26 — título da `br-table` reescrito:
        # "N processo(s)" (`table-title`), não mais "Mostrando X–Y de Z
        # processos" do rodapé antigo.
        self.assertIn(f"{total} processos", conteudo)

    # --- estado vazio ------------------------------------------------

    def test_estado_vazio_quando_filtro_nao_bate_nada(self):
        """Fase 15 — `aguardando_dfd` saiu do domínio (zero instâncias).
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

    # --- tags removíveis ------------------------------------------

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

    # Fase 26 —
    # `test_link_nao_classificado_aplica_filtro_de_primeira_classe` removido:
    # `prioridade`/`classificacao` deixaram de ser colunas visíveis da
    # tabela (máximo 6 colunas, `telas/listagem.md`), então a célula-badge
    # clicável "Não classificado" que gerava o href
    # `?prioridade=nao_classificado` não existe mais. "Não classificado"
    # continua sendo filtro de primeira classe (preservado) — agora
    # como opção normal dos `br-checkbox` de `filtros_form.prioridade`/
    # `filtros_form.classificacao` no form de busca/filtros, não mais um
    # atalho de 1 clique a partir da célula.

    # --- HTMX / OOB ------------------------------------------

    def test_requisicao_htmx_retorna_fragmento_sem_oob(self):
        """Fase 26 — inverte a asserção antiga: a
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
        """inverte a asserção antiga (o teste se
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
        self.assertLess(resposta_seguindo.context["pagina"].paginator.count, 149)

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
        #   3-4. SELECTs de permissão para o CTA de criação exclusivo do editor
        #   5. SELECT exercício corrente (resolver_exercicio)
        #   6. SELECT COUNT(*) — total geral (contador "de N processos")
        #   7. SELECT SUM(valor_estimado) — soma do resultado filtrado
        #   8. SELECT COUNT(*) — Paginator.count sobre o queryset filtrado
        #   9-10. SELECT grau_prioridade/classificacao — opções de 2 dos
        #      <select> de domínio da barra de filtro
        #   11. SELECT DISTINCT unidade_sei_atual — opções do filtro
        #      "Unidade no SEI" (`opcoes_unidade_sei`)
        #   12-15. SELECT unidade/categoria/tipo/modalidade — os demais
        #      <select> de domínio
        #   16. SELECT reuniões — opções do seletor do modo reunião
        #   17. SELECT ... (select_related + Subqueries) — as até 20 linhas
        #      da página atual, nunca uma query por linha
        #   18-20. BEGIN / UPDATE django_session / COMMIT — sessão salva a
        #      cada request (SESSION_SAVE_EVERY_REQUEST=True)
        #   21. SELECT pca_preferenciacolunas — colunas gravadas na conta
        #      do usuário
        #   (a 22ª, larguras de coluna, saiu com a grade estilo
        #   Excel)
        with self.assertNumQueries(21):
            resposta = self.client.get(reverse("pca:tabela"))
        self.assertEqual(resposta.status_code, 200)

    def test_assertnumqueries_fragmento_htmx_mais_barato(self):
        # A resposta HTMX não reconstrói os <select> da barra de filtro
        #só os 9 grupos "estruturais" acima e os 2 checks de
        # permissão, sem as 5 de vocabulário (+1: preferência de colunas na
        # conta).
        with self.assertNumQueries(13):
            resposta = self.client.get(
                reverse("pca:tabela"), HTTP_HX_REQUEST="true"
            )
        self.assertEqual(resposta.status_code, 200)


class TestFiltrosMultiSelecao(TransactionTestCase):
    """Gj7/ motor de multi-seleção de
    `apps/pca/filtros.py` (RED antes da implementação; ver <behavior>). Mesmo `setUp` de `TestFiltrosTabela`: import real via
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
        """Fase 17 — mesma fábrica de `TestFiltrosTabela._processo`
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
        """Fase 17 — migrado de `?status=` para
        `?situacao=`/`?estado=` (o exemplo original combinava
        vigente+a_renovar; `situacao` é o eixo multi-valor sucessor direto
        para o mesmo mecanismo de override em lista/tupla)."""
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
        """Fase 17 — migrado de `?status=` para
        `?situacao=` (do threat_model, agora -01):
        defesa em profundidade — um token fora de `Situacao.values`
        misturado a uma combinação válida não pode vazar para o ORM, quebrar
        a página nem ser refletido sem escape. A barreira é
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
        # A página legitimamente contém `<script>` (tema,
        # ECharts via json_script) — o que não pode aparecer é o PAYLOAD
        # malicioso refletido sem escape (Django autoescapa `<`/`>` por
        # padrão em templates).
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
    """Fase 17 — `?estado=`/`?situacao=`
    substituem `?status=` na barra de filtro global. Mesmo `setUp` de
    `TestFiltrosTabela`/`TestFiltrosMultiSelecao` (import real,
    `serialized_rollback=True`), mas os 149 processos importados nascem só
    com os defaults do schema (`estado=ativo`, `situacao=no_prazo` — Plano
    17-01) porque o importador ainda não foi migrado para os 3 eixos (Plano
    17-04, fora do escopo desta task). Os casos não-default usados abaixo
    são fabricados diretamente via ORM, mesmo padrão de
    `test_ordenacao_de_prazo_e_dias_usa_allowlist_e_annotations`."""

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
        """Teste 1 do <behavior> — `?estado=cancelado` filtra
        `estado="cancelado"`, combinando por AND com `?uo=`, mesmo padrão
        de `?tipo=` (já multi-valor)."""
        outra_uo = Unidade.objects.exclude(pk=self.unidade.pk).first()
        cancelado_na_uo_alvo = self._processo(
            920, estado=Estado.CANCELADO, unidade_organizacional=self.unidade
        )
        self._processo(
            921, estado=Estado.CANCELADO, unidade_organizacional=outra_uo
        )
        self._processo(922, estado=Estado.ATIVO, unidade_organizacional=self.unidade)

        resposta = self.client.get(
            reverse("pca:tabela"),
            {"estado": Estado.CANCELADO.value, "uo": self.unidade.pk},
        )
        pagina = resposta.context["pagina"]
        self.assertEqual(pagina.paginator.count, 1)
        self.assertEqual(pagina.object_list[0].pk, cancelado_na_uo_alvo.pk)

    def test_situacao_filtra_por_situacao_efetiva_incluindo_no_prazo_vencido(self):
        """Teste 2 do <behavior> — `?situacao=atrasado` filtra por
        `situacao_efetiva`: inclui tanto os gravados `atrasado` quanto os
        `no_prazo` corrigidos na leitura por `prazo_entrega` vencido
        ("nunca exibir/contar NO PRAZO vencido")."""
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
        """Teste 4 do <behavior> (regressão negativa) — `?status=cancelado`
        (chave antiga) não produz filtro nenhum: `status` saiu de
        `PARAMETROS_FILTRO`, e qualquer chave fora da allowlist é ignorada
        silenciosamente, como qualquer parâmetro desconhecido."""
        self._processo(940, estado=Estado.CANCELADO)
        resposta = self.client.get(
            reverse("pca:tabela"), {"status": "cancelado"}
        )
        self.assertEqual(resposta.status_code, 200)
        # Nenhum filtro foi aplicado: a contagem é a mesma de uma requisição
        # sem filtro nenhum (149 importados + 1 fixture criada acima).
        self.assertEqual(resposta.context["pagina"].paginator.count, 150)


class TestFiltroRecebidoGelicIntervalo(TransactionTestCase):
    """Fase 24 — filtro de intervalo de datas para
    `data_recebimento_gelic`, extensão autorizada de `filtros.py` (ver
    `<contexto_de_execucao_critico>`). Mesmo `setUp` de
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
    """Fase 24 — filtro de intervalo de datas
    ABSOLUTAS para `vigencia_fim`, extensão autorizada de `filtros.py`
    (mesmo molde de `TestFiltroRecebidoGelicIntervalo`) — mas
    ao contrário daquele, aqui a comparação é por data absoluta (com ano),
    porque vencimento de contrato é uma data de calendário real, não um
    recorte recorrente."""

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
    """(final, A02 parcial) — o painel de filtros deixou
    de abrir sozinho a partir de 768px (da Fase 23 revogada): agora
    começa fechado em qualquer largura, com um único botão "Filtros (N)"
    (contagem de tags ativas) em toda visão que tem painel de filtros.

    Fase 26 — `pca:tabela` migrou para a
    casca do padrão DSGov: o painel `_filtros.html` (Alpine, botão
    "Filtros (N)") sai desta tela por completo — o form de busca/filtros
    fica SEMPRE visível, sem painel para abrir/fechar (`telas/listagem.md`:
    "nunca um painel lateral"). `test_painel_comeca_fechado_e_botao_mostra_
    zero_sem_filtro`/`test_botao_conta_as_tags_ativas` (mecânica do botão
    específicos de `pca:tabela`) saem.

    Fase 26 — `pca:analise` também migrou (relatório
    puro, sem `_filtros.html`) e `pca:dashboard` foi apagada (`core:inicio` funde Início/Dashboard). Só `pca:calendario`/
    `pca:resumo_uo` (frente 5, ainda não migradas) continuam cobertas pelo
    teste abaixo."""

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
        """`pca:tabela` não tem mais o botão "Filtros (N)"/painel
        Alpine — o form de busca/filtros compostos fica sempre visível."""
        corpo = self.client.get(reverse("pca:tabela")).content.decode()
        self.assertNotIn("filtrosAbertos", corpo)
        self.assertNotIn("Filtros (0)", corpo)
        self.assertIn('id="filtros-processos"', corpo)

    def test_calendario_e_resumo_uo_tambem_nao_tem_mais_painel_sob_demanda(self):
        # Fase 26 — `pca:calendario`/`pca:resumo_uo`
        # migraram nesta fase: eram as 2 últimas telas com o painel
        # Alpine "Filtros (N)". Nenhuma tela do sistema tem mais esse
        # painel — as duas passam a recarregar a página inteira, sem
        # filtro global algum (não só sem o botão sob demanda).
        for rota in (
            reverse("pca:calendario"),
            reverse("pca:resumo_uo"),
        ):
            with self.subTest(rota=rota):
                corpo = self.client.get(rota).content.decode()
                self.assertNotIn("filtrosAbertos", corpo)
                self.assertNotIn("Filtros (0)", corpo)


class TestGradeDeFiltrosReorganizada(TestCase):
    """Fase 28 grade de filtros em 3
    blocos (faixa 1: Busca+Unidade; faixa 2: Situação+Mês previsto;
    "Mais filtros" recolhível com os 12 campos restantes), aberto sozinho
    quando algum desses 12 campos está ativo. `TestCase` (fixture leve por
    ORM direto): não depende do XLSX real, só do form renderizado."""

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

    def test_mais_filtros_continua_fechado_com_filtro_secundario_ativo(self):
        """(pedido do usuário, 22/09/2026) — revoga o
        abre-sozinho de o painel nunca nasce aberto; quem sinaliza
        filtro secundário ativo é a contagem no rótulo do botão."""
        self.client.force_login(self.usuario)
        conteudo = self.client.get(
            reverse("pca:tabela"), {"categoria": str(self.categoria.pk)}
        ).content.decode()
        inicio = conteudo.index('id="acordeao-mais-filtros"')
        fim = conteudo.index("</form>", inicio)
        trecho = conteudo[inicio:fim]
        self.assertNotIn('active="active"', trecho)
        self.assertNotIn('aria-expanded="true"', trecho)
        self.assertIn('aria-expanded="false"', trecho)
        self.assertIn("Mais filtros (1)", trecho)

    def test_mais_filtros_conta_estado_no_rotulo_sem_abrir(self):
        # (deviation) — `estado` não constava na enumeração de
        # EJAMENTO.md, mas é um campo real do form; entra
        # em "Mais filtros" como os demais 11 campos secundários. Quick
        # Conta no rótulo, sem abrir o painel.
        self.client.force_login(self.usuario)
        conteudo = self.client.get(
            reverse("pca:tabela"), {"estado": "cancelado"}
        ).content.decode()
        inicio = conteudo.index('id="acordeao-mais-filtros"')
        fim = conteudo.index("</form>", inicio)
        trecho = conteudo[inicio:fim]
        self.assertNotIn('active="active"', trecho)
        self.assertIn("Mais filtros (1)", trecho)

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
        # Mais `#estado-vista` (Lista | Tabela).
        self.assertIn('hx-include="#form-colunas, #estado-vista"', conteudo)


class TestFiltroUnidadeSei(TestCase):
    """Filtro "Unidade no SEI" (`unidade_sei_atual`),
    escalar (não entra em `CHAVES_MULTIVALOR`), igualdade simples (uma
    sigla só por processo, a do recebimento mais recente), e a coluna
    opcional "Unidade SEI" (`?colunas=unidade_sei_atual`). `TestCase`
    (fixture leve por ORM direto), mesmo molde de
    `TestGradeDeFiltrosReorganizada`."""

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.usuario = User.objects.create_user(
            email="filtro-unidade-sei@example.com", password="senha-segura"
        )
        cls.unidade = Unidade.objects.create(nome="Presidência")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.tipo = Tipo.objects.create(nome="Aquisição")
        cls.exercicio, _ = Exercicio.objects.get_or_create(ano=2026)

        def _processo(item, unidade_sei_atual):
            return Processo.objects.create(
                item_pca=item,
                descricao_objeto=f"Fixture unidade-sei {item}",
                tipo=cls.tipo,
                categoria=cls.categoria,
                unidade_organizacional=cls.unidade,
                exercicio=cls.exercicio,
                unidade_sei_atual=unidade_sei_atual,
            )

        cls.processo_gelic = _processo(801, "GELIC")
        cls.processo_projur = _processo(802, "PROJUR")
        # Fronteira de sigla — "GELIC-X" não pode casar com o filtro
        # "GELIC" (igualdade simples já garante isso, mas o caso continua
        # cobrindo a fronteira).
        cls.processo_fronteira = _processo(804, "GELIC-X")
        cls.processo_vazio = _processo(805, "")

    def test_filtro_por_igualdade_simples_nunca_casa_fronteira_de_sigla(self):
        self.client.force_login(self.usuario)
        resposta = self.client.get(
            reverse("pca:tabela"), {"unidade_sei": "GELIC"}
        )
        ids = {p.pk for p in resposta.context["pagina"].object_list}
        self.assertIn(self.processo_gelic.pk, ids)
        self.assertNotIn(self.processo_projur.pk, ids)
        self.assertNotIn(self.processo_fronteira.pk, ids)

    def test_chip_aparece_em_tags_ativas(self):
        get = QueryDict(mutable=True)
        get["unidade_sei"] = "GELIC"
        tags = tags_ativas(get)
        chip = [t for t in tags if t["chave"] == "unidade_sei"]
        self.assertEqual(len(chip), 1)
        self.assertEqual(chip[0]["rotulo"], "Unidade no SEI")
        self.assertEqual(chip[0]["valor"], "GELIC")

    def test_querystring_filtros_remove_so_unidade_sei_preserva_uo_ativo(self):
        get = QueryDict(mutable=True)
        get["unidade_sei"] = "GELIC"
        get.setlist("uo", [str(self.unidade.pk)])
        qs = querystring_filtros(get, excluir="unidade_sei")
        self.assertNotIn("unidade_sei", qs)
        self.assertIn(f"uo={self.unidade.pk}", qs)

    def test_valor_com_mais_de_80_caracteres_e_ignorado(self):
        self.client.force_login(self.usuario)
        resposta = self.client.get(
            reverse("pca:tabela"), {"unidade_sei": "X" * 90}
        )
        self.assertEqual(resposta.status_code, 200)
        ids = {p.pk for p in resposta.context["pagina"].object_list}
        self.assertIn(self.processo_gelic.pk, ids)
        self.assertIn(self.processo_vazio.pk, ids)

    def test_coluna_unidade_sei_aparece_na_tabela(self):
        self.client.force_login(self.usuario)
        resposta = self.client.get(
            reverse("pca:tabela"),
            {"colunas": ["item_pca", "unidade_sei_atual"]},
        )
        conteudo = resposta.content.decode()
        self.assertIn('data-th="Unidade SEI"', conteudo)
        # Processo 805 (vazio) exibe o traço padrão de `ou_traco` dentro da
        # própria linha (o template quebra linha entre a tag e o valor —
        # nunca `>—<` colado).
        inicio_linha = conteudo.index(f'id="item-{self.processo_vazio.pk}"')
        fim_linha = conteudo.index("</tr>", inicio_linha)
        self.assertIn("—", conteudo[inicio_linha:fim_linha])

    def test_opcoes_unidade_sei_devolve_siglas_distintas_ordenadas_sem_split(self):
        opcoes = opcoes_unidade_sei(self.exercicio)
        self.assertEqual(
            opcoes, sorted({"GELIC", "PROJUR", "GELIC-X"})
        )


class TestCondicaoLegendaTabela(TransactionTestCase):
    """Fase 28 — `condicao_legenda` vira um
    parâmetro canônico de `/tabela` (antes só interno do calendário),
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


class TestIdsHostis(TestFiltrosTabela):
    """QA 30/09/2026 (fuzz B1) — um ID de 20+ dígitos em qualquer filtro de
    lista levantava `OverflowError: Python int too large to convert to
    SQLite INTEGER` dentro do `__in=`, sem proteção de `_id_valido`."""

    def test_id_gigante_em_qualquer_filtro_nunca_derruba_a_tabela(self):
        for parametro in (
            "uo", "categoria", "tipo", "prioridade", "classificacao", "modalidade",
        ):
            with self.subTest(parametro=parametro):
                resposta = self.client.get(
                    reverse("pca:tabela"),
                    {parametro: "99999999999999999999"},
                )
                self.assertEqual(resposta.status_code, 200)
