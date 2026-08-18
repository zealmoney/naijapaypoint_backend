from django.urls import path

from .views import (
    CableProvidersView,
    CablePlansView,
    CableVerifyView,
    CablePurchaseView,
)

urlpatterns = [
    path("providers/", CableProvidersView.as_view()),
    path("plans/", CablePlansView.as_view()),
    path("verify/", CableVerifyView.as_view()),
    path("purchase/", CablePurchaseView.as_view()),
]