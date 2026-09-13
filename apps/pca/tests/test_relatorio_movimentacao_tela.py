"""Testes da tela "Relatório de movimentação".

Cobre só o que `apps.pca.tests.test_relatorio_movimentacao` (a lógica de
domínio) não alcança: a view (wiring de exercício/período) e a
renderização HTML real da tela, via `django.test.Client` — nunca grep de
template.
"""

import re
from datetime import date
from html.parser import HTMLParser

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.catalogo.models import Categoria, Exercicio, SituacaoNormalizada, Tipo, Unidade
from apps.pca.models import Acompanhamento, Processo, Reuniao, SituacaoReuniao, TipoEvento

_RE_TEMPLATE_COPIAVEL = re.compile(
    r'<template id="relatorio-corpo-copiavel">.*?</template>', re.S
)


def _sem_fragmento_copiavel(html):
    """Remove o `<template id="relatorio-corpo-copiavel">` do HTML bruto
    antes de contar ocorrências de texto — seu conteúdo espelha o
    relatório visível, então contagens simples dobrariam sem este filtro.
    O navegador nunca renderiza `<template>`; este teste só evita o falso
    positivo de uma checagem textual sobre o HTML bruto da resposta."""
    return _RE_TEMPLATE_COPIAVEL.sub("", html)


class _ColetorEstrutura(HTMLParser):
    """Mesmo coletor mínimo de `test_estrutura_paginas.py` — conta `<h1>`
    e `br-button primary`, sem depender de html5lib (indisponível)."""

    def __init__(self):
        super().__init__()
        self.h1_count = 0
        self.primary_count = 0

    def handle_starttag(self, tag, attrs):
        atributos = dict(attrs)
        if tag == "h1":
            self.h1_count += 1
        classes = atributos.get("class", "").split()
        if tag in ("button", "a") and "br-button" in classes and "primary" in classes:
            self.primary_count += 1


class _ColetorNaoImprimir(HTMLParser):
    """Rastreia se um texto (`agulha`) aparece dentro ou fora de algum
    elemento com a classe `dsgov-nao-imprimir` — `dsgov.css` esconde essa
    classe em `@media print`, então o texto do rodapé de rastreio só
    sobrevive à impressão se ficar fora dela. Mantém uma pilha booleana
    por tag aberta: cada nível herda True do pai se este já estava dentro
    de `.dsgov-nao-imprimir`."""

    def __init__(self, agulha):
        super().__init__()
        self.agulha = agulha
        self._pilha = []
        self.encontrado_dentro = False
        self.encontrado_fora = False

    def handle_starttag(self, tag, attrs):
        atributos = dict(attrs)
        classes = atributos.get("class", "").split()
        pai_dentro = self._pilha[-1] if self._pilha else False
        self._pilha.append(pai_dentro or "dsgov-nao-imprimir" in classes)

    def handle_startendtag(self, tag, attrs):
        # Tag auto-fechada (ex.: <input/>) não empilha estado para filhos.
        pass

    def handle_endtag(self, tag):
        if self._pilha:
            self._pilha.pop()

    def handle_data(self, data):
        if self.agulha not in data:
            return
        dentro = self._pilha[-1] if self._pilha else False
        if dentro:
            self.encontrado_dentro = True
        else:
            self.encontrado_fora = True


class RelatorioMovimentacaoTelaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.exercicio = Exercicio.objects.get(ano=2026)
        cls.unidade = Unidade.objects.create(nome="GEX-ITEC")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.tipo = Tipo.objects.create(nome="Aquisição")
        cls.situacao_normalizada = SituacaoNormalizada.objects.create(
            nome="Concluído (reunião)"
        )
        cls.usuario = get_user_model().objects.create_user(
            email="relatorio-tela@pca.local", password="senha-forte-123"
        )

    def setUp(self):
        self.client.force_login(self.usuario)

    def test_periodo_sem_movimentacao_mostra_os_6_blocos_vazios(self):
        """Um período sem nenhuma movimentação real (ex. antes de qualquer
        history) mostra a mensagem de bloco vazio 6 vezes — os 6 blocos
        sempre existem, mesmo vazios."""
        resposta = self.client.get(
            reverse("pca:relatorio_movimentacao"),
            {"de": "2020-01-01", "ate": "2020-01-02"},
        )
        self.assertEqual(resposta.status_code, 200)
        conteudo = _sem_fragmento_copiavel(resposta.content.decode())
        self.assertEqual(conteudo.count("Nenhum item neste período."), 6)

    def test_periodo_com_reuniao_mostra_bloco_adiados_populado(self):
        """Um compromisso de reunião (`prazo_prometido` + `evento`) dentro
        do período aparece no bloco Adiados, com a frase institucional
        completa."""
        reuniao = Reuniao.objects.create(
            data=date(2026, 9, 1),
            situacao=SituacaoReuniao.FECHADA,
            exercicio=self.exercicio,
        )
        processo = Processo.objects.create(
            item_pca=1,
            exercicio=self.exercicio,
            descricao_objeto="Aquisição de notebooks",
            tipo=self.tipo,
            categoria=self.categoria,
            unidade_organizacional=self.unidade,
            prazo_entrega=date(2026, 9, 10),
        )
        Acompanhamento.objects.create(
            processo=processo,
            referencia_data=reuniao.data,
            origem_hash="hash-tela-1",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO,
            situacao=self.situacao_normalizada,
            prazo_prometido=date(2026, 10, 20),
            reuniao=reuniao,
            evento="Aguardando parecer jurídico.",
        )

        resposta = self.client.get(
            reverse("pca:relatorio_movimentacao"),
            {"de": "2026-09-01", "ate": "2026-09-01"},
        )
        self.assertEqual(resposta.status_code, 200)
        conteudo = resposta.content.decode()
        self.assertIn("Adiados", conteudo)
        self.assertIn("Aquisição de notebooks", conteudo)
        self.assertIn("Aguardando parecer jurídico.", conteudo)

    def test_pagina_tem_exatamente_um_h1_e_no_maximo_um_primary(self):
        resposta = self.client.get(reverse("pca:relatorio_movimentacao"))
        self.assertEqual(resposta.status_code, 200)
        coletor = _ColetorEstrutura()
        coletor.feed(resposta.content.decode())
        self.assertEqual(coletor.h1_count, 1)
        self.assertLessEqual(coletor.primary_count, 1)

    def test_sem_exercicio_cadastrado_mostra_mensagem_e_nao_quebra(self):
        Exercicio.objects.all().delete()
        resposta = self.client.get(reverse("pca:relatorio_movimentacao"))
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("Nenhum exercício cadastrado.", resposta.content.decode())

    def test_rodape_de_rastreio_fica_fora_do_dsgov_nao_imprimir(self):
        """"Gerado em..." não pode ficar sob `.dsgov-nao-imprimir` —
        `dsgov.css` esconde essa classe em `@media print`, o que apagaria
        o rodapé de rastreio do PDF."""
        resposta = self.client.get(reverse("pca:relatorio_movimentacao"))
        self.assertEqual(resposta.status_code, 200)
        conteudo = _sem_fragmento_copiavel(resposta.content.decode())
        coletor = _ColetorNaoImprimir("Gerado em")
        coletor.feed(conteudo)
        self.assertTrue(coletor.encontrado_fora)
        self.assertFalse(coletor.encontrado_dentro)

    def test_rodape_institucional_vem_de_settings_dsgov(self):
        """O texto do timbrado impresso vem de
        `settings.DSGOV['RODAPE_TIMBRADO']`, não de um literal novo."""
        resposta = self.client.get(reverse("pca:relatorio_movimentacao"))
        self.assertEqual(resposta.status_code, 200)
        conteudo = resposta.content.decode()
        self.assertIn(settings.DSGOV["RODAPE_TIMBRADO"], conteudo)
