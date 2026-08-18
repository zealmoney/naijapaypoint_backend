from django.db import models


class GuestTransaction(models.Model):
    SERVICE_TYPES = (
        ("airtime", "Airtime"),
        ("data", "Data"),
        ("electricity", "Electricity"),
        ("cable", "Cable"),
    )

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("processing", "Processing"),
        ("paid", "Paid"),
        ("success", "Successful"),
        ("failed", "Failed"),
        ("refund_pending", "Refund Pending"),
        ("refunded", "Refunded"),
        ("refund_failed", "Refund Failed"),
    ]

    guest_email = models.EmailField()
    guest_phone = models.CharField(max_length=20)

    service_type = models.CharField(max_length=30, choices=SERVICE_TYPES)

    provider = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    recipient = models.CharField(
        max_length=100,
        help_text="Phone number, meter number, or smartcard number",
    )

    variation_code = models.CharField(max_length=100, blank=True)
    plan_name = models.CharField(max_length=255, blank=True)

    customer_name = models.CharField(max_length=255, blank=True)

    reference = models.CharField(max_length=100, unique=True)

    payment_reference = models.CharField(max_length=100, blank=True)
    authorization_url = models.URLField(blank=True)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending",
    )

    provider_reference = models.CharField(max_length=255, blank=True)
    token = models.TextField(blank=True)

    metadata = models.JSONField(default=dict, blank=True)
    provider_response = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    refund_reference = models.CharField(
        max_length=100,
        blank=True,
    )

    refund_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )

    refund_status = models.CharField(
        max_length=30,
        blank=True,
    )

    refund_response = models.JSONField(
        default=dict,
        blank=True,
    )

    refunded_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.service_type} - {self.reference}"