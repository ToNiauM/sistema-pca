"""Excluir acompanhamento pela ficha, com confirmação
que anuncia o efeito real no estado derivado (`Processo.objects.
para_listagem()`), calculado por transação+rollback (mesma técnica do
procedimento manual de 22/09/2026 que apagou 21 linhas redundantes do
robô, agora exposta ao operador antes do ato).

(`TestEfeitoDaExclusao`/`TestExcluirAcompanhamento`) cobre o
serviço isolado, sem HTTP — mesmo padrão de fixture de
`test_querysets.py::TestQuerysetBase` (TestCase puro, sem import de
planilha). acrescenta `TestAcompanhamentoExcluirViews` para as
duas rotas novas via `django.test.Client`."""

from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import Client, TestCase
from django.urls import reverse

from apps.catalogo.models import (
    Categoria,
    Exercicio,
    SituacaoExercicio,
    SituacaoNormalizada,
    Tipo,
    Unidade,
)
from apps.pca.models import Acompanhamento, Processo, TipoEvento
from apps.pca import services


class _BaseAcompanhamentoExcluir(TestCase):
    """Catálogo mínimo compartilhado — um processo por teste via
    `_criar_processo`/`_criar_acompanhamento`, mesmo padrão de
    `test_querysets.py::TestQuerysetBase`."""

    @classmethod
    def setUpTestData(cls):
        cls.unidade = Unidade.objects.create(nome="Unidade Excluir Acompanhamento")
        cls.categoria = Categoria.objects.create(nome="Categoria Excluir Acompanhamento")
        cls.tipo = Tipo.objects.create(nome="Tipo Excluir Acompanhamento")
        cls.situacao_normalizada = SituacaoNormalizada.objects.create(
            nome="Em tramitação Excluir Acompanhamento"
        )
        cls.exercicio = Exercicio.objects.get(ano=2026)

    def _criar_processo(self, item_pca, **kwargs):
        defaults = {
            "descricao_objeto": f"Objeto excluir acompanhamento {item_pca}",
            "tipo": self.tipo,
            "categoria": self.categoria,
            "unidade_organizacional": self.unidade,
        }
        defaults.update(kwargs)
        return Processo.objects.create(
            item_pca=item_pca, exercicio=self.exercicio, **defaults
        )

    def _criar_acompanhamento(self, processo, **kwargs):
        defaults = {
            "referencia_data": date(2026, 5, 4),
            "origem_hash": f"hash-excluir-acompanhamento-{processo.pk}-{Acompanhamento.objects.count()}",
            "tipo_evento": TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
            "situacao": self.situacao_normalizada,
        }
        defaults.update(kwargs)
        return Acompanhamento.objects.create(processo=processo, **defaults)


class TestEfeitoDaExclusao(_BaseAcompanhamentoExcluir):
    def test_linha_sem_prazo_nada_muda_e_zero_escrita_persistida(self):
        processo = self._criar_processo(1)
        acompanhamento = self._criar_acompanhamento(
            processo,
            referencia_data=date(2026, 3, 1),
            situacao_informada="Observação sem prazo",
        )
        # Uma segunda linha, mais recente, mantém "situacao_atual"
        # (`para_listagem()::ultimo`, desempatado por referencia_data/id)
        # estável mesmo depois de apagar a primeira — sem ela, apagar a
        # ÚNICA linha do processo sempre mudaria "situação atual" para
        # None, o que não é o cenário sob teste (linha SEM efeito real
        # entre várias).
        self._criar_acompanhamento(
            processo,
            referencia_data=date(2026, 4, 1),
            situacao_informada="Observação mais recente",
        )

        antes_count = Acompanhamento.objects.count()
        antes_situacao = processo.situacao
        antes_atualizado_em = processo.atualizado_em

        efeito = services.efeito_da_exclusao(acompanhamento)

        self.assertTrue(efeito["nada_muda"])
        self.assertEqual(efeito["mudancas"], [])

        self.assertEqual(Acompanhamento.objects.count(), antes_count)
        self.assertTrue(Acompanhamento.objects.filter(pk=acompanhamento.pk).exists())
        processo.refresh_from_db()
        self.assertEqual(processo.situacao, antes_situacao)
        self.assertEqual(processo.atualizado_em, antes_atualizado_em)

    def test_linha_com_prazo_vigente_lista_a_mudanca_e_nao_persiste(self):
        processo = self._criar_processo(2)
        acompanhamento = self._criar_acompanhamento(
            processo, prazo_prometido=date(2026, 6, 10)
        )

        antes_count = Acompanhamento.objects.count()

        efeito = services.efeito_da_exclusao(acompanhamento)

        self.assertFalse(efeito["nada_muda"])
        por_campo = {m["campo"]: m for m in efeito["mudancas"]}
        self.assertIn("prazo_vigente", por_campo)
        mudanca_prazo = por_campo["prazo_vigente"]
        self.assertEqual(mudanca_prazo["antes"], date(2026, 6, 10))
        self.assertIsNone(mudanca_prazo["depois"])
        self.assertTrue(mudanca_prazo["rotulo"])

        self.assertEqual(Acompanhamento.objects.count(), antes_count)
        self.assertTrue(Acompanhamento.objects.filter(pk=acompanhamento.pk).exists())
        atual = Processo.objects.para_listagem().get(pk=processo.pk)
        self.assertEqual(atual.prazo_vigente, date(2026, 6, 10))


class TestExcluirAcompanhamento(_BaseAcompanhamentoExcluir):
    def test_apaga_e_grava_exclusao_na_trilha_com_autor(self):
        processo = self._criar_processo(3)
        acompanhamento = self._criar_acompanhamento(
            processo, situacao_informada="Observação a excluir"
        )
        pk = acompanhamento.pk

        User = get_user_model()
        usuario = User.objects.create_user(
            email="autor-exclusao@pca.local", password="senha-segura"
        )

        resultado = services.excluir_acompanhamento(
            acompanhamento_id=pk, usuario=usuario
        )

        self.assertFalse(Acompanhamento.objects.filter(pk=pk).exists())
        historico_delete = Acompanhamento.history.model.objects.filter(
            id=pk, history_type="-"
        ).first()
        self.assertIsNotNone(historico_delete)
        self.assertEqual(historico_delete.history_user, usuario)
        self.assertIn("resumo", resultado)
        self.assertEqual(resultado["processo"].pk, processo.pk)

    def test_exercicio_fechado_recusa_e_nao_apaga(self):
        # QA 30/09 (achado fluxos nº12) — excluir acompanhamento num exercício fechado nunca grava.
        fechado, _ = Exercicio.objects.get_or_create(
            ano=2018, defaults={"situacao": SituacaoExercicio.FECHADO}
        )
        processo = Processo.objects.create(
            item_pca=1,
            exercicio=fechado,
            descricao_objeto="Objeto exercício fechado",
            tipo=self.tipo,
            categoria=self.categoria,
            unidade_organizacional=self.unidade,
        )
        acompanhamento = self._criar_acompanhamento(
            processo, situacao_informada="Observação em exercício fechado"
        )
        pk = acompanhamento.pk

        User = get_user_model()
        usuario = User.objects.create_user(
            email="autor-exclusao-fechado@pca.local", password="senha-segura"
        )

        with self.assertRaises(services.ExercicioFechado):
            services.excluir_acompanhamento(acompanhamento_id=pk, usuario=usuario)

        self.assertTrue(Acompanhamento.objects.filter(pk=pk).exists())


class TestAcompanhamentoExcluirViews(TestCase):
    """Coluna Ações, página de confirmação e POST real. Fixture
    própria (mesmo padrão de `test_geracao_n1.py::TestGerarN1Views`):
    superusuário ∧ `gerir_exercicio` é a guarda; editor/dirigente/
    visualizador recebem 403 nas duas rotas.

    Nomes de rota seguem o padrão JÁ USADO no app (`cenario_fluxo_
    excluir`/`cenario_fluxo_excluir_confirmar`, `views_analise.py`):
    `pca:acompanhamento_excluir_confirmar` é a URL mais longa
    (`.../excluir/confirmar`, GET, página de confirmação) e
    `pca:acompanhamento_excluir` é a URL curta (`.../excluir`, POST, a
    exclusão real) — desta quick invertia essa correspondência
    por engano (ver SUMMARY, seção Desvios)."""

    @classmethod
    def setUpTestData(cls):
        cls.exercicio = Exercicio.objects.get(ano=2026)
        cls.unidade = Unidade.objects.create(nome="Unidade Views Excluir Acompanhamento")
        cls.categoria = Categoria.objects.create(nome="Categoria Views Excluir Acompanhamento")
        cls.tipo = Tipo.objects.create(nome="Tipo Views Excluir Acompanhamento")
        cls.situacao_normalizada = SituacaoNormalizada.objects.create(
            nome="Em tramitação Views Excluir Acompanhamento"
        )
        cls.processo = Processo.objects.create(
            item_pca=1,
            exercicio=cls.exercicio,
            descricao_objeto="Objeto views excluir acompanhamento",
            tipo=cls.tipo,
            categoria=cls.categoria,
            unidade_organizacional=cls.unidade,
        )
        cls.acompanhamento = Acompanhamento.objects.create(
            processo=cls.processo,
            referencia_data=date(2026, 5, 4),
            origem_hash="hash-views-excluir-acompanhamento-1",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
            situacao=cls.situacao_normalizada,
            situacao_informada="Observação de teste",
        )
        # Uma segunda linha, mais recente, mantém "situação atual"
        # (`para_listagem()::ultimo`) estável quando `cls.acompanhamento` é
        # apagada — mesmo ajuste do fixture de `TestEfeitoDaExclusao`:
        #apagar a ÚNICA linha do processo sempre muda a
        # situação atual, o que não é o cenário "sem efeito" sob teste.
        cls.acompanhamento_mais_recente = Acompanhamento.objects.create(
            processo=cls.processo,
            referencia_data=date(2026, 5, 20),
            origem_hash="hash-views-excluir-acompanhamento-mais-recente",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
            situacao=cls.situacao_normalizada,
            situacao_informada="Observação mais recente",
        )

        outro_processo = Processo.objects.create(
            item_pca=2,
            exercicio=cls.exercicio,
            descricao_objeto="Objeto de outro processo",
            tipo=cls.tipo,
            categoria=cls.categoria,
            unidade_organizacional=cls.unidade,
        )
        cls.acompanhamento_de_outro_processo = Acompanhamento.objects.create(
            processo=outro_processo,
            referencia_data=date(2026, 5, 5),
            origem_hash="hash-views-excluir-acompanhamento-2",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
            situacao=cls.situacao_normalizada,
        )

        User = get_user_model()
        cls.superusuario = User.objects.create_superuser(
            email="super-excluir-acompanhamento@pca.local", password="senha-segura"
        )
        cls.superusuario.user_permissions.add(
            Permission.objects.get(codename="gerir_exercicio"),
            Permission.objects.get(codename="view_acompanhamento"),
        )
        # Tem a permissão mas NÃO é superusuário — a guarda exige as DUAS
        # condições (superuser ∧ gerir_exercicio), nunca só uma; um
        # `is_superuser=True` sem a permissão não dá para testar porque
        # `User.has_perm()` sempre devolve True para superusuário real
        # (mesmo padrão de `test_geracao_n1.py::TestGerarN1Views`).
        cls.usuario_com_permissao_sem_superuser = User.objects.create_user(
            email="permissao-sem-superuser-excluir@pca.local", password="senha-segura"
        )
        cls.usuario_com_permissao_sem_superuser.user_permissions.add(
            Permission.objects.get(codename="gerir_exercicio"),
            Permission.objects.get(codename="view_acompanhamento"),
        )
        cls.editor = User.objects.create_user(
            email="editor-excluir-acompanhamento@pca.local", password="senha-segura"
        )
        cls.editor.groups.add(Group.objects.get(name="editor"))
        cls.editor.user_permissions.add(
            Permission.objects.get(codename="view_acompanhamento")
        )
        cls.dirigente = User.objects.create_user(
            email="dirigente-excluir-acompanhamento@pca.local", password="senha-segura"
        )
        cls.dirigente.groups.add(Group.objects.get(name="dirigentes"))
        cls.visualizador = User.objects.create_user(
            email="visualizador-excluir-acompanhamento@pca.local", password="senha-segura"
        )
        cls.visualizador.user_permissions.add(
            Permission.objects.get(codename="view_acompanhamento")
        )

    def setUp(self):
        self.client = Client(HTTP_X_FORWARDED_PROTO="https")

    @property
    def url_confirmar(self):
        return reverse(
            "pca:acompanhamento_excluir_confirmar",
            args=[2026, self.processo.item_pca, self.acompanhamento.pk],
        )

    @property
    def url_excluir(self):
        return reverse(
            "pca:acompanhamento_excluir",
            args=[2026, self.processo.item_pca, self.acompanhamento.pk],
        )

    @property
    def url_detalhe(self):
        return reverse("pca:detalhe_processo", args=[2026, self.processo.item_pca])

    def test_editor_recebe_403_nas_duas_rotas(self):
        self.client.force_login(self.editor)
        self.assertEqual(self.client.get(self.url_confirmar).status_code, 403)
        self.assertEqual(self.client.post(self.url_excluir).status_code, 403)

    def test_dirigente_recebe_403_nas_duas_rotas(self):
        self.client.force_login(self.dirigente)
        self.assertEqual(self.client.get(self.url_confirmar).status_code, 403)
        self.assertEqual(self.client.post(self.url_excluir).status_code, 403)

    def test_visualizador_recebe_403_nas_duas_rotas(self):
        self.client.force_login(self.visualizador)
        self.assertEqual(self.client.get(self.url_confirmar).status_code, 403)
        self.assertEqual(self.client.post(self.url_excluir).status_code, 403)

    def test_usuario_com_permissao_mas_sem_superuser_recebe_403(self):
        self.client.force_login(self.usuario_com_permissao_sem_superuser)
        self.assertEqual(self.client.get(self.url_confirmar).status_code, 403)
        self.assertEqual(self.client.post(self.url_excluir).status_code, 403)

    def test_superusuario_com_permissao_ve_pagina_de_confirmacao_sem_efeito(self):
        self.client.force_login(self.superusuario)
        resposta = self.client.get(self.url_confirmar)
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Confirmar exclusão")
        self.assertContains(resposta, "Esta ação não pode ser desfeita")
        self.assertContains(
            resposta, "Nenhum prazo ou situação do item depende desta linha."
        )

    def test_pagina_de_confirmacao_mostra_efeito_quando_ha_prazo_vigente(self):
        acompanhamento_com_prazo = Acompanhamento.objects.create(
            processo=self.processo,
            referencia_data=date(2026, 6, 1),
            origem_hash="hash-views-excluir-acompanhamento-prazo",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
            situacao=self.situacao_normalizada,
            prazo_prometido=date(2026, 7, 15),
        )
        self.client.force_login(self.superusuario)
        url = reverse(
            "pca:acompanhamento_excluir_confirmar",
            args=[2026, self.processo.item_pca, acompanhamento_com_prazo.pk],
        )
        resposta = self.client.get(url)
        self.assertEqual(resposta.status_code, 200)
        self.assertNotContains(
            resposta, "Nenhum prazo ou situação do item depende desta linha."
        )
        self.assertContains(resposta, "Prazo vigente")

    def test_post_exclui_redireciona_para_ficha_ancorada_e_grava_mensagem(self):
        self.client.force_login(self.superusuario)
        pk = self.acompanhamento.pk
        resposta = self.client.post(self.url_excluir, follow=False)
        self.assertEqual(resposta.status_code, 302)
        self.assertTrue(resposta.url.startswith(self.url_detalhe))
        self.assertIn("#acompanhamentos", resposta.url)
        self.assertFalse(Acompanhamento.objects.filter(pk=pk).exists())

        resposta_seguida = self.client.get(resposta.url.split("#")[0])
        mensagens = [str(m) for m in resposta_seguida.context["messages"]]
        self.assertTrue(any("excluído" in m for m in mensagens))

    def test_post_com_pk_de_outro_processo_devolve_404_e_nao_apaga(self):
        self.client.force_login(self.superusuario)
        url = reverse(
            "pca:acompanhamento_excluir",
            args=[2026, self.processo.item_pca, self.acompanhamento_de_outro_processo.pk],
        )
        resposta = self.client.post(url)
        self.assertEqual(resposta.status_code, 404)
        self.assertTrue(
            Acompanhamento.objects.filter(
                pk=self.acompanhamento_de_outro_processo.pk
            ).exists()
        )

    def test_ficha_de_editor_nao_mostra_coluna_acoes_nem_link_excluir(self):
        self.client.force_login(self.editor)
        resposta = self.client.get(self.url_detalhe)
        self.assertEqual(resposta.status_code, 200)
        self.assertNotContains(resposta, ">Excluir<")
        self.assertNotContains(resposta, "Ações</th>")

    def test_ficha_de_superusuario_com_permissao_mostra_link_excluir(self):
        self.client.force_login(self.superusuario)
        resposta = self.client.get(self.url_detalhe)
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, ">Excluir<")
        self.assertContains(resposta, "Ações</th>")
