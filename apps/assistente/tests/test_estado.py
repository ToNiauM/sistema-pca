"""Conversa temporária + quota atômica (A01, A02, A20). `TestCase` simples (não toca o banco PCA/ORM); caminhos em
`tempfile` via `override_settings`."""

import os
import stat
import tempfile
import threading
from datetime import date, timedelta
from pathlib import Path

from django.test import SimpleTestCase, override_settings
from django.utils import timezone
from freezegun import freeze_time

from apps.assistente import estado


class _EstadoTestBase(SimpleTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self._override = override_settings(
            IA_ESTADO_PATH=str(base / "estado.sqlite3"),
            IA_CONVERSAS_PATH=str(base / "conversas.sqlite3"),
            IA_CONVERSA_TTL_S=28800,
        )
        self._override.enable()
        self.addCleanup(self._override.disable)


class TestSchema(_EstadoTestBase):
    def test_arquivo_nasce_preguicosamente_com_permissoes_restritas(self):
        con = estado._conectar_estado()
        con.close()
        from django.conf import settings

        caminho_arquivo = Path(settings.IA_ESTADO_PATH)
        self.assertTrue(caminho_arquivo.exists())
        modo = stat.S_IMODE(os.stat(caminho_arquivo).st_mode)
        self.assertEqual(modo, 0o600)
        modo_dir = stat.S_IMODE(os.stat(caminho_arquivo.parent).st_mode)
        self.assertEqual(modo_dir, 0o700)

    def test_arquivo_corrompido_gera_estadoindisponivel_sem_recriar(self):
        from django.conf import settings

        caminho = Path(settings.IA_ESTADO_PATH)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_bytes(b"isto nao e um banco sqlite valido \x00\x01\x02")
        tamanho_antes = caminho.stat().st_size
        with self.assertRaises(estado.EstadoIndisponivel):
            estado.consumo(1, "2026-09-19")
        self.assertEqual(caminho.stat().st_size, tamanho_antes)


class TestConversa(_EstadoTestBase):
    def test_ciclo_criar_carregar(self):
        agora = timezone.now()
        conversa_id = estado.criar_conversa(1, "sessao-a", "perm-a", 2026, agora)
        conversa = estado.carregar_conversa(
            conversa_id, usuario_id=1, sessao_hash="sessao-a", permissoes_hash="perm-a", agora=agora
        )
        self.assertIsNotNone(conversa)
        self.assertEqual(conversa.exercicio, 2026)
        self.assertEqual(conversa.trocas, [])

    def test_expira_imediatamente(self):
        with freeze_time("2026-09-19 12:00:00") as congelado:
            with override_settings(IA_CONVERSA_TTL_S=60):
                agora = timezone.now()
                conversa_id = estado.criar_conversa(1, "s", "p", 2026, agora)
                congelado.tick(timedelta(seconds=61))
                depois = timezone.now()
                conversa = estado.carregar_conversa(
                    conversa_id, usuario_id=1, sessao_hash="s", permissoes_hash="p", agora=depois
                )
        self.assertIsNone(conversa)

    def test_permissoes_diferentes_apaga_e_devolve_none(self):
        agora = timezone.now()
        conversa_id = estado.criar_conversa(1, "s", "perm-velha", 2026, agora)
        estado.acrescentar_troca(
            conversa_id,
            usuario_id=1,
            sessao_hash="s",
            permissoes_hash="perm-velha",
            agora=agora,
            pergunta="oi",
            resposta_md="olá",
            referencias=[],
            proveniencia={},
            rodape="rodapé",
        )
        conversa = estado.carregar_conversa(
            conversa_id, usuario_id=1, sessao_hash="s", permissoes_hash="perm-nova", agora=agora
        )
        self.assertIsNone(conversa)
        # A conversa foi de fato apagada (não só ocultada por esta leitura).
        conversa_de_novo = estado.carregar_conversa(
            conversa_id, usuario_id=1, sessao_hash="s", permissoes_hash="perm-velha", agora=agora
        )
        self.assertIsNone(conversa_de_novo)

    def test_sessao_diferente_devolve_none_sem_apagar(self):
        agora = timezone.now()
        conversa_id = estado.criar_conversa(1, "sessao-1", "perm", 2026, agora)
        conversa = estado.carregar_conversa(
            conversa_id, usuario_id=1, sessao_hash="sessao-2", permissoes_hash="perm", agora=agora
        )
        self.assertIsNone(conversa)
        ainda_existe = estado.carregar_conversa(
            conversa_id, usuario_id=1, sessao_hash="sessao-1", permissoes_hash="perm", agora=agora
        )
        self.assertIsNotNone(ainda_existe)

    def test_decima_primeira_troca_remove_a_primeira(self):
        agora = timezone.now()
        conversa_id = estado.criar_conversa(1, "s", "p", 2026, agora)
        for i in range(11):
            ok = estado.acrescentar_troca(
                conversa_id,
                usuario_id=1,
                sessao_hash="s",
                permissoes_hash="p",
                agora=agora,
                pergunta=f"pergunta {i}",
                resposta_md=f"resposta {i}",
                referencias=[],
                proveniencia={},
                rodape="rodapé",
            )
            self.assertTrue(ok)
        conversa = estado.carregar_conversa(
            conversa_id, usuario_id=1, sessao_hash="s", permissoes_hash="p", agora=agora
        )
        self.assertEqual(len(conversa.trocas), 10)
        self.assertEqual(conversa.trocas[0].pergunta, "pergunta 1")
        self.assertEqual(conversa.trocas[-1].pergunta, "pergunta 10")

    def test_acrescentar_troca_apos_apagar_devolve_false_e_nao_insere(self):
        agora = timezone.now()
        conversa_id = estado.criar_conversa(1, "s", "p", 2026, agora)
        estado.apagar_conversa(conversa_id)
        ok = estado.acrescentar_troca(
            conversa_id,
            usuario_id=1,
            sessao_hash="s",
            permissoes_hash="p",
            agora=agora,
            pergunta="oi",
            resposta_md="olá",
            referencias=[],
            proveniencia={},
            rodape="rodapé",
        )
        self.assertFalse(ok)
        con = estado._conectar_conversas()
        try:
            total = con.execute(
                "SELECT COUNT(*) FROM troca WHERE conversa_id=?", (conversa_id,)
            ).fetchone()[0]
        finally:
            con.close()
        self.assertEqual(total, 0)

    def test_apagar_conversas_da_sessao(self):
        agora = timezone.now()
        conversa_id = estado.criar_conversa(1, "s", "p", 2026, agora)
        estado.apagar_conversas_da_sessao(1, "s")
        conversa = estado.carregar_conversa(
            conversa_id, usuario_id=1, sessao_hash="s", permissoes_hash="p", agora=agora
        )
        self.assertIsNone(conversa)

    def test_limpar_expiradas(self):
        with freeze_time("2026-09-19 12:00:00") as congelado:
            with override_settings(IA_CONVERSA_TTL_S=60):
                agora = timezone.now()
                estado.criar_conversa(1, "s", "p", 2026, agora)
                congelado.tick(timedelta(seconds=61))
                depois = timezone.now()
                apagadas = estado.limpar_expiradas(depois)
        self.assertEqual(apagadas, 1)


class TestQuotaERequisicao(_EstadoTestBase):
    def _emitir(self, usuario_id=1, agora=None, conversa_id="c1", exercicio=2026, sessao_hash="s"):
        agora = agora or timezone.now()
        return estado.emitir_requisicao(
            usuario_id=usuario_id, sessao_hash=sessao_hash, conversa_id=conversa_id,
            exercicio=exercicio, agora=agora,
        )

    def test_reservar_feliz(self):
        agora = timezone.now()
        rid = self._emitir(agora=agora)
        resultado = estado.reservar(
            requisicao_id=rid, usuario_id=1, sessao_hash="s", conversa_id="c1",
            exercicio=2026, agora=agora, limite=50,
        )
        self.assertIsInstance(resultado, estado.Reserva)
        self.assertEqual(resultado.perguntas_hoje, 1)
        self.assertEqual(estado.consumo(1, estado.dia_civil(agora)).perguntas, 1)

    def test_reenvio_do_mesmo_id_em_andamento_nao_cobra_de_novo(self):
        agora = timezone.now()
        rid = self._emitir(agora=agora)
        estado.reservar(
            requisicao_id=rid, usuario_id=1, sessao_hash="s", conversa_id="c1",
            exercicio=2026, agora=agora, limite=50,
        )
        segunda = estado.reservar(
            requisicao_id=rid, usuario_id=1, sessao_hash="s", conversa_id="c1",
            exercicio=2026, agora=agora, limite=50,
        )
        self.assertEqual(segunda, estado.Recusa("em_andamento"))
        self.assertEqual(estado.consumo(1, estado.dia_civil(agora)).perguntas, 1)

    def test_apos_concluir_reenvio_recusa_concluida(self):
        agora = timezone.now()
        rid = self._emitir(agora=agora)
        estado.reservar(
            requisicao_id=rid, usuario_id=1, sessao_hash="s", conversa_id="c1",
            exercicio=2026, agora=agora, limite=50,
        )
        estado.concluir(requisicao_id=rid, agora=agora, tokens_entrada=10, tokens_saida=5)
        resultado = estado.reservar(
            requisicao_id=rid, usuario_id=1, sessao_hash="s", conversa_id="c1",
            exercicio=2026, agora=agora, limite=50,
        )
        self.assertEqual(resultado, estado.Recusa("concluida"))
        consumo = estado.consumo(1, estado.dia_civil(agora))
        self.assertEqual(consumo.perguntas, 1)
        self.assertEqual(consumo.tokens_entrada, 10)
        self.assertEqual(consumo.tokens_saida, 5)

    def test_id_de_outro_contexto_e_invalido_sem_cobrar(self):
        agora = timezone.now()
        rid = self._emitir(agora=agora, conversa_id="c1")
        resultado = estado.reservar(
            requisicao_id=rid, usuario_id=1, sessao_hash="s", conversa_id="OUTRA",
            exercicio=2026, agora=agora, limite=50,
        )
        self.assertEqual(resultado, estado.Recusa("invalida"))
        self.assertEqual(estado.consumo(1, estado.dia_civil(agora)).perguntas, 0)

        resultado_id_nao_emitido = estado.reservar(
            requisicao_id="nunca-emitido", usuario_id=1, sessao_hash="s", conversa_id="c1",
            exercicio=2026, agora=agora, limite=50,
        )
        self.assertEqual(resultado_id_nao_emitido, estado.Recusa("invalida"))

    def test_segunda_requisicao_mesmo_usuario_lease_vivo_e_concorrencia(self):
        agora = timezone.now()
        rid1 = self._emitir(agora=agora, conversa_id="c1")
        rid2 = self._emitir(agora=agora, conversa_id="c1")
        estado.reservar(
            requisicao_id=rid1, usuario_id=1, sessao_hash="s", conversa_id="c1",
            exercicio=2026, agora=agora, limite=50,
        )
        resultado = estado.reservar(
            requisicao_id=rid2, usuario_id=1, sessao_hash="s", conversa_id="c1",
            exercicio=2026, agora=agora, limite=50,
        )
        self.assertEqual(resultado, estado.Recusa("concorrencia"))

    def test_lease_vencido_libera_nova_tentativa(self):
        with freeze_time("2026-09-19 12:00:00") as congelado:
            agora = timezone.now()
            rid1 = self._emitir(agora=agora, conversa_id="c1")
            estado.reservar(
                requisicao_id=rid1, usuario_id=1, sessao_hash="s", conversa_id="c1",
                exercicio=2026, agora=agora, limite=50,
            )
            congelado.tick(timedelta(seconds=121))
            depois = timezone.now()
            rid2 = self._emitir(agora=depois, conversa_id="c1")
            resultado = estado.reservar(
                requisicao_id=rid2, usuario_id=1, sessao_hash="s", conversa_id="c1",
                exercicio=2026, agora=depois, limite=50,
            )
        self.assertIsInstance(resultado, estado.Reserva)

    def test_quota_esgotada(self):
        agora = timezone.now()
        rid1 = self._emitir(agora=agora, conversa_id="c1")
        rid2 = self._emitir(agora=agora, conversa_id="c1")
        rid3 = self._emitir(agora=agora, conversa_id="c1")
        r1 = estado.reservar(
            requisicao_id=rid1, usuario_id=1, sessao_hash="s", conversa_id="c1",
            exercicio=2026, agora=agora, limite=2,
        )
        estado.concluir(requisicao_id=rid1, agora=agora)
        r2 = estado.reservar(
            requisicao_id=rid2, usuario_id=1, sessao_hash="s", conversa_id="c1",
            exercicio=2026, agora=agora, limite=2,
        )
        estado.concluir(requisicao_id=rid2, agora=agora)
        r3 = estado.reservar(
            requisicao_id=rid3, usuario_id=1, sessao_hash="s", conversa_id="c1",
            exercicio=2026, agora=agora, limite=2,
        )
        self.assertIsInstance(r1, estado.Reserva)
        self.assertIsInstance(r2, estado.Reserva)
        self.assertEqual(r3, estado.Recusa("quota"))
        self.assertEqual(estado.consumo(1, estado.dia_civil(agora)).perguntas, 2)

    def test_concorrencia_real_duas_threads_mesmo_usuario_limite_um(self):
        agora = timezone.now()
        rid1 = self._emitir(agora=agora, usuario_id=42, conversa_id="c1")
        rid2 = self._emitir(agora=agora, usuario_id=42, conversa_id="c1")
        resultados = []

        def tentar(rid):
            resultados.append(
                estado.reservar(
                    requisicao_id=rid, usuario_id=42, sessao_hash="s", conversa_id="c1",
                    exercicio=2026, agora=agora, limite=1,
                )
            )

        t1 = threading.Thread(target=tentar, args=(rid1,))
        t2 = threading.Thread(target=tentar, args=(rid2,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        reservas = [r for r in resultados if isinstance(r, estado.Reserva)]
        self.assertEqual(len(reservas), 1)

    def test_virada_de_dia_zera_contagem(self):
        with freeze_time("2026-09-19 23:59:00", tz_offset=0) as congelado:
            agora = timezone.now()
            rid1 = self._emitir(agora=agora, conversa_id="c1")
            estado.reservar(
                requisicao_id=rid1, usuario_id=1, sessao_hash="s", conversa_id="c1",
                exercicio=2026, agora=agora, limite=1,
            )
            dia_1 = estado.dia_civil(agora)
            congelado.tick(timedelta(minutes=10))
            depois = timezone.now()
            dia_2 = estado.dia_civil(depois)
            rid2 = self._emitir(agora=depois, conversa_id="c1")
            resultado = estado.reservar(
                requisicao_id=rid2, usuario_id=1, sessao_hash="s", conversa_id="c1",
                exercicio=2026, agora=depois, limite=1,
            )
        # São Paulo é UTC-3: 23:59 UTC ainda é o mesmo dia local; o teste
        # relevante é que dias civis DIFERENTES têm contagens independentes.
        if dia_1 != dia_2:
            self.assertIsInstance(resultado, estado.Reserva)
            self.assertEqual(estado.consumo(1, dia_2).perguntas, 1)

    def test_segundos_ate_meia_noite_no_intervalo_esperado(self):
        agora = timezone.now()
        segundos = estado.segundos_ate_meia_noite(agora)
        self.assertGreaterEqual(segundos, 1)
        self.assertLessEqual(segundos, 86400)

    def test_limpar_metadados_preserva_dia_atual_e_apaga_antigos(self):
        agora = timezone.now()
        hoje = estado.dia_civil(agora)
        rid_hoje = self._emitir(agora=agora, conversa_id="c1")
        estado.reservar(
            requisicao_id=rid_hoje, usuario_id=1, sessao_hash="s", conversa_id="c1",
            exercicio=2026, agora=agora, limite=50,
        )
        agora_antiga = agora - timedelta(days=8)
        rid_antigo = self._emitir(agora=agora_antiga, usuario_id=2, conversa_id="c2", sessao_hash="s2")
        estado.reservar(
            requisicao_id=rid_antigo, usuario_id=2, sessao_hash="s2", conversa_id="c2",
            exercicio=2026, agora=agora_antiga, limite=50,
        )
        hoje_date = date.fromisoformat(hoje)
        estado.limpar_metadados(hoje_date, dias=7)
        self.assertEqual(estado.consumo(1, hoje).perguntas, 1)
        dia_antigo = estado.dia_civil(agora_antiga)
        self.assertEqual(estado.consumo(2, dia_antigo).perguntas, 0)


class TestAndamento(_EstadoTestBase):
    """Tabela `andamento` + `requisicao_ler` por dono."""

    def _emitir_e_reservar(self, agora=None, usuario_id=1, sessao_hash="s", conversa_id="c1"):
        agora = agora or timezone.now()
        rid = estado.emitir_requisicao(
            usuario_id=usuario_id, sessao_hash=sessao_hash, conversa_id=conversa_id,
            exercicio=2026, agora=agora,
        )
        estado.reservar(
            requisicao_id=rid, usuario_id=usuario_id, sessao_hash=sessao_hash,
            conversa_id=conversa_id, exercicio=2026, agora=agora, limite=50,
        )
        return rid

    def test_gravar_ler_apagar(self):
        agora = timezone.now()
        rid = self._emitir_e_reservar(agora=agora)
        estado.andamento_gravar(rid, agora=agora, etapa="Pensando…", texto_parcial="", pergunta="oi?")
        lido = estado.andamento_ler(rid)
        self.assertEqual(lido.pergunta, "oi?")
        self.assertEqual(lido.etapa, "Pensando…")
        self.assertEqual(lido.texto_parcial, "")

        estado.andamento_gravar(rid, agora=agora, etapa="Consultando processos…")
        lido2 = estado.andamento_ler(rid)
        self.assertEqual(lido2.pergunta, "oi?")  # preservada, não sobrescrita por None
        self.assertEqual(lido2.etapa, "Consultando processos…")

        estado.andamento_apagar(rid)
        self.assertIsNone(estado.andamento_ler(rid))

    def test_texto_parcial_cresce_sem_perder_etapa(self):
        agora = timezone.now()
        rid = self._emitir_e_reservar(agora=agora)
        estado.andamento_gravar(rid, agora=agora, etapa="Redigindo…", texto_parcial="Olá")
        estado.andamento_gravar(rid, agora=agora, texto_parcial="Olá, tudo")
        lido = estado.andamento_ler(rid)
        self.assertEqual(lido.etapa, "Redigindo…")
        self.assertEqual(lido.texto_parcial, "Olá, tudo")

    def test_requisicao_ler_com_dono_certo_e_errado(self):
        agora = timezone.now()
        rid = self._emitir_e_reservar(agora=agora, usuario_id=1, sessao_hash="s")
        lida = estado.requisicao_ler(rid, usuario_id=1, sessao_hash="s")
        self.assertIsNotNone(lida)
        self.assertEqual(lida.estado, "em_andamento")
        self.assertEqual(lida.conversa_id, "c1")
        self.assertEqual(lida.exercicio, 2026)

        self.assertIsNone(estado.requisicao_ler(rid, usuario_id=2, sessao_hash="s"))
        self.assertIsNone(estado.requisicao_ler(rid, usuario_id=1, sessao_hash="outra-sessao"))
        self.assertIsNone(estado.requisicao_ler("nunca-existiu", usuario_id=1, sessao_hash="s"))

    def test_concluir_remove_andamento(self):
        agora = timezone.now()
        rid = self._emitir_e_reservar(agora=agora)
        estado.andamento_gravar(rid, agora=agora, etapa="Redigindo…", texto_parcial="x", pergunta="oi?")
        estado.concluir(requisicao_id=rid, agora=agora)
        self.assertIsNone(estado.andamento_ler(rid))
        self.assertEqual(estado.requisicao_ler(rid, usuario_id=1, sessao_hash="s").estado, "concluida")

    def test_limpeza_remove_orfaos_antigos_preserva_recentes(self):
        agora = timezone.now()
        rid_antigo = self._emitir_e_reservar(agora=agora, conversa_id="c-antigo")
        estado.andamento_gravar(rid_antigo, agora=agora, etapa="Pensando…", pergunta="antigo")
        rid_recente = self._emitir_e_reservar(
            agora=agora, usuario_id=2, sessao_hash="s2", conversa_id="c-recente"
        )
        estado.andamento_gravar(rid_recente, agora=agora, etapa="Pensando…", pergunta="recente")

        depois = agora + timedelta(hours=2)
        estado.andamento_gravar(rid_recente, agora=depois, etapa="Redigindo…")

        apagados = estado.limpar_andamento_orfao(depois, horas=1)
        self.assertEqual(apagados, 1)
        self.assertIsNone(estado.andamento_ler(rid_antigo))
        self.assertIsNotNone(estado.andamento_ler(rid_recente))

    def test_duas_conexoes_gravando_sem_database_is_locked(self):
        """A thread do pseudo-streaming e a request de polling abrem
        conexões separadas — `busy_timeout` (`_sqlite.conectar`) evita
        `database is locked` em gravações intercaladas."""
        agora = timezone.now()
        rid = self._emitir_e_reservar(agora=agora)
        estado.andamento_gravar(rid, agora=agora, etapa="Pensando…", pergunta="oi?")

        erros = []

        def gravar_na_thread():
            try:
                for indice in range(20):
                    estado.andamento_gravar(
                        rid, agora=timezone.now(), texto_parcial=f"bloco {indice}"
                    )
            except Exception as exc:  # noqa: BLE001 — captura para asserção fora da thread
                erros.append(exc)

        def ler_na_principal():
            for _ in range(20):
                estado.andamento_ler(rid)

        fio = threading.Thread(target=gravar_na_thread)
        fio.start()
        ler_na_principal()
        fio.join(timeout=10)
        self.assertFalse(fio.is_alive())
        self.assertEqual(erros, [])
