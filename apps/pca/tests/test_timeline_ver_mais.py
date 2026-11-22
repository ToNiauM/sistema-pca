"""A tabela "Acompanhamentos e prazos" da ficha mostra só
os 5 acompanhamentos mais recentes por padrão (mais novo primeiro), com
"Ver mais (N)"/"Ver menos" alternando por link puro (`?acompanhamentos=
todos`), sem nenhuma consulta extra (`assertNumQueries` fixo). Mesmo padrão
de fixture de `test_compromisso_vigente.py`/`test_navegacao_detalhe.py`
(`Exercicio.objects.get(ano=2026)`, `TestCase`, `Client.force_login`)."""

from datetime import date, timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils.html import escape

from apps.catalogo.models import Categoria, Exercicio, SituacaoNormalizada, Tipo, Unidade
from apps.pca.models import Acompanhamento, Processo, TipoEvento
from apps.pca.views import TIMELINE_RESUMIDA


class TimelineVerMaisTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.exercicio = Exercicio.objects.get(ano=2026)
        cls.unidade = Unidade.objects.create(nome="Unidade Teste xdeab")
        cls.categoria = Categoria.objects.create(nome="Serviços")
        cls.tipo = Tipo.objects.create(nome="Aquisição")
        cls.situacao_normalizada = SituacaoNormalizada.objects.create(
            nome="Em andamento (xdeab)"
        )
        cls.editor = get_user_model().objects.create_user(
            email="editor-timeline@pca.local", password="senha-segura-260918"
        )
        # A timeline (Acompanhamentos e prazos) passou a
        # exigir `pca.view_acompanhamento`; `configurar_grupos` (idempotente,
        # não roda sozinho em produção) garante a permissão no grupo
        # `editor` também no banco de teste.
        call_command("configurar_grupos", stdout=StringIO())
        cls.editor.groups.add(Group.objects.get(name="editor"))

    def setUp(self):
        self.client.force_login(self.editor)

    def _criar_processo(self, item_pca):
        return Processo.objects.create(
            item_pca=item_pca,
            exercicio=self.exercicio,
            descricao_objeto=f"Objeto {item_pca}",
            tipo=self.tipo,
            categoria=self.categoria,
            unidade_organizacional=self.unidade,
        )

    def _criar_acompanhamentos(self, processo, quantidade):
        """`quantidade` acompanhamentos de datas distintas, sem reunião
        (reunião é opcional) — a mais recente é a de maior
        `referencia_data`."""
        base = date(2026, 1, 1)
        for i in range(quantidade):
            dia = base + timedelta(days=i)
            Acompanhamento.objects.create(
                processo=processo,
                referencia_data=dia,
                origem_hash=f"hash-timeline-{processo.item_pca}-{i}",
                tipo_evento=TipoEvento.AUTOMATICO.value,
                evento=f"Evento {i}",
                situacao=self.situacao_normalizada,
            )

    def _url_detalhe(self, processo, querystring=""):
        url = reverse("pca:detalhe_processo", args=[self.exercicio.ano, processo.item_pca])
        return f"{url}?{querystring}" if querystring else url

    def test_com_mais_de_cinco_mostra_so_os_cinco_mais_recentes(self):
        processo = self._criar_processo(1)
        self._criar_acompanhamentos(processo, TIMELINE_RESUMIDA + 2)

        resposta = self.client.get(self._url_detalhe(processo))
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(len(resposta.context["timeline_exibida"]), TIMELINE_RESUMIDA)
        # a mais recente (maior referencia_data) é a primeira linha exibida
        self.assertEqual(
            resposta.context["timeline_exibida"][0].evento, f"Evento {TIMELINE_RESUMIDA + 1}"
        )
        html = resposta.content.decode()
        self.assertContains(resposta, "Ver mais (2)")
        self.assertNotContains(resposta, "Ver menos")
        self.assertEqual(html.count("<td data-th=\"Data\">"), TIMELINE_RESUMIDA)

    def test_com_acompanhamentos_todos_mostra_tudo(self):
        processo = self._criar_processo(2)
        total = TIMELINE_RESUMIDA + 2
        self._criar_acompanhamentos(processo, total)

        resposta = self.client.get(self._url_detalhe(processo, "acompanhamentos=todos"))
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(len(resposta.context["timeline_exibida"]), total)
        html = resposta.content.decode()
        self.assertContains(resposta, "Ver menos")
        self.assertNotContains(resposta, "Ver mais (")
        self.assertEqual(html.count("<td data-th=\"Data\">"), total)

    def test_com_cinco_ou_menos_nao_ha_link_algum(self):
        processo = self._criar_processo(3)
        self._criar_acompanhamentos(processo, 3)

        resposta = self.client.get(self._url_detalhe(processo))
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(len(resposta.context["timeline_exibida"]), 3)
        html = resposta.content.decode()
        self.assertEqual(html.count("<td data-th=\"Data\">"), 3)
        self.assertNotContains(resposta, "Ver mais (")
        self.assertNotContains(resposta, "Ver menos")

    def test_ver_mais_preserva_querystring_da_tabela_e_termina_em_ancora(self):
        processo = self._criar_processo(4)
        self._criar_acompanhamentos(processo, TIMELINE_RESUMIDA + 1)

        resposta = self.client.get(self._url_detalhe(processo, "q=teste"))
        self.assertEqual(resposta.status_code, 200)
        url_esperada = (
            f"{reverse('pca:detalhe_processo', args=[self.exercicio.ano, processo.item_pca])}"
            "?q=teste&acompanhamentos=todos#acompanhamentos"
        )
        self.assertEqual(resposta.context["url_ver_mais"], url_esperada)
        self.assertContains(resposta, f'href="{escape(url_esperada)}"')

    def test_numero_de_consultas_nao_sobe_com_a_timeline(self):
        processo = self._criar_processo(5)
        self._criar_acompanhamentos(processo, TIMELINE_RESUMIDA + 2)

        # Uma primeira chamada "aquece" caches de nível de processo
        # (ContentType etc.) usados pelo restante da suíte; o número fixo
        # abaixo é medido a partir da SEGUNDA chamada, dentro do bloco.
        self.client.get(self._url_detalhe(processo))
        # 13: as larguras de coluna saíram com a grade estilo Excel.
        # Fase 43 — 15: +1 do contador "Para avaliar" do menu (equipe/diretoria) e +1 da aba
        # "Solicitações" da ficha; ambas constantes, não crescem com a timeline (que é o que este teste guarda).
        with self.assertNumQueries(15):
            self.client.get(self._url_detalhe(processo))
