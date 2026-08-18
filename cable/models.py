from django.conf import settings
from django.db import models


class CableTransaction(models.Model):
    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("success", "Success"),
        ("failed", "Failed"),
        ("refunded", "Refunded"),
    )

    PROVIDER_CHOICES = (
        ("dstv", "DStv"),
        ("gotv", "GOtv"),
        ("startimes", "Startimes"),
        ("showmax", "Showmax"),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="cable_transactions"
    )

    provider = models.CharField(max_length=30, choices=PROVIDER_CHOICES)
    smartcard_number = models.CharField(max_length=50)

    plan_id = models.CharField(max_length=100)
    plan_name = models.CharField(max_length=255)

    customer_name = models.CharField(max_length=255, blank=True, null=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    reference = models.CharField(max_length=255, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")

    provider_response = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.provider} - {self.smartcard_number} - {self.plan_name}"