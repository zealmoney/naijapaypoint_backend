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

from common.transaction_status import (
    classify_vtpass_response,
)

from common.vtpass_request_id import (
    generate_vtpass_request_id,
)

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
        serializer = DataPurchaseSerializer(
            data=request.data
        )
        serializer.is_valid(
            raise_exception=True
        )

        network = (
            serializer.validated_data[
                "network"
            ]
        )
        phone_number = (
            serializer.validated_data[
                "phone_number"
            ]
        )
        plan_id = (
            serializer.validated_data[
                "plan_id"
            ]
        )
        plan_name = (
            serializer.validated_data[
                "plan_name"
            ]
        )
        amount = (
            serializer.validated_data[
                "amount"
            ]
        )

        reference = generate_vtpass_request_id(
            "DATA"
        )

        # Create the transaction records and
        # reserve/debit the customer's wallet.
        with transaction.atomic():
            data_tx = (
                DataTransaction.objects.create(
                    user=request.user,
                    network=network,
                    phone_number=phone_number,
                    plan_id=plan_id,
                    plan_name=plan_name,
                    amount=amount,
                    reference=reference,
                    status="pending",
                )
            )

            main_tx = (
                Transaction.objects.create(
                    user=request.user,
                    service_type="data",
                    amount=amount,
                    reference=reference,
                    status="pending",
                    provider="vtpass",
                    description=(
                        f"{network.upper()} "
                        "data purchase"
                    ),
                    metadata={
                        "network": network,
                        "phone_number":
                            phone_number,
                        "plan_id": plan_id,
                        "plan_name": plan_name,
                    },
                )
            )

            WalletService.debit_wallet(
                wallet=request.user.wallet,
                amount=amount,
                reference=reference,
                description=(
                    f"{network.upper()} "
                    "data purchase"
                ),
            )

        # The provider request happens after
        # our initial database transaction.
        #
        # A timeout/connection error must NOT
        # immediately trigger a refund because
        # VTPass may still have completed the
        # transaction.
        try:
            provider_response = (
                VTPassDataService.purchase_data(
                    request_id=reference,
                    service_id=network,
                    billers_code=phone_number,
                    variation_code=plan_id,
                    amount=amount,
                    phone=phone_number,
                )
            )
        except Exception as exc:
            provider_response = {
                "code":
                    "PROVIDER_EXCEPTION",
                "response_description":
                    str(exc),
            }

        result = (
            classify_vtpass_response(
                provider_response
            )
        )

        # -----------------------------
        # SUCCESS
        # -----------------------------
        if result == "success":
            data_tx.status = "success"
            data_tx.provider_response = (
                provider_response
            )
            data_tx.save(
                update_fields=[
                    "status",
                    "provider_response",
                ]
            )

            main_tx.status = "success"
            main_tx.provider_reference = (
                provider_response.get(
                    "requestId"
                )
                or reference
            )
            main_tx.metadata = {
                **(main_tx.metadata or {}),
                "provider_response":
                    provider_response,
                "requires_requery": False,
                "requires_manual_review": False,
            }
            main_tx.save(
                update_fields=[
                    "status",
                    "provider_reference",
                    "metadata",
                ]
            )

            NotificationService.create_notification(
                user=request.user,
                notification_type="transaction",
                title=(
                    "Data Purchase Successful"
                ),
                message=(
                    f"₦{amount} data was "
                    f"purchased for "
                    f"{phone_number}."
                ),
            )

            return Response(
                DataTransactionSerializer(
                    data_tx
                ).data,
                status=(
                    status.HTTP_201_CREATED
                ),
            )

        # -----------------------------
        # PENDING / UNKNOWN
        # -----------------------------
        if result == "pending":
            data_tx.status = "pending"
            data_tx.provider_response = (
                provider_response
            )
            data_tx.save(
                update_fields=[
                    "status",
                    "provider_response",
                ]
            )

            main_tx.status = "pending"
            main_tx.metadata = {
                **(main_tx.metadata or {}),
                "provider_response":
                    provider_response,
                "requires_requery": True,
            }
            main_tx.save(
                update_fields=[
                    "status",
                    "metadata",
                ]
            )

            return Response(
                {
                    "detail": (
                        "Your data purchase is "
                        "still being confirmed "
                        "by the provider. Your "
                        "wallet has not been "
                        "refunded yet."
                    ),
                    "reference":
                        reference,
                    "status":
                        "pending",
                    "provider_response":
                        provider_response,
                    "transaction":
                        DataTransactionSerializer(
                            data_tx
                        ).data,
                },
                status=(
                    status.HTTP_202_ACCEPTED
                ),
            )

        # -----------------------------
        # MANUAL REVIEW
        # -----------------------------
        if result == "manual_review":
            data_tx.status = "pending"
            data_tx.provider_response = (
                provider_response
            )
            data_tx.save(
                update_fields=[
                    "status",
                    "provider_response",
                ]
            )

            main_tx.status = "pending"
            main_tx.metadata = {
                **(main_tx.metadata or {}),
                "provider_response":
                    provider_response,
                "requires_requery": False,
                "requires_manual_review": True,
                "reconciliation_result":
                    "manual_review",
            }
            main_tx.save(
                update_fields=[
                    "status",
                    "metadata",
                ]
            )

            return Response(
                {
                    "detail": (
                        "The provider could not "
                        "confirm this transaction "
                        "automatically. It has been "
                        "flagged for review. Your "
                        "wallet has not been "
                        "refunded yet."
                    ),
                    "reference": reference,
                    "status":
                        "manual_review",
                    "provider_response":
                        provider_response,
                    "transaction":
                        DataTransactionSerializer(
                            data_tx
                        ).data,
                },
                status=(
                    status.HTTP_202_ACCEPTED
                ),
            )

        # -----------------------------
        # CONFIRMED FAILURE
        # -----------------------------
        refund_reference = (
            f"REFUND-{reference}"
        )

        with transaction.atomic():
            WalletService.credit_wallet(
                wallet=request.user.wallet,
                amount=amount,
                reference=refund_reference,
                description=(
                    "Refund for failed "
                    "data purchase"
                ),
            )

            data_tx.status = "refunded"
            data_tx.provider_response = (
                provider_response
            )
            data_tx.save(
                update_fields=[
                    "status",
                    "provider_response",
                ]
            )

            main_tx.status = "refunded"
            main_tx.metadata = {
                **(main_tx.metadata or {}),
                "provider_response":
                    provider_response,
                "refund_reference":
                    refund_reference,
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
                    f"₦{amount} has been "
                    "refunded to your wallet."
                ),
            )

        return Response(
            {
                "detail": (
                    "Data purchase failed. "
                    "Wallet refunded."
                ),
                "provider_response":
                    provider_response,
                "transaction":
                    DataTransactionSerializer(
                        data_tx
                    ).data,
            },
            status=(
                status.HTTP_400_BAD_REQUEST
            ),
        )