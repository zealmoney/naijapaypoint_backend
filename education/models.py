from django.conf import settings
from django.db import models


class EducationTransaction(models.Model):
    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("success", "Success"),
        ("failed", "Failed"),
        ("refunded", "Refunded"),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="education_transactions",
    )

    provider = models.CharField(max_length=100)
    plan_id = models.CharField(max_length=100)
    plan_name = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    quantity = models.PositiveIntegerField(default=1)
    phone_number = models.CharField(max_length=20, blank=True, null=True)

    pin = models.TextField(blank=True, null=True)
    reference = models.CharField(max_length=255, unique=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    provider_response = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.provider} - {self.plan_name} - {self.status}"