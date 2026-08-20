import uuid

from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from transactions.models import Transaction
from wallets.services import WalletService

from .models import ElectricityTransaction
from .serializers import (
    MeterVerificationSerializer,
    ElectricityPurchaseSerializer,
    ElectricityTransactionSerializer,
)
from .services import VTPassElectricityService

from notifications.services import NotificationService


class ElectricityProvidersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        providers = [
            {"name": "Ikeja Electric", "service_id": "ikeja-electric"},
            {"name": "Eko Electric", "service_id": "eko-electric"},
            {"name": "Abuja Electric", "service_id": "abuja-electric"},
            {"name": "Kano Electric", "service_id": "kano-electric"},
            {"name": "Ibadan Electric", "service_id": "ibadan-electric"},
            {"name": "Port Harcourt Electric", "service_id": "portharcourt-electric"},
        ]

        return Response(providers)


class VerifyMeterView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = MeterVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        response = VTPassElectricityService.verify_meter(
            service_id=serializer.validated_data["provider"],
            billers_code=serializer.validated_data["meter_number"],
            meter_type=serializer.validated_data["meter_type"],
        )

        return Response(response)


class ElectricityPurchaseView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ElectricityPurchaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        provider = serializer.validated_data["provider"]
        meter_number = serializer.validated_data["meter_number"]
        meter_type = serializer.validated_data["meter_type"]
        customer_name = serializer.validated_data["customer_name"]
        amount = serializer.validated_data["amount"]

        reference = f"ELECTRICITY-{uuid.uuid4().hex[:16].upper()}"

        with transaction.atomic():
            electricity_tx = ElectricityTransaction.objects.create(
                user=request.user,
                provider=provider,
                meter_number=meter_number,
                meter_type=meter_type,
                customer_name=customer_name,
                amount=amount,
                reference=reference,
                status="pending",
            )

            main_tx = Transaction.objects.create(
                user=request.user,
                service_type="electricity",
                amount=amount,
                reference=reference,
                status="pending",
                provider="vtpass",
                description=f"{provider} electricity purchase",
                metadata={
                    "provider": provider,
                    "meter_number": meter_number,
                    "meter_type": meter_type,
                },
            )

            WalletService.debit_wallet(
                wallet=request.user.wallet,
                amount=amount,
                reference=reference,
                description=f"{provider} electricity payment",
            )

        provider_response = VTPassElectricityService.purchase_electricity(
            request_id=reference,
            service_id=provider,
            billers_code=meter_number,
            variation_code=meter_type,
            amount=amount,
            phone="08000000000",
        )

        print(
            "VTPASS ELECTRICITY PURCHASE RESPONSE:",
            provider_response,
            flush=True,
        )

        is_successful = (
            provider_response.get("code") == "000"
            or provider_response.get("response_description", "").lower() == "transaction successful"
        )

        if is_successful:
            token = (
                provider_response.get("purchased_code")
                or provider_response.get("token")
                or ""
            )

            electricity_tx.status = "success"
            electricity_tx.token = token
            electricity_tx.provider_response = provider_response
            electricity_tx.save(
                update_fields=["status", "token", "provider_response"]
            )

            main_tx.status = "success"
            main_tx.metadata = {
                **main_tx.metadata,
                "token": token,
                "provider_response": provider_response,
            }
            main_tx.save(update_fields=["status", "metadata"])

            NotificationService.create_notification(
                user=request.user,
                notification_type="transaction",
                title="Electricity Purchase Successful",
                message=f"₦{amount} electricity was purchased for {meter_number}.",
            )

            return Response(
                ElectricityTransactionSerializer(electricity_tx).data,
                status=status.HTTP_201_CREATED,
            )

        with transaction.atomic():
            WalletService.credit_wallet(
                wallet=request.user.wallet,
                amount=amount,
                reference=f"REFUND-{reference}",
                description="Refund for failed electricity purchase",
            )

            NotificationService.create_notification(
                user=request.user,
                notification_type="refund",
                title="Wallet Refunded",
                message=f"₦{amount} has been refunded to your wallet.",
            )

            electricity_tx.status = "refunded"
            electricity_tx.provider_response = provider_response
            electricity_tx.save(update_fields=["status", "provider_response"])

            main_tx.status = "refunded"
            main_tx.metadata = {
                **main_tx.metadata,
                "provider_response": provider_response,
            }
            main_tx.save(update_fields=["status", "metadata"])

        return Response(
            {
                "detail": "Electricity purchase failed. Wallet refunded.",
                "provider_response": provider_response,
                "transaction": ElectricityTransactionSerializer(electricity_tx).data,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )