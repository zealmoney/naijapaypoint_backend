from django.contrib.auth import get_user_model
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from audit_logs.services import AuditLogService
from notifications.email_service import EmailNotificationService
from notifications.services import NotificationService

from .models import SupportTicket, TicketReply
from .serializers import (
    SupportTicketSerializer,
    TicketPriorityUpdateSerializer,
    TicketReplyCreateSerializer,
    TicketStatusUpdateSerializer,
)


def notify_active_staff(*, title, message, metadata):
    """Create an in-app notification for each active staff account."""
    User = get_user_model()
    staff_users = User.objects.filter(is_staff=True, is_active=True)

    for staff_user in staff_users.iterator():
        NotificationService.create_notification(
            user=staff_user,
            notification_type="system",
            title=title,
            message=message,
            metadata=metadata,
        )


class SupportTicketListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.is_staff:
            tickets = SupportTicket.objects.select_related(
                "user", "assigned_to"
            ).prefetch_related("replies__author").all()
        else:
            tickets = SupportTicket.objects.select_related(
                "user", "assigned_to"
            ).prefetch_related("replies__author").filter(user=request.user)

        serializer = SupportTicketSerializer(tickets, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = SupportTicketSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        ticket = SupportTicket.objects.create(
            user=request.user,
            subject=serializer.validated_data["subject"],
            message=serializer.validated_data["message"],
            category=serializer.validated_data.get("category", "other"),
            related_reference=serializer.validated_data.get("related_reference", ""),
            priority=serializer.validated_data.get("priority", "normal"),
        )

        NotificationService.create_notification(
            user=request.user,
            notification_type="system",
            title="Support Ticket Created",
            message=f"Your support ticket #{ticket.id} has been created.",
            metadata={"ticket_id": ticket.id},
        )

        notify_active_staff(
            title="New Support Ticket",
            message=(
                f"{request.user.email} created ticket #{ticket.id}: "
                f"{ticket.subject}."
            ),
            metadata={
                "ticket_id": ticket.id,
                "category": ticket.category,
                "customer_email": request.user.email,
            },
        )

        return Response(SupportTicketSerializer(ticket).data, status=201)


class SupportTicketDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get_ticket(self, request, pk):
        try:
            ticket = SupportTicket.objects.select_related(
                "user", "assigned_to"
            ).prefetch_related("replies__author").get(id=pk)
        except SupportTicket.DoesNotExist:
            return None

        if not request.user.is_staff and ticket.user != request.user:
            return None

        return ticket

    def get(self, request, pk):
        ticket = self.get_ticket(request, pk)

        if not ticket:
            return Response({"detail": "Ticket not found."}, status=404)

        return Response(SupportTicketSerializer(ticket).data)


class SupportTicketReplyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        serializer = TicketReplyCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            ticket = SupportTicket.objects.select_related("user").get(id=pk)
        except SupportTicket.DoesNotExist:
            return Response({"detail": "Ticket not found."}, status=404)

        if not request.user.is_staff and ticket.user != request.user:
            return Response({"detail": "Permission denied."}, status=403)

        reply = TicketReply.objects.create(
            ticket=ticket,
            author=request.user,
            message=serializer.validated_data["message"],
            is_staff_reply=request.user.is_staff,
        )

        if request.user.is_staff:
            NotificationService.create_notification(
                user=ticket.user,
                notification_type="system",
                title="Support Ticket Reply",
                message=f"Support replied to ticket #{ticket.id}.",
                metadata={"ticket_id": ticket.id},
            )

            AuditLogService.log_action(
                admin_user=request.user,
                action_type="ticket_replied",
                target_user_email=ticket.user.email,
                target_reference=str(ticket.id),
                note=reply.message,
                metadata={"ticket_id": ticket.id},
            )

            EmailNotificationService.send_support_reply(
                user=ticket.user,
                ticket_id=ticket.id,
            )
        else:
            notify_active_staff(
                title="Customer Replied to Support Ticket",
                message=(
                    f"{request.user.email} replied to ticket #{ticket.id}: "
                    f"{ticket.subject}."
                ),
                metadata={
                    "ticket_id": ticket.id,
                    "category": ticket.category,
                    "customer_email": request.user.email,
                },
            )

        return Response({"detail": "Reply added."}, status=201)


class SupportTicketAssignView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        try:
            ticket = SupportTicket.objects.select_related("user").get(id=pk)
        except SupportTicket.DoesNotExist:
            return Response({"detail": "Ticket not found."}, status=404)

        ticket.assigned_to = request.user
        ticket.status = "in_progress"
        ticket.save(update_fields=["assigned_to", "status", "updated_at"])

        AuditLogService.log_action(
            admin_user=request.user,
            action_type="ticket_assigned",
            target_user_email=ticket.user.email,
            target_reference=str(ticket.id),
            note="Ticket assigned to staff.",
            metadata={"ticket_id": ticket.id},
        )

        return Response(SupportTicketSerializer(ticket).data)


class SupportTicketStatusView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        serializer = TicketStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            ticket = SupportTicket.objects.select_related("user").get(id=pk)
        except SupportTicket.DoesNotExist:
            return Response({"detail": "Ticket not found."}, status=404)

        old_status = ticket.status
        ticket.status = serializer.validated_data["status"]
        ticket.save(update_fields=["status", "updated_at"])

        AuditLogService.log_action(
            admin_user=request.user,
            action_type="ticket_status_changed",
            target_user_email=ticket.user.email,
            target_reference=str(ticket.id),
            note=f"Ticket status changed from {old_status} to {ticket.status}.",
            metadata={
                "ticket_id": ticket.id,
                "old_status": old_status,
                "new_status": ticket.status,
            },
        )

        NotificationService.create_notification(
            user=ticket.user,
            notification_type="system",
            title="Support Ticket Updated",
            message=f"Your ticket #{ticket.id} status is now {ticket.get_status_display()}.",
            metadata={"ticket_id": ticket.id},
        )

        return Response(SupportTicketSerializer(ticket).data)


class SupportTicketPriorityView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        serializer = TicketPriorityUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            ticket = SupportTicket.objects.select_related("user").get(id=pk)
        except SupportTicket.DoesNotExist:
            return Response({"detail": "Ticket not found."}, status=404)

        old_priority = ticket.priority
        ticket.priority = serializer.validated_data["priority"]
        ticket.save(update_fields=["priority", "updated_at"])

        AuditLogService.log_action(
            admin_user=request.user,
            action_type="ticket_priority_changed",
            target_user_email=ticket.user.email,
            target_reference=str(ticket.id),
            note=f"Ticket priority changed from {old_priority} to {ticket.priority}.",
            metadata={
                "ticket_id": ticket.id,
                "old_priority": old_priority,
                "new_priority": ticket.priority,
            },
        )

        return Response(SupportTicketSerializer(ticket).data)

class AdminSupportUnresolvedCountView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        unresolved_count = SupportTicket.objects.filter(
            status__in=["open", "in_progress"]
        ).count()

        return Response({
            "unresolved_count": unresolved_count,
        })
