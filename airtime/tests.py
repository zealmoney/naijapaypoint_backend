from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from transactions.models import Transaction
from wallets.models import WalletTransaction

from .models import AirtimeTransaction
from .views import AirtimePurchaseView


class AirtimeRefundSecurityTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.user = User.objects.create_user(
            username="airtime_refund_test",
            email="airtime-refund@example.com",
            password="TestPassword123!",
        )

        self.wallet = self.user.wallet
        self.wallet.balance = Decimal("4000.00")
        self.wallet.save(
            update_fields=["balance"]
        )
        self.client = APIClient()
        self.client.force_authenticate(
            user=self.user
        )

        self.reference = "AIRTIME-SECURITY-TEST"
        self.amount = Decimal("1000.00")

        self.airtime_tx = (
            AirtimeTransaction.objects.create(
                user=self.user,
                network="mtn",
                phone_number="08000000000",
                amount=self.amount,
                reference=self.reference,
                status="pending",
            )
        )

        self.main_tx = Transaction.objects.create(
            user=self.user,
            service_type="airtime",
            amount=self.amount,
            reference=self.reference,
            status="pending",
            provider="vtpass",
            description="Test airtime purchase",
            metadata={},
        )

        WalletTransaction.objects.create(
            wallet=self.wallet,
            transaction_type="debit",
            amount=self.amount,
            reference=self.reference,
            description="Test airtime debit",
        )

    def test_pending_transaction_refunds_once(self):
        provider_response = {
            "code": "016",
            "response_description":
                "TRANSACTION FAILED",
        }

        (
            airtime_tx,
            main_tx,
            refunded,
        ) = (
            AirtimePurchaseView
            ._refund_pending_transaction(
                airtime_tx=self.airtime_tx,
                main_tx=self.main_tx,
                amount=self.amount,
                reference=self.reference,
                provider_response=(
                    provider_response
                ),
                refund_message=(
                    "Test airtime refund"
                ),
            )
        )

        self.assertTrue(refunded)

        self.wallet.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            Decimal("5000.00"),
        )

        self.assertEqual(
            airtime_tx.status,
            "refunded",
        )
        self.assertEqual(
            main_tx.status,
            "refunded",
        )

        refund_reference = (
            f"REFUND-{self.reference}"
        )

        self.assertEqual(
            WalletTransaction.objects.filter(
                wallet=self.wallet,
                transaction_type="credit",
                reference=refund_reference,
            ).count(),
            1,
        )

    def test_refund_cannot_be_applied_twice(self):
        provider_response = {
            "code": "016",
            "response_description":
                "TRANSACTION FAILED",
        }

        first_result = (
            AirtimePurchaseView
            ._refund_pending_transaction(
                airtime_tx=self.airtime_tx,
                main_tx=self.main_tx,
                amount=self.amount,
                reference=self.reference,
                provider_response=(
                    provider_response
                ),
                refund_message=(
                    "Test airtime refund"
                ),
            )
        )

        self.assertTrue(first_result[2])

        self.wallet.refresh_from_db()
        self.assertEqual(
            self.wallet.balance,
            Decimal("5000.00"),
        )

        second_result = (
            AirtimePurchaseView
            ._refund_pending_transaction(
                airtime_tx=self.airtime_tx,
                main_tx=self.main_tx,
                amount=self.amount,
                reference=self.reference,
                provider_response=(
                    provider_response
                ),
                refund_message=(
                    "Duplicate airtime refund"
                ),
            )
        )

        self.assertFalse(second_result[2])

        self.wallet.refresh_from_db()
        self.assertEqual(
            self.wallet.balance,
            Decimal("5000.00"),
        )

        self.assertEqual(
            WalletTransaction.objects.filter(
                wallet=self.wallet,
                transaction_type="credit",
                reference=(
                    f"REFUND-{self.reference}"
                ),
            ).count(),
            1,
        )

    def test_successful_transaction_cannot_be_refunded(self):
        self.airtime_tx.status = "success"
        self.airtime_tx.save(
            update_fields=["status"]
        )

        self.main_tx.status = "success"
        self.main_tx.save(
            update_fields=["status"]
        )

        (
            airtime_tx,
            main_tx,
            refunded,
        ) = (
            AirtimePurchaseView
            ._refund_pending_transaction(
                airtime_tx=self.airtime_tx,
                main_tx=self.main_tx,
                amount=self.amount,
                reference=self.reference,
                provider_response={
                    "code": "016",
                    "response_description":
                        "TRANSACTION FAILED",
                },
                refund_message=(
                    "Invalid late refund"
                ),
            )
        )

        self.assertFalse(refunded)

        self.wallet.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            Decimal("4000.00"),
        )

        self.assertEqual(
            airtime_tx.status,
            "success",
        )
        self.assertEqual(
            main_tx.status,
            "success",
        )

        self.assertFalse(
            WalletTransaction.objects.filter(
                wallet=self.wallet,
                transaction_type="credit",
                reference=(
                    f"REFUND-{self.reference}"
                ),
            ).exists()
        )

    @patch(
        "airtime.views."
        "VTPassAirtimeService.purchase_airtime"
    )
    def test_provider_exception_does_not_refund(
        self,
        mock_purchase,
    ):
        mock_purchase.side_effect = Exception(
            "Simulated provider timeout"
        )

        response = self.client.post(
            "/api/airtime/purchase/",
            {
                "network": "mtn",
                "phone_number": "08000000001",
                "amount": "1000.00",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            202,
        )

        self.wallet.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            Decimal("3000.00"),
        )

        airtime_tx = (
            AirtimeTransaction.objects
            .exclude(
                reference=self.reference
            )
            .get()
        )

        main_tx = Transaction.objects.get(
            reference=airtime_tx.reference
        )

        self.assertEqual(
            airtime_tx.status,
            "pending",
        )
        self.assertEqual(
            main_tx.status,
            "pending",
        )

        self.assertEqual(
            WalletTransaction.objects.filter(
                wallet=self.wallet,
                transaction_type="credit",
                reference=(
                    f"REFUND-{airtime_tx.reference}"
                ),
            ).count(),
            0,
        )

    def test_refunded_transaction_cannot_be_marked_success(
        self,
    ):
        provider_response = {
            "code": "016",
            "response_description": "Failed",
        }

        (
            self.airtime_tx,
            self.main_tx,
            refunded,
        ) = AirtimePurchaseView._refund_pending_transaction(
            airtime_tx=self.airtime_tx,
            main_tx=self.main_tx,
            reference=self.reference,
            amount=self.amount,
            provider_response=provider_response,
            refund_message=(
                "Airtime purchase failed. "
                "Wallet refunded."
            ),
        )

        self.assertTrue(refunded)

        (
            airtime_tx,
            main_tx,
            marked_success,
        ) = AirtimePurchaseView._mark_pending_transaction_success(
            airtime_tx=self.airtime_tx,
            main_tx=self.main_tx,
        )

        self.assertFalse(marked_success)
        self.assertEqual(
            airtime_tx.status,
            "refunded",
        )
        self.assertEqual(
            main_tx.status,
            "refunded",
        )

        self.wallet.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            Decimal("5000.00"),
        )

    def test_refund_requires_matching_original_debit(
        self,
    ):
        WalletTransaction.objects.filter(
            wallet=self.wallet,
            reference=self.reference,
            transaction_type="debit",
        ).delete()

        provider_response = {
            "code": "016",
            "response_description": "Failed",
        }

        (
            airtime_tx,
            main_tx,
            refunded,
        ) = AirtimePurchaseView._refund_pending_transaction(
            airtime_tx=self.airtime_tx,
            main_tx=self.main_tx,
            reference=self.reference,
            amount=self.amount,
            provider_response=provider_response,
            refund_message=(
                "Airtime purchase failed. "
                "Wallet refunded."
            ),
        )

        self.assertFalse(refunded)

        self.wallet.refresh_from_db()
        airtime_tx.refresh_from_db()
        main_tx.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            Decimal("4000.00"),
        )
        self.assertEqual(
            airtime_tx.status,
            "pending",
        )
        self.assertEqual(
            main_tx.status,
            "pending",
        )

        self.assertFalse(
            WalletTransaction.objects.filter(
                wallet=self.wallet,
                reference=f"REFUND-{self.reference}",
                transaction_type="credit",
            ).exists()
        )

    @patch(
        "airtime.views."
        "VTPassAirtimeService.purchase_airtime"
    )
    def test_success_response_does_not_expose_provider_response(
        self,
        mock_purchase,
    ):
        mock_purchase.return_value = {
            "code": "000",
            "requestId": "PROVIDER-SECRET-REFERENCE",
            "response_description":
                "TRANSACTION SUCCESSFUL",
            "content": {
                "transactions": {
                    "status": "delivered",
                    "internal_provider_value":
                        "must-not-leak",
                },
            },
        }

        response = self.client.post(
            "/api/airtime/purchase/",
            {
                "network": "mtn",
                "phone_number": "08000000001",
                "amount": "500.00",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            201,
        )

        self.assertNotIn(
            "provider_response",
            response.data,
        )

        self.assertNotIn(
            "must-not-leak",
            str(response.data),
        )

        airtime_tx = (
            AirtimeTransaction.objects
            .exclude(reference=self.reference)
            .get()
        )

        self.assertEqual(
            airtime_tx.provider_response,
            {
                "code": "000",
                "result": "success",
            },
        )

        self.assertNotIn(
            "must-not-leak",
            str(airtime_tx.provider_response),
        )

    @patch(
        "airtime.views."
        "VTPassAirtimeService.purchase_airtime"
    )
    def test_failed_response_does_not_expose_provider_response(
        self,
        mock_purchase,
    ):
        mock_purchase.return_value = {
            "code": "016",
            "requestId": "PROVIDER-FAILED-REFERENCE",
            "response_description":
                "TRANSACTION FAILED",
            "internal_provider_value":
                "failed-secret-must-not-leak",
        }

        response = self.client.post(
            "/api/airtime/purchase/",
            {
                "network": "mtn",
                "phone_number": "08000000001",
                "amount": "500.00",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            400,
        )

        self.assertNotIn(
            "provider_response",
            response.data,
        )

        self.assertNotIn(
            "failed-secret-must-not-leak",
            str(response.data),
        )

        airtime_tx = (
            AirtimeTransaction.objects
            .exclude(reference=self.reference)
            .get()
        )

        self.assertEqual(
            airtime_tx.provider_response,
            {
                "code": "016",
                "result": "failed",
            },
        )

        self.assertNotIn(
            "failed-secret-must-not-leak",
            str(airtime_tx.provider_response),
        )