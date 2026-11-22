"""(documento interno de desenho §5) — `data-item-pca`/`data-exercicio` no
contêiner principal da ficha do item (`pca:detalhe_processo`), nas duas
cascas (DSGov e Tabler): seletor estável para a extensão SEI Pro achar o
item sem outra chamada de API. O PCA não muda mais nada na tela — o botão
"Iniciar processo" é inserido pela própria extensão, por fora."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.catalogo.models import Categoria, Exercicio, SituacaoExercicio, Tipo, Unidade
from apps.pca.models import Processo


class TestAtributosFichaItemExtensao(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.exercicio, _ = Exercicio.objects.get_or_create(
            ano=2026, defaults={"situacao": SituacaoExercicio.ABERTO}
        )
        cls.tipo = Tipo.objects.create(nome="Aquisição")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.unidade = Unidade.objects.create(nome="GECONT")
        cls.usuario = get_user_model().objects.create_user(
            email="ficha-extensao@example.com", password="senha-segura"
        )
        cls.processo = Processo.objects.create(
            item_pca=42,
            exercicio=cls.exercicio,
            descricao_objeto="Processo para a extensão SEI Pro achar",
            tipo=cls.tipo,
            categoria=cls.categoria,
            unidade_organizacional=cls.unidade,
        )

    def setUp(self):
        self.client.force_login(self.usuario)

    def test_atributos_na_casca_dsgov_padrao(self):
        resposta = self.client.get(
            reverse(
                "pca:detalhe_processo",
                args=[self.processo.exercicio.ano, self.processo.item_pca],
            )
        )
        self.assertContains(resposta, f'data-item-pca="{self.processo.item_pca}"')
        self.assertContains(resposta, f'data-exercicio="{self.processo.exercicio.ano}"')

    def test_atributos_na_casca_tabler(self):
        from core.tests.test_casca_tabler import CASCA_TABLER

        with CASCA_TABLER:
            resposta = self.client.get(
                reverse(
                    "pca:detalhe_processo",
                    args=[self.processo.exercicio.ano, self.processo.item_pca],
                )
            )
        self.assertContains(resposta, f'data-item-pca="{self.processo.item_pca}"')
        self.assertContains(resposta, f'data-exercicio="{self.processo.exercicio.ano}"')
