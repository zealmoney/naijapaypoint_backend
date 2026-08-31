from rest_framework import serializers
from .models import User
from referrals.models import ReferralProfile, Referral

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.core.mail import send_mail
from django.conf import settings


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

        return attrs

    def create(self, validated_data):
        referral_code = validated_data.pop(
            "referral_code",
            "",
        )

        validated_data.pop(
            "password_confirm"
        )

        user = User.objects.create_user(
            **validated_data
        )

        if referral_code:
            referral_profile = (
                ReferralProfile.objects.get(
                    referral_code=referral_code
                )
            )

            Referral.objects.create(
                referrer=referral_profile.user,
                referred_user=user,
                referral_code=referral_code,
            )

            referral_profile.total_referrals += 1
            referral_profile.save(
                update_fields=[
                    "total_referrals"
                ]
            )

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
        phone_number = value.strip()

        if not phone_number:
            raise serializers.ValidationError(
                "Phone number is required."
            )

        cleaned_number = (
            phone_number
            .replace(" ", "")
            .replace("-", "")
            .replace("(", "")
            .replace(")", "")
        )

        if cleaned_number.startswith("+"):
            digits = cleaned_number[1:]
        else:
            digits = cleaned_number

        if not digits.isdigit():
            raise serializers.ValidationError(
                "Enter a valid phone number."
            )

        if len(digits) < 10 or len(digits) > 15:
            raise serializers.ValidationError(
                "Enter a valid phone number."
            )

        return cleaned_number

User = get_user_model()

class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def save(self):
        email = self.validated_data["email"]

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return

        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)

        reset_link = f"{settings.FRONTEND_URL}/reset-password/{uid}/{token}"

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

        attrs["user"] = user
        return attrs

    def save(self):
        user = self.validated_data["user"]
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])