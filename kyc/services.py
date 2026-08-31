from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import KYCVerification

from notifications.services import NotificationService


class KYCService:
    """
    Business logic for the customer-facing KYC workflow.
    """

    EDITABLE_STATUSES = {
        KYCVerification.Status.NOT_STARTED,
        KYCVerification.Status.DRAFT,
        KYCVerification.Status.REJECTED,
    }

    SUBMITTABLE_STATUSES = {
        KYCVerification.Status.DRAFT,
        KYCVerification.Status.REJECTED,
    }

    # These document types normally have useful information on both sides.
    DOCUMENTS_REQUIRING_BACK = {
        KYCVerification.DocumentType.DRIVERS_LICENSE,
        KYCVerification.DocumentType.VOTERS_CARD,
    }

    REVIEWABLE_STATUSES = {
        KYCVerification.Status.SUBMITTED,
        KYCVerification.Status.UNDER_REVIEW,
    }


    @classmethod
    def get_for_user(cls, user) -> KYCVerification | None:
        return (
            KYCVerification.objects
            .select_related("user", "reviewed_by")
            .filter(user=user)
            .first()
        )

    @classmethod
    @transaction.atomic
    def start_verification(cls, user) -> tuple[KYCVerification, bool]:
        """
        Create a KYC record for the user or return the existing one.

        Returns:
            tuple: (verification, created)
        """

        verification, created = (
            KYCVerification.objects.select_for_update().get_or_create(
                user=user,
                defaults={
                    "status": KYCVerification.Status.DRAFT,
                    "verification_level": (
                        KYCVerification.VerificationLevel.REGISTERED
                    ),
                },
            )
        )

        if verification.status == KYCVerification.Status.NOT_STARTED:
            verification.status = KYCVerification.Status.DRAFT
            verification.save(
                update_fields=[
                    "status",
                    "updated_at",
                ]
            )

        return verification, created

    @classmethod
    def ensure_editable(
        cls,
        verification: KYCVerification,
    ) -> None:
        if verification.status not in cls.EDITABLE_STATUSES:
            raise ValidationError(
                {
                    "detail": (
                        "This KYC application cannot currently be edited."
                    ),
                    "status": verification.status,
                }
            )

    @classmethod
    def ensure_submittable(
        cls,
        verification: KYCVerification,
    ) -> None:
        if verification.status not in cls.SUBMITTABLE_STATUSES:
            raise ValidationError(
                {
                    "detail": (
                        "This KYC application cannot currently be submitted."
                    ),
                    "status": verification.status,
                }
            )

    @classmethod
    def get_missing_submission_fields(
        cls,
        verification: KYCVerification,
    ) -> dict[str, str]:
        """
        Return all fields that must be completed before submission.
        """

        required_fields = {
            "first_name": "First name is required.",
            "last_name": "Last name is required.",
            "date_of_birth": "Date of birth is required.",
            "nationality": "Nationality is required.",
            "residential_address": "Residential address is required.",
            "document_type": "Document type is required.",
            "document_number": "Document number is required.",
            "identity_verification_method": (
                "Identity verification method is required."
            ),
            "identity_verification_value": (
                "Identity verification value is required."
            ),
            "document_front": (
                "The front of your identity document is required."
            ),
            "selfie": "A selfie is required.",
        }

        errors: dict[str, str] = {}

        for field_name, message in required_fields.items():
            value = getattr(verification, field_name, None)

            if value is None:
                errors[field_name] = message
                continue

            if isinstance(value, str) and not value.strip():
                errors[field_name] = message

        if (
            verification.document_type
            in cls.DOCUMENTS_REQUIRING_BACK
            and not verification.document_back
        ):
            errors["document_back"] = (
                "The back of this identity document is required."
            )

        return errors

    @classmethod
    @transaction.atomic
    def submit_verification(
        cls,
        user,
    ) -> KYCVerification:
        try:
            verification = (
                KYCVerification.objects
                .select_for_update()
                .get(user=user)
            )
        except KYCVerification.DoesNotExist as exc:
            raise ValidationError(
                {
                    "detail": (
                        "Start your KYC verification before submitting it."
                    )
                }
            ) from exc

        cls.ensure_submittable(verification)

        missing_fields = cls.get_missing_submission_fields(
            verification
        )

        if missing_fields:
            raise ValidationError(
                {
                    "detail": (
                        "Complete all required KYC information before "
                        "submitting."
                    ),
                    "fields": missing_fields,
                }
            )

        now = timezone.now()

        verification.status = KYCVerification.Status.SUBMITTED
        verification.submitted_at = now

        # Clear information from a previous rejected review.
        verification.reviewed_by = None
        verification.reviewed_at = None
        verification.review_note = ""
        verification.rejection_reason = ""

        metadata: dict[str, Any] = verification.metadata or {}
        submission_history = metadata.get(
            "submission_history",
            [],
        )

        if not isinstance(submission_history, list):
            submission_history = []

        submission_history.append(
            {
                "submitted_at": now.isoformat(),
                "status": KYCVerification.Status.SUBMITTED,
            }
        )

        verification.metadata = {
            **metadata,
            "submission_history": submission_history[-20:],
        }

        verification.save(
            update_fields=[
                "status",
                "submitted_at",
                "reviewed_by",
                "reviewed_at",
                "review_note",
                "rejection_reason",
                "metadata",
                "updated_at",
            ]
        )

        return verification

    @classmethod
    def ensure_reviewable(
        cls,
        verification: KYCVerification,
    ) -> None:
        if verification.status not in cls.REVIEWABLE_STATUSES:
            raise ValidationError(
                {
                    "detail": (
                        "This KYC application cannot currently be reviewed."
                    ),
                    "status": verification.status,
                }
            )

    @classmethod
    @transaction.atomic
    def approve_verification(
        cls,
        verification_id: int,
        reviewer,
        review_note: str = "",
    ) -> KYCVerification:
        try:
            verification = (
                KYCVerification.objects
                .select_for_update()
                .select_related("user")
                .get(pk=verification_id)
            )
        except KYCVerification.DoesNotExist as exc:
            raise ValidationError(
                {"detail": "KYC application was not found."}
            ) from exc

        cls.ensure_reviewable(verification)

        now = timezone.now()

        verification.status = KYCVerification.Status.APPROVED
        verification.verification_level = (
            KYCVerification.VerificationLevel.IDENTITY_VERIFIED
        )
        verification.reviewed_by = reviewer
        verification.reviewed_at = now
        verification.review_note = review_note.strip()
        verification.rejection_reason = ""

        metadata: dict[str, Any] = verification.metadata or {}
        review_history = metadata.get("review_history", [])

        if not isinstance(review_history, list):
            review_history = []

        review_history.append(
            {
                "action": "approved",
                "reviewer_id": reviewer.pk,
                "reviewer_email": getattr(reviewer, "email", ""),
                "review_note": review_note.strip(),
                "reviewed_at": now.isoformat(),
            }
        )

        verification.metadata = {
            **metadata,
            "review_history": review_history[-50:],
        }

        verification.save(
            update_fields=[
                "status",
                "verification_level",
                "reviewed_by",
                "reviewed_at",
                "review_note",
                "rejection_reason",
                "metadata",
                "updated_at",
            ]
        )

        if not verification.user.is_verified:
            verification.user.is_verified = True
            verification.user.save(
                update_fields=["is_verified"]
            )

        transaction.on_commit(
            lambda: NotificationService.create_notification(
                user=verification.user,
                notification_type="kyc",
                title="Identity Verification Approved",
                message=(
                    "Congratulations! Your identity verification has been approved."
                ),
                metadata={
                    "status": "approved",
                    "verification_id": verification.id,
                },
            )
        )

        return verification

    @classmethod
    @transaction.atomic
    def reject_verification(
        cls,
        verification_id: int,
        reviewer,
        rejection_reason: str,
        review_note: str = "",
    ) -> KYCVerification:
        try:
            verification = (
                KYCVerification.objects
                .select_for_update()
                .select_related("user")
                .get(pk=verification_id)
            )
        except KYCVerification.DoesNotExist as exc:
            raise ValidationError(
                {"detail": "KYC application was not found."}
            ) from exc

        cls.ensure_reviewable(verification)

        now = timezone.now()

        verification.status = KYCVerification.Status.REJECTED
        verification.verification_level = (
            KYCVerification.VerificationLevel.REGISTERED
        )
        verification.reviewed_by = reviewer
        verification.reviewed_at = now
        verification.review_note = review_note.strip()
        verification.rejection_reason = rejection_reason.strip()

        metadata: dict[str, Any] = verification.metadata or {}
        review_history = metadata.get("review_history", [])

        if not isinstance(review_history, list):
            review_history = []

        review_history.append(
            {
                "action": "rejected",
                "reviewer_id": reviewer.pk,
                "reviewer_email": getattr(reviewer, "email", ""),
                "rejection_reason": rejection_reason.strip(),
                "review_note": review_note.strip(),
                "reviewed_at": now.isoformat(),
            }
        )

        verification.metadata = {
            **metadata,
            "review_history": review_history[-50:],
        }

        verification.save(
            update_fields=[
                "status",
                "verification_level",
                "reviewed_by",
                "reviewed_at",
                "review_note",
                "rejection_reason",
                "metadata",
                "updated_at",
            ]
        )

        transaction.on_commit(
            lambda: NotificationService.create_notification(
                user=verification.user,
                notification_type="kyc",
                title="Identity Verification Rejected",
                message=(
                    f"Your verification was rejected.\n\n"
                    f"Reason: {verification.rejection_reason}"
                ),
                metadata={
                    "status": "rejected",
                    "verification_id": verification.id,
                },
            )
        )

        return verification