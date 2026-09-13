from datetime import date

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.catalogo.models import Exercicio
from apps.pca.models import Reuniao
from apps.pca.services import criar_reuniao


class TestReuniaoValidaAnoContraExercicio(TestCase):
    @classmethod
    def setUpTestData(cls):
        # ano=2026 já existe no banco de teste via migração de dados
        # pca.0008_backfill_exercicio_2026 — get_or_create() evita a
        # UniqueViolation em "catalogo_exercicio_ano_key" que um .create()
        # simples produziria (mesmo padrão de test_multiexercicio_filtros.py).
        cls.exercicio, _ = Exercicio.objects.get_or_create(
            ano=2026, defaults={"rotulo": "PCA 2026"}
        )

    def test_ano_anterior_ao_exercicio_e_rejeitado(self):
        reuniao = Reuniao(data=date(2025, 9, 1), exercicio=self.exercicio)
        with self.assertRaises(ValidationError) as ctx:
            reuniao.full_clean()
        self.assertIn("data", ctx.exception.message_dict)

    def test_data_dentro_do_proprio_exercicio_e_aceita(self):
        Reuniao(data=date(2026, 9, 1), exercicio=self.exercicio).full_clean()

    def test_encerramento_em_janeiro_do_ano_seguinte_e_aceito(self):
        Reuniao(data=date(2027, 1, 15), exercicio=self.exercicio).full_clean()

    def test_dois_anos_depois_do_exercicio_e_rejeitado(self):
        reuniao = Reuniao(data=date(2028, 1, 1), exercicio=self.exercicio)
        with self.assertRaises(ValidationError) as ctx:
            reuniao.full_clean()
        self.assertIn("data", ctx.exception.message_dict)

    def test_criar_reuniao_propaga_validationerror_e_nao_cria_nada(self):
        with self.assertRaises(ValidationError):
            criar_reuniao(data=date(2025, 9, 1), exercicio=self.exercicio)
        self.assertEqual(Reuniao.objects.count(), 0)
