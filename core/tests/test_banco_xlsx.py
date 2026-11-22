"""Núcleo puro de exportar/importar o banco em XLSX."""

from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from openpyxl import load_workbook

from apps.catalogo.models import (
    Categoria,
    Classificacao,
    Exercicio,
    GrauPrioridade,
    InstrumentoContratual,
    Modalidade,
    SituacaoNormalizada,
    Tipo,
    Unidade,
)
from apps.pca.models import (
    Acompanhamento,
    Estado,
    HistoricalProcesso,
    Processo,
    Situacao,
    TipoEvento,
)
from core import banco_xlsx
from core.models import Usuario
from core.views_banco import CHAVE_SESSAO_UPLOAD_PENDENTE

CONTENT_TYPE_XLSX = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


class ToposortTests(TestCase):
    """`_toposort` é Kahn puro — testável com um grafo sintético, sem
    Django nenhum envolvido."""

    def test_ordenar_por_dependencia_com_grafo_sintetico(self):
        a, b, c, d = "A", "B", "C", "D"
        grafo = {d: {b, c}, c: {a}, b: {a}, a: set()}

        ordenados = banco_xlsx._toposort(grafo)

        self.assertEqual(set(ordenados), {a, b, c, d})
        posicoes = {no: indice for indice, no in enumerate(ordenados)}
        self.assertLess(posicoes[a], posicoes[b])
        self.assertLess(posicoes[a], posicoes[c])
        self.assertLess(posicoes[b], posicoes[d])
        self.assertLess(posicoes[c], posicoes[d])

    def test_toposort_recusa_grafo_com_ciclo(self):
        grafo = {"x": {"y"}, "y": {"x"}}
        with self.assertRaises(ValueError):
            banco_xlsx._toposort(grafo)


class ModelosIncluidosTests(TestCase):
    def test_modelos_incluidos_tem_18_entradas(self):
        self.assertEqual(len(banco_xlsx.MODELOS_INCLUIDOS), 18)

    def test_modelos_incluidos_bate_ordem_esperada_de_fk(self):
        posicoes = {
            modelo: indice for indice, modelo in enumerate(banco_xlsx.MODELOS_INCLUIDOS)
        }
        for modelo in banco_xlsx.MODELOS_INCLUIDOS:
            for campo in modelo._meta.get_fields():
                if not hasattr(campo, "related_model") or not getattr(
                    campo, "many_to_one", False
                ):
                    continue
                if campo.model is not modelo:
                    continue
                destino = campo.related_model
                if destino is modelo or destino not in posicoes:
                    continue
                self.assertLess(
                    posicoes[destino],
                    posicoes[modelo],
                    f"{destino.__name__} deveria vir antes de {modelo.__name__}",
                )


class BancoXlsxTestCase(TestCase):
    """Fixtures compartilhadas de catálogo/usuário para os testes do
    núcleo puro."""

    @classmethod
    def setUpTestData(cls):
        cls.exercicio = Exercicio.objects.get(ano=2026)
        cls.unidade = Unidade.objects.create(nome="Presidência")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.tipo = Tipo.objects.create(nome="Aquisição")
        cls.grau_prioridade = GrauPrioridade.objects.create(nome="Alta")
        cls.classificacao = Classificacao.objects.create(nome="Contínuo")
        cls.modalidade = Modalidade.objects.create(nome="Pregão")
        cls.instrumento_contratual = InstrumentoContratual.objects.create(nome="Contrato")
        cls.situacao_normalizada = SituacaoNormalizada.objects.create(nome="No prazo")
        cls.superuser = Usuario.objects.create_superuser(
            email="admin@example.com", password="senha-segura",
        )

    def _criar_processo(self, item_pca, **extra):
        valores = dict(
            item_pca=item_pca,
            descricao_objeto=f"Objeto do item {item_pca}",
            justificativa="",
            tipo=self.tipo,
            categoria=self.categoria,
            unidade_organizacional=self.unidade,
            exercicio=self.exercicio,
            valor_estimado=Decimal("162642475.66"),
            mes_previsto=3,
            data_inclusao_pca=date(2026, 1, 15),
            grau_prioridade=self.grau_prioridade,
            classificacao=self.classificacao,
            estado=Estado.ATIVO.value,
            situacao=Situacao.NO_PRAZO.value,
        )
        valores.update(extra)
        return Processo.objects.create(**valores)

    def _linha_de_instancia(self, modelo, instancia):
        """Dict `{attname: valor}` para todos os campos de `campos_modelo`,
        lidos direto da instância — usado para montar linhas de teste sem
        repetir o schema inteiro à mão."""
        return {
            campo.attname: getattr(instancia, campo.attname)
            for campo in banco_xlsx.campos_modelo(modelo)
        }

    def _exportar(self):
        return banco_xlsx.exportar_banco_xlsx()

    def _editar_celula(self, buffer_exportado, aba, coluna_chave, valor_chave, coluna, novo_valor):
        buffer_exportado.seek(0)
        livro = load_workbook(buffer_exportado)
        ws = livro[aba]
        cabecalho = [celula.value for celula in ws[1]]
        indice_chave = cabecalho.index(coluna_chave)
        indice_coluna = cabecalho.index(coluna)
        encontrado = False
        for linha in ws.iter_rows(min_row=2):
            if linha[indice_chave].value == valor_chave:
                linha[indice_coluna].value = novo_valor
                encontrado = True
                break
        self.assertTrue(encontrado, f"linha {valor_chave} não encontrada em {aba}")
        novo_buffer = BytesIO()
        livro.save(novo_buffer)
        novo_buffer.seek(0)
        return novo_buffer


class ExportarBancoXlsxTests(BancoXlsxTestCase):
    def test_exportar_contem_todas_as_abas_e_leia_me(self):
        self._criar_processo(item_pca=1)

        buffer = self._exportar()
        livro = load_workbook(buffer)

        self.assertEqual(livro.sheetnames[0], "_leia-me")
        self.assertEqual(len(livro.sheetnames), 19)
        for modelo in banco_xlsx.MODELOS_INCLUIDOS:
            self.assertIn(banco_xlsx.nome_aba(modelo), livro.sheetnames)

    def test_password_e_last_login_fora_do_cabecalho_de_usuario(self):
        buffer = self._exportar()
        livro = load_workbook(buffer)

        ws = livro["core.Usuario"]
        cabecalho = [celula.value for celula in ws[1]]

        self.assertNotIn("password", cabecalho)
        self.assertNotIn("last_login", cabecalho)


class RoundTripTests(BancoXlsxTestCase):
    def test_round_trip_sem_edicao_produz_relatorio_vazio(self):
        self._criar_processo(item_pca=1)
        processo2 = self._criar_processo(item_pca=2)
        Acompanhamento.objects.create(
            processo=processo2,
            referencia_data=date(2026, 2, 1),
            origem_hash="hash-teste-1",
            tipo_evento=TipoEvento.AUTOMATICO,
            situacao=self.situacao_normalizada,
        )

        buffer = self._exportar()
        buffer.seek(0)
        dados = banco_xlsx.ler_planilha_banco(buffer)
        relatorio = banco_xlsx.calcular_relatorio(dados)

        for aba in relatorio.abas:
            with self.subTest(aba=aba.nome):
                self.assertEqual(aba.novos, [])
                self.assertEqual(aba.alterados, [])
                self.assertEqual(aba.erros, [])
                self.assertEqual(aba.ignorados, aba.lidas)
        self.assertFalse(relatorio.tem_erros)

    def test_editar_uma_celula_de_processo_produz_um_alterado(self):
        processo = self._criar_processo(item_pca=1)

        buffer = self._exportar()
        editado = self._editar_celula(
            buffer, "pca.Processo", "id", processo.pk,
            "descricao_objeto", "Objeto editado no Excel",
        )
        dados = banco_xlsx.ler_planilha_banco(editado)
        relatorio = banco_xlsx.calcular_relatorio(dados)

        aba_processo = next(a for a in relatorio.abas if a.nome == "pca.Processo")
        self.assertEqual(len(aba_processo.alterados), 1)
        alterado = aba_processo.alterados[0]
        self.assertEqual(alterado.pk, processo.pk)
        self.assertEqual(len(alterado.diferencas), 1)
        diferenca = alterado.diferencas[0]
        self.assertEqual(diferenca.campo, "descricao_objeto")
        self.assertEqual(diferenca.antigo, processo.descricao_objeto)
        self.assertEqual(diferenca.novo, "Objeto editado no Excel")

        outras_abas_com_diff = [
            a.nome for a in relatorio.abas if a.nome != "pca.Processo" and a.alterados
        ]
        self.assertEqual(outras_abas_com_diff, [])
        self.assertFalse(relatorio.tem_erros)


class LinhaNovaTests(BancoXlsxTestCase):
    def test_linha_nova_com_pk_vazio_em_unidade_vira_novo(self):
        dados = {
            Unidade: [
                {"id": None, "nome": "Nova Unidade Importada", "nome_normalizado": None},
            ]
        }

        relatorio = banco_xlsx.calcular_relatorio(dados)

        aba_unidade = next(a for a in relatorio.abas if a.nome == "catalogo.Unidade")
        self.assertEqual(len(aba_unidade.novos), 1)
        self.assertEqual(aba_unidade.erros, [])
        self.assertFalse(relatorio.tem_erros)


class FkInexistenteTests(BancoXlsxTestCase):
    def test_fk_inexistente_vira_erro_e_bloqueia_confirmacao(self):
        processo = self._criar_processo(item_pca=1)
        linha = self._linha_de_instancia(Processo, processo)
        linha["id"] = None
        linha["item_pca"] = 2
        linha["unidade_organizacional_id"] = 999999

        relatorio = banco_xlsx.calcular_relatorio({Processo: [linha]})

        aba_processo = next(a for a in relatorio.abas if a.nome == "pca.Processo")
        self.assertTrue(relatorio.tem_erros)
        self.assertEqual(len(aba_processo.erros), 1)
        self.assertEqual(aba_processo.erros[0].coluna, "unidade_organizacional")
        self.assertEqual(aba_processo.novos, [])


class AplicarRelatorioTests(BancoXlsxTestCase):
    def test_aplicar_relatorio_grava_historico_com_usuario_e_motivo(self):
        processo = self._criar_processo(item_pca=1)
        linha = self._linha_de_instancia(Processo, processo)
        linha["descricao_objeto"] = "Objeto alterado pela importação"

        resultado = banco_xlsx.aplicar_relatorio({Processo: [linha]}, self.superuser)

        self.assertEqual(resultado[Processo], {"criados": 0, "atualizados": 1})
        processo.refresh_from_db()
        self.assertEqual(processo.descricao_objeto, "Objeto alterado pela importação")

        historico = HistoricalProcesso.objects.filter(id=processo.pk).order_by("-history_date").first()
        self.assertIsNotNone(historico)
        self.assertEqual(historico.history_user_id, self.superuser.pk)
        self.assertEqual(historico.history_change_reason, "Importação XLSX do banco")

    def test_aplicar_relatorio_processo_origem_autofk_em_duas_passagens(self):
        base = self._criar_processo(item_pca=1)
        linha_base = self._linha_de_instancia(Processo, base)
        linha_base["id"] = 5001
        linha_base["item_pca"] = 501
        linha_base["origem_id"] = 5002

        linha_derivada = self._linha_de_instancia(Processo, base)
        linha_derivada["id"] = 5002
        linha_derivada["item_pca"] = 502
        linha_derivada["origem_id"] = None

        banco_xlsx.aplicar_relatorio(
            {Processo: [linha_base, linha_derivada]}, self.superuser
        )

        processo_base = Processo.objects.get(pk=5001)
        processo_derivada = Processo.objects.get(pk=5002)
        self.assertEqual(processo_base.origem_id, 5002)
        self.assertIsNone(processo_derivada.origem_id)

    def test_password_nunca_e_escrito_mesmo_se_coluna_presente(self):
        usuario = Usuario.objects.create_user(
            email="alguem@example.com", password="senha-original",
        )
        hash_original = usuario.password
        linha = self._linha_de_instancia(Usuario, usuario)
        linha["password"] = "pbkdf2_sha256$fake$hash$forjado"
        linha["first_name"] = "Alguém Editado"

        banco_xlsx.aplicar_relatorio({Usuario: [linha]}, self.superuser)

        usuario.refresh_from_db()
        self.assertEqual(usuario.password, hash_original)
        self.assertEqual(usuario.first_name, "Alguém Editado")


class BackupSqliteTests(TransactionTestCase):
    """`TransactionTestCase` (não `TestCase`): `TestCase` embrulha cada
    teste numa transação externa que nunca comita — `sqlite3.Connection.
    backup()` fica retentando `SQLITE_BUSY` para sempre contra a própria
    conexão em transação aberta. No fluxo real, `confirmar_view` chama
    `fazer_backup_sqlite()` ANTES de abrir `transaction.atomic()`,
    então esse impasse nunca acontece fora de teste.

    `serialized_rollback = True`: sem isso, o `flush` do teardown desta
    classe reexecuta `post_migrate` (recria `ContentType`/grupos padrão do
    zero) sem restaurar os dados semeados por `RunPython` das migrações
    (`Exercicio(ano=2026)`, `ProcessoAlocador(chave=1)`) — o próximo
    `TransactionTestCase` do módulo (`BancoXlsxConfirmarViaHttpTests`),
    que RESTAURA o snapshot serializado original, então tenta inserir
    `ContentType` que o `post_migrate` anterior já recriou, batendo no
    `UNIQUE constraint` de `(app_label, model)`."""

    serialized_rollback = True

    def tearDown(self):
        for caminho in getattr(self, "_backups_criados", []):
            Path(caminho).unlink(missing_ok=True)

    def test_fazer_backup_sqlite_cria_arquivo(self):
        self._backups_criados = []
        caminho = banco_xlsx.fazer_backup_sqlite()
        if caminho is None:
            self.skipTest("Banco de teste não é SQLite.")
        self._backups_criados.append(caminho)

        self.assertTrue(caminho.is_file())
        self.assertGreater(caminho.stat().st_size, 0)


class _FixturasHttp:
    """Fixtures leves e comuns aos testes HTTP de `setUp` normal
    (não `setUpTestData`) porque a mesma mixin serve tanto `TestCase`
    quanto `TransactionTestCase`."""

    def setUp(self):
        self.exercicio = Exercicio.objects.get(ano=2026)
        self.unidade = Unidade.objects.create(nome="Presidência HTTP")
        self.categoria = Categoria.objects.create(nome="Serviços HTTP")
        self.tipo = Tipo.objects.create(nome="Aquisição HTTP")
        self.superuser = Usuario.objects.create_superuser(
            email="admin-http@example.com", password="senha-segura",
        )
        self.staff = Usuario.objects.create_user(
            email="staff-http@example.com", password="senha-segura", is_staff=True,
        )
        self.client = Client()

    def _processo(self, item_pca=1, **extra):
        valores = dict(
            item_pca=item_pca,
            descricao_objeto="Objeto HTTP",
            justificativa="",
            tipo=self.tipo,
            categoria=self.categoria,
            unidade_organizacional=self.unidade,
            exercicio=self.exercicio,
        )
        valores.update(extra)
        return Processo.objects.create(**valores)

    def _arquivo(self, conteudo):
        return SimpleUploadedFile("banco.xlsx", conteudo, content_type=CONTENT_TYPE_XLSX)


@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False)
class BancoXlsxAcessoTests(_FixturasHttp, TestCase):
    def test_usuario_sem_superuser_nunca_alcanca_as_tres_urls(self):
        # Mesmo padrão de `apps/pca/tests/test_import_admin.py::
        # test_staff_sem_superuser_nunca_alcanca_o_importador`: o gate de
        # site (`PcaAdminSite.has_permission`) intercepta ANTES da
        # view via `AdminSite.admin_view()` e redireciona para o login
        # (302) — só chegaria a 403 (`_exigir_superuser`, defesa em
        # profundidade local) se a view fosse alcançável por outro
        # caminho. As duas saídas contam como "não alcançou".
        self.client.force_login(self.staff)

        self.assertIn(
            self.client.get(reverse("admin:banco_exportar")).status_code, (302, 403)
        )
        self.assertIn(
            self.client.get(reverse("admin:banco_importar")).status_code, (302, 403)
        )
        self.assertIn(
            self.client.post(
                reverse("admin:banco_confirmar"), {"referencia": "a" * 43}
            ).status_code,
            (302, 403),
        )

    def test_exportar_via_http_devolve_xlsx_com_content_type_correto(self):
        self.client.force_login(self.superuser)

        resposta = self.client.get(reverse("admin:banco_exportar"))

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta["Content-Type"], CONTENT_TYPE_XLSX)
        self.assertIn("attachment", resposta["Content-Disposition"])

    def test_indice_do_admin_mostra_os_dois_links_para_superuser(self):
        self.client.force_login(self.superuser)

        resposta = self.client.get("/admin/")

        bloco = next(
            (app for app in resposta.context["app_list"] if app["name"] == "Banco de dados"),
            None,
        )
        self.assertIsNotNone(bloco)
        nomes = {modelo["name"] for modelo in bloco["models"]}
        self.assertEqual(nomes, {"Exportar banco (XLSX)", "Importar banco (XLSX)"})


@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False)
class BancoXlsxFluxoRelatorioTests(_FixturasHttp, TestCase):
    def test_fluxo_completo_sem_edicao_relatorio_zero_e_botao_confirmar_presente(self):
        self._processo()
        self.client.force_login(self.superuser)
        buffer = banco_xlsx.exportar_banco_xlsx()

        resposta = self.client.post(
            reverse("admin:banco_importar"), {"arquivo": self._arquivo(buffer.getvalue())}
        )

        self.assertTemplateUsed(resposta, "admin/banco/relatorio.html")
        self.assertContains(resposta, "Confirmar e gravar")

    def test_fluxo_com_erro_nao_mostra_botao_confirmar_e_post_direto_ao_confirmar_e_recusado(self):
        processo = self._processo()
        self.client.force_login(self.superuser)

        buffer = banco_xlsx.exportar_banco_xlsx()
        buffer.seek(0)
        livro = load_workbook(buffer)
        ws = livro["pca.Processo"]
        cabecalho = [celula.value for celula in ws[1]]
        indice_pk = cabecalho.index("id")
        indice_uo = cabecalho.index("unidade_organizacional_id")
        for linha in ws.iter_rows(min_row=2):
            if linha[indice_pk].value == processo.pk:
                linha[indice_uo].value = 999999
                break
        saida = BytesIO()
        livro.save(saida)

        resposta = self.client.post(
            reverse("admin:banco_importar"), {"arquivo": self._arquivo(saida.getvalue())}
        )

        self.assertTemplateUsed(resposta, "admin/banco/relatorio.html")
        self.assertNotContains(resposta, "Confirmar e gravar")

        referencia = self.client.session[CHAVE_SESSAO_UPLOAD_PENDENTE]["referencia"]
        resposta_confirmar = self.client.post(
            reverse("admin:banco_confirmar"), {"referencia": referencia}
        )

        self.assertEqual(resposta_confirmar.status_code, 302)
        processo.refresh_from_db()
        self.assertEqual(processo.unidade_organizacional_id, self.unidade.pk)


@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False)
class BancoXlsxConfirmarViaHttpTests(_FixturasHttp, TransactionTestCase):
    """`TransactionTestCase`: `confirmar_view` chama `fazer_backup_sqlite()`
    antes de `transaction.atomic()` — a mesma razão de `BackupSqliteTests`
    acima, `TestCase` embrulharia a requisição inteira numa transação
    externa que nunca comita."""

    serialized_rollback = True

    def _importar_e_confirmar(self, conteudo):
        self.client.force_login(self.superuser)
        resposta = self.client.post(
            reverse("admin:banco_importar"), {"arquivo": self._arquivo(conteudo)}
        )
        self.assertContains(resposta, "Confirmar e gravar")
        referencia = self.client.session[CHAVE_SESSAO_UPLOAD_PENDENTE]["referencia"]
        return self.client.post(reverse("admin:banco_confirmar"), {"referencia": referencia})

    def test_editar_processo_via_http_aplica_e_grava_historico_com_superuser(self):
        processo = self._processo()
        buffer = banco_xlsx.exportar_banco_xlsx()
        buffer.seek(0)
        livro = load_workbook(buffer)
        ws = livro["pca.Processo"]
        cabecalho = [celula.value for celula in ws[1]]
        indice_pk = cabecalho.index("id")
        indice_descricao = cabecalho.index("descricao_objeto")
        for linha in ws.iter_rows(min_row=2):
            if linha[indice_pk].value == processo.pk:
                linha[indice_descricao].value = "Objeto editado via HTTP"
                break
        saida = BytesIO()
        livro.save(saida)

        resposta = self._importar_e_confirmar(saida.getvalue())

        self.assertEqual(resposta.status_code, 302)
        processo.refresh_from_db()
        self.assertEqual(processo.descricao_objeto, "Objeto editado via HTTP")
        historico = (
            HistoricalProcesso.objects.filter(id=processo.pk)
            .order_by("-history_date")
            .first()
        )
        self.assertIsNotNone(historico)
        self.assertEqual(historico.history_user_id, self.superuser.pk)

    def test_password_no_arquivo_nao_muda_hash_apos_confirmar_via_http(self):
        usuario = Usuario.objects.create_user(
            email="alguem-http@example.com", password="senha-original-http",
        )
        hash_original = usuario.password
        buffer = banco_xlsx.exportar_banco_xlsx()
        buffer.seek(0)
        livro = load_workbook(buffer)
        ws = livro["core.Usuario"]
        cabecalho = [celula.value for celula in ws[1]]
        self.assertNotIn("password", cabecalho)
        indice_pk = cabecalho.index("id")
        indice_nome = cabecalho.index("first_name")
        for linha in ws.iter_rows(min_row=2):
            if linha[indice_pk].value == usuario.pk:
                linha[indice_nome].value = "Alguém via HTTP"
                break
        saida = BytesIO()
        livro.save(saida)

        resposta = self._importar_e_confirmar(saida.getvalue())

        self.assertEqual(resposta.status_code, 302)
        usuario.refresh_from_db()
        self.assertEqual(usuario.password, hash_original)
        self.assertEqual(usuario.first_name, "Alguém via HTTP")

    def test_backup_e_criado_apos_confirmar_via_http(self):
        from django.db import connection

        self._processo()
        buffer = banco_xlsx.exportar_banco_xlsx()

        diretorio_backups = Path(connection.settings_dict["NAME"]).parent / "backups"
        antes = (
            set(diretorio_backups.glob("pre-import-*.sqlite3"))
            if diretorio_backups.is_dir()
            else set()
        )

        resposta = self._importar_e_confirmar(buffer.getvalue())

        self.assertEqual(resposta.status_code, 302)
        depois = set(diretorio_backups.glob("pre-import-*.sqlite3"))
        novos = depois - antes
        self.assertEqual(len(novos), 1)
        caminho_novo = novos.pop()
        self.assertGreater(caminho_novo.stat().st_size, 0)
        caminho_novo.unlink(missing_ok=True)
