"""Orçamento de tempo e de consultas com 500 processos e relações 1:N
representativas (`ProcessoSEI`).

Behavior sob teste: nenhuma das 6 respostas críticas (`/inicio` via
`core:inicio`, `/tabela`, `/calendario`, `/resumo-uo`, `/analise`,
`/busca?q=1400`) cresce em número de consultas quando o volume de dados
sobe de 50 para 500 processos — o orçamento de cada view é fixo
(paginado/agregado no ORM), não uma consulta por linha.
`assertNumQueries` compara os dois volumes com a mesma contagem esperada;
o tempo é medido à parte com `time.perf_counter()` (nunca mock), critério
informativo de 2s, não bloqueante em CI sem SLA de hardware.

`django.test.TestCase` (não `TransactionTestCase`): a fixture desta
classe é 100% ORM direto (`bulk_create`), sem
`call_command("importar_pca", ...)` — dispensa `serialized_rollback`; os
8 vocabulários e o `bulk_create` inteiro entram na mesma transação por
teste, revertida ao final (rápido, sem I/O de planilha)."""

import time
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.urls import reverse
from django.utils.timezone import localdate

from apps.catalogo.models import (
    Categoria,
    Classificacao,
    Exercicio,
    GrauPrioridade,
    InstrumentoContratual,
    Modalidade,
    SituacaoNormalizada,
    Tipo,
    Unidade,
)
from apps.pca.busca import aplicar_busca
from apps.pca.filtros import queryset_filtrado
from apps.pca.models import (
    Acompanhamento,
    Estado,
    Processo,
    ProcessoSEI,
    Reuniao,
    Situacao,
    SituacaoReuniao,
    TipoEvento,
)
from apps.pca.relatorio_movimentacao import _bloco_adiados, frase_compromisso

LIMITE_SEGUNDOS = 2.0


def _popular_catalogo():
    """3-4 UOs, todos os `Tipo`/`Situacao`/`Estado` — vocabulário mínimo
    para uma fixture representativa, reaproveitado nos dois volumes
    (50/500) para a comparação de consultas ser justa (mesmo número de
    FKs distintas nos dois casos)."""
    unidades = [
        Unidade.objects.create(nome=f"Unidade Desempenho {i}") for i in range(1, 5)
    ]
    tipos = {
        "nova contratacao": Tipo.objects.create(nome="Nova Contratação Desempenho"),
        "renovacao": Tipo.objects.create(nome="Renovação Desempenho"),
        "vigente": Tipo.objects.create(nome="Vigente Desempenho"),
        "outro": Tipo.objects.create(nome="Outro Tipo Desempenho"),
    }
    categoria = Categoria.objects.create(nome="Categoria Desempenho")
    prioridade = GrauPrioridade.objects.create(nome="Prioridade Desempenho")
    classificacao = Classificacao.objects.create(nome="Classificação Desempenho")
    modalidade = Modalidade.objects.create(nome="Modalidade Desempenho")
    exercicio = Exercicio.objects.get(ano=2026)
    return unidades, list(tipos.values()), categoria, prioridade, classificacao, modalidade, exercicio


def _criar_processos(quantidade, unidades, tipos, categoria, prioridade, classificacao, modalidade, exercicio):
    """`bulk_create` (velocidade, sem passar por `save()`/histórico) com
    relações 1:N via `ProcessoSEI` em pelo menos 100 processos (2+
    números cada) e `valor_contratado=None` em ao menos 50, para o
    formato da fixture não mudar entre os dois volumes comparados."""
    situacoes = list(Situacao.values)
    hoje = localdate()
    processos = []
    for i in range(1, quantidade + 1):
        estado = Estado.CANCELADO.value if i % 11 == 0 else Estado.ATIVO.value
        situacao = situacoes[i % len(situacoes)]
        # ~20% sem valor contratado (piso: pelo menos 50 em 500 -> 10%
        # arredondado para cima já cobre a exigência; 25% garante a folga).
        sem_valor_contratado = (i % 4 == 0)
        processos.append(
            Processo(
                item_pca=i,
                exercicio=exercicio,
                descricao_objeto=f"Processo de desempenho nº {i} — item 1400" if i == 1 else f"Processo de desempenho nº {i}",
                tipo=tipos[i % len(tipos)],
                categoria=categoria,
                unidade_organizacional=unidades[i % len(unidades)],
                grau_prioridade=prioridade if i % 3 == 0 else None,
                classificacao=classificacao if i % 5 == 0 else None,
                modalidade=modalidade if i % 6 == 0 else None,
                estado=estado,
                situacao=situacao,
                valor_estimado=1000 + i,
                valor_contratado=None if sem_valor_contratado else 900 + i,
                mes_previsto=(i % 12) + 1,
                prazo_entrega=hoje + timedelta(days=(i % 90) - 30),
            )
        )
    Processo.objects.bulk_create(processos)

    # >= 100 processos (ou todos, se a fixture for menor) com 2+ SEIs —
    # relação 1:N representativa que `aplicar_busca`/agregações não podem
    # transformar em consulta por linha (Exists, nunca join duplicando).
    criados = list(
        Processo.objects.filter(exercicio=exercicio, item_pca__lte=quantidade).order_by("item_pca")
    )
    limite_com_sei = min(100, quantidade)
    seis = []
    for processo in criados[:limite_com_sei]:
        seis.append(ProcessoSEI(processo=processo, numero_sei=f"{processo.item_pca}.000001/2026-01"))
        seis.append(ProcessoSEI(processo=processo, numero_sei=f"{processo.item_pca}.000002/2026-11"))
    ProcessoSEI.objects.bulk_create(seis)
    return criados


class OrcamentoBase(TestCase):
    """Mede as 6 respostas críticas nos DOIS volumes (50 e 500) dentro do
    MESMO teste (mesma sessão autenticada, mesmo catálogo compartilhado) —
    evita duas classes/duas cargas de fixture inteiras."""

    @classmethod
    def setUpTestData(cls):
        (
            cls.unidades,
            cls.tipos,
            cls.categoria,
            cls.prioridade,
            cls.classificacao,
            cls.modalidade,
            cls.exercicio,
        ) = _popular_catalogo()
        cls.usuario = get_user_model().objects.create_user(
            email="desempenho28@pca.local", password="senha-forte-123"
        )

    def setUp(self):
        self.client.force_login(self.usuario)

    def _rotas(self):
        return {
            "inicio": reverse("core:inicio"),
            "tabela": reverse("pca:tabela"),
            "calendario": reverse("pca:calendario"),
            "resumo_uo": reverse("pca:resumo_uo"),
            "analise": reverse("pca:analise"),
            "busca": reverse("pca:busca") + "?q=1400",
        }

    def _contar_consultas(self):
        """Retorna {nome_rota: numero_de_consultas} para o volume ATUAL de
        `Processo` no banco (chamado uma vez com 50, outra com 500)."""
        contagens = {}
        for nome, url in self._rotas().items():
            with CaptureQueriesContext(connection) as captura:
                resposta = self.client.get(url)
            self.assertEqual(
                resposta.status_code, 200, f"{nome}: esperava 200, veio {resposta.status_code}"
            )
            contagens[nome] = len(captura.captured_queries)
        return contagens

    def _medir_tempo(self):
        tempos = {}
        for nome, url in self._rotas().items():
            inicio = time.perf_counter()
            resposta = self.client.get(url)
            duracao = time.perf_counter() - inicio
            self.assertEqual(resposta.status_code, 200)
            tempos[nome] = duracao
        return tempos


class TestOrcamentoDeConsultasNaoCresceComVolume(OrcamentoBase):
    """O número de consultas de cada rota crítica com 500 processos não
    é maior do que com 50 (nenhuma delas percorre linha a linha); tempo
    de resposta com 500 processos abaixo de 2s (informativo, ambiente
    controlado, sem mock)."""

    def test_consultas_500_nao_excedem_consultas_50(self):
        _criar_processos(
            50, self.unidades, self.tipos, self.categoria, self.prioridade,
            self.classificacao, self.modalidade, self.exercicio,
        )
        contagens_50 = self._contar_consultas()

        Processo.objects.filter(exercicio=self.exercicio).delete()
        _criar_processos(
            500, self.unidades, self.tipos, self.categoria, self.prioridade,
            self.classificacao, self.modalidade, self.exercicio,
        )
        contagens_500 = self._contar_consultas()

        for nome in contagens_50:
            with self.subTest(rota=nome):
                self.assertLessEqual(
                    contagens_500[nome],
                    contagens_50[nome],
                    f"{nome}: {contagens_500[nome]} consultas com 500 processos "
                    f"> {contagens_50[nome]} consultas com 50 — indício de "
                    "consulta por linha (agregação/busca deveria ser O(1) em N).",
                )

    def test_500_processos_respondem_abaixo_de_2_segundos(self):
        _criar_processos(
            500, self.unidades, self.tipos, self.categoria, self.prioridade,
            self.classificacao, self.modalidade, self.exercicio,
        )
        tempos = self._medir_tempo()
        for nome, duracao in tempos.items():
            with self.subTest(rota=nome):
                self.assertLess(
                    duracao,
                    LIMITE_SEGUNDOS,
                    f"{nome}: {duracao:.3f}s >= {LIMITE_SEGUNDOS}s com 500 processos",
                )


class TestBaselineConsultasDetalheProcesso(OrcamentoBase):
    """Baseline do GET de `pca:detalhe_processo`: fixa a contagem de
    consultas para o mesmo processo variando zero/vários números SEI e
    zero/vários acompanhamentos, separando o custo (já existente) da
    apuração de histórico de qualquer consulta nova."""

    def _contar(self, processo):
        url = reverse("pca:detalhe_processo", args=[processo.exercicio.ano, processo.item_pca])
        with CaptureQueriesContext(connection) as captura:
            resposta = self.client.get(url)
        self.assertEqual(resposta.status_code, 200)
        return len(captura.captured_queries)

    def test_baseline_zero_e_varios_sei_e_acompanhamentos(self):
        from apps.catalogo.models import SituacaoNormalizada
        from apps.pca import services
        from apps.pca.models import Situacao

        SituacaoNormalizada.objects.get_or_create(nome="Sem informação")
        [unidade] = self.unidades[:1]
        processo = Processo.objects.create(
            item_pca=9001,
            exercicio=self.exercicio,
            descricao_objeto="Processo baseline do detalhe",
            tipo=self.tipos[0],
            categoria=self.categoria,
            unidade_organizacional=unidade,
            situacao=Situacao.NO_PRAZO,
        )

        zero_zero = self._contar(processo)

        for indice in range(2):
            ProcessoSEI.objects.create(
                processo=processo, numero_sei=f"90001.{indice:06d}/2026-01"
            )
        varios_sei_zero_acompanhamento = self._contar(processo)

        for indice in range(3):
            processo.refresh_from_db()
            services.registrar_acompanhamento(
                processo_id=processo.pk,
                usuario=self.usuario,
                versao_cliente=processo.atualizado_em.isoformat(),
                prazo_prometido=localdate() + timedelta(days=10 + indice),
                observacao=f"Baseline {indice}",
                usar_reuniao_corrente=False,
            )
        varios_sei_varios_acompanhamento = self._contar(processo)

        # A invariante travada: incluir SEI sozinho (sem histórico) não
        # muda a contagem em relação a zero.
        self.assertEqual(zero_zero, varios_sei_zero_acompanhamento)
        self.assertGreaterEqual(varios_sei_varios_acompanhamento, varios_sei_zero_acompanhamento)


class TestOrcamentoFichaBaixoEAltoVolume(OrcamentoBase):
    """A ficha PNCP (SEI em leitura, `prazo_inicial`, `prazo_atual_ficha`)
    não pode acrescentar consulta por linha ao GET de
    `pca:detalhe_processo`: SEI cresce sem custo adicional (mesmo
    `prefetch_related`); o crescimento pré-existente de
    `apurar_situacao_compromisso`/`frase_compromisso` por acompanhamento
    (limitação conhecida, não refatorada aqui) é só registrado, comparado
    a um teto frouxo que capturaria uma explosão quadrática, não o
    crescimento linear já conhecido."""

    def _contar(self, processo):
        url = reverse("pca:detalhe_processo", args=[processo.exercicio.ano, processo.item_pca])
        with CaptureQueriesContext(connection) as captura:
            resposta = self.client.get(url)
        self.assertEqual(resposta.status_code, 200)
        return len(captura.captured_queries)

    def test_numeros_sei_baixo_e_alto_volume_mesma_contagem(self):
        from apps.catalogo.models import SituacaoNormalizada

        SituacaoNormalizada.objects.get_or_create(nome="Sem informação")
        [unidade] = self.unidades[:1]
        processo = Processo.objects.create(
            item_pca=9002,
            exercicio=self.exercicio,
            descricao_objeto="Processo orçamento SEI",
            tipo=self.tipos[0],
            categoria=self.categoria,
            unidade_organizacional=unidade,
            situacao=Situacao.NO_PRAZO,
        )
        for indice in range(2):
            ProcessoSEI.objects.create(
                processo=processo, numero_sei=f"90002.{indice:06d}/2026-01"
            )
        baixo = self._contar(processo)

        for indice in range(2, 20):
            ProcessoSEI.objects.create(
                processo=processo, numero_sei=f"90002.{indice:06d}/2026-01"
            )
        alto = self._contar(processo)

        self.assertEqual(
            baixo, alto,
            "contagem de queries do detalhe cresceu com o número de SEIs — "
            "prefetch_related(\"numeros_sei\") deixou de estar em vigor",
        )

    def test_historico_baixo_e_alto_volume_registrado_sem_explosao(self):
        # Custo histórico pré-existente (apurar_situacao_compromisso):
        # cresce com o número de acompanhamentos, mas de forma LINEAR
        # (uma consulta a mais por acompanhamento, não uma consulta por
        # acompanhamento POR acompanhamento) — teto frouxo (2 consultas
        # extras por item de histórico) só para capturar uma regressão
        # quadrática, não para travar a contagem exata.
        from apps.catalogo.models import SituacaoNormalizada
        from apps.pca import services

        SituacaoNormalizada.objects.get_or_create(nome="Sem informação")
        [unidade] = self.unidades[:1]
        processo = Processo.objects.create(
            item_pca=9003,
            exercicio=self.exercicio,
            descricao_objeto="Processo orçamento histórico",
            tipo=self.tipos[0],
            categoria=self.categoria,
            unidade_organizacional=unidade,
            situacao=Situacao.NO_PRAZO,
        )
        for indice in range(2):
            processo.refresh_from_db()
            services.registrar_acompanhamento(
                processo_id=processo.pk,
                usuario=self.usuario,
                versao_cliente=processo.atualizado_em.isoformat(),
                prazo_prometido=localdate() + timedelta(days=10 + indice),
                observacao=f"Baixo volume {indice}",
                usar_reuniao_corrente=False,
            )
        baixo = self._contar(processo)

        for indice in range(2, 20):
            processo.refresh_from_db()
            services.registrar_acompanhamento(
                processo_id=processo.pk,
                usuario=self.usuario,
                versao_cliente=processo.atualizado_em.isoformat(),
                prazo_prometido=localdate() + timedelta(days=10 + indice),
                observacao=f"Alto volume {indice}",
                usar_reuniao_corrente=False,
            )
        alto = self._contar(processo)

        delta_historico = 20 - 2
        self.assertLessEqual(
            alto,
            baixo + 2 * delta_historico,
            "crescimento de queries com o histórico passou do teto frouxo "
            "(explosão quadrática) — investigar apurar_situacao_compromisso",
        )


class TestBuscaSemConsultaPorLinha(OrcamentoBase):
    """`apps.pca.busca.aplicar_busca` sobre 500 processos não gera uma
    consulta por processo — a MESMA contagem de consultas para avaliar o
    queryset resultante em 50 e em 500 (a interpretação do termo é toda em
    Python/SQL de um único `Q()`/`Exists()`, nunca em loop)."""

    def test_aplicar_busca_nao_cresce_com_volume(self):
        _criar_processos(
            50, self.unidades, self.tipos, self.categoria, self.prioridade,
            self.classificacao, self.modalidade, self.exercicio,
        )
        with CaptureQueriesContext(connection) as captura_50:
            qs, _avisos = aplicar_busca(
                Processo.objects.para_listagem().filter(exercicio=self.exercicio), "1400"
            )
            list(qs)
        n_50 = len(captura_50.captured_queries)

        Processo.objects.filter(exercicio=self.exercicio).delete()
        _criar_processos(
            500, self.unidades, self.tipos, self.categoria, self.prioridade,
            self.classificacao, self.modalidade, self.exercicio,
        )
        with CaptureQueriesContext(connection) as captura_500:
            qs, _avisos = aplicar_busca(
                Processo.objects.para_listagem().filter(exercicio=self.exercicio), "1400"
            )
            list(qs)
        n_500 = len(captura_500.captured_queries)

        self.assertLessEqual(
            n_500, n_50,
            f"aplicar_busca: {n_500} consultas com 500 processos > {n_50} com 50 "
            "— indício de consulta por processo.",
        )


class TestBlocoAdiadosPrazoInicialSemConsultaPorLinha(TestCase):
    """`_bloco_adiados` anota `prazo_inicial_processo` em lote (`Subquery`
    correlacionada à mesma identidade de `para_listagem()::prazo_inicial`).

    `apurar_situacao_compromisso` (chamada por `frase_compromisso` para
    cada `Acompanhamento`) já consulta `Processo.history`/promessas
    posteriores por linha — um custo histórico pré-existente, fora do
    escopo desta refatoração. Por isso o teste não compara volumes
    diferentes de N (essa comparação capturaria o custo pré-existente,
    não o desta mudança) — ele compara o mesmo fixture antes/depois da
    anotação em lote, isolando
    exatamente a consulta que `_resolver_prazo_inicial` deixa de fazer por
    linha quando a anotação está presente."""

    @classmethod
    def setUpTestData(cls):
        cls.unidade = Unidade.objects.create(nome="Unidade Adiados Desempenho")
        cls.categoria = Categoria.objects.create(nome="Categoria Adiados Desempenho")
        cls.tipo = Tipo.objects.create(nome="Tipo Adiados Desempenho")
        cls.exercicio = Exercicio.objects.get(ano=2026)
        cls.situacao_normalizada = SituacaoNormalizada.objects.create(
            nome="Situação Adiados Desempenho"
        )
        cls.reuniao = Reuniao.objects.create(
            data=date(2026, 1, 15), situacao=SituacaoReuniao.FECHADA,
            exercicio=cls.exercicio,
        )

    def _popular(self, quantidade):
        Processo.objects.filter(exercicio=self.exercicio, categoria=self.categoria).delete()
        for i in range(1, quantidade + 1):
            processo = Processo.objects.create(
                item_pca=i,
                exercicio=self.exercicio,
                descricao_objeto=f"Adiado desempenho {i}",
                tipo=self.tipo,
                categoria=self.categoria,
                unidade_organizacional=self.unidade,
                prazo_entrega=None,
            )
            Acompanhamento.objects.create(
                processo=processo,
                referencia_data=date(2026, 1, 15),
                origem_hash=f"hash-adiado-desempenho-{i}",
                tipo_evento=TipoEvento.REUNIAO_ACOMPANHAMENTO.value,
                situacao=self.situacao_normalizada,
                prazo_prometido=date(2026, 3, 1),
                reuniao=self.reuniao,
            )

    def _queryset_sem_anotacao_em_lote(self):
        """A MESMA consulta base de `_bloco_adiados`, sem
        `prazo_inicial_processo` — reproduz o comportamento anterior a
        esta tarefa: `_resolver_prazo_inicial` cai na consulta unitária
        por linha (`processo.prazo_inicial` também ausente, pois
        `select_related("processo")` não passa por `para_listagem()`)."""
        return (
            Acompanhamento.objects.filter(
                processo__exercicio=self.exercicio,
                prazo_prometido__isnull=False,
                reuniao__data__range=(date(2026, 1, 1), date(2026, 1, 31)),
            )
            .select_related(
                "processo",
                "processo__unidade_organizacional",
                "processo__exercicio",
                "reuniao",
            )
            .order_by("processo_id", "-referencia_data", "-id")
        )

    def test_anotacao_em_lote_elimina_exatamente_uma_consulta_por_processo(self):
        quantidade = 10
        self._popular(quantidade)

        with CaptureQueriesContext(connection) as captura_sem_anotacao:
            for acompanhamento in self._queryset_sem_anotacao_em_lote():
                frase_compromisso(acompanhamento)
        n_sem_anotacao = len(captura_sem_anotacao.captured_queries)

        with CaptureQueriesContext(connection) as captura_com_anotacao:
            resultado = _bloco_adiados(self.exercicio, date(2026, 1, 1), date(2026, 1, 31))
        n_com_anotacao = len(captura_com_anotacao.captured_queries)

        self.assertEqual(len(resultado), quantidade)
        self.assertEqual(
            n_sem_anotacao - n_com_anotacao, quantidade,
            f"esperava exatamente {quantidade} consultas a menos com a "
            f"anotação em lote (uma eliminada por processo): sem_anotacao="
            f"{n_sem_anotacao} com_anotacao={n_com_anotacao} — o custo "
            "pré-existente de apurar_situacao_compromisso é o MESMO nos "
            "dois lados e cancela na subtração.",
        )
        # Cada processo mostra sua própria promessa (a única existente) como
        # prazo inicial — a anotação em lote não embaralha entre processos.
        algum_item = next(iter(resultado.values()))
        self.assertIn("prazo inicial 01/03/2026", algum_item["frases"][0])


class TestOrcamentoColunasFkExecucaoContratual(TestCase):
    """Selecionar as colunas FK de Execução contratual (`modalidade`,
    `instrumento_contratual`) no seletor da tabela ativa `select_related`
    condicional (`apps.pca.views.FKS_SELECT_RELATED_CONDICIONAL`); a
    contagem de consultas não pode crescer com o volume de linhas nem com
    a quantidade de FKs selecionadas — mesmo orçamento de `OrcamentoBase`
    acima, mas com fixture própria (`InstrumentoContratual`, ausente do
    catálogo compartilhado daquela classe)."""

    @classmethod
    def setUpTestData(cls):
        cls.unidade = Unidade.objects.create(nome="Unidade FK Desempenho 29-03")
        cls.tipo = Tipo.objects.create(nome="Tipo FK Desempenho 29-03")
        cls.categoria = Categoria.objects.create(nome="Categoria FK Desempenho 29-03")
        cls.modalidade = Modalidade.objects.create(nome="Modalidade FK Desempenho 29-03")
        cls.instrumento = InstrumentoContratual.objects.create(
            nome="Instrumento FK Desempenho 29-03"
        )
        cls.exercicio = Exercicio.objects.get(ano=2026)
        cls.usuario = get_user_model().objects.create_user(
            email="desempenho-fk-29-03@pca.local", password="senha-forte-123"
        )

    def setUp(self):
        self.client.force_login(self.usuario)

    def _criar(self, quantidade):
        Processo.objects.filter(exercicio=self.exercicio, categoria=self.categoria).delete()
        processos = [
            Processo(
                item_pca=i,
                exercicio=self.exercicio,
                descricao_objeto=f"Processo FK Desempenho 29-03 nº {i}",
                tipo=self.tipo,
                categoria=self.categoria,
                unidade_organizacional=self.unidade,
                modalidade=self.modalidade if i % 2 == 0 else None,
                instrumento_contratual=self.instrumento if i % 3 == 0 else None,
                valor_estimado=1000 + i,
            )
            for i in range(1, quantidade + 1)
        ]
        Processo.objects.bulk_create(processos)

    def _consultas_selecionando_colunas(self, colunas):
        with CaptureQueriesContext(connection) as captura:
            resposta = self.client.get(reverse("pca:tabela"), {"colunas": colunas})
        self.assertEqual(resposta.status_code, 200)
        return len(captura.captured_queries)

    def test_selecionar_modalidade_e_instrumento_nao_cresce_de_50_para_500(self):
        colunas = ["item_pca", "descricao_objeto", "modalidade", "instrumento_contratual"]

        self._criar(50)
        consultas_50 = self._consultas_selecionando_colunas(colunas)

        self._criar(500)
        consultas_500 = self._consultas_selecionando_colunas(colunas)

        self.assertLessEqual(
            consultas_500, consultas_50,
            f"{consultas_500} consultas com 500 processos > {consultas_50} com "
            "50 ao selecionar modalidade/instrumento_contratual — indício de "
            "N+1 (select_related deveria manter a contagem fixa).",
        )

    def test_selecionar_as_duas_fks_nao_soma_consulta_a_mais_que_nenhuma(self):
        # `select_related` é um JOIN na MESMA consulta — a contagem deve
        # ser IDÊNTICA com ou sem as FKs marcadas, nunca uma consulta a
        # mais por FK selecionada (o que indicaria `prefetch_related`
        # disfarçado ou acesso por linha).
        self._criar(50)
        sem_fks = self._consultas_selecionando_colunas(["item_pca", "descricao_objeto"])
        com_fks = self._consultas_selecionando_colunas(
            ["item_pca", "descricao_objeto", "modalidade", "instrumento_contratual"]
        )
        self.assertEqual(com_fks, sem_fks)
