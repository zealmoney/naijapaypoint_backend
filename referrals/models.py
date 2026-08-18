import uuid
from django.conf import settings
from django.db import models


def generate_referral_code():
    return f"NPP-{uuid.uuid4().hex[:8].upper()}"


class ReferralProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="referral_profile",
    )

    referral_code = models.CharField(
        max_length=20,
        unique=True,
        default=generate_referral_code,
    )

    total_referrals = models.PositiveIntegerField(default=0)
    total_bonus_earned = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.email} - {self.referral_code}"


class Referral(models.Model):
    referrer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="referrals_made",
    )

    referred_user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="referral_record",
    )

    referral_code = models.CharField(max_length=20)

    bonus_paid = models.BooleanField(default=False)
    bonus_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.referrer.email} referred {self.referred_user.email}"