from rest_framework import serializers
from .models import CustomerNote


class CustomerNoteSerializer(serializers.ModelSerializer):
    staff_email = serializers.EmailField(source="staff_user.email", read_only=True)

    class Meta:
        model = CustomerNote
        fields = [
            "id",
            "customer",
            "staff_email",
            "note",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["customer", "staff_user"]