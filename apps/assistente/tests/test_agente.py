"""Laço do agente com orçamento fechado (A03,
A04): cliente falso + relógio falso, sem chamada real ao provedor."""

import json
from unittest import mock

from apps.assistente import agente, cliente as cliente_mod, ferramentas
from apps.assistente.tests.base import (
    AssistenteTestBase,
    ClienteFalso,
    resposta_ferramenta,
    resposta_texto,
)


class _RelogioFalso:
    """Avança `passo` segundos a cada chamada, começando em 0."""

    def __init__(self, passo=1.0):
        self.agora = 0.0
        self.passo = passo

    def __call__(self):
        valor = self.agora
        self.agora += self.passo
        return valor


class TestTrilhaFeliz(AssistenteTestBase):
    def test_uma_ferramenta_mais_texto(self):
        from django.utils import timezone

        fake = ClienteFalso(
            [
                resposta_ferramenta(
                    "consultar_processos", {"exercicio": 2026, "limite": 20}
                ),
                resposta_texto("Há 3 itens atrasados."),
            ]
        )
        exercicio = self._exercicio_2026()
        resposta = agente.responder(
            usuario=self.editor,
            exercicio=exercicio,
            pergunta="quantos itens estão atrasados?",
            trocas=[],
            cliente=fake,
            agora=timezone.now(),
        )
        self.assertEqual(resposta.chamadas_chat, 2)
        self.assertEqual(resposta.ferramentas_usadas, 1)
        self.assertEqual(resposta.texto_md, "Há 3 itens atrasados.")
        self.assertTrue(len(resposta.referencias) >= 1)
        self.assertTrue(resposta.rodape.startswith("PCA consultado em"))

    def _exercicio_2026(self):
        from apps.catalogo.models import Exercicio

        return Exercicio.objects.get(ano=2026)


class TestOrcamentoDeFerramentas(AssistenteTestBase):
    def test_rodadas_separadas_dentro_do_novo_orcamento_executam_todas(self):
        """Com `MAX_FERRAMENTAS=12`/`MAX_CHAMADAS_CHAT=8`,
        1 `tool_call` por rodada ao longo de `MAX_CHAMADAS_CHAT - 1` rodadas
        soma no máximo 7 ferramentas — nunca alcança o orçamento de 12.
        Prova de regressão: o orçamento maior não quebra sequências
        multi-rodada legítimas que já cabiam no orçamento antigo."""
        from django.utils import timezone

        n_rodadas = agente.MAX_CHAMADAS_CHAT - 1
        respostas = [
            resposta_ferramenta("consultar_processos", {"exercicio": 2026, "limite": 20}, id=f"call_{i}")
            for i in range(n_rodadas)
        ]
        respostas.append(resposta_texto("ok"))
        fake = ClienteFalso(respostas)
        exercicio = self._exercicio_2026()

        with mock.patch(
            "apps.assistente.agente.ferramentas.executar",
            wraps=ferramentas.executar,
        ) as executar_espiao:
            resposta = agente.responder(
                usuario=self.editor,
                exercicio=exercicio,
                pergunta="pergunta",
                trocas=[],
                cliente=fake,
                agora=timezone.now(),
            )

        self.assertEqual(executar_espiao.call_count, n_rodadas)
        self.assertEqual(resposta.ferramentas_usadas, n_rodadas)
        self.assertEqual(resposta.texto_md, "ok")
        for chamada in fake.chamadas[:-1]:
            self.assertNotEqual(chamada["tool_choice"], "none")

    def _exercicio_2026(self):
        from apps.catalogo.models import Exercicio

        return Exercicio.objects.get(ano=2026)

    def test_ferramenta_inventada_conta_no_orcamento_sem_consultar(self):
        from django.utils import timezone

        fake = ClienteFalso(
            [
                resposta_ferramenta("executar_sql", {"query": "select 1"}),
                resposta_texto("ok"),
            ]
        )
        resposta = agente.responder(
            usuario=self.editor,
            exercicio=self._exercicio_2026(),
            pergunta="pergunta",
            trocas=[],
            cliente=fake,
            agora=timezone.now(),
        )
        self.assertEqual(resposta.ferramentas_usadas, 1)
        self.assertEqual(resposta.texto_md, "ok")

    def test_json_invalido_no_argumento_continua_o_laco(self):
        from django.utils import timezone

        fake = ClienteFalso(
            [
                cliente_mod.RespostaChat(
                    conteudo=None,
                    chamadas=[
                        cliente_mod.ChamadaFerramenta(
                            id="call_1", nome="consultar_processos", argumentos_json="{invalido"
                        )
                    ],
                ),
                resposta_texto("mesmo assim respondo"),
            ]
        )
        resposta = agente.responder(
            usuario=self.editor,
            exercicio=self._exercicio_2026(),
            pergunta="pergunta",
            trocas=[],
            cliente=fake,
            agora=timezone.now(),
        )
        self.assertEqual(resposta.texto_md, "mesmo assim respondo")


class TestPrazoEsgotado(AssistenteTestBase):
    def test_relogio_alem_do_prazo_gera_resposta_parcial(self):
        from django.utils import timezone

        fake = ClienteFalso([resposta_texto("nunca chega aqui")])
        resposta = agente.responder(
            usuario=self.editor,
            exercicio=None,
            pergunta="pergunta",
            trocas=[],
            cliente=fake,
            agora=timezone.now(),
            relogio=_RelogioFalso(passo=91.0),
            prazo_s=90,
        )
        self.assertTrue(resposta.parcial)
        self.assertEqual(resposta.erro_codigo, "prazo")
        self.assertEqual(len(fake.chamadas), 0)


class TestHistoricoEOrcamentoDeEntrada(AssistenteTestBase):
    def test_historico_grande_e_reduzido_a_48kib(self):
        from apps.assistente import estado as estado_mod

        trocas = [
            estado_mod.Troca(
                ordem=i,
                pergunta="p" * 100,
                resposta_md="r" * 8000,
                referencias=[],
                proveniencia={},
                rodape="",
                criada_em="",
            )
            for i in range(10)
        ]
        mensagens = agente._montar_mensagens("pergunta atual", trocas)
        self.assertLessEqual(agente._bytes_utf8(mensagens), agente.ORCAMENTO_ENTRADA_BYTES)
        self.assertEqual(mensagens[0]["role"], "system")
        self.assertEqual(mensagens[-1]["content"], "pergunta atual")


class TestErroDoProvedor(AssistenteTestBase):
    def test_erro_cliente_nao_vaza_pergunta_no_log(self):
        from django.utils import timezone

        class ClienteComErro:
            def chat(self, *args, **kwargs):
                raise cliente_mod.ErroCliente("limite_taxa")

        pergunta_secreta = "pergunta-que-nunca-pode-aparecer-no-log"
        with self.assertLogs("apps.assistente", level="INFO") as captura:
            resposta = agente.responder(
                usuario=self.editor,
                exercicio=None,
                pergunta=pergunta_secreta,
                trocas=[],
                cliente=ClienteComErro(),
                agora=timezone.now(),
            )
        self.assertEqual(resposta.erro_codigo, "limite_taxa")
        saida = "\n".join(captura.output)
        self.assertNotIn(pergunta_secreta, saida)


class TestNovaTentativaDoProvedor(AssistenteTestBase):
    """Falha passageira do provedor ganha uma nova tentativa dentro do prazo da pergunta (achado de
    2026-09-23: timeouts pontuais derrubavam perguntas inteiras com orçamento sobrando)."""

    def _cliente(self, erros, texto="Resposta depois da falha."):
        class ClienteInstavel:
            def __init__(self):
                self.chamadas = 0

            def chat(self, *args, **kwargs):
                self.chamadas += 1
                if self.chamadas <= len(erros):
                    raise cliente_mod.ErroCliente(erros[self.chamadas - 1])
                return resposta_texto(texto)

        return ClienteInstavel()

    def _responder(self, cliente, relogio=None, prazo_s=None):
        from django.utils import timezone

        return agente.responder(
            usuario=self.editor, exercicio=None, pergunta="oi", trocas=[], cliente=cliente,
            agora=timezone.now(), relogio=relogio or _RelogioFalso(passo=1.0), prazo_s=prazo_s,
        )

    def test_timeout_seguido_de_sucesso_responde(self):
        cliente = self._cliente(["timeout"])
        with self.assertLogs("apps.assistente", level="WARNING") as captura:
            resposta = self._responder(cliente)
        self.assertIsNone(resposta.erro_codigo)
        self.assertIn("Resposta depois da falha.", resposta.texto_md)
        self.assertEqual(cliente.chamadas, 2)
        self.assertTrue(any("nova tentativa" in linha for linha in captura.output))

    def test_conexao_e_provedor_tambem_ganham_nova_tentativa(self):
        for codigo in ("conexao", "provedor"):
            with self.subTest(codigo=codigo):
                resposta = self._responder(self._cliente([codigo]))
                self.assertIsNone(resposta.erro_codigo)

    def test_duas_falhas_seguidas_devolvem_o_erro(self):
        cliente = self._cliente(["timeout", "timeout"])
        resposta = self._responder(cliente)
        self.assertEqual(resposta.erro_codigo, "timeout")
        self.assertEqual(cliente.chamadas, 2)

    def test_limite_de_taxa_e_autenticacao_nao_tentam_de_novo(self):
        for codigo in ("limite_taxa", "autenticacao"):
            with self.subTest(codigo=codigo):
                cliente = self._cliente([codigo])
                resposta = self._responder(cliente)
                self.assertEqual(resposta.erro_codigo, codigo)
                self.assertEqual(cliente.chamadas, 1)

    def test_sem_prazo_suficiente_nao_tenta_de_novo(self):
        cliente = self._cliente(["timeout"])
        resposta = self._responder(cliente, relogio=_RelogioFalso(passo=30.0), prazo_s=40)
        self.assertEqual(resposta.erro_codigo, "timeout")
        self.assertEqual(cliente.chamadas, 1)


class TestRecusaPorPermissao(AssistenteTestBase):
    def test_recusa_aparece_mesmo_com_texto_vazio_do_modelo(self):
        from django.utils import timezone

        fake = ClienteFalso(
            [
                resposta_ferramenta("consultar_processos", {"exercicio": 2026, "limite": 20}),
                resposta_texto(""),
            ]
        )
        with mock.patch(
            "apps.assistente.agente.ferramentas.executar",
            return_value=ferramentas.Envelope(dados={}, sem_permissao=True),
        ):
            resposta = agente.responder(
                usuario=self.editor,
                exercicio=self._exercicio_2026(),
                pergunta="pergunta",
                trocas=[],
                cliente=fake,
                agora=timezone.now(),
            )
        self.assertIn("Sem permissão para consultar", resposta.texto_md)

    def _exercicio_2026(self):
        from apps.catalogo.models import Exercicio

        return Exercicio.objects.get(ano=2026)


class TestEncadeamentoAntesDeDesistir(AssistenteTestBase):
    """Achado do UAT informal de 19/09: o modelo
    chamava só `consultar_processos`, recebia itens sem signatários e
    respondia "não encontrei" em vez de encadear com `ficha`. O prompt
    passou a instruir esse encadeamento; este teste prova que o LAÇO do
    agente executa normalmente duas `tool_calls` em sequência (uma por
    rodada) antes da resposta final — o cenário que o UAT mostrou faltando."""

    def test_consultar_depois_ficha_antes_da_resposta_final(self):
        from django.utils import timezone

        fake = ClienteFalso(
            [
                resposta_ferramenta(
                    "consultar_processos", {"fornecedor": "Sollo", "exercicio": 2026, "limite": 20}
                ),
                resposta_ferramenta("ficha", {"exercicio": 2026, "item": 4}),
                resposta_texto("O contrato da Sollo foi assinado por Maria da Sollo."),
            ]
        )

        def _executar_falso(nome, argumentos_json, *, usuario, exercicio_padrao, contexto=None):
            if nome == "consultar_processos":
                return ferramentas.Envelope(
                    dados={"total": 2, "itens": [{"item_pca": 4}, {"item_pca": 9}]}
                )
            if nome == "ficha":
                return ferramentas.Envelope(
                    dados={"instrumentos": [{"signatarios": [{"nome": "Maria da Sollo"}]}]}
                )
            raise AssertionError(f"ferramenta inesperada: {nome}")

        with mock.patch(
            "apps.assistente.agente.ferramentas.executar", side_effect=_executar_falso
        ):
            resposta = agente.responder(
                usuario=self.editor,
                exercicio=self._exercicio_2026(),
                pergunta="quem assinou o contrato da Sollo?",
                trocas=[],
                cliente=fake,
                agora=timezone.now(),
            )

        self.assertEqual(resposta.chamadas_chat, 3)
        self.assertEqual(resposta.ferramentas_usadas, 2)
        self.assertIn("Maria da Sollo", resposta.texto_md)

    def _exercicio_2026(self):
        from apps.catalogo.models import Exercicio

        return Exercicio.objects.get(ano=2026)


class TestPromptEncadeamentoFonte(AssistenteTestBase):
    """Teste de fonte (sem chamada de rede): garante que a instrução de
    encadeamento e a referência cruzada entre ferramentas existem no texto
    enviado ao modelo — regressão contra a reintrodução do "não encontrei"
    precoce descrito no motivo desta quick."""

    def test_prompt_sistema_contem_encadeie(self):
        self.assertIn("ENCADEIE", agente.PROMPT_SISTEMA)

    def test_descricao_consultar_processos_referencia_ficha(self):
        descricao = ferramentas.ESQUEMAS["consultar_processos"]["function"]["description"]
        self.assertIn("chame `ficha(", descricao)


class TestPromptConceitosVaoParaDocs(AssistenteTestBase):
    """Pergunta conceitual encadeia `buscar_texto(fonte=
    'docs')` antes de responder; o modelo nunca oferece conhecimento geral
    nem 'fontes externas'."""

    def test_pergunta_conceitual_encadeia_buscar_texto_docs(self):
        from django.utils import timezone

        fake = ClienteFalso(
            [
                resposta_ferramenta(
                    "buscar_texto",
                    {
                        "pergunta": "indicador Kaplan-Meier",
                        "fonte": "docs",
                        "exercicio": None,
                        "item": None,
                    },
                ),
                resposta_texto("O indicador Kaplan-Meier estima a probabilidade de conclusão."),
            ]
        )
        resposta = agente.responder(
            usuario=self.editor,
            exercicio=self._exercicio_2026(),
            pergunta="O que é o indicador Kaplan-Meier?",
            trocas=[],
            cliente=fake,
            agora=timezone.now(),
        )
        self.assertEqual(resposta.chamadas_chat, 2)
        primeira_chamada = fake.chamadas[0]
        sistema = primeira_chamada["mensagens"][0]["content"]
        self.assertIn("fonte='docs'", sistema)
        # A proibição de conhecimento geral
        # deixou de ser genérica; continua valendo SÓ para perguntas sobre
        # o funcionamento do próprio sistema (telas/indicadores), nunca
        # para outros assuntos (ex.: legislação, boas práticas).
        self.assertIn("deste sistema especificamente", sistema)

    def test_prompt_sistema_nao_oferece_fontes_externas_fora_da_negacao(self):
        self.assertIn("nunca ofereça", agente.PROMPT_SISTEMA)
        self.assertIn("documentos externos", agente.PROMPT_SISTEMA)

    def test_descricao_buscar_texto_menciona_kaplan_meier(self):
        descricao = ferramentas.ESQUEMAS["buscar_texto"]["function"]["description"]
        self.assertIn("Kaplan-Meier", descricao)

    def _exercicio_2026(self):
        from apps.catalogo.models import Exercicio

        return Exercicio.objects.get(ano=2026)


class TestMontarRodapeDataFormatada(AssistenteTestBase):
    """'Textos indexados em' usa dd/mm/aaaa hh:mm
    (America/Sao_Paulo), como os demais carimbos do rodapé, nunca o ISO
    cru devolvido por `indice.publicado_em()`."""

    def test_indice_iso_conhecido_vira_data_formatada(self):
        from django.utils import timezone

        proveniencia = {
            "consultar_processos": {
                "pca_consultado_em": "2026-09-20T01:39:58.530492+00:00",
                "sei": None,
                "indice": "2026-09-20T01:39:58.530492+00:00",
            }
        }
        rodape = agente.montar_rodape(proveniencia, timezone.now())
        self.assertIn("Textos indexados em", rodape)
        trecho_indice = rodape.split("Textos indexados em")[1]
        self.assertNotIn("T", trecho_indice.split("·")[0].split(".")[0])
        self.assertNotIn("+00:00", trecho_indice)
        import re

        self.assertRegex(trecho_indice, r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}")

    def test_sem_indice_publicado_continua_nao_disponivel(self):
        from django.utils import timezone

        proveniencia = {
            "consultar_processos": {
                "pca_consultado_em": timezone.now().isoformat(),
                "sei": None,
                "indice": None,
            }
        }
        rodape = agente.montar_rodape(proveniencia, timezone.now())
        self.assertIn("Textos indexados em não disponível", rodape)


class TestPromptContextoEHistorico(AssistenteTestBase):
    """A mensagem de sistema informa data de hoje,
    exercício da página e exercícios existentes (o modelo chutava
    `exercicio=2024`), e declara o histórico da conversa como contexto,
    nunca fonte de dados (após uma edição, o modelo repetia a resposta
    antiga sem reconsultar a ferramenta)."""

    def _exercicio_2026(self):
        from apps.catalogo.models import Exercicio

        return Exercicio.objects.get(ano=2026)

    def test_prompt_informa_data_exercicio_e_exercicios_existentes(self):
        from datetime import datetime, timezone as tz

        from apps.catalogo.models import Exercicio

        fake = ClienteFalso(
            [
                resposta_ferramenta("ficha", {"exercicio": None, "item": 60}),
                resposta_texto("O item 60 é ..."),
            ]
        )
        agora = datetime(2026, 9, 21, 23, 56, tzinfo=tz.utc)  # 21/09 20:56 em São Paulo
        agente.responder(
            usuario=self.editor,
            exercicio=self._exercicio_2026(),
            pergunta="O 60 é qual",
            trocas=[],
            cliente=fake,
            agora=agora,
        )
        sistema = fake.chamadas[0]["mensagens"][0]["content"]
        self.assertIn("hoje é 21/09/2026", sistema)
        self.assertIn("Exercício (PCA) da página: 2026", sistema)
        anos = ", ".join(str(a) for a in Exercicio.objects.order_by("ano").values_list("ano", flat=True))
        self.assertIn(f"Exercícios existentes no sistema: {anos}", sistema)
        self.assertIn("nunca outro ano", sistema)

    def test_prompt_sistema_declara_historico_como_contexto_nunca_fonte(self):
        self.assertIn("NUNCA como fonte de dados", agente.PROMPT_SISTEMA)
        self.assertIn("chame a ferramenta de novo", agente.PROMPT_SISTEMA)

    def test_montar_mensagens_sem_contexto_mantem_prompt_puro(self):
        mensagens = agente._montar_mensagens("x", [])
        self.assertEqual(mensagens[0]["content"], agente.PROMPT_SISTEMA)
