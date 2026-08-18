from django.urls import path

from .views import (
    EducationProvidersView,
    EducationPlansView,
    EducationPurchaseView,
)

urlpatterns = [
    path(
        "providers/",
        EducationProvidersView.as_view(),
        name="education-providers",
    ),
    path(
        "plans/",
        EducationPlansView.as_view(),
        name="education-plans",
    ),
    path(
        "purchase/",
        EducationPurchaseView.as_view(),
        name="education-purchase",
    ),
]