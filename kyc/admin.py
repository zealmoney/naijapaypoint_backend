from django.contrib import admin

from .models import KYCVerification


@admin.register(KYCVerification)
class KYCVerificationAdmin(admin.ModelAdmin):
    def has_module_permission(self, request):
        return request.user.has_perm(
            "kyc.review_kycverification"
        )

    def has_view_permission(self, request, obj=None):
        return request.user.has_perm(
            "kyc.review_kycverification"
        )

    def has_change_permission(self, request, obj=None):
        return request.user.has_perm(
            "kyc.review_kycverification"
        )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

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