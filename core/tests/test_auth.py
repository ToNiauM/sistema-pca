from datetime import timedelta
from unittest.mock import patch

from axes.backends import AxesBackend
from axes.helpers import get_client_ip_address
from django.contrib.auth import authenticate
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.test import Client, RequestFactory, TestCase, override_settings
from django.utils import timezone

from core.models import Usuario


class AuthenticationFoundationTests(TestCase):
    def setUp(self):
        self.email = "pres@exemplo.gov.br"
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

    def test_axes_blocks_sixth_attempt_for_same_email_and_ip(self):
        # `authenticate()` de alto nível captura o `PermissionDenied` de
        # qualquer backend e nunca o propaga — só devolve `None`. Por isso
        # as 5 primeiras tentativas usam `authenticate()` de alto nível
        # (alimenta o rastreador de falhas do axes), e a 6ª chama o
        # `AxesBackend` diretamente para observar o `PermissionDenied`.
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
        AXES_IPWARE_PROXY_COUNT=2,
        AXES_IPWARE_META_PRECEDENCE_ORDER=(
            "HTTP_X_FORWARDED_FOR",
            "REMOTE_ADDR",
        ),
    )
    def test_axes_resolves_leftmost_client_ip_only_with_header_precedence(self):
        request = self.factory.get(
            "/login/",
            HTTP_X_FORWARDED_FOR=(
                "203.0.113.9, 198.51.100.5, 172.18.0.2"
            ),
            REMOTE_ADDR="172.18.0.3",
        )
        request.user = AnonymousUser()

        self.assertEqual(get_client_ip_address(request), "203.0.113.9")

        with override_settings(
            AXES_IPWARE_PROXY_COUNT=2,
            AXES_IPWARE_META_PRECEDENCE_ORDER=("REMOTE_ADDR",),
        ):
            self.assertIsNone(get_client_ip_address(request))

    @staticmethod
    def _session_expiry(client):
        return client.session.get_expiry_date()
