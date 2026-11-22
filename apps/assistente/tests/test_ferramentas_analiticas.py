"""do plano (A16/A17, C04) — `fluxo_de_caixa`,
`memoria_de_calculo`, `contratos_a_vencer`: paridade com as telas oficiais,
permissões fora do modelo verificadas ANTES de qualquer consulta, recortes/
truncamento explícitos, desambiguação e "ausência ≠ zero"."""

from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import Group
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.assistente import ferramentas
from apps.assistente.tests.base import AssistenteTestBase
from apps.catalogo.models import Exercicio
from apps.pca.projecao.fluxo import LinhaMemoria, Memoria
from apps.pca.servicos import consultas_fluxo
from apps.pca.servicos import contratos as contratos_svc


class TestPermissoesForaDoModelo(AssistenteTestBase):
    """Recusa nas três ANTES de qualquer consulta protegida — só a
    resolução de exercício (0 ou 1 consulta) pode acontecer."""

    def test_editor_sem_ver_analises_recusa_nas_tres(self):
        # Aquece o cache de permissões do usuário (`ModelBackend._perm_
        # cache`) ANTES de medir — a recusa em si não deve consultar nada
        # além da própria permissão; o custo de popular o cache na
        # primeira chamada de `has_perm` não é o que este teste mede.
        self.editor.has_perm("pca.ver_analises")
        for chamada in (
            lambda: ferramentas.fluxo_de_caixa(self.editor, exercicio=2026),
            lambda: ferramentas.memoria_de_calculo(self.editor, exercicio=2026, item=1),
            lambda: ferramentas.contratos_a_vencer(self.editor, exercicio=2026),
        ):
            with CaptureQueriesContext(connection) as capturado:
                envelope = chamada()
            self.assertTrue(envelope.sem_permissao)
            self.assertNotIn("por_ano", envelope.dados)
            self.assertNotIn("kpis", envelope.dados)
            self.assertLessEqual(len(capturado.captured_queries), 1)

    def test_dirigente_sem_view_acompanhamento_recusa_so_contratos(self):
        dirigente_sem_acomp = self._novo_usuario_dirigentes_apenas()

        envelope_fluxo = ferramentas.fluxo_de_caixa(dirigente_sem_acomp, exercicio=2026)
        self.assertFalse(envelope_fluxo.sem_permissao)

        envelope_contratos = ferramentas.contratos_a_vencer(dirigente_sem_acomp, exercicio=2026)
        self.assertTrue(envelope_contratos.sem_permissao)
        self.assertIn("pca.view_acompanhamento", envelope_contratos.dados["recusa"])

    def _novo_usuario_dirigentes_apenas(self):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        usuario = User.objects.create_user(
            email="dirigente-sem-acomp@pca.local", password="senha-segura"
        )
        usuario.groups.add(Group.objects.get(name="dirigentes"))
        return usuario


class TestParidadeFluxoDeCaixa(AssistenteTestBase):
    def test_por_ano_bate_com_o_servico_oficial(self):
        exercicio_obj = Exercicio.objects.get(ano=2026)
        projecao_servico, _itens = consultas_fluxo.projecao_oficial(exercicio_obj)

        envelope = ferramentas.fluxo_de_caixa(self.dirigente, exercicio=2026)
        self.assertFalse(envelope.sem_permissao)

        for ano, mapa in projecao_servico.por_ano.items():
            linha = envelope.dados["por_ano"][str(ano)]
            for camada, valor in mapa.items():
                self.assertEqual(linha[camada], str(valor))

    def test_referencia_resolve_200(self):
        envelope = ferramentas.fluxo_de_caixa(self.dirigente, exercicio=2026)
        client = Client(HTTP_X_FORWARDED_PROTO="https")
        client.force_login(self.dirigente)
        resposta = client.get(envelope.referencias[0]["url"], HTTP_HOST="testserver")
        self.assertEqual(resposta.status_code, 200)

    def test_mes_sem_ano_e_erro(self):
        envelope = ferramentas.fluxo_de_caixa(self.dirigente, exercicio=2026, mes=3)
        self.assertEqual(envelope.dados.get("erro"), "mês exige ano")

    def test_ano_fora_do_horizonte_e_erro(self):
        envelope = ferramentas.fluxo_de_caixa(self.dirigente, exercicio=2026, ano=2050)
        self.assertEqual(envelope.dados.get("erro"), "ano fora do horizonte")

    def test_recorte_ano_soma_bate_com_por_ano_do_servico(self):
        exercicio_obj = Exercicio.objects.get(ano=2026)
        projecao_servico, _itens = consultas_fluxo.projecao_oficial(exercicio_obj)
        esperado = sum(projecao_servico.por_ano.get(2026, {}).values(), Decimal("0"))

        envelope = ferramentas.fluxo_de_caixa(self.dirigente, exercicio=2026, ano=2026)
        self.assertIn("recorte", envelope.dados)
        self.assertEqual(Decimal(envelope.dados["recorte"]["total"]), esperado)

    def test_unidade_ambigua_devolve_alternativas_sem_projetar(self):
        # "CO" casa com várias UOs da fixture real (COAD/COFIS/COLOG/COREG).
        envelope = ferramentas.fluxo_de_caixa(self.dirigente, exercicio=2026, unidade="CO")
        self.assertTrue(envelope.dados.get("ambiguo"))
        self.assertGreater(len(envelope.dados["alternativas"]), 1)

    def test_decimal_nunca_vira_float(self):
        envelope = ferramentas.fluxo_de_caixa(self.dirigente, exercicio=2026)
        for linha in envelope.dados["por_ano"].values():
            for valor in linha.values():
                self.assertIsInstance(valor, str)

    def test_assert_num_queries_constante(self):
        self.dirigente.has_perm("pca.ver_analises")  # aquece o cache de permissões
        with CaptureQueriesContext(connection) as capturado:
            ferramentas.fluxo_de_caixa(self.dirigente, exercicio=2026)
        self.assertLessEqual(len(capturado.captured_queries), 5, capturado.captured_queries)


class TestParidadeMemoriaDeCalculo(AssistenteTestBase):
    def test_linhas_batem_com_memoria_oficial(self):
        exercicio_obj = Exercicio.objects.get(ano=2026)
        memoria_servico = consultas_fluxo.memoria_oficial(exercicio_obj, 1)
        self.assertIsNotNone(memoria_servico)

        envelope = ferramentas.memoria_de_calculo(self.dirigente, exercicio=2026, item=1)
        self.assertFalse(envelope.sem_permissao)

        linhas_servico = sorted(
            (l.competencia, l.camada, str(l.valor), l.formula) for l in memoria_servico.linhas
        )
        linhas_envelope = sorted(
            (l["competencia"], l["camada"], l["valor"], l["formula"])
            for l in envelope.dados["linhas"]
        )
        self.assertEqual(linhas_servico[:60], linhas_envelope)

    def test_item_inexistente_e_erro_nao_sem_dado(self):
        envelope = ferramentas.memoria_de_calculo(self.dirigente, exercicio=2026, item=999999)
        self.assertIn("erro", envelope.dados)
        self.assertNotIn("sem_dado", envelope.dados)

    def test_item_sem_projecao_e_sem_dado_explicito(self):
        from apps.pca.models import Processo

        processo = Processo.objects.filter(
            exercicio__ano=2026,
            vigencia_fim__isnull=True,
            valor_contratado__isnull=True,
            valor_estimado__isnull=True,
        ).first()
        if processo is None:
            self.skipTest("fixture sem item sem dado suficiente para este cenário")
        envelope = ferramentas.memoria_de_calculo(
            self.dirigente, exercicio=2026, item=processo.item_pca
        )
        self.assertTrue(envelope.dados.get("sem_dado"))
        self.assertNotIn("erro", envelope.dados)

    def test_truncamento_explicito_acima_de_60_linhas(self):
        linhas_fake = [
            LinhaMemoria(
                competencia=f"{2026 + (i // 12)}-{(i % 12) + 1:02d}",
                camada="contratado",
                valor=Decimal("10.00"),
                formula="10,00 (fixo, teste)",
            )
            for i in range(65)
        ]
        memoria_fake = Memoria(item_pca=1, fontes=[], premissas=[], descartados=[], linhas=linhas_fake)
        with mock.patch(
            "apps.pca.servicos.consultas_fluxo.memoria_oficial", return_value=memoria_fake
        ):
            envelope = ferramentas.memoria_de_calculo(self.dirigente, exercicio=2026, item=1)
        self.assertTrue(envelope.dados["truncado"])
        self.assertEqual(envelope.dados["total_linhas"], 65)
        self.assertEqual(len(envelope.dados["linhas"]), 60)

    def test_referencias_resolvem_200(self):
        envelope = ferramentas.memoria_de_calculo(self.dirigente, exercicio=2026, item=1)
        client = Client(HTTP_X_FORWARDED_PROTO="https")
        client.force_login(self.dirigente)
        for referencia in envelope.referencias:
            resposta = client.get(referencia["url"], HTTP_HOST="testserver")
            self.assertEqual(resposta.status_code, 200)


class TestParidadeContratosAVencer(AssistenteTestBase):
    def test_kpis_batem_com_o_servico_e_invariante_bate(self):
        exercicio_obj = Exercicio.objects.get(ano=2026)
        resultado_servico = contratos_svc.contratos_a_vencer(exercicio_obj, "todos")

        envelope = ferramentas.contratos_a_vencer(self.dirigente, exercicio=2026)
        self.assertFalse(envelope.sem_permissao)

        self.assertEqual(envelope.dados["kpis"]["total"], resultado_servico.kpis["total"])
        self.assertEqual(
            envelope.dados["kpis"]["por_destino"], resultado_servico.kpis["por_destino"]
        )
        self.assertTrue(envelope.dados["invariante"])
        self.assertEqual(envelope.dados["total_itens"], resultado_servico.queryset.count())

    def test_truncamento_explicito_quando_ha_mais_de_20(self):
        exercicio_obj = Exercicio.objects.get(ano=2026)
        total = contratos_svc.contratos_a_vencer(exercicio_obj, "todos").queryset.count()
        if total <= 20:
            self.skipTest("fixture com 20 ou menos itens — nada a truncar")
        envelope = ferramentas.contratos_a_vencer(self.dirigente, exercicio=2026)
        self.assertTrue(envelope.dados["truncado"])
        self.assertEqual(len(envelope.dados["itens"]), 20)

    def test_populacao_vazia_tem_observacao_e_mensagem_nunca_diz_zero_como_ausencia(self):
        envelope = ferramentas.contratos_a_vencer(self.dirigente, exercicio=2026, horizonte="vencidos")
        self.assertIn("observacao", envelope.dados)
        if envelope.dados["kpis"]["total"] == 0:
            self.assertIn("mensagem", envelope.dados)

    def test_horizonte_invalido_cai_no_padrao_todos(self):
        envelope = ferramentas.contratos_a_vencer(self.dirigente, exercicio=2026, horizonte="sla-invalida")
        self.assertEqual(envelope.dados["horizonte"], "todos")

    def test_referencia_resolve_200(self):
        envelope = ferramentas.contratos_a_vencer(self.dirigente, exercicio=2026)
        client = Client(HTTP_X_FORWARDED_PROTO="https")
        client.force_login(self.dirigente)
        resposta = client.get(envelope.referencias[0]["url"], HTTP_HOST="testserver")
        self.assertEqual(resposta.status_code, 200)

    def test_assert_num_queries_constante(self):
        self.dirigente.has_perm("pca.ver_analises")
        self.dirigente.has_perm("pca.view_acompanhamento")
        with CaptureQueriesContext(connection) as capturado:
            ferramentas.contratos_a_vencer(self.dirigente, exercicio=2026)
        self.assertLessEqual(len(capturado.captured_queries), 6, capturado.captured_queries)


class TestFerramentasViaExecutarRegistradas(AssistenteTestBase):
    """As três entram em `ESQUEMAS`/`FUNCOES` e o dispatch genérico de
    `executar()` já resolve `exercicio` sem nenhuma outra mudança no
    laço."""

    def test_esquemas_e_funcoes_registrados(self):
        for nome in ("fluxo_de_caixa", "memoria_de_calculo", "contratos_a_vencer"):
            self.assertIn(nome, ferramentas.ESQUEMAS)
            self.assertIn(nome, ferramentas.FUNCOES)

    def test_executar_fluxo_de_caixa_com_exercicio_none_assume_da_pagina(self):
        import json

        exercicio_obj = Exercicio.objects.get(ano=2026)
        envelope = ferramentas.executar(
            "fluxo_de_caixa",
            json.dumps({"exercicio": None}),
            usuario=self.dirigente,
            exercicio_padrao=exercicio_obj,
        )
        self.assertFalse(envelope.sem_permissao)
        self.assertEqual(envelope.dados["aviso"], "exercício assumido: 2026")
