import uuid

from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from transactions.models import Transaction
from wallets.services import WalletService

from .models import DataTransaction
from .serializers import (
    DataPurchaseSerializer,
    DataTransactionSerializer,
)
from .services import VTPassDataService

from notifications.services import NotificationService


class DataPlansView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        network = request.query_params.get("network")

        if not network:
            return Response(
                {"detail": "Network is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            response = VTPassDataService.get_data_plans(network)
        except Exception as error:
            return Response(
                {
                    "detail": "Unable to fetch data plans from provider.",
                    "error": str(error),
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(response)

class DataPurchaseView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = DataPurchaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        network = serializer.validated_data["network"]
        phone_number = serializer.validated_data["phone_number"]
        plan_id = serializer.validated_data["plan_id"]
        plan_name = serializer.validated_data["plan_name"]
        amount = serializer.validated_data["amount"]

        reference = f"DATA-{uuid.uuid4().hex[:16].upper()}"

        with transaction.atomic():
            data_tx = DataTransaction.objects.create(
                user=request.user,
                network=network,
                phone_number=phone_number,
                plan_id=plan_id,
                plan_name=plan_name,
                amount=amount,
                reference=reference,
                status="pending",
            )

            main_tx = Transaction.objects.create(
                user=request.user,
                service_type="data",
                amount=amount,
                reference=reference,
                status="pending",
                provider="vtpass",
                description=f"{network.upper()} data purchase",
                metadata={
                    "network": network,
                    "phone_number": phone_number,
                    "plan_id": plan_id,
                    "plan_name": plan_name,
                },
            )

            WalletService.debit_wallet(
                wallet=request.user.wallet,
                amount=amount,
                reference=reference,
                description=f"{network.upper()} data purchase",
            )

        provider_response = VTPassDataService.purchase_data(
            request_id=reference,
            service_id=network,
            billers_code=phone_number,
            variation_code=plan_id,
            amount=amount,
            phone=phone_number,
        )

        is_successful = (
            provider_response.get("code") == "000"
            or provider_response.get("response_description", "").lower() == "transaction successful"
        )

        if is_successful:
            data_tx.status = "success"
            data_tx.provider_response = provider_response
            data_tx.save(update_fields=["status", "provider_response"])

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
                title="Data Purchase Successful",
                message=f"₦{amount} data was purchased for {phone_number}.",
            )

            return Response(
                DataTransactionSerializer(data_tx).data,
                status=status.HTTP_201_CREATED,
            )


        with transaction.atomic():
            WalletService.credit_wallet(
                wallet=request.user.wallet,
                amount=amount,
                reference=f"REFUND-{reference}",
                description="Refund for failed data purchase",
            )

            NotificationService.create_notification(
                user=request.user,
                notification_type="refund",
                title="Wallet Refunded",
                message=f"₦{amount} has been refunded to your wallet.",
            )

            data_tx.status = "refunded"
            data_tx.provider_response = provider_response
            data_tx.save(update_fields=["status", "provider_response"])

            main_tx.status = "refunded"
            main_tx.metadata = {
                **main_tx.metadata,
                "provider_response": provider_response,
            }
            main_tx.save(update_fields=["status", "metadata"])

        return Response(
            {
                "detail": "Data purchase failed. Wallet refunded.",
                "provider_response": provider_response,
                "transaction": DataTransactionSerializer(data_tx).data,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )