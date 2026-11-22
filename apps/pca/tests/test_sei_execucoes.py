"""Testes de `apps.pca.sei.execucoes` (Fase 32). Todo teste roda contra um diretório temporário — nunca
`BASE_DIR/data` de verdade — via `tempfile.TemporaryDirectory()` +
`@override_settings(SEI_DATA_DIR=...)`, o mesmo requisito
("os testes do card não podem depender de `/app/data` gravável")."""

import json
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from django.test import TestCase, override_settings
from django.utils import timezone
from freezegun import freeze_time

from apps.pca.sei import execucoes


class DiretorioTemporarioBase(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._override = override_settings(SEI_DATA_DIR=self._tmp.name)
        self._override.enable()
        self.addCleanup(self._override.disable)
        self.base = Path(self._tmp.name)


class TestDiretorioBase(DiretorioTemporarioBase):
    def test_diretorio_base_le_a_setting(self):
        self.assertEqual(execucoes.diretorio_base(), self.base)

    def test_diretorio_base_sem_setting_cai_no_fallback_de_base_dir(self):
        self._override.disable()
        with override_settings(SEI_DATA_DIR=None):
            from django.conf import settings

            self.assertEqual(
                execucoes.diretorio_base(), Path(settings.BASE_DIR) / "data" / "sei"
            )
        self._override.enable()


class TestNovoCarimbo(DiretorioTemporarioBase):
    def test_formato_do_carimbo(self):
        carimbo = execucoes.novo_carimbo()
        # AAAA-MM-DD-HHMM
        self.assertRegex(carimbo, r"^\d{4}-\d{2}-\d{2}-\d{4}$")


class TestGravarColetaEExecucao(DiretorioTemporarioBase):
    def test_gravar_coleta_cria_arquivo_json(self):
        caminho = execucoes.gravar_coleta("2026-09-18-1400", {"processos": []})
        self.assertTrue(caminho.exists())
        self.assertEqual(caminho, self.base / "coletas" / "2026-09-18-1400.json")
        self.assertEqual(json.loads(caminho.read_text(encoding="utf-8")), {"processos": []})

    def test_gravar_execucao_cria_arquivo_json(self):
        caminho = execucoes.gravar_execucao("2026-09-18-1400", {"status": "ok"})
        self.assertTrue(caminho.exists())
        self.assertEqual(caminho, self.base / "execucoes" / "2026-09-18-1400.json")

    def test_gravar_coleta_serializa_date_e_decimal_do_documento(self):
        # Deferred de 33-02 (deferred-items.md): extracao.extrair_vigencia/
        # extrair_prorrogacao devolvem `date` Python direto; `valor_contratado`
        # pode chegar como Decimal. json.dumps sem encoder lançava TypeError.
        dados = {
            "processos": [
                {
                    "item_pca": 6,
                    "valor_contratado": Decimal("38731.90"),
                    "documentos": [
                        {
                            "vigencia": {
                                "inicio": date(2026, 1, 11),
                                "fim": date(2027, 1, 10),
                                "forma": "prazo",
                            },
                            "prorrogacao": {
                                "inicio": date(2026, 1, 11),
                                "fim": date(2027, 1, 10),
                            },
                        }
                    ],
                }
            ]
        }
        caminho = execucoes.gravar_coleta("2026-09-18-1400", dados)
        relido = json.loads(caminho.read_text(encoding="utf-8"))
        documento = relido["processos"][0]["documentos"][0]
        self.assertEqual(documento["vigencia"]["inicio"], "2026-01-11")
        self.assertEqual(documento["vigencia"]["fim"], "2027-01-10")
        self.assertEqual(documento["prorrogacao"]["inicio"], "2026-01-11")
        self.assertEqual(documento["prorrogacao"]["fim"], "2027-01-10")
        self.assertEqual(relido["processos"][0]["valor_contratado"], "38731.90")


class TestUltima(DiretorioTemporarioBase):
    def test_none_com_diretorio_inexistente(self):
        self.assertIsNone(execucoes.ultima())

    def test_none_com_diretorio_vazio(self):
        (self.base / "execucoes").mkdir(parents=True)
        self.assertIsNone(execucoes.ultima())

    def test_devolve_a_mais_recente_das_tres(self):
        execucoes.gravar_execucao("2026-09-16-0800", {"status": "ok", "ordem": 1})
        execucoes.gravar_execucao("2026-09-17-0800", {"status": "ok", "ordem": 2})
        execucoes.gravar_execucao("2026-09-18-0800", {"status": "erro", "ordem": 3})
        self.assertEqual(execucoes.ultima(), {"status": "erro", "ordem": 3})


class TestEstadoDePendencias(DiretorioTemporarioBase):
    def test_vazio_quando_nao_existe(self):
        self.assertEqual(execucoes.carregar_estado_pendencias(), {})

    def test_grava_e_recarrega(self):
        execucoes.gravar_estado_pendencias({"2026-3": ["unilateral:1204703"]})
        self.assertEqual(
            execucoes.carregar_estado_pendencias(), {"2026-3": ["unilateral:1204703"]}
        )


class TestGravacaoAtomica(DiretorioTemporarioBase):
    """Achado dados M7 (QA 30/09/2026) — `_gravar_json` nunca deixa um
    arquivo `.tmp-*` para trás."""

    def test_gravar_json_nunca_deixa_arquivo_tmp_para_tras(self):
        execucoes.gravar_estado_pendencias({"2026-1": []})
        self.assertEqual(list(self.base.glob("*.tmp-*")), [])
        self.assertEqual(execucoes.carregar_estado_pendencias(), {"2026-1": []})


class TestLeituraTolerante(DiretorioTemporarioBase):
    """Achado dados M7 — um `estado.json`/`ultima_consulta.json` corrompido
    vira `{}` (padrão), nunca uma exceção crua."""

    def test_json_corrompido_e_tratado_como_ausente(self):
        (self.base / "estado.json").write_text("{não é json", encoding="utf-8")
        self.assertEqual(execucoes.carregar_estado_pendencias(), {})


class TestLock(DiretorioTemporarioBase):
    def test_adquire_quando_nao_existe(self):
        self.assertTrue(execucoes.adquirir_lock())
        self.assertTrue((self.base / "em_execucao").exists())

    def test_bloqueia_com_lock_recente(self):
        agora = timezone.now()
        with freeze_time(agora):
            self.assertTrue(execucoes.adquirir_lock())
        with freeze_time(agora + timedelta(hours=2, minutes=59)):
            self.assertFalse(execucoes.adquirir_lock())

    def test_libera_com_lock_vencido(self):
        agora = timezone.now()
        with freeze_time(agora):
            self.assertTrue(execucoes.adquirir_lock())
        with freeze_time(agora + timedelta(hours=3, minutes=1)):
            self.assertTrue(execucoes.adquirir_lock())

    def test_liberar_lock_remove_arquivo(self):
        execucoes.adquirir_lock()
        execucoes.liberar_lock()
        self.assertFalse((self.base / "em_execucao").exists())

    def test_liberar_lock_sem_arquivo_nao_lanca(self):
        execucoes.liberar_lock()  # não deve lançar FileNotFoundError


class TestAtualizarProgresso(DiretorioTemporarioBase):
    """`atualizar_progresso`."""

    def test_grava_k_total_preservando_pid_carimbo_iniciado_em(self):
        execucoes.adquirir_lock()
        lock_antes = execucoes.ler_progresso()

        execucoes.atualizar_progresso(
            lock_antes["carimbo"],
            item=3,
            k=1,
            total=5,
            coletados=1,
            pulados=0,
            erros=0,
            ultima_linha="item 3 (1/5): coletado em 4.0 s",
        )

        lock_depois = execucoes.ler_progresso()
        self.assertEqual(lock_depois["pid"], lock_antes["pid"])
        self.assertEqual(lock_depois["carimbo"], lock_antes["carimbo"])
        self.assertEqual(lock_depois["iniciado_em"], lock_antes["iniciado_em"])
        self.assertEqual(lock_depois["item"], 3)
        self.assertEqual(lock_depois["k"], 1)
        self.assertEqual(lock_depois["total"], 5)
        self.assertEqual(lock_depois["coletados"], 1)
        self.assertEqual(lock_depois["ultima_linha"], "item 3 (1/5): coletado em 4.0 s")
        self.assertIn("atualizado_em", lock_depois)

    def test_chamada_sem_lock_presente_nao_recria_o_arquivo(self):
        execucoes.atualizar_progresso(
            "2026-09-18-2100",
            item=1,
            k=1,
            total=1,
            coletados=1,
            pulados=0,
            erros=0,
            ultima_linha="item 1 (1/1): coletado em 1.0 s",
        )
        self.assertFalse((self.base / "em_execucao").exists())


class TestLerProgresso(DiretorioTemporarioBase):
    """`ler_progresso`."""

    def test_sem_arquivo_devolve_none(self):
        self.assertIsNone(execucoes.ler_progresso())

    def test_lock_recente_com_k_total_devolve_dict_completo(self):
        execucoes.adquirir_lock()
        carimbo = execucoes.ler_progresso()["carimbo"]
        execucoes.atualizar_progresso(
            carimbo, item=2, k=1, total=3, coletados=1, pulados=0, erros=0,
            ultima_linha="item 2 (1/3): coletado em 2.0 s",
        )
        progresso = execucoes.ler_progresso()
        self.assertEqual(progresso["k"], 1)
        self.assertEqual(progresso["total"], 3)

    def test_lock_formato_antigo_sem_total_devolve_dict_sem_essas_chaves(self):
        execucoes.adquirir_lock()
        progresso = execucoes.ler_progresso()
        self.assertIsNotNone(progresso)
        self.assertNotIn("total", progresso)
        self.assertIn("carimbo", progresso)

    def test_lock_com_3h_ou_mais_devolve_none(self):
        agora = timezone.now()
        with freeze_time(agora):
            execucoes.adquirir_lock()
        with freeze_time(agora + timedelta(hours=3, minutes=1)):
            self.assertIsNone(execucoes.ler_progresso())


class TestAbrirLogExecucao(DiretorioTemporarioBase):
    def test_cria_o_arquivo_na_primeira_chamada(self):
        log = execucoes.abrir_log_execucao("2026-09-18-2100")
        log("primeira linha")
        caminho = self.base / "execucoes" / "2026-09-18-2100.log"
        self.assertTrue(caminho.exists())
        self.assertEqual(caminho.read_text(encoding="utf-8"), "primeira linha\n")

    def test_acumula_linhas_em_chamadas_seguintes(self):
        log = execucoes.abrir_log_execucao("2026-09-18-2100")
        log("linha 1")
        log("linha 2")
        log("linha 3")
        caminho = self.base / "execucoes" / "2026-09-18-2100.log"
        self.assertEqual(
            caminho.read_text(encoding="utf-8"), "linha 1\nlinha 2\nlinha 3\n"
        )


class TestInterpretarLinhaProgresso(DiretorioTemporarioBase):
    def test_coletado(self):
        info = execucoes.interpretar_linha_progresso("item 6 (2/10): coletado em 12.34 s")
        self.assertEqual(info, {"item": 6, "k": 2, "total": 10, "resultado": "coletado"})

    def test_pulado(self):
        info = execucoes.interpretar_linha_progresso(
            "item 6 (2/10): pulado (sem mudança no histórico)"
        )
        self.assertEqual(info["resultado"], "pulado")

    def test_erro(self):
        info = execucoes.interpretar_linha_progresso(
            "item 6 (2/10): erro — TimeoutError: x"
        )
        self.assertEqual(info["resultado"], "erro")

    def test_linha_final_devolve_none(self):
        self.assertIsNone(
            execucoes.interpretar_linha_progresso(
                "coleta concluída: 8 coletados, 100 pulados, 2 erros em 312.5 s"
            )
        )

    def test_string_qualquer_devolve_none(self):
        self.assertIsNone(execucoes.interpretar_linha_progresso("qualquer coisa"))


class TestRetencao(DiretorioTemporarioBase):
    def test_mantem_os_60_mais_recentes(self):
        nomes = [f"2026-01-{dia:02d}-0800" for dia in range(1, 32)] + [
            f"2026-02-{dia:02d}-0800" for dia in range(1, 29)
        ] + [f"2026-03-{dia:02d}-0800" for dia in range(1, 7)]
        self.assertEqual(len(nomes), 65)
        # Grava fora de ordem cronológica de propósito — a retenção decide
        # por NOME (carimbo), não pela ordem de criação no disco.
        for nome in sorted(nomes, key=lambda n: hash(n)):
            execucoes.gravar_coleta(nome, {"carimbo": nome})

        apagados = execucoes.aplicar_retencao("coletas", manter=60)

        self.assertEqual(apagados, 5)
        restantes = sorted(p.stem for p in (self.base / "coletas").glob("*.json"))
        self.assertEqual(restantes, sorted(nomes)[5:])
        self.assertEqual(len(restantes), 60)

    def test_pasta_inexistente_devolve_zero(self):
        self.assertEqual(execucoes.aplicar_retencao("coletas", manter=60), 0)

    def test_mantem_par_json_log_pelo_mesmo_carimbo(self):
        nomes = [f"2026-01-{dia:02d}-0800" for dia in range(1, 32)] + [
            f"2026-02-{dia:02d}-0800" for dia in range(1, 29)
        ] + [f"2026-03-{dia:02d}-0800" for dia in range(1, 7)]
        self.assertEqual(len(nomes), 65)
        for nome in nomes:
            execucoes.gravar_execucao(nome, {"carimbo": nome})
            execucoes.abrir_log_execucao(nome)(f"linha de {nome}")

        apagados = execucoes.aplicar_retencao("execucoes", manter=60)

        self.assertEqual(apagados, 5)
        restantes_json = sorted(p.stem for p in (self.base / "execucoes").glob("*.json"))
        restantes_log = sorted(p.stem for p in (self.base / "execucoes").glob("*.log"))
        self.assertEqual(restantes_json, sorted(nomes)[5:])
        self.assertEqual(restantes_log, sorted(nomes)[5:])
        self.assertEqual(len(restantes_json), 60)
        self.assertEqual(len(restantes_log), 60)


class TestFilaDePedidos(DiretorioTemporarioBase):
    def test_gravar_pedido_duas_vezes_mesmo_item_sobrescreve(self):
        execucoes.gravar_pedido(item_pca=3, exercicio=2026, solicitado_por=7)
        execucoes.gravar_pedido(item_pca=3, exercicio=2026, solicitado_por=9)
        arquivos = list((self.base / "pedidos").glob("*.json"))
        self.assertEqual(len(arquivos), 1)
        dados = json.loads(arquivos[0].read_text(encoding="utf-8"))
        self.assertEqual(dados["solicitado_por"], 9)

    def test_listar_pedidos_em_ordem_de_solicitacao(self):
        agora = timezone.now()
        with freeze_time(agora):
            execucoes.gravar_pedido(item_pca=10, exercicio=2026, solicitado_por=1)
        with freeze_time(agora + timedelta(minutes=5)):
            execucoes.gravar_pedido(item_pca=3, exercicio=2026, solicitado_por=2)
        pedidos = execucoes.listar_pedidos()
        self.assertEqual([pedido["item_pca"] for pedido in pedidos], [10, 3])

    def test_listar_pedidos_ignora_subpasta_atendidos(self):
        execucoes.gravar_pedido(item_pca=3, exercicio=2026, solicitado_por=1)
        pasta_atendidos = self.base / "pedidos" / "atendidos"
        pasta_atendidos.mkdir(parents=True)
        (pasta_atendidos / "2026-01-01-0000-99.json").write_text("{}", encoding="utf-8")
        pedidos = execucoes.listar_pedidos()
        self.assertEqual(len(pedidos), 1)
        self.assertEqual(pedidos[0]["item_pca"], 3)

    def test_descartar_pedidos_vencidos(self):
        agora = timezone.now()
        with freeze_time(agora):
            execucoes.gravar_pedido(item_pca=3, exercicio=2026, solicitado_por=1)
        with freeze_time(agora + timedelta(hours=2, minutes=5)):
            descartados = execucoes.descartar_pedidos_vencidos(limite_horas=2)

        self.assertEqual(len(descartados), 1)
        self.assertEqual(descartados[0]["item_pca"], 3)
        self.assertEqual(execucoes.listar_pedidos(), [])
        atendidos = list((self.base / "pedidos" / "atendidos").glob("*.json"))
        self.assertEqual(len(atendidos), 1)
        dados = json.loads(atendidos[0].read_text(encoding="utf-8"))
        self.assertEqual(dados["resultado"]["status"], "descartado_por_prazo")

    def test_descartar_pedidos_vencidos_preserva_pedido_recente(self):
        agora = timezone.now()
        with freeze_time(agora):
            execucoes.gravar_pedido(item_pca=3, exercicio=2026, solicitado_por=1)
        with freeze_time(agora + timedelta(minutes=30)):
            descartados = execucoes.descartar_pedidos_vencidos(limite_horas=2)
        self.assertEqual(descartados, [])
        self.assertEqual(len(execucoes.listar_pedidos()), 1)

    def test_pedido_com_data_sem_fuso_nao_derruba_o_descarte(self):
        # Achado dados M7 — um pedido gravado manualmente (ou por uma versão
        # anterior de `gravar_pedido`) sem offset ("solicitado_em" naive)
        # nunca pode derrubar o laço do robô com TypeError.
        pasta = self.base / "pedidos"
        pasta.mkdir(parents=True)
        (pasta / "2026-3.json").write_text(
            json.dumps(
                {
                    "item_pca": 3,
                    "exercicio": 2026,
                    "solicitado_por": 1,
                    "solicitado_em": "2020-01-01T00:00:00",
                }
            ),
            encoding="utf-8",
        )
        descartados = execucoes.descartar_pedidos_vencidos(limite_horas=2)
        self.assertEqual([d["item_pca"] for d in descartados], [3])
        self.assertEqual(execucoes.listar_pedidos(), [])

    def test_mover_pedido_para_atendidos_remove_original(self):
        execucoes.gravar_pedido(item_pca=3, exercicio=2026, solicitado_por=1)
        pedido = execucoes.listar_pedidos()[0]
        arquivo_original = pedido["_arquivo"]
        resultado = {
            "status": "ok",
            "campos": ["data_assinatura_contrato"],
            "pendencias": [],
            "mensagem": None,
            "atendido_em": timezone.localtime().isoformat(),
        }
        execucoes.mover_pedido_para_atendidos(pedido, resultado)
        self.assertFalse(Path(arquivo_original).exists())
        atendidos = list((self.base / "pedidos" / "atendidos").glob("*.json"))
        self.assertEqual(len(atendidos), 1)
        dados = json.loads(atendidos[0].read_text(encoding="utf-8"))
        self.assertNotIn("_arquivo", dados)
        self.assertEqual(dados["resultado"]["status"], "ok")


class TestCache(DiretorioTemporarioBase):
    """`ler_cache()`/`gravar_cache()` (Fase 34) — mesmo
    padrão de `carregar_estado_pendencias`/`gravar_estado_pendencias`, exceto
    que sem arquivo devolve as duas chaves vazias (nunca `{}`)."""

    def test_sem_arquivo_devolve_estrutura_vazia_das_duas_chaves(self):
        self.assertEqual(execucoes.ler_cache(), {"processos": {}, "documentos": {}})

    def test_round_trip_com_processos_e_documentos(self):
        cache = {
            "processos": {
                "90796110000007.000036/2025-81": {
                    "registros": 259,
                    "primeiro": {
                        "data_hora": "18/09/2026 10:00",
                        "unidade": "GELIC",
                        "descricao": "Processo recebido na unidade GELIC",
                    },
                    "coletado_em": "2026-09-18T10:00:00-03:00",
                    "id_procedimento": "1043956",
                }
            },
            "documentos": {
                "9999999": {
                    "id_documento": "9999999",
                    "protocolo": "1204703",
                    "tipo": "contrato",
                    "conteudo": "html",
                    "lido_em": "2026-09-18T10:05:00-03:00",
                }
            },
        }
        execucoes.gravar_cache(cache)
        self.assertEqual(execucoes.ler_cache(), cache)

    def test_ler_cache_nao_vaza_entre_diretorios_temporarios_distintos(self):
        execucoes.gravar_cache(
            {"processos": {"1": {"registros": 1}}, "documentos": {}}
        )
        self.assertEqual(
            execucoes.ler_cache(),
            {"processos": {"1": {"registros": 1}}, "documentos": {}},
        )
        # Um segundo diretório temporário (outro teste, mesmo padrão) nunca
        # veria o que foi gravado aqui — cada teste usa seu próprio tempfile
        # via DiretorioTemporarioBase.setUp, provado indiretamente pelo teste
        # anterior (test_sem_arquivo_devolve_estrutura_vazia_das_duas_chaves)
        # sempre partir vazio mesmo depois deste gravar.


class TestUltimoPedidoAtendido(DiretorioTemporarioBase):
    """`ultimo_pedido_atendido()` (Fase 34) — sempre
    preparado via `gravar_pedido`/`mover_pedido_para_atendidos`, nunca JSON
    escrito à mão (mesmo padrão do restante do arquivo)."""

    def _atender(self, *, item_pca, exercicio, status, quando):
        with freeze_time(quando):
            execucoes.gravar_pedido(
                item_pca=item_pca, exercicio=exercicio, solicitado_por=1
            )
            pedido = execucoes.listar_pedidos()[-1]
            resultado = {
                "status": status,
                "campos": [],
                "pendencias": [],
                "mensagem": None,
                "atendido_em": timezone.localtime().isoformat(),
            }
            execucoes.mover_pedido_para_atendidos(pedido, resultado)

    def test_sem_pasta_atendidos_devolve_none(self):
        self.assertIsNone(execucoes.ultimo_pedido_atendido())

    def test_pasta_vazia_devolve_none(self):
        (self.base / "pedidos" / "atendidos").mkdir(parents=True)
        self.assertIsNone(execucoes.ultimo_pedido_atendido())

    def test_um_arquivo_atendido_hoje(self):
        agora = timezone.now()
        self._atender(item_pca=5, exercicio=2026, status="ok", quando=agora)
        resultado = execucoes.ultimo_pedido_atendido()
        self.assertEqual(resultado["item_pca"], 5)
        self.assertEqual(resultado["status"], "ok")
        self.assertEqual(resultado["atendidos_hoje"], 1)

    def test_dois_hoje_um_ontem_conta_so_hoje_e_pega_o_mais_recente(self):
        agora = timezone.now()
        ontem = agora - timedelta(days=1)
        self._atender(item_pca=1, exercicio=2026, status="ok", quando=ontem)
        self._atender(item_pca=2, exercicio=2026, status="ok", quando=agora)
        self._atender(
            item_pca=3,
            exercicio=2026,
            status="ok",
            quando=agora + timedelta(minutes=5),
        )
        resultado = execucoes.ultimo_pedido_atendido()
        self.assertEqual(resultado["atendidos_hoje"], 2)
        self.assertEqual(resultado["item_pca"], 3)

    def test_status_diferente_de_ok_vira_erro(self):
        agora = timezone.now()
        self._atender(item_pca=7, exercicio=2026, status="erro_login", quando=agora)
        resultado = execucoes.ultimo_pedido_atendido()
        self.assertEqual(resultado["status"], "erro")


class TestUltimaConsulta(DiretorioTemporarioBase):
    def test_vazio_quando_nao_existe(self):
        self.assertEqual(execucoes.carregar_ultima_consulta(), {})

    def test_registrar_e_recarregar(self):
        execucoes.registrar_ultima_consulta(
            3, 2026, {"data_hora": "2026-09-18T14:33:10-03:00", "resultado": "ok"}
        )
        execucoes.registrar_ultima_consulta(
            10, 2026, {"data_hora": "2026-09-18T14:40:00-03:00", "resultado": "erro"}
        )
        estado = execucoes.carregar_ultima_consulta()
        self.assertEqual(estado["2026-3"]["resultado"], "ok")
        self.assertEqual(estado["2026-10"]["resultado"], "erro")


class TestUltimasConsultasDaVarredura(DiretorioTemporarioBase):
    """A varredura registra a última consulta de CADA
    item visitado (antes só `sei_atender` gravava, por pedido individual;
    a ficha do assistente dizia "SEI: não disponível" para todo o resto)."""

    def test_resumir_ok_quando_todos_os_processos_do_item_vieram_ok(self):
        # Lote 6 do QA 30/09/2026 (achado dados A3) — `resumir_consultas_da_
        # coleta` agora chaveia por `(item_pca, exercicio)`, nunca só
        # `item_pca`, para não misturar dois exercícios abertos ao mesmo
        # tempo.
        processos = [
            {"numero": "a", "item_pca": 3, "exercicio": 2026, "resultado": "ok", "pulado": True},
            {"numero": "b", "item_pca": 3, "exercicio": 2026, "resultado": "ok"},
            {"numero": "c", "item_pca": 7, "exercicio": 2026, "resultado": "nao_encontrado"},
            {"numero": "d", "exercicio": 2026, "resultado": "ok"},  # sem item_pca: ignorado
            {"numero": "e", "item_pca": 11, "resultado": "ok"},  # sem exercicio: ignorado
        ]
        mapa = execucoes.resumir_consultas_da_coleta(processos, "2026-09-21T04:06:45-03:00")
        self.assertEqual(
            mapa,
            {
                (3, 2026): {"data_hora": "2026-09-21T04:06:45-03:00", "resultado": "ok"},
                (7, 2026): {"data_hora": "2026-09-21T04:06:45-03:00", "resultado": "erro"},
            },
        )

    def test_registrar_em_lote_preserva_entradas_de_outros_itens(self):
        execucoes.registrar_ultima_consulta(
            10, 2026, {"data_hora": "2026-09-18T14:40:00-03:00", "resultado": "erro"}
        )
        execucoes.registrar_ultimas_consultas(
            {(3, 2026): {"data_hora": "2026-09-21T04:06:45-03:00", "resultado": "ok"}}
        )
        estado = execucoes.carregar_ultima_consulta()
        self.assertEqual(estado["2026-3"]["resultado"], "ok")
        self.assertEqual(estado["2026-10"]["resultado"], "erro")


class TestChaveItem(DiretorioTemporarioBase):
    """`chave_item`/`decompor_chave_item` (Lote 6 do QA 30/09/2026, achado
    dados A3) — chave composta ano-item."""

    def test_chave_item_formata_exercicio_hifen_item(self):
        self.assertEqual(execucoes.chave_item(14, 2026), "2026-14")

    def test_decompor_chave_item_devolve_item_e_exercicio(self):
        self.assertEqual(execucoes.decompor_chave_item("2026-14"), (14, 2026))

    def test_decompor_chave_item_fora_do_formato_lanca_value_error(self):
        with self.assertRaises(ValueError):
            execucoes.decompor_chave_item("quatorze")


class TestRetrocompatibilidadeEstadoPendencias(DiretorioTemporarioBase):
    """Um `estado.json` gravado em produção ANTES da chave composta
    ano-item (só o nº do item) continua sendo lido corretamente,
    reinterpretado como o exercício 2026 (achado dados A3)."""

    def test_chave_antiga_so_item_e_reinterpretada_como_2026(self):
        (self.base / "estado.json").write_text(
            json.dumps({"3": ["unilateral:1204703"]}), encoding="utf-8"
        )
        self.assertEqual(
            execucoes.carregar_estado_pendencias(), {"2026-3": ["unilateral:1204703"]}
        )


class TestRetrocompatibilidadeUltimaConsulta(DiretorioTemporarioBase):
    """Mesmo padrão acima, para `ultima_consulta.json`."""

    def test_chave_antiga_so_item_e_reinterpretada_como_2026(self):
        (self.base / "ultima_consulta.json").write_text(
            json.dumps({"14": {"data_hora": "2026-09-18T14:33:10-03:00", "resultado": "ok"}}),
            encoding="utf-8",
        )
        estado = execucoes.carregar_ultima_consulta()
        self.assertEqual(estado["2026-14"]["resultado"], "ok")
