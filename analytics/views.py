from django.contrib.auth import get_user_model
from django.db.models import Sum, Count
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from wallets.models import Wallet, WalletTransaction
from transactions.models import Transaction
from referrals.models import Referral, ReferralProfile

from django.utils import timezone
from datetime import timedelta
from support.models import SupportTicket

from guest_checkout.models import GuestTransaction


User = get_user_model()


class AdminAnalyticsView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        total_users = User.objects.count()

        today = timezone.now().date()
        week_start = today - timedelta(days=7)
        month_start = today.replace(day=1)

        total_customers = User.objects.filter(is_staff=False).count()
        total_staff = User.objects.filter(is_staff=True).count()

        registered_revenue_today = (
            Transaction.objects.filter(
                status="success",
                created_at__date=today,
            ).aggregate(total=Sum("amount"))["total"]
            or 0
        )

        guest_revenue_today = (
            GuestTransaction.objects.filter(
                status="success",
                created_at__date=today,
            ).aggregate(total=Sum("amount"))["total"]
            or 0
        )

        revenue_today = registered_revenue_today + guest_revenue_today

        registered_revenue_this_week = (
            Transaction.objects.filter(
                status="success",
                created_at__date__gte=week_start,
                created_at__date__lt=today + timedelta(days=1),
            ).aggregate(total=Sum("amount"))["total"]
            or 0
        )

        guest_revenue_this_week = (
            GuestTransaction.objects.filter(
                status="success",
                created_at__date__gte=week_start,
                created_at__date__lt=today + timedelta(days=1),
            ).aggregate(total=Sum("amount"))["total"]
            or 0
        )

        revenue_this_week = registered_revenue_this_week + guest_revenue_this_week

        registered_revenue_this_month = (
            Transaction.objects.filter(
                status="success",
                created_at__date__gte=month_start,
                created_at__date__lt=today + timedelta(days=1),
            ).aggregate(total=Sum("amount"))["total"]
            or 0
        )

        guest_revenue_this_month = (
            GuestTransaction.objects.filter(
                status="success",
                created_at__date__gte=month_start,
                created_at__date__lt=today + timedelta(days=1),
            ).aggregate(total=Sum("amount"))["total"]
            or 0
        )

        revenue_this_month = registered_revenue_this_month + guest_revenue_this_month

        revenue_today = registered_revenue_today + guest_revenue_today

        wallet_funding_today = WalletTransaction.objects.filter(
            transaction_type="credit",
            created_at__date=today,
        ).aggregate(total=Sum("amount"))["total"] or 0

        failed_today = Transaction.objects.filter(
            status="failed",
            created_at__date=today,
        ).count()

        pending_transactions = (
            Transaction.objects.filter(status="pending").count()
            +
            GuestTransaction.objects.filter(status="pending").count()
        )

        open_support_tickets = SupportTicket.objects.filter(
            status__in=["open", "in_progress"],
        ).count()

        total_wallet_balance = Wallet.objects.aggregate(
            total=Sum("balance")
        )["total"] or 0

        total_wallet_credits = WalletTransaction.objects.filter(
            transaction_type="credit"
        ).aggregate(total=Sum("amount"))["total"] or 0

        total_wallet_debits = WalletTransaction.objects.filter(
            transaction_type="debit"
        ).aggregate(total=Sum("amount"))["total"] or 0

        refunded_transactions = Transaction.objects.filter(status="refunded").count()

        registered_total = Transaction.objects.count()
        guest_total = GuestTransaction.objects.count()

        total_transactions = registered_total + guest_total

        registered_successful = Transaction.objects.filter(
            status="success"
        ).count()

        guest_successful = GuestTransaction.objects.filter(
            status="success"
        ).count()

        successful_transactions = (
            registered_successful + guest_successful
        )

        registered_failed = Transaction.objects.filter(
            status="failed"
        ).count()

        guest_failed = GuestTransaction.objects.filter(
            status="failed"
        ).count()

        failed_transactions = (
            registered_failed + guest_failed
        )

        registered_services = (
            Transaction.objects.values("service_type")
            .annotate(
                count=Count("id"),
                total_amount=Sum("amount"),
            )
        )

        guest_services = (
            GuestTransaction.objects.values("service_type")
            .annotate(
                count=Count("id"),
                total_amount=Sum("amount"),
            )
        )

        combined = {}

        for item in registered_services:
            combined[item["service_type"]] = {
                "service_type": item["service_type"],
                "count": item["count"],
                "total_amount": item["total_amount"] or 0,
            }

        for item in guest_services:
            key = item["service_type"]

            if key not in combined:
                combined[key] = {
                    "service_type": key,
                    "count": 0,
                    "total_amount": 0,
                }

            combined[key]["count"] += item["count"]
            combined[key]["total_amount"] += item["total_amount"] or 0

        service_breakdown = sorted(
            combined.values(),
            key=lambda x: x["service_type"],
        )

        referral_count = Referral.objects.count()
        paid_referrals = Referral.objects.filter(bonus_paid=True).count()

        total_referral_bonus = ReferralProfile.objects.aggregate(
            total=Sum("total_bonus_earned")
        )["total"] or 0

        return Response({
            "users": {
                "total_users": total_users,
            },
            "guest": {
                "transactions": guest_total,
                "successful": guest_successful,
                "failed": guest_failed,
                "revenue_today": guest_revenue_today,
                "revenue_this_week": guest_revenue_this_week,
                "revenue_this_month": guest_revenue_this_month,
            },
            "wallets": {
                "total_wallet_balance": total_wallet_balance,
                "total_wallet_credits": total_wallet_credits,
                "total_wallet_debits": total_wallet_debits,
            },
            "transactions": {
                "total_transactions": total_transactions,
                "successful_transactions": successful_transactions,
                "refunded_transactions": refunded_transactions,
                "failed_transactions": failed_transactions,
                "service_breakdown": list(service_breakdown),
            },
            "referrals": {
                "total_referrals": referral_count,
                "paid_referrals": paid_referrals,
                "total_referral_bonus": total_referral_bonus,
            },
            "kpis": {
                "revenue_today": revenue_today,
                "revenue_this_week": revenue_this_week,
                "revenue_this_month": revenue_this_month,
                "wallet_funding_today": wallet_funding_today,
                "failed_today": failed_today,
                "pending_transactions": pending_transactions,
                "open_support_tickets": open_support_tickets,
                "total_customers": total_customers,
                "total_staff": total_staff,
            },
        })