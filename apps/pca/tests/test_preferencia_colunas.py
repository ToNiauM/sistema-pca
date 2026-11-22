"""As colunas escolhidas na tela Processos ficam gravadas na
CONTA do usuário (não só na sessão): sobrevivem ao logout e a outro
navegador, até ele escolher outras ou restaurar o padrão."""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.http import QueryDict
from django.test import Client, TestCase
from django.urls import reverse

from apps.pca.colunas import CHAVE_SESSAO_COLUNAS, COLUNAS_PADRAO, colunas_selecionadas
from apps.pca.models import PreferenciaColunas

ESCOLHA = ["item_pca", "descricao_objeto", "valor_estimado"]


class _Request:
    def __init__(self, usuario, query="", sessao=None):
        self.user = usuario
        self.GET = QueryDict(query)
        self.session = sessao if sessao is not None else {}


def _query(chaves):
    return "&".join(f"colunas={c}" for c in chaves)


class TestPreferenciaColunasNaConta(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_superuser(email="pref@example.com", password="x")

    def test_escolha_grava_na_conta_e_vale_em_outra_sessao(self):
        colunas_selecionadas(_Request(self.usuario, _query(ESCOLHA)))
        self.assertEqual(PreferenciaColunas.objects.get(usuario=self.usuario).colunas, ESCOLHA)
        # Outro navegador / novo login: sessão vazia, sem ?colunas=.
        nova_sessao = {}
        self.assertEqual(colunas_selecionadas(_Request(self.usuario, sessao=nova_sessao)), ESCOLHA)
        self.assertEqual(nova_sessao[CHAVE_SESSAO_COLUNAS], ESCOLHA)

    def test_conta_vence_sessao_antiga(self):
        PreferenciaColunas.objects.create(usuario=self.usuario, colunas=ESCOLHA)
        sessao = {CHAVE_SESSAO_COLUNAS: ["item_pca", "descricao_objeto", "estado"]}
        self.assertEqual(colunas_selecionadas(_Request(self.usuario, sessao=sessao)), ESCOLHA)

    def test_restaurar_padrao_apaga_a_preferencia(self):
        PreferenciaColunas.objects.create(usuario=self.usuario, colunas=ESCOLHA)
        sessao = {CHAVE_SESSAO_COLUNAS: ESCOLHA}
        resultado = colunas_selecionadas(_Request(self.usuario, _query(COLUNAS_PADRAO), sessao))
        self.assertFalse(PreferenciaColunas.objects.filter(usuario=self.usuario).exists())
        self.assertEqual(colunas_selecionadas(_Request(self.usuario)), resultado)

    def test_escolha_antiga_so_na_sessao_sobe_para_a_conta(self):
        colunas_selecionadas(_Request(self.usuario, sessao={CHAVE_SESSAO_COLUNAS: ESCOLHA}))
        self.assertEqual(PreferenciaColunas.objects.get(usuario=self.usuario).colunas, ESCOLHA)

    def test_anonimo_nao_grava(self):
        colunas_selecionadas(_Request(AnonymousUser(), _query(ESCOLHA)))
        self.assertEqual(PreferenciaColunas.objects.count(), 0)

    def test_sobrevive_ao_logout_pela_tela(self):
        cliente = Client(HTTP_X_FORWARDED_PROTO="https")
        cliente.force_login(self.usuario)
        cliente.get(f"{reverse('pca:tabela')}?{_query(ESCOLHA)}")
        cliente.logout()
        outro = Client(HTTP_X_FORWARDED_PROTO="https")
        outro.force_login(self.usuario)
        resposta = outro.get(reverse("pca:tabela"))
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(outro.session[CHAVE_SESSAO_COLUNAS], ESCOLHA)


class TestGravacaoSoSameOriginQA(TestCase):
    """QA de segurança 30/09/2026 (achado B4) — `GET /tabela?colunas=...`
    tem efeito colateral de escrita (grava a preferência na conta); com
    `SameSite=Lax`, um link cross-site de nível superior bastava para
    forjar a preferência de outra pessoa. Usa `self.client`/`force_login`
    de verdade (não o `_Request` fake acima, que nunca carrega cabeçalhos
    HTTP)."""

    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_superuser(
            email="b4@example.com", password="x"
        )

    def test_get_cross_site_nao_grava_preferencia(self):
        self.client.force_login(self.usuario)
        resposta = self.client.get(
            f"{reverse('pca:tabela')}?{_query(ESCOLHA)}",
            HTTP_SEC_FETCH_SITE="cross-site",
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertFalse(
            PreferenciaColunas.objects.filter(usuario=self.usuario).exists()
        )

    def test_get_same_origin_continua_gravando(self):
        self.client.force_login(self.usuario)
        resposta = self.client.get(
            f"{reverse('pca:tabela')}?{_query(ESCOLHA)}",
            HTTP_SEC_FETCH_SITE="same-origin",
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(
            PreferenciaColunas.objects.get(usuario=self.usuario).colunas, ESCOLHA
        )
