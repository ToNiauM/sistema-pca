"""Comando `importar_solicitantes`: contas dos solicitantes a partir da planilha."""

import csv
import os
import stat
import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock

import openpyxl
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.catalogo.models import Unidade
from apps.solicitacoes.models import VinculoUnidade

MODULO = "apps.solicitacoes.management.commands.importar_solicitantes"
Usuario = get_user_model()


class ImportarSolicitantesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = Unidade.objects.create(nome="Gerência A")
        cls.b = Unidade.objects.create(nome="Gerência B")
        cls.c = Unidade.objects.create(nome="Controladoria")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.saida = self.dir / "senhas.csv"

    # -- apoio ------------------------------------------------------------------------------

    def csv(self, linhas, nome="solicitantes.csv", delimitador=","):
        caminho = self.dir / nome
        with open(caminho, "w", encoding="utf-8", newline="") as arquivo:
            escritor = csv.writer(arquivo, delimiter=delimitador, quoting=csv.QUOTE_MINIMAL)
            escritor.writerow(["nome", "e-mail", "unidades"])
            escritor.writerows(linhas)
        return caminho

    def xlsx(self, linhas, nome="solicitantes.xlsx"):
        pasta = openpyxl.Workbook()
        folha = pasta.active
        folha.append(["Nome", "E-mail", "Unidades"])
        for linha in linhas:
            folha.append(linha)
        caminho = self.dir / nome
        pasta.save(caminho)
        return caminho

    def rodar(self, planilha, *args, com_saida=True):
        saida, erro = StringIO(), StringIO()
        extra = ["--saida", str(self.saida)] if com_saida else []
        call_command("importar_solicitantes", str(planilha), *extra, *args, stdout=saida, stderr=erro)
        return saida.getvalue() + erro.getvalue()

    def senhas(self):
        with open(self.saida, encoding="utf-8", newline="") as arquivo:
            return {linha["e-mail"]: linha["senha provisória"] for linha in csv.DictReader(arquivo)}

    # -- criação ---------------------------------------------------------------------------------

    def test_cria_usuarios_no_grupo_com_vinculos_senha_aleatoria_e_troca_obrigatoria(self):
        planilha = self.csv([
            ["Ana Maria Souza", "ana@cfc.example", "Gerência A;Gerência B"],
            ["Bruno Lima", "Bruno@CFC.example", "Controladoria"],
        ])
        with self.assertNoLogs(level="DEBUG"):
            texto = self.rodar(planilha)

        ana = Usuario.objects.get(email="ana@cfc.example")
        bruno = Usuario.objects.get(email="bruno@cfc.example")
        self.assertEqual((ana.first_name, ana.last_name), ("Ana", "Maria Souza"))
        for usuario in (ana, bruno):
            self.assertTrue(usuario.senha_temporaria)
            self.assertEqual(list(usuario.groups.values_list("name", flat=True)), ["solicitante"])
            self.assertTrue(usuario.is_active)
            self.assertFalse(usuario.is_staff or usuario.is_superuser)
        self.assertEqual(set(ana.vinculos_unidade.values_list("unidade", flat=True)), {self.a.pk, self.b.pk})
        self.assertEqual(set(bruno.vinculos_unidade.values_list("unidade", flat=True)), {self.c.pk})

        senhas = self.senhas()
        self.assertEqual(set(senhas), {"ana@cfc.example", "bruno@cfc.example"})
        self.assertNotEqual(senhas["ana@cfc.example"], senhas["bruno@cfc.example"])
        self.assertTrue(ana.check_password(senhas["ana@cfc.example"]))
        self.assertTrue(bruno.check_password(senhas["bruno@cfc.example"]))
        self.assertTrue(all(len(s) >= 12 for s in senhas.values()))
        self.assertIn("2 criado(s), 0 atualizado(s), 0 sem mudança.", texto)

    def test_senhas_so_no_arquivo_com_permissao_600(self):
        planilha = self.csv([["Ana Souza", "ana@cfc.example", "Gerência A"]])
        texto = self.rodar(planilha)
        senha = self.senhas()["ana@cfc.example"]
        self.assertNotIn(senha, texto)
        self.assertEqual(stat.S_IMODE(os.stat(self.saida).st_mode), 0o600)
        # O arquivo é o ÚNICO lugar: a senha também não está em nada que o ORM guarde em claro.
        self.assertFalse(Usuario.objects.filter(password__contains=senha).exists())

    def test_csv_com_ponto_e_virgula_como_delimitador_e_unidades_soltas(self):
        caminho = self.dir / "pv.csv"
        caminho.write_text(
            "nome;e-mail;unidades\nAna Souza;ana@cfc.example;Gerência A;Gerência B\n", encoding="utf-8"
        )
        self.rodar(caminho)
        ana = Usuario.objects.get(email="ana@cfc.example")
        self.assertEqual(set(ana.vinculos_unidade.values_list("unidade", flat=True)), {self.a.pk, self.b.pk})

    def test_xlsx_e_unidade_casada_sem_acento_e_sem_caixa(self):
        planilha = self.xlsx([["Ana Souza", "ana@cfc.example", "gerencia a; CONTROLADORIA"]])
        self.rodar(planilha)
        ana = Usuario.objects.get(email="ana@cfc.example")
        self.assertEqual(set(ana.vinculos_unidade.values_list("unidade", flat=True)), {self.a.pk, self.c.pk})

    def test_csv_em_latin1_e_linha_em_branco(self):
        caminho = self.dir / "latin1.csv"
        caminho.write_bytes("nome,e-mail,unidades\nJoão Pé,joao@cfc.example,Gerência A\n,,\n".encode("latin-1"))
        self.rodar(caminho)
        self.assertEqual(Usuario.objects.get(email="joao@cfc.example").first_name, "João")
        self.assertEqual(Usuario.objects.filter(groups__name="solicitante").count(), 1)

    # -- dry-run, idempotência -------------------------------------------------------------

    def test_dry_run_confere_e_nao_grava_nada(self):
        planilha = self.csv([["Ana Souza", "ana@cfc.example", "Gerência A"]])
        texto = self.rodar(planilha, "--dry-run")
        self.assertIn("Simulação (--dry-run): nada foi gravado. 1 a criar", texto)
        self.assertIn("criar — ana@cfc.example", texto)
        self.assertFalse(Usuario.objects.filter(email="ana@cfc.example").exists())
        self.assertFalse(VinculoUnidade.objects.exists())
        self.assertFalse(self.saida.exists())
        # E sem --saida também: simular não exige o arquivo.
        self.rodar(planilha, "--dry-run", com_saida=False)

    def test_dry_run_tambem_lista_os_erros(self):
        planilha = self.csv([["Ana", "ana@cfc.example", "Setor Fantasma"]])
        with self.assertRaisesMessage(CommandError, "Setor Fantasma"):
            self.rodar(planilha, "--dry-run")

    def test_idempotente_nao_gera_senha_nem_mexe_no_arquivo(self):
        planilha = self.csv([["Ana Souza", "ana@cfc.example", "Gerência A;Gerência B"]])
        self.rodar(planilha)
        hash_antes = Usuario.objects.get(email="ana@cfc.example").password
        conteudo = self.saida.read_bytes()
        vinculos = VinculoUnidade.objects.count()

        texto = self.rodar(planilha)  # mesma linha de comando, mesmo --saida (já existe)
        self.assertIn("0 criado(s), 0 atualizado(s), 1 sem mudança.", texto)
        self.assertEqual(Usuario.objects.get(email="ana@cfc.example").password, hash_antes)
        self.assertEqual(self.saida.read_bytes(), conteudo)
        self.assertEqual(VinculoUnidade.objects.count(), vinculos)
        self.assertEqual(Usuario.objects.filter(email="ana@cfc.example").count(), 1)

    def test_usuario_existente_mantem_senha_e_ganha_grupo_nome_e_vinculos_sem_perder_nada(self):
        existente = Usuario.objects.create_user(
            email="ana@cfc.example", password="Senha-Antiga-123", first_name="Ana", senha_temporaria=False
        )
        VinculoUnidade.objects.create(usuario=existente, unidade=self.c)
        hash_antes = existente.password
        planilha = self.csv([["Ana Maria Souza", "ANA@cfc.example", "Gerência A"]])

        texto = self.rodar(planilha)

        existente.refresh_from_db()
        self.assertEqual(existente.password, hash_antes)
        self.assertFalse(existente.senha_temporaria)
        self.assertEqual((existente.first_name, existente.last_name), ("Ana", "Maria Souza"))
        self.assertTrue(existente.groups.filter(name="solicitante").exists())
        # Vínculos só se somam: a Controladoria (do Admin) continua.
        self.assertEqual(set(existente.vinculos_unidade.values_list("unidade", flat=True)), {self.a.pk, self.c.pk})
        self.assertIn("0 criado(s), 1 atualizado(s), 0 sem mudança.", texto)
        self.assertFalse(self.saida.exists())  # nada novo, nenhuma senha, nenhum arquivo

    def test_usuario_inativo_nao_e_reativado(self):
        Usuario.objects.create_user(email="ana@cfc.example", password="x", first_name="Ana", is_active=False)
        texto = self.rodar(self.csv([["Ana", "ana@cfc.example", "Gerência A"]]))
        self.assertIn("usuário inativo: não reativado", texto)
        self.assertFalse(Usuario.objects.get(email="ana@cfc.example").is_active)

    # -- erros: tudo ou nada -----------------------------------------------------------------------

    def test_unidade_inexistente_lista_o_erro_e_nao_cria_nada_pela_metade(self):
        planilha = self.csv([
            ["Ana Souza", "ana@cfc.example", "Gerência A"],
            ["Bruno Lima", "bruno@cfc.example", "Gerência B;Setor Fantasma"],
        ])
        with self.assertRaises(CommandError) as ctx:
            self.rodar(planilha)
        mensagem = str(ctx.exception)
        self.assertIn("Nada foi gravado", mensagem)
        self.assertIn("Linha 3: a unidade 'Setor Fantasma' não existe no cadastro.", mensagem)
        self.assertFalse(Usuario.objects.filter(email__in=["ana@cfc.example", "bruno@cfc.example"]).exists())
        self.assertFalse(VinculoUnidade.objects.exists())
        self.assertFalse(self.saida.exists())

    def test_todos_os_erros_vem_juntos(self):
        planilha = self.csv([
            ["", "ana@cfc.example", "Gerência A"],
            ["Bruno", "isto-nao-e-email", "Gerência A"],
            ["Carla", "carla@cfc.example", ""],
            ["Carla Dois", "CARLA@cfc.example", "Gerência A"],
        ])
        with self.assertRaises(CommandError) as ctx:
            self.rodar(planilha)
        mensagem = str(ctx.exception)
        for trecho in (
            "Linha 2: falta o nome.", "Linha 3: e-mail inválido (isto-nao-e-email).",
            "Linha 4: falta ao menos uma unidade.", "Linha 5: e-mail repetido (carla@cfc.example; já na linha 4).",
        ):
            self.assertIn(trecho, mensagem)
        self.assertFalse(Usuario.objects.filter(email__endswith="@cfc.example").exists())

    def test_falha_ao_gravar_o_arquivo_desfaz_tudo(self):
        planilha = self.csv([["Ana Souza", "ana@cfc.example", "Gerência A"]])
        with mock.patch(f"{MODULO}.os.fsync", side_effect=OSError("disco cheio")):
            with self.assertRaises(CommandError):
                self.rodar(planilha)
        self.assertFalse(Usuario.objects.filter(email="ana@cfc.example").exists())
        self.assertFalse(VinculoUnidade.objects.exists())
        self.assertFalse(self.saida.exists())

    def test_cria_sem_saida_e_recusado_sem_criar_ninguem(self):
        planilha = self.csv([["Ana Souza", "ana@cfc.example", "Gerência A"]])
        with self.assertRaisesMessage(CommandError, "informe --saida"):
            self.rodar(planilha, com_saida=False)
        self.assertFalse(Usuario.objects.filter(email="ana@cfc.example").exists())

    def test_saida_nunca_sobrescreve_nem_fica_dentro_do_projeto_nem_em_diretorio_inexistente(self):
        planilha = self.csv([["Ana Souza", "ana@cfc.example", "Gerência A"]])
        self.saida.write_text("importante", encoding="utf-8")
        with self.assertRaisesMessage(CommandError, "já existe"):
            self.rodar(planilha)
        self.assertEqual(self.saida.read_text(encoding="utf-8"), "importante")

        for destino, trecho in (
            (Path(settings.BASE_DIR) / "senhas-teste.csv", "FORA da árvore do projeto"),
            (self.dir / "nao-existe" / "senhas.csv", "não existe"),
        ):
            with self.subTest(destino=str(destino)):
                with self.assertRaisesMessage(CommandError, trecho):
                    call_command("importar_solicitantes", str(planilha), "--saida", str(destino), stdout=StringIO())
        self.assertFalse((Path(settings.BASE_DIR) / "senhas-teste.csv").exists())
        self.assertFalse(Usuario.objects.filter(email="ana@cfc.example").exists())

    def test_planilha_sem_coluna_formato_invalido_e_arquivo_inexistente(self):
        sem_coluna = self.dir / "sem-coluna.csv"
        sem_coluna.write_text("nome,e-mail\nAna,ana@cfc.example\n", encoding="utf-8")
        with self.assertRaisesMessage(CommandError, "Falta a coluna 'unidades'"):
            self.rodar(sem_coluna)
        pdf = self.dir / "x.pdf"
        pdf.write_bytes(b"%PDF")
        with self.assertRaisesMessage(CommandError, "Formato não suportado"):
            self.rodar(pdf)
        with self.assertRaises(CommandError):
            self.rodar(self.dir / "nao-existe.csv")
        falso_xlsx = self.dir / "falso.xlsx"
        falso_xlsx.write_text("não sou um zip", encoding="utf-8")
        with self.assertRaisesMessage(CommandError, "Não consegui abrir a planilha"):
            self.rodar(falso_xlsx)
