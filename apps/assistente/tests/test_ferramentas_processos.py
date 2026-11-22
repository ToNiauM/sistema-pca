"""`consultar_processos`/`executar` (A17): paridade com
a tela Processos, truncamento, desambiguação de unidade, erros de
argumento/exercício/situação, `assertNumQueries` constante entre 50 e 500
processos."""

import json

from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.db import connection

from apps.assistente import ferramentas
from apps.assistente.tests.base import AssistenteTestBase
from apps.catalogo.models import Categoria, Tipo, Unidade
from apps.pca.models import Estado, Processo, Situacao


class TestConsultarProcessos(AssistenteTestBase):
    def setUp(self):
        super().setUp()
        self.gecont, _ = Unidade.objects.get_or_create(nome="Gecont")

    def test_paridade_total_com_para_listagem(self):
        # Marca um processo real como Gecont/atrasado para o teste ter dado.
        processo = Processo.objects.filter(exercicio__ano=2026).first()
        processo.unidade_organizacional = self.gecont
        processo.situacao = Situacao.NO_PRAZO
        from datetime import timedelta

        from django.utils.timezone import localdate

        processo.prazo_entrega = localdate() - timedelta(days=5)
        processo.data_recebimento_gelic = None
        processo.save()

        envelope = ferramentas.consultar_processos(
            self.editor, exercicio=2026, unidade="Gecont", situacao="atrasado"
        )
        esperado = (
            Processo.objects.para_listagem()
            .filter(
                exercicio__ano=2026,
                estado=Estado.ATIVO,
                unidade_organizacional__nome_normalizado__icontains="gecont",
                situacao_efetiva="atrasado",
            )
            .count()
        )
        self.assertEqual(envelope.dados["total"], esperado)
        self.assertGreaterEqual(esperado, 1)

        url = envelope.referencias[0]["url"]
        resposta_http = self.client_autenticado_editor().get(url)
        self.assertEqual(resposta_http.status_code, 200)

    def client_autenticado_editor(self):
        cliente = Client(HTTP_X_FORWARDED_PROTO="https")
        cliente.force_login(self.editor)
        return cliente

    def test_limite_maior_que_20_trunca(self):
        envelope = ferramentas.consultar_processos(
            self.editor, exercicio=2026, limite=100
        )
        self.assertLessEqual(envelope.dados["exibidos"], 20)
        if envelope.dados["total"] > 20:
            self.assertTrue(envelope.truncado)

    def test_unidade_ambigua_nao_consulta_processos(self):
        Unidade.objects.get_or_create(nome="Gecont Regional")
        envelope = ferramentas.consultar_processos(
            self.editor, exercicio=2026, unidade="Gecont"
        )
        self.assertTrue(envelope.dados.get("ambiguo"))
        self.assertGreaterEqual(len(envelope.dados["alternativas"]), 2)
        self.assertNotIn("total", envelope.dados)

    def test_situacao_invalida(self):
        envelope = ferramentas.consultar_processos(
            self.editor, exercicio=2026, situacao="inexistente"
        )
        self.assertEqual(envelope.dados["erro"], "situação inválida")

    def test_categoria_material_filtra_e_leva_o_parametro_no_link(self):
        material, _ = Categoria.objects.get_or_create(nome="Material")
        for processo in Processo.objects.filter(exercicio__ano=2026):
            processo.categoria = material
            processo.save()
        esperado = Processo.objects.para_listagem().filter(
            exercicio__ano=2026, estado=Estado.ATIVO, categoria=material
        ).count()

        envelope = ferramentas.consultar_processos(
            self.editor, exercicio=2026, categoria="Material"
        )
        self.assertEqual(envelope.dados["total"], esperado)
        self.assertNotIn("aviso", envelope.dados)
        url = envelope.referencias[0]["url"]
        self.assertIn(f"categoria={material.pk}", url)

    def test_categoria_nao_encontrada_devolve_aviso_com_existentes(self):
        envelope = ferramentas.consultar_processos(
            self.editor, exercicio=2026, categoria="bens"
        )
        self.assertEqual(envelope.dados["total"], 0)
        self.assertIn("categoria não encontrada; existentes:", envelope.dados["aviso"])
        self.assertEqual(envelope.dados["filtros"]["categoria"], "bens")

    def test_categoria_none_nao_filtra(self):
        envelope_sem_filtro = ferramentas.consultar_processos(self.editor, exercicio=2026)
        envelope_categoria_none = ferramentas.consultar_processos(
            self.editor, exercicio=2026, categoria=None
        )
        self.assertEqual(
            envelope_sem_filtro.dados["total"], envelope_categoria_none.dados["total"]
        )
        self.assertNotIn("categoria", envelope_categoria_none.dados["filtros"])

    def test_esquema_categoria_estrito(self):
        esquema = ferramentas.ESQUEMAS["consultar_processos"]["function"]["parameters"]
        self.assertFalse(esquema["additionalProperties"])
        self.assertIn("categoria", esquema["required"])
        self.assertEqual(esquema["properties"]["categoria"]["type"], ["string", "null"])

    def test_exercicio_inexistente_via_executar(self):
        argumentos = json.dumps({"exercicio": 1999, "limite": 20})
        envelope = ferramentas.executar(
            "consultar_processos", argumentos, usuario=self.editor, exercicio_padrao=None
        )
        self.assertEqual(envelope.dados["erro"], "exercício inexistente")
        self.assertIn("exercicios", envelope.dados)

    def test_exercicio_none_assume_o_da_pagina_com_aviso(self):
        from apps.catalogo.models import Exercicio

        exercicio_padrao = Exercicio.objects.get(ano=2026)
        argumentos = json.dumps({"exercicio": None, "limite": 20})
        envelope = ferramentas.executar(
            "consultar_processos", argumentos, usuario=self.editor, exercicio_padrao=exercicio_padrao
        )
        self.assertIn("aviso", envelope.dados)
        self.assertEqual(envelope.dados["exercicio"], 2026)

    def test_argumentos_com_chave_desconhecida(self):
        argumentos = json.dumps({"exercicio": 2026, "limite": 20, "hackeando": True})
        envelope = ferramentas.executar(
            "consultar_processos", argumentos, usuario=self.editor, exercicio_padrao=None
        )
        self.assertEqual(envelope.dados["erro"], "argumentos inválidos")

    def test_ferramenta_desconhecida(self):
        with CaptureQueriesContext(connection) as capturado:
            envelope = ferramentas.executar(
                "executar_sql", "{}", usuario=self.editor, exercicio_padrao=None
            )
        self.assertEqual(envelope.dados["erro"], "ferramenta desconhecida")
        self.assertEqual(len(capturado.captured_queries), 0)

    def test_json_invalido(self):
        envelope = ferramentas.executar(
            "consultar_processos", "{isto nao e json", usuario=self.editor, exercicio_padrao=None
        )
        self.assertEqual(envelope.dados["erro"], "argumentos inválidos")

    def test_decimal_serializado_como_string(self):
        envelope = ferramentas.consultar_processos(self.editor, exercicio=2026, limite=1)
        texto = envelope.para_json()
        dados = json.loads(texto)
        item = dados["dados"]["itens"][0] if dados["dados"]["itens"] else None
        if item and item["valor_estimado"] is not None:
            self.assertIsInstance(item["valor_estimado"], str)

    def test_assert_num_queries_constante_entre_50_e_500(self):
        tipo = Tipo.objects.first()
        categoria = Categoria.objects.first()
        from apps.catalogo.models import Exercicio

        exercicio = Exercicio.objects.get(ano=2026)
        maior_item = Processo.objects.filter(exercicio=exercicio).order_by("-item_pca").first()
        proximo_item = (maior_item.item_pca if maior_item else 0) + 1

        def criar_lote(quantidade, inicio):
            objetos = [
                Processo(
                    item_pca=inicio + i,
                    exercicio=exercicio,
                    descricao_objeto=f"Objeto sintético {inicio + i}",
                    tipo=tipo,
                    categoria=categoria,
                    unidade_organizacional=self.gecont,
                )
                for i in range(quantidade)
            ]
            Processo.objects.bulk_create(objetos)

        criar_lote(50, proximo_item)
        with CaptureQueriesContext(connection) as com_50:
            ferramentas.consultar_processos(self.editor, exercicio=2026, unidade="Gecont")
        n_com_50 = len(com_50.captured_queries)

        criar_lote(450, proximo_item + 50)
        with CaptureQueriesContext(connection) as com_500:
            ferramentas.consultar_processos(self.editor, exercicio=2026, unidade="Gecont")
        n_com_500 = len(com_500.captured_queries)

        self.assertEqual(n_com_50, n_com_500)
        self.assertLessEqual(n_com_500, 6)
