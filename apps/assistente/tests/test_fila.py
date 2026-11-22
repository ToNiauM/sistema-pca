"""Fila própria de reindexação do Assistente do PCA (Fase 39 —,
A14). `TestGravarEListar`/`TestConsumirUmPedido`/
`TestDescartarVencidosEAplicarRetencao` isolam só os caminhos auxiliares
em `tempfile` (`SimpleTestCase`, sem ORM). `TestIntegracaoAtenderUmPasso`
espelha `apps.pca.tests.test_sei_comandos::TestSeiAtender` — mesma base
(`SEI_DATA_DIR` em tempfile + `IA_*` em tempfile), provando prioridade
SEI e o consumo real via `atender_um_passo`."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from freezegun import freeze_time

from apps.assistente import fila, indice
from apps.catalogo.models import (
    Categoria,
    Exercicio,
    SituacaoExercicio,
    SituacaoNormalizada,
    Tipo,
    Unidade,
)
from apps.pca.management.commands.sei_atender import atender_um_passo
from apps.pca.models import Estado, Processo, ProcessoSEI
from apps.pca.sei import execucoes


def _resumo_falso(**overrides):
    valores = dict(geracao=1, novos=0, reaproveitados=0, removidos=0, tokens=0, duracao_s=0.0)
    valores.update(overrides)
    return indice.ResumoIndexacao(**valores)


class _FilaTestBase(SimpleTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self._override = override_settings(
            IA_ESTADO_PATH=str(self.base / "estado.sqlite3"),
            IA_INDICE_PATH=str(self.base / "indice.sqlite3"),
            IA_CONVERSAS_PATH=str(self.base / "conversas.sqlite3"),
        )
        self._override.enable()
        self.addCleanup(self._override.disable)


class TestGravarEListar(_FilaTestBase):
    def test_gravar_pedido_cria_json_pendente_sem_nome_nem_email(self):
        agora = timezone.now()
        caminho = fila.gravar_pedido_reindexacao(solicitado_por=7, agora=agora)

        self.assertTrue(caminho.exists())
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        self.assertEqual(dados["estado"], "pendente")
        self.assertEqual(dados["solicitado_por"], 7)
        self.assertFalse(dados["completo"])
        self.assertNotIn("nome", dados)
        self.assertNotIn("email", dados)

    def test_listar_pedidos_so_pendentes_ordenado_por_solicitado_em(self):
        with freeze_time("2026-09-19 10:00:00") as congelado:
            fila.gravar_pedido_reindexacao(solicitado_por=1, agora=timezone.now())
            congelado.move_to("2026-09-19 11:00:00")
            caminho2 = fila.gravar_pedido_reindexacao(solicitado_por=2, agora=timezone.now())

        dados2 = json.loads(caminho2.read_text(encoding="utf-8"))
        dados2["estado"] = "concluido"
        caminho2.write_text(json.dumps(dados2), encoding="utf-8")

        pedidos = fila.listar_pedidos()
        self.assertEqual([p["solicitado_por"] for p in pedidos], [1])


class TestConsumirUmPedido(_FilaTestBase):
    def test_indexar_falso_marca_concluido_com_contadores(self):
        agora = timezone.now()
        fila.gravar_pedido_reindexacao(solicitado_por=1, agora=agora)
        indexar_falso = lambda cliente, *, completo, agora, stdout=None: _resumo_falso(  # noqa: E731
            geracao=3, novos=5, reaproveitados=10, removidos=1, tokens=100
        )

        resultado = fila.consumir_um_pedido(
            agora=agora, cliente_fabrica=lambda: object(), indexar=indexar_falso
        )

        self.assertEqual(resultado, {"status": "ok", "geracao": 3})
        arquivo = next((self.base / "pedidos").glob("*.json"))
        pedido = json.loads(arquivo.read_text(encoding="utf-8"))
        self.assertEqual(pedido["estado"], "concluido")
        self.assertEqual(pedido["geracao"], 3)
        self.assertEqual(pedido["novos"], 5)
        self.assertEqual(pedido["reaproveitados"], 10)
        self.assertEqual(pedido["removidos"], 1)
        self.assertEqual(pedido["tokens"], 100)

    def test_cliente_fabrica_none_marca_erro_sem_chave_sem_levantar(self):
        agora = timezone.now()
        fila.gravar_pedido_reindexacao(solicitado_por=1, agora=agora)

        resultado = fila.consumir_um_pedido(agora=agora, cliente_fabrica=lambda: None)

        self.assertEqual(resultado, {"status": "erro", "motivo": "sem_chave"})
        arquivo = next((self.base / "pedidos").glob("*.json"))
        pedido = json.loads(arquivo.read_text(encoding="utf-8"))
        self.assertEqual(pedido["estado"], "erro")
        self.assertEqual(pedido["erro_codigo"], "sem_chave")

    def test_indice_ocupado_devolve_pedido_a_pendente(self):
        agora = timezone.now()
        fila.gravar_pedido_reindexacao(solicitado_por=1, agora=agora)

        def indexar_ocupado(cliente, *, completo, agora, stdout=None):
            raise indice.IndiceOcupado("indexação já em andamento")

        resultado = fila.consumir_um_pedido(
            agora=agora, cliente_fabrica=lambda: object(), indexar=indexar_ocupado
        )

        self.assertEqual(resultado, {"status": "aguardando_lock_indice"})
        pendentes = fila.listar_pedidos()
        self.assertEqual(len(pendentes), 1)
        self.assertEqual(pendentes[0]["solicitado_por"], 1)

    def test_excecao_generica_marca_erro_com_nome_da_classe_sem_o_texto(self):
        agora = timezone.now()
        fila.gravar_pedido_reindexacao(solicitado_por=1, agora=agora)

        def indexar_com_erro(cliente, *, completo, agora, stdout=None):
            raise RuntimeError("segredo")

        resultado = fila.consumir_um_pedido(
            agora=agora, cliente_fabrica=lambda: object(), indexar=indexar_com_erro
        )

        self.assertEqual(resultado, {"status": "erro"})
        arquivo = next((self.base / "pedidos").glob("*.json"))
        conteudo = arquivo.read_text(encoding="utf-8")
        pedido = json.loads(conteudo)
        self.assertEqual(pedido["estado"], "erro")
        self.assertEqual(pedido["erro_codigo"], "RuntimeError")
        self.assertNotIn("segredo", conteudo)

    def test_dois_pedidos_so_um_consumido_por_chamada(self):
        # Todo o teste roda dentro do MESMO relógio congelado — chamar
        # `consumir_um_pedido` fora do `with` compararia `solicitado_em`
        # (congelado) contra `timezone.now()` real dentro de
        # `descartar_vencidos`, marcando os dois pedidos como vencidos por
        # um gap de relógio artificial, não pelo comportamento sob teste.
        with freeze_time("2026-09-19 10:00:00") as congelado:
            fila.gravar_pedido_reindexacao(solicitado_por=1, agora=timezone.now())
            congelado.move_to("2026-09-19 11:00:00")
            fila.gravar_pedido_reindexacao(solicitado_por=2, agora=timezone.now())

            fila.consumir_um_pedido(
                agora=timezone.now(),
                cliente_fabrica=lambda: object(),
                indexar=lambda cliente, *, completo, agora, stdout=None: _resumo_falso(),
            )

            pendentes = fila.listar_pedidos()

        self.assertEqual(len(pendentes), 1)
        self.assertEqual(pendentes[0]["solicitado_por"], 2)

    def test_sem_pedido_nenhum_devolve_none(self):
        resultado = fila.consumir_um_pedido(agora=timezone.now())
        self.assertIsNone(resultado)


class TestDescartarVencidosEAplicarRetencao(_FilaTestBase):
    def test_descartar_vencidos_marca_erro_e_some_da_listagem(self):
        with freeze_time("2026-09-19 08:00:00"):
            fila.gravar_pedido_reindexacao(solicitado_por=1, agora=timezone.now())

        with freeze_time("2026-09-19 15:00:00"):  # 7h depois, acima do limite default de 6h
            descartados = fila.descartar_vencidos()
            pendentes = fila.listar_pedidos()

        self.assertEqual(len(descartados), 1)
        self.assertEqual(pendentes, [])

    def test_aplicar_retencao_mantem_so_os_mais_recentes_concluidos_ou_erro(self):
        agora = timezone.now()
        for numero in range(5):
            caminho = fila.gravar_pedido_reindexacao(solicitado_por=numero, agora=agora)
            dados = json.loads(caminho.read_text(encoding="utf-8"))
            dados["estado"] = "concluido"
            caminho.write_text(json.dumps(dados), encoding="utf-8")

        removidos = fila.aplicar_retencao(manter=2)

        self.assertEqual(removidos, 3)
        self.assertEqual(len(list((self.base / "pedidos").glob("*.json"))), 2)


class TestIntegracaoAtenderUmPasso(TestCase):
    """Espelha `apps.pca.tests.test_sei_comandos::TestSeiAtender` — mesma
    base (`SEI_DATA_DIR` em tempfile), com os 3 caminhos `IA_*` também em
    tempfile (nunca o `data/ia/` real do container)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self._override = override_settings(
            SEI_DATA_DIR=str(self.base / "sei"),
            IA_ESTADO_PATH=str(self.base / "ia" / "estado.sqlite3"),
            IA_INDICE_PATH=str(self.base / "ia" / "indice.sqlite3"),
            IA_CONVERSAS_PATH=str(self.base / "ia" / "conversas.sqlite3"),
            IA_API_KEY="",
        )
        self._override.enable()
        self.addCleanup(self._override.disable)

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
        )
        valores.update(overrides)
        return Processo.objects.create(**valores)

    def test_pedido_sei_tem_prioridade_sobre_pedido_de_reindexacao(self):
        processo = self.processo(1)
        ProcessoSEI.objects.create(processo=processo, numero_sei="111")
        execucoes.gravar_pedido(item_pca=1, exercicio=2026, solicitado_por=1)
        fila.gravar_pedido_reindexacao(solicitado_por=2, agora=timezone.now())

        resultado = atender_um_passo(
            coletor=lambda alvos: {"executado_em": "x", "login": {"autenticado": True}, "processos": []}
        )

        self.assertEqual(resultado["status"], "ok")
        pendentes_reindexacao = fila.listar_pedidos()
        self.assertEqual(len(pendentes_reindexacao), 1)
        self.assertEqual(pendentes_reindexacao[0]["solicitado_por"], 2)

    @override_settings(IA_API_KEY="chave-de-teste")
    def test_sem_pedido_sei_consome_pedido_de_reindexacao(self):
        fila.gravar_pedido_reindexacao(solicitado_por=1, agora=timezone.now())

        with patch("apps.assistente.fila.indice.indexar", return_value=_resumo_falso()) as mock_indexar:
            resultado = atender_um_passo()

        self.assertEqual(resultado, {"status": "ok", "geracao": 1})
        mock_indexar.assert_called_once()
        self.assertEqual(fila.listar_pedidos(), [])

    def test_limpar_se_necessario_chamado_a_cada_passagem_toca_marcador(self):
        atender_um_passo()

        marcador = self.base / "ia" / "ultima_limpeza"
        self.assertTrue(marcador.exists())

    def test_segunda_passagem_dentro_de_60s_nao_limpa_de_novo(self):
        with freeze_time("2026-09-19 10:00:00"):
            atender_um_passo()
            marcador_conteudo_1 = (self.base / "ia" / "ultima_limpeza").read_text(encoding="utf-8")

        with freeze_time("2026-09-19 10:00:30"):  # 30s depois, abaixo do alvo de 60s
            atender_um_passo()
            marcador_conteudo_2 = (self.base / "ia" / "ultima_limpeza").read_text(encoding="utf-8")

        self.assertEqual(marcador_conteudo_1, marcador_conteudo_2)

    def test_com_ia_api_key_vazia_limpeza_continua_e_pedido_vira_erro_sem_chave(self):
        fila.gravar_pedido_reindexacao(solicitado_por=1, agora=timezone.now())

        atender_um_passo()

        marcador = self.base / "ia" / "ultima_limpeza"
        self.assertTrue(marcador.exists())
        pedidos_pendentes = fila.listar_pedidos()
        self.assertEqual(pedidos_pendentes, [])

    def test_quota_do_dia_atual_intacta_apos_limpar_se_necessario(self):
        from apps.assistente import estado

        agora = timezone.now()
        estado.reservar(
            requisicao_id=estado.emitir_requisicao(
                usuario_id=1,
                sessao_hash="hash",
                conversa_id="conversa",
                exercicio=2026,
                agora=agora,
            ),
            usuario_id=1,
            sessao_hash="hash",
            conversa_id="conversa",
            exercicio=2026,
            agora=agora,
            limite=50,
        )

        atender_um_passo()

        self.assertEqual(estado.consumo(1, estado.dia_civil(agora)).perguntas, 1)
