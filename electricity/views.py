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

from common.transaction_status import (
    classify_vtpass_response,
)
from common.vtpass_request_id import (
    generate_vtpass_request_id,
)


class ElectricityProvidersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        providers = [
            {
                "name": "Ikeja Electric",
                "service_id": "ikeja-electric",
            },
            {
                "name": "Eko Electric",
                "service_id": "eko-electric",
            },
            {
                "name": "Abuja Electric",
                "service_id": "abuja-electric",
            },
            {
                "name": "Kano Electric",
                "service_id": "kano-electric",
            },
            {
                "name": "Ibadan Electric",
                "service_id": "ibadan-electric",
            },
            {
                "name": "Port Harcourt Electric",
                "service_id": "portharcourt-electric",
            },
        ]

        return Response(providers)


class VerifyMeterView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = MeterVerificationSerializer(
            data=request.data
        )
        serializer.is_valid(
            raise_exception=True
        )

        response = (
            VTPassElectricityService.verify_meter(
                service_id=(
                    serializer.validated_data[
                        "provider"
                    ]
                ),
                billers_code=(
                    serializer.validated_data[
                        "meter_number"
                    ]
                ),
                meter_type=(
                    serializer.validated_data[
                        "meter_type"
                    ]
                ),
            )
        )

        return Response(response)


class ElectricityPurchaseView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = (
            ElectricityPurchaseSerializer(
                data=request.data
            )
        )
        serializer.is_valid(
            raise_exception=True
        )

        provider = serializer.validated_data[
            "provider"
        ]
        meter_number = (
            serializer.validated_data[
                "meter_number"
            ]
        )
        meter_type = (
            serializer.validated_data[
                "meter_type"
            ]
        )
        customer_name = (
            serializer.validated_data[
                "customer_name"
            ]
        )
        amount = serializer.validated_data[
            "amount"
        ]

        reference = (
            generate_vtpass_request_id(
                "ELECTRICITY"
            )
        )

        # -----------------------------------------
        # Create pending records and debit wallet.
        # -----------------------------------------

        with transaction.atomic():
            electricity_tx = (
                ElectricityTransaction.objects.create(
                    user=request.user,
                    provider=provider,
                    meter_number=meter_number,
                    meter_type=meter_type,
                    customer_name=customer_name,
                    amount=amount,
                    reference=reference,
                    status="pending",
                )
            )

            main_tx = Transaction.objects.create(
                user=request.user,
                service_type="electricity",
                amount=amount,
                reference=reference,
                status="pending",
                provider="vtpass",
                description=(
                    f"{provider} "
                    "electricity purchase"
                ),
                metadata={
                    "provider": provider,
                    "meter_number":
                        meter_number,
                    "meter_type":
                        meter_type,
                },
            )

            WalletService.debit_wallet(
                wallet=request.user.wallet,
                amount=amount,
                reference=reference,
                description=(
                    f"{provider} "
                    "electricity payment"
                ),
            )

        # -----------------------------------------
        # Send purchase request to VTPass.
        # -----------------------------------------

        try:
            provider_response = (
                VTPassElectricityService
                .purchase_electricity(
                    request_id=reference,
                    service_id=provider,
                    billers_code=meter_number,
                    variation_code=meter_type,
                    amount=amount,
                    phone="08000000000",
                )
            )

            print(
                "VTPASS ELECTRICITY "
                "PURCHASE RESPONSE:",
                provider_response,
                flush=True,
            )

        except Exception as error:
            print(
                "VTPASS ELECTRICITY EXCEPTION:",
                str(error),
                flush=True,
            )

            # Do not automatically refund a
            # network/provider exception.
            # VTPass may have processed the vend.
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
            "VTPASS ELECTRICITY RESULT:",
            provider_result,
            flush=True,
        )

        electricity_tx.provider_response = (
            provider_response
        )
        electricity_tx.save(
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
                update_fields=[
                    "metadata"
                ]
            )

        # -----------------------------------------
        # SUCCESS
        # -----------------------------------------

        if provider_result == "success":
            token = self._extract_token(
                provider_response
            )

            electricity_tx.status = "success"
            electricity_tx.token = token
            electricity_tx.provider_response = (
                provider_response
            )
            electricity_tx.save(
                update_fields=[
                    "status",
                    "token",
                    "provider_response",
                ]
            )

            main_tx.status = "success"
            main_tx.metadata = {
                **(main_tx.metadata or {}),
                "token": token,
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
                    "Electricity Purchase "
                    "Successful"
                ),
                message=(
                    f"₦{amount} electricity "
                    f"was purchased for "
                    f"{meter_number}."
                ),
                metadata={
                    "reference": reference,
                    "service_type":
                        "electricity",
                    "amount": str(amount),
                },
            )

            return Response(
                ElectricityTransactionSerializer(
                    electricity_tx
                ).data,
                status=(
                    status.HTTP_201_CREATED
                ),
            )

        # -----------------------------------------
        # PENDING
        #
        # Do not refund. Reconciliation will
        # determine the final provider status.
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
                        "Electricity purchase "
                        "is still being confirmed "
                        "by the provider. Your "
                        "wallet has not been "
                        "refunded yet."
                    ),
                    "reference": reference,
                    "status": "pending",
                    "provider_result":
                        provider_result,
                    "provider_response":
                        provider_response,
                    "transaction":
                        ElectricityTransactionSerializer(
                            electricity_tx
                        ).data,
                },
                status=(
                    status.HTTP_202_ACCEPTED
                ),
            )

        # -----------------------------------------
        # MANUAL REVIEW
        #
        # Also do not refund automatically.
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
                        "confirm this electricity "
                        "transaction automatically. "
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
                        ElectricityTransactionSerializer(
                            electricity_tx
                        ).data,
                },
                status=(
                    status.HTTP_202_ACCEPTED
                ),
            )

        # -----------------------------------------
        # CONFIRMED FAILURE
        #
        # Only confirmed provider failures reach
        # this point and are safe to refund.
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
                    "electricity purchase"
                ),
            )

            electricity_tx.status = "refunded"
            electricity_tx.provider_response = (
                provider_response
            )
            electricity_tx.save(
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
                    "service_type":
                        "electricity",
                    "amount": str(amount),
                },
            )

        return Response(
            {
                "detail": (
                    "Electricity purchase failed. "
                    "Wallet refunded."
                ),
                "provider_result":
                    provider_result,
                "provider_response":
                    provider_response,
                "transaction":
                    ElectricityTransactionSerializer(
                        electricity_tx
                    ).data,
            },
            status=(
                status.HTTP_400_BAD_REQUEST
            ),
        )

    @staticmethod
    def _extract_token(
        provider_response,
    ):
        """
        Extract an electricity token from the
        possible VTPass response locations.
        """

        if not isinstance(
            provider_response,
            dict,
        ):
            return ""

        content = provider_response.get(
            "content",
            {},
        )

        token = (
            provider_response.get(
                "purchased_code"
            )
            or provider_response.get(
                "token"
            )
            or (
                content.get(
                    "purchased_code"
                )
                if isinstance(
                    content,
                    dict,
                )
                else ""
            )
            or (
                content.get("token")
                if isinstance(
                    content,
                    dict,
                )
                else ""
            )
            or ""
        )

        token = str(token).strip()

        if token.lower().startswith(
            "token :"
        ):
            token = token.split(
                ":",
                1,
            )[1].strip()

        return token