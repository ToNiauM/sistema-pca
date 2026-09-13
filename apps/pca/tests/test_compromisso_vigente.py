"""O compromisso vigente aparece no detalhe do processo e no modal
"Registrar acompanhamento" com a mesma frase institucional do relatório
de movimentação (`compromisso_vigente`/`frase_compromisso`,
`apps.pca.relatorio_movimentacao`)."""

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from apps.catalogo.models import Categoria, Exercicio, SituacaoNormalizada, Tipo, Unidade
from apps.pca.models import Acompanhamento, Processo, Reuniao, SituacaoReuniao, TipoEvento


class CompromissoVigenteBaseTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.exercicio = Exercicio.objects.get(ano=2026)
        cls.unidade = Unidade.objects.create(nome="GEX-ITEC")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.tipo = Tipo.objects.create(nome="Aquisição")
        cls.situacao_normalizada = SituacaoNormalizada.objects.create(
            nome="Concluído (reunião)"
        )
        cls.editor = get_user_model().objects.create_user(
            email="editor-compromisso@pca.local", password="senha-segura"
        )
        cls.editor.groups.add(Group.objects.get(name="editor"))

    def setUp(self):
        self.client.force_login(self.editor)

    def _criar_processo(self, item_pca, **kwargs):
        defaults = {
            "descricao_objeto": f"Objeto {item_pca}",
            "tipo": self.tipo,
            "categoria": self.categoria,
            "unidade_organizacional": self.unidade,
        }
        defaults.update(kwargs)
        return Processo.objects.create(
            item_pca=item_pca, exercicio=self.exercicio, **defaults
        )

    def _criar_reuniao(self, data_reuniao):
        return Reuniao.objects.create(
            data=data_reuniao, situacao=SituacaoReuniao.FECHADA, exercicio=self.exercicio
        )

    def _criar_promessa(self, processo, *, reuniao, prazo_prometido, evento="Justificativa de teste"):
        return Acompanhamento.objects.create(
            processo=processo,
            referencia_data=reuniao.data,
            origem_hash=f"hash-{processo.pk}-{reuniao.data.isoformat()}",
            tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO,
            situacao=self.situacao_normalizada,
            prazo_prometido=prazo_prometido,
            reuniao=reuniao,
            evento=evento,
        )

    def _url_detalhe(self, processo):
        return reverse("pca:detalhe_processo", args=[self.exercicio.ano, processo.item_pca])

    def _url_modal(self, processo):
        return reverse("pca:acompanhamento_modal", args=[self.exercicio.ano, processo.item_pca])


class TestDetalheProcessoCompromissoVigente(CompromissoVigenteBaseTests):
    """O quadro "PRAZO ATUAL" da ficha PNCP: mesma frase institucional
    (`frase_compromisso`) na coluna Observação da timeline, mas o card de
    destaque é sempre presente (nunca condicionado a existir compromisso)
    e não repete o nome da UO (já está no par "Unidade" de
    Planejamento)."""

    def test_compromisso_vencido_mostra_uo_no_par_data_no_quadro_e_vencido(self):
        processo = self._criar_processo(101)
        reuniao = self._criar_reuniao(date.today() - timedelta(days=30))
        prazo = date.today() - timedelta(days=5)
        self._criar_promessa(processo, reuniao=reuniao, prazo_prometido=prazo)

        resposta = self.client.get(self._url_detalhe(processo))

        self.assertEqual(resposta.status_code, 200)
        conteudo = resposta.content.decode()
        self.assertIn("PRAZO ATUAL", conteudo)
        self.assertIn("GEX-ITEC", conteudo)  # par "Unidade" de Planejamento
        self.assertIn(prazo.strftime("%d/%m/%Y"), conteudo)
        self.assertIn("vencido", conteudo)

    def test_sem_nenhuma_promessa_quadro_mostra_nao_informado_e_nao_quebra(self):
        # Sem `prazo_entrega` e sem nenhuma promessa, `prazo_efetivo` é
        # `None`: o quadro PRAZO ATUAL continua presente (nunca
        # escondido), mostrando "Não informado" em vez de zero ou data
        # vazia.
        processo = self._criar_processo(102)

        resposta = self.client.get(self._url_detalhe(processo))

        self.assertEqual(resposta.status_code, 200)
        conteudo = resposta.content.decode()
        self.assertIn("PRAZO ATUAL", conteudo)
        self.assertIn("Não informado", conteudo)

    def test_timeline_mostra_a_mesma_frase_do_compromisso(self):
        processo = self._criar_processo(103)
        reuniao = self._criar_reuniao(date.today() - timedelta(days=10))
        prazo = date.today() + timedelta(days=10)
        self._criar_promessa(
            processo, reuniao=reuniao, prazo_prometido=prazo, evento="Compromisso de teste 103"
        )

        resposta = self.client.get(self._url_detalhe(processo))

        conteudo = resposta.content.decode()
        self.assertIn("Compromisso de teste 103", conteudo)
        self.assertIn("comprometeu-se a entregar até", conteudo)


class TestModalCompromissoVigente(CompromissoVigenteBaseTests):
    def test_get_mostra_aviso_de_compromisso_vigente(self):
        # O título do aviso no modal é "Prazo atual:"; a frase
        # institucional (`frase_compromisso`) continua a mesma.
        processo = self._criar_processo(104)
        reuniao = self._criar_reuniao(date.today() - timedelta(days=3))
        prazo = date.today() + timedelta(days=15)
        self._criar_promessa(processo, reuniao=reuniao, prazo_prometido=prazo)

        resposta = self.client.get(self._url_modal(processo), HTTP_HX_REQUEST="true")

        self.assertEqual(resposta.status_code, 200)
        conteudo = resposta.content.decode()
        self.assertIn("Prazo atual:", conteudo)
        self.assertIn("br-message", conteudo)
        self.assertIn("info", conteudo)

    def test_get_sem_promessa_nao_mostra_aviso(self):
        processo = self._criar_processo(105)

        resposta = self.client.get(self._url_modal(processo), HTTP_HX_REQUEST="true")

        conteudo = resposta.content.decode()
        self.assertNotIn("Prazo atual:", conteudo)
