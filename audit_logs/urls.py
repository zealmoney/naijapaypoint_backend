from django.urls import path
from .views import AdminAuditLogListView

urlpatterns = [
    path("", AdminAuditLogListView.as_view(), name="admin-audit-logs"),
]