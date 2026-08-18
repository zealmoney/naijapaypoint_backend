import uuid

from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from transactions.models import Transaction
from wallets.services import WalletService

from .models import EducationTransaction
from .serializers import (
    EducationPlansSerializer,
    EducationPurchaseSerializer,
    EducationTransactionSerializer,
)
from .services import VTPassEducationService
from notifications.services import NotificationService


class EducationProvidersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        providers = [
            {"name": "WAEC Result Checker", "service_id": "waec"},
            {"name": "WAEC Registration", "service_id": "waec-registration"},
            {"name": "NECO Token", "service_id": "neco"},
            {"name": "JAMB", "service_id": "jamb"},
        ]

        return Response(providers)


class EducationPlansView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = EducationPlansSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        provider = serializer.validated_data["provider"]

        response = VTPassEducationService.get_plans(provider)

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
        refund_message="Refund for failed education purchase",
    ):
        """
        Safely refund an Education transaction.

        The row locks + pending-status check prevent
        the same transaction from being refunded twice.
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

            # Prevent duplicate refunds.
            if education_tx.status != "pending":
                return education_tx, main_tx, False

            WalletService.credit_wallet(
                wallet=education_tx.user.wallet,
                amount=amount,
                reference=f"REFUND-{reference}",
                description=refund_message,
            )

            education_tx.status = "refunded"
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
                f"₦{amount} has been refunded "
                "to your wallet."
            ),
        )

        return (
            education_tx,
            main_tx,
            True,
        )

    def post(self, request):
        serializer = EducationPurchaseSerializer(
            data=request.data
        )

        serializer.is_valid(
            raise_exception=True
        )

        provider = (
            serializer.validated_data[
                "provider"
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

        reference = (
            f"EDU-"
            f"{uuid.uuid4().hex[:16].upper()}"
        )

        #
        # STEP 1:
        # Create transaction records and
        # debit the wallet atomically.
        #
        with transaction.atomic():
            education_tx = (
                EducationTransaction.objects.create(
                    user=request.user,
                    provider=provider,
                    plan_id=plan_id,
                    plan_name=plan_name,
                    amount=amount,
                    quantity=quantity,
                    phone_number=phone_number,
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
                        f"{provider.upper()} purchase"
                    ),
                    metadata={
                        "provider": provider,
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
                    f"{provider.upper()} purchase"
                ),
            )

        #
        # STEP 2:
        # Call VTPass.
        #
        # IMPORTANT:
        # Unexpected Python/network/service
        # exceptions are caught here and the
        # wallet is refunded.
        #
        try:
            provider_response = (
                VTPassEducationService.purchase_pin(
                    request_id=reference,
                    service_id=provider,
                    variation_code=plan_id,
                    quantity=quantity,
                    phone=phone_number,
                    profile_id=profile_id,
                )
            )

        except Exception as exc:
            print(
                "EDUCATION PROVIDER EXCEPTION:",
                repr(exc),
            )

            provider_response = {
                "code": "internal_provider_error",
                "response_description": (
                    "Education provider request "
                    "could not be completed."
                ),
                "error": str(exc),
            }

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
                            provider_response
                        ),
                        refund_message=(
                            "Refund for interrupted "
                            "education purchase"
                        ),
                    )
                )

            except Exception as refund_exc:
                #
                # Very important:
                # Do not falsely tell the customer
                # they were refunded if the refund
                # itself failed.
                #
                print(
                    "EDUCATION REFUND ERROR:",
                    repr(refund_exc),
                )

                return Response(
                    {
                        "detail": (
                            "The education purchase "
                            "could not be completed, "
                            "and the automatic refund "
                            "also encountered an error. "
                            "Please contact support."
                        ),
                        "reference": reference,
                    },
                    status=(
                        status.HTTP_500_INTERNAL_SERVER_ERROR
                    ),
                )

            return Response(
                {
                    "detail": (
                        "Education purchase could not "
                        "be completed. Wallet refunded."
                    ),
                    "provider_response":
                        provider_response,
                    "transaction":
                        EducationTransactionSerializer(
                            education_tx
                        ).data,
                },
                status=(
                    status.HTTP_502_BAD_GATEWAY
                ),
            )

        #
        # STEP 3:
        # Interpret normal VTPass response.
        #
        is_successful = (
            provider_response.get("code")
            == "000"
            or
            provider_response.get(
                "response_description",
                "",
            ).lower()
            == "transaction successful"
        )

        #
        # STEP 4:
        # Successful provider response.
        #
        if is_successful:
            pin = (
                provider_response.get("pin")
                or provider_response.get(
                    "token"
                )
                or provider_response.get(
                    "purchased_code"
                )
                or ""
            )

            #
            # Some VTPass products may put
            # purchased_code inside content.
            #
            if not pin:
                content = (
                    provider_response.get(
                        "content"
                    )
                    or {}
                )

                if isinstance(
                    content,
                    dict,
                ):
                    pin = (
                        content.get("pin")
                        or content.get(
                            "token"
                        )
                        or content.get(
                            "purchased_code"
                        )
                        or ""
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
                    .get(
                        pk=main_tx.pk
                    )
                )

                education_tx.status = (
                    "success"
                )

                education_tx.pin = str(
                    pin
                )

                education_tx.provider_response = (
                    provider_response
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
                        provider_response,
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
                    "Education Purchase Successful"
                ),
                message=(
                    f"₦{amount} education "
                    "was purchased."
                ),
            )

            return Response(
                EducationTransactionSerializer(
                    education_tx
                ).data,
                status=(
                    status.HTTP_201_CREATED
                ),
            )

        #
        # STEP 5:
        # VTPass responded normally,
        # but transaction failed.
        #
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
                        provider_response
                    ),
                )
            )

        except Exception as refund_exc:
            print(
                "EDUCATION REFUND ERROR:",
                repr(refund_exc),
            )

            return Response(
                {
                    "detail": (
                        "Education purchase failed, "
                        "but the automatic refund "
                        "encountered an error. "
                        "Please contact support."
                    ),
                    "reference": reference,
                    "provider_response":
                        provider_response,
                },
                status=(
                    status.HTTP_500_INTERNAL_SERVER_ERROR
                ),
            )

        return Response(
            {
                "detail": (
                    "Education purchase failed. "
                    "Wallet refunded."
                ),
                "provider_response":
                    provider_response,
                "transaction":
                    EducationTransactionSerializer(
                        education_tx
                    ).data,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )