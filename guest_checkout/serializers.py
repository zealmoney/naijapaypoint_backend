from rest_framework import serializers
from .models import GuestTransaction


class GuestTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = GuestTransaction
        fields = "__all__"
        read_only_fields = (
            "reference",
            "payment_reference",
            "authorization_url",
            "status",
            "provider_reference",
            "provider_response",
            "token",
            "created_at",
            "updated_at",
        )


class GuestPaymentInitializeSerializer(serializers.Serializer):
    guest_email = serializers.EmailField()
    guest_phone = serializers.CharField(max_length=20)

    service_type = serializers.ChoiceField(
        choices=[
            "airtime",
            "data",
            "electricity",
            "cable",
        ]
    )

    provider = serializers.CharField(max_length=100)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)

    recipient = serializers.CharField(max_length=100)

    variation_code = serializers.CharField(
        required=False,
        allow_blank=True,
    )

    plan_name = serializers.CharField(
        required=False,
        allow_blank=True,
    )

    customer_name = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=255,
    )