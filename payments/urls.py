from django.urls import path
from .views import (
    InitializePaymentView,
    PaystackWebhookView,
    VerifyPaymentView,
    MobilePaymentCallbackView,
)

urlpatterns = [
    path(
        "initialize/",
        InitializePaymentView.as_view(),
        name="initialize_payment",
    ),
    path(
        "verify/",
        VerifyPaymentView.as_view(),
        name="verify_payment",
    ),
    path(
        "webhook/",
        PaystackWebhookView.as_view(),
        name="paystack_webhook",
    ),
    path(
        "mobile-callback/",
        MobilePaymentCallbackView.as_view(),
        name="mobile-payment-callback",
    ),
]
