from django.conf import settings
from django.db import models


class DataTransaction(models.Model):
    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("success", "Success"),
        ("failed", "Failed"),
        ("refunded", "Refunded"),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="data_transactions"
    )

    network = models.CharField(max_length=20)
    phone_number = models.CharField(max_length=20)

    plan_id = models.CharField(max_length=100)
    plan_name = models.CharField(max_length=255)

    amount = models.DecimalField(max_digits=12, decimal_places=2)

    reference = models.CharField(max_length=255, unique=True)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending"
    )

    provider = models.CharField(max_length=50, default="vtpass")

    provider_response = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.network} - {self.phone_number} - {self.plan_name}"