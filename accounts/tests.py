from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIRequestFactory
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from accounts.authentication import TokenVersionJWTAuthentication
from accounts.serializers import blacklist_user_tokens
from accounts.views import RefreshTokenView, LogoutView

from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework.test import force_authenticate
from accounts.views import ChangePasswordView, PasswordResetConfirmView

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.db import close_old_connections
from django.test import TransactionTestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.exceptions import AuthenticationFailed


class AuthenticationSecurityTests(TestCase):

    def setUp(self):
        self.User = get_user_model()
        self.user = self.User.objects.create_user(
            username="securitytester",
            email="securitytester@example.com",
            password="SecureTestPassword123!",
        )
        self.factory = APIRequestFactory()

    def create_tokens(self):
        from accounts.models import UserSession

        session = UserSession.objects.create(user=self.user)

        refresh = RefreshToken.for_user(self.user)
        refresh["token_version"] = self.user.token_version
        refresh["sid"] = str(session.id)

        return str(refresh), str(refresh.access_token)

    def test_valid_access_token_authenticates(self):
        _, access = self.create_tokens()

        auth = TokenVersionJWTAuthentication()
        result = auth.authenticate(
            self.factory.get(
                "/api/auth/me/",
                HTTP_AUTHORIZATION=f"Bearer {access}",
            )
        )

        self.assertIsNotNone(result)
        self.assertEqual(result[0].pk, self.user.pk)

    def test_token_revocation_invalidates_access_token(self):
        _, access = self.create_tokens()

        blacklist_user_tokens(self.user)

        auth = TokenVersionJWTAuthentication()

        with self.assertRaises(AuthenticationFailed):
            auth.authenticate(
                self.factory.get(
                    "/api/auth/me/",
                    HTTP_AUTHORIZATION=f"Bearer {access}",
                )
            )

    def test_rotated_refresh_token_cannot_be_reused(self):
        refresh, _ = self.create_tokens()
        view = RefreshTokenView.as_view()

        first_response = view(
            self.factory.post(
                "/api/auth/token/refresh/",
                {"refresh": refresh},
                format="json",
            )
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertIn("refresh", first_response.data)

        second_response = view(
            self.factory.post(
                "/api/auth/token/refresh/",
                {"refresh": refresh},
                format="json",
            )
        )

        self.assertEqual(second_response.status_code, 401)

    def test_logout_revokes_access_and_refresh_tokens(self):
        refresh, access = self.create_tokens()

        response = LogoutView.as_view()(
            self.factory.post(
                "/api/auth/logout/",
                format="json",
                HTTP_AUTHORIZATION=f"Bearer {access}",
            )
        )

        self.assertEqual(response.status_code, 200)

        self.user.refresh_from_db()

        # Device-specific logout must not revoke other sessions globally.
        self.assertEqual(self.user.token_version, 0)

        auth = TokenVersionJWTAuthentication()

        with self.assertRaises(AuthenticationFailed):
            auth.authenticate(
                self.factory.get(
                    "/api/auth/me/",
                    HTTP_AUTHORIZATION=f"Bearer {access}",
                )
            )

        refresh_response = RefreshTokenView.as_view()(
            self.factory.post(
                "/api/auth/token/refresh/",
                {"refresh": refresh},
                format="json",
            )
        )

        self.assertEqual(refresh_response.status_code, 401)

    def test_password_change_revokes_existing_tokens(self):
        refresh, access = self.create_tokens()

        request = self.factory.post(
            "/api/auth/change-password/",
            {
                "current_password": "SecureTestPassword123!",
                "new_password": "NewSecurePassword456!",
                "new_password_confirm": "NewSecurePassword456!",
            },
            format="json",
        )
        force_authenticate(request, user=self.user)

        response = ChangePasswordView.as_view()(request)

        self.assertEqual(response.status_code, 200)

        self.user.refresh_from_db()
        self.assertEqual(self.user.token_version, 1)
        self.assertTrue(
            self.user.check_password("NewSecurePassword456!")
        )

        auth = TokenVersionJWTAuthentication()

        with self.assertRaises(AuthenticationFailed):
            auth.authenticate(
                self.factory.get(
                    "/api/auth/me/",
                    HTTP_AUTHORIZATION=f"Bearer {access}",
                )
            )

        refresh_response = RefreshTokenView.as_view()(
            self.factory.post(
                "/api/auth/token/refresh/",
                {"refresh": refresh},
                format="json",
            )
        )

        self.assertEqual(refresh_response.status_code, 401)

    def test_wrong_current_password_does_not_revoke_tokens(self):
        _, access = self.create_tokens()

        request = self.factory.post(
            "/api/auth/change-password/",
            {
                "current_password": "IncorrectPassword123!",
                "new_password": "NewSecurePassword456!",
                "new_password_confirm": "NewSecurePassword456!",
            },
            format="json",
        )
        force_authenticate(request, user=self.user)

        response = ChangePasswordView.as_view()(request)

        self.assertEqual(response.status_code, 400)

        self.user.refresh_from_db()
        self.assertEqual(self.user.token_version, 0)
        self.assertTrue(
            self.user.check_password("SecureTestPassword123!")
        )

        auth = TokenVersionJWTAuthentication()

        result = auth.authenticate(
            self.factory.get(
                "/api/auth/me/",
                HTTP_AUTHORIZATION=f"Bearer {access}",
            )
        )

        self.assertIsNotNone(result)
        self.assertEqual(result[0].pk, self.user.pk)

    def test_password_reset_revokes_tokens_and_reset_link(self):
        refresh, access = self.create_tokens()

        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        reset_token = default_token_generator.make_token(self.user)

        payload = {
            "uid": uid,
            "token": reset_token,
            "new_password": "ResetSecurePassword789!",
        }

        response = PasswordResetConfirmView.as_view()(
            self.factory.post(
                "/api/auth/password-reset-confirm/",
                payload,
                format="json",
            )
        )

        self.assertEqual(response.status_code, 200)

        self.user.refresh_from_db()
        self.assertEqual(self.user.token_version, 1)
        self.assertTrue(
            self.user.check_password("ResetSecurePassword789!")
        )

        auth = TokenVersionJWTAuthentication()

        with self.assertRaises(AuthenticationFailed):
            auth.authenticate(
                self.factory.get(
                    "/api/auth/me/",
                    HTTP_AUTHORIZATION=f"Bearer {access}",
                )
            )

        refresh_response = RefreshTokenView.as_view()(
            self.factory.post(
                "/api/auth/token/refresh/",
                {"refresh": refresh},
                format="json",
            )
        )

        self.assertEqual(refresh_response.status_code, 401)

        replay_response = PasswordResetConfirmView.as_view()(
            self.factory.post(
                "/api/auth/password-reset-confirm/",
                payload,
                format="json",
            )
        )

        self.assertEqual(replay_response.status_code, 400)

    def test_complete_api_authentication_flow(self):
        client = APIClient()

        # 1. Protected profile requires authentication.
        response = client.get("/api/auth/me/")
        self.assertEqual(response.status_code, 401)

        # 2. Log in using the user's email.
        login_response = client.post(
            "/api/auth/login/",
            {
                "email": "securitytester@example.com",
                "password": "SecureTestPassword123!",
            },
            format="json",
        )

        self.assertEqual(login_response.status_code, 200)
        self.assertIn("access", login_response.data)
        self.assertIn("refresh", login_response.data)

        access = login_response.data["access"]
        refresh = login_response.data["refresh"]

        # 3. Access protected profile with JWT.
        client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {access}"
        )

        profile_response = client.get("/api/auth/me/")
        self.assertEqual(profile_response.status_code, 200)
        self.assertEqual(
            profile_response.data["email"],
            "securitytester@example.com",
        )

        # 4. Refresh the session.
        refresh_response = client.post(
            "/api/auth/token/refresh/",
            {"refresh": refresh},
            format="json",
        )

        self.assertEqual(refresh_response.status_code, 200)
        self.assertIn("access", refresh_response.data)
        self.assertIn("refresh", refresh_response.data)

        new_access = refresh_response.data["access"]
        new_refresh = refresh_response.data["refresh"]

        # 5. Confirm the new access token works.
        client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {new_access}"
        )

        response = client.get("/api/auth/me/")
        self.assertEqual(response.status_code, 200)

        # 6. Log out using the rotated refresh token.
        logout_response = client.post(
            "/api/auth/logout/",
            {"refresh": new_refresh},
            format="json",
        )

        self.assertEqual(logout_response.status_code, 200)

        # 7. Confirm the access token is revoked.
        response = client.get("/api/auth/me/")
        self.assertEqual(response.status_code, 401)

        # 8. Confirm the refresh token is revoked.
        client.credentials()

        response = client.post(
            "/api/auth/token/refresh/",
            {"refresh": new_refresh},
            format="json",
        )

        self.assertEqual(response.status_code, 401)

    def test_separate_logins_create_distinct_device_sessions(self):
        from accounts.models import UserSession

        client = APIClient()

        credentials = {
            "email": "securitytester@example.com",
            "password": "SecureTestPassword123!",
        }

        # Simulate a login from Device A.
        response_a = client.post(
            "/api/auth/login/",
            credentials,
            format="json",
        )

        self.assertEqual(response_a.status_code, 200)

        # Simulate a separate login from Device B.
        response_b = client.post(
            "/api/auth/login/",
            credentials,
            format="json",
        )

        self.assertEqual(response_b.status_code, 200)

        # Decode the refresh tokens.
        refresh_a = RefreshToken(response_a.data["refresh"])
        refresh_b = RefreshToken(response_b.data["refresh"])

        # Both logins must have session identifiers.
        self.assertIn("sid", refresh_a)
        self.assertIn("sid", refresh_b)

        # Different logins must create different sessions.
        self.assertNotEqual(
            refresh_a["sid"],
            refresh_b["sid"],
        )

        # Each access token must match its refresh session.
        access_a = AccessToken(response_a.data["access"])
        access_b = AccessToken(response_b.data["access"])

        self.assertEqual(access_a["sid"], refresh_a["sid"])
        self.assertEqual(access_b["sid"], refresh_b["sid"])

        # Both tokens must preserve global revocation version.
        self.assertEqual(
            refresh_a["token_version"],
            self.user.token_version,
        )
        self.assertEqual(
            refresh_b["token_version"],
            self.user.token_version,
        )

        # Confirm both sessions exist in the database.
        sessions = UserSession.objects.filter(user=self.user)

        self.assertEqual(sessions.count(), 2)

        for sid in (refresh_a["sid"], refresh_b["sid"]):
            session = UserSession.objects.get(pk=sid)
            self.assertEqual(session.user_id, self.user.pk)
            self.assertIsNone(session.revoked_at)

    def test_logout_one_device_preserves_other_device(self):
        from accounts.models import UserSession

        credentials = {
            "email": "securitytester@example.com",
            "password": "SecureTestPassword123!",
        }

        device_a = APIClient()
        device_b = APIClient()

        # Log in independently on two devices.
        login_a = device_a.post(
            "/api/auth/login/",
            credentials,
            format="json",
        )
        login_b = device_b.post(
            "/api/auth/login/",
            credentials,
            format="json",
        )

        self.assertEqual(login_a.status_code, 200)
        self.assertEqual(login_b.status_code, 200)

        access_a = login_a.data["access"]
        refresh_a = login_a.data["refresh"]

        access_b = login_b.data["access"]
        refresh_b = login_b.data["refresh"]

        sid_a = RefreshToken(refresh_a)["sid"]
        sid_b = RefreshToken(refresh_b)["sid"]

        self.assertNotEqual(sid_a, sid_b)

        # Both devices can initially access protected resources.
        device_a.credentials(
            HTTP_AUTHORIZATION=f"Bearer {access_a}"
        )
        device_b.credentials(
            HTTP_AUTHORIZATION=f"Bearer {access_b}"
        )

        self.assertEqual(
            device_a.get("/api/auth/me/").status_code,
            200,
        )
        self.assertEqual(
            device_b.get("/api/auth/me/").status_code,
            200,
        )

        # Log out Device A only.
        logout_response = device_a.post(
            "/api/auth/logout/",
            format="json",
        )

        self.assertEqual(logout_response.status_code, 200)

        # Device A's session is revoked.
        session_a = UserSession.objects.get(pk=sid_a)
        self.assertIsNotNone(session_a.revoked_at)

        # Device B's session remains active.
        session_b = UserSession.objects.get(pk=sid_b)
        self.assertIsNone(session_b.revoked_at)

        # Device A can no longer use its access token.
        self.assertEqual(
            device_a.get("/api/auth/me/").status_code,
            401,
        )

        # Device A cannot refresh its token.
        device_a.credentials()

        self.assertEqual(
            device_a.post(
                "/api/auth/token/refresh/",
                {"refresh": refresh_a},
                format="json",
            ).status_code,
            401,
        )

        # Device B's access token still works.
        self.assertEqual(
            device_b.get("/api/auth/me/").status_code,
            200,
        )

        # Device B can still rotate its refresh token.
        refresh_response_b = device_b.post(
            "/api/auth/token/refresh/",
            {"refresh": refresh_b},
            format="json",
        )

        self.assertEqual(refresh_response_b.status_code, 200)

        # The newly rotated Device B access token works.
        device_b.credentials(
            HTTP_AUTHORIZATION=(
                f"Bearer {refresh_response_b.data['access']}"
            )
        )

        self.assertEqual(
            device_b.get("/api/auth/me/").status_code,
            200,
        )

        # Logout must not trigger global token revocation.
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_version, 0)

    def test_malformed_session_id_rejected(self):
        refresh = RefreshToken.for_user(self.user)
        refresh["token_version"] = self.user.token_version
        refresh["sid"] = "not-a-valid-uuid"

        access = str(refresh.access_token)
        refresh_token = str(refresh)

        # A malformed session ID must not authenticate.
        client = APIClient()
        client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {access}"
        )

        access_response = client.get("/api/auth/me/")

        self.assertEqual(access_response.status_code, 401)

        # A malformed session ID must not allow token refresh.
        client.credentials()

        refresh_response = client.post(
            "/api/auth/token/refresh/",
            {"refresh": refresh_token},
            format="json",
        )

        self.assertEqual(refresh_response.status_code, 401)

    def test_missing_session_id_rejected(self):
        refresh = RefreshToken.for_user(self.user)
        refresh["token_version"] = self.user.token_version

        access_token = str(refresh.access_token)
        refresh_token = str(refresh)

        client = APIClient()
        client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {access_token}"
        )

        self.assertEqual(
            client.get("/api/auth/me/").status_code,
            401,
        )

        client.credentials()

        self.assertEqual(
            client.post(
                "/api/auth/token/refresh/",
                {"refresh": refresh_token},
                format="json",
            ).status_code,
            401,
        )

    def test_unknown_session_id_rejected(self):
        import uuid

        refresh = RefreshToken.for_user(self.user)
        refresh["token_version"] = self.user.token_version
        refresh["sid"] = str(uuid.uuid4())

        access_token = str(refresh.access_token)
        refresh_token = str(refresh)

        client = APIClient()
        client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {access_token}"
        )

        self.assertEqual(
            client.get("/api/auth/me/").status_code,
            401,
        )

        client.credentials()

        self.assertEqual(
            client.post(
                "/api/auth/token/refresh/",
                {"refresh": refresh_token},
                format="json",
            ).status_code,
            401,
        )

class ConcurrentRefreshSecurityTests(TransactionTestCase):

    def setUp(self):
        from accounts.models import UserSession

        self.User = get_user_model()
        self.user = self.User.objects.create_user(
            username="concurrenttester",
            email="concurrenttester@example.com",
            password="SecureTestPassword123!",
        )

        # Create an active device session for this test.
        self.session = UserSession.objects.create(
            user=self.user
        )

        # Generate a refresh token associated with the session.
        refresh = RefreshToken.for_user(self.user)
        refresh["token_version"] = self.user.token_version
        refresh["sid"] = str(self.session.id)

        self.refresh_token = str(refresh)

    def refresh_worker(self, barrier):
        # Each thread uses its own database connection.
        close_old_connections()

        try:
            client = APIClient()

            # Synchronize request start times.
            barrier.wait(timeout=10)

            response = client.post(
                "/api/auth/token/refresh/",
                {"refresh": self.refresh_token},
                format="json",
            )

            return response.status_code

        finally:
            close_old_connections()

    def test_concurrent_refresh_allows_only_one_success(self):
        barrier = Barrier(2)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(self.refresh_worker, barrier)
                for _ in range(2)
            ]

            statuses = [
                future.result(timeout=20)
                for future in futures
            ]

        self.assertEqual(
            sorted(statuses),
            [200, 401],
            f"Unexpected concurrent refresh results: {statuses}",
        )

    def test_refresh_racing_with_logout_leaves_session_revoked(self):
        from accounts.models import UserSession

        # Use the valid session and refresh token created in setUp().
        session_id = self.session.id
        refresh_token = self.refresh_token

        barrier = Barrier(2)

        access_token = str(RefreshToken(refresh_token).access_token)

        def worker(endpoint):
            close_old_connections()

            try:
                client = APIClient()

                if endpoint == "/api/auth/logout/":
                    client.credentials(
                        HTTP_AUTHORIZATION=f"Bearer {access_token}"
                    )

                barrier.wait(timeout=30)

                if endpoint == "/api/auth/logout/":
                    return client.post(
                        endpoint,
                        format="json",
                    )

                return client.post(
                    endpoint,
                    {"refresh": refresh_token},
                    format="json",
                )

            except Exception as exc:
                print(
                    "WORKER ERROR:",
                    endpoint,
                    type(exc).__name__,
                    str(exc),
                )
                raise

            finally:
                close_old_connections()


        with ThreadPoolExecutor(max_workers=2) as executor:
            refresh_future = executor.submit(
                worker,
                "/api/auth/token/refresh/",
            )
            logout_future = executor.submit(
                worker,
                "/api/auth/logout/",
            )

            refresh_response = refresh_future.result(timeout=30)
            logout_response = logout_future.result(timeout=30)

        self.assertIn(refresh_response.status_code, [200, 401])
        self.assertEqual(logout_response.status_code, 200)

        # If logout succeeded, the session must be revoked.
        if logout_response.status_code == 200:
            session = UserSession.objects.get(pk=session_id)
            self.assertIsNotNone(session.revoked_at)

            # A newly rotated refresh token must not remain usable.
            if refresh_response.status_code == 200:
                rotated_refresh = refresh_response.data["refresh"]

                response = APIClient().post(
                    "/api/auth/token/refresh/",
                    {"refresh": rotated_refresh},
                    format="json",
                )

                self.assertEqual(response.status_code, 401)

    def test_logout_revokes_tokens_after_refresh_rotation(self):
        from accounts.models import UserSession

        original_refresh = self.refresh_token
        original_access = str(
            RefreshToken(original_refresh).access_token
        )

        # Capture the device session ID before refresh rotation
        # blacklists the original refresh token.
        session_id = RefreshToken(original_refresh)["sid"]

        # Refresh first, simulating rotation immediately
        # before the user requests logout.
        refresh_response = APIClient().post(
            "/api/auth/token/refresh/",
            {"refresh": original_refresh},
            format="json",
        )

        self.assertEqual(refresh_response.status_code, 200)

        rotated_access = refresh_response.data["access"]
        rotated_refresh = refresh_response.data["refresh"]

        # Logout using the original access token, which
        # remains valid even after refresh-token rotation.
        logout_client = APIClient()
        logout_client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {original_access}"
        )

        logout_response = logout_client.post(
            "/api/auth/logout/",
            format="json",
        )

        self.assertEqual(logout_response.status_code, 200)

        session = UserSession.objects.get(pk=session_id)
        self.assertIsNotNone(session.revoked_at)

        # Neither the original nor rotated access token
        # should work after logout.
        for access_token in [
            original_access,
            rotated_access,
        ]:
            client = APIClient()
            client.credentials(
                HTTP_AUTHORIZATION=f"Bearer {access_token}"
            )

            response = client.get("/api/auth/me/")
            self.assertEqual(response.status_code, 401)

        # The newly rotated refresh token must also fail.
        response = APIClient().post(
            "/api/auth/token/refresh/",
            {"refresh": rotated_refresh},
            format="json",
        )
        self.assertEqual(response.status_code, 401)