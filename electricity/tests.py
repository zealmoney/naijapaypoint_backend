from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from transactions.models import Transaction
from wallets.models import WalletTransaction

from .models import ElectricityTransaction
from .views import ElectricityPurchaseView

from .serializers import (
    ElectricityPurchaseSerializer,
    MeterVerificationSerializer,
)


class ElectricitySerializerSecurityTests(
    SimpleTestCase
):
    def test_supported_providers_are_allowed(self):
        for provider in (
            "ikeja-electric",
            "eko-electric",
            "abuja-electric",
            "kano-electric",
            "ibadan-electric",
            "portharcourt-electric",
        ):
            serializer = MeterVerificationSerializer(
                data={
                    "provider": provider,
                    "meter_number": "1234567890",
                    "meter_type": "prepaid",
                }
            )

            self.assertTrue(
                serializer.is_valid(),
                serializer.errors,
            )

    def test_verification_rejects_arbitrary_provider(
        self,
    ):
        serializer = MeterVerificationSerializer(
            data={
                "provider": "fake-electric",
                "meter_number": "1234567890",
                "meter_type": "prepaid",
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn(
            "provider",
            serializer.errors,
        )

    def test_purchase_rejects_arbitrary_provider(
        self,
    ):
        serializer = ElectricityPurchaseSerializer(
            data={
                "provider": "fake-electric",
                "meter_number": "1234567890",
                "meter_type": "prepaid",
                "customer_name": "Test Customer",
                "amount": "1000.00",
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn(
            "provider",
            serializer.errors,
        )

    def test_purchase_rejects_amount_below_minimum(
        self,
    ):
        serializer = ElectricityPurchaseSerializer(
            data={
                "provider": "ikeja-electric",
                "meter_number": "1234567890",
                "meter_type": "prepaid",
                "customer_name": "Test Customer",
                "amount": "999.99",
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn(
            "amount",
            serializer.errors,
        )

    def test_purchase_allows_minimum_amount(self):
        serializer = ElectricityPurchaseSerializer(
            data={
                "provider": "ikeja-electric",
                "meter_number": "1234567890",
                "meter_type": "prepaid",
                "customer_name": "Test Customer",
                "amount": "1000.00",
            }
        )

        self.assertTrue(
            serializer.is_valid(),
            serializer.errors,
        )

class ElectricityMeterVerificationSecurityTests(
    TestCase
):
    def setUp(self):
        User = get_user_model()

        self.user = User.objects.create_user(
            username="electricity_verify_test",
            email="electricity-verify@example.com",
            password="TestPassword123!",
        )

        self.client = APIClient()
        self.client.force_authenticate(
            user=self.user
        )

    @patch(
        "electricity.views."
        "VTPassElectricityService.verify_meter"
    )
    def test_verification_does_not_expose_provider_response(
        self,
        mock_verify,
    ):
        mock_verify.return_value = {
            "code": "000",
            "response_description":
                "TRANSACTION SUCCESSFUL",
            "requestId":
                "PROVIDER-SECRET-REFERENCE",
            "content": {
                "Customer_Name":
                    "Test Customer",
                "Address":
                    "Private Provider Address",
                "internal_provider_value":
                    "must-not-leak",
            },
            "internal_secret":
                "must-not-leak",
        }

        response = self.client.post(
            "/api/electricity/verify-meter/",
            {
                "provider":
                    "ikeja-electric",
                "meter_number":
                    "1234567890",
                "meter_type":
                    "prepaid",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            response.data,
            {
                "verified": True,
                "customer_name":
                    "Test Customer",
                "meter_number":
                    "1234567890",
                "meter_type":
                    "prepaid",
                "provider":
                    "ikeja-electric",
            },
        )

        response_text = str(
            response.data
        )

        self.assertNotIn(
            "PROVIDER-SECRET-REFERENCE",
            response_text,
        )
        self.assertNotIn(
            "must-not-leak",
            response_text,
        )
        self.assertNotIn(
            "Private Provider Address",
            response_text,
        )

    @patch(
        "electricity.views."
        "VTPassElectricityService.verify_meter"
    )
    def test_verification_provider_exception_is_safe(
        self,
        mock_verify,
    ):
        mock_verify.side_effect = TimeoutError(
            "secret provider timeout detail"
        )

        response = self.client.post(
            "/api/electricity/verify-meter/",
            {
                "provider":
                    "ikeja-electric",
                "meter_number":
                    "1234567890",
                "meter_type":
                    "prepaid",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            502,
        )

        self.assertNotIn(
            "secret provider timeout detail",
            str(response.data),
        )

    @patch(
        "electricity.views."
        "VTPassElectricityService.verify_meter"
    )
    def test_failed_verification_does_not_expose_provider_response(
        self,
        mock_verify,
    ):
        mock_verify.return_value = {
            "code": "016",
            "response_description":
                "INVALID METER",
            "internal_provider_value":
                "failed-secret-must-not-leak",
        }

        response = self.client.post(
            "/api/electricity/verify-meter/",
            {
                "provider":
                    "ikeja-electric",
                "meter_number":
                    "1234567890",
                "meter_type":
                    "prepaid",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            400,
        )

        self.assertNotIn(
            "failed-secret-must-not-leak",
            str(response.data),
        )

class ElectricityPurchaseSecurityTests(
    TestCase
):
    def setUp(self):
        User = get_user_model()

        self.user = User.objects.create_user(
            username="electricity_purchase_test",
            email="electricity-purchase@example.com",
            password="TestPassword123!",
        )

        self.wallet = self.user.wallet
        self.wallet.balance = Decimal("20000.00")
        self.wallet.save(
            update_fields=["balance"]
        )

        self.client = APIClient()
        self.client.force_authenticate(
            user=self.user
        )

        self.payload = {
            "provider": "ikeja-electric",
            "meter_number": "1234567890",
            "meter_type": "prepaid",
            "customer_name": "Test Customer",
            "amount": "4500.00",
        }

    @patch(
        "electricity.views."
        "VTPassElectricityService.purchase_electricity"
    )
    def test_success_response_does_not_expose_provider_response(
        self,
        mock_purchase,
    ):
        mock_purchase.return_value = {
            "code": "000",
            "requestId":
                "PROVIDER-SECRET-REFERENCE",
            "response_description":
                "TRANSACTION SUCCESSFUL",
            "purchased_code":
                "TOKEN : 1234-5678-9012",
            "internal_provider_value":
                "must-not-leak",
        }

        response = self.client.post(
            "/api/electricity/purchase/",
            self.payload,
            format="json",
        )

        self.assertEqual(
            response.status_code,
            201,
        )

        response_text = str(response.data)

        self.assertNotIn(
            "provider_response",
            response_text,
        )
        self.assertNotIn(
            "PROVIDER-SECRET-REFERENCE",
            response_text,
        )
        self.assertNotIn(
            "must-not-leak",
            response_text,
        )

        # Verify the electricity token is preserved
        # while sensitive provider data is excluded.
        electricity_tx = ElectricityTransaction.objects.latest(
            "id"
        )

        main_tx = Transaction.objects.get(
            reference=electricity_tx.reference
        )

        self.assertEqual(
            electricity_tx.token,
            "1234-5678-9012",
        )

        expected_sanitized_response = {
            "code": "000",
            "result": "success",
        }

        self.assertEqual(
            electricity_tx.provider_response,
            expected_sanitized_response,
        )

        self.assertEqual(
            main_tx.metadata["provider_response"],
            expected_sanitized_response,
        )

        self.assertEqual(
            main_tx.provider_reference,
            "PROVIDER-SECRET-REFERENCE",
        )

        self.assertNotIn(
            "must-not-leak",
            str(electricity_tx.provider_response),
        )

        self.assertNotIn(
            "must-not-leak",
            str(main_tx.metadata),
        )

    @patch(
        "electricity.views."
        "VTPassElectricityService.purchase_electricity"
    )
    def test_pending_response_does_not_expose_provider_response(
        self,
        mock_purchase,
    ):
        mock_purchase.return_value = {
            "code": "099",
            "response_description":
                "Transaction is being processed",
            "requestId":
                "PROVIDER-PENDING-SECRET",
            "internal_provider_value":
                "pending-secret-must-not-leak",
        }

        response = self.client.post(
            "/api/electricity/purchase/",
            self.payload,
            format="json",
        )

        self.assertEqual(
            response.status_code,
            202,
        )

        response_text = str(response.data)

        self.assertNotIn(
            "provider_response",
            response_text,
        )
        self.assertNotIn(
            "PROVIDER-PENDING-SECRET",
            response_text,
        )
        self.assertNotIn(
            "pending-secret-must-not-leak",
            response_text,
        )

    @patch(
        "electricity.views."
        "VTPassElectricityService.purchase_electricity"
    )
    def test_manual_review_does_not_expose_provider_response(
        self,
        mock_purchase,
    ):
        mock_purchase.return_value = {
            "code": "099",
            "response_description":
                "Transaction status unknown",
            "requestId":
                "PROVIDER-REVIEW-SECRET",
            "internal_provider_value":
                "review-secret-must-not-leak",
        }

        response = self.client.post(
            "/api/electricity/purchase/",
            self.payload,
            format="json",
        )

        self.assertEqual(
            response.status_code,
            202,
        )

        response_text = str(response.data)

        self.assertNotIn(
            "provider_response",
            response_text,
        )
        self.assertNotIn(
            "PROVIDER-REVIEW-SECRET",
            response_text,
        )
        self.assertNotIn(
            "review-secret-must-not-leak",
            response_text,
        )

    @patch(
        "electricity.views."
        "VTPassElectricityService.purchase_electricity"
    )
    def test_failed_response_does_not_expose_provider_response(
        self,
        mock_purchase,
    ):
        mock_purchase.return_value = {
            "code": "016",
            "response_description":
                "TRANSACTION FAILED",
            "requestId":
                "PROVIDER-FAILED-SECRET",
            "internal_provider_value":
                "failed-secret-must-not-leak",
        }

        response = self.client.post(
            "/api/electricity/purchase/",
            self.payload,
            format="json",
        )

        self.assertEqual(
            response.status_code,
            400,
        )

        response_text = str(response.data)

        self.assertNotIn(
            "provider_response",
            response_text,
        )
        self.assertNotIn(
            "PROVIDER-FAILED-SECRET",
            response_text,
        )
        self.assertNotIn(
            "failed-secret-must-not-leak",
            response_text,
        )

    @patch(
        "electricity.views."
        "VTPassElectricityService.purchase_electricity"
    )
    def test_provider_exception_detail_is_not_exposed(
        self,
        mock_purchase,
    ):
        mock_purchase.side_effect = TimeoutError(
            "secret electricity provider timeout"
        )

        response = self.client.post(
            "/api/electricity/purchase/",
            self.payload,
            format="json",
        )

        self.assertEqual(
            response.status_code,
            202,
        )

        response_text = str(response.data)

        self.assertNotIn(
            "secret electricity provider timeout",
            response_text,
        )
        self.assertNotIn(
            "provider_response",
            response_text,
        )

        electricity_tx = (
            ElectricityTransaction.objects.get(
                reference=response.data[
                    "reference"
                ]
            )
        )

        self.assertEqual(
            electricity_tx.status,
            "pending",
        )

class ElectricityRefundSecurityTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.user = User.objects.create_user(
            username="electricity_refund_test",
            email="electricity-refund@example.com",
            password="TestPassword123!",
        )

        self.wallet = self.user.wallet
        self.wallet.balance = Decimal("5500.00")
        self.wallet.save(
            update_fields=["balance"]
        )

        self.reference = (
            "ELECTRICITY-SECURITY-TEST"
        )
        self.amount = Decimal("4500.00")

        self.electricity_tx = (
            ElectricityTransaction.objects.create(
                user=self.user,
                provider="ikeja-electric",
                meter_number="1234567890",
                meter_type="prepaid",
                customer_name="Test Customer",
                amount=self.amount,
                reference=self.reference,
                status="pending",
            )
        )

        self.main_tx = Transaction.objects.create(
            user=self.user,
            service_type="electricity",
            amount=self.amount,
            reference=self.reference,
            status="pending",
            provider="vtpass",
        )

        WalletTransaction.objects.create(
            wallet=self.wallet,
            transaction_type="debit",
            amount=self.amount,
            reference=self.reference,
            description=(
                "Test original electricity debit"
            ),
        )

    def test_pending_transaction_refunds_once(self):
        (
            electricity_tx,
            main_tx,
            refunded,
        ) = (
            ElectricityPurchaseView
            ._refund_pending_transaction(
                electricity_tx=self.electricity_tx,
                main_tx=self.main_tx,
                amount=self.amount,
                reference=self.reference,
                provider_response={
                    "code": "016",
                    "response_description":
                        "Transaction failed",
                },
                refund_message=(
                    "Refund for failed "
                    "electricity purchase"
                ),
            )
        )

        self.assertTrue(refunded)
        self.assertEqual(
            electricity_tx.status,
            "refunded",
        )
        self.assertEqual(
            main_tx.status,
            "refunded",
        )

        self.wallet.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            Decimal("10000.00"),
        )

        self.assertTrue(
            WalletTransaction.objects.filter(
                wallet=self.wallet,
                reference=(
                    f"REFUND-{self.reference}"
                ),
                transaction_type="credit",
                amount=self.amount,
            ).exists()
        )

    def test_refund_cannot_apply_twice(self):
        first_result = (
            ElectricityPurchaseView
            ._refund_pending_transaction(
                electricity_tx=self.electricity_tx,
                main_tx=self.main_tx,
                amount=self.amount,
                reference=self.reference,
                provider_response={
                    "code": "016",
                },
                refund_message=(
                    "Refund for failed "
                    "electricity purchase"
                ),
            )
        )

        second_result = (
            ElectricityPurchaseView
            ._refund_pending_transaction(
                electricity_tx=self.electricity_tx,
                main_tx=self.main_tx,
                amount=self.amount,
                reference=self.reference,
                provider_response={
                    "code": "016",
                },
                refund_message=(
                    "Refund for failed "
                    "electricity purchase"
                ),
            )
        )

        self.assertTrue(first_result[2])
        self.assertFalse(second_result[2])

        self.wallet.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            Decimal("10000.00"),
        )

        self.assertEqual(
            WalletTransaction.objects.filter(
                reference=(
                    f"REFUND-{self.reference}"
                ),
                transaction_type="credit",
            ).count(),
            1,
        )
    def test_refund_requires_matching_original_debit(self):
        WalletTransaction.objects.filter(
            reference=self.reference,
            transaction_type="debit",
        ).delete()

        (
            electricity_tx,
            main_tx,
            refunded,
        ) = (
            ElectricityPurchaseView
            ._refund_pending_transaction(
                electricity_tx=self.electricity_tx,
                main_tx=self.main_tx,
                amount=self.amount,
                reference=self.reference,
                provider_response={
                    "code": "016",
                },
                refund_message=(
                    "Refund for failed "
                    "electricity purchase"
                ),
            )
        )

        self.assertFalse(refunded)

        electricity_tx.refresh_from_db()
        main_tx.refresh_from_db()
        self.wallet.refresh_from_db()

        self.assertEqual(
            electricity_tx.status,
            "pending",
        )
        self.assertEqual(
            main_tx.status,
            "pending",
        )
        self.assertEqual(
            self.wallet.balance,
            Decimal("5500.00"),
        )

        self.assertFalse(
            WalletTransaction.objects.filter(
                reference=(
                    f"REFUND-{self.reference}"
                ),
                transaction_type="credit",
            ).exists()
        )

    def test_successful_transaction_cannot_be_refunded(self):
        self.electricity_tx.status = "success"
        self.electricity_tx.save(
            update_fields=["status"]
        )

        self.main_tx.status = "success"
        self.main_tx.save(
            update_fields=["status"]
        )

        (
            electricity_tx,
            main_tx,
            refunded,
        ) = (
            ElectricityPurchaseView
            ._refund_pending_transaction(
                electricity_tx=self.electricity_tx,
                main_tx=self.main_tx,
                amount=self.amount,
                reference=self.reference,
                provider_response={
                    "code": "016",
                },
                refund_message=(
                    "Refund for failed "
                    "electricity purchase"
                ),
            )
        )

        self.assertFalse(refunded)

        electricity_tx.refresh_from_db()
        main_tx.refresh_from_db()
        self.wallet.refresh_from_db()

        self.assertEqual(
            electricity_tx.status,
            "success",
        )
        self.assertEqual(
            main_tx.status,
            "success",
        )
        self.assertEqual(
            self.wallet.balance,
            Decimal("5500.00"),
        )

        self.assertFalse(
            WalletTransaction.objects.filter(
                reference=(
                    f"REFUND-{self.reference}"
                ),
                transaction_type="credit",
            ).exists()
        )

    def test_refunded_transaction_cannot_be_marked_success(self):
        (
            self.electricity_tx,
            self.main_tx,
            refunded,
        ) = (
            ElectricityPurchaseView
            ._refund_pending_transaction(
                electricity_tx=self.electricity_tx,
                main_tx=self.main_tx,
                amount=self.amount,
                reference=self.reference,
                provider_response={
                    "code": "016",
                },
                refund_message=(
                    "Refund for failed "
                    "electricity purchase"
                ),
            )
        )

        self.assertTrue(refunded)

        (
            electricity_tx,
            main_tx,
            marked_success,
        ) = (
            ElectricityPurchaseView
            ._mark_pending_transaction_success(
                electricity_tx=self.electricity_tx,
                main_tx=self.main_tx,
            )
        )

        self.assertFalse(marked_success)

        electricity_tx.refresh_from_db()
        main_tx.refresh_from_db()
        self.wallet.refresh_from_db()

        self.assertEqual(
            electricity_tx.status,
            "refunded",
        )
        self.assertEqual(
            main_tx.status,
            "refunded",
        )
        self.assertEqual(
            self.wallet.balance,
            Decimal("10000.00"),
        )

        self.assertEqual(
            WalletTransaction.objects.filter(
                reference=(
                    f"REFUND-{self.reference}"
                ),
                transaction_type="credit",
            ).count(),
            1,
        )

    @patch(
        "electricity.views."
        "VTPassElectricityService."
        "purchase_electricity"
    )
    def test_provider_exception_does_not_refund(
        self,
        mock_purchase,
    ):
        mock_purchase.side_effect = Exception(
            "Simulated provider timeout"
        )

        client = APIClient()
        client.force_authenticate(user=self.user)

        response = client.post(
            "/api/electricity/purchase/",
            {
                "provider": "ikeja-electric",
                "meter_number": "9876543210",
                "meter_type": "prepaid",
                "customer_name": "Test Customer",
                "amount": "1000.00",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            202,
        )

        electricity_tx = (
            ElectricityTransaction.objects.get(
                reference=response.data["reference"]
            )
        )

        main_tx = Transaction.objects.get(
            reference=electricity_tx.reference
        )

        self.assertEqual(
            electricity_tx.status,
            "pending",
        )
        self.assertEqual(
            main_tx.status,
            "pending",
        )

        self.wallet.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            Decimal("4500.00"),
        )

        self.assertFalse(
            WalletTransaction.objects.filter(
                reference=(
                    f"REFUND-"
                    f"{electricity_tx.reference}"
                ),
                transaction_type="credit",
            ).exists()
        )