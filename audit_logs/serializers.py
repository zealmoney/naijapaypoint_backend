from rest_framework import serializers
from .models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    admin_email = serializers.EmailField(source="admin_user.email", read_only=True)

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "admin_email",
            "action_type",
            "target_user_email",
            "target_reference",
            "note",
            "metadata",
            "created_at",
        ]