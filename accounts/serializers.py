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
    password = serializers.CharField(write_only=True, min_length=8)
    referral_code = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
    )

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "username",
            "phone_number",
            "password",
            "referral_code",
        ]

    def create(self, validated_data):
        referral_code = validated_data.pop("referral_code", "")

        user = User.objects.create_user(**validated_data)

        if referral_code:
            try:
                referral_profile = ReferralProfile.objects.get(
                    referral_code=referral_code
                )

                if referral_profile.user != user:
                    Referral.objects.create(
                        referrer=referral_profile.user,
                        referred_user=user,
                        referral_code=referral_code,
                    )

                    referral_profile.total_referrals += 1
                    referral_profile.save(update_fields=["total_referrals"])

            except ReferralProfile.DoesNotExist:
                pass

        return user

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "username",
            "phone_number",
            "is_verified",
            "is_staff",
            "is_superuser",
        ]

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