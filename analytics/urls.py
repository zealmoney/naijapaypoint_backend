from django.urls import path
from .views import AdminAnalyticsView
from .admin_transactions import (
    AdminTransactionListView,
    AdminTransactionDetailView,
    AdminTransactionRefundView,
    AdminTransactionResolveView,
    AdminGuestTransactionRefundView,
)

from .admin_users import (
    AdminUserListView,
    AdminUserDetailView,
    AdminUserToggleActiveView,
    AdminCustomerListView,
    AdminStaffListView,
    AdminMakeStaffView,
    AdminRemoveStaffView,
)

from .admin_transaction_actions import (
    AdminTransactionNotesView,
    AdminTransactionUpdateStatusView,
    AdminTransactionUpdateProviderRefView,
)

urlpatterns = [
    path("", AdminAnalyticsView.as_view(), name="admin-analytics"),
    path("transactions/", AdminTransactionListView.as_view(), name="admin-transactions"),
    path("transactions/<str:reference>/", AdminTransactionDetailView.as_view(), name="admin-transaction-detail"),
    path(
        "transactions/<str:reference>/refund/",
        AdminTransactionRefundView.as_view(),
        name="admin-transaction-refund",
    ),
    path(
        "transactions/<str:reference>/resolve/",
        AdminTransactionResolveView.as_view(),
        name="admin-transaction-resolve",
    ),
    path("users/", AdminUserListView.as_view(), name="admin-users"),
    path("users/<int:user_id>/", AdminUserDetailView.as_view(), name="admin-user-detail"),
    path(
        "users/<int:user_id>/toggle-active/",
        AdminUserToggleActiveView.as_view(),
        name="admin-user-toggle-active",
    ),
    path("customers/", AdminCustomerListView.as_view(), name="admin-customers"),
    path("staff/", AdminStaffListView.as_view(), name="admin-staff"),
    path("users/<int:user_id>/make-staff/", AdminMakeStaffView.as_view(), name="admin-make-staff"),
    path("users/<int:user_id>/remove-staff/", AdminRemoveStaffView.as_view(), name="admin-remove-staff"),
    path(
        "transactions/<str:reference>/notes/",
        AdminTransactionNotesView.as_view(),
        name="admin-transaction-notes",
    ),
    path(
        "transactions/<str:reference>/update-status/",
        AdminTransactionUpdateStatusView.as_view(),
        name="admin-transaction-update-status",
    ),
    path(
        "transactions/<str:reference>/update-provider-ref/",
        AdminTransactionUpdateProviderRefView.as_view(),
        name="admin-transaction-update-provider-ref",
    ),
    path(
        "guest-transactions/<str:reference>/refund/",
        AdminGuestTransactionRefundView.as_view(),
        name="admin-guest-transaction-refund",
    ),
]