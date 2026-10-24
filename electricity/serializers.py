from rest_framework import serializers
from .models import ElectricityTransaction

ELECTRICITY_PROVIDER_CHOICES = (
    ("ikeja-electric", "Ikeja Electric"),
    ("eko-electric", "Eko Electric"),
    ("abuja-electric", "Abuja Electric"),
    ("kano-electric", "Kano Electric"),
    ("ibadan-electric", "Ibadan Electric"),
    (
        "portharcourt-electric",
        "Port Harcourt Electric",
    ),
)


class MeterVerificationSerializer(serializers.Serializer):
    provider = serializers.ChoiceField(choices=ELECTRICITY_PROVIDER_CHOICES)
    meter_number = serializers.CharField(max_length=50)
    meter_type = serializers.ChoiceField(
        choices=ElectricityTransaction.METER_TYPES
    )


class ElectricityPurchaseSerializer(serializers.Serializer):
    provider = serializers.ChoiceField(choices=ELECTRICITY_PROVIDER_CHOICES)
    meter_number = serializers.CharField(max_length=50)
    meter_type = serializers.ChoiceField(
        choices=ElectricityTransaction.METER_TYPES
    )
    customer_name = serializers.CharField(max_length=255)
    amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=1000,
    )


class ElectricityTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ElectricityTransaction
        fields = [
            "id",
            "provider",
            "meter_number",
            "meter_type",
            "customer_name",
            "amount",
            "token",
            "reference",
            "status",
            "created_at",
        ]