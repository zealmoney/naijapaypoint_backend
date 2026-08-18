from django.urls import path

from .views import (
    GuestCablePlansView,
    GuestCableProvidersView,
    GuestCableVerifyView,
    GuestDataPlansView,
    GuestElectricityVerifyView,
    GuestInitializePaymentView,
    GuestReceiptView,
    GuestVerifyPaymentView,
)

urlpatterns = [
    path(
        "data/plans/",
        GuestDataPlansView.as_view(),
    ),
    path(
        "initialize/",
        GuestInitializePaymentView.as_view(),
    ),

    path(
        "verify/",
        GuestVerifyPaymentView.as_view(),
    ),

    path(
        "receipt/<str:reference>/",
        GuestReceiptView.as_view(),
    ),

    path(
        "electricity/verify/",
        GuestElectricityVerifyView.as_view(),
    ),

    path(
        "cable/providers/",
        GuestCableProvidersView.as_view(),
    ),

    path(
        "cable/plans/",
        GuestCablePlansView.as_view(),
    ),

    path(
        "cable/verify/",
        GuestCableVerifyView.as_view(),
    ),
]