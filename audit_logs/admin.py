from django.contrib import admin
from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "admin_user",
        "action_type",
        "target_user_email",
        "target_reference",
    )

    list_filter = (
        "action_type",
        "created_at",
    )

    search_fields = (
        "admin_user__email",
        "target_user_email",
        "target_reference",
        "note",
    )

    readonly_fields = (
        "created_at",
        "admin_user",
        "action_type",
        "target_user_email",
        "target_reference",
        "note",
        "metadata",
    )

    ordering = ("-created_at",)