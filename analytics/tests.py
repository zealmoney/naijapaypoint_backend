from decimal import Decimal
from unittest.mock import patch

from django.utils import timezone
from guest_checkout.models import GuestTransaction

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import User
from transactions.models import Transaction
from wallets.models import Wallet, WalletTransaction


User = get_user_model()


class AdminTransactionRefundSecurityTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="refund_admin",
            email="refund-admin@example.com",
            password="StrongTestPassword123!",
            is_staff=True,
        )

        self.user = User.objects.create_user(
            username="refund_customer",
            email="refund-customer@example.com",
            password="StrongTestPassword123!",
        )

        self.wallet = self.user.wallet
        self.wallet.balance = Decimal("3500.00")
        self.wallet.save(update_fields=["balance"])

        self.tx = Transaction.objects.create(
            user=self.user,
            service_type="airtime",
            amount=Decimal("1500.00"),
            reference="ADMIN-REFUND-TEST-001",
            status="failed",
            provider="vtpass",
            metadata={},
        )

        WalletTransaction.objects.create(
            wallet=self.wallet,
            transaction_type="debit",
            amount=Decimal("1500.00"),
            reference=self.tx.reference,
            description="Original service debit",
        )

        self.url = reverse(
            "admin-transaction-refund",
            kwargs={
                "reference": self.tx.reference,
            },
        )

    def authenticate_admin(self):
        self.client.force_authenticate(
            user=self.admin
        )

    def test_refund_requires_admin_authentication(self):
        response = self.client.post(
            self.url,
            {
                "note": "Security test refund",
            },
            format="json",
        )

        self.assertIn(
            response.status_code,
            [
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_403_FORBIDDEN,
            ],
        )

        self.wallet.refresh_from_db()
        self.tx.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            Decimal("3500.00"),
        )
        self.assertEqual(
            self.tx.status,
            "failed",
        )

        self.assertFalse(
            WalletTransaction.objects.filter(
                reference=(
                    "ADMIN-REFUND-"
                    f"{self.tx.reference}"
                ),
            ).exists()
        )

    def test_non_admin_cannot_refund_transaction(self):
        self.client.force_authenticate(
            user=self.user
        )

        response = self.client.post(
            self.url,
            {
                "note": "Unauthorized refund",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        self.wallet.refresh_from_db()
        self.tx.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            Decimal("3500.00"),
        )
        self.assertEqual(
            self.tx.status,
            "failed",
        )

    def test_refund_credits_exact_original_amount_once(self):
        self.authenticate_admin()

        response = self.client.post(
            self.url,
            {
                "note": "Confirmed failed purchase",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.wallet.refresh_from_db()
        self.tx.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            Decimal("5000.00"),
        )
        self.assertEqual(
            self.tx.status,
            "refunded",
        )

        refund_reference = (
            f"ADMIN-REFUND-{self.tx.reference}"
        )

        refund_records = (
            WalletTransaction.objects.filter(
                wallet=self.wallet,
                transaction_type="credit",
                reference=refund_reference,
            )
        )

        self.assertEqual(
            refund_records.count(),
            1,
        )

        refund_record = refund_records.get()

        self.assertEqual(
            refund_record.amount,
            Decimal("1500.00"),
        )

    def test_duplicate_refund_does_not_credit_twice(self):
        self.authenticate_admin()

        first_response = self.client.post(
            self.url,
            {
                "note": "First refund",
            },
            format="json",
        )

        second_response = self.client.post(
            self.url,
            {
                "note": "Duplicate refund",
            },
            format="json",
        )

        self.assertEqual(
            first_response.status_code,
            status.HTTP_200_OK,
        )

        self.assertEqual(
            second_response.status_code,
            status.HTTP_409_CONFLICT,
        )

        self.wallet.refresh_from_db()
        self.tx.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            Decimal("5000.00"),
        )

        self.assertEqual(
            self.tx.status,
            "refunded",
        )

        self.assertEqual(
            WalletTransaction.objects.filter(
                wallet=self.wallet,
                transaction_type="credit",
                reference=(
                    "ADMIN-REFUND-"
                    f"{self.tx.reference}"
                ),
            ).count(),
            1,
        )

    def test_refund_without_matching_original_debit_is_rejected(
        self,
    ):
        self.authenticate_admin()

        WalletTransaction.objects.filter(
            wallet=self.wallet,
            transaction_type="debit",
            reference=self.tx.reference,
        ).delete()

        response = self.client.post(
            self.url,
            {
                "note": "Attempt refund without debit",
            },
            format="json",
        )

        self.assertIn(
            response.status_code,
            [
                status.HTTP_400_BAD_REQUEST,
                status.HTTP_409_CONFLICT,
            ],
        )

        self.wallet.refresh_from_db()
        self.tx.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            Decimal("3500.00"),
        )

        self.assertNotEqual(
            self.tx.status,
            "refunded",
        )

        self.assertFalse(
            WalletTransaction.objects.filter(
                wallet=self.wallet,
                transaction_type="credit",
                reference=(
                    "ADMIN-REFUND-"
                    f"{self.tx.reference}"
                ),
            ).exists()
        )

    def test_refund_with_wrong_original_debit_amount_is_rejected(
        self,
    ):
        self.authenticate_admin()

        original_debit = (
            WalletTransaction.objects.get(
                wallet=self.wallet,
                transaction_type="debit",
                reference=self.tx.reference,
            )
        )

        original_debit.amount = Decimal("500.00")
        original_debit.save(
            update_fields=["amount"]
        )

        response = self.client.post(
            self.url,
            {
                "note": "Attempt mismatched refund",
            },
            format="json",
        )

        self.assertIn(
            response.status_code,
            [
                status.HTTP_400_BAD_REQUEST,
                status.HTTP_409_CONFLICT,
            ],
        )

        self.wallet.refresh_from_db()
        self.tx.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            Decimal("3500.00"),
        )

        self.assertNotEqual(
            self.tx.status,
            "refunded",
        )

        self.assertFalse(
            WalletTransaction.objects.filter(
                wallet=self.wallet,
                transaction_type="credit",
                reference=(
                    "ADMIN-REFUND-"
                    f"{self.tx.reference}"
                ),
            ).exists()
        )

    def test_successful_transaction_cannot_be_refunded(
        self,
    ):
        self.authenticate_admin()

        self.tx.status = "success"
        self.tx.save(
            update_fields=["status"]
        )

        response = self.client.post(
            self.url,
            {
                "note": "Attempt refund of success",
            },
            format="json",
        )

        self.assertIn(
            response.status_code,
            [
                status.HTTP_400_BAD_REQUEST,
                status.HTTP_409_CONFLICT,
            ],
        )

        self.wallet.refresh_from_db()
        self.tx.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            Decimal("3500.00"),
        )

        self.assertEqual(
            self.tx.status,
            "success",
        )

        self.assertFalse(
            WalletTransaction.objects.filter(
                wallet=self.wallet,
                transaction_type="credit",
                reference=(
                    "ADMIN-REFUND-"
                    f"{self.tx.reference}"
                ),
            ).exists()
        )

class AdminTransactionStatusSecurityTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="status_admin",
            email="status-admin@example.com",
            password="StrongTestPassword123!",
            is_staff=True,
        )

        self.user = User.objects.create_user(
            username="status_customer",
            email="status-customer@example.com",
            password="StrongTestPassword123!",
        )

        self.tx = Transaction.objects.create(
            user=self.user,
            service_type="airtime",
            amount=Decimal("1500.00"),
            reference="ADMIN-STATUS-TEST-001",
            status="pending",
            provider="vtpass",
            metadata={},
        )

        self.url = reverse(
            "admin-transaction-update-status",
            kwargs={
                "reference": self.tx.reference,
            },
        )

    def test_status_update_requires_admin_authentication(self):
        response = self.client.post(
            self.url,
            {
                "status": "failed",
                "note": "Test update",
            },
            format="json",
        )

        self.assertIn(
            response.status_code,
            [
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_403_FORBIDDEN,
            ],
        )

        self.tx.refresh_from_db()
        self.assertEqual(
            self.tx.status,
            "pending",
        )

    def test_non_admin_cannot_update_status(self):
        self.client.force_authenticate(
            user=self.user
        )

        response = self.client.post(
            self.url,
            {
                "status": "failed",
                "note": "Unauthorized update",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        self.tx.refresh_from_db()
        self.assertEqual(
            self.tx.status,
            "pending",
        )

    def test_admin_cannot_manually_mark_refunded(self):
        self.client.force_authenticate(
            user=self.admin
        )

        response = self.client.post(
            self.url,
            {
                "status": "refunded",
                "note": "Manual refund",
            },
            format="json",
        )

        self.assertIn(
            response.status_code,
            [
                status.HTTP_400_BAD_REQUEST,
                status.HTTP_409_CONFLICT,
            ],
        )

        self.tx.refresh_from_db()
        self.assertEqual(
            self.tx.status,
            "pending",
        )

    def test_admin_cannot_manually_mark_success(self):
        self.client.force_authenticate(
            user=self.admin
        )

        response = self.client.post(
            self.url,
            {
                "status": "success",
                "note": "Manual success",
            },
            format="json",
        )

        self.assertIn(
            response.status_code,
            [
                status.HTTP_400_BAD_REQUEST,
                status.HTTP_409_CONFLICT,
            ],
        )

        self.tx.refresh_from_db()
        self.assertEqual(
            self.tx.status,
            "pending",
        )

    def test_admin_can_mark_pending_transaction_failed(self):
        self.client.force_authenticate(
            user=self.admin
        )

        response = self.client.post(
            self.url,
            {
                "status": "failed",
                "note": (
                    "Provider confirmed failure "
                    "during manual review."
                ),
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.tx.refresh_from_db()

        self.assertEqual(
            self.tx.status,
            "failed",
        )

        self.assertTrue(
            self.tx.metadata.get(
                "admin_status_update"
            )
        )

    def test_successful_transaction_cannot_be_changed(self):
        self.tx.status = "success"
        self.tx.save(
            update_fields=["status"]
        )

        self.client.force_authenticate(
            user=self.admin
        )

        response = self.client.post(
            self.url,
            {
                "status": "failed",
                "note": "Attempted reversal",
            },
            format="json",
        )

        self.assertIn(
            response.status_code,
            [
                status.HTTP_400_BAD_REQUEST,
                status.HTTP_409_CONFLICT,
            ],
        )

        self.tx.refresh_from_db()
        self.assertEqual(
            self.tx.status,
            "success",
        )

    def test_refunded_transaction_cannot_be_changed(self):
        self.tx.status = "refunded"
        self.tx.save(
            update_fields=["status"]
        )

        self.client.force_authenticate(
            user=self.admin
        )

        response = self.client.post(
            self.url,
            {
                "status": "failed",
                "note": "Attempted reversal",
            },
            format="json",
        )

        self.assertIn(
            response.status_code,
            [
                status.HTTP_400_BAD_REQUEST,
                status.HTTP_409_CONFLICT,
            ],
        )

        self.tx.refresh_from_db()
        self.assertEqual(
            self.tx.status,
            "refunded",
        )

    def test_admin_can_mark_processing_transaction_failed(self):
        self.tx.status = "processing"
        self.tx.save(
            update_fields=["status"]
        )

        self.client.force_authenticate(
            user=self.admin
        )

        response = self.client.post(
            self.url,
            {
                "status": "failed",
                "note": "Provider confirmed failure.",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.tx.refresh_from_db()

        self.assertEqual(
            self.tx.status,
            "failed",
        )

        self.assertEqual(
            self.tx.metadata.get(
                "previous_status"
            ),
            "processing",
        )

        self.assertEqual(
            self.tx.metadata.get(
                "new_status"
            ),
            "failed",
        )


    def test_failed_transaction_cannot_be_moved_back_to_pending(self):
        self.tx.status = "failed"
        self.tx.save(
            update_fields=["status"]
        )

        self.client.force_authenticate(
            user=self.admin
        )

        response = self.client.post(
            self.url,
            {
                "status": "pending",
                "note": (
                    "Attempt to reopen "
                    "transaction."
                ),
            },
            format="json",
        )

        self.assertIn(
            response.status_code,
            [
                status.HTTP_400_BAD_REQUEST,
                status.HTTP_409_CONFLICT,
            ],
        )

        self.tx.refresh_from_db()

        self.assertEqual(
            self.tx.status,
            "failed",
        )

class AdminProviderReferenceSecurityTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="provider_ref_admin",
            email="provider-ref-admin@example.com",
            password="StrongTestPassword123!",
            is_staff=True,
        )

        self.user = User.objects.create_user(
            username="provider_ref_customer",
            email="provider-ref-customer@example.com",
            password="StrongTestPassword123!",
        )

        self.tx = Transaction.objects.create(
            user=self.user,
            service_type="airtime",
            amount=Decimal("1500.00"),
            reference="PROVIDER-REF-SECURITY-001",
            status="pending",
            provider="vtpass",
            provider_reference="VT-ORIGINAL-REFERENCE",
            metadata={},
        )

        self.url = reverse(
            "admin-transaction-update-provider-ref",
            kwargs={
                "reference": self.tx.reference,
            },
        )

    def test_provider_reference_update_requires_authentication(
        self,
    ):
        response = self.client.post(
            self.url,
            {
                "provider_reference":
                    "VT-TAMPERED-REFERENCE",
                "note": "Attempted modification",
            },
            format="json",
        )

        self.assertIn(
            response.status_code,
            [
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_403_FORBIDDEN,
            ],
        )

        self.tx.refresh_from_db()

        self.assertEqual(
            self.tx.provider_reference,
            "VT-ORIGINAL-REFERENCE",
        )

    def test_non_admin_cannot_update_provider_reference(
        self,
    ):
        self.client.force_authenticate(
            user=self.user
        )

        response = self.client.post(
            self.url,
            {
                "provider_reference":
                    "VT-TAMPERED-REFERENCE",
                "note": "Unauthorized modification",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        self.tx.refresh_from_db()

        self.assertEqual(
            self.tx.provider_reference,
            "VT-ORIGINAL-REFERENCE",
        )

    def test_admin_cannot_update_provider_reference(
        self,
    ):
        self.client.force_authenticate(
            user=self.admin
        )

        response = self.client.post(
            self.url,
            {
                "provider_reference":
                    "VT-TAMPERED-REFERENCE",
                "note": "Attempted admin modification",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_409_CONFLICT,
        )

        self.tx.refresh_from_db()

        self.assertEqual(
            self.tx.provider_reference,
            "VT-ORIGINAL-REFERENCE",
        )

    def test_admin_cannot_add_missing_provider_reference(
        self,
    ):
        self.tx.provider_reference = None
        self.tx.save(
            update_fields=[
                "provider_reference",
            ]
        )

        self.client.force_authenticate(
            user=self.admin
        )

        response = self.client.post(
            self.url,
            {
                "provider_reference":
                    "VT-MANUALLY-ADDED",
                "note": "Attempted manual addition",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_409_CONFLICT,
        )

        self.tx.refresh_from_db()

        self.assertIsNone(
            self.tx.provider_reference
        )

class AdminTransactionResolveSecurityTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="resolve_admin",
            email="resolve-admin@example.com",
            password="StrongTestPassword123!",
            is_staff=True,
        )

        self.user = User.objects.create_user(
            username="resolve_customer",
            email="resolve-customer@example.com",
            password="StrongTestPassword123!",
        )

        self.tx = Transaction.objects.create(
            user=self.user,
            service_type="airtime",
            amount=Decimal("1500.00"),
            reference="ADMIN-RESOLVE-TEST-001",
            status="pending",
            provider="vtpass",
            metadata={
                "requires_manual_review": True,
                "reconciliation_result":
                    "manual_review",
            },
        )

        self.url = reverse(
            "admin-transaction-resolve",
            kwargs={
                "reference": self.tx.reference,
            },
        )

    def test_resolve_requires_authentication(self):
        response = self.client.post(
            self.url,
            {
                "note": "Manual review completed.",
            },
            format="json",
        )

        self.assertIn(
            response.status_code,
            [
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_403_FORBIDDEN,
            ],
        )

        self.tx.refresh_from_db()

        self.assertFalse(
            self.tx.metadata.get(
                "admin_resolved",
                False,
            )
        )

    def test_non_admin_cannot_resolve_transaction(self):
        self.client.force_authenticate(
            user=self.user
        )

        response = self.client.post(
            self.url,
            {
                "note": "Unauthorized resolution.",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        self.tx.refresh_from_db()

        self.assertFalse(
            self.tx.metadata.get(
                "admin_resolved",
                False,
            )
        )

    def test_resolution_note_is_required(self):
        self.client.force_authenticate(
            user=self.admin
        )

        response = self.client.post(
            self.url,
            {
                "note": "",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.tx.refresh_from_db()

        self.assertFalse(
            self.tx.metadata.get(
                "admin_resolved",
                False,
            )
        )

    def test_transaction_must_require_manual_review(self):
        self.tx.metadata = {
            "requires_manual_review": False,
        }
        self.tx.save(
            update_fields=["metadata"]
        )

        self.client.force_authenticate(
            user=self.admin
        )

        response = self.client.post(
            self.url,
            {
                "note": "Attempted resolution.",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_409_CONFLICT,
        )

        self.tx.refresh_from_db()

        self.assertFalse(
            self.tx.metadata.get(
                "admin_resolved",
                False,
            )
        )

    def test_successful_transaction_cannot_be_resolved(self):
        self.tx.status = "success"
        self.tx.save(
            update_fields=["status"]
        )

        self.client.force_authenticate(
            user=self.admin
        )

        response = self.client.post(
            self.url,
            {
                "note": "Attempted resolution.",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_409_CONFLICT,
        )

        self.tx.refresh_from_db()

        self.assertEqual(
            self.tx.status,
            "success",
        )

        self.assertFalse(
            self.tx.metadata.get(
                "admin_resolved",
                False,
            )
        )

    def test_refunded_transaction_cannot_be_resolved(self):
        self.tx.status = "refunded"
        self.tx.save(
            update_fields=["status"]
        )

        self.client.force_authenticate(
            user=self.admin
        )

        response = self.client.post(
            self.url,
            {
                "note": "Attempted resolution.",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_409_CONFLICT,
        )

        self.tx.refresh_from_db()

        self.assertEqual(
            self.tx.status,
            "refunded",
        )

        self.assertFalse(
            self.tx.metadata.get(
                "admin_resolved",
                False,
            )
        )

    def test_admin_can_resolve_manual_review_transaction(self):
        original_status = self.tx.status

        self.client.force_authenticate(
            user=self.admin
        )

        response = self.client.post(
            self.url,
            {
                "note": (
                    "Reviewed provider records; "
                    "no further action required."
                ),
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.tx.refresh_from_db()

        self.assertEqual(
            self.tx.status,
            original_status,
        )

        self.assertTrue(
            self.tx.metadata.get(
                "admin_resolved"
            )
        )

        self.assertTrue(
            self.tx.metadata.get(
                "requires_manual_review"
            )
        )

        self.assertEqual(
            self.tx.metadata.get(
                "admin_resolved_by"
            ),
            self.admin.email,
        )

        self.assertEqual(
            self.tx.metadata.get(
                "admin_resolution_note"
            ),
            (
                "Reviewed provider records; "
                "no further action required."
            ),
        )

        self.assertIsNotNone(
            self.tx.metadata.get(
                "admin_resolved_at"
            )
        )

    def test_resolve_does_not_change_financial_status(self):
        self.tx.status = "processing"
        self.tx.save(
            update_fields=["status"]
        )

        self.client.force_authenticate(
            user=self.admin
        )

        response = self.client.post(
            self.url,
            {
                "note": (
                    "Manual investigation "
                    "completed."
                ),
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.tx.refresh_from_db()

        self.assertEqual(
            self.tx.status,
            "processing",
        )

        self.assertTrue(
            self.tx.metadata.get(
                "admin_resolved"
            )
        )

    def test_transaction_cannot_be_resolved_twice(self):
        self.client.force_authenticate(
            user=self.admin
        )

        first_response = self.client.post(
            self.url,
            {
                "note": "First resolution.",
            },
            format="json",
        )

        self.assertEqual(
            first_response.status_code,
            status.HTTP_200_OK,
        )

        self.tx.refresh_from_db()

        first_resolved_at = (
            self.tx.metadata.get(
                "admin_resolved_at"
            )
        )

        second_response = self.client.post(
            self.url,
            {
                "note": "Second resolution.",
            },
            format="json",
        )

        self.assertEqual(
            second_response.status_code,
            status.HTTP_409_CONFLICT,
        )

        self.tx.refresh_from_db()

        self.assertEqual(
            self.tx.metadata.get(
                "admin_resolution_note"
            ),
            "First resolution.",
        )

        self.assertEqual(
            self.tx.metadata.get(
                "admin_resolved_at"
            ),
            first_resolved_at,
        )

class AdminGuestRefundConcurrencyTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="guest_refund_admin",
            email="guest-refund-admin@example.com",
            password="StrongTestPassword123!",
            is_staff=True,
        )

        self.guest_tx = GuestTransaction.objects.create(
            reference="GUEST-ADMIN-RACE-001",
            payment_reference="PAYSTACK-RACE-001",
            guest_email="guest-race@example.com",
            service_type="airtime",
            amount=Decimal("2000.00"),
            status="failed",
        )

        self.client.force_authenticate(user=self.admin)

        self.url = reverse(
            "admin-guest-transaction-refund",
            kwargs={"reference": self.guest_tx.reference},
        )

    @patch("analytics.admin_transactions.PaystackService.create_refund")
    def test_completed_refund_cannot_be_reverted_by_admin_response(
        self,
        mock_create_refund,
    ):
        def complete_refund_during_request(**kwargs):
            GuestTransaction.objects.filter(
                pk=self.guest_tx.pk,
            ).update(
                status="refunded",
                refund_status="processed",
                refund_reference="REFUND-RACE-001",
                refunded_at=timezone.now(),
            )

            return {
                "status": True,
                "data": {
                    "id": "REFUND-RACE-001",
                    "status": "pending",
                },
            }

        mock_create_refund.side_effect = complete_refund_during_request

        response = self.client.post(
            self.url,
            {"note": "Concurrency regression test"},
            format="json",
        )

        self.guest_tx.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.guest_tx.status, "refunded")
        self.assertEqual(self.guest_tx.refund_status, "processed")
        self.assertEqual(
            self.guest_tx.refund_reference,
            "REFUND-RACE-001",
        )
        self.assertIsNotNone(self.guest_tx.refunded_at)
        mock_create_refund.assert_called_once()

    @patch("analytics.admin_transactions.PaystackService.create_refund")
    def test_completed_refund_survives_unknown_admin_response(
        self,
        mock_create_refund,
    ):
        def timeout_after_refund_completed(**kwargs):
            GuestTransaction.objects.filter(
                pk=self.guest_tx.pk,
            ).update(
                status="refunded",
                refund_status="processed",
                refund_reference="REFUND-RACE-002",
                refunded_at=timezone.now(),
            )

            return {
                "status": False,
                "outcome": "unknown",
                "message": "Refund confirmation unavailable.",
            }

        mock_create_refund.side_effect = timeout_after_refund_completed

        self.client.post(
            self.url,
            {"note": "Unknown outcome concurrency test"},
            format="json",
        )

        self.guest_tx.refresh_from_db()

        self.assertEqual(self.guest_tx.status, "refunded")
        self.assertEqual(self.guest_tx.refund_status, "processed")
        self.assertEqual(
            self.guest_tx.refund_reference,
            "REFUND-RACE-002",
        )
        self.assertIsNotNone(self.guest_tx.refunded_at)
        mock_create_refund.assert_called_once()

    @patch("analytics.admin_transactions.PaystackService.create_refund")
    def test_successful_refund_does_not_store_sensitive_provider_data(
        self,
        mock_create_refund,
    ):
        mock_create_refund.return_value = {
            "status": True,
            "data": {
                "id": "REFUND-PRIVACY-001",
                "status": "pending",
                "customer_email": "private@example.com",
                "customer_phone": "08012345678",
                "secret_provider_data": "SENSITIVE-SECRET-123",
            },
        }

        response = self.client.post(
            self.url,
            {"note": "Refund privacy regression test"},
            format="json",
        )

        self.guest_tx.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.guest_tx.status, "refund_pending")
        self.assertEqual(
            self.guest_tx.refund_reference,
            "REFUND-PRIVACY-001",
        )
        self.assertEqual(
            self.guest_tx.refund_response,
            {
                "result": "initiated",
                "refund_reference": "REFUND-PRIVACY-001",
                "refund_status": "pending",
            },
        )

        mock_create_refund.assert_called_once()

    @patch("analytics.admin_transactions.PaystackService.create_refund")
    def test_failed_refund_cannot_be_reopened_by_admin_response(
        self,
        mock_create_refund,
    ):
        def fail_refund_during_request(**kwargs):
            GuestTransaction.objects.filter(
                pk=self.guest_tx.pk,
            ).update(
                status="refund_failed",
                refund_status="failed",
                refund_reference="REFUND-RACE-FAILED-001",
            )

            return {
                "status": True,
                "data": {
                    "id": "REFUND-RACE-FAILED-001",
                    "status": "pending",
                },
            }

        mock_create_refund.side_effect = fail_refund_during_request

        response = self.client.post(
            self.url,
            {"note": "Failed refund concurrency regression test"},
            format="json",
        )

        self.guest_tx.refresh_from_db()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.guest_tx.status, "refund_failed")
        self.assertEqual(self.guest_tx.refund_status, "failed")
        self.assertEqual(
            self.guest_tx.refund_reference,
            "REFUND-RACE-FAILED-001",
        )
        mock_create_refund.assert_called_once()