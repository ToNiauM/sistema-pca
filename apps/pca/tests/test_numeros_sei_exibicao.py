"""Guarda dos dois bugs de exibição de números SEI:

1. `processo_detalhe.html` incluía `_numeros_sei.html` sem `processo=p` —
   o parcial sempre caía no `{% empty %}` mesmo com números SEI cadastrados.
2. A coluna `numeros_sei` da tabela Processos não tinha ramo próprio em
   `_tabela_linha.html`, caía no filtro genérico `exibir` (que trata o
   `RelatedManager` como atributo simples) e estourava `TypeError` → 500.

Teste a: o detalhe é estritamente de leitura (lista separada por vírgula
ou "Não informado", sem formulário nem controle de remoção) e as rotas
`pca:adicionar_sei`/`pca:remover_sei` respondem 404. Teste b: nenhuma
coluna do registro `COLUNAS` derruba `pca:tabela`. Teste c: a contagem de
queries com `numeros_sei` marcado não cresce com o número de processos —
prova que o `prefetch_related("numeros_sei")` está em vigor."""

from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.db import connection
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import NoReverseMatch, reverse

from apps.catalogo.models import Categoria, Exercicio, Tipo, Unidade
from apps.pca import services
from apps.pca.colunas import COLUNAS
from apps.pca.models import Processo, ProcessoSEI

ARQUIVO_REAL = "apps/pca/fixtures/modelo-controle-exemplo.xlsx"


class NumerosSeiExibicaoTests(TransactionTestCase):
    """Mesmo padrão de setUp de `test_ordenacao_tabela.py`/
    `test_edicao_formulario.py`: import real a cada teste
    (`TransactionTestCase` não chama `setUpTestData`, dá flush entre
    testes), `serialized_rollback = True`."""

    serialized_rollback = True

    def setUp(self):
        call_command(
            "importar_pca",
            ARQUIVO_REAL,
            "--usuario=importador@pca.local",
            "--exercicio=2026",
            stdout=StringIO(),
        )
        User = get_user_model()
        self.editor = User.objects.create_user(
            email="editor-sei@pca.local", password="senha-segura"
        )
        self.editor.groups.add(Group.objects.get(name="editor"))
        self.leitor = User.objects.create_user(
            email="leitor-sei@pca.local", password="senha-segura"
        )

        # Item 1/2026 já carrega 1 número SEI real do XLSX (diagnóstico do
        # orquestrador). Acrescenta um segundo, distinto, para os testes
        # a/b precisarem de 2+ números sem violar `unique_together`.
        self.processo = Processo.objects.get(exercicio__ano=2026, item_pca=1)
        numeros_existentes = set(
            self.processo.numeros_sei.values_list("numero_sei", flat=True)
        )
        novo_numero = "99999.999999/9999-99"
        self.assertNotIn(novo_numero, numeros_existentes)
        ProcessoSEI.objects.create(processo=self.processo, numero_sei=novo_numero)
        self.numeros_esperados = list(
            self.processo.numeros_sei.values_list("numero_sei", flat=True)
        )
        self.assertGreaterEqual(len(self.numeros_esperados), 2)

    def test_detalhe_mostra_numeros_sei_em_leitura_sem_formulario_nem_controle(self):
        """Editor e leitor veem a mesma lista de leitura — o detalhe não
        distingue perfil para SEI: incluir/excluir só no fieldset
        Processo do `pca:editar_processo`."""
        self.assertEqual(self.processo.exercicio.situacao, "aberto")
        numeros_em_ordem = list(
            self.processo.numeros_sei.order_by("id").values_list(
                "numero_sei", flat=True
            )
        )
        for usuario in (self.editor, self.leitor):
            with self.subTest(usuario=usuario.email):
                self.client.force_login(usuario)
                resposta = self.client.get(
                    reverse("pca:detalhe_processo", args=[2026, self.processo.item_pca])
                )
                self.assertEqual(resposta.status_code, 200)
                conteudo = resposta.content.decode()

                self.assertIn(", ".join(numeros_em_ordem), conteudo)
                self.assertNotIn("numeros_sei-TOTAL_FORMS", conteudo)
                self.assertNotIn("/sei/adicionar", conteudo)
                self.assertNotIn("/sei/", conteudo)

    def test_rotas_antigas_de_sei_nao_existem_mais(self):
        with self.assertRaises(NoReverseMatch):
            reverse("pca:adicionar_sei", args=[2026, self.processo.item_pca])
        with self.assertRaises(NoReverseMatch):
            reverse("pca:remover_sei", args=[2026, self.processo.item_pca, 1])

        self.client.force_login(self.editor)
        sei_id = self.processo.numeros_sei.first().pk
        resposta_adicionar = self.client.post(
            f"/processo/2026/{self.processo.item_pca}/sei/adicionar",
            {"numero_sei": "77777.777777/2026-01"},
        )
        resposta_remover = self.client.post(
            f"/processo/2026/{self.processo.item_pca}/sei/{sei_id}/remover"
        )
        self.assertEqual(resposta_adicionar.status_code, 404)
        self.assertEqual(resposta_remover.status_code, 404)

    def test_detalhe_sem_numero_sei_mostra_nao_informado(self):
        processo_sem_sei = Processo.objects.get(exercicio__ano=2026, item_pca=2)
        processo_sem_sei.numeros_sei.all().delete()
        self.client.force_login(self.leitor)
        resposta = self.client.get(
            reverse("pca:detalhe_processo", args=[2026, processo_sem_sei.item_pca])
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("Não informado", resposta.content.decode())

    def test_query_count_do_detalhe_nao_cresce_com_o_numero_de_seis(self):
        # Acompanha o Task 1/29-01-SUMMARY.md: o detalhe lê
        # `processo.numeros_sei.all()` (uma consulta única, cacheada pelo
        # ORM). MESMO processo nos dois lados (mesmo histórico de
        # acompanhamento) — só o número de SEIs muda entre as duas medições.
        self.client.force_login(self.leitor)
        url = reverse("pca:detalhe_processo", args=[2026, self.processo.item_pca])
        self.assertGreaterEqual(self.processo.numeros_sei.count(), 2)

        with CaptureQueriesContext(connection) as consultas_varios:
            resposta_varios = self.client.get(url)
        self.assertEqual(resposta_varios.status_code, 200)

        self.processo.numeros_sei.all().delete()

        with CaptureQueriesContext(connection) as consultas_zero:
            resposta_zero = self.client.get(url)
        self.assertEqual(resposta_zero.status_code, 200)

        self.assertEqual(len(consultas_zero), len(consultas_varios))

    # --- Teste b -------------------------------------------------------

    def test_tabela_responde_200_para_cada_coluna_do_registro(self):
        self.client.force_login(self.leitor)
        url = reverse("pca:tabela")
        for coluna in COLUNAS:
            with self.subTest(chave=coluna.chave):
                resposta = self.client.get(
                    url,
                    {
                        "colunas": ["item_pca", "descricao_objeto", coluna.chave],
                    },
                )
                self.assertEqual(resposta.status_code, 200)

    def test_coluna_numeros_sei_isolada_mostra_numeros_separados_por_espaco(self):
        self.client.force_login(self.leitor)
        resposta = self.client.get(
            reverse("pca:tabela"), {"colunas": ["numeros_sei"], "por_pagina": 50}
        )
        self.assertEqual(resposta.status_code, 200)
        conteudo = resposta.content.decode()
        esperado = " ".join(self.numeros_esperados)
        self.assertIn(esperado, conteudo)

    # --- Teste c ---------------------------------------------------------

    def _criar_processos_com_sei(self, nome_unidade, quantidade):
        exercicio = Exercicio.objects.get(ano=2026)
        unidade = Unidade.objects.create(nome=nome_unidade)
        tipo = Tipo.objects.first()
        categoria = Categoria.objects.first()
        for indice in range(quantidade):
            processo = services.criar_processo(
                usuario=self.editor,
                descricao_objeto=f"Objeto teste de queries {nome_unidade} {indice}",
                tipo_id=tipo.pk,
                categoria_id=categoria.pk,
                unidade_organizacional_id=unidade.pk,
                exercicio=exercicio,
            )
            ProcessoSEI.objects.create(
                processo=processo, numero_sei=f"11111.{indice:06d}/2026-01"
            )
            ProcessoSEI.objects.create(
                processo=processo, numero_sei=f"11111.{indice:06d}/2026-02"
            )
        return unidade

    def test_query_count_da_coluna_numeros_sei_nao_cresce_com_o_numero_de_processos(self):
        unidade_pequena = self._criar_processos_com_sei(
            "Unidade Teste Queries Pequena", 2
        )
        unidade_grande = self._criar_processos_com_sei(
            "Unidade Teste Queries Grande", 10
        )
        self.client.force_login(self.leitor)
        url = reverse("pca:tabela")
        parametros_comuns = {
            "colunas": ["item_pca", "descricao_objeto", "numeros_sei"],
            "por_pagina": 50,
        }

        with CaptureQueriesContext(connection) as queries_pequena:
            resposta_pequena = self.client.get(
                url, {**parametros_comuns, "uo": unidade_pequena.pk}
            )
        self.assertEqual(resposta_pequena.status_code, 200)

        with CaptureQueriesContext(connection) as queries_grande:
            resposta_grande = self.client.get(
                url, {**parametros_comuns, "uo": unidade_grande.pk}
            )
        self.assertEqual(resposta_grande.status_code, 200)

        self.assertEqual(
            len(queries_pequena),
            len(queries_grande),
            "nº de queries da tabela cresceu com o nº de processos — "
            "prefetch_related(\"numeros_sei\") não está em vigor",
        )
