from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from transactions.models import Transaction
from wallets.services import WalletService
from wallets.models import WalletTransaction

from .models import EducationTransaction
from .serializers import (
    EducationPlansSerializer,
    EducationPurchaseSerializer,
    EducationTransactionSerializer,
)
from .services import VTPassEducationService

from notifications.services import NotificationService

from common.transaction_status import (
    classify_vtpass_response,
    sanitize_vtpass_response,
)
from common.vtpass_request_id import (
    generate_vtpass_request_id,
)
from common.vtpass_catalogue import (
    VTPassCatalogueError,
    get_authoritative_plan,
)


class EducationProvidersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        providers = [
            {
                "name": "WAEC Result Checker",
                "service_id": "waec",
            },
            {
                "name": "WAEC Registration",
                "service_id": "waec-registration",
            },
            {
                "name": "NECO Token",
                "service_id": "neco",
            },
            {
                "name": "JAMB",
                "service_id": "jamb",
            },
        ]

        return Response(providers)


class EducationPlansView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = EducationPlansSerializer(
            data=request.query_params
        )
        serializer.is_valid(
            raise_exception=True
        )

        provider = serializer.validated_data[
            "provider"
        ]

        response = (
            VTPassEducationService.get_plans(
                provider
            )
        )

        return Response(response)


class EducationPurchaseView(APIView):
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _refund_pending_transaction(
        *,
        education_tx,
        main_tx,
        amount,
        reference,
        provider_response,
        refund_message=(
            "Refund for failed "
            "education purchase"
        ),
    ):
        """
        Refund only a transaction that is
        still pending.

        Row locks and the pending-status
        check protect against duplicate
        refunds.
        """

        with transaction.atomic():
            education_tx = (
                EducationTransaction.objects
                .select_for_update()
                .get(pk=education_tx.pk)
            )

            main_tx = (
                Transaction.objects
                .select_for_update()
                .get(pk=main_tx.pk)
            )

            if (
                education_tx.status != "pending"
                or main_tx.status != "pending"
            ):
                return (
                    education_tx,
                    main_tx,
                    False,
                )

            original_debit_exists = (
                WalletTransaction.objects.filter(
                    wallet__user=education_tx.user,
                    reference=reference,
                    transaction_type="debit",
                    amount=amount,
                ).exists()
            )

            if not original_debit_exists:
                return (
                    education_tx,
                    main_tx,
                    False,
                )

            refund_reference = (
                f"REFUND-{reference}"
            )

            WalletService.credit_wallet(
                wallet=(
                    education_tx.user.wallet
                ),
                amount=amount,
                reference=refund_reference,
                description=refund_message,
            )

            education_tx.status = (
                "refunded"
            )
            education_tx.provider_response = (
                provider_response
            )

            education_tx.save(
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
            user=education_tx.user,
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
                    "education",
                "amount": str(amount),
            },
        )

        return (
            education_tx,
            main_tx,
            True,
        )

    @staticmethod
    def _extract_pin(provider_response):
        """
        Extract education PIN/card data from VTPass.

        Prefer structured cards when available.
        """

        if not isinstance(
            provider_response,
            dict,
        ):
            return ""

        cards = provider_response.get(
            "cards"
        )

        if isinstance(cards, list) and cards:
            formatted_cards = []

            for card in cards:
                if not isinstance(card, dict):
                    continue

                serial = str(
                    card.get("Serial")
                    or card.get("serial")
                    or ""
                ).strip()

                pin = str(
                    card.get("Pin")
                    or card.get("pin")
                    or ""
                ).strip()

                if serial and pin:
                    formatted_cards.append(
                        f"Serial No: {serial}\nPIN: {pin}"
                    )
                elif pin:
                    formatted_cards.append(
                        f"PIN: {pin}"
                    )

            if formatted_cards:
                return "\n\n".join(
                    formatted_cards
                )

        pin = (
            provider_response.get("pin")
            or provider_response.get("token")
            or provider_response.get(
                "purchased_code"
            )
            or ""
        )

        if pin:
            return str(pin).strip()

        content = (
            provider_response.get("content")
            or {}
        )

        if isinstance(content, dict):
            pin = (
                content.get("pin")
                or content.get("token")
                or content.get(
                    "purchased_code"
                )
                or ""
            )

        return str(pin).strip()

    def post(self, request):
        serializer = (
            EducationPurchaseSerializer(
                data=request.data
            )
        )

        serializer.is_valid(
            raise_exception=True
        )

        provider = serializer.validated_data[
            "provider"
        ]

        plan_id = serializer.validated_data[
            "plan_id"
        ]

        quantity = (
            serializer.validated_data[
                "quantity"
            ]
        )

        phone_number = (
            serializer.validated_data.get(
                "phone_number",
                "",
            )
        )

        profile_id = (
            serializer.validated_data.get(
                "profile_id",
                "",
            )
        )

        try:
            catalogue_response = (
                VTPassEducationService.get_plans(
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
                        "Selected education plan is "
                        "not currently available."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception:
            return Response(
                {
                    "detail":
                        "Unable to validate education "
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

        unit_amount = authoritative_plan[
            "amount"
        ]

        amount = unit_amount * quantity

        reference = (
            generate_vtpass_request_id(
                "EDU"
            )
        )

        # --------------------------------
        # Create pending records and
        # debit wallet atomically.
        # --------------------------------

        with transaction.atomic():
            education_tx = (
                EducationTransaction.objects
                .create(
                    user=request.user,
                    provider=provider,
                    plan_id=plan_id,
                    plan_name=plan_name,
                    amount=amount,
                    quantity=quantity,
                    phone_number=(
                        phone_number
                    ),
                    reference=reference,
                    status="pending",
                )
            )

            main_tx = (
                Transaction.objects.create(
                    user=request.user,
                    service_type="education",
                    amount=amount,
                    reference=reference,
                    status="pending",
                    provider="vtpass",
                    description=(
                        f"{provider.upper()} "
                        "purchase"
                    ),
                    metadata={
                        "provider": provider,
                        "plan_id": plan_id,
                        "plan_name":
                            plan_name,
                        "quantity":
                            quantity,
                        "phone_number":
                            phone_number,
                    },
                )
            )

            WalletService.debit_wallet(
                wallet=request.user.wallet,
                amount=amount,
                reference=reference,
                description=(
                    f"{provider.upper()} "
                    "purchase"
                ),
            )

        # --------------------------------
        # Send purchase to VTPass.
        # --------------------------------

        try:
            provider_response = (
                VTPassEducationService
                .purchase_pin(
                    request_id=reference,
                    service_id=provider,
                    variation_code=plan_id,
                    quantity=quantity,
                    phone=phone_number,
                    profile_id=profile_id,
                )
            )

        except Exception:

            # IMPORTANT:
            # Do not refund here. The provider
            # may have processed the request
            # even though our connection failed.
            # Never persist raw exception details.
            provider_response = {
                "response_description": (
                    "Provider request failed"
                ),
            }

        # --------------------------------
        # Classify response.
        # --------------------------------

        provider_result = (
            classify_vtpass_response(
                provider_response
            )
        )

        # Retain the original provider response
        # temporarily for examination PIN, serial
        # number, and provider reference extraction.
        # Persist only allowlisted provider data.
        sanitized_response = sanitize_vtpass_response(
            provider_response
        )

        education_tx.provider_response = (
            sanitized_response
        )

        education_tx.save(
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

        # --------------------------------
        # SUCCESS
        # --------------------------------

        if provider_result == "success":
            pin = self._extract_pin(
                provider_response
            )

            with transaction.atomic():
                education_tx = (
                    EducationTransaction.objects
                    .select_for_update()
                    .get(
                        pk=education_tx.pk
                    )
                )

                main_tx = (
                    Transaction.objects
                    .select_for_update()
                    .get(pk=main_tx.pk)
                )

                if (
                    education_tx.status != "pending"
                    or main_tx.status != "pending"
                ):
                    return Response(
                        {
                            "detail": (
                                "Education transaction "
                                "state changed before the "
                                "success result could be "
                                "applied."
                            ),
                            "reference": reference,
                            "status":
                                education_tx.status,
                        },
                        status=(
                            status.HTTP_409_CONFLICT
                        ),
                    )

                education_tx.status = (
                    "success"
                )

                education_tx.pin = pin

                education_tx.provider_response = (
                    sanitized_response
                )

                education_tx.save(
                    update_fields=[
                        "status",
                        "pin",
                        "provider_response",
                    ]
                )

                main_tx.status = "success"

                main_tx.metadata = {
                    **(
                        main_tx.metadata
                        or {}
                    ),
                    "pin": pin,
                    "provider_response":
                        sanitized_response,
                    "provider_result":
                        provider_result,
                    "requires_requery":
                        False,
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
                    "Education Purchase "
                    "Successful"
                ),
                message=(
                    f"₦{amount} education "
                    "was purchased."
                ),
                metadata={
                    "reference": reference,
                    "service_type":
                        "education",
                    "amount": str(amount),
                },
            )

            return Response(
                EducationTransactionSerializer(
                    education_tx
                ).data,
                status=(
                    status.HTTP_201_CREATED
                ),
            )

        # --------------------------------
        # PENDING
        # --------------------------------

        if provider_result == "pending":
            main_tx.metadata = {
                **(main_tx.metadata or {}),
                "requires_requery": True,
                "requires_manual_review":
                    False,
            }

            main_tx.save(
                update_fields=[
                    "metadata"
                ]
            )

            return Response(
                {
                    "detail": (
                        "Education purchase is "
                        "still being confirmed "
                        "by the provider. Your "
                        "wallet has not been "
                        "refunded yet."
                    ),
                    "reference": reference,
                    "status": "pending",
                    "provider_result":
                        provider_result,
                    "transaction":
                        EducationTransactionSerializer(
                            education_tx
                        ).data,
                },
                status=status.HTTP_202_ACCEPTED,
            )

        # --------------------------------
        # MANUAL REVIEW
        # --------------------------------

        if (
            provider_result
            == "manual_review"
        ):
            main_tx.metadata = {
                **(main_tx.metadata or {}),
                "requires_requery": False,
                "requires_manual_review":
                    True,
                "reconciliation_result":
                    "manual_review",
            }

            main_tx.save(
                update_fields=[
                    "metadata"
                ]
            )

            return Response(
                {
                    "detail": (
                        "The provider could not "
                        "confirm this education "
                        "purchase automatically. "
                        "It has been flagged for "
                        "review. Your wallet has "
                        "not been refunded yet."
                    ),
                    "reference": reference,
                    "status":
                        "manual_review",
                    "provider_result":
                        provider_result,
                    "transaction":
                        EducationTransactionSerializer(
                            education_tx
                        ).data,
                },
                status=(
                    status.HTTP_202_ACCEPTED
                ),
            )

        # --------------------------------
        # CONFIRMED FAILURE
        # --------------------------------

        try:
            (
                education_tx,
                main_tx,
                refunded,
            ) = (
                self._refund_pending_transaction(
                    education_tx=education_tx,
                    main_tx=main_tx,
                    amount=amount,
                    reference=reference,
                    provider_response=(
                        sanitized_response
                    ),
                )
            )

        except Exception:
            return Response(
                {
                    "detail": (
                        "Education purchase "
                        "failed, but the "
                        "automatic refund "
                        "encountered an error. "
                        "Please contact support."
                    ),
                    "reference": reference,
                },
                status=(
                    status.HTTP_500_INTERNAL_SERVER_ERROR
                ),
            )

        if not refunded:
            return Response(
                {
                    "detail": (
                        "Education transaction "
                        "state changed before the "
                        "refund could be applied."
                    ),
                    "reference": reference,
                    "status":
                        education_tx.status,
                },
                status=(
                    status.HTTP_409_CONFLICT
                ),
            )

        return Response(
            {
                "detail": (
                    "Education purchase failed. "
                    "Wallet refunded."
                ),
                "provider_result":
                    provider_result,
                "transaction":
                    EducationTransactionSerializer(
                        education_tx
                    ).data,
            },
            status=(
                status.HTTP_400_BAD_REQUEST
            ),
        )