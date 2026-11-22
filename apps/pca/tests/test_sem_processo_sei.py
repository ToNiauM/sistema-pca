""""Sem processo SEI" no lugar de Autuado/A autuar/Não se
aplica (campo `situacao_sei` removido, decisão do usuário).

Ter ou não processo SEI é derivado do próprio nº SEI. Item sem número é
fácil de identificar (card do Início, filtro pela URL com etiqueta,
Assistente, exportação) e nunca é atualizado pela sincronização com o SEI:
não há de onde tirar informação, e a sincronização não inventa."""

import json
import tempfile

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.assistente import ferramentas
from apps.catalogo.models import (
    Categoria,
    Exercicio,
    SituacaoExercicio,
    SituacaoNormalizada,
    Tipo,
    Unidade,
)
from apps.pca.exportacao import _extrair
from apps.pca.models import Processo, ProcessoSEI, Situacao
from apps.pca.sei import aplicador
from apps.pca.sei.regras import Proposta


class TestSemProcessoSei(TestCase):
    @classmethod
    def setUpTestData(cls):
        for nome in ("Concluído", "Em tramitação", "Sem informação"):
            SituacaoNormalizada.objects.get_or_create(nome=nome)
        cls.exercicio, _ = Exercicio.objects.get_or_create(
            ano=2026, defaults={"situacao": SituacaoExercicio.ABERTO}
        )
        cls.vigente = Tipo.objects.create(nome="Vigente")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.unidade = Unidade.objects.create(nome="Gerência de Teste")
        cls.usuario = get_user_model().objects.create_superuser(email="sei@example.com", password="x")
        cls.sem_a = cls._processo(10)
        cls.sem_b = cls._processo(11)
        cls.com = cls._processo(12, numero="00001.000012/2026-12")

    @classmethod
    def _processo(cls, item, numero=None):
        processo = Processo(
            item_pca=item, exercicio=cls.exercicio, descricao_objeto=f"Objeto {item}",
            tipo=cls.vigente, categoria=cls.categoria, unidade_organizacional=cls.unidade,
            estado="ativo", situacao=Situacao.NO_PRAZO,
        )
        processo._history_user = cls.usuario
        processo.save()
        if numero:
            ProcessoSEI.objects.create(processo=processo, numero_sei=numero)
        return processo

    def setUp(self):
        self.cliente = Client(HTTP_X_FORWARDED_PROTO="https")
        self.cliente.force_login(self.usuario)

    def test_sincronizacao_nao_toca_item_sem_numero(self):
        proposta = Proposta(
            item_pca=10, exercicio=2026, processo_principal=None,
            pendencias=[("sem_numero_sei", "Item ativo sem nenhum número de processo SEI cadastrado.")],
        )
        with tempfile.TemporaryDirectory() as pasta, override_settings(SEI_DATA_DIR=pasta):
            resumo = aplicador.aplicar([proposta])
        self.sem_a.refresh_from_db()
        # Tipo Vigente em No prazo: sem o pulo, a regra automática o
        # concluiria em nome da sincronização; e a pendência viraria
        # acompanhamento.
        self.assertEqual(self.sem_a.situacao, Situacao.NO_PRAZO)
        self.assertEqual(self.sem_a.acompanhamentos.count(), 0)
        self.assertEqual(resumo["sem_numero_sei"], 1)
        self.assertEqual(resumo["pendencias_novas"], 0)

    def test_filtro_pela_url_com_etiqueta(self):
        resposta = self.cliente.get(reverse("pca:tabela"), {"sem_processo_sei": "1", "exercicio": 2026})
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Sem processo SEI")
        self.assertEqual({p.item_pca for p in resposta.context["pagina"]}, {10, 11})

    def test_contador_no_card_do_inicio(self):
        with tempfile.TemporaryDirectory() as pasta, override_settings(SEI_DATA_DIR=pasta):
            resposta = self.cliente.get(reverse("core:inicio"), {"exercicio": 2026})
        self.assertContains(resposta, "2 item(ns) sem processo SEI")
        self.assertContains(resposta, "sem_processo_sei=1")

    def test_contador_no_card_do_inicio_na_casca_tabler(self):
        from core.tests.test_casca_tabler import CASCA_TABLER

        with CASCA_TABLER, tempfile.TemporaryDirectory() as pasta, override_settings(SEI_DATA_DIR=pasta):
            resposta = self.cliente.get(reverse("core:inicio"), {"exercicio": 2026})
        self.assertContains(resposta, "2 item(ns) sem processo SEI")
        self.assertContains(resposta, "sem_processo_sei=1")

    def test_assistente_filtra_e_a_ficha_informa(self):
        envelope = ferramentas.executar(
            "consultar_processos",
            json.dumps({"exercicio": 2026, "sem_processo_sei": True}),
            usuario=self.usuario, exercicio_padrao=self.exercicio,
        )
        self.assertEqual(envelope.dados["total"], 2)
        self.assertIn("sem_processo_sei=1", envelope.referencias[0]["url"])
        ficha = ferramentas.ficha(self.usuario, exercicio=2026, item=10)
        self.assertIs(ficha.dados["sem_processo_sei"], True)
        self.assertIs(ferramentas.ficha(self.usuario, exercicio=2026, item=12).dados["sem_processo_sei"], False)

    def test_exportacao_escreve_sem_processo_sei(self):
        processo = Processo.objects.prefetch_related("numeros_sei").get(pk=self.sem_a.pk)
        self.assertEqual(_extrair(processo, "numeros_sei"), "Sem processo SEI")
