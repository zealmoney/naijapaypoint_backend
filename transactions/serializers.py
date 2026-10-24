from rest_framework import serializers

from .models import Transaction


SAFE_METADATA_FIELDS = {
    "phone_number",
    "meter_number",
    "meter_type",
    "smartcard_number",
    "customer_name",
    "network",
    "provider",
    "plan_id",
    "plan_name",
    "token",
    "pin",
    "quantity",
    "requires_requery",
    "requires_manual_review",
    "requery_attempts",
    "last_requery_at",
    "reconciled",
    "reconciled_at",
    "reconciliation_result",
    "refund_reference",
}


def get_safe_transaction_metadata(metadata):
    if not isinstance(metadata, dict):
        return {}

    return {
        key: metadata[key]
        for key in SAFE_METADATA_FIELDS
        if key in metadata
    }


class TransactionSerializer(serializers.ModelSerializer):
    metadata = serializers.SerializerMethodField()

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

    def get_metadata(self, obj):
        return get_safe_transaction_metadata(
            obj.metadata
        )


class TransactionReceiptSerializer(
    serializers.ModelSerializer
):
    receipt_title = serializers.SerializerMethodField()
    receipt_status = serializers.CharField(
        source="status"
    )
    customer_details = serializers.SerializerMethodField()
    metadata = serializers.SerializerMethodField()

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
        return (
            f"{obj.service_type.replace('_', ' ').title()} "
            "Receipt"
        )

    def get_customer_details(self, obj):
        metadata = get_safe_transaction_metadata(
            obj.metadata
        )

        return {
            "phone_number":
                metadata.get("phone_number"),
            "meter_number":
                metadata.get("meter_number"),
            "smartcard_number":
                metadata.get("smartcard_number"),
            "customer_name":
                metadata.get("customer_name"),
            "network":
                metadata.get("network"),
            "provider":
                metadata.get("provider"),
            "plan_name":
                metadata.get("plan_name"),
            "token":
                metadata.get("token"),
        }

    def get_metadata(self, obj):
        return get_safe_transaction_metadata(
            obj.metadata
        )