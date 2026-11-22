"""Testes das 3 telas novas de Análises (Fase 36, spec
documento interno de desenho §6/
§7). Import real (`AnaliseBase`/`AnaliseTelasBase`, mesmo padrão
de `test_analise.py`/`test_estrutura_paginas.py`): `TransactionTestCase`,
`serialized_rollback=True`, `call_command("importar_pca", ...)` em
`setUp()`. Nenhum teste toca `apps.pca.sei.coletor` (robô SEI, Fase 32) —
fora de escopo desta frente."""

import time
from datetime import date, timedelta
from decimal import Decimal
from io import StringIO
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.messages import get_messages
from django.core.management import call_command
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils.timezone import localdate

from apps.catalogo.models import Categoria, Exercicio, SituacaoExercicio, Tipo, Unidade
from apps.pca.models import (
    Acompanhamento,
    CenarioFluxo,
    Estado,
    Processo,
    RegimeExecucao,
    Situacao,
)
from apps.pca.projecao import virada
from apps.pca.regras_situacao import regime_presumido_migracao
from apps.pca.tests.test_estrutura_paginas import _coletar

ARQUIVO_REAL = "Modelo_de_Controle_.xlsx"


class AnaliseTelasBase(TransactionTestCase):
    serialized_rollback = True

    def setUp(self):
        call_command(
            "importar_pca",
            ARQUIVO_REAL,
            "--usuario=importador@pca.local",
            "--exercicio=2026",
            stdout=StringIO(),
        )
        # /configurar_grupos — garante view_acompanhamento
        # no grupo "editor" (que já tem editar_pca desde a migration 0004);
        # "visualizador" fica sem as duas, mesmo padrão de
        # test_permissoes_acompanhamento.py.
        call_command("configurar_grupos", stdout=StringIO())
        User = get_user_model()
        self.editor = User.objects.create_user(
            email="editor-analise-telas@pca.local", password="senha-segura"
        )
        self.editor.groups.add(Group.objects.get(name="editor"))
        # Fase 37 (spec §7) — as 3 telas estratégicas passam a
        # exigir pca.ver_analises, concedida pelo grupo "dirigentes"
        # (migração 0028 do plano). self.editor continua sendo a
        # persona usada por TODA a suíte pré-existente desta fase para
        # acessar Fluxo/Estatísticas/Prazos com sucesso — sem também
        # pertencer a "dirigentes", cada teste dessa suíte que espera 200
        # passaria a receber 403 só por causa desta restrição nova, uma
        # regressão que não é o objetivo do plano (restringir quem
        # NÃO tem a permissão, não quebrar quem já testava o conteúdo das
        # telas). "visualizador" deliberadamente NÃO entra em
        # "dirigentes" — é a persona dos testes de acesso restrito abaixo.
        self.editor.groups.add(Group.objects.get(name="dirigentes"))
        self.visualizador = User.objects.create_user(
            email="visualizador-analise-telas@pca.local", password="senha-segura"
        )
        self.visualizador.groups.add(Group.objects.get(name="visualizador"))
        self.client = Client(HTTP_X_FORWARDED_PROTO="https")


class TestTelasRespondemDuzentosEUmH1(AnaliseTelasBase):
    """As 3 telas novas respondem 200 (persona `editor`, tem
    `view_acompanhamento`+`editar_pca`, vê as 3) com exatamente 1 `<h1>` e
    todo `[data-grafico]` com `role="img"`+`aria-label` (graficos.md)."""

    def test_as_3_telas_respondem_200_com_um_h1(self):
        self.client.force_login(self.editor)
        urls = {
            "fluxo": reverse("pca:analise_fluxo"),
            "estatisticas": reverse("pca:analise_estatisticas"),
            "prazos": reverse("pca:analise_prazos"),
        }
        for nome_tela, url in urls.items():
            with self.subTest(tela=nome_tela):
                resposta = self.client.get(url, HTTP_HOST="testserver")
                self.assertEqual(
                    resposta.status_code, 200, f"{nome_tela}: GET {url} != 200"
                )
                conteudo = resposta.content.decode()
                coletor = _coletar(conteudo)
                self.assertEqual(
                    coletor.h1_count,
                    1,
                    f"{nome_tela}: {coletor.h1_count} <h1> (deve haver exatamente 1)",
                )
                self.assertLessEqual(
                    coletor.primary_count,
                    1,
                    f"{nome_tela}: {coletor.primary_count} br-button primary (no máximo 1)",
                )
                for atributos in coletor.graficos:
                    self.assertEqual(
                        atributos.get("role"), "img", f'{nome_tela}: [data-grafico] sem role="img"'
                    )
                    self.assertTrue(
                        atributos.get("aria-label"), f"{nome_tela}: [data-grafico] sem aria-label"
                    )


class TestTrilhaTuplas(AnaliseTelasBase):
    """`navegacao.trilha_padrao` devolvia dict
    (`{"rotulo": ..., "url": ...}`), mas `dsgov/_breadcrumb.html` (congelado
    pelo padrão DSGov) faz `{% for rotulo, url in trilha %}`: iterar um dict dá as
    CHAVES, então a trilha renderizava literalmente "rotulo > rotulo" com
    `href="url"`. Cobre as 4 telas afetadas (Fluxo de caixa, Estatísticas,
    Prazos, Calendário) com GET real."""

    def test_trilha_nao_vaza_chaves_de_dict_e_mostra_o_rotulo_da_tela(self):
        self.client.force_login(self.editor)
        casos = (
            (reverse("pca:analise_fluxo"), "Fluxo de caixa"),
            (reverse("pca:analise_estatisticas"), "Estatísticas"),
            (reverse("pca:analise_prazos"), "Prazos"),
            (reverse("pca:calendario"), "Calendário"),
        )
        for url, rotulo_tela in casos:
            with self.subTest(url=url):
                resposta = self.client.get(
                    url, {"exercicio": "2026"}, HTTP_HOST="testserver"
                )
                self.assertEqual(resposta.status_code, 200)
                conteudo = resposta.content.decode()
                self.assertNotIn(">rotulo<", conteudo, f"{url}: vazou a chave 'rotulo'")
                self.assertNotIn('href="url"', conteudo, f"{url}: vazou a chave 'url'")
                self.assertIn(
                    f'aria-current="page">{rotulo_tela}<',
                    conteudo,
                    f"{url}: rótulo da tela ausente do item ativo da trilha",
                )
                self.assertIn(
                    f'href="{reverse("raiz")}?exercicio=2026">PCA 2026</a>',
                    conteudo,
                    f"{url}: ancestral 'PCA 2026' ausente ou sem link",
                )


class TestFluxoCsv(AnaliseTelasBase):
    def test_csv_responde_text_csv_com_cabecalho_e_ao_menos_uma_linha_de_dado(self):
        self.client.force_login(self.editor)
        resposta = self.client.get(reverse("pca:analise_fluxo_csv"), HTTP_HOST="testserver")
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta["Content-Type"].startswith("text/csv"))
        conteudo = b"".join(resposta.streaming_content).decode("utf-8-sig")
        linhas = conteudo.splitlines()
        self.assertEqual(linhas[0], "item_pca;competencia;camada;valor;origem")
        # Processo.item_pca=1 tem valor_contratado (2200,00, vigência
        # 11/02/2026-10/02/2027) na fixture real — a projeção sempre gera
        # ao menos a camada "contratado" para ele.
        self.assertGreater(len(linhas), 1, "CSV sem nenhuma linha de parcela")


class TestHorizonteUnicoEKpiComPeriodoLiteral(AnaliseTelasBase):
    """M11 — gráfico anual, tabela UO × ano e
    KPI "5 anos" cobrem o MESMO horizonte (exercicio..exercicio+5, 6 anos);
    o KPI declara o período literal que soma."""

    def test_projecao_2027_2031_e_tabela_uo_com_6_anos(self):
        self.client.force_login(self.editor)
        resposta = self.client.get(
            reverse("pca:analise_fluxo"),
            {"exercicio": "2026"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 200)
        conteudo = resposta.content.decode()
        # Resumo em blocos sem sobreposição que somam o horizonte: restante do exercício · ano seguinte · 4 anos.
        self.assertIn("Restante de 2026", conteudo)
        self.assertIn("2028–2031", conteudo)
        self.assertIn("2026–2031", conteudo)
        self.assertIn("Fluxo de caixa anual — 2026–2031", conteudo)
        for ano in range(2026, 2032):
            self.assertIn(f">{ano}<", conteudo, f"cabeçalho {ano} ausente da tabela UO/gráfico anual")


class TestPrazosPermissoes(AnaliseTelasBase):
    def test_prazos_403_sem_view_acompanhamento(self):
        self.client.force_login(self.visualizador)
        resposta = self.client.get(reverse("pca:analise_prazos"), HTTP_HOST="testserver")
        self.assertEqual(resposta.status_code, 403)

    def test_menu_analises_tem_4_filhos_para_editor_e_1_para_visualizador(self):
        """Fase 37 (spec §7) — `self.editor` (agora também no
        grupo "dirigentes", ver `AnaliseTelasBase.setUp`) continua vendo os
        4 filhos (Painel/Fluxo/Estatísticas/Prazos). `self.visualizador`
        (sem `ver_analises` nem `view_acompanhamento`) passa a ver só
        "Painel" — Fluxo/Estatísticas somem por `ver_analises`, Prazos por
        `ver_analises` E `view_acompanhamento` (antes desta fase,
        visualizador via 3 filhos; a restrição nova cobre Fluxo/
        Estatísticas também)."""
        from core.menu import itens as itens_menu
        from django.test import RequestFactory

        rf = RequestFactory()

        request_editor = rf.get("/")
        request_editor.user = self.editor
        pasta_editor = next(
            i for i in itens_menu(request_editor) if i.get("rotulo") == "Análises"
        )
        self.assertEqual(len(pasta_editor["filhos"]), 4)

        request_visualizador = rf.get("/")
        request_visualizador.user = self.visualizador
        pasta_visualizador = next(
            i for i in itens_menu(request_visualizador) if i.get("rotulo") == "Análises"
        )
        self.assertEqual(len(pasta_visualizador["filhos"]), 1)
        self.assertEqual(pasta_visualizador["filhos"][0]["rotulo"], "Painel")


class TestRenovarPRG(AnaliseTelasBase):
    def test_post_renovar_sem_editar_pca_devolve_403(self):
        self.client.force_login(self.visualizador)
        processo = Processo.objects.filter(
            exercicio__ano=2026, vigencia_fim__isnull=False
        ).first()
        resposta = self.client.post(
            reverse("pca:analise_prazos_renovar", args=[2026, processo.item_pca]),
            {"destino": "false"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 403)

    def test_post_renovar_com_editar_pca_redireciona_e_grava(self):
        self.client.force_login(self.editor)
        processo = Processo.objects.filter(
            exercicio__ano=2026, vigencia_fim__isnull=False
        ).first()
        valor_antes = processo.renovacao_prevista
        destino = "false" if valor_antes else "true"
        resposta = self.client.post(
            reverse("pca:analise_prazos_renovar", args=[2026, processo.item_pca]),
            {"destino": destino},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 302)
        self.assertTrue(resposta.url.startswith(reverse("pca:analise_prazos")))
        mensagens = list(get_messages(resposta.wsgi_request))
        self.assertTrue(any("renovação prevista" in str(m) for m in mensagens))
        processo.refresh_from_db()
        self.assertEqual(processo.renovacao_prevista, destino == "true")


class TestDesvioPercentualPontosPercentuais(AnaliseTelasBase):
    """(M08) — caso de aceite de `melhorias.md`: estimado
    100/contratado 120 tem de aparecer como 20,0% na tela de Estatísticas,
    nunca 0,2% (bug do desvio armazenado como fração crua)."""

    def test_estimado_100_contratado_120_mostra_20_0_por_cento(self):
        from apps.catalogo.models import Modalidade

        modalidade_isolada = Modalidade.objects.create(nome="Modalidade Teste M08")
        processo_alvo = Processo.objects.filter(exercicio__ano=2026).first()
        # Isola o pool geral de desvios: só `processo_alvo` fica com
        # `valor_estimado` preenchido — todos os demais saem do cálculo de
        # desvio (`estatistica.valores` pula item sem `valor_estimado`),
        # sem afetar os outros blocos da tela.
        # `managers.py` bloqueia `.update()` em massa,
        # `bulk_update_with_history`) — instância por instância.
        for processo in Processo.objects.exclude(pk=processo_alvo.pk):
            processo.valor_estimado = None
            processo.save(update_fields=["valor_estimado"])
        processo_alvo.valor_estimado = Decimal("100.00")
        processo_alvo.valor_contratado = Decimal("120.00")
        processo_alvo.modalidade = modalidade_isolada
        processo_alvo.save()

        self.client.force_login(self.editor)
        resposta = self.client.get(
            reverse("pca:analise_estatisticas"),
            {"exercicio": "2026"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 200)
        conteudo = resposta.content.decode()
        self.assertIn("20,0%", conteudo)
        self.assertNotIn("0,2%", conteudo)


class TestMigracaoRegimeExecucaoHeuristica(AnaliseTelasBase):
    """Fase 36 — a migração de dados 0027 preenche
    `regime_execucao` pela heurística de vigência (limiar 11 meses,
    `regras_situacao.regime_presumido_migracao`) nos processos JÁ
    existentes no banco no momento da migração; um processo real
    RE-IMPORTADO em `setUp()` nasce com `regime_execucao=None` de novo
    (import da planilha ignora o campo) — este teste prova a
    heurística em si contra dados REAIS de vigência da fixture (não
    sintéticos), confirmando a wiring que a migração usa continua correta."""

    def test_heuristica_preenche_continuado_para_vigencia_de_11_meses_ou_mais(self):
        candidatos = Processo.objects.filter(
            exercicio__ano=2026,
            vigencia_inicio__isnull=False,
            vigencia_fim__isnull=False,
        )
        self.assertTrue(
            candidatos.exists(),
            "fixture real sem nenhum processo com vigência preenchida",
        )
        testado = False
        for processo in candidatos:
            dias = (processo.vigencia_fim - processo.vigencia_inicio).days
            if dias >= 340:  # folga segura acima do limiar de 11 meses
                testado = True
                self.assertEqual(
                    regime_presumido_migracao(
                        processo.vigencia_inicio, processo.vigencia_fim
                    ),
                    "continuado",
                    f"item {processo.item_pca}: vigência de {dias} dias deveria presumir 'continuado'",
                )
        self.assertTrue(
            testado, "fixture real sem item com vigência >= 11 meses para testar a heurística"
        )


class TestAcessoRestritoAnalisesEstrategicas(AnaliseTelasBase):
    """Fase 37 (spec §7) — `pca.ver_analises`
    nas 3 telas estratégicas e na ação de renovação: `self.visualizador`
    (sem a permissão) recebe 403 explícito (nunca um 302 silencioso para
    login — já está autenticado); `self.editor` (no grupo "dirigentes",
    ver `AnaliseTelasBase.setUp`) continua acessando normalmente."""

    def test_visualizador_recebe_403_nas_5_rotas_estrategicas(self):
        self.client.force_login(self.visualizador)
        processo = Processo.objects.filter(
            exercicio__ano=2026, vigencia_fim__isnull=False
        ).first()
        casos = (
            ("GET", reverse("pca:analise_fluxo"), None),
            ("GET", reverse("pca:analise_fluxo_csv"), None),
            ("GET", reverse("pca:analise_estatisticas"), None),
            ("GET", reverse("pca:analise_prazos"), None),
            (
                "POST",
                reverse("pca:analise_prazos_renovar", args=[2026, processo.item_pca]),
                {"destino": "true"},
            ),
        )
        for metodo, url, dados in casos:
            with self.subTest(metodo=metodo, url=url):
                if metodo == "GET":
                    resposta = self.client.get(url, HTTP_HOST="testserver")
                else:
                    resposta = self.client.post(url, dados, HTTP_HOST="testserver")
                self.assertEqual(
                    resposta.status_code,
                    403,
                    f"{metodo} {url}: {resposta.status_code} != 403 (visualizador sem ver_analises)",
                )

    def test_dirigente_acessa_as_5_rotas_estrategicas_normalmente(self):
        """Grupo "dirigentes" puro (sem `editar_pca`/`view_acompanhamento`
        do grupo "editor") — só `ver_analises`. Prova que `ver_analises`
        sozinho basta para as 3 rotas GET; `analise_prazos` (que também
        exige `view_acompanhamento`) e o POST de renovação (que também
        exige `editar_pca`) continuam 403 para este usuário — a permissão
        nova SOMA-SE às exigências existentes, não as substitui."""
        User = get_user_model()
        dirigente = User.objects.create_user(
            email="dirigente-analise-telas@pca.local", password="senha-segura"
        )
        dirigente.groups.add(Group.objects.get(name="dirigentes"))
        self.client.force_login(dirigente)

        resposta_fluxo = self.client.get(
            reverse("pca:analise_fluxo"), HTTP_HOST="testserver"
        )
        self.assertEqual(resposta_fluxo.status_code, 200)

        resposta_csv = self.client.get(
            reverse("pca:analise_fluxo_csv"), HTTP_HOST="testserver"
        )
        self.assertEqual(resposta_csv.status_code, 200)

        resposta_estatisticas = self.client.get(
            reverse("pca:analise_estatisticas"), HTTP_HOST="testserver"
        )
        self.assertEqual(resposta_estatisticas.status_code, 200)

        resposta_prazos = self.client.get(
            reverse("pca:analise_prazos"), HTTP_HOST="testserver"
        )
        self.assertEqual(
            resposta_prazos.status_code,
            403,
            "dirigente sem view_acompanhamento deveria continuar 403 em Prazos",
        )

    def test_editor_com_dirigentes_acessa_prazos_e_renova(self):
        """`self.editor` combina `view_acompanhamento`/`editar_pca`
        (grupo "editor") com `ver_analises` (grupo "dirigentes",
        `AnaliseTelasBase.setUp`) — as 5 rotas respondem 200/302."""
        self.client.force_login(self.editor)
        processo = Processo.objects.filter(
            exercicio__ano=2026, vigencia_fim__isnull=False
        ).first()

        resposta_prazos = self.client.get(
            reverse("pca:analise_prazos"), HTTP_HOST="testserver"
        )
        self.assertEqual(resposta_prazos.status_code, 200)

        resposta_renovar = self.client.post(
            reverse("pca:analise_prazos_renovar", args=[2026, processo.item_pca]),
            {"destino": "true"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta_renovar.status_code, 302)

    def test_menu_sem_ver_analises_nao_lista_fluxo_estatisticas_prazos(self):
        from core.menu import itens as itens_menu
        from django.test import RequestFactory

        rf = RequestFactory()
        request = rf.get("/")
        request.user = self.visualizador
        pasta = next(
            i for i in itens_menu(request) if i.get("rotulo") == "Análises"
        )
        rotulos_filhos = [f["rotulo"] for f in pasta["filhos"]]
        self.assertNotIn("Fluxo de caixa", rotulos_filhos)
        self.assertNotIn("Estatísticas", rotulos_filhos)
        self.assertNotIn("Prazos", rotulos_filhos)


class TestAnaliseFluxoMemoria(AnaliseTelasBase):
    """Fase 37 (spec §5) — memória de cálculo por item: 200
    com "Parcelas"/fórmula para quem tem `pca.ver_analises`, 403 para quem
    não tem, conciliação exata com `Projecao.parcelas`."""

    def test_memoria_200_com_parcelas_e_formula_para_quem_tem_ver_analises(self):
        self.client.force_login(self.editor)
        # Processo.item_pca=1 tem valor_contratado (2200,00, vigência
        # 11/02/2026-10/02/2027) na fixture real (ver TestFluxoCsv acima)
        # — a projeção sempre gera ao menos a camada "contratado" para ele.
        processo = Processo.objects.get(exercicio__ano=2026, item_pca=1)
        resposta = self.client.get(
            reverse("pca:analise_fluxo_memoria", args=[processo.item_pca]),
            {"exercicio": "2026"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 200)
        conteudo = resposta.content.decode()
        self.assertIn("Parcelas", conteudo)
        self.assertIn("R$", conteudo)
        coletor = _coletar(conteudo)
        self.assertEqual(coletor.h1_count, 1)

    def test_memoria_403_para_visualizador_sem_ver_analises(self):
        self.client.force_login(self.visualizador)
        processo = Processo.objects.filter(exercicio__ano=2026).first()
        resposta = self.client.get(
            reverse("pca:analise_fluxo_memoria", args=[processo.item_pca]),
            {"exercicio": "2026"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 403)

    def test_memoria_sem_projecao_mostra_aviso_sem_404(self):
        """Item existente sem dado suficiente (sem vigência/valor
        contratado nem estimado) — `memoria=None`, nunca 404 (é
        sobre acesso, não sobre existência do dado)."""
        self.client.force_login(self.editor)
        processo = (
            Processo.objects.filter(
                exercicio__ano=2026,
                vigencia_fim__isnull=True,
                valor_contratado__isnull=True,
                valor_estimado__isnull=True,
            ).first()
        )
        if processo is None:
            self.skipTest("fixture sem item sem dado suficiente para este cenário")
        resposta = self.client.get(
            reverse("pca:analise_fluxo_memoria", args=[processo.item_pca]),
            {"exercicio": "2026"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("Sem dado suficiente", resposta.content.decode())

    def test_memoria_404_para_item_pca_inexistente(self):
        self.client.force_login(self.editor)
        resposta = self.client.get(
            reverse("pca:analise_fluxo_memoria", args=[999999]),
            {"exercicio": "2026"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 404)

    def test_link_memoria_aparece_na_lista_de_contratacoes_do_recorte(self):
        """Fase 37 — "Memória" ao lado do link do item na
        lista "Contratações neste recorte", sem remover o
        link para a ficha."""
        self.client.force_login(self.editor)
        resposta = self.client.get(
            reverse("pca:analise_fluxo"),
            {"exercicio": "2026", "ano": "2026"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 200)
        conteudo = resposta.content.decode()
        self.assertIn("Contratações neste recorte", conteudo)
        url_ficha = reverse("pca:detalhe_processo", args=[2026, 1])
        url_memoria = reverse("pca:analise_fluxo_memoria", args=[1])
        self.assertIn(url_ficha, conteudo)
        self.assertIn(url_memoria, conteudo)
        self.assertIn("Memória", conteudo)

    def test_memoria_concilia_totais_por_camada_com_parcelas_da_tela_de_fluxo(self):
        """`sum(memoria.linhas por camada) == sum(projecao.parcelas por
        item/camada)` — a mesma `Projecao` (todos os processos do
        exercício, mesmo cenário/índice) usada pela tela de Fluxo de
        caixa."""
        from django.http import QueryDict

        from apps.catalogo.models import Exercicio
        from apps.pca import views_analise
        from apps.pca.projecao import CAMADAS
        from apps.pca.projecao import fluxo as fluxo_mod

        exercicio = Exercicio.objects.get(ano=2026)
        processo = Processo.objects.get(exercicio=exercicio, item_pca=1)

        get = QueryDict()
        cenario = views_analise._cenario_valido(get)
        indice = views_analise._indice_valido(get)
        parametros = views_analise._parametros(exercicio, cenario, indice, localdate())
        itens = views_analise._itens_para_projecao(
            Processo.objects.para_listagem().filter(exercicio=exercicio)
        )
        projecao = fluxo_mod.projetar(itens, parametros)
        memoria = projecao.memorias.get(processo.item_pca)
        self.assertIsNotNone(memoria)

        for camada in CAMADAS:
            soma_memoria = sum(
                (l.valor for l in memoria.linhas if l.camada == camada), Decimal("0")
            )
            soma_parcelas = sum(
                (
                    p.valor
                    for p in projecao.parcelas
                    if p.item_pca == processo.item_pca and p.camada == camada
                ),
                Decimal("0"),
            )
            self.assertEqual(
                soma_memoria,
                soma_parcelas,
                f"camada {camada}: memoria={soma_memoria} != parcelas={soma_parcelas}",
            )


class TestLinkMemoriaCalculoNaFicha(AnaliseTelasBase):
    """Fase 37 (spec §5 item 6) — link "Memória de
    cálculo" na ficha do item, condicionado a `pca.ver_analises`."""

    def test_link_memoria_aparece_na_ficha_para_quem_tem_ver_analises(self):
        self.client.force_login(self.editor)
        processo = Processo.objects.filter(exercicio__ano=2026).first()
        resposta = self.client.get(
            reverse("pca:detalhe_processo", args=[2026, processo.item_pca]),
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 200)
        url_memoria = reverse("pca:analise_fluxo_memoria", args=[processo.item_pca])
        self.assertIn(url_memoria, resposta.content.decode())
        self.assertIn("Memória de cálculo", resposta.content.decode())

    def test_link_memoria_ausente_na_ficha_para_quem_nao_tem_ver_analises(self):
        self.client.force_login(self.visualizador)
        processo = Processo.objects.filter(exercicio__ano=2026).first()
        resposta = self.client.get(
            reverse("pca:detalhe_processo", args=[2026, processo.item_pca]),
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 200)
        url_memoria = reverse("pca:analise_fluxo_memoria", args=[processo.item_pca])
        self.assertNotIn(url_memoria, resposta.content.decode())
        self.assertNotIn("Memória de cálculo", resposta.content.decode())


class TestSimulacaoRascunhoSessao(AnaliseTelasBase):
    """Fase 37 (spec §3.2/§3.3) — rascunho de
    simulação na sessão: toda ação POST validada na fronteira antes de
    entrar em `request.session["fluxo_ajustes"]`, nunca no módulo puro
    `simulacao.py`."""

    def test_excluir_grava_item_pca_no_rascunho_e_redireciona_com_sim_rascunho(self):
        self.client.force_login(self.editor)
        resposta = self.client.post(
            reverse("pca:analise_fluxo_item_excluir", args=[1]),
            {"exercicio": "2026"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 302)
        self.assertIn("sim=rascunho", resposta.url)
        self.assertIn(1, self.client.session["fluxo_ajustes"]["itens_excluidos"])

    def test_excluir_item_pca_inexistente_retorna_404_sem_alterar_sessao(self):
        self.client.force_login(self.editor)
        resposta = self.client.post(
            reverse("pca:analise_fluxo_item_excluir", args=[999999]),
            {"exercicio": "2026"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 404)
        self.assertNotIn("fluxo_ajustes", self.client.session)

    def test_valor_nao_numerico_nao_altera_sessao_com_mensagem_erro(self):
        self.client.force_login(self.editor)
        resposta = self.client.post(
            reverse("pca:analise_fluxo_item_valor", args=[1]),
            {"exercicio": "2026", "valor": "abc"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 302)
        self.assertNotIn("fluxo_ajustes", self.client.session)
        mensagens = [str(m) for m in get_messages(resposta.wsgi_request)]
        self.assertTrue(any("inválido" in m.lower() for m in mensagens))

    def test_valor_nan_nao_altera_sessao_com_mensagem_erro(self):
        # QA 30/09/2026 (fuzz M3) — `Decimal("NaN")` é uma construção
        # válida (não levanta `InvalidOperation`); sem o `is_finite()`, a
        # comparação de faixa logo abaixo estourava 500.
        self.client.force_login(self.editor)
        resposta = self.client.post(
            reverse("pca:analise_fluxo_item_valor", args=[1]),
            {"exercicio": "2026", "valor": "NaN"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 302)
        self.assertNotIn("fluxo_ajustes", self.client.session)
        mensagens = [str(m) for m in get_messages(resposta.wsgi_request)]
        self.assertTrue(any("inválido" in m.lower() for m in mensagens))

    def test_indice_nan_nao_altera_sessao_com_mensagem_erro(self):
        # QA 30/09/2026 (fuzz M3), painel "Simular".
        self.client.force_login(self.editor)
        resposta = self.client.post(
            reverse("pca:analise_fluxo_simular"),
            {"exercicio": "2026", "indice_2026": "NaN"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 302)
        self.assertNotIn("fluxo_ajustes", self.client.session)
        mensagens = [str(m) for m in get_messages(resposta.wsgi_request)]
        self.assertTrue(any("inválido" in m.lower() for m in mensagens))

    def test_valor_valido_grava_no_rascunho(self):
        self.client.force_login(self.editor)
        resposta = self.client.post(
            reverse("pca:analise_fluxo_item_valor", args=[1]),
            {"exercicio": "2026", "valor": "2500.00"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 302)
        self.assertIn("sim=rascunho", resposta.url)
        self.assertEqual(
            self.client.session["fluxo_ajustes"]["valor_por_item"]["1"], "2500.00"
        )

    def test_inicio_invalido_nao_altera_sessao(self):
        self.client.force_login(self.editor)
        resposta = self.client.post(
            reverse("pca:analise_fluxo_item_inicio", args=[1]),
            {"exercicio": "2026", "inicio": "não é uma data"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 302)
        self.assertNotIn("fluxo_ajustes", self.client.session)

    def test_voltar_oficial_limpa_fluxo_ajustes_da_sessao(self):
        self.client.force_login(self.editor)
        self.client.post(
            reverse("pca:analise_fluxo_item_excluir", args=[1]),
            {"exercicio": "2026"},
            HTTP_HOST="testserver",
        )
        self.assertIn("fluxo_ajustes", self.client.session)
        resposta = self.client.post(
            reverse("pca:analise_fluxo_voltar_oficial"),
            {"exercicio": "2026"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 302)
        self.assertIn("sim=oficial", resposta.url)
        self.assertNotIn("fluxo_ajustes", self.client.session)

    def test_visualizador_sem_ver_analises_recebe_403_nas_acoes(self):
        self.client.force_login(self.visualizador)
        resposta = self.client.post(
            reverse("pca:analise_fluxo_item_excluir", args=[1]),
            {"exercicio": "2026"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 403)

    def test_painel_simular_e_acoes_por_item_aparecem_na_tela_com_recorte(self):
        self.client.force_login(self.editor)
        resposta = self.client.get(
            reverse("pca:analise_fluxo"),
            {"exercicio": "2026", "ano": "2026"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 200)
        conteudo = resposta.content.decode()
        self.assertIn("Simular", conteudo)
        self.assertIn("Excluir da simulação", conteudo)
        coletor = _coletar(conteudo)
        self.assertEqual(coletor.h1_count, 1)


class TestComparacaoOficialSimulado(AnaliseTelasBase):
    """Fase 37 (spec §3.4) — comparação Oficial ×
    Simulado × Diferença só aparece com `sim` explícito; o padrão
    (`sim=oficial`, inclusive sem `sim=` nenhum) nunca aplica simulação por
    acidente, mesmo com rascunho ativo na sessão."""

    def test_sim_rascunho_com_item_excluido_mostra_simulacao_ativa(self):
        self.client.force_login(self.editor)
        self.client.post(
            reverse("pca:analise_fluxo_item_excluir", args=[1]),
            {"exercicio": "2026"},
            HTTP_HOST="testserver",
        )
        resposta = self.client.get(
            reverse("pca:analise_fluxo"),
            {"exercicio": "2026", "sim": "rascunho"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("Simulação ativa", resposta.content.decode())

    def test_cenario_salvo_com_nan_no_json_nao_derruba_a_tela(self):
        # QA 30/09/2026 (achado INFO I2) — um `CenarioFluxo` editado
        # manualmente pelo Admin (LGPD, 11/09/2026) pode carregar um valor
        # não finito no JSON; `de_json` precisa descartá-lo antes que
        # `_comparacao` o alcance.
        self.client.force_login(self.editor)
        cenario = CenarioFluxo.objects.create(
            exercicio=Exercicio.objects.get(ano=2026),
            nome="Com NaN",
            autor=self.editor,
            ajustes={"valor_por_item": {"1": "NaN"}},
        )
        resposta = self.client.get(
            reverse("pca:analise_fluxo"),
            {"exercicio": "2026", "sim": str(cenario.pk)},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 200)

    def test_sim_oficial_padrao_nao_mostra_simulacao_ativa_mesmo_com_rascunho(self):
        self.client.force_login(self.editor)
        self.client.post(
            reverse("pca:analise_fluxo_item_excluir", args=[1]),
            {"exercicio": "2026"},
            HTTP_HOST="testserver",
        )
        resposta = self.client.get(
            reverse("pca:analise_fluxo"),
            {"exercicio": "2026"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertNotIn("Simulação ativa", resposta.content.decode())

    def test_sim_id_invalido_cai_em_oficial_sem_500(self):
        self.client.force_login(self.editor)
        resposta = self.client.get(
            reverse("pca:analise_fluxo"),
            {"exercicio": "2026", "sim": "999999"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertNotIn("Simulação ativa", resposta.content.decode())

    def test_memoria_com_sim_rascunho_mostra_duas_colunas(self):
        self.client.force_login(self.editor)
        self.client.post(
            reverse("pca:analise_fluxo_item_valor", args=[1]),
            {"exercicio": "2026", "valor": "9999.00"},
            HTTP_HOST="testserver",
        )
        resposta = self.client.get(
            reverse("pca:analise_fluxo_memoria", args=[1]),
            {"exercicio": "2026", "sim": "rascunho"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 200)
        conteudo = resposta.content.decode()
        self.assertIn("Simulação ativa", conteudo)
        self.assertIn("Oficial", conteudo)
        self.assertIn("Simulado", conteudo)


def _situacoes_carga():
    return list(Situacao.values)


class TestCargaComparacaoOficialSimulado(TestCase):
    """Fase 37 (spec §3.4/§9) — motor chamado 2x por
    requisição (oficial + simulado) sob o MESMO orçamento de 500 itens ×
    72 meses do plano (600 ms), agora exercido pela VIEW completa com
    `sim=rascunho` ativo. `TestCase` (bulk_create direto, mesmo padrão de
    `test_desempenho_fase28.py`) — dispensa `serialized_rollback`."""

    @classmethod
    def setUpTestData(cls):
        call_command("configurar_grupos", stdout=StringIO())
        unidade = Unidade.objects.create(nome="Unidade Carga Simulação 37-05")
        tipo = Tipo.objects.create(nome="Tipo Carga Simulação 37-05")
        categoria = Categoria.objects.create(nome="Categoria Carga Simulação 37-05")
        exercicio = Exercicio.objects.get(ano=2026)
        situacoes = _situacoes_carga()

        processos = []
        for i in range(1, 501):
            comum = dict(
                item_pca=i,
                exercicio=exercicio,
                descricao_objeto=f"Item de carga 37-05 nº {i}",
                tipo=tipo,
                categoria=categoria,
                unidade_organizacional=unidade,
                estado=Estado.ATIVO.value,
                situacao=situacoes[i % len(situacoes)],
            )
            tipo_item = i % 4
            if tipo_item == 0:
                processos.append(
                    Processo(
                        **comum,
                        valor_mensal=Decimal("10000.00"),
                        regime_execucao="continuado",
                        renovacao_prevista=True,
                        vigencia_inicio=date(2024, 1, 1),
                        vigencia_fim=date(2026, 12, 31),
                    )
                )
            elif tipo_item == 1:
                processos.append(
                    Processo(
                        **comum,
                        valor_contratado=Decimal("50000.00"),
                        regime_execucao="unico",
                        vigencia_fim=date(2026, 6, 30),
                    )
                )
            elif tipo_item == 2:
                processos.append(
                    Processo(
                        **comum,
                        valor_estimado=Decimal("24000.00"),
                        mes_previsto=(i % 12) + 1,
                        regime_execucao="continuado",
                    )
                )
            else:
                comum["estado"] = Estado.CANCELADO.value
                processos.append(Processo(**comum))
        Processo.objects.bulk_create(processos)

        User = get_user_model()
        cls.usuario = User.objects.create_user(
            email="carga-simulacao-37-05@pca.local", password="senha-segura"
        )
        cls.usuario.groups.add(Group.objects.get(name="dirigentes"))

    def test_view_completa_sim_rascunho_500_itens_72_meses_abaixo_de_600ms(self):
        client = Client(HTTP_X_FORWARDED_PROTO="https")
        client.force_login(self.usuario)
        # Rascunho de sessão não vazio — `comparacao_ativa` de fato aciona
        # o motor pela 2ª vez (spec §3.4); excluir um item qualquer basta.
        client.post(
            reverse("pca:analise_fluxo_item_excluir", args=[1]),
            {"exercicio": "2026"},
            HTTP_HOST="testserver",
        )

        inicio = time.perf_counter()
        resposta = client.get(
            reverse("pca:analise_fluxo"),
            {"exercicio": "2026", "sim": "rascunho"},
            HTTP_HOST="testserver",
        )
        duracao_ms = (time.perf_counter() - inicio) * 1000

        self.assertEqual(resposta.status_code, 200)
        self.assertIn("Simulação ativa", resposta.content.decode())
        self.assertLess(duracao_ms, 600, f"view completa levou {duracao_ms:.1f} ms")


class TestCenarioFluxoCRUD(AnaliseTelasBase):
    """Fase 37 (spec §0 decisão 5/§3.2) — CRUD completo
    de `CenarioFluxo`: salvar como novo, sobrescrever, carregar no rascunho,
    excluir com página de confirmação. `self.editor` (grupo "dirigentes",
    `ver_analises`) é sempre o AUTOR nestes testes; `self.outro_dirigente`
    (também `ver_analises`, mas outra pessoa) prova a checagem de
    autor-ou-superusuário nas ações destrutivas."""

    def setUp(self):
        super().setUp()
        User = get_user_model()
        self.outro_dirigente = User.objects.create_user(
            email="outro-dirigente-cenario@pca.local", password="senha-segura"
        )
        self.outro_dirigente.groups.add(Group.objects.get(name="dirigentes"))
        self.superusuario = User.objects.create_superuser(
            email="super-cenario@pca.local", password="senha-segura"
        )
        self.exercicio = Exercicio.objects.get(ano=2026)

    def test_salvar_como_cria_cenario_com_autor_do_usuario_logado(self):
        self.client.force_login(self.editor)
        self.client.post(
            reverse("pca:analise_fluxo_item_excluir", args=[1]),
            {"exercicio": "2026"},
            HTTP_HOST="testserver",
        )
        resposta = self.client.post(
            reverse("pca:analise_fluxo_cenario_salvar_como"),
            {"exercicio": "2026", "nome": "Cenário X"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 302)
        cenario = CenarioFluxo.objects.get(exercicio=self.exercicio, nome="Cenário X")
        self.assertEqual(cenario.autor_id, self.editor.id)
        self.assertIn(1, cenario.ajustes["itens_excluidos"])
        self.assertIn(f"sim={cenario.pk}", resposta.url)

    def test_salvar_como_sem_nome_nao_grava_e_mostra_mensagem_erro(self):
        self.client.force_login(self.editor)
        resposta = self.client.post(
            reverse("pca:analise_fluxo_cenario_salvar_como"),
            {"exercicio": "2026", "nome": "   "},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(CenarioFluxo.objects.filter(exercicio=self.exercicio).count(), 0)
        mensagens = [str(m) for m in get_messages(resposta.wsgi_request)]
        self.assertTrue(any("nome" in m.lower() for m in mensagens))

    def test_salvar_como_nome_ja_usado_no_exercicio_nao_grava(self):
        CenarioFluxo.objects.create(
            exercicio=self.exercicio, nome="Duplicado", autor=self.editor, ajustes={}
        )
        self.client.force_login(self.editor)
        resposta = self.client.post(
            reverse("pca:analise_fluxo_cenario_salvar_como"),
            {"exercicio": "2026", "nome": "Duplicado"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(
            CenarioFluxo.objects.filter(exercicio=self.exercicio, nome="Duplicado").count(), 1
        )

    def test_salvar_como_nome_maior_que_100_caracteres_nao_grava(self):
        self.client.force_login(self.editor)
        resposta = self.client.post(
            reverse("pca:analise_fluxo_cenario_salvar_como"),
            {"exercicio": "2026", "nome": "x" * 101},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(CenarioFluxo.objects.filter(exercicio=self.exercicio).count(), 0)

    def test_sobrescrever_por_nao_autor_nao_superusuario_devolve_403(self):
        cenario = CenarioFluxo.objects.create(
            exercicio=self.exercicio, nome="Cenário do editor", autor=self.editor, ajustes={}
        )
        self.client.force_login(self.outro_dirigente)
        resposta = self.client.post(
            reverse("pca:analise_fluxo_cenario_salvar", args=[cenario.pk]),
            {"exercicio": "2026"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 403)
        cenario.refresh_from_db()
        self.assertEqual(cenario.ajustes, {})

    def test_sobrescrever_pelo_autor_atualiza_ajustes_e_redireciona(self):
        cenario = CenarioFluxo.objects.create(
            exercicio=self.exercicio, nome="Cenário do editor", autor=self.editor, ajustes={}
        )
        self.client.force_login(self.editor)
        self.client.post(
            reverse("pca:analise_fluxo_item_valor", args=[1]),
            {"exercicio": "2026", "valor": "3500.00"},
            HTTP_HOST="testserver",
        )
        resposta = self.client.post(
            reverse("pca:analise_fluxo_cenario_salvar", args=[cenario.pk]),
            {"exercicio": "2026"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 302)
        cenario.refresh_from_db()
        self.assertEqual(cenario.ajustes["valor_por_item"]["1"], "3500.00")

    def test_sobrescrever_pelo_superusuario_funciona_mesmo_sem_ser_autor(self):
        cenario = CenarioFluxo.objects.create(
            exercicio=self.exercicio, nome="Cenário do editor", autor=self.editor, ajustes={}
        )
        self.client.force_login(self.superusuario)
        resposta = self.client.post(
            reverse("pca:analise_fluxo_cenario_salvar", args=[cenario.pk]),
            {"exercicio": "2026"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 302)

    def test_carregar_copia_ajustes_do_cenario_para_o_rascunho_da_sessao(self):
        cenario = CenarioFluxo.objects.create(
            exercicio=self.exercicio,
            nome="Cenário para carregar",
            autor=self.editor,
            ajustes={"itens_excluidos": [7], "indices_por_ano": {}, "renovacao_por_item": {},
                     "valor_por_item": {}, "inicio_por_item": {}, "lead_time_dias": None},
        )
        self.client.force_login(self.outro_dirigente)
        resposta = self.client.post(
            reverse("pca:analise_fluxo_cenario_carregar", args=[cenario.pk]),
            {"exercicio": "2026"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 302)
        self.assertIn("sim=rascunho", resposta.url)
        self.assertIn(7, self.client.session["fluxo_ajustes"]["itens_excluidos"])
        # Carregar NÃO muda o cenário salvo (spec §3.2) — só a sessão.
        cenario.refresh_from_db()
        self.assertEqual(cenario.ajustes["itens_excluidos"], [7])

    def test_excluir_por_nao_autor_nao_superusuario_devolve_403(self):
        cenario = CenarioFluxo.objects.create(
            exercicio=self.exercicio, nome="Cenário do editor", autor=self.editor, ajustes={}
        )
        self.client.force_login(self.outro_dirigente)
        resposta = self.client.post(
            reverse("pca:analise_fluxo_cenario_excluir", args=[cenario.pk]),
            {"exercicio": "2026"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 403)
        self.assertTrue(CenarioFluxo.objects.filter(pk=cenario.pk).exists())

    def test_excluir_confirmar_por_nao_autor_devolve_403(self):
        cenario = CenarioFluxo.objects.create(
            exercicio=self.exercicio, nome="Cenário do editor", autor=self.editor, ajustes={}
        )
        self.client.force_login(self.outro_dirigente)
        resposta = self.client.get(
            reverse("pca:analise_fluxo_cenario_excluir_confirmar", args=[cenario.pk]),
            {"exercicio": "2026"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 403)

    def test_excluir_confirmar_pelo_autor_mostra_form_post_nunca_modal(self):
        cenario = CenarioFluxo.objects.create(
            exercicio=self.exercicio, nome="Cenário a excluir", autor=self.editor, ajustes={}
        )
        self.client.force_login(self.editor)
        resposta = self.client.get(
            reverse("pca:analise_fluxo_cenario_excluir_confirmar", args=[cenario.pk]),
            {"exercicio": "2026"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 200)
        conteudo = resposta.content.decode()
        self.assertIn('<form method="post"', conteudo)
        self.assertNotIn("br-modal", conteudo)
        coletor = _coletar(conteudo)
        self.assertEqual(coletor.h1_count, 1)

    def test_excluir_pelo_autor_apaga_o_cenario_e_redireciona_sim_oficial(self):
        cenario = CenarioFluxo.objects.create(
            exercicio=self.exercicio, nome="Cenário a excluir", autor=self.editor, ajustes={}
        )
        self.client.force_login(self.editor)
        resposta = self.client.post(
            reverse("pca:analise_fluxo_cenario_excluir", args=[cenario.pk]),
            {"exercicio": "2026"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 302)
        self.assertIn("sim=oficial", resposta.url)
        self.assertFalse(CenarioFluxo.objects.filter(pk=cenario.pk).exists())

    def test_seletor_e_botoes_de_cenario_aparecem_na_tela(self):
        cenario = CenarioFluxo.objects.create(
            exercicio=self.exercicio, nome="Cenário visível", autor=self.editor, ajustes={}
        )
        self.client.force_login(self.editor)
        resposta = self.client.get(
            reverse("pca:analise_fluxo"),
            {"exercicio": "2026", "sim": str(cenario.pk)},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 200)
        conteudo = resposta.content.decode()
        self.assertIn("Cenário visível", conteudo)
        self.assertIn("Carregar no rascunho", conteudo)
        self.assertIn("Excluir", conteudo)
        coletor = _coletar(conteudo)
        self.assertEqual(coletor.h1_count, 1)
        self.assertLessEqual(coletor.primary_count, 1)


def _criar_item_com_contrato(item_pca, **campos):
    """Fase 38 — item sintético para as classes de teste de
    "Contratos a vencer" (view e ação). Padrão: `tipo=Vigente`,
    `situacao=concluido`, `regime_execucao=continuado`, vigência fim
    31/12/2026 — reproduz M07 (aparece na seção mesmo concluído)."""
    exercicio = Exercicio.objects.get(ano=2026)
    tipo_vigente = Tipo.objects.filter(nome__icontains="vigente").first()
    unidade = Unidade.objects.first()
    categoria = Categoria.objects.first()
    padrao = dict(
        item_pca=item_pca,
        exercicio=exercicio,
        descricao_objeto=f"Processo de teste contratos a vencer {item_pca}",
        tipo=tipo_vigente,
        categoria=categoria,
        unidade_organizacional=unidade,
        estado=Estado.ATIVO,
        situacao=Situacao.CONCLUIDO,
        regime_execucao=RegimeExecucao.CONTINUADO,
        vigencia_fim=date(2026, 12, 31),
        renovacao_prevista=True,
        valor_mensal=Decimal("1000.00"),
    )
    padrao.update(campos)
    return Processo.objects.create(**padrao)


class TestContratosAVencerSecao(AnaliseTelasBase):
    """Fase 38 (spec §2-§4) — a seção "Contratos a vencer" substitui a antiga seção de
    itens vincendos em 90/180/365 dias (M07)."""

    def _criar_item_com_contrato(self, item_pca, **campos):
        return _criar_item_com_contrato(item_pca, **campos)

    def test_secao_e_a_primeira_apos_h1_e_vincendos_sumiu(self):
        self.client.force_login(self.editor)
        resposta = self.client.get(
            reverse("pca:analise_prazos"), {"exercicio": "2026"}, HTTP_HOST="testserver"
        )
        self.assertEqual(resposta.status_code, 200)
        conteudo = resposta.content.decode()
        self.assertNotIn("Vincendos em 90/180/365", conteudo)
        self.assertNotIn("continuado com renovação prevista", conteudo)
        # Fase 40 — o `<h2>` ganhou um `<div>` flex ao redor
        # (título + botão "Gerar itens de N+1", só para quem pode) e a
        # classe `mb-3` migrou do `<h2>` (agora `mb-0`) para o `<div>`
        # pai — a busca aponta para o `<div>`, continuando a primeira
        # seção depois do `<h1>`.
        pos_secao = conteudo.find(
            '<div class="d-flex align-items-center justify-content-between mb-3">'
        )
        pos_lead_time = conteudo.find("Lead time por etapa")
        self.assertGreater(pos_secao, 0)
        self.assertGreater(pos_lead_time, pos_secao)
        self.assertIn("Exercício 2026 · todas as unidades · exercício seguinte: 2027", conteudo)

    def test_m07_item_vigente_concluido_aparece_unico_nao_aparece_vencido_com_tag(self):
        hoje = localdate()
        self._criar_item_com_contrato(9001)
        self._criar_item_com_contrato(9002, regime_execucao=RegimeExecucao.UNICO)
        self._criar_item_com_contrato(
            9003, vigencia_fim=hoje - timedelta(days=3)
        )
        self.client.force_login(self.editor)
        resposta = self.client.get(
            reverse("pca:analise_prazos"), {"exercicio": "2026"}, HTTP_HOST="testserver"
        )
        conteudo = resposta.content.decode()
        self.assertIn("9001", conteudo)
        self.assertNotIn("9002", conteudo)
        secao = conteudo[conteudo.find("Contratos a vencer"):conteudo.find("Lead time por etapa")]
        self.assertIn("9003", secao)
        self.assertIn("Vencido", secao)

    def test_parametros_legados_nao_afetam_a_populacao(self):
        self._criar_item_com_contrato(9001)
        nova_contratacao = Tipo.objects.filter(nome__icontains="nova").first()
        self.client.force_login(self.editor)
        resposta = self.client.get(
            reverse("pca:analise_prazos"),
            {
                "exercicio": "2026",
                "situacao": "no_prazo",
                "tipo": str(nova_contratacao.pk) if nova_contratacao else "1",
                "estado": "cancelado",
            },
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 200)
        conteudo = resposta.content.decode()
        secao = conteudo[conteudo.find("Contratos a vencer"):conteudo.find("Lead time por etapa")]
        self.assertIn("9001", secao)

    def test_total_e_soma_das_quatro_categorias_e_concilia_com_queryset(self):
        self._criar_item_com_contrato(9001)
        self._criar_item_com_contrato(9002, renovacao_prevista=False)
        self.client.force_login(self.editor)
        resposta = self.client.get(
            reverse("pca:analise_prazos"), {"exercicio": "2026"}, HTTP_HOST="testserver"
        )
        conteudo = resposta.content.decode()
        for rotulo in (
            "Itens com contrato",
            "Vencidos ou encerram em 2026",
            "Renovação em 2026",
            "Renovações em 2027",
            "Vigentes em 2027",
        ):
            self.assertIn(rotulo, conteudo)
        k = resposta.context["contratos"]["kpis"]
        soma = k["encerramento_n"] + k["renovacao_n"] + k["renovacao_n1"] + k["vigente_n1"]
        self.assertEqual(k["total"], soma)
        from apps.pca.servicos import contratos as contratos_mod

        self.assertEqual(
            k["total"],
            contratos_mod.contratos_a_vencer(
                Exercicio.objects.get(ano=2026), hoje=localdate()
            ).queryset.count(),
        )

    def test_cards_apontam_para_grupo_destino_sem_destino_nem_pagina(self):
        self._criar_item_com_contrato(9001, vigencia_fim=date(2027, 6, 15))
        self.client.force_login(self.editor)
        resposta = self.client.get(
            reverse("pca:analise_prazos"), {"exercicio": "2026"}, HTTP_HOST="testserver"
        )
        cards = {c["rotulo"]: c for c in resposta.context["contratos"]["cards"]}
        href_renovacao_n1 = cards["Renovações em 2027"]["url"]
        qs_renovacao_n1 = parse_qs(urlparse(href_renovacao_n1).query)
        self.assertEqual(qs_renovacao_n1.get("grupo_destino"), ["renovacao_n1"])
        self.assertNotIn("destino", qs_renovacao_n1)
        self.assertNotIn("pagina", qs_renovacao_n1)
        self.assertEqual(qs_renovacao_n1.get("exercicio"), ["2026"])
        href_total = cards["Itens com contrato"]["url"]
        qs_total = parse_qs(urlparse(href_total).query)
        self.assertNotIn("grupo_destino", qs_total)
        self.assertNotIn("destino", qs_total)

    def test_filtro_vence_vencidos_renovacao_nao_destino_prevalece(self):
        hoje = localdate()
        self._criar_item_com_contrato(9001, vigencia_fim=hoje - timedelta(days=3))
        self._criar_item_com_contrato(9002, vigencia_fim=date(2026, 12, 31))
        self.client.force_login(self.editor)

        resposta = self.client.get(
            reverse("pca:analise_prazos"),
            {"exercicio": "2026", "vence": "vencidos"},
            HTTP_HOST="testserver",
        )
        secao = resposta.content.decode()
        secao = secao[secao.find("Contratos a vencer"):secao.find("Lead time por etapa")]
        self.assertIn("9001", secao)
        self.assertNotIn("9002", secao)

        resposta = self.client.get(
            reverse("pca:analise_prazos"),
            {"exercicio": "2026", "renovacao": "nao"},
            HTTP_HOST="testserver",
        )
        secao = resposta.content.decode()
        secao = secao[secao.find("Contratos a vencer"):secao.find("Lead time por etapa")]
        self.assertNotIn("<span>Sim</span>", secao)

        resposta_base = self.client.get(
            reverse("pca:analise_prazos"), {"exercicio": "2026"}, HTTP_HOST="testserver"
        )
        resposta_destino = self.client.get(
            reverse("pca:analise_prazos"),
            {"exercicio": "2026", "destino": "vencido", "grupo_destino": "vigente_n1"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta_base.status_code, 200)
        self.assertEqual(resposta_destino.status_code, 200)
        self.assertEqual(
            resposta_base.context["contratos"]["kpis"],
            resposta_destino.context["contratos"]["kpis"],
        )
        secao_destino = resposta_destino.content.decode()
        secao_destino = secao_destino[
            secao_destino.find("Contratos a vencer"):secao_destino.find("Lead time por etapa")
        ]
        self.assertIn("9001", secao_destino)
        self.assertNotIn("9002", secao_destino)
        cards_destino = {c["rotulo"]: c for c in resposta_destino.context["contratos"]["cards"]}
        qs_total_destino = parse_qs(urlparse(cards_destino["Itens com contrato"]["url"]).query)
        self.assertNotIn("grupo_destino", qs_total_destino)
        self.assertNotIn("destino", qs_total_destino)

    def test_filtro_invalido_ignorado_com_warning(self):
        self.client.force_login(self.editor)
        resposta = self.client.get(
            reverse("pca:analise_prazos"),
            {"exercicio": "2026", "vence": "xyz"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 200)
        mensagens = [str(m) for m in get_messages(resposta.wsgi_request)]
        self.assertTrue(
            any('Filtro "vence" com valor inválido foi ignorado.' in m for m in mensagens)
        )

    def test_form_e_limpar_preservam_exercicio_e_duas_uos(self):
        unidades = list(Unidade.objects.all()[:2])
        self._criar_item_com_contrato(9001, unidade_organizacional=unidades[0])
        self.client.force_login(self.editor)
        from urllib.parse import urlencode

        url = reverse("pca:analise_prazos") + "?" + urlencode(
            [("exercicio", "2026"), ("uo", unidades[0].pk), ("uo", unidades[1].pk)],
            doseq=True,
        )
        resposta = self.client.get(url, HTTP_HOST="testserver")
        conteudo = resposta.content.decode()
        inicio_form = conteudo.find('<form method="get"')
        fim_form = conteudo.find("</form>", inicio_form)
        form_filtro = conteudo[inicio_form:fim_form]
        self.assertIn('<input type="hidden" name="exercicio" value="2026"/>', form_filtro)
        self.assertEqual(
            form_filtro.count(
                f'<input type="hidden" name="uo" value="{unidades[0].pk}"/>'
            )
            + form_filtro.count(
                f'<input type="hidden" name="uo" value="{unidades[1].pk}"/>'
            ),
            2,
        )
        pos_limpar = conteudo.find("Limpar filtros")
        trecho_limpar = conteudo[max(0, pos_limpar - 400):pos_limpar]
        self.assertIn("exercicio=2026", trecho_limpar)
        self.assertIn(f"uo={unidades[0].pk}", trecho_limpar)
        self.assertIn(f"uo={unidades[1].pk}", trecho_limpar)
        self.assertNotIn("vence=", trecho_limpar)
        self.assertNotIn("renovacao=", trecho_limpar)
        self.assertNotIn("destino=", trecho_limpar)
        self.assertNotIn("grupo_destino=", trecho_limpar)
        self.assertNotIn("pagina=", trecho_limpar)

    def test_paginacao_sem_htmx_e_pagina_fora_do_intervalo_cai_na_ultima(self):
        unidade_isolada = Unidade.objects.create(nome="Unidade paginação 38-02")
        for i in range(25):
            self._criar_item_com_contrato(
                9100 + i,
                vigencia_fim=date(2026, 12, 1 + (i % 28)),
                unidade_organizacional=unidade_isolada,
            )
        self.client.force_login(self.editor)
        resposta = self.client.get(
            reverse("pca:analise_prazos"),
            {"exercicio": "2026", "uo": str(unidade_isolada.pk)},
            HTTP_HOST="testserver",
        )
        conteudo = resposta.content.decode()
        secao = conteudo[conteudo.find("Contratos a vencer"):conteudo.find("Lead time por etapa")]
        self.assertEqual(secao.count('data-th="Item"'), 20)
        self.assertIn("Mostrando 1–20 de 25 itens com contrato", conteudo)
        self.assertIn('pagina=2', conteudo)
        self.assertNotIn("hx-", secao)

        resposta_ultima = self.client.get(
            reverse("pca:analise_prazos"),
            {"exercicio": "2026", "uo": str(unidade_isolada.pk), "pagina": "99"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta_ultima.status_code, 200)
        self.assertEqual(resposta_ultima.context["contratos"]["pagina"].number, 2)

    def test_vazio_e_inicio_futuro(self):
        hoje = localdate()
        unidade_vazia = Unidade.objects.create(nome="Unidade sem contratos 38-02")
        self.client.force_login(self.editor)
        resposta = self.client.get(
            reverse("pca:analise_prazos"),
            {"exercicio": "2026", "uo": str(unidade_vazia.pk)},
            HTTP_HOST="testserver",
        )
        self.assertIn("Nenhum item com contrato no recorte atual.", resposta.content.decode())

        self._criar_item_com_contrato(
            9001,
            vigencia_inicio=hoje + timedelta(days=30),
            vigencia_fim=hoje + timedelta(days=400),
        )
        resposta2 = self.client.get(
            reverse("pca:analise_prazos"), {"exercicio": "2026"}, HTTP_HOST="testserver"
        )
        secao = resposta2.content.decode()
        secao = secao[secao.find("Contratos a vencer"):secao.find("Lead time por etapa")]
        self.assertIn("Vigência ainda não iniciada", secao)

    def test_coluna_acao_so_com_editar_pca(self):
        self._criar_item_com_contrato(9001, renovacao_prevista=True)
        self._criar_item_com_contrato(9002, renovacao_prevista=False)
        self.client.force_login(self.editor)
        resposta = self.client.get(
            reverse("pca:analise_prazos"), {"exercicio": "2026"}, HTTP_HOST="testserver"
        )
        conteudo = resposta.content.decode()
        self.assertIn("Desmarcar renovação", conteudo)
        self.assertIn("Marcar renovação", conteudo)

        leitor = get_user_model().objects.create_user(
            email="leitor-contratos-38-02@pca.local", password="senha-segura"
        )
        leitor.user_permissions.add(
            Permission.objects.get(codename="ver_analises", content_type__app_label="pca"),
            Permission.objects.get(
                codename="view_acompanhamento", content_type__app_label="pca"
            ),
        )
        self.client.force_login(leitor)
        resposta_leitor = self.client.get(
            reverse("pca:analise_prazos"), {"exercicio": "2026"}, HTTP_HOST="testserver"
        )
        self.assertEqual(resposta_leitor.status_code, 200)
        conteudo_leitor = resposta_leitor.content.decode()
        secao = conteudo_leitor[
            conteudo_leitor.find("Contratos a vencer"):conteudo_leitor.find("Lead time por etapa")
        ]
        self.assertNotIn("analise_prazos_renovar", secao)
        self.assertNotIn("Marcar renovação", secao)


class TestContratosAVencerAcao(AnaliseTelasBase):
    """Fase 38 (spec §5) — ação de renovação nos dois
    sentidos: `destino` estrito (400 sem gravação), redirect reconstruído
    a partir dos ocultos validados (nunca `next`/`HTTP_REFERER`), saída
    do recorte explicada com link seguro (C02/C06)."""

    def test_desmarcar_sem_ocultos_redireciona_grava_historico_e_mensagem_com_destino(self):
        item = _criar_item_com_contrato(9001, renovacao_prevista=True)
        self.client.force_login(self.editor)
        historico_antes = item.history.count()
        acompanhamentos_antes = item.acompanhamentos.count()
        resposta = self.client.post(
            reverse("pca:analise_prazos_renovar", args=[2026, item.item_pca]),
            {"destino": "false"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(resposta.url, reverse("pca:analise_prazos"))
        item.refresh_from_db()
        self.assertFalse(item.renovacao_prevista)
        self.assertGreater(item.history.count(), historico_antes)
        self.assertEqual(item.acompanhamentos.count(), acompanhamentos_antes)
        rotulo_esperado = virada.destino(item.vigencia_fim, False, 2026, localdate()).rotulo
        mensagens = [str(m) for m in get_messages(resposta.wsgi_request)]
        self.assertIn(
            f"Item {item.item_pca}: renovação prevista desmarcada. "
            f"Destino em 2027: {virada.com_anos(rotulo_esperado, 2026)}.",
            mensagens,
        )

    def test_marcar_de_volta_botao_vira_inverso(self):
        item = _criar_item_com_contrato(9001, renovacao_prevista=False)
        self.client.force_login(self.editor)
        resposta = self.client.post(
            reverse("pca:analise_prazos_renovar", args=[2026, item.item_pca]),
            {"destino": "true"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 302)
        item.refresh_from_db()
        self.assertTrue(item.renovacao_prevista)
        mensagens = [str(m) for m in get_messages(resposta.wsgi_request)]
        self.assertTrue(any("marcada." in m for m in mensagens))
        resposta_get = self.client.get(
            reverse("pca:analise_prazos"), {"exercicio": "2026"}, HTTP_HOST="testserver"
        )
        self.assertIn("Desmarcar renovação", resposta_get.content.decode())

    def test_redirect_preserva_exercicio_duas_uos_vence_pagina_com_doseq(self):
        unidades = list(Unidade.objects.all()[:2])
        item = _criar_item_com_contrato(9001, unidade_organizacional=unidades[0])
        self.client.force_login(self.editor)
        resposta = self.client.post(
            reverse("pca:analise_prazos_renovar", args=[2026, item.item_pca]),
            {
                "destino": "false",
                "exercicio": "2026",
                "uo": [str(unidades[0].pk), str(unidades[1].pk)],
                "vence": "N",
                "renovacao": "todas",
                "destino_filtro": "",
                "grupo_destino": "",
                "pagina": "2",
            },
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 302)
        qs = parse_qs(urlparse(resposta.url).query)
        self.assertEqual(
            qs,
            {
                "exercicio": ["2026"],
                "uo": [str(unidades[0].pk), str(unidades[1].pk)],
                "vence": ["N"],
                "pagina": ["2"],
            },
        )

    def test_ocultos_invalidos_caem_no_padrao_nunca_500(self):
        item = _criar_item_com_contrato(9001)
        self.client.force_login(self.editor)
        resposta = self.client.post(
            reverse("pca:analise_prazos_renovar", args=[2026, item.item_pca]),
            {
                "destino": "false",
                "vence": "xyz",
                "renovacao": "talvez",
                "destino_filtro": "nada",
                "grupo_destino": "x",
                "pagina": "abc",
                "uo": "abc",
                "exercicio": "1999",
            },
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(resposta.url, reverse("pca:analise_prazos"))
        item.refresh_from_db()
        self.assertFalse(item.renovacao_prevista)

    def test_destino_invalido_ou_ausente_400_sem_gravar(self):
        item = _criar_item_com_contrato(9001, renovacao_prevista=True)
        self.client.force_login(self.editor)
        historico_antes = item.history.count()
        for dados in ({"destino": "maybe"}, {}, {"destino": "True"}):
            with self.subTest(dados=dados):
                resposta = self.client.post(
                    reverse("pca:analise_prazos_renovar", args=[2026, item.item_pca]),
                    dados,
                    HTTP_HOST="testserver",
                )
                self.assertEqual(resposta.status_code, 400)
        item.refresh_from_db()
        self.assertTrue(item.renovacao_prevista)
        self.assertEqual(item.history.count(), historico_antes)

    def test_saida_do_recorte_preserva_filtro_e_avisa_com_link_seguro(self):
        self.client.force_login(self.editor)

        item1 = _criar_item_com_contrato(9001, renovacao_prevista=True)
        resposta = self.client.post(
            reverse("pca:analise_prazos_renovar", args=[2026, item1.item_pca]),
            {"destino": "false", "renovacao": "sim"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 302)
        self.assertIn("renovacao=sim", resposta.url)
        mensagens = [str(m) for m in get_messages(resposta.wsgi_request)]
        aviso = next(
            (m for m in mensagens if m.startswith("O item deixou de atender aos filtros atuais")),
            None,
        )
        self.assertIsNotNone(aviso)
        self.assertIn('<a href="', aviso)
        href = aviso.split('href="')[1].split('"')[0]
        self.assertTrue(href.startswith(reverse("pca:analise_prazos")))
        qs_aviso = parse_qs(urlparse(href).query)
        self.assertNotIn("renovacao", qs_aviso)
        self.assertNotIn("destino", qs_aviso)
        self.assertNotIn("grupo_destino", qs_aviso)
        resposta_get = self.client.get(resposta.url, HTTP_HOST="testserver")
        conteudo_get = resposta_get.content.decode()
        secao_get = conteudo_get[
            conteudo_get.find("Contratos a vencer"):conteudo_get.find("Lead time por etapa")
        ]
        self.assertNotIn(str(item1.item_pca), secao_get)

        item2 = _criar_item_com_contrato(
            9002, renovacao_prevista=True, vigencia_fim=date(2026, 12, 31)
        )
        resposta2 = self.client.post(
            reverse("pca:analise_prazos_renovar", args=[2026, item2.item_pca]),
            {"destino": "false", "destino_filtro": "renova_n"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta2.status_code, 302)
        mensagens2 = [str(m) for m in get_messages(resposta2.wsgi_request)]
        self.assertTrue(
            any(m.startswith("O item deixou de atender aos filtros atuais") for m in mensagens2)
        )

        item3 = _criar_item_com_contrato(
            9003, renovacao_prevista=True, vigencia_fim=date(2026, 12, 31)
        )
        resposta3 = self.client.post(
            reverse("pca:analise_prazos_renovar", args=[2026, item3.item_pca]),
            {"destino": "false", "grupo_destino": "renovacao_n"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta3.status_code, 302)
        mensagens3 = [str(m) for m in get_messages(resposta3.wsgi_request)]
        self.assertTrue(
            any(m.startswith("O item deixou de atender aos filtros atuais") for m in mensagens3)
        )

    def test_sem_filtro_incompativel_item_permanece(self):
        item = _criar_item_com_contrato(9001, renovacao_prevista=True)
        self.client.force_login(self.editor)
        resposta = self.client.post(
            reverse("pca:analise_prazos_renovar", args=[2026, item.item_pca]),
            {"destino": "false", "renovacao": "todas", "vence": "N"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 302)
        mensagens = [str(m) for m in get_messages(resposta.wsgi_request)]
        self.assertFalse(any("deixou de atender" in m for m in mensagens))
        resposta_get = self.client.get(resposta.url, HTTP_HOST="testserver")
        conteudo = resposta_get.content.decode()
        self.assertIn(str(item.item_pca), conteudo)
        self.assertIn("Marcar renovação", conteudo)

    def test_item_inexistente_404(self):
        self.client.force_login(self.editor)
        resposta = self.client.post(
            reverse("pca:analise_prazos_renovar", args=[2026, 99999]),
            {"destino": "false"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 404)
        resposta2 = self.client.post(
            reverse("pca:analise_prazos_renovar", args=[2030, 1]),
            {"destino": "false"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta2.status_code, 404)

    def test_exercicio_fechado_recusa_com_mensagem_e_nao_grava(self):
        # QA 30/09 (achados fluxos nº4/dominio nº4) — "renovar?" não pode gravar em exercício
        # encerrado; a view converte ExercicioFechado em mensagem + redirect, nunca 500.
        fechado, _ = Exercicio.objects.get_or_create(
            ano=2017, defaults={"situacao": SituacaoExercicio.FECHADO}
        )
        item = _criar_item_com_contrato(9001, exercicio=fechado, renovacao_prevista=True)
        self.client.force_login(self.editor)
        resposta = self.client.post(
            reverse("pca:analise_prazos_renovar", args=[2017, item.item_pca]),
            {"destino": "false"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 302)
        item.refresh_from_db()
        self.assertTrue(item.renovacao_prevista)
        mensagens = [str(m) for m in get_messages(resposta.wsgi_request)]
        self.assertTrue(any("exercício 2017 está fechado" in m for m in mensagens))

    def test_pagina_com_digito_unicode_nunca_derruba_o_redirect(self):
        # QA 30/09 (fuzz M2) — "²".isdigit() é True mas int("²") levanta ValueError;
        # o redirect não pode crashear depois que a gravação já aconteceu com sucesso.
        item = _criar_item_com_contrato(9001, renovacao_prevista=True)
        self.client.force_login(self.editor)
        resposta = self.client.post(
            reverse("pca:analise_prazos_renovar", args=[2026, item.item_pca]),
            {"destino": "false", "pagina": "²"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 302)
        item.refresh_from_db()
        self.assertFalse(item.renovacao_prevista)


class TestContratosAVencerAcesso(AnaliseTelasBase):
    """Fase 38 (spec §6, C04) — matriz de acesso
    dupla (tela) / tripla (ação)."""

    def test_dirigente_sem_view_acompanhamento_403_tela_e_acao(self):
        item = _criar_item_com_contrato(9001)
        dirigente = get_user_model().objects.create_user(
            email="dirigente-38-02@pca.local", password="senha-segura"
        )
        dirigente.groups.add(Group.objects.get(name="dirigentes"))
        self.client.force_login(dirigente)
        resposta = self.client.get(
            reverse("pca:analise_prazos"), {"exercicio": "2026"}, HTTP_HOST="testserver"
        )
        self.assertEqual(resposta.status_code, 403)
        resposta_post = self.client.post(
            reverse("pca:analise_prazos_renovar", args=[2026, item.item_pca]),
            {"destino": "false"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta_post.status_code, 403)

    def test_leitura_sem_editar_pca_200_sem_acao_e_403_no_post(self):
        item = _criar_item_com_contrato(9001)
        leitor = get_user_model().objects.create_user(
            email="leitor-38-02-acesso@pca.local", password="senha-segura"
        )
        leitor.user_permissions.add(
            Permission.objects.get(codename="ver_analises", content_type__app_label="pca"),
            Permission.objects.get(
                codename="view_acompanhamento", content_type__app_label="pca"
            ),
        )
        self.client.force_login(leitor)
        resposta = self.client.get(
            reverse("pca:analise_prazos"), {"exercicio": "2026"}, HTTP_HOST="testserver"
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertNotIn("analise_prazos_renovar", resposta.content.decode())
        resposta_post = self.client.post(
            reverse("pca:analise_prazos_renovar", args=[2026, item.item_pca]),
            {"destino": "false"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta_post.status_code, 403)

    def test_editar_pca_sem_view_acompanhamento_403_no_post(self):
        item = _criar_item_com_contrato(9001)
        usuario = get_user_model().objects.create_user(
            email="editor-sem-acompanhamento-38-02@pca.local", password="senha-segura"
        )
        usuario.groups.add(Group.objects.get(name="dirigentes"))
        usuario.user_permissions.add(
            Permission.objects.get(codename="editar_pca", content_type__app_label="pca"),
        )
        self.client.force_login(usuario)
        resposta_post = self.client.post(
            reverse("pca:analise_prazos_renovar", args=[2026, item.item_pca]),
            {"destino": "false"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta_post.status_code, 403)

    def test_menu_dirigente_puro_nao_lista_prazos(self):
        from django.test import RequestFactory

        from core.menu import itens as itens_menu

        dirigente = get_user_model().objects.create_user(
            email="dirigente-menu-38-02@pca.local", password="senha-segura"
        )
        dirigente.groups.add(Group.objects.get(name="dirigentes"))
        rf = RequestFactory()
        request = rf.get("/")
        request.user = dirigente
        pasta = next(i for i in itens_menu(request) if i.get("rotulo") == "Análises")
        rotulos = [f["rotulo"] for f in pasta["filhos"]]
        self.assertNotIn("Prazos", rotulos)


class TestComAnosDestino(TestCase):
    """29/09/2026 — na tela de prazos, "N" vira o ano do PCA e "N+1" o seguinte."""

    def test_troca_n_e_n_mais_1(self):
        from apps.pca.projecao import virada

        self.assertEqual(virada.com_anos("Encerra em N", 2026), "Encerra em 2026")
        self.assertEqual(virada.com_anos("Vigente em N+1", 2026), "Vigente em 2027")
        self.assertEqual(
            virada.com_anos("Entra no PCA N+1 como Vigente; vence depois de N+1.", 2026),
            "Entra no PCA 2027 como Vigente; vence depois de 2027.",
        )
        self.assertEqual(virada.com_anos("Nova contratação em N", 2026), "Nova contratação em 2026")
        self.assertEqual(virada.com_anos("Encerra em N", None), "Encerra em N")


class TestLeadTimeDescartaDuracoesNegativas(TestCase):
    """QA 30/09 (domínio nº3) — duração negativa (assinatura ANTES do
    recebimento no Gelic, contrato reaproveitado de ciclo anterior) não
    pode contaminar mediana/P25/P75 do lead time de Análises › Prazos.
    Fixture leve (mesmo padrão de `TestQuerysetBase` em
    `test_querysets.py`), não `AnaliseTelasBase` (import real pesado)."""

    @classmethod
    def setUpTestData(cls):
        cls.unidade = Unidade.objects.create(nome="Presidência")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.tipo = Tipo.objects.create(nome="Aquisição")
        cls.exercicio = Exercicio.objects.get(ano=2026)
        cls.usuario = get_user_model().objects.create_user(
            email="lead-time-negativo@pca.local", password="senha-segura"
        )
        cls.usuario.user_permissions.add(
            Permission.objects.get(codename="ver_analises", content_type__app_label="pca"),
            Permission.objects.get(
                codename="view_acompanhamento", content_type__app_label="pca"
            ),
        )

    def setUp(self):
        self.client.force_login(self.usuario)

    def _criar_processo(self, item_pca, **kwargs):
        defaults = {
            "descricao_objeto": f"Objeto {item_pca}",
            "tipo": self.tipo,
            "categoria": self.categoria,
            "unidade_organizacional": self.unidade,
            "situacao": Situacao.CONCLUIDO,
        }
        defaults.update(kwargs)
        return Processo.objects.create(
            item_pca=item_pca, exercicio=self.exercicio, **defaults
        )

    def test_descarta_duracao_negativa_de_contrato_reaproveitado(self):
        self._criar_processo(
            1,
            data_envio_gelic=date(2026, 1, 10),
            data_recebimento_gelic=date(2026, 1, 20),
            data_assinatura_contrato=date(2026, 2, 1),  # 12 dias, válida
        )
        self._criar_processo(
            2,
            data_envio_gelic=date(2026, 1, 5),
            data_recebimento_gelic=date(2026, 9, 1),
            data_assinatura_contrato=date(2024, 3, 1),  # contrato reaproveitado — negativa
        )

        resposta = self.client.get(
            reverse("pca:analise_prazos"), {"exercicio": "2026"}, HTTP_HOST="testserver"
        )
        self.assertEqual(resposta.status_code, 200)
        etapa = resposta.context["lead_time_etapas"]["recebimento_assinatura"]
        self.assertEqual(etapa["descartados"], 1)
        self.assertEqual(etapa["mediana"], 12)
        self.assertIn("descartado", etapa["aviso"])
