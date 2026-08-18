from rest_framework import serializers

from .models import SupportTicket, TicketReply


class TicketReplySerializer(serializers.ModelSerializer):
    author_email = serializers.EmailField(source="author.email", read_only=True)

    class Meta:
        model = TicketReply
        fields = [
            "id",
            "author_email",
            "message",
            "is_staff_reply",
            "created_at",
        ]


class SupportTicketSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)
    assigned_to_email = serializers.EmailField(source="assigned_to.email", read_only=True)
    category_display = serializers.CharField(source="get_category_display", read_only=True)
    ticket_number = serializers.CharField(read_only=True)
    replies = TicketReplySerializer(many=True, read_only=True)
    

    class Meta:
        model = SupportTicket
        fields = [
            "id",
            "ticket_number",
            "user_email",
            "subject",
            "message",
            "category",
            "category_display",
            "related_reference",
            "status",
            "priority",
            "assigned_to",
            "assigned_to_email",
            "replies",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["user", "assigned_to"]


class TicketReplyCreateSerializer(serializers.Serializer):
    message = serializers.CharField(trim_whitespace=True, allow_blank=False)


class TicketStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=SupportTicket.STATUS_CHOICES)


class TicketPriorityUpdateSerializer(serializers.Serializer):
    priority = serializers.ChoiceField(choices=SupportTicket.PRIORITY_CHOICES)
