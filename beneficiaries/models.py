from django.db import models
from django.conf import settings


class Beneficiary(models.Model):
    BENEFICIARY_TYPES = (
        ("airtime", "Airtime"),
        ("data", "Data"),
        ("electricity", "Electricity"),
        ("cable", "Cable"),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="beneficiaries",
    )

    beneficiary_type = models.CharField(
        max_length=20,
        choices=BENEFICIARY_TYPES,
    )

    nickname = models.CharField(max_length=100)

    identifier = models.CharField(
        max_length=100,
        help_text="Phone number, meter number or smartcard number",
    )

    provider = models.CharField(
        max_length=100,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.nickname} ({self.beneficiary_type})"