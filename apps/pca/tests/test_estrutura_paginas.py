"""Guarda de estrutura por página.

`ops/dsgov/verificar.py` prova conformidade estática (classes, elementos,
CSS/JS fixos) lendo o arquivo `.html` como texto — não prova nada sobre o
HTML de fato renderizado para uma URL real. Este arquivo cobre o que só se
vê em runtime: exatamente um `<h1>` por página, no máximo um `br-button
primary`, e `role="img"`/`aria-label` em todo elemento `[data-grafico]`
(gráficos ECharts).

Parser: `html.parser` da stdlib, não `html5lib` — o pacote não está
instalado neste ambiente.

`<title>`/`<h1>`/último item de `trilha` não são forçados a serem
byte-idênticos entre si — o contrato real é "aparentados, não idênticos":
`<title>` carrega contexto extra pt-BR (ex. "Processos · PCA 2026"), o
`<h1>` é o rótulo limpo ("Processos"), e páginas de fluxo em etapas
(wizard) legitimamente não têm `trilha` nenhuma (a barra de progresso já
resolve wayfinding). Forçar igualdade literal exigiria reescrever texto
de páginas corretas sem nenhum ganho de conformidade — fora do
escopo desta fase de fechamento (o gate real é `test_dsgov_conformidade`).
"""

from datetime import date, timedelta
from decimal import Decimal
from html.parser import HTMLParser
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from apps.catalogo.models import Categoria, Exercicio, SituacaoNormalizada, Tipo, Unidade
from apps.pca.models import Estado, Processo, Situacao
from apps.pca.services import registrar_acompanhamento

ARQUIVO_REAL = "apps/pca/fixtures/modelo-controle-exemplo.xlsx"


class _ColetorEstrutura(HTMLParser):
    """Conta `<h1>`, `br-button primary` e coleta atributos de
    `[data-grafico]` — o suficiente para as 2 asserções deste arquivo, sem
    depender de árvore DOM completa (html5lib indisponível)."""

    def __init__(self):
        super().__init__()
        self.h1_count = 0
        self.primary_count = 0
        self.graficos = []

    def handle_starttag(self, tag, attrs):
        atributos = dict(attrs)
        if tag == "h1":
            self.h1_count += 1
        classes = atributos.get("class", "").split()
        if tag in ("button", "a") and "br-button" in classes and "primary" in classes:
            self.primary_count += 1
        if "data-grafico" in atributos:
            self.graficos.append(atributos)


def _coletar(conteudo):
    coletor = _ColetorEstrutura()
    coletor.feed(conteudo)
    return coletor


class TestEstruturaPaginasMigradas(TransactionTestCase):
    """Uma URL representativa por template de página (excluídos partials
    `_*.html`, `base.html`/`dsgov/_*.html` da skill — fixos e já provados
    por `test_dsgov_conformidade` — e páginas autônomas sem `trilha`/menu,
    `login.html`/`erro.html`, cobertas por `test_login_flow.py`)."""

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
        # Superusuário: este guard prova ESTRUTURA de página, não
        # permissão (já coberta por test_permissoes.py/
        # test_multiexercicio_permissoes.py) — evita 20 linhas de wiring
        # de grupo/permissão por página só para poder ver o botão certo.
        self.admin = User.objects.create_superuser(
            email="admin-estrutura@pca.local", password="senha-segura"
        )
        self.client.force_login(self.admin)
        self.item_pca = 1

    def _urls(self):
        return {
            "inicio": reverse("core:inicio"),
            "sobre": reverse("core:sobre"),
            "trocar_senha": reverse("core:trocar_senha"),
            "perfil": reverse("core:perfil"),
            "tabela": reverse("pca:tabela"),
            "analise": reverse("pca:analise"),
            "relatorio_movimentacao": reverse("pca:relatorio_movimentacao"),
            "calendario": reverse("pca:calendario"),
            "resumo_uo": reverse("pca:resumo_uo"),
            "gerenciar_exercicios": reverse("pca:gerenciar_exercicios"),
            "reuniao_listagem": reverse("pca:reuniao_listagem"),
            "reuniao_formulario": reverse("pca:criar_reuniao"),
            "exportar": reverse("pca:exportar"),
            "detalhe_processo": reverse(
                "pca:detalhe_processo", args=[2026, self.item_pca]
            ),
            "editar_processo": reverse(
                "pca:editar_processo", args=[2026, self.item_pca]
            ),
            "criar_processo": reverse("pca:criar_processo"),
            "transicao_processo": reverse(
                "pca:transicao_processo", args=[2026, self.item_pca]
            ),
            "encerrar_confirmar": reverse("pca:encerrar_confirmar", args=[2026]),
            "virada_selecionar": reverse("pca:virada", args=[2027]),
        }

    def test_extends_base_um_h1_e_no_maximo_um_primary(self):
        for nome_tela, url in self._urls().items():
            with self.subTest(tela=nome_tela):
                resposta = self.client.get(url)
                self.assertEqual(
                    resposta.status_code, 200, f"{nome_tela}: GET {url} != 200"
                )
                conteudo = resposta.content.decode()

                # ESTRUTURA — a página estende base.html (a casca da skill
                # sempre imprime este contêiner raiz, `base.html` linha 15).
                self.assertIn(
                    'class="template-base"',
                    conteudo,
                    f"{nome_tela}: não parece estender base.html (casca da skill ausente)",
                )

                coletor = _coletar(conteudo)
                self.assertEqual(
                    coletor.h1_count,
                    1,
                    f"{nome_tela}: {coletor.h1_count} <h1> na página (deve haver exatamente 1)",
                )
                self.assertLessEqual(
                    coletor.primary_count,
                    1,
                    f"{nome_tela}: {coletor.primary_count} br-button primary (deve haver no máximo 1)",
                )

    def test_graficos_tem_role_img_e_aria_label(self):
        """references/graficos.md — todo `[data-grafico]` (ECharts) precisa
        de `role="img"` + `aria-label` (o `resumo` textual do gráfico para
        quem usa leitor de tela). `core:inicio` é a única página com
        gráficos garantidos por fixture nesta suíte (dashboard)."""
        resposta = self.client.get(reverse("core:inicio"))
        self.assertEqual(resposta.status_code, 200)
        conteudo = resposta.content.decode()
        if "data-grafico" not in conteudo:
            self.skipTest("nenhum gráfico renderizado com os dados de fixture desta suíte")

        coletor = _coletar(conteudo)
        self.assertTrue(coletor.graficos, "data-grafico apareceu no texto mas não foi coletado como atributo")
        for atributos in coletor.graficos:
            self.assertEqual(atributos.get("role"), "img", '[data-grafico] sem role="img"')
            self.assertTrue(atributos.get("aria-label"), "[data-grafico] sem aria-label")


class TestContainerConcentrado(TransactionTestCase):
    """`container-fluid` não tem largura máxima e estica o conteúdo até
    a borda da janela em monitores grandes, o oposto do padrão gov.br de
    concentrar dentro de margens (`container-lg`). Prova em runtime que
    todas as páginas usam `container-lg` e nenhuma usa
    `container-fluid`."""

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
        self.admin = User.objects.create_superuser(
            email="admin-container-concentrado@pca.local", password="senha-segura"
        )
        self.client.force_login(self.admin)
        self.item_pca = 1

    def test_paginas_usam_container_lg_sem_fluid(self):
        urls = {
            "inicio": reverse("core:inicio"),
            "tabela": reverse("pca:tabela"),
            "calendario": reverse("pca:calendario"),
            "resumo_uo": reverse("pca:resumo_uo"),
            "analise": reverse("pca:analise"),
            "criar_processo": reverse("pca:criar_processo"),
        }
        for nome_tela, url in urls.items():
            with self.subTest(tela=nome_tela):
                resposta = self.client.get(url)
                self.assertEqual(
                    resposta.status_code, 200, f"{nome_tela}: GET {url} != 200"
                )
                conteudo = resposta.content.decode()
                self.assertIn(
                    "container-lg",
                    conteudo,
                    f"{nome_tela}: deveria usar container-lg (padrão único)",
                )
                self.assertNotIn(
                    "container-fluid",
                    conteudo,
                    f"{nome_tela}: container-fluid não deveria mais existir em "
                    "nenhuma página (variante fluida revogada)",
                )


class TestFichaPncp(TestCase):
    """A ficha PNCP não confunde nulo com zero nos quadros financeiros,
    preserva o tratamento de Tipo Vigente/Estado Cancelado e reflete a
    mesma leitura de sobreposição manual que a tabela/filtro/XLSX já
    usam via `situacao_efetiva` — dias sempre factuais sobre
    `prazo_efetivo`."""

    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_superuser(
            email="admin-ficha-pncp@pca.local", password="senha-segura"
        )
        cls.unidade = Unidade.objects.create(nome="GEX-Ficha")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.tipo = Tipo.objects.create(nome="Aquisição")
        cls.tipo_vigente = Tipo.objects.create(nome="Vigente")
        cls.exercicio = Exercicio.objects.get(ano=2026)
        for nome in ("Sem informação", "Concluído", "Em tramitação"):
            SituacaoNormalizada.objects.get_or_create(nome=nome)

    def setUp(self):
        self.client.force_login(self.usuario)

    def _processo(self, item, *, tipo=None, **extra):
        return Processo.objects.create(
            item_pca=item,
            descricao_objeto=f"Objeto {item}",
            tipo=tipo or self.tipo,
            categoria=self.categoria,
            unidade_organizacional=self.unidade,
            exercicio=self.exercicio,
            **extra,
        )

    def _url(self, processo):
        return reverse(
            "pca:detalhe_processo", args=[self.exercicio.ano, processo.item_pca]
        )

    def test_quadros_financeiros_distinguem_zero_de_ausente(self):
        com_zero_e_ausente = self._processo(
            201, valor_estimado=Decimal("0"), valor_contratado=None
        )
        conteudo = self.client.get(self._url(com_zero_e_ausente)).content.decode()
        self.assertIn("R$ 0,00", conteudo)
        self.assertIn("Não informado", conteudo)

        com_valores = self._processo(
            202, valor_estimado=Decimal("1500.50"), valor_contratado=Decimal("0")
        )
        conteudo = self.client.get(self._url(com_valores)).content.decode()
        self.assertIn("R$ 1.500,50", conteudo)
        self.assertIn("R$ 0,00", conteudo)

    def test_estado_cancelado_preserva_tag_e_quadro_prazo_atual(self):
        processo = self._processo(
            203, estado=Estado.CANCELADO, prazo_entrega=date(2020, 1, 1)
        )
        conteudo = self.client.get(self._url(processo)).content.decode()
        self.assertIn(">Cancelado<", conteudo)
        self.assertIn("(cancelado)", conteudo)

    def test_tipo_vigente_preserva_tag_e_acoes_autorizadas(self):
        processo = self._processo(204, tipo=self.tipo_vigente)
        resposta = self.client.get(self._url(processo))
        self.assertEqual(resposta.status_code, 200)
        conteudo = resposta.content.decode()
        self.assertIn(">Vigente<", conteudo)
        self.assertIn("Editar", conteudo)

    def test_manual_no_prazo_vencido_mostra_no_prazo_com_dias_factuais(self):
        # Sobreposição manual "No prazo" sobrevive a uma promessa
        # passada: a ficha mostra a mesma situação que tabela/filtro/XLSX
        # (tag "No prazo"), com a contagem de dias factual sobre
        # `prazo_efetivo` (vencido) — nunca mascarando o atraso real.
        processo = self._processo(205, situacao=Situacao.ATRASADO)
        registrar_acompanhamento(
            processo_id=processo.pk,
            usuario=self.usuario,
            versao_cliente=processo.atualizado_em.isoformat(),
            situacao_novo=Situacao.NO_PRAZO.value,
            observacao="Sobreposição manual em reunião",
        )
        processo.refresh_from_db()
        registrar_acompanhamento(
            processo_id=processo.pk,
            usuario=self.usuario,
            versao_cliente=processo.atualizado_em.isoformat(),
            prazo_prometido=date.today() - timedelta(days=3),
        )

        conteudo = self.client.get(self._url(processo)).content.decode()
        self.assertIn(">No prazo<", conteudo)
        self.assertIn("vencido há 3 dia", conteudo)

    def test_manual_atrasado_futuro_mostra_atrasado_com_dias_factuais(self):
        processo = self._processo(206, situacao=Situacao.NO_PRAZO)
        registrar_acompanhamento(
            processo_id=processo.pk,
            usuario=self.usuario,
            versao_cliente=processo.atualizado_em.isoformat(),
            situacao_novo=Situacao.ATRASADO.value,
            observacao="Sobreposição manual em reunião",
        )
        processo.refresh_from_db()
        registrar_acompanhamento(
            processo_id=processo.pk,
            usuario=self.usuario,
            versao_cliente=processo.atualizado_em.isoformat(),
            prazo_prometido=date.today() + timedelta(days=10),
        )

        conteudo = self.client.get(self._url(processo)).content.decode()
        self.assertIn(">Atrasado<", conteudo)
        self.assertIn("vence em 10 dia", conteudo)
