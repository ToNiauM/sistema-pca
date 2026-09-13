"""Registro único de colunas e resolvedor com precedência URL > sessão
> padrão.

Testes puros do resolvedor (`apps.pca.colunas`), sem banco — um objeto de
requisição falso (`_RequestFalso`) é suficiente, já que
`colunas_selecionadas` só usa `request.GET`/`request.session`. Também
cobre os cenários de comportamento fim-a-fim (sessão real via
`django.test.Client`, HTMX, seletor em acordeão).

`secao`/`SECOES_COLUNAS`/`colunas_por_secao` (seletor agrupado) e o
saneamento das três chaves extintas
(`prazo_vigente`/`prazo_entrega`/`data_prevista_conclusao`)."""

from django.contrib.auth import get_user_model
from django.http import QueryDict
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from apps.catalogo.models import Categoria, Exercicio, Tipo, Unidade
from apps.pca.colunas import (
    COLUNAS,
    COLUNAS_OBRIGATORIAS,
    COLUNAS_PADRAO,
    COLUNAS_POR_CHAVE,
    SECOES_COLUNAS,
    canonizar,
    colunas_por_secao,
    colunas_selecionadas,
)
from apps.pca.models import Processo


class _RequestFalso:
    """Duplo de teste mínimo: só o que `colunas_selecionadas` acessa
    (`request.GET`/`request.session`)."""

    def __init__(self, query="", sessao=None):
        self.GET = QueryDict(query)
        self.session = sessao if sessao is not None else {}


class _SessaoEspia(dict):
    """28-REVIEW (WR-03) — `dict` que conta toda chamada de `__setitem__`,
    para provar que `colunas_selecionadas` não regrava a sessão quando o
    resultado já é igual ao valor salvo (`request.session` real do Django
    sempre resalva a linha no banco a cada requisição —
    `SESSION_SAVE_EVERY_REQUEST = True`, config/settings/base.py —, então
    o efeito só é observável neste nível de unidade, não pela linha
    persistida)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.escritas = 0

    def __setitem__(self, chave, valor):
        self.escritas += 1
        super().__setitem__(chave, valor)


class TestRegistroDeColunas(SimpleTestCase):
    def test_padrao_tem_as_cinco_colunas_da_fase_28(self):
        # Padrão: `unidade_organizacional` sai do núcleo, `prazo_efetivo`
        # entra.
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

    def test_obrigatorias_sao_item_e_objeto(self):
        self.assertEqual(COLUNAS_OBRIGATORIAS, ("item_pca", "descricao_objeto"))

    def test_registro_nao_duplica_chave(self):
        chaves = [coluna.chave for coluna in COLUNAS]
        self.assertEqual(len(chaves), len(set(chaves)))

    def test_todas_as_chaves_do_padrao_e_das_obrigatorias_existem_no_registro(self):
        for chave in (*COLUNAS_PADRAO, *COLUNAS_OBRIGATORIAS):
            with self.subTest(chave=chave):
                self.assertIn(chave, COLUNAS_POR_CHAVE)

    def test_coluna_suporta_acesso_estilo_dict_para_o_filtro_exibir(self):
        # core.templatetags.dsgov.exibir acessa `coluna["campo"]`/
        # `coluna.get("tipo")` — mesmo contrato de `pendencias.colunas`
        # (core/templates/core/inicio.html).
        coluna = COLUNAS_POR_CHAVE["valor_estimado"]
        self.assertEqual(coluna["campo"], "valor_estimado")
        self.assertEqual(coluna.get("tipo"), "moeda")
        self.assertIsNone(coluna.get("inexistente"))


class TestSecoesDoRegistro(SimpleTestCase):
    """`secao` em cada `Coluna`, `SECOES_COLUNAS` (as quatro legendas,
    nesta ordem) e `colunas_por_secao()` (agrupamento estável, sem
    perder nem duplicar chave)."""

    def test_quatro_secoes_na_ordem_canonica(self):
        self.assertEqual(
            SECOES_COLUNAS,
            ("Planejamento", "Processo", "Execução contratual", "Publicação"),
        )

    def test_colunas_por_secao_cobre_o_registro_inteiro_sem_duplicar(self):
        grupos = colunas_por_secao()
        self.assertEqual(tuple(nome for nome, _ in grupos), SECOES_COLUNAS)
        chaves_agrupadas = [
            coluna.chave for _, colunas in grupos for coluna in colunas
        ]
        self.assertEqual(len(chaves_agrupadas), len(COLUNAS))
        self.assertEqual(set(chaves_agrupadas), set(COLUNAS_POR_CHAVE))

    def test_item_e_objeto_sao_as_duas_primeiras_caixas_de_planejamento(self):
        grupos = dict(colunas_por_secao())
        chaves_planejamento = [coluna.chave for coluna in grupos["Planejamento"]]
        self.assertEqual(chaves_planejamento[:2], ["item_pca", "descricao_objeto"])

    def test_colunas_de_execucao_contratual_e_publicacao_completas(self):
        # Todos os campos dessas duas seções entram como colunas opcionais.
        grupos = dict(colunas_por_secao())
        chaves_execucao = {coluna.chave for coluna in grupos["Execução contratual"]}
        chaves_publicacao = {coluna.chave for coluna in grupos["Publicação"]}
        self.assertEqual(
            chaves_execucao,
            {
                "modalidade",
                "numero_contratacao",
                "numero_arp",
                "instrumento_contratual",
                "numero_instrumento_contratual",
                "fornecedor_cnpj",
                "fornecedor_razao_social",
                "valor_contratado",
                "data_assinatura_contrato",
                "vigencia_inicio",
                "vigencia_fim",
            },
        )
        self.assertEqual(
            chaves_publicacao,
            {
                "data_lancamento_spw",
                "data_lancamento_wordpress",
                "data_lancamento_dados_abertos",
            },
        )

    def test_prazo_vigente_prazo_entrega_e_data_prevista_conclusao_saem_do_registro(self):
        # As três chaves fechadas não existem mais no registro;
        # `prazo_inicial` entra no lugar de `prazo_entrega`.
        for chave in ("prazo_vigente", "prazo_entrega", "data_prevista_conclusao"):
            with self.subTest(chave=chave):
                self.assertNotIn(chave, COLUNAS_POR_CHAVE)
        self.assertIn("prazo_inicial", COLUNAS_POR_CHAVE)
        self.assertEqual(COLUNAS_POR_CHAVE["prazo_inicial"].rotulo, "Prazo inicial")
        self.assertEqual(COLUNAS_POR_CHAVE["prazo_efetivo"].rotulo, "Prazo atual")


class TestResolvedorDeColunas(SimpleTestCase):
    """Precedência URL explícita válida > sessão > padrão; duplicatas
    removidas; chaves desconhecidas rejeitadas; seleção inválida nunca
    produz tabela sem colunas."""

    def test_sem_get_e_sem_sessao_devolve_o_padrao(self):
        request = _RequestFalso()
        self.assertEqual(colunas_selecionadas(request), list(COLUNAS_PADRAO))

    def test_duplicata_removida_chave_invalida_descartada_ordem_preservada(self):
        request = _RequestFalso(
            "colunas=item_pca&colunas=item_pca&colunas=lixo&colunas=descricao_objeto"
        )
        self.assertEqual(
            colunas_selecionadas(request), ["item_pca", "descricao_objeto"]
        )

    def test_get_com_apenas_chaves_invalidas_cai_no_padrao(self):
        request = _RequestFalso("colunas=lixo")
        self.assertEqual(colunas_selecionadas(request), list(COLUNAS_PADRAO))

    def test_get_grava_a_selecao_na_sessao(self):
        sessao = {}
        request = _RequestFalso(
            "colunas=item_pca&colunas=descricao_objeto&colunas=situacao",
            sessao=sessao,
        )
        resultado = colunas_selecionadas(request)
        self.assertEqual(resultado, ["item_pca", "descricao_objeto", "situacao"])
        self.assertEqual(sessao["pca_colunas_tabela"], resultado)

    def test_sem_get_le_a_sessao(self):
        sessao = {
            "pca_colunas_tabela": ["item_pca", "descricao_objeto", "valor_estimado"]
        }
        request = _RequestFalso(sessao=sessao)
        self.assertEqual(
            colunas_selecionadas(request),
            ["item_pca", "descricao_objeto", "valor_estimado"],
        )

    def test_get_explicito_tem_precedencia_sobre_a_sessao(self):
        sessao = {"pca_colunas_tabela": ["item_pca", "descricao_objeto", "estado"]}
        request = _RequestFalso(
            "colunas=item_pca&colunas=descricao_objeto&colunas=tipo", sessao=sessao
        )
        self.assertEqual(
            colunas_selecionadas(request), ["item_pca", "descricao_objeto", "tipo"]
        )
        self.assertEqual(
            sessao["pca_colunas_tabela"], ["item_pca", "descricao_objeto", "tipo"]
        )

    def test_obrigatorias_ausentes_sao_reinjetadas(self):
        request = _RequestFalso("colunas=valor_estimado")
        resultado = colunas_selecionadas(request)
        self.assertIn("item_pca", resultado)
        self.assertIn("descricao_objeto", resultado)
        self.assertIn("valor_estimado", resultado)

    def test_sessao_com_apenas_chaves_invalidas_cai_no_padrao(self):
        request = _RequestFalso(sessao={"pca_colunas_tabela": ["lixo", "outra_lixo"]})
        self.assertEqual(colunas_selecionadas(request), list(COLUNAS_PADRAO))

    def test_sessao_antiga_com_chaves_extintas_e_saneada(self):
        # `prazo_vigente`/`prazo_entrega`/`data_prevista_conclusao`
        # saíram do registro; uma preferência de sessão gravada antes
        # dessa mudança precisa cair no padrão, nunca quebrar
        # `_normalizar`.
        request = _RequestFalso(
            sessao={
                "pca_colunas_tabela": [
                    "item_pca",
                    "prazo_vigente",
                    "prazo_entrega",
                    "data_prevista_conclusao",
                ]
            }
        )
        resultado = colunas_selecionadas(request)
        self.assertNotIn("prazo_vigente", resultado)
        self.assertNotIn("prazo_entrega", resultado)
        self.assertNotIn("data_prevista_conclusao", resultado)
        self.assertIn("item_pca", resultado)
        self.assertIn("descricao_objeto", resultado)

    def test_resultado_nunca_e_lista_vazia(self):
        for request in (
            _RequestFalso(),
            _RequestFalso("colunas=lixo"),
            _RequestFalso(sessao={"pca_colunas_tabela": []}),
        ):
            with self.subTest(request=request):
                self.assertTrue(len(colunas_selecionadas(request)) > 0)

    def test_get_repetindo_a_selecao_ja_salva_nao_regrava_a_sessao(self):
        # 28-REVIEW (WR-03) — navegação HTMX da tela Processos (filtro/
        # ordenação/paginação) reenvia `colunas=` a cada GET via
        # `hx-include="#form-colunas"` mesmo quando o usuário não tocou no
        # seletor "Colunas": se a seleção já é a mesma da sessão, o GET
        # não deve ter o efeito colateral de regravar (método deveria ser
        # seguro/idempotente).
        sessao = _SessaoEspia(
            {"pca_colunas_tabela": ["item_pca", "descricao_objeto", "estado"]}
        )
        request = _RequestFalso(
            "colunas=item_pca&colunas=descricao_objeto&colunas=estado",
            sessao=sessao,
        )
        resultado = colunas_selecionadas(request)
        self.assertEqual(resultado, ["item_pca", "descricao_objeto", "estado"])
        self.assertEqual(sessao.escritas, 0)

    def test_get_com_selecao_diferente_da_sessao_regrava(self):
        # Mesmo cenário acima, mas a seleção do GET genuinamente difere da
        # sessão — a gravação continua acontecendo (URL explícita
        # prevalece), só o caso "sem mudança nenhuma" é que não regrava.
        sessao = _SessaoEspia(
            {"pca_colunas_tabela": ["item_pca", "descricao_objeto", "estado"]}
        )
        request = _RequestFalso(
            "colunas=item_pca&colunas=descricao_objeto&colunas=tipo",
            sessao=sessao,
        )
        resultado = colunas_selecionadas(request)
        self.assertEqual(resultado, ["item_pca", "descricao_objeto", "tipo"])
        self.assertEqual(sessao.escritas, 1)
        self.assertEqual(sessao["pca_colunas_tabela"], resultado)

    def test_get_sem_sessao_previa_grava_normalmente(self):
        # Primeira seleção explícita (sessão ainda vazia) continua
        # gravando normalmente — a guarda de WR-03 só evita a regravação
        # REDUNDANTE, nunca a gravação inicial.
        sessao = _SessaoEspia()
        request = _RequestFalso(
            "colunas=item_pca&colunas=descricao_objeto&colunas=situacao",
            sessao=sessao,
        )
        resultado = colunas_selecionadas(request)
        self.assertEqual(sessao.escritas, 1)
        self.assertEqual(sessao["pca_colunas_tabela"], resultado)

    # `canonizar()` reordena sempre núcleo primeiro (ordem de
    # `COLUNAS_PADRAO`), depois opcionais na ordem do registro `COLUNAS`,
    # independentemente da ordem de chegada do `?colunas=`/sessão.

    def test_get_com_nucleo_e_opcionais_embaralhados_devolve_ordem_canonica_e_grava(
        self,
    ):
        sessao = _SessaoEspia()
        request = _RequestFalso(
            "colunas=situacao&colunas=modalidade&colunas=item_pca"
            "&colunas=descricao_objeto&colunas=valor_estimado",
            sessao=sessao,
        )
        resultado = colunas_selecionadas(request)
        self.assertEqual(
            resultado,
            [
                "item_pca",
                "descricao_objeto",
                "valor_estimado",
                "situacao",
                "modalidade",
            ],
        )
        # A gravação em sessão também usa a ordem CANÔNICA, nunca a ordem
        # crua recebida — uma sessão gravada por este GET nunca fica
        # poluída fora de ordem.
        self.assertEqual(sessao["pca_colunas_tabela"], resultado)
        self.assertEqual(sessao.escritas, 1)

    def test_sessao_poluida_fora_de_ordem_devolve_canonica_sem_regravar_na_leitura(
        self,
    ):
        # Sem `?colunas=`: `colunas_selecionadas` só LÊ a sessão (nunca
        # escreve nesse ramo, guarda WR-03 preservada por construção) —
        # uma preferência antiga, gravada ANTES desta canonização existir,
        # continua produzindo a resposta canônica na hora de montar a
        # tabela, sem nenhum efeito colateral de escrita.
        for chaves_poluidas in (
            # Fora de ordem, mas já teria "parecido" canônico a um teste
            # ingênuo de igualdade (mistura núcleo/opcional intercalada).
            ["situacao", "modalidade", "item_pca", "descricao_objeto"],
            # Mesma seleção, já na ordem canônica — também não regrava.
            ["item_pca", "descricao_objeto", "situacao", "modalidade"],
        ):
            with self.subTest(chaves_poluidas=chaves_poluidas):
                sessao = _SessaoEspia({"pca_colunas_tabela": chaves_poluidas})
                request = _RequestFalso(sessao=sessao)
                resultado = colunas_selecionadas(request)
                self.assertEqual(
                    resultado,
                    ["item_pca", "descricao_objeto", "situacao", "modalidade"],
                )
                self.assertEqual(sessao.escritas, 0)

    def test_get_canonico_repetido_nao_regrava_a_sessao(self):
        # (c) — variante de WR-03 com núcleo E opcional misturados: a
        # canonização não introduz nenhuma escrita a mais quando o GET já
        # chega na ordem canônica e ela já é a mesma da sessão salva.
        # `descricao_objeto` (COLUNAS_OBRIGATORIAS) é sempre reinjetada por
        # `_normalizar`, então precisa estar na seleção para o resultado
        # ser estável entre a sessão salva e o GET repetido.
        sessao = _SessaoEspia(
            {
                "pca_colunas_tabela": [
                    "item_pca",
                    "descricao_objeto",
                    "valor_estimado",
                    "situacao",
                    "modalidade",
                ]
            }
        )
        request = _RequestFalso(
            "colunas=item_pca&colunas=descricao_objeto&colunas=valor_estimado"
            "&colunas=situacao&colunas=modalidade",
            sessao=sessao,
        )
        resultado = colunas_selecionadas(request)
        self.assertEqual(
            resultado,
            [
                "item_pca",
                "descricao_objeto",
                "valor_estimado",
                "situacao",
                "modalidade",
            ],
        )
        self.assertEqual(sessao.escritas, 0)

    def test_canonizar_nucleo_primeiro_opcionais_na_ordem_do_registro(self):
        # Teste direto de `canonizar` (sem `_RequestFalso`) — a mesma
        # garantia que `_normalizar`/`colunas_selecionadas` delegam a ela.
        self.assertEqual(
            canonizar(["situacao", "modalidade", "item_pca", "descricao_objeto"]),
            ["item_pca", "descricao_objeto", "situacao", "modalidade"],
        )
        # Dedup automático (via set) não depende da ordem de chegada.
        self.assertEqual(
            canonizar(["estado", "estado", "item_pca"]), ["item_pca", "estado"]
        )
        # Lista vazia continua vazia.
        self.assertEqual(canonizar([]), [])


class TestTabelaColunasDinamicas(TestCase):
    """Comportamento fim-a-fim de `/tabela` com o registro único de
    colunas: tabela dinâmica, seletor em acordeão e persistência por
    sessão Django. `TestCase` (não `TransactionTestCase`): fixture leve
    por ORM direto, sem depender do XLSX real — mesmo padrão de
    `test_acoes_tabela.py`."""

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.usuario = User.objects.create_user(
            email="colunas@example.com", password="senha-segura"
        )
        cls.unidade = Unidade.objects.create(nome="Presidência")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.tipo = Tipo.objects.create(nome="Aquisição")
        cls.exercicio = Exercicio.objects.get(ano=2026)
        cls.processo = Processo.objects.create(
            item_pca=1,
            descricao_objeto="Processo de teste do seletor de colunas",
            tipo=cls.tipo,
            categoria=cls.categoria,
            unidade_organizacional=cls.unidade,
            exercicio=cls.exercicio,
        )

    def test_padrao_mostra_exatamente_as_cinco_colunas_da_fase_28(self):
        client = Client()
        client.force_login(self.usuario)
        resposta = client.get(reverse("pca:tabela"))
        self.assertEqual(
            [c["chave"] for c in resposta.context["cabecalhos_dinamicos"]],
            list(COLUNAS_PADRAO),
        )
        conteudo = resposta.content.decode()
        self.assertIn("Prazo atual", conteudo)
        self.assertNotIn('data-th="Unidade"', conteudo)

    def test_selecao_explicita_na_url_troca_as_colunas_exibidas_e_grava_na_sessao(self):
        client = Client()
        client.force_login(self.usuario)
        resposta = client.get(
            reverse("pca:tabela"),
            {
                "colunas": ["item_pca", "descricao_objeto", "unidade_organizacional"],
            },
        )
        self.assertEqual(
            resposta.context["colunas_selecionadas"],
            ["item_pca", "descricao_objeto", "unidade_organizacional"],
        )
        self.assertEqual(
            client.session["pca_colunas_tabela"],
            ["item_pca", "descricao_objeto", "unidade_organizacional"],
        )
        conteudo = resposta.content.decode()
        self.assertIn('data-th="Unidade"', conteudo)
        self.assertNotIn('data-th="Situação"', conteudo)

    def test_requisicao_seguinte_sem_colunas_repete_a_selecao_da_sessao(self):
        client = Client()
        client.force_login(self.usuario)
        client.get(
            reverse("pca:tabela"),
            {"colunas": ["item_pca", "descricao_objeto", "estado"]},
        )
        resposta = client.get(reverse("pca:tabela"))
        self.assertEqual(
            resposta.context["colunas_selecionadas"],
            ["item_pca", "descricao_objeto", "estado"],
        )

    def test_duas_sessoes_distintas_nunca_interferem_uma_na_outra(self):
        cliente_a = Client()
        cliente_a.force_login(self.usuario)
        cliente_b = Client()
        cliente_b.force_login(self.usuario)

        cliente_a.get(
            reverse("pca:tabela"),
            {"colunas": ["item_pca", "descricao_objeto", "estado"]},
        )
        cliente_b.get(
            reverse("pca:tabela"),
            {"colunas": ["item_pca", "descricao_objeto", "tipo"]},
        )

        resposta_a = cliente_a.get(reverse("pca:tabela"))
        resposta_b = cliente_b.get(reverse("pca:tabela"))
        self.assertEqual(
            resposta_a.context["colunas_selecionadas"],
            ["item_pca", "descricao_objeto", "estado"],
        )
        self.assertEqual(
            resposta_b.context["colunas_selecionadas"],
            ["item_pca", "descricao_objeto", "tipo"],
        )

    def test_colunas_so_com_chaves_invalidas_cai_no_padrao_nunca_tabela_vazia(self):
        client = Client()
        client.force_login(self.usuario)
        resposta = client.get(reverse("pca:tabela"), {"colunas": ["lixo"]})
        self.assertEqual(
            resposta.context["colunas_selecionadas"], list(COLUNAS_PADRAO)
        )
        self.assertTrue(len(resposta.context["cabecalhos_dinamicos"]) > 0)

    def test_ordenacao_sem_colunas_preserva_a_selecao_da_sessao(self):
        client = Client()
        client.force_login(self.usuario)
        client.get(
            reverse("pca:tabela"),
            {"colunas": ["item_pca", "descricao_objeto", "estado"]},
        )
        resposta = client.get(
            reverse("pca:tabela"), {"ordenar": "item_pca", "dir": "desc"}
        )
        self.assertEqual(
            resposta.context["colunas_selecionadas"],
            ["item_pca", "descricao_objeto", "estado"],
        )

    def test_htmx_repetindo_a_mesma_selecao_continua_resolvendo_igual(self):
        # 28-REVIEW (WR-03) — smoke fim-a-fim: uma navegação HTMX
        # (`_listagem.html`, `hx-include="#form-colunas"`) que repete a
        # MESMA seleção já salva na sessão continua resolvendo a mesma
        # seleção corretamente após a guarda de WR-03 (a prova de que o
        # `__setitem__` deixa de disparar é unitária —
        # `test_get_repetindo_a_selecao_ja_salva_nao_regrava_a_sessao`,
        # em `TestResolvedorDeColunas` — porque `SESSION_SAVE_EVERY_
        # REQUEST = True` resalva a linha da sessão a cada requisição de
        # qualquer forma, tornando o efeito colateral invisível na linha
        # persistida no banco).
        client = Client()
        client.force_login(self.usuario)
        client.get(
            reverse("pca:tabela"),
            {"colunas": ["item_pca", "descricao_objeto", "estado"]},
        )
        self.assertEqual(
            client.session["pca_colunas_tabela"],
            ["item_pca", "descricao_objeto", "estado"],
        )
        resposta = client.get(
            reverse("pca:tabela"),
            {"colunas": ["item_pca", "descricao_objeto", "estado"]},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(
            resposta.context["colunas_selecionadas"],
            ["item_pca", "descricao_objeto", "estado"],
        )
        self.assertEqual(
            client.session["pca_colunas_tabela"],
            ["item_pca", "descricao_objeto", "estado"],
        )

    def test_seletor_colunas_expoe_aplicar_e_restaurar_padrao(self):
        client = Client()
        client.force_login(self.usuario)
        conteudo = client.get(reverse("pca:tabela")).content.decode()
        self.assertIn("Aplicar colunas", conteudo)
        self.assertIn("Restaurar padrão", conteudo)

    def test_seletor_colunas_mostra_as_quatro_legendas_das_secoes(self):
        # Planejamento, Processo, Execução contratual e Publicação,
        # nesta ordem, uma por `<legend>`.
        client = Client()
        client.force_login(self.usuario)
        conteudo = client.get(reverse("pca:tabela")).content.decode()
        posicoes = [
            conteudo.index(f"<legend>{nome}</legend>")
            for nome in ("Planejamento", "Processo", "Execução contratual", "Publicação")
        ]
        self.assertEqual(posicoes, sorted(posicoes))
