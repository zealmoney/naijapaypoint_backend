import uuid

from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from transactions.models import Transaction
from wallets.services import WalletService
from wallets.models import WalletTransaction

from .models import DataTransaction
from .serializers import (
    DataPlansSerializer,
    DataPurchaseSerializer,
    DataTransactionSerializer,
)

from .services import VTPassDataService

from notifications.services import NotificationService

from common.transaction_status import (
    classify_vtpass_response,
    sanitize_vtpass_response,
)

from common.vtpass_catalogue import (
    VTPassCatalogueError,
    get_authoritative_plan,
)

from common.vtpass_request_id import (
    generate_vtpass_request_id,
)

class DataPlansView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = DataPlansSerializer(
            data=request.query_params
        )
        serializer.is_valid(
            raise_exception=True
        )

        network = serializer.validated_data[
            "network"
        ]

        try:
            response = VTPassDataService.get_data_plans(network)
        except Exception:
            return Response(
                {
                    "detail":
                        "Unable to fetch data plans from provider."
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(response)

class DataPurchaseView(APIView):
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _refund_pending_transaction(
        *,
        data_tx,
        main_tx,
        amount,
        reference,
        provider_response,
        refund_message,
    ):
        with transaction.atomic():
            data_tx = (
                DataTransaction.objects
                .select_for_update()
                .get(pk=data_tx.pk)
            )

            main_tx = (
                Transaction.objects
                .select_for_update()
                .get(pk=main_tx.pk)
            )

            if (
                data_tx.status != "pending"
                or main_tx.status != "pending"
            ):
                return (
                    data_tx,
                    main_tx,
                    False,
                )

            original_debit_exists = (
                WalletTransaction.objects.filter(
                    wallet__user=data_tx.user,
                    reference=reference,
                    transaction_type="debit",
                    amount=amount,
                ).exists()
            )

            if not original_debit_exists:
                return (
                    data_tx,
                    main_tx,
                    False,
                )

            refund_reference = (
                f"REFUND-{reference}"
            )

            WalletService.credit_wallet(
                wallet=data_tx.user.wallet,
                amount=amount,
                reference=refund_reference,
                description=refund_message,
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
            data_tx,
            main_tx,
            True,
        )

    @staticmethod
    def _mark_pending_transaction_success(
        *,
        data_tx,
        main_tx,
    ):
        with transaction.atomic():
            data_tx = (
                DataTransaction.objects
                .select_for_update()
                .get(pk=data_tx.pk)
            )

            main_tx = (
                Transaction.objects
                .select_for_update()
                .get(pk=main_tx.pk)
            )

            if (
                data_tx.status != "pending"
                or main_tx.status != "pending"
            ):
                return (
                    data_tx,
                    main_tx,
                    False,
                )

            data_tx.status = "success"
            data_tx.save(
                update_fields=["status"]
            )

            main_tx.status = "success"
            main_tx.save(
                update_fields=["status"]
            )

        return (
            data_tx,
            main_tx,
            True,
        )

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
        try:
            catalogue_response = (
                VTPassDataService.get_data_plans(
                    network
                )
            )

            authoritative_plan = (
                get_authoritative_plan(
                    catalogue_response,
                    plan_id,
                )
            )
        except VTPassCatalogueError:
            return Response(
                {
                    "detail":
                        "Selected data plan is "
                        "not currently available."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception:
            return Response(
                {
                    "detail":
                        "Unable to validate data "
                        "plan with provider."
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        plan_id = authoritative_plan[
            "plan_id"
        ]
        plan_name = authoritative_plan[
            "plan_name"
        ]
        amount = authoritative_plan[
            "amount"
        ]

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
        except Exception:
            provider_response = {
                "code": "PROVIDER_EXCEPTION",
                "response_description":
                    "Provider outcome could not be confirmed.",
            }

        result = (
            classify_vtpass_response(
                provider_response
            )
        )

        # Store only allowlisted provider information.
        # Keep the original response temporarily for
        # provider reference extraction and classification.
        sanitized_response = sanitize_vtpass_response(
            provider_response
        )

        # -----------------------------
        # SUCCESS
        # -----------------------------
        if result == "success":
            (
                data_tx,
                main_tx,
                marked_success,
            ) = self._mark_pending_transaction_success(
                data_tx=data_tx,
                main_tx=main_tx,
            )

            if not marked_success:
                return Response(
                    {
                        "detail": (
                            "Data transaction state "
                            "changed before the success "
                            "result could be applied."
                        ),
                        "reference": reference,
                        "status": main_tx.status,
                    },
                    status=status.HTTP_409_CONFLICT,
                )

            data_tx.provider_response = (
                sanitized_response
            )
            data_tx.save(
                update_fields=[
                    "provider_response",
                ]
            )
            main_tx.provider_reference = (
                provider_response.get(
                    "requestId"
                )
                or reference
            )
            main_tx.metadata = {
                **(main_tx.metadata or {}),
                "provider_response":
                    sanitized_response,
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
                sanitized_response
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
                    sanitized_response,
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
                sanitized_response
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
                    sanitized_response,
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
        (
            data_tx,
            main_tx,
            refunded,
        ) = self._refund_pending_transaction(
            data_tx=data_tx,
            main_tx=main_tx,
            amount=amount,
            reference=reference,
            provider_response=sanitized_response,
            refund_message=(
                "Refund for failed data purchase"
            ),
        )

        if not refunded:
            return Response(
                {
                    "detail": (
                        "Data transaction state changed "
                        "before the refund could be "
                        "applied. No duplicate refund "
                        "was issued."
                    ),
                    "reference": reference,
                    "status": main_tx.status,
                },
                status=status.HTTP_409_CONFLICT,
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
                "transaction":
                    DataTransactionSerializer(
                        data_tx
                    ).data,
            },
            status=(
                status.HTTP_400_BAD_REQUEST
            ),
        )