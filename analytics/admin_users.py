from django.contrib.auth import get_user_model
from django.db.models import Sum
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from transactions.models import Transaction
from wallets.models import Wallet

from audit_logs.services import AuditLogService


User = get_user_model()


def paginate_queryset(queryset, page, page_size):
    total_count = queryset.count()
    start = (page - 1) * page_size
    end = start + page_size

    return {
        "items": queryset[start:end],
        "count": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": (total_count + page_size - 1) // page_size,
    }


def build_user_summary(user):
    wallet, _ = Wallet.objects.get_or_create(user=user)

    total_transactions = Transaction.objects.filter(user=user).count()

    total_spent = (
        Transaction.objects.filter(user=user, status="success").aggregate(
            total=Sum("amount")
        )["total"]
        or 0
    )

    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "phone_number": getattr(user, "phone_number", ""),
        "is_active": user.is_active,
        "is_staff": user.is_staff,
        "is_superuser": user.is_superuser,
        "date_joined": user.date_joined,
        "wallet_balance": wallet.balance,
        "total_transactions": total_transactions,
        "total_spent": total_spent,
    }


class AdminCustomerListView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        search = request.query_params.get("search", "")
        page = int(request.query_params.get("page", 1))
        page_size = int(request.query_params.get("page_size", 20))

        users = User.objects.filter(is_staff=False).order_by("-date_joined")

        if search:
            users = users.filter(email__icontains=search) | users.filter(
                username__icontains=search
            )

        paginated = paginate_queryset(users, page, page_size)

        return Response(
            {
                "results": [
                    build_user_summary(user) for user in paginated["items"]
                ],
                "count": paginated["count"],
                "page": paginated["page"],
                "page_size": paginated["page_size"],
                "total_pages": paginated["total_pages"],
            }
        )


class AdminStaffListView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        search = request.query_params.get("search", "")
        page = int(request.query_params.get("page", 1))
        page_size = int(request.query_params.get("page_size", 20))

        if not request.user.is_superuser:
            return Response(
                {"detail": "Only super admins can view staff accounts."},
                status=403,
            )

        users = User.objects.filter(is_staff=True).order_by("-date_joined")

        if search:
            users = users.filter(email__icontains=search) | users.filter(
                username__icontains=search
            )

        paginated = paginate_queryset(users, page, page_size)

        return Response(
            {
                "results": [
                    build_user_summary(user) for user in paginated["items"]
                ],
                "count": paginated["count"],
                "page": paginated["page"],
                "page_size": paginated["page_size"],
                "total_pages": paginated["total_pages"],
            }
        )


class AdminUserListView(APIView):
    """
    Kept for backward compatibility.
    Returns all users.
    """

    permission_classes = [IsAdminUser]

    def get(self, request):
        search = request.query_params.get("search", "")
        page = int(request.query_params.get("page", 1))
        page_size = int(request.query_params.get("page_size", 20))

        users = User.objects.all().order_by("-date_joined")

        if search:
            users = users.filter(email__icontains=search) | users.filter(
                username__icontains=search
            )

        paginated = paginate_queryset(users, page, page_size)

        return Response(
            {
                "results": [
                    build_user_summary(user) for user in paginated["items"]
                ],
                "count": paginated["count"],
                "page": paginated["page"],
                "page_size": paginated["page_size"],
                "total_pages": paginated["total_pages"],
            }
        )


class AdminUserDetailView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request, user_id):
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({"detail": "User not found."}, status=404)

        wallet, _ = Wallet.objects.get_or_create(user=user)

        transactions = Transaction.objects.filter(user=user).order_by(
            "-created_at"
        )[:10]

        return Response(
            {
                **build_user_summary(user),
                "wallet_balance": wallet.balance,
                "recent_transactions": [
                    {
                        "id": tx.id,
                        "reference": tx.reference,
                        "service_type": tx.service_type,
                        "amount": tx.amount,
                        "status": tx.status,
                        "created_at": tx.created_at,
                    }
                    for tx in transactions
                ],
            }
        )

        if user.is_staff and not request.user.is_superuser:
            return Response(
                {"detail": "Only super admins can view staff accounts."},
                status=403,
            )


class AdminUserToggleActiveView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, user_id):
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({"detail": "User not found."}, status=404)

        if user == request.user:
            return Response(
                {"detail": "You cannot suspend your own account."},
                status=400,
            )

        if user.is_superuser and not request.user.is_superuser:
            return Response(
                {"detail": "Only a super admin can modify another super admin."},
                status=403,
            )

        user.is_active = not user.is_active
        user.save(update_fields=["is_active"])

        if user.is_staff and not request.user.is_superuser:
            return Response(
                {"detail": "Only super admins can modify staff accounts."},
                status=403,
            )

        AuditLogService.log_action(
            admin_user=request.user,
            action_type="activate_user" if user.is_active else "suspend_user",
            target_user_email=user.email,
            note="User account status changed by admin.",
            metadata={
                "user_id": user.id,
                "is_active": user.is_active,
            },
        )

        return Response(
            {
                "detail": "User status updated.",
                "is_active": user.is_active,
            }
        )


class AdminMakeStaffView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, user_id):
        if not request.user.is_superuser:
            return Response(
                {"detail": "Only a super admin can promote staff."},
                status=403,
            )

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({"detail": "User not found."}, status=404)

        user.is_staff = True
        user.save(update_fields=["is_staff"])

        AuditLogService.log_action(
            admin_user=request.user,
            action_type="promote_staff",
            target_user_email=user.email,
            note="User promoted to staff.",
            metadata={
                "user_id": user.id,
            },
        )

        return Response({"detail": "User promoted to staff."})


class AdminRemoveStaffView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, user_id):
        if not request.user.is_superuser:
            return Response(
                {"detail": "Only a super admin can remove staff."},
                status=403,
            )

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({"detail": "User not found."}, status=404)

        if user == request.user:
            return Response(
                {"detail": "You cannot remove your own staff access."},
                status=400,
            )

        if user.is_superuser:
            return Response(
                {"detail": "Super admin status cannot be removed here."},
                status=400,
            )

        user.is_staff = False
        user.save(update_fields=["is_staff"])

        AuditLogService.log_action(
            admin_user=request.user,
            action_type="remove_staff",
            target_user_email=user.email,
            note="Staff access removed.",
            metadata={
                "user_id": user.id,
            },
        )

        return Response({"detail": "Staff access removed."})