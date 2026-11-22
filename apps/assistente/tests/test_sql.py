"""`apps/assistente/sql.py::executar_select`:
execução SQL somente leitura, pura (sem Django/ORM). Arquivo SQLite
temporário com tabelas fictícias, nunca o banco real do Django — a classe
inteira compartilha o mesmo arquivo (`setUpClass`/`tearDownClass`) para que
o hash SHA-256 antes/depois prove, de uma vez, que NENHUM teste alterou o
arquivo (T-xaq-01)."""

import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from apps.assistente import sql


def _preparar_banco(caminho: str) -> None:
    conexao = sqlite3.connect(caminho)
    try:
        conexao.executescript(
            """
            CREATE TABLE grupos (id INTEGER PRIMARY KEY, nome TEXT);
            INSERT INTO grupos (id, nome) VALUES (1, 'A'), (2, 'B');

            CREATE TABLE pessoas (
                id INTEGER PRIMARY KEY, nome TEXT, grupo_id INTEGER, valor REAL
            );
            INSERT INTO pessoas (id, nome, grupo_id, valor) VALUES
                (1, 'Ana', 1, 10.0), (2, 'Bia', 1, 20.0), (3, 'Caio', 2, 5.0);

            CREATE TABLE django_session (
                session_key TEXT PRIMARY KEY, session_data TEXT
            );
            INSERT INTO django_session VALUES ('abc123', 'segredo-de-sessao');

            CREATE TABLE axes_accesslog (id INTEGER PRIMARY KEY, ip_address TEXT);
            INSERT INTO axes_accesslog VALUES (1, '127.0.0.1');

            CREATE TABLE core_usuario (
                id INTEGER PRIMARY KEY, email TEXT, password TEXT
            );
            INSERT INTO core_usuario VALUES (1, 'a@a.com', 'hash-secreto-nunca-pode-sair');

            CREATE TABLE muitas_linhas (id INTEGER PRIMARY KEY, valor TEXT);

            CREATE TABLE textao (id INTEGER PRIMARY KEY, texto TEXT);
            """
        )
        conexao.executemany(
            "INSERT INTO muitas_linhas (valor) VALUES (?)",
            [(f"linha {i}",) for i in range(250)],
        )
        conexao.executemany(
            "INSERT INTO textao (texto) VALUES (?)",
            [("x" * 300,) for _ in range(5)],
        )
        conexao.commit()
    finally:
        conexao.close()


def _hash_arquivo(caminho: str) -> str:
    return hashlib.sha256(Path(caminho).read_bytes()).hexdigest()


class TestExecutarSelect(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmp = tempfile.TemporaryDirectory()
        cls.caminho_db = str(Path(cls._tmp.name) / "teste.sqlite3")
        _preparar_banco(cls.caminho_db)
        cls._hash_antes = _hash_arquivo(cls.caminho_db)

    @classmethod
    def tearDownClass(cls):
        hash_depois = _hash_arquivo(cls.caminho_db)
        cls._tmp.cleanup()
        super().tearDownClass()
        if hash_depois != cls._hash_antes:
            raise AssertionError(
                "o arquivo .sqlite3 de teste foi alterado por algum teste desta classe "
                "— a conexão de executar_select deveria ser somente leitura"
            )

    def _contar(self, tabela: str) -> int:
        conexao = sqlite3.connect(self.caminho_db)
        try:
            return conexao.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0]
        finally:
            conexao.close()

    # --- SELECT legítimo: JOIN, GROUP BY, CTE recursiva -----------------

    def test_select_simples_com_join_e_group_by(self):
        resultado = sql.executar_select(
            "SELECT g.nome, COUNT(*) AS total, SUM(p.valor) AS soma "
            "FROM pessoas p JOIN grupos g ON g.id = p.grupo_id "
            "GROUP BY g.nome ORDER BY g.nome",
            caminho_db=self.caminho_db,
        )
        self.assertEqual(set(resultado.keys()), {"colunas", "linhas", "total_linhas", "truncado"})
        self.assertEqual(resultado["colunas"], ["nome", "total", "soma"])
        self.assertEqual(resultado["linhas"], [["A", 2, 30.0], ["B", 1, 5.0]])
        self.assertEqual(resultado["total_linhas"], 2)
        self.assertFalse(resultado["truncado"])

    def test_cte_recursiva_funciona(self):
        resultado = sql.executar_select(
            "WITH RECURSIVE cnt(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM cnt WHERE x < 5) "
            "SELECT x FROM cnt",
            caminho_db=self.caminho_db,
        )
        self.assertEqual(resultado["linhas"], [[1], [2], [3], [4], [5]])

    # --- Escrita/estrutura: sempre ErroSQL, nunca executa ---------------

    def test_insert_e_negado_e_nao_executa(self):
        with self.assertRaises(sql.ErroSQL):
            sql.executar_select(
                "INSERT INTO pessoas (nome) VALUES ('Novo')", caminho_db=self.caminho_db
            )
        self.assertEqual(self._contar("pessoas"), 3)

    def test_update_e_negado_e_nao_executa(self):
        with self.assertRaises(sql.ErroSQL):
            sql.executar_select("UPDATE pessoas SET valor = 999", caminho_db=self.caminho_db)
        conexao = sqlite3.connect(self.caminho_db)
        try:
            maior = conexao.execute("SELECT MAX(valor) FROM pessoas").fetchone()[0]
        finally:
            conexao.close()
        self.assertEqual(maior, 20.0)

    def test_delete_e_negado_e_nao_executa(self):
        with self.assertRaises(sql.ErroSQL):
            sql.executar_select("DELETE FROM pessoas", caminho_db=self.caminho_db)
        self.assertEqual(self._contar("pessoas"), 3)

    def test_create_table_e_negado(self):
        with self.assertRaises(sql.ErroSQL):
            sql.executar_select(
                "CREATE TABLE nova_tabela (id INTEGER)", caminho_db=self.caminho_db
            )

    def test_drop_table_e_negado_e_nao_executa(self):
        with self.assertRaises(sql.ErroSQL):
            sql.executar_select("DROP TABLE pessoas", caminho_db=self.caminho_db)
        self.assertEqual(self._contar("pessoas"), 3)

    def test_attach_database_e_negado(self):
        caminho_outro = str(Path(self._tmp.name) / "outro.sqlite3")
        with self.assertRaises(sql.ErroSQL):
            sql.executar_select(
                f"ATTACH DATABASE '{caminho_outro}' AS outro", caminho_db=self.caminho_db
            )

    def test_pragma_e_negado(self):
        with self.assertRaises(sql.ErroSQL):
            sql.executar_select("PRAGMA table_info(pessoas)", caminho_db=self.caminho_db)

    def test_load_extension_e_negado(self):
        with self.assertRaises(sql.ErroSQL):
            sql.executar_select(
                "SELECT load_extension('qualquer')", caminho_db=self.caminho_db
            )

    # --- Allowlist de tabelas/colunas -----------------------------------

    def test_leitura_de_django_session_e_negada(self):
        with self.assertRaises(sql.ErroSQL):
            sql.executar_select(
                "SELECT * FROM django_session", caminho_db=self.caminho_db
            )

    def test_leitura_de_tabela_prefixada_axes_e_negada(self):
        with self.assertRaises(sql.ErroSQL):
            sql.executar_select(
                "SELECT * FROM axes_accesslog", caminho_db=self.caminho_db
            )

    def test_leitura_de_password_e_negada(self):
        with self.assertRaises(sql.ErroSQL):
            sql.executar_select(
                "SELECT password FROM core_usuario", caminho_db=self.caminho_db
            )

    def test_leitura_de_email_na_mesma_tabela_e_permitida(self):
        resultado = sql.executar_select(
            "SELECT email FROM core_usuario", caminho_db=self.caminho_db
        )
        self.assertEqual(resultado["linhas"], [["a@a.com"]])

    # --- Múltiplas instruções -------------------------------------------

    def test_multiplas_instrucoes_sao_recusadas(self):
        with self.assertRaises(sql.ErroSQL):
            sql.executar_select(
                "SELECT 1; DROP TABLE pessoas", caminho_db=self.caminho_db
            )
        self.assertEqual(self._contar("pessoas"), 3)

    # --- Timeout ----------------------------------------------------------

    def test_consulta_lenta_e_abortada_por_timeout(self):
        with self.assertRaises(sql.ErroSQL) as contexto:
            sql.executar_select(
                "WITH RECURSIVE cnt(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM cnt) "
                "SELECT x FROM cnt",
                caminho_db=self.caminho_db,
                timeout_s=0.05,
                max_linhas=50_000_000,
            )
        self.assertIn("tempo limite", contexto.exception.mensagem)

    # --- Corte por linhas e por bytes -------------------------------------

    def test_corte_por_max_linhas(self):
        resultado = sql.executar_select(
            "SELECT id FROM muitas_linhas ORDER BY id", caminho_db=self.caminho_db
        )
        self.assertEqual(resultado["total_linhas"], 200)
        self.assertEqual(len(resultado["linhas"]), 200)
        self.assertTrue(resultado["truncado"])

    def test_corte_por_teto_bytes(self):
        resultado = sql.executar_select(
            "SELECT texto FROM textao", caminho_db=self.caminho_db, teto_bytes=200
        )
        self.assertTrue(resultado["truncado"])
        self.assertLess(len(resultado["linhas"]), 5)

    # --- Erro de sintaxe legível -------------------------------------------

    def test_erro_de_sintaxe_e_legivel_em_pt_br(self):
        with self.assertRaises(sql.ErroSQL) as contexto:
            sql.executar_select("SELCT 1", caminho_db=self.caminho_db)
        mensagem = contexto.exception.mensagem
        self.assertIn("syntax error", mensagem)
        self.assertNotEqual(mensagem, "erro ao executar a consulta")
