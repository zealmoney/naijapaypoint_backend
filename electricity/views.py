from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from transactions.models import Transaction
from wallets.services import WalletService
from wallets.models import WalletTransaction

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
    sanitize_vtpass_response,
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

        try:
            provider_response = (
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
        except Exception:
            return Response(
                {
                    "detail": (
                        "Meter verification could not "
                        "be completed at this time."
                    )
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        if not isinstance(
            provider_response,
            dict,
        ):
            return Response(
                {
                    "detail": (
                        "Meter verification could not "
                        "be completed at this time."
                    )
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        code = str(
            provider_response.get(
                "code",
                "",
            )
        ).strip()

        content = provider_response.get(
            "content",
            {},
        )

        if not isinstance(content, dict):
            content = {}

        customer_name = (
            content.get("Customer_Name")
            or content.get("customer_name")
            or content.get("CustomerName")
            or provider_response.get(
                "Customer_Name"
            )
            or provider_response.get(
                "customer_name"
            )
            or ""
        )

        customer_name = str(
            customer_name
        ).strip()

        if code != "000" or not customer_name:
            return Response(
                {
                    "detail": (
                        "Meter verification failed. "
                        "Please check the meter "
                        "details and try again."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "verified": True,
                "customer_name": customer_name,
                "meter_number": (
                    serializer.validated_data[
                        "meter_number"
                    ]
                ),
                "meter_type": (
                    serializer.validated_data[
                        "meter_type"
                    ]
                ),
                "provider": (
                    serializer.validated_data[
                        "provider"
                    ]
                ),
            },
            status=status.HTTP_200_OK,
        )


class ElectricityPurchaseView(APIView):
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _refund_pending_transaction(
        *,
        electricity_tx,
        main_tx,
        amount,
        reference,
        provider_response,
        refund_message,
    ):
        with transaction.atomic():
            electricity_tx = (
                ElectricityTransaction.objects
                .select_for_update()
                .get(pk=electricity_tx.pk)
            )

            main_tx = (
                Transaction.objects
                .select_for_update()
                .get(pk=main_tx.pk)
            )

            if (
                electricity_tx.status != "pending"
                or main_tx.status != "pending"
            ):
                return (
                    electricity_tx,
                    main_tx,
                    False,
                )

            original_debit_exists = (
                WalletTransaction.objects.filter(
                    wallet__user=electricity_tx.user,
                    reference=reference,
                    transaction_type="debit",
                    amount=amount,
                ).exists()
            )

            if not original_debit_exists:
                return (
                    electricity_tx,
                    main_tx,
                    False,
                )

            refund_reference = (
                f"REFUND-{reference}"
            )

            WalletService.credit_wallet(
                wallet=electricity_tx.user.wallet,
                amount=amount,
                reference=refund_reference,
                description=refund_message,
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
            electricity_tx,
            main_tx,
            True,
        )

    @staticmethod
    def _mark_pending_transaction_success(
        *,
        electricity_tx,
        main_tx,
    ):
        with transaction.atomic():
            electricity_tx = (
                ElectricityTransaction.objects
                .select_for_update()
                .get(pk=electricity_tx.pk)
            )

            main_tx = (
                Transaction.objects
                .select_for_update()
                .get(pk=main_tx.pk)
            )

            if (
                electricity_tx.status != "pending"
                or main_tx.status != "pending"
            ):
                return (
                    electricity_tx,
                    main_tx,
                    False,
                )

            electricity_tx.status = "success"
            electricity_tx.save(
                update_fields=["status"]
            )

            main_tx.status = "success"
            main_tx.save(
                update_fields=["status"]
            )

        return (
            electricity_tx,
            main_tx,
            True,
        )

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

        except Exception:
            # Do not automatically refund a
            # network/provider exception.
            # VTPass may have processed the vend.
            #
            # Keep the transaction pending because
            # the provider may still have processed
            # the vend. Do not persist raw exception
            # details.
            provider_response = {
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

        # Retain the original response temporarily
        # for electricity token and reference extraction.
        # Persist only allowlisted provider information.
        sanitized_response = sanitize_vtpass_response(
            provider_response
        )

        electricity_tx.provider_response = (
            sanitized_response
        )
        electricity_tx.save(
            update_fields=[
                "provider_response"
            ]
        )

        main_tx.metadata = {
            **(main_tx.metadata or {}),
            "provider_response":
                sanitized_response,
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

            (
                electricity_tx,
                main_tx,
                marked_success,
            ) = self._mark_pending_transaction_success(
                electricity_tx=electricity_tx,
                main_tx=main_tx,
            )

            if not marked_success:
                return Response(
                    {
                        "detail": (
                            "Electricity transaction "
                            "state changed before the "
                            "success result could be "
                            "applied."
                        ),
                        "reference": reference,
                        "status": electricity_tx.status,
                    },
                    status=status.HTTP_409_CONFLICT,
                )

            electricity_tx.token = token
            electricity_tx.provider_response = (
                sanitized_response
            )
            electricity_tx.save(
                update_fields=[
                    "token",
                    "provider_response",
                ]
            )

            main_tx.metadata = {
                **(main_tx.metadata or {}),
                "token": token,
                "provider_response":
                    sanitized_response,
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

        (
            electricity_tx,
            main_tx,
            refunded,
        ) = self._refund_pending_transaction(
            electricity_tx=electricity_tx,
            main_tx=main_tx,
            amount=amount,
            reference=reference,
            provider_response=sanitized_response,
            refund_message=(
                "Refund for failed "
                "electricity purchase"
            ),
        )

        if not refunded:
            return Response(
                {
                    "detail": (
                        "Electricity transaction "
                        "state changed before the "
                        "refund could be applied. "
                        "No duplicate refund was "
                        "issued."
                    ),
                    "reference": reference,
                    "status": electricity_tx.status,
                },
                status=status.HTTP_409_CONFLICT,
            )

        refund_reference = (
            f"REFUND-{reference}"
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