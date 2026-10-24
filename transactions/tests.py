from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from transactions.models import Transaction
from wallets.models import Wallet, WalletTransaction

from airtime.models import AirtimeTransaction


User = get_user_model()


class TransactionEndpointSecurityTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="transaction_security_user",
            email="transaction-security@example.com",
            password="StrongTestPassword123!",
        )

        self.other_user = User.objects.create_user(
            username="transaction_other_user",
            email="transaction-other@example.com",
            password="StrongTestPassword123!",
        )

        self.transaction = Transaction.objects.create(
            user=self.user,
            service_type="cable",
            amount=Decimal("2500.00"),
            reference="SECURITY-TX-001",
            status="pending",
            provider="vtpass",
            provider_reference="SAFE-PROVIDER-REF",
            description="Cable subscription",
            metadata={
                "phone_number": "08000000001",
                "smartcard_number": "1234567890",
                "provider": "dstv",
                "plan_id": "dstv-test-plan",
                "plan_name": "Test DStv Plan",
                "requires_requery": True,
                "requery_attempts": 2,

                # Internal fields that must never
                # cross the customer API boundary.
                "provider_response": {
                    "code": "099",
                    "requestId": "SECRET-REQUEST-ID",
                    "response_description":
                        "SECRET PROVIDER DESCRIPTION",
                    "internal_provider_value":
                        "must-not-leak",
                },
                "requery_history": [
                    {
                        "attempt": 1,
                        "response": {
                            "internal_provider_value":
                                "history-secret",
                        },
                    }
                ],
                "reconciliation_warning":
                    "internal operations warning",
                "unknown_internal_field":
                    "another-secret",
            },
        )

        self.other_transaction = (
            Transaction.objects.create(
                user=self.other_user,
                service_type="airtime",
                amount=Decimal("1000.00"),
                reference="OTHER-USER-TX-001",
                status="success",
                provider="vtpass",
                metadata={
                    "phone_number":
                        "08000000002",
                    "provider_response": {
                        "internal_provider_value":
                            "other-user-secret",
                    },
                },
            )
        )

    def test_transaction_list_requires_authentication(
        self,
    ):
        response = self.client.get(
            "/api/transactions/"
        )

        self.assertIn(
            response.status_code,
            {
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_403_FORBIDDEN,
            },
        )

    def test_transaction_list_only_returns_own_transactions(
        self,
    ):
        self.client.force_authenticate(
            user=self.user
        )

        response = self.client.get(
            "/api/transactions/"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        references = {
            item["reference"]
            for item in response.data
        }

        self.assertIn(
            self.transaction.reference,
            references,
        )

        self.assertNotIn(
            self.other_transaction.reference,
            references,
        )

    def test_transaction_list_metadata_is_allowlisted(
        self,
    ):
        self.client.force_authenticate(
            user=self.user
        )

        response = self.client.get(
            "/api/transactions/"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        item = next(
            entry
            for entry in response.data
            if entry["reference"]
            == self.transaction.reference
        )

        metadata = item["metadata"]

        self.assertEqual(
            metadata["phone_number"],
            "08000000001",
        )

        self.assertEqual(
            metadata["plan_name"],
            "Test DStv Plan",
        )

        self.assertTrue(
            metadata["requires_requery"]
        )

        self.assertEqual(
            metadata["requery_attempts"],
            2,
        )

        self.assertNotIn(
            "provider_response",
            metadata,
        )

        self.assertNotIn(
            "requery_history",
            metadata,
        )

        self.assertNotIn(
            "reconciliation_warning",
            metadata,
        )

        self.assertNotIn(
            "unknown_internal_field",
            metadata,
        )

        response_text = str(response.data)

        self.assertNotIn(
            "must-not-leak",
            response_text,
        )

        self.assertNotIn(
            "history-secret",
            response_text,
        )

        self.assertNotIn(
            "SECRET PROVIDER DESCRIPTION",
            response_text,
        )

    def test_transaction_detail_cannot_access_other_user(
        self,
    ):
        self.client.force_authenticate(
            user=self.user
        )

        response = self.client.get(
            (
                "/api/transactions/"
                f"{self.other_transaction.reference}/"
            )
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_transaction_detail_metadata_is_allowlisted(
        self,
    ):
        self.client.force_authenticate(
            user=self.user
        )

        response = self.client.get(
            (
                "/api/transactions/"
                f"{self.transaction.reference}/"
            )
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        metadata = response.data["metadata"]

        self.assertEqual(
            metadata["smartcard_number"],
            "1234567890",
        )

        self.assertNotIn(
            "provider_response",
            metadata,
        )

        self.assertNotIn(
            "requery_history",
            metadata,
        )

        self.assertNotIn(
            "unknown_internal_field",
            metadata,
        )

        self.assertNotIn(
            "must-not-leak",
            str(response.data),
        )

    def test_receipt_metadata_is_allowlisted(
        self,
    ):
        self.client.force_authenticate(
            user=self.user
        )

        response = self.client.get(
            (
                "/api/transactions/"
                f"{self.transaction.reference}/"
                "receipt/"
            )
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        metadata = response.data["metadata"]

        self.assertEqual(
            metadata["phone_number"],
            "08000000001",
        )

        self.assertEqual(
            metadata["plan_name"],
            "Test DStv Plan",
        )

        self.assertNotIn(
            "provider_response",
            metadata,
        )

        self.assertNotIn(
            "requery_history",
            metadata,
        )

        self.assertNotIn(
            "reconciliation_warning",
            metadata,
        )

        self.assertNotIn(
            "unknown_internal_field",
            metadata,
        )

        self.assertNotIn(
            "must-not-leak",
            str(response.data),
        )

        self.assertNotIn(
            "history-secret",
            str(response.data),
        )

    def test_receipt_cannot_access_other_user(
        self,
    ):
        self.client.force_authenticate(
            user=self.user
        )

        response = self.client.get(
            (
                "/api/transactions/"
                f"{self.other_transaction.reference}/"
                "receipt/"
            )
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

class ReconcilePendingTransactionsSecurityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="reconciliation_security_user",
            email="reconciliation-security@example.com",
            password="StrongTestPassword123!",
        )

        self.wallet = self.user.wallet
        self.wallet.balance = Decimal("7500.00")
        self.wallet.save(update_fields=["balance"])

        self.reference = "RECON-AIRTIME-001"
        self.amount = Decimal("2500.00")

        self.transaction = Transaction.objects.create(
            user=self.user,
            service_type="airtime",
            amount=self.amount,
            reference=self.reference,
            status="pending",
            provider="vtpass",
            description="Airtime purchase",
            metadata={
                "phone_number": "08000000001",
                "network": "mtn",
                "requires_requery": True,
                "requires_manual_review": False,
                "requery_attempts": 0,
            },
        )

        self.airtime_transaction = (
            AirtimeTransaction.objects.create(
                user=self.user,
                network="mtn",
                phone_number="08000000001",
                amount=self.amount,
                reference=self.reference,
                status="pending",
                provider="vtpass",
            )
        )

        WalletTransaction.objects.create(
            wallet=self.wallet,
            transaction_type="debit",
            amount=self.amount,
            reference=self.reference,
            description="Airtime purchase",
        )

    def run_command(self, **kwargs):
        stdout = StringIO()
        stderr = StringIO()

        kwargs.setdefault("min_age", 0)

        call_command(
            "reconcile_pending_transactions",
            stdout=stdout,
            stderr=stderr,
            **kwargs,
        )

        return stdout.getvalue(), stderr.getvalue()

    @patch(
        "transactions.management.commands."
        "reconcile_pending_transactions."
        "VTPassRecoveryService.requery"
    )
    def test_confirmed_failure_refunds_exactly_once(
        self,
        mock_requery,
    ):
        mock_requery.return_value = {
            "code": "016",
            "requestId": "PROVIDER-FAILED-001",
            "response_description": "TRANSACTION FAILED",
        }

        original_balance = self.wallet.balance

        self.run_command()

        self.wallet.refresh_from_db()
        self.transaction.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            original_balance + self.amount,
        )

        self.assertEqual(
            self.transaction.status,
            "refunded",
        )

        self.airtime_transaction.refresh_from_db()

        self.assertEqual(
            self.airtime_transaction.status,
            "refunded",
        )

        self.assertEqual(
            self.airtime_transaction.provider_response,
            {
                "code": "016",
                "result": "failed",
            },
        )

        self.assertNotIn(
            "requestId",
            self.airtime_transaction.provider_response,
        )

        self.assertNotIn(
            "response_description",
            self.airtime_transaction.provider_response,
        )

        self.assertEqual(
            self.transaction.metadata[
                "provider_response"
            ],
            {
                "code": "016",
                "result": "failed",
            },
        )

        self.assertNotIn(
            "requestId",
            self.transaction.metadata[
                "provider_response"
            ],
        )

        self.assertNotIn(
            "response_description",
            self.transaction.metadata[
                "provider_response"
            ],
        )

        self.assertEqual(
            WalletTransaction.objects.filter(
                wallet=self.wallet,
                transaction_type="credit",
                reference=f"REFUND-{self.reference}",
                amount=self.amount,
            ).count(),
            1,
        )

        # Run reconciliation again. The transaction is no
        # longer pending, so a second refund must not occur.
        self.run_command()

        self.wallet.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            original_balance + self.amount,
        )

        self.assertEqual(
            WalletTransaction.objects.filter(
                reference=f"REFUND-{self.reference}",
            ).count(),
            1,
        )

    @patch(
        "transactions.management.commands."
        "reconcile_pending_transactions."
        "VTPassRecoveryService.requery"
    )
    def test_failure_without_original_debit_does_not_refund(
        self,
        mock_requery,
    ):
        WalletTransaction.objects.filter(
            reference=self.reference,
        ).delete()

        mock_requery.return_value = {
            "code": "016",
            "requestId": "PROVIDER-FAILED-002",
            "response_description": "TRANSACTION FAILED",
        }

        original_balance = self.wallet.balance

        self.run_command()

        self.wallet.refresh_from_db()
        self.transaction.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            original_balance,
        )

        self.assertEqual(
            self.transaction.status,
            "pending",
        )

        metadata = self.transaction.metadata

        self.assertTrue(
            metadata["requires_manual_review"]
        )

        self.assertFalse(
            metadata["requires_requery"]
        )

        self.assertEqual(
            metadata["reconciliation_result"],
            "manual_review",
        )

        self.assertEqual(
            metadata["reconciliation_reason"],
            "original_wallet_debit_not_found",
        )

        self.assertFalse(
            WalletTransaction.objects.filter(
                reference=f"REFUND-{self.reference}",
            ).exists()
        )

    @patch(
        "transactions.management.commands."
        "reconcile_pending_transactions."
        "VTPassRecoveryService.requery"
    )
    def test_failure_with_wrong_debit_amount_does_not_refund(
        self,
        mock_requery,
    ):
        debit = WalletTransaction.objects.get(
            reference=self.reference,
        )

        debit.amount = Decimal("1000.00")
        debit.save(update_fields=["amount"])

        mock_requery.return_value = {
            "code": "016",
            "response_description": "TRANSACTION FAILED",
        }

        original_balance = self.wallet.balance

        self.run_command()

        self.wallet.refresh_from_db()
        self.transaction.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            original_balance,
        )

        self.assertEqual(
            self.transaction.status,
            "pending",
        )

        self.assertTrue(
            self.transaction.metadata[
                "requires_manual_review"
            ]
        )

        self.assertFalse(
            WalletTransaction.objects.filter(
                reference=f"REFUND-{self.reference}",
            ).exists()
        )

    @patch(
        "transactions.management.commands."
        "reconcile_pending_transactions."
        "VTPassRecoveryService.requery"
    )
    def test_pending_provider_result_does_not_refund(
        self,
        mock_requery,
    ):
        mock_requery.return_value = {
            "code": "099",
            "response_description": (
                "TRANSACTION PENDING - "
                "customer@example.com"
            ),
            "customer_phone": "08012345678",
            "token": "PRIVATE-TEST-TOKEN",
        }

        original_balance = self.wallet.balance

        self.run_command()

        self.wallet.refresh_from_db()
        self.transaction.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            original_balance,
        )

        self.assertEqual(
            self.transaction.status,
            "pending",
        )

        self.assertTrue(
            self.transaction.metadata[
                "requires_requery"
            ]
        )

        self.assertEqual(
            self.transaction.metadata[
                "requery_attempts"
            ],
            1,
        )

        metadata = self.transaction.metadata

        expected_snapshot = {
            "code": "099",
            "result": "pending",
        }

        self.assertEqual(
            metadata["provider_response"],
            expected_snapshot,
        )

        self.assertEqual(
            metadata["requery_history"][0]["response"],
            expected_snapshot,
        )

        self.airtime_transaction.refresh_from_db()

        self.assertEqual(
            self.airtime_transaction.status,
            "pending",
        )

        self.assertEqual(
            self.airtime_transaction.provider_response,
            expected_snapshot,
        )

        service_response_text = str(
            self.airtime_transaction.provider_response
        )

        for sensitive_value in (
            "customer@example.com",
            "08012345678",
            "PRIVATE-TEST-TOKEN",
        ):
            self.assertNotIn(
                sensitive_value,
                service_response_text,
            )

        metadata_text = str(metadata)

        for sensitive_value in (
            "customer@example.com",
            "08012345678",
            "PRIVATE-TEST-TOKEN",
        ):
            self.assertNotIn(
                sensitive_value,
                metadata_text,
            )

        self.assertFalse(
            WalletTransaction.objects.filter(
                reference=f"REFUND-{self.reference}",
            ).exists()
        )

    @patch(
        "transactions.management.commands."
        "reconcile_pending_transactions."
        "VTPassRecoveryService.requery"
    )
    def test_manual_review_provider_result_does_not_refund(
        self,
        mock_requery,
    ):
        mock_requery.return_value = {
            "code": "015",
            "response_description": "UNKNOWN PROVIDER STATE",
        }

        original_balance = self.wallet.balance

        self.run_command()

        self.wallet.refresh_from_db()
        self.transaction.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            original_balance,
        )

        self.assertEqual(
            self.transaction.status,
            "pending",
        )

        self.assertTrue(
            self.transaction.metadata[
                "requires_manual_review"
            ]
        )

        self.assertFalse(
            self.transaction.metadata[
                "requires_requery"
            ]
        )

        self.assertEqual(
            self.transaction.metadata[
                "provider_response"
            ],
            {
                "code": "015",
                "result": "manual_review",
            },
        )

        self.assertNotIn(
            "response_description",
            self.transaction.metadata[
                "provider_response"
            ],
        )

        self.assertFalse(
            WalletTransaction.objects.filter(
                reference=f"REFUND-{self.reference}",
            ).exists()
        )

    @patch(
        "transactions.management.commands."
        "reconcile_pending_transactions."
        "VTPassRecoveryService.requery"
    )
    def test_provider_exception_does_not_refund(
        self,
        mock_requery,
    ):
        mock_requery.side_effect = TimeoutError(
            "secret provider timeout detail"
        )

        original_balance = self.wallet.balance

        self.run_command()

        self.wallet.refresh_from_db()
        self.transaction.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            original_balance,
        )

        self.assertEqual(
            self.transaction.status,
            "pending",
        )

        self.assertFalse(
            WalletTransaction.objects.filter(
                reference=f"REFUND-{self.reference}",
            ).exists()
        )

    @patch(
        "transactions.management.commands."
        "reconcile_pending_transactions."
        "VTPassRecoveryService.requery"
    )
    def test_education_success_preserves_pin_privately(
        self,
        mock_requery,
    ):
        from education.models import EducationTransaction

        self.transaction.service_type = "education"
        self.transaction.description = "Education purchase"
        self.transaction.save(
            update_fields=["service_type", "description"]
        )

        education_tx = EducationTransaction.objects.create(
            user=self.user,
            provider="vtpass",
            plan_id="waec-registration",
            plan_name="WAEC Registration",
            amount=self.amount,
            quantity=1,
            phone_number="08000000001",
            reference=self.reference,
            status="pending",
        )

        test_pin = "PRIVATE-WAEC-PIN-123456"

        mock_requery.return_value = {
            "code": "000",
            "requestId": "PRIVATE-EDUCATION-REQUEST",
            "response_description": "TRANSACTION SUCCESSFUL",
            "content": {
                "pin": test_pin,
                "transactions": {
                    "status": "delivered",
                },
                "customer_name": "Private Test Student",
            },
        }

        original_balance = self.wallet.balance

        self.run_command()

        self.wallet.refresh_from_db()
        self.transaction.refresh_from_db()
        education_tx.refresh_from_db()

        expected_snapshot = {
            "code": "000",
            "result": "success",
        }

        self.assertEqual(
            self.transaction.status,
            "success",
        )

        self.assertEqual(
            education_tx.status,
            "success",
        )

        self.assertEqual(
            education_tx.pin,
            test_pin,
        )

        self.assertEqual(
            education_tx.provider_response,
            expected_snapshot,
        )

        self.assertEqual(
            self.transaction.metadata["provider_response"],
            expected_snapshot,
        )

        self.assertEqual(
            self.wallet.balance,
            original_balance,
        )

        self.assertFalse(
            WalletTransaction.objects.filter(
                reference=f"REFUND-{self.reference}",
            ).exists()
        )

        for stored_response in (
            education_tx.provider_response,
            self.transaction.metadata,
        ):
            stored_text = str(stored_response)

            for sensitive_value in (
                test_pin,
                "PRIVATE-EDUCATION-REQUEST",
                "Private Test Student",
            ):
                self.assertNotIn(
                    sensitive_value,
                    stored_text,
                )

    @patch(
        "transactions.management.commands."
        "reconcile_pending_transactions."
        "VTPassRecoveryService.requery"
    )
    def test_electricity_success_preserves_token_privately(
        self,
        mock_requery,
    ):
        from electricity.models import ElectricityTransaction

        self.transaction.service_type = "electricity"
        self.transaction.description = "Electricity purchase"
        self.transaction.save(
            update_fields=["service_type", "description"]
        )

        electricity_tx = ElectricityTransaction.objects.create(
            user=self.user,
            provider="ikeja-electric",
            meter_number="12345678901",
            meter_type="prepaid",
            amount=self.amount,
            reference=self.reference,
            status="pending",
        )

        test_token = "1234-5678-9012-3456"

        mock_requery.return_value = {
            "code": "000",
            "requestId": "PRIVATE-ELECTRICITY-REQUEST",
            "response_description": "TRANSACTION SUCCESSFUL",
            "token": f"Token : {test_token}",
            "content": {
                "transactions": {
                    "status": "delivered",
                },
                "customer_name": "Private Test Customer",
            },
        }

        original_balance = self.wallet.balance

        self.run_command()

        self.wallet.refresh_from_db()
        self.transaction.refresh_from_db()
        electricity_tx.refresh_from_db()

        expected_snapshot = {
            "code": "000",
            "result": "success",
        }

        self.assertEqual(
            self.transaction.status,
            "success",
        )

        self.assertEqual(
            electricity_tx.status,
            "success",
        )

        self.assertEqual(
            electricity_tx.token,
            test_token,
        )

        self.assertEqual(
            electricity_tx.provider_response,
            expected_snapshot,
        )

        self.assertEqual(
            self.transaction.metadata["provider_response"],
            expected_snapshot,
        )

        self.assertEqual(
            self.wallet.balance,
            original_balance,
        )

        self.assertFalse(
            WalletTransaction.objects.filter(
                reference=f"REFUND-{self.reference}",
            ).exists()
        )

        for stored_response in (
            electricity_tx.provider_response,
            self.transaction.metadata,
        ):
            stored_text = str(stored_response)

            for sensitive_value in (
                test_token,
                "PRIVATE-ELECTRICITY-REQUEST",
                "Private Test Customer",
            ):
                self.assertNotIn(
                    sensitive_value,
                    stored_text,
                )

    @patch(
        "transactions.management.commands."
        "reconcile_pending_transactions."
        "VTPassRecoveryService.requery"
    )
    def test_success_does_not_credit_wallet(
        self,
        mock_requery,
    ):
        mock_requery.return_value = {
            "code": "000",
            "requestId": "PROVIDER-SUCCESS-001",
            "response_description": "TRANSACTION SUCCESSFUL",
            "content": {
                "transactions": {
                    "status": "delivered",
                }
            },
        }

        original_balance = self.wallet.balance

        self.run_command()

        self.wallet.refresh_from_db()
        self.transaction.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            original_balance,
        )

        self.assertEqual(
            self.transaction.status,
            "success",
        )

        self.airtime_transaction.refresh_from_db()

        self.assertEqual(
            self.airtime_transaction.status,
            "success",
        )

        self.assertEqual(
            self.airtime_transaction.provider_response,
            {
                "code": "000",
                "result": "success",
            },
        )

        self.assertNotIn(
            "requestId",
            self.airtime_transaction.provider_response,
        )

        self.assertNotIn(
            "response_description",
            self.airtime_transaction.provider_response,
        )

        self.assertEqual(
            self.transaction.metadata[
                "provider_response"
            ],
            {
                "code": "000",
                "result": "success",
            },
        )

        self.assertNotIn(
            "response_description",
            self.transaction.metadata[
                "provider_response"
            ],
        )

        self.assertNotIn(
            "requestId",
            self.transaction.metadata[
                "provider_response"
            ],
        )

        self.assertFalse(
            WalletTransaction.objects.filter(
                reference=f"REFUND-{self.reference}",
            ).exists()
        )

    @patch(
        "transactions.management.commands."
        "reconcile_pending_transactions."
        "VTPassRecoveryService.requery"
    )
    def test_manual_review_transaction_is_skipped(
        self,
        mock_requery,
    ):
        self.transaction.metadata = {
            **self.transaction.metadata,
            "requires_requery": False,
            "requires_manual_review": True,
        }

        self.transaction.save(
            update_fields=["metadata"]
        )

        original_balance = self.wallet.balance

        self.run_command()

        self.wallet.refresh_from_db()
        self.transaction.refresh_from_db()

        mock_requery.assert_not_called()

        self.assertEqual(
            self.wallet.balance,
            original_balance,
        )

        self.assertEqual(
            self.transaction.status,
            "pending",
        )

    @patch(
        "transactions.management.commands."
        "reconcile_pending_transactions."
        "VTPassRecoveryService.requery"
    )
    def test_max_attempts_escalates_without_refund(
        self,
        mock_requery,
    ):
        self.transaction.metadata = {
            **self.transaction.metadata,
            "requery_attempts": 4,
        }

        self.transaction.save(
            update_fields=["metadata"]
        )

        mock_requery.return_value = {
            "code": "099",
            "response_description": "TRANSACTION PENDING",
        }

        original_balance = self.wallet.balance

        self.run_command(max_attempts=5)

        self.wallet.refresh_from_db()
        self.transaction.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            original_balance,
        )

        self.assertEqual(
            self.transaction.status,
            "pending",
        )

        self.assertEqual(
            self.transaction.metadata[
                "requery_attempts"
            ],
            5,
        )

        expected_snapshot = {
            "code": "099",
            "result": "pending",
        }

        metadata = self.transaction.metadata

        self.assertEqual(
            metadata["provider_response"],
            expected_snapshot,
        )

        self.assertEqual(
            metadata["requery_history"][-1]["response"],
            expected_snapshot,
        )

        self.assertNotIn(
            "response_description",
            metadata["provider_response"],
        )

        self.assertNotIn(
            "response_description",
            metadata["requery_history"][-1]["response"],
        )

        self.assertTrue(
            self.transaction.metadata[
                "requires_manual_review"
            ]
        )

        self.assertFalse(
            self.transaction.metadata[
                "requires_requery"
            ]
        )

        self.assertFalse(
            WalletTransaction.objects.filter(
                reference=f"REFUND-{self.reference}",
            ).exists()
        )

    @patch(
        "transactions.management.commands."
        "reconcile_pending_transactions."
        "VTPassRecoveryService.requery"
    )
    def test_dry_run_does_not_change_database_or_wallet(
        self,
        mock_requery,
    ):
        mock_requery.return_value = {
            "code": "099",
            "response_description": "TRANSACTION PENDING",
        }

        original_balance = self.wallet.balance
        original_metadata = dict(
            self.transaction.metadata
        )

        self.run_command(dry_run=True)

        self.wallet.refresh_from_db()
        self.transaction.refresh_from_db()

        mock_requery.assert_called_once_with(
            self.reference
        )

        self.assertEqual(
            self.wallet.balance,
            original_balance,
        )

        self.assertEqual(
            self.transaction.status,
            "pending",
        )

        self.assertEqual(
            self.transaction.metadata,
            original_metadata,
        )

        self.assertFalse(
            WalletTransaction.objects.filter(
                reference=f"REFUND-{self.reference}",
            ).exists()
        )