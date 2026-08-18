from rest_framework import serializers

from .models import ReferralProfile, Referral


class ReferralProfileSerializer(serializers.ModelSerializer):
    referral_link = serializers.SerializerMethodField()

    class Meta:
        model = ReferralProfile
        fields = [
            "referral_code",
            "total_referrals",
            "total_bonus_earned",
            "referral_link",
        ]

    def get_referral_link(self, obj):
        return f"https://naijapaypoint.com/register?ref={obj.referral_code}"


class ReferralSerializer(serializers.ModelSerializer):
    referred_email = serializers.EmailField(
        source="referred_user.email",
        read_only=True,
    )

    class Meta:
        model = Referral
        fields = [
            "id",
            "referred_email",
            "bonus_paid",
            "bonus_amount",
            "created_at",
        ]