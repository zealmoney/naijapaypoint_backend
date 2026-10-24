from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from transactions.models import Transaction

from .models import PaymentTransaction
from .views import (
    PaystackWebhookView,
    ensure_wallet_funding_transaction,
)

from unittest.mock import patch

from rest_framework.test import APIClient
from django.conf import settings

import hashlib
import hmac
import json

from django.urls import reverse
from django.utils import timezone
from guest_checkout.models import GuestTransaction

from .services import PaystackService

User = get_user_model()


class WalletFundingTransactionSecurityTests(
    TestCase
):
    def setUp(self):
        self.user = User.objects.create_user(
            username="payment_security_test",
            email="payment-security@example.com",
            password="test-password-123",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_conflicting_canonical_transaction_fails_closed(
        self,
    ):
        reference = "NPP-CONFLICT-TEST"

        payment = PaymentTransaction.objects.create(
            user=self.user,
            amount=Decimal("5000.00"),
            reference=reference,
            status="success",
        )

        existing_tx = Transaction.objects.create(
            user=self.user,
            service_type="airtime",
            amount=Decimal("1000.00"),
            reference=reference,
            status="success",
            provider="vtpass",
            description="Existing unrelated transaction",
        )

        with self.assertRaises(ValueError):
            ensure_wallet_funding_transaction(
                payment,
                self.user,
            )

        existing_tx.refresh_from_db()

        self.assertEqual(
            existing_tx.service_type,
            "airtime",
        )
        self.assertEqual(
            existing_tx.amount,
            Decimal("1000.00"),
        )
        self.assertEqual(
            existing_tx.provider,
            "vtpass",
        )

    def test_canonical_transaction_is_idempotent(
        self,
    ):
        reference = "NPP-IDEMPOTENT-TEST"

        payment = PaymentTransaction.objects.create(
            user=self.user,
            amount=Decimal("5000.00"),
            reference=reference,
            status="success",
        )

        first_tx = ensure_wallet_funding_transaction(
            payment,
            self.user,
        )

        second_tx = ensure_wallet_funding_transaction(
            payment,
            self.user,
        )

        self.assertEqual(
            first_tx.pk,
            second_tx.pk,
        )

        self.assertEqual(
            Transaction.objects.filter(
                reference=reference,
            ).count(),
            1,
        )

        first_tx.refresh_from_db()

        self.assertEqual(
            first_tx.user,
            self.user,
        )
        self.assertEqual(
            first_tx.service_type,
            "wallet_funding",
        )
        self.assertEqual(
            first_tx.amount,
            Decimal("5000.00"),
        )
        self.assertEqual(
            first_tx.status,
            "success",
        )
        self.assertEqual(
            first_tx.provider,
            "paystack",
        )
        self.assertEqual(
            first_tx.provider_reference,
            reference,
        )
        self.assertEqual(
            first_tx.metadata[
                "payment_transaction_id"
            ],
            payment.id,
        )

    @patch(
        "payments.views."
        "PaystackService.verify_transaction"
    )
    def test_verify_rejects_provider_reference_mismatch(
        self,
        mock_verify,
    ):
        payment = PaymentTransaction.objects.create(
            user=self.user,
            amount=Decimal("5000.00"),
            reference="NPP-EXPECTED-REFERENCE",
        )

        starting_balance = self.user.wallet.balance

        mock_verify.return_value = {
            "status": True,
            "data": {
                "status": "success",
                "reference":
                    "NPP-DIFFERENT-REFERENCE",
                "amount": 500000,
                "currency": "NGN",
            },
        }

        response = self.client.post(
            "/api/payments/verify/",
            {
                "reference": payment.reference,
            },
            format="json",
        )

        payment.refresh_from_db()
        self.user.wallet.refresh_from_db()

        self.assertNotEqual(
            response.status_code,
            200,
        )
        self.assertEqual(
            payment.status,
            "pending",
        )
        self.assertEqual(
            self.user.wallet.balance,
            starting_balance,
        )
        self.assertFalse(
            Transaction.objects.filter(
                reference=payment.reference,
                service_type="wallet_funding",
            ).exists()
        )

    @patch(
        "payments.views."
        "PaystackService.verify_transaction"
    )
    def test_verify_rejects_non_ngn_currency(
        self,
        mock_verify,
    ):
        payment = PaymentTransaction.objects.create(
            user=self.user,
            amount=Decimal("5000.00"),
            reference="NPP-CURRENCY-TEST",
        )

        starting_balance = self.user.wallet.balance

        mock_verify.return_value = {
            "status": True,
            "data": {
                "status": "success",
                "reference": payment.reference,
                "amount": 500000,
                "currency": "USD",
            },
        }

        response = self.client.post(
            "/api/payments/verify/",
            {
                "reference": payment.reference,
            },
            format="json",
        )

        payment.refresh_from_db()
        self.user.wallet.refresh_from_db()

        self.assertNotEqual(
            response.status_code,
            200,
        )
        self.assertEqual(
            payment.status,
            "pending",
        )
        self.assertEqual(
            self.user.wallet.balance,
            starting_balance,
        )
        self.assertFalse(
            Transaction.objects.filter(
                reference=payment.reference,
                service_type="wallet_funding",
            ).exists()
        )

    @patch(
        "payments.views."
        "EmailNotificationService.send_wallet_funded"
    )
    @patch(
        "payments.views."
        "NotificationService.create_notification"
    )
    def test_webhook_first_success_creates_canonical_transaction(
        self,
        mock_notification,
        mock_email,
    ):
        payment = PaymentTransaction.objects.create(
            user=self.user,
            amount=Decimal("5000.00"),
            reference="NPP-WEBHOOK-CANONICAL",
        )

        starting_balance = self.user.wallet.balance

        response = (
            PaystackWebhookView
            ._handle_charge_success(
                event_data={
                    "status": "success",
                    "reference":
                        payment.reference,
                    "amount": 500000,
                    "currency": "NGN",
                },
                payload={
                    "event": "charge.success",
                },
            )
        )

        payment.refresh_from_db()
        self.user.wallet.refresh_from_db()

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertEqual(
            payment.status,
            "success",
        )
        self.assertEqual(
            self.user.wallet.balance,
            starting_balance
            + Decimal("5000.00"),
        )

        canonical_tx = Transaction.objects.get(
            reference=payment.reference,
        )

        self.assertEqual(
            canonical_tx.user,
            self.user,
        )
        self.assertEqual(
            canonical_tx.service_type,
            "wallet_funding",
        )
        self.assertEqual(
            canonical_tx.amount,
            payment.amount,
        )
        self.assertEqual(
            canonical_tx.status,
            "success",
        )
        self.assertEqual(
            canonical_tx.provider,
            "paystack",
        )

    @patch(
        "payments.views."
        "EmailNotificationService.send_wallet_funded"
    )
    @patch(
        "payments.views."
        "NotificationService.create_notification"
    )
    def test_webhook_rejects_non_ngn_currency(
        self,
        mock_notification,
        mock_email,
    ):
        payment = PaymentTransaction.objects.create(
            user=self.user,
            amount=Decimal("5000.00"),
            reference="NPP-WEBHOOK-CURRENCY",
        )

        starting_balance = self.user.wallet.balance

        response = (
            PaystackWebhookView
            ._handle_charge_success(
                event_data={
                    "status": "success",
                    "reference": payment.reference,
                    "amount": 500000,
                    "currency": "USD",
                },
                payload={
                    "event": "charge.success",
                },
            )
        )

        payment.refresh_from_db()
        self.user.wallet.refresh_from_db()

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertFalse(
            response.data["processed"]
        )
        self.assertEqual(
            response.data["reason"],
            "currency_mismatch",
        )
        self.assertEqual(
            payment.status,
            "pending",
        )
        self.assertEqual(
            self.user.wallet.balance,
            starting_balance,
        )
        self.assertFalse(
            Transaction.objects.filter(
                reference=payment.reference,
            ).exists()
        )

    @patch(
        "payments.views."
        "EmailNotificationService.send_wallet_funded"
    )
    @patch(
        "payments.views."
        "NotificationService.create_notification"
    )
    def test_webhook_duplicate_success_is_idempotent(
        self,
        mock_notification,
        mock_email,
    ):
        payment = PaymentTransaction.objects.create(
            user=self.user,
            amount=Decimal("5000.00"),
            reference="NPP-WEBHOOK-DUPLICATE",
        )

        starting_balance = self.user.wallet.balance

        event_data = {
            "status": "success",
            "reference": payment.reference,
            "amount": 500000,
            "currency": "NGN",
        }

        first_response = (
            PaystackWebhookView
            ._handle_charge_success(
                event_data=event_data,
                payload={
                    "event": "charge.success",
                },
            )
        )

        second_response = (
            PaystackWebhookView
            ._handle_charge_success(
                event_data=event_data,
                payload={
                    "event": "charge.success",
                },
            )
        )

        payment.refresh_from_db()
        self.user.wallet.refresh_from_db()

        self.assertEqual(
            first_response.status_code,
            200,
        )
        self.assertEqual(
            second_response.status_code,
            200,
        )
        self.assertTrue(
            second_response.data["already_processed"]
        )
        self.assertEqual(
            payment.status,
            "success",
        )
        self.assertEqual(
            self.user.wallet.balance,
            starting_balance + Decimal("5000.00"),
        )
        self.assertEqual(
            Transaction.objects.filter(
                reference=payment.reference,
                service_type="wallet_funding",
            ).count(),
            1,
        )

    @patch(
        "payments.views."
        "EmailNotificationService.send_wallet_funded"
    )
    @patch(
        "payments.views."
        "NotificationService.create_notification"
    )
    def test_webhook_canonical_conflict_rolls_back_credit(
        self,
        mock_notification,
        mock_email,
    ):
        payment = PaymentTransaction.objects.create(
            user=self.user,
            amount=Decimal("5000.00"),
            reference="NPP-WEBHOOK-CONFLICT",
        )

        existing_tx = Transaction.objects.create(
            user=self.user,
            reference=payment.reference,
            service_type="airtime",
            amount=Decimal("1000.00"),
            status="success",
            provider="vtpass",
        )

        starting_balance = self.user.wallet.balance

        with self.assertRaises(ValueError):
            PaystackWebhookView._handle_charge_success(
                event_data={
                    "status": "success",
                    "reference": payment.reference,
                    "amount": 500000,
                    "currency": "NGN",
                },
                payload={
                    "event": "charge.success",
                },
            )

        payment.refresh_from_db()
        existing_tx.refresh_from_db()
        self.user.wallet.refresh_from_db()

        self.assertEqual(payment.status, "pending")
        self.assertEqual(
            self.user.wallet.balance,
            starting_balance,
        )
        self.assertEqual(
            existing_tx.service_type,
            "airtime",
        )
        self.assertEqual(
            existing_tx.amount,
            Decimal("1000.00"),
        )
        self.assertEqual(
            existing_tx.provider,
            "vtpass",
        )

    @patch(
        "payments.views."
        "PaystackService.verify_transaction"
    )
    def test_verify_rejects_malformed_provider_amount(
        self,
        mock_verify,
    ):
        payment = PaymentTransaction.objects.create(
            user=self.user,
            amount=Decimal("5000.00"),
            reference="NPP-MALFORMED-AMOUNT",
        )

        starting_balance = self.user.wallet.balance

        mock_verify.return_value = {
            "status": True,
            "data": {
                "status": "success",
                "reference": payment.reference,
                "amount": "not-a-number",
                "currency": "NGN",
            },
        }

        response = self.client.post(
            "/api/payments/verify/",
            {
                "reference": payment.reference,
            },
            format="json",
        )

        payment.refresh_from_db()
        self.user.wallet.refresh_from_db()

        self.assertEqual(
            response.status_code,
            400,
        )
        self.assertEqual(
            payment.status,
            "pending",
        )
        self.assertEqual(
            self.user.wallet.balance,
            starting_balance,
        )
        self.assertFalse(
            Transaction.objects.filter(
                reference=payment.reference,
            ).exists()
        )

    @patch(
        "payments.views."
        "EmailNotificationService.send_wallet_funded"
    )
    @patch(
        "payments.views."
        "NotificationService.create_notification"
    )
    def test_webhook_rejects_non_finite_amount(
        self,
        mock_notification,
        mock_email,
    ):
        payment = PaymentTransaction.objects.create(
            user=self.user,
            amount=Decimal("5000.00"),
            reference="NPP-WEBHOOK-NAN",
        )

        starting_balance = self.user.wallet.balance

        response = (
            PaystackWebhookView
            ._handle_charge_success(
                event_data={
                    "status": "success",
                    "reference": payment.reference,
                    "amount": "NaN",
                    "currency": "NGN",
                },
                payload={
                    "event": "charge.success",
                },
            )
        )

        payment.refresh_from_db()
        self.user.wallet.refresh_from_db()

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertFalse(
            response.data["processed"]
        )
        self.assertEqual(
            response.data["reason"],
            "invalid_amount",
        )
        self.assertEqual(
            payment.status,
            "pending",
        )
        self.assertEqual(
            self.user.wallet.balance,
            starting_balance,
        )
        self.assertFalse(
            Transaction.objects.filter(
                reference=payment.reference,
            ).exists()
        )

    def test_webhook_rejects_invalid_signature(self):
        payment = PaymentTransaction.objects.create(
            user=self.user,
            amount=Decimal("5000.00"),
            reference="NPP-WEBHOOK-BAD-SIGNATURE",
        )

        starting_balance = self.user.wallet.balance

        response = self.client.post(
            "/api/payments/webhook/",
            {
                "event": "charge.success",
                "data": {
                    "status": "success",
                    "reference": payment.reference,
                    "amount": 500000,
                    "currency": "NGN",
                },
            },
            format="json",
            HTTP_X_PAYSTACK_SIGNATURE="invalid-signature",
        )

        payment.refresh_from_db()
        self.user.wallet.refresh_from_db()

        self.assertEqual(
            response.status_code,
            403,
        )
        self.assertEqual(
            payment.status,
            "pending",
        )
        self.assertEqual(
            self.user.wallet.balance,
            starting_balance,
        )
        self.assertFalse(
            Transaction.objects.filter(
                reference=payment.reference,
            ).exists()
        )

    @patch(
        "payments.views."
        "PaystackService.initialize_transaction"
    )
    def test_initialize_does_not_trust_external_callback(
        self,
        mock_initialize,
    ):
        mock_initialize.return_value = {
            "status": True,
            "data": {
                "authorization_url":
                    "https://checkout.example.test/payment",
            },
        }

        response = self.client.post(
            "/api/payments/initialize/",
            {
                "amount": "5000.00",
                "callback_url":
                    "https://attacker.example/callback",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            201,
        )

        mock_initialize.assert_called_once()

        callback_url = (
            mock_initialize.call_args.kwargs[
                "callback_url"
            ]
        )

        self.assertEqual(
            callback_url,
            f"{settings.FRONTEND_URL}/wallet",
        )

    @patch(
        "payments.views."
        "PaystackService.verify_transaction"
    )
    def test_verify_provider_error_keeps_payment_pending(
        self,
        mock_verify,
    ):
        payment = PaymentTransaction.objects.create(
            user=self.user,
            amount=Decimal("5000.00"),
            reference="NPP-VERIFY-UNAVAILABLE",
            status="pending",
        )

        mock_verify.return_value = {
            "status": False,
            "message":
                "Paystack verification request timed out.",
        }

        response = self.client.post(
            "/api/payments/verify/",
            {
                "reference": payment.reference,
            },
            format="json",
        )

        payment.refresh_from_db()

        self.assertEqual(
            payment.status,
            "pending",
        )

        self.assertNotEqual(
            response.status_code,
            200,
        )

    @patch(
        "payments.views."
        "PaystackService.verify_transaction"
    )
    def test_verify_pending_provider_status_stays_pending(
        self,
        mock_verify,
    ):
        payment = PaymentTransaction.objects.create(
            user=self.user,
            amount=Decimal("5000.00"),
            reference="NPP-VERIFY-PENDING",
            status="pending",
        )

        mock_verify.return_value = {
            "status": True,
            "data": {
                "status": "pending",
                "reference": payment.reference,
                "amount": 500000,
                "currency": "NGN",
            },
        }

        response = self.client.post(
            "/api/payments/verify/",
            {
                "reference": payment.reference,
            },
            format="json",
        )

        payment.refresh_from_db()

        self.assertEqual(
            payment.status,
            "pending",
        )

        self.assertNotEqual(
            response.status_code,
            200,
        )

    @patch(
        "payments.views."
        "PaystackService.verify_transaction"
    )
    def test_verify_reversed_status_does_not_credit_or_fail(
        self,
        mock_verify,
    ):
        payment = PaymentTransaction.objects.create(
            user=self.user,
            amount=Decimal("5000.00"),
            reference="NPP-VERIFY-REVERSED",
            status="pending",
        )

        initial_balance = self.user.wallet.balance

        mock_verify.return_value = {
            "status": True,
            "data": {
                "status": "reversed",
                "reference": payment.reference,
                "amount": 500000,
                "currency": "NGN",
            },
        }

        response = self.client.post(
            "/api/payments/verify/",
            {
                "reference": payment.reference,
            },
            format="json",
        )

        payment.refresh_from_db()
        self.user.wallet.refresh_from_db()

        self.assertEqual(
            payment.status,
            "pending",
        )

        self.assertEqual(
            self.user.wallet.balance,
            initial_balance,
        )

        self.assertNotEqual(
            response.status_code,
            200,
        )

    @patch(
        "payments.views."
        "EmailNotificationService.send_wallet_funded"
    )
    @patch(
        "payments.views."
        "PaystackService.verify_transaction"
    )
    def test_verify_email_failure_does_not_rollback_payment(
        self,
        mock_verify,
        mock_email,
    ):
        payment = PaymentTransaction.objects.create(
            user=self.user,
            amount=Decimal("5000.00"),
            reference="NPP-VERIFY-EMAIL-FAILURE",
            status="pending",
        )

        initial_balance = self.user.wallet.balance

        mock_verify.return_value = {
            "status": True,
            "data": {
                "status": "success",
                "reference": payment.reference,
                "amount": 500000,
                "currency": "NGN",
            },
        }

        mock_email.side_effect = RuntimeError(
            "Email provider unavailable"
        )

        response = self.client.post(
            "/api/payments/verify/",
            {
                "reference": payment.reference,
            },
            format="json",
        )

        payment.refresh_from_db()
        self.user.wallet.refresh_from_db()

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            payment.status,
            "success",
        )

        self.assertEqual(
            self.user.wallet.balance,
            initial_balance + Decimal("5000.00"),
        )

    @patch(
        "payments.views."
        "PaystackService.verify_transaction"
    )
    def test_verify_unknown_provider_status_stays_pending(
        self,
        mock_verify,
    ):
        payment = PaymentTransaction.objects.create(
            user=self.user,
            amount=Decimal("5000.00"),
            reference="NPP-VERIFY-UNKNOWN",
            status="pending",
        )

        initial_balance = self.user.wallet.balance

        mock_verify.return_value = {
            "status": True,
            "data": {
                "status": "unexpected_status",
                "reference": payment.reference,
                "amount": 500000,
                "currency": "NGN",
            },
        }

        response = self.client.post(
            "/api/payments/verify/",
            {
                "reference": payment.reference,
            },
            format="json",
        )

        payment.refresh_from_db()
        self.user.wallet.refresh_from_db()

        self.assertEqual(
            response.status_code,
            202,
        )

        self.assertEqual(
            payment.status,
            "pending",
        )

        self.assertEqual(
            self.user.wallet.balance,
            initial_balance,
        )

    @patch(
        "payments.views."
        "PaystackService.verify_transaction"
    )
    def test_verify_confirmed_failed_status_marks_payment_failed(
        self,
        mock_verify,
    ):
        payment = PaymentTransaction.objects.create(
            user=self.user,
            amount=Decimal("5000.00"),
            reference="NPP-VERIFY-FAILED",
            status="pending",
        )

        initial_balance = self.user.wallet.balance

        mock_verify.return_value = {
            "status": True,
            "data": {
                "status": "failed",
                "reference": payment.reference,
                "amount": 500000,
                "currency": "NGN",
            },
        }

        response = self.client.post(
            "/api/payments/verify/",
            {
                "reference": payment.reference,
            },
            format="json",
        )

        payment.refresh_from_db()
        self.user.wallet.refresh_from_db()

        self.assertEqual(
            response.status_code,
            400,
        )

        self.assertEqual(
            payment.status,
            "failed",
        )

        self.assertEqual(
            self.user.wallet.balance,
            initial_balance,
        )

    @patch(
        "payments.views."
        "PaystackService.initialize_transaction"
    )
    def test_initialization_does_not_expose_paystack_failure_response(
        self,
        mock_initialize,
    ):
        mock_initialize.return_value = {
            "status": False,
            "message": "Provider rejected request",
            "data": {
                "internal_provider_detail":
                    "DO NOT EXPOSE",
            },
        }

        response = self.client.post(
            "/api/payments/initialize/",
            {
                "amount": "5000.00",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            502,
        )

        self.assertEqual(
            response.data,
            {
                "detail": (
                    "Unable to initialize payment right now. "
                    "Please try again."
                ),
            },
        )

        response_text = str(response.data)

        self.assertNotIn(
            "Provider rejected request",
            response_text,
        )
        self.assertNotIn(
            "DO NOT EXPOSE",
            response_text,
        )
        self.assertNotIn(
            "provider_response",
            response.data,
        )

    @patch(
        "payments.views."
        "PaystackService.initialize_transaction"
    )
    def test_initialization_handles_paystack_exception_safely(
        self,
        mock_initialize,
    ):
        mock_initialize.side_effect = TimeoutError(
            "secret provider timeout detail"
        )

        response = self.client.post(
            "/api/payments/initialize/",
            {
                "amount": "5000.00",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            502,
        )

        self.assertEqual(
            response.data,
            {
                "detail": (
                    "Unable to initialize payment right now. "
                    "Please try again."
                ),
            },
        )

        self.assertNotIn(
            "secret provider timeout detail",
            str(response.data),
        )

class PaystackRefundServiceSecurityTests(TestCase):
    @patch("payments.services.requests.post")
    def test_invalid_json_refund_response_has_unknown_outcome(
        self, mock_post
    ):
        mock_response = mock_post.return_value
        mock_response.status_code = 200
        mock_response.ok = True
        mock_response.json.side_effect = ValueError("Invalid JSON")

        result = PaystackService.create_refund(
            transaction_reference="GUEST-REFUND-JSON-001",
            amount=Decimal("2000.00"),
        )

        self.assertFalse(result["status"])
        self.assertEqual(result["outcome"], "unknown")
        self.assertEqual(result["http_status"], 200)

        mock_post.assert_called_once()
        self.assertEqual(
            mock_post.call_args.kwargs["json"]["amount"],
            200000,
        )

    @patch("payments.services.requests.post")
    def test_invalid_refund_amounts_are_rejected_before_provider_call(
        self, mock_post
    ):
        invalid_amounts = [
            Decimal("0"),
            Decimal("-100"),
            Decimal("10.001"),
            Decimal("NaN"),
            Decimal("Infinity"),
            Decimal("-Infinity"),
            "invalid",
            "",
        ]

        for amount in invalid_amounts:
            with self.subTest(amount=str(amount)):
                result = PaystackService.create_refund(
                    transaction_reference="GUEST-REFUND-INVALID-001",
                    amount=amount,
                )

                self.assertFalse(result["status"])
                self.assertEqual(
                    result["outcome"],
                    "invalid_amount",
                )

        mock_post.assert_not_called()

class GuestRefundWebhookSecurityTests(TestCase):

    def test_missing_refund_id_cannot_complete_refund(self):
        transaction = GuestTransaction.objects.create(
            guest_email="guest@example.com",
            guest_phone="08000000001",
            service_type="airtime",
            provider="mtn",
            amount=Decimal("2000.00"),
            recipient="08000000001",
            reference="GUEST-REFUND-NO-ID-001",
            payment_reference="GUEST-REFUND-NO-ID-001",
            status="refund_pending",
            refund_amount=Decimal("2000.00"),
            refund_status="pending",
        )

        payload = {
            "event": "refund.processed",
            "data": {
                "amount": 200000,
                "transaction": {
                    "reference": transaction.payment_reference,
                },
                "status": "processed",
            },
        }

        raw_body = json.dumps(payload).encode("utf-8")

        signature = hmac.new(
            settings.PAYSTACK_SECRET_KEY.encode("utf-8"),
            raw_body,
            hashlib.sha512,
        ).hexdigest()

        response = APIClient().post(
            "/api/payments/webhook/",
            data=raw_body,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=signature,
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["matched"])

        transaction.refresh_from_db()

        self.assertEqual(transaction.status, "refund_pending")
        self.assertEqual(transaction.refund_status, "pending")
        self.assertFalse(transaction.refund_reference)
        self.assertIsNone(transaction.refunded_at)

    def test_delayed_pending_event_cannot_reverse_refund(self):

        transaction = GuestTransaction.objects.create(
            guest_email="guest@example.com",
            guest_phone="08000000001",
            service_type="airtime",
            provider="mtn",
            amount=Decimal("2000.00"),
            recipient="08000000001",
            reference="GUEST-REFUND-SECURITY-001",
            payment_reference="GUEST-REFUND-SECURITY-001",
            status="refunded",
            refund_reference="REFUND-SECURITY-001",
            refund_amount=Decimal("2000.00"),
            refund_status="processed",
            refunded_at=timezone.now(),
        )

        original_refunded_at = transaction.refunded_at

        payload = {
            "event": "refund.pending",
            "data": {
                "id": "REFUND-SECURITY-001",
                "amount": 200000,
                "transaction": {
                    "reference": transaction.payment_reference,
                },
                "status": "pending",
            },
        }

        raw_body = json.dumps(payload).encode("utf-8")

        signature = hmac.new(
            settings.PAYSTACK_SECRET_KEY.encode("utf-8"),
            raw_body,
            hashlib.sha512,
        ).hexdigest()

        response = APIClient().post(
            "/api/payments/webhook/",
            data=raw_body,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=signature,
        )

        self.assertEqual(response.status_code, 200)

        transaction.refresh_from_db()

        self.assertEqual(transaction.status, "refunded")
        self.assertEqual(transaction.refund_status, "processed")
        self.assertEqual(
            transaction.refunded_at,
            original_refunded_at,
        )

    def test_mismatched_refund_id_cannot_update_transaction(self):

        transaction = GuestTransaction.objects.create(
            guest_email="guest@example.com",
            guest_phone="08000000001",
            service_type="airtime",
            provider="mtn",
            amount=Decimal("2000.00"),
            recipient="08000000001",
            reference="GUEST-REFUND-MISMATCH-001",
            payment_reference="GUEST-REFUND-MISMATCH-001",
            status="refund_pending",
            refund_reference="REFUND-ORIGINAL-001",
            refund_amount=Decimal("2000.00"),
            refund_status="pending",
        )

        payload = {
            "event": "refund.processed",
            "data": {
                "id": "REFUND-DIFFERENT-999",
                "amount": 200000,
                "transaction": {
                    "reference": transaction.payment_reference,
                },
                "status": "processed",
            },
        }

        raw_body = json.dumps(payload).encode("utf-8")

        signature = hmac.new(
            settings.PAYSTACK_SECRET_KEY.encode("utf-8"),
            raw_body,
            hashlib.sha512,
        ).hexdigest()

        response = APIClient().post(
            "/api/payments/webhook/",
            data=raw_body,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=signature,
        )

        self.assertEqual(response.status_code, 200)

        transaction.refresh_from_db()

        self.assertEqual(
            transaction.status,
            "refund_pending",
        )
        self.assertEqual(
            transaction.refund_reference,
            "REFUND-ORIGINAL-001",
        )
        self.assertEqual(
            transaction.refund_status,
            "pending",
        )
        self.assertIsNone(transaction.refunded_at)

    def test_mismatched_refund_id_cannot_update_transaction(self):
        transaction = GuestTransaction.objects.create(
            guest_email="guest@example.com",
            guest_phone="08000000001",
            service_type="airtime",
            provider="mtn",
            amount=Decimal("2000.00"),
            recipient="08000000001",
            reference="GUEST-REFUND-MISMATCH-001",
            payment_reference="GUEST-REFUND-MISMATCH-001",
            status="refund_pending",
            refund_reference="REFUND-ORIGINAL-001",
            refund_amount=Decimal("2000.00"),
            refund_status="pending",
        )

        payload = {
            "event": "refund.processed",
            "data": {
                "id": "REFUND-DIFFERENT-999",
                "amount": 200000,
                "transaction": {
                    "reference": transaction.payment_reference,
                },
                "status": "processed",
            },
        }

        raw_body = json.dumps(payload).encode("utf-8")

        signature = hmac.new(
            settings.PAYSTACK_SECRET_KEY.encode("utf-8"),
            raw_body,
            hashlib.sha512,
        ).hexdigest()

        response = APIClient().post(
            "/api/payments/webhook/",
            data=raw_body,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=signature,
        )

        self.assertEqual(response.status_code, 200)

        transaction.refresh_from_db()

        self.assertEqual(
            transaction.status,
            "refund_pending",
        )
        self.assertEqual(
            transaction.refund_reference,
            "REFUND-ORIGINAL-001",
        )
        self.assertEqual(
            transaction.refund_status,
            "pending",
        )
        self.assertIsNone(transaction.refunded_at)

    def test_mismatched_refund_amount_cannot_complete_refund(self):
        transaction = GuestTransaction.objects.create(
            guest_email="guest@example.com",
            guest_phone="08000000001",
            service_type="airtime",
            provider="mtn",
            amount=Decimal("2000.00"),
            recipient="08000000001",
            reference="GUEST-REFUND-AMOUNT-001",
            payment_reference="GUEST-REFUND-AMOUNT-001",
            status="refund_pending",
            refund_reference="REFUND-AMOUNT-001",
            refund_amount=Decimal("2000.00"),
            refund_status="pending",
        )

        payload = {
            "event": "refund.processed",
            "data": {
                "id": "REFUND-AMOUNT-001",
                "amount": 100000,
                "transaction": {
                    "reference": transaction.payment_reference,
                },
                "status": "processed",
            },
        }

        raw_body = json.dumps(payload).encode("utf-8")

        signature = hmac.new(
            settings.PAYSTACK_SECRET_KEY.encode("utf-8"),
            raw_body,
            hashlib.sha512,
        ).hexdigest()

        response = APIClient().post(
            "/api/payments/webhook/",
            data=raw_body,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=signature,
        )

        self.assertEqual(response.status_code, 200)

        transaction.refresh_from_db()

        self.assertEqual(
            transaction.status,
            "refund_pending",
        )
        self.assertEqual(
            transaction.refund_amount,
            Decimal("2000.00"),
        )
        self.assertEqual(
            transaction.refund_status,
            "pending",
        )
        self.assertIsNone(transaction.refunded_at)

    def test_refund_webhook_does_not_store_sensitive_provider_data(self):
        transaction = GuestTransaction.objects.create(
            guest_email="guest@example.com",
            guest_phone="08000000001",
            service_type="airtime",
            provider="mtn",
            amount=Decimal("2000.00"),
            recipient="08000000001",
            reference="GUEST-REFUND-PRIVACY-001",
            payment_reference="GUEST-REFUND-PRIVACY-001",
            status="refund_pending",
            refund_reference="REFUND-PRIVACY-001",
            refund_amount=Decimal("2000.00"),
            refund_status="pending",
        )

        payload = {
            "event": "refund.processed",
            "data": {
                "id": "REFUND-PRIVACY-001",
                "amount": 200000,
                "status": "processed",
                "transaction": {
                    "reference": transaction.payment_reference,
                },
                "customer_email": "sensitive@example.com",
                "customer_phone": "08012345678",
                "secret_provider_data": "PRIVATE-REFUND-SECRET",
            },
        }

        raw_body = json.dumps(payload).encode("utf-8")

        signature = hmac.new(
            settings.PAYSTACK_SECRET_KEY.encode("utf-8"),
            raw_body,
            hashlib.sha512,
        ).hexdigest()

        response = APIClient().post(
            "/api/payments/webhook/",
            data=raw_body,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=signature,
        )

        self.assertEqual(response.status_code, 200)

        transaction.refresh_from_db()

        self.assertEqual(transaction.status, "refunded")

        self.assertEqual(
            transaction.refund_response,
            {
                "event": "refund.processed",
                "refund_reference": "REFUND-PRIVACY-001",
                "status": "processed",
                "amount_kobo": 200000,
            },
        )

        stored_data = json.dumps({
            "refund_response": transaction.refund_response,
            "metadata": transaction.metadata,
        })

        self.assertNotIn(
            "sensitive@example.com",
            stored_data,
        )
        self.assertNotIn(
            "08012345678",
            stored_data,
        )
        self.assertNotIn(
            "PRIVATE-REFUND-SECRET",
            stored_data,
        )

    def test_refund_webhook_cannot_refund_without_authorization(self):
        transaction = GuestTransaction.objects.create(
            guest_email="guest@example.com",
            guest_phone="08000000001",
            service_type="airtime",
            provider="mtn",
            amount=Decimal("2000.00"),
            recipient="08000000001",
            reference="GUEST-REFUND-UNAUTHORIZED-001",
            payment_reference="GUEST-REFUND-UNAUTHORIZED-001",
            status="failed",
            refund_amount=Decimal("2000.00"),
            refund_status="",
        )

        payload = {
            "event": "refund.processed",
            "data": {
                "id": "REFUND-UNAUTHORIZED-001",
                "amount": 200000,
                "status": "processed",
                "transaction": {
                    "reference": transaction.payment_reference,
                },
            },
        }

        raw_body = json.dumps(payload).encode("utf-8")

        signature = hmac.new(
            settings.PAYSTACK_SECRET_KEY.encode("utf-8"),
            raw_body,
            hashlib.sha512,
        ).hexdigest()

        response = APIClient().post(
            "/api/payments/webhook/",
            data=raw_body,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=signature,
        )

        self.assertEqual(response.status_code, 200)

        transaction.refresh_from_db()

        self.assertEqual(transaction.status, "failed")
        self.assertEqual(transaction.refund_status, "")
        self.assertEqual(
            transaction.refund_amount,
            Decimal("2000.00"),
        )
        self.assertFalse(transaction.refund_reference)
        self.assertIsNone(transaction.refunded_at)

    def test_delayed_processing_event_cannot_reopen_failed_refund(self):
        transaction = GuestTransaction.objects.create(
            guest_email="guest@example.com",
            guest_phone="08000000001",
            service_type="airtime",
            provider="mtn",
            amount=Decimal("2000.00"),
            recipient="08000000001",
            reference="GUEST-REFUND-DELAYED-001",
            payment_reference="GUEST-REFUND-DELAYED-001",
            status="refund_failed",
            refund_reference="REFUND-DELAYED-001",
            refund_amount=Decimal("2000.00"),
            refund_status="failed",
        )

        payload = {
            "event": "refund.processing",
            "data": {
                "id": "REFUND-DELAYED-001",
                "status": "processing",
                "amount": 200000,
                "transaction": {
                    "reference": transaction.payment_reference,
                },
            },
        }

        body = json.dumps(payload).encode("utf-8")

        signature = hmac.new(
            settings.PAYSTACK_SECRET_KEY.encode("utf-8"),
            body,
            hashlib.sha512,
        ).hexdigest()

        response = APIClient().post(
            "/api/payments/webhook/",
            data=body,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=signature,
        )

        transaction.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["matched"])
        self.assertEqual(transaction.status, "refund_failed")
        self.assertEqual(transaction.refund_status, "failed")
        self.assertEqual(
            transaction.refund_reference,
            "REFUND-DELAYED-001",
        )
        self.assertIsNone(transaction.refunded_at)

    def test_processed_refund_can_follow_failed_event_for_same_refund(self):
        transaction = GuestTransaction.objects.create(
            guest_email="guest@example.com",
            guest_phone="08000000001",
            service_type="airtime",
            provider="mtn",
            amount=Decimal("2000.00"),
            recipient="08000000001",
            reference="GUEST-REFUND-ORDER-001",
            payment_reference="GUEST-REFUND-ORDER-001",
            status="refund_failed",
            refund_reference="REFUND-ORDER-001",
            refund_amount=Decimal("2000.00"),
            refund_status="failed",
        )

        payload = {
            "event": "refund.processed",
            "data": {
                "id": "REFUND-ORDER-001",
                "status": "processed",
                "amount": 200000,
                "transaction": {
                    "reference": transaction.payment_reference,
                },
            },
        }

        body = json.dumps(payload).encode("utf-8")
        signature = hmac.new(
            settings.PAYSTACK_SECRET_KEY.encode("utf-8"),
            body,
            hashlib.sha512,
        ).hexdigest()

        response = APIClient().post(
            "/api/payments/webhook/",
            data=body,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=signature,
        )

        transaction.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(transaction.status, "refunded")
        self.assertEqual(transaction.refund_status, "processed")
        self.assertEqual(
            transaction.refund_reference,
            "REFUND-ORDER-001",
        )
        self.assertIsNotNone(transaction.refunded_at)