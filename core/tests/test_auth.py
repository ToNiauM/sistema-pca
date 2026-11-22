from datetime import timedelta
from unittest.mock import patch

from axes.backends import AxesBackend
from axes.helpers import get_client_ip_address
from django.contrib.auth import authenticate
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.test import Client, RequestFactory, TestCase, override_settings
from django.utils import timezone

from config.settings import prod as prod_settings
from core.models import Usuario


class AuthenticationFoundationTests(TestCase):
    def setUp(self):
        self.email = "pres@cfc.org.br"
        self.password = "correta"
        self.user = Usuario.objects.create_user(
            email=self.email,
            password=self.password,
        )
        self.factory = RequestFactory()

    def test_authenticate_uses_email_with_username_keyword(self):
        request = self.factory.post("/login/", REMOTE_ADDR="203.0.113.10")

        user = authenticate(
            request,
            username=self.email,
            password=self.password,
        )

        self.assertEqual(user, self.user)

    def test_authenticate_e_insensivel_a_maiuscula_minuscula_no_email(self):
        """QA 30/09/2026, periferia #8 — login autentica com o e-mail em
        qualquer capitalização. O axes continuar contando cada grafia
        como tentativa separada é comportamento aceito (T-41o-04), não é
        bypass do bloqueio."""
        request = self.factory.post("/login/", REMOTE_ADDR="203.0.113.12")

        user = authenticate(
            request,
            username="PRES@CFC.ORG.BR",
            password=self.password,
        )

        self.assertEqual(user, self.user)

    def test_axes_blocks_sixth_attempt_for_same_email_and_ip(self):
        # `django.contrib.auth.authenticate()` (o dispatcher de nível superior)
        # captura o `PermissionDenied` levantado por qualquer backend e NUNCA o
        # propaga para quem chamou — apenas devolve `None` (comportamento
        # documentado em `django/contrib/auth/__init__.py`, confirmado também
        # pelo próprio comentário em `axes/backends.py`: "This error stops
        # bubbling up at the authenticate call which catches backend
        # PermissionDenied errors."). Por isso as 5 primeiras tentativas usam
        # o `authenticate()` de alto nível (é ele quem alimenta o rastreador
        # de falhas do axes via o sinal `user_login_failed`), e a 6ª chama o
        # `AxesBackend` diretamente para observar o `PermissionDenied` que a
        # documentação da lib garante — a mesma exceção que `core/views.py`
        #precisa tratar via `request.axes_locked_out`, não via
        # `except PermissionDenied` ao redor do `authenticate()` de alto nível.
        request = self.factory.post("/login/", REMOTE_ADDR="203.0.113.11")

        for _ in range(5):
            self.assertIsNone(
                authenticate(
                    request,
                    username=self.email,
                    password="incorreta",
                )
            )

        with self.assertRaises(PermissionDenied):
            AxesBackend().authenticate(
                request,
                username=self.email,
                password="incorreta",
            )

    @override_settings(
        SESSION_COOKIE_AGE=120,
        SESSION_SAVE_EVERY_REQUEST=True,
        SESSION_COOKIE_SECURE=False,
    )
    def test_read_only_requests_extend_session_expiry(self):
        client = Client()
        client.force_login(self.user)
        first_expiry = self._session_expiry(client)

        # O valor futuro precisa ser calculado ANTES de entrar no bloco
        # `with patch(...)` — chamar `timezone.now()` já dentro do patch
        # retorna o `MagicMock` autogerado (não uma data real), e somar
        # `timedelta` a ele produz outro `MagicMock` em vez de um datetime,
        # quebrando a consulta de sessão no banco mais adiante.
        future_time = timezone.now() + timedelta(seconds=30)
        with patch("django.utils.timezone.now") as mocked_now:
            mocked_now.return_value = future_time
            response = client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertGreater(self._session_expiry(client), first_expiry)

    @override_settings(
        AXES_IPWARE_PROXY_COUNT=1,
        AXES_IPWARE_META_PRECEDENCE_ORDER=(
            "HTTP_X_FORWARDED_FOR",
            "REMOTE_ADDR",
        ),
    )
    def test_axes_resolves_leftmost_client_ip_only_with_header_precedence(self):
        # QA 30/09/2026 (achado A1): `proxy_count=1` é o valor correto para a
        # topologia real (Cloudflare + nginx repassando só a borda, ver
        # `config/settings/prod.py`) — um XFF de 2 entradas (cliente, borda)
        # resolve ao valor da esquerda.
        request = self.factory.get(
            "/login/",
            HTTP_X_FORWARDED_FOR="203.0.113.9, 172.18.0.2",
            REMOTE_ADDR="172.18.0.3",
        )
        request.user = AnonymousUser()

        self.assertEqual(get_client_ip_address(request), "203.0.113.9")

        with override_settings(
            AXES_IPWARE_PROXY_COUNT=1,
            AXES_IPWARE_META_PRECEDENCE_ORDER=("REMOTE_ADDR",),
        ):
            self.assertIsNone(get_client_ip_address(request))

    @staticmethod
    def _session_expiry(client):
        return client.session.get_expiry_date()

    def test_xff_realista_cloudflare_nginx_resolve_ao_ip_do_cliente(self):
        """A1 — topologia real (Cloudflare acrescenta o IP do cliente, nginx
        do host só repassa a borda Cloudflare): XFF chega com EXATAMENTE 2
        entradas. Com `AXES_IPWARE_PROXY_COUNT` da produção (lido de
        `config.settings.prod`, nunca hardcoded aqui), isso precisa resolver
        ao IP real do cliente — hoje (`=2`) resolve `None` (achado A1)."""
        request = self.factory.get(
            "/login/",
            HTTP_X_FORWARDED_FOR="198.51.100.9, 172.70.1.1",
            REMOTE_ADDR="172.18.0.3",
        )
        request.user = AnonymousUser()

        with override_settings(
            AXES_IPWARE_PROXY_COUNT=prod_settings.AXES_IPWARE_PROXY_COUNT,
            AXES_IPWARE_META_PRECEDENCE_ORDER=(
                prod_settings.AXES_IPWARE_META_PRECEDENCE_ORDER
            ),
        ):
            self.assertEqual(get_client_ip_address(request), "198.51.100.9")

    def test_xff_forjado_nunca_resolve_ao_ip_escolhido_pelo_atacante(self):
        """A1 — cliente injeta uma 3ª entrada tentando se passar por
        "1.2.3.4". Com a contagem de proxy correta da produção, isso nunca
        pode resolver para o valor forjado pelo atacante (hoje, com `=2`,
        resolve EXATAMENTE para "1.2.3.4" — o ataque do achado)."""
        request = self.factory.get(
            "/login/",
            HTTP_X_FORWARDED_FOR="1.2.3.4, 198.51.100.9, 172.70.1.1",
            REMOTE_ADDR="172.18.0.3",
        )
        request.user = AnonymousUser()

        with override_settings(
            AXES_IPWARE_PROXY_COUNT=prod_settings.AXES_IPWARE_PROXY_COUNT,
            AXES_IPWARE_META_PRECEDENCE_ORDER=(
                prod_settings.AXES_IPWARE_META_PRECEDENCE_ORDER
            ),
        ):
            self.assertNotEqual(get_client_ip_address(request), "1.2.3.4")
