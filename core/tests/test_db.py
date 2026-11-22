"""Fase 31 — testes-guarda das peças portáveis de `core.db`:
collation `ptbr` (ordenação de texto sem depender de ICU do Postgres) e
`DiasEntre` (diferença de dias sem `Extract(DurationField)`)."""

from datetime import date
from unittest import skipUnless

from django.db import connection
from django.test import TestCase
from freezegun import freeze_time

from apps.catalogo.models import Categoria, Exercicio, Tipo, Unidade
from apps.pca.models import Processo


class TestCollationPtbr(TestCase):
    """`Unidade` não passa `order_by` explícito — confia no `Meta.ordering`
    de `DominioBase`, agora `Collate(F("nome"), "ptbr")`."""

    def test_ordenacao_ignora_acento_e_caixa(self):
        for nome in ["Zebra", "ética", "Árvore", "banana"]:
            Unidade.objects.create(nome=nome)

        self.assertEqual(
            list(Unidade.objects.values_list("nome", flat=True)),
            ["Árvore", "banana", "ética", "Zebra"],
        )


class TestDiasEntre(TestCase):
    """`ProcessoQuerySet.para_listagem()` usa `core.db.DiasEntre` em vez de
    `Extract(DurationField)` para `dias_atraso` — mesmo golden number já
    coberto por `test_dias_atraso_respeita_localdate`
    (apps/pca/tests/test_querysets.py), reconfirmado aqui após a troca."""

    @classmethod
    def setUpTestData(cls):
        cls.unidade = Unidade.objects.create(nome="Presidência")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.tipo = Tipo.objects.create(nome="Aquisição")
        cls.exercicio = Exercicio.objects.get(ano=2026)

    def test_dias_atraso_bate_com_a_diferenca_esperada(self):
        with freeze_time("2026-08-15 12:00:00"):
            processo = Processo.objects.create(
                item_pca=1,
                descricao_objeto="Objeto teste",
                tipo=self.tipo,
                categoria=self.categoria,
                unidade_organizacional=self.unidade,
                exercicio=self.exercicio,
                prazo_entrega=date(2026, 8, 5),
            )
            resultado = Processo.objects.para_listagem().get(pk=processo.pk)
            self.assertTrue(resultado.atrasado)
            self.assertEqual(resultado.dias_atraso, 10)


class TestBancoDeTesteEmArquivo(TestCase):
    """Revisão da Fase 31 (MD-01) — guarda de que `DATABASES["default"]["TEST"]`
    (config/settings/base.py) realmente aponta para um arquivo com WAL ativo,
    não para o `:memory:` padrão do Django (sem WAL, lock de tabela inteira
    em vez do lock de banco inteiro de produção)."""

    @skipUnless(connection.vendor == "sqlite", "guarda específica do backend sqlite3")
    def test_banco_de_teste_usa_wal(self):
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA journal_mode")
            (modo,) = cursor.fetchone()
        self.assertEqual(modo.lower(), "wal")
