from django.contrib import admin

from .models import GuestTransaction


@admin.register(GuestTransaction)
class GuestTransactionAdmin(admin.ModelAdmin):

    list_display = (
        "reference",
        "guest_email",
        "service_type",
        "provider",
        "amount",
        "status",
        "created_at",
    )

    list_filter = (
        "status",
        "service_type",
        "provider",
    )

    search_fields = (
        "reference",
        "guest_email",
        "guest_phone",
        "recipient",
    )

    readonly_fields = (
        "reference",
        "payment_reference",
        "provider_reference",
        "provider_response",
        "token",
        "created_at",
        "updated_at",
    )