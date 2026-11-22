"""`atualizacoes_recentes`: "quais processos tiveram
atualização?" respondido pela trilha `simple_history` (diff líquido por
campo, origem equipe/robô SEI/importação), acompanhamentos só com
`pca.view_acompanhamento`, consultas constantes e envelope dentro do teto
de bytes do agente."""

import json

from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.assistente import agente, ferramentas
from apps.assistente.tests.base import AssistenteTestBase
from apps.catalogo.models import Exercicio
from apps.pca.models import Processo


def _argumentos(**extras):
    base = {"exercicio": None, "dias": 7, "data": None, "unidade": None, "origem": None}
    base.update(extras)
    return json.dumps(base)


class TestAtualizacoesRecentes(AssistenteTestBase):
    def setUp(self):
        super().setUp()
        self.exercicio = Exercicio.objects.get(ano=2026)
        self.processo = Processo.objects.filter(exercicio=self.exercicio).order_by("item_pca").first()
        self.valor_antigo = self.processo.descricao_objeto
        self.processo.descricao_objeto = "Objeto reescrito na reunião"
        self.processo._history_user = self.editor
        self.processo.save()

    def _executar(self, usuario, **extras):
        return ferramentas.executar(
            "atualizacoes_recentes", _argumentos(**extras),
            usuario=usuario, exercicio_padrao=self.exercicio,
        )

    def test_registrada_no_esquema_e_na_allowlist(self):
        self.assertIn("atualizacoes_recentes", ferramentas.ESQUEMAS)
        self.assertIn("atualizacoes_recentes", ferramentas.FUNCOES)
        self.assertIn("atualizacoes_recentes", agente.PROMPT_SISTEMA)

    def test_edicao_da_equipe_aparece_com_antes_e_depois(self):
        envelope = self._executar(self.editor, origem="equipe")
        dados = envelope.dados
        self.assertEqual(dados["total_itens_atualizados"], 1)
        item = dados["itens"][0]
        self.assertEqual(item["item_pca"], self.processo.item_pca)
        self.assertEqual(item["origens"], ["equipe"])
        campo = next(c for c in item["campos_alterados"] if c["campo"] != "item criado")
        self.assertEqual(campo["depois"], "Objeto reescrito na reunião")
        self.assertEqual(campo["antes"], self.valor_antigo[:77] + "…" if len(self.valor_antigo) > 80 else self.valor_antigo)
        self.assertEqual(envelope.referencias[0]["url"].rstrip("/").split("/")[-1], str(self.processo.item_pca))

    def test_origem_robo_sei_separada_da_equipe(self):
        robo = get_user_model().objects.create_user(email="robo-sei@pca.local", password=None)
        outro = Processo.objects.filter(exercicio=self.exercicio).order_by("-item_pca").first()
        outro.unidade_sei_atual = "GELIC"
        outro._history_user = robo
        outro.save()
        dados = self._executar(self.editor, origem="sincronização com o SEI").dados
        self.assertEqual([i["item_pca"] for i in dados["itens"]], [outro.item_pca])
        self.assertEqual(dados["itens_por_origem"], {"sincronização com o SEI": 1})

    def test_importacao_conta_como_criacao(self):
        dados = self._executar(self.editor, origem="importação da planilha").dados
        self.assertEqual(
            dados["total_itens_atualizados"],
            Processo.objects.filter(exercicio=self.exercicio).count(),
        )
        self.assertEqual(dados["itens_por_campo"].get("item criado"), dados["total_itens_atualizados"])

    def test_visualizador_sem_acompanhamentos(self):
        envelope = self._executar(self.visualizador, origem="acompanhamento")
        self.assertTrue(envelope.sem_permissao)
        self.assertIn("aviso_permissao", envelope.dados)
        self.assertEqual(envelope.dados["itens"], [])

    def test_envelope_cabe_no_teto_e_consultas_constantes(self):
        self.editor.has_perm("pca.view_acompanhamento")
        with CaptureQueriesContext(connection) as capturado:
            envelope = self._executar(self.editor, dias=90)
        self.assertLessEqual(len(capturado.captured_queries), 7, capturado.captured_queries)
        self.assertLess(len(envelope.para_json().encode("utf-8")), agente.TETO_RESULTADO_FERRAMENTA_BYTES)
        self.assertTrue(envelope.truncado)
        self.assertEqual(envelope.dados["exibidos"], len(envelope.dados["itens"]))

    def test_origem_invalida_e_unidade_inexistente(self):
        self.assertEqual(
            ferramentas.atualizacoes_recentes(self.editor, exercicio=2026, origem="xpto").dados["erro"],
            "origem inválida",
        )
        self.assertEqual(
            self._executar(self.editor, unidade="unidade que não existe").dados["erro"],
            "unidade não encontrada",
        )

    def test_hoje_e_dia_de_calendario_e_data_recorta_um_dia(self):
        from datetime import datetime, time, timedelta

        from django.utils import timezone

        Historico = Processo.history.model
        linha = Historico.objects.filter(id=self.processo.pk).latest("history_date")
        ontem = timezone.localdate() - timedelta(days=1)
        linha.history_date = datetime.combine(ontem, time(23, 30), tzinfo=timezone.get_current_timezone())
        linha.save()

        hoje = self._executar(self.editor, dias=1, origem="equipe").dados
        self.assertEqual(hoje["total_itens_atualizados"], 0)
        self.assertEqual(hoje["periodo"], f"{timezone.localdate():%d/%m/%Y}")
        do_dia = self._executar(self.editor, data=ontem.isoformat(), origem="equipe").dados
        self.assertEqual([i["item_pca"] for i in do_dia["itens"]], [self.processo.item_pca])
        self.assertIn("23:30", do_dia["itens"][0]["ultima_atualizacao"])
        self.assertEqual(
            self._executar(self.editor, data="25/09/2026").dados["erro"],
            "data inválida (use AAAA-MM-DD)",
        )

    def test_nenhum_texto_do_assistente_fala_em_robo(self):
        import re

        esquema = json.dumps(ferramentas.ESQUEMAS["atualizacoes_recentes"], ensure_ascii=False)
        envelope = self._executar(self.editor, dias=90).para_json()
        for texto in (esquema, envelope):
            self.assertIsNone(re.search(r"rob[ôo]", texto, re.IGNORECASE))
        self.assertIn("Nunca use as palavras 'robô'", agente.PROMPT_SISTEMA)
