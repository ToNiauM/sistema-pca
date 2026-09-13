from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from apps.pca.models import Acompanhamento
from apps.pca.tests._bases_edicao_campo import DetalheEdicaoBase
from apps.pca.validators import validar_digitos_cnpj, validar_formato_cnpj


class TestValidarFormatoCnpj(SimpleTestCase):
    def test_com_mascara_nao_levanta(self):
        validar_formato_cnpj("00.000.000/0001-91")

    def test_sem_mascara_levanta(self):
        with self.assertRaises(ValidationError):
            validar_formato_cnpj("00000000000191")


class TestValidarDigitosCnpj(SimpleTestCase):
    def test_banco_do_brasil_nao_levanta(self):
        validar_digitos_cnpj("00.000.000/0001-91")

    def test_petrobras_nao_levanta(self):
        validar_digitos_cnpj("33.000.167/0001-01")

    def test_bradesco_nao_levanta(self):
        validar_digitos_cnpj("60.746.948/0001-12")

    def test_digitos_repetidos_levanta(self):
        with self.assertRaises(ValidationError):
            validar_digitos_cnpj("11.111.111/1111-11")

    def test_todos_os_digitos_zero_levantam(self):
        with self.assertRaises(ValidationError):
            validar_digitos_cnpj("00.000.000/0000-00")

    def test_checksum_incorreto_levanta(self):
        with self.assertRaises(ValidationError):
            validar_digitos_cnpj("00.000.000/0001-00")


class TestEdicaoCnpjEVigenciaViaFormularioCompleto(DetalheEdicaoBase):
    # Validadores rodam via `ProcessoForm`/`pca:editar_processo`
    # (`_dados_completos`/`_url_editar`), submetendo o formulário inteiro
    # em vez de um campo isolado.
    def test_cnpj_valido_grava(self):
        antes = Acompanhamento.objects.count()
        dados = self._dados_completos(fornecedor_cnpj="00.000.000/0001-91")
        resposta = self.client.post(self._url_editar(), dados)
        self.assertEqual(resposta.status_code, 302, resposta.context and resposta.context["form"].errors)
        self.processo.refresh_from_db()
        self.assertEqual(self.processo.fornecedor_cnpj, "00.000.000/0001-91")
        self.assertEqual(Acompanhamento.objects.count(), antes)

    def test_cnpj_com_digito_verificador_invalido_e_rejeitado_e_preserva_valor(self):
        dados = self._dados_completos(fornecedor_cnpj="11.111.111/1111-11")
        resposta = self.client.post(self._url_editar(), dados)
        self.assertEqual(resposta.status_code, 200)
        conteudo = resposta.content.decode()
        self.assertIn("Informe um valor válido.", conteudo)
        self.assertIn("11.111.111/1111-11", conteudo)
        self.processo.refresh_from_db()
        self.assertNotEqual(self.processo.fornecedor_cnpj, "11.111.111/1111-11")

    def test_cnpj_com_todos_os_digitos_zero_e_rejeitado_e_preserva_valor(self):
        cnpj_submetido = "00.000.000/0000-00"
        cnpj_persistido = self.processo.fornecedor_cnpj
        dados = self._dados_completos(fornecedor_cnpj=cnpj_submetido)
        resposta = self.client.post(self._url_editar(), dados)
        self.assertEqual(resposta.status_code, 200)
        conteudo = resposta.content.decode()
        self.assertIn("Informe um valor válido.", conteudo)
        self.assertIn(cnpj_submetido, conteudo)
        self.processo.refresh_from_db()
        self.assertEqual(self.processo.fornecedor_cnpj, cnpj_persistido)

    def test_vigencia_fim_aceita_quando_maior_ou_igual_ao_inicio_salvo(self):
        self.processo.vigencia_inicio = "2026-01-10"
        self.processo._history_user = self.editor
        self.processo.save(update_fields=["vigencia_inicio", "atualizado_em"])
        self.processo.refresh_from_db()

        dados = self._dados_completos(vigencia_inicio="2026-01-10", vigencia_fim="2026-01-10")
        resposta = self.client.post(self._url_editar(), dados)
        self.assertEqual(resposta.status_code, 302, resposta.context and resposta.context["form"].errors)
        self.processo.refresh_from_db()
        self.assertEqual(str(self.processo.vigencia_fim), "2026-01-10")

    def test_vigencia_fim_rejeitada_quando_anterior_ao_inicio_salvo(self):
        antes = Acompanhamento.objects.count()
        self.processo.vigencia_inicio = "2026-01-10"
        self.processo._history_user = self.editor
        self.processo.save(update_fields=["vigencia_inicio", "atualizado_em"])
        self.processo.refresh_from_db()

        dados = self._dados_completos(vigencia_inicio="2026-01-10", vigencia_fim="2026-01-01")
        resposta = self.client.post(self._url_editar(), dados)
        self.assertEqual(resposta.status_code, 200)
        conteudo = resposta.content.decode()
        self.assertIn("A vigência final não pode ser anterior à inicial.", conteudo)
        self.assertIn("2026-01-01", conteudo)
        self.processo.refresh_from_db()
        self.assertIsNone(self.processo.vigencia_fim)
        self.assertEqual(Acompanhamento.objects.count(), antes)

    def test_vigencia_inicio_aceita_quando_menor_ou_igual_ao_fim_salvo(self):
        self.processo.vigencia_fim = "2026-06-30"
        self.processo._history_user = self.editor
        self.processo.save(update_fields=["vigencia_fim", "atualizado_em"])
        self.processo.refresh_from_db()

        dados = self._dados_completos(vigencia_fim="2026-06-30", vigencia_inicio="2026-06-30")
        resposta = self.client.post(self._url_editar(), dados)
        self.assertEqual(resposta.status_code, 302, resposta.context and resposta.context["form"].errors)
        self.processo.refresh_from_db()
        self.assertEqual(str(self.processo.vigencia_inicio), "2026-06-30")

    def test_vigencia_inicio_rejeitada_quando_posterior_ao_fim_salvo(self):
        antes = Acompanhamento.objects.count()
        self.processo.vigencia_fim = "2026-06-30"
        self.processo._history_user = self.editor
        self.processo.save(update_fields=["vigencia_fim", "atualizado_em"])
        self.processo.refresh_from_db()

        dados = self._dados_completos(vigencia_fim="2026-06-30", vigencia_inicio="2026-07-01")
        resposta = self.client.post(self._url_editar(), dados)
        self.assertEqual(resposta.status_code, 200)
        conteudo = resposta.content.decode()
        self.assertIn("A vigência final não pode ser anterior à inicial.", conteudo)
        self.processo.refresh_from_db()
        self.assertIsNone(self.processo.vigencia_inicio)
        self.assertEqual(Acompanhamento.objects.count(), antes)
