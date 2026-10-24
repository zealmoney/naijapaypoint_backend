from rest_framework import serializers
from .models import EducationTransaction

EDUCATION_PROVIDER_CHOICES = (
    ("waec", "WAEC Result Checker"),
    ("waec-registration", "WAEC Registration"),
    ("neco", "NECO Token"),
    ("jamb", "JAMB"),
)

class EducationPlansSerializer(serializers.Serializer):
    provider = serializers.ChoiceField(
        choices=EDUCATION_PROVIDER_CHOICES
    )


class EducationPurchaseSerializer(serializers.Serializer):
    provider = serializers.ChoiceField(choices=EDUCATION_PROVIDER_CHOICES)
    plan_id = serializers.CharField(max_length=100)
    quantity = serializers.IntegerField(default=1, min_value=1, max_value=10)

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

        if (
            attrs.get("provider") == "jamb"
            and attrs.get("quantity", 1) != 1
        ):
            raise serializers.ValidationError({
                "quantity":
                    "JAMB purchases must have "
                    "a quantity of 1."
            })

        return attrs


class EducationTransactionSerializer(
    serializers.ModelSerializer
):
    class Meta:
        model = EducationTransaction
        fields = [
            "id",
            "provider",
            "plan_id",
            "plan_name",
            "amount",
            "quantity",
            "phone_number",
            "pin",
            "reference",
            "status",
            "created_at",
        ]