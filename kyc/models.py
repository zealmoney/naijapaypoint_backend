from django.conf import settings
from django.db import models


class KYCVerification(models.Model):
    class VerificationLevel(models.IntegerChoices):
        REGISTERED = 1, "Registered"
        IDENTITY_VERIFIED = 2, "Identity Verified"
        ENHANCED = 3, "Enhanced Verification"

    class Status(models.TextChoices):
        NOT_STARTED = "not_started", "Not Started"
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        UNDER_REVIEW = "under_review", "Under Review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    class DocumentType(models.TextChoices):
        NATIONAL_ID = "national_id", "National ID"
        DRIVERS_LICENSE = "drivers_license", "Driver's License"
        INTERNATIONAL_PASSPORT = (
            "international_passport",
            "International Passport",
        )
        VOTERS_CARD = "voters_card", "Voter's Card"

    class AutomatedVerificationStatus(models.TextChoices):
        NOT_STARTED = "not_started", "Not Started"
        PENDING = "pending", "Pending"
        PASSED = "passed", "Passed"
        FAILED = "failed", "Failed"
        ERROR = "error", "Error"

    class IdentityVerificationMethod(models.TextChoices):
        BVN = "bvn", "BVN"
        PHONE_NUMBER = "phone_number", "Phone Number"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="kyc_verification",
    )

    verification_level = models.PositiveSmallIntegerField(
        choices=VerificationLevel.choices,
        default=VerificationLevel.REGISTERED,
    )

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.NOT_STARTED,
    )

    first_name = models.CharField(max_length=100, blank=True)
    middle_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)

    date_of_birth = models.DateField(
        null=True,
        blank=True,
    )

    nationality = models.CharField(
        max_length=100,
        blank=True,
    )

    residential_address = models.TextField(blank=True)

    document_type = models.CharField(
        max_length=40,
        choices=DocumentType.choices,
        blank=True,
    )

    document_number = models.CharField(
        max_length=100,
        blank=True,
    )

    document_front = models.ImageField(
        upload_to="kyc/documents/front/%Y/%m/",
        blank=True,
        null=True,
    )

    document_back = models.ImageField(
        upload_to="kyc/documents/back/%Y/%m/",
        blank=True,
        null=True,
    )

    selfie = models.ImageField(
        upload_to="kyc/selfies/%Y/%m/",
        blank=True,
        null=True,
    )

    submitted_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="reviewed_kyc_applications",
        null=True,
        blank=True,
    )

    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    review_note = models.TextField(blank=True)
    rejection_reason = models.TextField(blank=True)

    metadata = models.JSONField(
        default=dict,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    verification_provider = models.CharField(
        max_length=50,
        blank=True,
    )

    provider_reference = models.CharField(
        max_length=150,
        blank=True,
        db_index=True,
    )

    automated_verification_status = models.CharField(
        max_length=30,
        choices=[
            ("not_started", "Not Started"),
            ("pending", "Pending"),
            ("passed", "Passed"),
            ("failed", "Failed"),
            ("error", "Error"),
        ],
        default="not_started",
    )

    document_authentic = models.BooleanField(
        null=True,
        blank=True,
    )

    face_match_passed = models.BooleanField(
        null=True,
        blank=True,
    )

    liveness_passed = models.BooleanField(
        null=True,
        blank=True,
    )

    face_match_score = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        null=True,
        blank=True,
    )

    provider_result = models.JSONField(
        default=dict,
        blank=True,
    )

    automated_verified_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    verification_provider = models.CharField(
        max_length=30,
        blank=True,
        default="",
    )

    provider_reference = models.CharField(
        max_length=150,
        blank=True,
        default="",
        db_index=True,
    )

    automated_verification_status = models.CharField(
        max_length=30,
        choices=AutomatedVerificationStatus.choices,
        default=AutomatedVerificationStatus.NOT_STARTED,
    )

    identity_match_passed = models.BooleanField(
        null=True,
        blank=True,
    )

    document_authentic = models.BooleanField(
        null=True,
        blank=True,
    )

    face_match_passed = models.BooleanField(
        null=True,
        blank=True,
    )

    liveness_passed = models.BooleanField(
        null=True,
        blank=True,
    )

    face_match_score = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        null=True,
        blank=True,
    )

    provider_response = models.JSONField(
        default=dict,
        blank=True,
    )

    automated_verified_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    automated_verification_error = models.TextField(
        blank=True,
        default="",
    )

    identity_verification_method = models.CharField(
        max_length=30,
        choices=IdentityVerificationMethod.choices,
        blank=True,
        default="",
    )

    identity_verification_value = models.CharField(
        max_length=30,
        blank=True,
        default="",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "KYC Verification"
        verbose_name_plural = "KYC Verifications"

    def __str__(self):
        return f"{self.user.email} - {self.get_status_display()}"

    