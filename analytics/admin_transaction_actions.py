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
        note = request.data.get("note", "")

        allowed_statuses = ["pending", "success", "failed", "refunded"]

        if new_status not in allowed_statuses:
            return Response({"detail": "Invalid status."}, status=400)

        try:
            tx = Transaction.objects.select_related("user").get(reference=reference)
        except Transaction.DoesNotExist:
            return Response({"detail": "Transaction not found."}, status=404)

        old_status = tx.status
        tx.status = new_status
        tx.metadata = {
            **(tx.metadata or {}),
            "admin_status_update": True,
            "previous_status": old_status,
            "new_status": new_status,
            "admin_status_note": note,
        }
        tx.save(update_fields=["status", "metadata"])

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

        return Response({
            "detail": "Transaction status updated.",
            "old_status": old_status,
            "new_status": new_status,
        })


class AdminTransactionUpdateProviderRefView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, reference):
        provider_reference = request.data.get("provider_reference", "").strip()
        note = request.data.get("note", "")

        if not provider_reference:
            return Response(
                {"detail": "Provider reference is required."},
                status=400,
            )

        try:
            tx = Transaction.objects.select_related("user").get(reference=reference)
        except Transaction.DoesNotExist:
            return Response({"detail": "Transaction not found."}, status=404)

        old_provider_reference = tx.provider_reference

        tx.provider_reference = provider_reference
        tx.metadata = {
            **(tx.metadata or {}),
            "admin_provider_reference_update": True,
            "previous_provider_reference": old_provider_reference,
            "new_provider_reference": provider_reference,
            "admin_provider_note": note,
        }
        tx.save(update_fields=["provider_reference", "metadata"])

        AuditLogService.log_action(
            admin_user=request.user,
            action_type="provider_reference_updated",
            target_user_email=tx.user.email,
            target_reference=tx.reference,
            note=note,
            metadata={
                "old_provider_reference": old_provider_reference,
                "new_provider_reference": provider_reference,
                "service_type": tx.service_type,
            },
        )

        return Response({
            "detail": "Provider reference updated.",
            "provider_reference": provider_reference,
        })