import uuid
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status

from .models import PaymentTransaction
from .serializers import InitializePaymentSerializer, PaymentTransactionSerializer
from .services import PaystackService

from wallets.services import WalletService
from notifications.services import NotificationService
from referrals.models import Referral, ReferralProfile
from notifications.email_service import EmailNotificationService

import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.db import transaction as database_transaction
from django.utils import timezone
from rest_framework.permissions import AllowAny

from guest_checkout.models import GuestTransaction

from django.http import HttpResponseRedirect
from urllib.parse import urlencode

from transactions.models import Transaction

from django.db.models import Sum

logger = logging.getLogger(__name__)

REFERRAL_BONUS_AMOUNT = Decimal("100.00")
REFERRAL_FUNDING_THRESHOLD = Decimal("5000.00")

def award_referral_bonus_if_eligible(user):
    """
    Award the referral bonus once the referred user has
    cumulatively funded at least ₦5,000 through successful
    wallet-funding payments.

    Spending from the wallet does not reduce referral progress.
    """

    referral = (
        Referral.objects
        .select_for_update()
        .select_related("referrer")
        .filter(
            referred_user=user,
            bonus_paid=False,
        )
        .first()
    )

    if not referral:
        return False

    total_successful_funding = (
        PaymentTransaction.objects
        .filter(
            user=user,
            status="success",
        )
        .aggregate(
            total=Sum("amount")
        )["total"]
        or Decimal("0.00")
    )

    if (
        total_successful_funding
        < REFERRAL_FUNDING_THRESHOLD
    ):
        return False

    referrer_wallet = (
        referral.referrer.wallet
    )

    bonus_reference = (
        f"REF-BONUS-{referral.id}"
    )

    WalletService.credit_wallet(
        wallet=referrer_wallet,
        amount=REFERRAL_BONUS_AMOUNT,
        reference=bonus_reference,
        description=(
            "Referral bonus for inviting "
            f"{user.email}"
        ),
    )

    referral.bonus_paid = True
    referral.bonus_amount = (
        REFERRAL_BONUS_AMOUNT
    )

    referral.save(
        update_fields=[
            "bonus_paid",
            "bonus_amount",
        ]
    )

    referral_profile, _ = (
        ReferralProfile.objects
        .get_or_create(
            user=referral.referrer
        )
    )

    referral_profile.total_bonus_earned += (
        REFERRAL_BONUS_AMOUNT
    )

    referral_profile.save(
        update_fields=[
            "total_bonus_earned"
        ]
    )

    NotificationService.create_notification(
        user=referral.referrer,
        notification_type="wallet",
        title="Referral Bonus Earned",
        message=(
            f"You earned "
            f"₦{REFERRAL_BONUS_AMOUNT} "
            f"for inviting {user.email}."
        ),
        metadata={
            "reference":
                bonus_reference,
            "referred_user":
                user.email,
            "amount":
                str(
                    REFERRAL_BONUS_AMOUNT
                ),
            "qualification_amount":
                str(
                    total_successful_funding
                ),
        },
    )

    return True

def ensure_wallet_funding_transaction(payment, user):
    transaction, created = Transaction.objects.get_or_create(
        reference=payment.reference,
        defaults={
            "user": user,
            "service_type": "wallet_funding",
            "amount": payment.amount,
            "status": "success",
            "provider": "paystack",
            "provider_reference": payment.reference,
            "description": "Wallet funding via Paystack",
            "metadata": {
                "payment_transaction_id": payment.id,
                "payment_method": "paystack",
                "source": "wallet_funding",
            },
        },
    )

    # If the row already existed but wasn't marked successful,
    # normalize it to the successful wallet-funding state.
    if not created:
        changed = False

        if transaction.status != "success":
            transaction.status = "success"
            changed = True

        if transaction.service_type != "wallet_funding":
            transaction.service_type = "wallet_funding"
            changed = True

        if transaction.provider != "paystack":
            transaction.provider = "paystack"
            changed = True

        if changed:
            transaction.save(
                update_fields=[
                    "status",
                    "service_type",
                    "provider",
                ]
            )

    return transaction

class InitializePaymentView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = InitializePaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        amount = serializer.validated_data["amount"]
        reference = f"NPP-{uuid.uuid4().hex[:16].upper()}"

        # Optional callback URL supplied by the client.
        # The mobile app uses this to return from Paystack
        # back into NaijaPayPoint after payment.
        callback_url = (
            request.data.get("callback_url")
            or f"{settings.FRONTEND_URL}/payment-success"
        )

        print(
            "PAYMENT VIEW CALLBACK:",
            callback_url,
        )

        paystack_response = PaystackService.initialize_transaction(
            email=request.user.email,
            amount=amount,
            reference=reference,
            callback_url=callback_url,
        )

        if not paystack_response.get("status"):
            return Response(
                {
                    "detail": "Unable to initialize payment",
                    "provider_response": paystack_response,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = paystack_response.get("data", {})

        payment = PaymentTransaction.objects.create(
            user=request.user,
            amount=amount,
            reference=reference,
            authorization_url=data.get("authorization_url"),
            status="pending",
        )

        return Response(
            PaymentTransactionSerializer(payment).data,
            status=status.HTTP_201_CREATED,
        )

class VerifyPaymentView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        reference = request.data.get("reference")

        if not reference:
            return Response(
                {"detail": "Reference is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            payment = PaymentTransaction.objects.get(
                reference=reference,
                user=request.user,
            )
        except PaymentTransaction.DoesNotExist:
            return Response(
                {"detail": "Payment not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if payment.status == "success":
            ensure_wallet_funding_transaction(
                payment,
                request.user,
            )

            with transaction.atomic():
                award_referral_bonus_if_eligible(
                    request.user
                )

            return Response(
                PaymentTransactionSerializer(
                    payment
                ).data
            )

        paystack_response = PaystackService.verify_transaction(reference)

        if not paystack_response.get("status"):
            payment.status = "failed"
            payment.save(update_fields=["status"])

            return Response(
                {
                    "detail": "Payment verification failed",
                    "provider_response": paystack_response,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = paystack_response.get("data", {})

        if data.get("status") != "success":
            payment.status = "failed"
            payment.save(update_fields=["status"])

            return Response(
                {"detail": "Payment was not successful"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        paid_amount = Decimal(data.get("amount", 0)) / Decimal("100")

        if paid_amount != payment.amount:
            return Response(
                {"detail": "Payment amount mismatch"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            payment = PaymentTransaction.objects.select_for_update().get(
                id=payment.id
            )

            if payment.status == "success":
                ensure_wallet_funding_transaction(
                    payment,
                    request.user,
                )

                award_referral_bonus_if_eligible(
                    request.user
                )

                return Response(
                    PaymentTransactionSerializer(payment).data
                )

            WalletService.credit_wallet(
                wallet=request.user.wallet,
                amount=payment.amount,
                reference=payment.reference,
                description="Wallet funding via Paystack",
            )

            ensure_wallet_funding_transaction(
                payment,
                request.user,
            )

            payment.status = "success"
            payment.verified_at = timezone.now()
            payment.save(update_fields=["status", "verified_at"])

            NotificationService.create_notification(
                user=request.user,
                notification_type="wallet",
                title="Wallet Funded",
                message=f"Your wallet has been credited with ₦{payment.amount}.",
            )

            EmailNotificationService.send_wallet_funded(
                user=request.user,
                amount=payment.amount,
            )

            award_referral_bonus_if_eligible(
                request.user
            )

        return Response(PaymentTransactionSerializer(payment).data)

class MobilePaymentCallbackView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        reference = (
            request.query_params.get("reference")
            or request.query_params.get("trxref")
            or ""
        ).strip()

        if not reference:
            deep_link = "naijapaypointmobile://wallet-payment"
            return HttpResponseRedirect(deep_link)

        query_string = urlencode(
            {
                "reference": reference,
            }
        )

        deep_link = (
            "naijapaypointmobile://wallet-payment"
            f"?{query_string}"
        )

        return HttpResponseRedirect(deep_link)

class PaystackWebhookView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    REFUND_EVENTS = {
        "refund.pending",
        "refund.processing",
        "refund.processed",
        "refund.failed",
    }

    PAYMENT_EVENTS = {
        "charge.success",
    }

    def post(self, request):
        raw_body = request.body
        received_signature = request.headers.get(
            "x-paystack-signature",
            "",
        )

        expected_signature = hmac.new(
            settings.PAYSTACK_SECRET_KEY.encode("utf-8"),
            raw_body,
            hashlib.sha512,
        ).hexdigest()

        if (
            not received_signature
            or not hmac.compare_digest(
                received_signature,
                expected_signature,
            )
        ):
            logger.warning(
                "Rejected Paystack webhook with invalid signature."
            )

            return Response(
                {"detail": "Invalid webhook signature."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return Response(
                {"detail": "Invalid webhook payload."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        event = payload.get("event", "")
        event_data = payload.get("data") or {}

        # Acknowledge unrelated Paystack events without processing them.
        if event in self.PAYMENT_EVENTS:
            return self._handle_charge_success(
                event_data=event_data,
                payload=payload,
            )

        if event not in self.REFUND_EVENTS:
            return Response(
                {
                    "received": True,
                    "event": event,
                },
                status=status.HTTP_200_OK,
            )

        guest_transaction = self._find_guest_transaction(
            event_data
        )

        if guest_transaction is None:
            # Return 200 so Paystack does not repeatedly resend an event
            # that does not belong to a known guest transaction.
            logger.warning(
                "Refund webhook could not be matched. Event: %s; data: %s",
                event,
                event_data,
            )

            return Response(
                {
                    "received": True,
                    "matched": False,
                    "event": event,
                },
                status=status.HTTP_200_OK,
            )

        with database_transaction.atomic():
            guest_transaction = (
                GuestTransaction.objects
                .select_for_update()
                .get(pk=guest_transaction.pk)
            )

            refund_id = (
                event_data.get("id")
                or event_data.get("refund_id")
                or ""
            )

            provider_refund_status = (
                event_data.get("status")
                or event.replace("refund.", "")
            )

            refund_amount_kobo = event_data.get("amount")

            if refund_amount_kobo is not None:
                try:
                    guest_transaction.refund_amount = (
                        int(refund_amount_kobo) / 100
                    )
                except (TypeError, ValueError):
                    pass

            if refund_id:
                guest_transaction.refund_reference = str(
                    refund_id
                )

            guest_transaction.refund_status = str(
                provider_refund_status
            )

            guest_transaction.refund_response = payload

            metadata = guest_transaction.metadata or {}
            webhook_history = metadata.get(
                "refund_webhook_history",
                [],
            )

            webhook_history.append(
                {
                    "event": event,
                    "status": provider_refund_status,
                    "refund_reference": str(refund_id),
                    "received_at": timezone.now().isoformat(),
                }
            )

            guest_transaction.metadata = {
                **metadata,
                "refund_webhook_history": webhook_history[-20:],
            }

            if event == "refund.processed":
                guest_transaction.status = "refunded"
                guest_transaction.refund_status = "processed"
                guest_transaction.refunded_at = timezone.now()

            elif event == "refund.failed":
                guest_transaction.status = "refund_failed"
                guest_transaction.refund_status = "failed"

            elif event == "refund.processing":
                guest_transaction.status = "refund_pending"
                guest_transaction.refund_status = "processing"

            elif event == "refund.pending":
                guest_transaction.status = "refund_pending"
                guest_transaction.refund_status = "pending"

            guest_transaction.save(
                update_fields=[
                    "status",
                    "refund_reference",
                    "refund_amount",
                    "refund_status",
                    "refund_response",
                    "refunded_at",
                    "metadata",
                    "updated_at",
                ]
            )

        logger.info(
            "Processed Paystack refund webhook %s for %s",
            event,
            guest_transaction.reference,
        )

        return Response(
            {
                "received": True,
                "matched": True,
                "event": event,
                "reference": guest_transaction.reference,
                "refund_status": (
                    guest_transaction.refund_status
                ),
            },
            status=status.HTTP_200_OK,
        )

    @staticmethod
    def _handle_charge_success(
        *,
        event_data,
        payload,
    ):
        reference = str(
            event_data.get("reference") or ""
        ).strip()

        if not reference:
            logger.warning(
                "charge.success webhook missing reference."
            )

            return Response(
                {
                    "received": True,
                    "processed": False,
                    "reason": "missing_reference",
                },
                status=status.HTTP_200_OK,
            )

        try:
            payment = PaymentTransaction.objects.get(
                reference=reference
            )
        except PaymentTransaction.DoesNotExist:
            logger.info(
                "charge.success reference %s does not belong "
                "to a registered wallet payment.",
                reference,
            )

            return Response(
                {
                    "received": True,
                    "processed": False,
                    "reference": reference,
                    "reason": "payment_not_found",
                },
                status=status.HTTP_200_OK,
            )

        paystack_status = str(
            event_data.get("status") or ""
        ).lower()

        if paystack_status != "success":
            return Response(
                {
                    "received": True,
                    "processed": False,
                    "reference": reference,
                    "reason": "payment_not_successful",
                },
                status=status.HTTP_200_OK,
            )

        try:
            paid_amount = (
                Decimal(
                    str(event_data.get("amount") or "0")
                )
                / Decimal("100")
            )
        except Exception:
            logger.warning(
                "Invalid amount in charge.success for %s",
                reference,
            )

            return Response(
                {
                    "received": True,
                    "processed": False,
                    "reference": reference,
                    "reason": "invalid_amount",
                },
                status=status.HTTP_200_OK,
            )

        if paid_amount != payment.amount:
            logger.warning(
                "Paystack amount mismatch for %s. "
                "Expected %s, received %s.",
                reference,
                payment.amount,
                paid_amount,
            )

            return Response(
                {
                    "received": True,
                    "processed": False,
                    "reference": reference,
                    "reason": "amount_mismatch",
                },
                status=status.HTTP_200_OK,
            )

        with database_transaction.atomic():
            payment = (
                PaymentTransaction.objects
                .select_for_update()
                .select_related(
                    "user",
                    "user__wallet",
                )
                .get(pk=payment.pk)
            )

            if payment.status == "success":
                ensure_wallet_funding_transaction(
                    payment,
                    payment.user,
                )

                award_referral_bonus_if_eligible(
                    payment.user
                )

                return Response(
                    {
                        "received": True,
                        "processed": True,
                        "already_processed": True,
                        "reference": reference,
                    },
                    status=status.HTTP_200_OK,
                )

            WalletService.credit_wallet(
                wallet=payment.user.wallet,
                amount=payment.amount,
                reference=payment.reference,
                description="Wallet funding via Paystack",
            )

            payment.status = "success"
            payment.verified_at = timezone.now()

            payment.save(
                update_fields=[
                    "status",
                    "verified_at",
                ]
            )

            NotificationService.create_notification(
                user=payment.user,
                notification_type="wallet",
                title="Wallet Funded",
                message=(
                    f"Your wallet has been credited with "
                    f"₦{payment.amount}."
                ),
                metadata={
                    "reference": payment.reference,
                    "amount": str(payment.amount),
                    "source": "paystack_webhook",
                },
            )

            try:
                EmailNotificationService.send_wallet_funded(
                    user=payment.user,
                    amount=payment.amount,
                )
            except Exception:
                logger.exception(
                    "Wallet funded email failed for %s",
                    payment.reference,
                )

            award_referral_bonus_if_eligible(
                payment.user
            )

        logger.info(
            "Processed charge.success for wallet payment %s",
            reference,
        )

        return Response(
            {
                "received": True,
                "processed": True,
                "reference": reference,
            },
            status=status.HTTP_200_OK,
        )

    @staticmethod
    def _find_guest_transaction(event_data):
        """
        Paystack refund payloads can expose the original transaction
        reference in slightly different nested locations. Try the
        strongest identifiers first.
        """

        transaction_data = event_data.get("transaction") or {}

        if not isinstance(transaction_data, dict):
            transaction_data = {}

        candidate_payment_references = [
            transaction_data.get("reference"),
            event_data.get("transaction_reference"),
            event_data.get("reference"),
        ]

        for payment_reference in candidate_payment_references:
            if not payment_reference:
                continue

            guest_transaction = (
                GuestTransaction.objects
                .filter(
                    payment_reference=str(
                        payment_reference
                    )
                )
                .first()
            )

            if guest_transaction:
                return guest_transaction

            # In the current guest flow, the internal and Paystack
            # references are normally identical.
            guest_transaction = (
                GuestTransaction.objects
                .filter(
                    reference=str(payment_reference)
                )
                .first()
            )

            if guest_transaction:
                return guest_transaction

        refund_id = (
            event_data.get("id")
            or event_data.get("refund_id")
        )

        if refund_id:
            guest_transaction = (
                GuestTransaction.objects
                .filter(
                    refund_reference=str(refund_id)
                )
                .first()
            )

            if guest_transaction:
                return guest_transaction

        return None