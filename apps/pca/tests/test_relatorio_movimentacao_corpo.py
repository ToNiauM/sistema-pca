"""Testes do fragmento copiável para o SEI.

Garante por teste automatizado, não por leitura humana, que
`pca/_relatorio_movimentacao_corpo.html` só produz tags da allowlist fechada
(h2/h3/p/strong/table/thead/tbody/tr/th/td/ul/li) e nenhum atributo
`class`/`style`/`svg` — a cola real no SEI fica para o UAT humano.
"""

from datetime import date, datetime
from decimal import Decimal
from html.parser import HTMLParser

from django.template.loader import render_to_string
from django.test import TestCase
from django.utils import timezone

from apps.catalogo.models import Categoria, Exercicio, Tipo, Unidade
from apps.pca.models import Processo
from apps.pca.relatorio_movimentacao import (
    BlocoRelatorio,
    ItemRelatorio,
    RelatorioMovimentacao,
)

ALLOWLIST_TAGS = {
    "h2",
    "h3",
    "p",
    "strong",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "ul",
    "li",
}

ATRIBUTOS_PROIBIDOS = {"class", "style"}


class _ColetorAllowlist(HTMLParser):
    """Registra toda tag e atributo fora da allowlist fechada."""

    def __init__(self):
        super().__init__()
        self.tags_fora_da_allowlist = []
        self.atributos_proibidos = []

    def handle_starttag(self, tag, attrs):
        if tag not in ALLOWLIST_TAGS:
            self.tags_fora_da_allowlist.append(tag)
        for nome, _valor in attrs:
            if nome in ATRIBUTOS_PROIBIDOS:
                self.atributos_proibidos.append((tag, nome))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)


class RelatorioMovimentacaoCorpoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.exercicio = Exercicio.objects.get(ano=2026)
        cls.unidade = Unidade.objects.create(nome="GEX-ITEC")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.tipo = Tipo.objects.create(nome="Aquisição")
        cls.processo = Processo.objects.create(
            item_pca=37,
            exercicio=cls.exercicio,
            descricao_objeto="Aquisição de notebooks",
            tipo=cls.tipo,
            categoria=cls.categoria,
            unidade_organizacional=cls.unidade,
        )

    def _relatorio_de_teste(self):
        item = ItemRelatorio(
            processo=self.processo,
            frase_principal=(
                "Item 37 – Aquisição de notebooks (GEX-ITEC): situação "
                "alterada de Em tramitação para Concluído em 28/08/2026."
            ),
            frases_extra=["ago → set em 05/08", "set → out em 20/08"],
            automatico=False,
        )
        bloco_com_itens = BlocoRelatorio(
            chave="concluidos",
            titulo="Concluídos",
            contagem=1,
            soma_valor=Decimal("15000.00"),
            itens=[item],
        )
        bloco_vazio = BlocoRelatorio(
            chave="exclusoes",
            titulo="Exclusões",
            contagem=0,
            soma_valor=None,
            itens=[],
        )
        return RelatorioMovimentacao(
            exercicio=self.exercicio,
            de=date(2026, 8, 1),
            ate=date(2026, 8, 31),
            blocos=[bloco_com_itens, bloco_vazio],
            gerado_em=timezone.make_aware(datetime(2026, 9, 10, 10, 0)),
            gerado_por="Fulano de Tal",
        )

    def _renderizar(self):
        return render_to_string(
            "pca/_relatorio_movimentacao_corpo.html",
            {"relatorio": self._relatorio_de_teste()},
        )

    def test_so_tags_da_allowlist_fechada(self):
        """Nenhuma tag fora de h2/h3/p/strong/table/thead/tbody/tr/th/td/ul/li
        — mesmo com bloco populado (tabela real) e bloco vazio (mensagem)."""
        html = self._renderizar()
        coletor = _ColetorAllowlist()
        coletor.feed(html)
        self.assertEqual(
            coletor.tags_fora_da_allowlist,
            [],
            f"Tags fora da allowlist encontradas: {coletor.tags_fora_da_allowlist}",
        )

    def test_nenhum_atributo_class_ou_style(self):
        """Nenhuma tag do fragmento carrega `class`/`style` — é HTML mínimo
        para o editor nativo do SEI, nunca o DOM com classes br-*."""
        html = self._renderizar()
        coletor = _ColetorAllowlist()
        coletor.feed(html)
        self.assertEqual(
            coletor.atributos_proibidos,
            [],
            f"Atributos proibidos encontrados: {coletor.atributos_proibidos}",
        )

    def test_conteudo_essencial_presente(self):
        """O fragmento traz o título, a linha de abertura, o bloco populado
        (com total) e o bloco vazio (mensagem padrão) — allowlist fechada
        não pode custar conteúdo."""
        html = self._renderizar()
        self.assertIn("Relatório de Acompanhamento do Plano de Contratações Anual", html)
        self.assertIn("Movimentação do PCA 2026 entre 01/08/2026 e 31/08/2026.", html)
        self.assertIn("Concluídos", html)
        self.assertIn("Aquisição de notebooks", html)
        self.assertIn("Total: R$ 15.000,00", html)
        self.assertIn("Nenhum item neste período.", html)

    def test_nao_estende_base_nem_carrega_classes_br(self):
        """Sem `{% extends %}` (o fragmento não é uma página) e sem nenhuma
        ocorrência do prefixo `br-` (nunca o DOM da tela com classes do DS)."""
        html = self._renderizar()
        self.assertNotIn("<html", html)
        self.assertNotIn("br-", html)

    def test_item_automatico_mostra_marcador_no_fragmento_copiavel(self):
        """Item com `automatico=True` recebe a marca "(automático)"
        também no fragmento copiável para o SEI, dentro da allowlist
        fechada (só `<strong>`, sem `span`/`class`)."""
        item_automatico = ItemRelatorio(
            processo=self.processo,
            frase_principal=(
                "Item 37 – Aquisição de notebooks (GEX-ITEC): mudou de mês "
                "previsto automaticamente."
            ),
            frases_extra=[],
            automatico=True,
        )
        bloco = BlocoRelatorio(
            chave="mudou_mes",
            titulo="Mudaram de mês",
            contagem=1,
            soma_valor=None,
            itens=[item_automatico],
        )
        relatorio = RelatorioMovimentacao(
            exercicio=self.exercicio,
            de=date(2026, 8, 1),
            ate=date(2026, 8, 31),
            blocos=[bloco],
            gerado_em=timezone.make_aware(datetime(2026, 9, 10, 10, 0)),
            gerado_por="Fulano de Tal",
        )
        html = render_to_string(
            "pca/_relatorio_movimentacao_corpo.html", {"relatorio": relatorio}
        )
        self.assertIn("(automático)", html)

        coletor = _ColetorAllowlist()
        coletor.feed(html)
        self.assertEqual(coletor.tags_fora_da_allowlist, [])
        self.assertEqual(coletor.atributos_proibidos, [])
