"""Testes do card "Sincronização com o SEI" no Início (Fase 32, Plano
32-05, spec §3.6). Cobre os 3 estados (`nunca_executado`/`ok`/
`alerta`) e a visibilidade restrita a `pca.editar_pca`/superusuário
(decisão do usuário, 18/09/2026 — `<visibilidade_do_card>` do plano).

Nunca depende de `/app/data`: todo teste roda contra um diretório
temporário via `@override_settings(SEI_DATA_DIR=...)`, e todo cenário é
preparado por `apps.pca.sei.execucoes.gravar_execucao` — nunca escrevendo
o JSON à mão fora do módulo."""

import tempfile
from datetime import timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time

from apps.catalogo.models import Exercicio
from apps.pca.sei import execucoes


def _totais(itens_alterados=0, pendencias_novas=0, erros=0):
    return {
        "itens": 1,
        "processos": 1,
        "coletados": 1,
        "nao_encontrados": 0,
        "erros": erros,
        "itens_alterados": itens_alterados,
        "pendencias_novas": pendencias_novas,
        "eventos_gravados": itens_alterados,
    }


def _dados_execucao(status, mensagem=None, **totais_kwargs):
    agora = timezone.localtime().isoformat()
    return {
        "iniciado_em": agora,
        "terminado_em": agora,
        "status": status,
        "totais": _totais(**totais_kwargs),
        "alterados": [],
        "pendencias": [],
        "erros": [],
        "mensagem": mensagem,
        "metricas": {},
    }


class SEICardTestBase(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._override = override_settings(SEI_DATA_DIR=self._tmp.name)
        self._override.enable()
        self.addCleanup(self._override.disable)
        self.base = Path(self._tmp.name)

        self.exercicio = Exercicio.objects.create(
            ano=2099, rotulo="PCA 2099", situacao="aberto"
        )

        User = get_user_model()
        self.editor = User.objects.create_user(
            email="editor-sei-card@pca.local", password="senha-segura-123"
        )
        self.editor.groups.add(Group.objects.get(name="editor"))
        self.leitor = User.objects.create_user(
            email="leitor-sei-card@pca.local", password="senha-segura-123"
        )

        self.url = reverse("core:inicio")

    def _get(self, usuario):
        self.client.force_login(usuario)
        return self.client.get(self.url, {"exercicio": self.exercicio.ano})


class TestVisibilidadeDoCard(SEICardTestBase):
    """`<visibilidade_do_card>` do plano — só `pca.editar_pca`/superusuário
    veem o card; leitores não veem nada diferente no Início."""

    def test_leitor_nao_ve_o_card(self):
        resposta = self._get(self.leitor)
        self.assertEqual(resposta.status_code, 200)
        self.assertIsNone(resposta.context["sei_card"])
        self.assertNotIn("Sincronização com o SEI", resposta.content.decode())

    def test_editor_ve_o_card(self):
        resposta = self._get(self.editor)
        self.assertEqual(resposta.status_code, 200)
        self.assertIsNotNone(resposta.context["sei_card"])
        self.assertIn("Sincronização com o SEI", resposta.content.decode())


class TestEstadoNuncaExecutado(SEICardTestBase):
    """Nenhum arquivo em `data/sei/execucoes/` — `execucoes.ultima()`
    devolve `None`."""

    def test_card_mostra_nunca_executado(self):
        resposta = self._get(self.editor)
        conteudo = resposta.content.decode()
        self.assertEqual(resposta.context["sei_card"]["estado"], "nunca_executado")
        self.assertIn("Sincronização com o SEI", conteudo)
        self.assertIn("Nunca executado.", conteudo)
        self.assertNotIn("br-message warning", conteudo)

    def test_card_mostra_ultimo_pedido_e_atendidos_hoje_mesmo_sem_varredura(self):
        """`sei_card["ultimo_pedido"]`/`sei_card["pedidos_atendidos_hoje"]`
        presentes mesmo no estado `nunca_executado`."""
        execucoes.gravar_pedido(
            item_pca=42, exercicio=self.exercicio.ano, solicitado_por=self.editor.id
        )
        pedido = execucoes.listar_pedidos()[0]
        execucoes.mover_pedido_para_atendidos(
            pedido,
            {
                "status": "ok",
                "campos": [],
                "pendencias": [],
                "mensagem": None,
                "atendido_em": timezone.localtime().isoformat(),
            },
        )
        resposta = self._get(self.editor)
        conteudo = resposta.content.decode()
        self.assertEqual(resposta.context["sei_card"]["estado"], "nunca_executado")
        self.assertIn("Último pedido pelo Admin", conteudo)
        self.assertIn("item 42", conteudo)
        self.assertIn("Pedidos atendidos hoje: 1", conteudo)


class TestEstadoOk(SEICardTestBase):
    """Execução recente, `status="ok"` — card sem `br-message` (neutro)."""

    def test_card_sem_br_message_com_totais(self):
        execucoes.gravar_execucao(
            execucoes.novo_carimbo(),
            _dados_execucao("ok", itens_alterados=2, pendencias_novas=1, erros=0),
        )
        resposta = self._get(self.editor)
        conteudo = resposta.content.decode()
        self.assertEqual(resposta.context["sei_card"]["estado"], "ok")
        # Card neutro — nenhuma variante de `br-message` (nem info nem
        # warning) aparece para o estado "ok".
        self.assertNotIn("br-message warning", conteudo)
        self.assertNotIn("Nunca executado.", conteudo)
        self.assertIn("2", conteudo)

    def test_card_dentro_de_tres_dias_uteis_fica_ok(self):
        execucoes.gravar_execucao(
            execucoes.novo_carimbo(),
            _dados_execucao("ok", itens_alterados=0, pendencias_novas=0, erros=0),
        )
        resposta = self._get(self.editor)
        self.assertEqual(resposta.context["sei_card"]["estado"], "ok")

    def test_card_mostra_ultimo_pedido_e_atendidos_hoje(self):
        execucoes.gravar_execucao(
            execucoes.novo_carimbo(),
            _dados_execucao("ok", itens_alterados=2, pendencias_novas=1, erros=0),
        )
        execucoes.gravar_pedido(
            item_pca=9, exercicio=self.exercicio.ano, solicitado_por=self.editor.id
        )
        pedido = execucoes.listar_pedidos()[0]
        execucoes.mover_pedido_para_atendidos(
            pedido,
            {
                "status": "erro",
                "campos": [],
                "pendencias": [],
                "mensagem": None,
                "atendido_em": timezone.localtime().isoformat(),
            },
        )
        resposta = self._get(self.editor)
        conteudo = resposta.content.decode()
        self.assertIn("Último pedido pelo Admin", conteudo)
        self.assertIn("item 9", conteudo)
        self.assertIn("Pedidos atendidos hoje: 1", conteudo)


class TestEstadoAlertaPorFalha(SEICardTestBase):
    """Execução `status="erro"` — card em alerta mesmo dentro do prazo."""

    def test_card_em_alerta_com_mensagem(self):
        execucoes.gravar_execucao(
            execucoes.novo_carimbo(),
            _dados_execucao("erro", mensagem="login recusado pelo SEI"),
        )
        resposta = self._get(self.editor)
        conteudo = resposta.content.decode()
        self.assertEqual(resposta.context["sei_card"]["estado"], "alerta")
        self.assertIn("br-message warning", conteudo)
        self.assertIn("Última execução falhou.", conteudo)
        self.assertIn("login recusado pelo SEI", conteudo)


class TestEstadoAlertaPorPrazo(SEICardTestBase):
    """`status="ok"` mas `terminado_em` há mais de 3 dias úteis (freezegun)
    — alerta mesmo sem falha."""

    def test_card_em_alerta_sem_falha(self):
        with freeze_time("2026-09-01T10:00:00-03:00"):
            execucoes.gravar_execucao(
                execucoes.novo_carimbo(),
                _dados_execucao("ok", itens_alterados=0, pendencias_novas=0, erros=0),
            )
        # 2026-09-01 (terça) -> 2026-09-10 (quinta): 7 dias úteis depois.
        with freeze_time("2026-09-10T10:00:00-03:00"):
            resposta = self._get(self.editor)
        conteudo = resposta.content.decode()
        self.assertEqual(resposta.context["sei_card"]["estado"], "alerta")
        self.assertIn("br-message warning", conteudo)
        self.assertIn("Mais de 3 dias úteis sem execução.", conteudo)


class TestCardReposicionado(SEICardTestBase):
    """O card sobe para logo abaixo dos KPIs, antes dos gráficos."""

    def test_card_aparece_antes_do_primeiro_grafico(self):
        resposta = self._get(self.editor)
        conteudo = resposta.content.decode()
        self.assertIn("Sincronização com o SEI", conteudo)
        self.assertIn("Processos por situação", conteudo)
        self.assertLess(
            conteudo.index("Sincronização com o SEI"),
            conteudo.index("Processos por situação"),
        )


class TestEstadoEmExecucao(SEICardTestBase):
    """4º estado do card — lido do lock `em_execucao`
    via `execucoes.ler_progresso()`/`atualizar_progresso()`, nunca escrito
    à mão."""

    def _gravar_progresso_em_andamento(self):
        execucoes.adquirir_lock()
        carimbo = execucoes.ler_progresso()["carimbo"]
        execucoes.atualizar_progresso(
            carimbo, item=3, k=2, total=5, coletados=1, pulados=1, erros=0,
            ultima_linha="item 3 (2/5): coletado em 4.0 s",
        )
        self.addCleanup(execucoes.liberar_lock)

    def test_card_mostra_progresso_e_hx_trigger(self):
        self._gravar_progresso_em_andamento()
        resposta = self._get(self.editor)
        conteudo = resposta.content.decode()
        self.assertEqual(resposta.context["sei_card"]["estado"], "em_execucao")
        self.assertIn("item 3 (2/5", conteudo)
        self.assertIn("40%", conteudo)
        self.assertIn("1 coletado(s)", conteudo)
        self.assertIn(reverse("core:sei_card"), conteudo)
        self.assertIn('hx-trigger="every 15s"', conteudo)

    def test_sem_lock_nao_ha_hx_trigger_em_lugar_nenhum(self):
        # Cobre os 3 cenários de hoje (nunca_executado/ok/alerta) rápido —
        # nenhum tem lock/progresso, então nenhum tem hx-trigger.
        resposta = self._get(self.editor)  # nunca_executado
        self.assertNotIn('hx-trigger="every 15s"', resposta.content.decode())

        execucoes.gravar_execucao(
            execucoes.novo_carimbo(), _dados_execucao("ok", itens_alterados=0)
        )
        resposta = self._get(self.editor)  # ok
        self.assertNotIn('hx-trigger="every 15s"', resposta.content.decode())


class TestLockObsoletoIgnorado(SEICardTestBase):
    def test_lock_com_3h_ou_mais_nao_entra_em_execucao(self):
        # `mtime` do arquivo é sempre o relógio REAL do sistema — freezegun
        # não o falsifica — então `agora` precisa ser o `timezone.now()`
        # real (mesmo truque de `TestLock.test_libera_com_lock_vencido`
        # em test_sei_execucoes.py), não uma string de data fixa.
        agora = timezone.now()
        with freeze_time(agora):
            execucoes.adquirir_lock()
            carimbo = execucoes.ler_progresso()["carimbo"]
            execucoes.atualizar_progresso(
                carimbo, item=1, k=1, total=1, coletados=1, pulados=0, erros=0,
                ultima_linha="item 1 (1/1): coletado em 1.0 s",
            )
        with freeze_time(agora + timedelta(hours=3, minutes=1)):
            resposta = self._get(self.editor)
        self.assertNotEqual(resposta.context["sei_card"]["estado"], "em_execucao")
        self.assertEqual(resposta.context["sei_card"]["estado"], "nunca_executado")


class TestFragmentoSeiCard(SEICardTestBase):
    """`core:sei_card` — só o fragmento, protegido por
    `pca.editar_pca`."""

    def test_editor_com_progresso_devolve_so_o_fragmento(self):
        execucoes.adquirir_lock()
        carimbo = execucoes.ler_progresso()["carimbo"]
        execucoes.atualizar_progresso(
            carimbo, item=1, k=1, total=2, coletados=1, pulados=0, erros=0,
            ultima_linha="item 1 (1/2): coletado em 1.0 s",
        )
        self.addCleanup(execucoes.liberar_lock)

        self.client.force_login(self.editor)
        resposta = self.client.get(reverse("core:sei_card"))
        conteudo = resposta.content.decode()

        self.assertEqual(resposta.status_code, 200)
        self.assertIn("Varredura em andamento", conteudo)
        self.assertNotIn("<h1", conteudo)
        self.assertNotIn("<html", conteudo)
        self.assertNotIn("br-menu", conteudo)

    def test_leitor_recebe_403(self):
        self.client.force_login(self.leitor)
        resposta = self.client.get(reverse("core:sei_card"))
        self.assertEqual(resposta.status_code, 403)

    def test_anonimo_e_redirecionado_ao_login(self):
        resposta = self.client.get(reverse("core:sei_card"))
        self.assertEqual(resposta.status_code, 302)
        self.assertIn(reverse("core:login"), resposta.headers["Location"])
