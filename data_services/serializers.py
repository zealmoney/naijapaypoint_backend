from rest_framework import serializers
from .models import DataTransaction

DATA_NETWORK_CHOICES = (
    ("mtn-data", "MTN"),
    ("airtel-data", "Airtel"),
    ("glo-data", "Glo"),
    ("etisalat-data", "9mobile"),
)


class DataPurchaseSerializer(serializers.Serializer):
    network = serializers.ChoiceField(
        choices=DATA_NETWORK_CHOICES
    )
    phone_number = serializers.CharField(
        max_length=20
    )
    plan_id = serializers.CharField(
        max_length=100
    )

class DataPlansSerializer(serializers.Serializer):
    network = serializers.ChoiceField(choices=DATA_NETWORK_CHOICES)


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
            "created_at",
        ]