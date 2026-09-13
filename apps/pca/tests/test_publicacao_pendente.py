from datetime import date, timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils.timezone import localdate

from apps.pca.filtros import querystring_filtros
from apps.pca.models import Processo


ARQUIVO_REAL = "apps/pca/fixtures/modelo-controle-exemplo.xlsx"


class TestPublicacaoPendente(TransactionTestCase):
    """PUB-02/03 — publicação só fica pendente após assinatura e enquanto
    faltar ao menos um dos três lançamentos."""

    serialized_rollback = True

    def setUp(self):
        call_command(
            "importar_pca",
            ARQUIVO_REAL,
            "--usuario=importador@pca.local",
            "--exercicio=2026",
            stdout=StringIO(),
        )
        self.usuario = get_user_model().objects.create_user(
            email="leitor@pca.local", password="x-forte-123"
        )
        self.client.force_login(self.usuario)
        self.processo = Processo.objects.get(item_pca=26)

    def _atualizar_lancamentos(self, assinatura, spw, wordpress, dados_abertos):
        self.processo.data_assinatura_contrato = assinatura
        self.processo.data_lancamento_spw = spw
        self.processo.data_lancamento_wordpress = wordpress
        self.processo.data_lancamento_dados_abertos = dados_abertos
        self.processo.save()
        return Processo.objects.para_listagem().get(pk=self.processo.pk)

    def test_tres_lancamentos_ausentes_apos_assinatura_sao_pendentes(self):
        resultado = self._atualizar_lancamentos(date(2026, 1, 10), None, None, None)
        self.assertTrue(resultado.publicacao_pendente)

    def test_tres_lancamentos_preenchidos_nao_sao_pendentes(self):
        resultado = self._atualizar_lancamentos(
            date(2026, 1, 10), date(2026, 1, 11), date(2026, 1, 12), date(2026, 1, 13)
        )
        self.assertFalse(resultado.publicacao_pendente)

    def test_sem_assinatura_nunca_e_pendente(self):
        resultado = self._atualizar_lancamentos(None, None, date(2026, 1, 12), None)
        self.assertFalse(resultado.publicacao_pendente)

    def test_um_unico_lancamento_ausente_ainda_e_pendente(self):
        resultado = self._atualizar_lancamentos(
            date(2026, 1, 10), None, date(2026, 1, 12), date(2026, 1, 13)
        )
        self.assertTrue(resultado.publicacao_pendente)

    def test_assinatura_de_hoje_ou_futura_nao_gera_pendencia(self):
        # O invariante de negócio coberto é o flag agregado
        # `publicacao_pendente`, que a tabela usa para filtrar.
        for assinatura in (localdate(), localdate() + timedelta(days=1)):
            with self.subTest(assinatura=assinatura):
                resultado = self._atualizar_lancamentos(assinatura, None, None, None)
                self.assertFalse(resultado.publicacao_pendente)

                resposta_tabela = self.client.get(
                    reverse("pca:tabela"), {"publicacao_pendente": "1"}
                )
                self.assertNotIn(
                    26,
                    [p.item_pca for p in resposta_tabela.context["pagina"].object_list],
                )

    def test_flags_filtram_e_querystring_preserva_contratado_e_pendencia(self):
        outro = Processo.objects.get(item_pca=28)
        self.processo.valor_contratado = "1200.00"
        self.processo.data_assinatura_contrato = date(2026, 1, 10)
        self.processo.save()
        outro.valor_contratado = None
        outro.data_assinatura_contrato = None
        outro.save()

        resposta_contratado = self.client.get(reverse("pca:tabela"), {"contratado": "1"})
        self.assertEqual(resposta_contratado.status_code, 200)
        self.assertTrue(
            all(p.valor_contratado is not None for p in resposta_contratado.context["pagina"].object_list)
        )

        resposta_pendente = self.client.get(
            reverse("pca:tabela"), {"publicacao_pendente": "1"}
        )
        self.assertEqual(resposta_pendente.status_code, 200)
        self.assertTrue(
            all(p.publicacao_pendente for p in resposta_pendente.context["pagina"].object_list)
        )
        querystring = querystring_filtros(
            {"contratado": "1", "publicacao_pendente": "1"}
        )
        self.assertIn("contratado=1", querystring)
        self.assertIn("publicacao_pendente=1", querystring)

    def test_valor_contratado_e_ordenavel_em_ordem_descendente(self):
        outro = Processo.objects.get(item_pca=28)
        self.processo.valor_contratado = "1200.00"
        self.processo.save()
        outro.valor_contratado = "3400.00"
        outro.save()

        resposta = self.client.get(
            reverse("pca:tabela"),
            {"contratado": "1", "ordenar": "valor_contratado", "dir": "desc"},
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.context["campo_ordenacao"], "valor_contratado")
        valores = [p.valor_contratado for p in resposta.context["pagina"].object_list]
        self.assertEqual(valores, sorted(valores, reverse=True))

    def test_detalhe_mostra_os_tres_selos_de_canal_quando_nenhum_lancado(self):
        # Os selos "pendente há N dias" vivem na seção "Publicação" de
        # `pca:detalhe_processo`.
        self._atualizar_lancamentos(date(2026, 1, 10), None, None, None)
        resposta = self.client.get(
            reverse("pca:detalhe_processo", args=[2026, self.processo.item_pca])
        )
        html = resposta.content.decode("utf-8")

        self.assertIn("SPW pendente há", html)
        self.assertIn("WordPress pendente há", html)
        self.assertIn("Dados Abertos pendente há", html)

    def test_detalhe_preencher_um_canal_remove_so_o_selo_daquele_canal(self):
        self._atualizar_lancamentos(date(2026, 1, 10), date(2026, 1, 11), None, None)
        resposta = self.client.get(
            reverse("pca:detalhe_processo", args=[2026, self.processo.item_pca])
        )
        html = resposta.content.decode("utf-8")

        self.assertNotIn("SPW pendente há", html)
        self.assertIn("WordPress pendente há", html)
        self.assertIn("Dados Abertos pendente há", html)

    def test_detalhe_sem_publicacao_pendente_nao_mostra_selo_nenhum(self):
        self._atualizar_lancamentos(
            date(2026, 1, 10), date(2026, 1, 11), date(2026, 1, 12), date(2026, 1, 13)
        )
        resposta = self.client.get(
            reverse("pca:detalhe_processo", args=[2026, self.processo.item_pca])
        )
        html = resposta.content.decode("utf-8")

        self.assertNotIn("pendente há", html)

    def test_tabela_mostra_indicador_somente_para_publicacao_pendente(self):
        self._atualizar_lancamentos(date(2026, 1, 10), None, None, None)
        resposta = self.client.get(reverse("pca:tabela"), {"publicacao_pendente": "1"})
        self.assertContains(resposta, "Publicação pendente")

        self._atualizar_lancamentos(
            date(2026, 1, 10), date(2026, 1, 11), date(2026, 1, 12), date(2026, 1, 13)
        )
        # Quick 260911-usq (Q-05/Q-06) — a requisição anterior gravou
        # `?publicacao_pendente=1` na sessão (`CHAVE_SESSAO_ESTADO_TABELA`);
        # um GET vazio agora restaura esse estado por redirect (persistência
        # intencional) — `follow=True` reencaminharia para o MESMO filtro,
        # cujo chip "Publicação pendente" (rótulo do filtro ativo, não do
        # item) continuaria na página mesmo com a listagem vazia. `?limpar=1`
        # é o jeito real de voltar à tabela sem filtro nenhum (mesmo
        # marcador do link "Limpar filtros"), o que este teste sempre quis
        # dizer com "revisita sem filtro".
        resposta = self.client.get(reverse("pca:tabela"), {"limpar": "1"})
        self.assertNotContains(resposta, "Publicação pendente")

    # Os selos vivem na seção "Publicação" de `pca:detalhe_processo` —
    # ver `test_detalhe_mostra_os_tres_selos_de_canal_quando_nenhum_lancado`,
    # `test_detalhe_preencher_um_canal_remove_so_o_selo_daquele_canal` e
    # `test_detalhe_sem_publicacao_pendente_nao_mostra_selo_nenhum` acima.
