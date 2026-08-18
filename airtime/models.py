from django.conf import settings
from django.db import models


class AirtimeTransaction(models.Model):
    NETWORK_CHOICES = (
        ("mtn", "MTN"),
        ("airtel", "Airtel"),
        ("glo", "Glo"),
        ("9mobile", "9mobile"),
        ("etisalat", "9mobile / Etisalat"),
    )

    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("success", "Success"),
        ("failed", "Failed"),
        ("refunded", "Refunded"),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="airtime_transactions"
    )
    network = models.CharField(max_length=20, choices=NETWORK_CHOICES)
    phone_number = models.CharField(max_length=20)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reference = models.CharField(max_length=255, unique=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")

    provider = models.CharField(max_length=50, default="vtpass")
    provider_response = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.network} - {self.phone_number} - {self.amount}"