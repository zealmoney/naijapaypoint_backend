from rest_framework import serializers
from .models import PaymentTransaction


class InitializePaymentSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=100)


class PaymentTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentTransaction
        fields = [
            "id",
            "amount",
            "reference",
            "authorization_url",
            "status",
            "provider",
            "created_at",
            "verified_at",
        ]