from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import AuditLog
from .serializers import AuditLogSerializer


class AdminAuditLogListView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        logs = AuditLog.objects.select_related("admin_user").order_by("-created_at")

        search = request.query_params.get("search", "")
        action_type = request.query_params.get("action_type", "all")
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")

        page = int(request.query_params.get("page", 1))
        page_size = int(request.query_params.get("page_size", 20))

        if search:
            logs = (
                logs.filter(admin_user__email__icontains=search)
                | logs.filter(target_user_email__icontains=search)
                | logs.filter(target_reference__icontains=search)
                | logs.filter(note__icontains=search)
            )

        if action_type and action_type != "all":
            logs = logs.filter(action_type=action_type)

        if date_from:
            logs = logs.filter(created_at__date__gte=date_from)

        if date_to:
            logs = logs.filter(created_at__date__lte=date_to)

        total_count = logs.count()
        start = (page - 1) * page_size
        end = start + page_size

        serializer = AuditLogSerializer(logs[start:end], many=True)

        return Response({
            "results": serializer.data,
            "count": total_count,
            "page": page,
            "page_size": page_size,
            "total_pages": (total_count + page_size - 1) // page_size,
        })