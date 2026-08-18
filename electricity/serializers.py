from rest_framework import serializers
from .models import ElectricityTransaction


class MeterVerificationSerializer(serializers.Serializer):
    provider = serializers.CharField(max_length=100)
    meter_number = serializers.CharField(max_length=50)
    meter_type = serializers.ChoiceField(
        choices=ElectricityTransaction.METER_TYPES
    )


class ElectricityPurchaseSerializer(serializers.Serializer):
    provider = serializers.CharField(max_length=100)
    meter_number = serializers.CharField(max_length=50)
    meter_type = serializers.ChoiceField(
        choices=ElectricityTransaction.METER_TYPES
    )
    customer_name = serializers.CharField(max_length=255)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)


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
            "provider_response",
            "created_at",
        ]