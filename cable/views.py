from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from decimal import Decimal, InvalidOperation

from transactions.models import Transaction
from wallets.services import WalletService
from wallets.models import WalletTransaction

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
    sanitize_vtpass_response,
)

from common.vtpass_catalogue import (
    VTPassCatalogueError,
    extract_variations,
    get_authoritative_plan,
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

        try:
            provider_response = (
                VTPassCableService.get_plans(
                    provider
                )
            )

            variations = extract_variations(
                provider_response
            )

            plans = []

            for plan in variations:
                if not isinstance(plan, dict):
                    continue

                plan_id = str(
                    plan.get("variation_code")
                    or plan.get("code")
                    or ""
                ).strip()

                plan_name = str(
                    plan.get("name")
                    or ""
                ).strip()

                raw_amount = (
                    plan.get("variation_amount")
                    if plan.get(
                        "variation_amount"
                    ) is not None
                    else plan.get("amount")
                )

                if (
                    not plan_id
                    or not plan_name
                    or raw_amount is None
                ):
                    continue

                try:
                    amount = Decimal(
                        str(raw_amount)
                    )
                except (
                    InvalidOperation,
                    TypeError,
                    ValueError,
                ):
                    continue

                if (
                    not amount.is_finite()
                    or amount <= Decimal("0")
                ):
                    continue

                plans.append(
                    {
                        "plan_id": plan_id,
                        "plan_name": plan_name,
                        "amount": format(
                            amount,
                            ".2f",
                        ),
                    }
                )

            if not plans:
                return Response(
                    {
                        "detail": (
                            "Cable plans are "
                            "temporarily unavailable."
                        )
                    },
                    status=(
                        status
                        .HTTP_502_BAD_GATEWAY
                    ),
                )

            return Response(
                plans,
                status=status.HTTP_200_OK,
            )

        except VTPassCatalogueError:
            return Response(
                {
                    "detail": (
                        "Cable plans are "
                        "temporarily unavailable."
                    )
                },
                status=(
                    status.HTTP_502_BAD_GATEWAY
                ),
            )

        except Exception:
            return Response(
                {
                    "detail": (
                        "Cable plans are "
                        "temporarily unavailable."
                    )
                },
                status=(
                    status.HTTP_502_BAD_GATEWAY
                ),
            )


class CableVerifyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CableVerifySerializer(
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

        try:
            provider_response = (
                VTPassCableService.verify_smartcard(
                    service_id=provider,
                    smartcard_number=(
                        smartcard_number
                    ),
                )
            )
        except Exception:
            return Response(
                {
                    "detail": (
                        "Unable to verify the "
                        "smartcard at this time. "
                        "Please try again."
                    )
                },
                status=(
                    status.HTTP_502_BAD_GATEWAY
                ),
            )

        if not isinstance(
            provider_response,
            dict,
        ):
            return Response(
                {
                    "detail": (
                        "Unable to verify the "
                        "smartcard at this time. "
                        "Please try again."
                    )
                },
                status=(
                    status.HTTP_502_BAD_GATEWAY
                ),
            )

        provider_result = (
            classify_vtpass_response(
                provider_response
            )
        )

        if provider_result != "success":
            return Response(
                {
                    "detail": (
                        "Smartcard verification "
                        "failed. Please check the "
                        "details and try again."
                    )
                },
                status=(
                    status.HTTP_400_BAD_REQUEST
                ),
            )

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
            or ""
        )

        customer_number = (
            content.get("Customer_Number")
            or content.get("customer_number")
            or smartcard_number
        )

        account_status = (
            content.get("Status")
            or content.get("status")
            or ""
        )

        return Response(
            {
                "verified": True,
                "customer_name":
                    str(customer_name),
                "customer_number":
                    str(customer_number),
                "status":
                    str(account_status),
            },
            status=status.HTTP_200_OK,
        )


class CablePurchaseView(APIView):
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _refund_pending_transaction(
        *,
        cable_tx,
        main_tx,
        amount,
        reference,
        provider_response,
        refund_message,
    ):
        with transaction.atomic():
            cable_tx = (
                CableTransaction.objects
                .select_for_update()
                .get(pk=cable_tx.pk)
            )

            main_tx = (
                Transaction.objects
                .select_for_update()
                .get(pk=main_tx.pk)
            )

            if (
                cable_tx.status != "pending"
                or main_tx.status != "pending"
            ):
                return (
                    cable_tx,
                    main_tx,
                    False,
                )

            original_debit_exists = (
                WalletTransaction.objects.filter(
                    wallet__user=cable_tx.user,
                    reference=reference,
                    transaction_type="debit",
                    amount=amount,
                ).exists()
            )

            if not original_debit_exists:
                return (
                    cable_tx,
                    main_tx,
                    False,
                )

            refund_reference = (
                f"REFUND-{reference}"
            )

            WalletService.credit_wallet(
                wallet=cable_tx.user.wallet,
                amount=amount,
                reference=refund_reference,
                description=refund_message,
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
            cable_tx,
            main_tx,
            True,
        )

    @staticmethod
    def _mark_pending_transaction_success(
        *,
        cable_tx,
        main_tx,
    ):
        with transaction.atomic():
            cable_tx = (
                CableTransaction.objects
                .select_for_update()
                .get(pk=cable_tx.pk)
            )

            main_tx = (
                Transaction.objects
                .select_for_update()
                .get(pk=main_tx.pk)
            )

            if (
                cable_tx.status != "pending"
                or main_tx.status != "pending"
            ):
                return (
                    cable_tx,
                    main_tx,
                    False,
                )

            cable_tx.status = "success"
            cable_tx.save(
                update_fields=["status"]
            )

            main_tx.status = "success"
            main_tx.save(
                update_fields=["status"]
            )

        return (
            cable_tx,
            main_tx,
            True,
        )

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

        customer_name = (
            serializer.validated_data.get(
                "customer_name",
                "",
            )
        )

        try:
            catalogue_response = (
                VTPassCableService.get_plans(
                    provider
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
                        "Selected cable plan is "
                        "not currently available."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception:
            return Response(
                {
                    "detail":
                        "Unable to validate cable "
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
                    smartcard_number=smartcard_number,
                    variation_code=plan_id,
                    amount=amount,
                    phone="08000000000",
                )
            )

        except Exception:
            # Provider outcome is uncertain.
            # Never log or persist raw exception details.
            # Do not refund without confirmation.
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

        sanitized_response = sanitize_vtpass_response(
            provider_response
        )

        cable_tx.provider_response = (
            sanitized_response
        )
        cable_tx.save(
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
                update_fields=["metadata"]
            )

        # -----------------------------------------
        # SUCCESS
        # -----------------------------------------

        if provider_result == "success":
            (
                cable_tx,
                main_tx,
                marked_success,
            ) = self._mark_pending_transaction_success(
                cable_tx=cable_tx,
                main_tx=main_tx,
            )

            if not marked_success:
                return Response(
                    {
                        "detail": (
                            "Cable transaction state "
                            "changed before the success "
                            "result could be applied."
                        ),
                        "reference": reference,
                        "status": main_tx.status,
                    },
                    status=(
                        status.HTTP_409_CONFLICT
                    ),
                )

            cable_tx.provider_response = (
                sanitized_response
            )
            cable_tx.save(
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

        (
            cable_tx,
            main_tx,
            refunded,
        ) = self._refund_pending_transaction(
            cable_tx=cable_tx,
            main_tx=main_tx,
            amount=amount,
            reference=reference,
            provider_response=sanitized_response,
            refund_message=(
                "Refund for failed "
                "cable subscription"
            ),
        )

        if not refunded:
            return Response(
                {
                    "detail": (
                        "Cable transaction state "
                        "changed before the refund "
                        "could be applied. No "
                        "duplicate refund was issued."
                    ),
                    "reference": reference,
                    "status": main_tx.status,
                },
                status=(
                    status.HTTP_409_CONFLICT
                ),
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
                    f"REFUND-{reference}",
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
                "transaction":
                    CableTransactionSerializer(
                        cable_tx
                    ).data,
            },
            status=(
                status.HTTP_400_BAD_REQUEST
            ),
        )