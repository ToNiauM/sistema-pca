"""Testes de paridade do serviço extraído (Fase 39) — `apps.pca.servicos.consultas_fluxo` precisa devolver EXATAMENTE
os mesmos números que a tela `pca:analise_fluxo`, o CSV e a memória de
cálculo, sem nunca ler `request.session`/cenário salvo. Reaproveita
`AnaliseTelasBase` (fixture real `Modelo_de_Controle_.xlsx`, exercício
2026), mesmo padrão de `test_exportacao_fluxo.py`."""

from decimal import Decimal
from io import StringIO

from django.contrib.sessions.middleware import SessionMiddleware
from django.db import connection
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils.timezone import localdate

from apps.catalogo.models import Exercicio
from apps.pca import views_analise
from apps.pca.models import Processo
from apps.pca.projecao import CAMADAS, simulacao
from apps.pca.servicos import consultas_fluxo
from apps.pca.tests.test_analise_telas import AnaliseTelasBase

CAMINHO_MODULO = "apps/pca/servicos/consultas_fluxo.py"


def _ctx_fluxo(usuario, params):
    """Mesmo helper de `test_exportacao_fluxo.py::_ctx_fluxo` — monta o
    `_contexto_fluxo` real via `RequestFactory`, sem HTTP de verdade."""
    factory = RequestFactory()
    request = factory.get(reverse("pca:analise_fluxo"), params)
    request.user = usuario
    SessionMiddleware(lambda r: None).process_request(request)
    request.session.save()
    return views_analise._contexto_fluxo(request)


class TestParidadeProjecaoOficial(AnaliseTelasBase):
    def test_por_ano_bate_com_a_tela_cenario_base(self):
        exercicio = Exercicio.objects.get(ano=2026)
        ctx = _ctx_fluxo(self.editor, {"exercicio": "2026", "cenario": "base"})
        projecao_servico, _itens = consultas_fluxo.projecao_oficial(exercicio)
        self.assertEqual(projecao_servico.por_ano, ctx["projecao"].por_ano)
        self.assertEqual(projecao_servico.totais, ctx["projecao"].totais)

    def test_por_ano_bate_com_a_tela_mesmo_com_rascunho_de_simulacao_ativo(self):
        """(d) — mesmo com `sim=rascunho` ativo e um rascunho de verdade
        gravado na sessão, `projecao_oficial` continua devolvendo os
        valores OFICIAIS: a função não recebe `request` nem sessão, então
        não há como o rascunho alcançá-la."""
        exercicio = Exercicio.objects.get(ano=2026)
        ajustes = simulacao.Ajustes(lead_time_dias=999)

        factory = RequestFactory()
        request = factory.get(
            reverse("pca:analise_fluxo"),
            {"exercicio": "2026", "cenario": "base", "sim": "rascunho"},
        )
        request.user = self.editor
        SessionMiddleware(lambda r: None).process_request(request)
        request.session[views_analise.CHAVE_SESSAO_FLUXO_AJUSTES] = simulacao.para_json(ajustes)
        request.session.save()
        ctx = views_analise._contexto_fluxo(request)

        # A sessão realmente tem um rascunho ativo (senão o teste provaria
        # nada) e a projeção SIMULADA da tela realmente difere da oficial.
        self.assertTrue(ctx["simulacao_ativa_sessao"])
        self.assertIsNotNone(ctx["projecao_sim"])

        projecao_servico, _itens = consultas_fluxo.projecao_oficial(exercicio)
        self.assertEqual(projecao_servico.por_ano, ctx["projecao"].por_ano)

    def test_numero_de_consultas_constante_com_149_itens_reais(self):
        """(f) — fixture real tem 149 itens para 2026 (dentro de
        50..500); `projecao_oficial` não pode crescer em número de
        consultas conforme o volume de itens: 1 de processos + 1 de
        prefetch de eventos + 1 de índices ≤ 4."""
        exercicio = Exercicio.objects.get(ano=2026)
        total_itens = Processo.objects.filter(exercicio=exercicio).count()
        self.assertGreaterEqual(total_itens, 50)
        self.assertLessEqual(total_itens, 500)
        with CaptureQueriesContext(connection) as capturado:
            consultas_fluxo.projecao_oficial(exercicio)
        self.assertLessEqual(
            len(capturado.captured_queries),
            4,
            capturado.captured_queries,
        )


class TestParidadeCsv(AnaliseTelasBase):
    def test_soma_do_csv_por_ano_bate_com_por_ano_do_servico(self):
        exercicio = Exercicio.objects.get(ano=2026)
        self.client.force_login(self.editor)
        resposta = self.client.get(
            reverse("pca:analise_fluxo_csv"),
            {"exercicio": "2026", "cenario": "base"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 200)
        linhas = b"".join(resposta.streaming_content).decode("utf-8-sig").splitlines()
        somas_csv: dict[int, Decimal] = {}
        for linha in linhas[1:]:
            if not linha:
                continue
            _item_pca, competencia, _camada, valor_str, _origem = linha.split(";")
            ano = int(competencia.split("-")[0])
            somas_csv[ano] = somas_csv.get(ano, Decimal("0")) + Decimal(valor_str.replace(",", "."))

        projecao_servico, _itens = consultas_fluxo.projecao_oficial(exercicio)
        somas_servico = {
            ano: sum((mapa.get(camada, Decimal("0")) for camada in CAMADAS), Decimal("0"))
            for ano, mapa in projecao_servico.por_ano.items()
        }
        for ano, soma in somas_csv.items():
            self.assertEqual(soma, somas_servico.get(ano, Decimal("0")), f"ano {ano}")


class TestParidadeMemoria(AnaliseTelasBase):
    def test_memoria_oficial_tem_as_mesmas_linhas_da_pagina(self):
        exercicio = Exercicio.objects.get(ano=2026)
        processo = Processo.objects.get(exercicio=exercicio, item_pca=1)

        self.client.force_login(self.editor)
        resposta = self.client.get(
            reverse("pca:analise_fluxo_memoria", args=[processo.item_pca]),
            {"exercicio": "2026"},
            HTTP_HOST="testserver",
        )
        self.assertEqual(resposta.status_code, 200)
        memoria_pagina = resposta.context["memoria"]
        self.assertIsNotNone(memoria_pagina)

        memoria_servico = consultas_fluxo.memoria_oficial(exercicio, processo.item_pca)
        self.assertIsNotNone(memoria_servico)

        linhas_pagina = sorted(
            (l.competencia, l.camada, l.valor, l.formula) for l in memoria_pagina.linhas
        )
        linhas_servico = sorted(
            (l.competencia, l.camada, l.valor, l.formula) for l in memoria_servico.linhas
        )
        self.assertEqual(linhas_pagina, linhas_servico)

    def test_memoria_oficial_devolve_none_para_item_sem_projecao(self):
        exercicio = Exercicio.objects.get(ano=2026)
        processo = Processo.objects.filter(
            exercicio=exercicio,
            vigencia_fim__isnull=True,
            valor_contratado__isnull=True,
            valor_estimado__isnull=True,
        ).first()
        if processo is None:
            self.skipTest("fixture sem item sem dado suficiente para este cenário")
        memoria = consultas_fluxo.memoria_oficial(exercicio, processo.item_pca)
        self.assertIsNone(memoria)

    def test_memoria_oficial_devolve_none_para_item_inexistente(self):
        exercicio = Exercicio.objects.get(ano=2026)
        self.assertIsNone(consultas_fluxo.memoria_oficial(exercicio, 999999))


class TestServicoNuncaLeSessaoOuArgumentoDoModelo(AnaliseTelasBase):
    """(e) — prova por grep: o módulo do serviço nunca cita os tokens que
    entregariam rascunho/cenário salvo a uma ferramenta somente leitura."""

    TOKENS_PROIBIDOS = ("request", "session", "RequestFactory", "CenarioFluxo", "simulacao")

    def test_modulo_nao_cita_tokens_de_sessao_ou_requisicao(self):
        with open(CAMINHO_MODULO, encoding="utf-8") as arquivo:
            linhas = [l for l in arquivo if not l.strip().startswith("#")]
        texto = "".join(linhas)
        for token in self.TOKENS_PROIBIDOS:
            self.assertNotIn(token, texto, f"token proibido encontrado: {token}")


class TestContratoDoPcaSemDuplicacao(AnaliseTelasBase):
    """Correção de 2026-09-23: a série de eventos que o robô grava com o número do próprio contrato do PCA
    virava um segundo contrato e o valor saía contado duas vezes (78 itens; 2026–2031 com R$ 495,8 mi em
    vez de R$ 216,6 mi). O fluxo projeta só o contrato do PCA."""

    def _processo_com_contrato(self):
        from datetime import date

        from apps.pca.models import EventoFinanceiro

        processo = Processo.objects.filter(exercicio__ano=2026).first()
        processo.valor_contratado = Decimal("1200000.00")
        processo.valor_mensal = None
        processo.vigencia_inicio = date(2026, 1, 1)
        processo.vigencia_fim = date(2026, 12, 31)
        processo.numero_instrumento_contratual = "84/2024"
        processo.estado = "ativo"
        processo._history_user = self.editor
        processo._change_reason = "teste de duplicação no fluxo"
        processo.save()
        for instrumento, valor in (("84/2024", "1200000.00"), ("0584421", "1200000.00"), ("69/2025", "500000.00")):
            EventoFinanceiro.objects.create(
                processo=processo, data=date(2026, 1, 1), tipo="contrato", valor=Decimal(valor),
                periodicidade="global", instrumento=instrumento,
            )
        return Processo.objects.para_listagem().get(pk=processo.pk)

    def test_um_contrato_por_item_o_do_pca(self):
        contratos = consultas_fluxo.contratos_do_processo(self._processo_com_contrato())
        self.assertEqual(len(contratos), 1)
        self.assertEqual(contratos[0]["valor"], Decimal("1200000.00"))
        self.assertEqual(contratos[0]["numero_sei"], "84/2024")

    def test_projecao_do_contrato_nao_dobra(self):
        from apps.pca.projecao import fluxo as fluxo_mod

        processo = self._processo_com_contrato()
        itens = consultas_fluxo.itens_para_projecao(Processo.objects.para_listagem().filter(pk=processo.pk))
        exercicio = Exercicio.objects.get(ano=2026)
        parametros = consultas_fluxo.parametros_oficiais(exercicio, "contratado", "IPCA", localdate().replace(year=2026, month=1, day=1))
        projecao = fluxo_mod.projetar(itens, parametros)
        total = sum((p.valor for p in projecao.parcelas if p.camada == "contratado"), Decimal("0"))
        self.assertEqual(total, Decimal("1200000.00"))
