from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    ACTION_TYPES = (
        ("refund_transaction", "Refund Transaction"),
        ("resolve_transaction", "Resolve Transaction"),
        ("suspend_user", "Suspend User"),
        ("activate_user", "Activate User"),
        ("promote_staff", "Promote Staff"),
        ("remove_staff", "Remove Staff"),
        ("system", "System"),
        ("transaction_note_added", "Transaction Note Added"),
        ("transaction_status_changed", "Transaction Status Changed"),
        ("provider_reference_updated", "Provider Reference Updated"),
        ("ticket_replied", "Ticket Replied"),
        ("ticket_assigned", "Ticket Assigned"),
        ("ticket_status_changed", "Ticket Status Changed"),
        ("ticket_priority_changed", "Ticket Priority Changed"),
        ("customer_note_added", "Customer Note Added"),
        ("customer_note_deleted", "Customer Note Deleted"),
    )

    admin_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="audit_logs",
    )

    action_type = models.CharField(max_length=50, choices=ACTION_TYPES)
    target_user_email = models.EmailField(blank=True)
    target_reference = models.CharField(max_length=255, blank=True)

    note = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.action_type} by {self.admin_user}"