# beneficiaries/urls.py

from django.urls import path
from .views import (
    BeneficiaryListCreateView,
    BeneficiaryDetailView,
)

urlpatterns = [
    path(
        "",
        BeneficiaryListCreateView.as_view(),
        name="beneficiary-list",
    ),
    path(
        "<int:pk>/",
        BeneficiaryDetailView.as_view(),
        name="beneficiary-detail",
    ),
]