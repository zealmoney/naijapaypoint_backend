from __future__ import annotations

from pathlib import Path

from rest_framework import serializers
from rest_framework.reverse import reverse

from .models import KYCVerification
from .services import KYCService
from PIL import Image


MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MB
MAX_IMAGE_PIXELS = 25_000_000  # 25 megapixels

ALLOWED_IMAGE_TYPES = {
    "JPEG": {
        "extensions": {".jpg", ".jpeg"},
        "content_types": {"image/jpeg"},
    },
    "PNG": {
        "extensions": {".png"},
        "content_types": {"image/png"},
    },
    "WEBP": {
        "extensions": {".webp"},
        "content_types": {"image/webp"},
    },
}

ALLOWED_IMAGE_EXTENSIONS = {
    extension
    for image_type in ALLOWED_IMAGE_TYPES.values()
    for extension in image_type["extensions"]
}

ALLOWED_IMAGE_CONTENT_TYPES = {
    content_type
    for image_type in ALLOWED_IMAGE_TYPES.values()
    for content_type in image_type["content_types"]
}


def validate_kyc_image(uploaded_file):
    if not uploaded_file:
        return uploaded_file

    if uploaded_file.size > MAX_IMAGE_SIZE:
        raise serializers.ValidationError(
            "Each image must be 5 MB or smaller."
        )

    extension = Path(
        uploaded_file.name
    ).suffix.lower()

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

    try:
        uploaded_file.seek(0)

        with Image.open(uploaded_file) as image:
            actual_format = (
                image.format or ""
            ).upper()

            if actual_format not in ALLOWED_IMAGE_TYPES:
                raise serializers.ValidationError(
                    "The uploaded file is not a supported image type."
                )

            expected_type = ALLOWED_IMAGE_TYPES[
                actual_format
            ]

            if extension not in expected_type["extensions"]:
                raise serializers.ValidationError(
                    "The image file extension does not match its actual format."
                )

            if (
                content_type
                and content_type
                not in expected_type["content_types"]
            ):
                raise serializers.ValidationError(
                    "The image content type does not match its actual format."
                )

            width, height = image.size

            if width <= 0 or height <= 0:
                raise serializers.ValidationError(
                    "The uploaded image has invalid dimensions."
                )

            if width * height > MAX_IMAGE_PIXELS:
                raise serializers.ValidationError(
                    "The uploaded image dimensions are too large."
                )

            image.verify()

    except serializers.ValidationError:
        raise
    except Exception as exc:
        raise serializers.ValidationError(
            "The uploaded file could not be validated as an image."
        ) from exc
    finally:
        uploaded_file.seek(0)

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

    masked_document_number = serializers.SerializerMethodField()

    document_front = serializers.SerializerMethodField()
    document_back = serializers.SerializerMethodField()
    selfie = serializers.SerializerMethodField()

    requires_document_back = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()
    can_submit = serializers.SerializerMethodField()
    missing_submission_fields = serializers.SerializerMethodField()

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
            "masked_document_number",
            "document_front",
            "document_back",
            "selfie",
            "requires_document_back",
            "can_edit",
            "can_submit",
            "missing_submission_fields",
            "submitted_at",
            "reviewed_at",
            "rejection_reason",
            "created_at",
            "updated_at",
            "identity_verification_method",
            "masked_identity_verification_value",
        )

        read_only_fields = fields

    def _get_protected_document_url(
        self,
        obj: KYCVerification,
        field_name: str,
        document_type: str,
    ):
        document = getattr(
            obj,
            field_name,
            None,
        )

        if not document:
            return None

        request = self.context.get("request")

        return reverse(
            "kyc:document",
            kwargs={
                "document_type": document_type,
            },
            request=request,
        )

    def get_document_front(
        self,
        obj: KYCVerification,
    ):
        return self._get_protected_document_url(
            obj,
            "document_front",
            "front",
        )

    def get_document_back(
        self,
        obj: KYCVerification,
    ):
        return self._get_protected_document_url(
            obj,
            "document_back",
            "back",
        )

    def get_selfie(
        self,
        obj: KYCVerification,
    ):
        return self._get_protected_document_url(
            obj,
            "selfie",
            "selfie",
        )

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

    def get_masked_identity_verification_value(
        self,
        obj: KYCVerification,
    ) -> str:
        value = obj.identity_verification_value or ""

        if value:
            visible_characters = 4

            if len(value) <= visible_characters:
                return "*" * len(value)

            return (
                "*" * (len(value) - visible_characters)
                + value[-visible_characters:]
            )

        last4 = obj.identity_verification_last4 or ""

        if last4:
            return f"*******{last4}"

        return ""

    def get_masked_document_number(
        self,
        obj: KYCVerification,
    ) -> str:
        value = (obj.document_number or "").strip()

        if value:
            visible_characters = 4

            if len(value) <= visible_characters:
                return "*" * len(value)

            return (
                "*" * (len(value) - visible_characters)
                + value[-visible_characters:]
            )

        last4 = (obj.document_number_last4 or "").strip()

        if last4:
            return f"*******{last4}"

        return ""


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
        
        identity_method = attrs.get(
            "identity_verification_method",
            getattr(instance, "identity_verification_method", ""),
        )

        identity_value = attrs.get(
            "identity_verification_value",
            getattr(instance, "identity_verification_value", ""),
        )

        if identity_value:
            identity_value = str(identity_value).strip()

            if identity_method == KYCVerification.IdentityVerificationMethod.BVN:
                if not identity_value.isdigit() or len(identity_value) != 11:
                    raise serializers.ValidationError(
                        {
                            "identity_verification_value": (
                                "BVN must be exactly 11 digits."
                            )
                        }
                    )

            elif (
                identity_method
                == KYCVerification.IdentityVerificationMethod.PHONE_NUMBER
            ):
                cleaned_phone = (
                    identity_value
                    .replace(" ", "")
                    .replace("-", "")
                    .replace("(", "")
                    .replace(")", "")
                )

                if cleaned_phone.startswith("+"):
                    digits = cleaned_phone[1:]
                else:
                    digits = cleaned_phone

                if not digits.isdigit() or len(digits) < 10 or len(digits) > 15:
                    raise serializers.ValidationError(
                        {
                            "identity_verification_value": (
                                "Enter a valid phone number."
                            )
                        }
                    )

                attrs["identity_verification_value"] = cleaned_phone

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

        identity_method_changed = (
            "identity_verification_method" in validated_data
            and validated_data["identity_verification_method"]
            != instance.identity_verification_method
        )

        identity_value_changed = (
            "identity_verification_value" in validated_data
            and validated_data["identity_verification_value"]
            != instance.identity_verification_value
        )

        document_number_changed = (
            "document_number" in validated_data
            and validated_data["document_number"]
            != instance.document_number
        )

        if identity_method_changed or identity_value_changed:
            instance.identity_verification_last4 = ""

        if document_number_changed:
            instance.document_number_last4 = ""

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

    reviewed_by = serializers.SerializerMethodField()

    document_front = serializers.SerializerMethodField()
    document_back = serializers.SerializerMethodField()
    selfie = serializers.SerializerMethodField()

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
            "review_note",
            "document_number",
            "reviewed_by",
        )

        read_only_fields = fields

    def get_customer(self, obj):
        return {
            "id": obj.user_id,
            "email": obj.user.email,
            "name": obj.user.get_full_name(),
        }

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

    def get_automated_verification_summary(self, obj):
        provider_response = obj.provider_response or {}

        return {
            "verification": provider_response.get("verification"),
        }

    def _get_admin_document_url(
        self,
        obj: KYCVerification,
        field_name: str,
        document_type: str,
    ):
        document = getattr(obj, field_name, None)

        if not document:
            return None

        request = self.context.get("request")

        return reverse(
            "kyc:admin-document",
            kwargs={
                "verification_id": obj.id,
                "document_type": document_type,
            },
            request=request,
        )


    def get_document_front(self, obj):
        return self._get_admin_document_url(
            obj,
            "document_front",
            "front",
        )


    def get_document_back(self, obj):
        return self._get_admin_document_url(
            obj,
            "document_back",
            "back",
        )


    def get_selfie(self, obj):
        return self._get_admin_document_url(
            obj,
            "selfie",
            "selfie",
        )

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