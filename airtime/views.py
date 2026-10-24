from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from transactions.models import Transaction
from wallets.services import WalletService
from wallets.models import WalletTransaction

from .models import AirtimeTransaction
from .serializers import (
    AirtimePurchaseSerializer,
    AirtimeTransactionSerializer,
)
from .services import VTPassAirtimeService

from notifications.services import NotificationService

from common.vtpass_request_id import generate_vtpass_request_id
from common.transaction_status import (
    classify_vtpass_response,
    sanitize_vtpass_response,
)

import logging

logger = logging.getLogger(__name__)


class AirtimePurchaseView(APIView):
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _refund_pending_transaction(
        *,
        airtime_tx,
        main_tx,
        amount,
        reference,
        provider_response,
        refund_message,
    ):
        with transaction.atomic():
            airtime_tx = (
                AirtimeTransaction.objects
                .select_for_update()
                .get(pk=airtime_tx.pk)
            )

            main_tx = (
                Transaction.objects
                .select_for_update()
                .get(pk=main_tx.pk)
            )

            if (
                airtime_tx.status != "pending"
                or main_tx.status != "pending"
            ):
                return (
                    airtime_tx,
                    main_tx,
                    False,
                )

            original_debit_exists = (
                WalletTransaction.objects.filter(
                    wallet__user=airtime_tx.user,
                    reference=reference,
                    transaction_type="debit",
                    amount=amount,
                ).exists()
            )

            if not original_debit_exists:
                return (
                    airtime_tx,
                    main_tx,
                    False,
                )

            refund_reference = (
                f"REFUND-{reference}"
            )

            WalletService.credit_wallet(
                wallet=airtime_tx.user.wallet,
                amount=amount,
                reference=refund_reference,
                description=refund_message,
            )

            airtime_tx.status = "refunded"
            airtime_tx.provider_response = (
                provider_response
            )
            airtime_tx.save(
                update_fields=[
                    "status",
                    "provider_response",
                ]
            )

            main_tx.status = "refunded"
            main_tx.metadata = {
                **(main_tx.metadata or {}),
                "refund_reference":
                    refund_reference,
                "requires_requery": False,
                "requires_manual_review":
                    False,
            }
            main_tx.save(
                update_fields=[
                    "status",
                    "metadata",
                ]
            )

        return (
            airtime_tx,
            main_tx,
            True,
        )

    @staticmethod
    def _mark_pending_transaction_success(
        *,
        airtime_tx,
        main_tx,
    ):
        with transaction.atomic():
            airtime_tx = (
                AirtimeTransaction.objects
                .select_for_update()
                .get(pk=airtime_tx.pk)
            )

            main_tx = (
                Transaction.objects
                .select_for_update()
                .get(pk=main_tx.pk)
            )

            if (
                airtime_tx.status != "pending"
                or main_tx.status != "pending"
            ):
                return (
                    airtime_tx,
                    main_tx,
                    False,
                )

            airtime_tx.status = "success"
            airtime_tx.save(
                update_fields=["status"]
            )

            main_tx.status = "success"
            main_tx.save(
                update_fields=["status"]
            )

        return (
            airtime_tx,
            main_tx,
            True,
        )

    def post(self, request):
        serializer = AirtimePurchaseSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        network = serializer.validated_data["network"]
        phone_number = serializer.validated_data[
            "phone_number"
        ]
        amount = serializer.validated_data["amount"]

        reference = generate_vtpass_request_id(
            "AIRTIME"
        )

        # -------------------------------------------------
        # Create pending records and debit wallet first.
        # -------------------------------------------------

        with transaction.atomic():
            airtime_tx = AirtimeTransaction.objects.create(
                user=request.user,
                network=network,
                phone_number=phone_number,
                amount=amount,
                reference=reference,
                status="pending",
            )

            main_tx = Transaction.objects.create(
                user=request.user,
                service_type="airtime",
                amount=amount,
                reference=reference,
                status="pending",
                provider="vtpass",
                description=(
                    f"{network.upper()} airtime "
                    f"purchase for {phone_number}"
                ),
                metadata={
                    "network": network,
                    "phone_number": phone_number,
                },
            )

            WalletService.debit_wallet(
                wallet=request.user.wallet,
                amount=amount,
                reference=reference,
                description=(
                    f"{network.upper()} airtime purchase"
                ),
            )

        # -------------------------------------------------
        # Send purchase request to VTPass.
        # -------------------------------------------------

        try:
            provider_response = (
                VTPassAirtimeService.purchase_airtime(
                    request_id=reference,
                    service_id=network,
                    phone=phone_number,
                    amount=amount,
                )
            )

        except Exception:
            logger.warning(
                "VTPass airtime purchase outcome could not be "
                "confirmed for reference %s.",
                reference,
            )

            # The provider outcome is uncertain.
            # Never persist raw exception details.
            # Do not refund without confirmation.
            provider_response = {
                "response_description": (
                    "Provider request failed"
                ),
            }

        # -------------------------------------------------
        # Classify provider response.
        # -------------------------------------------------

        provider_result = classify_vtpass_response(
            provider_response
        )

        # Persist only sanitized provider information.
        sanitized_response = sanitize_vtpass_response(
            provider_response
        )

        airtime_tx.provider_response = sanitized_response
        airtime_tx.save(
            update_fields=["provider_response"]
        )

        main_tx.metadata = {
            **(main_tx.metadata or {}),
            "provider_response": sanitized_response,
            "provider_result": provider_result,
        }

        provider_reference = (
            provider_response.get("requestId")
            if isinstance(provider_response, dict)
            else None
        )

        if provider_reference:
            main_tx.provider_reference = (
                provider_reference
            )

            main_tx.save(
                update_fields=[
                    "provider_reference",
                    "metadata",
                ]
            )
        else:
            main_tx.save(
                update_fields=["metadata"]
            )

        # -------------------------------------------------
        # SUCCESS
        # -------------------------------------------------

        if provider_result == "success":
            (
                airtime_tx,
                main_tx,
                marked_success,
            ) = self._mark_pending_transaction_success(
                airtime_tx=airtime_tx,
                main_tx=main_tx,
            )

            if not marked_success:
                return Response(
                    {
                        "detail": (
                            "Airtime transaction state "
                            "changed before the success "
                            "result could be applied."
                        ),
                        "reference": reference,
                        "status": main_tx.status,
                    },
                    status=status.HTTP_409_CONFLICT,
                )

            NotificationService.create_notification(
                user=request.user,
                notification_type="transaction",
                title="Airtime Purchase Successful",
                message=(
                    f"₦{amount} airtime was purchased "
                    f"for {phone_number}."
                ),
                metadata={
                    "reference": reference,
                    "service_type": "airtime",
                    "amount": str(amount),
                },
            )

            return Response(
                AirtimeTransactionSerializer(
                    airtime_tx
                ).data,
                status=status.HTTP_201_CREATED,
            )

        # -------------------------------------------------
        # PENDING / MANUAL REVIEW
        #
        # Do NOT refund.
        # Reconciliation will determine final status.
        # -------------------------------------------------

        if provider_result in (
            "pending",
            "manual_review",
        ):
            return Response(
                {
                    "detail": (
                        "Airtime purchase is being "
                        "processed. Please check the "
                        "transaction status shortly."
                    ),
                    "provider_result": provider_result,
                    "transaction": (
                        AirtimeTransactionSerializer(
                            airtime_tx
                        ).data
                    ),
                },
                status=status.HTTP_202_ACCEPTED,
            )

        # -------------------------------------------------
        # CONFIRMED FAILURE
        #
        # Only now is it safe to refund.
        # -------------------------------------------------

        (
            airtime_tx,
            main_tx,
            refunded,
        ) = self._refund_pending_transaction(
            airtime_tx=airtime_tx,
            main_tx=main_tx,
            amount=amount,
            reference=reference,
            provider_response=sanitized_response,
            refund_message=(
                "Refund for failed "
                f"{network.upper()} airtime purchase"
            ),
        )

        if refunded:
            NotificationService.create_notification(
                user=request.user,
                notification_type="refund",
                title="Wallet Refunded",
                message=(
                    f"₦{amount} has been refunded "
                    "for failed airtime purchase."
                ),
                metadata={
                    "reference": reference,
                    "refund_reference":
                        f"REFUND-{reference}",
                    "service_type": "airtime",
                    "amount": str(amount),
                },
            )

        if not refunded:
            return Response(
                {
                    "detail": (
                        "Airtime transaction state "
                        "changed before the refund "
                        "could be applied. No duplicate "
                        "refund was issued."
                    ),
                    "reference": reference,
                    "status": main_tx.status,
                    "provider_result":
                        provider_result,
                    "transaction": (
                        AirtimeTransactionSerializer(
                            airtime_tx
                        ).data
                    ),
                },
                status=status.HTTP_409_CONFLICT,
            )

        return Response(
            {
                "detail": (
                    "Airtime purchase failed. "
                    "Wallet has been refunded."
                ),
                "provider_result": provider_result,
                "transaction": (
                    AirtimeTransactionSerializer(
                        airtime_tx
                    ).data
                ),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )