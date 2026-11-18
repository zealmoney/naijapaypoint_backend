from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed
from .models import UserSession
from uuid import UUID


class TokenVersionJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        user = super().get_user(validated_token)

        # Preserve global token revocation.
        token_version = validated_token.get("token_version")

        if (
            token_version is None
            or token_version != user.token_version
        ):
            raise AuthenticationFailed(
                "Token is no longer valid.",
                code="token_not_valid",
            )

        # Every access token must belong to a device session.
        session_id = validated_token.get("sid")

        if not session_id:
            raise AuthenticationFailed(
                "Session identifier is missing.",
                code="token_not_valid",
            )

        # Validate the session UUID before querying the database.
        try:
            session_id = UUID(session_id)
        except (ValueError, TypeError, AttributeError):
            raise AuthenticationFailed(
                "Invalid session identifier.",
                code="token_not_valid",
            )

        # Reject deleted, unknown, or revoked sessions.
        session_is_active = UserSession.objects.filter(
            pk=session_id,
            user=user,
            revoked_at__isnull=True,
        ).exists()

        if not session_is_active:
            raise AuthenticationFailed(
                "Session has expired or been revoked.",
                code="token_not_valid",
            )

        return user
