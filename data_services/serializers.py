from rest_framework import serializers
from .models import DataTransaction


class DataPurchaseSerializer(serializers.Serializer):
    network = serializers.CharField(max_length=20)
    phone_number = serializers.CharField(max_length=20)
    plan_id = serializers.CharField(max_length=100)
    plan_name = serializers.CharField(max_length=255)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)


class DataTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = DataTransaction
        fields = [
            "id",
            "network",
            "phone_number",
            "plan_id",
            "plan_name",
            "amount",
            "reference",
            "status",
            "provider",
            "provider_response",
            "created_at",
        ]