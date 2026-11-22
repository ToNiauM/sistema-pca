"""PCA DSGov com a cara do PNCP (proposta aprovada em
14/10/2026). Só a apresentação muda; estes testes provam que nada do que
existia se perdeu: Processos ganha a visualização Lista (a Tabela continua o
padrão, com colunas, exportação e paginação) e a ficha passa a ter cartões de
valor nas cores do PNCP, a linha "Compromisso vigente" e abas."""

import json
from datetime import date
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.db import connection
from django.http import QueryDict
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.catalogo.models import Categoria, Exercicio, Tipo, Unidade
from apps.pca.filtros import querystring_tabela, vista_valida
from apps.pca.models import Processo, Situacao

HTTPS = {"HTTP_X_FORWARDED_PROTO": "https"}


class PadraoPncpBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("configurar_grupos", stdout=StringIO())
        usuario = get_user_model()
        cls.editor = usuario.objects.create_user(email="editor-p5n@example.com", password="senha-segura")
        cls.editor.groups.add(Group.objects.get(name="editor"))
        cls.leitor = usuario.objects.create_user(email="leitor-p5n@example.com", password="senha-segura")
        cls.leitor.groups.add(Group.objects.get(name="visualizador"))
        cls.exercicio = Exercicio.objects.get(ano=2026)
        from apps.catalogo.models import SituacaoNormalizada
        from apps.pca.services import MAPA_SITUACAO_NORMALIZADA_POR_SITUACAO

        for nome in MAPA_SITUACAO_NORMALIZADA_POR_SITUACAO.values():
            SituacaoNormalizada.objects.get_or_create(nome=nome)
        unidade = Unidade.objects.create(nome="GEX-P5N")
        categoria = Categoria.objects.create(nome="Serviços P5N")
        tipo = Tipo.objects.create(nome="Nova Contratação P5N")
        cls.processos = [
            Processo.objects.create(
                item_pca=numero,
                exercicio=cls.exercicio,
                descricao_objeto=f"Objeto do item {numero} p5n",
                tipo=tipo,
                categoria=categoria,
                unidade_organizacional=unidade,
                situacao=Situacao.NO_PRAZO,
                valor_estimado=1000 * numero,
                mes_previsto=(numero % 12) + 1,
                prazo_entrega=date(2026, 11, 30),
            )
            for numero in range(1, 26)
        ]

    def _get(self, usuario, url, **params):
        self.client.force_login(usuario)
        return self.client.get(url, params, **HTTPS)


class TestVistaListaProcessos(PadraoPncpBase):
    def test_vista_valida_so_aceita_lista_ou_cai_na_tabela(self):
        self.assertEqual(vista_valida("lista"), "lista")
        self.assertEqual(vista_valida("tabela"), "tabela")
        self.assertEqual(vista_valida("<script>"), "tabela")
        self.assertEqual(vista_valida(None), "tabela")

    def test_tabela_continua_o_padrao_com_colunas_e_exportar(self):
        resposta = self._get(self.editor, reverse("pca:tabela"), exercicio=2026)
        conteudo = resposta.content.decode()
        self.assertEqual(resposta.context["vista"], "tabela")
        self.assertIn('<div class="br-table small">', conteudo)
        self.assertIn('id="acordeao-colunas"', conteudo)
        self.assertIn("Exportar XLSX", conteudo)
        self.assertNotIn('class="dsgov-resultado"', conteudo)
        self.assertNotIn('id="estado-vista"', conteudo)

    def test_lista_mostra_resultados_com_acoes_e_ancora(self):
        resposta = self._get(self.editor, reverse("pca:tabela"), exercicio=2026, vista="lista")
        conteudo = resposta.content.decode()
        self.assertEqual(resposta.context["vista"], "lista")
        self.assertEqual(conteudo.count('class="dsgov-resultado"'), 20)
        primeiro = self.processos[0]
        self.assertIn(f'id="item-{primeiro.pk}"', conteudo)
        self.assertIn("Item 1/2026", conteudo)
        self.assertIn("Objeto do item 1 p5n", conteudo)
        self.assertIn(f'aria-label="Registrar acompanhamento do item {primeiro.item_pca}"', conteudo)
        self.assertIn("<strong>Unidade:</strong> GEX-P5N", conteudo)
        self.assertIn("Prazo atual", conteudo)
        self.assertIn('id="estado-vista"', conteudo)
        self.assertIn("Exportar XLSX", conteudo)
        self.assertIn("Soma do valor estimado (resultado filtrado)", conteudo)
        self.assertNotIn('<div class="br-table small">', conteudo)
        self.assertNotIn('id="acordeao-colunas"', conteudo)

    def test_lista_sem_permissao_de_acompanhamento_nao_mostra_prazo(self):
        conteudo = self._get(self.leitor, reverse("pca:tabela"), exercicio=2026, vista="lista").content.decode()
        self.assertNotIn("Prazo atual", conteudo)
        self.assertNotIn("Registrar acompanhamento do item", conteudo)

    def test_vista_lista_entra_no_estado_da_tabela_e_na_sessao(self):
        self.assertIn("vista=lista", querystring_tabela(QueryDict("exercicio=2026&vista=lista")))
        self.assertNotIn("vista", querystring_tabela(QueryDict("exercicio=2026&vista=tabela")))
        self._get(self.editor, reverse("pca:tabela"), exercicio=2026, vista="lista")
        resposta = self.client.get(reverse("pca:tabela"), **HTTPS)
        self.assertEqual(resposta.status_code, 302)
        self.assertIn("vista=lista", resposta["Location"])

    def test_link_da_ficha_e_voltar_levam_a_vista(self):
        conteudo = self._get(self.editor, reverse("pca:tabela"), exercicio=2026, vista="lista").content.decode()
        self.assertIn("/processo/2026/1?exercicio=2026&amp;vista=lista", conteudo)

    def test_lista_nao_faz_consulta_por_linha(self):
        self.client.force_login(self.editor)
        with CaptureQueriesContext(connection) as dez:
            self.client.get(reverse("pca:tabela"), {"exercicio": 2026, "vista": "lista", "por_pagina": 10}, **HTTPS)
        with CaptureQueriesContext(connection) as vinte:
            self.client.get(reverse("pca:tabela"), {"exercicio": 2026, "vista": "lista", "por_pagina": 20}, **HTTPS)
        self.assertEqual(len(dez), len(vinte))

    def test_modal_salvo_a_partir_da_lista_volta_para_a_lista(self):
        processo = self.processos[0]
        self.client.force_login(self.editor)
        resposta = self.client.post(
            reverse("pca:acompanhamento_modal", args=[2026, processo.item_pca]),
            {"versao": processo.atualizado_em.isoformat(), "observacao": "Registro de teste p5n",
             "origem": "tabela", "querystring_retorno": "exercicio=2026&vista=lista"},
            HTTP_HX_REQUEST="true",
            **HTTPS,
        )
        self.assertEqual(resposta.status_code, 200)
        destino = json.loads(resposta["HX-Location"])
        self.assertIn("vista=lista", destino["path"])
        self.assertEqual(destino["target"], "#listagem")


class TestFichaPadraoPncp(PadraoPncpBase):
    def _ficha(self, usuario):
        return self._get(usuario, reverse("pca:detalhe_processo", args=[2026, 1])).content.decode()

    def test_cartoes_de_valor_nas_cores_do_pncp(self):
        conteudo = self._ficha(self.leitor)
        self.assertIn("dsgov-cartao-valor dsgov-cartao-valor-estimado", conteudo)
        self.assertIn("dsgov-cartao-valor dsgov-cartao-valor-contratado", conteudo)
        self.assertIn("Valor total estimado do item", conteudo)
        self.assertIn("Valor total contratado do item", conteudo)

    def test_editor_ve_as_tres_acoes_no_topo_e_as_duas_abas(self):
        conteudo = self._ficha(self.editor)
        topo = conteudo[: conteudo.index('id="modal-acompanhamento"')]
        self.assertIn("Alterar situação", topo)
        self.assertIn("Registrar acompanhamento", topo)
        self.assertIn("Editar", topo)
        self.assertIn('data-panel="acompanhamentos"', conteudo)
        self.assertIn('data-panel="execucao"', conteudo)
        self.assertIn('id="acompanhamentos"', conteudo)
        self.assertIn("Compromisso vigente:", conteudo)
        self.assertIn("Prazo inicial 30/11/2026", conteudo)

    def test_leitor_so_ve_a_aba_de_execucao_ja_aberta(self):
        conteudo = self._ficha(self.leitor)
        self.assertNotIn('data-panel="acompanhamentos"', conteudo)
        self.assertIn('class="tab-item active" title="Execução contratual e publicação"', conteudo)
        self.assertNotIn("Compromisso vigente", conteudo)
        self.assertNotIn("Alterar situação", conteudo)
