from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Q

from transactions.models import Transaction
from transactions.serializers import TransactionSerializer

from django.db import transaction as db_transaction
from rest_framework import status
from wallets.services import WalletService
from notifications.services import NotificationService

from audit_logs.services import AuditLogService
from django.db import transaction as database_transaction
from guest_checkout.models import GuestTransaction
from payments.services import PaystackService

def serialize_registered_transaction(tx):
    return {
        "id": tx.id,
        "reference": tx.reference,
        "source": "registered",
        "customer_email": tx.user.email if tx.user else "",
        "customer_name": (
            tx.user.get_full_name()
            if tx.user and hasattr(tx.user, "get_full_name")
            else ""
        ),
        "service_type": tx.service_type,
        "provider": tx.provider,
        "description": tx.description,
        "amount": tx.amount,
        "status": tx.status,
        "provider_reference": tx.provider_reference,
        "created_at": tx.created_at,
        "updated_at": tx.updated_at,
        "metadata": tx.metadata or {},
        "can_refund": tx.status not in {"refunded"},
    }


def serialize_guest_transaction(tx):
    return {
        "id": tx.id,
        "reference": tx.reference,
        "source": "guest",
        "customer_email": tx.guest_email,
        "customer_name": tx.customer_name,
        "customer_phone": tx.guest_phone,
        "service_type": tx.service_type,
        "provider": tx.provider,
        "description": (
            f"Guest {tx.service_type} purchase for {tx.recipient}"
        ),
        "amount": tx.amount,
        "status": tx.status,
        "provider_reference": tx.provider_reference,
        "created_at": tx.created_at,
        "updated_at": tx.updated_at,
        "metadata": tx.metadata or {},
        "provider_response": tx.provider_response or {},
        "recipient": tx.recipient,
        "variation_code": tx.variation_code,
        "plan_name": tx.plan_name,
        "token": tx.token,
        "refund_status": getattr(tx, "refund_status", ""),
        "refund_reference": getattr(tx, "refund_reference", ""),
        "can_refund": tx.status in {
            "failed",
            "paid",
            "refund_failed",
        },
    }

class AdminTransactionListView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        search = request.query_params.get("search", "").strip()
        status_filter = request.query_params.get("status", "all")
        service_filter = request.query_params.get(
            "service_type",
            "all",
        )
        source_filter = request.query_params.get("source", "all")

        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")

        try:
            page = max(
                int(request.query_params.get("page", 1)),
                1,
            )
            page_size = min(
                max(
                    int(
                        request.query_params.get(
                            "page_size",
                            20,
                        )
                    ),
                    1,
                ),
                100,
            )
        except ValueError:
            return Response(
                {
                    "detail": (
                        "Page and page size must be valid numbers."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        registered_transactions = (
            Transaction.objects
            .select_related("user")
            .all()
        )

        guest_transactions = GuestTransaction.objects.all()

        if search:
            registered_transactions = (
                registered_transactions.filter(
                    Q(reference__icontains=search)
                    | Q(user__email__icontains=search)
                    | Q(description__icontains=search)
                )
            )

            guest_transactions = guest_transactions.filter(
                Q(reference__icontains=search)
                | Q(guest_email__icontains=search)
                | Q(guest_phone__icontains=search)
                | Q(recipient__icontains=search)
                | Q(customer_name__icontains=search)
            )

        if status_filter != "all":
            registered_transactions = (
                registered_transactions.filter(
                    status=status_filter
                )
            )
            guest_transactions = guest_transactions.filter(
                status=status_filter
            )

        if service_filter != "all":
            registered_transactions = (
                registered_transactions.filter(
                    service_type=service_filter
                )
            )
            guest_transactions = guest_transactions.filter(
                service_type=service_filter
            )

        if date_from:
            registered_transactions = (
                registered_transactions.filter(
                    created_at__date__gte=date_from
                )
            )
            guest_transactions = guest_transactions.filter(
                created_at__date__gte=date_from
            )

        if date_to:
            registered_transactions = (
                registered_transactions.filter(
                    created_at__date__lte=date_to
                )
            )
            guest_transactions = guest_transactions.filter(
                created_at__date__lte=date_to
            )

        results = []

        if source_filter in {"all", "registered"}:
            results.extend(
                serialize_registered_transaction(tx)
                for tx in registered_transactions
            )

        if source_filter in {"all", "guest"}:
            results.extend(
                serialize_guest_transaction(tx)
                for tx in guest_transactions
            )

        results.sort(
            key=lambda item: item["created_at"],
            reverse=True,
        )

        total_count = len(results)
        start = (page - 1) * page_size
        end = start + page_size

        return Response(
            {
                "results": results[start:end],
                "count": total_count,
                "page": page,
                "page_size": page_size,
                "total_pages": (
                    total_count + page_size - 1
                ) // page_size,
            }
        )

class AdminTransactionDetailView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request, reference):
        try:
            registered_tx = (
                Transaction.objects
                .select_related("user")
                .get(reference=reference)
            )

            return Response(
                serialize_registered_transaction(
                    registered_tx
                )
            )

        except Transaction.DoesNotExist:
            pass

        try:
            guest_tx = GuestTransaction.objects.get(
                reference=reference
            )

            return Response(
                serialize_guest_transaction(guest_tx)
            )

        except GuestTransaction.DoesNotExist:
            return Response(
                {"detail": "Transaction not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

class AdminTransactionRefundView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, reference):
        try:
            tx = Transaction.objects.select_related("user").get(reference=reference)
        except Transaction.DoesNotExist:
            return Response({"detail": "Transaction not found."}, status=404)

        if tx.status == "refunded":
            return Response(
                {"detail": "Transaction already refunded."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        refund_reference = f"ADMIN-REFUND-{tx.reference}"

        with db_transaction.atomic():
            WalletService.credit_wallet(
                wallet=tx.user.wallet,
                amount=tx.amount,
                reference=refund_reference,
                description=f"Admin refund for transaction {tx.reference}",
            )

            tx.status = "refunded"
            tx.metadata = {
                **(tx.metadata or {}),
                "admin_refund": True,
                "refund_reference": refund_reference,
                "admin_note": request.data.get("note", ""),
            }
            tx.save(update_fields=["status", "metadata"])

            NotificationService.create_notification(
                user=tx.user,
                notification_type="refund",
                title="Transaction Refunded",
                message=f"₦{tx.amount} has been refunded for transaction {tx.reference}.",
                metadata={
                    "reference": tx.reference,
                    "refund_reference": refund_reference,
                    "amount": str(tx.amount),
                },
            )

            AuditLogService.log_action(
                admin_user=request.user,
                action_type="refund_transaction",
                target_user_email=tx.user.email,
                target_reference=tx.reference,
                note=request.data.get("note", ""),
                metadata={
                    "amount": str(tx.amount),
                    "refund_reference": refund_reference,
                    "service_type": tx.service_type,
                },
            )

        return Response({"detail": "Transaction refunded successfully."})


class AdminTransactionResolveView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, reference):
        try:
            tx = Transaction.objects.get(reference=reference)
        except Transaction.DoesNotExist:
            return Response({"detail": "Transaction not found."}, status=404)

        tx.metadata = {
            **(tx.metadata or {}),
            "admin_resolved": True,
            "admin_note": request.data.get("note", ""),
        }
        tx.save(update_fields=["metadata"])

        AuditLogService.log_action(
            admin_user=request.user,
            action_type="resolve_transaction",
            target_user_email=tx.user.email,
            target_reference=tx.reference,
            note=request.data.get("note", ""),
            metadata={
                "service_type": tx.service_type,
                "amount": str(tx.amount),
            },
        )

        return Response({"detail": "Transaction marked as resolved."})

class AdminGuestTransactionRefundView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, reference):
        note = request.data.get("note", "").strip()

        try:
            with database_transaction.atomic():
                guest_tx = (
                    GuestTransaction.objects
                    .select_for_update()
                    .get(reference=reference)
                )

                if guest_tx.status == "success":
                    return Response(
                        {
                            "detail": (
                                "This guest purchase is marked successful. "
                                "Confirm the service was not delivered "
                                "before refunding."
                            )
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                if guest_tx.status in {
                    "refund_pending",
                    "refunded",
                }:
                    return Response(
                        {
                            "detail": (
                                "A refund has already been initiated "
                                "for this transaction."
                            )
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                if guest_tx.status not in {
                    "failed",
                    "paid",
                }:
                    return Response(
                        {
                            "detail": (
                                "Only paid or failed guest transactions "
                                "can be refunded."
                            )
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                guest_tx.status = "refund_pending"
                guest_tx.refund_amount = guest_tx.amount
                guest_tx.save(
                    update_fields=[
                        "status",
                        "refund_amount",
                    ]
                )

            refund_response = PaystackService.create_refund(
                transaction_reference=guest_tx.payment_reference,
                amount=guest_tx.amount,
                customer_note=(
                    "Refund for unsuccessful NaijaPayPoint purchase."
                ),
                merchant_note=(
                    note or f"Admin refund for {guest_tx.reference}"
                ),
            )

            if not refund_response.get("status"):
                guest_tx.status = "refund_failed"
                guest_tx.refund_status = "failed"
                guest_tx.refund_response = refund_response
                guest_tx.save(
                    update_fields=[
                        "status",
                        "refund_status",
                        "refund_response",
                    ]
                )

                return Response(
                    {
                        "detail": refund_response.get(
                            "message",
                            "Unable to initiate Paystack refund.",
                        ),
                        "refund_response": refund_response,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            refund_data = refund_response.get("data") or {}

            guest_tx.status = "refund_pending"
            guest_tx.refund_status = (
                refund_data.get("status") or "pending"
            )
            guest_tx.refund_reference = str(
                refund_data.get("id") or ""
            )
            guest_tx.refund_response = refund_response

            guest_tx.save(
                update_fields=[
                    "status",
                    "refund_status",
                    "refund_reference",
                    "refund_response",
                ]
            )

            AuditLogService.log_action(
                admin_user=request.user,
                action_type="refund_guest_transaction",
                target_user_email=guest_tx.guest_email,
                target_reference=guest_tx.reference,
                note=note,
                metadata={
                    "amount": str(guest_tx.amount),
                    "service_type": guest_tx.service_type,
                    "paystack_reference": (
                        guest_tx.payment_reference
                    ),
                    "refund_reference": (
                        guest_tx.refund_reference
                    ),
                },
            )

            return Response(
                {
                    "detail": "Guest refund queued successfully.",
                    "transaction_reference": guest_tx.reference,
                    "refund_status": guest_tx.refund_status,
                    "refund_reference": guest_tx.refund_reference,
                },
                status=status.HTTP_200_OK,
            )

        except GuestTransaction.DoesNotExist:
            return Response(
                {"detail": "Guest transaction not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        except Exception as exc:
            return Response(
                {
                    "detail": "Unable to process guest refund.",
                    "error": str(exc),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )