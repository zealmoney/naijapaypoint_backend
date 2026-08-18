from django.urls import path

from .views import (
    AdminSupportUnresolvedCountView,
    SupportTicketListCreateView,
    SupportTicketDetailView,
    SupportTicketReplyView,
    SupportTicketAssignView,
    SupportTicketStatusView,
    SupportTicketPriorityView,
)

urlpatterns = [
    path("tickets/", SupportTicketListCreateView.as_view(), name="support-tickets"),
    path("tickets/<int:pk>/", SupportTicketDetailView.as_view(), name="support-ticket-detail"),
    path("tickets/<int:pk>/reply/", SupportTicketReplyView.as_view(), name="support-ticket-reply"),
    path("tickets/<int:pk>/assign/", SupportTicketAssignView.as_view(), name="support-ticket-assign"),
    path("tickets/<int:pk>/status/", SupportTicketStatusView.as_view(), name="support-ticket-status"),
    path("tickets/<int:pk>/priority/", SupportTicketPriorityView.as_view(), name="support-ticket-priority"),
    path("admin/unresolved-count/", AdminSupportUnresolvedCountView.as_view(), name="admin-support-unresolved-count"),
]