from rest_framework import serializers
from .models import User
from referrals.models import ReferralProfile, Referral

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.db import IntegrityError, transaction
from django.db.models import F

from rest_framework_simplejwt.token_blacklist.models import (
    OutstandingToken,
    BlacklistedToken,
)
from .utils import (
    normalize_nigerian_phone,
    PhoneNormalizationError,
)

from django.contrib.auth import get_user_model
from rest_framework_simplejwt.serializers import (
    TokenObtainPairSerializer,
    TokenRefreshSerializer,
)
from rest_framework_simplejwt.exceptions import InvalidToken


def blacklist_user_tokens(user):
    type(user).objects.filter(pk=user.pk).update(
        token_version=F("token_version") + 1
    )

    user.refresh_from_db(fields=["token_version"])

    for token in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(
            token=token
        )


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        min_length=8,
    )

    password_confirm = serializers.CharField(
        write_only=True,
        min_length=8,
    )

    referral_code = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
    )

    class Meta:
        model = User
        fields = [
            "id",
            "first_name",
            "last_name",
            "username",
            "email",
            "phone_number",
            "password",
            "password_confirm",
            "referral_code",
        ]
        
    def validate_referral_code(self, value):
        code = value.strip().upper()

        if not code:
            return ""

        if not ReferralProfile.objects.filter(
            referral_code=code
        ).exists():
            raise serializers.ValidationError(
                "Invalid referral code."
            )

        return code

    def validate(self, attrs):
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError(
                {
                    "password_confirm":
                        "Passwords do not match."
                }
            )

        candidate_user = User(
            username=attrs.get("username", ""),
            email=attrs.get("email", ""),
            first_name=attrs.get("first_name", ""),
            last_name=attrs.get("last_name", ""),
        )

        validate_password(
            attrs["password"],
            user=candidate_user,
        )

        return attrs

    def create(self, validated_data):
        referral_code = validated_data.pop(
            "referral_code",
            "",
        )

        validated_data.pop(
            "password_confirm"
        )

        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    **validated_data
                )

                if referral_code:
                    referral_profile = (
                        ReferralProfile.objects.select_for_update().get(
                            referral_code=referral_code
                        )
                    )

                    Referral.objects.create(
                        referrer=referral_profile.user,
                        referred_user=user,
                        referral_code=referral_code,
                    )

                    ReferralProfile.objects.filter(
                        pk=referral_profile.pk
                    ).update(
                        total_referrals=F("total_referrals") + 1
                    )

        except IntegrityError as exc:
            raise serializers.ValidationError(
                {
                    "detail": (
                        "An account with this username, "
                        "email, or phone number already exists."
                    )
                }
            ) from exc

        return user

    def validate_username(self, value):
        username = value.strip().lower()

        if User.objects.filter(
            username__iexact=username
        ).exists():
            raise serializers.ValidationError(
                "This username is already taken."
            )

        return username

    def validate_email(self, value):
        email = value.strip().lower()

        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError(
                "An account with this email already exists."
            )

        return email

    def validate_phone_number(self, value):
        try:
            phone_number = normalize_nigerian_phone(value)
        except PhoneNormalizationError as exc:
            raise serializers.ValidationError(str(exc))

        if User.objects.filter(
            phone_number=phone_number
        ).exists():
            raise serializers.ValidationError(
                "An account with this phone number already exists."
            )

        return phone_number

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["token_version"] = user.token_version
        return token

class CustomTokenRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        refresh = self.token_class(attrs["refresh"])

        user_id = refresh.get("user_id")
        token_version = refresh.get("token_version")

        User = get_user_model()

        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            raise InvalidToken("Token is no longer valid.")

        if (
            token_version is None
            or token_version != user.token_version
        ):
            raise InvalidToken("Token is no longer valid.")

        return super().validate(attrs)

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "id",
            "first_name",
            "last_name",
            "username",
            "email",
            "phone_number",
            "is_verified",
            "is_staff",
            "is_superuser",
        ]
        read_only_fields = [
            "id",
            "email",
            "is_verified",
            "is_staff",
            "is_superuser",
        ]

    def validate_first_name(self, value):
        first_name = value.strip()

        if not first_name:
            raise serializers.ValidationError(
                "First name is required."
            )

        return first_name

    def validate_last_name(self, value):
        last_name = value.strip()

        if not last_name:
            raise serializers.ValidationError(
                "Last name is required."
            )

        return last_name

    def validate_username(self, value):
        username = value.strip().lower()

        if not username:
            raise serializers.ValidationError(
                "Username is required."
            )

        queryset = User.objects.filter(
            username__iexact=username
        )

        if self.instance:
            queryset = queryset.exclude(
                pk=self.instance.pk
            )

        if queryset.exists():
            raise serializers.ValidationError(
                "This username is already taken."
            )

        return username

    def validate_phone_number(self, value):
        try:
            phone_number = normalize_nigerian_phone(value)
        except PhoneNormalizationError as exc:
            raise serializers.ValidationError(str(exc))

        queryset = User.objects.filter(
            phone_number=phone_number
        )

        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise serializers.ValidationError(
                "An account with this phone number already exists."
            )

        return phone_number

User = get_user_model()

class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        return value.strip().lower()

    def save(self):
        email = self.validated_data["email"]

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return

        uid = urlsafe_base64_encode(
            force_bytes(user.pk)
        )

        token = default_token_generator.make_token(
            user
        )

        reset_link = (
            f"{settings.FRONTEND_URL}"
            f"/reset-password/{uid}/{token}"
        )

        send_mail(
            subject="Reset your NaijaPayPoint password",
            message=f"""
Hello,

You requested a password reset for your NaijaPayPoint account.

Click the link below to reset your password:

{reset_link}

If you did not request this, you can ignore this email.
            """,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=True,
        )


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True, min_length=8)

    def validate(self, attrs):
        from django.utils.http import urlsafe_base64_decode
        from django.utils.encoding import force_str

        try:
            uid = force_str(urlsafe_base64_decode(attrs["uid"]))
            user = User.objects.get(pk=uid)
        except Exception:
            raise serializers.ValidationError("Invalid password reset link.")

        if not default_token_generator.check_token(user, attrs["token"]):
            raise serializers.ValidationError("Invalid or expired password reset link.")
        validate_password(
            attrs["new_password"],
            user=user,
        )
        attrs["user"] = user
        return attrs

    def save(self):
        user = self.validated_data["user"]

        user.set_password(
            self.validated_data["new_password"]
        )
        user.save(
            update_fields=["password"]
        )

        blacklist_user_tokens(user)

        return user


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(
        write_only=True,
    )
    new_password = serializers.CharField(
        write_only=True,
        min_length=8,
    )
    new_password_confirm = serializers.CharField(
        write_only=True,
        min_length=8,
    )

    def validate_current_password(self, value):
        user = self.context["request"].user

        if not user.check_password(value):
            raise serializers.ValidationError(
                "Current password is incorrect."
            )

        return value

    def validate(self, attrs):
        if attrs["new_password"] != attrs["new_password_confirm"]:
            raise serializers.ValidationError(
                {
                    "new_password_confirm":
                        "Passwords do not match."
                }
            )

        user = self.context["request"].user

        validate_password(
            attrs["new_password"],
            user=user,
        )

        if user.check_password(attrs["new_password"]):
            raise serializers.ValidationError(
                {
                    "new_password":
                        "New password must be different from your current password."
                }
            )

        return attrs

    def save(self):
        user = self.context["request"].user

        user.set_password(
            self.validated_data["new_password"]
        )
        user.save(
            update_fields=["password"]
        )

        blacklist_user_tokens(user)

        return user
