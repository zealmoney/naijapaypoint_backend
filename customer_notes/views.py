from django.contrib.auth import get_user_model
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from audit_logs.services import AuditLogService
from .models import CustomerNote
from .serializers import CustomerNoteSerializer


User = get_user_model()


class CustomerNoteListCreateView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request, user_id):
        try:
            customer = User.objects.get(id=user_id, is_staff=False)
        except User.DoesNotExist:
            return Response({"detail": "Customer not found."}, status=404)

        notes = CustomerNote.objects.filter(customer=customer)
        serializer = CustomerNoteSerializer(notes, many=True)

        return Response(serializer.data)

    def post(self, request, user_id):
        note_text = request.data.get("note", "").strip()

        if not note_text:
            return Response({"detail": "Note is required."}, status=400)

        try:
            customer = User.objects.get(id=user_id, is_staff=False)
        except User.DoesNotExist:
            return Response({"detail": "Customer not found."}, status=404)

        note = CustomerNote.objects.create(
            customer=customer,
            staff_user=request.user,
            note=note_text,
        )

        AuditLogService.log_action(
            admin_user=request.user,
            action_type="customer_note_added",
            target_user_email=customer.email,
            note=note_text,
            metadata={"customer_id": customer.id},
        )

        return Response(CustomerNoteSerializer(note).data, status=201)


class CustomerNoteDeleteView(APIView):
    permission_classes = [IsAdminUser]

    def delete(self, request, note_id):
        try:
            note = CustomerNote.objects.select_related("customer").get(id=note_id)
        except CustomerNote.DoesNotExist:
            return Response({"detail": "Note not found."}, status=404)

        customer_email = note.customer.email
        note_text = note.note
        note.delete()

        AuditLogService.log_action(
            admin_user=request.user,
            action_type="customer_note_deleted",
            target_user_email=customer_email,
            note=note_text,
        )

        return Response({"detail": "Customer note deleted."})