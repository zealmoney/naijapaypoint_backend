from django.db import transaction
from django.utils import timezone

from .integrations.dojah import (
    DojahAPIError,
    DojahService,
)
from .models import KYCVerification


class KYCAutomatedVerificationService:
    @classmethod
    @transaction.atomic
    def run_identity_check(
        cls,
        *,
        verification_id: int,
    ) -> KYCVerification:
        verification = (
            KYCVerification.objects
            .select_for_update()
            .select_related("user")
            .get(pk=verification_id)
        )

        if verification.status not in {
            KYCVerification.Status.SUBMITTED,
            KYCVerification.Status.UNDER_REVIEW,
        }:
            raise ValueError(
                "Only submitted KYC applications can be checked."
            )

        if not verification.identity_verification_method:
            raise ValueError(
                "Identity verification method is missing."
            )

        if not verification.identity_verification_value:
            raise ValueError(
                "Identity verification value is missing."
            )

        verification.verification_provider = "dojah"
        verification.automated_verification_status = "pending"
        verification.automated_verification_error = ""
        verification.save(
            update_fields=[
                "verification_provider",
                "automated_verification_status",
                "automated_verification_error",
                "updated_at",
            ]
        )

        customer_reference = (
            f"NPP-KYC-{verification.pk}"
        )

        try:
            response = DojahService.verify_identity(
                first_name=verification.first_name,
                last_name=verification.last_name,
                date_of_birth=(
                    verification.date_of_birth.isoformat()
                    if verification.date_of_birth
                    else None
                ),
                mode=(
                    verification.identity_verification_method
                ),
                identity_value=(
                    verification.identity_verification_value
                ),
                customer_reference=customer_reference,
            )
        except DojahAPIError as exc:
            verification.automated_verification_status = "error"
            verification.automated_verification_error = str(exc)
            verification.provider_reference = customer_reference
            verification.automated_verified_at = timezone.now()
            verification.save(
                update_fields=[
                    "automated_verification_status",
                    "automated_verification_error",
                    "provider_reference",
                    "automated_verified_at",
                    "updated_at",
                ]
            )
            return verification

        entity = response.get("entity") or {}
        passed = bool(entity.get("verification"))

        verification.provider_reference = customer_reference
        verification.provider_response = response
        verification.identity_match_passed = passed
        verification.automated_verification_status = (
            "passed" if passed else "failed"
        )
        verification.automated_verified_at = timezone.now()
        verification.save(
            update_fields=[
                "provider_reference",
                "provider_response",
                "identity_match_passed",
                "automated_verification_status",
                "automated_verified_at",
                "updated_at",
            ]
        )

        return verification