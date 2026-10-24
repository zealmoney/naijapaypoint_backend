from decimal import Decimal

from rest_framework import serializers

from airtime.models import AirtimeTransaction
from cable.models import CableTransaction
from data_services.serializers import DATA_NETWORK_CHOICES
from electricity.models import ElectricityTransaction
from electricity.serializers import (
    ELECTRICITY_PROVIDER_CHOICES,
)

from .models import GuestTransaction


AIRTIME_PROVIDERS = {
    value
    for value, _label
    in AirtimeTransaction.NETWORK_CHOICES
}

DATA_PROVIDERS = {
    value
    for value, _label
    in DATA_NETWORK_CHOICES
}

CABLE_PROVIDERS = {
    value
    for value, _label
    in CableTransaction.PROVIDER_CHOICES
}

ELECTRICITY_PROVIDERS = {
    value
    for value, _label
    in ELECTRICITY_PROVIDER_CHOICES
}

ELECTRICITY_METER_TYPES = {
    value
    for value, _label
    in ElectricityTransaction.METER_TYPES
}


class GuestTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = GuestTransaction
        fields = (
            "guest_email",
            "guest_phone",
            "service_type",
            "provider",
            "amount",
            "recipient",
            "variation_code",
            "plan_name",
            "customer_name",
            "reference",
            "payment_reference",
            "authorization_url",
            "status",
            "provider_reference",
            "token",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


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

    def validate(self, attrs):
        service_type = attrs["service_type"]
        provider = attrs["provider"]
        amount = attrs["amount"]
        variation_code = (
            attrs.get("variation_code") or ""
        ).strip()

        provider_choices = {
            "airtime": AIRTIME_PROVIDERS,
            "data": DATA_PROVIDERS,
            "cable": CABLE_PROVIDERS,
            "electricity": ELECTRICITY_PROVIDERS,
        }

        if provider not in provider_choices[service_type]:
            raise serializers.ValidationError(
                {
                    "provider":
                        "Invalid provider for the "
                        "selected service."
                }
            )

        if amount <= Decimal("0"):
            raise serializers.ValidationError(
                {
                    "amount":
                        "Amount must be greater than zero."
                }
            )

        if service_type in {"data", "cable"}:
            if not variation_code:
                raise serializers.ValidationError(
                    {
                        "variation_code":
                            "A plan is required for this "
                            "service."
                    }
                )

        if service_type == "electricity":
            if variation_code not in (
                ELECTRICITY_METER_TYPES
            ):
                raise serializers.ValidationError(
                    {
                        "variation_code":
                            "Invalid meter type."
                    }
                )

            if amount < Decimal("1000"):
                raise serializers.ValidationError(
                    {
                        "amount":
                            "Electricity purchases require "
                            "a minimum amount of 1000."
                    }
                )

        return attrs