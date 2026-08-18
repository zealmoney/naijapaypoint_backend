from django.contrib import admin
from .models import Beneficiary


@admin.register(Beneficiary)
class BeneficiaryAdmin(admin.ModelAdmin):
    list_display = (
        "nickname",
        "beneficiary_type",
        "identifier",
        "provider",
        "user",
    )

    search_fields = (
        "nickname",
        "identifier",
        "user__email",
    )