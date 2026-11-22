"""`apps.assistente.fontes`: `Trecho`, manifesto fechado,
`fragmentar` em bytes, extratores (A05/A09/A11/A12)."""

import json
from pathlib import Path

from django.test import SimpleTestCase
from django.utils.timezone import localdate

from apps.assistente import fontes
from apps.assistente.tests.base import AssistenteTestBase
from apps.pca.models import (
    Acompanhamento,
    EventoFinanceiro,
    OrigemEventoFinanceiro,
    Processo,
    ProcessoSEI,
    SituacaoNormalizada,
    TipoEvento,
    TipoEventoFinanceiro,
)
from apps.pca.sei import execucoes


class TestFragmentar(SimpleTestCase):
    def test_nunca_produz_trecho_maior_que_teto(self):
        texto = "\n\n".join(
            f"Parágrafo número {i} com bastante texto de exemplo repetido diversas vezes."
            for i in range(40)
        )
        trechos = fontes.fragmentar(texto, teto=200, sobreposicao=50)
        self.assertGreater(len(trechos), 1)
        for trecho in trechos:
            self.assertLessEqual(len(trecho.encode("utf-8")), 200)

    def test_paragrafo_gigante_e_partido_com_sobreposicao_ate_o_limite(self):
        paragrafo = " ".join(f"palavra{i}" for i in range(500))
        trechos = fontes.fragmentar(paragrafo, teto=100, sobreposicao=20)
        self.assertGreater(len(trechos), 1)
        for trecho in trechos:
            self.assertLessEqual(len(trecho.encode("utf-8")), 100)

    def test_nao_quebra_caractere_multibyte_cao_e_emoji(self):
        texto = ("ção " * 60) + ("🎉 " * 30)
        trechos = fontes.fragmentar(texto, teto=30, sobreposicao=10)
        self.assertGreater(len(trechos), 0)
        for trecho in trechos:
            # Não lança UnicodeDecodeError — prova de que nenhum caractere
            # multibyte foi cortado ao meio.
            trecho.encode("utf-8").decode("utf-8")

    def test_texto_vazio_devolve_lista_vazia(self):
        self.assertEqual(fontes.fragmentar(""), [])
        self.assertEqual(fontes.fragmentar(None), [])
        self.assertEqual(fontes.fragmentar("   "), [])

    def test_secao_longa_e_partida_em_mais_de_um_trecho(self):
        texto = "\n\n".join(f"Parágrafo {i} " * 100 for i in range(3))
        trechos = fontes.fragmentar(texto, teto=300)
        self.assertGreater(len(trechos), 1)


class TestSecoesMarkdown(SimpleTestCase):
    def test_divide_por_h2_e_h1_vira_secao_0(self):
        texto = "# Título geral\n\nIntro.\n\n## Seção A\n\nCorpo A.\n\n## Seção B\n\nCorpo B.\n"
        secoes = fontes.secoes_markdown(texto)
        titulos = [titulo for titulo, _ in secoes]
        self.assertEqual(titulos, ["Título geral", "Seção A", "Seção B"])

    def test_exclui_secao_por_titulo_normalizado(self):
        texto = "# T\n\n## Quem fez\n\nAlgo.\n\n## Contato\n\nWhatsApp e e-mails.\n"
        secoes = fontes.secoes_markdown(texto, excluir=("Contato",))
        titulos = [titulo for titulo, _ in secoes]
        self.assertIn("Quem fez", titulos)
        self.assertNotIn("Contato", titulos)
        self.assertFalse(any("WhatsApp" in corpo for _, corpo in secoes))


class TestDocumentoDoManifesto(SimpleTestCase):
    def test_slug_valido(self):
        self.assertIsNotNone(fontes.documento_do_manifesto("sobre-o-sistema"))
        self.assertIsNotNone(fontes.documento_do_manifesto("assistente"))
        self.assertIsNotNone(fontes.documento_do_manifesto("analises-fluxo-de-caixa"))

    def test_slug_fora_do_manifesto(self):
        self.assertIsNone(fontes.documento_do_manifesto("deployment"))
        self.assertIsNone(fontes.documento_do_manifesto("arquitetura"))

    def test_slug_com_traversal_ou_barra(self):
        self.assertIsNone(fontes.documento_do_manifesto("../etc/passwd"))
        self.assertIsNone(fontes.documento_do_manifesto("docs/deployment"))
        self.assertIsNone(fontes.documento_do_manifesto(""))
        self.assertIsNone(fontes.documento_do_manifesto(None))

    def test_manifesto_tem_exatamente_quatro_documentos(self):
        self.assertEqual(len(fontes.MANIFESTO_DOCS), 4)
        self.assertIsNotNone(fontes.documento_do_manifesto("solicitacoes"))


class TestHashTextoNormalizado(SimpleTestCase):
    def test_insensivel_a_espaco_e_caixa(self):
        self.assertEqual(
            fontes.hash_texto_normalizado("Texto Igual"),
            fontes.hash_texto_normalizado("texto   igual"),
        )


class TestExtrairDocs(SimpleTestCase):
    def test_gera_trechos_dos_quatro_documentos_com_permissoes_declaradas(self):
        trechos = fontes.extrair_docs()
        fontes_presentes = {t.fonte for t in trechos}
        self.assertEqual(fontes_presentes, {"docs"})

        slugs_com_trecho = {t.ref.split("/")[0] for t in trechos}
        self.assertEqual(
            slugs_com_trecho, {"sobre-o-sistema", "assistente", "analises-fluxo-de-caixa", "solicitacoes"}
        )

        permissoes_por_slug = {}
        for trecho in trechos:
            slug = trecho.ref.split("/")[0]
            permissoes_por_slug.setdefault(slug, set()).add(trecho.permissao)
        self.assertEqual(permissoes_por_slug["sobre-o-sistema"], {""})
        self.assertEqual(permissoes_por_slug["analises-fluxo-de-caixa"], {"pca.ver_analises"})
        self.assertEqual(permissoes_por_slug["solicitacoes"], {""})

    def test_secao_contato_nao_entra_no_indice(self):
        trechos = fontes.extrair_docs()
        textos = " ".join(t.texto for t in trechos if t.ref.startswith("sobre-o-sistema"))
        self.assertNotIn("WhatsApp", textos)
        self.assertNotIn("@", textos)
        self.assertIn("Toninho", textos)

    def test_arquivo_ausente_levanta_fonte_indisponivel(self, tmp_path=None):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(fontes.FonteIndisponivel):
                fontes.extrair_docs(base_dir=tmp)

    def test_url_resolve_para_rota_de_documentacao(self):
        trechos = fontes.extrair_docs()
        alvo = next(t for t in trechos if t.ref.startswith("assistente/"))
        self.assertEqual(alvo.url, "/assistente/docs/assistente")


class TestExtrairAcompanhamentos(AssistenteTestBase):
    def test_so_processos_ativos_permissao_acompanhamento_e_ref_com_id(self):
        processo = Processo.objects.filter(exercicio__ano=2026).first()
        situacao, _ = SituacaoNormalizada.objects.get_or_create(nome="Em tramitação")
        acompanhamento = Acompanhamento.objects.create(
            processo=processo,
            referencia_data=localdate(),
            origem_hash="hash-teste-fontes-1",
            evento="Reunião de acompanhamento de teste",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO,
            situacao_informada="Em andamento",
            situacao=situacao,
        )

        trechos = fontes.extrair_acompanhamentos()
        alvo = [t for t in trechos if t.ref == f"ac:2026/{processo.item_pca}/{acompanhamento.pk}"]

        self.assertEqual(len(alvo), 1)
        self.assertEqual(alvo[0].permissao, "pca.view_acompanhamento")
        self.assertIn("Reunião de acompanhamento de teste", alvo[0].texto)
        self.assertEqual(alvo[0].exercicio, 2026)
        self.assertEqual(alvo[0].item_pca, processo.item_pca)

    def test_evento_financeiro_com_observacao_vira_trecho_com_ref_propria(self):
        processo = Processo.objects.filter(exercicio__ano=2026).first()
        evento = EventoFinanceiro.objects.create(
            processo=processo,
            tipo=TipoEventoFinanceiro.CONTRATO,
            valor="1000.00",
            origem=OrigemEventoFinanceiro.MANUAL,
            observacao="Observação livre de teste sobre o evento.",
        )
        trechos = fontes.extrair_acompanhamentos()
        alvo = [t for t in trechos if t.ref == f"ef:2026/{processo.item_pca}/{evento.pk}"]
        self.assertEqual(len(alvo), 1)
        self.assertEqual(alvo[0].permissao, "pca.view_acompanhamento")
        self.assertIn("Observação livre de teste sobre o evento.", alvo[0].texto)

    def test_sem_texto_livre_nao_gera_trecho(self):
        processo = Processo.objects.filter(exercicio__ano=2026).first()
        situacao, _ = SituacaoNormalizada.objects.get_or_create(nome="Em tramitação")
        acompanhamento = Acompanhamento.objects.create(
            processo=processo,
            referencia_data=localdate(),
            origem_hash="hash-teste-fontes-vazio",
            evento="",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO,
            situacao_informada="",
            situacao=situacao,
        )
        trechos = fontes.extrair_acompanhamentos()
        refs = {t.ref for t in trechos}
        self.assertNotIn(f"ac:2026/{processo.item_pca}/{acompanhamento.pk}", refs)


class TestExtrairSei(AssistenteTestBase):
    def _fixture_cache(self):
        return {
            "processos": {
                "111": {
                    "documentos_contratuais": [
                        {
                            "id_documento": "9001",
                            "tipo": "contrato",
                            "texto_corpo": "CLÁUSULA PRIMEIRA – objeto do contrato de teste.",
                            "lido_em": "2026-09-18T10:00:00-03:00",
                            "assinaturas": [
                                {
                                    "papel": "externo",
                                    "cargo": "Diretora",
                                    "nome": "Maria da Sollo",
                                    "data": "18/09/2026",
                                    "hora": "10:00",
                                }
                            ],
                        },
                        {
                            "id_documento": "9002",
                            "tipo": "ordem_fornecimento",
                            "texto_corpo": "Texto que não deveria entrar (tipo não indexável).",
                        },
                    ]
                },
                "222": {
                    # Número SEI SEM ProcessoSEI vinculado — não deve entrar.
                    "documentos_contratuais": [
                        {
                            "id_documento": "9003",
                            "tipo": "contrato",
                            "texto_corpo": "Documento de processo não vinculado.",
                        }
                    ]
                },
            },
            "documentos": {},
        }

    def test_so_numero_vinculado_entra_com_url_e_nome_do_signatario(self):
        processo = Processo.objects.filter(exercicio__ano=2026).first()
        ProcessoSEI.objects.create(processo=processo, numero_sei="111")
        execucoes.gravar_cache(self._fixture_cache())
        execucoes.gravar_links({"processos": {"111": {"id_procedimento": "77"}}, "documentos": {}})

        trechos = fontes.extrair_sei()
        refs = {t.ref for t in trechos}
        self.assertTrue(any(ref.endswith("/9001") for ref in refs))
        self.assertFalse(any(ref.endswith("/9002") for ref in refs))
        self.assertFalse(any(ref.endswith("/9003") for ref in refs))

        alvo = next(t for t in trechos if t.ref.endswith("/9001"))
        self.assertEqual(alvo.permissao, "")
        self.assertIn("Maria da Sollo", alvo.texto)
        # Documento do SEI aponta para o processo dele (link de documento exige a sessão do SEI).
        self.assertEqual(alvo.url, "https://sei.cfc.org.br/sei/controlador.php?acao=procedimento_trabalhar&id_procedimento=77")


class TestExtrairTudo(AssistenteTestBase):
    def test_concatena_as_tres_fontes(self):
        trechos = fontes.extrair_tudo()
        fontes_presentes = {t.fonte for t in trechos}
        self.assertIn("docs", fontes_presentes)


class TestPermissoesAutorizadas(AssistenteTestBase):
    def test_visualizador_so_autenticado(self):
        self.assertEqual(fontes.permissoes_autorizadas(self.visualizador), frozenset({""}))

    def test_editor_tem_view_acompanhamento(self):
        permitidas = fontes.permissoes_autorizadas(self.editor)
        self.assertIn("", permitidas)
        self.assertIn("pca.view_acompanhamento", permitidas)
        self.assertNotIn("pca.ver_analises", permitidas)

    def test_dirigente_tem_as_tres(self):
        permitidas = fontes.permissoes_autorizadas(self.dirigente)
        self.assertEqual(permitidas, frozenset({"", "pca.view_acompanhamento", "pca.ver_analises"}))

    def test_none_ou_anonimo_devolve_vazio(self):
        self.assertEqual(fontes.permissoes_autorizadas(None), frozenset())
