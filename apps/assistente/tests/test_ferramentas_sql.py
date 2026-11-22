"""Ferramenta `consultar_sql` em `ferramentas.
py`: registrada em `ESQUEMAS`/`FUNCOES`, descrição embute o catálogo de
`esquema.catalogo()`, nunca levanta exceção (SQL negado vira `erro` no
envelope) e o dispatcher não exige `exercicio` para ela — mesmo
tratamento de `buscar_texto`."""

import json
from unittest import mock

from apps.assistente import ferramentas
from apps.assistente.tests.base import AssistenteTestBase


class TestConsultarSqlRegistrada(AssistenteTestBase):
    def test_esta_em_esquemas_e_funcoes(self):
        self.assertIn("consultar_sql", ferramentas.ESQUEMAS)
        self.assertIn("consultar_sql", ferramentas.FUNCOES)

    def test_descricao_embute_o_catalogo(self):
        descricao = ferramentas.ESQUEMAS["consultar_sql"]["function"]["description"]
        self.assertIn("pca_processo", descricao)


class TestConsultarSqlFuncao(AssistenteTestBase):
    def test_select_simples_devolve_colunas_e_linhas(self):
        envelope = ferramentas.consultar_sql(
            self.editor, sql="SELECT COUNT(*) AS n FROM pca_processo"
        )
        self.assertNotIn("erro", envelope.dados)
        self.assertEqual(envelope.dados["colunas"], ["n"])
        self.assertTrue(envelope.dados["linhas"])

    def test_drop_table_devolve_erro_sem_levantar_e_sem_permissao_falso(self):
        envelope = ferramentas.consultar_sql(self.editor, sql="DROP TABLE pca_processo")
        self.assertTrue(envelope.dados.get("erro"))
        self.assertFalse(envelope.sem_permissao)

    def test_sql_vazio_devolve_erro_sem_abrir_conexao(self):
        with mock.patch("apps.assistente.sql.executar_select") as espiao:
            envelope = ferramentas.consultar_sql(self.editor, sql="")
        self.assertTrue(envelope.dados.get("erro"))
        espiao.assert_not_called()

    def test_sql_longo_demais_devolve_erro_sem_abrir_conexao(self):
        with mock.patch("apps.assistente.sql.executar_select") as espiao:
            envelope = ferramentas.consultar_sql(self.editor, sql="x" * 4001)
        self.assertTrue(envelope.dados.get("erro"))
        espiao.assert_not_called()

    def test_sem_referencias_e_com_atualidade(self):
        envelope = ferramentas.consultar_sql(self.editor, sql="SELECT 1 AS um")
        self.assertEqual(envelope.referencias, [])
        self.assertIn("pca_consultado_em", envelope.atualidade)


class TestConsultarSqlViaDispatcher(AssistenteTestBase):
    def test_executar_funciona_sem_exigir_exercicio(self):
        envelope = ferramentas.executar(
            "consultar_sql",
            json.dumps({"sql": "SELECT 1"}),
            usuario=self.editor,
            exercicio_padrao=None,
        )
        self.assertNotIn("erro", envelope.dados)
        self.assertEqual(envelope.dados["linhas"], [[1]])
