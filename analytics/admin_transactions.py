from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Q
from django.utils import timezone

from transactions.models import Transaction
from transactions.serializers import TransactionSerializer

from wallets.models import WalletTransaction

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
        "can_refund": tx.status in {
            "pending",
            "processing",
            "failed",
        },
        "can_resolve": (
            tx.status not in {
                "success",
                "refunded",
            }
            and bool(
                (tx.metadata or {}).get(
                    "requires_manual_review",
                    False,
                )
            )
            and not bool(
                (tx.metadata or {}).get(
                    "admin_resolved",
                    False,
                )
            )
        ),
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
        note = request.data.get("note", "").strip()

        try:
            with db_transaction.atomic():
                tx = (
                    Transaction.objects
                    .select_for_update()
                    .select_related("user")
                    .get(reference=reference)
                )

                if tx.status == "refunded":
                    return Response(
                        {
                            "detail": (
                                "Transaction has already been "
                                "refunded."
                            )
                        },
                        status=status.HTTP_409_CONFLICT,
                    )

                if tx.status != "failed":
                    return Response(
                        {
                            "detail": (
                                "Only failed transactions can "
                                "be refunded."
                            )
                        },
                        status=status.HTTP_409_CONFLICT,
                    )

                # Admin wallet refunds are only valid for
                # service-purchase transactions that actually
                # debited the customer's wallet.
                original_debit = (
                    WalletTransaction.objects
                    .select_for_update()
                    .filter(
                        wallet=tx.user.wallet,
                        transaction_type="debit",
                        reference=tx.reference,
                    )
                    .first()
                )

                if original_debit is None:
                    return Response(
                        {
                            "detail": (
                                "Refund blocked because no matching "
                                "original wallet debit was found."
                            )
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                if original_debit.amount != tx.amount:
                    return Response(
                        {
                            "detail": (
                                "Refund blocked because the original "
                                "wallet debit amount does not match "
                                "the transaction amount."
                            )
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                refund_reference = (
                    f"ADMIN-REFUND-{tx.reference}"
                )

                existing_refund = (
                    WalletTransaction.objects
                    .filter(
                        wallet=tx.user.wallet,
                        transaction_type="credit",
                        reference=refund_reference,
                    )
                    .first()
                )

                if existing_refund is not None:
                    return Response(
                        {
                            "detail": (
                                "A refund already exists for this "
                                "transaction."
                            )
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                WalletService.credit_wallet(
                    wallet=tx.user.wallet,
                    amount=tx.amount,
                    reference=refund_reference,
                    description=(
                        "Admin refund for transaction "
                        f"{tx.reference}"
                    ),
                )

                tx.status = "refunded"
                tx.metadata = {
                    **(tx.metadata or {}),
                    "admin_refund": True,
                    "refund_reference": refund_reference,
                    "admin_note": note,
                }
                tx.save(
                    update_fields=[
                        "status",
                        "metadata",
                    ]
                )

                NotificationService.create_notification(
                    user=tx.user,
                    notification_type="refund",
                    title="Transaction Refunded",
                    message=(
                        f"₦{tx.amount} has been refunded "
                        f"for transaction {tx.reference}."
                    ),
                    metadata={
                        "reference": tx.reference,
                        "refund_reference":
                            refund_reference,
                        "amount": str(tx.amount),
                    },
                )

                AuditLogService.log_action(
                    admin_user=request.user,
                    action_type="refund_transaction",
                    target_user_email=tx.user.email,
                    target_reference=tx.reference,
                    note=note,
                    metadata={
                        "amount": str(tx.amount),
                        "refund_reference":
                            refund_reference,
                        "service_type":
                            tx.service_type,
                    },
                )

        except Transaction.DoesNotExist:
            return Response(
                {"detail": "Transaction not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            {
                "detail":
                    "Transaction refunded successfully."
            }
        )

class AdminTransactionResolveView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, reference):
        note = request.data.get(
            "note",
            "",
        ).strip()

        if not note:
            return Response(
                {
                    "detail": (
                        "A resolution note is "
                        "required."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            with db_transaction.atomic():
                tx = (
                    Transaction.objects
                    .select_for_update()
                    .select_related("user")
                    .get(reference=reference)
                )

                metadata = tx.metadata or {}

                if tx.status in {
                    "success",
                    "refunded",
                }:
                    return Response(
                        {
                            "detail": (
                                "Completed transactions "
                                "cannot be marked as "
                                "manually resolved."
                            )
                        },
                        status=status.HTTP_409_CONFLICT,
                    )

                if not metadata.get(
                    "requires_manual_review",
                    False,
                ):
                    return Response(
                        {
                            "detail": (
                                "This transaction does "
                                "not require manual "
                                "review."
                            )
                        },
                        status=status.HTTP_409_CONFLICT,
                    )

                if metadata.get(
                    "admin_resolved",
                    False,
                ):
                    return Response(
                        {
                            "detail": (
                                "This transaction has "
                                "already been marked "
                                "as resolved."
                            )
                        },
                        status=status.HTTP_409_CONFLICT,
                    )

                resolved_at = (
                    timezone.now().isoformat()
                )

                tx.metadata = {
                    **metadata,
                    "admin_resolved": True,
                    "admin_resolved_at":
                        resolved_at,
                    "admin_resolved_by":
                        request.user.email,
                    "admin_resolution_note":
                        note,
                }

                tx.save(
                    update_fields=[
                        "metadata",
                    ]
                )

                AuditLogService.log_action(
                    admin_user=request.user,
                    action_type=(
                        "resolve_transaction"
                    ),
                    target_user_email=tx.user.email,
                    target_reference=tx.reference,
                    note=note,
                    metadata={
                        "service_type":
                            tx.service_type,
                        "amount":
                            str(tx.amount),
                        "transaction_status":
                            tx.status,
                        "requires_manual_review":
                            True,
                    },
                )

        except Transaction.DoesNotExist:
            return Response(
                {
                    "detail":
                        "Transaction not found."
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            {
                "detail": (
                    "Manual review marked as "
                    "resolved."
                )
            }
        )

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
                      "refund_failed",
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
                with database_transaction.atomic():
                    guest_tx = (
                        GuestTransaction.objects
                        .select_for_update()
                        .get(pk=guest_tx.pk)
                    )

                    # A webhook may have completed the refund
                    # before the API request returned.
                    if guest_tx.status == "refunded":
                        return Response(
                            {
                                "detail": "Guest refund already completed.",
                                "transaction_reference": guest_tx.reference,
                                "refund_status": guest_tx.refund_status,
                                "refund_reference": guest_tx.refund_reference,
                            },
                            status=status.HTTP_200_OK,
                        )

                    if guest_tx.status != "refund_pending":
                        return Response(
                            {
                                "detail": (
                                    "Refund state changed. "
                                    "Manual review is required."
                                ),
                            },
                            status=status.HTTP_409_CONFLICT,
                        )

                    if refund_response.get("outcome") == "unknown":
                        guest_tx.status = "refund_pending"
                        guest_tx.refund_status = "manual_review"
                    else:
                        guest_tx.status = "refund_failed"
                        guest_tx.refund_status = "failed"

                    guest_tx.refund_response = {
                        "outcome": (
                            "unknown"
                            if refund_response.get("outcome") == "unknown"
                            else "failed"
                        )
                    }

                    guest_tx.save(
                        update_fields=[
                            "status",
                            "refund_status",
                            "refund_response",
                        ]
                    )

                return Response(
                    {
                        "detail": (
                            "Refund confirmation is unavailable. "
                            "Check Paystack before taking further action."
                            if refund_response.get("outcome") == "unknown"
                            else "Paystack could not initiate the refund."
                        ),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            refund_data = refund_response.get("data") or {}

            # Reacquire the database lock after Paystack responds.
            # The webhook may have completed the refund meanwhile.
            with database_transaction.atomic():
                guest_tx = (
                    GuestTransaction.objects
                    .select_for_update()
                    .get(pk=guest_tx.pk)
                )

                if guest_tx.status == "refunded":
                    return Response(
                        {
                            "detail": "Guest refund already completed.",
                            "transaction_reference": guest_tx.reference,
                            "refund_status": guest_tx.refund_status,
                            "refund_reference": guest_tx.refund_reference,
                        },
                        status=status.HTTP_200_OK,
                    )

                if guest_tx.status != "refund_pending":
                    return Response(
                        {
                            "detail": (
                                "Refund state changed while Paystack "
                                "was processing the request. "
                                "Manual review is required."
                            ),
                        },
                        status=status.HTTP_409_CONFLICT,
                    )

                guest_tx.status = "refund_pending"
                guest_tx.refund_status = (
                    refund_data.get("status") or "pending"
                )
                guest_tx.refund_reference = str(
                    refund_data.get("id") or ""
                )
                # Retain only the information needed for reconciliation.
                # Never persist the full Paystack response.
                guest_tx.refund_response = {
                    "result": "initiated",
                    "refund_reference": str(
                        refund_data.get("id") or ""
                    ),
                    "refund_status": str(
                        refund_data.get("status") or "pending"
                    ),
                }

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

        except Exception:
            return Response(
                {
                    "detail": (
                        "Unable to process guest refund. "
                        "Check the transaction and Paystack refund status "
                        "before attempting another action."
                    ),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )