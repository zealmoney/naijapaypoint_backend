from django.conf import settings
from django.db import models


class ElectricityTransaction(models.Model):
    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("success", "Success"),
        ("failed", "Failed"),
        ("refunded", "Refunded"),
    )

    METER_TYPES = (
        ("prepaid", "Prepaid"),
        ("postpaid", "Postpaid"),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="electricity_transactions"
    )

    provider = models.CharField(max_length=100)

    meter_number = models.CharField(max_length=50)

    meter_type = models.CharField(
        max_length=20,
        choices=METER_TYPES
    )

    customer_name = models.CharField(
        max_length=255,
        blank=True,
        null=True
    )

    amount = models.DecimalField(max_digits=12, decimal_places=2)

    token = models.CharField(
        max_length=255,
        blank=True,
        null=True
    )

    reference = models.CharField(max_length=255, unique=True)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending"
    )

    provider_response = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.provider} - {self.meter_number}"