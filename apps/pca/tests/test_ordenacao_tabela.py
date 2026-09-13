from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TransactionTestCase
from django.urls import reverse

from apps.pca.colunas import COLUNAS, COLUNAS_PADRAO
from apps.pca.filtros import COLUNAS_ORDENACAO, direcao_valida
from apps.pca.models import Processo
from apps.pca.views import _cabecalhos_ordenaveis

ARQUIVO_REAL = "apps/pca/fixtures/modelo-controle-exemplo.xlsx"


class TestOrdenacaoBidirecional(TransactionTestCase):
    """Ordenação por clique no cabeçalho alternando crescente ↔
    decrescente, com seta e aria-sort. `?ordenar=` é validado contra o
    mapa fechado, e `order_by(campo)` respeita a direção.

    Mesmo padrão de setUp() de TestFiltrosTabela: import real a cada teste
    (TransactionTestCase não chama setUpTestData e dá flush entre testes).
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

    def _todas_paginas(self, **params):
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

    # --- validação da direção (lista fechada) --------------------------

    def test_direcao_valida_aceita_so_asc_e_desc(self):
        self.assertEqual(direcao_valida("asc"), "asc")
        self.assertEqual(direcao_valida("desc"), "desc")

    def test_direcao_invalida_cai_no_padrao_ascendente(self):
        for entrada in ("-item_pca", "DESC", "'; DROP TABLE", "", None):
            with self.subTest(entrada=entrada):
                self.assertEqual(direcao_valida(entrada), "asc")

    def test_direcao_invalida_na_url_nao_quebra_a_pagina(self):
        resposta = self.client.get(
            reverse("pca:tabela"), {"ordenar": "valor_estimado", "dir": "-valor"}
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.context["direcao_ordenacao"], "asc")

    # --- os dois sentidos ordenam de verdade -----------------------------

    def test_valor_estimado_ordena_nos_dois_sentidos(self):
        crescente = [
            p.valor_estimado
            for p in self._todas_paginas(ordenar="valor_estimado", dir="asc")
            if p.valor_estimado is not None
        ]
        decrescente = [
            p.valor_estimado
            for p in self._todas_paginas(ordenar="valor_estimado", dir="desc")
            if p.valor_estimado is not None
        ]
        self.assertEqual(crescente, sorted(crescente))
        self.assertEqual(decrescente, sorted(decrescente, reverse=True))
        self.assertEqual(crescente, list(reversed(decrescente)))

    def test_sem_dir_o_padrao_continua_ascendente(self):
        sem_dir = [p.item_pca for p in self._todas_paginas(ordenar="valor_estimado")]
        com_asc = [
            p.item_pca
            for p in self._todas_paginas(ordenar="valor_estimado", dir="asc")
        ]
        self.assertEqual(sem_dir, com_asc)

    # --- o item sem mês fica por último nos dois sentidos --------------

    def test_mes_previsto_mantem_nulo_por_ultimo_no_ascendente(self):
        meses = [p.mes_previsto for p in self._todas_paginas(ordenar="mes_previsto")]
        self.assertIsNone(meses[-1])
        self.assertTrue(all(m is not None for m in meses[:-1]))

    def test_mes_previsto_mantem_nulo_por_ultimo_no_descendente(self):
        """O ponto do teste: `nulls_last` precisa ser repetido no desc. Sem
        isso o PostgreSQL põe NULL na frente e o item 137 vira o primeiro."""
        meses = [
            p.mes_previsto
            for p in self._todas_paginas(ordenar="mes_previsto", dir="desc")
        ]
        self.assertIsNone(meses[-1])
        preenchidos = [m for m in meses if m is not None]
        self.assertEqual(preenchidos, sorted(preenchidos, reverse=True))

    # --- paginação estável (desempate por item_pca) ----------------------

    def test_paginacao_nao_repete_nem_perde_processo_em_coluna_com_empates(self):
        """`status` tem muitos valores repetidos. Sem desempate explícito a
        ordem das linhas empatadas é indefinida no PostgreSQL e o mesmo
        processo pode aparecer em duas páginas."""
        itens = [p.item_pca for p in self._todas_paginas(ordenar="status")]
        self.assertEqual(len(itens), len(set(itens)))
        self.assertEqual(len(itens), 30)

    # --- contrato visível do cabeçalho -----------------------------------
    # Cabeçalho ordenável via `{% ordenar_por_tabela %}`
    # (apps/pca/templatetags/pca_listagem.py): ícone Font Awesome
    # (`fa-sort-up`/`fa-sort-down`); `href`/`hx-get` montados com
    # `QueryDict.urlencode()` (`&` cru, nunca `&amp;`); e `aria-sort`
    # declarado em toda coluna ordenável (`aria-sort="none"` nas demais é
    # o contrato correto de acessibilidade).

    def test_cabecalho_ativo_expoe_aria_sort_e_icone_conforme_a_ui_spec(self):
        resposta = self.client.get(
            reverse("pca:tabela"), {"ordenar": "valor_estimado", "dir": "asc"}
        )
        conteudo = resposta.content.decode("utf-8")
        self.assertIn('aria-sort="ascending"', conteudo)
        self.assertIn("fa-sort-up", conteudo)

        resposta = self.client.get(
            reverse("pca:tabela"), {"ordenar": "valor_estimado", "dir": "desc"}
        )
        conteudo = resposta.content.decode("utf-8")
        self.assertIn('aria-sort="descending"', conteudo)
        self.assertIn("fa-sort-down", conteudo)

    def test_link_da_coluna_ativa_pede_o_sentido_oposto(self):
        resposta = self.client.get(
            reverse("pca:tabela"), {"ordenar": "valor_estimado", "dir": "asc"}
        )
        conteudo = resposta.content.decode("utf-8")
        self.assertIn("ordenar=valor_estimado&dir=desc", conteudo)

    def test_link_de_coluna_nova_comeca_ascendente(self):
        # `mes_previsto` saiu do padrão; `prazo_efetivo` é uma das 5
        # colunas padrão, presente na carga inicial sem `?colunas=`.
        resposta = self.client.get(
            reverse("pca:tabela"), {"ordenar": "valor_estimado", "dir": "desc"}
        )
        conteudo = resposta.content.decode("utf-8")
        self.assertIn("ordenar=prazo_efetivo&dir=asc", conteudo)

    def test_apenas_uma_coluna_declara_aria_sort_ativo(self):
        """As 5 colunas ordenáveis da carga inicial declaram `aria-sort`
        sempre (WAI-ARIA recomenda o atributo em toda coluna ordenável,
        com "none" fora da ativa); só a coluna ativa pode ter
        `aria-sort="ascending"`/`"descending"`."""
        resposta = self.client.get(
            reverse("pca:tabela"), {"ordenar": "valor_estimado", "dir": "asc"}
        )
        conteudo = resposta.content.decode("utf-8")
        self.assertEqual(conteudo.count("aria-sort=\"ascending\""), 1)
        self.assertEqual(conteudo.count("aria-sort=\"descending\""), 0)
        self.assertEqual(conteudo.count("aria-sort="), 5)

    # --- a direção sobrevive à paginação ---------------------------------

    def test_links_de_paginacao_carregam_a_direcao(self):
        """`dsgov/_paginacao.html` (skill) gera `<a href>` reais por página
        via `{% url_com %}`, que copia `request.GET` inteiro — a direção
        (`ordenar`/`dir`) sobrevive automaticamente em cada link, sem
        nenhum marcador de URL-modelo. `url_com` (diferente de
        `ordenar_por_tabela`, que devolve a `<a>` inteira via `mark_safe`)
        devolve string simples — o autoescape do Django escapa `&` para
        `&amp;` dentro do `href="..."`, contrato correto de atributo HTML."""
        resposta = self.client.get(
            reverse("pca:tabela"), {"ordenar": "valor_estimado", "dir": "desc"}
        )
        conteudo = resposta.content.decode("utf-8")
        self.assertIn("ordenar=valor_estimado&amp;dir=desc", conteudo)

    def test_paginacao_e_br_pagination_com_current_e_total_corretos(self):
        """`dsgov/_paginacao.html` (skill) é `<nav class="br-pagination"
        data-total=... data-current=... data-per-page=...>` — CSS-only,
        sem o Custom Element `<br-pagination>` nem o marcador
        `data-pca-url-pagina="...__PAGINA__"` do contrato antigo."""
        resposta = self.client.get(reverse("pca:tabela"), {"pagina": 2})
        conteudo = resposta.content.decode("utf-8")
        pagina = resposta.context["pagina"]
        self.assertIn('class="br-pagination"', conteudo)
        self.assertIn(f'data-current="{pagina.number}"', conteudo)
        self.assertIn(f'data-total="{pagina.paginator.count}"', conteudo)
        self.assertNotIn("<br-pagination", conteudo)

    # --- quick 260817-oew: FK/booleano/nulls_last nas colunas novas -------
    # (260817-qon reverteu a exceção de UO; ela agora entra no grupo FK-sort)

    def test_grau_prioridade_ordena_pelo_nome_nos_dois_sentidos_com_nulo_por_ultimo(self):
        crescente = self._todas_paginas(ordenar="grau_prioridade", dir="asc")
        decrescente = self._todas_paginas(ordenar="grau_prioridade", dir="desc")

        nomes_asc = [
            p.grau_prioridade.nome if p.grau_prioridade_id else None for p in crescente
        ]
        nomes_desc = [
            p.grau_prioridade.nome if p.grau_prioridade_id else None for p in decrescente
        ]

        self.assertIsNone(nomes_asc[-1])
        self.assertIsNone(nomes_desc[-1])
        preenchidos_asc = [n for n in nomes_asc if n is not None]
        preenchidos_desc = [n for n in nomes_desc if n is not None]
        self.assertEqual(preenchidos_asc, sorted(preenchidos_asc))
        self.assertEqual(preenchidos_desc, sorted(preenchidos_desc, reverse=True))

    def test_classificacao_ordena_pelo_nome_nos_dois_sentidos_com_nulo_por_ultimo(self):
        crescente = self._todas_paginas(ordenar="classificacao", dir="asc")
        decrescente = self._todas_paginas(ordenar="classificacao", dir="desc")

        nomes_asc = [
            p.classificacao.nome if p.classificacao_id else None for p in crescente
        ]
        nomes_desc = [
            p.classificacao.nome if p.classificacao_id else None for p in decrescente
        ]

        self.assertIsNone(nomes_asc[-1])
        self.assertIsNone(nomes_desc[-1])
        preenchidos_asc = [n for n in nomes_asc if n is not None]
        preenchidos_desc = [n for n in nomes_desc if n is not None]
        self.assertEqual(preenchidos_asc, sorted(preenchidos_asc))
        self.assertEqual(preenchidos_desc, sorted(preenchidos_desc, reverse=True))

    def test_atrasado_ordena_booleano_nos_dois_sentidos_sem_nulos(self):
        crescente = [p.atrasado for p in self._todas_paginas(ordenar="atrasado", dir="asc")]
        decrescente = [
            p.atrasado for p in self._todas_paginas(ordenar="atrasado", dir="desc")
        ]
        self.assertEqual(crescente, sorted(crescente, key=lambda v: (v is None, v)))
        self.assertEqual(
            decrescente, sorted(decrescente, key=lambda v: (v is None, v), reverse=True)
        )
        self.assertNotIn(None, crescente)
        self.assertNotIn(None, decrescente)

    def test_data_envio_gelic_mantem_nulo_por_ultimo_nos_dois_sentidos(self):
        crescente = [
            p.data_envio_gelic for p in self._todas_paginas(ordenar="data_envio_gelic")
        ]
        decrescente = [
            p.data_envio_gelic
            for p in self._todas_paginas(ordenar="data_envio_gelic", dir="desc")
        ]
        self.assertIsNone(crescente[-1])
        self.assertIsNone(decrescente[-1])
        preenchidos_asc = [d for d in crescente if d is not None]
        preenchidos_desc = [d for d in decrescente if d is not None]
        self.assertEqual(preenchidos_asc, sorted(preenchidos_asc))
        self.assertEqual(preenchidos_desc, sorted(preenchidos_desc, reverse=True))

    def test_unidade_organizacional_ordena_pelo_nome_nos_dois_sentidos(self):
        """Quick 260817-qon reverteu a exceção da 260817-oew: UO ordena pelo
        nome da unidade nos dois sentidos, igual às demais colunas FK. FK
        obrigatória (sem null=True/blank=True em Processo.unidade_organizacional),
        então não há caso de nulo a tratar aqui."""
        crescente = self._todas_paginas(ordenar="unidade_organizacional", dir="asc")
        decrescente = self._todas_paginas(ordenar="unidade_organizacional", dir="desc")

        nomes_asc = [p.unidade_organizacional.nome for p in crescente]
        nomes_desc = [p.unidade_organizacional.nome for p in decrescente]

        self.assertEqual(nomes_asc, sorted(nomes_asc))
        self.assertEqual(nomes_desc, sorted(nomes_desc, reverse=True))

    # --- cabeçalho "situacao" -------------------------------------------

    def test_situacao_ordena_por_situacao_efetiva_nos_dois_sentidos(self):
        """`?ordenar=situacao` precisa traduzir para `situacao_efetiva`
        (CAMPOS_ORDENACAO_FK) — a mesma correção-na-leitura que a
        exibição usa, nunca a coluna crua `situacao`."""
        crescente = [
            p.situacao_efetiva
            for p in self._todas_paginas(ordenar="situacao", dir="asc")
        ]
        decrescente = [
            p.situacao_efetiva
            for p in self._todas_paginas(ordenar="situacao", dir="desc")
        ]
        self.assertEqual(crescente, sorted(crescente))
        self.assertEqual(decrescente, sorted(decrescente, reverse=True))
        self.assertEqual(crescente, list(reversed(decrescente)))

    # --- FKs de Execução contratual e anotação prazo_inicial -----------

    def test_modalidade_ordena_pelo_nome_nos_dois_sentidos_com_nulo_por_ultimo(self):
        crescente = self._todas_paginas(ordenar="modalidade", dir="asc")
        decrescente = self._todas_paginas(ordenar="modalidade", dir="desc")

        nomes_asc = [
            p.modalidade.nome if p.modalidade_id else None for p in crescente
        ]
        nomes_desc = [
            p.modalidade.nome if p.modalidade_id else None for p in decrescente
        ]

        self.assertIsNone(nomes_asc[-1])
        self.assertIsNone(nomes_desc[-1])
        preenchidos_asc = [n for n in nomes_asc if n is not None]
        preenchidos_desc = [n for n in nomes_desc if n is not None]
        self.assertTrue(preenchidos_asc)
        self.assertEqual(preenchidos_asc, sorted(preenchidos_asc))
        self.assertEqual(preenchidos_desc, sorted(preenchidos_desc, reverse=True))

    def test_instrumento_contratual_ordena_pelo_nome_nos_dois_sentidos_com_nulo_por_ultimo(self):
        crescente = self._todas_paginas(ordenar="instrumento_contratual", dir="asc")
        decrescente = self._todas_paginas(ordenar="instrumento_contratual", dir="desc")

        nomes_asc = [
            p.instrumento_contratual.nome if p.instrumento_contratual_id else None
            for p in crescente
        ]
        nomes_desc = [
            p.instrumento_contratual.nome if p.instrumento_contratual_id else None
            for p in decrescente
        ]

        self.assertIsNone(nomes_asc[-1])
        self.assertIsNone(nomes_desc[-1])
        preenchidos_asc = [n for n in nomes_asc if n is not None]
        preenchidos_desc = [n for n in nomes_desc if n is not None]
        self.assertTrue(preenchidos_asc)
        self.assertEqual(preenchidos_asc, sorted(preenchidos_asc))
        self.assertEqual(preenchidos_desc, sorted(preenchidos_desc, reverse=True))

    def test_prazo_inicial_ordena_pela_anotacao_com_nulo_por_ultimo(self):
        # `?ordenar=prazo_inicial` usa a mesma anotação
        # COALESCE(prazo_entrega, primeira promessa) de `para_listagem()`,
        # nunca o campo cru `prazo_entrega`.
        esperado = {
            p.item_pca: p.prazo_inicial
            for p in Processo.objects.para_listagem()
        }
        crescente = [
            esperado[p.item_pca]
            for p in self._todas_paginas(ordenar="prazo_inicial", dir="asc")
        ]
        decrescente = [
            esperado[p.item_pca]
            for p in self._todas_paginas(ordenar="prazo_inicial", dir="desc")
        ]
        self.assertIsNone(crescente[-1])
        self.assertIsNone(decrescente[-1])
        preenchidos_asc = [d for d in crescente if d is not None]
        preenchidos_desc = [d for d in decrescente if d is not None]
        self.assertTrue(preenchidos_asc)
        self.assertEqual(preenchidos_asc, sorted(preenchidos_asc))
        self.assertEqual(preenchidos_desc, sorted(preenchidos_desc, reverse=True))

    def test_toda_coluna_ordenavel_do_registro_responde_200_com_link_coerente(self):
        # Percorre toda chave do registro (`apps.pca.colunas.COLUNAS`)
        # que também está em `COLUNAS_ORDENACAO` (todas, exceto a
        # composta `numeros_sei`), confirma 200 e um link de ordenação
        # com o sentido oposto no cabeçalho — nunca um `<span>` mudo.
        chaves = [
            coluna.chave for coluna in COLUNAS if coluna.chave in COLUNAS_ORDENACAO
        ]
        self.assertGreater(len(chaves), 30)  # guarda contra loop vazio
        for chave in chaves:
            with self.subTest(chave=chave):
                resposta = self.client.get(
                    reverse("pca:tabela"),
                    {"ordenar": chave, "dir": "asc", "colunas": list(COLUNAS_PADRAO) + [chave]},
                )
                self.assertEqual(resposta.status_code, 200)
                conteudo = resposta.content.decode("utf-8")
                self.assertIn(f"ordenar={chave}&dir=desc", conteudo)

    def test_ordenacao_e_direcao_convivem_com_filtro(self):
        resposta = self.client.get(
            reverse("pca:tabela"),
            {"status": "concluido", "ordenar": "valor_estimado", "dir": "desc"},
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.context["direcao_ordenacao"], "desc")
        valores = [
            p.valor_estimado
            for p in resposta.context["pagina"].object_list
            if p.valor_estimado is not None
        ]
        self.assertEqual(valores, sorted(valores, reverse=True))


class TestColunasPadraoDaTabela(SimpleTestCase):
    """A fonte única de colunas vive em `apps.pca.colunas` (registro
    `COLUNAS` + padrão `COLUNAS_PADRAO`), plugada ao contrato de
    `_cabecalhos_ordenaveis(campo, direcao, colunas_resolvidas)`, que
    recebe a lista de chaves já resolvida em vez de iterar um registro
    fixo inteiro. Sem banco: mais barata que as `TransactionTestCase` do
    resto do arquivo."""

    def test_padrao_tem_as_cinco_colunas_da_fase_28(self):
        # Padrão: `unidade_organizacional` sai, `prazo_efetivo` entra.
        self.assertEqual(
            COLUNAS_PADRAO,
            (
                "item_pca",
                "descricao_objeto",
                "valor_estimado",
                "prazo_efetivo",
                "situacao",
            ),
        )

    def test_cabecalhos_ordenaveis_resolve_rotulo_e_tipo_na_ordem_recebida(self):
        cabecalhos = _cabecalhos_ordenaveis("item_pca", "asc", list(COLUNAS_PADRAO))
        self.assertEqual([c["chave"] for c in cabecalhos], list(COLUNAS_PADRAO))
        for cabecalho in cabecalhos:
            self.assertIn("rotulo", cabecalho)
            self.assertIn("tipo", cabecalho)

    def test_colunas_ausentes_do_registro_sao_ignoradas_em_silencio(self):
        cabecalhos = _cabecalhos_ordenaveis(
            "item_pca", "asc", ["item_pca", "chave_inventada", "situacao"]
        )
        self.assertEqual([c["chave"] for c in cabecalhos], ["item_pca", "situacao"])

    def test_apenas_numeros_sei_fica_fora_de_colunas_ordenacao(self):
        """`justificativa`/`categoria`/`situacao_sei` estão em
        `filtros.COLUNAS_ORDENACAO` (campos escalares simples);
        `prazo_vigente` saiu do registro por completo. Só `numeros_sei`
        (concatenação de várias linhas de `ProcessoSEI`, sem coluna
        escalar única no banco) continua fora — todas as outras chaves
        do registro são ordenáveis."""
        cabecalhos = _cabecalhos_ordenaveis(
            "item_pca", "asc", [coluna.chave for coluna in COLUNAS]
        )
        nao_ordenaveis = {c["chave"] for c in cabecalhos if c["ordenavel"] is False}
        self.assertEqual(nao_ordenaveis, {"numeros_sei"})

    def test_cabecalho_situacao_e_ordenavel(self):
        """O cabeçalho de chave "situacao" precisa marcar
        `ordenavel=True` assim que entra em `filtros.COLUNAS_ORDENACAO`."""
        cabecalhos = _cabecalhos_ordenaveis("item_pca", "asc", list(COLUNAS_PADRAO))
        situacao = next(c for c in cabecalhos if c["chave"] == "situacao")
        self.assertTrue(situacao["ordenavel"])
