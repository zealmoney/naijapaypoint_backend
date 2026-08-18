from rest_framework import serializers
from .models import CableTransaction


class CableVerifySerializer(serializers.Serializer):
    provider = serializers.ChoiceField(choices=CableTransaction.PROVIDER_CHOICES)
    smartcard_number = serializers.CharField(max_length=50)


class CablePlansSerializer(serializers.Serializer):
    provider = serializers.ChoiceField(choices=CableTransaction.PROVIDER_CHOICES)


class CablePurchaseSerializer(serializers.Serializer):
    provider = serializers.ChoiceField(choices=CableTransaction.PROVIDER_CHOICES)
    smartcard_number = serializers.CharField(max_length=50)
    plan_id = serializers.CharField(max_length=100)
    plan_name = serializers.CharField(max_length=255)
    customer_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)


class CableTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CableTransaction
        fields = "__all__"