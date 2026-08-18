from django.contrib import admin
from .models import CustomerNote


@admin.register(CustomerNote)
class CustomerNoteAdmin(admin.ModelAdmin):
    list_display = ("customer", "staff_user", "created_at")
    search_fields = ("customer__email", "staff_user__email", "note")
    list_filter = ("created_at",)
    readonly_fields = ("created_at", "updated_at")