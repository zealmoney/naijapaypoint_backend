import uuid

from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from transactions.models import Transaction
from wallets.services import WalletService

from .models import AirtimeTransaction
from .serializers import AirtimePurchaseSerializer, AirtimeTransactionSerializer
from .services import VTPassAirtimeService

from notifications.services import NotificationService


class AirtimePurchaseView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = AirtimePurchaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        network = serializer.validated_data["network"]
        phone_number = serializer.validated_data["phone_number"]
        amount = serializer.validated_data["amount"]
        reference = f"AIRTIME-{uuid.uuid4().hex[:16].upper()}"

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
                description=f"{network.upper()} airtime purchase for {phone_number}",
                metadata={
                    "network": network,
                    "phone_number": phone_number,
                },
            )

            WalletService.debit_wallet(
                wallet=request.user.wallet,
                amount=amount,
                reference=reference,
                description=f"{network.upper()} airtime purchase",
            )

        try:
            provider_response = VTPassAirtimeService.purchase_airtime(
                request_id=reference,
                service_id=network,
                phone=phone_number,
                amount=amount,
            )
        except Exception as error:
            print("VTPASS AIRTIME EXCEPTION:", str(error))

            provider_response = {
                "error": str(error),
                "response_description": "Provider request failed",
            }

        is_successful = (
            provider_response.get("code") == "000"
            or provider_response.get("response_description", "").lower()
            == "transaction successful"
        )

        if is_successful:
            airtime_tx.status = "success"
            airtime_tx.provider_response = provider_response
            airtime_tx.save(update_fields=["status", "provider_response"])

            main_tx.status = "success"
            main_tx.provider_reference = provider_response.get("requestId") or reference
            main_tx.metadata = {
                **main_tx.metadata,
                "provider_response": provider_response,
            }
            main_tx.save(update_fields=["status", "provider_reference", "metadata"])

            NotificationService.create_notification(
                user=request.user,
                notification_type="transaction",
                title="Airtime Purchase Successful",
                message=f"₦{amount} airtime was purchased for {phone_number}.",
                metadata={
                    "reference": reference,
                    "service_type": "airtime",
                    "amount": str(amount),
                },
            )

            return Response(
                AirtimeTransactionSerializer(airtime_tx).data,
                status=status.HTTP_201_CREATED,
            )

        refund_reference = f"REFUND-{reference}"

        with transaction.atomic():
            WalletService.credit_wallet(
                wallet=request.user.wallet,
                amount=amount,
                reference=refund_reference,
                description=f"Refund for failed {network.upper()} airtime purchase",
            )

            NotificationService.create_notification(
                user=request.user,
                notification_type="refund",
                title="Wallet Refunded",
                message=f"₦{amount} has been refunded for failed airtime purchase.",
                metadata={
                    "reference": reference,
                    "refund_reference": f"REFUND-{reference}",
                    "service_type": "airtime",
                    "amount": str(amount),
                },
            )

            airtime_tx.status = "refunded"
            airtime_tx.provider_response = provider_response
            airtime_tx.save(update_fields=["status", "provider_response"])

            main_tx.status = "refunded"
            main_tx.metadata = {
                **main_tx.metadata,
                "provider_response": provider_response,
                "refund_reference": refund_reference,
            }
            main_tx.save(update_fields=["status", "metadata"])

        return Response(
            {
                "detail": "Airtime purchase failed. Wallet has been refunded.",
                "provider_response": provider_response,
                "transaction": AirtimeTransactionSerializer(airtime_tx).data,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )