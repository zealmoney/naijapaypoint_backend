from django.urls import path

from .views import (
    AdminKYCApproveView,
    AdminKYCDetailView,
    AdminKYCListView,
    AdminKYCPendingCountView,
    AdminKYCPendingListView,
    AdminKYCRejectView,
    KYCStartView,
    KYCStatusView,
    KYCSubmitView,
    KYCUpdateView,
    AdminKYCRunAutomatedCheckView,
)

app_name = "kyc"

urlpatterns = [
    path(
        "status/",
        KYCStatusView.as_view(),
        name="status",
    ),
    path(
        "start/",
        KYCStartView.as_view(),
        name="start",
    ),
    path(
        "update/",
        KYCUpdateView.as_view(),
        name="update",
    ),
    path(
        "submit/",
        KYCSubmitView.as_view(),
        name="submit",
    ),

    path(
        "admin/",
        AdminKYCListView.as_view(),
        name="admin-list",
    ),
    path(
        "admin/pending/",
        AdminKYCPendingListView.as_view(),
        name="admin-pending",
    ),
    path(
        "admin/pending-count/",
        AdminKYCPendingCountView.as_view(),
        name="admin-pending-count",
    ),
    path(
        "admin/<int:verification_id>/",
        AdminKYCDetailView.as_view(),
        name="admin-detail",
    ),
    path(
        "admin/<int:verification_id>/approve/",
        AdminKYCApproveView.as_view(),
        name="admin-approve",
    ),
    path(
        "admin/<int:verification_id>/reject/",
        AdminKYCRejectView.as_view(),
        name="admin-reject",
    ),
    path(
        "admin/<int:verification_id>/automated-check/",
        AdminKYCRunAutomatedCheckView.as_view(),
        name="admin-automated-check",
    ),
]