from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from decimal import Decimal, InvalidOperation

from .models import GuestTransaction
from .serializers import (
    GuestPaymentInitializeSerializer,
    GuestTransactionSerializer,
)
from .services import GuestReferenceService

from payments.services import PaystackService

from payments.services import PaystackService
from airtime.services import VTPassAirtimeService
from data_services.services import VTPassDataService

from .purchase_service import GuestPurchaseService
from django.conf import settings

import secrets

import logging
from rest_framework.permissions import AllowAny

from django.db import transaction as database_transaction

from electricity.services import VTPassElectricityService
from cable.services import VTPassCableService

from common.vtpass_catalogue import (
    VTPassCatalogueError,
    get_authoritative_plan,
)

from common.transaction_status import (
    classify_vtpass_response,
    sanitize_vtpass_response,
)

logger = logging.getLogger(__name__)

class GuestInitializePaymentView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = GuestPaymentInitializeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        reference = GuestReferenceService.generate_reference()
        validated_data = serializer.validated_data.copy()

        if validated_data["service_type"] == "data":
            try:
                catalogue_response = (
                    VTPassDataService.get_data_plans(
                        validated_data["provider"]
                    )
                )

                authoritative_plan = (
                    get_authoritative_plan(
                        catalogue_response,
                        validated_data.get(
                            "variation_code"
                        ),
                    )
                )

            except VTPassCatalogueError as exc:
                return Response(
                    {"detail": str(exc)},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            except Exception:
                logger.exception(
                    "Guest data catalogue lookup failed."
                )
                return Response(
                    {
                        "detail":
                            "Unable to verify the selected "
                            "data plan right now."
                    },
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )

            validated_data["amount"] = (
                authoritative_plan["amount"]
            )
            validated_data["plan_name"] = (
                authoritative_plan["plan_name"]
            )

        if validated_data["service_type"] == "cable":
            try:
                catalogue_response = (
                    VTPassCableService.get_plans(
                        validated_data["provider"]
                    )
                )

                authoritative_plan = (
                    get_authoritative_plan(
                        catalogue_response,
                        validated_data.get(
                            "variation_code"
                        ),
                    )
                )

            except VTPassCatalogueError as exc:
                return Response(
                    {"detail": str(exc)},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            except Exception:
                logger.exception(
                    "Guest cable catalogue lookup failed."
                )
                return Response(
                    {
                        "detail":
                            "Unable to verify the selected "
                            "cable plan right now."
                    },
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )

            validated_data["amount"] = (
                authoritative_plan["amount"]
            )
            validated_data["plan_name"] = (
                authoritative_plan["plan_name"]
            )

        amount = validated_data["amount"]
        guest_email = validated_data["guest_email"]

        frontend_url = getattr(
            settings,
            "FRONTEND_URL",
            "http://localhost:3000",
        ).rstrip("/")

        callback_url = f"{frontend_url}/guest/payment-success"

        try:
            paystack_response = PaystackService.initialize_transaction(
                email=guest_email,
                amount=amount,
                reference=reference,
                callback_url=callback_url,
            )

        except Exception:
            logger.exception(
                "Paystack guest initialization failed for %s",
                reference,
            )

            return Response(
                {
                    "detail": "Unable to initialize guest payment.",
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        if not isinstance(paystack_response, dict):
            return Response(
                {
                    "detail": "Unable to initialize guest payment.",
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        if paystack_response.get("status") is not True:
            return Response(
                {
                    "detail": "Unable to initialize guest payment.",
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        paystack_data = paystack_response.get("data") or {}
        authorization_url = paystack_data.get("authorization_url")

        if not authorization_url:
            return Response(
                {
                    "detail": "Unable to initialize guest payment.",
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        transaction = GuestTransaction.objects.create(
            reference=reference,
            receipt_access_token=secrets.token_urlsafe(32),
            payment_reference=paystack_data.get(
                "reference",
                reference,
            ),
            authorization_url=authorization_url,
            **validated_data,
        )

        response_data = GuestTransactionSerializer(transaction).data

        return Response(
            {
                **response_data,
                "authorization_url": authorization_url,
                "access_code": paystack_data.get("access_code"),
                "receipt_access_token": transaction.receipt_access_token,
            },
            status=status.HTTP_201_CREATED,
        )

class GuestVerifyPaymentView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        reference = request.data.get("reference")

        if not reference:
            return Response(
                {"detail": "Reference is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        receipt_access_token = request.headers.get(
            "X-Guest-Receipt-Token"
        )

        if not receipt_access_token:
            return Response(
                {
                    "detail":
                        "Guest transaction access token is required."
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            # Claim this transaction before calling Paystack or VTPass.
            with database_transaction.atomic():
                guest_transaction = (
                    GuestTransaction.objects
                    .select_for_update()
                    .get(reference=reference)
                )

                stored_access_token = (
                    guest_transaction.receipt_access_token or ""
                )

                if (
                    not stored_access_token
                    or not secrets.compare_digest(
                        receipt_access_token,
                        stored_access_token,
                    )
                ):
                    return Response(
                        {
                            "detail":
                                "Guest transaction access denied."
                        },
                        status=status.HTTP_403_FORBIDDEN,
                    )

                # Idempotent response for an already completed purchase.
                if guest_transaction.status == "success":
                    return Response(
                        GuestTransactionSerializer(
                            guest_transaction
                        ).data,
                        status=status.HTTP_200_OK,
                    )

                # Prevent simultaneous verification requests from
                # purchasing the service more than once.
                if guest_transaction.status == "processing":
                    return Response(
                        {
                            "detail": (
                                "This transaction is already being "
                                "processed."
                            ),
                            "reference": guest_transaction.reference,
                            "status": guest_transaction.status,
                        },
                        status=status.HTTP_202_ACCEPTED,
                    )

                # A paid transaction that already reached the provider
                # must not automatically call VTPass again.
                if guest_transaction.status == "failed":
                    return Response(
                        {
                            "detail": (
                                "Payment was received, but the service "
                                "purchase was not completed. Please "
                                "contact support with your reference."
                            ),
                            "transaction": GuestTransactionSerializer(
                                guest_transaction
                            ).data,
                        },
                        status=status.HTTP_409_CONFLICT,
                    )

                guest_transaction.status = "processing"
                guest_transaction.save(update_fields=["status"])

        except GuestTransaction.DoesNotExist:
            return Response(
                {"detail": "Guest transaction not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Paystack verification occurs after this request has claimed
        # the transaction.
        paystack_response = PaystackService.verify_transaction(reference)

        if not paystack_response.get("status"):
            guest_transaction.status = "pending"
            guest_transaction.metadata = {
                **(guest_transaction.metadata or {}),
                "payment_verification": "outcome_unknown",
            }
            guest_transaction.save(
                update_fields=["status", "metadata"]
            )

            return Response(
                {
                    "detail": (
                        "Payment verification could not be confirmed "
                        "right now. Please try again using your "
                        "reference."
                    ),
                    "reference": guest_transaction.reference,
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        paystack_data = paystack_response.get("data") or {}

        if paystack_data.get("status") != "success":
            guest_transaction.status = "pending"
            guest_transaction.metadata = {
                **(guest_transaction.metadata or {}),
                "payment_verification": "not_completed",
            }
            guest_transaction.save(
                update_fields=["status", "metadata"]
            )

            return Response(
                {
                    "detail": "Payment has not been completed.",
                    "reference": guest_transaction.reference,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        verified_currency = str(
            paystack_data.get("currency") or ""
        ).upper()

        if verified_currency != "NGN":
            guest_transaction.status = "pending"
            guest_transaction.save(
                update_fields=["status"]
            )

            return Response(
                {
                    "detail":
                        "Payment currency verification failed.",
                    "reference":
                        guest_transaction.reference,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Confirm that Paystack verified the same transaction reference.
        verified_reference = paystack_data.get("reference")

        if verified_reference != guest_transaction.payment_reference:
            guest_transaction.status = "pending"
            guest_transaction.save(update_fields=["status"])

            return Response(
                {"detail": "Payment reference mismatch."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Paystack returns amounts in kobo. Parse the provider value
        # defensively and never treat malformed payment data as a
        # refund-eligible service failure.
        expected_amount = guest_transaction.amount * Decimal("100")

        try:
            verified_amount = Decimal(
                str(paystack_data.get("amount"))
            )
        except (InvalidOperation, TypeError, ValueError):
            verified_amount = None

        amount_is_valid = (
            verified_amount is not None
            and verified_amount.is_finite()
            and verified_amount == expected_amount
        )

        if not amount_is_valid:
            guest_transaction.status = "pending"
            guest_transaction.save(
                update_fields=["status"]
            )

            return Response(
                {
                    "detail":
                        "The verified payment amount is incorrect.",
                    "reference":
                        guest_transaction.reference,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        guest_transaction.metadata = {
            **(guest_transaction.metadata or {}),
            "payment_verification": "verified",
        }
        guest_transaction.save(update_fields=["metadata"])

        try:
            provider_response = GuestPurchaseService.execute(
                guest_transaction
            )
        except Exception:
            logger.error(
                "Guest provider purchase raised an exception "
                "for reference %s.",
                guest_transaction.reference,
            )

            guest_transaction.status = "pending"
            guest_transaction.provider_response = {
                "result": "provider_outcome_unknown",
            }
            guest_transaction.save(
                update_fields=[
                    "status",
                    "provider_response",
                ]
            )

            return Response(
                {
                    "detail": (
                        "Payment was successful, but the service "
                        "provider outcome could not be confirmed. "
                        "Please contact support with your reference."
                    ),
                    "reference": guest_transaction.reference,
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        provider_response = provider_response or {}

        provider_outcome = classify_vtpass_response(
            provider_response
        )

        is_successful = provider_outcome == "success"

        guest_transaction.provider_response = (
            sanitize_vtpass_response(provider_response)
        )
        guest_transaction.provider_reference = (
            provider_response.get("requestId")
            or provider_response.get("request_id")
            or provider_response.get("transactionId")
            or guest_transaction.reference
        )

        if guest_transaction.service_type == "electricity":
            guest_transaction.token = (
                provider_response.get("token")
                or provider_response.get("purchased_code")
                or (
                    provider_response.get("content") or {}
                ).get("token")
                or ""
            )

        if provider_outcome == "success":
            guest_transaction.status = "success"
        elif provider_outcome == "failed":
            guest_transaction.status = "failed"
        else:
            # Pending, manual-review, malformed, and unknown
            # outcomes must never become refund-eligible failures.
            guest_transaction.status = "pending"

        guest_transaction.save(
            update_fields=[
                "provider_response",
                "provider_reference",
                "token",
                "status",
            ]
        )

        serialized_transaction = GuestTransactionSerializer(
            guest_transaction
        ).data

        if provider_outcome in {
            "pending",
            "manual_review",
        }:
            return Response(
                {
                    "detail": (
                        "Payment was successful, but the service "
                        "provider outcome is still being confirmed. "
                        "Please keep your reference for support."
                    ),
                    "transaction": serialized_transaction,
                },
                status=status.HTTP_202_ACCEPTED,
            )

        if provider_outcome == "failed":
            return Response(
                {
                    "detail": (
                        "Payment was successful, but the service "
                        "purchase could not be completed. "
                        "Please contact support with your reference."
                    ),
                    "transaction": serialized_transaction,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            serialized_transaction,
            status=status.HTTP_200_OK,
        )

class GuestReceiptView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, reference):
        receipt_access_token = request.headers.get(
            "X-Guest-Receipt-Token",
            "",
        )

        if not receipt_access_token:
            return Response(
                {
                    "detail":
                        "Receipt access credentials are required."
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            transaction = GuestTransaction.objects.get(
                reference=reference,
                receipt_access_token=receipt_access_token,
            )
        except GuestTransaction.DoesNotExist:
            return Response(
                {
                    "detail":
                        "Receipt access credentials are invalid."
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        return Response(
            GuestTransactionSerializer(transaction).data,
            status=status.HTTP_200_OK,
        )

class GuestDataPlansView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        network = request.query_params.get("network")

        if not network:
            return Response(
                {"detail": "Network is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            provider_response = (
                VTPassDataService.get_data_plans(network)
            )
        except Exception as exc:
            logger.exception(
                "Unable to load guest data plans for %s",
                network,
            )

            return Response(
                {
                    "detail": (
                        "Unable to fetch data plans from "
                        "the provider."
                    ),
                    "error": str(exc),
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            provider_response,
            status=status.HTTP_200_OK,
        )

class GuestElectricityVerifyView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        provider = request.data.get("provider")
        meter_number = request.data.get("meter_number")
        meter_type = request.data.get("meter_type")

        if not provider:
            return Response(
                {"detail": "Electricity provider is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not meter_number:
            return Response(
                {"detail": "Meter number is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if meter_type not in {"prepaid", "postpaid"}:
            return Response(
                {
                    "detail": (
                        "Meter type must be prepaid or postpaid."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            provider_response = (
                VTPassElectricityService.verify_meter(
                    service_id=provider,
                    billers_code=meter_number,
                    meter_type=meter_type,
                )
            )
        except Exception as exc:
            logger.exception(
                "Guest electricity verification failed for %s",
                meter_number,
            )

            return Response(
                {
                    "detail": "Unable to verify meter details.",
                    "error": str(exc),
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        response_code = str(
            provider_response.get("code", "")
        )

        if response_code not in {"000", "00"}:
            return Response(
                {
                    "detail": (
                        provider_response.get(
                            "response_description"
                        )
                        or provider_response.get("message")
                        or "Meter verification failed."
                    ),
                    "provider_response": provider_response,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            provider_response,
            status=status.HTTP_200_OK,
        )

class GuestCableProvidersView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        providers = [
            {"name": "DStv", "service_id": "dstv"},
            {"name": "GOtv", "service_id": "gotv"},
            {"name": "Startimes", "service_id": "startimes"},
            {"name": "Showmax", "service_id": "showmax"},
        ]

        return Response(
            providers,
            status=status.HTTP_200_OK,
        )


class GuestCablePlansView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        provider = request.query_params.get("provider")

        valid_providers = {
            "dstv",
            "gotv",
            "startimes",
            "showmax",
        }

        if not provider:
            return Response(
                {"detail": "Cable provider is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if provider not in valid_providers:
            return Response(
                {"detail": "Unsupported cable provider."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            provider_response = VTPassCableService.get_plans(
                provider
            )
        except Exception as exc:
            logger.exception(
                "Unable to load guest cable plans for %s",
                provider,
            )

            return Response(
                {
                    "detail": (
                        "Unable to fetch cable plans from "
                        "the provider."
                    ),
                    "error": str(exc),
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            provider_response,
            status=status.HTTP_200_OK,
        )


class GuestCableVerifyView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        provider = request.data.get("provider")
        smartcard_number = request.data.get(
            "smartcard_number"
        )

        valid_providers = {
            "dstv",
            "gotv",
            "startimes",
            "showmax",
        }

        if not provider:
            return Response(
                {"detail": "Cable provider is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if provider not in valid_providers:
            return Response(
                {"detail": "Unsupported cable provider."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not smartcard_number:
            return Response(
                {
                    "detail": (
                        "Smartcard or IUC number is required."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            provider_response = (
                VTPassCableService.verify_smartcard(
                    service_id=provider,
                    smartcard_number=smartcard_number,
                )
            )
        except Exception as exc:
            logger.exception(
                "Guest cable verification failed for %s",
                smartcard_number,
            )

            return Response(
                {
                    "detail": (
                        "Unable to verify the smartcard."
                    ),
                    "error": str(exc),
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        response_code = str(
            provider_response.get("code", "")
        )

        if response_code not in {"000", "00"}:
            return Response(
                {
                    "detail": (
                        provider_response.get(
                            "response_description"
                        )
                        or provider_response.get("message")
                        or "Smartcard verification failed."
                    ),
                    "provider_response": provider_response,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            provider_response,
            status=status.HTTP_200_OK,
        )