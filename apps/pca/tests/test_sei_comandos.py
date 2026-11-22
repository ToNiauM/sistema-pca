"""Testes de `sei_coletar`/`sei_aplicar`/`sei_sincronizar` (Fase 32, Plano
32-04). Nenhum teste chama Playwright nem o SEI real:
`apps.pca.sei.coletor.coletar` é sempre mockado via `unittest.mock.patch`.
Todo teste roda contra um diretório temporário
(`tempfile.TemporaryDirectory()` + `@override_settings(SEI_DATA_DIR=...)`),
nunca `BASE_DIR/data` de verdade."""

import json
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone as django_timezone
from freezegun import freeze_time

from apps.catalogo.models import (
    Categoria,
    Exercicio,
    InstrumentoContratual,
    Modalidade,
    SituacaoExercicio,
    SituacaoNormalizada,
    Tipo,
    Unidade,
)
from apps.pca.management.commands.sei_aplicar import campos_atuais_de as campos_atuais_aplicar
from apps.pca.management.commands.sei_atender import atender_um_passo
from apps.pca.management.commands.sei_atender import _campos_atuais as campos_atuais_atender
from apps.pca.management.commands.sei_sincronizar import _campos_atuais as campos_atuais_sincronizar
from apps.pca.models import Estado, Processo, ProcessoSEI, Situacao
from apps.pca.sei import coletor, execucoes
from apps.pca.sei.extracao import VERSAO_EXTRACAO_DOCUMENTO
from apps.pca.sei.regras import propor

_FIXTURES = Path(__file__).parent / "fixtures" / "sei"


def _coleta_item_3(item_pca=3, exercicio=2026):
    """Carrega `coleta_item_3.json` e carimba `item_pca`/
    `exercicio` em cada processo coletado — o formato real produzido por
    `apps.pca.sei.coletor.coletar`, diferente do campo `item`
    solto que a fixture original trazia. `login` com `autenticado: True`
o envelope real de `coletar()` sempre traz essa
    chave; sem ela, `atender_um_passo` classificaria como `erro_login`."""
    with open(_FIXTURES / "coleta_item_3.json", encoding="utf-8") as arquivo:
        dados = json.load(arquivo)
    processos = []
    for processo in dados["processos"]:
        processo = dict(processo)
        processo["item_pca"] = item_pca
        processo["exercicio"] = exercicio
        processos.append(processo)
    return {"login": {"autenticado": True}, "processos": processos}


class ComandosSeiBase(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._override = override_settings(SEI_DATA_DIR=self._tmp.name)
        self._override.enable()
        self.addCleanup(self._override.disable)
        self.base = Path(self._tmp.name)

        # Fase 39 — `atender_um_passo` agora também chama
        # `assistente.estado.limpar_se_necessario`/`assistente.fila.
        # consumir_um_pedido` a cada passagem. Sem isolar os 3 caminhos
        # auxiliares do assistente aqui, os testes desta classe tocariam o
        # `data/ia/*.sqlite3` REAL do container de dev (default de
        # `IA_ESTADO_PATH` deriva do banco PCA de produção/dev, não do
        # banco de teste — ver `config/settings/base.py`), violando "sem
        # escrita fora de manage.py test em dados reais". `IA_API_KEY=""`
        # garante que nenhum teste desta classe tenta criar um cliente
        # OpenAI de verdade.
        self._override_ia = override_settings(
            IA_ESTADO_PATH=str(Path(self._tmp.name) / "ia" / "estado.sqlite3"),
            IA_INDICE_PATH=str(Path(self._tmp.name) / "ia" / "indice.sqlite3"),
            IA_CONVERSAS_PATH=str(Path(self._tmp.name) / "ia" / "conversas.sqlite3"),
            IA_API_KEY="",
        )
        self._override_ia.enable()
        self.addCleanup(self._override_ia.disable)

        # `sei_sincronizar` resolve os links dos números que a coleta (falsa)
        # não trouxe chamando `coletor.resolver_links` — o REAL abre o
        # Chromium e loga no SEI. Nenhum teste desta base pode chegar nele
        # (convenções do projeto, Robô SEI); quem precisa do comportamento faz o próprio
        # `patch` por cima deste.
        self._patch_links = patch(
            "apps.pca.sei.coletor.resolver_links", return_value={"processos": []}
        )
        self._patch_links.start()
        self.addCleanup(self._patch_links.stop)

        self.exercicio, _ = Exercicio.objects.get_or_create(
            ano=2026, defaults={"rotulo": "PCA 2026", "situacao": SituacaoExercicio.ABERTO}
        )
        self.tipo = Tipo.objects.create(nome="Serviço")
        self.categoria = Categoria.objects.create(nome="Serviços")
        self.unidade = Unidade.objects.create(nome="Presidência")
        for nome in ("Sem informação", "Concluído", "Em tramitação"):
            SituacaoNormalizada.objects.get_or_create(nome=nome)

    def processo(self, item, **overrides):
        valores = dict(
            item_pca=item,
            exercicio=self.exercicio,
            descricao_objeto="Objeto de teste",
            justificativa="Justificativa",
            tipo=self.tipo,
            categoria=self.categoria,
            unidade_organizacional=self.unidade,
            estado=Estado.ATIVO,
            situacao=Situacao.NO_PRAZO,
        )
        valores.update(overrides)
        return Processo.objects.create(**valores)

    def processo_item_6_ja_correto(self):
        """`Processo` do item 6 já com os 12 campos de tramitação +
        execução contratual EXATAMENTE como `coleta_item_6.json` (Plano
        33-02) traria — usado pelos 3 testes de idempotência
        ponta a ponta (nenhum dos 3 comandos reescreve o que já
        está correto)."""
        instrumento = InstrumentoContratual.objects.create(nome="Termo Aditivo")
        modalidade = Modalidade.objects.create(nome="Dispensa Com Disputa")
        return self.processo(
            6,
            data_assinatura_contrato=date(2025, 12, 12),
            numero_instrumento_contratual="01/2025",
            instrumento_contratual=instrumento,
            valor_contratado=Decimal("38731.90"),
            data_recebimento_gelic=date(2024, 10, 31),
            fornecedor_razao_social="Engemax Engenharia e Comércio Ltda",
            fornecedor_cnpj="12.345.678/0001-95",
            modalidade=modalidade,
            numero_contratacao="90027/2024",
            vigencia_inicio=date(2026, 1, 11),
            vigencia_fim=date(2027, 1, 10),
        )


def _coleta_item_6(item_pca=6, exercicio=2026):
    """Carrega `coleta_item_6.json` e carimba
    `item_pca`/`exercicio` em cada processo coletado — mesmo padrão de
    `_coleta_item_3` acima."""
    with open(_FIXTURES / "coleta_item_6.json", encoding="utf-8") as arquivo:
        dados = json.load(arquivo)
    processos = []
    for processo in dados["processos"]:
        processo = dict(processo)
        processo["item_pca"] = item_pca
        processo["exercicio"] = exercicio
        processos.append(processo)
    return {"processos": processos}


def _coleta_item_15(item_pca=15, exercicio=2026):
    """Carrega `coleta_item_15.json` (fixture com apostilamento de reajuste
    global qualificado, Fase 35) e carimba `item_pca`/`exercicio` — mesmo
    padrão de `_coleta_item_3`/`_coleta_item_6` acima, inclusive `login`
    (ver `_coleta_item_3`)."""
    with open(_FIXTURES / "coleta_item_15.json", encoding="utf-8") as arquivo:
        dados = json.load(arquivo)
    processos = []
    for processo in dados["processos"]:
        processo = dict(processo)
        processo["item_pca"] = item_pca
        processo["exercicio"] = exercicio
        processos.append(processo)
    return {"login": {"autenticado": True}, "processos": processos}


_CAMPOS_EXECUCAO_CONTRATUAL = {
    "fornecedor_razao_social",
    "fornecedor_cnpj",
    "modalidade",
    "numero_contratacao",
    "vigencia_inicio",
    "vigencia_fim",
}


class TestSeiAplicarCamposAtuaisExecucaoContratual(ComandosSeiBase):
    """`sei_aplicar.py::campos_atuais_de` inclui os 6 campos novos
    — quando o `Processo` já está com o mesmo valor que a coleta traria,
    `regras.propor()` não vê nenhum dos 6 campos novos em `alteracoes`
    (idempotência ponta a ponta, não só dentro de `regras.py` isolado)."""

    def test_processo_ja_correto_nao_gera_alteracoes_de_execucao_contratual(self):
        processo = self.processo_item_6_ja_correto()

        proposta = propor(
            item_pca=6,
            exercicio=2026,
            campos_atuais=campos_atuais_aplicar(processo),
            processos_coletados=_coleta_item_6(item_pca=6, exercicio=2026)["processos"],
        )

        self.assertFalse(_CAMPOS_EXECUCAO_CONTRATUAL & proposta.alteracoes.keys())


class TestSeiSincronizarCamposAtuaisExecucaoContratual(ComandosSeiBase):
    """`sei_sincronizar.py::_campos_atuais` inclui os 6 campos
    novos — mesma prova de idempotência do comando que o cron chama."""

    def test_processo_ja_correto_nao_gera_alteracoes_de_execucao_contratual(self):
        processo = self.processo_item_6_ja_correto()

        proposta = propor(
            item_pca=6,
            exercicio=2026,
            campos_atuais=campos_atuais_sincronizar(processo),
            processos_coletados=_coleta_item_6(item_pca=6, exercicio=2026)["processos"],
        )

        self.assertFalse(_CAMPOS_EXECUCAO_CONTRATUAL & proposta.alteracoes.keys())


class TestSeiAtenderCamposAtuaisExecucaoContratual(ComandosSeiBase):
    """`sei_atender.py::_campos_atuais` inclui os 6 campos novos —
    mesma prova de idempotência do comando que atende o botão "Atualizar
    com o SEI" do Admin."""

    def test_processo_ja_correto_nao_gera_alteracoes_de_execucao_contratual(self):
        processo = self.processo_item_6_ja_correto()

        proposta = propor(
            item_pca=6,
            exercicio=2026,
            campos_atuais=campos_atuais_atender(processo),
            processos_coletados=_coleta_item_6(item_pca=6, exercicio=2026)["processos"],
        )

        self.assertFalse(_CAMPOS_EXECUCAO_CONTRATUAL & proposta.alteracoes.keys())


class TestSeiColetar(ComandosSeiBase):
    def test_grava_json_de_coleta_sem_tocar_o_banco(self):
        processo = self.processo(3)
        ProcessoSEI.objects.create(processo=processo, numero_sei="90796110000007.000036/2025-81")

        with patch(
            "apps.pca.sei.coletor.coletar",
            return_value={"executado_em": "2026-09-18T00:00:00+00:00", "login": {}, "processos": []},
        ) as coletar_mock:
            saida = StringIO()
            call_command("sei_coletar", stdout=saida)

        alvos_chamados = coletar_mock.call_args[0][0]
        self.assertEqual(
            alvos_chamados,
            [{"item_pca": 3, "exercicio": 2026, "numero_sei": "90796110000007.000036/2025-81"}],
        )

        arquivos = list((self.base / "coletas").glob("*.json"))
        self.assertEqual(len(arquivos), 1)
        gravado = json.loads(arquivos[0].read_text(encoding="utf-8"))
        self.assertEqual(gravado["processos"], [])

        processo.refresh_from_db()
        self.assertIsNone(processo.data_assinatura_contrato)

    def test_filtro_por_itens(self):
        p1 = self.processo(1)
        p2 = self.processo(2)
        ProcessoSEI.objects.create(processo=p1, numero_sei="111")
        ProcessoSEI.objects.create(processo=p2, numero_sei="222")

        with patch(
            "apps.pca.sei.coletor.coletar",
            return_value={"executado_em": "x", "login": {}, "processos": []},
        ) as coletar_mock:
            call_command("sei_coletar", "--itens", "1", stdout=StringIO())

        alvos_chamados = coletar_mock.call_args[0][0]
        self.assertEqual([a["item_pca"] for a in alvos_chamados], [1])

    def test_saida_extra_grava_copia(self):
        processo = self.processo(3)
        ProcessoSEI.objects.create(processo=processo, numero_sei="111")
        destino = self.base / "copia-extra" / "saida.json"

        with patch(
            "apps.pca.sei.coletor.coletar",
            return_value={"executado_em": "x", "login": {}, "processos": []},
        ):
            call_command("sei_coletar", "--saida", str(destino), stdout=StringIO())

        self.assertTrue(destino.exists())
        # o registro padrão em coletas/ também existe — --saida NUNCA o substitui
        self.assertEqual(len(list((self.base / "coletas").glob("*.json"))), 1)


class TestSeiColetarForcar(ComandosSeiBase):
    """Fase 34: `sei_coletar` carrega o cache antes
    da coleta e repassa `--forcar` como `forcar=` a `coletor.coletar`."""

    def test_sem_forcar_usa_o_cache_forcar_false(self):
        processo = self.processo(3)
        ProcessoSEI.objects.create(processo=processo, numero_sei="111")

        with patch(
            "apps.pca.sei.coletor.coletar",
            return_value={"executado_em": "x", "login": {}, "processos": []},
        ) as coletar_mock:
            call_command("sei_coletar", stdout=StringIO())

        self.assertFalse(coletar_mock.call_args.kwargs["forcar"])

    def test_com_forcar_passa_forcar_true(self):
        processo = self.processo(3)
        ProcessoSEI.objects.create(processo=processo, numero_sei="111")

        with patch(
            "apps.pca.sei.coletor.coletar",
            return_value={"executado_em": "x", "login": {}, "processos": []},
        ) as coletar_mock:
            call_command("sei_coletar", "--forcar", stdout=StringIO())

        self.assertTrue(coletar_mock.call_args.kwargs["forcar"])

    def test_grava_o_cache_apos_a_coleta(self):
        processo = self.processo(3)
        ProcessoSEI.objects.create(processo=processo, numero_sei="111")

        def coletar_fake(alvos, cache=None, forcar=None, reprocessar_documentos=None):
            cache["processos"]["teste"] = {"registros": 1, "primeiro": None}
            return {"executado_em": "x", "login": {}, "processos": []}

        with patch("apps.pca.sei.coletor.coletar", side_effect=coletar_fake):
            call_command("sei_coletar", stdout=StringIO())

        self.assertEqual(
            execucoes.ler_cache()["processos"]["teste"], {"registros": 1, "primeiro": None}
        )


class TestSeiColetarReprocessarDocumentos(ComandosSeiBase):
    """Fase 39: `--reprocessar-documentos` repassa o flag
    a `coletor.coletar` e imprime a linha de resumo — sem NUNCA aplicar nada
    ao PCA (mesmo mecanismo de coletor falso injetado de `TestSeiColetar`)."""

    def test_repassa_reprocessar_documentos_true(self):
        processo = self.processo(3)
        ProcessoSEI.objects.create(processo=processo, numero_sei="111")

        with patch(
            "apps.pca.sei.coletor.coletar",
            return_value={"executado_em": "x", "login": {}, "processos": []},
        ) as coletar_mock:
            call_command("sei_coletar", "--reprocessar-documentos", stdout=StringIO())

        self.assertTrue(coletar_mock.call_args.kwargs["reprocessar_documentos"])

    def test_sem_a_flag_repassa_false(self):
        processo = self.processo(3)
        ProcessoSEI.objects.create(processo=processo, numero_sei="111")

        with patch(
            "apps.pca.sei.coletor.coletar",
            return_value={"executado_em": "x", "login": {}, "processos": []},
        ) as coletar_mock:
            call_command("sei_coletar", stdout=StringIO())

        self.assertFalse(coletar_mock.call_args.kwargs["reprocessar_documentos"])

    def test_linha_de_resumo_conta_relidos_e_preservados_sem_tocar_o_pca(self):
        processo = self.processo(3)
        ProcessoSEI.objects.create(processo=processo, numero_sei="111")
        antes = list(Processo.objects.filter(pk=processo.pk).values())

        dados = {
            "executado_em": "x",
            "login": {},
            "processos": [
                {
                    "numero": "111",
                    "resultado": "ok",
                    "documentos_contratuais": [
                        # Golden number 2 -> 3
                        # (VERSAO_EXTRACAO_DOCUMENTO) junto com o bump da
                        # constante — "relido" exige bater com a versão
                        # ATUAL, nunca com um número fixo.
                        {"id_documento": "1", "versao_extracao": VERSAO_EXTRACAO_DOCUMENTO, "texto_corpo": "x"},
                        {"id_documento": "2", "versao_extracao": VERSAO_EXTRACAO_DOCUMENTO, "do_cache": True},
                        {"id_documento": "3", "reprocessamento_erro": "TimeoutError: x"},
                    ],
                }
            ],
        }
        with patch("apps.pca.sei.coletor.coletar", return_value=dados):
            saida = StringIO()
            call_command("sei_coletar", "--reprocessar-documentos", stdout=saida)

        self.assertIn("documentos relidos: 1 · falhas preservadas: 1", saida.getvalue())
        depois = list(Processo.objects.filter(pk=processo.pk).values())
        self.assertEqual(antes, depois)


class TestSeiAplicar(ComandosSeiBase):
    def _gravar_coleta_item_3(self):
        caminho = self.base / "entrada.json"
        caminho.write_text(json.dumps(_coleta_item_3()), encoding="utf-8")
        return caminho

    def test_simular_imprime_tabela_e_nao_grava(self):
        processo = self.processo(3)
        caminho = self._gravar_coleta_item_3()

        saida = StringIO()
        call_command("sei_aplicar", str(caminho), "--simular", stdout=saida)

        self.assertIn("simulad", saida.getvalue().lower())
        processo.refresh_from_db()
        self.assertIsNone(processo.data_assinatura_contrato)
        self.assertEqual(processo.acompanhamentos.count(), 0)

    def test_sem_simular_grava_e_cria_acompanhamento(self):
        processo = self.processo(3)
        caminho = self._gravar_coleta_item_3()

        call_command("sei_aplicar", str(caminho), stdout=StringIO())

        processo.refresh_from_db()
        self.assertEqual(processo.data_assinatura_contrato, date(2026, 2, 19))
        self.assertEqual(processo.valor_contratado, Decimal("18001.20"))
        self.assertGreater(processo.acompanhamentos.count(), 0)

    def test_arquivo_inexistente_gera_command_error(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("sei_aplicar", str(self.base / "nao-existe.json"), stdout=StringIO())

    def test_json_sem_a_chave_processos_gera_command_error(self):
        # Achado dados B8 (QA 30/09/2026) — JSON válido, mas fora da
        # estrutura esperada (sem "processos"), nunca pode lançar
        # AttributeError/TypeError crus.
        from django.core.management.base import CommandError

        caminho = self.base / "entrada.json"
        caminho.write_text(json.dumps({"outra_coisa": 1}), encoding="utf-8")
        with self.assertRaises(CommandError):
            call_command("sei_aplicar", str(caminho), stdout=StringIO())

    def test_json_processos_nao_e_lista_gera_command_error(self):
        from django.core.management.base import CommandError

        caminho = self.base / "entrada.json"
        caminho.write_text(json.dumps({"processos": "não é lista"}), encoding="utf-8")
        with self.assertRaises(CommandError):
            call_command("sei_aplicar", str(caminho), stdout=StringIO())


class TestSeiSincronizar(ComandosSeiBase):
    def test_lock_presente_ha_menos_de_3h_sai_com_codigo_2(self):
        self.assertTrue(execucoes.adquirir_lock())

        with self.assertRaises(SystemExit) as contexto:
            call_command("sei_sincronizar", stdout=StringIO(), stderr=StringIO())

        self.assertEqual(contexto.exception.code, 2)

    def test_erro_fatal_na_coleta_grava_execucao_status_erro_com_mensagem_cortada(self):
        processo = self.processo(3)
        ProcessoSEI.objects.create(processo=processo, numero_sei="90796110000007.000036/2025-81")

        mensagem_longa = "falha de login " * 100  # bem mais que 500 caracteres
        with patch("apps.pca.sei.coletor.coletar", side_effect=Exception(mensagem_longa)):
            with self.assertRaises(SystemExit) as contexto:
                call_command("sei_sincronizar", stdout=StringIO(), stderr=StringIO())

        self.assertEqual(contexto.exception.code, 1)
        execucao = execucoes.ultima()
        self.assertEqual(execucao["status"], "erro")
        self.assertLessEqual(len(execucao["mensagem"]), 500)

    def test_simular_sem_processos_ativos_grava_execucao_simulado_e_sai_0(self):
        with patch(
            "apps.pca.sei.coletor.coletar",
            return_value={"executado_em": "x", "login": {}, "processos": []},
        ):
            with self.assertRaises(SystemExit) as contexto:
                call_command("sei_sincronizar", "--simular", stdout=StringIO(), stderr=StringIO())

        self.assertEqual(contexto.exception.code, 0)
        execucao = execucoes.ultima()
        self.assertEqual(execucao["status"], "simulado")

    def test_varredura_registra_ultima_consulta_de_cada_item_visitado(self):
        """Item "pulado (sem mudança)" também foi consultado
        — entra em `ultima_consulta.json` com `ok` e a hora do término."""
        processo = self.processo(3)
        ProcessoSEI.objects.create(
            processo=processo, numero_sei="90796110000007.000036/2025-81"
        )
        coleta = {
            "executado_em": "x",
            "login": {},
            "processos": [
                {
                    "numero": "90796110000007.000036/2025-81",
                    "item_pca": 3,
                    "exercicio": 2026,
                    "resultado": "ok",
                    "pulado": True,
                }
            ],
        }
        with patch("apps.pca.sei.coletor.coletar", return_value=coleta):
            with self.assertRaises(SystemExit) as contexto:
                call_command("sei_sincronizar", stdout=StringIO(), stderr=StringIO())

        self.assertEqual(contexto.exception.code, 0)
        mapa = execucoes.carregar_ultima_consulta()
        self.assertEqual(mapa["2026-3"]["resultado"], "ok")
        self.assertEqual(mapa["2026-3"]["data_hora"], execucoes.ultima()["terminado_em"])

    def test_simular_nao_registra_ultima_consulta(self):
        processo = self.processo(3)
        ProcessoSEI.objects.create(
            processo=processo, numero_sei="90796110000007.000036/2025-81"
        )
        coleta = {
            "executado_em": "x",
            "login": {},
            "processos": [
                {
                    "numero": "90796110000007.000036/2025-81",
                    "item_pca": 3,
                    "exercicio": 2026,
                    "resultado": "ok",
                }
            ],
        }
        with patch("apps.pca.sei.coletor.coletar", return_value=coleta):
            with self.assertRaises(SystemExit):
                call_command("sei_sincronizar", "--simular", stdout=StringIO(), stderr=StringIO())

        self.assertEqual(execucoes.carregar_ultima_consulta(), {})

    def test_nunca_instala_nem_chama_cron(self):
        caminho = (
            Path(__file__).resolve().parents[1]
            / "management" / "commands" / "sei_sincronizar.py"
        )
        conteudo = caminho.read_text(encoding="utf-8").lower()
        for proibido in ("crontab", "subprocess", "os.system"):
            self.assertNotIn(proibido, conteudo)

    def test_carrega_e_grava_o_cache_apos_a_coleta(self):
        """Fase 34: `coletor.coletar` recebe
        `cache=` mutável — a mutação feita durante a coleta (simulada aqui
        por `side_effect`) precisa estar em disco depois que o comando
        termina, provando que `execucoes.gravar_cache(cache)` rodou."""
        processo = self.processo(3)
        ProcessoSEI.objects.create(
            processo=processo, numero_sei="90796110000007.000036/2025-81"
        )

        def coletar_fake(alvos, cache=None, forcar=None, progresso=None, **kwargs):
            cache["processos"]["teste"] = {"registros": 1, "primeiro": None}
            return {"executado_em": "x", "login": {}, "processos": []}

        with patch("apps.pca.sei.coletor.coletar", side_effect=coletar_fake):
            with self.assertRaises(SystemExit) as contexto:
                call_command("sei_sincronizar", stdout=StringIO(), stderr=StringIO())

        self.assertEqual(contexto.exception.code, 0)
        self.assertEqual(
            execucoes.ler_cache()["processos"]["teste"], {"registros": 1, "primeiro": None}
        )

    def test_progresso_e_impresso_no_stdout(self):
        """`sei_sincronizar` passa `progresso=` a `coletor.coletar`
        — qualquer linha que o coletor mande via `progresso(...)` aparece no
        `stdout` do comando (o que `docker compose logs -f robo` mostra)."""
        processo = self.processo(3)
        ProcessoSEI.objects.create(
            processo=processo, numero_sei="90796110000007.000036/2025-81"
        )

        def coletar_fake(alvos, cache=None, forcar=None, progresso=None, **kwargs):
            progresso("linha de teste")
            return {"executado_em": "x", "login": {}, "processos": []}

        saida = StringIO()
        with patch("apps.pca.sei.coletor.coletar", side_effect=coletar_fake):
            with self.assertRaises(SystemExit):
                call_command("sei_sincronizar", stdout=saida, stderr=StringIO())

        self.assertIn("linha de teste", saida.getvalue())

    def test_progresso_atualiza_o_lock_com_k_total_durante_a_execucao(self):
        """O lock `em_execucao` só existe DURANTE a
        corrida — a leitura precisa acontecer de dentro do `coletar_fake`,
        antes de `call_command` devolver (`liberar_lock()` já removeu o
        arquivo depois)."""
        processo = self.processo(3)
        ProcessoSEI.objects.create(
            processo=processo, numero_sei="90796110000007.000036/2025-81"
        )
        capturado = {}

        def coletar_fake(alvos, cache=None, forcar=None, progresso=None, **kwargs):
            progresso("item 3 (1/1): coletado em 5.0 s")
            capturado["progresso"] = execucoes.ler_progresso()
            return {"executado_em": "x", "login": {}, "processos": []}

        with patch("apps.pca.sei.coletor.coletar", side_effect=coletar_fake):
            with self.assertRaises(SystemExit):
                call_command("sei_sincronizar", stdout=StringIO(), stderr=StringIO())

        lock = capturado["progresso"]
        self.assertEqual(lock["item"], 3)
        self.assertEqual(lock["k"], 1)
        self.assertEqual(lock["total"], 1)
        self.assertEqual(lock["coletados"], 1)
        self.assertEqual(lock["ultima_linha"], "item 3 (1/1): coletado em 5.0 s")

    def test_grava_log_por_execucao_com_uma_linha_por_chamada_de_progresso(self):
        """`execucoes/<carimbo>.log` recebe uma linha por
        chamada de `progresso` mais a linha final `self.style.SUCCESS(...)`
        do passo 8."""
        processo = self.processo(3)
        ProcessoSEI.objects.create(
            processo=processo, numero_sei="90796110000007.000036/2025-81"
        )

        def coletar_fake(alvos, cache=None, forcar=None, progresso=None, **kwargs):
            progresso("item 3 (1/2): coletado em 5.0 s")
            progresso("item 4 (2/2): pulado (sem mudança no histórico)")
            progresso("coleta concluída: 1 coletados, 1 pulados, 0 erros em 6.0 s")
            return {"executado_em": "x", "login": {}, "processos": []}

        with patch("apps.pca.sei.coletor.coletar", side_effect=coletar_fake):
            with self.assertRaises(SystemExit):
                call_command("sei_sincronizar", stdout=StringIO(), stderr=StringIO())

        arquivos_log = list((self.base / "execucoes").glob("*.log"))
        self.assertEqual(len(arquivos_log), 1)
        linhas = arquivos_log[0].read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(linhas), 4)
        self.assertIn("item 3 (1/2): coletado em 5.0 s", linhas)
        self.assertIn("item 4 (2/2): pulado (sem mudança no histórico)", linhas)
        self.assertIn("coleta concluída: 1 coletados, 1 pulados, 0 erros em 6.0 s", linhas)
        self.assertTrue(any("Sincronização concluída" in linha for linha in linhas))

    def test_grava_series_no_json_de_execucao_quando_ha_apostilamento_qualificado(self):
        """(Fase 35): apostilamento de reajuste global
        qualificado grava a série de valores do item em
        `dados_execucao["series"]`."""
        processo = self.processo(15)
        ProcessoSEI.objects.create(
            processo=processo, numero_sei="90796110000007.000015/2025-44"
        )

        with patch(
            "apps.pca.sei.coletor.coletar",
            return_value=_coleta_item_15(item_pca=15, exercicio=2026),
        ):
            with self.assertRaises(SystemExit) as contexto:
                call_command("sei_sincronizar", stdout=StringIO(), stderr=StringIO())

        self.assertEqual(contexto.exception.code, 0)
        execucao = execucoes.ultima()
        self.assertIn("2026-15", execucao["series"])
        self.assertTrue(execucao["series"]["2026-15"])


class TestSeiAtender(ComandosSeiBase):
    """`atender_um_passo` — sempre chamada direto, nunca via
    `call_command`, com `coletor` injetado (nenhum teste toca Playwright)."""

    def test_sem_pedidos_devolve_none_e_nao_toca_o_lock(self):
        with (
            patch("apps.pca.sei.execucoes.adquirir_lock") as lock_mock,
            patch("apps.pca.sei.execucoes.liberar_lock") as unlock_mock,
        ):
            resultado = atender_um_passo()

        self.assertIsNone(resultado)
        lock_mock.assert_not_called()
        unlock_mock.assert_not_called()

    def test_atende_o_pedido_mais_antigo_primeiro(self):
        processo1 = self.processo(1)
        processo2 = self.processo(2)
        ProcessoSEI.objects.create(processo=processo1, numero_sei="111")
        ProcessoSEI.objects.create(processo=processo2, numero_sei="222")

        with freeze_time("2026-09-18 09:00:00") as congelado:
            execucoes.gravar_pedido(item_pca=1, exercicio=2026, solicitado_por=1)
            congelado.move_to("2026-09-18 10:00:00")
            execucoes.gravar_pedido(item_pca=2, exercicio=2026, solicitado_por=1)
            congelado.move_to("2026-09-18 10:05:00")  # ambos ainda dentro do limite de 2h
            resultado = atender_um_passo(
                coletor=lambda alvos: {
                    "executado_em": "x",
                    "login": {"autenticado": True},
                    "processos": [],
                }
            )

        self.assertEqual(resultado["status"], "ok")
        pendentes = execucoes.listar_pedidos()
        self.assertEqual([p["item_pca"] for p in pendentes], [2])
        atendidos = list((self.base / "pedidos" / "atendidos").glob("*.json"))
        self.assertEqual(len(atendidos), 1)
        conteudo = json.loads(atendidos[0].read_text(encoding="utf-8"))
        self.assertEqual(conteudo["item_pca"], 1)

    def test_pedido_atendido_grava_os_campos_alterados_pelo_aplicador(self):
        """Defeito real do UAT 18/09/2026 (itens 1, 2, 20): o JSON do
        pedido atendido saía com `"campos": []` mesmo quando o aplicador
        gravou 5 campos — `aplicador.aplicar(..., simular=False)` nunca
        preenchia `resumo["alterados"]`."""
        processo = self.processo(3)
        ProcessoSEI.objects.create(
            processo=processo, numero_sei="90796110000007.000036/2025-81"
        )
        execucoes.gravar_pedido(item_pca=3, exercicio=2026, solicitado_por=1)

        resultado = atender_um_passo(coletor=lambda alvos: _coleta_item_3())

        self.assertEqual(resultado["status"], "ok")
        self.assertIn("data_assinatura_contrato", resultado["campos"])
        self.assertIn("valor_contratado", resultado["campos"])

        atendidos = list((self.base / "pedidos" / "atendidos").glob("*.json"))
        self.assertEqual(len(atendidos), 1)
        conteudo = json.loads(atendidos[0].read_text(encoding="utf-8"))
        self.assertIn("data_assinatura_contrato", conteudo["resultado"]["campos"])
        self.assertIn("valor_contratado", conteudo["resultado"]["campos"])

        processo.refresh_from_db()
        self.assertEqual(processo.data_assinatura_contrato, date(2026, 2, 19))
        self.assertEqual(processo.valor_contratado, Decimal("18001.20"))

    def test_pedido_atendido_grava_series_quando_ha_apostilamento_qualificado(self):
        """(Fase 35): `resultado["series"]` (e o JSON
        de `pedidos/atendidos/*.json`) inclui a série de valores calculada
        por `regras.propor()`/`aplicador.aplicar()` quando o item tem
        apostilamento de reajuste global qualificado."""
        processo = self.processo(15)
        ProcessoSEI.objects.create(
            processo=processo, numero_sei="90796110000007.000015/2025-44"
        )
        execucoes.gravar_pedido(item_pca=15, exercicio=2026, solicitado_por=1)

        resultado = atender_um_passo(coletor=lambda alvos: _coleta_item_15())

        self.assertEqual(resultado["status"], "ok")
        self.assertTrue(resultado["series"])

        atendidos = list((self.base / "pedidos" / "atendidos").glob("*.json"))
        self.assertEqual(len(atendidos), 1)
        conteudo = json.loads(atendidos[0].read_text(encoding="utf-8"))
        self.assertTrue(conteudo["resultado"]["series"])

    def test_uma_vez_loga_cada_etapa_do_pedido_no_stdout(self):
        """`sei_atender --uma-vez` só logava a linha de subida (UAT
        18/09/2026) — precisa de uma linha por etapa do pedido, sem nomes
        de pessoas nem credenciais."""
        processo = self.processo(3)
        ProcessoSEI.objects.create(
            processo=processo, numero_sei="90796110000007.000036/2025-81"
        )
        execucoes.gravar_pedido(item_pca=3, exercicio=2026, solicitado_por=1)

        with patch(
            "apps.pca.sei.coletor.coletar", return_value=_coleta_item_3()
        ):
            saida = StringIO()
            call_command("sei_atender", "--uma-vez", stdout=saida)

        linhas = saida.getvalue()
        self.assertIn("pedido item 3 recebido (solicitado_em ", linhas)
        self.assertIn("item 3: login ok / coleta de 1 número(s) concluída em ", linhas)
        self.assertIn("item 3: aplicado — campos: ", linhas)
        self.assertIn("data_assinatura_contrato", linhas)
        self.assertIn("| pendências: ", linhas)
        self.assertIn("| eventos: ", linhas)
        for termo_proibido in ("senha", "usuario_sei", "toniaum", "credencia"):
            self.assertNotIn(termo_proibido, linhas.lower())

    def test_pedido_vencido_loga_descarte_no_stdout(self):
        processo = self.processo(1)
        ProcessoSEI.objects.create(processo=processo, numero_sei="111")

        with freeze_time("2026-09-18 08:00:00"):
            execucoes.gravar_pedido(item_pca=1, exercicio=2026, solicitado_por=1)

        with freeze_time("2026-09-18 11:00:00"):  # 3h depois, acima do limite de 2h
            saida = StringIO()
            call_command("sei_atender", "--uma-vez", stdout=saida)

        self.assertIn("pedido item 1 descartado por prazo", saida.getvalue())

    def test_respeita_lock_da_varredura_noturna(self):
        processo = self.processo(1)
        ProcessoSEI.objects.create(processo=processo, numero_sei="111")
        execucoes.gravar_pedido(item_pca=1, exercicio=2026, solicitado_por=1)
        self.assertTrue(execucoes.adquirir_lock())  # simula varredura noturna em curso

        coletor_fake = Mock(side_effect=AssertionError("coletor não deveria ser chamado"))
        resultado = atender_um_passo(coletor=coletor_fake)

        self.assertEqual(resultado, {"status": "aguardando_lock"})
        coletor_fake.assert_not_called()
        pendentes = execucoes.listar_pedidos()
        self.assertEqual(len(pendentes), 1)
        # lock não foi tocado por este passo (não era dono do lock)
        self.assertTrue((self.base / "em_execucao").exists())

    def test_descarta_pedido_vencido_sem_chamar_o_coletor(self):
        processo = self.processo(1)
        ProcessoSEI.objects.create(processo=processo, numero_sei="111")

        with freeze_time("2026-09-18 08:00:00"):
            execucoes.gravar_pedido(item_pca=1, exercicio=2026, solicitado_por=1)

        coletor_fake = Mock(side_effect=AssertionError("coletor não deveria ser chamado"))
        with freeze_time("2026-09-18 11:00:00"):  # 3h depois, acima do limite de 2h
            resultado = atender_um_passo(coletor=coletor_fake)

        coletor_fake.assert_not_called()
        self.assertIsNone(resultado)  # nada mais na fila após o descarte
        atendidos = list((self.base / "pedidos" / "atendidos").glob("*.json"))
        self.assertEqual(len(atendidos), 1)
        conteudo = json.loads(atendidos[0].read_text(encoding="utf-8"))
        self.assertEqual(conteudo["resultado"]["status"], "descartado_por_prazo")

    def test_erro_de_login_nao_propaga_marca_erro_login_e_libera_lock(self):
        processo = self.processo(1)
        ProcessoSEI.objects.create(processo=processo, numero_sei="111")
        execucoes.gravar_pedido(item_pca=1, exercicio=2026, solicitado_por=1)

        def coletor_com_erro(alvos):
            raise Exception("login recusado")

        resultado = atender_um_passo(coletor=coletor_com_erro)

        self.assertEqual(resultado["status"], "erro_login")
        self.assertIn("login", resultado["mensagem"].lower())
        self.assertFalse((self.base / "em_execucao").exists())  # lock liberado no finally
        atendidos = list((self.base / "pedidos" / "atendidos").glob("*.json"))
        self.assertEqual(len(atendidos), 1)

    def test_coletor_todos_os_numeros_com_erro_marca_status_erro_sem_aplicar(self):
        processo = self.processo(1)
        ProcessoSEI.objects.create(processo=processo, numero_sei="111")
        execucoes.gravar_pedido(item_pca=1, exercicio=2026, solicitado_por=1)

        resultado = atender_um_passo(
            coletor=lambda alvos: {
                "executado_em": "x",
                "login": {"autenticado": True},
                "processos": [
                    {"numero": "111", "resultado": "erro", "erro": "TimeoutError: tempo esgotado"}
                ],
            }
        )

        self.assertEqual(resultado["status"], "erro")
        self.assertIn("TimeoutError", resultado["mensagem"])
        processo.refresh_from_db()
        self.assertIsNone(processo.data_assinatura_contrato)

    def test_coletor_login_nao_autenticado_marca_erro_login_sem_aplicar(self):
        processo = self.processo(1)
        ProcessoSEI.objects.create(processo=processo, numero_sei="111")
        execucoes.gravar_pedido(item_pca=1, exercicio=2026, solicitado_por=1)

        resultado = atender_um_passo(
            coletor=lambda alvos: {
                "executado_em": "x",
                "login": {"autenticado": False, "erro": "credenciais_recusadas"},
                "processos": [],
            }
        )

        self.assertEqual(resultado["status"], "erro_login")
        self.assertIn("credenciais_recusadas", resultado["mensagem"])
        processo.refresh_from_db()
        self.assertIsNone(processo.data_assinatura_contrato)

    def test_coletor_com_pelo_menos_um_numero_ok_continua_aplicando(self):
        processo = self.processo(1)
        ProcessoSEI.objects.create(processo=processo, numero_sei="111")
        ProcessoSEI.objects.create(processo=processo, numero_sei="222")
        execucoes.gravar_pedido(item_pca=1, exercicio=2026, solicitado_por=1)

        resultado = atender_um_passo(
            coletor=lambda alvos: {
                "executado_em": "x",
                "login": {"autenticado": True},
                "processos": [
                    {"numero": "111", "resultado": "ok", "documentos_contratuais": []},
                    {"numero": "222", "resultado": "erro", "erro": "TimeoutError: tempo esgotado"},
                ],
            }
        )

        self.assertEqual(resultado["status"], "ok")

    def test_pedido_para_processo_sem_numero_sei_nao_chama_coletor(self):
        self.processo(1)  # sem ProcessoSEI
        execucoes.gravar_pedido(item_pca=1, exercicio=2026, solicitado_por=1)
        coletor_fake = Mock(side_effect=AssertionError("coletor não deveria ser chamado"))

        resultado = atender_um_passo(coletor=coletor_fake)

        coletor_fake.assert_not_called()
        self.assertEqual(resultado["status"], "erro")

    def test_import_de_playwright_nunca_no_topo_do_arquivo(self):
        caminho = (
            Path(__file__).resolve().parents[1]
            / "management" / "commands" / "sei_atender.py"
        )
        for linha in caminho.read_text(encoding="utf-8").splitlines():
            self.assertFalse(
                linha.startswith("import playwright")
                or linha.startswith("from playwright")
                or linha.startswith("from apps.pca.sei.coletor")
                or linha.startswith("from apps.pca.sei import coletor"),
                f"import de coletor/playwright fora de função: {linha!r}",
            )


class TestSeiAtenderColetorReal(ComandosSeiBase):
    """`_coletor_real` (Fase 34) isolada de
    `atender_um_passo` — os testes acima injetam `coletor=<fake de 1
    argumento>`, mantendo `coletor_fn(alvos)` sem `cache`/`forcar`; só
    `_coletor_real` (produção) carrega/grava o cache e chama
    `coletor.coletar(..., forcar=True)`."""

    def test_coletor_real_chama_coletar_com_forcar_true(self):
        from apps.pca.management.commands.sei_atender import _coletor_real

        with patch(
            "apps.pca.sei.coletor.coletar",
            return_value={"executado_em": "x", "login": {}, "processos": []},
        ) as coletar_mock:
            _coletor_real([{"item_pca": 1, "exercicio": 2026, "numero_sei": "111"}])

        self.assertTrue(coletar_mock.call_args.kwargs["forcar"])

    def test_coletor_real_carrega_e_grava_o_cache(self):
        from apps.pca.management.commands.sei_atender import _coletor_real

        def coletar_fake(alvos, cache=None, forcar=None, **kwargs):
            cache["processos"]["teste"] = {"registros": 1, "primeiro": None}
            return {"executado_em": "x", "login": {}, "processos": []}

        with patch("apps.pca.sei.coletor.coletar", side_effect=coletar_fake):
            _coletor_real([{"item_pca": 1, "exercicio": 2026, "numero_sei": "111"}])

        self.assertEqual(
            execucoes.ler_cache()["processos"]["teste"], {"registros": 1, "primeiro": None}
        )


class _SeiProibidoComandos:
    """`sei` falso que lança `AssertionError` em QUALQUER chamada — mesmo
    papel de `_SEIProibido` de `test_sei_coletor.py`, redefinido aqui para
    não acoplar os dois módulos de teste. Prova, nos testes de integração
    de `sei_sincronizar`/`_coletor_real` abaixo, que o pulo por coleta
    recente da extensão realmente evita abrir o
    processo no navegador."""

    def _proibido(self, *args, **kwargs):
        raise AssertionError("coletor_um chamou o SEI apesar do pulo por extensão recente")

    def __getattr__(self, nome):
        return self._proibido


class _SeiFakeRegistraChamadasComandos:
    """`sei` falso com métodos `Mock` (mesmo padrão de `SEIFalso` de
    `test_sei_coletor.py`) — usado quando o teste PRECISA que `coletar_um`
    chegue a abrir o processo (prova de que `forcar=True` continua
    bypassando o pulo)."""

    def __init__(self):
        self.abrir_processo = Mock(return_value={"titulo_confere": True, "id_procedimento": "1"})
        self.url_historico = Mock(return_value="https://sei.cfc.org.br/sei/historico")
        self.historico_resumo = Mock(
            return_value={
                "registros": 1,
                "primeiro": {"data_hora": "01/01/2026 08:00", "unidade": "X", "descricao": "y"},
            }
        )
        self.abrir_todas_pastas = Mock(return_value={})
        self.documentos = Mock(return_value=[])
        self.historico = Mock(return_value={"marcos": {"primeiro": None, "ultimo": None}})
        self.ler_documento = Mock(return_value={})


def _coletar_de_verdade_com(sei_fake):
    """Fábrica de `side_effect` para `apps.pca.sei.coletor.coletar`: em vez
    de um dict canônico fixo, chama o `coletor.coletar_um` REAL (a função
    com o pulo desta fase) por `alvo`, com `sei_fake` injetado no lugar do
    navegador — mesmo princípio de `_SEIProibido`/`SEIFalso` de
    `test_sei_coletor.py`, aqui a nível de integração do comando inteiro.
    Nunca entra em `sync_playwright` (convenções do projeto: coletor sempre mockado no
    nível de `coletor.coletar`), mas exercita de verdade a decisão de pulo
    de `coletor.coletar_um`."""

    def _fn(alvos, cache=None, forcar=False, progresso=None, extensao=None,
            pular_se_extensao_h=24.0, reprocessar_documentos=False):
        processos = []
        for alvo in alvos:
            r = coletor.coletar_um(
                sei_fake,
                alvo["numero_sei"],
                cache=cache,
                forcar=forcar,
                extensao=extensao,
                pular_se_extensao_h=pular_se_extensao_h,
            )
            r["item_pca"] = alvo["item_pca"]
            r["exercicio"] = alvo["exercicio"]
            processos.append(r)
        return {"executado_em": "x", "login": {"autenticado": True}, "processos": processos}

    return _fn


class TestSeiSincronizarExtensao(ComandosSeiBase):
    """`sei_sincronizar` carrega `extensao.json` e
    repassa `extensao`/`pular_se_extensao_h` a `coletor.coletar`, pulando
    (sem abrir o navegador) qualquer número com coleta recente da
    extensão — `sei_sincronizar` NUNCA escreve em `extensao.json` (só lê,
    `execucoes.gravar_extensao` existe só para seed de teste)."""

    def _semear_extensao(self, numero_sei, coleta, horas_atras=1, usuario_id=7):
        recebido_em = (django_timezone.now() - timedelta(hours=horas_atras)).isoformat()
        execucoes.gravar_extensao({
            "processos": {
                numero_sei: {"coleta": coleta, "recebido_em": recebido_em, "usuario_id": usuario_id}
            }
        })

    @override_settings(SEI_PULAR_SE_EXTENSAO_H=24)  # independe do .env (produção usa 12)
    def test_repassa_extensao_e_pular_se_extensao_h_para_coletor_coletar(self):
        processo = self.processo(3)
        ProcessoSEI.objects.create(processo=processo, numero_sei="90796110000007.000036/2025-81")
        self._semear_extensao("90796110000007.000036/2025-81", {"resultado": "ok"})

        with patch(
            "apps.pca.sei.coletor.coletar",
            return_value={"executado_em": "x", "login": {}, "processos": []},
        ) as coletar_mock:
            with self.assertRaises(SystemExit):
                call_command("sei_sincronizar", stdout=StringIO(), stderr=StringIO())

        kwargs = coletar_mock.call_args.kwargs
        self.assertEqual(
            kwargs["extensao"]["processos"]["90796110000007.000036/2025-81"]["coleta"],
            {"resultado": "ok"},
        )
        self.assertEqual(kwargs["pular_se_extensao_h"], 24)

    def test_sei_sincronizar_nunca_grava_extensao_json(self):
        processo = self.processo(3)
        ProcessoSEI.objects.create(processo=processo, numero_sei="90796110000007.000036/2025-81")
        self._semear_extensao("90796110000007.000036/2025-81", {"resultado": "ok"})
        antes = execucoes.ler_extensao()

        with patch(
            "apps.pca.sei.coletor.coletar",
            return_value={"executado_em": "x", "login": {}, "processos": []},
        ):
            with self.assertRaises(SystemExit):
                call_command("sei_sincronizar", stdout=StringIO(), stderr=StringIO())

        self.assertEqual(execucoes.ler_extensao(), antes)

    def test_numero_com_coleta_recente_da_extensao_aplica_sem_chamar_o_sei(self):
        """Ponta a ponta, sem canned dict: a "coleta" armazenada em
        `extensao.json` (fixture real `coleta_item_3.json`) é a ÚNICA fonte
        do processo coletado — `coletor.coletar_um` real decide pular
        ANTES de abrir o processo (sei `_SeiProibidoComandos` lançaria se
        fosse chamado), e o resultado ainda assim chega alterado ao banco
        pelas mesmas `regras.propor`/`aplicador.aplicar`."""
        processo = self.processo(3)
        ProcessoSEI.objects.create(processo=processo, numero_sei="90796110000007.000036/2025-81")
        coleta = _coleta_item_3(item_pca=3, exercicio=2026)["processos"][0]
        self._semear_extensao("90796110000007.000036/2025-81", coleta)

        with patch(
            "apps.pca.sei.coletor.coletar",
            side_effect=_coletar_de_verdade_com(_SeiProibidoComandos()),
        ):
            with self.assertRaises(SystemExit) as contexto:
                call_command("sei_sincronizar", stdout=StringIO(), stderr=StringIO())

        self.assertEqual(contexto.exception.code, 0)
        execucao = execucoes.ultima()
        alterado_item_3 = next(
            (a for a in execucao["alterados"] if a["item"] == 3), None
        )
        self.assertIsNotNone(alterado_item_3)
        self.assertIn("data_assinatura_contrato", alterado_item_3["campos"])
        processo.refresh_from_db()
        self.assertEqual(processo.valor_contratado, Decimal("18001.20"))


class TestSeiAtenderColetorRealExtensao(ComandosSeiBase):
    """`_coletor_real` (produção de `sei_atender`)
    também carrega e repassa `extensao`/`pular_se_extensao_h` — mesmo
    contrato uniforme dos três comandos. `forcar=True` (default de
    `_coletor_real`) sempre bypassa o pulo NA PRÁTICA — comportamento
    documentado, não bug a esconder (ver `<behavior>` do plano)."""

    @override_settings(SEI_PULAR_SE_EXTENSAO_H=24)  # independe do .env (produção usa 12)
    def test_coletor_real_repassa_extensao_e_pular_se_extensao_h(self):
        from apps.pca.management.commands.sei_atender import _coletor_real

        with patch(
            "apps.pca.sei.coletor.coletar",
            return_value={"executado_em": "x", "login": {}, "processos": []},
        ) as coletar_mock:
            _coletor_real([{"item_pca": 1, "exercicio": 2026, "numero_sei": "111"}])

        kwargs = coletar_mock.call_args.kwargs
        self.assertIn("extensao", kwargs)
        self.assertEqual(kwargs["pular_se_extensao_h"], 24)

    def test_forcar_true_continua_abrindo_o_processo_mesmo_com_extensao_recente(self):
        from apps.pca.management.commands.sei_atender import _coletor_real

        recebido_em = (django_timezone.now() - timedelta(hours=1)).isoformat()
        execucoes.gravar_extensao({
            "processos": {
                "111": {"coleta": {"resultado": "ok"}, "recebido_em": recebido_em, "usuario_id": 7}
            }
        })
        sei_fake = _SeiFakeRegistraChamadasComandos()

        with patch(
            "apps.pca.sei.coletor.coletar", side_effect=_coletar_de_verdade_com(sei_fake)
        ):
            _coletor_real([{"item_pca": 1, "exercicio": 2026, "numero_sei": "111"}])

        sei_fake.abrir_processo.assert_called_once()
