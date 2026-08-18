from __future__ import annotations

from pathlib import Path

from rest_framework import serializers

from .models import KYCVerification
from .services import KYCService


MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MB

ALLOWED_IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
}

ALLOWED_IMAGE_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
}


def validate_kyc_image(uploaded_file):
    if not uploaded_file:
        return uploaded_file

    if uploaded_file.size > MAX_IMAGE_SIZE:
        raise serializers.ValidationError(
            "Each image must be 5 MB or smaller."
        )

    extension = Path(uploaded_file.name).suffix.lower()

    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise serializers.ValidationError(
            "Only JPG, JPEG, PNG, and WebP images are allowed."
        )

    content_type = getattr(
        uploaded_file,
        "content_type",
        None,
    )

    if (
        content_type
        and content_type not in ALLOWED_IMAGE_CONTENT_TYPES
    ):
        raise serializers.ValidationError(
            "The uploaded file is not a supported image type."
        )

    return uploaded_file


class KYCVerificationSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )

    verification_level_display = serializers.CharField(
        source="get_verification_level_display",
        read_only=True,
    )

    document_type_display = serializers.CharField(
        source="get_document_type_display",
        read_only=True,
    )

    masked_identity_verification_value = (
        serializers.SerializerMethodField()
    )

    requires_document_back = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()
    can_submit = serializers.SerializerMethodField()
    missing_submission_fields = serializers.SerializerMethodField()

    reviewed_by = serializers.SerializerMethodField()

    class Meta:
        model = KYCVerification
        fields = (
            "id",
            "verification_level",
            "verification_level_display",
            "status",
            "status_display",
            "first_name",
            "middle_name",
            "last_name",
            "date_of_birth",
            "nationality",
            "residential_address",
            "document_type",
            "document_type_display",
            "document_number",
            "document_front",
            "document_back",
            "selfie",
            "requires_document_back",
            "can_edit",
            "can_submit",
            "missing_submission_fields",
            "submitted_at",
            "reviewed_by",
            "reviewed_at",
            "review_note",
            "rejection_reason",
            "created_at",
            "updated_at",
            "identity_verification_method",
            "masked_identity_verification_value",
        )

        read_only_fields = fields

    def get_requires_document_back(
        self,
        obj: KYCVerification,
    ) -> bool:
        return (
            obj.document_type
            in KYCService.DOCUMENTS_REQUIRING_BACK
        )

    def get_can_edit(
        self,
        obj: KYCVerification,
    ) -> bool:
        return obj.status in KYCService.EDITABLE_STATUSES

    def get_can_submit(
        self,
        obj: KYCVerification,
    ) -> bool:
        return obj.status in KYCService.SUBMITTABLE_STATUSES

    def get_missing_submission_fields(
        self,
        obj: KYCVerification,
    ) -> list[str]:
        return list(
            KYCService.get_missing_submission_fields(obj).keys()
        )

    def get_reviewed_by(
        self,
        obj: KYCVerification,
    ):
        reviewer = obj.reviewed_by

        if not reviewer:
            return None

        return {
            "id": reviewer.pk,
            "email": getattr(reviewer, "email", ""),
            "name": reviewer.get_full_name(),
        }

    def get_masked_identity_verification_value(
        self,
        obj: KYCVerification,
    ) -> str:
        value = obj.identity_verification_value or ""

        if not value:
            return ""

        visible_characters = 4

        if len(value) <= visible_characters:
            return "*" * len(value)

        return (
            "*" * (len(value) - visible_characters)
            + value[-visible_characters:]
        )


class KYCUpdateSerializer(serializers.ModelSerializer):
    document_front = serializers.ImageField(
        required=False,
        allow_null=True,
        validators=[validate_kyc_image],
    )

    document_back = serializers.ImageField(
        required=False,
        allow_null=True,
        validators=[validate_kyc_image],
    )

    selfie = serializers.ImageField(
        required=False,
        allow_null=True,
        validators=[validate_kyc_image],
    )

    class Meta:
        model = KYCVerification
        fields = (
            "first_name",
            "middle_name",
            "last_name",
            "date_of_birth",
            "nationality",
            "residential_address",
            "document_type",
            "document_number",
            "identity_verification_method",
            "identity_verification_value",
            "document_front",
            "document_back",
            "selfie",
        )

        extra_kwargs = {
            "first_name": {
                "required": False,
                "allow_blank": True,
            },
            "middle_name": {
                "required": False,
                "allow_blank": True,
            },
            "last_name": {
                "required": False,
                "allow_blank": True,
            },
            "date_of_birth": {
                "required": False,
                "allow_null": True,
            },
            "nationality": {
                "required": False,
                "allow_blank": True,
            },
            "residential_address": {
                "required": False,
                "allow_blank": True,
            },
            "document_type": {
                "required": False,
                "allow_blank": True,
            },
            "document_number": {
                "required": False,
                "allow_blank": True,
            },
            "identity_verification_method": {
                "required": False,
                "allow_blank": True,
            },
            "identity_verification_value": {
                "required": False,
                "allow_blank": True,
                "write_only": True,
            },
        }

    def validate(self, attrs):
        instance = self.instance

        if instance:
            KYCService.ensure_editable(instance)

        document_type = attrs.get(
            "document_type",
            getattr(instance, "document_type", ""),
        )

        document_back = attrs.get(
            "document_back",
            getattr(instance, "document_back", None),
        )

        # Do not require the back while saving a draft. The requirement
        # is enforced when the user submits the application.
        attrs["_requires_document_back"] = (
            document_type
            in KYCService.DOCUMENTS_REQUIRING_BACK
            and not document_back
        )

        return attrs

    def update(self, instance, validated_data):
        validated_data.pop(
            "_requires_document_back",
            None,
        )

        # Editing a rejected application moves it back into draft mode.
        if instance.status in {
            KYCVerification.Status.NOT_STARTED,
            KYCVerification.Status.REJECTED,
        }:
            instance.status = KYCVerification.Status.DRAFT

        for field_name, value in validated_data.items():
            setattr(instance, field_name, value)

        instance.save()

        return instance


class KYCStartSerializer(serializers.Serializer):
    """
    Start currently requires no request fields.
    """

    pass


class KYCSubmitSerializer(serializers.Serializer):
    """
    Submission currently requires no request fields.
    """

    pass

class AdminKYCListSerializer(serializers.ModelSerializer):
    customer_email = serializers.EmailField(
        source="user.email",
        read_only=True,
    )

    customer_name = serializers.SerializerMethodField()

    status_display = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )

    document_type_display = serializers.CharField(
        source="get_document_type_display",
        read_only=True,
    )

    class Meta:
        model = KYCVerification
        fields = (
            "id",
            "customer_email",
            "customer_name",
            "status",
            "status_display",
            "verification_level",
            "document_type",
            "document_type_display",
            "submitted_at",
            "reviewed_at",
            "created_at",
            "updated_at",
        )

    def get_customer_name(self, obj):
        full_name = f"{obj.first_name} {obj.last_name}".strip()

        if full_name:
            return full_name

        return obj.user.get_full_name() or obj.user.email

class AdminKYCDetailSerializer(KYCVerificationSerializer):
    customer = serializers.SerializerMethodField()
    automated_verification_summary = (
        serializers.SerializerMethodField()
    )
    masked_identity_verification_value = (
        serializers.SerializerMethodField()
    )

    class Meta(KYCVerificationSerializer.Meta):
        fields = KYCVerificationSerializer.Meta.fields + (
            "customer",
            "metadata",
            "verification_provider",
            "provider_reference",
            "automated_verification_status",
            "identity_match_passed",
            "document_authentic",
            "face_match_passed",
            "liveness_passed",
            "face_match_score",
            "automated_verified_at",
            "automated_verification_error",
            "automated_verification_summary",
            "masked_identity_verification_value",
        )

        read_only_fields = fields

    def get_customer(self, obj):
        return {
            "id": obj.user_id,
            "email": obj.user.email,
            "name": obj.user.get_full_name(),
        }

    def get_automated_verification_summary(self, obj):
        provider_response = obj.provider_response or {}
        entity = provider_response.get("entity") or {}

        return {
            "verification": entity.get("verification"),
            "first_name": entity.get("first_name"),
            "middle_name": entity.get("middle_name"),
            "last_name": entity.get("last_name"),
            "date_of_birth": (
                entity.get("date_of_birth")
                or entity.get("dob")
            ),
            "gender": entity.get("gender"),
            "phone_number": (
                entity.get("phone_number")
                or entity.get("phone")
            ),
            "identity_number": (
                entity.get("identity_number")
                or entity.get("bvn")
                or entity.get("nin")
            ),
        }

class KYCApproveSerializer(serializers.Serializer):
    review_note = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=2000,
    )


class KYCRejectSerializer(serializers.Serializer):
    rejection_reason = serializers.CharField(
        required=True,
        allow_blank=False,
        max_length=2000,
    )

    review_note = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=2000,
    )