from django.contrib import admin

from .models import SupportTicket, TicketReply


class TicketReplyInline(admin.TabularInline):
    model = TicketReply
    extra = 0


@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "subject",
        "category",
        "user",
        "status",
        "priority",
        "assigned_to",
        "ticket_number",
        "created_at",
    )
    list_filter = ("category", "status", "priority", "created_at")
    search_fields = ("ticket_number","subject", "message", "user__email", "related_reference")
    inlines = [TicketReplyInline]


@admin.register(TicketReply)
class TicketReplyAdmin(admin.ModelAdmin):
    list_display = ("ticket", "author", "is_staff_reply", "created_at")
    search_fields = ("message", "author__email")
