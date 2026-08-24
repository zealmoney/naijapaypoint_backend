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

from common.transaction_status import (
    classify_vtpass_response,
)
from common.vtpass_request_id import (
    generate_vtpass_request_id,
)


class CableProvidersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        providers = [
            {
                "name": "DStv",
                "service_id": "dstv",
            },
            {
                "name": "GOtv",
                "service_id": "gotv",
            },
            {
                "name": "Startimes",
                "service_id": "startimes",
            },
            {
                "name": "Showmax",
                "service_id": "showmax",
            },
        ]

        return Response(providers)


class CablePlansView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = CablePlansSerializer(
            data=request.query_params
        )
        serializer.is_valid(
            raise_exception=True
        )

        provider = serializer.validated_data[
            "provider"
        ]

        response = (
            VTPassCableService.get_plans(
                provider
            )
        )

        return Response(response)


class CableVerifyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CableVerifySerializer(
            data=request.data
        )
        serializer.is_valid(
            raise_exception=True
        )

        response = (
            VTPassCableService.verify_smartcard(
                service_id=(
                    serializer.validated_data[
                        "provider"
                    ]
                ),
                smartcard_number=(
                    serializer.validated_data[
                        "smartcard_number"
                    ]
                ),
            )
        )

        return Response(response)


class CablePurchaseView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CablePurchaseSerializer(
            data=request.data
        )
        serializer.is_valid(
            raise_exception=True
        )

        provider = serializer.validated_data[
            "provider"
        ]
        smartcard_number = (
            serializer.validated_data[
                "smartcard_number"
            ]
        )
        plan_id = serializer.validated_data[
            "plan_id"
        ]
        plan_name = serializer.validated_data[
            "plan_name"
        ]
        customer_name = (
            serializer.validated_data.get(
                "customer_name",
                "",
            )
        )
        amount = serializer.validated_data[
            "amount"
        ]

        reference = (
            generate_vtpass_request_id(
                "CABLE"
            )
        )

        # -----------------------------------------
        # Create pending records and debit wallet.
        # -----------------------------------------

        with transaction.atomic():
            cable_tx = (
                CableTransaction.objects.create(
                    user=request.user,
                    provider=provider,
                    smartcard_number=(
                        smartcard_number
                    ),
                    plan_id=plan_id,
                    plan_name=plan_name,
                    customer_name=customer_name,
                    amount=amount,
                    reference=reference,
                    status="pending",
                )
            )

            main_tx = Transaction.objects.create(
                user=request.user,
                service_type="cable",
                amount=amount,
                reference=reference,
                status="pending",
                provider="vtpass",
                description=(
                    f"{provider.upper()} "
                    "subscription purchase"
                ),
                metadata={
                    "provider": provider,
                    "smartcard_number":
                        smartcard_number,
                    "plan_id": plan_id,
                    "plan_name": plan_name,
                    "customer_name":
                        customer_name,
                },
            )

            WalletService.debit_wallet(
                wallet=request.user.wallet,
                amount=amount,
                reference=reference,
                description=(
                    f"{provider.upper()} "
                    "subscription payment"
                ),
            )

        # -----------------------------------------
        # Send purchase request to VTPass.
        # -----------------------------------------

        try:
            provider_response = (
                VTPassCableService
                .purchase_subscription(
                    request_id=reference,
                    service_id=provider,
                    smartcard_number=(
                        smartcard_number
                    ),
                    variation_code=plan_id,
                    amount=amount,
                    phone="08000000000",
                )
            )

            print(
                "VTPASS CABLE PURCHASE RESPONSE:",
                provider_response,
                flush=True,
            )

        except Exception as error:
            print(
                "VTPASS CABLE EXCEPTION:",
                str(error),
                flush=True,
            )

            # Do not refund an ambiguous network
            # exception. The provider may have
            # completed the subscription.
            provider_response = {
                "error": str(error),
                "response_description": (
                    "Provider request failed"
                ),
            }

        # -----------------------------------------
        # Classify provider response.
        # -----------------------------------------

        provider_result = (
            classify_vtpass_response(
                provider_response
            )
        )

        print(
            "VTPASS CABLE RESULT:",
            provider_result,
            flush=True,
        )

        cable_tx.provider_response = (
            provider_response
        )
        cable_tx.save(
            update_fields=[
                "provider_response"
            ]
        )

        main_tx.metadata = {
            **(main_tx.metadata or {}),
            "provider_response":
                provider_response,
            "provider_result":
                provider_result,
        }

        provider_reference = (
            provider_response.get(
                "requestId"
            )
            if isinstance(
                provider_response,
                dict,
            )
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

        # -----------------------------------------
        # SUCCESS
        # -----------------------------------------

        if provider_result == "success":
            cable_tx.status = "success"
            cable_tx.provider_response = (
                provider_response
            )
            cable_tx.save(
                update_fields=[
                    "status",
                    "provider_response",
                ]
            )

            main_tx.status = "success"
            main_tx.metadata = {
                **(main_tx.metadata or {}),
                "provider_response":
                    provider_response,
                "provider_result":
                    provider_result,
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

            NotificationService.create_notification(
                user=request.user,
                notification_type="transaction",
                title=(
                    "Cable Subscription "
                    "Successful"
                ),
                message=(
                    f"₦{amount} cable "
                    "subscription was purchased "
                    f"for {smartcard_number}."
                ),
                metadata={
                    "reference": reference,
                    "service_type": "cable",
                    "amount": str(amount),
                },
            )

            return Response(
                CableTransactionSerializer(
                    cable_tx
                ).data,
                status=(
                    status.HTTP_201_CREATED
                ),
            )

        # -----------------------------------------
        # PENDING
        # -----------------------------------------

        if provider_result == "pending":
            main_tx.metadata = {
                **(main_tx.metadata or {}),
                "requires_requery": True,
                "requires_manual_review":
                    False,
            }
            main_tx.save(
                update_fields=["metadata"]
            )

            return Response(
                {
                    "detail": (
                        "Cable subscription is "
                        "still being confirmed by "
                        "the provider. Your wallet "
                        "has not been refunded yet."
                    ),
                    "reference": reference,
                    "status": "pending",
                    "provider_result":
                        provider_result,
                    "provider_response":
                        provider_response,
                    "transaction":
                        CableTransactionSerializer(
                            cable_tx
                        ).data,
                },
                status=(
                    status.HTTP_202_ACCEPTED
                ),
            )

        # -----------------------------------------
        # MANUAL REVIEW
        # -----------------------------------------

        if provider_result == "manual_review":
            main_tx.metadata = {
                **(main_tx.metadata or {}),
                "requires_requery": False,
                "requires_manual_review": True,
                "reconciliation_result":
                    "manual_review",
            }
            main_tx.save(
                update_fields=["metadata"]
            )

            return Response(
                {
                    "detail": (
                        "The provider could not "
                        "confirm this cable "
                        "subscription automatically. "
                        "It has been flagged for "
                        "review. Your wallet has "
                        "not been refunded yet."
                    ),
                    "reference": reference,
                    "status": "manual_review",
                    "provider_result":
                        provider_result,
                    "provider_response":
                        provider_response,
                    "transaction":
                        CableTransactionSerializer(
                            cable_tx
                        ).data,
                },
                status=(
                    status.HTTP_202_ACCEPTED
                ),
            )

        # -----------------------------------------
        # CONFIRMED FAILURE
        # -----------------------------------------

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
                    "cable subscription"
                ),
            )

            cable_tx.status = "refunded"
            cable_tx.provider_response = (
                provider_response
            )
            cable_tx.save(
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
                "provider_result":
                    provider_result,
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

            NotificationService.create_notification(
                user=request.user,
                notification_type="refund",
                title="Wallet Refunded",
                message=(
                    f"₦{amount} has been "
                    "refunded to your wallet."
                ),
                metadata={
                    "reference": reference,
                    "refund_reference":
                        refund_reference,
                    "service_type": "cable",
                    "amount": str(amount),
                },
            )

        return Response(
            {
                "detail": (
                    "Cable subscription failed. "
                    "Wallet refunded."
                ),
                "provider_result":
                    provider_result,
                "provider_response":
                    provider_response,
                "transaction":
                    CableTransactionSerializer(
                        cable_tx
                    ).data,
            },
            status=(
                status.HTTP_400_BAD_REQUEST
            ),
        )