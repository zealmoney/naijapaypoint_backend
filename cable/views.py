import uuid

from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from transactions.models import Transaction
from wallets.services import WalletService

from .models import CableTransaction
from .serializers import (
    CablePlansSerializer,
    CablePurchaseSerializer,
    CableTransactionSerializer,
    CableVerifySerializer,
)
from .services import VTPassCableService
from notifications.services import NotificationService


class CableProvidersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        providers = [
            {"name": "DStv", "service_id": "dstv"},
            {"name": "GOtv", "service_id": "gotv"},
            {"name": "Startimes", "service_id": "startimes"},
            {"name": "Showmax", "service_id": "showmax"},
        ]
        return Response(providers)


class CablePlansView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = CablePlansSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        provider = serializer.validated_data["provider"]
        response = VTPassCableService.get_plans(provider)
        return Response(response)


class CableVerifyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CableVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        response = VTPassCableService.verify_smartcard(
            service_id=serializer.validated_data["provider"],
            smartcard_number=serializer.validated_data["smartcard_number"],
        )
        return Response(response)


class CablePurchaseView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CablePurchaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        provider = serializer.validated_data["provider"]
        smartcard_number = serializer.validated_data["smartcard_number"]
        plan_id = serializer.validated_data["plan_id"]
        plan_name = serializer.validated_data["plan_name"]
        customer_name = serializer.validated_data.get("customer_name", "")
        amount = serializer.validated_data["amount"]

        reference = f"CABLE-{uuid.uuid4().hex[:16].upper()}"

        with transaction.atomic():
            cable_tx = CableTransaction.objects.create(
                user=request.user,
                provider=provider,
                smartcard_number=smartcard_number,
                plan_id=plan_id,
                plan_name=plan_name,
                customer_name=customer_name,
                amount=amount,
                reference=reference,
                status="pending",
            )

            main_tx = Transaction.objects.create(
                user=request.user,
                service_type="cable",
                amount=amount,
                reference=reference,
                status="pending",
                provider="vtpass",
                description=f"{provider.upper()} subscription purchase",
                metadata={
                    "provider": provider,
                    "smartcard_number": smartcard_number,
                    "plan_id": plan_id,
                    "plan_name": plan_name,
                    "customer_name": customer_name,
                },
            )

            WalletService.debit_wallet(
                wallet=request.user.wallet,
                amount=amount,
                reference=reference,
                description=f"{provider.upper()} subscription payment",
            )

        provider_response = VTPassCableService.purchase_subscription(
            request_id=reference,
            service_id=provider,
            smartcard_number=smartcard_number,
            variation_code=plan_id,
            amount=amount,
            phone="08000000000",
        )

        is_successful = (
            provider_response.get("code") == "000"
            or provider_response.get("response_description", "").lower() == "transaction successful"
        )

        if is_successful:
            cable_tx.status = "success"
            cable_tx.provider_response = provider_response
            cable_tx.save(update_fields=["status", "provider_response"])

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
                title="Cable Subscription Successful",
                message=f"₦{amount} cable subscription was purchased for {smartcard_number}.",
            )

            return Response(
                CableTransactionSerializer(cable_tx).data,
                status=status.HTTP_201_CREATED,
            )

        with transaction.atomic():
            WalletService.credit_wallet(
                wallet=request.user.wallet,
                amount=amount,
                reference=f"REFUND-{reference}",
                description="Refund for failed cable subscription",
            )

            NotificationService.create_notification(
                user=request.user,
                notification_type="refund",
                title="Wallet Refunded",
                message=f"₦{amount} has been refunded to your wallet.",
            )

            cable_tx.status = "refunded"
            cable_tx.provider_response = provider_response
            cable_tx.save(update_fields=["status", "provider_response"])

            main_tx.status = "refunded"
            main_tx.metadata = {
                **main_tx.metadata,
                "provider_response": provider_response,
            }
            main_tx.save(update_fields=["status", "metadata"])

        return Response(
            {
                "detail": "Cable subscription failed. Wallet refunded.",
                "provider_response": provider_response,
                "transaction": CableTransactionSerializer(cable_tx).data,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )