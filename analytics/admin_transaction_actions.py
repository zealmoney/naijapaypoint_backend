from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from audit_logs.services import AuditLogService
from transactions.models import Transaction, TransactionNote


class AdminTransactionNotesView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request, reference):
        try:
            tx = Transaction.objects.get(reference=reference)
        except Transaction.DoesNotExist:
            return Response({"detail": "Transaction not found."}, status=404)

        notes = tx.support_notes.select_related("staff_user").all()

        return Response([
            {
                "id": note.id,
                "note": note.note,
                "staff_email": note.staff_user.email if note.staff_user else "System",
                "created_at": note.created_at,
            }
            for note in notes
        ])

    def post(self, request, reference):
        note_text = request.data.get("note", "").strip()

        if not note_text:
            return Response({"detail": "Note is required."}, status=400)

        try:
            tx = Transaction.objects.select_related("user").get(reference=reference)
        except Transaction.DoesNotExist:
            return Response({"detail": "Transaction not found."}, status=404)

        note = TransactionNote.objects.create(
            transaction=tx,
            staff_user=request.user,
            note=note_text,
        )

        AuditLogService.log_action(
            admin_user=request.user,
            action_type="transaction_note_added",
            target_user_email=tx.user.email,
            target_reference=tx.reference,
            note=note_text,
            metadata={
                "service_type": tx.service_type,
                "amount": str(tx.amount),
            },
        )

        return Response({
            "id": note.id,
            "note": note.note,
            "staff_email": request.user.email,
            "created_at": note.created_at,
        })


class AdminTransactionUpdateStatusView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, reference):
        new_status = request.data.get("status")
        note = request.data.get("note", "").strip()

        # This generic admin endpoint must never be used
        # to manufacture provider success or perform a
        # financial refund.
        allowed_admin_statuses = [
            "pending",
            "failed",
        ]

        if new_status not in allowed_admin_statuses:
            return Response(
                {
                    "detail": (
                        "This status cannot be set manually. "
                        "Success must be confirmed through the "
                        "provider/reconciliation workflow, and "
                        "refunds must use the refund workflow."
                    )
                },
                status=400,
            )

        try:
            tx = Transaction.objects.select_related(
                "user"
            ).get(
                reference=reference
            )
        except Transaction.DoesNotExist:
            return Response(
                {
                    "detail":
                        "Transaction not found."
                },
                status=404,
            )

        old_status = tx.status

        # Terminal financial/provider states must not be
        # reopened or rewritten through this endpoint.
        if old_status in {
            "success",
            "refunded",
        }:
            return Response(
                {
                    "detail": (
                        "A successful or refunded "
                        "transaction cannot be changed "
                        "manually."
                    )
                },
                status=409,
            )

        # Avoid pretending that an administrative action
        # occurred when nothing actually changed.
        if new_status == old_status:
            return Response(
                {
                    "detail": (
                        "Transaction already has "
                        f"status '{old_status}'."
                    )
                },
                status=400,
            )

        # The only meaningful transition currently allowed
        # by this endpoint is an unresolved transaction
        # being administratively marked failed.
        if new_status == "failed" and old_status not in {
            "pending",
            "processing",
        }:
            return Response(
                {
                    "detail": (
                        "Only pending or processing "
                        "transactions can be marked failed "
                        "manually."
                    )
                },
                status=409,
            )

        # There is currently no valid transition *to*
        # pending through this endpoint. Keeping "pending"
        # in the input allowlist above gives us an explicit,
        # controlled rejection rather than silently allowing
        # arbitrary state rewrites.
        if new_status == "pending":
            return Response(
                {
                    "detail": (
                        "Transactions cannot be moved back "
                        "to pending manually."
                    )
                },
                status=409,
            )

        tx.status = new_status
        tx.metadata = {
            **(tx.metadata or {}),
            "admin_status_update": True,
            "previous_status": old_status,
            "new_status": new_status,
            "admin_status_note": note,
        }

        tx.save(
            update_fields=[
                "status",
                "metadata",
            ]
        )

        AuditLogService.log_action(
            admin_user=request.user,
            action_type="transaction_status_changed",
            target_user_email=tx.user.email,
            target_reference=tx.reference,
            note=note,
            metadata={
                "old_status": old_status,
                "new_status": new_status,
                "service_type": tx.service_type,
                "amount": str(tx.amount),
            },
        )

        return Response(
            {
                "detail":
                    "Transaction status updated.",
                "old_status": old_status,
                "new_status": new_status,
            }
        )

class AdminTransactionUpdateProviderRefView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, reference):
        try:
            tx = Transaction.objects.select_related(
                "user"
            ).get(
                reference=reference
            )
        except Transaction.DoesNotExist:
            return Response(
                {
                    "detail":
                        "Transaction not found."
                },
                status=404,
            )

        return Response(
            {
                "detail": (
                    "Provider references cannot be "
                    "modified manually. They are "
                    "controlled by provider and "
                    "reconciliation workflows."
                )
            },
            status=409,
        )