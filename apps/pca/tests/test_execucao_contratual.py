from apps.catalogo.models import InstrumentoContratual, Modalidade
from apps.pca.models import Acompanhamento, TipoEvento
from apps.pca.tests._bases_edicao_campo import DetalheEdicaoBase

CAMPOS_EXECUCAO = (
    "data_recebimento_gelic",
    "modalidade",
    "vigencia_inicio",
    "vigencia_fim",
    "numero_contratacao",
    "numero_arp",
    "instrumento_contratual",
    "numero_instrumento_contratual",
    "valor_contratado",
    "fornecedor_cnpj",
    "fornecedor_razao_social",
    "data_assinatura_contrato",
    "data_lancamento_spw",
    "data_lancamento_wordpress",
    "data_lancamento_dados_abertos",
)

# Cobertos por test_validators.py (checksum de CNPJ e a checagem cruzada de
# vigência) — este arquivo cobre os demais campos "genéricos" do bloco, cujo
# dispatch de widget já é resolvido por `ProcessoForm`/`field.clean()` sem
# nenhuma branch nova.
CAMPOS_GENERICOS = tuple(
    campo
    for campo in CAMPOS_EXECUCAO
    if campo not in ("fornecedor_cnpj", "vigencia_inicio", "vigencia_fim")
)


class ExecucaoContratualBase(DetalheEdicaoBase):
    """`pca:editar_processo` é página própria (`processo_formulario.html`),
    sem abas: o `ProcessoForm` inteiro é submetido de uma vez, não um
    campo por POST num `<form>` de aba isolado. `_dados_completos`/
    `_url_editar` vivem em `_bases_edicao_campo.py`, reaproveitados também
    por `test_validators.py`."""


class TestExecucaoContratualDisplay(ExecucaoContratualBase):
    def test_campo_cnpj_aparece_editavel_no_formulario(self):
        resposta = self.client.get(self._url_editar())
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'name="fornecedor_cnpj"')


class TestExecucaoContratualEdicao(ExecucaoContratualBase):
    def _valor_e_esperado(self, campo):
        """Devolve (valor_submetido, avaliador(processo)) para o campo."""
        if campo == "data_recebimento_gelic":
            return "2026-02-01", lambda p: str(p.data_recebimento_gelic) == "2026-02-01"
        if campo == "modalidade":
            modalidade = Modalidade.objects.first()
            return str(modalidade.pk), lambda p: p.modalidade_id == modalidade.pk
        if campo == "numero_contratacao":
            return "123/2026", lambda p: p.numero_contratacao == "123/2026"
        if campo == "numero_arp":
            return "ARP-001/2026", lambda p: p.numero_arp == "ARP-001/2026"
        if campo == "instrumento_contratual":
            instrumento = InstrumentoContratual.objects.first()
            return str(instrumento.pk), lambda p: p.instrumento_contratual_id == instrumento.pk
        if campo == "numero_instrumento_contratual":
            return "INST-01/2026", lambda p: p.numero_instrumento_contratual == "INST-01/2026"
        if campo == "valor_contratado":
            return "1234.56", lambda p: str(p.valor_contratado) == "1234.56"
        if campo == "fornecedor_razao_social":
            return "Empresa Teste LTDA", lambda p: p.fornecedor_razao_social == "Empresa Teste LTDA"
        if campo == "data_assinatura_contrato":
            return "2026-02-10", lambda p: str(p.data_assinatura_contrato) == "2026-02-10"
        if campo == "data_lancamento_spw":
            return "2026-02-15", lambda p: str(p.data_lancamento_spw) == "2026-02-15"
        if campo == "data_lancamento_wordpress":
            return "2026-02-16", lambda p: str(p.data_lancamento_wordpress) == "2026-02-16"
        if campo == "data_lancamento_dados_abertos":
            return "2026-02-17", lambda p: str(p.data_lancamento_dados_abertos) == "2026-02-17"
        raise AssertionError(f"campo sem valor de teste: {campo}")

    def test_editor_salva_cada_campo_generico_sem_criar_acompanhamento(self):
        # Dois campos não são neutros: preencher `data_recebimento_gelic`
        # ou `data_assinatura_contrato` pode disparar
        # `aplicar_regras_automaticas`, que grava no máximo um
        # acompanhamento automático (reuniao=None) por transição real. Para
        # os demais campos, a contagem continua parada.
        campos_gatilho = ("data_recebimento_gelic", "data_assinatura_contrato")
        for campo in CAMPOS_GENERICOS:
            with self.subTest(campo=campo):
                self.processo.refresh_from_db()
                antes = Acompanhamento.objects.count()
                valor, avaliador = self._valor_e_esperado(campo)
                dados = self._dados_completos(**{campo: valor})

                resposta = self.client.post(self._url_editar(), dados)

                self.assertEqual(resposta.status_code, 302, resposta.context and resposta.context["form"].errors)
                self.processo.refresh_from_db()
                self.assertTrue(
                    avaliador(self.processo),
                    f"{campo} não gravou o valor esperado ({valor!r})",
                )
                novos = Acompanhamento.objects.count() - antes
                if campo in campos_gatilho:
                    self.assertIn(novos, (0, 1))
                    if novos == 1:
                        ultimo = Acompanhamento.objects.latest("pk")
                        self.assertEqual(
                            ultimo.tipo_evento, TipoEvento.AUTOMATICO
                        )
                        self.assertIsNone(ultimo.reuniao)
                else:
                    self.assertEqual(novos, 0)

    def test_valor_contratado_aparece_formatado_em_moeda_no_detalhe(self):
        dados = self._dados_completos(valor_contratado="1234.56")

        resposta = self.client.post(self._url_editar(), dados)
        self.assertEqual(resposta.status_code, 302)

        detalhe = self.client.get(resposta.url)
        self.assertContains(detalhe, "1.234,56")
        self.assertNotContains(detalhe, "1234.56")
