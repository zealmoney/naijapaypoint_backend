from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from .models import GuestTransaction
from rest_framework.test import APIClient


class GuestCheckoutSecurityTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch(
        "guest_checkout.views."
        "PaystackService.initialize_transaction"
    )
    @patch(
        "guest_checkout.views."
        "VTPassDataService.get_data_plans"
    )
    def test_data_initialization_uses_authoritative_price(
        self,
        mock_get_plans,
        mock_paystack,
    ):
        mock_get_plans.return_value = {
            "content": {
                "varations": [
                    {
                        "variation_code": "mtn-test-plan",
                        "name": "MTN Test Plan",
                        "variation_amount": "2000.00",
                    }
                ]
            }
        }

        mock_paystack.return_value = {
            "status": True,
            "data": {
                "authorization_url":
                    "https://checkout.example.test/pay",
                "access_code": "TEST_ACCESS",
                "reference": "GUEST-TEST-REFERENCE",
            },
        }

        response = self.client.post(
            "/api/guest/initialize/",
            {
                "guest_email": "guest@example.com",
                "guest_phone": "08000000001",
                "service_type": "data",
                "provider": "mtn-data",
                "amount": "1.00",
                "recipient": "08000000001",
                "variation_code": "mtn-test-plan",
                "plan_name": "Fake Client Plan Name",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            201,
        )

        mock_paystack.assert_called_once()

        self.assertEqual(
            mock_paystack.call_args.kwargs["amount"],
            Decimal("2000.00"),
        )

        self.assertEqual(
            response.data["amount"],
            "2000.00",
        )

        self.assertEqual(
            response.data["plan_name"],
            "MTN Test Plan",
        )

    @patch(
        "guest_checkout.views."
        "PaystackService.initialize_transaction"
    )
    @patch(
        "guest_checkout.views."
        "VTPassCableService.get_plans"
    )
    def test_cable_initialization_uses_authoritative_price(
        self,
        mock_get_plans,
        mock_paystack,
    ):
        mock_get_plans.return_value = {
            "content": {
                "varations": [
                    {
                        "variation_code": "dstv-test-plan",
                        "name": "DStv Test Plan",
                        "variation_amount": "7500.00",
                    }
                ]
            }
        }

        mock_paystack.return_value = {
            "status": True,
            "data": {
                "authorization_url":
                    "https://checkout.example.test/pay",
                "access_code": "TEST_ACCESS",
                "reference": "GUEST-TEST-REFERENCE",
            },
        }

        response = self.client.post(
            "/api/guest/initialize/",
            {
                "guest_email": "guest@example.com",
                "guest_phone": "08000000001",
                "service_type": "cable",
                "provider": "dstv",
                "amount": "1.00",
                "recipient": "1234567890",
                "variation_code": "dstv-test-plan",
                "plan_name": "Fake Client Plan Name",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            201,
        )

        mock_paystack.assert_called_once()

        self.assertEqual(
            mock_paystack.call_args.kwargs["amount"],
            Decimal("7500.00"),
        )

        self.assertEqual(
            response.data["amount"],
            "7500.00",
        )

        self.assertEqual(
            response.data["plan_name"],
            "DStv Test Plan",
        )

    @patch(
        "guest_checkout.views."
        "PaystackService.initialize_transaction"
    )
    def test_initialization_does_not_expose_paystack_failure_response(
        self,
        mock_paystack,
    ):
        mock_paystack.return_value = {
            "status": False,
            "message": "SENSITIVE PROVIDER MESSAGE",
            "internal_debug": "SECRET PROVIDER DATA",
        }

        response = self.client.post(
            "/api/guest/initialize/",
            {
                "guest_email": "guest@example.com",
                "guest_phone": "08000000001",
                "service_type": "airtime",
                "provider": "mtn",
                "amount": "1000.00",
                "recipient": "08000000001",
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
                "detail": "Unable to initialize guest payment.",
            },
        )

        self.assertNotIn(
            "SENSITIVE PROVIDER MESSAGE",
            str(response.data),
        )
        self.assertNotIn(
            "SECRET PROVIDER DATA",
            str(response.data),
        )

        self.assertFalse(
            GuestTransaction.objects.exists()
        )

    @patch(
        "guest_checkout.views."
        "PaystackService.initialize_transaction"
    )
    def test_initialization_does_not_expose_paystack_failure_response(
        self,
        mock_paystack,
    ):
        mock_paystack.return_value = {
            "status": False,
            "message": "SENSITIVE PROVIDER MESSAGE",
            "internal_debug": "SECRET PROVIDER DATA",
        }

        response = self.client.post(
            "/api/guest/initialize/",
            {
                "guest_email": "guest@example.com",
                "guest_phone": "08000000001",
                "service_type": "airtime",
                "provider": "mtn",
                "amount": "1000.00",
                "recipient": "08000000001",
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
                "detail": "Unable to initialize guest payment.",
            },
        )

        self.assertNotIn(
            "SENSITIVE PROVIDER MESSAGE",
            str(response.data),
        )
        self.assertNotIn(
            "SECRET PROVIDER DATA",
            str(response.data),
        )

        self.assertFalse(
            GuestTransaction.objects.exists()
        )

    @patch(
        "guest_checkout.views."
        "PaystackService.initialize_transaction"
    )
    def test_electricity_below_minimum_is_rejected(
        self,
        mock_paystack,
    ):
        response = self.client.post(
            "/api/guest/initialize/",
            {
                "guest_email": "guest@example.com",
                "guest_phone": "08000000001",
                "service_type": "electricity",
                "provider": "ikeja-electric",
                "amount": "999.99",
                "recipient": "12345678901",
                "variation_code": "prepaid",
                "customer_name": "Test Customer",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            400,
        )

        self.assertIn(
            "amount",
            response.data,
        )

        mock_paystack.assert_not_called()

    @patch(
        "guest_checkout.views."
        "PaystackService.initialize_transaction"
    )
    def test_invalid_provider_for_service_is_rejected(
        self,
        mock_paystack,
    ):
        response = self.client.post(
            "/api/guest/initialize/",
            {
                "guest_email": "guest@example.com",
                "guest_phone": "08000000001",
                "service_type": "airtime",
                "provider": "ikeja-electric",
                "amount": "1000.00",
                "recipient": "08000000001",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            400,
        )

        self.assertIn(
            "provider",
            response.data,
        )

        mock_paystack.assert_not_called()

    @patch(
        "guest_checkout.views."
        "PaystackService.initialize_transaction"
    )
    def test_invalid_electricity_meter_type_is_rejected(
        self,
        mock_paystack,
    ):
        response = self.client.post(
            "/api/guest/initialize/",
            {
                "guest_email": "guest@example.com",
                "guest_phone": "08000000001",
                "service_type": "electricity",
                "provider": "ikeja-electric",
                "amount": "1000.00",
                "recipient": "12345678901",
                "variation_code": "invalid-meter-type",
                "customer_name": "Test Customer",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            400,
        )

        self.assertIn(
            "variation_code",
            response.data,
        )

        mock_paystack.assert_not_called()

    @patch(
        "guest_checkout.views."
        "GuestPurchaseService.execute"
    )
    @patch(
        "guest_checkout.views."
        "PaystackService.verify_transaction"
    )
    def test_verify_rejects_non_ngn_currency(
        self,
        mock_verify,
        mock_purchase,
    ):
        transaction = GuestTransaction.objects.create(
            guest_email="guest@example.com",
            guest_phone="08000000001",
            service_type="airtime",
            provider="mtn",
            amount=Decimal("1000.00"),
            recipient="08000000001",
            reference="GUEST-CURRENCY-TEST",
            payment_reference="GUEST-CURRENCY-TEST",
            authorization_url="https://example.test/pay",
            status="pending",
            receipt_access_token="secure-test-token",
        )

        mock_verify.return_value = {
            "status": True,
            "data": {
                "status": "success",
                "reference":
                    transaction.payment_reference,
                "amount": 100000,
                "currency": "USD",
            },
        }

        response = self.client.post(
            "/api/guest/verify/",
            {
                "reference": transaction.reference,
            },
            format="json",
            HTTP_X_GUEST_RECEIPT_TOKEN=(
                transaction.receipt_access_token
            ),
        )

        self.assertEqual(
            response.status_code,
            400,
        )

        transaction.refresh_from_db()

        self.assertEqual(
            transaction.status,
            "pending",
        )

        mock_purchase.assert_not_called()

    @patch(
        "guest_checkout.views."
        "GuestPurchaseService.execute"
    )
    @patch(
        "guest_checkout.views."
        "PaystackService.verify_transaction"
    )
    def test_verify_rejects_malformed_paystack_amount(
        self,
        mock_verify,
        mock_purchase,
    ):
        transaction = GuestTransaction.objects.create(
            guest_email="guest@example.com",
            guest_phone="08000000001",
            service_type="airtime",
            provider="mtn",
            amount=Decimal("1000.00"),
            recipient="08000000001",
            reference="GUEST-AMOUNT-TEST",
            payment_reference="GUEST-AMOUNT-TEST",
            authorization_url="https://example.test/pay",
            status="pending",
            receipt_access_token="secure-test-token",
        )

        mock_verify.return_value = {
            "status": True,
            "data": {
                "status": "success",
                "reference":
                    transaction.payment_reference,
                "amount": "not-a-number",
                "currency": "NGN",
            },
        }

        response = self.client.post(
            "/api/guest/verify/",
            {
                "reference": transaction.reference,
            },
            format="json",
            HTTP_X_GUEST_RECEIPT_TOKEN=(
                transaction.receipt_access_token
            ),
        )

        self.assertEqual(
            response.status_code,
            400,
        )

        transaction.refresh_from_db()

        self.assertEqual(
            transaction.status,
            "pending",
        )

        mock_purchase.assert_not_called()

    @patch(
        "guest_checkout.views."
        "GuestPurchaseService.execute"
    )
    @patch(
        "guest_checkout.views."
        "PaystackService.verify_transaction"
    )
    def test_provider_exception_after_payment_stays_pending(
        self,
        mock_verify,
        mock_purchase,
    ):
        transaction = GuestTransaction.objects.create(
            guest_email="guest@example.com",
            guest_phone="08000000001",
            service_type="airtime",
            provider="mtn",
            amount=Decimal("1000.00"),
            recipient="08000000001",
            reference="GUEST-PROVIDER-EXCEPTION",
            payment_reference="GUEST-PROVIDER-EXCEPTION",
            authorization_url="https://example.test/pay",
            status="pending",
            receipt_access_token="secure-test-token",
        )

        mock_verify.return_value = {
            "status": True,
            "data": {
                "status": "success",
                "reference":
                    transaction.payment_reference,
                "amount": 100000,
                "currency": "NGN",
            },
        }

        mock_purchase.side_effect = TimeoutError(
            "provider timeout"
        )

        response = self.client.post(
            "/api/guest/verify/",
            {
                "reference": transaction.reference,
            },
            format="json",
            HTTP_X_GUEST_RECEIPT_TOKEN=(
                transaction.receipt_access_token
            ),
        )

        self.assertEqual(
            response.status_code,
            502,
        )

        transaction.refresh_from_db()

        self.assertEqual(
            transaction.status,
            "pending",
        )

    @patch(
        "guest_checkout.views."
        "GuestPurchaseService.execute"
    )
    @patch(
        "guest_checkout.views."
        "PaystackService.verify_transaction"
    )
    def test_ambiguous_provider_response_stays_pending(
        self,
        mock_verify,
        mock_purchase,
    ):
        transaction = GuestTransaction.objects.create(
            guest_email="guest@example.com",
            guest_phone="08000000001",
            service_type="airtime",
            provider="mtn",
            amount=Decimal("1000.00"),
            recipient="08000000001",
            reference="GUEST-AMBIGUOUS-PROVIDER",
            payment_reference="GUEST-AMBIGUOUS-PROVIDER",
            authorization_url="https://example.test/pay",
            status="pending",
            receipt_access_token="secure-test-token",
        )

        mock_verify.return_value = {
            "status": True,
            "data": {
                "status": "success",
                "reference":
                    transaction.payment_reference,
                "amount": 100000,
                "currency": "NGN",
            },
        }

        mock_purchase.return_value = {
            "code": "099",
            "response_description":
                "Transaction is being processed",
            "customer_email": "private@example.com",
            "customer_phone": "08012345678",
            "secret_provider_data": "sensitive-test-value",
        }

        response = self.client.post(
            "/api/guest/verify/",
            {
                "reference": transaction.reference,
            },
            format="json",
            HTTP_X_GUEST_RECEIPT_TOKEN=(
                transaction.receipt_access_token
            ),
        )

        self.assertEqual(
            response.status_code,
            202,
        )

        transaction.refresh_from_db()

        self.assertEqual(
            transaction.status,
            "pending",
        )

        self.assertEqual(
            transaction.provider_response,
            {
                "code": "099",
                "result": "pending",
            },
        )

    @patch(
        "guest_checkout.views."
        "GuestPurchaseService.execute"
    )
    @patch(
        "guest_checkout.views."
        "PaystackService.verify_transaction"
    )
    def test_electricity_token_survives_provider_sanitization(
        self,
        mock_verify,
        mock_purchase,
    ):
        transaction = GuestTransaction.objects.create(
            guest_email="guest@example.com",
            guest_phone="08000000001",
            service_type="electricity",
            provider="ikeja-electric",
            amount=Decimal("2000.00"),
            recipient="1234567890123",
            reference="GUEST-ELECTRICITY-TOKEN-TEST",
            payment_reference="GUEST-ELECTRICITY-TOKEN-TEST",
            authorization_url="https://example.test/pay",
            status="pending",
            receipt_access_token="secure-test-token",
        )

        mock_verify.return_value = {
            "status": True,
            "data": {
                "status": "success",
                "reference": transaction.payment_reference,
                "amount": 200000,
                "currency": "NGN",
            },
        }

        mock_purchase.return_value = {
            "code": "000",
            "requestId": "VTPASS-ELECTRICITY-123",
            "content": {
                "transactions": {
                    "status": "delivered",
                },
                "token": "1234-5678-9012-3456",
            },
            "customer_email": "private@example.com",
            "secret_provider_data": "sensitive-test-value",
        }

        response = self.client.post(
            "/api/guest/verify/",
            {
                "reference": transaction.reference,
            },
            format="json",
            HTTP_X_GUEST_RECEIPT_TOKEN=(
                transaction.receipt_access_token
            ),
        )

        self.assertEqual(response.status_code, 200)

        transaction.refresh_from_db()

        self.assertEqual(transaction.status, "success")

        self.assertEqual(
            transaction.token,
            "1234-5678-9012-3456",
        )

        self.assertEqual(
            transaction.provider_reference,
            "VTPASS-ELECTRICITY-123",
        )

        self.assertEqual(
            transaction.provider_response,
            {
                "code": "000",
                "result": "success",
            },
        )

    @patch(
        "guest_checkout.views."
        "GuestPurchaseService.execute"
    )
    @patch(
        "guest_checkout.views."
        "PaystackService.verify_transaction"
    )
    def test_provider_value_error_after_payment_stays_pending(
        self,
        mock_verify,
        mock_purchase,
    ):
        transaction = GuestTransaction.objects.create(
            guest_email="guest@example.com",
            guest_phone="08000000001",
            service_type="airtime",
            provider="mtn",
            amount=Decimal("1000.00"),
            recipient="08000000001",
            reference="GUEST-PROVIDER-VALUE-ERROR",
            payment_reference="GUEST-PROVIDER-VALUE-ERROR",
            authorization_url="https://example.test/pay",
            status="pending",
            receipt_access_token="secure-test-token",
        )

        mock_verify.return_value = {
            "status": True,
            "data": {
                "status": "success",
                "reference":
                    transaction.payment_reference,
                "amount": 100000,
                "currency": "NGN",
            },
        }

        mock_purchase.side_effect = ValueError(
            "unexpected provider parsing error"
        )

        response = self.client.post(
            "/api/guest/verify/",
            {
                "reference": transaction.reference,
            },
            format="json",
            HTTP_X_GUEST_RECEIPT_TOKEN=(
                transaction.receipt_access_token
            ),
        )

        self.assertEqual(
            response.status_code,
            502,
        )

        transaction.refresh_from_db()

        self.assertEqual(
            transaction.status,
            "pending",
        )
        self.assertEqual(
            transaction.provider_response,
            {
                "result": "provider_outcome_unknown",
            },
        )
        self.assertNotIn(
            "unexpected provider parsing error",
            str(response.data),
        )

    def test_public_guest_serializer_excludes_internal_fields(self):
        transaction = GuestTransaction.objects.create(
            guest_email="guest@example.com",
            guest_phone="08000000001",
            service_type="electricity",
            provider="ikeja-electric",
            amount=Decimal("1000.00"),
            recipient="12345678901",
            variation_code="prepaid",
            customer_name="Test Customer",
            reference="GUEST-SERIALIZER-SECURITY",
            receipt_access_token="TEST-RECEIPT-ACCESS-TOKEN",
            payment_reference="GUEST-SERIALIZER-SECURITY",
            authorization_url="https://example.test/pay",
            status="success",
            provider_reference="VT-TEST-REFERENCE",
            token="TEST-ELECTRICITY-TOKEN",
            metadata={
                "internal_secret": "DO NOT EXPOSE",
            },
            provider_response={
                "internal_provider_data": "DO NOT EXPOSE",
            },
            refund_reference="REFUND-INTERNAL",
            refund_amount=Decimal("1000.00"),
            refund_status="processed",
            refund_response={
                "refund_secret": "DO NOT EXPOSE",
            },
        )

        response = self.client.get(
            f"/api/guest/receipt/{transaction.reference}/",
            HTTP_X_GUEST_RECEIPT_TOKEN=(
                transaction.receipt_access_token
            ),
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        for internal_field in (
            "receipt_access_token",
            "metadata",
            "provider_response",
            "refund_reference",
            "refund_amount",
            "refund_status",
            "refund_response",
            "refunded_at",
        ):
            self.assertNotIn(
                internal_field,
                response.data,
            )

        self.assertEqual(
            response.data["provider_reference"],
            "VT-TEST-REFERENCE",
        )
        self.assertEqual(
            response.data["token"],
            "TEST-ELECTRICITY-TOKEN",
        )

    def test_guest_receipt_requires_access_token(self):
        transaction = GuestTransaction.objects.create(
            guest_email="guest@example.com",
            guest_phone="08000000001",
            service_type="airtime",
            provider="mtn",
            amount=Decimal("1000.00"),
            recipient="08000000001",
            reference="GUEST-RECEIPT-NO-TOKEN",
            payment_reference="GUEST-RECEIPT-NO-TOKEN",
            receipt_access_token="VALID-RECEIPT-TOKEN",
            status="success",
        )

        response = self.client.get(
            f"/api/guest/receipt/{transaction.reference}/"
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_guest_receipt_rejects_invalid_access_token(self):
        transaction = GuestTransaction.objects.create(
            guest_email="guest@example.com",
            guest_phone="08000000001",
            service_type="airtime",
            provider="mtn",
            amount=Decimal("1000.00"),
            recipient="08000000001",
            reference="GUEST-RECEIPT-WRONG-TOKEN",
            payment_reference="GUEST-RECEIPT-WRONG-TOKEN",
            receipt_access_token="VALID-RECEIPT-TOKEN",
            status="success",
        )

        response = self.client.get(
            f"/api/guest/receipt/{transaction.reference}/",
            HTTP_X_GUEST_RECEIPT_TOKEN="WRONG-RECEIPT-TOKEN",
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    @patch(
        "guest_checkout.views.PaystackService.verify_transaction"
    )
    @patch(
        "guest_checkout.views.GuestPurchaseService.execute"
    )
    def test_guest_verify_requires_access_token(
        self,
        mock_purchase,
        mock_verify,
    ):
        transaction = GuestTransaction.objects.create(
            guest_email="guest@example.com",
            guest_phone="08000000001",
            service_type="airtime",
            provider="mtn",
            amount=Decimal("1000.00"),
            recipient="08000000001",
            reference="GUEST-VERIFY-NO-TOKEN",
            payment_reference="GUEST-VERIFY-NO-TOKEN",
        )

        response = self.client.post(
            "/api/guest/verify/",
            {
                "reference": transaction.reference,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            403,
        )

        transaction.refresh_from_db()

        self.assertEqual(
            transaction.status,
            "pending",
        )

        mock_verify.assert_not_called()
        mock_purchase.assert_not_called()

    @patch(
        "guest_checkout.views.PaystackService.verify_transaction"
    )
    @patch(
        "guest_checkout.views.GuestPurchaseService.execute"
    )
    def test_guest_verify_rejects_invalid_access_token(
        self,
        mock_purchase,
        mock_verify,
    ):
        transaction = GuestTransaction.objects.create(
            guest_email="guest@example.com",
            guest_phone="08000000001",
            service_type="airtime",
            provider="mtn",
            amount=Decimal("1000.00"),
            recipient="08000000001",
            reference="GUEST-VERIFY-BAD-TOKEN",
            payment_reference="GUEST-VERIFY-BAD-TOKEN",
        )

        response = self.client.post(
            "/api/guest/verify/",
            {
                "reference": transaction.reference,
            },
            format="json",
            HTTP_X_GUEST_RECEIPT_TOKEN="wrong-token",
        )

        self.assertEqual(
            response.status_code,
            403,
        )

        transaction.refresh_from_db()

        self.assertEqual(
            transaction.status,
            "pending",
        )

        mock_verify.assert_not_called()
        mock_purchase.assert_not_called()