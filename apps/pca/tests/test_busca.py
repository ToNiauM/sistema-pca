"""Serviço único de busca transversal (`apps.pca.busca.aplicar_busca`).
Fixtures reais via ORM direto (`django.test.TestCase`, nunca mock) —
mesmo padrão de `TestTabelaColunasDinamicas` em `test_colunas_tabela.py`,
sem depender do XLSX real."""

from decimal import Decimal

from django.test import TestCase

from apps.catalogo.models import Categoria, Exercicio, Tipo, Unidade
from apps.pca.busca import LIMITE_TERMO, aplicar_busca
from apps.pca.models import Estado, Processo, ProcessoSEI, Situacao


class _BaseBusca(TestCase):
    """Setup comum: vocabulário mínimo + `para_listagem()` já anotado
    (mesma fonte que `queryset_filtrado`/`views_busca.busca_view`
    consomem)."""

    @classmethod
    def setUpTestData(cls):
        cls.exercicio = Exercicio.objects.get(ano=2026)
        cls.tipo = Tipo.objects.create(nome="Aquisição")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.unidade = Unidade.objects.create(nome="Presidência")

    def base_qs(self):
        return Processo.objects.para_listagem()

    def criar(self, item_pca, **kwargs):
        defaults = dict(
            descricao_objeto=f"Processo de teste {item_pca}",
            tipo=self.tipo,
            categoria=self.categoria,
            unidade_organizacional=self.unidade,
            exercicio=self.exercicio,
        )
        defaults.update(kwargs)
        return Processo.objects.create(item_pca=item_pca, **defaults)


class TestNormalizacaoDinheiro(_BaseBusca):
    """As 4 grafias produzem o mesmo Decimal; 1400 nunca colide com
    14005 (substring proibida em Decimal)."""

    def test_quatro_grafias_encontram_o_mesmo_processo(self):
        alvo = self.criar(1, valor_estimado=Decimal("1400.00"))
        # ruído: valor "vizinho" que NUNCA deve colidir por substring.
        self.criar(2, valor_estimado=Decimal("14005.00"))

        for termo in ("1400", "1.400", "1400,00", "R$ 1.400,00"):
            with self.subTest(termo=termo):
                qs, avisos = aplicar_busca(self.base_qs(), termo)
                self.assertEqual(avisos, [])
                self.assertEqual(list(qs.values_list("pk", flat=True)), [alvo.pk])

    def test_valor_vizinho_14005_nunca_aparece_na_busca_por_1400(self):
        self.criar(1, valor_estimado=Decimal("1400.00"))
        vizinho = self.criar(2, valor_estimado=Decimal("14005.00"))

        qs, _ = aplicar_busca(self.base_qs(), "1400")
        self.assertNotIn(vizinho.pk, qs.values_list("pk", flat=True))


class TestUniaoDeCampos(_BaseBusca):
    """A união nunca para no primeiro achado: 5 registros diferentes,
    cada um casando por uma família de campo diferente, aparecem todos
    juntos na mesma busca por "1400"."""

    def test_1400_encontra_cinco_registros_por_familias_diferentes(self):
        por_item = self.criar(1400)
        por_descricao = self.criar(1, descricao_objeto="Contém 1400 no meio do texto")
        unidade_1400 = Unidade.objects.create(nome="Unidade 1400")
        por_unidade = self.criar(2, unidade_organizacional=unidade_1400)
        por_sei = self.criar(3)
        ProcessoSEI.objects.create(processo=por_sei, numero_sei="SEI 1400/2026")
        por_valor = self.criar(4, valor_estimado=Decimal("1400.00"))
        # ruído: não deve aparecer.
        self.criar(5, descricao_objeto="Nada a ver por aqui")

        qs, avisos = aplicar_busca(self.base_qs(), "1400")
        self.assertEqual(avisos, [])
        encontrados = set(qs.values_list("pk", flat=True))
        self.assertEqual(
            encontrados,
            {por_item.pk, por_descricao.pk, por_unidade.pk, por_sei.pk, por_valor.pk},
        )

    def test_processo_com_dois_numeros_sei_aparece_uma_unica_vez(self):
        """Exists (não JOIN): nenhuma duplicação por 1:N."""
        processo = self.criar(1)
        ProcessoSEI.objects.create(processo=processo, numero_sei="SEI 1400/2026")
        ProcessoSEI.objects.create(processo=processo, numero_sei="SEI 999/2026")

        qs, _ = aplicar_busca(self.base_qs(), "1400")
        self.assertEqual(qs.filter(pk=processo.pk).count(), 1)


class TestData(_BaseBusca):
    """Data só dd/mm/aaaa completa e válida; inválida gera aviso, nunca
    é reinterpretada como dinheiro; termo sem barra nunca aciona a
    interpretação de data."""

    def test_data_invalida_nao_encontra_nada_e_gera_aviso(self):
        self.criar(1, prazo_entrega=None)
        qs, avisos = aplicar_busca(self.base_qs(), "31/02/2026")
        self.assertEqual(list(qs), [])
        self.assertEqual(
            avisos, ["Data inválida: 31/02/2026 não existe no calendário."]
        )

    def test_data_invalida_nunca_vira_tentativa_de_dinheiro(self):
        # Se "31/02/2026" fosse (erroneamente) tentado como dinheiro, um
        # processo com valor exatamente igual a essa "leitura" apareceria.
        # Não deve existir NENHUM jeito de casar — a barra descarta a
        # tentativa monetária por completo (mutuamente exclusivas).
        self.criar(1, valor_estimado=Decimal("31.00"))
        self.criar(2, valor_estimado=Decimal("2026.00"))
        qs, avisos = aplicar_busca(self.base_qs(), "31/02/2026")
        self.assertEqual(list(qs), [])
        self.assertTrue(avisos)

    def test_termo_sem_barra_nunca_aciona_interpretacao_de_data(self):
        alvo = self.criar(1400, prazo_entrega=None)
        qs, avisos = aplicar_busca(self.base_qs(), "1400")
        self.assertEqual(avisos, [])
        self.assertIn(alvo.pk, qs.values_list("pk", flat=True))

    def test_data_valida_encontra_por_igualdade_exata(self):
        from datetime import date

        alvo = self.criar(1, prazo_entrega=date(2026, 3, 15))
        outro = self.criar(2, prazo_entrega=date(2026, 3, 16))
        qs, avisos = aplicar_busca(self.base_qs(), "15/03/2026")
        self.assertEqual(avisos, [])
        encontrados = set(qs.values_list("pk", flat=True))
        self.assertIn(alvo.pk, encontrados)
        self.assertNotIn(outro.pk, encontrados)


class TestRotulos(_BaseBusca):
    """Rótulos pela representação apresentada; "Concluído" nunca casa
    um processo cancelado, mesmo com a coluna crua residual
    `situacao="concluido"`."""

    def test_concluido_nunca_encontra_processo_cancelado_com_situacao_residual(self):
        cancelado = self.criar(
            1, estado=Estado.CANCELADO, situacao=Situacao.CONCLUIDO
        )
        ativo_concluido = self.criar(
            2, estado=Estado.ATIVO, situacao=Situacao.CONCLUIDO
        )

        qs, avisos = aplicar_busca(self.base_qs(), "Concluído")
        self.assertEqual(avisos, [])
        encontrados = set(qs.values_list("pk", flat=True))
        self.assertNotIn(cancelado.pk, encontrados)
        self.assertIn(ativo_concluido.pk, encontrados)

    def test_cancelado_encontra_pelo_rotulo_do_eixo_estado(self):
        cancelado = self.criar(1, estado=Estado.CANCELADO)
        ativo = self.criar(2, estado=Estado.ATIVO)

        qs, _ = aplicar_busca(self.base_qs(), "Cancelado")
        encontrados = set(qs.values_list("pk", flat=True))
        self.assertIn(cancelado.pk, encontrados)
        self.assertNotIn(ativo.pk, encontrados)


class TestAcentoECaixa(_BaseBusca):
    """Texto por trecho, sem caixa/acento."""

    def test_tres_grafias_encontram_o_mesmo_conjunto(self):
        alvo = self.criar(1, descricao_objeto="Item não classificado nesta reunião")
        for termo in ("nao classificado", "NÃO CLASSIFICADO", "não classificado"):
            with self.subTest(termo=termo):
                qs, _ = aplicar_busca(self.base_qs(), termo)
                self.assertIn(alvo.pk, qs.values_list("pk", flat=True))


class TestLimiteDeCaracteres(_BaseBusca):
    """Corte de 200 caracteres antes de qualquer interpretação."""

    def test_termo_e_cortado_para_200_caracteres_antes_de_interpretar(self):
        prefixo = "A" * LIMITE_TERMO
        alvo = self.criar(1, descricao_objeto=f"{prefixo} sufixo real do objeto")
        termo_longo = prefixo + "x" * 50  # 250 caracteres, só os 200 primeiros contam
        self.assertEqual(len(termo_longo), LIMITE_TERMO + 50)

        qs, avisos = aplicar_busca(self.base_qs(), termo_longo)
        self.assertEqual(avisos, [])
        self.assertIn(alvo.pk, qs.values_list("pk", flat=True))


class TestTermoVazio(_BaseBusca):
    def test_termo_vazio_devolve_o_queryset_original_sem_filtrar(self):
        self.criar(1)
        self.criar(2)
        base = self.base_qs()
        qs, avisos = aplicar_busca(base, "")
        self.assertEqual(avisos, [])
        self.assertEqual(qs.count(), base.count())
