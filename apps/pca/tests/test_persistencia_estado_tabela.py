"""Quick 260911-usq — cobertura automatizada de Q-05/Q-06 (must_haves):
`/tabela` grava seu estado canônico (`querystring_tabela(request.GET)`) em
sessão (`views.CHAVE_SESSAO_ESTADO_TABELA`, guarda "só grava se diferir",
mesmo padrão WR-03 de `apps.pca.colunas.colunas_selecionadas`) e um GET
vazio não-htmx restaura esse estado por redirect; `?limpar=1` (marcador do
link "Limpar filtros") zera de verdade, sem ficar preso ao filtro anterior;
trocar de exercício explicitamente vira o novo padrão persistido.

Sem import de XLSX — só precisa de um `Exercicio` para `/tabela` resolver
`exercicio` via `resolver_exercicio`/`filtros_ativos`, nenhum `Processo`."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.catalogo.models import Exercicio


class TestPersistenciaEstadoTabela(TestCase):
    def setUp(self):
        # `Exercicio(ano=2026)` já existe no banco de teste desde a
        # migração de dados `pca.0008_backfill_exercicio_2026` — `create()`
        # duplicaria a chave única `ano` (mesmo padrão de `.get(ano=2026)`
        # já usado por `TestGradeDeFiltrosReorganizada`, test_filtros_tabela.py).
        Exercicio.objects.get(ano=2026)
        self.usuario = get_user_model().objects.create_user(
            email="leitor-persistencia@pca.local", password="senha-segura-260911"
        )
        self.client.force_login(self.usuario)

    def test_filtro_grava_sessao_e_get_vazio_nao_htmx_redireciona(self):
        self.client.get(reverse("pca:tabela"), {"situacao": "atrasado"})
        self.assertEqual(self.client.session["pca_estado_tabela"], "situacao=atrasado")

        resposta = self.client.get(reverse("pca:tabela"))
        self.assertEqual(resposta.status_code, 302)
        self.assertIn("situacao=atrasado", resposta["Location"])

        resposta_htmx = self.client.get(
            reverse("pca:tabela"), HTTP_HX_REQUEST="true"
        )
        self.assertEqual(resposta_htmx.status_code, 200)

    def test_limpar_filtros_zera_de_verdade(self):
        self.client.get(reverse("pca:tabela"), {"situacao": "atrasado"})

        resposta_limpar = self.client.get(reverse("pca:tabela"), {"limpar": "1"})
        self.assertEqual(resposta_limpar.status_code, 200)
        self.assertEqual(self.client.session["pca_estado_tabela"], "")

        resposta_seguinte = self.client.get(reverse("pca:tabela"))
        self.assertEqual(resposta_seguinte.status_code, 200)

    def test_exercicio_explicito_vira_novo_padrao(self):
        Exercicio.objects.create(ano=2025, rotulo="PCA 2025")

        self.client.get(reverse("pca:tabela"), {"exercicio": "2025"})
        self.assertIn("exercicio=2025", self.client.session["pca_estado_tabela"])

        resposta = self.client.get(reverse("pca:tabela"))
        self.assertEqual(resposta.status_code, 302)
        self.assertIn("exercicio=2025", resposta["Location"])

    def test_ordenar_pagina_por_pagina_sobrevivem_no_estado_gravado(self):
        self.client.get(
            reverse("pca:tabela"),
            {
                "ordenar": "descricao_objeto",
                "dir": "desc",
                "pagina": "2",
                "por_pagina": "50",
            },
        )
        estado = self.client.session["pca_estado_tabela"]
        self.assertIn("ordenar=descricao_objeto", estado)
        self.assertIn("dir=desc", estado)
        self.assertIn("pagina=2", estado)
        self.assertIn("por_pagina=50", estado)
