"""`ficha`/`buscar_texto` (A05/A12/A13/A17):
paridade de campos, atualidade SEI por item, recusa parcial de
acompanhamentos, orçamento de embeddings, ACL antes do envio ao provedor."""

from unittest import mock

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils.timezone import localdate

from apps.assistente import ferramentas, fontes, indice
from apps.assistente.tests.base import AssistenteTestBase, ClienteFalso, vetor_do_hash
from apps.pca.filtros import NOMES_MES
from apps.pca.models import Acompanhamento, Processo, ProcessoSEI, SituacaoNormalizada
from apps.pca.sei import execucoes

_URL_SEI_PREFIXO = "https://sei.cfc.org.br/"


def _cache_com_instrumento():
    return {
        "processos": {
            "111": {
                "documentos_contratuais": [
                    {
                        "id_documento": "9001",
                        "tipo": "contrato",
                        "protocolo": "1204703",
                        "rotulo": "Contrato 01/2026",
                        "ultima_assinatura": "18/09/2026 14:30",
                        "valor": {"cifra": "18.001,20", "extenso": "dezoito mil...", "confere": True},
                        "vigencia": {"inicio": "2026-01-01", "fim": "2026-12-31"},
                        "assinaturas": [
                            {
                                "papel": "externo",
                                "cargo": "Diretora",
                                "nome": "Maria da Sollo",
                                "data": "18/09/2026",
                                "hora": "14:30",
                            }
                        ],
                        "lido_em": "2026-09-18T15:00:00-03:00",
                    }
                ]
            }
        },
        "documentos": {},
    }


class TestFicha(AssistenteTestBase):
    def _dar_numero_sei_com_instrumento(self, processo):
        ProcessoSEI.objects.create(processo=processo, numero_sei="111")
        execucoes.gravar_cache(_cache_com_instrumento())
        execucoes.gravar_links(
            {"processos": {"111": {"id_procedimento": "1043956"}}, "documentos": {}}
        )
        execucoes.registrar_ultima_consulta(
            processo.item_pca,
            processo.exercicio.ano,
            {"data_hora": "2026-09-18T15:00:00-03:00", "resultado": "ok"},
        )

    def test_editor_ve_instrumentos_signatarios_e_acompanhamentos(self):
        processo = Processo.objects.filter(exercicio__ano=2026).first()
        self._dar_numero_sei_com_instrumento(processo)
        situacao, _ = SituacaoNormalizada.objects.get_or_create(nome="Em tramitação")
        Acompanhamento.objects.create(
            processo=processo,
            referencia_data=localdate(),
            origem_hash="hash-ficha-1",
            evento="Reunião de teste",
            tipo_evento="reuniao_acompanhamento",
            situacao_informada="Em andamento",
            situacao=situacao,
        )

        envelope = ferramentas.ficha(self.editor, exercicio=2026, item=processo.item_pca)

        self.assertEqual(envelope.dados["instrumentos"][0]["signatarios"][0]["nome"], "Maria da Sollo")
        self.assertEqual(
            envelope.dados["instrumentos"][0]["url"],
            # Documento do SEI aponta para o processo dele (link de documento exige a sessão do SEI).
            "https://sei.cfc.org.br/sei/controlador.php?acao=procedimento_trabalhar&id_procedimento=1043956",
        )
        self.assertLessEqual(len(envelope.dados["acompanhamentos"]), 5)
        self.assertEqual(envelope.atualidade["sei"]["resultado"], "ok")
        self.assertFalse(envelope.sem_permissao)

        for referencia in envelope.referencias:
            url = referencia["url"]
            self.assertTrue(url.startswith("/") or url.startswith(_URL_SEI_PREFIXO))
            self.assertNotIn("documento_visualizar", url)

    def test_mes_previsto_devolve_nome_do_mes_nunca_o_inteiro(self):
        processo = Processo.objects.filter(
            exercicio__ano=2026, mes_previsto__isnull=False
        ).first()
        if processo is None:
            processo = Processo.objects.filter(exercicio__ano=2026).first()
            processo.mes_previsto = 3
            processo.save(update_fields=["mes_previsto"])

        envelope = ferramentas.ficha(self.editor, exercicio=2026, item=processo.item_pca)

        self.assertIsInstance(envelope.dados["mes_previsto"], str)
        self.assertIn(envelope.dados["mes_previsto"], NOMES_MES.values())

    def test_visualizador_nao_ve_acompanhamentos_recusa_parcial(self):
        processo = Processo.objects.filter(exercicio__ano=2026).first()
        situacao, _ = SituacaoNormalizada.objects.get_or_create(nome="Em tramitação")
        Acompanhamento.objects.create(
            processo=processo,
            referencia_data=localdate(),
            origem_hash="hash-ficha-2",
            evento="Texto de reunião sigiloso",
            tipo_evento="reuniao_acompanhamento",
            situacao_informada="",
            situacao=situacao,
        )

        envelope = ferramentas.ficha(self.visualizador, exercicio=2026, item=processo.item_pca)

        self.assertIsNone(envelope.dados["acompanhamentos"])
        self.assertTrue(envelope.sem_permissao)
        self.assertNotIn("Texto de reunião sigiloso", envelope.para_json())

    def test_ultima_consulta_com_erro_nunca_vira_atualizado(self):
        processo = Processo.objects.filter(exercicio__ano=2026).first()
        ProcessoSEI.objects.create(processo=processo, numero_sei="222")
        execucoes.registrar_ultima_consulta(
            processo.item_pca,
            processo.exercicio.ano,
            {"data_hora": "2026-09-17T10:00:00-03:00", "resultado": "erro"},
        )

        envelope = ferramentas.ficha(self.editor, exercicio=2026, item=processo.item_pca)

        self.assertEqual(envelope.atualidade["sei"]["resultado"], "erro")

    def test_item_sem_numero_sei_atualidade_sei_none(self):
        processo = Processo.objects.filter(exercicio__ano=2026).first()
        ProcessoSEI.objects.filter(processo=processo).delete()
        envelope = ferramentas.ficha(self.editor, exercicio=2026, item=processo.item_pca)
        self.assertIsNone(envelope.atualidade["sei"])

    def test_item_inexistente_e_erro_nao_zero(self):
        envelope = ferramentas.ficha(self.editor, exercicio=2026, item=999999)
        self.assertIn("erro", envelope.dados)
        self.assertNotIn("instrumentos", envelope.dados)

    def test_assert_num_queries_no_maximo_cinco(self):
        processo = Processo.objects.filter(exercicio__ano=2026).first()
        self._dar_numero_sei_com_instrumento(processo)
        # Aquece o cache de permissões do usuário (2 consultas de
        # user_permissions/group_permissions do Django, pagas uma vez por
        # request de verdade — ex.: menu/breadcrumb já chamam `has_perm`
        # antes da view — nunca o orçamento de consultas da PRÓPRIA `ficha`).
        self.editor.has_perm("pca.view_acompanhamento")
        with CaptureQueriesContext(connection) as capturado:
            ferramentas.ficha(self.editor, exercicio=2026, item=processo.item_pca)
        self.assertLessEqual(len(capturado.captured_queries), 5)


class TestBuscarTexto(AssistenteTestBase):
    def setUp(self):
        super().setUp()
        import tempfile
        from pathlib import Path

        from django.test import override_settings

        self._tmp_indice = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp_indice.cleanup)
        self._override = override_settings(
            IA_INDICE_PATH=str(Path(self._tmp_indice.name) / "indice.sqlite3")
        )
        self._override.enable()
        self.addCleanup(self._override.disable)
        indice._CACHE_MATRIZ.clear()
        self.addCleanup(indice._CACHE_MATRIZ.clear)

        # Texto do trecho DELIBERADAMENTE diferente da pergunta que o teste
        # de payload envia (abaixo) — senão a própria pergunta do usuário
        # (que sempre entra na mensagem `user`) faria o teste de vazamento
        # dar falso positivo/negativo por coincidência de palavras.
        self.trecho_item_42 = fontes.Trecho(
            fonte="acompanhamento", ref="ac:2026/42/1", ordem=0, titulo="Acompanhamento — item 42",
            texto="reuniao de julho registrou compromisso confidencial codigo-sigiloso-XPTO42",
            url="/pca/2026/42/", exercicio=2026, item_pca=42,
            permissao="pca.view_acompanhamento", atualizado_em=None,
        )
        cliente_indexacao = ClienteFalso()
        with mock.patch(
            "apps.assistente.fontes.extrair_tudo", return_value=[self.trecho_item_42]
        ):
            from django.utils import timezone as tz

            indice.indexar(cliente_indexacao, agora=tz.now())

    def _contexto(self, cliente, restantes=4):
        return ferramentas.ContextoExecucao(
            usuario=self.editor, exercicio_padrao=None, cliente=cliente, embeddings_restantes=restantes,
        )

    def test_editor_obtem_o_trecho_do_item_42(self):
        cliente = ClienteFalso()
        envelope = ferramentas.buscar_texto(
            self.editor,
            pergunta=self.trecho_item_42.texto,
            contexto=self._contexto(cliente),
        )
        self.assertGreaterEqual(envelope.dados["total"], 1)
        self.assertFalse(envelope.dados["abstencao"])

    def test_visualizador_obtem_abstencao(self):
        cliente = ClienteFalso()
        envelope = ferramentas.buscar_texto(
            self.visualizador,
            pergunta=self.trecho_item_42.texto,
            contexto=self._contexto(cliente),
        )
        self.assertTrue(envelope.dados["abstencao"])
        self.assertEqual(envelope.dados["trechos"], [])

    def test_payload_enviado_ao_provedor_nao_contem_texto_restrito(self):
        # Trilha completa via `agente.responder`: o texto do
        # acompanhamento do item 42 nunca aparece nas mensagens enviadas ao
        # cliente falso (que espiona o payload, mesma técnica do provedor
        # real), mesmo que a ferramenta tenha sido chamada.
        cliente_falso_agente = ClienteFalso(
            [
                _resposta_ferramenta_buscar_texto(self.trecho_item_42.texto),
                _resposta_texto_generica(),
            ]
        )
        from apps.assistente import agente
        from django.utils import timezone as tz

        agente.responder(
            usuario=self.visualizador,
            exercicio=None,
            pergunta="o que ficou combinado em julho sobre o item 42?",
            trocas=[],
            cliente=cliente_falso_agente,
            agora=tz.now(),
        )
        payload_ferramentas = "".join(
            str(mensagem.get("content", ""))
            for chamada in cliente_falso_agente.chamadas
            for mensagem in chamada["mensagens"]
        )
        self.assertNotIn("codigo-sigiloso-XPTO42", payload_ferramentas)

    def test_fonte_invalida(self):
        envelope = ferramentas.buscar_texto(
            self.editor, pergunta="teste", fonte="sql", contexto=self._contexto(ClienteFalso())
        )
        self.assertIn("erro", envelope.dados)

    def test_orcamento_de_busca_esgotado_nao_chama_embeddings(self):
        cliente = ClienteFalso()
        contexto = self._contexto(cliente, restantes=0)
        envelope = ferramentas.buscar_texto(self.editor, pergunta="teste", contexto=contexto)
        self.assertEqual(envelope.dados["erro"], "orçamento de busca esgotado")
        self.assertEqual(cliente.chamadas_embeddings, [])

    def test_indice_ausente_erro_amigavel(self):
        import tempfile
        from pathlib import Path

        from django.test import override_settings

        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(IA_INDICE_PATH=str(Path(tmp) / "outro.sqlite3")):
                envelope = ferramentas.buscar_texto(
                    self.editor, pergunta="teste", contexto=self._contexto(ClienteFalso())
                )
        self.assertIn("índice", envelope.dados["erro"])


def _resposta_ferramenta_buscar_texto(pergunta_texto):
    from apps.assistente.tests.base import resposta_ferramenta

    return resposta_ferramenta("buscar_texto", {"pergunta": pergunta_texto, "fonte": None, "exercicio": None, "item": None})


def _resposta_texto_generica():
    from apps.assistente.tests.base import resposta_texto

    return resposta_texto("não encontrei dados para responder")
