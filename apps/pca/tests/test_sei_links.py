"""Testes de hiperlinks SEI — `apps.pca.sei.execucoes.
ler_links/gravar_links`, `apps.pca.sei.links.atualizar_de_coleta` (função
pura), o comando `sei_resolver_links` e os filtros de template `link_sei`/
`linkar_sei`. Nenhum teste chama Playwright/o SEI real —
`apps.pca.sei.coletor.resolver_links` é sempre mockado via
`unittest.mock.patch`, mesmo padrão de `test_sei_comandos.py`."""

import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.catalogo.models import Categoria, Exercicio, SituacaoExercicio, Tipo, Unidade
from apps.pca.models import Estado, Processo, ProcessoSEI, Situacao
from apps.pca.sei import execucoes, links
from apps.pca.templatetags.sei_links import link_sei, linkar_sei


class DiretorioTemporarioBase(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._override = override_settings(SEI_DATA_DIR=self._tmp.name)
        self._override.enable()
        self.addCleanup(self._override.disable)
        self.base = Path(self._tmp.name)
        # Os filtros de template fazem cache por mtime (`functools.
        # lru_cache`) — limpa entre testes para não vazar `links.json` de
        # um diretório temporário para outro (mesmo cuidado de
        # `test_sei_execucoes.py::test_ler_cache_nao_vaza_entre_...`).
        from apps.pca.templatetags import sei_links as sei_links_mod

        sei_links_mod._links_cache.cache_clear()
        self.addCleanup(sei_links_mod._links_cache.cache_clear)


class TestLinksRoundTrip(DiretorioTemporarioBase):
    """`ler_links()`/`gravar_links()` — mesmo padrão de `TestCache` em
    `test_sei_execucoes.py`, exceto que sem arquivo devolve as duas chaves
    vazias (nunca `{}`)."""

    def test_sem_arquivo_devolve_estrutura_vazia_das_duas_chaves(self):
        self.assertEqual(execucoes.ler_links(), {"processos": {}, "documentos": {}})

    def test_round_trip_com_processos_e_documentos(self):
        dados = {
            "processos": {
                "90796110000007.000036/2025-81": {
                    "id_procedimento": "1043956",
                    "nao_encontrado": False,
                    "resolvido_em": "2026-09-18T10:00:00-03:00",
                }
            },
            "documentos": {
                "1204703": {"id_documento": "9999999", "numero_sei": "90796110000007.000036/2025-81"}
            },
        }
        execucoes.gravar_links(dados)
        self.assertEqual(execucoes.ler_links(), dados)

    def test_ler_links_nao_vaza_entre_diretorios_temporarios_distintos(self):
        execucoes.gravar_links({"processos": {"1": {"id_procedimento": "x"}}, "documentos": {}})
        self.assertEqual(
            execucoes.ler_links(),
            {"processos": {"1": {"id_procedimento": "x"}}, "documentos": {}},
        )
        # Um segundo diretório temporário (outro teste) nunca veria o que
        # foi gravado aqui — cada teste usa seu próprio tempfile.
        with tempfile.TemporaryDirectory() as outro_tmp:
            with override_settings(SEI_DATA_DIR=outro_tmp):
                self.assertEqual(execucoes.ler_links(), {"processos": {}, "documentos": {}})


class TestAtualizarDeColeta(TestCase):
    """`apps.pca.sei.links.atualizar_de_coleta` — função pura, sem banco/
    Playwright."""

    def test_processo_ok_com_id_procedimento_grava_entrada_resolvida(self):
        mapa = {"processos": {}, "documentos": {}}
        dados_coleta = {
            "processos": [
                {"numero": "111", "resultado": "ok", "abertura": {"id_procedimento": "999"}}
            ]
        }
        links.atualizar_de_coleta(mapa, dados_coleta)
        self.assertEqual(mapa["processos"]["111"]["id_procedimento"], "999")
        self.assertFalse(mapa["processos"]["111"]["nao_encontrado"])
        self.assertIn("resolvido_em", mapa["processos"]["111"])

    def test_nao_encontrado_grava_sem_id_procedimento(self):
        mapa = {"processos": {}, "documentos": {}}
        dados_coleta = {"processos": [{"numero": "222", "resultado": "nao_encontrado"}]}
        links.atualizar_de_coleta(mapa, dados_coleta)
        self.assertEqual(mapa["processos"]["222"], {
            "nao_encontrado": True,
            "resolvido_em": mapa["processos"]["222"]["resolvido_em"],
        })
        self.assertNotIn("id_procedimento", mapa["processos"]["222"])

    def test_documentos_contratuais_gravam_links_de_documentos(self):
        mapa = {"processos": {}, "documentos": {}}
        dados_coleta = {
            "processos": [
                {
                    "numero": "111",
                    "resultado": "ok",
                    "abertura": {"id_procedimento": "999"},
                    "documentos_contratuais": [
                        {"id_documento": "888", "protocolo": "1204703", "rotulo": "Contrato"}
                    ],
                }
            ]
        }
        links.atualizar_de_coleta(mapa, dados_coleta)
        self.assertEqual(
            mapa["documentos"]["1204703"],
            {"id_documento": "888", "numero_sei": "111"},
        )

    def test_item_sem_numero_ou_sem_abertura_nao_quebra_o_laco(self):
        mapa = {"processos": {}, "documentos": {}}
        dados_coleta = {
            "processos": [
                {"resultado": "ok"},  # sem "numero"
                {"numero": "333", "resultado": "ok"},  # sem "abertura"
                {"numero": "444", "resultado": "ok", "abertura": {"id_procedimento": "1"}},
            ]
        }
        resultado = links.atualizar_de_coleta(mapa, dados_coleta)
        self.assertIs(resultado, mapa)
        self.assertNotIn("333", mapa["processos"])
        self.assertEqual(mapa["processos"]["444"]["id_procedimento"], "1")

    def test_devolve_e_muta_por_referencia(self):
        mapa = {"processos": {}, "documentos": {}}
        resultado = links.atualizar_de_coleta(mapa, {"processos": []})
        self.assertIs(resultado, mapa)


class TestSeiResolverLinksComando(DiretorioTemporarioBase):
    def setUp(self):
        super().setUp()
        self.exercicio, _ = Exercicio.objects.get_or_create(
            ano=2026, defaults={"rotulo": "PCA 2026", "situacao": SituacaoExercicio.ABERTO}
        )
        self.tipo = Tipo.objects.create(nome="Serviço")
        self.categoria = Categoria.objects.create(nome="Serviços")
        self.unidade = Unidade.objects.create(nome="Presidência")

    def _processo_com_sei(self, item_pca, numero_sei):
        processo = Processo.objects.create(
            item_pca=item_pca,
            exercicio=self.exercicio,
            descricao_objeto="Objeto de teste",
            tipo=self.tipo,
            categoria=self.categoria,
            unidade_organizacional=self.unidade,
            estado=Estado.ATIVO,
            situacao=Situacao.NO_PRAZO,
        )
        ProcessoSEI.objects.create(processo=processo, numero_sei=numero_sei)
        return processo

    def test_sem_pendente_nao_chama_resolver_links(self):
        with patch("apps.pca.sei.coletor.resolver_links") as resolver_mock:
            call_command("sei_resolver_links", stdout=StringIO())
        resolver_mock.assert_not_called()

    def test_com_pendentes_chama_so_com_numeros_ausentes(self):
        self._processo_com_sei(1, "111")
        self._processo_com_sei(2, "222")
        execucoes.gravar_links({"processos": {"111": {"id_procedimento": "9"}}, "documentos": {}})

        with patch(
            "apps.pca.sei.coletor.resolver_links",
            return_value={"executado_em": "x", "login": {}, "processos": []},
        ) as resolver_mock:
            call_command("sei_resolver_links", stdout=StringIO())

        numeros_chamados = resolver_mock.call_args[0][0]
        self.assertEqual(numeros_chamados, ["222"])

    def test_todos_chama_com_todo_numero_do_banco_mesmo_ja_resolvido(self):
        self._processo_com_sei(1, "111")
        self._processo_com_sei(2, "222")
        execucoes.gravar_links({"processos": {"111": {"id_procedimento": "9"}}, "documentos": {}})

        with patch(
            "apps.pca.sei.coletor.resolver_links",
            return_value={"executado_em": "x", "login": {}, "processos": []},
        ) as resolver_mock:
            call_command("sei_resolver_links", "--todos", stdout=StringIO())

        numeros_chamados = resolver_mock.call_args[0][0]
        self.assertEqual(numeros_chamados, ["111", "222"])

    def test_grava_links_json_ao_final(self):
        self._processo_com_sei(1, "111")

        with patch(
            "apps.pca.sei.coletor.resolver_links",
            return_value={
                "executado_em": "x",
                "login": {},
                "processos": [
                    {"numero": "111", "resultado": "ok", "abertura": {"id_procedimento": "999"}}
                ],
            },
        ):
            call_command("sei_resolver_links", stdout=StringIO())

        self.assertEqual(
            execucoes.ler_links()["processos"]["111"]["id_procedimento"], "999"
        )

    def test_progresso_vai_para_stdout_e_para_log(self):
        """`sei_resolver_links` passa `progresso=` a
        `coletor.resolver_links` — stdout + `execucoes/<carimbo>.log`, mesmo
        padrão de `sei_sincronizar`, mas sem tocar o lock `em_execucao`."""
        self._processo_com_sei(1, "111")

        def resolver_fake(numeros, progresso=None):
            progresso("linha de teste resolver")
            return {"executado_em": "x", "login": {}, "processos": []}

        saida = StringIO()
        with patch("apps.pca.sei.coletor.resolver_links", side_effect=resolver_fake):
            call_command("sei_resolver_links", stdout=saida)

        self.assertIn("linha de teste resolver", saida.getvalue())
        arquivos_log = list((self.base / "execucoes").glob("*.log"))
        self.assertEqual(len(arquivos_log), 1)
        self.assertIn("linha de teste resolver", arquivos_log[0].read_text(encoding="utf-8"))


class TestFiltroLinkSei(DiretorioTemporarioBase):
    def test_numero_resolvido_vira_link(self):
        execucoes.gravar_links({
            "processos": {"111": {"id_procedimento": "999", "nao_encontrado": False}},
            "documentos": {},
        })
        resultado = link_sei("111")
        self.assertIn("<a href=", resultado)
        self.assertIn("id_procedimento=999", resultado)
        self.assertIn("111", resultado)

    def test_nao_encontrado_vira_texto_mais_tag(self):
        execucoes.gravar_links({
            "processos": {"222": {"nao_encontrado": True}},
            "documentos": {},
        })
        resultado = link_sei("222")
        self.assertIn("222", resultado)
        self.assertIn("br-tag", resultado)
        self.assertIn("não encontrado no SEI", resultado)
        self.assertNotIn("<a href=", resultado)

    def test_numero_ausente_do_mapa_fica_texto_puro(self):
        execucoes.gravar_links({"processos": {}, "documentos": {}})
        self.assertEqual(link_sei("333"), "333")

    def test_sem_numero_devolve_como_veio(self):
        self.assertIsNone(link_sei(None))
        self.assertEqual(link_sei(""), "")


class TestFiltroLinkarSei(DiretorioTemporarioBase):
    def test_numero_de_processo_resolvido_vira_link_no_texto_livre(self):
        execucoes.gravar_links({
            "processos": {
                "90796110000007.000036/2025-81": {"id_procedimento": "999", "nao_encontrado": False}
            },
            "documentos": {},
        })
        texto = "Ver processo 90796110000007.000036/2025-81 para detalhes."
        resultado = linkar_sei(texto)
        self.assertIn("<a href=", resultado)
        self.assertIn("id_procedimento=999", resultado)
        self.assertIn("90796110000007.000036/2025-81", resultado)

    def test_dois_numeros_so_o_resolvido_vira_link(self):
        execucoes.gravar_links({
            "processos": {
                "90796110000007.000036/2025-81": {"id_procedimento": "999", "nao_encontrado": False}
            },
            "documentos": {},
        })
        texto = (
            "Processo 90796110000007.000036/2025-81 substitui o "
            "90000000000000.000000/2020-00."
        )
        resultado = linkar_sei(texto)
        self.assertEqual(resultado.count("<a href="), 1)
        self.assertIn("90000000000000.000000/2020-00", resultado)

    # Documento citado abre o PROCESSO dele: o SEI recusa link direto de documento sem a sessão
    # ("Link sem assinatura"), e o de processo funciona para qualquer usuário.
    def test_protocolo_sei_no_formato_com_prefixo_abre_o_processo(self):
        execucoes.gravar_links({
            "processos": {"x": {"id_procedimento": "999"}},
            "documentos": {"1234567": {"id_documento": "555", "numero_sei": "x"}},
        })
        resultado = linkar_sei("Conforme SEI nº 1234567.")
        self.assertIn("<a href=", resultado)
        self.assertIn("procedimento_trabalhar&amp;id_procedimento=999", resultado)
        self.assertNotIn("documento_visualizar", resultado)
        self.assertIn("1234567", resultado)

    def test_protocolo_entre_parenteses_abre_o_processo(self):
        execucoes.gravar_links({
            "processos": {"x": {"id_procedimento": "999"}},
            "documentos": {"1234567": {"id_documento": "555", "numero_sei": "x"}},
        })
        resultado = linkar_sei("Documento assinado (1234567).")
        self.assertIn("id_procedimento=999", resultado)
        self.assertNotIn("id_documento", resultado)

    def test_protocolo_de_processo_nao_resolvido_fica_sem_link(self):
        execucoes.gravar_links({
            "processos": {},
            "documentos": {"1234567": {"id_documento": "555", "numero_sei": "x"}},
        })
        resultado = linkar_sei("Conforme SEI nº 1234567.")
        self.assertNotIn("<a href=", resultado)
        self.assertIn("1234567", resultado)

    def test_texto_vazio_devolve_como_veio(self):
        self.assertIsNone(linkar_sei(None))
        self.assertEqual(linkar_sei(""), "")

    def test_escapa_html_antes_de_substituir(self):
        execucoes.gravar_links({"processos": {}, "documentos": {}})
        resultado = linkar_sei("<script>alert(1)</script> sem número nenhum")
        self.assertNotIn("<script>", resultado)
        self.assertIn("&lt;script&gt;", resultado)
