from django.urls import path

from .views import (
    ElectricityProvidersView,
    VerifyMeterView,
    ElectricityPurchaseView,
)

urlpatterns = [
    path("providers/", ElectricityProvidersView.as_view()),
    path("verify-meter/", VerifyMeterView.as_view()),
    path("purchase/", ElectricityPurchaseView.as_view()),
]