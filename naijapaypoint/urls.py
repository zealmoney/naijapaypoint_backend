from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("accounts.urls")),
    path("api/wallet/", include("wallets.urls")),
    path("api/payments/", include("payments.urls")),
    path("api/transactions/", include("transactions.urls")),
    path("api/airtime/", include("airtime.urls")),
    path("api/data/", include("data_services.urls")),
    path("api/electricity/", include("electricity.urls")),
    path("api/cable/", include("cable.urls")),
    path("api/beneficiaries/", include("beneficiaries.urls")),
    path("api/education/", include("education.urls")),
    path("api/notifications/", include("notifications.urls")),
    path("api/referrals/", include("referrals.urls")),
    path("api/analytics/", include("analytics.urls")),
    path("api/audit-logs/", include("audit_logs.urls")),
    path("api/support/", include("support.urls")),
    path("api/customer-notes/", include("customer_notes.urls")),
    path("api/guest/", include("guest_checkout.urls")),
    path("api/kyc/", include("kyc.urls")),
]

if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT,
    )