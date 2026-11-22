"""Fase 39 — endurecimento operacional ((7)):
`makemigrations --check`, isolamento do assistente em relação a backup/
export/import do PCA, `.gitignore`, `GUNICORN_TIMEOUT` parametrizado e
desempenho sem N+1 (50/500 processos) por ferramenta."""

from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext

from apps.assistente import ferramentas
from apps.assistente.tests.base import AssistenteTestBase
from apps.catalogo.models import Categoria, Exercicio, Tipo, Unidade
from apps.pca.models import Processo

_RAIZ = Path(__file__).resolve().parents[3]


class TestMakemigrationsLimpo(TestCase):
    def test_makemigrations_check_dry_run_sem_mudancas(self):
        saida = StringIO()
        try:
            call_command(
                "makemigrations", "--check", "--dry-run", stdout=saida, stderr=saida
            )
        except SystemExit as exc:
            self.fail(f"makemigrations --check encontrou mudanças pendentes: {saida.getvalue()} ({exc})")


class TestBackupExportImportIsoladosDoAssistente(SimpleTestCase):
    """(b)/(c) — o backup do PCA e o export/import de planilha nunca leem/
    escrevem os auxiliares do assistente."""

    def test_backup_sh_copia_so_o_banco_pca_sem_mencionar_ia(self):
        conteudo = (_RAIZ / "ops" / "backup" / "backup.sh").read_text(encoding="utf-8")
        self.assertIn("SQLITE_NO_CONTAINER", conteudo)
        self.assertIn("db.sqlite3", conteudo)
        linhas_uteis = [
            linha for linha in conteudo.splitlines() if not linha.strip().startswith("#")
        ]
        self.assertEqual(sum("ia/" in linha for linha in linhas_uteis), 0)

    def test_modulos_de_exportacao_e_importacao_nao_citam_ia(self):
        modulos = [
            _RAIZ / "apps" / "pca" / "exportacao.py",
            _RAIZ / "apps" / "pca" / "exportacao_fluxo.py",
            _RAIZ / "apps" / "pca" / "exportacao_resumo_uo.py",
            _RAIZ / "apps" / "pca" / "importacao" / "executor.py",
            _RAIZ / "apps" / "pca" / "importacao" / "views.py",
            _RAIZ / "apps" / "pca" / "importacao" / "parsers.py",
        ]
        for modulo in modulos:
            with self.subTest(modulo=str(modulo)):
                conteudo = modulo.read_text(encoding="utf-8")
                linhas_uteis = [
                    linha for linha in conteudo.splitlines() if not linha.strip().startswith("#")
                ]
                self.assertEqual(
                    sum("IA_" in linha for linha in linhas_uteis), 0, f"{modulo} cita IA_*"
                )


class TestGitignoreEGunicornTimeout(SimpleTestCase):
    def test_gitignore_ignora_data_ia(self):
        conteudo = (_RAIZ / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("data/ia/", conteudo)

    def test_entrypoint_continua_com_gunicorn_timeout_parametrizado(self):
        conteudo = (_RAIZ / "entrypoint.sh").read_text(encoding="utf-8")
        self.assertIn("GUNICORN_TIMEOUT", conteudo)

    def test_env_example_documenta_gunicorn_timeout_150(self):
        conteudo = (_RAIZ / ".env.example").read_text(encoding="utf-8")
        self.assertIn("GUNICORN_TIMEOUT=150", conteudo)


class TestDesempenhoSemNMaisUm(AssistenteTestBase):
    """(f) — `consultar_processos` já tem cobertura própria (`test_
    ferramentas_processos.py::test_assert_num_queries_constante_entre_
    50_e_500`); aqui ficam `ficha`/`fluxo_de_caixa`/`contratos_a_vencer`,
    os três que ainda não tinham a comparação 50 vs. 500. Tetos medidos
    nesta fatia (registrados no SUMMARY, não prometidos como "6 para
    tudo"): `ficha` seu próprio teto já é ≤5 (39-02); `fluxo_de_caixa`/
    `contratos_a_vencer` já tinham teto ≤5/≤6 (39-03) — aqui provamos que
    o teto não CRESCE de 50 para 500 processos no exercício."""

    def setUp(self):
        super().setUp()
        self.gecont, _ = Unidade.objects.get_or_create(nome="Gecont")
        self.exercicio = Exercicio.objects.get(ano=2026)
        self.tipo = Tipo.objects.first()
        self.categoria = Categoria.objects.first()

    def _criar_lote(self, quantidade, inicio):
        objetos = [
            Processo(
                item_pca=inicio + i,
                exercicio=self.exercicio,
                descricao_objeto=f"Objeto sintético {inicio + i}",
                tipo=self.tipo,
                categoria=self.categoria,
                unidade_organizacional=self.gecont,
            )
            for i in range(quantidade)
        ]
        Processo.objects.bulk_create(objetos)

    def _proximo_item(self):
        maior = Processo.objects.filter(exercicio=self.exercicio).order_by("-item_pca").first()
        return (maior.item_pca if maior else 0) + 1

    def test_ficha_constante_entre_50_e_500_processos_no_exercicio(self):
        # `ficha` busca UM item por chave — a prova aqui é que o total de
        # processos no exercício não vaza para o número de consultas.
        proximo = self._proximo_item()
        self._criar_lote(50, proximo)
        self.dirigente.has_perm("pca.ver_analises")
        with CaptureQueriesContext(connection) as com_50:
            ferramentas.ficha(self.dirigente, exercicio=2026, item=42)
        n_com_50 = len(com_50.captured_queries)

        self._criar_lote(450, proximo + 50)
        with CaptureQueriesContext(connection) as com_500:
            ferramentas.ficha(self.dirigente, exercicio=2026, item=42)
        n_com_500 = len(com_500.captured_queries)

        self.assertEqual(n_com_50, n_com_500)
        self.assertLessEqual(n_com_500, 5)

    def test_fluxo_de_caixa_constante_entre_50_e_500_processos(self):
        proximo = self._proximo_item()
        self.dirigente.has_perm("pca.ver_analises")

        self._criar_lote(50, proximo)
        with CaptureQueriesContext(connection) as com_50:
            ferramentas.fluxo_de_caixa(self.dirigente, exercicio=2026)
        n_com_50 = len(com_50.captured_queries)

        self._criar_lote(450, proximo + 50)
        with CaptureQueriesContext(connection) as com_500:
            ferramentas.fluxo_de_caixa(self.dirigente, exercicio=2026)
        n_com_500 = len(com_500.captured_queries)

        self.assertEqual(n_com_50, n_com_500)
        self.assertLessEqual(n_com_500, 5)

    def test_contratos_a_vencer_constante_entre_50_e_500_processos(self):
        proximo = self._proximo_item()
        self.dirigente.has_perm("pca.ver_analises")
        self.dirigente.has_perm("pca.view_acompanhamento")

        self._criar_lote(50, proximo)
        with CaptureQueriesContext(connection) as com_50:
            ferramentas.contratos_a_vencer(self.dirigente, exercicio=2026)
        n_com_50 = len(com_50.captured_queries)

        self._criar_lote(450, proximo + 50)
        with CaptureQueriesContext(connection) as com_500:
            ferramentas.contratos_a_vencer(self.dirigente, exercicio=2026)
        n_com_500 = len(com_500.captured_queries)

        self.assertEqual(n_com_50, n_com_500)
        self.assertLessEqual(n_com_500, 6)
