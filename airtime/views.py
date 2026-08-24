from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from transactions.models import Transaction
from wallets.services import WalletService

from .models import AirtimeTransaction
from .serializers import (
    AirtimePurchaseSerializer,
    AirtimeTransactionSerializer,
)
from .services import VTPassAirtimeService

from notifications.services import NotificationService

from common.vtpass_request_id import generate_vtpass_request_id
from common.transaction_status import classify_vtpass_response


class AirtimePurchaseView(APIView):
    permission_classes = [IsAuthenticated]

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

            print(
                "VTPASS AIRTIME PURCHASE RESPONSE:",
                provider_response,
            )

        except Exception as error:
            print(
                "VTPASS AIRTIME EXCEPTION:",
                str(error),
            )

            # IMPORTANT:
            # We do NOT refund here because we do not know
            # whether VTPass processed the transaction.
            provider_response = {
                "error": str(error),
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

        print(
            "VTPASS AIRTIME RESULT:",
            provider_result,
        )

        # Always preserve provider response.
        airtime_tx.provider_response = provider_response
        airtime_tx.save(
            update_fields=["provider_response"]
        )

        main_tx.metadata = {
            **main_tx.metadata,
            "provider_response": provider_response,
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
            airtime_tx.status = "success"
            airtime_tx.save(
                update_fields=["status"]
            )

            main_tx.status = "success"
            main_tx.save(
                update_fields=["status"]
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
                    "provider_response": provider_response,
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

        refund_reference = f"REFUND-{reference}"

        with transaction.atomic():
            WalletService.credit_wallet(
                wallet=request.user.wallet,
                amount=amount,
                reference=refund_reference,
                description=(
                    "Refund for failed "
                    f"{network.upper()} airtime purchase"
                ),
            )

            airtime_tx.status = "refunded"
            airtime_tx.save(
                update_fields=["status"]
            )

            main_tx.status = "refunded"
            main_tx.metadata = {
                **main_tx.metadata,
                "refund_reference": refund_reference,
            }

            main_tx.save(
                update_fields=[
                    "status",
                    "metadata",
                ]
            )

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
                    "refund_reference": (
                        refund_reference
                    ),
                    "service_type": "airtime",
                    "amount": str(amount),
                },
            )

        return Response(
            {
                "detail": (
                    "Airtime purchase failed. "
                    "Wallet has been refunded."
                ),
                "provider_result": provider_result,
                "provider_response": provider_response,
                "transaction": (
                    AirtimeTransactionSerializer(
                        airtime_tx
                    ).data
                ),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )