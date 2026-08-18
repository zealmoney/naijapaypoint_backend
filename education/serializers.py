from rest_framework import serializers
from .models import EducationTransaction


class EducationPlansSerializer(serializers.Serializer):
    provider = serializers.CharField(max_length=100)


class EducationPurchaseSerializer(serializers.Serializer):
    provider = serializers.CharField(max_length=100)
    plan_id = serializers.CharField(max_length=100)
    plan_name = serializers.CharField(max_length=255)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    quantity = serializers.IntegerField(default=1)

    phone_number = serializers.CharField(
        max_length=20,
        required=False,
        allow_blank=True,
    )

    profile_id = serializers.CharField(
        max_length=50,
        required=False,
        allow_blank=True,
    )

    def validate(self, attrs):
        if (
            attrs.get("provider") == "jamb"
            and not attrs.get("profile_id")
        ):
            raise serializers.ValidationError({
                "profile_id":
                    "JAMB Profile ID is required."
            })

        return attrs


class EducationTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = EducationTransaction
        fields = "__all__"