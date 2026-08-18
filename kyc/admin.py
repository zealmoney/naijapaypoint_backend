from django.contrib import admin

from .models import KYCVerification


@admin.register(KYCVerification)
class KYCVerificationAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "status",
        "verification_level",
        "document_type",
        "submitted_at",
        "reviewed_by",
        "reviewed_at",
        "created_at",
    )

    list_filter = (
        "status",
        "verification_level",
        "document_type",
        "created_at",
    )

    search_fields = (
        "user__email",
        "user__username",
        "first_name",
        "last_name",
        "document_number",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
        "submitted_at",
        "reviewed_at",
    )

    fieldsets = (
        (
            "Account",
            {
                "fields": (
                    "user",
                    "verification_level",
                    "status",
                )
            },
        ),
        (
            "Personal Information",
            {
                "fields": (
                    "first_name",
                    "middle_name",
                    "last_name",
                    "date_of_birth",
                    "nationality",
                    "residential_address",
                )
            },
        ),
        (
            "Identity Document",
            {
                "fields": (
                    "document_type",
                    "document_number",
                    "document_front",
                    "document_back",
                    "selfie",
                )
            },
        ),
        (
            "Review",
            {
                "fields": (
                    "submitted_at",
                    "reviewed_by",
                    "reviewed_at",
                    "review_note",
                    "rejection_reason",
                )
            },
        ),
        (
            "System",
            {
                "fields": (
                    "metadata",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )