from rest_framework import serializers
from .models import Transaction


class TransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        fields = [
            "id",
            "service_type",
            "amount",
            "reference",
            "status",
            "provider",
            "provider_reference",
            "description",
            "metadata",
            "created_at",
            "updated_at",
        ]


class TransactionReceiptSerializer(serializers.ModelSerializer):
    receipt_title = serializers.SerializerMethodField()
    receipt_status = serializers.CharField(source="status")
    customer_details = serializers.SerializerMethodField()

    class Meta:
        model = Transaction
        fields = [
            "receipt_title",
            "receipt_status",
            "reference",
            "service_type",
            "amount",
            "provider",
            "provider_reference",
            "description",
            "customer_details",
            "metadata",
            "created_at",
            "updated_at",
        ]

    def get_receipt_title(self, obj):
        return f"{obj.service_type.replace('_', ' ').title()} Receipt"

    def get_customer_details(self, obj):
        metadata = obj.metadata or {}

        return {
            "phone_number": metadata.get("phone_number"),
            "meter_number": metadata.get("meter_number"),
            "smartcard_number": metadata.get("smartcard_number"),
            "customer_name": metadata.get("customer_name"),
            "network": metadata.get("network"),
            "provider": metadata.get("provider"),
            "plan_name": metadata.get("plan_name"),
            "token": metadata.get("token"),
        }