"""Testes de `apps/pca/mudancas.py` — módulo puro
que propõe texto para o campo Observação do modal "Registrar
acompanhamento" a partir do histórico de edições do item desde o último
Acompanhamento registrado."""

from datetime import date
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.catalogo.models import Categoria, Exercicio, SituacaoNormalizada, Tipo, Unidade
from apps.pca.mudancas import frase, propor_texto
from apps.pca.models import Acompanhamento, Processo, TipoEvento


class TestFrase(TestCase):
    """`frase(campo, antes, depois)` — unidade, sem view/histórico."""

    @classmethod
    def setUpTestData(cls):
        cls.unidade_antes = Unidade.objects.create(nome="GEX-ITEC")
        cls.unidade_depois = Unidade.objects.create(nome="GEX-ADM")

    def test_moeda(self):
        self.assertEqual(
            frase("valor_estimado", Decimal("120000.00"), Decimal("148500.00")),
            "Valor estimado alterado de R$ 120.000,00 para R$ 148.500,00.",
        )

    def test_data(self):
        self.assertEqual(
            frase("data_assinatura_contrato", date(2026, 1, 10), date(2026, 2, 20)),
            "Data de assinatura do contrato alterada de 10/01/2026 para 20/02/2026.",
        )

    def test_mes_por_extenso(self):
        self.assertEqual(
            frase("mes_previsto", 6, 9),
            "Mês previsto alterado de junho para setembro.",
        )

    def test_fk_por_nome(self):
        self.assertEqual(
            frase("unidade_organizacional", self.unidade_antes, self.unidade_depois),
            "Unidade organizacional alterada de GEX-ITEC para GEX-ADM.",
        )

    def test_texto_longo_objeto_gera_frase_generica(self):
        self.assertEqual(
            frase("descricao_objeto", "Objeto A", "Objeto B"),
            "Objeto atualizado.",
        )

    def test_texto_longo_justificativa_gera_frase_generica(self):
        self.assertEqual(
            frase("justificativa", "porque sim", "porque não"),
            "Justificativa do item atualizada.",
        )

    def test_vazio_para_valor_usa_definido_como(self):
        self.assertEqual(
            frase("prazo_entrega", None, date(2026, 4, 30)),
            "Prazo inicial definido como 30/04/2026.",
        )

    def test_valor_para_vazio_usa_removido(self):
        self.assertEqual(
            frase("fornecedor_razao_social", "Fornecedor ACME Ltda", ""),
            "Fornecedor removido.",
        )

    def test_campo_fora_da_lista_e_ignorado(self):
        self.assertIsNone(frase("campo_que_nao_existe", "a", "b"))

    def test_sem_mudanca_devolve_none(self):
        self.assertIsNone(frase("valor_estimado", Decimal("100.00"), Decimal("100.00")))


class TestProporTexto(TestCase):
    """`propor_texto(processo)` — integração com `Processo.history` e
    `Processo.acompanhamentos` (ORM real, `TestCase` com rollback por
    teste)."""

    @classmethod
    def setUpTestData(cls):
        cls.exercicio = Exercicio.objects.get(ano=2026)
        cls.unidade = Unidade.objects.create(nome="GEX-ITEC")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.tipo = Tipo.objects.create(nome="Aquisição")
        cls.situacao_normalizada = SituacaoNormalizada.objects.create(
            nome="Em tramitação (teste mudancas)"
        )
        cls.editor = get_user_model().objects.create_user(
            email="editor-mudancas@pca.local", password="senha-segura"
        )
        email_robo = getattr(settings, "SEI_USUARIO_TECNICO_EMAIL", None) or "robo-sei@pca.local"
        cls.robo, _ = get_user_model().objects.get_or_create(
            email=email_robo,
            defaults={"is_active": False, "first_name": "Robô SEI"},
        )

    def _criar_processo(self, item_pca, **kwargs):
        defaults = {
            "descricao_objeto": f"Objeto {item_pca}",
            "tipo": self.tipo,
            "categoria": self.categoria,
            "unidade_organizacional": self.unidade,
            "valor_estimado": Decimal("100.00"),
        }
        defaults.update(kwargs)
        processo = Processo(item_pca=item_pca, exercicio=self.exercicio, **defaults)
        processo._history_user = self.editor
        processo.save()
        return processo

    def _editar(self, processo, *, usuario, **kwargs):
        for campo, valor in kwargs.items():
            setattr(processo, campo, valor)
        processo._history_user = usuario
        processo.save()
        return processo

    def _criar_acompanhamento(self, processo):
        quantos = Acompanhamento.objects.filter(processo=processo).count()
        return Acompanhamento.objects.create(
            processo=processo,
            referencia_data=date.today(),
            origem_hash=f"hash-mudancas-{processo.pk}-{quantos}",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO,
            situacao=self.situacao_normalizada,
        )

    def test_consolida_tres_edicoes_do_mesmo_campo_em_uma_frase(self):
        processo = self._criar_processo(1, valor_estimado=Decimal("100.00"))
        self._criar_acompanhamento(processo)
        self._editar(processo, usuario=self.editor, valor_estimado=Decimal("150.00"))
        self._editar(processo, usuario=self.editor, valor_estimado=Decimal("200.00"))
        self._editar(processo, usuario=self.editor, valor_estimado=Decimal("250.00"))

        texto = propor_texto(processo)

        self.assertEqual(texto, "Valor estimado alterado de R$ 100,00 para R$ 250,00.")

    def test_corte_pelo_ultimo_acompanhamento_mudanca_anterior_nao_entra(self):
        processo = self._criar_processo(2, valor_estimado=Decimal("100.00"))
        self._editar(processo, usuario=self.editor, valor_estimado=Decimal("150.00"))
        self._criar_acompanhamento(processo)
        self._editar(processo, usuario=self.editor, valor_estimado=Decimal("200.00"))

        texto = propor_texto(processo)

        self.assertEqual(texto, "Valor estimado alterado de R$ 150,00 para R$ 200,00.")
        self.assertNotIn("100,00", texto)

    def test_edicao_do_usuario_tecnico_nao_gera_proposta(self):
        processo = self._criar_processo(3, valor_estimado=Decimal("100.00"))
        self._criar_acompanhamento(processo)
        self._editar(processo, usuario=self.robo, valor_estimado=Decimal("999.00"))

        self.assertEqual(propor_texto(processo), "")

    def test_item_sem_historico_novo_devolve_vazio(self):
        processo = self._criar_processo(4, valor_estimado=Decimal("100.00"))
        self._criar_acompanhamento(processo)

        self.assertEqual(propor_texto(processo), "")

    def test_sem_acompanhamento_considera_todas_as_versoes(self):
        processo = self._criar_processo(5, valor_estimado=Decimal("100.00"))
        self._editar(processo, usuario=self.editor, valor_estimado=Decimal("300.00"))

        texto = propor_texto(processo)

        self.assertEqual(texto, "Valor estimado alterado de R$ 100,00 para R$ 300,00.")

    def test_referencia_fk_apagada_no_historico_nao_quebra_a_proposta(self):
        """Achado real (banco de dev, 22/09/2026): 11 dos 155 itens têm uma
        versão do histórico apontando para uma linha de catálogo (Unidade/
        Tipo/Categoria/Modalidade/Instrumento) já excluída (fusão/depuração
        de vocabulário) — `getattr` levanta `DoesNotExist` em vez de
        devolver `None`. `propor_texto` tem que degradar pulando só a frase
        do campo quebrado, nunca 500 o modal inteiro por causa disso."""
        unidade_removida_depois = Unidade.objects.create(nome="Unidade removida depois")
        processo = self._criar_processo(
            6,
            unidade_organizacional=unidade_removida_depois,
            valor_estimado=Decimal("100.00"),
        )
        self._criar_acompanhamento(processo)
        self._editar(
            processo,
            usuario=self.editor,
            unidade_organizacional=self.unidade,
            valor_estimado=Decimal("200.00"),
        )
        unidade_removida_depois.delete()

        texto = propor_texto(processo)

        self.assertEqual(texto, "Valor estimado alterado de R$ 100,00 para R$ 200,00.")
