"""`apps/assistente/esquema.py::catalogo()`:
catálogo de tabelas/colunas/FKs/choices de `apps.pca` + `apps.catalogo` +
`core.Usuario` (+ `Historical*`), omitindo tabela/coluna bloqueada e
cacheado por processo. `django.test.TestCase` comum (usa `django.apps`/
`model._meta`, não é puro como `sql.py`)."""

from django.test import TestCase

from apps.assistente import esquema


class TestCatalogo(TestCase):
    def test_contem_as_tabelas_principais(self):
        texto = esquema.catalogo()
        self.assertIsInstance(texto, str)
        self.assertTrue(texto)
        self.assertIn("pca_processo", texto)
        self.assertIn("catalogo_unidade", texto)

    def test_cita_choices_do_campo_estado_em_valor_igual_rotulo(self):
        texto = esquema.catalogo()
        self.assertIn("ativo=Ativo", texto)
        self.assertIn("cancelado=Cancelado", texto)

    def test_nunca_cita_password(self):
        texto = esquema.catalogo()
        self.assertNotIn("password", texto)

    def test_nunca_cita_django_session_nem_tabela_axes(self):
        texto = esquema.catalogo()
        self.assertNotIn("django_session", texto)
        self.assertNotIn("axes_", texto)

    def test_cita_tabela_historica_com_nota_de_convencao(self):
        texto = esquema.catalogo()
        self.assertIn("pca_historicalprocesso", texto)
        self.assertIn("history_date", texto)
        self.assertIn("history_type", texto)
        self.assertIn("history_user_id", texto)

    def test_segunda_chamada_usa_o_cache(self):
        esquema.catalogo.cache_clear()
        esquema.catalogo()
        esquema.catalogo()
        self.assertGreaterEqual(esquema.catalogo.cache_info().hits, 1)
