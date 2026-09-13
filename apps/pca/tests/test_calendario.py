import re
from datetime import date
from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.http import QueryDict
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.catalogo.models import Exercicio
from apps.pca.filtros import MESES
from apps.pca.models import Acompanhamento, Estado, Processo, Situacao
from apps.pca.views import ORDEM_CONDICOES, ORDEM_ROSCA, _condicao_calendario

ARQUIVO_REAL = "apps/pca/fixtures/modelo-controle-exemplo.xlsx"

# Golden numbers do calendário anual: janeiro a dezembro, mais o único
# processo sem mês previsto. A ordem é a de meses, nunca a ordem
# incidental do banco. A fonte de bucketing é `prazo_efetivo`.
DISTRIBUICAO_DOURADA_POR_MES = (16, 22, 13, 12, 11, 18, 16, 10, 10, 10, 7, 3)


def _limpar_promessa_e_definir_prazo_entrega(processo, prazo):
    """Helper de teste: um processo pode já ter uma promessa vigente
    (`Acompanhamento.prazo_prometido`), que vence `prazo_entrega` no
    Coalesce de `prazo_efetivo`. Testes que precisam posicionar um
    processo numa data exata do calendário precisam neutralizar a
    promessa antes de setar `prazo_entrega`, senão a promessa continua
    mandando. `.update()` é bloqueado nos modelos versionados
    (managers.py), então percorre e salva um a um em vez de um UPDATE em
    massa."""
    for acompanhamento in Acompanhamento.objects.filter(
        processo=processo, prazo_prometido__isnull=False
    ):
        acompanhamento.prazo_prometido = None
        acompanhamento.save(update_fields=["prazo_prometido"])
    processo.prazo_entrega = prazo
    processo.save(update_fields=["prazo_entrega"])


class TestCalendarioAnual(TransactionTestCase):
    """Contrato observável do calendário anual. Mesmo padrão de
    `TestFiltrosTabela`/`TestDashboardGoldenNumbers`: import real em
    `setUp()` (TransactionTestCase nunca chama `setUpTestData()` e faz
    `flush()` a cada teste), `serialized_rollback=True` para preservar o
    usuário de serviço da migração de dados entre testes.

    A visão anual é 12 mini-calendários literais com marcador compacto
    por dia."""

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

    def _todas_paginas_tabela(self, **params):
        """Percorre todas as páginas de `/tabela` via
        `response.context["pagina"]` — mesmo padrão de
        `TestFiltrosTabela._todas_paginas`, usado aqui para provar a
        paridade de conjunto entre as duas visões."""
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

    def test_reverse_pca_calendario_resolve(self):
        self.assertEqual(reverse("pca:calendario"), "/calendario")

    # --- calendário anual, ordem cronológica ------------------------------

    def test_doze_meses_na_ordem_anual_e_sem_mes_explicito(self):
        resposta = self.client.get(reverse("pca:calendario"), {"visao": "anual"})
        self.assertEqual(resposta.status_code, 200)
        meses = resposta.context["meses"]
        self.assertEqual([mes["numero"] for mes in meses], list(MESES))
        self.assertEqual(len(meses), 12)
        self.assertEqual(resposta.context["sem_mes"]["numero"], None)
        conteudo = resposta.content.decode("utf-8")
        for rotulo in ("Janeiro", "Dezembro", "Sem mês previsto"):
            self.assertIn(rotulo, conteudo)

    def test_distribuicao_dourada_por_mes_e_total_30(self):
        resposta = self.client.get(reverse("pca:calendario"), {"visao": "anual"})
        meses = resposta.context["meses"]
        self.assertEqual(resposta.context["sem_mes"]["total"], 1)
        self.assertEqual(
            sum(mes["total"] for mes in meses) + resposta.context["sem_mes"]["total"],
            30,
        )

    def test_mes_vazio_permanece_visivel_com_estado_proprio(self):
        # quick-260810-l1o — a grade literal substitui a lista vertical
        # (a frase "Nenhum processo previsto neste mês" some do template
        # nesta quick); a prova de que o mês vazio continua presente passa a
        # ser via contexto: janeiro (numero=1) existe em `meses_grade` com
        # total agregado zero, não mais uma frase fixa no HTML.
        # A fonte de bucketing é `prazo_efetivo`: neutraliza promessa
        # vigente e `prazo_entrega` de qualquer processo que caia em
        # janeiro, para garantir o mês vazio.
        for processo in list(Processo.objects.para_listagem().all()):
            if processo.mes_previsto == 1 or (
                processo.prazo_efetivo and processo.prazo_efetivo.month == 1
            ):
                for acompanhamento in Acompanhamento.objects.filter(
                    processo=processo, prazo_prometido__isnull=False
                ):
                    acompanhamento.prazo_prometido = None
                    acompanhamento.save(update_fields=["prazo_prometido"])
                processo.mes_previsto = 2
                processo.prazo_entrega = None
                processo.save(update_fields=["mes_previsto", "prazo_entrega"])
        resposta = self.client.get(reverse("pca:calendario"), {"visao": "anual"})
        meses_grade = resposta.context["meses_grade"]
        janeiro = next(mes for mes in meses_grade if mes["numero"] == 1)
        total_janeiro = sum(
            celula["total"]
            for semana in janeiro["semanas"]
            for celula in semana
            if celula["do_mes"]
        )
        self.assertEqual(total_janeiro, 0)

    # --- grade literal anual (quick-260810-l1o) -----------------------------

    def test_grade_anual_tem_doze_mini_calendarios_com_semanas_de_sete_dias(self):
        resposta = self.client.get(reverse("pca:calendario"), {"visao": "anual"})
        meses_grade = resposta.context["meses_grade"]
        self.assertEqual(len(meses_grade), 12)
        self.assertEqual([mes["numero"] for mes in meses_grade], list(MESES))
        for mes in meses_grade:
            for semana in mes["semanas"]:
                self.assertEqual(len(semana), 7)

    def test_grade_anual_marca_o_dia_com_contador_e_condicao_sem_query_por_mes(self):
        # `condicoes_presentes` opera no espaço de 5 condições
        # (Cancelado + 4 situações efetivas), não o enum `status`.
        processo = Processo.objects.get(item_pca=26)
        _limpar_promessa_e_definir_prazo_entrega(processo, date(2026, 3, 10))
        # Neutraliza o prazo recém-definido para não disparar a correção
        # de leitura (o teste marca o dia, não testa atraso).
        processo.situacao = Situacao.NO_PRAZO.value
        processo.prazo_entrega = date(2026, 3, 10)
        processo.save(update_fields=["situacao", "prazo_entrega"])

        resposta = self.client.get(reverse("pca:calendario"), {"visao": "anual"})
        meses_grade = resposta.context["meses_grade"]
        marco = next(mes for mes in meses_grade if mes["numero"] == 3)
        celula = next(
            celula
            for semana in marco["semanas"]
            for celula in semana
            if celula["do_mes"] and celula["data"] == date(2026, 3, 10)
        )
        self.assertEqual(celula["total"], 1)
        processo_anotado = Processo.objects.para_listagem().get(item_pca=26)
        eixo_esperado, valor_esperado = _condicao_calendario(processo_anotado)
        # Quick 260909-rwm — `condicoes_presentes` virou lista de DICTS
        # (`eixo`/`valor`/`rotulo`/`classe`), não mais tuplas.
        self.assertEqual(len(celula["condicoes_presentes"]), 1)
        self.assertEqual(celula["condicoes_presentes"][0]["eixo"], eixo_esperado)
        self.assertEqual(celula["condicoes_presentes"][0]["valor"], valor_esperado)

        with CaptureQueriesContext(connection) as sem_filtro:
            self.client.get(reverse("pca:calendario"), {"visao": "anual"})
        with CaptureQueriesContext(connection) as com_filtro:
            self.client.get(
                reverse("pca:calendario"),
                {"visao": "anual", "status": "nao_iniciado"},
            )
        self.assertEqual(
            len(sem_filtro.captured_queries), len(com_filtro.captured_queries)
        )

    def test_grade_anual_querystring_abrir_preserva_filtro_e_aponta_para_o_mes(self):
        # `situacao=no_prazo` é o parâmetro real hoje (Situacao.choices).
        resposta = self.client.get(
            reverse("pca:calendario"),
            {"visao": "anual", "situacao": "no_prazo"},
        )
        marco = resposta.context["meses_grade"][2]
        self.assertEqual(marco["numero"], 3)
        querystring = marco["querystring_abrir"]
        self.assertIn("visao=mensal", querystring)
        self.assertIn("mes_calendario=3", querystring)
        self.assertIn("situacao=no_prazo", querystring)

    # --- grade literal anual e cards mensais compactos (quick-260810-l1o) --

    def test_grade_anual_marca_dia_sem_descricao_e_link_abre_o_mes(self):
        # A grade anual identifica 1 item por dia (número + `aria-label`
        # com "Item N: objeto", `truncatechars:40` sobre a descrição
        # completa); a frase longa do objeto do item 26 (fixture de
        # exemplo) começa bem depois do caractere 40, então o truncamento
        # nunca a revela — nem em texto visível, nem dentro do
        # `aria-label`.
        processo = Processo.objects.get(item_pca=26)
        _limpar_promessa_e_definir_prazo_entrega(processo, date(2026, 3, 10))

        resposta = self.client.get(reverse("pca:calendario"), {"visao": "anual"})
        conteudo = resposta.content.decode("utf-8")
        self.assertNotIn("Gerenciamento de Serviços de TI (ITSM)", conteudo)
        self.assertIn("mes_calendario=3", conteudo)
        self.assertIn("visao=mensal", conteudo)

    def test_cartoes_mensais_sao_compactos_sem_descricao_longa(self):
        # A grade mensal usa `{% tag_status %}` (pílula do DS, texto
        # visível); a condição do evento é provada pelo rótulo
        # renderizado, não por um atributo `data-*`.
        from apps.pca.templatetags.pca_listagem import rotulo_situacao

        processo = Processo.objects.get(item_pca=26)
        _limpar_promessa_e_definir_prazo_entrega(processo, date(2026, 3, 10))

        resposta = self.client.get(
            reverse("pca:calendario"), {"visao": "mensal", "mes_calendario": "3"}
        )
        conteudo = resposta.content.decode("utf-8")
        self.assertIn(f"Item {processo.item_pca}", conteudo)
        self.assertNotIn("Gerenciamento de Serviços de TI (ITSM)", conteudo)
        anotado = Processo.objects.para_listagem().get(pk=processo.pk)
        self.assertIn(rotulo_situacao(anotado.situacao_efetiva), conteudo)

    def test_dia_com_mais_de_tres_eventos_lista_ate_tres_e_link_mais_n(self):
        # Quick 260909-rwm (`telas/calendario.md`) — a célula lista até 3
        # eventos e um link "+n" para a tabela filtrada por aquele dia
        # (`dia_calendario`), no lugar da listagem completa sem truncar.
        base = Processo.objects.get(item_pca=26)
        _limpar_promessa_e_definir_prazo_entrega(base, date(2026, 3, 10))
        for indice in range(4):
            Processo.objects.create(
                item_pca=200 + indice,
                descricao_objeto=f"Processo sintético {indice}",
                tipo=base.tipo,
                categoria=base.categoria,
                unidade_organizacional=base.unidade_organizacional,
                valor_estimado=Decimal("1.00"),
                mes_previsto=3,
                prazo_entrega=date(2026, 3, 10),
                exercicio=base.exercicio,
            )

        resposta = self.client.get(
            reverse("pca:calendario"), {"visao": "mensal", "mes_calendario": "3"}
        )
        conteudo = resposta.content.decode("utf-8")
        # Ordem estável por `item_pca` (item base, 200, 201, 202, 203):
        # os 3 primeiros (limite mensal) ficam visíveis, os 2 últimos só
        # no "+2". O texto visível do item é só o número (sem o prefixo
        # "Item"); "Item N: objeto" continua no `aria-label`.
        self.assertRegex(conteudo, rf">{base.item_pca}</a>")
        self.assertIn(">200</a>", conteudo)
        self.assertIn(">201</a>", conteudo)
        self.assertNotIn(">202</a>", conteudo)
        self.assertNotIn(">203</a>", conteudo)
        self.assertIn(f'aria-label="Item {base.item_pca}:', conteudo)
        self.assertIn('aria-label="Item 200:', conteudo)
        self.assertIn('aria-label="Item 201:', conteudo)
        self.assertNotIn('aria-label="Item 202:', conteudo)
        self.assertNotIn('aria-label="Item 203:', conteudo)
        self.assertIn(">+2<", conteudo)
        match = re.search(r'href="([^"]*)">\+2<', conteudo)
        self.assertIsNotNone(match)
        href = match.group(1).replace("&amp;", "&")
        self.assertIn("dia_calendario=2026-03-10", href)
        resposta_tabela = self.client.get(href)
        self.assertEqual(resposta_tabela.context["pagina"].paginator.count, 5)

    # --- grade uniforme -----------------------------------------------------

    def test_fevereiro_comum_e_bissexto_tem_sempre_42_celulas_mensal_e_anual(self):
        # 2026 não é bissexto (28 dias em fevereiro); 2028 é bissexto (29
        # dias) — os dois têm exatamente 42 células (6 semanas x 7 dias) na
        # visão mensal E na mini-grade anual, sem NENHUMA data inventada
        # fora de sequência (cada célula de preenchimento é a continuação
        # cronológica real da semana anterior).
        Exercicio.objects.get_or_create(
            ano=2028, defaults={"rotulo": "PCA 2028", "situacao": "aberto"}
        )
        for ano in (2026, 2028):
            with self.subTest(ano=ano):
                resposta = self.client.get(
                    reverse("pca:calendario"),
                    {"visao": "mensal", "mes_calendario": "2", "exercicio": ano},
                )
                semanas = resposta.context["semanas_calendario"]
                self.assertEqual(len(semanas), 6)
                self.assertTrue(all(len(semana) == 7 for semana in semanas))
                # Continuação cronológica real: cada dia é exatamente um dia
                # depois do anterior, do início ao fim da grade completa.
                todos_os_dias = [dia["data"] for semana in semanas for dia in semana]
                for anterior, atual in zip(todos_os_dias, todos_os_dias[1:]):
                    self.assertEqual((atual - anterior).days, 1)

                resposta_anual = self.client.get(
                    reverse("pca:calendario"),
                    {"visao": "anual", "exercicio": ano},
                )
                fevereiro = next(
                    mes
                    for mes in resposta_anual.context["meses_grade"]
                    if mes["numero"] == 2
                )
                self.assertEqual(len(fevereiro["semanas"]), 6)
                self.assertTrue(
                    all(len(semana) == 7 for semana in fevereiro["semanas"])
                )

    def test_dia_com_quatro_eventos_mostra_1_mais_3_na_anual_e_3_mais_1_na_mensal(self):
        base = Processo.objects.get(item_pca=26)
        _limpar_promessa_e_definir_prazo_entrega(base, date(2026, 3, 10))
        for indice in range(3):
            Processo.objects.create(
                item_pca=300 + indice,
                descricao_objeto=f"Quarto processo {indice}",
                tipo=base.tipo,
                categoria=base.categoria,
                unidade_organizacional=base.unidade_organizacional,
                valor_estimado=Decimal("1.00"),
                mes_previsto=3,
                prazo_entrega=date(2026, 3, 10),
                exercicio=base.exercicio,
            )

        resposta_anual = self.client.get(reverse("pca:calendario"), {"visao": "anual"})
        marco = next(
            mes for mes in resposta_anual.context["meses_grade"] if mes["numero"] == 3
        )
        celula_anual = next(
            celula
            for semana in marco["semanas"]
            for celula in semana
            if celula["do_mes"] and celula["data"] == date(2026, 3, 10)
        )
        self.assertEqual(celula_anual["total"], 4)
        self.assertEqual(len(celula_anual["eventos_visiveis"]), 1)
        self.assertEqual(celula_anual["eventos_ocultos"], 3)

        resposta_mensal = self.client.get(
            reverse("pca:calendario"), {"visao": "mensal", "mes_calendario": "3"}
        )
        celula_mensal = next(
            celula
            for semana in resposta_mensal.context["semanas_calendario"]
            for celula in semana
            if celula["do_mes"] and celula["data"] == date(2026, 3, 10)
        )
        self.assertEqual(celula_mensal["total"], 4)
        self.assertEqual(len(celula_mensal["eventos_visiveis"]), 3)
        self.assertEqual(celula_mensal["eventos_ocultos"], 1)

        # Nenhum item some sem "+N": visíveis + ocultos == total, nas duas
        # visões.
        self.assertEqual(
            len(celula_anual["eventos_visiveis"]) + celula_anual["eventos_ocultos"],
            celula_anual["total"],
        )
        self.assertEqual(
            len(celula_mensal["eventos_visiveis"]) + celula_mensal["eventos_ocultos"],
            celula_mensal["total"],
        )

    def test_ordem_dos_itens_dentro_do_dia_e_sempre_por_item_pca_crescente(self):
        base = Processo.objects.get(item_pca=26)
        _limpar_promessa_e_definir_prazo_entrega(base, date(2026, 3, 10))
        # Cria fora de ordem (203 antes de 201) para provar que a ordem
        # final não é a de inserção/banco, e sim `item_pca` crescente.
        for item_pca in (203, 201, 202):
            Processo.objects.create(
                item_pca=item_pca,
                descricao_objeto=f"Sintético {item_pca}",
                tipo=base.tipo,
                categoria=base.categoria,
                unidade_organizacional=base.unidade_organizacional,
                valor_estimado=Decimal("1.00"),
                mes_previsto=3,
                prazo_entrega=date(2026, 3, 10),
                exercicio=base.exercicio,
            )

        for _ in range(2):
            resposta = self.client.get(
                reverse("pca:calendario"), {"visao": "mensal", "mes_calendario": "3"}
            )
            celula = next(
                celula
                for semana in resposta.context["semanas_calendario"]
                for celula in semana
                if celula["do_mes"] and celula["data"] == date(2026, 3, 10)
            )
            itens = [
                evento["processo"].item_pca for evento in celula["eventos"]
            ]
            self.assertEqual(itens, sorted(itens))
            self.assertEqual(itens, [26, 201, 202, 203])

    def test_grade_anual_usa_col_xl_3_nunca_col_lg_3_isolado(self):
        # 4 meses por linha só a partir de 1600px (`col-xl-3`); a classe
        # `col-lg-3` isolada (sem `col-xl-3` par) não pode aparecer.
        resposta = self.client.get(reverse("pca:calendario"), {"visao": "anual"})
        conteudo = resposta.content.decode("utf-8")
        self.assertIn("col-12 col-md-6 col-lg-4 col-xl-3", conteudo)
        self.assertNotIn("col-sm-6 col-lg-3", conteudo)

    def test_css_do_calendario_tem_alturas_fixas_e_bloco_pointer_coarse(self):
        caminho = Path(settings.BASE_DIR) / "core/static/dsgov/css/dsgov.css"
        css = caminho.read_text(encoding="utf-8")
        self.assertIn("80px", css)
        self.assertIn("128px", css)
        self.assertIn("112px", css)
        self.assertIn("192px", css)
        self.assertIn("pointer: coarse", css)

    # --- popover acessível ---------------------------------------------------

    def test_popover_do_item_tem_estrutura_acessivel_e_conteudo_correto(self):
        processo = Processo.objects.get(item_pca=26)
        _limpar_promessa_e_definir_prazo_entrega(processo, date(2026, 3, 10))
        processo.refresh_from_db()
        processo.valor_contratado = Decimal("0")
        processo.save(update_fields=["valor_contratado"])

        resposta = self.client.get(
            reverse("pca:calendario"), {"visao": "mensal", "mes_calendario": "3"}
        )
        conteudo = resposta.content.decode("utf-8")
        popover_id = f"popover-calendario-{processo.pk}"
        # Ativador: `<a>` real (fallback sem JS), `data-popover-calendario`
        # + `aria-describedby` apontando ao popover.
        self.assertIn("data-popover-calendario", conteudo)
        self.assertIn(f'aria-describedby="{popover_id}"', conteudo)
        # Popover: irmão IMEDIATO do ativador (mesma exigência estrutural
        # do `.br-tooltip` nativo), `role="dialog"`/`aria-modal="false"`,
        # NUNCA o atributo HTML5 nativo `popover` isolado (Popover API —
        # ver dsgov.js/dsgov.css).
        match = re.search(
            r'<a class="dsgov-calendario-item[^>]*>[^<]*</a><div class="br-tooltip"([^>]*)>',
            conteudo,
        )
        self.assertIsNotNone(match)
        atributos_popover = match.group(1)
        self.assertIn('role="dialog"', atributos_popover)
        self.assertIn('aria-modal="false"', atributos_popover)
        self.assertIn(f'id="{popover_id}"', atributos_popover)
        self.assertNotRegex(atributos_popover, r'(^| )popover(=|>| )')
        # Conteúdo: Item/Objeto (header), UO/Valor previsto/Valor
        # contratado (body — "0" aparece, zero é preenchimento real),
        # "Ver mais"/"Fechar detalhes" (footer).
        self.assertIn(f"<span class=\"text\">Item {processo.item_pca}</span>", conteudo)
        self.assertIn(processo.unidade_organizacional.nome, conteudo)
        self.assertIn("Valor contratado: R$ 0,00", conteudo)
        self.assertIn("Ver mais", conteudo)
        self.assertIn("Fechar detalhes", conteudo)
        self.assertIn("data-fechar-popover-calendario", conteudo)

    def test_popover_omite_valor_contratado_quando_realmente_ausente(self):
        processo = Processo.objects.get(item_pca=26)
        _limpar_promessa_e_definir_prazo_entrega(processo, date(2026, 3, 10))
        processo.refresh_from_db()
        processo.valor_contratado = None
        processo.save(update_fields=["valor_contratado"])

        resposta = self.client.get(
            reverse("pca:calendario"), {"visao": "mensal", "mes_calendario": "3"}
        )
        conteudo = resposta.content.decode("utf-8")
        self.assertNotIn("Valor contratado:", conteudo)

    def test_dsgov_js_exclui_popover_calendario_do_brtooltip_e_implementa_comportamento_proprio(self):
        caminho = Path(settings.BASE_DIR) / "core/static/dsgov/js/dsgov.js"
        js = caminho.read_text(encoding="utf-8")
        self.assertIn("data-popover-calendario", js)
        self.assertIn(':not([data-popover-calendario])', js)
        self.assertIn("data-fixado", js)
        self.assertIn("Escape", js)
        # Nunca reintroduz a inicialização automática do BRTooltip para o
        # popover próprio (regra literal do plano: excluir, nunca só
        # documentar).
        self.assertNotIn('new Ctor("br-tooltip", el)', js)

    def test_mais_n_com_legenda_isolada_em_atrasado_bate_com_a_contagem_de_atrasados_do_dia(self):
        # "+n" precisa abrir a mesma seleção de situações da legenda,
        # não o total bruto do dia. 4 atrasados (> limite mensal de 3)
        # força o "+1"; 1 em tramitação no mesmo dia fica de fora da
        # seleção — sem a paridade de filtro, o "+n"/a contagem o
        # incluiriam também.
        base = Processo.objects.get(item_pca=26)
        _limpar_promessa_e_definir_prazo_entrega(base, date(2026, 3, 10))
        base.situacao = Situacao.ATRASADO.value
        base.save(update_fields=["situacao"])
        # Um "no_prazo" gravado com prazo vencido é corrigido na leitura
        # para "atrasado" (a data de teste, 2026-03-10, já passou);
        # "em_tramitacao" não sofre essa correção, então é o valor
        # genuíno para provar a exclusão pela legenda isolada.
        for indice, situacao in enumerate(
            (Situacao.ATRASADO, Situacao.ATRASADO, Situacao.ATRASADO, Situacao.EM_TRAMITACAO)
        ):
            Processo.objects.create(
                item_pca=210 + indice,
                descricao_objeto=f"Paridade condicao_legenda {indice}",
                tipo=base.tipo,
                categoria=base.categoria,
                unidade_organizacional=base.unidade_organizacional,
                valor_estimado=Decimal("1.00"),
                mes_previsto=3,
                prazo_entrega=date(2026, 3, 10),
                exercicio=base.exercicio,
                situacao=situacao.value,
            )

        resposta = self.client.get(
            reverse("pca:calendario"),
            {
                "visao": "mensal",
                "mes_calendario": "3",
                "condicao_legenda": "situacao:atrasado",
            },
        )
        celula = next(
            celula
            for semana in resposta.context["semanas_calendario"]
            for celula in semana
            if celula["do_mes"] and celula["data"] == date(2026, 3, 10)
        )
        # A célula (bucketização em Python) já enxerga só os 4 atrasados —
        # 3 visíveis (limite mensal) + "+1" oculto, nunca os 5 do dia todo.
        self.assertEqual(celula["total"], 4)
        self.assertEqual(celula["eventos_ocultos"], 1)
        conteudo = resposta.content.decode()
        self.assertIn(">+1<", conteudo)
        match = re.search(r'href="([^"]*)">\+1<', conteudo)
        self.assertIsNotNone(match)
        href = match.group(1).replace("&amp;", "&")
        self.assertIn("dia_calendario=2026-03-10", href)
        self.assertIn("condicao_legenda=situacao%3Aatrasado", href)
        resposta_tabela = self.client.get(href)
        self.assertEqual(resposta_tabela.context["pagina"].paginator.count, 4)
        for processo in resposta_tabela.context["pagina"].object_list:
            self.assertEqual(processo.situacao_efetiva, Situacao.ATRASADO.value)

    def test_mais_n_com_legenda_cancelados_ou_atrasados_devolve_uniao(self):
        base = Processo.objects.get(item_pca=26)
        _limpar_promessa_e_definir_prazo_entrega(base, date(2026, 3, 10))
        base.situacao = Situacao.ATRASADO.value
        base.save(update_fields=["situacao"])
        cancelado = Processo.objects.create(
            item_pca=220,
            descricao_objeto="Cancelado no mesmo dia",
            tipo=base.tipo,
            categoria=base.categoria,
            unidade_organizacional=base.unidade_organizacional,
            valor_estimado=Decimal("1.00"),
            mes_previsto=3,
            prazo_entrega=date(2026, 3, 10),
            exercicio=base.exercicio,
            estado=Estado.CANCELADO.value,
        )
        # "em_tramitacao" (não "no_prazo") para o excluído: um "no_prazo"
        # gravado com prazo vencido corrige na leitura para "atrasado"
        # (2026-03-10 já passou), o que faria esta fixture entrar na
        # união por engano.
        Processo.objects.create(
            item_pca=221,
            descricao_objeto="Em tramitação no mesmo dia (fora da seleção)",
            tipo=base.tipo,
            categoria=base.categoria,
            unidade_organizacional=base.unidade_organizacional,
            valor_estimado=Decimal("1.00"),
            mes_previsto=3,
            prazo_entrega=date(2026, 3, 10),
            exercicio=base.exercicio,
            situacao=Situacao.EM_TRAMITACAO.value,
        )

        resposta = self.client.get(
            reverse("pca:tabela"),
            QueryDict(
                "condicao_legenda=estado%3Acancelado"
                "&condicao_legenda=situacao%3Aatrasado"
                "&dia_calendario=2026-03-10"
            ),
        )
        itens = {p.item_pca for p in resposta.context["pagina"].object_list}
        self.assertEqual(itens, {base.item_pca, cancelado.item_pca})

    # --- paridade de filtro com a tabela --------------------------------------

    def test_mesmo_querystring_abre_o_mesmo_conjunto_na_tabela_e_no_calendario(self):
        alvo = Processo.objects.filter(tipo__nome_normalizado="vigente").first()
        params = {
            "situacao": Situacao.CONCLUIDO.value,
            "uo": alvo.unidade_organizacional_id,
        }
        resposta = self.client.get(reverse("pca:calendario"), params)
        conjunto_calendario = {
            p.item_pca
            for agrupamento in [*resposta.context["meses"], resposta.context["sem_mes"]]
            for p in agrupamento["processos"]
        }
        conjunto_tabela = {
            p.item_pca for p in self._todas_paginas_tabela(**params)
        }
        self.assertGreater(len(conjunto_calendario), 0)
        self.assertEqual(conjunto_calendario, conjunto_tabela)

    def test_grade_mensal_particiona_datas_reais_e_fallbacks_sem_duplicar(self):
        base = Processo.objects.get(item_pca=26)
        base.mes_previsto = 1
        base.save(update_fields=["mes_previsto"])
        _limpar_promessa_e_definir_prazo_entrega(base, date(2026, 2, 15))
        apenas_mes = Processo.objects.create(
            item_pca=200, descricao_objeto="Apenas mês", tipo=base.tipo,
            categoria=base.categoria, unidade_organizacional=base.unidade_organizacional,
            valor_estimado=Decimal("1.00"), mes_previsto=2,
            exercicio=base.exercicio,
        )
        sem_mes = Processo.objects.create(
            item_pca=201, descricao_objeto="Sem mês", tipo=base.tipo,
            categoria=base.categoria, unidade_organizacional=base.unidade_organizacional,
            valor_estimado=Decimal("1.00"), exercicio=base.exercicio,
        )
        fora_exercicio = Processo.objects.create(
            item_pca=202, descricao_objeto="Data fora do exercício", tipo=base.tipo,
            categoria=base.categoria, unidade_organizacional=base.unidade_organizacional,
            valor_estimado=Decimal("1.00"), mes_previsto=2,
            prazo_entrega=date(2027, 2, 1), exercicio=base.exercicio,
        )

        resposta = self.client.get(
            reverse("pca:calendario"), {"visao": "mensal", "mes_calendario": "2"}
        )
        self.assertEqual(resposta.context["visao_calendario"], "mensal")
        self.assertEqual(resposta.context["mes_calendario"], 2)
        # Sempre 6 semanas (42 células), mesmo fevereiro (que
        # `Calendar.monthdatescalendar` devolveria com só 4 semanas em
        # 2026, ano não bissexto).
        self.assertEqual(len(resposta.context["semanas_calendario"]), 6)
        self.assertTrue(all(len(semana) == 7 for semana in resposta.context["semanas_calendario"]))
        ids_datados = {
            evento["processo"].pk
            for semana in resposta.context["semanas_calendario"]
            for celula in semana
            for evento in celula["eventos"]
        }
        ids_sem_dia = {
            evento["processo"].pk
            for evento in resposta.context["sem_dia_do_mes"]["eventos"]
        }
        ids_sem_mes = {
            evento["processo"].pk
            for evento in resposta.context["sem_mes"]["eventos"]
        }
        self.assertEqual(ids_datados & ids_sem_dia, set())
        self.assertEqual(ids_datados & ids_sem_mes, set())
        self.assertEqual(ids_sem_dia & ids_sem_mes, set())
        self.assertIn(base.pk, ids_datados)
        self.assertIn(apenas_mes.pk, ids_sem_dia)
        self.assertIn(fora_exercicio.pk, ids_sem_dia)
        self.assertIn(sem_mes.pk, ids_sem_mes)
        self.assertTrue(
            any(evento["data_fora_exercicio"] for evento in resposta.context["sem_dia_do_mes"]["eventos"])
        )

    # --- prazo efetivo --------------------------------------------------------

    def test_calendario_usa_prazo_efetivo_nao_conclusao_contratacao(self):
        """`data_prevista_conclusao` não escolhe o dia; a promessa
        vigente vence sobre `prazo_entrega`, e sem promessa o processo
        cai no dia do prazo de Planejamento."""
        processo = Processo.objects.get(item_pca=26)
        # `data_prevista_conclusao` apontando para um dia diferente do
        # prazo_efetivo real não deve mover o processo do dia certo.
        processo.data_prevista_conclusao = date(2026, 1, 5)
        processo.save(update_fields=["data_prevista_conclusao"])

        resposta = self.client.get(
            reverse("pca:calendario"),
            {"visao": "mensal", "mes_calendario": "1"},
        )
        ids_janeiro = {
            evento["processo"].pk
            for semana in resposta.context["semanas_calendario"]
            for celula in semana
            for evento in celula["eventos"]
        }
        self.assertNotIn(processo.pk, ids_janeiro)

        # Sem promessa vigente, cai no dia de `prazo_entrega`.
        sem_promessa = Processo.objects.get(item_pca=1)
        _limpar_promessa_e_definir_prazo_entrega(sem_promessa, date(2026, 4, 20))
        resposta_abril = self.client.get(
            reverse("pca:calendario"),
            {"visao": "mensal", "mes_calendario": "4"},
        )
        eventos_abril = {
            evento["processo"].pk: evento
            for semana in resposta_abril.context["semanas_calendario"]
            for celula in semana
            for evento in celula["eventos"]
        }
        self.assertIn(sem_promessa.pk, eventos_abril)

    def test_atraso_e_dias_aparecem_no_calendario(self):
        """O calendário lê `atrasado`/`dias_atraso`/`qualificador_prazo`
        já anotados, sem recalcular. Fabrica um processo vencido
        (prazo_entrega no passado, sem entrega) e prova o badge de dias
        na superfície."""
        exercicio = Processo.objects.get(item_pca=1).exercicio
        vencido = Processo.objects.create(
            item_pca=920,
            exercicio=exercicio,
            descricao_objeto="Atraso visível no calendário",
            tipo=Processo.objects.get(item_pca=1).tipo,
            categoria=Processo.objects.get(item_pca=1).categoria,
            unidade_organizacional=Processo.objects.get(item_pca=1).unidade_organizacional,
            prazo_entrega=date(2020, 1, 1),
            mes_previsto=1,
        )

        resposta_calendario = self.client.get(
            reverse("pca:calendario"),
            {"visao": "mensal", "mes_calendario": "1"},
        )
        conteudo_calendario = resposta_calendario.content.decode("utf-8")
        self.assertRegex(conteudo_calendario, r"Atrasado há \d+ dia")

    def test_controles_do_calendario_sao_allowlist_e_anual_exibe_legenda(self):
        resposta = self.client.get(
            reverse("pca:calendario"), {"visao": "injetada", "mes_calendario": "99"}
        )
        self.assertEqual(resposta.context["visao_calendario"], "anual")
        self.assertIn(resposta.context["mes_calendario"], MESES)

        resposta = self.client.get(reverse("pca:calendario"), {"visao": "anual"})
        self.assertEqual(resposta.context["visao_calendario"], "anual")
        self.assertEqual([mes["numero"] for mes in resposta.context["meses"]], list(MESES))
        conteudo = resposta.content.decode("utf-8")
        # A legenda usa as 5 condições de ORDEM_ROSCA (Cancelado + 4
        # situações efetivas).
        for _eixo, _valor, rotulo in ORDEM_ROSCA:
            self.assertIn(rotulo, conteudo)

    # --- visão anual como padrão -----------------------------------------

    def test_visao_anual_e_o_padrao_sem_parametro(self):
        resposta = self.client.get(reverse("pca:calendario"))
        self.assertEqual(resposta.context["visao_calendario"], "anual")

    def test_visao_mensal_explicita_continua_honrada(self):
        resposta = self.client.get(reverse("pca:calendario"), {"visao": "mensal"})
        self.assertEqual(resposta.context["visao_calendario"], "mensal")

    # --- legenda no espaço de 5 condições — Cancelado (eixo Estado) +
    # as 4 situações efetivas dos ativos (eixo Situação, `ORDEM_ROSCA`,
    # mesma ordem canônica que a rosca do dashboard). ---------------------

    def _total_processos(self, resposta):
        meses = resposta.context["meses"]
        return sum(mes["total"] for mes in meses) + resposta.context["sem_mes"]["total"]

    # --- Teste 1 (behavior 17-09) — condição única por processo -----------

    def test_condicao_calendario_e_unica_cancelado_vence_situacao(self):
        base = Processo.objects.first()
        cancelado = Processo.objects.create(
            item_pca=901, exercicio=base.exercicio, descricao_objeto="Cancelado",
            tipo=base.tipo, categoria=base.categoria,
            unidade_organizacional=base.unidade_organizacional,
            estado=Estado.CANCELADO.value, situacao=Situacao.EM_TRAMITACAO.value,
        )
        # Cancelado tem condição fixa no eixo Estado, independente da
        # `situacao` gravada — não precisa da annotation
        # `situacao_efetiva` para este ramo.
        self.assertEqual(
            _condicao_calendario(cancelado), ("estado", Estado.CANCELADO.value)
        )

        ativo = Processo.objects.create(
            item_pca=902, exercicio=base.exercicio,
            descricao_objeto="Ativo em tramitação",
            tipo=base.tipo, categoria=base.categoria,
            unidade_organizacional=base.unidade_organizacional,
            estado=Estado.ATIVO.value, situacao=Situacao.EM_TRAMITACAO.value,
        )
        ativo_anotado = Processo.objects.para_listagem().get(pk=ativo.pk)
        self.assertEqual(
            _condicao_calendario(ativo_anotado),
            ("situacao", Situacao.EM_TRAMITACAO.value),
        )

    # --- correção de leitura propagada ao calendário -----------------------

    def test_situacao_efetiva_atrasada_propaga_para_condicao_do_calendario(self):
        base = Processo.objects.first()
        vencido = Processo.objects.create(
            item_pca=903, exercicio=base.exercicio,
            descricao_objeto="No prazo gravado, prazo vencido",
            tipo=base.tipo, categoria=base.categoria,
            unidade_organizacional=base.unidade_organizacional,
            estado=Estado.ATIVO.value, situacao=Situacao.NO_PRAZO.value,
            prazo_entrega=date(2020, 1, 1),
        )
        anotado = Processo.objects.para_listagem().get(pk=vencido.pk)
        self.assertEqual(anotado.situacao_efetiva, Situacao.ATRASADO.value)
        # A condição do calendário lê `situacao_efetiva` (corrigida), nunca
        # a coluna `situacao` crua gravada.
        self.assertEqual(
            _condicao_calendario(anotado), ("situacao", Situacao.ATRASADO.value)
        )

    # --- Teste 3 (behavior 17-09) — legenda com 5 entradas, ordem de
    # ORDEM_ROSCA ------------------------------------------------------------

    def test_legenda_do_calendario_tem_cinco_entradas_na_ordem_de_ordem_rosca(self):
        resposta = self.client.get(reverse("pca:calendario"))
        legenda = resposta.context["condicoes_calendario"]
        self.assertEqual(len(legenda), 5)
        self.assertEqual(
            [(item["eixo"], item["valor"]) for item in legenda],
            [
                (eixo, valor.value if hasattr(valor, "value") else valor)
                for eixo, valor, _rotulo in ORDEM_ROSCA
            ],
        )
        self.assertTrue(all(item["marcado"] for item in legenda))
        self.assertEqual(self._total_processos(resposta), 30)

    # --- isolar: uma requisição GET direta com `condicao_legenda=eixo:
    # valor` (`_resolver_condicao_legenda`) -------------------------------

    def test_clicar_em_uma_condicao_isola_mostra_so_aquela_condicao(self):
        resposta = self.client.get(
            reverse("pca:calendario"),
            {"condicao_legenda": f"situacao:{Situacao.NO_PRAZO.value}"},
        )
        condicoes = {
            (i["eixo"], i["valor"]): i["marcado"]
            for i in resposta.context["condicoes_calendario"]
        }
        self.assertTrue(condicoes[("situacao", Situacao.NO_PRAZO.value)])
        for chave, marcado in condicoes.items():
            if chave != ("situacao", Situacao.NO_PRAZO.value):
                self.assertFalse(marcado)
        total = self._total_processos(resposta)
        self.assertGreater(total, 0)
        self.assertLess(total, 30)
        for mes in resposta.context["meses"]:
            for processo in mes["processos"]:
                self.assertEqual(
                    _condicao_calendario(processo), ("situacao", Situacao.NO_PRAZO.value)
                )
        for processo in resposta.context["sem_mes"]["processos"]:
            self.assertEqual(
                _condicao_calendario(processo), ("situacao", Situacao.NO_PRAZO.value)
            )

    # --- Teste 5 (behavior 17-09) — acumular/remover/restaurar, via
    # requisições GET diretas com `condicao_legenda` multivalorado (o
    # `br-select multiple` do formulário envia um `condicao_legenda` por
    # checkbox marcado — mesmo formato de querystring de sempre) ------------

    def test_acumular_remover_e_restaurar_condicoes_da_legenda(self):
        resposta_isolada = self.client.get(
            reverse("pca:calendario"),
            {"condicao_legenda": f"situacao:{Situacao.NO_PRAZO.value}"},
        )
        self.assertLess(self._total_processos(resposta_isolada), 30)

        querystring_acumulada = (
            f"condicao_legenda=situacao%3A{Situacao.NO_PRAZO.value}"
            f"&condicao_legenda=situacao%3A{Situacao.CONCLUIDO.value}"
        )
        resposta_acumulada = self.client.get(
            reverse("pca:calendario") + "?" + querystring_acumulada
        )
        condicoes_acumuladas = {
            (i["eixo"], i["valor"]): i["marcado"]
            for i in resposta_acumulada.context["condicoes_calendario"]
        }
        self.assertTrue(condicoes_acumuladas[("situacao", Situacao.NO_PRAZO.value)])
        self.assertTrue(condicoes_acumuladas[("situacao", Situacao.CONCLUIDO.value)])
        for chave, marcado in condicoes_acumuladas.items():
            if chave not in {
                ("situacao", Situacao.NO_PRAZO.value),
                ("situacao", Situacao.CONCLUIDO.value),
            }:
                self.assertFalse(marcado)

        # Enviar só uma das duas — remoção parcial, não esvazia.
        resposta_uma_ativa = self.client.get(
            reverse("pca:calendario"),
            {"condicao_legenda": f"situacao:{Situacao.CONCLUIDO.value}"},
        )
        condicoes_uma = {
            (i["eixo"], i["valor"]): i["marcado"]
            for i in resposta_uma_ativa.context["condicoes_calendario"]
        }
        self.assertFalse(condicoes_uma[("situacao", Situacao.NO_PRAZO.value)])
        self.assertTrue(condicoes_uma[("situacao", Situacao.CONCLUIDO.value)])

        # Ausência do parâmetro restaura as 5 (comportamento padrão de
        # `_resolver_condicao_legenda`, nunca produz o conjunto vazio).
        resposta_restaurada = self.client.get(reverse("pca:calendario"))
        self.assertEqual(self._total_processos(resposta_restaurada), 30)
        self.assertNotIn(
            "condicao_legenda", resposta_restaurada.context["querystring_anual"]
        )
        self.assertTrue(
            all(i["marcado"] for i in resposta_restaurada.context["condicoes_calendario"])
        )

    # --- Teste 6 (behavior 17-09) — sentinela "nenhum" preservado ----------

    def test_condicao_legenda_nenhum_hand_crafted_continua_suportado(self):
        # `_resolver_condicao_legenda` continua aceitando o sentinela
        # hand-crafted mesmo esse estado não sendo mais alcançável por
        # clique na legenda (compatibilidade retroativa com o antigo
        # `_resolver_status_legenda`).
        resposta = self.client.get(
            reverse("pca:calendario"), {"condicao_legenda": "nenhum"}
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(self._total_processos(resposta), 0)
        self.assertTrue(
            all(not i["marcado"] for i in resposta.context["condicoes_calendario"])
        )

    # --- cobertura adicional preservada da era `status_legenda` -----------

    def test_querystring_calendario_carrega_condicao_legenda_em_todos_os_links(self):
        resposta = self.client.get(
            reverse("pca:calendario"),
            {"condicao_legenda": "situacao:no_prazo", "visao": "anual"},
        )
        marco = resposta.context["meses_grade"][2]
        self.assertIn("condicao_legenda=situacao%3Ano_prazo", marco["querystring_abrir"])
        self.assertIn("visao=mensal", marco["querystring_abrir"])
        self.assertIn("mes_calendario=3", marco["querystring_abrir"])
        self.assertIn(
            "condicao_legenda=situacao%3Ano_prazo", resposta.context["querystring_mensal"]
        )
        self.assertIn(
            "condicao_legenda=situacao%3Ano_prazo", resposta.context["querystring_anual"]
        )

    def test_querystring_condicao_legenda_preserva_visao_mes_e_filtros_globais(self):
        # Quick 260909-rwm — a legenda deixou de ser clicável (sem
        # `item["querystring"]` por condição); a cobertura equivalente
        # (visão/mês/filtro global sobrevivendo na navegação) passa a ser
        # `querystring_mensal`, já usada como o valor "mes_calendario"
        # oculto do formulário único — mesma leitura de
        # `test_querystring_calendario_carrega_condicao_legenda_em_todos_os_links`,
        # confirmando também que um filtro global (`uo`) sobrevive.
        from apps.catalogo.models import Unidade

        uo_real = Unidade.objects.first()
        resposta = self.client.get(
            reverse("pca:calendario"),
            {"visao": "mensal", "mes_calendario": "5", "uo": uo_real.id},
        )
        self.assertIn("visao=mensal", resposta.context["querystring_mensal"])
        self.assertIn("mes_calendario=5", resposta.context["querystring_mensal"])
        self.assertIn(f"uo={uo_real.id}", resposta.context["querystring_mensal"])
        # `uo` também chega como campo oculto do formulário único (o
        # `br-select` de situação não gerencia esse filtro diretamente).
        self.assertIn(("uo", str(uo_real.id)), resposta.context["filtros_ocultos_calendario"])

    def test_condicao_legenda_nao_gera_query_nova(self):
        # Sem ramificação HTMX: o orçamento de queries é o mesmo com ou
        # sem o cabeçalho `HX-Request`. O formulário único de
        # calendario.html referencia `exercicios_disponiveis` (context
        # processor global), que só dispara a consulta quando o template
        # efetivamente itera a lista — orçamento de 11 queries.
        with self.assertNumQueries(11):
            resposta = self.client.get(
                reverse("pca:calendario"), {"condicao_legenda": "situacao:no_prazo"}
            )
        self.assertEqual(resposta.status_code, 200)
        with self.assertNumQueries(11):
            resposta = self.client.get(
                reverse("pca:calendario"),
                {"condicao_legenda": "situacao:no_prazo"},
                HTTP_HX_REQUEST="true",
            )
        self.assertEqual(resposta.status_code, 200)

    # Quick 260909-rwm — `test_legenda_padrao_cinco_botoes_todos_com_
    # aria_pressed_true`, `test_isolar_condicao_reflete_aria_pressed_e_
    # esconde_as_demais_condicoes`, `test_fragmento_htmx_ja_traz_legenda_
    # atualizada_no_mesmo_swap` e `test_estado_da_legenda_sobrevive_como_
    # link_com_outro_filtro` REMOVIDOS: a legenda deixou de ser clicável
    # (informativa, `telas/calendario.md`) — não há mais `aria-pressed` nem
    # `item["querystring"]` por condição, e `HX-Request` não é mais um
    # caminho especial. A cobertura de isolar/acumular/restaurar/preservar
    # filtros continua em `test_clicar_em_uma_condicao_isola_mostra_so_
    # aquela_condicao`/`test_acumular_remover_e_restaurar_condicoes_da_
    # legenda`/`test_querystring_condicao_legenda_preserva_visao_mes_e_
    # filtros_globais` acima, via requisições GET diretas.

    # --- orçamento de queries -------------------------------------------------

    def test_orcamento_de_queries_independe_do_numero_de_cartoes(self):
        # 53 cartões (concluído) de um lado, 15 (em tramitação) do outro —
        # o número de queries não pode variar: qualquer divergência é N+1
        # nas propriedades derivadas ou no bloco de tags/opções. O caso de
        # zero cartões fica fora de propósito (mesmo motivo documentado em
        # TestFiltrosTabela: otimizações do ORM no caso trivial não são
        # detectores de N+1).
        with CaptureQueriesContext(connection) as muitos_cartoes:
            resposta_muitos = self.client.get(
                reverse("pca:calendario"), {"status": "concluido"}
            )
        with CaptureQueriesContext(connection) as poucos_cartoes:
            resposta_poucos = self.client.get(
                reverse("pca:calendario"), {"status": "em_tramitacao"}
            )
        self.assertEqual(resposta_muitos.status_code, 200)
        self.assertEqual(resposta_poucos.status_code, 200)
        self.assertEqual(
            len(muitos_cartoes.captured_queries),
            len(poucos_cartoes.captured_queries),
        )

    def test_assertnumqueries_pagina_completa(self):
        # Sem painel de filtros global e sem ramificação HTMX: o
        # orçamento é 11 (o formulário único referencia
        # `exercicios_disponiveis`, que só dispara quando iterado).
        with self.assertNumQueries(11):
            resposta = self.client.get(reverse("pca:calendario"))
        self.assertEqual(resposta.status_code, 200)

    def test_requisicao_normal_tambem_leva_cache_control(self):
        resposta = self.client.get(reverse("pca:calendario"))
        self.assertEqual(resposta["Cache-Control"], "private, no-store")


class TestTabelaLinkaParaDetalhe(TransactionTestCase):
    """A rota de detalhe não existia em 02-01 — o SUMMARY daquela plan
    registrou explicitamente que as células "Item"/"Descrição" da tabela
    ficariam sem link até `/processo/<item_pca>` existir (UI-SPEC
    §Screen Contracts 3: "O link para o detalhe fica nas células 'Item' e
    'Descrição'"). A coluna "Item" é a única com link (Objeto é texto
    puro), navegação normal para `pca:detalhe_processo`, sem
    `hx-get`/`#modal`."""

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

    def test_celula_item_navega_para_o_detalhe_sem_modal(self):
        resposta = self.client.get(
            reverse("pca:tabela"), {"situacao": "no_prazo"}
        )
        pagina = resposta.context["pagina"]
        conteudo = resposta.content.decode("utf-8")
        alvo = pagina.object_list[0]
        url_detalhe = reverse(
            "pca:detalhe_processo", args=[2026, alvo.item_pca]
        )
        # Colunas numéricas ganham `class="dsgov-numero"` — `<td
        # data-th="Item" class="dsgov-numero">` — o padrão precisa
        # aceitar atributos extras na abertura da tag, não só o
        # fechamento exato de `data-th="Item"`.
        celula_item = re.search(
            r'<td data-th="Item"[^>]*>.*?</td>', conteudo, re.S
        ).group(0)
        # O link da linha carrega a querystring canônica da tabela
        # (`querystring_tabela`), para que Anterior/Próximo no detalhe
        # percorram a mesma sequência filtrada.
        self.assertIn(f'href="{url_detalhe}?situacao=no_prazo"', celula_item)
        self.assertNotIn("hx-get=", celula_item)
        self.assertNotIn('hx-target="#modal"', celula_item)
        # A rota do modo=ver não existe mais como fragmento — nenhuma
        # célula da linha referencia `?modo=ver`.
        self.assertNotIn("modo=ver", conteudo)


class TestCaptionCalendarioVisivel(TransactionTestCase):
    """`caption{opacity:0;position:absolute;z-index:-1}` é regra global
    de `core.min.css` (skill dsgov, intocável). O mês/ano visível não
    depende de uma sobrescrita de CSS próprio: cada grade carrega um
    rótulo visível fora do `<caption>`, sempre `<h2>` (mensal: título do
    único card; anual: um por mini-calendário) — o `<caption>` continua
    existindo só para leitores de tela."""

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
            email="leitor-caption@pca.local", password="x-forte-123"
        )
        self.client.force_login(self.usuario)

    def test_rotulo_visivel_da_grade_mensal_tem_mes_e_ano(self):
        resposta = self.client.get(reverse("pca:calendario"), {"visao": "mensal"})
        conteudo = resposta.content.decode("utf-8")
        rotulo = re.search(r"<h2[^>]*>([^<]*)</h2>", conteudo)
        self.assertIsNotNone(rotulo)
        # Mês + ano do exercício, nunca só o nome do mês isolado (A12).
        self.assertRegex(rotulo.group(1), r"\b(19|20)\d{2}\b")
        # `<caption>` continua presente (acessibilidade), sem depender dele
        # para o rótulo visível.
        self.assertIsNotNone(re.search(r"<caption[^>]*>.*?</caption>", conteudo, re.S))

    def test_rotulo_visivel_da_grade_anual_tem_mes_e_ano_nos_12_meses(self):
        resposta = self.client.get(reverse("pca:calendario"), {"visao": "anual"})
        conteudo = resposta.content.decode("utf-8")
        # `<h2>` com ano — os 12 títulos de mini-calendário. Exclui o
        # `<h2>Sem mês previsto</h2>` (sem ano) do card de baixo, que não faz
        # parte da grade de 12 meses.
        rotulos_h2 = [
            r
            for r in re.findall(r"<h2[^>]*>.*?</h2>", conteudo, re.S)
            if re.search(r"\b(19|20)\d{2}\b", r)
        ]
        self.assertEqual(len(rotulos_h2), 12)
        captions = re.findall(r"<caption[^>]*>.*?</caption>", conteudo, re.S)
        self.assertEqual(len(captions), 12)


class TestFiltroDiaCalendario(TransactionTestCase):
    """Quick 260909-rwm — `dia_calendario` (`apps/pca/filtros.py`), o
    drill-down exato por dia usado pelo "+n" da visão mensal e pelo número
    do dia com evento na visão anual (`telas/calendario.md`). Mesmo padrão
    de `TestDrilldownResumoUO`: provado pela rota HTTP real, nunca só por
    inspeção de template."""

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
            email="dia-calendario@pca.local", password="x-forte-123"
        )
        self.client.force_login(self.usuario)

    def test_dia_calendario_filtra_so_o_dia_exato(self):
        alvo = Processo.objects.get(item_pca=26)
        _limpar_promessa_e_definir_prazo_entrega(alvo, date(2026, 3, 10))
        outro = Processo.objects.exclude(pk=alvo.pk).first()
        _limpar_promessa_e_definir_prazo_entrega(outro, date(2026, 3, 11))

        resposta = self.client.get(
            reverse("pca:tabela"), {"dia_calendario": "2026-03-10"}
        )
        itens = {p.item_pca for p in resposta.context["pagina"].object_list}
        self.assertIn(alvo.item_pca, itens)
        self.assertNotIn(outro.item_pca, itens)

    def test_celula_url_do_contexto_do_calendario_reproduz_a_mesma_contagem(self):
        alvo = Processo.objects.get(item_pca=26)
        _limpar_promessa_e_definir_prazo_entrega(alvo, date(2026, 3, 10))

        resposta = self.client.get(
            reverse("pca:calendario"), {"visao": "mensal", "mes_calendario": "3"}
        )
        celula = next(
            celula
            for semana in resposta.context["semanas_calendario"]
            for celula in semana
            if celula["do_mes"] and celula["data"] == date(2026, 3, 10)
        )
        self.assertIn("dia_calendario=2026-03-10", celula["url"])
        resposta_tabela = self.client.get(celula["url"])
        self.assertEqual(
            resposta_tabela.context["pagina"].paginator.count, celula["total"]
        )
