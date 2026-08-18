from rest_framework import serializers
from .models import AirtimeTransaction


class AirtimePurchaseSerializer(serializers.Serializer):
    network = serializers.ChoiceField(choices=AirtimeTransaction.NETWORK_CHOICES)
    phone_number = serializers.CharField(max_length=20)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=50)


class AirtimeTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AirtimeTransaction
        fields = [
            "id",
            "network",
            "phone_number",
            "amount",
            "reference",
            "status",
            "provider",
            "provider_response",
            "created_at",
        ]