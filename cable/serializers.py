from rest_framework import serializers
from .models import CableTransaction


class CableVerifySerializer(serializers.Serializer):
    provider = serializers.ChoiceField(choices=CableTransaction.PROVIDER_CHOICES)
    smartcard_number = serializers.CharField(max_length=50)


class CablePlansSerializer(serializers.Serializer):
    provider = serializers.ChoiceField(choices=CableTransaction.PROVIDER_CHOICES)


class CablePurchaseSerializer(serializers.Serializer):
    provider = serializers.ChoiceField(
        choices=CableTransaction.PROVIDER_CHOICES
    )
    smartcard_number = serializers.CharField(
        max_length=50
    )
    plan_id = serializers.CharField(
        max_length=100
    )
    customer_name = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
    )

class CableTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CableTransaction
        fields = [
            "id",
            "provider",
            "smartcard_number",
            "plan_id",
            "plan_name",
            "customer_name",
            "amount",
            "reference",
            "status",
            "created_at",
        ]